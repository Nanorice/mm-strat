"""
Quantamental SEPA System (QSS) - Configuration File
Central configuration for all strategy parameters and system settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ==============================================================================
# DIRECTORY PATHS
# ==============================================================================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
# DEPRECATED: parquet per-ticker cache — replaced by direct DuckDB writes in Phase 1.
# Retained as cold backup only; existing files in data/price/ are not written to.
PRICE_DATA_DIR = DATA_DIR / 'price'
FUNDAMENTALS_DIR = DATA_DIR / 'fundamentals'
COMPANY_INFO_DIR = DATA_DIR / 'company_info'
EARNINGS_DIR = DATA_DIR / 'earnings'
MACRO_DATA_DIR = DATA_DIR / 'macro'
DATABASE_DIR = BASE_DIR / 'database'
NOTEBOOKS_DIR = BASE_DIR / 'notebooks'

# DuckDB database path (used by engines/pipelines)
DUCKDB_PATH = DATA_DIR / 'market_data.duckdb'

# Ensure directories exist
for dir_path in [PRICE_DATA_DIR, FUNDAMENTALS_DIR, COMPANY_INFO_DIR, EARNINGS_DIR, MACRO_DATA_DIR, DATABASE_DIR, NOTEBOOKS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# ==============================================================================
# DATA SETTINGS
# ==============================================================================
BENCHMARK_TICKER = 'SPY'

# Universe Selection Settings
UNIVERSE_SOURCE = 'FMP_SCREENER'  # Options: 'SSGA' (S&P 500), 'FMP_SCREENER'
SSGA_URL = 'https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx'

# FMP Stock Screener Filters (used when UNIVERSE_SOURCE = 'FMP_SCREENER')
FMP_SCREENER_PARAMS = {
    "marketCapMoreThan": 300000000,      # $300M minimum market cap
    "priceMoreThan": 5,                  # $5 minimum price
    "volumeMoreThan": 200000,            # 200K minimum daily volume
    "isEtf": "false",                    # Exclude ETFs
    "isActivelyTrading": "true",         # Only actively trading stocks
    "country": "US",                     # US stocks only
    "exchange": "NYSE,NASDAQ,AMEX",      # Major US exchanges
    "limit": 10000,                      # Max results (get all in one request)
    "isEtf": "false",
    "isFUnd": "false"
}

# Data Download Settings
LOOKBACK_PERIOD = '5y'  # History needed for technical indicators (SMA_200, 52W high/low, etc.)
BATCH_SIZE = 50  # Number of tickers to download per batch

# DEPRECATED: File age check removed in favor of data coverage validation
# This setting is no longer used by DataRepository
# Kept for backward compatibility with external scripts
DATA_CACHE_DAYS = 1  # Re-download if data older than N days

# New validation strategy:
# - Dataset building: Validates cache covers start_date to end_date
# - Scanner: Validates cache includes latest_trading_day
# - File modification time is NOT checked - only data coverage matters

# Financial Modeling Prep API Settings
FMP_API_KEY = os.getenv('FMP_API_KEY', '')  # Load from .env file
FMP_BASE_URL = 'https://financialmodelingprep.com/stable'
FMP_BATCH_SIZE = 50  # Target tickers per batch (actual batch size varies by URL length)

# Fred API Key
FRED_API_KEY = os.getenv('FRED_API_KEY', '')  # Load from .env file

# ==============================================================================
# MACROECONOMIC DATA SETTINGS (M03 Regime Model)
# ==============================================================================
# FRED Series for Net Liquidity calculation
# Net Liquidity = (WALCL/1000) - WTREGEN - RRPONTSYD
# Note: WALCL is in Millions, others are in Billions
FRED_SERIES = {
    'WALCL': {'name': 'Fed Total Assets', 'freq': 'W', 'unit': 'millions'},
    'WTREGEN': {'name': 'Treasury General Account', 'freq': 'W', 'unit': 'billions'},
    'RRPONTSYD': {'name': 'Reverse Repo (Overnight)', 'freq': 'D', 'unit': 'billions'},
    'BAMLH0A0HYM2': {'name': 'HY Credit Spread (OAS)', 'freq': 'D', 'unit': 'percent'},
    'DGS10': {'name': '10Y Treasury Yield', 'freq': 'D', 'unit': 'percent'},
    'DGS2': {'name': '2Y Treasury Yield', 'freq': 'D', 'unit': 'percent'},
    'WBAA': {'name': "Moody's Baa Corporate Yield", 'freq': 'W', 'unit': 'percent'},
}

# ==============================================================================
# BENCHMARK / ETF / INDEX UNIVERSE
# ==============================================================================
# Non-equity tradeable instruments added to price_data and company_profiles.
# - ticker_type drives ScreenerManager bypass and UniverseScorer exclusion.
# - sector uses 'ETF:<GICS>' namespace to avoid polluting equity cross-sectional ranks.
# - INDEX tickers retain '^' prefix (e.g. '^GSPC') — DuckDB stores as-is.

BENCHMARK_TICKERS = [
    {'ticker': 'SPY',   'name': 'SPDR S&P 500 ETF',                  'ticker_type': 'ETF',   'sector': 'ETF:Benchmark'},
    {'ticker': 'QQQ',   'name': 'Invesco QQQ Trust (Nasdaq-100)',    'ticker_type': 'ETF',   'sector': 'ETF:Benchmark'},
    {'ticker': '^GSPC', 'name': 'S&P 500 Index',                     'ticker_type': 'INDEX', 'sector': 'ETF:Benchmark'},
    {'ticker': '^DJI',  'name': 'Dow Jones Industrial Average',      'ticker_type': 'INDEX', 'sector': 'ETF:Benchmark'},
    {'ticker': '^IXIC', 'name': 'Nasdaq Composite',                  'ticker_type': 'INDEX', 'sector': 'ETF:Benchmark'},
    {'ticker': 'IWM',   'name': 'iShares Russell 2000 ETF',          'ticker_type': 'ETF',   'sector': 'ETF:Benchmark'},
    {'ticker': 'EFA',   'name': 'iShares MSCI EAFE (Developed ex-US)','ticker_type': 'ETF',  'sector': 'ETF:Benchmark'},
    {'ticker': 'EEM',   'name': 'iShares MSCI Emerging Markets',     'ticker_type': 'ETF',   'sector': 'ETF:Benchmark'},
]

SECTOR_ETFS = [
    {'ticker': 'XLE',  'name': 'Energy Select Sector SPDR',          'ticker_type': 'ETF', 'sector': 'ETF:Energy'},
    {'ticker': 'XLF',  'name': 'Financial Select Sector SPDR',       'ticker_type': 'ETF', 'sector': 'ETF:Financials'},
    {'ticker': 'XLK',  'name': 'Technology Select Sector SPDR',      'ticker_type': 'ETF', 'sector': 'ETF:Technology'},
    {'ticker': 'XLV',  'name': 'Health Care Select Sector SPDR',     'ticker_type': 'ETF', 'sector': 'ETF:Healthcare'},
    {'ticker': 'XLI',  'name': 'Industrial Select Sector SPDR',      'ticker_type': 'ETF', 'sector': 'ETF:Industrials'},
    {'ticker': 'XLY',  'name': 'Consumer Discretionary Select SPDR', 'ticker_type': 'ETF', 'sector': 'ETF:ConsumerCyclical'},
    {'ticker': 'XLP',  'name': 'Consumer Staples Select SPDR',       'ticker_type': 'ETF', 'sector': 'ETF:ConsumerDefensive'},
    {'ticker': 'XLU',  'name': 'Utilities Select Sector SPDR',       'ticker_type': 'ETF', 'sector': 'ETF:Utilities'},
    {'ticker': 'XLB',  'name': 'Materials Select Sector SPDR',       'ticker_type': 'ETF', 'sector': 'ETF:Materials'},
    {'ticker': 'XLRE', 'name': 'Real Estate Select Sector SPDR',     'ticker_type': 'ETF', 'sector': 'ETF:RealEstate'},
    {'ticker': 'SOXX', 'name': 'iShares Semiconductor ETF',          'ticker_type': 'ETF', 'sector': 'ETF:Semiconductors'},
    {'ticker': 'IBB',  'name': 'iShares Biotechnology ETF',          'ticker_type': 'ETF', 'sector': 'ETF:Biotech'},
    {'ticker': 'KRE',  'name': 'SPDR S&P Regional Banking',          'ticker_type': 'ETF', 'sector': 'ETF:RegionalBanks'},
    {'ticker': 'XOP',  'name': 'SPDR S&P Oil & Gas E&P',             'ticker_type': 'ETF', 'sector': 'ETF:OilGasEP'},
]

COMMODITY_ETFS = [
    {'ticker': 'GLD',  'name': 'SPDR Gold Shares',                   'ticker_type': 'ETF', 'sector': 'ETF:Commodity'},
    {'ticker': 'SLV',  'name': 'iShares Silver Trust',               'ticker_type': 'ETF', 'sector': 'ETF:Commodity'},
    {'ticker': 'CPER', 'name': 'United States Copper Index Fund',    'ticker_type': 'ETF', 'sector': 'ETF:Commodity'},
    {'ticker': 'USO',  'name': 'United States Oil Fund',             'ticker_type': 'ETF', 'sector': 'ETF:Commodity'},
    {'ticker': 'BNO',  'name': 'United States Brent Oil Fund',       'ticker_type': 'ETF', 'sector': 'ETF:Commodity'},
    {'ticker': 'UNG',  'name': 'United States Natural Gas Fund',     'ticker_type': 'ETF', 'sector': 'ETF:Commodity'},
    {'ticker': 'SOYB', 'name': 'Teucrium Soybean Fund',              'ticker_type': 'ETF', 'sector': 'ETF:Commodity'},
    {'ticker': 'WEAT', 'name': 'Teucrium Wheat Fund',                'ticker_type': 'ETF', 'sector': 'ETF:Commodity'},
    {'ticker': 'CORN', 'name': 'Teucrium Corn Fund',                 'ticker_type': 'ETF', 'sector': 'ETF:Commodity'},
    {'ticker': 'VEGI', 'name': 'iShares MSCI Agriculture Producers', 'ticker_type': 'ETF', 'sector': 'ETF:Commodity'},
    {'ticker': 'DBA',  'name': 'Invesco DB Agriculture Fund',        'ticker_type': 'ETF', 'sector': 'ETF:Commodity'},
    {'ticker': 'PDBC', 'name': 'Invesco Optimum Yield Diversified Commodity', 'ticker_type': 'ETF', 'sector': 'ETF:Commodity'},
    {'ticker': 'URA',  'name': 'Global X Uranium ETF',               'ticker_type': 'ETF', 'sector': 'ETF:Commodity'},
]

FIXED_INCOME_ETFS = [
    {'ticker': 'TLT', 'name': 'iShares 20+ Year Treasury Bond ETF',  'ticker_type': 'ETF', 'sector': 'ETF:FixedIncome'},
    {'ticker': 'HYG', 'name': 'iShares iBoxx High Yield Corporate',  'ticker_type': 'ETF', 'sector': 'ETF:FixedIncome'},
    {'ticker': 'LQD', 'name': 'iShares iBoxx Investment Grade Corp', 'ticker_type': 'ETF', 'sector': 'ETF:FixedIncome'},
    {'ticker': 'UUP', 'name': 'Invesco DB US Dollar Index Bullish',  'ticker_type': 'ETF', 'sector': 'ETF:FixedIncome'},
]

NON_EQUITY_UNIVERSE = BENCHMARK_TICKERS + SECTOR_ETFS + COMMODITY_ETFS + FIXED_INCOME_ETFS

# M03 Regime Score Thresholds (0-100 scale)
M03_REGIME_THRESHOLDS = {
    'strong_bull': 80,
    'bull': 60,
    'neutral': 40,
    'bear': 20,
}

# M03 Signal Gating
M03_LONG_ALLOW_MIN = 30   # Skip longs if regime score < 30
M03_LONG_REDUCED_MIN = 50  # Reduced sizing if regime score < 50

# ==============================================================================
# STRATEGY PARAMETERS - SEPA (Specific Entry Point Analysis)
# ==============================================================================

# Trend Filter (Stage 2 Detection)
SMA_FAST = 50
SMA_MEDIUM = 150
SMA_SLOW = 200
WEEKS_52_HIGH_THRESHOLD = 0.85  # Price must be within 15% of 52-week high
WEEKS_52_LOW_THRESHOLD = 1.30   # Price must be 30% above 52-week low

# Volatility Contraction Pattern (VCP)
CONSOLIDATION_PERIOD = 20  # Breakout of 20-day high
VOL_SPIKE_THRESHOLD = 1.3   # Volume must be 130% of average

# Relative Strength
RS_LOOKBACK = 63  # ~3 months for RS comparison vs SPY

# ATR (Average True Range)
ATR_PERIOD = 14

# ==============================================================================
# PORTFOLIO & RISK MANAGEMENT
# ==============================================================================

# Account Settings
INITIAL_CAPITAL = 100000  # Starting capital
MAX_POSITIONS = 8         # Maximum concurrent positions

# Position Sizing (Fixed Fractional)
POSITION_SIZE_PCT = 0.125  # 12.5% per position (1/8 of capital)

# Stop Loss (Fixed Percentage)
STOP_LOSS_PCT = 0.08  # 8% hard stop

# Profit Targets
PROFIT_TARGET_R = 3.0  # 3R profit target (3x risk)
TRAILING_STOP_SMA = 50  # Trail stop using 50-day SMA

# TODO: Add transaction costs later
# COMMISSION_PER_TRADE = 0.0  # Modern brokers are commission-free
# SLIPPAGE_PCT = 0.001  # 0.1% slippage assumption

# ==============================================================================
# BACKTEST SETTINGS
# ==============================================================================
BACKTEST_START_DATE = '2021-01-01'  # Start of backtest period
HISTORICAL_START_DATE = '2020-01-01'  # Extra data for indicator warmup

# ==============================================================================
# DATABASE SETTINGS
# ==============================================================================
DB_PATH = DATABASE_DIR / 'trades.db'
WATCHLIST_TABLE = 'watchlist'
TRADES_TABLE = 'trades'

# ==============================================================================
# REPORTING SETTINGS
# ==============================================================================
RISK_FREE_RATE = 0.04  # 4% annual risk-free rate for Sharpe calculation

# Performance Metrics
METRICS_TO_CALCULATE = [
    'total_return',
    'sharpe_ratio',
    'sortino_ratio',
    'max_drawdown',
    'win_rate',
    'profit_factor',
    'avg_win',
    'avg_loss',
    'expectancy'
]

# ==============================================================================
# FUNDAMENTAL DATA SETTINGS
# ==============================================================================
FUNDAMENTAL_CACHE_DAYS = 90  # Refresh quarterly (fundamentals update every ~90 days)
FUNDAMENTAL_LOOKBACK_YEARS = 5  # Historical fundamental data to fetch
FMP_FUNDAMENTAL_RATE_LIMIT = 300  # FMP Starter tier: 300 calls/minute
FMP_FUNDAMENTAL_BATCH_SIZE = 95  # Process 95 tickers at a time (95 * 3 calls = 285 calls, safe buffer)
FMP_FUNDAMENTAL_BATCH_DELAY = 5  # Small delay between batches (rate limiting is handled by _rate_limit_check)

# ==============================================================================
# FUNDAMENTAL FILTERS (PLACEHOLDER FOR FUTURE)
# ==============================================================================
# TODO: Implement fundamental filters once data is available
MIN_EARNINGS_GROWTH = None  # Placeholder: e.g., 0.15 for 15% YoY growth
MIN_SALES_GROWTH = None     # Placeholder: e.g., 0.10 for 10% YoY growth
EXCLUDED_SECTORS = []       # Placeholder: e.g., ['Utilities', 'Real Estate']

# ==============================================================================
# EARNINGS CALENDAR SETTINGS
# ==============================================================================
EARNINGS_CACHE_DAYS = 7  # Refresh earnings cache weekly (earnings dates rarely change)
EARNINGS_LOOKBACK_LIMIT = 1000  # Historical earnings to fetch per ticker
EARNINGS_ALERT_DAYS = 14  # Refresh cache if next earnings within this window (2 weeks)

# ==============================================================================
# COMPANY PROFILE SETTINGS
# ==============================================================================
COMPANY_PROFILE_CACHE_DAYS = 30  # Company info changes infrequently

# ==============================================================================
# MACHINE LEARNING SETTINGS
# ==============================================================================
# Production ML Model Configuration
ML_PRODUCTION_MODEL = 'models/model_m01.json'  # Path to production model
ML_MODEL_TYPE = 'regression'  # 'regression' or 'classification'

# Dual-Model Configuration (M01 + M02)
# M01: Regression model predicting expected return %
# M02: Classification model predicting ignition probability (triple barrier)
ML_M01_MODEL = 'models/model_m01.json'           # M01: Regressor (Expected Return %)
ML_M02_MODEL = 'models/model_m02.json'           # M02: Classifier (Ignition Probability)

# Legacy alias for backward compatibility (deprecated - use ML_M02_MODEL)
ML_M01_3BAR_MODEL = 'models/model_m01_3bar_v2.json'

# Triple Barrier Parameters (from M02 training config)
BARRIER_K_SL = 1.0      # Stop loss = Close - (k_sl × ATR)
BARRIER_K_TP = 4.0      # Profit target ATR multiplier
BARRIER_MIN_TP = 0.2    # Minimum 20% profit target
BARRIER_MAX_TIME = 30   # Maximum trading days

# Legacy settings (for backward compatibility)
ML_ENABLED = False
ML_MODEL_PATH = None
ML_CONFIDENCE_THRESHOLD = 0.6  # Only take trades with >60% ML confidence

# ==============================================================================
# PIPELINE ORCHESTRATION CONFIGURATION
# ==============================================================================

from enum import Enum

class PipelineFailureMode(Enum):
    """How to handle phase failures."""
    HALT = "halt"       # Stop pipeline immediately (critical phase)
    WARN = "warn"       # Log warning, continue (non-critical phase)
    SKIP = "skip"       # Skip phase, continue (optional phase)


# Pipeline failure modes per phase
# HALT: Critical phases that must succeed (price data, daily_features)
# WARN: Non-critical phases that can fail without blocking (fundamentals, macro)
# SKIP: Optional phases (T3 lazy can lag by 1 day)
PIPELINE_FAILURE_MODES = {
    # Phase 1: T1 Ingestion
    "phase_1_t1_price": PipelineFailureMode.HALT,         # CRITICAL - can't proceed without prices
    "phase_1_t1_fundamentals": PipelineFailureMode.WARN,  # Non-critical - stale data OK
    "phase_1_t1_shares": PipelineFailureMode.WARN,        # Non-critical - use previous shares
    "phase_1_t1_macro": PipelineFailureMode.WARN,         # Non-critical - M03 will use previous scores

    # Phase 2-3: T2 Screener
    "phase_2_screener_membership": PipelineFailureMode.HALT,  # CRITICAL - needed for T2 features
    "phase_3_t2_screener": PipelineFailureMode.HALT,          # CRITICAL - needed for T3

    # Phase 4: T2 Regime
    "phase_4_t2_regime": PipelineFailureMode.WARN,        # Non-critical - daily_features will use NULLs

    # Phase 5: daily_features
    "phase_5_daily_features": PipelineFailureMode.HALT,   # CRITICAL - needed for T3

    # Phase 6-8: T3 + Views
    "phase_6_t3_lazy": PipelineFailureMode.WARN,          # Non-critical - T3 can lag by 1 day
    "phase_7_views": PipelineFailureMode.WARN,            # Non-critical - views are recreatable
    "phase_8_cache": PipelineFailureMode.WARN,            # Non-critical - cache is optional
}

# Alert thresholds
PIPELINE_ALERT_THRESHOLDS = {
    'breakout_drought_days': 5,      # Alert if 0 breakouts for N days
    'failure_rate_threshold': 0.1,    # Alert if failure rate >10%
    't1_price_coverage_warn_pct': 80.0,   # Audit warn threshold (audit_t1_data_quality.py)
    't1_price_coverage_retry_pct': 90.0,  # Phase 1.5 same-run retry trigger
}

# ==============================================================================
# LOGGING & OUTPUT
# ==============================================================================
LOG_LEVEL = 'INFO'  # DEBUG, INFO, WARNING, ERROR
SAVE_TRADE_LOGS = True
EXPORT_FORMAT = 'html'  # Options: 'html', 'pdf', 'csv'
