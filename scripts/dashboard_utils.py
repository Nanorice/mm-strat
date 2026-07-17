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
    """True when R2 creds are present (Streamlit Cloud); False on local runs.

    ⚠️ KNOWN FLAW (2026-07-16, not yet fixed — needs the user's call): this infers
    "am I the cloud app?" from R2 creds, but the ops box (sh019) holds the same
    creds for the nightly sync and the dev box's .env carries them too. So any
    dotenv-loading process that imports dashboard_utils (pytest, scripts) starts a
    ~751 MB R2 download. Creds mean "can reach R2", not "am the cloud app". A real
    fix needs a positive cloud marker whose value can be verified ON Streamlit
    Cloud — guessing it here would silently stop the remote pull (stale DB, worse
    than this). Locally, `_db_env` (DASHBOARD_DB_PATH) usually short-circuits it.
    """
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

    Re-downloads when the R2 object's ETag differs from the one we last pulled
    (recorded in a git-ignored sidecar marker), or as a >23h backstop. The ETag
    is a content hash, so it flips on every nightly rebuild — unlike file SIZE,
    which is ~793 MB every day and matched spuriously, leaving the app serving
    yesterday's DB for up to the TTL. Downloads atomically (temp file + rename)
    so a failed download never leaves a truncated DB behind. No-op on local runs.
    """
    if not _on_cloud():
        return  # local run — do nothing
    if not _db_env:
        return  # no explicit DB path configured, nothing to pull to

    import time

    target = DB_PATH
    marker = target.with_suffix(".r2etag")  # git-ignored; last-pulled ETag
    client = _r2_client()
    bucket = os.environ["R2_BUCKET_NAME"]

    head = client.head_object(Bucket=bucket, Key="latest/dashboard.duckdb")
    r2_etag = head["ETag"].strip('"')

    # Skip only if the local DB is present, its ETag marker matches R2's current
    # ETag, AND it's fresh (<23h backstop in case the marker drifts from the DB).
    if (
        target.exists()
        and marker.exists()
        and marker.read_text().strip() == r2_etag
        and (time.time() - target.stat().st_mtime) < 23 * 3600
    ):
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    try:
        client.download_file(bucket, "latest/dashboard.duckdb", str(tmp))
        # os.replace, not Path.rename: on Windows rename() raises FileExistsError
        # when the target exists (POSIX rename overwrites silently). os.replace is
        # atomic-overwrite on both platforms.
        os.replace(tmp, target)
        marker.write_text(r2_etag)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


# Per-rerun R2 freshness re-check. `_ensure_local_db()` only ran at module import
# (once per container), so a warm Streamlit Cloud container never saw a new nightly
# upload until it restarted. Routing reads through `_connect()` re-checks the R2
# ETag (cheap head_object) at most every _R2_RECHECK_SECS and re-pulls when it
# changed; the 300s query cache then surfaces the new data within ~5 min. The
# throttle global persists across Streamlit reruns (module imported once). No-op
# on local runs.
_R2_RECHECK_SECS = 120
_last_r2_check = 0.0


def _maybe_refresh_from_r2() -> None:
    global _last_r2_check
    if not _on_cloud() or not _db_env:
        return
    import time
    now = time.time()
    if now - _last_r2_check < _R2_RECHECK_SECS:
        return
    _last_r2_check = now
    try:
        _ensure_local_db()  # ETag-gated: re-downloads only when R2 actually changed
    except Exception:
        pass


def _connect(read_only: bool = True):
    """Open the dashboard DB, first re-pulling from R2 if the nightly upload
    changed it (throttled). Use for all reads so a warm cloud container stays
    current without a manual reboot."""
    _maybe_refresh_from_r2()
    return duckdb.connect(str(DB_PATH), read_only=read_only)


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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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


@st.cache_data(ttl=3600)
def load_macro_pillars() -> pd.DataFrame:
    """Load the 6 Macro Pillars: VIX, Credit, Term Spread, Rates, Liquidity, CAPE.

    Reads ALL series — including CAPE and DFII10 — from the `macro_data` table.
    No live network fetch: the macro pipeline (Phase 1) is the single writer.

    Calculates display-only percentiles (0-100) for each pillar:
    - Fast Risk (all-time rank): VIX, Credit, Term Spread
    - Slow Fundamentals (5-yr rolling rank): Rates, Liquidity, CAPE
    NOTE: all-time rank uses the full series (look-ahead) — fine for a "where are
    we historically" gauge, but do NOT feed these percentiles into a backtest.
    """
    con = _connect()
    try:
        df_db = con.execute("""
            SELECT date, symbol, close AS value
            FROM macro_data
            WHERE symbol IN (
                'VIX', 'BAMLH0A0HYM2', 'DGS10', 'DGS2',
                'WALCL', 'WTREGEN', 'RRPONTSYD', 'CAPE', 'CAPE_OURS'
            )
        """).fetchdf()
    finally:
        con.close()

    df_db['value'] = pd.to_numeric(df_db['value'], errors='coerce')
    # DuckDB DATE -> pandas can land as datetime64[us]; normalize so consumers
    # can compare against pd.Timestamp without dtype-mismatch TypeErrors.
    df_db['date'] = pd.to_datetime(df_db['date'])
    df_db = df_db.drop_duplicates(subset=['date', 'symbol'])
    df_db = df_db.pivot(index='date', columns='symbol', values='value').reset_index()
    # Forward fill missing daily values, then drop rows before we have VIX data
    for col in ('VIX', 'CAPE', 'CAPE_OURS'):
        if col not in df_db.columns:
            df_db[col] = pd.NA
    df_db = df_db.set_index('date').sort_index().ffill().dropna(subset=['VIX'])

    # Valuation pillar sources from our self-computed CAPE_OURS (live, updates nightly).
    # Yale 'CAPE' is dormant (froze 2024-09) — kept as a raw cross-check column only.
    # See docs/session_logs/sprint_13/cape_fred_proxy_findings.md.
    df_db['CAPE_yale'] = df_db['CAPE']
    if not df_db['CAPE_OURS'].isna().all():
        df_db['CAPE'] = df_db['CAPE_OURS']

    # Map raw series to the 6 pillars.
    df_db['Credit'] = df_db['BAMLH0A0HYM2']
    df_db['Term Spread'] = df_db['DGS10'] - df_db['DGS2']
    # Net Liquidity in billions, matching MacroEngine.get_net_liquidity():
    #   WALCL (millions) - WTREGEN (millions) - RRPONTSYD (already billions)
    df_db['Liquidity'] = (
        df_db['WALCL'] / 1000.0
        - df_db['WTREGEN'].fillna(0) / 1000.0
        - df_db['RRPONTSYD'].fillna(0)
    )
    df_db['Rates'] = df_db['DGS10']

    # Percentiles — all-time rank for fast pillars, 5-yr rolling for slow ones.
    for col in ['VIX', 'Credit', 'Term Spread']:
        df_db[f'{col}_pct'] = df_db[col].rank(pct=True) * 100

    for col in ['Rates', 'Liquidity', 'CAPE']:
        if col in df_db.columns and not df_db[col].isna().all():
            df_db[f'{col}_pct'] = df_db[col].rolling(1260, min_periods=252).rank(pct=True) * 100
        else:
            df_db[f'{col}_pct'] = pd.NA

    return df_db.reset_index()


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
    """Watchlist rows joined with the prod-model score that matters for each row.

    Scores are pre-computed by the nightly pipeline (Phase 7.4) and backfilled
    across the d3 window (scripts/backfill_daily_predictions.py), stored in
    daily_predictions — so the model file never needs to exist on the serving host.

    Same-day score, no carry-forward (lifecycle scoring makes carry-forward
    obsolete — the daily pipeline now scores the whole held + setup population every
    day, so each watchlist row has a genuine same-day score). The join is on the
    watchlist row's as-of date (`price_date`):
      - ACTIVE  → `price_date` is the latest trading day, so this is today's score —
                  the name's score as the position ages, refreshed daily.
      - EXITED  → `price_date` is the exit day, so this is its score on the exit day
                  (the last `removed` row). "Now" is meaningless for a closed trade.

    A name with no `daily_predictions` row on its `price_date` flows through with
    NULLs — a real signal that it fell out of the scoring population (e.g. left t3),
    NOT a silently stale value from a prior day. Cohort-agnostic: any tag's row for
    that (ticker, date) is the same prod-model score on the same feature set. Output
    carries the `m01_class` / `p_<label>` columns the watchlist renderer expects.
    """
    con = _connect()
    try:
        df = con.execute("""
            WITH preds AS (
                -- One score per (ticker, date) across tags. A held name re-setting up
                -- is written under one tag/day (active > removed > pre_breakout), but
                -- guard against any overlap by taking the best-ranked row.
                SELECT ticker, prediction_date,
                       prob_class_0, prob_class_1, prob_class_2, prob_class_3,
                       predicted_class, rank_within_day
                FROM daily_predictions
                WHERE model_version_id = ?   -- any cohort
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY ticker, prediction_date
                    ORDER BY rank_within_day
                ) = 1
            )
            SELECT sw.ticker, sw.company_name, sw.sector, sw.industry,
                   sw.market_cap, sw.entry_date, sw.entry_price,
                   sw.exit_date, sw.status, sw.close_price, sw.price_date,
                   sw.pct_return, sw.days_held, sw.refreshed_at,
                   p.prob_class_0, p.prob_class_1, p.prob_class_2, p.prob_class_3,
                   p.predicted_class, p.rank_within_day, p.prediction_date
            FROM screener_watchlist sw
            LEFT JOIN preds p
                ON p.ticker = sw.ticker
               -- Same-day score: the watchlist row's as-of date. No carry-forward.
               AND p.prediction_date = sw.price_date
            ORDER BY sw.entry_date DESC, sw.ticker
        """, [model_version_id]).fetchdf()
    finally:
        con.close()
    return _attach_class_labels(df)


@st.cache_data(ttl=300)
def load_shortlist() -> pd.DataFrame:
    """Today's ranked manual-review shortlist — the sprint-14 tail edge as a product.

    Reads `v_d3_shortlist` (materialized nightly), which is a pure join of the
    active SEPA breakouts with the prod model's score, ranked by the strong-RS ×
    small-cap × prob_elite composite and tagged liquid/posture. Model-swap safe by
    construction — the view resolves the `status_flag='prod'` model itself, so no
    version id is threaded through here (unlike `load_scored_watchlist`). Present
    as tail-odds, NOT a point return (the median inverts).
    """
    con = _connect()
    try:
        return con.execute("SELECT * FROM v_d3_shortlist").fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_screening() -> pd.DataFrame:
    """Screening surface — today's trend_ok/breakout_ok universe, ranked by P(HR).

    Reads `v_d3_screening` (materialized nightly): the whole screening population
    (stage = setup/triggered) with the prod model's P(Home Run), precomputed
    margins/growth, and a derived P/E ("—" when unprofitable). One filterable
    table that supersedes the scattered Shortlist / Pre-Breakout / VIP candidate
    tables on the old Today page. P(HR) is NULL for names outside the scored
    cohorts — an honest gap, not a stale value. Sorted P(HR) desc by the view.
    """
    con = _connect()
    try:
        return con.execute("SELECT * FROM v_d3_screening").fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_portfolio() -> pd.DataFrame:
    """Open positions derived from the hand-entered `trades` fill log.

    `trades` is append-only (one row per fill); positions are DERIVED, never
    stored — qty = SUM(+buy/-sell), avg_cost weighted over BUY fills only so a
    partial sale doesn't distort the remaining lot's basis. Marked to the latest
    `price_data.close`; an unpriced ticker marks NULL rather than dropping out.

    Empty is the normal state until fills are entered via scripts/portfolio.py.

    The derivation mirrors PortfolioManager.positions() rather than calling it:
    the manager's ensure_schema() opens a WRITE connection, which would take an
    exclusive lock against the dashboard's readers (and fail outright on the
    read-only cloud container). `tests/test_portfolio_manager.py::
    test_loader_matches_manager` pins the two to the same numbers.
    """
    con = _connect()
    try:
        return con.execute("""
            WITH agg AS (
                SELECT ticker,
                       SUM(CASE WHEN side='BUY' THEN quantity ELSE -quantity END) AS qty,
                       SUM(CASE WHEN side='BUY' THEN quantity*price + fees END)
                         / NULLIF(SUM(CASE WHEN side='BUY' THEN quantity END), 0)  AS avg_cost,
                       MIN(trade_date) AS first_entry,
                       COUNT(*)        AS n_fills
                FROM trades GROUP BY ticker
            ),
            px AS (
                SELECT ticker, close, date AS price_date,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
                FROM price_data
                WHERE ticker IN (SELECT ticker FROM agg) AND close IS NOT NULL
            ),
            -- Latest PROD-model row per held ticker. The model scores only the
            -- SEPA lifecycle universe (~751 of ~3,980 active names), so a held
            -- name outside it gets NULL — an honest gap, not a stale score.
            -- prob_class_1 is the binary model's P(fwd>30%); prob_class_3 is the
            -- archived 4-class column and is NULL here (the known COALESCE trap).
            scored AS (
                SELECT ticker, cohort, prediction_date, rank_within_day,
                       COALESCE(prob_class_3, prob_class_1) AS score_raw,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY prediction_date DESC) AS rn
                FROM daily_predictions
                WHERE model_version_id = (
                        SELECT model_version_id FROM daily_predictions
                        GROUP BY 1 ORDER BY MAX(prediction_date) DESC, MAX(ingested_at) DESC LIMIT 1)
                  AND ticker IN (SELECT ticker FROM agg)
            )
            SELECT a.ticker, a.qty, a.avg_cost, p.close, p.price_date,
                   a.qty * p.close                          AS market_value,
                   (p.close - a.avg_cost) * a.qty           AS unrealized_pnl,
                   (p.close / NULLIF(a.avg_cost,0) - 1)*100 AS pct_return,
                   s.score_raw, s.cohort, s.rank_within_day, s.prediction_date AS score_date,
                   c.sector, c.industry,
                   a.first_entry, a.n_fills
            FROM agg a
            LEFT JOIN px p     ON p.ticker = a.ticker AND p.rn = 1
            LEFT JOIN scored s ON s.ticker = a.ticker AND s.rn = 1
            LEFT JOIN company_profiles c ON c.ticker = a.ticker
            WHERE a.qty > 1e-9
            ORDER BY market_value DESC NULLS LAST
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_nav_history() -> pd.DataFrame:
    """Daily NAV marks from `nav_history`. NAV = cash + positions."""
    con = _connect()
    try:
        return con.execute(
            "SELECT date, nav, cash, positions_value, net_flow, n_open "
            "FROM nav_history ORDER BY date"
        ).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_cash() -> float:
    """Cash balance DERIVED from cash_flows + fills (never a stored balance)."""
    con = _connect()
    try:
        flows = con.execute("""
            SELECT COALESCE(SUM(CASE WHEN kind='DEPOSIT' THEN amount ELSE -amount END), 0)
            FROM cash_flows
        """).fetchone()[0]
        fills = con.execute("""
            SELECT COALESCE(SUM(CASE WHEN side='BUY' THEN -(quantity*price) - fees
                                     ELSE  (quantity*price) - fees END), 0)
            FROM trades
        """).fetchone()[0]
    finally:
        con.close()
    return float(flows) + float(fills)


