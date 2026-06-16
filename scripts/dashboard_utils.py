"""Shared dashboard utilities — DB loaders, constants, label helpers.

Centralizes things every page needs so the per-page files stay focused on
rendering. Read-only DB access throughout.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent

# Streamlit Cloud stores secrets in st.secrets, not os.environ. Pull each key
# we care about explicitly — iterating st.secrets can miss keys depending on
# TOML structure.
_SECRET_KEYS = (
    "DASHBOARD_DB_PATH",
    "R2_ACCOUNT_ID", "R2_ACCESS_KEY", "R2_SECRET_KEY",
    "R2_BUCKET_NAME", "R2_JURI_ENDPOINT_URL",
)
try:
    for _k in _SECRET_KEYS:
        if _k not in os.environ and _k in st.secrets:
            os.environ[_k] = str(st.secrets[_k])
except Exception:
    pass  # no st.secrets (local run) — env vars already in os.environ

# DB path is configurable so the same app runs against the full local DB or a
# slim, remote-synced dashboard.duckdb. Set DASHBOARD_DB_PATH (absolute, or
# relative to repo root) to point at the slim DB. Default: full local DB.
_db_env = os.environ.get("DASHBOARD_DB_PATH")
if _db_env:
    _db = Path(_db_env)
    DB_PATH = _db if _db.is_absolute() else ROOT / _db
else:
    DB_PATH = ROOT / "data" / "market_data.duckdb"


def _on_cloud() -> bool:
    """True when R2 creds are present (Streamlit Cloud); False on local runs."""
    return bool(os.environ.get("R2_ACCOUNT_ID") and os.environ.get("R2_ACCESS_KEY"))


def _r2_client():
    import boto3

    account_id = os.environ["R2_ACCOUNT_ID"]
    endpoint = os.environ.get("R2_JURI_ENDPOINT_URL") or f"https://{account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],
        aws_secret_access_key=os.environ["R2_SECRET_KEY"],
        region_name="auto",
    )


def _ensure_local_db() -> None:
    """Pull dashboard.duckdb from R2 when running on Streamlit Cloud.

    Downloads when: file is missing, local size doesn't match R2, or file is
    >23h old. Downloads atomically (temp file + rename) so a failed download
    never leaves a truncated DB behind. No-op on local runs.
    """
    if not _on_cloud():
        return  # local run — do nothing
    if not _db_env:
        return  # no explicit DB path configured, nothing to pull to

    import time

    target = DB_PATH
    client = _r2_client()
    bucket = os.environ["R2_BUCKET_NAME"]

    head = client.head_object(Bucket=bucket, Key="latest/dashboard.duckdb")
    r2_size = head["ContentLength"]

    # Skip if local file matches R2 size and is fresh (<23h)
    if (
        target.exists()
        and target.stat().st_size == r2_size
        and (time.time() - target.stat().st_mtime) < 23 * 3600
    ):
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    try:
        client.download_file(bucket, "latest/dashboard.duckdb", str(tmp))
        tmp.rename(target)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


# Disk-file dirs pulled from R2 on cloud boot. (local_dir, r2_prefix). Mirror of
# sync_dashboard_db.ASSET_DIRS — pages that read these degrade gracefully if the
# pull fails. data/backtest/ is intentionally not synced (WIP).
_ASSET_DIRS: list[tuple[Path, str]] = [
    (ROOT / "model_cards",            "model_cards"),
    (ROOT / "data" / "audit_reports", "audit_reports"),
    (ROOT / "docs" / "reports",       "docs_reports"),
    (ROOT / "models",                 "model_artifacts"),
]


# Per-dir outcome of the last _ensure_asset_dirs() run, surfaced by the
# Pipeline Health debug expander. One record per asset dir:
#   {"prefix", "pulled", "skipped", "exists", "error"}
ASSET_PULL_DIAG: list[dict] = []


def _ensure_asset_dirs() -> None:
    """Pull the dashboard's disk-file asset dirs from R2 on Streamlit Cloud.

    Each dir is mirrored from latest/<prefix>/ preserving relative paths. Best-
    effort and per-dir freshness-gated (>23h) so a cold start re-pulls but warm
    reruns don't. Failures never block the app — the reading pages degrade to a
    'not available' message. No-op on local runs. Per-dir results land in
    ASSET_PULL_DIAG so the Pipeline Health page can show what actually happened
    on the cloud host (the failure mode is invisible otherwise).
    """
    ASSET_PULL_DIAG.clear()
    if not _on_cloud():
        return

    import time

    try:
        client = _r2_client()
        bucket = os.environ["R2_BUCKET_NAME"]
    except Exception as e:
        ASSET_PULL_DIAG.append({"prefix": "<client>", "pulled": 0,
                                "skipped": False, "exists": False, "error": repr(e)})
        return

    paginator = client.get_paginator("list_objects_v2")
    for local_dir, prefix in _ASSET_DIRS:
        rec = {"prefix": prefix, "pulled": 0, "skipped": False,
               "exists": False, "error": None}
        try:
            # Freshness gate keyed on a sentinel marker that ONLY this pull writes
            # — NOT on file mtimes. Git may deploy a stale/partial subset of these
            # dirs (e.g. card .json files are tracked, .html are not); an mtime gate
            # would see those fresh files and skip the R2 pull, leaving the .html
            # (what Model Lab renders) absent. The marker is git-ignored, so a
            # cold cloud boot always pulls.
            marker = local_dir / ".r2_synced"
            if marker.exists() and (time.time() - marker.stat().st_mtime) < 23 * 3600:
                rec["skipped"] = True
                rec["exists"] = local_dir.exists()
                continue  # pulled within 23h — skip
            for page in paginator.paginate(Bucket=bucket, Prefix=f"latest/{prefix}/"):
                for obj in page.get("Contents", []):
                    rel = obj["Key"].split(f"latest/{prefix}/", 1)[-1]
                    if not rel:
                        continue
                    dest = local_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    client.download_file(bucket, obj["Key"], str(dest))
                    rec["pulled"] += 1
            local_dir.mkdir(parents=True, exist_ok=True)
            rec["exists"] = local_dir.exists()
            # Only set the 23h sentinel if we actually pulled something. An empty
            # listing (transient R2 hiccup, wrong prefix) would otherwise cache an
            # empty dir for 23h and starve the reading pages.
            if rec["pulled"] > 0:
                marker.touch()
        except Exception as e:
            rec["error"] = repr(e)  # surface, don't swallow — still non-fatal
        finally:
            ASSET_PULL_DIAG.append(rec)


_ensure_local_db()
_ensure_asset_dirs()

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
def load_regime_history(days: int | None = None) -> pd.DataFrame:
    """M03 regime score + 3 pillars over time (date asc). `days=None` → full history."""
    where = "" if days is None else f"WHERE date >= (SELECT MAX(date) FROM t2_regime_scores) - INTERVAL {int(days)} DAY"
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(f"""
            SELECT date, m03_score, m03_pillar_trend, m03_pillar_liq, m03_pillar_risk
            FROM t2_regime_scores
            {where}
            ORDER BY date
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_risk_history(days: int | None = None) -> pd.DataFrame:
    """5F factor z-scores + weighted_z over time (date asc). `days=None` → full history."""
    where = "" if days is None else f"AND date >= (SELECT MAX(date) FROM t2_risk_scores) - INTERVAL {int(days)} DAY"
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(f"""
            SELECT date, z_vix, z_hy, z_term, z_trend, z_slope, weighted_z
            FROM t2_risk_scores
            WHERE target_exposure IS NOT NULL
            {where}
            ORDER BY date
        """).fetchdf()
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


