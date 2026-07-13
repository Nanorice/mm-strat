"""
Feature Pipeline — T2 screener features + T3 SEPA features computation for DuckDB.

T2 (compute_t2_screener_features):
  Phase A (SQL): Base features via window functions (~61 cols, full ~2400 ticker universe)
  Phase B (Python): XS alpha factors (9 alphas: need full universe for valid cross-sectional rank)
  Phase C (SQL): Cross-sectional ranks (7 cols)

T3 (compute_t3_features):
  Phase A (SQL): Per-ticker window features (momentum, RSI, ATR, pct_chg deltas, etc.)
  Carry-forward: All t2 cols + OHLCV from price_data
  Phase B (Python): TS alpha factors (9 alphas: pure per-ticker time-series)
  M03: Joined from t2_regime_scores
"""

import logging
from pathlib import Path
from typing import List, Optional

import duckdb
from src import db
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Cross-sectional alphas (require full universe, computed in t2)
ALPHA_NUMS_XS = [1, 2, 4, 8, 11, 13, 15, 19, 60]
# Pure time-series alphas (per-ticker only, computed in t3)
ALPHA_NUMS_TS = [6, 9, 12, 41, 46, 49, 51, 54, 101]
ALPHA_NUMS = ALPHA_NUMS_XS + ALPHA_NUMS_TS
ALPHA_COLS = [f"alpha{n:03d}" for n in ALPHA_NUMS]
ALPHA_COLS_XS = [f"alpha{n:03d}" for n in ALPHA_NUMS_XS]
ALPHA_COLS_TS = [f"alpha{n:03d}" for n in ALPHA_NUMS_TS]

RANK_COLS = [
    'RS_Universe_Rank', 'RS_Sector_Rank', 'RS_vs_Sector',
    'Sector_Momentum', 'RS_Industry_Rank', 'RS_vs_Industry',
    'Industry_Momentum',
]

EMA_SPANS = [8, 21, 50, 100, 200]
EMA_COLS = [f"ema_{s}" for s in EMA_SPANS]

M03_BASE_COLS = ['m03_score', 'm03_pillar_trend', 'm03_pillar_liq', 'm03_pillar_risk']
M03_DERIVED_COLS = ['m03_delta_5d', 'm03_delta_20d', 'm03_regime_vol']

# Tripwire: must equal the column count produced by _create_t3_table.
# Update this constant whenever the DDL changes — the post-INSERT guard in
# compute_t3_features() will fail if DDL and INSERT/SELECT lists drift apart.
EXPECTED_T3_COLUMN_COUNT = 144


# Module-level function for multiprocessing (must be picklable)
def _compute_single_alpha_wrapper(alpha_tuple, df):
    """
    Wrapper function for multiprocessing Pool.
    Must be at module level (not inside class) for pickling.

    Args:
        alpha_tuple: (name, alpha_function)
        df: Pre-computed dataframe with intermediates

    Returns:
        (name, pd.Series) — alpha name and computed values
    """
    name, func = alpha_tuple
    result = func(df)
    return (name, result)


