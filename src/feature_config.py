"""
Feature Configuration - Centralized Feature Management
======================================================
This file is the SINGLE SOURCE OF TRUTH for all features used in the SEPA ML models.
Edit this file to add/remove features from training and scoring.

PHILOSOPHY:
  - Define ONCE, use EVERYWHERE.
  - Model-specific feature sets reference this config.
"""

from typing import List, Dict

# =============================================================================
# TECHNICAL FEATURES (From Price Data)
# =============================================================================
TECHNICAL_FEATURES = [
    # Moving Averages (Normalized Distance)
    'Price_vs_SMA_50',
    'Price_vs_SMA_150',
    'Price_vs_SMA_200',

    # Volatility
    'nATR',              # Normalized ATR (price-relative)
    'ATR',
    'VCP_Ratio',         # Volatility Contraction Pattern
    'Consolidation_Width',

    # Relative Strength (Minervini-style)
    'RS',                # Price ratio (for charting)
    'RS_MA',
    'rs_rating',         # Weighted momentum: 0.4*3m + 0.2*6m + 0.2*9m + 0.2*12m

    # Volume
    'Vol_Ratio',         # Today's volume vs 50d avg
    'Dry_Up_Volume',
    'vol_ma20',          # 20-day volume MA
    'vol_ma50',          # 50-day volume MA

    # Turnover (Liquidity)
    'turnover',          # Close * Volume (dollar volume)
    'turnover_ma20',     # 20-day turnover MA

    # Momentum (Multi-period)
    'mom_21d',           # 1-month ROC
    'mom_63d',           # 3-month ROC
    'mom_126d',          # 6-month ROC
    'mom_189d',          # 9-month ROC
    'mom_252d',          # 12-month ROC

    # Momentum Oscillators
    'RSI_14',
    # 'RSI_Regime',  # EXCLUDED: Constant column (no variance)
    'SMA_50_Slope',

    # Price Structure
    'Dist_From_52W_High',
    'Dist_From_52W_Low',     # Distance from 52-week low
    'Dist_From_20D_Low',     # Distance from 20-day low
    'Dist_From_20D_High',    # Distance from 20-day high

    'Green_Days_Ratio_20D',
    'High_52W',
    'Low_52W',
    'Lowest_Low_20D',        # 20-day low value (needed for distance calc)
    'Highest_High_20D',      # 20-day high value (needed for distance calc)
    'High_20D',              # 20-day high (for breakout detection)

    # Binary Flags & Regimes
    'Breakout',              # Breakout signal (1/0)
    'Is_Green_Day',          # Bullish candle (1/0)

    # Velocity Features (Phase 2: Ignition Engine)
    'rs_velocity',           # Speed of RS change (momentum-based, not benchmark)
    'volume_acceleration',   # Volume second derivative (surge detector)
    'breakout_momentum',     # Breakout strength in ATR units
    'consolidation_duration',# Days of tight consolidation (coil length)
    'price_momentum_curve',  # Price second derivative (parabolic detector)
]

# =============================================================================
# ALPHA FACTORS (WorldQuant-Style)
# =============================================================================

ALPHA_FEATURES = [
    'alpha001',    # Momentum reversal
    'alpha002',
    'alpha004',
    'alpha006',
    'alpha009',    # Trend acceleration
    'alpha011',
    'alpha012',
    'alpha013',
    'alpha015',
    'alpha041',
    'alpha046',    # Slope change (ignition)
    'alpha049',    # Slope deceleration (ignition)
    'alpha051',    # Slope deceleration (ignition)
    'alpha054',
    'alpha060',
    'alpha101',
]

# =============================================================================
# FUNDAMENTAL FEATURES (Compressed "Snapshot" at T)
# =============================================================================
# These are derived at feature extraction time from raw fundamental data.
# See `compute_fundamental_snapshot()` in feature_engine for logic.
FUNDAMENTAL_FEATURES = [
    # Growth Metrics (from FundamentalProcessor)
    'eps_growth_yoy',
    'revenue_growth_yoy',
    'net_income_growth_yoy',  # YoY net income growth
    'eps_accel',           # QoQ change in EPS growth rate
    'revenue_accel',       # QoQ change in revenue growth rate

    # Profitability Margins
    'gross_margin',
    'operating_margin',
    'net_margin',          # netIncome / revenue
    'roe',                 # Return on Equity
    'roa',                 # Return on Assets (ALREADY CALCULATED)

    # Safety & Solvency Ratios (ALREADY CALCULATED)
    'debt_to_equity',      # Total Debt / Total Equity
    'current_ratio',       # Current Assets / Current Liabilities
    'quick_ratio',         # (Current Assets - Inventory) / Current Liabilities

    # Long-term Track Record (ALREADY CALCULATED)
    'revenue_cagr_3y',     # 3-year revenue compound annual growth rate
    'eps_stability_score', # StdDev of EPS growth over 8 quarters (lower = better)

    # SEPA Specific Quality Checks
    'inventory_vs_sales_spread',  # Inventory growth - Revenue growth (positive = red flag)
    'inventory_growth_yoy',       # YoY inventory growth (ALREADY CALCULATED)

    # Cash Flow & Quality Metrics
    'earnings_quality_score',     # Operating_Cash_Flow / Net_Income
    'fcf_margin',                 # Free_Cash_Flow / Revenue (%)
    'gross_margin_trend',         # Current_Gross_Margin - Avg_Gross_Margin_4Q

    # Valuation Ratios (ALREADY IMPLEMENTED in fundamental_merger.py)
    'pe_ratio',            # Price / EPS
    'ps_ratio',            # Market Cap / Revenue
    'pb_ratio',            # Price / Book Value Per Share
    'peg_adjusted',        # (P/E) / EPS Growth (Peter Lynch metric)

    # Quality & Risk Flags
    'is_declining_earnings',  # Flag: EPS growth <= 0 (turnaround risk)

    # Staleness Indicator (days since last earnings filing)
    'days_since_earnings',
]

