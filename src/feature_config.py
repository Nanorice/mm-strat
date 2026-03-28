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

# =============================================================================
# MODEL-SPECIFIC FEATURE SETS
# =============================================================================
# M01: SEPA Signal Regressor Model (Predicts: expected return)
M01_Bench_FEATURES = [
    # Alphas
    'alpha009', 
    'alpha011', 
    'alpha013', 
    'alpha041', 
    'alpha060', 
    'alpha101', 
    # Price Structure
    'nATR', 
    'RS', 
    'RS_Delta', 
    'VCP_Ratio', 
    'SMA_50_Slope', 
    'Price_vs_SMA_50', 
    'Price_vs_SMA_200', 
    'Dry_Up_Volume',
    'Dist_From_20D_Low',
    'Dist_From_52W_High',
    # Fundamentals
    'operating_margin', 
    'eps_growth_yoy', 
    'revenue_accel', 
    'pe_ratio', 
    'eps_accel', 
]

M01_V3_FEATURES = [
    'breakout_momentum',
    'log_VCP_Ratio_Delta',  # log-transformed
    'price_momentum_curve',
    'log_rs_line_delta',  # log-transformed
    'log_Dist_From_20D_Low_Delta',  # log-transformed
    'log_Dry_Up_Volume_Delta',  # log-transformed
    'alpha013',
    'log_Price_vs_SMA_50',  # log-transformed
    'log_RS_Delta',  # log-transformed
    'Dist_From_52W_High_Delta',
    'alpha101',
    'log_alpha060',  # log-transformed
    'log_Price_vs_SMA_200_Delta',  # log-transformed
    'log_volume_velocity',  # already log-transformed
    'log_Price_vs_SMA_150',  # log-transformed
    'Price_vs_SMA_150_Delta',
    'RSI_14',
    'log_mom_63d',  # log-transformed
    'alpha009',
    'log_rs_velocity',  # log-transformed
    'industry',
    'Dist_From_20D_High_Delta',
    'VCP_Ratio',
    # 'price_vs_spy_ma63',
    'log_Dry_Up_Volume',  # log-transformed
    'alpha011',
    'm03_pillar_risk',
    'RS_Universe_Rank',
    'alpha054',
    'operating_margin',
    'Price_vs_SMA_50_Delta',
    'alpha006',
    'log_turnover_ma20',
    'turnover_ma20',
    'log_volume_acceleration',  # log-transformed
    'roa',
    'alpha002',
    'alpha015',
    'm03_regime_vol',
    'log_Price_vs_SMA_50_Lag1',
    'price_accel_10d',
    'log_alpha001',  # log-transformed
    'log_current_ratio',  # log-transformed
    'log_RS_MA_Delta',  # log-transformed
    'log_fcf_margin',  # log-transformed
    'log_gross_margin_trend',  # log-transformed
    'log_eps_growth_yoy',  # log-transformed
    'log_days_since_report',  # log-transformed
    'log_pe_ratio',
    'm03_delta_20d',
    'roe',
    'alpha004',
    'gross_margin',
    'log_debt_to_equity',  # log-transformed
    'm03_pillar_liq',
    'log_eps_accel',  # log-transformed
    'log_rs_line_lag_delta',  # log-transformed
    'eps_stability_score',
    'log_revenue_accel',  # log-transformed
    'RS_vs_Sector',
    'log_pb_ratio',  # log-transformed
    'earnings_quality_score',
    'inventory_growth_yoy',
    'm03_pillar_trend',
    'alpha046',
    'log_revenue_growth_yoy',  # log-transformed
    'm03_score',
    'log_revenue_cagr_3y',  # log-transformed
    'ps_ratio',
    'm03_delta_5d',
    'log_RS_vs_Industry',  # log-transformed
]


