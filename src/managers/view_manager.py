import logging
import time
from pathlib import Path
from typing import Dict, Optional

import duckdb
from src import db
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/market_data.duckdb")

# DuckDB stores all column names as lowercase.
# M01_FEATURES references TitleCase names from the legacy parquet pipeline.
# This map bridges the two; apply via df.rename(columns=COLUMN_CASE_MAP).
COLUMN_CASE_MAP: Dict[str, str] = {
    "rsi_14": "RSI_14",
    "vcp_ratio": "VCP_Ratio",
    "is_green_day": "Is_Green_Day",
    "price_vs_sma_50_delta": "Price_vs_SMA_50_Delta",
    "price_vs_sma_150_delta": "Price_vs_SMA_150_Delta",
    "dist_from_20d_high_delta": "Dist_From_20D_High_Delta",
    "dist_from_52w_high_delta": "Dist_From_52W_High_Delta",

    # Raw OHLCV (PascalCase in exclusion list)
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume": "Volume",

    # Outcomes / Leakage (Excluded via LEAKAGE_FEATURES)
    "mae_pct": "MAE",
    "mfe_pct": "MFE",

    # Technicals (map view names to feature_config names)
    "sma_50": "SMA_50",
    "sma_150": "SMA_150",
    "sma_200": "SMA_200",
    "atr_20d": "ATR",
    "vol_avg_20": "Vol_MA",
    "high_52w": "High_52W",
    "low_52w": "Low_52W",
    "dist_from_52w_high": "Dist_From_52W_High",
    "dist_from_52w_low": "Dist_From_52W_Low",
    "dist_from_20d_low": "Dist_From_20D_Low",
    "dist_from_20d_high": "Dist_From_20D_High",
    "dry_up_volume": "Dry_Up_Volume",
}


