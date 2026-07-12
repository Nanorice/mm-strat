"""
Quantamental SEPA System (QSS) - Configuration File
Central configuration for all strategy parameters and system settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env. Anchor to this file's directory so the
# vars load regardless of CWD — Task Scheduler runs with CWD=C:\Windows\System32,
# where a bare load_dotenv() finds nothing and silently leaves R2 creds unset.
load_dotenv(Path(__file__).resolve().parent / ".env")

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
# DUCKDB RESOURCE LIMITS
# ==============================================================================
# Single source of truth for DuckDB memory/thread governance. DuckDB otherwise
# defaults to ~80% of physical RAM and one thread per core. On a shared 16GB box
# two ungoverned DuckDB processes (the orchestrator + the dashboard-build
# subprocess) can exhaust RAM and starve a parallel agent. With a memory_limit
# set, heavy window-function queries spill to temp_directory instead of OOMing.
# Override per-machine via environment variables.
DUCKDB_MEMORY_LIMIT = os.getenv('DUCKDB_MEMORY_LIMIT', '6GB')
DUCKDB_THREADS = int(os.getenv('DUCKDB_THREADS', '4'))
DUCKDB_TEMP_DIR = os.getenv('DUCKDB_TEMP_DIR', str(DATA_DIR / '.duckdb_tmp'))

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

# SEC EDGAR — no API key required, but SEC mandates a User-Agent header
# identifying the requester (Name + Email). Rate limit: 10 req/sec.
# Format: "Quantamental Research yourname@example.com"
EDGAR_USER_AGENT = os.getenv('EDGAR_USER_AGENT', 'Quantamental Research contact@example.com')
EDGAR_RATE_LIMIT_PER_SEC = 10
EDGAR_TICKERS_URL = 'https://www.sec.gov/files/company_tickers.json'
EDGAR_SUBMISSIONS_URL = 'https://data.sec.gov/submissions/CIK{cik:010d}.json'

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
    'DFII10': {'name': '10Y Real Yield (TIPS)', 'freq': 'D', 'unit': 'percent'},
    'WBAA': {'name': "Moody's Baa Corporate Yield", 'freq': 'W', 'unit': 'percent'},
    'CPIAUCSL': {'name': 'CPI (All Urban, SA)', 'freq': 'M', 'unit': 'index'},  # deflator for CAPE_OURS
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

# A ticker's fundamentals are stale when last period_end > this many days ago.
# Co-equal trigger alongside the earnings_calendar in update_fundamentals: catches
# ghost tickers (no calendar row) and any case where the calendar refresh missed them.
FUNDAMENTAL_STALENESS_DAYS = 100

# Expected lag from a fiscal quarter-end to its NEXT 10-Q filing: ~90d to the next
# quarter-end + ~45d to file = ~135d. The DQ staleness check flags a ticker only
# when today is past (last_period_end + this), i.e. the next quarter is genuinely
# overdue — NOT merely >FUNDAMENTAL_STALENESS_DAYS since the last filing (which a
# healthy filer crosses every quarter while waiting for the next report). Anchoring
# on period_end (the quarter we have) rather than filing_date (which says nothing
# about when the next quarter is due) removes the per-quarter false positives.
EXPECTED_NEXT_FILING_LAG_DAYS = 135

# How often the earnings_calendar must be refreshed. Gated on the last successful
# phase_1_earnings_calendar_refresh entry in pipeline_runs.
EARNINGS_CALENDAR_REFRESH_DAYS = 7

# Filing-date backfill (Phase 1.x): cap tickers per daily run to keep latency
# bounded. SEC EDGAR rate limit is 10 req/sec → 200 tickers ≈ 20s.
# Only rows where period_end is older than FILING_BACKFILL_MIN_AGE_DAYS are
# eligible — recent quarters' 10-Q filings typically land 30-45d after period_end.
FILING_BACKFILL_MAX_TICKERS = 200
FILING_BACKFILL_MIN_AGE_DAYS = 30

# How often to refresh the ticker→CIK map from SEC. Gated on the last successful
# phase_1_cik_map_refresh entry in pipeline_runs.
CIK_MAP_REFRESH_DAYS = 7

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


# Pipeline failure modes per phase, keyed by STABLE phase id.
#
# This is the single source of truth for failure handling. src.orchestrators.
# phase_registry imports this map and attaches display labels + sort order — the
# registry is the source of truth for label/order, this dict for failure mode.
# (config must stay low-level: it does NOT import the registry, to avoid a cycle.)
#
# The "sub-phase" keys (phase_1_t1_*, etc.) are bookkeeping tags written via
# record_write/record_errors, not orchestrated phases. phase_1_t1_price is read
# by the orchestrator's price-ingestion HALT check, so it must stay HALT.
PIPELINE_FAILURE_MODES = {
    # --- Sub-phase bookkeeping keys (not orchestrated phases) ---
    "phase_1_t1_price": PipelineFailureMode.HALT,         # CRITICAL - drives Phase 1 ingestion HALT check
    "phase_1_t1_fundamentals": PipelineFailureMode.WARN,  # Non-critical - stale data OK
    "phase_1_t1_shares": PipelineFailureMode.WARN,        # Non-critical - use previous shares
    "phase_1_t1_macro": PipelineFailureMode.WARN,         # Non-critical - M03 will use previous scores
    "phase_1_cik_map_refresh": PipelineFailureMode.WARN,         # Non-critical - cik_map staleness only delays new SEC filings
    "phase_1_filing_date_backfill": PipelineFailureMode.WARN,    # Non-critical - fills NULL filing_dates from SEC EDGAR
    "phase_1_earnings_calendar_refresh": PipelineFailureMode.WARN,  # Non-critical - weekly cadence

    # --- Orchestrated phases (stable ids; order+label live in phase_registry) ---
    "ingestion":           PipelineFailureMode.HALT,
    "screener_membership": PipelineFailureMode.HALT,
    "t2_screener":         PipelineFailureMode.HALT,
    "t2_regime":           PipelineFailureMode.WARN,
    "sepa_watchlist":      PipelineFailureMode.HALT,
    "t3_features":         PipelineFailureMode.HALT,
    "views":               PipelineFailureMode.WARN,
    "cache":               PipelineFailureMode.WARN,
    "scoring":             PipelineFailureMode.WARN,
    "weather":             PipelineFailureMode.WARN,   # advisory gauge; never halts the run
    "dashboard_db":        PipelineFailureMode.WARN,
    "r2_sync":             PipelineFailureMode.WARN,
    "monitoring":          PipelineFailureMode.WARN,
    "model_card":          PipelineFailureMode.WARN,
}

# Alert thresholds
PIPELINE_ALERT_THRESHOLDS = {
    'breakout_drought_days': 5,      # Alert if 0 breakouts for N days
    'failure_rate_threshold': 0.1,    # Alert if failure rate >10%
    't1_price_coverage_warn_pct': 80.0,   # Audit warn threshold (audit_t1_data_quality.py)
    't1_price_coverage_retry_pct': 90.0,  # Phase 1.5 same-run retry trigger
}

# T1 plausibility bounds — single source of truth for engine write clamps, the Phase 1.6
# gate, audit_t1_data_quality.py, and clean_dirty_shares_price.py. Absolute bounds only:
# nothing legitimate sits above them (see sprint_13 ISSUE_dirty_shares_cap_dq_gap.md).
T1_PLAUSIBILITY_BOUNDS = {
    'shares_max': 3e10,        # real max ~25B split-adj (AAPL); C peaked ~29B pre-2011 rev split
    'close_max': 1e6,          # real US max ~$810k/share (BRK-A)
    'implied_cap_max': 8e12,   # largest company ever ~$4.7T
    'shares_scale_abs': 1e9,   # relative tripwire: only values > 1B shares...
    'shares_scale_ratio': 500, # ...that are also > 500x the ticker's own median (audit-only —
                               #    needs full history; EXE was 200x legit pre-1:200 rev split)
    'ohlc_excess_fail': 0.10,  # ordering violation > 10% = corrupt bar (FAIL)
    'ohlc_excess_warn': 0.001, # 0.1%-10% = live-feed tape artifact (WARN); below = rounding
}

# Minimum plausible gap between period_end and a real 10-Q filing_date. Shared by
# fundamental_engine._sanitize_filing_dates and the audit's fast-filing check.
FILING_MIN_REAL_GAP_DAYS = 8

# ==============================================================================
# LOGGING & OUTPUT
# ==============================================================================
LOG_LEVEL = 'INFO'  # DEBUG, INFO, WARNING, ERROR
SAVE_TRADE_LOGS = True
EXPORT_FORMAT = 'html'  # Options: 'html', 'pdf', 'csv'
