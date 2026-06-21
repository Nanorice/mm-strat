"""Eval data loader for the model card.

Loads rows from `v_d2_training` (entry-ledger), applies the SEPA + trend_ok
filter, runs the model, attaches both labels (binary > 30 and 4-class bins),
and returns a single `EvalSplit` consumed by every section.

The model is loaded as an `xgb.Booster` and predicted with
`enable_categorical=True` (sector/industry are VARCHAR categoricals — see
memory `Models & Feature Catalog`). For 4-class models, the home-run class
probability is taken as `pred_proba` per §6 R6 of the framework.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import duckdb
from src import db
import numpy as np
import pandas as pd
import xgboost as xgb

from src.evaluation.categorical_encoding import encode_categoricals, load_categorical_map

logger = logging.getLogger(__name__)

# Outcome columns on v_d2_training that MUST be excluded from features.
# Per framework §A1 + memory `m01_two_model_system` (outcome columns sit on
# the same row as features on v_d2_training).
OUTCOME_COLUMNS: frozenset[str] = frozenset({
    "mae_pct", "mfe_pct", "return_pct", "return_at_exit",
    "mae_date", "mfe_date", "sepa_exit_date",
    "entry_date", "exit_date", "entry_price", "exit_price",
    "holding_days", "days_observed",
    "sl_triggered", "sl_date", "sl_exit_date", "sl_pct",
    "trade_id", "is_new_trigger",
})

# Non-feature bookkeeping columns (also excluded from features).
META_COLUMNS: frozenset[str] = frozenset({
    "ticker", "date", "feature_version", "ingested_at",
    "fundamental_filing_date", "fiscal_period", "days_since_report",
})

# Binary label threshold (matches label_registry/mfe_binary_homerun_v1.json).
BINARY_HOME_RUN_THRESHOLD = 30.0

# 4-class bins for mfe_pct (matches label_registry/mfe_4class_v1.json).
FOURCLASS_BINS = [2.0, 10.0, 30.0]
FOURCLASS_NAMES = ["Noise", "Moderate", "Strong", "HomeRun"]
HOME_RUN_CLASS_IDX = 3  # last bin


@dataclass(frozen=True)
class EvalSplit:
    """Frozen eval-time bundle consumed by every section."""
    df: pd.DataFrame                # rows from v_d2_training (entry ledger)
    feature_cols: list[str]         # feature names the model was trained on
    label_binary: pd.Series         # 1 if mfe_pct > 30 else 0
    label_mfe: pd.Series            # raw mfe_pct
    label_4class: pd.Series         # 0..3 bin index
    pred_proba: pd.Series           # P(home-run)
    meta: dict                      # model_id, n, prevalence, date range, etc.
    db_path: Path                   # for sections that need follow-up queries
    model_path: Path

    @property
    def prevalence(self) -> float:
        return float(self.label_binary.mean())

    @property
    def n(self) -> int:
        return len(self.df)


def _load_feature_list(model_path: Path) -> list[str]:
    """Pull feature list from metadata.json co-located with model.json.

    Per framework: feature list MUST come from the model's metadata, NOT from
    the dataframe column list. The dataframe contains outcome columns we
    must NOT pass to predict.
    """
    metadata_path = model_path.parent / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(
            f"metadata.json missing next to model: expected {metadata_path}"
        )
    metadata = json.loads(metadata_path.read_text())
    features = metadata.get("valid_features")
    if not features:
        raise ValueError(f"metadata.json at {metadata_path} has no 'valid_features'")
    return list(features)


def _detect_model_kind(booster: xgb.Booster) -> tuple[str, int]:
    """Return ('binary' or 'multi', num_class)."""
    config = json.loads(booster.save_config())
    objective = config.get("learner", {}).get("objective", {}).get("name", "")
    num_class = int(
        config.get("learner", {}).get("learner_model_param", {}).get("num_class", "0") or 0
    )
    if "binary" in objective:
        return "binary", 2
    if "softprob" in objective or "softmax" in objective:
        return "multi", num_class
    raise ValueError(f"Unsupported objective for model card: {objective}")


def _predict_home_run_proba(
    booster: xgb.Booster,
    X: pd.DataFrame,
    kind: str,
) -> np.ndarray:
    dmat = xgb.DMatrix(X, enable_categorical=True)
    raw = booster.predict(dmat)
    if kind == "binary":
        # xgboost returns 1-D P(class=1)
        return np.asarray(raw, dtype=float).ravel()
    # multi -> project to home-run class
    arr = np.asarray(raw, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"Expected 2-D multi-class proba, got shape {arr.shape}")
    if arr.shape[1] <= HOME_RUN_CLASS_IDX:
        raise ValueError(
            f"Model returned {arr.shape[1]} classes; need at least "
            f"{HOME_RUN_CLASS_IDX + 1} for home-run projection"
        )
    return arr[:, HOME_RUN_CLASS_IDX]


def _binarise_mfe(mfe: pd.Series) -> pd.Series:
    return (mfe > BINARY_HOME_RUN_THRESHOLD).astype(int)


def _bucket_4class(mfe: pd.Series) -> pd.Series:
    # bins=[2,10,30] -> 4 classes: (-inf,2], (2,10], (10,30], (30,+inf)
    edges = [-np.inf] + FOURCLASS_BINS + [np.inf]
    return pd.cut(mfe, bins=edges, labels=False, include_lowest=True).astype(int)


def _resolve_source_table(con: duckdb.DuckDBPyConnection) -> str:
    """Prefer the materialized cache (d2_training_cache) over the view.

    v_d2_training is a complex CTE that takes ~5 min on full history.
    d2_training_cache is the same content materialized for fast loads
    (memory: View Materialization 3.5.4). When the cache exists and has
    outcomes, use it; fall back to the view otherwise.
    """
    cache_exists = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'd2_training_cache'"
    ).fetchone()[0]
    if not cache_exists:
        return "v_d2_training"
    has_mfe = con.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = 'd2_training_cache' AND column_name = 'mfe_pct'"
    ).fetchone()[0]
    return "d2_training_cache" if has_mfe else "v_d2_training"


def load_eval_data(
    model_id: str,
    model_path: Path,
    db_path: Path,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    apply_trend_ok_filter: bool = True,
    feature_version: str = "v3.1",
    apply_calibration: bool = False,
) -> EvalSplit:
    """Load eval rows + predict + attach labels."""
    model_path = Path(model_path)
    db_path = Path(db_path)
    if not model_path.exists():
        raise FileNotFoundError(f"model file not found: {model_path}")
    if not db_path.exists():
        raise FileNotFoundError(f"db file not found: {db_path}")

    feature_cols = _load_feature_list(model_path)
    booster = xgb.Booster()
    booster.load_model(str(model_path))
    kind, num_class = _detect_model_kind(booster)
    logger.info(
        "Loaded %s (kind=%s, num_class=%d, features=%d)",
        model_id, kind, num_class, len(feature_cols),
    )

    where_clauses = [
        f"feature_version = '{feature_version}'",
        "mfe_pct IS NOT NULL",
    ]
    if apply_trend_ok_filter:
        where_clauses.append("trend_ok = TRUE")
    if start_date:
        where_clauses.append(f"date >= DATE '{start_date}'")
    if end_date:
        where_clauses.append(f"date <= DATE '{end_date}'")
    where_sql = " AND ".join(where_clauses)

    con = db.connect(str(db_path), read_only=True)
    try:
        source = _resolve_source_table(con)
        logger.info("Reading eval data from %s", source)
        sql = f"SELECT * FROM {source} WHERE {where_sql} ORDER BY date, ticker"
        df = con.execute(sql).fetchdf()
    finally:
        con.close()

    if df.empty:
        raise ValueError(
            f"No eval rows for model={model_id} window=({start_date},{end_date}) "
            f"trend_ok={apply_trend_ok_filter}"
        )

    missing_features = [c for c in feature_cols if c not in df.columns]
    if missing_features:
        raise ValueError(
            f"v_d2_training missing {len(missing_features)} model features: "
            f"{missing_features[:5]}..."
        )

    categorical_map = load_categorical_map(model_path)
    df_for_predict = encode_categoricals(df, feature_cols, categorical_map)
    pred = _predict_home_run_proba(booster, df_for_predict[feature_cols], kind)

    label_binary = _binarise_mfe(df["mfe_pct"])
    label_4class = _bucket_4class(df["mfe_pct"])

    if apply_calibration:
        from src.evaluation.calibrator import IsotonicCalibrator
        cal_path = model_path.parent / "calibrator.joblib"
        if cal_path.exists():
            logger.info("Applying saved calibrator from %s", cal_path)
            cal = IsotonicCalibrator.load(cal_path)
            pred = cal.transform(pred)
        else:
            logger.warning("No saved calibrator found. Fitting an ad-hoc calibrator for evaluation.")
            # Fit an ad-hoc calibrator using the eval slice itself (used for the 4-class workaround)
            cal = IsotonicCalibrator()
            cal.fit(label_binary.values, pred)
            pred = cal.transform(pred)

    meta = {
        "model_id": model_id,
        "model_kind": kind,
        "num_class": num_class,
        "n_rows": int(len(df)),
        "n_positives": int(label_binary.sum()),
        "prevalence": float(label_binary.mean()),
        "date_min": str(df["date"].min()),
        "date_max": str(df["date"].max()),
        "feature_version": feature_version,
        "trend_ok_filtered": apply_trend_ok_filter,
        "n_features": len(feature_cols),
        "outcome_columns_excluded": sorted(OUTCOME_COLUMNS),
    }

    return EvalSplit(
        df=df,
        feature_cols=list(feature_cols),
        label_binary=pd.Series(label_binary.values, index=df.index, name="label_binary"),
        label_mfe=pd.Series(df["mfe_pct"].values, index=df.index, name="mfe_pct"),
        label_4class=pd.Series(label_4class.values, index=df.index, name="label_4class"),
        pred_proba=pd.Series(pred, index=df.index, name="pred_proba"),
        meta=meta,
        db_path=db_path,
        model_path=model_path,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — stateful pool builders for Section D / E
# ─────────────────────────────────────────────────────────────────────────────

# Columns that Mode B scoring may need but which are NOT model features.
_MODE_B_KEEP_COLS = ["ticker", "date", "trend_ok", "m03_score"]


def build_mode_a_pool(split: EvalSplit) -> pd.DataFrame:
    """Entry-only pool (the headline). One row per realised trade entry.

    Already in `split.df` — we just normalise the columns Section D/E need
    (date dtype + pred_proba + labels) so the pool is self-contained and
    pickleable.
    """
    df = split.df
    if "trend_ok" in df.columns:
        mask = df["trend_ok"].astype(bool)
        df = df[mask]
    if df.empty:
        raise ValueError("Mode A pool empty after trend_ok filter")
    out = pd.DataFrame({
        "ticker": df["ticker"].values,
        "date": pd.to_datetime(df["date"]).values,
        "pred_proba": split.pred_proba.loc[df.index].values,
        "label_binary": split.label_binary.loc[df.index].values,
        "label_mfe": split.label_mfe.loc[df.index].values,
        "label_4class": split.label_4class.loc[df.index].values,
    })
    # Mode A is generated directly from the EvalSplit probabilities, which are already calibrated if apply_calibration was true.
    if "m03_score" in df.columns:
        out["m03_score"] = df["m03_score"].values
    if "sector" in df.columns:
        out["sector"] = df["sector"].values
    return out.reset_index(drop=True)


def _hash_window(model_id: str, start: str, end: str, feature_version: str) -> str:
    import hashlib
    h = hashlib.sha1(
        f"{model_id}|{start}|{end}|{feature_version}".encode("utf-8")
    ).hexdigest()
    return h[:12]


# Categoricals + derived ratios that v_d2_features adds on top of t3 + ff.
# These need bespoke SELECT expressions in Mode B because they're computed
# from the join, not stored on any single table.
_DERIVED_COLS = frozenset({
    "pe_ratio", "ps_ratio", "pb_ratio", "peg_adjusted",
    "market_cap", "shares_outstanding",
    "sector", "industry",
})

_DERIVED_SQL = {
    "pe_ratio": (
        "CASE WHEN ABS(ff.eps_diluted) > 0.01 "
        "THEN (t3.\"close\" / ff.eps_diluted) ELSE NULL END AS pe_ratio"
    ),
    "ps_ratio": (
        "CASE WHEN ff.revenue > 0 AND sh.shares_outstanding > 0 "
        "THEN (t3.\"close\" * sh.shares_outstanding / ff.revenue) ELSE NULL END AS ps_ratio"
    ),
    "pb_ratio": (
        "CASE WHEN ff.total_equity > 0 AND sh.shares_outstanding > 0 "
        "THEN (t3.\"close\" * sh.shares_outstanding / ff.total_equity) ELSE NULL END AS pb_ratio"
    ),
    "peg_adjusted": (
        "CASE WHEN ff.eps_growth_yoy > 0 AND ABS(ff.eps_diluted) > 0.01 "
        "THEN ((t3.\"close\" / ff.eps_diluted) / ff.eps_growth_yoy) "
        "ELSE NULL END AS peg_adjusted"
    ),
    "market_cap": "cp.market_cap AS market_cap",
    "shares_outstanding": "sh.shares_outstanding AS shares_outstanding",
    "sector": "cp.sector AS sector",
    "industry": "cp.industry AS industry",
}


def _build_mode_b_select(
    t3_cols: set[str], ff_cols: set[str], needed_cols: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """Build SELECT expressions for Mode B from `t3_sepa_features`.

    Four sources stitched together:
      1. Direct t3 columns (most price/volume/momentum features)
      2. *_delta renames from *_pct_chg / 100 (per memory `View 3.1`)
      3. Fundamental columns from `fundamental_features` (as-of join)
      4. Derived ratios + categoricals from company_profiles + shares_history

    Returns (select_exprs, fundamental_cols, unresolved).
    """
    select_exprs: list[str] = []
    fundamental_cols: list[str] = []
    unresolved: list[str] = []
    for col in needed_cols:
        if col in t3_cols:
            select_exprs.append(f"t3.{col}")
            continue
        if col.endswith("_delta"):
            src = col[: -len("_delta")] + "_pct_chg"
            if src in t3_cols:
                select_exprs.append(f"(t3.{src} / 100.0) AS {col}")
                continue
        if col == "days_since_report":
            select_exprs.append(
                "CAST(datediff('day', ff.filing_date, t3.date) AS INTEGER) "
                "AS days_since_report"
            )
            continue
        if col in _DERIVED_COLS:
            select_exprs.append(_DERIVED_SQL[col])
            continue
        if col in ff_cols:
            select_exprs.append(f"ff.{col}")
            fundamental_cols.append(col)
            continue
        unresolved.append(col)
    return select_exprs, fundamental_cols, unresolved


def build_mode_b_pool(
    db_path: Path,
    model_id: str,
    model_path: Path,
    feature_cols: list[str],
    start_date: str,
    end_date: str,
    feature_version: str = "v3.1",
    cache_dir: Optional[Path] = None,
    chunk_months: int = 3,
    force_recompute: bool = False,
    apply_calibration: bool = False,
) -> pd.DataFrame:
    """Stateful daily pool.

    For every (ticker, date) in `t3_sepa_features` where trend_ok=TRUE within
    the window, score the model and (where available) join the realised
    outcome from the trade entered on that date.

    `t3_sepa_features` is the canonical SEPA daily pool (per memory `T3
    Backfill 4.1.2`). Price/momentum features come directly from t3;
    fundamental features are joined as-of the latest filing date ≤ row
    date (mirroring `v_d2_features`); `*_delta` features are rescaled from
    `*_pct_chg`.

    Cached to parquet keyed by (model_id, start, end, feature_version). Pass
    `force_recompute=True` to override.
    """
    db_path = Path(db_path)
    model_path = Path(model_path)
    cache_path: Optional[Path] = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        slug = model_id.replace("/", "_").replace(" ", "_")
        cache_path = cache_dir / (
            f"mode_b_{slug}_{_hash_window(model_id, start_date, end_date, feature_version)}.parquet"
        )
        if cache_path.exists() and not force_recompute:
            logger.info("Loading cached Mode B pool from %s", cache_path)
            return pd.read_parquet(cache_path)

    booster = xgb.Booster()
    booster.load_model(str(model_path))
    kind, _ = _detect_model_kind(booster)
    categorical_map = load_categorical_map(model_path)

    needed_cols = list(dict.fromkeys(_MODE_B_KEEP_COLS + feature_cols))
    con = db.connect(str(db_path), read_only=True)
    try:
        t3_cols = {
            r[0] for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 't3_sepa_features'"
            ).fetchall()
        }
        ff_cols = {
            r[0] for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'fundamental_features'"
            ).fetchall()
        }

        select_exprs, fundamental_cols, unresolved = _build_mode_b_select(
            t3_cols, ff_cols, needed_cols,
        )
        if unresolved:
            raise ValueError(
                f"Mode B cannot resolve {len(unresolved)} feature(s) "
                f"(not in t3, not _pct_chg-derived, not a known fundamental): "
                f"{unresolved[:5]}..."
            )

        col_list = ", ".join(select_exprs)

        # As-of fundamental join + dedup, mirroring v_d2_features. Note we
        # always pull eps_diluted / revenue / total_equity / eps_growth_yoy
        # because the derived ratio SQL references them even if they aren't
        # explicit features of the loaded model.
        ff_join_cols = sorted(set(fundamental_cols) | {
            "eps_diluted", "revenue", "total_equity", "eps_growth_yoy",
        } & ff_cols)
        ff_keep_cols_sql = ", ".join(
            ["ticker", "filing_date", "fiscal_period"] + ff_join_cols
        )
        chunks: list[pd.DataFrame] = []
        for chunk_start, chunk_end in _month_chunks(start_date, end_date, chunk_months):
            logger.info("Mode B chunk %s..%s", chunk_start, chunk_end)
            sql = f"""
                WITH ff_dedup AS (
                    SELECT {ff_keep_cols_sql}
                    FROM fundamental_features
                    QUALIFY ROW_NUMBER() OVER (
                        PARTITION BY ticker, filing_date
                        ORDER BY fiscal_period DESC NULLS LAST
                    ) = 1
                )
                SELECT {col_list}
                FROM t3_sepa_features AS t3
                LEFT JOIN company_profiles AS cp
                  ON t3.ticker = cp.ticker
                LEFT JOIN shares_history AS sh
                  ON t3.ticker = sh.ticker
                 AND sh.date = (
                    SELECT MAX(date) FROM shares_history
                    WHERE ticker = t3.ticker AND date <= t3.date
                 )
                LEFT JOIN ff_dedup AS ff
                  ON t3.ticker = ff.ticker
                 AND ff.filing_date = (
                    SELECT MAX(filing_date) FROM ff_dedup
                    WHERE ticker = t3.ticker AND filing_date <= t3.date
                 )
                WHERE t3.feature_version = '{feature_version}'
                  AND t3.trend_ok = TRUE
                  AND t3.date >= DATE '{chunk_start}'
                  AND t3.date <  DATE '{chunk_end}'
                ORDER BY t3.date, t3.ticker
            """
            chunk = con.execute(sql).fetchdf()
            if chunk.empty:
                continue
            for_predict = encode_categoricals(chunk, feature_cols, categorical_map)
            dmat = xgb.DMatrix(for_predict[feature_cols], enable_categorical=True)
            raw = booster.predict(dmat)
            if kind == "binary":
                chunk["pred_proba"] = np.asarray(raw, dtype=float).ravel()
            else:
                arr = np.asarray(raw, dtype=float)
                chunk["pred_proba"] = arr[:, HOME_RUN_CLASS_IDX]
            chunks.append(chunk[_MODE_B_KEEP_COLS + ["pred_proba"]].copy())

        if not chunks:
            raise ValueError(
                f"Mode B pool empty for window {start_date}..{end_date}"
            )
        pool = pd.concat(chunks, ignore_index=True)
        
        if apply_calibration:
            from src.evaluation.calibrator import IsotonicCalibrator
            cal_path = model_path.parent / "calibrator.joblib"
            if cal_path.exists():
                cal = IsotonicCalibrator.load(cal_path)
                pool["pred_proba"] = cal.transform(pool["pred_proba"].values)
            else:
                # Ad-hoc calibration cannot be done strictly on Mode B without labels, 
                # but we shouldn't hit this path since Mode B is stateful scoring.
                pass

        # Join realised outcomes from the d2 entry-ledger (training cache).
        d2_source = _resolve_source_table(con)
        outcomes_sql = f"""
            SELECT ticker, date, mfe_pct, return_pct, holding_days
            FROM {d2_source}
            WHERE feature_version = '{feature_version}'
              AND mfe_pct IS NOT NULL
              AND date >= DATE '{start_date}'
              AND date <  DATE '{end_date}'
        """
        outcomes = con.execute(outcomes_sql).fetchdf()
    finally:
        con.close()

    pool["date"] = pd.to_datetime(pool["date"])
    if not outcomes.empty:
        outcomes["date"] = pd.to_datetime(outcomes["date"])
    pool = pool.merge(outcomes, on=["ticker", "date"], how="left")
    pool["has_entry"] = pool["mfe_pct"].notna()
    pool["label_binary"] = (pool["mfe_pct"] > BINARY_HOME_RUN_THRESHOLD).astype("Int64")
    # Keep mfe_pct under the consistent name `label_mfe` for Section D parity.
    pool["label_mfe"] = pool["mfe_pct"]

    if cache_path is not None:
        try:
            pool.to_parquet(cache_path, index=False)
            logger.info("Cached Mode B pool to %s (%d rows)", cache_path, len(pool))
        except Exception as e:  # pragma: no cover - cache failures shouldn't kill the build
            logger.warning("Failed to write cache %s: %s", cache_path, e)

    return pool


def _month_chunks(start: str, end: str, months: int):
    """Yield half-open (start, end) chunks of `months` width inclusive of `end`."""
    s = pd.to_datetime(start)
    e = pd.to_datetime(end)
    cur = s
    while cur < e:
        nxt = (cur + pd.DateOffset(months=months))
        if nxt > e:
            nxt = e + pd.Timedelta(days=1)
        yield (cur.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d"))
        cur = nxt
