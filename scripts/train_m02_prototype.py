"""Phase 3 (m02_prototype): quantile XGBoost trainer, target-variant sweep + WF eval.

Sweeps target definitions to separate real excursion edge from volatility autocorrelation
(the vol-autocorrelation diagnostic showed raw MFE/MAE IC ~= raw natr IC). All variants
are derived at load time by joining natr from t3_training_cache — no target-table rebuild.

Variants (vol = natr at entry):
    raw_ret      P50 fwd_ret_pct            (control: the +0.038 directional signal)
    radj_ret     P50 fwd_ret_pct / natr     (risk-adjusted / Sharpe-like return)
    vadj_mfe     P90 fwd_mfe_pct / natr     (vol-adjusted favorable excursion -> TP)
    vadj_mae     P10 fwd_mae_pct / natr     (vol-adjusted drawdown -> SL)

For every variant the report includes the RAW-natr IC against that same target, so we can
see whether the model beats "just rank by volatility" (the edge-vs-tautology test).

Infra (per smoke-test-before-big-runs protocol):
    --smoke         limit to a few tickers, validate path in seconds
    flush=True      live per-fold logging
    checkpoints     per (variant, quantile, fold) JSON under the run dir; resume skips done
XGBoost: reg:quantileerror, enable_categorical on the DMatrix (sector/industry).
"""

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import xgboost as xgb

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DUCKDB_PATH
from src.evaluation.m02_cv import cross_sectional_rank_ic
from src.evaluation.walk_forward import anchored_walk_forward

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HORIZON = 21
FEATURE_SET_ID = "fs_m01_prototype"
VOL_COL = "natr"
SMOKE_TICKERS = ("AAPL", "NVDA", "MSFT", "TSLA", "AMD")
OUT_BASE = Path("models/m02_prototype")

# variant -> (quantile alpha, raw target col, vol_normalize?)
# raw_mfe/raw_mae are the SLIM baselines: same raw MFE/MAE targets as the first run, but
# trained on the 5y window so they are apples-to-apples vs the vol-adjusted variants.
VARIANTS = {
    "raw_mfe":  (0.90, "fwd_mfe_pct", False),
    "raw_mae":  (0.10, "fwd_mae_pct", False),
    "raw_ret":  (0.50, "fwd_ret_pct", False),
    "vadj_mfe": (0.90, "fwd_mfe_pct", True),
    "vadj_mae": (0.10, "fwd_mae_pct", True),
    "radj_ret": (0.50, "fwd_ret_pct", True),
}

_XGB_PARAMS = {
    "objective": "reg:quantileerror",
    "tree_method": "hist",
    "max_depth": 6, "eta": 0.05,
    "subsample": 0.8, "colsample_bytree": 0.8, "min_child_weight": 20,
}
NUM_BOOST_ROUND = 300


def get_feature_cols(con: duckdb.DuckDBPyConnection) -> list[str]:
    rows = con.execute(
        "SELECT feature_name FROM model_feature_sets WHERE feature_set_id = ? ORDER BY ordinal",
        [FEATURE_SET_ID],
    ).fetchall()
    if not rows:
        raise RuntimeError(f"feature set {FEATURE_SET_ID!r} empty/missing")
    return [r[0].lower() for r in rows]


def load_matrix(db_path: str, feature_cols: list[str], smoke: bool):
    con = duckdb.connect(db_path, read_only=True)
    try:
        avail = {c.lower() for c in con.execute("SELECT * FROM t3_training_cache LIMIT 1").df().columns}
        use = [c for c in feature_cols if c in avail]
        if VOL_COL not in use and VOL_COL in avail:
            use_extra = [VOL_COL]  # need natr for normalization even if not a model feature
        else:
            use_extra = []
        sel = ", ".join(f"f.{c}" for c in dict.fromkeys(use + use_extra))
        where_smoke = ""
        if smoke:
            tk = ",".join(f"'{t}'" for t in SMOKE_TICKERS)
            where_smoke = f"AND f.ticker IN ({tk})"
        df = con.execute(f"""
            SELECT f.ticker, f.date, {sel},
                   t.fwd_mae_pct, t.fwd_ret_pct, t.fwd_mfe_pct
            FROM t3_training_cache f
            JOIN m02_prototype_targets t ON f.ticker = t.ticker AND f.date = t.date
            WHERE t.has_full_window {where_smoke}
            ORDER BY f.date, f.ticker
        """).df()
    finally:
        con.close()
    df.columns = df.columns.str.lower()
    return df, use


def _prep_cat(X: pd.DataFrame) -> pd.DataFrame:
    X = X.copy()
    for c in X.select_dtypes(include="object").columns:
        X[c] = X[c].astype("category")
    return X.replace([np.inf, -np.inf], np.nan)


def _build_target(df: pd.DataFrame, raw_col: str, vol_normalize: bool) -> pd.Series:
    if not vol_normalize:
        return df[raw_col]
    # vol-normalized: divide by natr; guard tiny/zero vol
    vol = df[VOL_COL].replace(0, np.nan)
    return df[raw_col] / vol