# =============================================================================
# COMPANY PROFILE FEATURES (From Company Metadata)
# =============================================================================
# Added via add_company_features() in FeatureEngineer
COMPANY_FEATURES = [
    'sector',             # String categorical (XGBoost enable_categorical)
    'industry',           # String categorical (XGBoost enable_categorical)
    # 'mktCap_log',       # EXCLUDED: Company profile data rarely updated
    # 'beta',             # EXCLUDED: Company profile data rarely updated
]

# =============================================================================
# CROSS-SECTIONAL FEATURES (Relative Rankings)
# =============================================================================
# Added via add_cross_sectional_features() after multi-ticker concatenation
CROSS_SECTIONAL_FEATURES = [
    # Universe-level
    'RS_Universe_Rank',   # Percentile rank (0-1) of RS across all tickers per date

    # Sector-level
    'RS_Sector_Rank',     # Percentile rank (0-1) of RS within sector per date
    'RS_vs_Sector',       # Z-score of RS relative to sector mean
    'Sector_Momentum',    # Mean RS of sector on each date

    # Industry-level
    'RS_Industry_Rank',   # Percentile rank (0-1) of RS within industry per date
    'RS_vs_Industry',     # Z-score of RS relative to industry mean
    'Industry_Momentum',  # Mean RS of industry on each date
]

# =============================================================================
# LAGGED FEATURES
# =============================================================================
# Features for which we want T-1 values to separate "cause" (setup) from "effect" (trigger).
FEATURES_TO_LAG = [
    'nATR', 'ATR', 'VCP_Ratio', 'Consolidation_Width',
    'Price_vs_SMA_50', 'Price_vs_SMA_150', 'Price_vs_SMA_200',
    'RS', 'RS_MA',  # Momentum-based (not benchmark)
    'Dry_Up_Volume',
    'High_52W', 'Low_52W', 'Lowest_Low_20D', 'Highest_High_20D',
    'RSI_14', 'Dist_From_52W_High', 'Dist_From_52W_Low', 'Dist_From_20D_Low', 'Dist_From_20D_High'
]

# =============================================================================
# DELTA FEATURES
# =============================================================================
# Percentage change from T-1 to T for lagged features
# Delta = (Current - Lag1) / Lag1
# Captures momentum/change separately from absolute levels
# Automatically generated from FEATURES_TO_LAG
DELTA_FEATURES = [f"{feature}_Delta" for feature in FEATURES_TO_LAG]

# =============================================================================
# FEATURE EXCLUSION LISTS
# =============================================================================

# Leakage Features - NEVER use in training/prediction
# These are only known AFTER the trade outcome, not at entry time
LEAKAGE_FEATURES = [
    'mae_pct',           # Maximum Favorable Excursion (peak during trade)
    'mfe_pct',           # Maximum Adverse Excursion (worst drawdown during trade)
    'y_max',         # Survivor target label
    'regret',        # MFE - actual return (only known at exit)
    'return_pct',    # The target variable itself
    'exit_reason',   # Only known at exit
    'return_at_exit',
    'sepa_exit_date',
    'holding_days',
    'days_observed',
    'MAE', 'MFE',        # PascalCase aliases (from view_manager)
    'exit_price', 'exit_date', # Explicit leakage
]

# Categorical Features - Require special encoding, NOT linear treatment
# These are integer IDs with no ordinal meaning (Banks=20 is not "less than" Software=105)
CATEGORICAL_FEATURES = [
    'sector',        # String categorical (XGBoost enable_categorical)
    'industry',      # String categorical (XGBoost enable_categorical)
]

# M03 Regime Features (generated by m03_regime.py, exclude via workflow flag)
M03_FEATURES = [
    'm03_score', 'm03_regime_cat', 'm03_delta_5d', 'm03_delta_20d',
    'm03_regime_vol', 'm03_pillar_trend', 'm03_pillar_liq', 'm03_pillar_risk',
]

