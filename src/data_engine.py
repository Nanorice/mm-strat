"""
Data Engine - DataRepository Class
Handles universe management, data downloading, and DuckDB price ingestion.
"""

import pandas as pd
import numpy as np
import yfinance as yf
import duckdb
from src import db
import requests
import json
import time
import concurrent.futures
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Tuple
from enum import Enum
import logging
from tqdm import tqdm
import sys
sys.path.append(str(Path(__file__).parent.parent))
import config
from src.utils import get_latest_trading_day

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL))
logger = logging.getLogger(__name__)

# Historical data fetch start date (can be adjusted for older data)
DEFAULT_HISTORICAL_START_DATE = '2000-01-01'


class CacheMode(Enum):
    """
    Data access modes for DataRepository cache validation.
    
    Use these modes to clearly indicate your data freshness requirements:
    
    - LIVE: For scanners/dashboards that need today's data. Will check if cache
            has the latest trading day and can trigger API updates if stale.
    
    - HISTORICAL: For model training/backtesting on a specific date range.
                  Only validates that data covers the required range, does NOT
                  check for latest trading day. No API calls.
    
    - CACHE_ONLY: For feature extraction/parallel processing. Uses whatever
                  exists in cache without any validation. No API calls.
    """
    LIVE = "live"           # Scanners: requires today's data, may auto-update
    HISTORICAL = "historical"  # Training: validates date range only, no "latest day" check
    CACHE_ONLY = "cache_only"  # Feature extraction: use as-is, no validation