class ViewManager:
    """Creates and manages DuckDB virtual views for the SEPA ML pipeline.

    Views (Phase 5.1 - Updated to use t3_sepa_features):
        v_sepa_candidates      — Trend template (C1-C9) + metadata
        v_d1_candidates        — Full SEPA signal (C1-C11) with lags/deltas
        v_d2_features          — D1 + fundamentals (point-in-time)
        v_d2_hydrated          — D1 trades hydrated to SEPA exit
        v_d2_training          — D2 features + outcomes + log transforms
        v_d3_deployment        — Last 252 days of SEPA candidates for scoring
        v_screener_dashboard   — SEPA screener tracker (entry date, return, company info)
    """

    def __init__(self, db_path: Optional[str] = None, feature_version: str = 'v3.1'):
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        self.feature_version = feature_version

    def create_all(self) -> int:
        print(f"[ViewManager] Creating views (feature_version={self.feature_version})...")
        views = [
            self._create_models_table,
            self._create_v_price_combined,
            self._create_v_shares_combined,
            self._create_v_sepa_candidates,
            self._create_v_d1_candidates,
            self._create_v_d2_features,
            self._create_v_d2_hydrated,
            self._create_v_d2_training,
            self._create_v_d3_deployment,
            self._create_v_d3_prebreakout,
            self._create_v_screener_dashboard,
            self._refresh_screener_watchlist,
            self._create_v_d3_lifecycle,  # after watchlist table — it joins it
            self._create_v_d3_shortlist,  # after lifecycle — it builds on it
        ]
        # NOTE: t3_training_cache (v_t3_training materialization) is NOT in this list.
        # Its ASOF joins cost ~215s and its inputs (fundamentals/shares) change weekly at
        # most, so it is refreshed on a weekly cadence via refresh_t3_training_cache(),
        # not on every create_all() run. See docs/.../v2_regression_model_design.md.
        con = db.connect(self.db_path)
        try:
            # Retired views: CREATE OR REPLACE never drops what it stops creating,
            # so explicitly remove the deprecated v_d1_trades alias and the
            # v_d2r_hydrated back-compat alias on each run.
            con.execute("DROP VIEW IF EXISTS v_d1_trades")
            con.execute("DROP VIEW IF EXISTS v_d2r_hydrated")
            for fn in views:
                fn(con)
            print("[OK] All views created successfully")
            return len(views)
        except Exception as e:
            logger.error(f"View creation failed: {e}")
            print(f"[ERROR] View creation failed: {e}")
            raise
        finally:
            con.close()

    # ------------------------------------------------------------------
    # MODEL REGISTRY TABLE: MLOps metadata and versioning
    # ------------------------------------------------------------------

    @staticmethod
    def _create_models_table(con: duckdb.DuckDBPyConnection) -> None:
        con.execute("""
            CREATE TABLE IF NOT EXISTS models (
                version_id VARCHAR PRIMARY KEY,
                status_flag VARCHAR CHECK (status_flag IN ('prod', 'test', 'archived')),
                specs_json JSON,
                feature_version VARCHAR,
                training_date DATE,
                dataset_rows BIGINT,
                rmse DOUBLE,
                mae DOUBLE,
                r2 DOUBLE,
                spearman_corr DOUBLE,
                artifacts_path VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        count = con.execute("SELECT COUNT(*) FROM models").fetchone()[0]
        print(f"   [OK] models table: {count} versions registered")

    # ------------------------------------------------------------------
    # COMBINED VIEWS: UNION ALL of production + backfill tables
    # ------------------------------------------------------------------

    @staticmethod
    def _create_v_price_combined(con: duckdb.DuckDBPyConnection) -> None:
        has_backfill = con.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = 'price_data_backfill'
        """).fetchone()[0] > 0

        if not has_backfill:
            con.execute("""
                CREATE OR REPLACE VIEW v_price_combined AS
                SELECT ticker, date, open, high, low, close, volume
                FROM price_data
            """)
            print("   [OK] v_price_combined: production only (no backfill table)")
        else:
            con.execute("""
                CREATE OR REPLACE VIEW v_price_combined AS
                SELECT ticker, date, open, high, low, close, volume
                FROM price_data
                UNION ALL
                SELECT b.ticker, b.date, b.open, b.high, b.low, b.close, b.volume
                FROM price_data_backfill b
                LEFT JOIN price_data p ON b.ticker = p.ticker AND b.date = p.date
                WHERE p.ticker IS NULL
            """)
            print("   [OK] v_price_combined: production + backfill (anti-join)")

    @staticmethod
    def _create_v_shares_combined(con: duckdb.DuckDBPyConnection) -> None:
        has_shares = con.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = 'shares_history'
        """).fetchone()[0] > 0
        has_backfill = con.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = 'shares_backfill'
        """).fetchone()[0] > 0

        if not has_shares:
            con.execute("CREATE OR REPLACE VIEW v_shares_combined AS SELECT NULL::VARCHAR AS ticker, NULL::DATE AS date, NULL::BIGINT AS shares_outstanding WHERE FALSE")
            print("   [OK] v_shares_combined: empty (no shares tables)")
        elif not has_backfill:
            con.execute("""
                CREATE OR REPLACE VIEW v_shares_combined AS
                SELECT ticker, date, shares_outstanding
                FROM shares_history
            """)
            print("   [OK] v_shares_combined: production only (no backfill table)")
        else:
            con.execute("""
                CREATE OR REPLACE VIEW v_shares_combined AS
                SELECT ticker, date, shares_outstanding
                FROM shares_history
                UNION ALL
                SELECT b.ticker, b.date, b.shares_outstanding
                FROM shares_backfill b
                LEFT JOIN shares_history h ON b.ticker = h.ticker AND b.date = h.date
                WHERE h.ticker IS NULL
            """)
            print("   [OK] v_shares_combined: production + backfill (anti-join)")

    # ------------------------------------------------------------------
    # VIEW 1: v_sepa_candidates — Trend Template (C1-C9)
    # ------------------------------------------------------------------

    def _create_v_sepa_candidates(self, con: duckdb.DuckDBPyConnection) -> None:
        """Queries t3_sepa_features for SEPA breakout candidates."""
        con.execute(f"""
            CREATE OR REPLACE VIEW v_sepa_candidates AS
            SELECT
                f.date,
                f.ticker,
                f.close,
                f.sma_50,
                f.sma_150,
                f.sma_200,
                f.sma_200_lag20,
                f.high_52w,
                f.low_52w,
                f.pct_from_high_52w,
                f.vol_avg_20,
                f.vol_avg_50,
                f.vol_ratio,
                f.natr,
                f.atr_20d,
                f.volatility_20d,
                f.adr_20d,
                f.rs_rating,
                f.rs,
                f.rs_ma,
                f.price_vs_spy,
                f.price_vs_spy_ma63,
                f.rs_line_uptrend,
                f.rs_line_log,
                f.rs_line_delta,
                f.breakout,
                f.return_20d,
                f.rsi_14,
                f.sma_50_slope,
                c.sector,
                c.industry
            FROM t3_sepa_features f
            INNER JOIN company_profiles c
                ON f.ticker = c.ticker
            WHERE c.is_active = TRUE
              AND f.feature_version = '{self.feature_version}'
              AND f.trend_ok = TRUE
              AND f.breakout_ok = TRUE
        """)
        n = con.execute(
            f"SELECT COUNT(*) FROM v_sepa_candidates "
            f"WHERE date = (SELECT MAX(date) FROM t3_sepa_features WHERE feature_version = '{self.feature_version}')"
        ).fetchone()[0]
        print(f"   [OK] v_sepa_candidates: C1-C9 trend template ({n} on latest date, version={self.feature_version})")

    # ------------------------------------------------------------------
    # VIEW 2: v_d1_candidates — Full SEPA Signal (C1-C11) + Lags/Deltas
    # ------------------------------------------------------------------

    def _create_v_d1_candidates(self, con: duckdb.DuckDBPyConnection) -> None:
        """Phase 5.1: Updated to query t3_sepa_features with feature_version filter."""
        con.execute(f"""
            CREATE OR REPLACE VIEW v_d1_candidates AS
            -- Step 0: Compute exit trend (C1+C2+C6 only) for session boundaries.
            --         C1: close > SMA150, C2: close > SMA200, C6: close > SMA50.
            --         C3-C5/C7/C8 lag price by weeks/months — not useful for timely exits.
            --         C9 RS line excluded (entry filter only, not Minervini exit criteria).
            --         Entry still requires full trend_ok (C1-C9) + breakout_ok.
            WITH trend_c8_base AS (
                SELECT
                    t2.ticker,
                    t2.date,
                    t2.trend_ok,
                    t2.breakout_ok,
                    COALESCE(
                        t2.close > t2.sma_150
                        AND t2.close > t2.sma_200
                        AND t2.close > t2.sma_50,
                        FALSE
                    ) AS trend_c8
                FROM t2_screener_features t2
                INNER JOIN company_profiles c ON t2.ticker = c.ticker
                WHERE c.is_active = TRUE
            ),
            -- Step 1: Detect session starts (C1+C2+C6 transitions from FALSE to TRUE)
            trend_sessions AS (
                SELECT
                    *,
                    CASE WHEN trend_c8 AND NOT COALESCE(
                        LAG(trend_c8) OVER (PARTITION BY ticker ORDER BY date),
                        FALSE
                    ) THEN 1 ELSE 0 END AS trend_session_start
                FROM trend_c8_base
            ),
            -- Step 2: Assign monotonic session_id per ticker (sessions defined by C1+C2+C6)
            sessions AS (
                SELECT
                    ticker, date, trend_ok, breakout_ok, trend_c8,
                    SUM(trend_session_start) OVER (
                        PARTITION BY ticker ORDER BY date
                    ) AS session_id
                FROM trend_sessions
                WHERE trend_c8
            ),
            -- Step 3: Find entry date = first day with FULL trend_ok (C1-C9) + breakout_ok per session
            entries AS (
                SELECT ticker, session_id, MIN(date) AS entry_date
                FROM sessions
                WHERE trend_ok AND breakout_ok
                GROUP BY ticker, session_id
            ),
            -- Step 4: Keep only entry_date row (one row per trade)
            candidates AS (
                SELECT
                    s.ticker,
                    s.date,
                    s.session_id,
                    e.entry_date,
                    printf('%s_%s', s.ticker, strftime(e.entry_date, '%Y%m%d')) AS trade_id,
                    1 AS is_new_trigger
                FROM sessions s
                INNER JOIN entries e
                    ON s.ticker = e.ticker
                    AND s.session_id = e.session_id
                WHERE s.date = e.entry_date
            ),
            -- Step 5: Exit = first trading day AFTER C1-C8 trend breaks (no lookahead bias).
            --         Precompute LEAD(date)/LEAD(close) per ticker in price_data (O(n), not O(n²)).
            session_bounds AS (
                SELECT ticker, session_id, MAX(date) AS last_trend_date
                FROM sessions
                GROUP BY ticker, session_id
            ),
            price_with_next AS (
                SELECT
                    ticker, date, close,
                    LEAD(date)  OVER (PARTITION BY ticker ORDER BY date) AS next_date,
                    LEAD(close) OVER (PARTITION BY ticker ORDER BY date) AS next_close
                FROM price_data
            ),
            trade_prices AS (
                SELECT
                    c.ticker,
                    c.trade_id,
                    c.entry_date,
                    sb.last_trend_date,
                    pe.close  AS entry_price,
                    COALESCE(px.next_date,  sb.last_trend_date) AS exit_date,
                    COALESCE(px.next_close, px.close)           AS exit_price
                FROM candidates c
                INNER JOIN session_bounds sb
                    ON c.ticker = sb.ticker AND c.session_id = sb.session_id
                LEFT JOIN price_with_next pe
                    ON c.ticker = pe.ticker AND c.entry_date = pe.date
                LEFT JOIN price_with_next px
                    ON sb.ticker = px.ticker AND sb.last_trend_date = px.date
            ),
            -- Step 6: Enrich with full features + lags computed across ALL days
            enriched AS (
                -- v3.1+: pre-computed pct_chg features from t3_sepa_features (no lags needed).
                -- LEFT JOIN (not INNER) to t3: T3 is lazily materialized and can have
                -- transient (ticker,date) holes (e.g. a late sepa_watchlist admission).
                -- An INNER JOIN silently DELETES the whole trade on a missing entry row;
                -- LEFT keeps the trade with NULL features so it stays visible/scoreable.
                -- ticker/date come from `cand` (always present) — EXCLUDE the t3 copies
                -- so they don't surface as NULL when f is unmatched.
                SELECT
                    cand.ticker,
                    cand.date,
                    f.* EXCLUDE (ticker, date),
                    c.sector,
                    c.industry,
                    cand.trade_id,
                    cand.is_new_trigger,
                    cand.entry_date,
                    tp.exit_date,
                    tp.entry_price,
                    tp.exit_price,
                    CASE WHEN tp.entry_price > 0
                        THEN ((tp.exit_price / tp.entry_price) - 1.0) * 100.0
                    END AS return_pct
                FROM candidates cand
                LEFT JOIN t3_sepa_features f
                    ON cand.ticker = f.ticker
                    AND cand.date = f.date
                    AND f.feature_version = '{self.feature_version}'
                INNER JOIN company_profiles c ON cand.ticker = c.ticker
                INNER JOIN trade_prices tp ON cand.trade_id = tp.trade_id
            )
            SELECT
                e.* EXCLUDE (
                    natr_pct_chg, atr_pct_chg, vcp_ratio_pct_chg, consolidation_width_pct_chg,
                    price_vs_sma_50_pct_chg, price_vs_sma_150_pct_chg, price_vs_sma_200_pct_chg,
                    rs_pct_chg, rs_ma_pct_chg, dry_up_volume_pct_chg,
                    high_52w_pct_chg, low_52w_pct_chg, lowest_low_20d_pct_chg, highest_high_20d_pct_chg,
                    rsi_14_pct_chg, dist_from_52w_high_pct_chg, dist_from_52w_low_pct_chg,
                    dist_from_20d_low_pct_chg, dist_from_20d_high_pct_chg
                ),
                -- v3.1: Delta features from pre-computed pct_chg columns (convert % to ratio)
                -- NOTE: pct_chg is in percentage (0-100 scale), delta is ratio (0-1 scale)
                e.natr_pct_chg / 100.0 AS natr_delta,
                e.vcp_ratio_pct_chg / 100.0 AS vcp_ratio_delta,
                e.consolidation_width_pct_chg / 100.0 AS consolidation_width_delta,
                e.price_vs_sma_50_pct_chg / 100.0 AS price_vs_sma_50_delta,
                e.price_vs_sma_150_pct_chg / 100.0 AS price_vs_sma_150_delta,
                e.price_vs_sma_200_pct_chg / 100.0 AS price_vs_sma_200_delta,
                e.rs_pct_chg / 100.0 AS rs_delta,
                e.rs_ma_pct_chg / 100.0 AS rs_ma_delta,
                e.dry_up_volume_pct_chg / 100.0 AS dry_up_volume_delta,
                e.high_52w_pct_chg / 100.0 AS high_52w_delta,
                e.low_52w_pct_chg / 100.0 AS low_52w_delta,
                e.lowest_low_20d_pct_chg / 100.0 AS lowest_low_20d_delta,
                e.highest_high_20d_pct_chg / 100.0 AS highest_high_20d_delta,
                e.rsi_14_pct_chg / 100.0 AS rsi_14_delta,
                e.dist_from_52w_high_pct_chg / 100.0 AS dist_from_52w_high_delta,
                e.dist_from_52w_low_pct_chg / 100.0 AS dist_from_52w_low_delta,
                e.dist_from_20d_low_pct_chg / 100.0 AS dist_from_20d_low_delta,
                e.dist_from_20d_high_pct_chg / 100.0 AS dist_from_20d_high_delta
            FROM enriched e
        """)
        n = con.execute(
            f"SELECT COUNT(*) FROM v_d1_candidates "
            f"WHERE date = (SELECT MAX(date) FROM t3_sepa_features WHERE feature_version = '{self.feature_version}')"
        ).fetchone()[0]
        print(f"   [OK] v_d1_candidates: session-based C1-C11 + lags/deltas ({n} on latest date)")

    # ------------------------------------------------------------------
    # VIEW 3: v_d2_features — D1 + Fundamentals (Point-in-Time)
    # ------------------------------------------------------------------

    @staticmethod
    def _create_v_d2_features(con: duckdb.DuckDBPyConnection) -> None:
        # Check if shares_history table exists
        has_shares = con.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = 'shares_history'
        """).fetchone()[0] > 0

        if has_shares:
            shares_col = "sh.shares_outstanding"
            shares_join = """
            LEFT JOIN shares_history sh
                ON d1.ticker = sh.ticker
                AND sh.date = (
                    SELECT MAX(date)
                    FROM shares_history
                    WHERE ticker = d1.ticker
                    AND date <= d1.date
                )"""
        else:
            shares_col = "cp.shares_outstanding"
            shares_join = ""

        # ff_dedup collapses same-day amended filings via fiscal_period tiebreaker
        # (e.g. UNH 2007-03-06 had Q2/Q3/Q4 stamped on the same filing_date).
        # Without it, the as-of join fans out one d1 row into N rows downstream.
        con.execute(f"""
            CREATE OR REPLACE VIEW v_d2_features AS
            WITH ff_dedup AS (
                SELECT
                    ticker, filing_date, fiscal_period,
                    revenue, net_income, eps_diluted, total_assets, total_equity,
                    revenue_growth_yoy, eps_growth_yoy, net_income_growth_yoy,
                    eps_accel, revenue_accel, revenue_cagr_3y, eps_stability_score,
                    debt_to_equity, current_ratio, quick_ratio,
                    gross_margin, operating_margin, net_margin, roe, roa, fcf_margin,
                    earnings_quality_score, inventory_growth_yoy,
                    inventory_vs_sales_spread, gross_margin_trend
                FROM fundamental_features
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY ticker, filing_date
                    ORDER BY fiscal_period DESC NULLS LAST
                ) = 1
            )
            SELECT
                d1.*,
                ff.revenue,
                ff.net_income,
                ff.eps_diluted,
                ff.total_assets,
                ff.total_equity,
                ff.revenue_growth_yoy,
                ff.eps_growth_yoy,
                ff.net_income_growth_yoy,
                ff.eps_accel,
                ff.revenue_accel,
                ff.revenue_cagr_3y,
                ff.eps_stability_score,
                ff.debt_to_equity,
                ff.current_ratio,
                ff.quick_ratio,
                ff.gross_margin,
                ff.operating_margin,
                ff.net_margin,
                ff.roe,
                ff.roa,
                ff.fcf_margin,
                ff.earnings_quality_score,
                ff.inventory_growth_yoy,
                ff.inventory_vs_sales_spread,
                ff.gross_margin_trend,
                ff.filing_date AS fundamental_filing_date,
                ff.fiscal_period,
                CAST(datediff('day', ff.filing_date, d1.date) AS INTEGER) AS days_since_report,
                cp.market_cap,
                {shares_col} AS shares_outstanding,
                CASE WHEN ABS(ff.eps_diluted) > 0.01
                    THEN d1.close / ff.eps_diluted END AS pe_ratio,
                CASE WHEN ff.revenue > 0 AND {shares_col} > 0
                    THEN (d1.close * {shares_col}) / ff.revenue END AS ps_ratio,
                CASE WHEN ff.total_equity > 0 AND {shares_col} > 0
                    THEN (d1.close * {shares_col}) / ff.total_equity END AS pb_ratio,
                CASE WHEN ff.eps_growth_yoy > 0 AND ABS(ff.eps_diluted) > 0.01
                    THEN (d1.close / ff.eps_diluted) / ff.eps_growth_yoy END AS peg_adjusted
            FROM v_d1_candidates d1
            LEFT JOIN company_profiles cp
                ON d1.ticker = cp.ticker
            {shares_join}
            LEFT JOIN ff_dedup ff
                ON d1.ticker = ff.ticker
                AND ff.filing_date = (
                    SELECT MAX(filing_date)
                    FROM ff_dedup
                    WHERE ticker = d1.ticker
                    AND filing_date <= d1.date
                )
        """)
        n = con.execute(
            "SELECT COUNT(*) FROM v_d2_features "
            "WHERE date = (SELECT MAX(date) FROM t3_sepa_features)"
        ).fetchone()[0]
        print(f"   [OK] v_d2_features: D1 + fundamentals ({n} on latest date)")

    # ------------------------------------------------------------------
    # VIEW 4: v_d2_hydrated — SEPA-Bounded Trade Hydration
    # (Phase 5.1: Renamed from v_d2r_hydrated for naming consistency)
    # ------------------------------------------------------------------

    def _create_v_d2_hydrated(self, con: duckdb.DuckDBPyConnection) -> None:
        """Phase 5.1: Updated to query t3_sepa_features, renamed from v_d2r_hydrated."""
        con.execute(f"""
            CREATE OR REPLACE VIEW v_d2_hydrated AS
            WITH trades AS (
                SELECT DISTINCT
                    trade_id,
                    ticker,
                    entry_date,
                    entry_price,
                    COALESCE(exit_date, entry_date + INTERVAL 120 DAY) AS effective_exit_date
                FROM v_d1_candidates
            ),
            hydrated AS (
                SELECT
                    t.trade_id,
                    t.ticker,
                    t.entry_date,
                    t.entry_price,
                    t.effective_exit_date AS sepa_exit_date,
                    p.date,
                    CAST(datediff('day', t.entry_date, p.date) AS INTEGER) AS days_in_trade,
                    p.open, p.high, p.low, p.close, p.volume,
                    df.sma_50,
                    df.atr_20d,
                    -- Stop-loss level: worse of -15% and -2×ATR (adaptive per day)
                    t.entry_price * (1.0 + LEAST(-0.15, -2.0 * COALESCE(df.atr_20d, 0) / NULLIF(t.entry_price, 0))) AS sl_level
                FROM trades t
                INNER JOIN price_data p
                    ON t.ticker = p.ticker
                    AND p.date >= t.entry_date
                    AND p.date <= t.effective_exit_date
                LEFT JOIN t3_sepa_features df
                    ON t.ticker = df.ticker
                    AND p.date = df.date
                    AND df.feature_version = '{self.feature_version}'
            )
            SELECT
                h.*,
                h.close < h.sl_level AS sl_hit
            FROM hydrated h
        """)
        print(f"   [OK] v_d2_hydrated: SEPA-bounded hydration with SMA/ATR/stop-loss")

    # ------------------------------------------------------------------
    # VIEW 5: v_d2_training — D2 Features + Outcomes + Log Transforms
    # ------------------------------------------------------------------

    @staticmethod
    def _create_v_d2_training(con: duckdb.DuckDBPyConnection) -> None:
        con.execute("""
            CREATE OR REPLACE VIEW v_d2_training AS
            WITH outcomes AS (
                SELECT
                    trade_id,
                    -- Exclude entry day (days_in_trade=0): intraday low/high occur before we enter at close
                    (MIN(CASE WHEN days_in_trade > 0 THEN low END) / FIRST(close ORDER BY date) - 1.0) * 100.0 AS mae_pct,
                    (MAX(high) / FIRST(close ORDER BY date) - 1.0) * 100.0 AS mfe_pct,
                    (LAST(close ORDER BY date) / FIRST(close ORDER BY date) - 1.0) * 100.0 AS return_at_exit,
                    -- MAE/MFE dates: when the extremes occurred
                    ARG_MIN(CASE WHEN days_in_trade > 0 THEN date END, CASE WHEN days_in_trade > 0 THEN low END) AS mae_date,
                    ARG_MAX(date, high) AS mfe_date,
                    MAX(sepa_exit_date) AS sepa_exit_date,
                    MAX(days_in_trade) AS holding_days,
                    COUNT(*) AS days_observed
                FROM v_d2_hydrated
                GROUP BY trade_id
            ),
            -- Stop-loss: first day close breached the adaptive SL level
            sl_events AS (
                SELECT
                    h.trade_id,
                    h.ticker,
                    h.entry_price,
                    MIN(h.date) AS sl_date
                FROM v_d2_hydrated h
                WHERE h.sl_hit
                  AND h.days_in_trade > 0  -- skip entry day itself
                GROUP BY h.trade_id, h.ticker, h.entry_price
            ),
            -- Precompute next trading day per ticker (one O(n) pass, replaces two correlated subqueries per trade)
            price_with_next AS (
                SELECT
                    ticker, date,
                    LEAD(date)  OVER (PARTITION BY ticker ORDER BY date) AS next_date,
                    LEAD(close) OVER (PARTITION BY ticker ORDER BY date) AS next_close
                FROM price_data
            ),
            sl_exits AS (
                SELECT
                    s.trade_id,
                    s.sl_date,
                    s.entry_price,
                    px.next_date  AS sl_exit_date,
                    px.next_close AS sl_exit_price
                FROM sl_events s
                LEFT JOIN price_with_next px
                    ON s.ticker = px.ticker AND s.sl_date = px.date
            )
            SELECT
                f.*,
                -- Outcome labels
                o.mae_pct,
                o.mfe_pct,
                o.return_at_exit,
                o.mae_date,
                o.mfe_date,
                o.sepa_exit_date,
                o.holding_days,
                o.days_observed,
                -- Stop-loss outcomes
                sl.sl_date IS NOT NULL AS sl_triggered,
                sl.sl_date,
                sl.sl_exit_date,
                CASE WHEN sl.sl_exit_price IS NOT NULL AND sl.entry_price > 0
                    THEN (sl.sl_exit_price / sl.entry_price - 1.0) * 100.0
                END AS sl_pct

            FROM v_d2_features f
            LEFT JOIN outcomes o ON f.trade_id = o.trade_id
            LEFT JOIN sl_exits sl ON f.trade_id = sl.trade_id
        """)
        print("   [OK] v_d2_training: features + outcomes (deferred — query to check row count)")

    # ------------------------------------------------------------------
    # VIEW 7: v_d3_deployment — Last 252 Days for Model Scoring
    # ------------------------------------------------------------------

    def _create_v_d3_deployment(self, con: duckdb.DuckDBPyConnection) -> None:
        """Phase 5.2: Deployment view for M01 scoring (last 252 trading days)."""
        con.execute(f"""
            CREATE OR REPLACE VIEW v_d3_deployment AS
            SELECT d2.*
            FROM v_d2_features d2
            WHERE d2.date >= (
                SELECT MAX(date) - INTERVAL '252 days'
                FROM t3_sepa_features
                WHERE feature_version = '{self.feature_version}'
            )
            ORDER BY d2.date DESC, d2.ticker
        """)
        print(f"   [OK] v_d3_deployment: Last 252 days (deferred — query to check row count)")

    # ------------------------------------------------------------------
    # VIEW 7b: v_d3_prebreakout — Pre-Breakout Cohort for Model Scoring
    # ------------------------------------------------------------------

    def _create_v_d3_prebreakout(self, con: duckdb.DuckDBPyConnection) -> None:
        """Deployment view for the PRE-BREAKOUT cohort (trend_ok & !breakout_ok).

        v_d3_deployment only carries SEPA *entries* (breakout_ok=TRUE), so it can't
        score in-setup names. This view hydrates the pre-breakout cohort with the
        SAME feature contract: t3_sepa_features base + delta renames (from the
        pre-computed pct_chg columns, exactly as v_d1_candidates) + the fundamentals
        as-of join + price-derived ratios (exactly as v_d2_features). Identical
        column set ⇒ the prod model scores both cohorts with one feature list.

        Windowed to the last 252 days for parity with v_d3_deployment.
        """
        has_shares = con.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = 'shares_history'
        """).fetchone()[0] > 0

        if has_shares:
            shares_col = "sh.shares_outstanding"
            shares_join = """
            LEFT JOIN shares_history sh
                ON base.ticker = sh.ticker
                AND sh.date = (
                    SELECT MAX(date) FROM shares_history
                    WHERE ticker = base.ticker AND date <= base.date
                )"""
        else:
            shares_col = "cp.shares_outstanding"
            shares_join = ""

        con.execute(f"""
            CREATE OR REPLACE VIEW v_d3_prebreakout AS
            WITH ff_dedup AS (
                SELECT
                    ticker, filing_date, fiscal_period,
                    revenue, net_income, eps_diluted, total_assets, total_equity,
                    revenue_growth_yoy, eps_growth_yoy, net_income_growth_yoy,
                    eps_accel, revenue_accel, revenue_cagr_3y, eps_stability_score,
                    debt_to_equity, current_ratio, quick_ratio,
                    gross_margin, operating_margin, net_margin, roe, roa, fcf_margin,
                    earnings_quality_score, inventory_growth_yoy,
                    inventory_vs_sales_spread, gross_margin_trend
                FROM fundamental_features
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY ticker, filing_date
                    ORDER BY fiscal_period DESC NULLS LAST
                ) = 1
            ),
            -- Base: pre-breakout rows + delta renames (mirrors v_d1_candidates tail).
            base AS (
                SELECT
                    f.* EXCLUDE (
                        natr_pct_chg, atr_pct_chg, vcp_ratio_pct_chg, consolidation_width_pct_chg,
                        price_vs_sma_50_pct_chg, price_vs_sma_150_pct_chg, price_vs_sma_200_pct_chg,
                        rs_pct_chg, rs_ma_pct_chg, dry_up_volume_pct_chg,
                        high_52w_pct_chg, low_52w_pct_chg, lowest_low_20d_pct_chg, highest_high_20d_pct_chg,
                        rsi_14_pct_chg, dist_from_52w_high_pct_chg, dist_from_52w_low_pct_chg,
                        dist_from_20d_low_pct_chg, dist_from_20d_high_pct_chg
                    ),
                    c.sector,
                    c.industry,
                    f.natr_pct_chg / 100.0 AS natr_delta,
                    f.vcp_ratio_pct_chg / 100.0 AS vcp_ratio_delta,
                    f.consolidation_width_pct_chg / 100.0 AS consolidation_width_delta,
                    f.price_vs_sma_50_pct_chg / 100.0 AS price_vs_sma_50_delta,
                    f.price_vs_sma_150_pct_chg / 100.0 AS price_vs_sma_150_delta,
                    f.price_vs_sma_200_pct_chg / 100.0 AS price_vs_sma_200_delta,
                    f.rs_pct_chg / 100.0 AS rs_delta,
                    f.rs_ma_pct_chg / 100.0 AS rs_ma_delta,
                    f.dry_up_volume_pct_chg / 100.0 AS dry_up_volume_delta,
                    f.high_52w_pct_chg / 100.0 AS high_52w_delta,
                    f.low_52w_pct_chg / 100.0 AS low_52w_delta,
                    f.lowest_low_20d_pct_chg / 100.0 AS lowest_low_20d_delta,
                    f.highest_high_20d_pct_chg / 100.0 AS highest_high_20d_delta,
                    f.rsi_14_pct_chg / 100.0 AS rsi_14_delta,
                    f.dist_from_52w_high_pct_chg / 100.0 AS dist_from_52w_high_delta,
                    f.dist_from_52w_low_pct_chg / 100.0 AS dist_from_52w_low_delta,
                    f.dist_from_20d_low_pct_chg / 100.0 AS dist_from_20d_low_delta,
                    f.dist_from_20d_high_pct_chg / 100.0 AS dist_from_20d_high_delta
                FROM t3_sepa_features f
                INNER JOIN company_profiles c ON f.ticker = c.ticker
                WHERE f.feature_version = '{self.feature_version}'
                  AND f.trend_ok = TRUE
                  AND f.breakout_ok = FALSE
                  AND f.date >= (
                      SELECT MAX(date) - INTERVAL '252 days'
                      FROM t3_sepa_features
                      WHERE feature_version = '{self.feature_version}'
                  )
            )
            SELECT
                base.*,
                ff.revenue,
                ff.net_income,
                ff.eps_diluted,
                ff.total_assets,
                ff.total_equity,
                ff.revenue_growth_yoy,
                ff.eps_growth_yoy,
                ff.net_income_growth_yoy,
                ff.eps_accel,
                ff.revenue_accel,
                ff.revenue_cagr_3y,
                ff.eps_stability_score,
                ff.debt_to_equity,
                ff.current_ratio,
                ff.quick_ratio,
                ff.gross_margin,
                ff.operating_margin,
                ff.net_margin,
                ff.roe,
                ff.roa,
                ff.fcf_margin,
                ff.earnings_quality_score,
                ff.inventory_growth_yoy,
                ff.inventory_vs_sales_spread,
                ff.gross_margin_trend,
                ff.filing_date AS fundamental_filing_date,
                ff.fiscal_period,
                CAST(datediff('day', ff.filing_date, base.date) AS INTEGER) AS days_since_report,
                cp.market_cap,
                {shares_col} AS shares_outstanding,
                CASE WHEN ABS(ff.eps_diluted) > 0.01
                    THEN base.close / ff.eps_diluted END AS pe_ratio,
                CASE WHEN ff.revenue > 0 AND {shares_col} > 0
                    THEN (base.close * {shares_col}) / ff.revenue END AS ps_ratio,
                CASE WHEN ff.total_equity > 0 AND {shares_col} > 0
                    THEN (base.close * {shares_col}) / ff.total_equity END AS pb_ratio,
                CASE WHEN ff.eps_growth_yoy > 0 AND ABS(ff.eps_diluted) > 0.01
                    THEN (base.close / ff.eps_diluted) / ff.eps_growth_yoy END AS peg_adjusted
            FROM base
            LEFT JOIN company_profiles cp ON base.ticker = cp.ticker
            {shares_join}
            LEFT JOIN ff_dedup ff
                ON base.ticker = ff.ticker
                AND ff.filing_date = (
                    SELECT MAX(filing_date) FROM ff_dedup
                    WHERE ticker = base.ticker AND filing_date <= base.date
                )
            ORDER BY base.date DESC, base.ticker
        """)
        print(f"   [OK] v_d3_prebreakout: pre-breakout cohort, last 252d (same contract as v_d3_deployment)")

    # ------------------------------------------------------------------
    # VIEW 7c: v_d3_lifecycle — MECE lifecycle population for daily scoring
    # ------------------------------------------------------------------

    # `removed` window: a name shows for ~20 trading days (≈28 calendar days)
    # after exit, then drops out. Calendar approximation (design 4c, confirmed).
    REMOVED_WINDOW_CALENDAR_DAYS = 28

    def _create_v_d3_lifecycle(self, con: duckdb.DuckDBPyConnection) -> None:
        """Lifecycle-tagged scoring population (supersedes status-gated cohorts).

        Replaces the breakout/pre_breakout split with the MECE union of the three
        SEPA lifecycle states, each row carrying a derived `cohort` tag:

            pre_breakout — trend_ok=TRUE AND breakout_ok=FALSE (in setup, not entered)
            active       — screener_watchlist.status='ACTIVE'  (C1+C2+C6 holds)
            removed      — status='EXITED' AND exit_date within last ~20 trading days

        Tag priority per ticker per day: active > removed > pre_breakout (a held
        name re-setting up is reported as a held position first). Hydrated with the
        SAME feature contract as v_d3_prebreakout/v_d3_deployment so the prod model
        scores all three tags with one feature list.

        Note: a name is `active`/`removed` only if it has a t3 row that day. Held
        names that left the candidate frontier are force-materialized by the Phase 5
        self-heal (see _t3_holed_dates) so they remain scorable.
        """
        has_shares = con.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = 'shares_history'
        """).fetchone()[0] > 0

        if has_shares:
            shares_col = "sh.shares_outstanding"
            shares_join = """
            LEFT JOIN shares_history sh
                ON base.ticker = sh.ticker
                AND sh.date = (
                    SELECT MAX(date) FROM shares_history
                    WHERE ticker = base.ticker AND date <= base.date
                )"""
        else:
            shares_col = "cp.shares_outstanding"
            shares_join = ""

        con.execute(f"""
            CREATE OR REPLACE VIEW v_d3_lifecycle AS
            WITH ff_dedup AS (
                SELECT
                    ticker, filing_date, fiscal_period,
                    revenue, net_income, eps_diluted, total_assets, total_equity,
                    revenue_growth_yoy, eps_growth_yoy, net_income_growth_yoy,
                    eps_accel, revenue_accel, revenue_cagr_3y, eps_stability_score,
                    debt_to_equity, current_ratio, quick_ratio,
                    gross_margin, operating_margin, net_margin, roe, roa, fcf_margin,
                    earnings_quality_score, inventory_growth_yoy,
                    inventory_vs_sales_spread, gross_margin_trend
                FROM fundamental_features
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY ticker, filing_date
                    ORDER BY fiscal_period DESC NULLS LAST
                ) = 1
            ),
            -- Per-(ticker,date) lifecycle membership off the watchlist, resolved by
            -- TRADE INTERVAL so a historical t3 date gets the tag it had on that day
            -- (correct for the backfill, not just today). For each t3 row we find the
            -- watchlist trade whose interval covers f.date and tag it:
            --   active  : entry_date <= f.date <= exit_date          (trade open)
            --   removed : exit_date <  f.date <= exit_date + window   (recently closed)
            -- active wins if a row sits in both (re-entry overlap). One tag per row.
            wl AS (
                SELECT ticker, date, cohort FROM (
                    SELECT
                        f.ticker, f.date,
                        CASE
                            WHEN f.date BETWEEN sw.entry_date AND sw.exit_date THEN 'active'
                            ELSE 'removed'
                        END AS cohort,
                        ROW_NUMBER() OVER (
                            PARTITION BY f.ticker, f.date
                            -- active (interval-open) ranked ahead of removed
                            ORDER BY CASE WHEN f.date BETWEEN sw.entry_date AND sw.exit_date
                                          THEN 0 ELSE 1 END,
                                     sw.exit_date DESC
                        ) AS rn
                    FROM (SELECT DISTINCT ticker, date FROM t3_sepa_features
                          WHERE feature_version = '{self.feature_version}'
                            AND date >= (
                                SELECT MAX(date) - INTERVAL '252 days'
                                FROM t3_sepa_features
                                WHERE feature_version = '{self.feature_version}')) f
                    JOIN screener_watchlist sw
                        ON f.ticker = sw.ticker
                       AND f.date >= sw.entry_date
                       AND f.date <= sw.exit_date
                                     + INTERVAL '{self.REMOVED_WINDOW_CALENDAR_DAYS}' DAY
                ) WHERE rn = 1
            ),
            -- Base population: t3 rows tagged by lifecycle state. A row qualifies if
            -- it is pre_breakout (flags) OR the name is active/recently-removed that day.
            base AS (
                SELECT
                    f.*,
                    c.sector,
                    c.industry,
                    COALESCE(wl.cohort, 'pre_breakout') AS cohort,
                    f.natr_pct_chg / 100.0 AS natr_delta,
                    f.vcp_ratio_pct_chg / 100.0 AS vcp_ratio_delta,
                    f.consolidation_width_pct_chg / 100.0 AS consolidation_width_delta,
                    f.price_vs_sma_50_pct_chg / 100.0 AS price_vs_sma_50_delta,
                    f.price_vs_sma_150_pct_chg / 100.0 AS price_vs_sma_150_delta,
                    f.price_vs_sma_200_pct_chg / 100.0 AS price_vs_sma_200_delta,
                    f.rs_pct_chg / 100.0 AS rs_delta,
                    f.rs_ma_pct_chg / 100.0 AS rs_ma_delta,
                    f.dry_up_volume_pct_chg / 100.0 AS dry_up_volume_delta,
                    f.high_52w_pct_chg / 100.0 AS high_52w_delta,
                    f.low_52w_pct_chg / 100.0 AS low_52w_delta,
                    f.lowest_low_20d_pct_chg / 100.0 AS lowest_low_20d_delta,
                    f.highest_high_20d_pct_chg / 100.0 AS highest_high_20d_delta,
                    f.rsi_14_pct_chg / 100.0 AS rsi_14_delta,
                    f.dist_from_52w_high_pct_chg / 100.0 AS dist_from_52w_high_delta,
                    f.dist_from_52w_low_pct_chg / 100.0 AS dist_from_52w_low_delta,
                    f.dist_from_20d_low_pct_chg / 100.0 AS dist_from_20d_low_delta,
                    f.dist_from_20d_high_pct_chg / 100.0 AS dist_from_20d_high_delta
                FROM t3_sepa_features f
                INNER JOIN company_profiles c ON f.ticker = c.ticker
                LEFT JOIN wl ON f.ticker = wl.ticker AND f.date = wl.date
                WHERE f.feature_version = '{self.feature_version}'
                  AND f.date >= (
                      SELECT MAX(date) - INTERVAL '252 days'
                      FROM t3_sepa_features
                      WHERE feature_version = '{self.feature_version}'
                  )
                  AND (
                      -- pre_breakout by flags, OR active/removed per the trade interval
                      (f.trend_ok = TRUE AND f.breakout_ok = FALSE)
                      OR wl.cohort IS NOT NULL
                  )
            )
            SELECT
                base.*,
                ff.revenue,
                ff.net_income,
                ff.eps_diluted,
                ff.total_assets,
                ff.total_equity,
                ff.revenue_growth_yoy,
                ff.eps_growth_yoy,
                ff.net_income_growth_yoy,
                ff.eps_accel,
                ff.revenue_accel,
                ff.revenue_cagr_3y,
                ff.eps_stability_score,
                ff.debt_to_equity,
                ff.current_ratio,
                ff.quick_ratio,
                ff.gross_margin,
                ff.operating_margin,
                ff.net_margin,
                ff.roe,
                ff.roa,
                ff.fcf_margin,
                ff.earnings_quality_score,
                ff.inventory_growth_yoy,
                ff.inventory_vs_sales_spread,
                ff.gross_margin_trend,
                ff.filing_date AS fundamental_filing_date,
                ff.fiscal_period,
                CAST(datediff('day', ff.filing_date, base.date) AS INTEGER) AS days_since_report,
                cp.market_cap,
                {shares_col} AS shares_outstanding,
                CASE WHEN ABS(ff.eps_diluted) > 0.01
                    THEN base.close / ff.eps_diluted END AS pe_ratio,
                CASE WHEN ff.revenue > 0 AND {shares_col} > 0
                    THEN (base.close * {shares_col}) / ff.revenue END AS ps_ratio,
                CASE WHEN ff.total_equity > 0 AND {shares_col} > 0
                    THEN (base.close * {shares_col}) / ff.total_equity END AS pb_ratio,
                CASE WHEN ff.eps_growth_yoy > 0 AND ABS(ff.eps_diluted) > 0.01
                    THEN (base.close / ff.eps_diluted) / ff.eps_growth_yoy END AS peg_adjusted
            FROM base
            LEFT JOIN company_profiles cp ON base.ticker = cp.ticker
            {shares_join}
            LEFT JOIN ff_dedup ff
                ON base.ticker = ff.ticker
                AND ff.filing_date = (
                    SELECT MAX(filing_date) FROM ff_dedup
                    WHERE ticker = base.ticker AND filing_date <= base.date
                )
            ORDER BY base.date DESC, base.ticker
        """)
        print(f"   [OK] v_d3_lifecycle: MECE lifecycle population (pre_breakout|active|removed), last 252d")

    # ------------------------------------------------------------------
    # VIEW 7d: v_d3_shortlist — the daily manual-review shortlist
    # ------------------------------------------------------------------

    def _create_v_d3_shortlist(self, con: duckdb.DuckDBPyConnection) -> None:
        """Ranked, tagged daily shortlist — the sprint-14 tail edge as a product.

        Pure JOIN of already-materialized parts (no new compute):
            v_d3_lifecycle (cohort='active')  ⋈  daily_predictions (prod model score)

        The edge (summary_eda §E/§H): a TAIL phenomenon at strong-RS × small-cap,
        m01's unique add is industry-tail, liquidity-capped (~$7.5M/day), median
        inverts. So the shortlist ranks today's ACTIVE breakouts by a composite of
        RS-percentile × small-cap × prob_elite and presents TAIL-ODDS, not a point
        return (a forecast would mislead — the median inverts).

        Model-swap free: the score joins the model flagged `status_flag='prod'` in
        the `models` table (ModelRegistry.get_prod_version). Swapping the model =
        set_prod() + backfill_daily_predictions; this view re-points, no edit.

        Columns are display lowercase (this is a display artifact, NOT model-fed) so
        the COLUMN_CASE_MAP casing bridge does not apply — RS_* ranks are referenced
        quoted verbatim.

        Tags, not hard filters (let the reviewer see borderline names; sort buries):
            liquidity_ok  — dollar_volume_avg_20 >= $7.5M/day (the R3 constraint)
            posture       — 'aggressive' (tail: high RS ∧ small-cap) vs 'defensive'
                            (calmer: lower rel-vol proxy natr) — a coarse split.
        """
        con.execute("""
            CREATE OR REPLACE VIEW v_d3_shortlist AS
            WITH prod AS (
                SELECT version_id FROM models WHERE status_flag = 'prod' LIMIT 1
            ),
            preds AS (
                -- prod-model score per (ticker, date); best-ranked row on any tag.
                SELECT ticker, prediction_date,
                       prob_class_3 AS prob_elite, rank_within_day
                FROM daily_predictions
                WHERE model_version_id = (SELECT version_id FROM prod)
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY ticker, prediction_date
                    ORDER BY rank_within_day
                ) = 1
            ),
            active AS (
                -- today's ACTIVE breakouts only (held SEPA positions in-hand).
                SELECT
                    lc.ticker, lc.date, lc.sector, lc.industry,
                    lc.close, lc.market_cap,
                    lc."RS_Universe_Rank"  AS rs_universe_rank,
                    lc."RS_Sector_Rank"    AS rs_sector_rank,
                    lc."RS_Industry_Rank"  AS rs_industry_rank,
                    lc.dollar_volume_avg_20 AS dollar_volume,
                    lc.natr
                FROM v_d3_lifecycle lc
                WHERE lc.cohort = 'active'
                  AND lc.date = (SELECT MAX(date) FROM v_d3_lifecycle)
            ),
            scored AS (
                SELECT
                    a.*,
                    p.prob_elite,
                    p.rank_within_day,
                    -- small-cap percentile within today's active set (small = 1.0).
                    1.0 - PERCENT_RANK() OVER (ORDER BY a.market_cap) AS smallcap_pctl,
                    a.dollar_volume >= 7.5e6 AS liquidity_ok
                FROM active a
                LEFT JOIN preds p
                    ON p.ticker = a.ticker AND p.prediction_date = a.date
            )
            SELECT
                ticker, date, sector, industry, close, market_cap,
                rs_universe_rank, rs_sector_rank, rs_industry_rank,
                dollar_volume, liquidity_ok, natr,
                prob_elite, rank_within_day,
                smallcap_pctl,
                -- composite: strong-RS × small-cap × prob_elite (the §E/§H tail cell).
                -- COALESCE prob to 0.25 (base rate) for un-scored fresh breakouts so a
                -- NULL score doesn't NULL the whole composite (NaN-passthrough intent).
                (rs_universe_rank + smallcap_pctl + COALESCE(prob_elite, 0.25)) / 3.0
                    AS shortlist_score,
                CASE
                    WHEN rs_universe_rank >= 0.8 AND smallcap_pctl >= 0.6 THEN 'aggressive'
                    ELSE 'defensive'
                END AS posture
            FROM scored
            -- liquid names first, then by tail composite. Borderline (illiquid) sink.
            ORDER BY liquidity_ok DESC, shortlist_score DESC
        """)
        print(f"   [OK] v_d3_shortlist: ranked/tagged active-breakout shortlist (tail edge)")

    # ------------------------------------------------------------------
    # VIEW 8: v_screener_dashboard — SEPA Screener Tracker
    # ------------------------------------------------------------------

    def _create_v_screener_dashboard(self, con: duckdb.DuckDBPyConnection) -> None:
        """SEPA screener dashboard: tracks which tickers passed screening,
        when they first triggered, entry price, and return vs current price."""
        con.execute("""
            CREATE OR REPLACE VIEW v_screener_dashboard AS
            -- Step 1: Detect trend sessions using C1+C2+C6 only (matches v_d1_candidates)
            --         C1: close > SMA150, C2: close > SMA200, C6: close > SMA50
            WITH trend_c8_base AS (
                SELECT
                    t2.ticker,
                    t2.date,
                    t2.trend_ok,
                    t2.breakout_ok,
                    COALESCE(
                        t2.close > t2.sma_150
                        AND t2.close > t2.sma_200
                        AND t2.close > t2.sma_50,
                        FALSE
                    ) AS trend_c8
                FROM t2_screener_features t2
                INNER JOIN company_profiles c ON t2.ticker = c.ticker
                WHERE c.is_active = TRUE
            ),
            trend_sessions AS (
                SELECT
                    *,
                    CASE WHEN trend_c8 AND NOT COALESCE(
                        LAG(trend_c8) OVER (PARTITION BY ticker ORDER BY date),
                        FALSE
                    ) THEN 1 ELSE 0 END AS trend_session_start
                FROM trend_c8_base
            ),
            sessions AS (
                SELECT
                    ticker, date, trend_ok, breakout_ok, trend_c8,
                    SUM(trend_session_start) OVER (
                        PARTITION BY ticker ORDER BY date
                    ) AS session_id
                FROM trend_sessions
                WHERE trend_c8
            ),
            -- Step 2: First breakout per session = entry (requires full trend_ok + breakout_ok)
            entries AS (
                SELECT
                    ticker,
                    session_id,
                    MIN(date) AS entry_date
                FROM sessions
                WHERE trend_ok AND breakout_ok
                GROUP BY ticker, session_id
            ),
            -- Step 3: Session end = last C1-C8 True day
            session_bounds AS (
                SELECT ticker, session_id, MAX(date) AS last_trend_date
                FROM sessions
                GROUP BY ticker, session_id
            ),
            -- Precompute LEAD(date)/LEAD(close) to avoid O(n²) correlated subqueries
            price_with_next AS (
                SELECT
                    ticker, date, close,
                    LEAD(date)  OVER (PARTITION BY ticker ORDER BY date) AS next_date,
                    LEAD(close) OVER (PARTITION BY ticker ORDER BY date) AS next_close
                FROM price_data
            ),
            -- Step 4: Entry price + exit price per trade
            --         Exit = first trading day AFTER trend breaks (no lookahead bias)
            trades AS (
                SELECT
                    e.ticker,
                    e.session_id,
                    e.entry_date,
                    pe.close AS entry_price,
                    COALESCE(px.next_date,  sb.last_trend_date) AS exit_date,
                    COALESCE(px.next_close, px.close)           AS exit_price
                FROM entries e
                INNER JOIN session_bounds sb
                    ON e.ticker = sb.ticker AND e.session_id = sb.session_id
                LEFT JOIN price_with_next pe
                    ON e.ticker = pe.ticker AND e.entry_date = pe.date
                LEFT JOIN price_with_next px
                    ON sb.ticker = px.ticker AND sb.last_trend_date = px.date
            ),
            -- Step 5: Latest available close per ticker (handles delistings)
            latest_prices AS (
                SELECT
                    ticker,
                    MAX(date) AS latest_date,
                    ARG_MAX(close, date) AS current_close
                FROM price_data
                GROUP BY ticker
            ),
            -- Step 6: Determine status and pick the right reference price
            with_status AS (
                SELECT
                    t.*,
                    cp.name AS company_name,
                    cp.sector,
                    cp.industry,
                    cp.market_cap,
                    CASE WHEN t.exit_date >= COALESCE(lp.latest_date, t.exit_date)
                        THEN 'ACTIVE' ELSE 'EXITED' END AS status,
                    lp.current_close,
                    lp.latest_date
                FROM trades t
                INNER JOIN company_profiles cp ON t.ticker = cp.ticker
                LEFT JOIN latest_prices lp ON t.ticker = lp.ticker
            )
            SELECT
                ticker,
                company_name,
                sector,
                industry,
                market_cap,
                entry_date,
                entry_price,
                exit_date,
                status,
                CASE WHEN status = 'ACTIVE' THEN current_close
                     ELSE exit_price END AS close_price,
                CASE WHEN status = 'ACTIVE' THEN latest_date
                     ELSE exit_date END AS price_date,
                CASE WHEN entry_price > 0 THEN
                    ((CASE WHEN status = 'ACTIVE' THEN current_close
                           ELSE exit_price END) / entry_price - 1.0) * 100.0
                END AS pct_return,
                CAST(datediff('day', entry_date,
                    CASE WHEN status = 'ACTIVE' THEN COALESCE(latest_date, exit_date)
                         ELSE exit_date END) AS INTEGER) AS days_held
            FROM with_status
            ORDER BY entry_date DESC, ticker
        """)
        n = con.execute(
            "SELECT COUNT(*), COUNT(DISTINCT ticker) FROM v_screener_dashboard"
        ).fetchone()
        active = con.execute(
            "SELECT COUNT(*) FROM v_screener_dashboard WHERE status = 'ACTIVE'"
        ).fetchone()[0]
        print(f"   [OK] v_screener_dashboard: {n[0]:,} trades, {n[1]} tickers ({active} active)")

    # ------------------------------------------------------------------
    # MATERIALIZED TABLE: screener_watchlist
    # ------------------------------------------------------------------

    def _refresh_screener_watchlist(self, con: duckdb.DuckDBPyConnection) -> None:
        """Materialise v_screener_dashboard into screener_watchlist table."""
        start = time.time()
        con.execute("""
            CREATE OR REPLACE TABLE screener_watchlist AS
            SELECT *, CURRENT_TIMESTAMP AS refreshed_at
            FROM v_screener_dashboard
        """)
        elapsed = time.time() - start
        n = con.execute("SELECT COUNT(*), COUNT(DISTINCT ticker) FROM screener_watchlist").fetchone()
        active = con.execute("SELECT COUNT(*) FROM screener_watchlist WHERE status = 'ACTIVE'").fetchone()[0]
        print(f"   [OK] screener_watchlist: {n[0]:,} trades, {n[1]} tickers ({active} active) [{elapsed:.1f}s]")

    def refresh_screener_watchlist(self, verbose: bool = True) -> None:
        """Public API: refresh screener_watchlist table (standalone call)."""
        con = db.connect(self.db_path)
        try:
            self._refresh_screener_watchlist(con)
        except Exception as e:
            logger.error(f"screener_watchlist refresh failed: {e}")
            if verbose:
                print(f"   [ERROR] screener_watchlist refresh failed: {e}")
            raise
        finally:
            con.close()

    def _refresh_t3_training_cache(self, con: duckdb.DuckDBPyConnection) -> None:
        """Materialise v_t3_training (t3 features + ASOF-joined fundamentals/shares +
        derived valuation ratios) into the t3_training_cache table.

        v_t3_training is a VIEW whose two ASOF joins re-execute on every query (~80s).
        This table pays that cost once per pipeline run so all consumers (m02 training,
        universe scorer, EDA, backtests) read instantly. The view definition is owned by
        UniverseScorer.create_view — ensure it exists before materialising."""
        from src.backtest.universe_scorer import UniverseScorer

        has_view = con.execute("""
            SELECT COUNT(*) FROM information_schema.views WHERE table_name = 'v_t3_training'
        """).fetchone()[0] > 0
        if not has_view:
            UniverseScorer.create_view(self.db_path)

        start = time.time()
        con.execute("""
            CREATE OR REPLACE TABLE t3_training_cache AS
            SELECT *, CURRENT_TIMESTAMP AS cached_at
            FROM v_t3_training
        """)
        elapsed = time.time() - start
        n = con.execute("SELECT COUNT(*) FROM t3_training_cache").fetchone()[0]
        print(f"   [OK] t3_training_cache: {n:,} rows materialized [{elapsed:.1f}s]")

    def refresh_t3_training_cache(self, verbose: bool = True) -> None:
        """Public API: refresh t3_training_cache table (standalone call)."""
        con = duckdb.connect(self.db_path)
        try:
            self._refresh_t3_training_cache(con)
        except Exception as e:
            logger.error(f"t3_training_cache refresh failed: {e}")
            if verbose:
                print(f"   [ERROR] t3_training_cache refresh failed: {e}")
            raise
        finally:
            con.close()

    # ------------------------------------------------------------------
    # MATERIALIZED CACHE: Speed up training data loads
    # ------------------------------------------------------------------

    def create_cache_table(self) -> None:
        """
        Create d2_training_cache table (materialized v_d2_training).

        Purpose: Speed up model training data loads from 5-10s → <1s.
        Usage: Call refresh_cache() after feature pipeline completion.
        """
        con = db.connect(self.db_path)
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS d2_training_cache (
                    -- This table mirrors v_d2_training structure
                    -- It is refreshed via CREATE OR REPLACE after t3_sepa_features updates
                    ticker VARCHAR,
                    date DATE,
                    trade_id BIGINT,
                    -- (All other columns inherited from v_d2_training via CREATE TABLE AS)
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            print("[OK] d2_training_cache table created (empty)")
        except Exception as e:
            logger.error(f"Failed to create d2_training_cache: {e}")
            raise
        finally:
            con.close()

    def refresh_cache(self, verbose: bool = True) -> None:
        """
        Refresh d2_training_cache by materializing v_d2_training.

        This replaces the entire cache table with current view data.
        Call this after t3_sepa_features is updated to ensure cache freshness.

        Args:
            verbose: If True, print progress messages
        """
        import time

        con = db.connect(self.db_path)
        try:
            if verbose:
                print("   [CACHE] Refreshing d2_training_cache...")

            start = time.time()

            # Materialize v_d2_training into cache table
            con.execute("""
                CREATE OR REPLACE TABLE d2_training_cache AS
                SELECT
                    *,
                    CURRENT_TIMESTAMP AS cached_at
                FROM v_d2_training
            """)

            elapsed = time.time() - start
            row_count = con.execute("SELECT COUNT(*) FROM d2_training_cache").fetchone()[0]

            if verbose:
                print(f"   [OK] Cache refreshed: {row_count:,} rows in {elapsed:.2f}s")

            logger.info(f"d2_training_cache refreshed: {row_count} rows in {elapsed:.2f}s")

        except Exception as e:
            logger.error(f"Cache refresh failed: {e}")
            if verbose:
                print(f"   [ERROR] Cache refresh failed: {e}")
            raise
        finally:
            con.close()

    def get_cache_stats(self) -> dict:
        """
        Get cache statistics (row count, last refresh time).

        Returns:
            dict with keys: row_count, cached_at, age_hours
        """
        con = db.connect(self.db_path)
        try:
            result = con.execute("""
                SELECT
                    COUNT(*) as row_count,
                    MAX(cached_at) as cached_at,
                    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - MAX(cached_at))) / 3600.0 as age_hours
                FROM d2_training_cache
            """).fetchone()

            if result is None or result[0] == 0:
                return {'row_count': 0, 'cached_at': None, 'age_hours': None}

            return {
                'row_count': result[0],
                'cached_at': result[1],
                'age_hours': result[2]
            }
        except Exception:
            # Table doesn't exist
            return {'row_count': 0, 'cached_at': None, 'age_hours': None}
        finally:
            con.close()