class FeaturePipeline:
    """Two-table feature computation pipeline: T2 screener features -> T3 SEPA features."""

    def __init__(self, db_path: str, use_backfill: bool = False, feature_version: str = 'v3.1'):
        self.db_path = str(db_path)
        self.price_source = "v_price_combined" if use_backfill else "price_data"
        self.feature_version = feature_version

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def compute_all(
        self,
        start_date: str = '2020-01-01',
        warmup_days: int = 365,
        skip_t2: bool = False,
        skip_t3: bool = False,
        recreate_t3: bool = False,
    ) -> None:
        """
        Compute all features: T2 screener features -> T3 SEPA features.

        Args:
            start_date: Start date for feature computation
            warmup_days: Days before start_date to fetch for lookback windows
            skip_t2: Skip T2 screener features (default: False)
            skip_t3: Skip T3 SEPA features (default: False)
            recreate_t3: Drop and recreate t3_sepa_features table (default: False)
        """
        if not skip_t2:
            logger.info("📊 Computing T2 screener features (full universe)...")
            self.compute_t2_screener_features(start_date, warmup_days=warmup_days)

        if skip_t3:
            logger.info("[T3] Skipped (skip_t3=True)")
            return

        # Ensure t3 table exists (create if missing, recreate if requested)
        con = db.connect(self.db_path)
        try:
            tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if recreate_t3 or 't3_sepa_features' not in tables:
                logger.info("[T3] Creating t3_sepa_features table...")
                self._create_t3_table(con)
        finally:
            con.close()

        self.compute_t3_features(start_date=start_date)
        self._refresh_training_cache()

    # ------------------------------------------------------------------
    # T2: Lightweight Screener Features (Milestone 3.3)
    # ------------------------------------------------------------------

    def compute_t2_screener_features(self, start_date: str = '2020-01-01', warmup_days: int = 400, end_date: str = None) -> int:
        """Compute T2 screener features for full universe (30 lightweight columns).

        This table supports SEPA C1-C11 screening and is computed eagerly for all tickers.
        Heavy ML features (alphas, ranks) are deferred to T3 (lazy, SEPA candidates only).

        Args:
            start_date: Start date for feature computation
            warmup_days: Number of days before start_date to fetch for lookback windows
            end_date: End date for feature computation (default: MAX(price_data.date))

        Returns:
            Number of rows inserted into t2_screener_features
        """
        from datetime import date as date_cls
        if end_date is None:
            end_date = date_cls.today().strftime('%Y-%m-%d')

        logger.info(f"[T2] Computing screener features (full universe, {start_date} -> {end_date}, warmup={warmup_days}d)...")
        con = db.connect(self.db_path)

        fetch_start_date = (pd.to_datetime(start_date) - pd.Timedelta(days=warmup_days)).strftime('%Y-%m-%d')

        try:
            # Create table if not exists
            con.execute("""
                CREATE TABLE IF NOT EXISTS t2_screener_features (
                    ticker VARCHAR NOT NULL,
                    date DATE NOT NULL,

                    -- Raw OHLCV
                    open DOUBLE,
                    high DOUBLE,
                    low DOUBLE,
                    close DOUBLE,
                    volume UBIGINT,

                    -- Simple Moving Averages (SEPA Core)
                    sma_20 DOUBLE,
                    sma_50 DOUBLE,
                    sma_150 DOUBLE,
                    sma_200 DOUBLE,
                    sma_200_lag20 DOUBLE,

                    -- Price vs SMA (SEPA Criteria)
                    price_vs_sma_50 DOUBLE,
                    price_vs_sma_150 DOUBLE,
                    price_vs_sma_200 DOUBLE,
                    close_above_sma200 BOOLEAN,

                    -- Relative Strength (SEPA Core)
                    rs_rating DOUBLE,
                    rs DOUBLE,
                    rs_ma DOUBLE,
                    rs_line_log DOUBLE,
                    rs_line_delta DOUBLE,
                    rs_line_uptrend BOOLEAN,

                    -- 52-Week Highs/Lows (SEPA Criteria)
                    high_52w DOUBLE,
                    low_52w DOUBLE,
                    dist_from_52w_high DOUBLE,
                    dist_from_52w_low DOUBLE,
                    pct_from_high_52w DOUBLE,
                    pct_above_low_52w DOUBLE,

                    -- 20-Day Highs/Lows
                    high_20d DOUBLE,
                    lowest_low_20d DOUBLE,
                    highest_high_20d DOUBLE,
                    dist_from_20d_high DOUBLE,
                    dist_from_20d_low DOUBLE,

                    -- Volume
                    vol_avg_20 DOUBLE,
                    vol_avg_50 DOUBLE,
                    vol_ratio DOUBLE,
                    dry_up_volume DOUBLE,

                    -- Volatility
                    atr_20d DOUBLE,
                    natr DOUBLE,
                    volatility_20d DOUBLE,

                    -- VCP Pattern
                    vcp_ratio DOUBLE,
                    consolidation_width DOUBLE,

                    -- SEPA composite flags
                    trend_ok BOOLEAN,
                    breakout_ok BOOLEAN,

                    -- SPY ratio (needed for rs_line_uptrend + carry-forward to t3)
                    price_vs_spy DOUBLE,
                    price_vs_spy_ma63 DOUBLE,

                    -- Cross-sectional ranks (need full screener population)
                    RS_Universe_Rank DOUBLE,
                    RS_Sector_Rank DOUBLE,
                    RS_vs_Sector DOUBLE,
                    Sector_Momentum DOUBLE,
                    RS_Industry_Rank DOUBLE,
                    RS_vs_Industry DOUBLE,
                    Industry_Momentum DOUBLE,

                    -- Cross-sectional alpha factors (need full screener population)
                    alpha001 DOUBLE, alpha002 DOUBLE, alpha004 DOUBLE, alpha008 DOUBLE,
                    alpha011 DOUBLE, alpha013 DOUBLE, alpha015 DOUBLE, alpha019 DOUBLE,
                    alpha060 DOUBLE,

                    -- Metadata
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (ticker, date)
                )
            """)

            # Migrate existing table: add new columns if missing (idempotent)
            existing_cols = {r[0] for r in con.execute("DESCRIBE t2_screener_features").fetchall()}
            new_cols = [
                ("open", "DOUBLE"), ("high", "DOUBLE"), ("low", "DOUBLE"),
                ("close", "DOUBLE"), ("volume", "UBIGINT"),
                ("pct_above_low_52w", "DOUBLE"),
                ("highest_high_20d", "DOUBLE"),
                ("price_vs_spy", "DOUBLE"),
                ("price_vs_spy_ma63", "DOUBLE"),
                ("RS_Universe_Rank", "DOUBLE"),
                ("RS_Sector_Rank", "DOUBLE"),
                ("RS_vs_Sector", "DOUBLE"),
                ("Sector_Momentum", "DOUBLE"),
                ("RS_Industry_Rank", "DOUBLE"),
                ("RS_vs_Industry", "DOUBLE"),
                ("Industry_Momentum", "DOUBLE"),
                ("alpha001", "DOUBLE"), ("alpha002", "DOUBLE"), ("alpha004", "DOUBLE"),
                ("alpha008", "DOUBLE"), ("alpha011", "DOUBLE"), ("alpha013", "DOUBLE"),
                ("alpha015", "DOUBLE"), ("alpha019", "DOUBLE"), ("alpha060", "DOUBLE"),
            ]
            for col_name, col_type in new_cols:
                if col_name not in existing_cols:
                    con.execute(f"ALTER TABLE t2_screener_features ADD COLUMN {col_name} {col_type}")
                    logger.info(f"[T2] Added column: {col_name}")

            # Delete existing rows in target range, then insert (avoids PK check against full table)
            con.execute(f"DELETE FROM t2_screener_features WHERE date BETWEEN '{start_date}' AND '{end_date}'")

            con.execute(f"""
                INSERT INTO t2_screener_features BY NAME
                WITH price_base AS (
                    SELECT
                        p.ticker, p.date, p.open, p.close, p.high, p.low, p.volume,
                        LAG(p.close, 1) OVER (PARTITION BY p.ticker ORDER BY p.date) as prev_close,
                        LAG(p.open, 1) OVER (PARTITION BY p.ticker ORDER BY p.date) as prev_open
                    FROM {self.price_source} p
                    INNER JOIN (
                        -- Point-in-time membership: event valid from effective_date until next event
                        SELECT ticker, effective_date, is_active,
                               LEAD(effective_date) OVER (PARTITION BY ticker ORDER BY effective_date) AS next_date
                        FROM screener_membership
                    ) sm ON p.ticker = sm.ticker
                        AND p.date >= sm.effective_date
                        AND (sm.next_date IS NULL OR p.date < sm.next_date)
                        AND sm.is_active = TRUE
                    WHERE p.date >= '{fetch_start_date}' AND p.date <= '{end_date}'
                ),
                spy_data AS (
                    SELECT date, spy_close
                    FROM t1_macro
                    WHERE date >= '{fetch_start_date}' AND date <= '{end_date}'
                ),
                price_with_spy AS (
                    SELECT
                        p.*,
                        s.spy_close,
                        p.close / NULLIF(s.spy_close, 0) as price_vs_spy
                    FROM price_base p
                    LEFT JOIN spy_data s ON p.date = s.date
                ),
                core_features AS (
                    SELECT
                        ticker, date, open, high, low, close, volume, prev_close,
                        price_vs_spy,

                        AVG(close) OVER w20 as sma_20,
                        AVG(close) OVER w50 as sma_50,
                        AVG(close) OVER w150 as sma_150,
                        AVG(close) OVER w200 as sma_200,

                        AVG(price_vs_spy) OVER w63 as price_vs_spy_ma63,
                        LN(price_vs_spy) as rs_line_log,
                        (price_vs_spy / NULLIF(LAG(price_vs_spy, 1) OVER ticker_date, 0) - 1) as rs_line_delta,

                        AVG(volume) OVER w5 as vol_avg_5,
                        AVG(volume) OVER w20 as vol_avg_20,
                        AVG(volume) OVER w50 as vol_avg_50,
                        AVG(volume) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 50 PRECEDING AND 1 PRECEDING) as vol_avg_50_prev,

                        STDDEV(close) OVER w20 as volatility_20d,
                        GREATEST(high - low, ABS(high - prev_close), ABS(low - prev_close)) as true_range,

                        (close / NULLIF(LAG(close, 21) OVER ticker_date, 0) - 1) as mom_21d,
                        (close / NULLIF(LAG(close, 63) OVER ticker_date, 0) - 1) as mom_63d,
                        (close / NULLIF(LAG(close, 126) OVER ticker_date, 0) - 1) as mom_126d,
                        (close / NULLIF(LAG(close, 189) OVER ticker_date, 0) - 1) as mom_189d,
                        (close / NULLIF(LAG(close, 252) OVER ticker_date, 0) - 1) as mom_252d,

                        MAX(close) OVER w252 as high_52w,
                        MIN(close) OVER w252 as low_52w,
                        MAX(high) OVER w20 as highest_high_20d,
                        MIN(low) OVER w20 as lowest_low_20d,
                        MAX(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) as high_20d,

                        CASE WHEN close > MAX(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
                             THEN 1 ELSE 0 END as breakout

                    FROM price_with_spy
                    WINDOW
                        ticker_date AS (PARTITION BY ticker ORDER BY date),
                        w5 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
                        w20 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
                        w50 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
                        w63 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 62 PRECEDING AND CURRENT ROW),
                        w150 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 149 PRECEDING AND CURRENT ROW),
                        w200 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW),
                        w252 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW)
                ),
                derived_features AS (
                    SELECT
                        cf.*,

                        AVG(true_range) OVER w14 as atr_14,
                        AVG(true_range) OVER w20 as atr_20d,
                        AVG(true_range) OVER w10 as atr_10,
                        AVG(true_range) OVER w50 as atr_50,

                        0.4 * mom_63d + 0.2 * mom_126d + 0.2 * mom_189d + 0.2 * mom_252d as rs_rating,
                        LAG(sma_200, 20) OVER (PARTITION BY ticker ORDER BY date) as sma_200_lag20,

                        ((close - sma_50) / NULLIF(sma_50, 0)) * 100 as price_vs_sma_50,
                        ((close - sma_150) / NULLIF(sma_150, 0)) * 100 as price_vs_sma_150,
                        ((close - sma_200) / NULLIF(sma_200, 0)) * 100 as price_vs_sma_200,

                        (close - high_52w) / NULLIF(high_52w, 0) as dist_from_52w_high,
                        (close / NULLIF(low_52w, 0)) - 1 as dist_from_52w_low,
                        (close / NULLIF(lowest_low_20d, 0)) - 1 as dist_from_20d_low,
                        (close / NULLIF(highest_high_20d, 0)) - 1 as dist_from_20d_high,
                        (close - high_52w) / NULLIF(high_52w, 0) as pct_from_high_52w,
                        (close - low_52w) / NULLIF(low_52w, 0) as pct_above_low_52w

                    FROM core_features cf
                    WINDOW
                        w10 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),
                        w14 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),
                        w20 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
                        w50 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW)
                ),
                final_features AS (
                    SELECT
                        df.*,

                        (atr_14 / NULLIF(close, 0)) * 100 as natr,
                        atr_10 / NULLIF(atr_50, 0) as vcp_ratio,
                        ((highest_high_20d - lowest_low_20d) / NULLIF(close, 0)) * 100 as consolidation_width,
                        volume / NULLIF(vol_avg_50, 0) as vol_ratio,
                        vol_avg_5 / NULLIF(vol_avg_50, 0) as dry_up_volume,

                        rs_rating as rs,
                        AVG(rs_rating) OVER w63 as rs_ma,

                        CASE WHEN price_vs_spy > price_vs_spy_ma63 THEN TRUE ELSE FALSE END as rs_line_uptrend,
                        CASE WHEN close > sma_200 THEN TRUE ELSE FALSE END as close_above_sma200,

                        -- SEPA composite flags (C1-C9 trend template)
                        COALESCE(
                            close > sma_150 AND close > sma_200
                            AND sma_150 > sma_200 AND sma_200 > sma_200_lag20
                            AND sma_50 > sma_150 AND close > sma_50
                            AND close > low_52w * 1.3
                            AND close > high_52w * 0.85
                            AND price_vs_spy > price_vs_spy_ma63,
                            FALSE
                        ) AS trend_ok,

                        COALESCE(
                            breakout = 1 AND volume / NULLIF(vol_avg_50_prev, 0) > 1.3,
                            FALSE
                        ) AS breakout_ok

                    FROM derived_features df
                    WINDOW
                        w63 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 62 PRECEDING AND CURRENT ROW)
                )
                SELECT
                    ticker, date,
                    open, high, low, close, volume,
                    sma_20, sma_50, sma_150, sma_200, sma_200_lag20,
                    price_vs_sma_50, price_vs_sma_150, price_vs_sma_200, close_above_sma200,
                    rs_rating, rs, rs_ma, rs_line_log, rs_line_delta, rs_line_uptrend,
                    high_52w, low_52w, dist_from_52w_high, dist_from_52w_low, pct_from_high_52w, pct_above_low_52w,
                    high_20d, lowest_low_20d, highest_high_20d, dist_from_20d_high, dist_from_20d_low,
                    vol_avg_20, vol_avg_50, vol_ratio, dry_up_volume,
                    atr_20d, natr, volatility_20d,
                    vcp_ratio, consolidation_width,
                    trend_ok, breakout_ok,
                    price_vs_spy, price_vs_spy_ma63,
                    CURRENT_TIMESTAMP as updated_at
                FROM final_features
                WHERE date BETWEEN '{start_date}' AND '{end_date}'
            """)

            row_count = con.execute(f"SELECT COUNT(*) FROM t2_screener_features WHERE date BETWEEN '{start_date}' AND '{end_date}'").fetchone()[0]
            ticker_count = con.execute("SELECT COUNT(DISTINCT ticker) FROM t2_screener_features").fetchone()[0]
            logger.info(f"[T2] Inserted {row_count:,} rows for {ticker_count:,} tickers")

        except Exception as e:
            logger.error(f"T2 feature computation failed: {e}")
            raise
        finally:
            con.close()

        # Cross-sectional alphas (XS) — need full screener population, run after SQL insert
        self.compute_alpha_features(
            start_date=start_date,
            end_date=end_date,
            warmup_days=warmup_days,
            target_table='t2_screener_features',
            alpha_cols=ALPHA_COLS_XS,
        )

        # EMAs — recursive, must be computed in Python (pandas ewm)
        self.compute_ema_features(
            start_date=start_date,
            end_date=end_date,
            warmup_days=warmup_days,
            target_table='t2_screener_features',
        )

        # Cross-sectional ranks — PERCENT_RANK() across full t2 population
        self.compute_cross_sectional_ranks(target_table='t2_screener_features', start_date=start_date, end_date=end_date)

        return row_count

    # ------------------------------------------------------------------
    # T3: SEPA Features (lazy materialization)
    # ------------------------------------------------------------------

    def _create_t3_table(self, con) -> None:
        """Create t3_sepa_features with clean schema (no _1 artifact cols)."""
        con.execute("DROP TABLE IF EXISTS t3_sepa_features")
        con.execute(f"""
            CREATE TABLE t3_sepa_features (
                -- Keys
                ticker VARCHAR NOT NULL,
                date DATE NOT NULL,
                feature_version VARCHAR NOT NULL DEFAULT '{self.feature_version}',

                -- OHLCV (needed for backtest simulation)
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
                volume BIGINT,

                -- Carried from t2 (all non-metadata t2 cols)
                sma_20 DOUBLE, sma_50 DOUBLE, sma_150 DOUBLE, sma_200 DOUBLE, sma_200_lag20 DOUBLE,
                price_vs_sma_50 DOUBLE, price_vs_sma_150 DOUBLE, price_vs_sma_200 DOUBLE,
                close_above_sma200 BOOLEAN,
                price_vs_spy DOUBLE, price_vs_spy_ma63 DOUBLE,
                rs_rating DOUBLE, rs DOUBLE, rs_ma DOUBLE,
                rs_line_log DOUBLE, rs_line_delta DOUBLE, rs_line_uptrend BOOLEAN,
                high_52w DOUBLE, low_52w DOUBLE,
                dist_from_52w_high DOUBLE, dist_from_52w_low DOUBLE,
                pct_from_high_52w DOUBLE, pct_above_low_52w DOUBLE,
                high_20d DOUBLE, lowest_low_20d DOUBLE, highest_high_20d DOUBLE,
                dist_from_20d_high DOUBLE, dist_from_20d_low DOUBLE,
                vol_avg_20 DOUBLE, vol_avg_50 DOUBLE, vol_ratio DOUBLE, dry_up_volume DOUBLE,
                atr_20d DOUBLE, natr DOUBLE, volatility_20d DOUBLE,
                vcp_ratio DOUBLE, consolidation_width DOUBLE,
                trend_ok BOOLEAN, breakout_ok BOOLEAN,
                RS_Universe_Rank DOUBLE, RS_Sector_Rank DOUBLE, RS_vs_Sector DOUBLE,
                Sector_Momentum DOUBLE, RS_Industry_Rank DOUBLE, RS_vs_Industry DOUBLE,
                Industry_Momentum DOUBLE,
                alpha001 DOUBLE, alpha002 DOUBLE, alpha004 DOUBLE, alpha008 DOUBLE,
                alpha011 DOUBLE, alpha013 DOUBLE, alpha015 DOUBLE, alpha019 DOUBLE,
                alpha060 DOUBLE,

                -- EMAs (carried from t2)
                ema_8 DOUBLE, ema_21 DOUBLE, ema_50 DOUBLE, ema_100 DOUBLE, ema_200 DOUBLE,

                -- Lag features
                rs_line_lag_delta DOUBLE,

                -- Per-ticker features computed from price_data window functions
                mom_21d DOUBLE, mom_63d DOUBLE, mom_126d DOUBLE, mom_189d DOUBLE, mom_252d DOUBLE,
                rsi_14 DOUBLE,
                sma_50_slope DOUBLE,
                vol_ma20 DOUBLE, vol_ma50 DOUBLE, vol_ratio_50 DOUBLE,
                dollar_volume_avg_20 DOUBLE, turnover DOUBLE, turnover_ma20 DOUBLE,
                atr_14 DOUBLE,
                return_1d DOUBLE, return_5d DOUBLE, return_20d DOUBLE, return_60d DOUBLE,
                breakout INTEGER, is_green_day INTEGER, green_days_ratio_20d DOUBLE, adr_20d DOUBLE,
                rs_velocity DOUBLE, volume_acceleration DOUBLE, breakout_momentum DOUBLE,
                consolidation_duration DOUBLE, price_momentum_curve DOUBLE,
                volume_velocity_2d DOUBLE, price_accel_10d DOUBLE, immediate_thrust DOUBLE,

                -- pct_chg deltas (required by v_d1_candidates which converts them to _delta names)
                price_vs_sma_50_pct_chg DOUBLE, price_vs_sma_150_pct_chg DOUBLE,
                price_vs_sma_200_pct_chg DOUBLE,
                rs_pct_chg DOUBLE, rs_ma_pct_chg DOUBLE, dry_up_volume_pct_chg DOUBLE,
                natr_pct_chg DOUBLE, atr_pct_chg DOUBLE, vcp_ratio_pct_chg DOUBLE,
                consolidation_width_pct_chg DOUBLE, rsi_14_pct_chg DOUBLE,
                dist_from_52w_high_pct_chg DOUBLE, dist_from_52w_low_pct_chg DOUBLE,
                low_52w_pct_chg DOUBLE, high_52w_pct_chg DOUBLE,
                dist_from_20d_high_pct_chg DOUBLE, dist_from_20d_low_pct_chg DOUBLE,
                lowest_low_20d_pct_chg DOUBLE, highest_high_20d_pct_chg DOUBLE,

                -- m01_prototype features: SQL-derived ratios/slopes (Group A)
                ema_8_21_ratio DOUBLE,
                ema_21_50_ratio DOUBLE,
                ema_50_100_ratio DOUBLE,
                mom_slope_21_63 DOUBLE,
                mom_slope_63_126 DOUBLE,
                sma_ratio_150_200 DOUBLE,
                gap_risk_ratio DOUBLE,

                -- m01_prototype features: vol-adjusted (Group B, Python-computed)
                price_vs_sma_50_vol_adj DOUBLE,
                mom_21d_vol_adj DOUBLE,

                -- Fundamentals (net_income, revenue, shares_outstanding, peg_adjusted)
                -- intentionally NOT stored here — joined at query time via fundamental_features
                -- and shares_history in v_d2_hydrated / v_d2_training. Storing them per (ticker, date)
                -- in T3 duplicated quarterly snapshots across thousands of trading days.

                -- TS alpha factors (per-ticker only)
                alpha006 DOUBLE, alpha009 DOUBLE, alpha012 DOUBLE, alpha041 DOUBLE,
                alpha046 DOUBLE, alpha049 DOUBLE, alpha051 DOUBLE, alpha054 DOUBLE,
                alpha101 DOUBLE,

                -- M03 regime (joined from t2_regime_scores)
                m03_score DOUBLE, m03_pillar_trend DOUBLE, m03_pillar_liq DOUBLE,
                m03_pillar_risk DOUBLE, m03_delta_5d DOUBLE, m03_delta_20d DOUBLE,
                m03_regime_vol DOUBLE,

                -- Metadata
                ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY (ticker, date, feature_version)
            )
        """)

    def compute_t3_features(self, start_date: str = '2020-01-01', end_date: str = None) -> int:
        """Compute T3 features densely over the SEPA-watchlist universe.

        Universe gate (Option C): a ticker is in T3 iff it has ever entered a SEPA
        session (i.e. appears in `sepa_watchlist`). T3 carries the ticker's full
        history regardless of current session status; cooldown gates new sessions
        in `sepa_watchlist`, not row inclusion in T3.

        `trend_ok` and `breakout_ok` are stored as explicit columns — neither is
        implicit. Filter downstream consumers explicitly:
          - entry candidates:   WHERE trend_ok = TRUE AND breakout_ok = TRUE
          - trend-active set:   WHERE trend_ok = TRUE
          - full universe:      no filter

        Sources:
        - Universe membership: SELECT DISTINCT ticker FROM sepa_watchlist
        - OHLCV + per-ticker window features: price_data (SQL CTEs, warmup via full history)
        - T2 carry-forward (SMAs, RS, ranks, XS alphas, trend_ok, breakout_ok): t2_screener_features
        - M03: joined from t2_regime_scores
        - TS alphas: computed in Python after SQL insert
        - Fundamentals (net_income, revenue, shares_outstanding, peg_adjusted):
          NOT stored here. Joined at query time in v_d2_hydrated / v_d2_training.
        """
        from datetime import date as date_cls
        if end_date is None:
            end_date = date_cls.today().strftime('%Y-%m-%d')

        # Warmup: fetch 365d before start for rolling windows
        fetch_start = (pd.to_datetime(start_date) - pd.Timedelta(days=365)).strftime('%Y-%m-%d')

        logger.info(f"[T3] Computing SEPA features for {start_date} to {end_date}...")
        con = db.connect(self.db_path)

        try:
            before_count = con.execute("SELECT COUNT(*) FROM t3_sepa_features").fetchone()[0]

            # Plain INSERT (no OR IGNORE): the caller (backfill wrapper / orchestrator)
            # is required to ensure the chunk's date range is empty in t3 before this
            # runs. INSERT OR IGNORE was paying a per-row PK-index probe whose cost grew
            # with total t3 size — turning per-quarter wall time into a function of
            # cumulative t3 rows instead of chunk size. With a guaranteed-empty target
            # window the index probe is wasted work; plain INSERT keeps wall time flat.
            con.execute(f"""
                INSERT INTO t3_sepa_features BY NAME
                WITH candidates AS (
                    -- Universe = sepa_watchlist (any ticker that ever entered a SEPA session)
                    -- UNION vip_watchlist (manually-curated names forced into T3 so the
                    -- pipeline reports their daily status even if they never pass the screen).
                    -- Carries full history for those tickers — gating happens at session level
                    -- inside sepa_watchlist, not via row inclusion in T3. VIP names are
                    -- forward-only in practice: they only appear in chunks run after they're
                    -- added (T3 is incremental per date-chunk), with the normal 200d warmup.
                    -- Date upper bound is critical: without it the t2 join below scans all
                    -- history per ticker (O(cumulative) per-chunk wall time).
                    SELECT p.ticker, p.date,
                        p.open, p.high, p.low, p.close,
                        CAST(p.volume AS BIGINT) as volume,
                        LAG(p.close, 1) OVER w_tk as prev_close
                    FROM {self.price_source} p
                    WHERE p.date >= '{fetch_start}'
                      AND p.date <= '{end_date}'
                      AND p.ticker IN (
                          SELECT ticker FROM sepa_watchlist
                          UNION
                          SELECT ticker FROM vip_watchlist WHERE active
                      )
                    WINDOW w_tk AS (PARTITION BY p.ticker ORDER BY p.date)
                ),
                per_ticker AS (
                    SELECT
                        c.ticker, c.date, c.open, c.high, c.low, c.close, c.volume,

                        -- Momentum
                        (c.close / NULLIF(LAG(c.close, 21)  OVER w_tk, 0) - 1) as mom_21d,
                        (c.close / NULLIF(LAG(c.close, 63)  OVER w_tk, 0) - 1) as mom_63d,
                        (c.close / NULLIF(LAG(c.close, 126) OVER w_tk, 0) - 1) as mom_126d,
                        (c.close / NULLIF(LAG(c.close, 189) OVER w_tk, 0) - 1) as mom_189d,
                        (c.close / NULLIF(LAG(c.close, 252) OVER w_tk, 0) - 1) as mom_252d,

                        -- Returns
                        (c.close / NULLIF(c.prev_close, 0) - 1) as return_1d,
                        (c.close / NULLIF(LAG(c.close, 5)  OVER w_tk, 0) - 1) as return_5d,
                        (c.close / NULLIF(LAG(c.close, 20) OVER w_tk, 0) - 1) as return_20d,
                        (c.close / NULLIF(LAG(c.close, 60) OVER w_tk, 0) - 1) as return_60d,

                        -- Volume depth
                        AVG(CAST(c.volume AS BIGINT)) OVER w20 as vol_ma20,
                        AVG(CAST(c.volume AS BIGINT)) OVER w50 as vol_ma50,
                        CAST(c.volume AS BIGINT) / NULLIF(AVG(CAST(c.volume AS BIGINT)) OVER w50, 0) as vol_ratio_50,
                        AVG(c.close * CAST(c.volume AS BIGINT)) OVER w20 as dollar_volume_avg_20,
                        CAST(c.volume AS BIGINT) / NULLIF(c.close * 1e6, 0) as turnover,
                        AVG(CAST(c.volume AS BIGINT) / NULLIF(c.close * 1e6, 0)) OVER w20 as turnover_ma20,

                        -- ATR14 (needed for breakout_momentum)
                        AVG(GREATEST(c.high - c.low,
                            ABS(c.high - c.prev_close),
                            ABS(c.low  - c.prev_close))) OVER w14 as atr_14,

                        -- RSI 14
                        AVG(CASE WHEN c.close > c.prev_close THEN c.close - c.prev_close ELSE 0 END) OVER w14
                            / NULLIF(AVG(CASE WHEN c.close < c.prev_close THEN c.prev_close - c.close ELSE 0 END) OVER w14, 0)
                            as rsi_rs,

                        -- Pattern flags
                        CASE WHEN c.close > MAX(c.close) OVER (PARTITION BY c.ticker ORDER BY c.date
                            ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) THEN 1 ELSE 0 END as breakout,
                        CASE WHEN c.close >= c.prev_close THEN 1 ELSE 0 END as is_green_day,
                        AVG(CASE WHEN c.close >= c.prev_close THEN 1.0 ELSE 0.0 END) OVER w20 as green_days_ratio_20d,
                        AVG((c.high - c.low) / NULLIF(c.prev_close, 0)) OVER w20 as adr_20d,

                        -- Velocity features (depend on atr_14 — computed in next CTE)
                        LAG(c.close, 5) OVER w_tk as close_lag5

                    FROM candidates c
                    WINDOW
                        w_tk AS (PARTITION BY c.ticker ORDER BY c.date),
                        w14  AS (PARTITION BY c.ticker ORDER BY c.date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),
                        w20  AS (PARTITION BY c.ticker ORDER BY c.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
                        w50  AS (PARTITION BY c.ticker ORDER BY c.date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW)
                ),
                with_velocity AS (
                    SELECT pt.*,
                        100.0 / (1.0 + NULLIF(rsi_rs, -1)) as rsi_14,

                        -- pct_chg deltas (required by v_d1_candidates)
                        (t2.price_vs_sma_50  - LAG(t2.price_vs_sma_50,  1) OVER w_tk) / NULLIF(ABS(LAG(t2.price_vs_sma_50,  1) OVER w_tk), 0) * 100 as price_vs_sma_50_pct_chg,
                        (t2.price_vs_sma_150 - LAG(t2.price_vs_sma_150, 1) OVER w_tk) / NULLIF(ABS(LAG(t2.price_vs_sma_150, 1) OVER w_tk), 0) * 100 as price_vs_sma_150_pct_chg,
                        (t2.price_vs_sma_200 - LAG(t2.price_vs_sma_200, 1) OVER w_tk) / NULLIF(ABS(LAG(t2.price_vs_sma_200, 1) OVER w_tk), 0) * 100 as price_vs_sma_200_pct_chg,
                        (t2.rs      - LAG(t2.rs,      1) OVER w_tk) / NULLIF(ABS(LAG(t2.rs,      1) OVER w_tk), 0) * 100 as rs_pct_chg,
                        (t2.rs_ma   - LAG(t2.rs_ma,   1) OVER w_tk) / NULLIF(ABS(LAG(t2.rs_ma,   1) OVER w_tk), 0) * 100 as rs_ma_pct_chg,
                        (t2.dry_up_volume - LAG(t2.dry_up_volume, 1) OVER w_tk) / NULLIF(ABS(LAG(t2.dry_up_volume, 1) OVER w_tk), 0) * 100 as dry_up_volume_pct_chg,
                        (t2.natr    - LAG(t2.natr,    1) OVER w_tk) / NULLIF(ABS(LAG(t2.natr,    1) OVER w_tk), 0) * 100 as natr_pct_chg,
                        (t2.atr_20d - LAG(t2.atr_20d, 1) OVER w_tk) / NULLIF(ABS(LAG(t2.atr_20d, 1) OVER w_tk), 0) * 100 as atr_pct_chg,
                        (t2.vcp_ratio - LAG(t2.vcp_ratio, 1) OVER w_tk) / NULLIF(ABS(LAG(t2.vcp_ratio, 1) OVER w_tk), 0) * 100 as vcp_ratio_pct_chg,
                        (t2.consolidation_width - LAG(t2.consolidation_width, 1) OVER w_tk) / NULLIF(ABS(LAG(t2.consolidation_width, 1) OVER w_tk), 0) * 100 as consolidation_width_pct_chg,
                        CASE WHEN t2.dist_from_52w_high = LAG(t2.dist_from_52w_high, 1) OVER w_tk THEN 0.0
                             WHEN LAG(t2.dist_from_52w_high, 1) OVER w_tk = 0.0
                               THEN (t2.dist_from_52w_high - LAG(t2.dist_from_52w_high, 1) OVER w_tk) * 100
                             ELSE (t2.dist_from_52w_high - LAG(t2.dist_from_52w_high, 1) OVER w_tk) / ABS(LAG(t2.dist_from_52w_high, 1) OVER w_tk) * 100
                        END as dist_from_52w_high_pct_chg,
                        (t2.dist_from_52w_low  - LAG(t2.dist_from_52w_low,  1) OVER w_tk) / NULLIF(ABS(LAG(t2.dist_from_52w_low,  1) OVER w_tk), 0) * 100 as dist_from_52w_low_pct_chg,
                        (t2.low_52w  - LAG(t2.low_52w,  1) OVER w_tk) / NULLIF(ABS(LAG(t2.low_52w,  1) OVER w_tk), 0) * 100 as low_52w_pct_chg,
                        (t2.high_52w - LAG(t2.high_52w, 1) OVER w_tk) / NULLIF(ABS(LAG(t2.high_52w, 1) OVER w_tk), 0) * 100 as high_52w_pct_chg,
                        CASE WHEN t2.dist_from_20d_high = LAG(t2.dist_from_20d_high, 1) OVER w_tk THEN 0.0
                             WHEN LAG(t2.dist_from_20d_high, 1) OVER w_tk = 0.0
                               THEN (t2.dist_from_20d_high - LAG(t2.dist_from_20d_high, 1) OVER w_tk) * 100
                             ELSE (t2.dist_from_20d_high - LAG(t2.dist_from_20d_high, 1) OVER w_tk) / ABS(LAG(t2.dist_from_20d_high, 1) OVER w_tk) * 100
                        END as dist_from_20d_high_pct_chg,
                        (t2.dist_from_20d_low    - LAG(t2.dist_from_20d_low,    1) OVER w_tk) / NULLIF(ABS(LAG(t2.dist_from_20d_low,    1) OVER w_tk), 0) * 100 as dist_from_20d_low_pct_chg,
                        (t2.lowest_low_20d  - LAG(t2.lowest_low_20d,  1) OVER w_tk) / NULLIF(ABS(LAG(t2.lowest_low_20d,  1) OVER w_tk), 0) * 100 as lowest_low_20d_pct_chg,
                        (t2.highest_high_20d - LAG(t2.highest_high_20d, 1) OVER w_tk) / NULLIF(ABS(LAG(t2.highest_high_20d, 1) OVER w_tk), 0) * 100 as highest_high_20d_pct_chg,

                        -- rsi_14 pct_chg
                        (100.0 / (1.0 + NULLIF(pt.rsi_rs, -1))
                            - LAG(100.0 / (1.0 + NULLIF(pt.rsi_rs, -1)), 1) OVER w_tk)
                            / NULLIF(ABS(LAG(100.0 / (1.0 + NULLIF(pt.rsi_rs, -1)), 1) OVER w_tk), 0) * 100 as rsi_14_pct_chg,

                        -- m01_prototype Group A: EMA ratios (slope of MA stack, scale-free %)
                        (t2.ema_8  / NULLIF(t2.ema_21,  0) - 1) * 100 as ema_8_21_ratio,
                        (t2.ema_21 / NULLIF(t2.ema_50,  0) - 1) * 100 as ema_21_50_ratio,
                        (t2.ema_50 / NULLIF(t2.ema_100, 0) - 1) * 100 as ema_50_100_ratio,

                        -- m01_prototype Group A: momentum slope diffs (acceleration/deceleration)
                        pt.mom_21d - pt.mom_63d  as mom_slope_21_63,
                        pt.mom_63d - pt.mom_126d as mom_slope_63_126,

                        -- m01_prototype Group A: SMA stack ratio (sma_200/sma_150 expressed in price-vs-MA space)
                        ((t2.price_vs_sma_200 + 100) / NULLIF(t2.price_vs_sma_150 + 100, 0) - 1) * 100 as sma_ratio_150_200,

                        -- m01_prototype Group A: gap risk (intraday vol vs avg daily range)
                        t2.natr / NULLIF(pt.adr_20d, 0) as gap_risk_ratio,

                        -- SMA50 slope: uses t2.sma_50 (avoids nested window functions)
                        (t2.sma_50 - LAG(t2.sma_50, 5) OVER w_tk) / 5.0 as sma_50_slope,

                        -- RS line lag delta (LAG of rs_line_delta from T2)
                        LAG(t2.rs_line_delta, 1) OVER w_tk as rs_line_lag_delta,

                        -- Velocity (need atr_14 from pt)
                        (t2.rs_rating - LAG(t2.rs_rating, 5) OVER w_tk) / 5.0 as rs_velocity,
                        (pt.volume - LAG(pt.volume, 1) OVER w_tk)
                            - (LAG(pt.volume, 1) OVER w_tk - LAG(pt.volume, 2) OVER w_tk) as volume_acceleration,
                        CASE WHEN pt.atr_14 > 0
                            THEN (pt.close - t2.high_20d) / pt.atr_14
                            ELSE 0 END as breakout_momentum,
                        SUM(CASE WHEN (pt.high - pt.low) < 0.5 * pt.atr_14 THEN 1 ELSE 0 END)
                            OVER (PARTITION BY pt.ticker ORDER BY pt.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
                            as consolidation_duration,
                        (pt.close - LAG(pt.close, 1) OVER w_tk)
                            - (LAG(pt.close, 1) OVER w_tk - LAG(pt.close, 2) OVER w_tk) as price_momentum_curve,
                        LN(NULLIF(pt.volume, 0)) - LAG(LN(NULLIF(pt.volume, 0)), 2) OVER w_tk as volume_velocity_2d,
                        ((pt.close - pt.close_lag5) / 5.0)
                            - ((pt.close_lag5 - LAG(pt.close, 10) OVER w_tk) / 5.0) as price_accel_10d,
                        pt.close - 2 * LAG(pt.close, 1) OVER w_tk + LAG(pt.close, 2) OVER w_tk as immediate_thrust

                    FROM per_ticker pt
                    INNER JOIN t2_screener_features t2
                        ON pt.ticker = t2.ticker AND pt.date = t2.date
                       AND t2.date BETWEEN '{fetch_start}' AND '{end_date}'
                    WINDOW w_tk AS (PARTITION BY pt.ticker ORDER BY pt.date)
                )
                SELECT
                    wv.ticker, wv.date, '{self.feature_version}' as feature_version,
                    wv.open, wv.high, wv.low, wv.close, wv.volume,
                    -- t2 carry-forward
                    t2.sma_20, t2.sma_50, t2.sma_150, t2.sma_200, t2.sma_200_lag20,
                    t2.price_vs_sma_50, t2.price_vs_sma_150, t2.price_vs_sma_200, t2.close_above_sma200,
                    t2.price_vs_spy, t2.price_vs_spy_ma63,
                    t2.rs_rating, t2.rs, t2.rs_ma, t2.rs_line_log, t2.rs_line_delta, t2.rs_line_uptrend,
                    t2.high_52w, t2.low_52w, t2.dist_from_52w_high, t2.dist_from_52w_low,
                    t2.pct_from_high_52w, t2.pct_above_low_52w,
                    t2.high_20d, t2.lowest_low_20d, t2.highest_high_20d, t2.dist_from_20d_high, t2.dist_from_20d_low,
                    t2.vol_avg_20, t2.vol_avg_50, t2.vol_ratio, t2.dry_up_volume,
                    t2.atr_20d, t2.natr, t2.volatility_20d, t2.vcp_ratio, t2.consolidation_width,
                    t2.trend_ok, t2.breakout_ok,
                    t2.RS_Universe_Rank, t2.RS_Sector_Rank, t2.RS_vs_Sector, t2.Sector_Momentum,
                    t2.RS_Industry_Rank, t2.RS_vs_Industry, t2.Industry_Momentum,
                    t2.alpha001, t2.alpha002, t2.alpha004, t2.alpha008, t2.alpha011,
                    t2.alpha013, t2.alpha015, t2.alpha019, t2.alpha060,
                    t2.ema_8, t2.ema_21, t2.ema_50, t2.ema_100, t2.ema_200,
                    wv.rs_line_lag_delta,
                    -- per-ticker window features
                    wv.mom_21d, wv.mom_63d, wv.mom_126d, wv.mom_189d, wv.mom_252d,
                    wv.rsi_14, wv.sma_50_slope,
                    wv.vol_ma20, wv.vol_ma50, wv.vol_ratio_50, wv.dollar_volume_avg_20,
                    wv.turnover, wv.turnover_ma20, wv.atr_14,
                    wv.return_1d, wv.return_5d, wv.return_20d, wv.return_60d,
                    wv.breakout, wv.is_green_day, wv.green_days_ratio_20d, wv.adr_20d,
                    wv.rs_velocity, wv.volume_acceleration, wv.breakout_momentum,
                    wv.consolidation_duration, wv.price_momentum_curve,
                    wv.volume_velocity_2d, wv.price_accel_10d, wv.immediate_thrust,
                    -- pct_chg deltas
                    wv.price_vs_sma_50_pct_chg, wv.price_vs_sma_150_pct_chg, wv.price_vs_sma_200_pct_chg,
                    wv.rs_pct_chg, wv.rs_ma_pct_chg, wv.dry_up_volume_pct_chg,
                    wv.natr_pct_chg, wv.atr_pct_chg, wv.vcp_ratio_pct_chg, wv.consolidation_width_pct_chg,
                    wv.rsi_14_pct_chg, wv.dist_from_52w_high_pct_chg, wv.dist_from_52w_low_pct_chg,
                    wv.low_52w_pct_chg, wv.high_52w_pct_chg, wv.dist_from_20d_high_pct_chg,
                    wv.dist_from_20d_low_pct_chg, wv.lowest_low_20d_pct_chg, wv.highest_high_20d_pct_chg,
                    -- m01_prototype Group A
                    wv.ema_8_21_ratio, wv.ema_21_50_ratio, wv.ema_50_100_ratio,
                    wv.mom_slope_21_63, wv.mom_slope_63_126,
                    wv.sma_ratio_150_200, wv.gap_risk_ratio,
                    -- M03 regime
                    r.m03_score, r.m03_pillar_trend, r.m03_pillar_liq, r.m03_pillar_risk,
                    r.m03_delta_5d, r.m03_delta_20d, r.m03_regime_vol
                FROM with_velocity wv
                LEFT JOIN t2_screener_features t2
                    ON wv.ticker = t2.ticker AND wv.date = t2.date
                LEFT JOIN t2_regime_scores r
                    ON wv.date = r.date
                WHERE wv.date BETWEEN '{start_date}' AND '{end_date}'
            """)

            after_count = con.execute("SELECT COUNT(*) FROM t3_sepa_features").fetchone()[0]
            inserted = after_count - before_count
            ticker_count = con.execute(
                f"SELECT COUNT(DISTINCT ticker) FROM t3_sepa_features WHERE date BETWEEN '{start_date}' AND '{end_date}'"
            ).fetchone()[0]
            logger.info(f"[T3] Inserted {inserted:,} SEPA rows ({ticker_count} tickers)")

            # Tripwire: catch INSERT/SELECT column-list drift early. The DDL, INSERT list,
            # and SELECT list must all align — a silent shift would corrupt every column
            # downstream. Update EXPECTED_T3_COLUMN_COUNT alongside any DDL change.
            actual_cols = con.execute(
                "SELECT COUNT(*) FROM information_schema.columns WHERE table_name='t3_sepa_features'"
            ).fetchone()[0]
            if actual_cols != EXPECTED_T3_COLUMN_COUNT:
                raise RuntimeError(
                    f"t3_sepa_features column count mismatch: expected {EXPECTED_T3_COLUMN_COUNT}, got {actual_cols}. "
                    "Schema drift detected — DDL, INSERT list, and EXPECTED_T3_COLUMN_COUNT must stay in sync."
                )

        except Exception as e:
            logger.error(f"T3 feature computation failed: {e}")
            raise
        finally:
            con.close()

        # Group B (m01_prototype): vol-adjusted features — needs return_1d history,
        # so runs after the SQL INSERT populates the base columns.
        self._compute_vol_adjusted_features(start_date=start_date, end_date=end_date)

        # TS alphas — per-ticker rolling windows; load history from t2 (continuous),
        # but write results back only to t3 rows (via UPDATE WHERE ticker+date match).
        # Scope the writeback to the chunk window — without end_date, write_df spans
        # [start_date, MAX(t2.date)] and corrupts every later chunk already in t3.
        self.compute_alpha_features(
            start_date=start_date,
            end_date=end_date,
            warmup_days=365,
            target_table='t3_sepa_features',
            alpha_cols=ALPHA_COLS_TS,
            warmup_table='t2_screener_features',
        )

        return inserted

    def _compute_vol_adjusted_features(self, start_date: str, end_date: str) -> None:
        """Compute price_vs_sma_50_vol_adj and mom_21d_vol_adj per-ticker.

        Both features divide a position metric by the rolling std of return_1d.
        return_1d is pulled from price_data (continuous history) so the rolling
        windows seed properly even when t3 only covers a short range. Numerator
        columns (price_vs_sma_50, mom_21d) come from t2 — also continuous — so
        we can compute the ratio for every (ticker, date), then write back only
        rows that exist in t3 via the existing UPDATE pattern.
        """
        VOL_ADJ_COLS = ['price_vs_sma_50_vol_adj', 'mom_21d_vol_adj']
        logger.info(f"[B-VolAdj] Computing {VOL_ADJ_COLS} for {start_date}..{end_date}")

        # 90-day warmup is plenty for 50d rolling std (need ~50 trading days = ~70 calendar days)
        fetch_start = (pd.to_datetime(start_date) - pd.Timedelta(days=90)).strftime('%Y-%m-%d')

        con = db.connect(self.db_path)
        try:
            df = con.execute(f"""
                SELECT
                    p.ticker,
                    p.date,
                    t2.price_vs_sma_50,
                    (p.close / NULLIF(LAG(p.close, 1) OVER (PARTITION BY p.ticker ORDER BY p.date), 0) - 1) AS return_1d,
                    (p.close / NULLIF(LAG(p.close, 21) OVER (PARTITION BY p.ticker ORDER BY p.date), 0) - 1) AS mom_21d
                FROM {self.price_source} p
                INNER JOIN t2_screener_features t2
                    ON p.ticker = t2.ticker AND p.date = t2.date
                WHERE p.date >= '{fetch_start}' AND p.date <= '{end_date}'
                ORDER BY p.ticker, p.date
            """).df()
        finally:
            con.close()

        if df.empty:
            logger.warning("[B-VolAdj] No data loaded — skipping")
            return

        ret_groups = df.groupby('ticker')['return_1d']
        std_50 = ret_groups.transform(lambda s: s.rolling(50, min_periods=20).std())
        std_21 = ret_groups.transform(lambda s: s.rolling(21, min_periods=10).std())
        df['price_vs_sma_50_vol_adj'] = df['price_vs_sma_50'] / std_50.replace(0, np.nan)
        df['mom_21d_vol_adj'] = df['mom_21d'] / std_21.replace(0, np.nan)

        for col in VOL_ADJ_COLS:
            df[col] = df[col].replace([np.inf, -np.inf], np.nan)

        start_dt = pd.to_datetime(start_date)
        write_df = df[df['date'] >= start_dt][['ticker', 'date'] + VOL_ADJ_COLS]
        if write_df.empty:
            logger.warning("[B-VolAdj] No rows in target window — skipping write")
            return

        self._write_alpha_columns(write_df, 't3_sepa_features', VOL_ADJ_COLS)
        logger.info(f"[OK] [B-VolAdj] Wrote {len(write_df):,} rows")

    # ------------------------------------------------------------------
    # Phase B: Python alpha factors (kept for reference — called from compute_t2 and compute_t3)
    # ------------------------------------------------------------------

    def compute_base_features(self, start_date: str = '2020-01-01', warmup_days: int = 365) -> int:
        raise NotImplementedError("compute_base_features removed. Use compute_t2_screener_features + compute_t3_features.")

    # ------------------------------------------------------------------
    # Phase B-EMA: Exponential Moving Averages (Python pandas.ewm)
    # ------------------------------------------------------------------

    def compute_ema_features(
        self,
        start_date: str = '2020-01-01',
        warmup_days: int = 365,
        end_date: str = None,
        target_table: str = 't2_screener_features',
    ) -> None:
        """Compute EMA columns via pandas ewm() and write back to target table.

        Uses the same load/write pattern as compute_alpha_features.
        """
        logger.info(f"[B-EMA] Computing EMAs ({EMA_SPANS}) -> {target_table} (start={start_date}, warmup={warmup_days}d)...")

        self._ensure_alpha_columns_exist(target_table, EMA_COLS)

        con = db.connect(self.db_path)
        fetch_start = (pd.to_datetime(start_date) - pd.Timedelta(days=warmup_days)).strftime('%Y-%m-%d')
        end_filter = f"AND p.date <= '{end_date}'" if end_date else ""
        try:
            df = con.execute(f"""
                SELECT p.ticker, p.date, p.close
                FROM {self.price_source} p
                INNER JOIN {target_table} t ON p.ticker = t.ticker AND p.date = t.date
                WHERE p.date >= '{fetch_start}' {end_filter}
                ORDER BY p.ticker, p.date
            """).df()
        finally:
            con.close()

        if df.empty:
            logger.warning("[B-EMA] No data loaded for EMA computation")
            return

        for span in EMA_SPANS:
            df[f'ema_{span}'] = df.groupby('ticker')['close'].transform(
                lambda x: x.ewm(span=span, adjust=False).mean()
            )

        # Trim warmup rows
        start_dt = pd.to_datetime(start_date)
        write_df = df[df['date'] >= start_dt][['ticker', 'date'] + EMA_COLS]
        if end_date:
            write_df = write_df[write_df['date'] <= pd.to_datetime(end_date)]

        self._write_alpha_columns(write_df, target_table, EMA_COLS)
        logger.info(f"[OK] [B-EMA] Computed {len(EMA_COLS)} EMAs ({len(write_df):,} rows written)")

    # ------------------------------------------------------------------
    # Phase B: Python alpha factors
    # ------------------------------------------------------------------

    def compute_alpha_features(
        self,
        start_date: str = '2020-01-01',
        warmup_days: int = 365,
        end_date: str = None,
        target_table: str = 't2_screener_features',
        alpha_cols: Optional[List[str]] = None,
        warmup_table: Optional[str] = None,
    ) -> None:
        import os
        from multiprocessing import Pool, cpu_count
        from functools import partial
        from tqdm import tqdm

        warmup_table = warmup_table or target_table
        logger.info(f"[B] Computing alpha factors -> {target_table} (start={start_date}, warmup={warmup_days}d)...")

        # 1. Load data — ticker filter from warmup_table (broader set for TS alphas on t3)
        df = self._load_data_for_alphas(start_date, warmup_days=warmup_days, end_date=end_date, target_table=warmup_table)
        if df.empty:
            logger.warning("[B] No data loaded for alpha computation")
            return

        self._ensure_alpha_columns_exist(target_table, alpha_cols or ALPHA_COLS)

        # 2. Pre-compute intermediates used by multiple alphas
        df['vwap'] = (df['high'] + df['low'] + df['close']) / 3.0
        df['delta_close_1'] = df.groupby('ticker')['close'].diff(1)
        df['delta_vol_1'] = df.groupby('ticker')['volume'].diff(1)
        df['close_lag10'] = df.groupby('ticker')['close'].shift(10)
        df['close_lag20'] = df.groupby('ticker')['close'].shift(20)
        df['wq_returns'] = df.groupby('ticker')['close'].pct_change(1) * 100

        # Cross-sectional rank: rank across tickers on the same date (WQ101 intent for rank())
        for col in ['low', 'close', 'high', 'volume']:
            df[f'rank_{col}'] = df.groupby('date')[col].rank(pct=True)

        # Additional intermediates for alpha008 and alpha019
        df['open_sum5'] = df.groupby('ticker')['open'].transform(lambda x: x.rolling(5).sum())
        df['returns_sum5'] = df.groupby('ticker')['wq_returns'].transform(lambda x: x.rolling(5).sum())
        df['returns_sum250'] = df.groupby('ticker')['wq_returns'].transform(lambda x: x.rolling(250).sum())

        # 3. Define alpha tasks
        # Full registry — XS first (cross-sectional), then TS (time-series)
        all_alphas = [
            ('alpha001', self._alpha001), ('alpha002', self._alpha002),
            ('alpha004', self._alpha004), ('alpha008', self._alpha008),
            ('alpha011', self._alpha011), ('alpha013', self._alpha013),
            ('alpha015', self._alpha015), ('alpha019', self._alpha019),
            ('alpha060', self._alpha060),
            ('alpha006', self._alpha006), ('alpha009', self._alpha009),
            ('alpha012', self._alpha012), ('alpha041', self._alpha041),
            ('alpha046', self._alpha046), ('alpha049', self._alpha049),
            ('alpha051', self._alpha051), ('alpha054', self._alpha054),
            ('alpha101', self._alpha101),
        ]
        requested = set(alpha_cols or ALPHA_COLS)
        alphas_to_run = [(n, f) for n, f in all_alphas if n in requested]

        # 4. Determine worker count (env var for tuning, default: cpu_count - 1, cap at 8)
        n_workers = int(os.getenv('ALPHA_WORKERS', min(cpu_count() - 1, 8)))
        use_parallel = os.getenv('USE_PARALLEL_ALPHAS', '1') == '1'

        alpha_results = pd.DataFrame({'ticker': df['ticker'], 'date': df['date']})

        # 5. Parallel or sequential execution
        if use_parallel and n_workers > 1:
            logger.info(f"[B] Running {len(alphas_to_run)} alphas on {n_workers} workers...")
            with Pool(processes=n_workers) as pool:
                # Use partial to pass df to all workers
                compute_func = partial(_compute_single_alpha_wrapper, df=df)

                # Map alphas to workers (with progress bar)
                with tqdm(total=len(alphas_to_run), desc="   [B] Alphas", unit="fact") as pbar:
                    for name, result in pool.imap_unordered(compute_func, alphas_to_run):
                        alpha_results[name] = result
                        pbar.update(1)
        else:
            # Sequential fallback (for debugging or single-core machines)
            logger.info(f"[B] Running {len(alphas_to_run)} alphas sequentially (USE_PARALLEL_ALPHAS=0 or n_workers=1)...")
            with tqdm(total=len(alphas_to_run), desc="   [B] Alphas", unit="fact") as pbar:
                for name, func in alphas_to_run:
                    alpha_results[name] = func(df)
                    pbar.update(1)

        # 6. Sanitize
        cols_computed = [name for name, _ in alphas_to_run]
        for col in cols_computed:
            alpha_results[col] = self._sanitize_alpha(alpha_results[col], col)

        # 7. Write back to DB — trim warmup rows to avoid unnecessary UPDATEs
        start_dt = pd.to_datetime(start_date)
        write_df = alpha_results[alpha_results['date'] >= start_dt]
        if end_date:
            write_df = write_df[write_df['date'] <= pd.to_datetime(end_date)]
        self._write_alpha_columns(write_df, target_table, cols_computed)
        logger.info(f"[OK] [B] Computed {len(cols_computed)} alpha factors ({len(write_df):,} rows written, {len(alpha_results):,} computed)")

    def _load_data_for_alphas(
        self, start_date: str, warmup_days: int = 365, end_date: str = None, target_table: str = 't2_screener_features'
    ) -> pd.DataFrame:
        con = db.connect(self.db_path)
        fetch_start_date = (pd.to_datetime(start_date) - pd.Timedelta(days=warmup_days)).strftime('%Y-%m-%d')
        end_filter = f"AND p.date <= '{end_date}'" if end_date else ""
        try:
            df = con.execute(f"""
                SELECT p.ticker, p.date,
                    p.open, p.high, p.low, p.close,
                    CAST(p.volume AS BIGINT) as volume
                FROM {self.price_source} p
                INNER JOIN {target_table} t ON p.ticker = t.ticker AND p.date = t.date
                WHERE p.date >= '{fetch_start_date}' {end_filter}
                ORDER BY p.ticker, p.date
            """).df()
            return df
        finally:
            con.close()

    def _ensure_alpha_columns_exist(self, target_table: str, cols: List[str]) -> None:
        con = db.connect(self.db_path)
        try:
            existing = {r[0] for r in con.execute(f"DESCRIBE {target_table}").fetchall()}
            for col in cols:
                if col not in existing:
                    con.execute(f"ALTER TABLE {target_table} ADD COLUMN {col} DOUBLE")
        finally:
            con.close()

    def _write_alpha_columns(self, alpha_df: pd.DataFrame, target_table: str, cols: List[str]) -> None:
        """Direct UPDATE FROM — scoped by date range so cost is O(chunk).

        Replaces the old DELETE+INSERT-via-temp pattern that risked PK collisions
        when the source df contained duplicate keys or DuckDB's UPDATE-FROM
        multiplied chunk rows under specific transaction states.
        """
        if alpha_df.empty:
            return
        con = db.connect(self.db_path)
        try:
            min_date = alpha_df['date'].min()
            max_date = alpha_df['date'].max()
            con.register('alpha_src', alpha_df)
            set_clause = ', '.join(f"{c} = src.{c}" for c in cols)
            con.execute(f"""
                UPDATE {target_table} t
                SET {set_clause}
                FROM alpha_src src
                WHERE t.ticker = src.ticker
                  AND t.date = src.date
                  AND t.date BETWEEN '{min_date}' AND '{max_date}'
            """)
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Alpha helper functions (staticmethod for multiprocessing)
    # ------------------------------------------------------------------

    @staticmethod
    def _ts_rank(series: pd.Series, window: int) -> pd.Series:
        """Rolling rank: position of current value within its rolling window, as fraction."""
        def _rank_in_window(x):
            return (np.sum(x[-1] > x[:-1]) + 1.0) / len(x)
        return series.rolling(window, min_periods=2).apply(_rank_in_window, raw=True)

    @staticmethod
    def _ts_argmax(series: pd.Series, window: int) -> pd.Series:
        """Position of maximum value in rolling window (1-indexed)."""
        return series.rolling(window, min_periods=window).apply(
            lambda x: np.argmax(x) + 1, raw=True
        )

    @staticmethod
    def _scale(series: pd.Series) -> pd.Series:
        """Normalize so sum(abs(series)) = 1."""
        denom = series.abs().sum()
        if denom == 0:
            return series * 0.0
        return series / denom

    @staticmethod
    def _sanitize_alpha(series: pd.Series, name: str) -> pd.Series:
        series = series.replace([np.inf, -np.inf], np.nan)
        series = series.fillna(0)
        if len(series) > 0:
            upper = series.quantile(0.999)
            lower = series.quantile(0.001)
            series = series.clip(lower, upper)
        return series

    # ------------------------------------------------------------------
    # 16 Alpha implementations (staticmethod for multiprocessing)
    # ------------------------------------------------------------------

    @staticmethod
    def _alpha001(df: pd.DataFrame) -> pd.Series:
        """rank(ts_argmax(returns<0 ? stddev(ret,20)^2 : close^2, 5)) — cross-sectional outer rank"""
        def _per_ticker(g):
            ret = g['wq_returns']
            std_20 = ret.rolling(20).std()
            inner = g['close'] ** 2
            inner = inner.copy()
            inner[ret < 0] = std_20[ret < 0] ** 2
            return FeaturePipeline._ts_argmax(inner, 5)   # raw ts_argmax, no rank here
        raw = df.groupby('ticker', group_keys=False).apply(_per_ticker, include_groups=False)
        return raw.groupby(df['date']).rank(pct=True)   # cross-sectional rank across tickers

    @staticmethod
    def _alpha002(df: pd.DataFrame) -> pd.Series:
        """-1 * corr(rank(delta(log(vol),2)), rank((close-open)/open), 6) — ranks are cross-sectional"""
        # Compute raw per-ticker values first, then cross-sectional rank across tickers per date
        delta_log_vol_2 = df.groupby('ticker')['volume'].transform(
            lambda x: np.log(x.replace(0, np.nan)).diff(2))
        close_open_ratio = (df['close'] - df['open']) / df['open'].replace(0, np.nan)
        # Cross-sectional rank on each date
        rank_dlv = delta_log_vol_2.groupby(df['date']).rank(pct=True)
        rank_cor = close_open_ratio.groupby(df['date']).rank(pct=True)
        # Rolling correlation is per-ticker
        corr_result = rank_dlv.groupby(df['ticker']).transform(
            lambda x: x.rolling(6).corr(rank_cor.loc[x.index]))
        return -1.0 * corr_result

    @staticmethod
    def _alpha004(df: pd.DataFrame) -> pd.Series:
        """-1 * ts_rank(rank(low), 9) — inner rank(low) is cross-sectional"""
        # rank_low is already cross-sectional (groupby date), ts_rank is per-ticker rolling
        def _per_ticker(g):
            return -1.0 * FeaturePipeline._ts_rank(g['rank_low'], 9)
        return df.groupby('ticker', group_keys=False).apply(_per_ticker, include_groups=False)

    @staticmethod
    def _alpha006(df: pd.DataFrame) -> pd.Series:
        """-1 * corr(open, volume, 10)"""
        vol_float = df['volume'].astype(float)
        return -1.0 * df.groupby('ticker')['open'].transform(
            lambda x: x.rolling(10).corr(vol_float.loc[x.index]))

    @staticmethod
    def _alpha009(df: pd.DataFrame) -> pd.Series:
        """Conditional on min/max of delta(close,1) over 5d."""
        dc = df['delta_close_1']
        min_5 = df.groupby('ticker')['delta_close_1'].transform(lambda x: x.rolling(5).min())
        max_5 = df.groupby('ticker')['delta_close_1'].transform(lambda x: x.rolling(5).max())
        result = -1.0 * dc
        cond = (min_5 > 0) | (max_5 < 0)
        result = result.where(~cond, dc)
        return result

    @staticmethod
    def _alpha008(df: pd.DataFrame) -> pd.Series:
        """-1 * rank((sum(open,5)*sum(returns,5)) - delay(...,10)) — cross-sectional rank of momentum"""
        raw = (df['open_sum5'] * df['returns_sum5']) - (df['open_sum5'] * df['returns_sum5']).groupby(df['ticker']).shift(10)
        return -1.0 * raw.groupby(df['date']).rank(pct=True)

    @staticmethod
    def _alpha011(df: pd.DataFrame) -> pd.Series:
        """(rank(ts_max(vwap-close,3)) + rank(ts_min(vwap-close,3))) * rank(delta(vol,3)) — cross-sectional ranks"""
        vc = df['vwap'] - df['close']
        ts_max_vals = vc.groupby(df['ticker']).transform(lambda x: x.rolling(3).max())
        ts_min_vals = vc.groupby(df['ticker']).transform(lambda x: x.rolling(3).min())
        delta_vol   = df.groupby('ticker')['volume'].transform(lambda x: x.diff(3))
        rank_max  = ts_max_vals.groupby(df['date']).rank(pct=True)
        rank_min  = ts_min_vals.groupby(df['date']).rank(pct=True)
        rank_dvol = delta_vol.groupby(df['date']).rank(pct=True)
        return (rank_max + rank_min) * rank_dvol

    @staticmethod
    def _alpha012(df: pd.DataFrame) -> pd.Series:
        """sign(delta(vol,1)) * (-1 * delta(close,1))"""
        return np.sign(df['delta_vol_1']) * (-1.0 * df['delta_close_1'])

    @staticmethod
    def _alpha013(df: pd.DataFrame) -> pd.Series:
        """-1 * rank(cov(rank(close), rank(volume), 5)) — inner ranks and outer rank are cross-sectional"""
        cov_raw = df.groupby('ticker')['rank_close'].transform(
            lambda x: x.rolling(5).cov(df.loc[x.index, 'rank_volume']))
        return -1.0 * cov_raw.groupby(df['date']).rank(pct=True)

    @staticmethod
    def _alpha015(df: pd.DataFrame) -> pd.Series:
        """-1 * sum(rank(corr(rank(high), rank(volume), 3)), 3) — inner and outer ranks cross-sectional"""
        corr_raw = df.groupby('ticker')['rank_high'].transform(
            lambda x: x.rolling(3).corr(df.loc[x.index, 'rank_volume']))
        ranked_corr = corr_raw.groupby(df['date']).rank(pct=True)
        return -1.0 * df.groupby('ticker')['rank_high'].transform(
            lambda x: ranked_corr.loc[x.index].rolling(3).sum())

    @staticmethod
    def _alpha019(df: pd.DataFrame) -> pd.Series:
        """-1*sign(close-delay(close,7)) * (1 + rank(1+sum(returns,250))) — cross-sectional momentum rank"""
        sign_part = -1.0 * np.sign(
            df.groupby('ticker')['close'].transform(lambda x: x - x.shift(7)))
        rank_part = (1.0 + df['returns_sum250']).groupby(df['date']).rank(pct=True)
        return sign_part * (1.0 + rank_part)

    @staticmethod
    def _alpha041(df: pd.DataFrame) -> pd.Series:
        """sqrt(high * low) - vwap"""
        return np.sqrt(df['high'] * df['low']) - df['vwap']

    @staticmethod
    def _alpha046(df: pd.DataFrame) -> pd.Series:
        """Slope change detector (threshold 0.25)."""
        slope_accel = (
            (df['close'] - df['close_lag10']) / 10.0
            - (df['close_lag10'] - df['close_lag20']) / 10.0
        )
        result = -1.0 * df['delta_close_1']
        result = result.copy()
        result[slope_accel > 0.25] = -1.0
        result[slope_accel < 0] = 1.0
        return result

    @staticmethod
    def _alpha049(df: pd.DataFrame) -> pd.Series:
        """Slope deceleration (threshold -0.1)."""
        slope_accel = (
            (df['close'] - df['close_lag10']) / 10.0
            - (df['close_lag10'] - df['close_lag20']) / 10.0
        )
        result = -1.0 * df['delta_close_1']
        result = result.copy()
        result[slope_accel < -0.1] = 1.0
        return result

    @staticmethod
    def _alpha051(df: pd.DataFrame) -> pd.Series:
        """Slope deceleration (threshold -0.05)."""
        slope_accel = (
            (df['close'] - df['close_lag10']) / 10.0
            - (df['close_lag10'] - df['close_lag20']) / 10.0
        )
        result = -1.0 * df['delta_close_1']
        result = result.copy()
        result[slope_accel < -0.05] = 1.0
        return result

    @staticmethod
    def _alpha054(df: pd.DataFrame) -> pd.Series:
        """(-1*(low-close)*(open^5)) / ((low-high)*(close^5))"""
        denom = (df['low'] - df['high']) * (df['close'] ** 5)
        numer = -1.0 * (df['low'] - df['close']) * (df['open'] ** 5)
        result = numer / denom
        # Guard division by zero
        mask = (abs(df['low'] - df['high']) < 0.0001) | (abs(df['close']) < 0.0001)
        result[mask] = 0.0
        return result

    @staticmethod
    def _alpha060(df: pd.DataFrame) -> pd.Series:
        """-1*(2*scale(rank(inner)) - scale(rank(ts_argmax(close,10)))) — ranks are cross-sectional"""
        # Compute raw inner (money-flow proxy) per ticker
        hl_range = df['high'] - df['low']
        inner = pd.Series(0.0, index=df.index)
        valid = hl_range > 0
        inner[valid] = (
            ((df['close'] - df['low']) - (df['high'] - df['close'])) / hl_range * df['volume'].astype(float)
        )[valid]
        # ts_argmax is per-ticker rolling
        argmax_10 = df.groupby('ticker', group_keys=False).apply(
            lambda g: FeaturePipeline._ts_argmax(g['close'], 10), include_groups=False)
        # Both ranks are cross-sectional (across tickers on each date)
        rank_inner = inner.groupby(df['date']).rank(pct=True)
        rank_argmax = argmax_10.groupby(df['date']).rank(pct=True)
        return -1.0 * (2.0 * FeaturePipeline._scale(rank_inner) - FeaturePipeline._scale(rank_argmax))

    @staticmethod
    def _alpha101(df: pd.DataFrame) -> pd.Series:
        """(close - open) / ((high - low) + 0.001)"""
        return (df['close'] - df['open']) / ((df['high'] - df['low']) + 0.001)

    # ------------------------------------------------------------------
    # Phase C: Cross-sectional ranks (SQL UPDATE)
    # ------------------------------------------------------------------

    def compute_cross_sectional_ranks(self, target_table: str = 't2_screener_features', start_date: str = None, end_date: str = None) -> None:
        logger.info(f"[C] Computing cross-sectional ranks -> {target_table}...")
        con = db.connect(self.db_path)

        try:
            existing = {r[0] for r in con.execute(f"DESCRIBE {target_table}").fetchall()}
            for col in RANK_COLS:
                if col not in existing:
                    con.execute(f"ALTER TABLE {target_table} ADD COLUMN {col} DOUBLE")

            # Build date filter for the chunk extraction
            date_clause = ""
            if start_date and end_date:
                date_clause = f"date BETWEEN '{start_date}' AND '{end_date}'"
            elif start_date:
                date_clause = f"date >= '{start_date}'"
            elif end_date:
                date_clause = f"date <= '{end_date}'"

            # Extract chunk → update in temp → re-insert (avoids full-table UPDATE scan)
            chunk_where = f"WHERE {date_clause}" if date_clause else ""
            con.execute(f"""
                CREATE OR REPLACE TEMP TABLE _rank_chunk AS
                SELECT * FROM {target_table} {chunk_where}
            """)
            if date_clause:
                con.execute(f"DELETE FROM {target_table} WHERE {date_clause}")
            else:
                con.execute(f"DELETE FROM {target_table}")

            con.execute(f"""
                WITH sector_map AS (
                    SELECT ticker, sector, industry
                    FROM company_profiles
                ),
                ranked_base AS (
                    SELECT
                        f.ticker,
                        f.date,
                        f.rs,
                        sm.sector,
                        sm.industry,
                        PERCENT_RANK() OVER (PARTITION BY f.date ORDER BY f.rs) as rs_universe_rank
                    FROM _rank_chunk f
                    LEFT JOIN sector_map sm ON f.ticker = sm.ticker
                    WHERE f.rs IS NOT NULL
                ),
                ranked AS (
                    SELECT
                        ticker, date, rs, sector, industry,
                        rs_universe_rank,
                        PERCENT_RANK() OVER (PARTITION BY date, sector ORDER BY rs) as rs_sector_rank,
                        AVG(rs_universe_rank) OVER (PARTITION BY date, sector) as sector_momentum,
                        STDDEV(rs_universe_rank) OVER (PARTITION BY date, sector) as sector_rs_std,
                        PERCENT_RANK() OVER (PARTITION BY date, industry ORDER BY rs) as rs_industry_rank,
                        AVG(rs_universe_rank) OVER (PARTITION BY date, industry) as industry_momentum,
                        STDDEV(rs_universe_rank) OVER (PARTITION BY date, industry) as industry_rs_std
                    FROM ranked_base
                )
                UPDATE _rank_chunk f
                SET
                    RS_Universe_Rank = r.rs_universe_rank,
                    rs_rating = CAST(ROUND(r.rs_universe_rank * 98) + 1 AS INT),
                    RS_Sector_Rank = r.rs_sector_rank,
                    RS_vs_Sector = CASE WHEN r.sector_rs_std > 0
                        THEN (r.rs - r.sector_momentum) / r.sector_rs_std
                        ELSE 0 END,
                    Sector_Momentum = r.sector_momentum,
                    RS_Industry_Rank = r.rs_industry_rank,
                    RS_vs_Industry = CASE WHEN r.industry_rs_std > 0
                        THEN (r.rs - r.industry_momentum) / r.industry_rs_std
                        ELSE 0 END,
                    Industry_Momentum = r.industry_momentum
                FROM ranked r
                WHERE f.ticker = r.ticker AND f.date = r.date
            """)

            all_cols = ', '.join(r[0] for r in con.execute("DESCRIBE _rank_chunk").fetchall())
            con.execute(f"""
                INSERT INTO {target_table} ({all_cols})
                SELECT {all_cols} FROM _rank_chunk
            """)

            cs_count = con.execute(
                f"SELECT COUNT(*) FROM _rank_chunk WHERE RS_Universe_Rank IS NOT NULL"
            ).fetchone()[0]
            con.execute("DROP TABLE IF EXISTS _rank_chunk")
            logger.info(f"[OK] [C] Cross-sectional ranks: {cs_count:,} rows (8 columns)")

        except Exception as e:
            logger.error(f"Phase C (cross-sectional ranks) failed: {e}")
            logger.error(f"[C] Phase C failed: {e}")
            raise
        finally:
            con.close()


    def _refresh_training_cache(self) -> None:
        """
        Refresh materialized cache for v_d2_training.

        This speeds up model training data loads from 5-10s -> <1s by
        materializing the complex view into a simple table.

        Called automatically after compute_all() completes.
        """
        from src.managers.view_manager import ViewManager

        try:
            vm = ViewManager(db_path=self.db_path)
            vm.refresh_cache(verbose=True)
        except Exception as e:
            logger.warning(f"Cache refresh failed (non-critical): {e}")
            logger.warning(f"Cache refresh failed: {e}")
            # Don't raise - cache is a performance optimization, not critical