class DataRepository:
    """
    Single source of truth for all market data.
    Implements smart Parquet caching to minimize API calls and bandwidth.
    """

    def __init__(self, db_path: str = None, enable_validation: bool = True):
        if db_path is None:
            db_path = str(Path(__file__).parent.parent / "data" / "market_data.duckdb")
        self.db_path = db_path
        self.price_dir = config.PRICE_DATA_DIR  # read-only cold backup; not written to
        self.benchmark_ticker = config.BENCHMARK_TICKER
        self.cache_days = config.DATA_CACHE_DAYS

        # API call tracking for rate limiting (300 calls/minute like fundamentals)
        self._call_timestamps = []
        self._rate_limit_lock = threading.Lock()
        self.rate_limit = 250  # FMP Starter tier is 300, use 250 for safety margin

        # Global cooldown for 429 errors - when set, all workers wait
        self._global_cooldown_until = 0
        self._cooldown_lock = threading.Lock()

        # IPO validation settings
        self.enable_validation = enable_validation
        self._ipo_cache = {}  # Cache for IPO dates to avoid repeated API calls

        # Error tracking: populated after each update_cache() call
        # List of (ticker, error_detail) for tickers that failed
        self.last_errors: List[Tuple[str, Optional[str]]] = []

    def get_screener_universe(self) -> List[str]:
        """
        Fetch ticker universe from FMP stock screener API.
        Applies filters for market cap, price, volume, exchange, etc.
        
        Returns:
            List of ticker symbols matching screener criteria
        """
        if not config.FMP_API_KEY:
            logger.warning("FMP_API_KEY not set, cannot use screener")
            return []
        
        logger.info("Fetching ticker universe from FMP stock screener...")
        
        try:
            url = f"{config.FMP_BASE_URL}/company-screener"
            params = config.FMP_SCREENER_PARAMS.copy()
            params['apikey'] = config.FMP_API_KEY
            
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if not isinstance(data, list):
                logger.warning(f"Unexpected screener response format: {type(data)}")
                return []
            
            # Extract ticker symbols from response
            tickers = []
            for company in data:
                if isinstance(company, dict) and 'symbol' in company:
                    symbol = str(company['symbol']).strip()
                    # Filter out invalid symbols (e.g., too long, has special chars)
                    if len(symbol) > 0 and len(symbol) <= 5 and symbol.isalnum():
                        tickers.append(symbol.replace('.', '-'))
            
            unique_tickers = list(set(tickers))
            logger.info(f"Successfully loaded {len(unique_tickers)} tickers from FMP screener")
            return unique_tickers
            
        except Exception as e:
            logger.error(f"FMP screener failed: {e}")
            return []

    def update_universe(self, source: str = None) -> List[str]:
        """
        Fetches ticker universe from specified source.
        
        Args:
            source: Universe source - 'PRICE_FOLDER' (cached tickers), 'SSGA' (S&P 500), or 'FMP_SCREENER'. 
                   If None, defaults to PRICE_FOLDER
        
        Returns:
            List of clean ticker symbols
        """
        # Default to price folder (largest population)
        if source is None:
            source = 'PRICE_FOLDER'
        
        logger.info(f"Fetching ticker universe from source: {source}")
        
        # Try price folder first (default - uses all cached tickers)
        if source == 'PRICE_FOLDER':
            try:
                logger.info("Scanning data/price folder for tickers...")
                price_files = list(self.price_dir.glob('*.parquet'))
                if price_files:
                    tickers_from_files = [f.stem for f in price_files]
                    # Filter out benchmark and universe files if present
                    tickers_from_files = [t for t in tickers_from_files 
                                          if t != self.benchmark_ticker 
                                          and not t.startswith('universe_')]
                    logger.info(f"Found {len(tickers_from_files)} tickers from price folder")
                    return tickers_from_files
                else:
                    logger.warning("Price folder is empty, falling back to S&P 500...")
                    # Fall through to S&P 500 fallback
            except Exception as e:
                logger.warning(f"Failed to scan price folder: {e}, falling back to S&P 500...")
                # Fall through to S&P 500 fallback
        
        # FMP Screener (if explicitly requested)
        if source == 'FMP_SCREENER':
            tickers = self.get_screener_universe()
            if tickers:
                return tickers
            logger.warning("FMP screener failed, falling back to S&P 500...")
            # Fall through to S&P 500 fallback
        
        # S&P 500 from SSGA (either explicit request or fallback)
        try:
            logger.info("Fetching S&P 500 universe from SSGA...")
            df = pd.read_excel(config.SSGA_URL, engine='openpyxl', skiprows=4)
            tickers = df['Ticker'].dropna().tolist()

            # Clean tickers (remove cash, fix formatting)
            clean_tickers = []
            for t in tickers:
                t = str(t).strip()
                if len(t) > 0 and t != 'CASH_USD' and len(t) <= 5:
                    clean_tickers.append(t.replace('.', '-'))

            unique_tickers = list(set(clean_tickers))
            logger.info(f"Successfully loaded {len(unique_tickers)} unique tickers from S&P 500")
            return unique_tickers

        except Exception as e:
            logger.warning(f"Failed to fetch SSGA data: {e}")
            
            # Last resort: Use hardcoded tech-heavy subset
            logger.warning("Using hardcoded fallback ticker list")
            return ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'TSLA',
                    'AMD', 'PLTR', 'SMCI', 'JPM', 'V', 'MA', 'LLY', 'AVGO']

    def _get_stale_tickers(self, latest_trading_day: str) -> List[str]:
        """
        Active tickers in company_profiles missing a price row for latest_trading_day,
        but only those with at least one valid row in the last 45 days.

        Blacklisted tickers are already removed from company_profiles, so no
        additional filtering is needed here.
        """
        conn = db.connect(self.db_path)
        try:
            cutoff = (pd.Timestamp(latest_trading_day) - pd.Timedelta(days=45)).strftime('%Y-%m-%d')

            rows = conn.execute("""
                SELECT cp.ticker
                FROM company_profiles cp
                INNER JOIN (
                    SELECT DISTINCT ticker
                    FROM price_data
                    WHERE date >= ?
                ) recent ON cp.ticker = recent.ticker
                LEFT JOIN (
                    SELECT DISTINCT ticker
                    FROM price_data
                    WHERE date = ?
                ) fresh ON cp.ticker = fresh.ticker
                WHERE cp.is_active = TRUE
                  AND fresh.ticker IS NULL
                ORDER BY cp.ticker
            """, [cutoff, latest_trading_day]).fetchall()

            stale = [r[0] for r in rows]

            fresh_count = conn.execute(
                "SELECT COUNT(DISTINCT ticker) FROM price_data WHERE date = ?",
                [latest_trading_day]
            ).fetchone()[0]
            total = conn.execute(
                "SELECT COUNT(*) FROM company_profiles WHERE is_active = TRUE"
            ).fetchone()[0]

            if stale:
                logger.info(f"[Phase 1] Staleness: {len(stale)}/{total} stale (target={latest_trading_day})")
                logger.debug(f"[Phase 1] Stale sample: {', '.join(stale[:10])}")
            else:
                logger.info(f"[Phase 1] All {total} tickers fresh for {latest_trading_day}")
            return stale
        finally:
            conn.close()

    def _get_all_active_tickers(self) -> List[str]:
        """All active tickers from company_profiles. Used by force=True path."""
        conn = db.connect(self.db_path)
        try:
            return [r[0] for r in conn.execute(
                "SELECT ticker FROM company_profiles WHERE is_active = TRUE ORDER BY ticker"
            ).fetchall()]
        finally:
            conn.close()

    def _is_cache_stale(self, file_path: Path,
                        mode: CacheMode = None,
                        date_range: Optional[Tuple[str, str]] = None,
                        # Legacy parameters (for backward compatibility)
                        current_market_date: Optional[pd.Timestamp] = None,
                        min_date: str = '2000-01-01', check_min_date: bool = False,
                        required_end_date: Optional[pd.Timestamp] = None,
                        force_cache_only: bool = False) -> bool:
        """
        Check if cached data is stale based on access mode.
        
        NEW API (recommended):
            mode: CacheMode enum value (LIVE, HISTORICAL, or CACHE_ONLY)
            date_range: Tuple of (start_date, end_date) for HISTORICAL mode validation
        
        LEGACY API (deprecated, for backward compatibility):
            force_cache_only, check_min_date, required_end_date, etc.
        
        Args:
            file_path: Path to parquet cache file
            mode: Data access mode - LIVE (scanner), HISTORICAL (training), or CACHE_ONLY
            date_range: Required (start, end) date range for HISTORICAL mode
            current_market_date: (Legacy) Latest trading day for LIVE mode
            min_date: (Legacy) Minimum required start date
            check_min_date: (Legacy) If True, validates cache starts at or before min_date
            required_end_date: (Legacy) Validates cache covers up to this date
            force_cache_only: (Legacy) Maps to CACHE_ONLY mode
        
        Returns:
            True if cache is stale/incomplete, False otherwise
        """
        # Backward compatibility: map legacy flags to CacheMode
        if mode is None:
            if force_cache_only:
                mode = CacheMode.CACHE_ONLY
            elif required_end_date is not None or check_min_date:
                mode = CacheMode.HISTORICAL
                # Build date_range from legacy params if not provided
                if date_range is None and required_end_date is not None:
                    date_range = (min_date if check_min_date else None, 
                                  required_end_date.strftime('%Y-%m-%d') if required_end_date else None)
            else:
                mode = CacheMode.LIVE
        
        # CACHE_ONLY: Never stale if file exists (fastest path)
        if mode == CacheMode.CACHE_ONLY:
            return not file_path.exists()
        
        if not file_path.exists():
            return True
        
        try:
            # Read only the index (dates) from parquet - super fast!
            df = pd.read_parquet(file_path, columns=[])
            
            # Check index length instead of df.empty (df.empty returns True when columns=[] even with data)
            if len(df.index) == 0:
                return True
                
            cache_start_date = df.index.min().date()
            cache_end_date = df.index.max().date()
            
            if mode == CacheMode.HISTORICAL:
                # HISTORICAL mode: Only validate date range, NO "latest trading day" check
                if date_range:
                    if date_range[0]:  # Check start date
                        required_start = pd.Timestamp(date_range[0]).date()
                        if cache_start_date > required_start:
                            return True
                    if date_range[1]:  # Check end date
                        required_end = pd.Timestamp(date_range[1]).date()
                        if cache_end_date < required_end:
                            return True
                # Legacy support: check_min_date without date_range
                elif check_min_date:
                    required_start = pd.Timestamp(min_date).date()
                    if cache_start_date > required_start:
                        return True
                    if required_end_date is not None:
                        target_end = required_end_date.date()
                        if cache_end_date < target_end:
                            return True
                return False  # HISTORICAL: never checks latest trading day!
            
            elif mode == CacheMode.LIVE:
                # LIVE mode: Must have latest trading day
                if current_market_date is None:
                    current_market_date = get_latest_trading_day()
                
                target_date = current_market_date.date()
                if cache_end_date < target_date:
                    return True
                return False
            
        except Exception as e:
            logger.debug(f"Cache staleness check failed for {file_path.stem}: {e}")
            return True    
    
    def _trigger_global_cooldown(self, duration_seconds: float = 5.0):
        """
        Trigger a brief cooldown if we hit 429 (shouldn't happen with fixed-rate throttling).
        """
        with self._cooldown_lock:
            new_cooldown = time.time() + duration_seconds
            if new_cooldown > self._global_cooldown_until:
                self._global_cooldown_until = new_cooldown
    
    def _wait_for_cooldown(self):
        """Wait if there's an active cooldown."""
        with self._cooldown_lock:
            cooldown_until = self._global_cooldown_until
        
        now = time.time()
        if cooldown_until > now:
            time.sleep(cooldown_until - now)
    
    def _rate_limit_check(self):
        """
        Fixed-rate throttling for FMP API at 300 calls/minute.
        
        Simple approach: Each request waits 0.2 seconds (5 requests/second = 300/minute).
        This is more predictable than reactive backoff and avoids 429 errors entirely.
        """
        # Check for any active cooldown from 429 errors
        self._wait_for_cooldown()
        
        # Fixed delay: 0.2 seconds = 5 requests/second = 300/minute
        # Use lock to ensure consistent pacing across workers
        with self._rate_limit_lock:
            now = time.time()
            if self._call_timestamps:
                last_call = self._call_timestamps[-1]
                elapsed = now - last_call
                min_interval = 0.2  # 300 calls/minute = 5 calls/second
                if elapsed < min_interval:
                    time.sleep(min_interval - elapsed)
            
            # Record this call
            self._call_timestamps.append(time.time())
            # Keep only last 10 timestamps to avoid memory growth
            if len(self._call_timestamps) > 10:
                self._call_timestamps = self._call_timestamps[-10:]

    def _get_ipo_date(self, ticker: str) -> Optional[pd.Timestamp]:
        """
        Fetch IPO date from FMP company profile API with caching.

        Args:
            ticker: Stock symbol

        Returns:
            IPO date as Timestamp, or None if not available
        """
        # Check cache first
        if ticker in self._ipo_cache:
            return self._ipo_cache[ticker]

        if not config.FMP_API_KEY:
            return None

        try:
            url = f"{config.FMP_BASE_URL}/profile/{ticker}"
            params = {'apikey': config.FMP_API_KEY}

            response = requests.get(url, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()

                if isinstance(data, list) and len(data) > 0:
                    profile = data[0]
                    ipo_date = profile.get('ipoDate')

                    if ipo_date and ipo_date != '':
                        ipo_timestamp = pd.to_datetime(ipo_date)
                        self._ipo_cache[ticker] = ipo_timestamp
                        return ipo_timestamp

            # Cache None result to avoid repeated failed lookups
            self._ipo_cache[ticker] = None
            return None

        except Exception as e:
            logger.debug(f"Could not fetch IPO date for {ticker}: {e}")
            self._ipo_cache[ticker] = None
            return None

    def _validate_and_trim_data(self, df: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
        """
        Validate price data and trim to IPO date if validation is enabled.

        Args:
            df: Price DataFrame with Date index
            ticker: Stock symbol

        Returns:
            Validated/trimmed DataFrame, or None if validation fails
        """
        if not self.enable_validation:
            return df

        if df is None or df.empty:
            return None

        # Get IPO date
        ipo_date = self._get_ipo_date(ticker)

        if ipo_date:
            data_start = df.index.min()

            if data_start < ipo_date:
                years_before = (ipo_date - data_start).days / 365.25
                logger.warning(
                    f"{ticker}: Data starts {years_before:.1f} years before IPO "
                    f"({data_start.date()} < {ipo_date.date()}). Trimming to IPO date."
                )

                # Trim data to start from IPO
                df = df[df.index >= ipo_date]

                if df.empty:
                    logger.error(f"{ticker}: No data after IPO date filter")
                    return None

        # Additional validation checks
        if df['Close'].min() <= 0:
            logger.error(f"{ticker}: Invalid data - zero or negative prices")
            return None

        if df.index.min().year < 1970:
            logger.error(f"{ticker}: Invalid data - unrealistic start date ({df.index.min().year})")
            return None

        return df


    def _fetch_fmp_historical(self, ticker: str, from_date: str = None, max_retries: int = 5, force_from_date: bool = False) -> Optional[dict]:
        """
        Fetch historical OHLCV data from FMP API for a single ticker with smart retry logic.
        Implements INCREMENTAL fetching - only downloads data since last cached date.
        NOTE: FMP Starter tier does NOT support batch requests for historical data.

        Args:
            ticker: Single ticker symbol
            from_date: Start date for historical data (default: DEFAULT_HISTORICAL_START_DATE)
            max_retries: Maximum number of retries for transient errors (default: 5)
            force_from_date: If True, use from_date directly without checking cache (for full historical fetch)

        Returns:
            JSON response dict with historical data, or None if failed
        """
        import random
        
        if not config.FMP_API_KEY:
            raise ValueError("FMP_API_KEY not set in environment")

        # Use default if not specified
        if from_date is None:
            from_date = DEFAULT_HISTORICAL_START_DATE

        # Calculate optimal start date for incremental fetch
        # (Skip this logic if force_from_date is True - user wants full historical data)
        if not force_from_date:
            conn = db.connect(self.db_path)
            try:
                result = conn.execute(
                    "SELECT MAX(date) FROM price_data WHERE ticker = ?", [ticker]
                ).fetchone()
                last_date = result[0] if result and result[0] else None
            finally:
                conn.close()
            if last_date:
                from_date = (pd.Timestamp(last_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            else:
                from_date = DEFAULT_HISTORICAL_START_DATE
        
        url = f"{config.FMP_BASE_URL}/historical-price-eod/full"
        params = {
            'symbol': ticker,
            'from': from_date,
            'apikey': config.FMP_API_KEY
        }
        
        last_error = None
        for attempt in range(max_retries):
            # Rate limiting
            self._rate_limit_check()
            
            try:
                response = requests.get(url, params=params, timeout=30)
                
                # Handle 429 rate limit errors with exponential backoff + jitter
                if response.status_code == 429:
                    self._trigger_global_cooldown(5.0)
                    if attempt < max_retries - 1:
                        wait_time = 3 * (attempt + 1) + random.uniform(0, 2)
                        logger.debug(f"{ticker}: Rate limit (429), retrying in {wait_time:.1f}s... ({attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.debug(f"{ticker}: Rate limit (429), max retries exceeded")
                        return None

                # Handle server errors (5xx) - retry with backoff
                if 500 <= response.status_code < 600:
                    if attempt < max_retries - 1:
                        wait_time = (2 ** attempt) * 2 + random.uniform(0, 1)
                        logger.debug(f"{ticker}: Server error ({response.status_code}), retrying in {wait_time:.1f}s... ({attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.debug(f"{ticker}: Server error ({response.status_code}), max retries exceeded")
                        return None

                # Handle client errors (4xx except 429) - don't retry, these are permanent
                if 400 <= response.status_code < 500:
                    logger.debug(f"{ticker}: Client error ({response.status_code}), not retrying")
                    return None
                
                response.raise_for_status()
                data = response.json()
                
                # FMP returns dict with 'historical' key OR a list
                if isinstance(data, dict):
                    # Standard FMP format - return as-is
                    return data
                elif isinstance(data, list):
                    if len(data) > 0:
                        # List with data - wrap it
                        return {'historical': data}
                    else:
                        # Empty list means no new data available (cache is up-to-date)
                        logger.debug(f"{ticker}: No new data available from FMP (cache is current)")
                        return {'historical': [], 'already_current': True}
                else:
                    logger.warning(f"Unexpected FMP response format for {ticker}: {type(data)}")
                    return None
                    
            except requests.exceptions.Timeout as e:
                last_error = f"Timeout: {e}"
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 2 + random.uniform(0, 1)
                    logger.debug(f"{ticker}: Timeout, retrying in {wait_time:.1f}s... ({attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                return None

            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 3 + random.uniform(0, 2)
                    logger.debug(f"{ticker}: Connection error, retrying in {wait_time:.1f}s... ({attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                return None

            except requests.exceptions.RequestException as e:
                last_error = str(e)
                if attempt < max_retries - 1 and "429" in str(e):
                    wait_time = (2 ** attempt) * 3 + random.uniform(0, 2)
                    logger.debug(f"{ticker}: Request error (likely 429), retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    continue
                return None

            except json.JSONDecodeError as e:
                last_error = f"JSON decode error: {e}"
                if attempt < max_retries - 1:
                    wait_time = 1 + random.uniform(0, 1)
                    logger.debug(f"{ticker}: JSON decode error, retrying... ({attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                return None

        logger.debug(f"{ticker}: All {max_retries} attempts failed. Last error: {last_error}")
        return None

    def _parse_fmp_response(self, response_data: dict, ticker: str) -> Optional[pd.DataFrame]:
        """
        Convert FMP JSON response to DataFrame.
        
        Args:
            response_data: FMP API response for a single ticker
            ticker: Ticker symbol
            
        Returns:
            DataFrame with OHLCV data, or None if parsing fails
        """
        try:
            if not response_data or 'historical' not in response_data:
                return None
            
            historical = response_data['historical']
            if not historical:
                return None
            
            # No date filtering - allow full historical data for ML training
            # (Filter was previously set to 2010-01-01 but removed for comprehensive training)
            
            # Convert to DataFrame
            df = pd.DataFrame(historical)
            
            # Rename columns to match yfinance format
            column_mapping = {
                'date': 'Date',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            }
            df = df.rename(columns=column_mapping)
            
            # Convert date to datetime and set as index
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.set_index('Date')
            
            # Sort by date (FMP returns newest first, we want oldest first)
            df = df.sort_index()
            
            # Ensure we have the required columns
            required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            for col in required_cols:
                if col not in df.columns:
                    if col == 'Volume':
                        df[col] = 0
                    else:
                        df[col] = df['Close']
            
            return df[required_cols]
            
        except Exception as e:
            logger.debug(f"Failed to parse FMP data for {ticker}: {e}")
            return None

    def _safe_extract_close(self, df) -> Optional[pd.Series]:
        """
        Safely extracts 'Close' column from messy yfinance data.
        Handles MultiIndex and various edge cases.
        """
        if df is None or df.empty:
            return None
        if isinstance(df, pd.Series):
            return df

        # Standard Column
        if 'Close' in df.columns:
            if isinstance(df['Close'], pd.DataFrame):
                return df['Close'].iloc[:, 0]
            return df['Close']

        # MultiIndex Handling
        if isinstance(df.columns, pd.MultiIndex):
            for i in range(df.columns.nlevels):
                if 'Close' in df.columns.get_level_values(i):
                    try:
                        slice_df = df.xs('Close', axis=1, level=i)
                        if len(slice_df.columns) == 1:
                            return slice_df.iloc[:, 0]
                        return slice_df
                    except:
                        continue
        return None

    def get_ticker_data(self, ticker: str, use_cache: bool = True, source: str = 'fmp', 
                        mode: CacheMode = None,
                        date_range: Optional[Tuple[str, str]] = None,
                        # Legacy parameters (for backward compatibility)
                        min_date: str = '2000-01-01',
                        check_min_date: bool = True, max_retries: int = 2, update_cache: bool = False,
                        required_end_date: Optional[pd.Timestamp] = None, force_cache_only: bool = False) -> Optional[pd.DataFrame]:
        """
        Returns OHLCV data for a single ticker.
        First checks Parquet cache, then downloads from FMP if needed.

        NEW API (recommended):
            mode: CacheMode enum - LIVE, HISTORICAL, or CACHE_ONLY
            date_range: Tuple of (start_date, end_date) for HISTORICAL mode
        
        LEGACY API (deprecated, still supported):
            force_cache_only, check_min_date, required_end_date, etc.

        Args:
            ticker: Stock symbol
            use_cache: If True, uses cached data when available
            source: Data source - 'fmp' (default) or 'yfinance' (not recommended)
            mode: Data access mode (LIVE, HISTORICAL, or CACHE_ONLY)
            date_range: Required date range for HISTORICAL mode validation
            min_date: (Legacy) Minimum required start date
            check_min_date: (Legacy) If True, validates full date range
            max_retries: Number of FMP download attempts before failing (default: 2)
            update_cache: If True, allows cache updates via API calls
            required_end_date: (Legacy) Validates cache covers up to this date
            force_cache_only: (Legacy) Maps to CACHE_ONLY mode

        Returns:
            DataFrame with OHLCV data (adjusted), or None if failed
        """
        cache_file = self.price_dir / f"{ticker}.parquet"

        # Backward compatibility: map legacy flags to CacheMode
        if mode is None:
            if force_cache_only:
                mode = CacheMode.CACHE_ONLY
            elif required_end_date is not None or check_min_date:
                mode = CacheMode.HISTORICAL
            else:
                mode = CacheMode.LIVE

        # CACHE_ONLY mode: just read cache, no validation or API calls
        if mode == CacheMode.CACHE_ONLY:
            if cache_file.exists():
                try:
                    df = pd.read_parquet(cache_file)
                    logger.debug(f"Loaded {ticker} from cache (CACHE_ONLY mode)")
                    return df
                except Exception as e:
                    logger.warning(f"Cache read failed for {ticker}: {e}")
                    return None
            else:
                logger.debug(f"{ticker}: No cache available (CACHE_ONLY mode)")
                return None

        # Try cache first (with mode-based validation)
        if use_cache and cache_file.exists() and not self._is_cache_stale(
            cache_file,
            mode=mode,
            date_range=date_range,
            # Pass legacy params for backward compat
            min_date=min_date,
            check_min_date=check_min_date,
            required_end_date=required_end_date,
        ):
            try:
                df = pd.read_parquet(cache_file)
                logger.debug(f"Loaded {ticker} from cache")
                return df
            except Exception as e:
                logger.warning(f"Cache read failed for {ticker}: {e}")

        # Download fresh data from FMP (primary source)
        if source == 'fmp' and update_cache == True:
            if not config.FMP_API_KEY:
                logger.error(f"FMP_API_KEY not set - cannot download {ticker}")
                return None
            
            # Retry logic for FMP
            for attempt in range(1, max_retries + 1):
                try:
                    logger.debug(f"Downloading {ticker} from FMP (attempt {attempt}/{max_retries})...")
                    data = self._get_ticker_data_fmp(ticker)
                    if data is not None and not data.empty:
                        # Save to cache
                        data.to_parquet(cache_file)
                        logger.debug(f"Successfully cached {ticker} to {cache_file}")
                        return data
                    else:
                        logger.warning(f"FMP returned no data for {ticker} (attempt {attempt}/{max_retries})")
                        if attempt < max_retries:
                            time.sleep(1)  # Brief pause before retry
                except Exception as e:
                    logger.warning(f"FMP failed for {ticker} (attempt {attempt}/{max_retries}): {e}")
                    if attempt < max_retries:
                        time.sleep(1)  # Brief pause before retry
            
            # All FMP attempts failed
            logger.error(f"Failed to download {ticker} from FMP after {max_retries} attempts")
            return None
        
        # Legacy yfinance fallback (not recommended - use FMP for quality)
        # logger.warning(f"Using yfinance for {ticker} - data quality may be inconsistent")
        # return self._get_ticker_data_yfinance(ticker, cache_file)

    def _get_ticker_data_fmp(self, ticker: str) -> Optional[pd.DataFrame]:
        """
        Fetch ticker data from FMP API.
        
        Args:
            ticker: Stock symbol
            
        Returns:
            DataFrame with OHLCV data, or None if failed
        """
        try:
            # Fetch from FMP (single ticker, non-batch)
            fmp_data = self._fetch_fmp_historical(ticker)
            
            if not fmp_data:
                return None
            
            # Parse response
            df = self._parse_fmp_response(fmp_data, ticker)
            return df
            
        except Exception as e:
            logger.error(f"FMP fetch failed for {ticker}: {e}")
            return None
    
    def _get_ticker_data_yfinance(self, ticker: str, cache_file: Path) -> Optional[pd.DataFrame]:
        """
        Fetch ticker data from yfinance (fallback method).
        
        Args:
            ticker: Stock symbol
            cache_file: Path to cache file for saving
            
        Returns:
            DataFrame with OHLCV data, or None if failed
        """
        try:
            logger.debug(f"Downloading {ticker} from yfinance...")
            data = yf.download(
                ticker,
                period='max',  # Get full historical data (yfinance ignores start= param by default)
                auto_adjust=True,
                progress=False
            )

            if data.empty:
                return None

            # Handle MultiIndex if present
            if isinstance(data.columns, pd.MultiIndex):
                # yfinance returns MultiIndex like ('Close', 'SPY')
                # We want to keep just the price column names (Close, High, etc.)
                # Check which level has the price names
                if 'Close' in data.columns.get_level_values(0):
                    data.columns = data.columns.droplevel(1)  # Remove ticker level
                else:
                    data.columns = data.columns.droplevel(0)  # Remove price level

            # Ensure we have at minimum Close and Volume
            # Some tickers may not have all OHLCV after auto_adjust
            if 'Close' not in data.columns:
                logger.warning(f"{ticker}: Missing Close column")
                return None

            # Fill in missing OHLC with Close if needed (happens with auto_adjust)
            if 'Open' not in data.columns:
                data['Open'] = data['Close']
            if 'High' not in data.columns:
                data['High'] = data['Close']
            if 'Low' not in data.columns:
                data['Low'] = data['Close']
            if 'Volume' not in data.columns:
                data['Volume'] = 0

            # Save to cache
            data.to_parquet(cache_file)
            logger.debug(f"Cached {ticker} to {cache_file}")

            return data

        except Exception as e:
            logger.error(f"Failed to download {ticker}: {e}")
            return None

    def update_cache(
        self,
        tickers: List[str] = None,
        force: bool = False,
        source: str = 'yfinance',
        max_workers: int = 10,
        from_date: str = None,
        flush_threshold: int = 5000,
        latest_trading_day: str = None,
    ) -> Dict[str, bool]:
        """
        Incremental price update: fetches only stale tickers, bulk-writes to DuckDB.

        Args:
            tickers: Pre-computed stale list (skips internal staleness query)
            force: Re-fetch full history for all active tickers (requires confirmation)
            source: 'yfinance' (default) or 'fmp'
            max_workers: Parallel workers for FMP path
            from_date: Override start date (FMP path only)
            flush_threshold: Max buffer rows before intermediate flush (force=True path)
            latest_trading_day: Pre-computed trading day (skips get_latest_trading_day call)
        """
        if latest_trading_day is None:
            latest_trading_day = get_latest_trading_day()
            if isinstance(latest_trading_day, pd.Timestamp):
                latest_trading_day = latest_trading_day.strftime('%Y-%m-%d')

        if force:
            candidate_tickers = tickers or self._get_all_active_tickers()
            n = len(candidate_tickers)
            print(f"⚠️  Force mode: will re-fetch full price history for {n} active tickers.")
            print(f"    This consumes significant API quota and may take 30-60 minutes.")
            confirm = input("    Type 'yes' to continue: ").strip().lower()
            if confirm != 'yes':
                logger.info("Force update cancelled by user.")
                return {}
            to_update = candidate_tickers
        elif tickers is not None:
            to_update = tickers  # caller already computed the stale list
        else:
            to_update = self._get_stale_tickers(latest_trading_day)

        if not to_update:
            logger.debug(f"All active tickers fresh as of {latest_trading_day}")
            return {}

        logger.debug(f"{len(to_update)} tickers to update (latest: {latest_trading_day})")

        buffer: List[Tuple[str, pd.DataFrame]] = []
        results: Dict[str, bool] = {}
        rows_written = 0
        self.last_errors = []

        if source == 'fmp' and config.FMP_API_KEY:
            fmp_results, buffer, fmp_errors = self._update_cache_fmp(to_update, max_workers=max_workers, from_date=from_date)
            results.update(fmp_results)
            self.last_errors = fmp_errors
        else:
            # yfinance path: returns (results_dict, buffer, errors_dict)
            yf_results, buffer, yf_errors = self._update_cache_yfinance(to_update, latest_trading_day)
            results.update(yf_results)
            # Surface per-ticker cause so PipelineRunManager.classify_error can
            # bucket into RATE_LIMIT / TIMEOUT / NO_DATA / FETCH_FAILURE.
            self.last_errors = [
                (t, yf_errors.get(t, 'yfinance fetch failed (no cause recorded)'))
                for t, ok in yf_results.items() if not ok
            ]

            # Intermediate flush if buffer is large (force=True full-history scenario)
            if len(buffer) > 0:
                total_rows = sum(len(d) for _, d in buffer)
                if total_rows >= flush_threshold:
                    rows_written += self._flush_buffer(buffer, latest_trading_day)
                    buffer.clear()

        # Final flush
        if buffer:
            rows_written += self._flush_buffer(buffer, latest_trading_day)

        # Log post-retry failures
        failed = [t for t, ok in results.items() if not ok]
        if failed:
            self._log_quality_issues(
                [('FETCH_FAILURE', failed, f"no data after retries on {latest_trading_day}")],
                latest_trading_day,
            )

        failure_rate = len(failed) / len(to_update) if to_update else 0
        if failure_rate > 0.10:
            self._log_quality_issues(
                [('HIGH_FAILURE_RATE', [], f"{len(failed)}/{len(to_update)} failed — >10% threshold")],
                latest_trading_day,
            )

        logger.debug(f"Price flush: {rows_written} rows written to price_data")
        return results    
    
    def _fetch_price_worker(self, ticker: str, max_retries: int = 3, from_date: str = None) -> tuple:
        """
        Worker function for parallel price fetching with retry logic.

        Args:
            ticker: Stock symbol to fetch
            max_retries: Maximum number of retry attempts
            from_date: Override start date (bypasses incremental logic if specified)

        Returns:
            Tuple of (ticker, success_status, error_message)
        """
        # Determine if we should force from_date (bypass cache check)
        force_from_date = from_date is not None
        
        for attempt in range(max_retries):
            try:
                fmp_data = self._fetch_fmp_historical(ticker, from_date=from_date, force_from_date=force_from_date)

                if fmp_data:
                    if fmp_data.get('already_current', False):
                        logger.debug(f"{ticker}: Already current, no update needed")
                        return (ticker, None, None)  # None df = already fresh, not a failure

                    df = self._parse_fmp_response(fmp_data, ticker)
                    if df is not None and not df.empty:
                        validated = self._validate_and_trim_data(df, ticker)
                        if validated is None:
                            return (ticker, None, "Validation failed")
                        return (ticker, validated, None)
                    else:
                        return (ticker, None, "No data parsed")
                else:
                    return (ticker, None, "No FMP response")

            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(f"{ticker}: Retry {attempt + 1}/{max_retries} after error: {e}")
                    time.sleep(1 * (attempt + 1))
                    continue
                else:
                    return (ticker, None, str(e))

        return (ticker, None, "Max retries exceeded")

    def _update_cache_fmp(self, tickers: List[str], max_workers: int = 5, show_progress: bool = True, from_date: str = None) -> Dict[str, bool]:
        """
        Update cache using FMP API with parallel execution and automatic retry of failures.
        NOTE: FMP Starter tier does NOT support batch requests for historical data.
        Rate limited to 300 calls/minute.

        Features:
        - Parallel fetching with configurable workers
        - Exponential backoff with jitter for transient errors
        - Automatic retry pass for failed tickers (reduced parallelism)
        - Detailed progress tracking

        Args:
            tickers: List of ticker symbols
            max_workers: Number of parallel workers (default: 10)
            show_progress: Show detailed progress updates (default: True)
            from_date: Override start date for fetching (bypasses incremental logic)

        Returns:
            Tuple of (results dict, buffer of (ticker, df) pairs for bulk write)
        """
        results: Dict[str, bool] = {}
        buffer: List[Tuple[str, pd.DataFrame]] = []
        failed_tickers = []
        total_tickers = len(tickers)
        success_count = 0
        fail_count = 0

        logger.debug(f"FMP fetch: {total_tickers} tickers, {max_workers} workers, rate={self.rate_limit}/min")
        start_time = time.time()

        use_tqdm = False
        if show_progress:
            try:
                from tqdm import tqdm
                use_tqdm = True
            except ImportError:
                pass

        def _collect(ticker: str, df: Optional[pd.DataFrame], error_msg: Optional[str]) -> None:
            if df is not None:
                buffer.append((ticker, df))
                results[ticker] = True
            elif error_msg is None:
                results[ticker] = True  # already_current
            else:
                results[ticker] = False
                failed_tickers.append((ticker, error_msg))

        # First pass
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ticker = {executor.submit(self._fetch_price_worker, ticker, 5, from_date): ticker for ticker in tickers}

            if use_tqdm:
                with tqdm(total=total_tickers, desc="Fetching prices", unit="ticker") as pbar:
                    for future in concurrent.futures.as_completed(future_to_ticker):
                        ticker, df, error_msg = future.result()
                        _collect(ticker, df, error_msg)
                        success_count = sum(v for v in results.values() if v)
                        fail_count = sum(1 for v in results.values() if not v)
                        pbar.update(1)
                        pbar.set_postfix({'OK': success_count, 'FAIL': fail_count})
            else:
                completed = 0
                for future in concurrent.futures.as_completed(future_to_ticker):
                    ticker, df, error_msg = future.result()
                    _collect(ticker, df, error_msg)
                    success_count = sum(v for v in results.values() if v)
                    fail_count = sum(1 for v in results.values() if not v)
                    completed += 1
                    if completed % 100 == 0 or completed == total_tickers:
                        elapsed = time.time() - start_time
                        rate = completed / elapsed if elapsed > 0 else 0
                        logger.debug(
                            f"FMP progress: {completed}/{total_tickers} | "
                            f"OK {success_count} FAIL {fail_count} | {rate:.1f}/sec"
                        )

        # Retry pass
        if failed_tickers and len(failed_tickers) <= 100:
            logger.debug(f"FMP retry: {len(failed_tickers)} tickers (10s cooldown)")
            time.sleep(10)
            retry_tickers = [t for t, _ in failed_tickers]
            failed_tickers.clear()
            retry_workers = min(3, max_workers)

            with concurrent.futures.ThreadPoolExecutor(max_workers=retry_workers) as executor:
                future_to_ticker = {executor.submit(self._fetch_price_worker, ticker, 5, from_date): ticker for ticker in retry_tickers}
                for future in concurrent.futures.as_completed(future_to_ticker):
                    ticker, df, error_msg = future.result()
                    _collect(ticker, df, error_msg)
                    if results.get(ticker):
                        logger.debug(f"FMP recovered: {ticker}")

        # Summary
        elapsed_total = time.time() - start_time
        success_count = sum(1 for v in results.values() if v)
        fail_count = sum(1 for v in results.values() if not v)
        logger.debug(f"FMP done: {success_count}/{total_tickers} OK, {fail_count} failed | {elapsed_total:.1f}s")

        return results, buffer, failed_tickers

    def _update_cache_yfinance(self, tickers: List[str], latest_trading_day: str = None) -> Tuple[Dict[str, bool], List[Tuple[str, pd.DataFrame]], Dict[str, str]]:
        """
        Update cache using a single yfinance bulk download (no batching).

        Derives from_date from the most-recent existing data across the stale set
        (MAX of per-ticker MAX dates). This avoids the MIN pitfall where one corrupt
        ticker drags the whole batch back to 1970.

        IPO validation is skipped — these are incremental updates, not full history.
        Returns (results dict, buffer of (ticker, df) for bulk DuckDB write,
        errors dict mapping failed ticker -> cause string).
        """
        results: Dict[str, bool] = {}
        buffer: List[Tuple[str, pd.DataFrame]] = []
        errors: Dict[str, str] = {}

        # Use MIN(MAX(date)) — the oldest gap across stale tickers, but exclude
        # corrupt pre-2000 rows (e.g. 1970-01-01 from bad yfinance data).
        # yfinance returns all available data from `start` onward per ticker,
        # so tickers that are already ahead simply get no new rows (INSERT OR IGNORE).
        conn = db.connect(self.db_path)
        try:
            result = conn.execute("""
                SELECT MIN(max_date) FROM (
                    SELECT ticker, MAX(date) AS max_date
                    FROM price_data
                    WHERE ticker IN (SELECT unnest(?))
                      AND date >= '2000-01-01'
                    GROUP BY ticker
                )
            """, [tickers]).fetchone()
            last_date = result[0] if result and result[0] else None
        finally:
            conn.close()

        if last_date:
            from_date = (pd.Timestamp(last_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            from_date = DEFAULT_HISTORICAL_START_DATE

        # Compute explicit end date (yfinance end is exclusive)
        # Without this, yfinance uses datetime.now() which on non-US timezones
        # can produce end < start and trigger "Invalid input" errors.
        if latest_trading_day:
            end_date = (pd.Timestamp(latest_trading_day) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            end_date = (pd.Timestamp.now() + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

        # Per-ticker isolation: a single bulk yf.download() for all stale tickers
        # marks EVERY ticker False on one 429/timeout. Batch the call so one bad
        # batch can't sink the rest, then retry the failed subset once.
        BATCH_SIZE = 200
        RETRY_BATCH_SIZE = 50
        RETRY_SLEEP_S = 15

        def _download_and_extract(batch: List[str]) -> List[str]:
            """Download + extract one batch. Returns tickers that yielded no data.
            On success appends to buffer, sets results[ticker]=True, clears any
            prior error; on failure sets results[ticker]=False and records the
            cause in errors[ticker]. Identical for first + retry pass."""
            try:
                data = yf.download(
                    batch,
                    start=from_date,
                    end=end_date,
                    group_by='ticker',
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                )
            except Exception as e:
                cause = f"yfinance batch download exception: {type(e).__name__}: {e}"
                logger.warning(f"[Phase 1] yfinance batch ({len(batch)} tickers) failed: {e}")
                for ticker in batch:
                    results[ticker] = False
                    errors[ticker] = cause
                return list(batch)

            failed: List[str] = []
            for ticker in batch:
                try:
                    ticker_data = self._extract_ticker_from_batch(data, ticker)
                    if ticker_data is not None and not ticker_data.empty:
                        buffer.append((ticker, ticker_data))
                        results[ticker] = True
                        errors.pop(ticker, None)
                    else:
                        results[ticker] = False
                        errors[ticker] = (
                            'yfinance returned no data for ticker (not in response or empty frame)'
                        )
                        failed.append(ticker)
                except Exception as e:
                    logger.debug(f"Failed to extract {ticker}: {e}")
                    results[ticker] = False
                    errors[ticker] = f"yfinance extract exception: {type(e).__name__}: {e}"
                    failed.append(ticker)
            return failed

        logger.debug(
            f"yfinance batched download: {len(tickers)} tickers, "
            f"{from_date} to {end_date}, batch={BATCH_SIZE}"
        )

        all_failed: List[str] = []
        for i in range(0, len(tickers), BATCH_SIZE):
            batch = tickers[i : i + BATCH_SIZE]
            all_failed.extend(_download_and_extract(batch))

        # Retry pass — once, smaller batches, after a cooldown.
        if all_failed:
            logger.info(
                f"yfinance retry: {len(all_failed)} tickers "
                f"({RETRY_SLEEP_S}s cooldown, batch={RETRY_BATCH_SIZE})"
            )
            time.sleep(RETRY_SLEEP_S)
            for i in range(0, len(all_failed), RETRY_BATCH_SIZE):
                batch = all_failed[i : i + RETRY_BATCH_SIZE]
                # Recovered tickers flip results[ticker]=True inside the closure,
                # so update_cache() will no longer count them in last_errors.
                _download_and_extract(batch)

        ok = sum(1 for v in results.values() if v)
        no_data = len(tickers) - ok
        logger.debug(f"yfinance done: {ok}/{len(tickers)} OK, {no_data} no data")

        return results, buffer, errors

    def _flush_buffer(self, buffer: List[Tuple[str, pd.DataFrame]], run_date: str) -> int:
        """
        Concatenate buffer, run quality checks, bulk-insert into price_data.
        Returns number of rows written.
        """
        if not buffer:
            return 0

        df = pd.concat(
            [d.assign(ticker=t) for t, d in buffer],
        )
        # yfinance stores dates in the DatetimeIndex — move to column
        if 'date' not in [c.lower() for c in df.columns]:
            df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]
        # reset_index() may produce 'index', 'datetime', or 'date' depending on index name
        for col in ('index', 'datetime'):
            if col in df.columns and 'date' not in df.columns:
                df = df.rename(columns={col: 'date'})
        df['date'] = pd.to_datetime(df['date']).dt.date

        # Write-time plausibility clamp: close above the ceiling is vendor scaling dirt
        # (yfinance serves $T/share bars for some low-float tickers). Null OHLC but keep
        # the row so the date spine survives — same remedy as clean_dirty_shares_price.py.
        close_max = config.T1_PLAUSIBILITY_BOUNDS['close_max']
        implausible = df['close'] > close_max
        if implausible.any():
            tickers = df.loc[implausible, 'ticker'].unique().tolist()
            logger.warning(
                f"[Phase 1] Nulled OHLC on {int(implausible.sum())} bars with close > "
                f"${close_max:,.0f} (implausible; vendor scaling dirt): {tickers[:10]}"
            )
            df.loc[implausible, ['open', 'high', 'low', 'close']] = None

        issues = self._quality_check(df, run_date)
        if issues:
            self._log_quality_issues(issues, run_date)

        conn = db.connect(self.db_path)
        try:
            conn.execute("""
                INSERT OR IGNORE INTO price_data (ticker, date, open, high, low, close, volume)
                SELECT ticker, date, open, high, low, close, CAST(volume AS UBIGINT)
                FROM df
            """)
            conn.commit()
            return len(df)
        except Exception as e:
            logger.error(f"[Phase 1] Bulk DuckDB write failed: {e}", exc_info=True)
            return 0
        finally:
            conn.close()

    def _quality_check(
        self, df: pd.DataFrame, run_date: str
    ) -> List[Tuple[str, List[str], str]]:
        """Cross-ticker checks on the full buffer before write. Post-retry only."""
        issues = []

        bad_close = df[df['close'] <= 0]
        if not bad_close.empty:
            tickers = bad_close['ticker'].unique().tolist()
            issues.append(('NEGATIVE_CLOSE', tickers, f"close <= 0 on {run_date}"))

        run_date_val = pd.Timestamp(run_date).date()
        zero_vol = df[(df['volume'] == 0) & (df['date'] == run_date_val)]
        if not zero_vol.empty:
            tickers = zero_vol['ticker'].unique().tolist()
            issues.append(('ZERO_VOLUME', tickers, f"volume=0 on {run_date}"))

        return issues

    def _log_quality_issues(
        self, issues: List[Tuple[str, List[str], str]], run_date: str
    ) -> None:
        """Append quality issues to logs/data_quality/YYYY-MM.log (monthly rotation)."""
        log_dir = Path("logs/data_quality")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{run_date[:7]}.log"

        with open(log_file, 'a') as f:
            for issue_type, tickers, detail in issues:
                tickers_str = ', '.join(tickers[:20])
                if len(tickers) > 20:
                    tickers_str += f' ... +{len(tickers) - 20} more'
                f.write(f"{run_date} | {issue_type:<18} | {tickers_str:<50} | {detail}\n")

    def _extract_ticker_from_batch(self, data: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
        """Extract single ticker data from batch download result."""
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if ticker in data.columns.levels[0]:
                    df = data[ticker].copy()
                else:
                    return None
            else:
                # Single ticker batch
                df = data.copy()

            # Flatten MultiIndex columns if needed
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(0)

            # Handle nested Close column
            if 'Close' in df.columns and isinstance(df['Close'], pd.DataFrame):
                df['Close'] = df['Close'].iloc[:, 0]

            # Ensure minimum required columns exist
            if 'Close' not in df.columns:
                return None

            # Fill missing OHLC with Close if needed
            if 'Open' not in df.columns:
                df['Open'] = df['Close']
            if 'High' not in df.columns:
                df['High'] = df['Close']
            if 'Low' not in df.columns:
                df['Low'] = df['Close']
            if 'Volume' not in df.columns:
                df['Volume'] = 0

            return df.dropna(subset=['Close'])

        except Exception as e:
            logger.debug(f"Could not extract {ticker}: {e}")
            return None

    def get_benchmark_data(self, 
                            mode: CacheMode = None,
                            date_range: Optional[Tuple[str, str]] = None,
                            # Legacy parameters (for backward compatibility)
                            min_date: str = '2000-01-01', check_min_date: bool = True, 
                            required_end_date: Optional[pd.Timestamp] = None, 
                            force_cache_only: bool = False) -> Optional[pd.Series]:
        """
        Returns the benchmark (SPY) close prices.
        
        NEW API (recommended):
            mode: CacheMode enum - LIVE, HISTORICAL, or CACHE_ONLY
            date_range: Tuple of (start_date, end_date) for HISTORICAL mode
        
        LEGACY API (deprecated, still supported):
            min_date, check_min_date, required_end_date, force_cache_only
        """
        df = self.get_ticker_data(
            self.benchmark_ticker,
            mode=mode,
            date_range=date_range,
            # Legacy params for backward compat
            min_date=min_date,
            check_min_date=check_min_date,
            required_end_date=required_end_date,
            force_cache_only=force_cache_only
        )
        if df is None:
            return None
        return self._safe_extract_close(df)
    
    def get_batch_data(self, tickers: List[str], max_workers: int = 8, show_progress: bool = False,
                        mode: CacheMode = None,
                        date_range: Optional[Tuple[str, str]] = None,
                        # Legacy parameters (for backward compatibility)
                        min_date: str = '2000-01-01', check_min_date: bool = False,
                        required_end_date: Optional[pd.Timestamp] = None, force_cache_only: bool = False) -> Dict[str, pd.DataFrame]:
        """
        Loads multiple tickers from cache efficiently using parallel execution.

        NEW API (recommended):
            mode: CacheMode enum - LIVE, HISTORICAL, or CACHE_ONLY
            date_range: Tuple of (start_date, end_date) for HISTORICAL mode
        
        LEGACY API (deprecated, still supported):
            min_date, check_min_date, required_end_date, force_cache_only

        Args:
            tickers: List of ticker symbols
            max_workers: Number of parallel threads (default: 8)
            show_progress: If True, display progress bar (default: False)
            mode: Data access mode (LIVE, HISTORICAL, or CACHE_ONLY)
            date_range: Required date range for HISTORICAL mode validation
            min_date: (Legacy) Minimum required start date
            check_min_date: (Legacy) If True, validates full historical range
            required_end_date: (Legacy) Validates cache covers up to this date
            force_cache_only: (Legacy) Maps to CACHE_ONLY mode

        Returns:
            Dict mapping ticker -> DataFrame (only includes tickers with data)
        """
        data = {}

        # Helper function for parallel execution
        def load_single(ticker):
            return ticker, self.get_ticker_data(
                ticker,
                use_cache=True,
                mode=mode,
                date_range=date_range,
                # Legacy params for backward compat
                min_date=min_date,
                check_min_date=check_min_date,
                required_end_date=required_end_date,
                force_cache_only=force_cache_only
            )

        # Use ThreadPoolExecutor for IO-bound file reading
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_ticker = {executor.submit(load_single, ticker): ticker for ticker in tickers}

            # Process results as they complete
            if show_progress:
                try:
                    from tqdm import tqdm
                    futures_iter = tqdm(
                        concurrent.futures.as_completed(future_to_ticker),
                        total=len(future_to_ticker),
                        desc="Loading price data",
                        unit="ticker"
                    )
                except ImportError:
                    futures_iter = concurrent.futures.as_completed(future_to_ticker)
            else:
                futures_iter = concurrent.futures.as_completed(future_to_ticker)

            for future in futures_iter:
                ticker = future_to_ticker[future]
                try:
                    t, df = future.result()
                    if df is not None:
                        data[t] = df
                except Exception as e:
                    logger.warning(f"Failed to load {ticker}: {e}")

        return data

    def get_cached_tickers(self) -> List[str]:
        """
        Get list of all tickers available in the price cache.

        Returns:
            List of ticker symbols that have cached price data
        """
        if not self.price_dir.exists():
            return []

        # Get all .parquet files in price cache directory
        parquet_files = list(self.price_dir.glob('*.parquet'))

        # Extract ticker symbols from filenames (remove .parquet extension)
        tickers = [f.stem for f in parquet_files]
        
        # Filter out non-ticker files (like universe_*)
        tickers = [t for t in tickers if not t.startswith('universe_')]

        # Sort alphabetically
        tickers.sort()

        logger.debug(f"Found {len(tickers)} tickers in price cache")
        return tickers
