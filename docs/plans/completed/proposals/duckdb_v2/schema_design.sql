-- DuckDB V2 Schema Design (DDL Statements)
-- ===========================================
-- This file contains all CREATE TABLE statements for the v2 architecture.
-- Run this file to create the complete v2 schema in a new database.

-- ==============================================================================
-- TIER 1: RAW DATA (Eager Ingestion, Full Universe)
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- T1.1: Price Data (OHLCV)
-- ------------------------------------------------------------------------------
-- MIGRATION: Rename existing `price_data` table
-- Current status: ✅ EXISTS (9.7M rows)
-- Action: ALTER TABLE price_data RENAME TO t1_price;

CREATE TABLE IF NOT EXISTS t1_price (
    ticker VARCHAR NOT NULL,
    date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume UBIGINT,            -- IMPORTANT: UBIGINT to handle large volumes
    adj_close DOUBLE,
    adj_factor DOUBLE,
    vwap DOUBLE,               -- (H+L+C)/3 standard VWAP
    source VARCHAR,            -- 'yfinance', 'polygon', etc.
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);

-- Indexes for fast ticker+date lookups (used by window functions)
CREATE INDEX IF NOT EXISTS idx_t1_price_ticker ON t1_price(ticker);
CREATE INDEX IF NOT EXISTS idx_t1_price_date ON t1_price(date);

-- ------------------------------------------------------------------------------
-- T1.2: Fundamentals (Quarterly/Annual Reports)
-- ------------------------------------------------------------------------------
-- MIGRATION: Rename existing `fundamentals` table
-- Current status: ✅ EXISTS (387K rows)
-- Action: ALTER TABLE fundamentals RENAME TO t1_fundamentals;
-- Note: Missing P/E, P/S, P/B ratios - will be added in Phase 2.2 audit

CREATE TABLE IF NOT EXISTS t1_fundamentals (
    ticker VARCHAR NOT NULL,
    report_date DATE NOT NULL,
    filing_date DATE,
    period_type VARCHAR NOT NULL,  -- 'Q1', 'Q2', 'Q3', 'Q4', 'FY'
    fiscal_year INTEGER,

    -- Income Statement
    revenue DOUBLE,
    net_income DOUBLE,
    eps_diluted DOUBLE,
    gross_profit DOUBLE,
    operating_income DOUBLE,

    -- Balance Sheet
    total_assets DOUBLE,
    total_equity DOUBLE,
    total_debt DOUBLE,
    total_current_assets DOUBLE,
    total_current_liabilities DOUBLE,
    inventory DOUBLE,

    -- Cash Flow
    operating_cash_flow DOUBLE,
    free_cash_flow DOUBLE,

    -- Valuation Ratios (TO BE ADDED in Phase 2.2)
    -- pe_ratio DOUBLE,
    -- ps_ratio DOUBLE,
    -- pb_ratio DOUBLE,
    -- peg_ratio DOUBLE,
    -- market_cap DOUBLE,

    -- Metadata
    raw_data JSON,             -- Full yfinance response for audit
    source VARCHAR,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, report_date, period_type)
);

CREATE INDEX IF NOT EXISTS idx_t1_fundamentals_ticker ON t1_fundamentals(ticker);
CREATE INDEX IF NOT EXISTS idx_t1_fundamentals_date ON t1_fundamentals(report_date);

-- ------------------------------------------------------------------------------
-- T1.3: Shares Outstanding
-- ------------------------------------------------------------------------------
-- MIGRATION: Rename existing `shares_history` table
-- Current status: ✅ EXISTS (919K rows)
-- Action: ALTER TABLE shares_history RENAME TO t1_shares_outstanding;

