"""Shared dashboard utilities — DB loaders, constants, label helpers.

Centralizes things every page needs so the per-page files stay focused on
rendering. Read-only DB access throughout.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import duckdb
import numpy as np
import pandas as pd
import streamlit as st
import xgboost as xgb

ROOT = Path(__file__).resolve().parent.parent

# DB path is configurable so the same app runs against the full local DB or a
# slim, remote-synced dashboard.duckdb. Set DASHBOARD_DB_PATH (absolute, or
# relative to repo root) to point at the slim DB. Default: full local DB.
_db_env = os.environ.get("DASHBOARD_DB_PATH")
if _db_env:
    _db = Path(_db_env)
    DB_PATH = _db if _db.is_absolute() else ROOT / _db
else:
    DB_PATH = ROOT / "data" / "market_data.duckdb"


def _ensure_local_db() -> None:
    """Pull dashboard.duckdb from R2 when running on Streamlit Cloud.

    Only activates when R2_ACCOUNT_ID is present AND the target DB file is
    missing or stale (>23h old). This makes the cloud host self-healing: on
    every cold start it pulls the latest slim DB that the dev box uploaded
    overnight.

    Env vars required (set in Streamlit Cloud secrets):
        R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME
        DASHBOARD_DB_PATH  — local path where the pulled file is written
    """
    if not os.environ.get("R2_ACCOUNT_ID") or not os.environ.get("R2_ACCESS_KEY"):
        return  # local run — do nothing

    if not _db_env:
        return  # no explicit DB path configured, nothing to pull to

    import time

    target = DB_PATH
    # Pull if missing or older than 23h (nightly upload lands ~1h after midnight)
    if target.exists() and (time.time() - target.stat().st_mtime) < 23 * 3600:
        return

    import boto3

    account_id = os.environ["R2_ACCOUNT_ID"]
    endpoint = os.environ.get("R2_JURI_ENDPOINT_URL") or f"https://{account_id}.r2.cloudflarestorage.com"
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],
        aws_secret_access_key=os.environ["R2_SECRET_KEY"],
        region_name="auto",
    )
    bucket = os.environ["R2_BUCKET_NAME"]
    target.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(bucket, "latest/dashboard.duckdb", str(target))


_ensure_local_db()

# ── M01 class taxonomy ────────────────────────────────────────────────────────

CLASS_LABELS = ["Noise (0-2%)", "Moderate (2-10%)", "Strong (10-30%)", "Home Run (>30%)"]
CLASS_COLORS = ["#9e9e9e", "#42a5f5", "#66bb6a", "#ffa726"]
P_HR_COL = f"p_{CLASS_LABELS[3]}"  # P(Home Run >30%) — used as default sort key
P_STRONG_COL = f"p_{CLASS_LABELS[2]}"

# ── M03 regime taxonomy ───────────────────────────────────────────────────────

REGIME_THRESHOLDS = {
    "Strong Bull": (80, 100, "#2e7d32"),
    "Bull":        (60, 80, "#66bb6a"),
    "Neutral":     (40, 60, "#fdd835"),
    "Bear":        (20, 40, "#ef5350"),
    "Strong Bear": (0, 20, "#b71c1c"),
}

PILLAR_FORMULAS = {
    "Trend (40%)": "50 + 50 x tanh(pct_above_sma200 x 10)  —  SPY vs 200d SMA",
    "Liquidity (30%)": "50 + 50 x tanh(slope_pct x 50)  —  20d slope of Fed Net Liquidity",
    "Risk Appetite (30%)": "VIX component (0-50) + HY Credit Spread component (0-50)",
}

# ── 5F regime taxonomy (mirrors src/pipeline/risk_5_factor.py) ───────────────

# Mirrored constants — kept in sync with risk_5_factor.py to avoid runtime import
# cycles and to keep dashboard self-contained. If EXPOSURE_BANDS changes there,
# update here too.
EXPOSURE_BANDS = [
    (0.00, 0.20, 1.00),
    (0.20, 0.40, 0.85),
    (0.40, 0.55, 0.75),
    (0.55, 0.70, 0.50),
    (0.70, 0.85, 0.35),
    (0.85, 1.00, 0.15),
]

EXPOSURE_BAND_LABELS = {
    1.00: ("Full",     "#2e7d32"),
    0.85: ("Reduced",  "#66bb6a"),
    0.75: ("Cautious", "#fdd835"),
    0.50: ("Defensive","#fb8c00"),
    0.35: ("Heavy Defensive", "#ef5350"),
    0.15: ("Veto",     "#b71c1c"),
}

FACTOR_FRIENDLY = {
    "z_vix":   "VIX",
    "z_hy":    "HY Spread",
    "z_term":  "Term",
    "z_trend": "Trend",
    "z_slope": "Slope",
}

VETO_THRESHOLD = 2.0


def classify_regime(score: float) -> tuple[str, str]:
    for label, (lo, hi, color) in REGIME_THRESHOLDS.items():
        if lo <= score < hi or (label == "Strong Bull" and score >= hi):
            return label, color
    return "Unknown", "#757575"


def exposure_band_label(target_exposure: float) -> tuple[str, str]:
    """Map a target_exposure to a (label, color). Tolerant to rounding."""
    if pd.isna(target_exposure):
        return ("N/A", "#757575")
    # exact match preferred, nearest band as fallback
    if target_exposure in EXPOSURE_BAND_LABELS:
        return EXPOSURE_BAND_LABELS[target_exposure]
    nearest = min(EXPOSURE_BAND_LABELS.keys(), key=lambda k: abs(k - target_exposure))
    return EXPOSURE_BAND_LABELS[nearest]


# ── DB loaders (cached) ───────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_regime() -> pd.Series | None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        row = con.execute("""
            SELECT date, m03_score, m03_pillar_trend, m03_pillar_liq, m03_pillar_risk,
                   m03_delta_5d, m03_delta_20d
            FROM t2_regime_scores
            ORDER BY date DESC LIMIT 1
        """).fetchdf()
        return row.iloc[0] if not row.empty else None
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_risk_5f() -> pd.Series | None:
    """Latest 5F row from t2_risk_scores."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        row = con.execute("""
            SELECT date, target_exposure, base_exposure, weighted_z,
                   rolling_percentile, veto_flag,
                   z_vix, z_hy, z_term, z_trend, z_slope
            FROM t2_risk_scores
            WHERE target_exposure IS NOT NULL
            ORDER BY date DESC LIMIT 1
        """).fetchdf()
        return row.iloc[0] if not row.empty else None
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_watchlist() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute("""
            SELECT ticker, company_name, sector, industry, market_cap,
                   entry_date, entry_price, exit_date, status,
                   close_price, price_date, pct_return, days_held, refreshed_at
            FROM screener_watchlist
            ORDER BY entry_date DESC, ticker
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_deployment_features() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute("SELECT * FROM v_d3_deployment").fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_pipeline_status(limit: int = 20) -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(f"""
            SELECT target_date, phase_name, status, runtime_seconds,
                   started_at, completed_at, error_message
            FROM pipeline_runs
            ORDER BY started_at DESC
            LIMIT {int(limit)}
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_pipeline_runs_window(days: int = 30) -> pd.DataFrame:
    """Page 5 heatmap source — all phases x dates for the last N days.

    Includes `n_errors` (count of pipeline_error_log rows joined on run_id) so
    the heatmap can surface 'success-with-warnings' (e.g. T1 ingestion completes
    but logs per-ticker failures).
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(f"""
            SELECT pr.target_date, pr.phase_name, pr.status, pr.runtime_seconds,
                   pr.started_at, pr.completed_at, pr.error_message,
                   COALESCE(el.n_errors, 0) AS n_errors
            FROM pipeline_runs pr
            LEFT JOIN (
                SELECT run_id, COUNT(*) AS n_errors
                FROM pipeline_error_log
                GROUP BY run_id
            ) el ON pr.run_id = el.run_id
            WHERE pr.target_date >= CURRENT_DATE - INTERVAL {int(days)} DAY
            ORDER BY pr.target_date DESC, pr.phase_name
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_null_filing_writes(days: int = 30) -> pd.DataFrame:
    """Per-run count of fundamentals rows written with a NULL filing_date.

    Read from pipeline_runs.metadata.null_filing_date_written (written by the
    Phase-1 fundamentals step). These are OK writes whose yfinance earnings fetch
    failed → no PIT filing anchor until the EDGAR backfill repairs them. NOT errors
    (don't appear in pipeline_error_log), so this is the only place the per-run rate
    is observable. Empty frame if no run carries the field yet.
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(f"""
            SELECT target_date,
                   CAST(json_extract_string(metadata, '$.null_filing_date_written') AS INTEGER)
                       AS null_filing_written
            FROM pipeline_runs
            WHERE phase_name = 'phase_1_t1_ingestion'
              AND target_date >= CURRENT_DATE - INTERVAL {int(days)} DAY
              AND json_extract_string(metadata, '$.null_filing_date_written') IS NOT NULL
            ORDER BY target_date DESC
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_data_freshness() -> pd.DataFrame:
    """One row per key table: max date and rows. For Page 5 freshness panel.

    Table list mirrors `docs/manual_for_me.md` §Key Tables. Tables without a
    natural date column (company_profiles, ticker_blacklist,
    screener_criteria_versions, pipeline_runs) are omitted.
    """
    queries = [
        # Phase 1 — raw ingestion
        ("price_data",           "SELECT MAX(date)::DATE max_d, COUNT(*) n FROM price_data"),
        ("fundamentals",         "SELECT MAX(period_end)::DATE max_d, COUNT(*) n FROM fundamentals"),
        ("earnings_calendar",    "SELECT MAX(earnings_date)::DATE max_d, COUNT(*) n FROM earnings_calendar"),
        ("shares_history",       "SELECT MAX(date)::DATE max_d, COUNT(*) n FROM shares_history"),
        ("macro_data",           "SELECT MAX(date)::DATE max_d, COUNT(*) n FROM macro_data"),
        ("t1_macro",             "SELECT MAX(date)::DATE max_d, COUNT(*) n FROM t1_macro"),
        # Phase 2 — universe
        ("screener_membership",  "SELECT MAX(effective_date)::DATE max_d, COUNT(*) n FROM screener_membership"),
        # Phase 3-5 — features
        ("t2_screener_features", "SELECT MAX(date)::DATE max_d, COUNT(*) n FROM t2_screener_features"),
        ("t2_regime_scores",     "SELECT MAX(date)::DATE max_d, COUNT(*) n FROM t2_regime_scores"),
        ("t2_risk_scores",       "SELECT MAX(date)::DATE max_d, COUNT(*) n FROM t2_risk_scores"),
        ("sepa_watchlist",       "SELECT MAX(entry_date)::DATE max_d, COUNT(*) n FROM sepa_watchlist"),
        ("t3_sepa_features",     "SELECT MAX(date)::DATE max_d, COUNT(*) n FROM t3_sepa_features"),
        # Phase 6-7 — materialised
        ("screener_watchlist",   "SELECT MAX(price_date)::DATE max_d, COUNT(*) n FROM screener_watchlist"),
        ("d2_training_cache",    "SELECT MAX(date)::DATE max_d, COUNT(*) n FROM d2_training_cache"),
        # ML registry
        ("models",               "SELECT MAX(training_date)::DATE max_d, COUNT(*) n FROM models"),
    ]
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        rows = []
        today = con.execute("SELECT CURRENT_DATE").fetchone()[0]
        for table, q in queries:
            try:
                r = con.execute(q).fetchone()
                if r and r[0] is not None:
                    max_d = r[0]
                    lag = (today - max_d).days if max_d else None
                    rows.append({"table": table, "max_date": max_d, "rows": r[1], "lag_days": lag})
                else:
                    rows.append({"table": table, "max_date": None, "rows": 0, "lag_days": None})
            except duckdb.Error:
                rows.append({"table": table, "max_date": None, "rows": 0, "lag_days": None})
        return pd.DataFrame(rows)
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_t1_ingestion_failures(days: int = 30) -> pd.DataFrame:
    """Aggregated T1 failures from pipeline_error_log for Page 5.

    One row per (ticker, phase, error_type) — sorted by days_failing desc so
    chronic offenders surface first as pruning candidates.
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(f"""
            SELECT pel.affected_entity                AS ticker,
                   pel.phase_name                     AS phase,
                   pel.error_type                     AS error_type,
                   COUNT(DISTINCT pr.target_date)     AS days_failing,
                   MIN(pr.target_date)                AS first_failure_date,
                   MAX(pr.target_date)                AS last_failure_date,
                   ANY_VALUE(pel.error_detail)        AS sample_detail
            FROM pipeline_error_log pel
            JOIN pipeline_runs pr ON pel.run_id = pr.run_id
            WHERE pel.phase_name LIKE 'phase_1%'
              AND pr.target_date >= CURRENT_DATE - INTERVAL '{int(days)} day'
              AND pel.affected_entity IS NOT NULL
            GROUP BY 1, 2, 3
            ORDER BY days_failing DESC, last_failure_date DESC
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_latest_fundamentals_snapshot(n: int = 10) -> pd.DataFrame:
    """For Page 5 Fundamentals Audit: most recently updated tickers with key metrics."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(f"""
            SELECT ticker, period_end, filing_date, updated_at, source,
                   total_revenue, net_income, basic_eps, free_cash_flow
            FROM fundamentals
            WHERE updated_at IS NOT NULL
            ORDER BY updated_at DESC, period_end DESC
            LIMIT {int(n)}
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_fundamentals_volume_by_quarter(start_year: int = 2020) -> pd.DataFrame:
    """For Page 5 Fundamentals Audit: row counts per period quarter.

    Catches volume drops that would indicate yfinance/FMP coverage gaps.
    Counts rows where revenue is non-null (a row with only date is not a real fetch).
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(f"""
            SELECT YEAR(period_end)                                 AS year,
                   QUARTER(period_end)                              AS quarter,
                   YEAR(period_end) || '-Q' || QUARTER(period_end)  AS quarter_label,
                   COUNT(*)                                         AS rows_fetched,
                   COUNT(DISTINCT ticker)                           AS tickers
            FROM fundamentals
            WHERE period_end >= '{int(start_year)}-01-01'
              AND total_revenue IS NOT NULL
            GROUP BY 1, 2
            ORDER BY year, quarter
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_universe_trend(days: int = 60) -> pd.DataFrame:
    """For Page 5: trend_ok / breakout_ok counts per day."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(f"""
            SELECT date,
                   COUNT(*) FILTER (WHERE trend_ok)                  AS trend_ok_n,
                   COUNT(*) FILTER (WHERE trend_ok AND breakout_ok)  AS breakout_n
            FROM t2_screener_features
            WHERE date >= CURRENT_DATE - INTERVAL {int(days)} DAY
            GROUP BY date
            ORDER BY date
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_pre_breakout(limit: int = 100) -> pd.DataFrame:
    """Latest-day trend_ok=True AND breakout_ok=False tickers with t3 features.

    Joins screener_features (broad) with t3_sepa_features (dense features needed
    for scoring) so the model can run end-to-end on the cohort. Only tickers
    that survive the join (i.e., already on the SEPA universe) are returned —
    other trend_ok names that aren't in t3 are not scoreable yet.
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(f"""
            WITH latest_t2 AS (
                SELECT * FROM t2_screener_features
                WHERE date = (SELECT MAX(date) FROM t2_screener_features)
                  AND trend_ok = TRUE
                  AND breakout_ok = FALSE
            ),
            t3_latest AS (
                SELECT * FROM t3_sepa_features
                WHERE date = (SELECT MAX(date) FROM t3_sepa_features)
            ),
            sepa_active AS (
                SELECT ticker, MAX(entry_date) AS setup_started
                FROM sepa_watchlist
                WHERE status = 'ACTIVE'
                GROUP BY ticker
            )
            SELECT t3.*,
                   c.sector, c.industry, c.name AS company_name,
                   sa.setup_started,
                   CASE WHEN sa.setup_started IS NOT NULL
                        THEN DATEDIFF('day', sa.setup_started, t3.date)
                        ELSE NULL END AS days_in_setup
            FROM t3_latest t3
            JOIN latest_t2 lt2 ON lt2.ticker = t3.ticker
            LEFT JOIN company_profiles c ON c.ticker = t3.ticker
            LEFT JOIN sepa_active sa     ON sa.ticker = t3.ticker
            LIMIT {int(limit)}
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_sector_heat(window_days: int = 1) -> pd.DataFrame:
    """Sector heat over a lookback window. window_days=1 → today only;
    window_days=5 → last 5 trading days averaged; etc.

    Returns one row per sector with average trend_ok / breakout counts per day
    within the window, plus the latest-day point for comparison.
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    # window_days=1 → today only. window_days=N → last N trading days from MAX(date).
    try:
        return con.execute(f"""
            WITH window_dates AS (
                SELECT date FROM (
                    SELECT DISTINCT date FROM t2_screener_features
                    ORDER BY date DESC
                    LIMIT {int(window_days)}
                )
            ),
            per_day AS (
                SELECT t.date,
                       c.sector,
                       COUNT(*) FILTER (WHERE t.trend_ok)                  AS trend_ok_n,
                       COUNT(*) FILTER (WHERE t.trend_ok AND t.breakout_ok) AS breakout_n,
                       COUNT(*)                                            AS universe_n
                FROM t2_screener_features t
                JOIN window_dates w ON w.date = t.date
                LEFT JOIN company_profiles c ON c.ticker = t.ticker
                WHERE c.sector IS NOT NULL
                GROUP BY t.date, c.sector
            )
            SELECT sector,
                   AVG(trend_ok_n)::DOUBLE AS trend_ok_n,
                   AVG(breakout_n)::DOUBLE AS breakout_n,
                   AVG(universe_n)::DOUBLE AS universe_n,
                   COUNT(DISTINCT date)    AS days_in_window
            FROM per_day
            GROUP BY sector
            ORDER BY breakout_n DESC, trend_ok_n DESC
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_prod_model_version_id() -> str | None:
    """version_id of the currently-promoted prod classifier, or None if none registered."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        row = con.execute("""
            SELECT version_id FROM models
            WHERE status_flag = 'prod' AND model_type = 'classifier'
            ORDER BY updated_at DESC LIMIT 1
        """).fetchone()
        return row[0] if row else None
    finally:
        con.close()


@st.cache_data(ttl=60)
def load_daily_predictions_today(model_version_id: str) -> pd.DataFrame:
    """Latest-date daily_predictions for a given model. Empty df if none logged yet."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute("""
            SELECT prediction_date, ticker, model_version_id,
                   prob_class_0, prob_class_1, prob_class_2, prob_class_3,
                   predicted_class, rank_within_day,
                   decision_taken, taken_at, notes
            FROM daily_predictions
            WHERE model_version_id = ?
              AND prediction_date = (
                  SELECT MAX(prediction_date) FROM daily_predictions
                  WHERE model_version_id = ?
              )
            ORDER BY rank_within_day NULLS LAST, ticker
        """, [model_version_id, model_version_id]).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=60)
def load_past_decisions(model_version_id: str, limit: int = 200) -> pd.DataFrame:
    """Past decisions joined against screener_watchlist for realized outcomes.

    Used by the "Performance of past decisions" view on Page 1. Only rows where
    the user has actually toggled `decision_taken` (NULL rows are excluded).
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute("""
            SELECT
                dp.prediction_date, dp.ticker, dp.predicted_class,
                dp.prob_class_3 AS p_home_run,
                dp.rank_within_day,
                dp.decision_taken, dp.taken_at, dp.notes,
                sw.entry_date, sw.exit_date, sw.status,
                sw.pct_return, sw.days_held
            FROM daily_predictions dp
            LEFT JOIN screener_watchlist sw
                ON sw.ticker = dp.ticker AND sw.entry_date >= dp.prediction_date
            WHERE dp.model_version_id = ?
              AND dp.decision_taken IS NOT NULL
            ORDER BY dp.prediction_date DESC, dp.rank_within_day NULLS LAST
            LIMIT ?
        """, [model_version_id, int(limit)]).fetchdf()
    finally:
        con.close()


def update_decision_taken(
    prediction_date,
    ticker: str,
    model_version_id: str,
    decision: str | None,
    notes: str | None = None,
) -> None:
    """Flip decision_taken / taken_at for one (date, ticker, model) row.

    `decision` is one of 'taken' | 'skipped' | None (clears the decision).
    Writer is uncached — caller should clear `load_daily_predictions_today` and
    `load_past_decisions` after invoking.
    """
    if decision not in (None, "taken", "skipped"):
        raise ValueError(f"decision must be 'taken' | 'skipped' | None, got {decision!r}")

    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute("""
            UPDATE daily_predictions
            SET decision_taken = ?,
                taken_at = CASE WHEN ? IS NULL THEN NULL ELSE CURRENT_TIMESTAMP END,
                notes = COALESCE(?, notes)
            WHERE prediction_date = ? AND ticker = ? AND model_version_id = ?
        """, [decision, decision, notes, prediction_date, ticker, model_version_id])
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_models_table() -> pd.DataFrame:
    """For Model Lab — registry list."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute("""
            SELECT version_id, status_flag, model_type, feature_version,
                   training_date, dataset_rows, accuracy, weighted_f1, macro_f1,
                   artifacts_path, specs_json, updated_at
            FROM models
            ORDER BY
                CASE status_flag WHEN 'prod' THEN 0 WHEN 'test' THEN 1 ELSE 2 END,
                training_date DESC
        """).fetchdf()
    finally:
        con.close()


@st.cache_resource
def load_prod_model() -> tuple[xgb.XGBClassifier, list[str]]:
    """The prod M01 classifier + its valid_features list. Cached as a resource."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        row = con.execute("""
            SELECT artifacts_path
            FROM models
            WHERE status_flag = 'prod' AND model_type = 'classifier'
            ORDER BY updated_at DESC LIMIT 1
        """).fetchone()
    finally:
        con.close()

    model_dir = ROOT / row[0] if row and row[0] else ROOT / "models" / "m01_baseline"
    meta = json.loads((model_dir / "metadata.json").read_text())
    features = meta["valid_features"]
    model = xgb.XGBClassifier()
    model.load_model(str(model_dir / "model.json"))
    return model, features


# ── M01 scoring helper (extracted so multiple pages can use it) ──────────────

def score_features_df(features_df: pd.DataFrame) -> pd.DataFrame:
    """Run M01 prod model on a features DataFrame and append class/proba columns.

    features_df must have at least 'ticker' and the model's required feature
    columns (case-insensitive). Returns the input plus m01_class, m01_class_id,
    and p_<label> columns.
    """
    if features_df.empty:
        return features_df

    model, features = load_prod_model()

    col_map = {c.lower(): c for c in features_df.columns}
    available = []
    for f in features:
        col = col_map.get(f.lower())
        if col:
            available.append((f, col))

    if not available:
        return features_df

    X = features_df[[col for _, col in available]].copy()
    X.columns = [f for f, _ in available]
    for f in features:
        if f not in X.columns:
            X[f] = np.nan
    X = X[features]

    for col in X.select_dtypes(include="object").columns:
        try:
            X[col] = X[col].astype(float)
        except (ValueError, TypeError):
            X[col] = X[col].astype("category")

    probas = model.predict_proba(X)
    preds = np.argmax(probas, axis=1)

    out = features_df.copy()
    out["m01_class"] = [CLASS_LABELS[p] for p in preds]
    out["m01_class_id"] = preds
    for i, label in enumerate(CLASS_LABELS):
        out[f"p_{label}"] = probas[:, i]
    return out