# including M03 features makes M01 worse
M01_FEATURES = [
    'log_breakout_momentum',  # log-transformed
    'log_VCP_Ratio_Delta',  # log-transformed
    'log_price_momentum_curve',  # log-transformed
    'alpha012',
    'log_Dist_From_52W_Low_Delta',  # log-transformed
    'log_RS',  # log-transformed (momentum-based)
    'log_Price_vs_SMA_50',  # log-transformed
    'alpha013',
    'log_Price_vs_SMA_200',  # log-transformed
    'alpha101',
    'log_Dry_Up_Volume_Delta',  # log-transformed
    'log_Dist_From_20D_Low_Delta',  # log-transformed
    'log_alpha060',  # log-transformed
    'log_mom_63d',  # log-transformed
    'log_volume_velocity',  # already log-transformed
    'rs_velocity',
    'log_rs_velocity',      # log-transformed
    'log_alpha009',  # log-transformed
    'log_Price_vs_SMA_200_Delta',  # log-transformed
    'log_High_52W_Delta',  # log-transformed
    'Price_vs_SMA_150_Delta',
    'RSI_14',
    'Dist_From_20D_High_Delta',
    'RS_Universe_Rank',
    'current_ratio',
    'alpha054',
    'operating_margin',
    # v3.1: Removed log_Dry_Up_Volume_Lag1 (duplicate of log_Dry_Up_Volume_Delta at line 376)
    'VCP_Ratio',
    'eps_stability_score',
    'log_Price_vs_SMA_50_Delta',  # v3.1: was log_Price_vs_SMA_50_Lag1
    'alpha002',
    'Price_vs_SMA_50_Delta',
    'alpha011',
    'm03_pillar_risk',
    'turnover_ma20',
    'Dist_From_52W_High_Delta',
    'alpha006',
    'log_vol_ma20',  # log-transformed
    'roe',
    'log_alpha001',  # log-transformed
    'm03_pillar_trend',
    'log_volume_acceleration',  # log-transformed
    'alpha015',
    'log_fcf_margin',  # log-transformed
    'alpha041',
    'roa',
    'log_pb_ratio',  # log-transformed
    'm03_score',
    'alpha004',
    'Is_Green_Day',
    'log_debt_to_equity',  # log-transformed
    'log_days_since_report',  # log-transformed
    'log_revenue_cagr_3y',  # log-transformed
    'earnings_quality_score',
    'alpha046',
    'm03_regime_vol',
    'RS_vs_Sector',
    'log_gross_margin_trend',  # log-transformed
    'm03_pillar_liq',
    'pe_ratio',
    'log_eps_growth_yoy',  # log-transformed
    'ps_ratio',
    'net_income_growth_yoy',
    'log_net_income_growth_yoy',
    'log_revenue_growth_yoy',  # log-transformed
    'm03_delta_20d',
    'inventory_vs_sales_spread',
    'log_eps_accel',  # log-transformed
    'm03_delta_5d',
    'gross_margin',
    'log_revenue_accel',  # log-transformed
    'peg_adjusted',
    # Native categorical features (XGBoost enable_categorical)
    'industry',
    'sector',
]

M01_NO_INDUSTRY = [f for f in M01_FEATURES if f != 'industry']  # For testing industry exclusion impact

M01_V2_FEATURES = [
    'log_Price_vs_SMA_200',  # log-transformed
    'alpha011',
    'log_nATR',  # log-transformed
    'alpha013',
    'log_RS_Delta',  # log-transformed
    'log_Dist_From_52W_Low',  # log-transformed
    'log_alpha060',  # log-transformed
    'log_current_ratio',  # log-transformed
    'eps_stability_score',
    'operating_margin',
    'log_Dry_Up_Volume_Delta',  # log-transformed
    'Price_vs_SMA_50_Delta',
    'alpha101',
    'log_debt_to_equity',  # log-transformed
    'log_volume_velocity',  # already log-transformed
    'log_eps_growth_yoy',  # log-transformed
    'log_alpha001',  # log-transformed
    'rs_velocity',
    'alpha054',
    'earnings_quality_score',
    'nATR_Delta',
    'log_revenue_growth_yoy',  # log-transformed
    'price_accel_10d',
    'log_fcf_margin',  # log-transformed
    'alpha006',
    'log_Dist_From_20D_Low_Delta',  # log-transformed
    'pe_ratio',
    'RSI_14',
    'log_RS_MA_Delta',  # log-transformed
    'log_revenue_accel',  # log-transformed
    'inventory_vs_sales_spread',
    'roa',
    'alpha012',
    'alpha015',
    'log_revenue_cagr_3y',  # log-transformed
    'Price_vs_SMA_150_Delta',
    'alpha041',
    'log_breakout_momentum',  # log-transformed
    'roe',
    'alpha002',
    'alpha009',
    'Dist_From_20D_High_Delta',
    'log_eps_accel',  # log-transformed
    'VCP_Ratio',
    'days_since_report',
    'log_pb_ratio',  # log-transformed
    'log_Price_vs_SMA_200_Delta',  # log-transformed
    'peg_adjusted',
    'ps_ratio',
    'log_gross_margin_trend',  # log-transformed
    'log_Dry_Up_Volume',  # log-transformed
    'log_volume_acceleration',  # log-transformed
    'gross_margin',
    'SMA_50_Slope',
    'Dist_From_52W_High',
    'Is_Green_Day',
    'log_Lowest_Low_20D_Delta',  # log-transformed
]

# M01_3BAR: Triple Barrier Meta-Labeling Model (Baseline)
# Uses same features as M01 but predicts barrier-exit outcomes (TP vs SL/Time)
M01_3BAR_FEATURES = M01_FEATURES.copy()  # Start with proven M01 feature set

# M01_3BAR_V2: Enhanced with Velocity Features (Phase 2: Ignition Engine)
# Adds velocity-specific features to distinguish igniters from drifters
# =============================================================================
# M02: IGNITION CLASSIFIER (Velocity-Only Features)
# =============================================================================
# M02 is the Ignition Classifier that predicts triple barrier outcomes.
# Uses velocity-focused features to identify fast-moving "igniters".