# DEPRECATED: RS is now momentum-based, not benchmark-based
# Previously excluded when RS = Close/SPY (benchmark ratio)
# Now RS = rs_rating (momentum: 0.4*3m + 0.2*6m + 0.2*9m + 0.2*12m)
EXCLUDE_BENCHMARK_RS = [
    'price_vs_spy',
    'price_vs_spy_ma20',
    'price_vs_spy_ma50',
    'price_vs_spy_ma63',
    'price_vs_spy_ma200',
]

# Stale features to exclude (company profile data rarely updated)
EXCLUDE_STALE_FEATURES = ['mktCap_log', 'beta', 'RSI_Regime', 'log_beta']

# Combined auto-exclusion list for EDA/feature selection
FEATURE_AUTO_EXCLUDE = EXCLUDE_BENCHMARK_RS + EXCLUDE_STALE_FEATURES + LEAKAGE_FEATURES

# Metadata columns (not features)
EXCLUDE_METADATA = ['date', 'ticker', 'label', 'return_pct', 'days_held', 'exit_reason', 'year', 'breakout', 'is_new_trigger']

# Raw price/volume columns (non-stationary, can cause data leakage)
EXCLUDE_RAW_COLUMNS = [
    'Open', 'High', 'Low', 'Close', 'Volume',
    'High_52W', 'Low_52W', 'ATR', 'Vol_MA', 'High_20D',
    'ATR_Lag1', 'High_52W_Lag1', 'Low_52W_Lag1',
    'is_stale', 'has_fundamentals',
    'SMA_50', 'SMA_150', 'SMA_200', 'RS_MA',
    'log_close',         # Raw price proxy
    'entry_price',       # Raw price (non-stationary)
]

# Price structure columns (absolute values, not normalized)
EXCLUDE_PRICE_STRUCTURE = [
    'Lowest_Low_20D', 'Highest_High_20D',
    'Lowest_Low_20D_Lag1', 'Highest_High_20D_Lag1',
]

# Lag features (use deltas instead, avoid double-counting)
EXCLUDE_LAG_FEATURES = [f"{f}_Lag1" for f in FEATURES_TO_LAG]

# Raw fundamental columns (use derived ratios instead)
EXCLUDE_RAW_FUNDAMENTALS = ['operatingCashFlow', 'freeCashFlow', 'netIncome', 'revenue']

# Combined exclusion list for FeatureScreener pre-filtering
# NOTE: High correlation is computed dynamically in FeatureScreener, not hardcoded
FEATURE_EXCLUSION_LIST = (
    EXCLUDE_METADATA +
    EXCLUDE_RAW_COLUMNS +
    EXCLUDE_PRICE_STRUCTURE +
    EXCLUDE_LAG_FEATURES +
    EXCLUDE_RAW_FUNDAMENTALS +
    EXCLUDE_STALE_FEATURES +
    LEAKAGE_FEATURES +       # CRITICAL: Exclude leakage features from EDA
    CATEGORICAL_FEATURES     # Exclude categoricals from linear EDA (handle separately)
)

# =============================================================================
# MODEL FEATURE LOOKUP (DuckDB-backed)
# =============================================================================
# Model feature sets are stored in `model_feature_sets` table.
# Run scripts/populate_feature_catalog.py to seed if empty.

def get_model_features(model_name: str = 'M01', db_path: str = 'data/market_data.duckdb') -> List[str]:
    """Return the feature list for a model from the model_feature_sets table.

    Queries the prod model version for model_name and returns its registered features
    in ordinal order.

    Args:
        model_name: Prefix to match against version_id (e.g., 'M01' matches 'M01_baseline_v0.1').
        db_path: Path to DuckDB database.

    Returns:
        Ordered list of feature names.

    Raises:
        RuntimeError: If model_feature_sets table is empty or no prod model found.
    """
    import duckdb as _duckdb

    con = _duckdb.connect(db_path)
    try:
        result = con.execute(
            """
            SELECT feature_set_id FROM models
            WHERE status_flag = 'prod' AND version_id LIKE ?
            ORDER BY created_at DESC LIMIT 1
            """,
            [f"{model_name}%"],
        ).fetchone()

        if not result:
            raise RuntimeError(
                f"No prod model found for '{model_name}'. "
                "Run scripts/populate_feature_catalog.py first."
            )

        feature_set_id = result[0]
        if not feature_set_id:
            raise RuntimeError(
                f"Prod model for '{model_name}' has no feature_set_id. "
                "Run scripts/populate_feature_catalog.py first."
            )

        rows = con.execute(
            """
            SELECT feature_name FROM model_feature_sets
            WHERE feature_set_id = ?
            ORDER BY ordinal
            """,
            [feature_set_id],
        ).fetchall()

        if not rows:
            raise RuntimeError(
                f"model_feature_sets is empty for feature_set_id='{feature_set_id}'. "
                "Run scripts/populate_feature_catalog.py first."
            )

        return [r[0] for r in rows]
    finally:
        con.close()
