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
PRICE_DATA_DIR = DATA_DIR / 'price'
FUNDAMENTALS_DIR = DATA_DIR / 'fundamentals'
COMPANY_INFO_DIR = DATA_DIR / 'company_info'
EARNINGS_DIR = DATA_DIR / 'earnings'
MACRO_DATA_DIR = DATA_DIR / 'macro'
DATABASE_DIR = BASE_DIR / 'database'
NOTEBOOKS_DIR = BASE_DIR / 'notebooks'

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
}

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
WEEKS_52_HIGH_THRESHOLD = 0.75  # Price must be within 25% of 52-week high
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
# LOGGING & OUTPUT
# ==============================================================================
LOG_LEVEL = 'INFO'  # DEBUG, INFO, WARNING, ERROR
SAVE_TRADE_LOGS = True
EXPORT_FORMAT = 'html'  # Options: 'html', 'pdf', 'csv'
