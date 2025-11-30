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
DATABASE_DIR = BASE_DIR / 'database'
NOTEBOOKS_DIR = BASE_DIR / 'notebooks'

# Ensure directories exist
for dir_path in [PRICE_DATA_DIR, FUNDAMENTALS_DIR, DATABASE_DIR, NOTEBOOKS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# ==============================================================================
# DATA SETTINGS
# ==============================================================================
BENCHMARK_TICKER = 'SPY'
UNIVERSE_SOURCE = 'SSGA'  # State Street S&P 500 Holdings
SSGA_URL = 'https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx'

# Data Download Settings
LOOKBACK_PERIOD = '5y'  # History needed for technical indicators (SMA_200, 52W high/low, etc.)
BATCH_SIZE = 50  # Number of tickers to download per batch
DATA_CACHE_DAYS = 1  # Re-download if data older than N days

# Financial Modeling Prep API Settings
FMP_API_KEY = os.getenv('FMP_API_KEY', '')  # Load from .env file
FMP_BASE_URL = 'https://financialmodelingprep.com/stable'
FMP_BATCH_SIZE = 50  # Target tickers per batch (actual batch size varies by URL length)

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
FMP_FUNDAMENTAL_BATCH_SIZE = 10  # Process 10 tickers at a time
FMP_FUNDAMENTAL_BATCH_DELAY = 2.5  # Delay between batches (seconds) to respect rate limits

# ==============================================================================
# FUNDAMENTAL FILTERS (PLACEHOLDER FOR FUTURE)
# ==============================================================================
# TODO: Implement fundamental filters once data is available
MIN_EARNINGS_GROWTH = None  # Placeholder: e.g., 0.15 for 15% YoY growth
MIN_SALES_GROWTH = None     # Placeholder: e.g., 0.10 for 10% YoY growth
EXCLUDED_SECTORS = []       # Placeholder: e.g., ['Utilities', 'Real Estate']

# ==============================================================================
# MACHINE LEARNING SETTINGS (PLACEHOLDER FOR FUTURE)
# ==============================================================================
# TODO: Meta-labeling with Random Forest
ML_ENABLED = False
ML_MODEL_PATH = None
ML_CONFIDENCE_THRESHOLD = 0.6  # Only take trades with >60% ML confidence

# ==============================================================================
# LOGGING & OUTPUT
# ==============================================================================
LOG_LEVEL = 'INFO'  # DEBUG, INFO, WARNING, ERROR
SAVE_TRADE_LOGS = True
EXPORT_FORMAT = 'html'  # Options: 'html', 'pdf', 'csv'