def _slice(df, start, end):
    d = pd.to_datetime(df["date"]).dt.date
    return df.loc[(d >= start) & (d <= end)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DUCKDB_PATH))
    ap.add_argument("--train-start", default="2016-01-04")
    ap.add_argument("--test-start", default="2021-01-04")
    ap.add_argument("--test-end", default="2026-01-01")
    ap.add_argument("--step", default="1Y")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--variants", default=",".join(VARIANTS), help="comma list subset")
    args = ap.parse_args()

    run_tag = ("smoke_" if args.smoke else "") + datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUT_BASE / run_tag
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"run dir: {run_dir}", flush=True)

    con = duckdb.connect(args.db, read_only=True)
    feature_cols = get_feature_cols(con)
    con.close()
    df, used = load_matrix(args.db, feature_cols, args.smoke)
    print(f"matrix: {len(df):,} rows x {len(used)} features", flush=True)

    fold_specs = list(anchored_walk_forward(
        df, "date", date.fromisoformat(args.train_start),
        date.fromisoformat(args.test_start), date.fromisoformat(args.test_end),
        step=args.step, embargo_days=HORIZON,
    ))
    print(f"{len(fold_specs)} folds, embargo={HORIZON}d", flush=True)

    summary = {}
    for vname in args.variants.split(","):
        alpha, raw_col, vol_norm = VARIANTS[vname]
        vdir = run_dir / vname
        vdir.mkdir(exist_ok=True)
        print(f"\n=== variant {vname}: P{int(alpha*100)} on {raw_col}{' /natr' if vol_norm else ''} ===", flush=True)
        fold_rows = []
        for spec in fold_specs:
            ckpt = vdir / f"fold_{spec.fold_idx:02d}.json"
            if ckpt.exists():
                fold_rows.append(json.loads(ckpt.read_text()))
                print(f"  fold {spec.fold_idx}: resumed from checkpoint", flush=True)
                continue
            tr = _slice(df, spec.train_start, spec.train_end).copy()
            te = _slice(df, spec.test_start, spec.test_end).copy()
            if tr.empty or te.empty:
                continue
            tr["_y"] = _build_target(tr, raw_col, vol_norm)
            te["_y"] = _build_target(te, raw_col, vol_norm)
            tr = tr.dropna(subset=["_y"]); te = te.dropna(subset=["_y"])

            t0 = datetime.now()
            dtr = xgb.DMatrix(_prep_cat(tr[used]), label=tr["_y"], enable_categorical=True)
            booster = xgb.train({**_XGB_PARAMS, "quantile_alpha": alpha}, dtr, num_boost_round=NUM_BOOST_ROUND)
            pred = booster.predict(xgb.DMatrix(_prep_cat(te[used]), enable_categorical=True))
            secs = (datetime.now() - t0).total_seconds()

            sc = te[["date"]].copy(); sc["_pred"] = pred; sc["_y"] = te["_y"].values
            ic, ic_std = cross_sectional_rank_ic(sc, "date", "_pred", "_y")
            # raw-natr IC vs the SAME target (edge-vs-tautology baseline)
            scv = te[["date"]].copy(); scv[VOL_COL] = te[VOL_COL].values; scv["_y"] = te["_y"].values
            natr_ic, _ = cross_sectional_rank_ic(scv.dropna(), "date", VOL_COL, "_y")

            booster.save_model(str(vdir / f"fold_{spec.fold_idx:02d}_model.json"))
            row = {
                "fold": spec.fold_idx,
                "test_start": spec.test_start.isoformat(), "test_end": spec.test_end.isoformat(),
                "rank_ic": ic, "rank_ic_std": ic_std, "natr_ic": natr_ic,
                "n_train": int(len(tr)), "n_test": int(len(te)), "train_secs": secs,
            }
            ckpt.write_text(json.dumps(row, indent=2))
            fold_rows.append(row)
            print(f"  fold {spec.fold_idx} [{row['test_start']}..{row['test_end']}] "
                  f"IC={ic:+.4f} natr_IC={natr_ic:+.4f} edge={ic-abs(natr_ic):+.4f} "
                  f"n_test={row['n_test']} [{secs:.0f}s]", flush=True)

        ics = [r["rank_ic"] for r in fold_rows if not np.isnan(r["rank_ic"])]
        natr_ics = [abs(r["natr_ic"]) for r in fold_rows if not np.isnan(r["natr_ic"])]
        summary[vname] = {
            "alpha": alpha, "target": raw_col, "vol_norm": vol_norm,
            "ic_mean": float(np.mean(ics)) if ics else None,
            "ic_worst": float(np.min(ics)) if ics else None,
            "natr_ic_mean_abs": float(np.mean(natr_ics)) if natr_ics else None,
            "edge_mean": float(np.mean(ics) - np.mean(natr_ics)) if ics and natr_ics else None,
            "folds": fold_rows,
        }

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nsummary -> {run_dir / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
