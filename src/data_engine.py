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
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict
import logging

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config
from src.utils import get_latest_trading_day

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL))
logger = logging.getLogger(__name__)


class DataRepository:
    """
    Single source of truth for all market data.
    Implements smart Parquet caching to minimize API calls and bandwidth.
    """

    def __init__(self):
        self.price_dir = config.PRICE_DATA_DIR
        self.benchmark_ticker = config.BENCHMARK_TICKER
        self.cache_days = config.DATA_CACHE_DAYS
        
        # API call tracking for rate limiting (300 calls/minute like fundamentals)
        self._call_timestamps = []
        self.rate_limit = 300  # FMP Starter tier rate limit

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


    def _is_cache_stale(self, file_path: Path, min_date: str = '2000-01-01', check_min_date: bool = True) -> bool:
        """
        Check if cached Parquet file is stale or doesn't have required date range.

        Args:
            file_path: Path to cached file
            min_date: Minimum required start date (default: 2000-01-01)
            check_min_date: If False, skips historical range check and only validates latest data.
                          Use False for scanner (only needs current data), True for ML training.

        Returns:
            True if cache should be refreshed, False otherwise
        """
        if not file_path.exists():
            return True

        # Check file age (quick check before loading data)
        file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
        age_days = (datetime.now() - file_mtime).days
        if age_days >= self.cache_days:
            logger.debug(f"{file_path.name}: Stale (file age: {age_days} days)")
            return True

        # Check date range coverage and latest data date
        try:
            df = pd.read_parquet(file_path)
            if df.empty:
                logger.debug(f"{file_path.name}: Empty cache file")
                return True

            cache_start = df.index.min()
            cache_end = df.index.max()

            # Check if historical data goes back far enough (only if requested)
            if check_min_date:
                required_start = pd.Timestamp(min_date)

                if cache_start > required_start:
                    logger.debug(f"{file_path.name}: Insufficient range (has {cache_start.date()}, need {required_start.date()})")
                    return True

            # Check if latest data is current (most recent closed trading day)
            latest_trading_day = get_latest_trading_day()

            # Cache is stale if latest data is older than the most recent closed trading day
            # This accounts for weekends, holidays, and market hours
            if cache_end < latest_trading_day:
                logger.debug(f"{file_path.name}: Outdated (latest data: {cache_end.date()}, need: {latest_trading_day.date()})")
                return True

            logger.debug(f"{file_path.name}: Valid cache (from {cache_start.date()} to {cache_end.date()})")
            return False

        except Exception as e:
            logger.warning(f"{file_path.name}: Cache validation failed ({e}), treating as stale")
            return True

    def _rate_limit_check(self):
        """
        Enforce rate limiting for FMP API (300 calls/minute for Starter tier).
        Pauses execution if approaching rate limit.
        """
        now = time.time()
        # Keep only timestamps from last 60 seconds
        self._call_timestamps = [ts for ts in self._call_timestamps if now - ts < 60]
        
        # If approaching limit, wait
        if len(self._call_timestamps) >= self.rate_limit - 10:  # 10-call buffer
            sleep_time = 60 - (now - self._call_timestamps[0])
            if sleep_time > 0:
                logger.debug(f"Rate limit approaching, sleeping {sleep_time:.1f}s...")
                time.sleep(sleep_time)
                self._call_timestamps = []
        
        self._call_timestamps.append(now)
    
    def _fetch_fmp_historical(self, ticker: str, from_date: str = '1990-01-01', max_retries: int = 3) -> Optional[dict]:
        """
        Fetch historical OHLCV data from FMP API for a single ticker with retry logic.
        NOTE: FMP Starter tier does NOT support batch requests for historical data.

        Args:
            ticker: Single ticker symbol
            from_date: Start date for historical data (default: 1990-01-01)
            max_retries: Maximum number of retries for 429 errors (default: 3)

        Returns:
            JSON response dict with historical data, or None if failed
        """
        if not config.FMP_API_KEY:
            raise ValueError("FMP_API_KEY not set in environment")

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
                
                # FMP returns a list of historical data directly
                if isinstance(data, list) and len(data) > 0:
                    return {'historical': data}
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

    def get_ticker_data(self, ticker: str, use_cache: bool = True, source: str = 'fmp', min_date: str = '2000-01-01',
                       check_min_date: bool = True, max_retries: int = 2) -> Optional[pd.DataFrame]:
        """
        Returns OHLCV data for a single ticker.
        First checks Parquet cache, then downloads from FMP if needed.

        Args:
            ticker: Stock symbol
            use_cache: If True, uses cached data when available
            source: Data source - 'fmp' (default, recommended for quality) or 'yfinance' (not recommended)
            min_date: Minimum required start date for cache validation (default: 2000-01-01)
            check_min_date: If False, skips historical range check (for scanner). If True, validates full date range (for ML training)
            max_retries: Number of FMP download attempts before failing (default: 2)

        Returns:
            DataFrame with OHLCV data (adjusted), or None if failed
        """
        cache_file = self.price_dir / f"{ticker}.parquet"

        # Try cache first (with date range validation)
        if use_cache and cache_file.exists() and not self._is_cache_stale(cache_file, min_date=min_date, check_min_date=check_min_date):
            try:
                df = pd.read_parquet(cache_file)
                logger.debug(f"Loaded {ticker} from cache")
                return df
            except Exception as e:
                logger.warning(f"Cache read failed for {ticker}: {e}")

        # Download fresh data from FMP (primary source)
        if source == 'fmp':
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
        logger.warning(f"Using yfinance for {ticker} - data quality may be inconsistent")
        return self._get_ticker_data_yfinance(ticker, cache_file)

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

    def update_cache(self, tickers: List[str], force: bool = False, source: str = 'fmp', min_date: str = '1900-01-01',
                    check_min_date: bool = True) -> Dict[str, bool]:
        """
        Smart batch update of Parquet cache.
        Only downloads tickers that are missing or stale.

        Args:
            tickers: List of ticker symbols to update
            force: If True, re-downloads all tickers regardless of cache
            source: Data source - 'yfinance' (default) or 'fmp'
            min_date: Minimum required start date for cache validation (default: 1900-01-01)
            check_min_date: If False, skips historical range check (for scanner). If True, validates full date range (for ML training)

        Returns:
            Dict mapping ticker -> success status
        """
        results = {}
        to_download = []

        # Determine which tickers need updating
        for ticker in tickers:
            cache_file = self.price_dir / f"{ticker}.parquet"
            if force or self._is_cache_stale(cache_file, min_date=min_date, check_min_date=check_min_date):
                to_download.append(ticker)
            else:
                results[ticker] = True  # Already cached

        if not to_download:
            logger.info("All tickers are up to date in cache")
            return results

        logger.info(f"Updating cache for {len(to_download)}/{len(tickers)} tickers...")

        # Use FMP batch endpoint if explicitly requested and API key is available
        if source == 'fmp' and config.FMP_API_KEY:
            try:
                logger.info(f"Using FMP API for batch update...")
                fmp_results = self._update_cache_fmp(to_download)
                results.update(fmp_results)
                
                # Log success stats
                success_count = sum(fmp_results.values())
                logger.info(f"FMP batch update: {success_count}/{len(to_download)} successful")
                return results
                
            except Exception as e:
                logger.warning(f"FMP batch update failed: {e}")
        
        # Use yfinance batch download (fallback or explicit)
        logger.info(f"Using yfinance for batch update...")
        yf_results = self._update_cache_yfinance(to_download)
        results.update(yf_results)
        
        success_count = sum(yf_results.values())
        logger.info(f"Cache update complete: {success_count}/{len(to_download)} successful")
        return results
    
    def _update_cache_fmp(self, tickers: List[str]) -> Dict[str, bool]:
        """
        Update cache using FMP API (non-batch, individual requests).
        NOTE: FMP Starter tier does NOT support batch requests for historical data.
        Rate limited to 300 calls/minute.
        
        Args:
            tickers: List of ticker symbols
            
        Returns:
            Dict mapping ticker -> success status
        """
        results = {}
        total_tickers = len(tickers)
        success_count = 0
        fail_count = 0
        
        logger.info(f"Fetching {total_tickers} tickers from FMP (non-batch, rate limited to 300/min)...")
        start_time = time.time()
        
        for idx, ticker in enumerate(tickers, 1):
            try:
                # Fetch single ticker from FMP (with rate limiting)
                fmp_data = self._fetch_fmp_historical(ticker)
                
                if fmp_data:
                    df = self._parse_fmp_response(fmp_data, ticker)
                    if df is not None and not df.empty:
                        cache_file = self.price_dir / f"{ticker}.parquet"
                        df.to_parquet(cache_file)
                        results[ticker] = True
                        success_count += 1
                        logger.debug(f"Successfully cached {ticker}")
                    else:
                        logger.debug(f"No data parsed for {ticker}")
                        results[ticker] = False
                        fail_count += 1
                else:
                    logger.debug(f"No FMP response for {ticker}")
                    results[ticker] = False
                    fail_count += 1
                    
            except Exception as e:
                logger.error(f"Failed to fetch {ticker}: {e}")
                results[ticker] = False
                fail_count += 1
            
            # Progress update every 25 tickers or at milestones
            if idx % 25 == 0 or idx == total_tickers:
                pct_complete = (idx / total_tickers) * 100
                elapsed = time.time() - start_time
                rate = idx / elapsed if elapsed > 0 else 0
                eta_seconds = (total_tickers - idx) / rate if rate > 0 else 0
                eta_minutes = eta_seconds / 60
                
                logger.info(
                    f"Progress: {idx}/{total_tickers} ({pct_complete:.1f}%) | "
                    f"✓ {success_count} ✗ {fail_count} | "
                    f"Rate: {rate:.1f} tickers/sec | "
                    f"ETA: {eta_minutes:.1f} min"
                )
        
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

    def get_benchmark_data(self) -> Optional[pd.Series]:
        """
        Returns the benchmark (SPY) close prices.
        Used for relative strength calculations.
        """
        df = self.get_ticker_data(self.benchmark_ticker)
        if df is None:
            return None
        return self._safe_extract_close(df)

    def get_batch_data(self, tickers: List[str], max_workers: int = 8, show_progress: bool = False,
                      min_date: str = '2000-01-01', check_min_date: bool = False) -> Dict[str, pd.DataFrame]:
        """
        Loads multiple tickers from cache efficiently using parallel execution.

        Args:
            tickers: List of ticker symbols
            max_workers: Number of parallel threads (default: 8)
            show_progress: If True, display progress bar (default: False)
            min_date: Minimum required start date for cache validation (default: 2000-01-01)
                     For scanner use, set to ~2 years ago to allow recent IPOs
                     For ML training, set to 2010-01-01 for historical depth
            check_min_date: If False (default), skips historical range check and only validates latest data (scanner mode).
                          If True, validates full historical range (ML training mode).

        Returns:
            Dict mapping ticker -> DataFrame
        """
        data = {}

        # Helper function for parallel execution
        def load_single(ticker):
            return ticker, self.get_ticker_data(ticker, use_cache=True, min_date=min_date, check_min_date=check_min_date)

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
