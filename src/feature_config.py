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
    
    # Relative Strength
    'RS',
    'RS_MA',
    
    # Volume
    'Vol_Ratio',         # Today's volume vs 50d avg
    'Dry_Up_Volume',
    
    # Momentum
    'RSI_14',
    'RSI_Regime',
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
    'RSI_Regime',            # Context-aware RSI (bull=1, bear=0)

    # Velocity Features (Phase 2: Ignition Engine)
    'rs_velocity',           # RS acceleration (5-day slope)
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
    'sector_id',          # Encoded sector classification (0-10, -1 if missing)
    'industry_id',        # Encoded industry classification (0-158, -1 if missing)
    'mktCap_log',         # Log10 of market cap (scale normalization)
    'beta',               # Stock volatility vs market
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
    'RS', 'RS_MA', 'Dry_Up_Volume',
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

# including M03 features makes M01 worse
M01_V2_FEATURES = [
    'alpha011',
    'log_nATR',  # log-transformed
    'log_Price_vs_SMA_200',  # log-transformed
    'log_Dist_From_52W_Low',  # log-transformed
    'eps_stability_score',
    'alpha013',
    'operating_margin',
    'log_alpha060',  # log-transformed
    "m03_regime_cat",
    'm03_pillar_risk',
    'log_debt_to_equity',  # log-transformed
    'm03_pillar_trend',
    'log_RS_Delta',  # log-transformed
    'log_current_ratio',  # log-transformed
    'log_fcf_margin',  # log-transformed
    'earnings_quality_score',
    'rs_velocity',
    'log_nATR_Delta',  # log-transformed
    'm03_score',
    'log_volume_velocity',  # already log-transformed
    'log_alpha001',  # log-transformed
    'alpha054',
    'alpha101',
    'log_days_since_report',  # log-transformed
    'roe',
    'price_accel_10d',
    'alpha041',
    'Price_vs_SMA_50_Delta',
    'roa',
    'RSI_14',
    'm03_pillar_liq',
    'alpha012',
    'log_RS_MA_Delta',  # log-transformed
    'log_Dry_Up_Volume_Delta',  # log-transformed
    'alpha015',
    'pe_ratio',
    'log_revenue_growth_yoy',  # log-transformed
    'is_declining_earnings',
    'log_Dry_Up_Volume',  # log-transformed
    'log_Dist_From_20D_Low_Delta',  # log-transformed
    'SMA_50_Slope',
    'peg_adjusted',
    'log_revenue_cagr_3y',  # log-transformed
    'gross_margin',
    'log_Price_vs_SMA_200_Delta',  # log-transformed
    'inventory_growth_yoy',
    'alpha006',
    'Dist_From_20D_High_Delta',
    'log_pb_ratio',  # log-transformed
    'log_revenue_accel',  # log-transformed
    'log_eps_accel',  # log-transformed
    'alpha002',
    'log_volume_acceleration',  # log-transformed
    'ps_ratio',
    'm03_delta_5d',
    'log_gross_margin_trend',  # log-transformed
    'VCP_Ratio',
    'Dist_From_52W_High',
    'log_breakout_momentum',  # log-transformed
    'Price_vs_SMA_150_Delta',
    'm03_regime_vol',
    'm03_delta_20d',
    'Is_Green_Day',
]

M01_FEATURES = [
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
EXCLUDE_METADATA = ['date', 'ticker', 'label', 'return_pct', 'days_held', 'exit_reason', 'year']

# Raw price/volume columns (non-stationary, can cause data leakage)
EXCLUDE_RAW_COLUMNS = [
    'Open', 'High', 'Low', 'Close', 'Volume',
    'High_52W', 'Low_52W', 'ATR', 'Vol_MA', 'High_20D',
    'ATR_Lag1', 'High_52W_Lag1', 'Low_52W_Lag1',
    'is_stale', 'has_fundamentals',
    'SMA_50', 'SMA_150', 'SMA_200', 'RS_MA',
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
    EXCLUDE_RAW_FUNDAMENTALS
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
    # --- Company Profile Features ---
    'mktCap_log',
    'beta',
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