CREATE TABLE IF NOT EXISTS t1_shares_outstanding (
    ticker VARCHAR NOT NULL,
    date DATE NOT NULL,
    shares_outstanding BIGINT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_t1_shares_ticker ON t1_shares_outstanding(ticker);

-- ------------------------------------------------------------------------------
-- T1.4: Company Profiles
-- ------------------------------------------------------------------------------
-- MIGRATION: Rename existing `company_profiles` table
-- Current status: ✅ EXISTS
-- Action: ALTER TABLE company_profiles RENAME TO t1_company_profiles;

CREATE TABLE IF NOT EXISTS t1_company_profiles (
    ticker VARCHAR PRIMARY KEY,
    name VARCHAR,
    sector VARCHAR,           -- 'Technology', 'Healthcare', etc.
    industry VARCHAR,         -- More granular than sector
    exchange VARCHAR,         -- 'NASDAQ', 'NYSE', etc.
    market_cap DOUBLE,
    description TEXT,
    website VARCHAR,
    country VARCHAR,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------------------------
-- T1.5: Macro Data (Market-Wide Indicators)
-- ------------------------------------------------------------------------------
-- MIGRATION: Extend existing `macro_data` table
-- Current status: 🟡 EXISTS (53.6K rows) - NEEDS EXTENSION
-- Current schema: (date, symbol, close, volume, value, unit)
-- Action: Add VIX, breadth indicators, restructure to wide format

CREATE TABLE IF NOT EXISTS t1_macro (
    date DATE PRIMARY KEY,

    -- Index Data
    spy_close DOUBLE,
    spy_volume UBIGINT,
    spy_high DOUBLE,
    spy_low DOUBLE,

    qqq_close DOUBLE,
    qqq_volume UBIGINT,
    qqq_high DOUBLE,
    qqq_low DOUBLE,

    vix_close DOUBLE,

    -- Market Breadth (TO BE ADDED)
    -- advance_decline_ratio DOUBLE,      -- (Advances - Declines) / Total
    -- new_high_low_ratio DOUBLE,         -- (New Highs - New Lows) / Total
    -- percent_above_200ma DOUBLE,        -- % of S&P500 stocks above 200-day MA

    -- Sector Rotation (TO BE ADDED)
    -- xlk_close DOUBLE,                  -- Technology
    -- xlv_close DOUBLE,                  -- Healthcare
    -- xlf_close DOUBLE,                  -- Financials
    -- xle_close DOUBLE,                  -- Energy

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_t1_macro_date ON t1_macro(date);

-- MIGRATION NOTE: Migrate existing macro_data (long format) to t1_macro (wide format)
-- Example migration SQL:
-- INSERT INTO t1_macro (date, spy_close, spy_volume, qqq_close, qqq_volume, vix_close)
-- SELECT
--     date,
--     MAX(CASE WHEN symbol = 'SPY' THEN close END) as spy_close,
--     MAX(CASE WHEN symbol = 'SPY' THEN volume END) as spy_volume,
--     MAX(CASE WHEN symbol = 'QQQ' THEN close END) as qqq_close,
--     MAX(CASE WHEN symbol = 'QQQ' THEN volume END) as qqq_volume,
--     MAX(CASE WHEN symbol = '^VIX' THEN close END) as vix_close
-- FROM macro_data
-- GROUP BY date;

-- ==============================================================================
-- TIER 2: DERIVED FEATURES (Eager Computation, Full Universe)
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- T2.1: Screener Features (Lightweight Technical Indicators)
-- ------------------------------------------------------------------------------
-- MIGRATION: NEW TABLE (extract 30 columns from current `daily_features`)
-- Current status: ❌ DOES NOT EXIST (will be created in Phase 3.3)

CREATE TABLE IF NOT EXISTS t2_screener_features (
    ticker VARCHAR NOT NULL,
    date DATE NOT NULL,

    -- Simple Moving Averages (SEPA Core)
    sma_20 DOUBLE,
    sma_50 DOUBLE,
    sma_150 DOUBLE,
    sma_200 DOUBLE,
    sma_200_lag20 DOUBLE,        -- For trend confirmation (SMA200 > LAG(SMA200, 20))

    -- Price vs SMA (SEPA Criteria)
    price_vs_sma_50 DOUBLE,      -- close / sma_50 - 1
    price_vs_sma_150 DOUBLE,
    price_vs_sma_200 DOUBLE,
    close_above_sma200 BOOLEAN,  -- SEPA C1

    -- Relative Strength (SEPA Core)
    rs_rating DOUBLE,            -- Composite RS (0-100 scale)
    rs DOUBLE,                   -- 0.4*3m + 0.2*6m + 0.2*9m + 0.2*12m
    rs_ma DOUBLE,                -- 20-day MA of RS
    rs_line_log DOUBLE,          -- log(close / spy_close)
    rs_line_delta DOUBLE,        -- RS line slope
    rs_line_uptrend BOOLEAN,     -- SEPA C2

    -- 52-Week Highs/Lows (SEPA Criteria)
    high_52w DOUBLE,
    low_52w DOUBLE,
    dist_from_52w_high DOUBLE,   -- (close - high_52w) / high_52w
    dist_from_52w_low DOUBLE,
    pct_from_high_52w DOUBLE,    -- SEPA C9: close >= 0.70 * high_52w

    -- 20-Day Highs/Lows
    high_20d DOUBLE,
    lowest_low_20d DOUBLE,
    dist_from_20d_high DOUBLE,
    dist_from_20d_low DOUBLE,

    -- Volume
    vol_avg_20 DOUBLE,           -- 20-day average volume
    vol_avg_50 DOUBLE,
    vol_ratio DOUBLE,            -- volume / vol_avg_20
    dry_up_volume DOUBLE,        -- Volume contraction during consolidation

    -- Volatility
    atr_20d DOUBLE,              -- Average True Range (20-day)
    natr DOUBLE,                 -- Normalized ATR (atr / close)
    volatility_20d DOUBLE,       -- Standard deviation of returns

    -- VCP Pattern
    vcp_ratio DOUBLE,            -- Volatility Contraction Pattern indicator
    consolidation_width DOUBLE,  -- (high_20d - low_20d) / low_20d

    -- Metadata
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);

-- Indexes for SEPA screener queries
CREATE INDEX IF NOT EXISTS idx_t2_screener_ticker ON t2_screener_features(ticker);
CREATE INDEX IF NOT EXISTS idx_t2_screener_date ON t2_screener_features(date);
CREATE INDEX IF NOT EXISTS idx_t2_screener_rs ON t2_screener_features(rs_rating);

-- ------------------------------------------------------------------------------
-- T2.2: Screener Membership (Historical Pass/Fail Tracking)
-- ------------------------------------------------------------------------------
-- MIGRATION: Rename existing `stock_screener` (if exists)
-- Current status: ❓ UNKNOWN (may not exist)
-- Action: Create if missing

CREATE TABLE IF NOT EXISTS t2_screener_members (
    ticker VARCHAR NOT NULL,
    date DATE NOT NULL,
    meets_price BOOLEAN,         -- close >= 15
    meets_volume BOOLEAN,        -- volume >= 100,000
    meets_mktcap BOOLEAN,        -- Optional market cap filter
    in_screener BOOLEAN,         -- Passes all baseline filters
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_t2_screener_members_date ON t2_screener_members(date);

-- ------------------------------------------------------------------------------
-- T2.3: Regime Scores (M03 Model Outputs)
-- ------------------------------------------------------------------------------
-- MIGRATION: NEW TABLE (replaces `data/regime_scores.parquet`)
-- Current status: ❌ DOES NOT EXIST (parquet file only)
-- Action: Create + migrate parquet data in Phase 3.2

CREATE TABLE IF NOT EXISTS t2_regime_scores (
    date DATE PRIMARY KEY,

    -- M03 Outputs
    m03_score DOUBLE,            -- Composite regime score (0-100)
    m03_pillar_trend DOUBLE,     -- Trend strength pillar
    m03_pillar_liq DOUBLE,       -- Liquidity/breadth pillar
    m03_pillar_risk DOUBLE,      -- Risk/volatility pillar

    -- Derived Features (computed in daily_features Phase E)
    m03_delta_5d DOUBLE,         -- 5-day change in m03_score
    m03_delta_20d DOUBLE,        -- 20-day change
    m03_regime_vol DOUBLE,       -- Volatility of regime transitions

    -- Metadata
    model_version VARCHAR DEFAULT 'v1.0',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_t2_regime_date ON t2_regime_scores(date);

-- ==============================================================================
-- TIER 3: HEAVY ML FEATURES (Lazy Computation, SEPA Breakouts Only)
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- T3: SEPA Features (Persistent ML Features)
-- ------------------------------------------------------------------------------
-- MIGRATION: NEW TABLE (extracts heavy features from `daily_features`)
-- Current status: ❌ DOES NOT EXIST
-- Action: Create + backfill from 2020-01-01 in Phase 4.1

CREATE TABLE IF NOT EXISTS t3_sepa_features (
    -- Primary Keys
    ticker VARCHAR NOT NULL,
    date DATE NOT NULL,
    feature_version VARCHAR DEFAULT 'v3.0' NOT NULL,  -- Enables reproducibility

    -- Raw OHLCV (copied from t1_price for convenience)
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume UBIGINT,

    -- ========================================================================
    -- PHASE A: SQL Features (79 columns)
    -- ========================================================================

    -- SMAs (from T2, duplicated here for point-in-time snapshot)
    sma_20 DOUBLE,
    sma_50 DOUBLE,
    sma_150 DOUBLE,
    sma_200 DOUBLE,
    sma_200_lag20 DOUBLE,
    sma_50_slope DOUBLE,

    -- Price vs SMA
    price_vs_sma_50 DOUBLE,
    price_vs_sma_150 DOUBLE,
    price_vs_sma_200 DOUBLE,
    close_above_sma200 BOOLEAN,

    -- Relative Strength (RS Line)
    price_vs_spy DOUBLE,         -- close / spy_close (benchmark ratio, NOT RS momentum)
    price_vs_spy_ma20 DOUBLE,
    price_vs_spy_ma50 DOUBLE,
    price_vs_spy_ma63 DOUBLE,
    price_vs_spy_ma200 DOUBLE,
    rs_line_log DOUBLE,
    rs_line_delta DOUBLE,
    rs_line_lag_delta DOUBLE,
    rs_line_uptrend BOOLEAN,

    -- RS Rating (Momentum-Based)
    rs_rating DOUBLE,            -- Cross-sectional rank (computed in Phase C)
    rs DOUBLE,                   -- 0.4*3m + 0.2*6m + 0.2*9m + 0.2*12m
    rs_ma DOUBLE,

    -- Volume
    vol_avg_20 DOUBLE,
    vol_avg_50 DOUBLE,
    vol_ratio DOUBLE,
    vol_ratio_50 DOUBLE,
    vol_ma20 DOUBLE,
    vol_ma50 DOUBLE,
    dollar_volume_avg_20 DOUBLE,
    dry_up_volume DOUBLE,
    turnover DOUBLE,
    turnover_ma20 DOUBLE,

    -- Volatility
    atr_14 DOUBLE,
    atr_20d DOUBLE,
    natr DOUBLE,
    volatility_20d DOUBLE,
    vcp_ratio DOUBLE,
    consolidation_width DOUBLE,

    -- 52-Week & 20-Day Ranges
    high_52w DOUBLE,
    low_52w DOUBLE,
    highest_high_20d DOUBLE,
    lowest_low_20d DOUBLE,
    high_20d DOUBLE,
    pct_from_high_52w DOUBLE,
    pct_above_low_52w DOUBLE,
    dist_from_52w_high DOUBLE,
    dist_from_52w_low DOUBLE,
    dist_from_20d_low DOUBLE,
    dist_from_20d_high DOUBLE,

    -- Returns & Momentum
    return_1d DOUBLE,
    return_5d DOUBLE,
    return_20d DOUBLE,
    return_60d DOUBLE,
    mom_21d DOUBLE,              -- 21-day momentum
    mom_63d DOUBLE,              -- 3-month momentum
    mom_126d DOUBLE,             -- 6-month momentum
    mom_189d DOUBLE,             -- 9-month momentum
    mom_252d DOUBLE,             -- 12-month momentum

    -- Technical Indicators
    rsi_14 DOUBLE,
    is_green_day INTEGER,        -- close > open
    green_days_ratio_20d DOUBLE, -- % green days in last 20 days
    breakout INTEGER,            -- Boolean: breakout above 20d high
    adr_20d DOUBLE,              -- Average Daily Range

    -- Velocity Features (Custom)
    rs_velocity DOUBLE,
    volume_acceleration BIGINT,
    breakout_momentum DOUBLE,
    consolidation_duration HUGEINT,
    price_momentum_curve DOUBLE,
    log_volume_velocity DOUBLE,
    price_accel_10d DOUBLE,
    immediate_thrust DOUBLE,

    -- SEPA Signal Flags
    trend_ok BOOLEAN,            -- Passes C1-C9 trend template
    breakout_ok BOOLEAN,         -- Passes C10-C11 breakout criteria

    -- ========================================================================
    -- PHASE B: Python Alpha Features (16 columns, WQ101 factors)
    -- ========================================================================
    alpha001 DOUBLE,             -- (-1 * correlation(rank(delta(log(volume))), rank((close - open) / open)))
    alpha002 DOUBLE,             -- (-1 * delta((close - low) - (high - close)) / (high - low))
    alpha004 DOUBLE,             -- (-1 * Ts_Rank(rank(low), 9))
    alpha006 DOUBLE,             -- (-1 * correlation(open, volume, 10))
    alpha009 DOUBLE,             -- (close - ts_min(low, 5)) / (ts_max(high, 5) - ts_min(low, 5))
    alpha011 DOUBLE,             -- ((rank(ts_max(vwap, 3)) + rank(ts_min(vwap, 3))) * rank(delta(volume, 3)))
    alpha012 DOUBLE,             -- (sign(delta(volume, 1)) * (-1 * delta(close, 1)))
    alpha013 DOUBLE,             -- (-1 * rank(covariance(rank(close), rank(volume), 5)))
    alpha015 DOUBLE,             -- (-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3))
    alpha041 DOUBLE,             -- (pow(high * low, 0.5) - vwap)
    alpha046 DOUBLE,             -- (mean(close) - close) / decay_linear(abs(close - mean(close)))
    alpha049 DOUBLE,             -- (ts_max(high, 9) - close) / (ts_max(high, 9) - ts_min(low, 9))
    alpha051 DOUBLE,             -- (ts_max(high, 9) - close) / (ts_max(high, 9) - ts_min(low, 9)) - delay(...)
    alpha054 DOUBLE,             -- (-1 * (low - close) * pow(open, 5)) / ((low - high) * pow(close, 5))
    alpha060 DOUBLE,             -- (close - low) - (high - close)) / (high - low) * volume
    alpha101 DOUBLE,             -- (close - open) / ((high - low) + 0.001)

    -- ========================================================================
    -- PHASE C: Cross-Sectional Ranks (7 columns)
    -- ========================================================================
    RS_Universe_Rank DOUBLE,     -- Percentile rank of RS across all tickers
    RS_Sector_Rank DOUBLE,       -- Percentile rank within sector
    RS_vs_Sector DOUBLE,         -- RS relative to sector median
    Sector_Momentum DOUBLE,      -- Sector-wide momentum score
    RS_Industry_Rank DOUBLE,     -- Percentile rank within industry
    RS_vs_Industry DOUBLE,       -- RS relative to industry median
    Industry_Momentum DOUBLE,    -- Industry-wide momentum score

    -- ========================================================================
    -- PHASE D: M03 Regime Features (joined from t2_regime_scores)
    -- ========================================================================
    m03_score DOUBLE,
    m03_pillar_trend DOUBLE,
    m03_pillar_liq DOUBLE,
    m03_pillar_risk DOUBLE,
    m03_delta_5d DOUBLE,
    m03_delta_20d DOUBLE,
    m03_regime_vol DOUBLE,

    -- ========================================================================
    -- Fundamental Snapshot (point-in-time join from t1_fundamentals)
    -- ========================================================================
    fundamental_pe DOUBLE,       -- P/E ratio (TO BE ADDED in Phase 2.2)
    fundamental_ps DOUBLE,       -- P/S ratio
    fundamental_pb DOUBLE,       -- P/B ratio
    -- Additional fundamentals as needed

    -- ========================================================================
    -- Metadata
    -- ========================================================================
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (ticker, date, feature_version)
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_t3_ticker ON t3_sepa_features(ticker);
CREATE INDEX IF NOT EXISTS idx_t3_date ON t3_sepa_features(date);
CREATE INDEX IF NOT EXISTS idx_t3_version ON t3_sepa_features(feature_version);
CREATE INDEX IF NOT EXISTS idx_t3_ticker_date ON t3_sepa_features(ticker, date);

-- ==============================================================================
-- SUPPORTING TABLES (Infrastructure)
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- Model Registry (MLOps Tracking)
-- ------------------------------------------------------------------------------
-- MIGRATION: ✅ KEEP AS-IS (already exists)

CREATE TABLE IF NOT EXISTS models (
    version_id VARCHAR PRIMARY KEY,
    status_flag VARCHAR CHECK (status_flag IN ('prod', 'test', 'archived')),
    specs_json JSON,
    feature_version VARCHAR,     -- Links to t3_sepa_features.feature_version
    training_date DATE,
    dataset_rows BIGINT,
    rmse DOUBLE,
    mae DOUBLE,
    r2 DOUBLE,
    spearman_corr DOUBLE,
    artifacts_path VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------------------------
-- Buy List (Daily Scored Candidates)
-- ------------------------------------------------------------------------------
-- MIGRATION: ✅ KEEP AS-IS (already exists, ~50 columns)

-- Note: Schema already defined, no changes needed
-- Primary use: Output of M01/M02/M03 scoring pipeline

-- ------------------------------------------------------------------------------
-- Pipeline Runs (Monitoring)
-- ------------------------------------------------------------------------------
-- MIGRATION: ❌ NEW TABLE (for Phase 6 monitoring)

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_date DATE PRIMARY KEY,
    status VARCHAR CHECK (status IN ('running', 'success', 'failed')),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    t1_rows_inserted BIGINT,
    t2_rows_updated BIGINT,
    t3_rows_inserted BIGINT,
    runtime_seconds INTEGER
);

-- ------------------------------------------------------------------------------
-- Master Ticker Registry (Universe Management)
-- ------------------------------------------------------------------------------
-- MIGRATION: ✅ KEEP AS-IS (already exists)

-- Note: Schema already defined, no changes needed

-- ------------------------------------------------------------------------------
-- Universe Snapshots (Monthly Screener History)
-- ------------------------------------------------------------------------------
-- MIGRATION: ✅ KEEP AS-IS (already exists)

-- Note: Schema already defined, no changes needed

-- ==============================================================================
-- MIGRATION SUMMARY
-- ==============================================================================

/*
PHASE 3: Execute Migrations

Step 1: Rename existing tables
-----------------------------
ALTER TABLE price_data RENAME TO t1_price;
ALTER TABLE fundamentals RENAME TO t1_fundamentals;
ALTER TABLE shares_history RENAME TO t1_shares_outstanding;
ALTER TABLE company_profiles RENAME TO t1_company_profiles;

Step 2: Extend macro_data → t1_macro
-----------------------------
-- Option A: Rename + add columns
ALTER TABLE macro_data RENAME TO t1_macro_old;
CREATE TABLE t1_macro AS (...);  -- Migrate from long to wide format

-- Option B: Keep macro_data, create new t1_macro
CREATE TABLE t1_macro AS (...);

Step 3: Create new tables
-----------------------------
CREATE TABLE t2_screener_features (...);
CREATE TABLE t2_screener_members (...);
CREATE TABLE t2_regime_scores (...);
CREATE TABLE t3_sepa_features (...);
CREATE TABLE pipeline_runs (...);

Step 4: Backfill t3_sepa_features
-----------------------------
-- Run scripts/backfill_t3_sepa_features.py (Phase 4.1)
-- Expected: ~500K rows from 2020-01-01 to present

Step 5: Drop deprecated tables (after validation)
-----------------------------
DROP TABLE daily_features;  -- Replaced by t2_screener_features + t3_sepa_features
DROP TABLE macro_data_old;  -- If using Option A above
DROP TABLE price_data_backfill;  -- If backfill complete
DROP TABLE shares_backfill;  -- If backfill complete

*/

-- ==============================================================================
-- VALIDATION QUERIES
-- ==============================================================================

/*
-- Check table row counts
SELECT 't1_price' as table_name, COUNT(*) as row_count FROM t1_price
UNION ALL SELECT 't1_fundamentals', COUNT(*) FROM t1_fundamentals
UNION ALL SELECT 't1_shares_outstanding', COUNT(*) FROM t1_shares_outstanding
UNION ALL SELECT 't1_macro', COUNT(*) FROM t1_macro
UNION ALL SELECT 't2_screener_features', COUNT(*) FROM t2_screener_features
UNION ALL SELECT 't2_regime_scores', COUNT(*) FROM t2_regime_scores
UNION ALL SELECT 't3_sepa_features', COUNT(*) FROM t3_sepa_features;

-- Check t3_sepa_features completeness
SELECT
    feature_version,
    COUNT(*) as total_rows,
    COUNT(DISTINCT ticker) as unique_tickers,
    MIN(date) as earliest_date,
    MAX(date) as latest_date
FROM t3_sepa_features
GROUP BY feature_version;

-- Check for NULL values in critical T3 columns
SELECT
    COUNT(*) FILTER (WHERE alpha001 IS NULL) as null_alpha001,
    COUNT(*) FILTER (WHERE rs_rating IS NULL) as null_rs_rating,
    COUNT(*) FILTER (WHERE m03_score IS NULL) as null_m03_score
FROM t3_sepa_features
WHERE feature_version = 'v3.0';

-- Verify T2 features match daily_features (legacy)
SELECT
    t2.ticker, t2.date,
    t2.sma_50 as t2_sma50,
    df.sma_50 as df_sma50,
    ABS(t2.sma_50 - df.sma_50) as diff
FROM t2_screener_features t2
JOIN daily_features df ON t2.ticker = df.ticker AND t2.date = df.date
WHERE ABS(t2.sma_50 - df.sma_50) > 0.01  -- Flag >1 cent differences
LIMIT 10;
*/