M01_3BAR_VELOCITY_ONLY = [
    # --- 1. THE CAPTAINS (Core Strength) ---
    'RS',                   # Relative Strength Ratio (The "Freshness" Signal)
    'alpha011',             # VWAP Divergence (Institutional Intent)
    'Dist_From_20D_Low',    # Support Proximity (Risk/Reward)
    'Price_vs_SMA_200',     # Primary Trend Extension (Normalized)
    'alpha054',             # Structure (Open/Close/Low physics)
    'Vol_Ratio',            # Demand Fuel
    'VCP_Ratio',            # Tightness (Volatility Contraction)

    # --- 2. THE VELOCITY SQUAD (Speed & Acceleration) ---
    'volume_acceleration',  # Demand Surge (2nd derivative)
    'rs_velocity',          # Speed of RS change
    'RS_Delta',             # Rate of change of Strength
    'price_momentum_curve', # Parabolic check
    'breakout_momentum',    # Thrust
    'Dist_From_52W_High_Delta', # Speed into highs
    'Dry_Up_Volume_Delta',  # Supply shock
    # 'immediate_thrust',     # Price 2nd derivative (Physics)
    'log_volume_velocity',  # Log-scaled volume force

    # --- 3. WORLDQUANT PHYSICS (Alpha Factors) ---
    'alpha046',   # Slope Acceleration
    'alpha051',   # Conditional Slope Change
    'alpha101',   # Candle Body Strength
    'alpha009',   # Delta Close Stability
    'alpha013',   # Price/Volume Covariance
    'alpha006',   # Volume/Open Correlation
    'alpha001',   # Rank of Returns
    'alpha015',   # Rank Correlation (High/Vol)
    # -- RESTORED ALPHAS --
    'alpha002',   # Volume/Price Rank Correlation (Unique Physics)
    'alpha004',   # Rank of Lows (Trend Consistency)
    'alpha012',   # Directional Volume Force

    # --- 4. CONTEXT & STRUCTURE (No Raw Prices) ---
    'Dist_From_52W_High',       # Proximity to Blue Sky
    'consolidation_duration',   # Fuel tank size
    'Breakout',                 # Context Switch
    'Consolidation_Width_Delta',# Base tightening
    'Dist_From_20D_High',       # Proximity to trigger
    'Dist_From_52W_Low',        # Trend Maturity
    'RSI_14_Delta',             # Momentum Regime Change

    # --- 5. LAGGED STATE (Context) ---
    'RS_Lag1',
    'VCP_Ratio_Lag1',
    'Dist_From_20D_Low_Lag1',
    'Price_vs_SMA_200_Lag1',
    'Dist_From_52W_High_Lag1'
]

# M02_FEATURES: The canonical feature set for Ignition Classifier
M02_FEATURES = M01_3BAR_VELOCITY_ONLY.copy()

# Backward compatibility aliases (deprecated - use M02_FEATURES)
M01_3BAR_FEATURES_V2 = M02_FEATURES

# =============================================================================
# FEATURE PRE-FILTERS (Applied before KS threshold screening)
# =============================================================================
# These columns are excluded BEFORE statistical screening because they are:
# - Metadata (not features)
# - Raw/non-stationary (absolute prices, volumes)
# - Structurally redundant (lagged versions used to compute deltas)

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
# CANDIDATE FEATURES FOR AUTOMATED WORKFLOW
# =============================================================================
# Add experimental features here to test in the automated workflow.
# The workflow will screen these using KS test and select those that pass.
M01_CANDIDATE_FEATURES = M01_FEATURES + [
    # --- Cross-Sectional Features (New) ---
    'RS_Universe_Rank',
    'RS_Sector_Rank',
    'RS_Industry_Rank',
    'RS_vs_Sector',
    'RS_vs_Industry',
    'Sector_Momentum',
    'Industry_Momentum',
    # mktCap_log, beta removed - company profile data rarely updated
]


def get_model_features(model_name: str = 'M01') -> List[str]:
    """
    Get the feature list for a specific model.

    Args:
        model_name: 'M01', 'M02', or legacy 'M01_3BAR' names (deprecated).

    Returns:
        List of feature column names.
    """
    registry = {
        # Current models
        'M01': M01_FEATURES,
        'M02': M02_FEATURES,
        
        # Legacy aliases (backward compatibility - deprecated)
        'M01_3BAR': M01_3BAR_FEATURES,        # Original baseline
        'M01_3BAR_V2': M02_FEATURES,           # Now called M02
        'M01_3BAR_VELOCITY_ONLY': M02_FEATURES # Now called M02
    }

    if model_name not in registry:
        raise ValueError(f"Unknown model: {model_name}. Available: {list(registry.keys())}")

    return registry[model_name]