def _attach_class_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Translate materialized prob_class_N / predicted_class → the label columns
    the renderers expect (`m01_class`, `m01_class_id`, `p_<label>`).

    This is the read-side mirror of score_features_df's output contract, so the
    same render functions work whether scores come live (legacy) or from
    daily_predictions (current). Rows with no score (NULL predicted_class) get
    no label columns populated — NaN flows through formatting cleanly.
    """
    prob_cols = [f"prob_class_{i}" for i in range(len(CLASS_LABELS))]
    if not all(c in df.columns for c in prob_cols):
        return df
    out = df.copy()
    for i, label in enumerate(CLASS_LABELS):
        out[f"p_{label}"] = out[f"prob_class_{i}"]
    if "predicted_class" in out.columns:
        out["m01_class_id"] = out["predicted_class"]
        out["m01_class"] = out["predicted_class"].apply(
            lambda c: CLASS_LABELS[int(c)] if pd.notna(c) else None
        )
    return out


@st.cache_data(ttl=300)
def load_scored_watchlist(model_version_id: str) -> pd.DataFrame:
    """Watchlist rows joined with each row's OWN breakout-cohort score.

    Scores are pre-computed by the nightly pipeline (Phase 7.4) and backfilled
    across the d3 window (scripts/backfill_daily_predictions.py), stored in
    daily_predictions — so the model file never needs to exist on the serving host.

    Each watchlist row is matched to the breakout score at the latest
    prediction_date <= its entry_date (the score as the name actually broke out),
    NOT the single global latest date — otherwise only tickers that broke out on
    the most recent day would carry a score. Rows with no score at/before entry
    (e.g. entries predating the d3 window) flow through with NULLs. Output carries
    the `m01_class` / `p_<label>` columns the watchlist renderer expects.
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute("""
            WITH preds AS (
                SELECT ticker, prediction_date,
                       prob_class_0, prob_class_1, prob_class_2, prob_class_3,
                       predicted_class, rank_within_day
                FROM daily_predictions
                WHERE model_version_id = ? AND cohort = 'breakout'
            ),
            scored AS (
                SELECT sw.*,
                       p.prob_class_0, p.prob_class_1, p.prob_class_2, p.prob_class_3,
                       p.predicted_class, p.rank_within_day, p.prediction_date,
                       ROW_NUMBER() OVER (
                           PARTITION BY sw.ticker, sw.entry_date
                           ORDER BY p.prediction_date DESC
                       ) AS rn
                FROM screener_watchlist sw
                LEFT JOIN preds p
                    ON p.ticker = sw.ticker
                   AND p.prediction_date <= sw.entry_date
            )
            SELECT ticker, company_name, sector, industry,
                   market_cap, entry_date, entry_price,
                   exit_date, status, close_price, price_date,
                   pct_return, days_held, refreshed_at,
                   prob_class_0, prob_class_1, prob_class_2, prob_class_3,
                   predicted_class, rank_within_day, prediction_date
            FROM scored
            WHERE rn = 1            -- nearest score at/before entry per (ticker, entry_date)
            ORDER BY entry_date DESC, ticker
        """, [model_version_id]).fetchdf()
    finally:
        con.close()
    return _attach_class_labels(df)


