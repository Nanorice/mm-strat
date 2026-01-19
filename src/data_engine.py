"""
Data Engine - DataRepository Class
Handles universe management, data downloading, and Parquet caching.
"""

import pandas as pd
import numpy as np
import yfinance as yf
import requests
import json
import time
import concurrent.futures
import threading
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Tuple
from enum import Enum
import logging
from tqdm import tqdm
import pyarrow.parquet as pq
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

    def __init__(self, enable_validation: bool = True):
        self.price_dir = config.PRICE_DATA_DIR
        self.benchmark_ticker = config.BENCHMARK_TICKER
        self.cache_days = config.DATA_CACHE_DAYS

        # API call tracking for rate limiting (300 calls/minute like fundamentals)
        self._call_timestamps = []
        self._rate_limit_lock = threading.Lock()  # Thread-safe lock
        self.rate_limit = 300  # FMP Starter tier rate limit

        # Per-file locks for parallel safety (allows concurrent writes to different files)
        self._file_locks = {}  # Dict mapping file path -> lock
        self._file_locks_lock = threading.Lock()  # Lock for modifying the locks dict itself

        # IPO validation settings
        self.enable_validation = enable_validation
        self._ipo_cache = {}  # Cache for IPO dates to avoid repeated API calls

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
                    # Filter out benchmark if present
                    tickers_from_files = [t for t in tickers_from_files if t != self.benchmark_ticker]
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
    
    def _rate_limit_check(self):
        """
        Enforce rate limiting for FMP API (300 calls/minute for Starter tier).
        Uses sliding window approach - pauses only when necessary.
        Thread-safe for parallel execution.
        
        CRITICAL: Lock is ONLY held when checking/updating timestamps, NOT during sleep.
        This allows multiple workers to proceed in parallel while respecting the rate limit.
        """
        # Phase 1: Check if we need to wait (acquire lock briefly)
        with self._rate_limit_lock:
            now = time.time()
            
            # Remove timestamps older than 60 seconds (sliding window)
            self._call_timestamps = [ts for ts in self._call_timestamps if now - ts < 60]
            
            # Check if we're at capacity
            if len(self._call_timestamps) >= self.rate_limit:
                # Calculate sleep time
                oldest_call = self._call_timestamps[0]
                time_since_oldest = now - oldest_call
                sleep_time = 60.0 - time_since_oldest + 0.1  # Add 0.1s buffer
            else:
                sleep_time = 0
        
        # Phase 2: Sleep OUTSIDE the lock (if needed) so other workers can proceed
        if sleep_time > 0:
            logger.debug(f"Rate limit reached, sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)
        
        # Phase 3: Record this call (acquire lock briefly again)
        with self._rate_limit_lock:
            now = time.time()
            # Re-clean after potential sleep
            self._call_timestamps = [ts for ts in self._call_timestamps if now - ts < 60]
            # Record this call
            self._call_timestamps.append(now)

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

    def _safe_write_parquet(self, df: pd.DataFrame, file_path: Path, ticker: str,
                           merge_with_existing: bool = False) -> bool:
        """
        Thread-safe parquet file write with validation.
        Uses per-file locks to allow parallel writes to different files.

        Args:
            df: DataFrame to write
            file_path: Destination file path
            ticker: Stock symbol (for logging)
            merge_with_existing: If True, merge with existing cache file (for incremental updates)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get or create a lock for this specific file
            file_key = str(file_path)
            with self._file_locks_lock:
                if file_key not in self._file_locks:
                    self._file_locks[file_key] = threading.Lock()
                file_lock = self._file_locks[file_key]
            
            # Use per-file lock (only blocks writes to the SAME file, not all files)
            with file_lock:
                # If merging, load existing cache inside the lock (thread-safe)
                if merge_with_existing and file_path.exists():
                    try:
                        old_df = pd.read_parquet(file_path)
                        df = pd.concat([old_df, df])
                        # Drop duplicates by index (date), keeping last (newer data)
                        df = df[~df.index.duplicated(keep='last')]
                        # Ensure chronological order
                        df = df.sort_index()
                        logger.debug(f"{ticker}: Merged new data with existing cache")
                    except Exception as e:
                        logger.warning(f"{ticker}: Could not merge with existing cache: {e}. Using new data only.")
                        # Continue with new data only if merge fails

                # Validate data before writing
                validated_df = self._validate_and_trim_data(df, ticker)

                if validated_df is None:
                    logger.error(f"{ticker}: Validation failed, not saving")
                    return False

                # Write to parquet
                validated_df.to_parquet(file_path)
                logger.debug(f"{ticker}: Successfully saved to {file_path.name}")
                return True

        except Exception as e:
            logger.error(f"{ticker}: Failed to write parquet: {e}")
            return False

    def _fetch_fmp_historical(self, ticker: str, from_date: str = None, max_retries: int = 3, force_from_date: bool = False) -> Optional[dict]:
        """
        Fetch historical OHLCV data from FMP API for a single ticker with retry logic.
        Implements INCREMENTAL fetching - only downloads data since last cached date.
        NOTE: FMP Starter tier does NOT support batch requests for historical data.

        Args:
            ticker: Single ticker symbol
            from_date: Start date for historical data (default: DEFAULT_HISTORICAL_START_DATE)
            max_retries: Maximum number of retries for 429 errors (default: 3)
            force_from_date: If True, use from_date directly without checking cache (for full historical fetch)

        Returns:
            JSON response dict with historical data, or None if failed
        """
        if not config.FMP_API_KEY:
            raise ValueError("FMP_API_KEY not set in environment")

        # Use default if not specified
        if from_date is None:
            from_date = DEFAULT_HISTORICAL_START_DATE

        # Determine cache file path for this ticker
        cache_file = self.price_dir / f"{ticker}.parquet"

        # Calculate optimal start date for incremental fetch
        # (Skip this logic if force_from_date is True - user wants full historical data)
        if not force_from_date and cache_file.exists():
            try:
                df = pd.read_parquet(cache_file, columns=[])
                last_date = df.index.max()
                from_date = (last_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            except:
                from_date = DEFAULT_HISTORICAL_START_DATE  # Full download if cache corrupted
        elif not force_from_date:
            from_date = DEFAULT_HISTORICAL_START_DATE  # Full download for new ticker
        
        url = f"{config.FMP_BASE_URL}/historical-price-eod/full"
        params = {
            'symbol': ticker,
            'from': from_date,
            'apikey': config.FMP_API_KEY
        }
        
        for attempt in range(max_retries):
            # Rate limiting
            self._rate_limit_check()
            
            try:
                response = requests.get(url, params=params, timeout=30)
                
                # Handle 429 rate limit errors with progressive backoff
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        # Sleep intervals: 5s, 10s, 15s
                        wait_time = 5 * (attempt + 1)
                        logger.warning(f"{ticker}: Rate limit hit (429), retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"{ticker}: Rate limit hit (429), max retries exceeded")
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
                    
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1 and "429" in str(e):
                    wait_time = 5 * (attempt + 1)
                    logger.warning(f"{ticker}: Request error (likely 429), retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                logger.error(f"FMP API request failed for {ticker}: {e}")
                return None
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse FMP response for {ticker}: {e}")
                return None
        
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

    def update_cache(self, tickers: List[str], force: bool = False, source: str = 'fmp', max_workers: int = 10, from_date: str = None) -> Dict[str, bool]:
        """
        Parallelized Cache Update with market date hoisting and incremental fetching.
        
        Args:
            tickers: List of ticker symbols to update
            force: If True, re-download all tickers regardless of cache status
            source: Data source - 'fmp' (Financial Modeling Prep) or 'yfinance'
            max_workers: Number of parallel workers for downloading (default: 10)
            from_date: Override start date for fetching (YYYY-MM-DD). If specified,
                      bypasses incremental logic and fetches full history from this date.
        
        Returns:
            Dict mapping ticker -> success status
        """
        # Market hours check - skip update during trading hours unless forced
        from datetime import datetime, time as dt_time
        import pytz

        results = {}
        to_download = []

        if force:
            logger.info("Force mode enabled - downloading all")
            to_download = tickers
        else:
            # 1. CALCULATE DATE ONCE (The Fix)
            logger.info("Fetching latest trading day...")
            market_date = get_latest_trading_day()
            logger.info(f"Latest trading day is: {market_date}")
            
            logger.info(f"Checking {len(tickers)} files (Parallel Metadata Scan)...")
            
            try:
                from tqdm import tqdm
                pbar = tqdm(total=len(tickers), desc="Scanning cache", unit="file")
            except ImportError:
                pbar = None

            # 2. Worker uses the pre-calculated date
            def check_worker(ticker):
                path = self.price_dir / f"{ticker}.parquet"
                # Use simplified staleness check
                is_stale = self._is_cache_stale(path, current_market_date=market_date)
                return ticker, is_stale

            # 3. Parallel Execution
            with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
                future_to_ticker = {executor.submit(check_worker, t): t for t in tickers}
                
                for future in concurrent.futures.as_completed(future_to_ticker):
                    ticker, is_stale = future.result()
                    if is_stale:
                        to_download.append(ticker)
                    else:
                        results[ticker] = True
                    
                    if pbar: pbar.update(1)
            
            if pbar: pbar.close()

        if not to_download:
            logger.info("✅ All tickers up to date.")
            return results

        logger.info(f"⬇️ Downloading {len(to_download)} missing/stale tickers...")
        
        # Pass max_workers and from_date through to FMP fetcher
        if source == 'fmp' and config.FMP_API_KEY:
            fmp_results = self._update_cache_fmp(to_download, max_workers=max_workers, from_date=from_date)
            results.update(fmp_results)
            return results

        yf_results = self._update_cache_yfinance(to_download)
        results.update(yf_results)
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
                # Fetch single ticker from FMP (with rate limiting)
                fmp_data = self._fetch_fmp_historical(ticker, from_date=from_date, force_from_date=force_from_date)

                if fmp_data:
                    # Check if cache is already current (no new data available)
                    if fmp_data.get('already_current', False):
                        logger.debug(f"{ticker}: Cache is already current, no update needed")
                        return (ticker, True, None)
                    
                    # Parse and save new data
                    df = self._parse_fmp_response(fmp_data, ticker)
                    if df is not None and not df.empty:
                        cache_file = self.price_dir / f"{ticker}.parquet"

                        # Use thread-safe write with validation (handles cache merging internally)
                        success = self._safe_write_parquet(df, cache_file, ticker, merge_with_existing=True)
                        return (ticker, success, None if success else "Validation failed")
                    else:
                        return (ticker, False, "No data parsed")
                else:
                    return (ticker, False, "No FMP response")

            except Exception as e:
                if attempt < max_retries - 1:
                    logger.debug(f"{ticker}: Retry {attempt + 1}/{max_retries} after error: {e}")
                    time.sleep(1 * (attempt + 1))  # Progressive backoff: 1s, 2s, 3s
                    continue
                else:
                    return (ticker, False, str(e))

        return (ticker, False, "Max retries exceeded")

    def _update_cache_fmp(self, tickers: List[str], max_workers: int = 10, show_progress: bool = True, from_date: str = None) -> Dict[str, bool]:
        """
        Update cache using FMP API with parallel execution and retry logic.
        NOTE: FMP Starter tier does NOT support batch requests for historical data.
        Rate limited to 300 calls/minute.

        Args:
            tickers: List of ticker symbols
            max_workers: Number of parallel workers (default: 10)
            show_progress: Show detailed progress updates (default: True)
            from_date: Override start date for fetching (bypasses incremental logic)

        Returns:
            Dict mapping ticker -> success status
        """
        results = {}
        failed_tickers = []
        total_tickers = len(tickers)
        success_count = 0
        fail_count = 0

        logger.info(f"Fetching {total_tickers} tickers from FMP with {max_workers} parallel workers...")
        logger.info(f"Rate limit: {self.rate_limit} calls/minute")
        start_time = time.time()

        # Check if tqdm is available
        use_tqdm = False
        if show_progress:
            try:
                from tqdm import tqdm
                use_tqdm = True
            except ImportError:
                logger.info("Install tqdm for progress bar: pip install tqdm")

        # Use ThreadPoolExecutor for parallel fetching
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks with from_date
            future_to_ticker = {executor.submit(self._fetch_price_worker, ticker, 3, from_date): ticker for ticker in tickers}

            # Process completed tasks with progress tracking
            if use_tqdm:
                with tqdm(total=total_tickers, desc="Fetching prices", unit="ticker") as pbar:
                    for future in concurrent.futures.as_completed(future_to_ticker):
                        ticker, success, error_msg = future.result()
                        results[ticker] = success
                        if success:
                            success_count += 1
                        else:
                            fail_count += 1
                            failed_tickers.append((ticker, error_msg))
                        pbar.update(1)
                        pbar.set_postfix({'✓': success_count, '✗': fail_count})
            else:
                completed = 0
                for future in concurrent.futures.as_completed(future_to_ticker):
                    ticker, success, error_msg = future.result()
                    results[ticker] = success
                    if success:
                        success_count += 1
                    else:
                        fail_count += 1
                        failed_tickers.append((ticker, error_msg))

                    completed += 1
                    # Log progress every 25 tickers or at milestones
                    if completed % 25 == 0 or completed == total_tickers:
                        pct_complete = (completed / total_tickers) * 100
                        elapsed = time.time() - start_time
                        rate = completed / elapsed if elapsed > 0 else 0
                        eta_seconds = (total_tickers - completed) / rate if rate > 0 else 0
                        eta_minutes = eta_seconds / 60

                        logger.info(
                            f"Progress: {completed}/{total_tickers} ({pct_complete:.1f}%) | "
                            f"✓ {success_count} ✗ {fail_count} | "
                            f"Rate: {rate:.1f} tickers/sec | "
                            f"ETA: {eta_minutes:.1f} min"
                        )

        # Final summary
        elapsed_total = time.time() - start_time
        logger.info(f"\n{'='*80}")
        logger.info(f"FMP Cache Update Complete!")
        logger.info(f"Total Time: {elapsed_total:.1f}s ({elapsed_total/60:.1f} min)")
        logger.info(f"Successful: {success_count}/{total_tickers} ({success_count/total_tickers*100:.1f}%)")
        logger.info(f"Failed: {fail_count}/{total_tickers} ({fail_count/total_tickers*100:.1f}%)")

        if failed_tickers:
            logger.warning(f"\n{'='*80}")
            logger.warning(f"FAILED TICKERS ({len(failed_tickers)}):")
            logger.warning(f"{'='*80}")
            for ticker, error in failed_tickers[:20]:  # Show first 20
                logger.warning(f"  {ticker}: {error}")
            if len(failed_tickers) > 20:
                logger.warning(f"  ... and {len(failed_tickers) - 20} more")

        logger.info(f"{'='*80}\n")

        return results
    
    def _update_cache_yfinance(self, tickers: List[str]) -> Dict[str, bool]:
        """
        Update cache using yfinance batch downloads.
        
        Args:
            tickers: List of ticker symbols
            
        Returns:
            Dict mapping ticker -> success status
        """
        results = {}
        batch_size = config.BATCH_SIZE
        
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}/{(len(tickers)-1)//batch_size + 1}")

            try:
                # Batch download - use period='max' for full history
                data = yf.download(
                    batch,
                    period='max',  # Get full historical data (start= param is often ignored)
                    group_by='ticker',
                    auto_adjust=True,
                    progress=False,
                    threads=True
                )

                # Save each ticker individually
                for ticker in batch:
                    try:
                        ticker_data = self._extract_ticker_from_batch(data, ticker)
                        if ticker_data is not None and not ticker_data.empty:
                            cache_file = self.price_dir / f"{ticker}.parquet"
                            ticker_data.to_parquet(cache_file)
                            results[ticker] = True
                        else:
                            results[ticker] = False
                    except Exception as e:
                        logger.debug(f"Failed to cache {ticker}: {e}")
                        results[ticker] = False

            except Exception as e:
                logger.error(f"Batch download failed for {len(batch)} tickers: {e}")
                for ticker in batch:
                    results[ticker] = False

        return results

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

        # Sort alphabetically
        tickers.sort()

        logger.debug(f"Found {len(tickers)} tickers in price cache")
        return tickers
