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
# M01: SEPA Signal Quality Model (Predicts: "Will this trade hit 15%+ profit?")
M01_FEATURES = [
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

# M01_3BAR: Triple Barrier Meta-Labeling Model (Baseline)
# Uses same features as M01 but predicts barrier-exit outcomes (TP vs SL/Time)
M01_3BAR_FEATURES = M01_FEATURES.copy()  # Start with proven M01 feature set

# M01_3BAR_V2: Enhanced with Velocity Features (Phase 2: Ignition Engine)
# Adds velocity-specific features to distinguish igniters from drifters
M01_3BAR_FEATURES_V2 = M01_3BAR_FEATURES.copy()
M01_3BAR_FEATURES_V2.extend([
    # WorldQuant Slope Change Factors (Acceleration/Deceleration)
    'alpha046',  # Slope change detector (old slope - new slope)
    'alpha049',  # Slope deceleration (threshold -0.1)
    'alpha051',  # Slope deceleration (threshold -0.05)

    # Velocity Features (Custom)
    'rs_velocity',           # RS acceleration (5-day slope)
    'volume_acceleration',   # Volume surge detector (2nd derivative)
    'breakout_momentum',     # Breakout strength (ATR-normalized)
    'consolidation_duration',# Coil length (tight days count)
    'price_momentum_curve',  # Price acceleration (2nd derivative)
])

# Future Models (Placeholders)
# M02_FEATURES = [...]  # Regime Detection Model
# M03_FEATURES = [...]  # Liquidity Model


def get_model_features(model_name: str = 'M01') -> List[str]:
    """
    Get the feature list for a specific model.

    Args:
        model_name: 'M01', 'M01_3BAR', 'M01_3BAR_V2', 'M02', etc.

    Returns:
        List of feature column names.
    """
    registry = {
        'M01': M01_FEATURES,
        'M01_3BAR': M01_3BAR_FEATURES,
        'M01_3BAR_V2': M01_3BAR_FEATURES_V2,  # Phase 2: Velocity-enhanced
        # 'M02': M02_FEATURES,
    }

    if model_name not in registry:
        raise ValueError(f"Unknown model: {model_name}. Available: {list(registry.keys())}")

    return registry[model_name]