# ── F2: watchlist activity / exit tracking ────────────────────────────────────
#
# `screener_watchlist` is the materialized trade log (every ACTIVE + EXITED
# session). `screener_membership` is the append-only universe event log (one row
# per is_active flip). These loaders surface "what left the watchlist / universe
# recently" — a gap the status-filtered watchlist table didn't expose.
#
# NOTE on ACTIVE rows: an ACTIVE watchlist row's `exit_date` equals its
# `price_date` (the prospective trend-break boundary, not a realized exit). These
# loaders only ever read EXITED rows for the exit/feed surfaces, so that quirk
# never leaks here.

@st.cache_data(ttl=300)
def load_recent_exits(days: int = 30) -> pd.DataFrame:
    """EXITED watchlist trades whose exit fell in the last `days` (by exit_date).

    Surfaces realized winners/losers that left the watchlist — e.g. LITE +777%,
    AXTI +1369%. Ordered most-recent-exit first.
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute("""
            WITH max_d AS (SELECT MAX(price_date) AS d FROM screener_watchlist)
            SELECT ticker, company_name, sector,
                   entry_date, exit_date, days_held, pct_return
            FROM screener_watchlist, max_d
            WHERE status = 'EXITED'
              AND exit_date >= max_d.d - INTERVAL (?) DAY
            ORDER BY exit_date DESC, pct_return DESC
        """, [int(days)]).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_ticker_history(ticker: str) -> pd.DataFrame:
    """Every screener_watchlist session for one ticker (all entry→exit cycles)."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute("""
            SELECT ticker, company_name, sector,
                   entry_date, entry_price, exit_date, status,
                   close_price, pct_return, days_held
            FROM screener_watchlist
            WHERE ticker = ?
            ORDER BY entry_date
        """, [ticker.strip().upper()]).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_activity_feed(days: int = 14) -> pd.DataFrame:
    """Unified recent-activity timeline merging two event sources:

      - TRADE_EXIT     : a screener_watchlist session closed (status=EXITED)
      - UNIVERSE_ADD   : a screener_membership is_active=TRUE flip
      - UNIVERSE_REMOVE: a screener_membership is_active=FALSE flip

    One row per event, newest first. `detail` is a pre-formatted human string so
    the renderer stays dumb. Company name comes from company_profiles (membership
    carries ticker only).
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute("""
            WITH exits AS (
                     SELECT
                         sw.exit_date              AS event_date,
                         sw.ticker,
                         sw.company_name,
                         'TRADE_EXIT'              AS event_type,
                         printf('%+.1f%% over %dd', sw.pct_return, sw.days_held) AS detail
                     FROM screener_watchlist sw
                     WHERE sw.status = 'EXITED'
                       AND sw.exit_date >= (
                           SELECT MAX(price_date) FROM screener_watchlist
                       ) - INTERVAL (?) DAY
                 ),
                 flips AS (
                     SELECT
                         m.effective_date          AS event_date,
                         m.ticker,
                         cp.name                   AS company_name,
                         CASE WHEN m.is_active THEN 'UNIVERSE_ADD'
                              ELSE 'UNIVERSE_REMOVE' END AS event_type,
                         printf('$%.2f', m.last_price) AS detail
                     FROM screener_membership m
                     LEFT JOIN company_profiles cp ON cp.ticker = m.ticker
                     WHERE m.effective_date >= (
                           SELECT MAX(effective_date) FROM screener_membership
                       ) - INTERVAL (?) DAY
                 )
            SELECT event_date, ticker, company_name, event_type, detail
            FROM (SELECT * FROM exits UNION ALL SELECT * FROM flips)
            ORDER BY event_date DESC, event_type, ticker
        """, [int(days), int(days)]).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_scored_pre_breakout(model_version_id: str, limit: int = 100) -> pd.DataFrame:
    """Pre-breakout cohort (trend_ok & !breakout_ok) with materialized scores.

    Reads v_d3_prebreakout (display features) LEFT JOINed to daily_predictions
    (cohort='pre_breakout', latest scored date) — no live model scoring. Adds
    company_name + days_in_setup for display. Output carries the `m01_class` /
    `p_<label>` columns the renderer expects.
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute("""
            WITH pb AS (
                SELECT * FROM v_d3_prebreakout
                WHERE date = (SELECT MAX(date) FROM v_d3_prebreakout)
            ),
            sepa_active AS (
                SELECT ticker, MAX(entry_date) AS setup_started
                FROM sepa_watchlist WHERE status = 'ACTIVE'
                GROUP BY ticker
            )
            SELECT
                pb.ticker, pb.sector, pb.close, pb.dist_from_20d_high,
                pb.vol_ratio_50, pb.vcp_ratio, pb.date,
                cp.name AS company_name,
                CASE WHEN sa.setup_started IS NOT NULL
                     THEN DATEDIFF('day', sa.setup_started, pb.date)
                     ELSE NULL END AS days_in_setup,
                dp.prob_class_0, dp.prob_class_1, dp.prob_class_2, dp.prob_class_3,
                dp.predicted_class, dp.rank_within_day, dp.prediction_date
            FROM pb
            LEFT JOIN company_profiles cp ON cp.ticker = pb.ticker
            LEFT JOIN sepa_active sa       ON sa.ticker = pb.ticker
            LEFT JOIN daily_predictions dp
                ON dp.ticker = pb.ticker
               AND dp.model_version_id = ?
               AND dp.cohort = 'pre_breakout'
               AND dp.prediction_date = (
                   SELECT MAX(prediction_date) FROM daily_predictions
                   WHERE model_version_id = ? AND cohort = 'pre_breakout'
               )
            ORDER BY dp.rank_within_day NULLS LAST, pb.ticker
            LIMIT ?
        """, [model_version_id, model_version_id, int(limit)]).fetchdf()
    finally:
        con.close()
    return _attach_class_labels(df)


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