@st.cache_data(ttl=300)
def load_returns() -> pd.DataFrame:
    """Daily TIME-WEIGHTED return series derived from nav_history.

    r_t = (nav_t - net_flow_t) / nav_{t-1} - 1 — the day's external flow is
    stripped, so a deposit is NOT a gain (a naive pct_change would book a 500k
    contribution as a 500k profit). Mirrors PortfolioManager.returns(); pinned
    by test_loader_returns_match_manager.
    """
    nav = load_nav_history()
    if len(nav) < 2:
        return pd.DataFrame(columns=["date", "ret", "cum_ret", "drawdown"])
    nav = nav.sort_values("date").reset_index(drop=True)
    prev = nav["nav"].shift(1)
    nav["ret"] = (nav["nav"] - nav["net_flow"].fillna(0)) / prev - 1
    nav = nav.iloc[1:].copy()
    curve = (1 + nav["ret"]).cumprod()
    nav["cum_ret"] = curve - 1
    nav["drawdown"] = curve / curve.cummax().clip(lower=1.0) - 1
    return nav[["date", "ret", "cum_ret", "drawdown"]]


@st.cache_data(ttl=300)
def load_portfolio_risk() -> pd.DataFrame:
    """Per-position risk EXPOSURE facts for the held book. Descriptive, not signals.

    Sourcing is deliberately split:
      * ATR(14) / realized vol / 20d-50d support-resistance come from `price_data`,
        so EVERY holding is covered — entries are discretionary, so a held name is
        often outside the SEPA screen (t3 covers ~2.4k of ~4.0k active tickers).
      * True 52-week high/low is READ from `t3_sepa_features` (precomputed, so it
        survives the slim DB's ~172-bar window — a real 52w level cannot be
        recomputed on the remote). NULL for non-screen names: an honest gap.

    ATR is Wilder's true range averaged over 14 bars, computed here rather than
    read from t3's `atr_20d` so the window is the same for every holding.

    No VaR / expected shortfall on purpose: at ~4 concentrated same-sector names the
    covariance term dominates, and a normal-ish VaR on a 172-bar window prints a
    comfortable number right up to the regime that breaks it. It would mislead.
    """
    con = _connect()
    try:
        return con.execute("""
            WITH held AS (
                SELECT ticker,
                       SUM(CASE WHEN side='BUY' THEN quantity ELSE -quantity END) AS qty
                FROM trades GROUP BY ticker HAVING SUM(CASE WHEN side='BUY' THEN quantity ELSE -quantity END) > 1e-9
            ),
            bars AS (
                SELECT p.ticker, p.date, p.high, p.low, p.close,
                       LAG(p.close) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_close,
                       ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) AS rn
                FROM price_data p
                WHERE p.ticker IN (SELECT ticker FROM held) AND p.close IS NOT NULL
            ),
            tr AS (
                -- True range; GREATEST/LEAST bound the OHLC dirt (rounding-epsilon
                -- ordering violations are known in price_data).
                SELECT ticker, date, close, rn,
                       GREATEST(high, close) - LEAST(low, close)          AS hl,
                       ABS(GREATEST(high, close) - COALESCE(prev_close, close)) AS hc,
                       ABS(LEAST(low, close)  - COALESCE(prev_close, close))    AS lc,
                       close / NULLIF(prev_close, 0) - 1                  AS ret
                FROM bars
            ),
            agg AS (
                SELECT ticker,
                       AVG(CASE WHEN rn <= 14 THEN GREATEST(hl, hc, lc) END)        AS atr_14,
                       STDDEV_SAMP(CASE WHEN rn <= 20 THEN ret END) * SQRT(252)*100 AS vol_20d,
                       STDDEV_SAMP(CASE WHEN rn <= 60 THEN ret END) * SQRT(252)*100 AS vol_60d,
                       MAX(CASE WHEN rn <= 20 THEN close END)                       AS res_20d,
                       MIN(CASE WHEN rn <= 20 THEN close END)                       AS sup_20d,
                       MAX(CASE WHEN rn <= 50 THEN close END)                       AS res_50d,
                       MIN(CASE WHEN rn <= 50 THEN close END)                       AS sup_50d,
                       MAX(CASE WHEN rn  = 1  THEN close END)                       AS last_close
                FROM tr GROUP BY ticker
            ),
            wk52 AS (   -- precomputed; survives the slim window. NULL off-screen.
                SELECT ticker, high_52w, low_52w,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
                FROM t3_sepa_features WHERE ticker IN (SELECT ticker FROM held)
            )
            SELECT h.ticker, h.qty, a.last_close, a.atr_14,
                   a.atr_14 / NULLIF(a.last_close,0) * 100 AS atr_pct,
                   a.vol_20d, a.vol_60d,
                   a.sup_20d, a.res_20d, a.sup_50d, a.res_50d,
                   w.high_52w, w.low_52w,
                   -- distances in ATR units: comparable across names, dollars are not
                   (a.last_close - a.sup_50d) / NULLIF(a.atr_14,0) AS atr_to_sup_50d,
                   (a.res_50d - a.last_close) / NULLIF(a.atr_14,0) AS atr_to_res_50d,
                   h.qty * a.atr_14                                AS atr_move_value,
                   c.beta
            FROM held h
            LEFT JOIN agg  a ON a.ticker = h.ticker
            LEFT JOIN wk52 w ON w.ticker = h.ticker AND w.rn = 1
            LEFT JOIN company_profiles c ON c.ticker = h.ticker
            ORDER BY atr_move_value DESC NULLS LAST
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_vip_watchlist() -> pd.DataFrame:
    """Manually-curated VIP watchlist with each name's latest live status.

    Reads `v_d3_vip` (materialized nightly) — the VIP names you added via the CLI,
    LEFT-joined to their latest t3 flags, lifecycle cohort, and prod score, so you
    monitor the prod model score + SEPA status on your own picks even if they'd
    never pass the screen. `not_in_universe` flags a name with no price data yet.
    """
    con = _connect()
    try:
        return con.execute("SELECT * FROM v_d3_vip").fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_weather_gauge(history_days: int = 250) -> pd.DataFrame:
    """Weather-gauge state rows — the latest deploy posture + a history strip.

    Reads `weather_gauge` (computed nightly by weather_engine), one row/day of the
    combined SPY-200d brake + stress + breakout-supply state. Returns the last
    `history_days` rows (oldest→newest) so the caller has both the current headline
    (`.iloc[-1]`) and the transition strip. `stress_z` is PROVISIONAL (flicker
    stabilization open); the posture leans on the brake + supply.
    """
    con = _connect()
    try:
        return con.execute(
            "SELECT * FROM weather_gauge ORDER BY date DESC LIMIT ?",
            [history_days],
        ).fetchdf().iloc[::-1].reset_index(drop=True)
    finally:
        con.close()


@st.cache_data(ttl=3600)
def load_fear_greed(history_days: int = 250) -> pd.DataFrame:
    """CNN Fear & Greed (0-100 risk-appetite composite), newest last.

    Ingested nightly into `macro_data` as symbol 'FEAR_GREED' by macro_engine
    (`fetch_fear_greed`, curl_cffi chrome-impersonation to clear the Cloudflare
    TLS gate). CNN serves only ~1yr of daily history — there is no deep archive,
    so this series starts ~250 rows and does not backfill to 2003 like the FRED
    series. Empty frame if the scrape has never run.
    """
    con = _connect()
    try:
        return con.execute("""
            SELECT date, close AS score
            FROM macro_data
            WHERE symbol = 'FEAR_GREED'
            ORDER BY date DESC LIMIT ?
        """, [int(history_days)]).fetchdf().iloc[::-1].reset_index(drop=True)
    finally:
        con.close()


def fear_greed_label(score: float) -> str:
    """CNN's own 0-100 banding."""
    if pd.isna(score):
        return "—"
    if score < 25:
        return "Extreme Fear"
    if score < 45:
        return "Fear"
    if score <= 55:
        return "Neutral"
    if score <= 75:
        return "Greed"
    return "Extreme Greed"


@st.cache_data(ttl=300)
def load_macro_indicators(spark_days: int = 180) -> pd.DataFrame:
    """Macro-page S3 indicator board — one row per `config.FRED_SERIES` /
    `config.YAHOO_SERIES` / `config.SENTIMENT_SERIES` entry that carries a `group`
    tag, newest observation first.

    Columns: symbol, name, group, freq, unit, revised, date, value, prior, chg_pct,
    z, spark (list[float], oldest→newest), n_obs. A configured series with no rows in
    `macro_data` still returns a row (value NaN) so the board can grey it out rather
    than hide it — coverage is incomplete by design (C2 scrapes + C3 feeds pending).

    `prior` is the previous OBSERVATION, not a fixed calendar lag — so chg_pct means
    week-over-week for a weekly series and month-over-month for a monthly one.

    `z` = (latest change − mean change) / std change, over the series' **full**
    history (not the spark window — 180 obs is only 6 points for a monthly series).
    NaN when sigma is 0 or fewer than 30 changes exist. Change-z, not level-z: slow
    series sit at level ±2σ for years, so a level banner would never switch off.
    ⚠️ Full-history moments are an all-time stat = LOOK-AHEAD. Display-only; never
    feed z (or anything on this board) to a model.

    ⚠️ `revised=True` series (payrolls, CPI, PCE, GDPNow, …) are DISPLAY-ONLY: FRED
    restates them, but macro_engine writes INSERT OR IGNORE so the first print wins
    and revisions are dropped. Do not feed these to a model expecting point-in-time
    accuracy. See config.FRED_SERIES.
    """
    import config

    meta = {s: m for s, m in {**config.FRED_SERIES, **config.YAHOO_SERIES,
                              **config.SENTIMENT_SERIES}.items()
            if m.get("group")}
    if not meta:
        return pd.DataFrame()

    syms = list(meta)
    ph = ",".join("?" * len(syms))
    con = _connect()
    try:
        obs = con.execute(f"""
            WITH ranked AS (
                SELECT symbol, date, close,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                FROM macro_data
                WHERE symbol IN ({ph}) AND close IS NOT NULL
            )
            SELECT symbol, date, close FROM ranked WHERE rn <= ?
            ORDER BY symbol, date
        """, syms + [int(spark_days)]).fetchdf()

        # Change-z stats over FULL history (not the spark window — 180 obs is only 6
        # points for a monthly series). Computed in SQL so we never pull 200k rows
        # into pandas just for two moments.
        #
        # The change is measured in PCT for level-like units and ABSOLUTE for
        # spreads/rates (config.S3_PCT_UNITS) — absolute change isn't stationary for
        # a trending price, pct-change explodes for a series crossing zero. See the
        # config note for the measured evidence.
        pct_syms = [s for s, m in meta.items() if m.get("unit") in config.S3_PCT_UNITS]
        pct_list = ",".join("?" * len(pct_syms)) if pct_syms else "NULL"
        stats = con.execute(f"""
            WITH d AS (
                SELECT symbol, date, close,
                       LAG(close) OVER (PARTITION BY symbol ORDER BY date) AS prev
                FROM macro_data
                WHERE symbol IN ({ph}) AND close IS NOT NULL
            ), e AS (
                SELECT symbol, date,
                       CASE WHEN symbol IN ({pct_list})
                            THEN (close - prev) / ABS(prev) * 100
                            ELSE close - prev END AS v
                FROM d
                WHERE prev IS NOT NULL
                  AND NOT (symbol IN ({pct_list}) AND prev = 0)
            )
            SELECT symbol,
                   AVG(v) AS mu, STDDEV_SAMP(v) AS sd, COUNT(v) AS n,
                   -- the latest change, in the same unit the moments were built from
                   (ARRAY_AGG(v ORDER BY date DESC))[1] AS latest_v
            FROM e GROUP BY symbol
        """, syms + pct_syms + pct_syms).fetchdf().set_index("symbol")
    finally:
        con.close()

    rows = []
    for sym, m in meta.items():
        g = obs[obs["symbol"] == sym]
        latest = g.iloc[-1] if not g.empty else None
        prior = g.iloc[-2]["close"] if len(g) >= 2 else float("nan")
        value = float(latest["close"]) if latest is not None else float("nan")

        # z of the latest CHANGE vs the series' own full-history change distribution.
        # `latest_v` comes from the same SQL that built mu/sd, so it is guaranteed to
        # be in the same unit (pct vs absolute) as the moments — recomputing it here
        # would silently mix units for the pct series.
        z = float("nan")
        if sym in stats.index:
            mu, sd, n, latest_v = stats.loc[sym, ["mu", "sd", "n", "latest_v"]]
            # sd==0 (a series that never moves) or n<30 (too few points for a stable
            # sigma) -> no z rather than a fabricated one.
            if pd.notna(sd) and sd > 0 and n >= 30 and pd.notna(latest_v):
                z = (latest_v - mu) / sd

        rows.append({
            "symbol": sym,
            "name": m.get("name", sym),
            "group": m["group"],
            "freq": m.get("freq", ""),
            "unit": m.get("unit", ""),
            "revised": bool(m.get("revised", False)),
            "date": latest["date"] if latest is not None else None,
            "value": value,
            "prior": prior,
            # guard div-by-zero: spreads legitimately cross zero (T10Y2Y inverted 2022-23)
            "chg_pct": (value - prior) / abs(prior) * 100 if prior and pd.notna(prior) and prior != 0 else float("nan"),
            "z": z,
            "spark": g["close"].astype(float).tolist(),
            "n_obs": len(g),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=300)
def load_sector_breadth() -> pd.DataFrame:
    """Macro-page S2 heatmap snapshot — sector + subsector rows for the latest day.

    Reads `sector_breadth` (materialized nightly by sector_breadth_engine): one row
    per sector (grain='sector') and per subsector (grain='subsector', with a parent
    `sector`). Carries today's return quantiles (KDE shape), up/down breadth,
    trend/breakout participation + names added today/5d. Page filters by grain.
    """
    con = _connect()
    try:
        return con.execute("SELECT * FROM sector_breadth").fetchdf()
    finally:
        con.close()


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
    con = _connect()
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
def load_ticker_history(ticker: str, model_version_id: str | None = None) -> pd.DataFrame:
    """Every screener_watchlist session for one ticker (all entry→exit cycles).

    When `model_version_id` is given, each session carries the prod-model
    P(Home Run) score (`prob_class_3`) as of the day the signal fired — the latest
    prediction (any cohort) at/before entry_date. Sessions predating the d3 window
    have a NULL score. Closed sessions are historical, so we always anchor on
    entry_date here (no ACTIVE "current" carve-out — that lives in the watchlist
    table).
    """
    con = _connect()
    try:
        if model_version_id is None:
            return con.execute("""
                SELECT ticker, company_name, sector,
                       entry_date, entry_price, exit_date, status,
                       close_price, pct_return, days_held
                FROM screener_watchlist
                WHERE ticker = ?
                ORDER BY entry_date
            """, [ticker.strip().upper()]).fetchdf()
        return con.execute("""
            WITH preds AS (
                SELECT prediction_date, prob_class_3
                FROM daily_predictions
                WHERE model_version_id = ? AND ticker = ?
            ),
            scored AS (
                SELECT sw.ticker, sw.company_name, sw.sector,
                       sw.entry_date, sw.entry_price, sw.exit_date, sw.status,
                       sw.close_price, sw.pct_return, sw.days_held,
                       p.prob_class_3 AS entry_score,
                       ROW_NUMBER() OVER (
                           PARTITION BY sw.entry_date
                           ORDER BY p.prediction_date DESC
                       ) AS rn
                FROM screener_watchlist sw
                LEFT JOIN preds p ON p.prediction_date <= sw.entry_date
                WHERE sw.ticker = ?
            )
            SELECT ticker, company_name, sector,
                   entry_date, entry_price, exit_date, status,
                   close_price, pct_return, days_held, entry_score
            FROM scored
            WHERE rn = 1
            ORDER BY entry_date
        """, [model_version_id, ticker.strip().upper(),
              ticker.strip().upper()]).fetchdf()
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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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
    con = _connect()
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


# Score-column map for the rank bump chart. `rank_within_day` is the canonical
# rank (1 = best P(Home Run)) for any model, but the underlying probability lives
# in a different column per architecture: the 4-class prototype reads P(Home Run)
# off prob_class_3, the binary model off prob_class_1. We surface that probability
# as the hover value only — never as the rank source — so the chart works
# unchanged when the binary model is promoted. Default tolerates either.
RANK_METRIC_COLUMNS: dict[str, str] = {
    "prob_class_3": "prob_class_3",   # 4-class prototype P(Home Run)
    "prob_class_1": "prob_class_1",   # binary P(Home Run)
}


@st.cache_data(ttl=300)
def load_rank_history(
    model_version_id: str,
    top_n: int = 10,
    start=None,
    end=None,
    metric: str = "prob_class_3",
    cohort: str = "breakout",
) -> pd.DataFrame:
    """Per-day top-N rank trajectory for the bump chart (read-only).

    Pulls every (date, ticker) whose `rank_within_day` <= `top_n` within
    [start, end] for one model + cohort. Membership is per-day: a ticker appears
    on a given date only if it cleared top-N that day, so the set changes over
    time. `score` carries the model's P(Home Run) (column chosen by `metric`) for
    hover; rank itself always comes from the materialized `rank_within_day`.

    `start`/`end` are date-like (or None → unbounded). Returns columns:
    prediction_date, ticker, rank_within_day, score. Empty df if nothing matches.
    """
    score_col = RANK_METRIC_COLUMNS.get(metric)
    if score_col is None:
        raise ValueError(
            f"metric must be one of {sorted(RANK_METRIC_COLUMNS)}, got {metric!r}"
        )

    where = ["model_version_id = ?", "cohort = ?",
             "rank_within_day IS NOT NULL", "rank_within_day <= ?"]
    params: list = [model_version_id, cohort, int(top_n)]
    if start is not None:
        where.append("prediction_date >= ?")
        params.append(start)
    if end is not None:
        where.append("prediction_date <= ?")
        params.append(end)

    con = _connect()
    try:
        return con.execute(f"""
            SELECT prediction_date, ticker, rank_within_day,
                   {score_col} AS score
            FROM daily_predictions
            WHERE {' AND '.join(where)}
            ORDER BY prediction_date, rank_within_day
        """, params).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_rank_history_bounds(model_version_id: str, cohort: str | None = None) -> tuple:
    """(min_date, max_date) of daily_predictions for a model, optionally scoped to
    one cohort. (None, None) when nothing is logged."""
    where = ["model_version_id = ?"]
    params: list = [model_version_id]
    if cohort is not None:
        where.append("cohort = ?")
        params.append(cohort)
    con = _connect()
    try:
        row = con.execute(f"""
            SELECT MIN(prediction_date), MAX(prediction_date)
            FROM daily_predictions
            WHERE {' AND '.join(where)}
        """, params).fetchone()
        return (row[0], row[1]) if row else (None, None)
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_rank_cohorts(model_version_id: str) -> list[str]:
    """Cohorts that actually have predictions for this model (e.g. binary has only
    'breakout' until it's scored on the pre_breakout universe). Ordered."""
    con = _connect()
    try:
        rows = con.execute("""
            SELECT DISTINCT cohort FROM daily_predictions
            WHERE model_version_id = ? AND cohort IS NOT NULL
            ORDER BY cohort
        """, [model_version_id]).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_cohort_return_panel(
    model_version_id: str,
    cohort: str = "breakout",
    min_score: float = 0.0,
    mode: str = "to_today",
    horizon: int = 20,
) -> pd.DataFrame:
    """Realized-return distribution per signal day, for the watchlist-health plot.

    For each prediction_date D (the "x days before today" axis), takes the tickers
    scored that day in `daily_predictions` for `model_version_id`/`cohort` with
    `prob_class_3 >= min_score`, and computes each name's realized return from its
    close on D. Membership is genuinely per-day — a name counts on D only if it was
    scored (and cleared the threshold) that day.

    `mode`:
      - "to_today": return from D's close to the latest available close (horizon
        grows for older days — answers "how has the recent watchlist done since").
      - "forward": N-day forward return (close on D → close ~`horizon` trading days
        later). Fixed horizon, but the last ~`horizon` days have no complete future
        and drop out.

    Bounded by the slim DB's price window: signal days whose close (or forward
    close) falls outside `price_data` yield no rows and are absent from the panel.
    The caller reads the returned `days_before_today` span to caption the real range.

    Returns tidy per-(day, ticker) rows: prediction_date, days_before_today, ticker,
    prob_class_3, ret_pct. Empty df when nothing matches. Aggregation (median/mean/
    quantiles/count) is left to the caller — cheaper in pandas at this row count.
    """
    if mode not in ("to_today", "forward"):
        raise ValueError(f"mode must be 'to_today' | 'forward', got {mode!r}")

    con = _connect()
    try:
        # Entry close = first bar on/after D. Exit close = latest bar (to_today) or
        # first bar on/after D + horizon calendar days (forward). Calendar-day math
        # over-reaches vs trading days, but "first bar on/after" snaps to the next
        # real bar, so ~horizon*(7/5) days lands close enough for a distribution view.
        if mode == "to_today":
            exit_join = """
                LEFT JOIN LATERAL (
                    SELECT close FROM price_data px
                    WHERE px.ticker = s.ticker
                    ORDER BY px.date DESC LIMIT 1
                ) pe ON TRUE
            """
        else:
            exit_join = f"""
                LEFT JOIN LATERAL (
                    SELECT close FROM price_data px
                    WHERE px.ticker = s.ticker
                      AND px.date >= s.prediction_date + INTERVAL {int(horizon)} DAY
                    ORDER BY px.date ASC LIMIT 1
                ) pe ON TRUE
            """
        df = con.execute(f"""
            WITH sig AS (
                SELECT prediction_date, ticker, prob_class_3
                FROM daily_predictions
                WHERE model_version_id = ? AND cohort = ?
                  AND prob_class_3 >= ?
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY ticker, prediction_date ORDER BY rank_within_day
                ) = 1
            ),
            s AS (SELECT * FROM sig)
            SELECT
                s.prediction_date,
                s.ticker,
                s.prob_class_3,
                p0.close AS entry_close,
                pe.close AS exit_close
            FROM s
            LEFT JOIN LATERAL (
                SELECT close FROM price_data px
                WHERE px.ticker = s.ticker AND px.date >= s.prediction_date
                ORDER BY px.date ASC LIMIT 1
            ) p0 ON TRUE
            {exit_join}
        """, [model_version_id, cohort, float(min_score)]).fetchdf()
    finally:
        con.close()

    if df.empty:
        return df
    df = df.dropna(subset=["entry_close", "exit_close"])
    df = df[df["entry_close"] > 0]
    if df.empty:
        return df
    df["ret_pct"] = (df["exit_close"] / df["entry_close"] - 1.0) * 100.0
    max_d = df["prediction_date"].max()
    df["days_before_today"] = (max_d - df["prediction_date"]).dt.days
    return df[["prediction_date", "days_before_today", "ticker",
               "prob_class_3", "ret_pct"]].reset_index(drop=True)


@st.cache_data(ttl=60)
def load_past_decisions(model_version_id: str, limit: int = 200) -> pd.DataFrame:
    """Past decisions joined against screener_watchlist for realized outcomes.

    Used by the "Performance of past decisions" view on Page 1. Only rows where
    the user has actually toggled `decision_taken` (NULL rows are excluded).
    """
    con = _connect()
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
    con = _connect()
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
