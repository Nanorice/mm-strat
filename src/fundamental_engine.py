"""
Fundamental Engine - FundamentalEngine Class
Handles fundamental data fetching from FMP API and Parquet caching.
"""

import pandas as pd
import requests
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict
import logging

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL))
logger = logging.getLogger(__name__)


class FundamentalEngine:
    """
    Manages fundamental data from Financial Modeling Prep API.
    Fetches income statements and balance sheets, stores in parquet cache.
    """

    def __init__(self, api_key: str = None, fundamentals_dir: Path = None, force_cache_only: bool = False):
        """
        Initialize Fundamental Engine.

        Args:
            api_key: FMP API key (defaults to config.FMP_API_KEY)
            fundamentals_dir: Directory for parquet storage (defaults to config.FUNDAMENTALS_DIR)
            force_cache_only: If True, always use cached data without staleness checks or API calls
        """
        self.api_key = api_key or config.FMP_API_KEY
        if not self.api_key and not force_cache_only:
            raise ValueError("FMP_API_KEY is required. Set it in .env file or pass to constructor.")

        self.fundamentals_dir = fundamentals_dir or config.FUNDAMENTALS_DIR
        self.fundamentals_dir.mkdir(parents=True, exist_ok=True)

        self.base_url = config.FMP_BASE_URL
        self.cache_days = config.FUNDAMENTAL_CACHE_DAYS
        self.lookback_years = config.FUNDAMENTAL_LOOKBACK_YEARS
        self.rate_limit = config.FMP_FUNDAMENTAL_RATE_LIMIT
        self.batch_size = config.FMP_FUNDAMENTAL_BATCH_SIZE
        self.batch_delay = config.FMP_FUNDAMENTAL_BATCH_DELAY
        self.force_cache_only = force_cache_only

        # API call tracking for rate limiting (thread-safe)
        self._call_timestamps = []
        self._rate_limit_lock = threading.Lock()

        # Quota exhaustion tracking (shared across all workers)
        self._quota_exhausted = False
        self._quota_lock = threading.Lock()

    def _is_cache_stale(self, file_path: Path) -> bool:
        """
        Check if cached fundamental data is stale and needs refresh.
        
        Args:
            file_path: Path to parquet cache file
            
        Returns:
            True if cache is missing or older than cache_days
        """
        if not file_path.exists():
            return True
        
        file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
        age_days = (datetime.now() - file_mtime).days
        return age_days >= self.cache_days

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

    def _fetch_statement(self, ticker: str, statement_type: str, max_retries: int = 2) -> Optional[pd.DataFrame]:
        """
        Fetch a single financial statement from FMP API with retry logic.

        Args:
            ticker: Stock symbol
            statement_type: 'income-statement' or 'balance-sheet-statement'
            max_retries: Maximum number of retry attempts (default: 2)

        Returns:
            DataFrame with financial statement data, or None if failed
        """
        # Check if quota is exhausted (shared flag across all workers)
        with self._quota_lock:
            if self._quota_exhausted:
                logger.debug(f"{ticker} {statement_type}: Skipping due to quota exhaustion")
                return None

        # Build URL - FMP stable endpoint uses query parameters
        url = f"{self.base_url}/{statement_type}"
        params = {
            'symbol': ticker,
            'period': 'quarter',
            'apikey': self.api_key,
            'limit': 500 # self.lookback_years * 4  # Quarterly reports: 4 per year
        }

        for attempt in range(max_retries):
            # Rate limiting
            self._rate_limit_check()

            try:
                response = requests.get(url, params=params, timeout=30)

                # Handle rate limit (429) - check if it's quota exhaustion or transient rate limit
                if response.status_code == 429:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get('message', '').lower() if isinstance(error_data, dict) else ''
                    except:
                        error_msg = ''

                    # Check for quota exhaustion keywords
                    is_quota_exhausted = any(keyword in error_msg for keyword in [
                        'limit reached', 'quota', 'subscription', 'upgrade', 'plan'
                    ])

                    if is_quota_exhausted:
                        # Set global flag to stop all workers from retrying
                        with self._quota_lock:
                            if not self._quota_exhausted:
                                self._quota_exhausted = True
                                logger.error(f"API QUOTA EXHAUSTED: {error_msg}")
                                logger.error("All further API calls will be skipped. Please check your FMP API plan.")
                        return None

                    # Transient rate limit - retry with backoff
                    if attempt < max_retries - 1:
                        wait_time = (2 ** attempt) * 10  # 10s, 20s (more aggressive backoff)
                        logger.warning(f"{ticker} {statement_type}: Rate limit (429), retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"{ticker} {statement_type}: Rate limit (429), max retries exceeded")
                        return None

                response.raise_for_status()
                data = response.json()

                if not data or not isinstance(data, list):
                    logger.debug(f"No {statement_type} data for {ticker}")
                    return None

                # Convert to DataFrame
                df = pd.DataFrame(data)

                # Add statement type column
                if 'income' in statement_type:
                    df['statement_type'] = 'income'
                elif 'cash-flow' in statement_type or 'cash_flow' in statement_type:
                    df['statement_type'] = 'cash_flow'
                else:
                    df['statement_type'] = 'balance_sheet'

                return df

            except requests.exceptions.Timeout as e:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 2  # 2s, 4s, 8s
                    logger.warning(f"{ticker} {statement_type}: Timeout, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"API timeout for {ticker} {statement_type}: {e}")
                    return None
            except requests.exceptions.RequestException as e:
                # Don't retry on client errors (400-499 except 429)
                if hasattr(e, 'response') and e.response is not None and 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                    logger.error(f"API client error for {ticker} {statement_type}: {e}")
                    return None
                # Retry on server errors (500+) and network errors
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 3  # 3s, 6s, 12s
                    logger.warning(f"{ticker} {statement_type}: Request error, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"API request failed for {ticker} {statement_type}: {e}")
                    return None
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse response for {ticker} {statement_type}: {e}")
                return None
            except Exception as e:
                logger.error(f"Unexpected error fetching {ticker} {statement_type}: {e}")
                return None

        return None

    def fetch_income_statement(self, ticker: str) -> Optional[pd.DataFrame]:
        """
        Fetch income statement data for a ticker.
        
        Args:
            ticker: Stock symbol
            
        Returns:
            DataFrame with income statement data
        """
        return self._fetch_statement(ticker, 'income-statement')

    def fetch_balance_sheet(self, ticker: str) -> Optional[pd.DataFrame]:
        """
        Fetch balance sheet data for a ticker.
        
        Args:
            ticker: Stock symbol
            
        Returns:
            DataFrame with balance sheet data
        """
        return self._fetch_statement(ticker, 'balance-sheet-statement')

    def fetch_cash_flow_statement(self, ticker: str) -> Optional[pd.DataFrame]:
        """
        Fetch cash flow statement data for a ticker.
        
        Args:
            ticker: Stock symbol
            
        Returns:
            DataFrame with cash flow statement data
        """
        return self._fetch_statement(ticker, 'cash-flow-statement')

    def fetch_all_fundamentals(self, ticker: str) -> Optional[pd.DataFrame]:
        """
        Fetch income statement, balance sheet, and cash flow statement, merge into single DataFrame.
        
        Args:
            ticker: Stock symbol
            
        Returns:
            Combined DataFrame with all fundamental data (3 statement types)
        """
        logger.debug(f"Fetching fundamentals for {ticker}...")
        
        # Fetch all three statements
        income_df = self.fetch_income_statement(ticker)
        balance_df = self.fetch_balance_sheet(ticker)
        cash_flow_df = self.fetch_cash_flow_statement(ticker)
        
        # Collect available statements
        statements = []
        if income_df is not None:
            statements.append(income_df)
        if balance_df is not None:
            statements.append(balance_df)
        if cash_flow_df is not None:
            statements.append(cash_flow_df)
        
        # Handle missing data
        if not statements:
            logger.warning(f"No fundamental data available for {ticker}")
            return None
        
        # Log what we got
        statement_types = []
        if income_df is not None:
            statement_types.append('income')
        if balance_df is not None:
            statement_types.append('balance')
        if cash_flow_df is not None:
            statement_types.append('cash_flow')
        logger.debug(f"{ticker}: Fetched {len(statements)}/3 statements: {', '.join(statement_types)}")
        
        # Concatenate all available statements
        combined = pd.concat(statements, axis=0, ignore_index=True)
        
        # Standardize columns
        combined = self._standardize_columns(combined, ticker)
        
        return combined

    def _standardize_columns(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """
        Standardize column names and add metadata.
        
        Args:
            df: Raw dataframe from FMP
            ticker: Stock symbol
            
        Returns:
            Standardized DataFrame
        """
        # Rename key date columns if they exist
        column_mapping = {
            'date': 'fiscal_date',
            'filingDate': 'filing_date',
            'acceptedDate': 'accepted_date',
            'period': 'fiscal_period',
            'calendarYear': 'fiscal_year'
        }
        
        df = df.rename(columns=column_mapping)
        
        # Add ticker column
        df['ticker'] = ticker
        
        # Convert date columns to datetime
        date_cols = ['fiscal_date', 'filing_date', 'accepted_date']
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')
        
        # Sort by fiscal date (newest first as received from API)
        if 'fiscal_date' in df.columns:
            df = df.sort_values('fiscal_date', ascending=False)
        
        return df

    def get_ticker_fundamentals(self, ticker: str, use_cache: bool = True) -> Optional[pd.DataFrame]:
        """
        Get fundamental data for a ticker, from cache or API.

        Args:
            ticker: Stock symbol
            use_cache: If True, use cached data when available

        Returns:
            DataFrame with fundamental data, or None if failed
        """
        cache_file = self.fundamentals_dir / f"{ticker}.parquet"

        # Try cache first
        if use_cache and cache_file.exists() and (self.force_cache_only or not self._is_cache_stale(cache_file)):
            try:
                df = pd.read_parquet(cache_file)
                logger.debug(f"Loaded {ticker} fundamentals from cache")
                return df
            except Exception as e:
                logger.warning(f"Cache read failed for {ticker}: {e}")

        # If force_cache_only is True and cache doesn't exist, return None
        if self.force_cache_only:
            logger.warning(f"{ticker}: Cache-only mode enabled but no cached data found")
            return None

        # Fetch from API
        df = self.fetch_all_fundamentals(ticker)

        if df is not None and not df.empty:
            # Save to cache
            try:
                df.to_parquet(cache_file)
                logger.debug(f"Cached {ticker} fundamentals to {cache_file}")
            except Exception as e:
                logger.warning(f"Failed to cache {ticker}: {e}")

        return df

    def _fetch_ticker_worker(self, ticker: str) -> tuple[str, bool]:
        """
        Worker function for parallel ticker fetching.

        Args:
            ticker: Stock symbol to fetch

        Returns:
            Tuple of (ticker, success_status)
        """
        try:
            df = self.get_ticker_fundamentals(ticker, use_cache=False)
            if df is not None and not df.empty:
                return (ticker, True)
            else:
                return (ticker, False)
        except Exception as e:
            logger.error(f"Failed to fetch {ticker}: {e}")
            return (ticker, False)

    def update_fundamentals_cache(
        self,
        tickers: List[str],
        force: bool = False,
        show_progress: bool = True,
        max_workers: int = 10,
        use_earnings_calendar: bool = True
    ) -> Dict[str, bool]:
        """
        Batch update fundamental data cache for multiple tickers using parallel execution.

        Smart Update Strategy (use_earnings_calendar=True):
        - Uses earnings calendar to detect when new quarterly reports are available
        - Only fetches fundamentals for tickers with earnings releases after last cache update
        - Dramatically reduces API calls vs time-based staleness checks

        Legacy Mode (use_earnings_calendar=False or force=True):
        - Only checks for missing ticker files
        - Does not use time-based staleness (fundamentals update quarterly, not daily)

        Args:
            tickers: List of ticker symbols
            force: If True, re-fetch all tickers (disables earnings calendar)
            show_progress: If True, display progress information
            max_workers: Maximum number of parallel workers (default: 10, ~100 API calls/min with 3 calls per ticker)
            use_earnings_calendar: If True, use earnings calendar for intelligent updates (default: True)

        Returns:
            Dict mapping ticker -> success status
        """
        results = {}
        to_fetch = []

        # Determine which tickers need updating
        if force:
            # Force mode: Re-download everything
            logger.info("Force mode enabled - re-downloading all tickers")
            to_fetch = tickers
        elif use_earnings_calendar:
            # Smart mode: Use earnings calendar to determine updates
            logger.info("Using earnings calendar for intelligent fundamental updates...")

            try:
                from src.earnings_engine import EarningsEngine
                earnings_engine = EarningsEngine()

                # Step 1: Update earnings cache for all tickers
                logger.info("Updating earnings cache...")
                earnings_results = earnings_engine.update_earnings_cache(
                    tickers,
                    force=False,
                    max_workers=max_workers
                )

                earnings_success = sum(earnings_results.values())
                logger.info(f"Earnings cache updated: {earnings_success}/{len(tickers)} tickers")

                # Step 2: Get tickers needing fundamental update based on earnings
                to_fetch = earnings_engine.get_tickers_needing_fundamental_update(
                    tickers,
                    self.fundamentals_dir
                )

                # Mark cached tickers as success
                cached = set(tickers) - set(to_fetch)
                for ticker in cached:
                    results[ticker] = True

                logger.info(f"Earnings calendar analysis: {len(to_fetch)}/{len(tickers)} tickers need fundamental update")

            except Exception as e:
                logger.warning(f"Earnings calendar failed ({e}), falling back to legacy mode")
                use_earnings_calendar = False

        if not use_earnings_calendar and not force:
            # Legacy mode: Only download missing tickers (no date staleness check)
            # Fundamentals update quarterly on earnings dates, not daily trading days
            for ticker in tickers:
                cache_file = self.fundamentals_dir / f"{ticker}.parquet"
                if not cache_file.exists():
                    to_fetch.append(ticker)
                else:
                    results[ticker] = True  # Already cached

        if not to_fetch:
            logger.info("All tickers are up to date in cache")
            return results

        logger.info(f"Updating fundamental cache for {len(to_fetch)}/{len(tickers)} tickers...")
        logger.info(f"Estimated: {len(to_fetch) * 3} API calls with {max_workers} parallel workers")
        # Rate limit: 300 calls/min ÷ 3 calls per ticker = max 100 tickers/min
        # Conservative estimate: 80-90 tickers/min to stay under limit
        calls_per_ticker = 3
        max_tickers_per_min = (self.rate_limit * 0.9) / calls_per_ticker  # 90% of rate limit for safety
        estimated_minutes = len(to_fetch) / max_tickers_per_min if max_tickers_per_min > 0 else 0
        logger.info(f"Rate limit: {self.rate_limit} calls/min → max ~{max_tickers_per_min:.0f} tickers/min")
        logger.info(f"Estimated time: ~{estimated_minutes:.1f} minutes ({estimated_minutes/60:.1f} hours)")

        # Process tickers in parallel with ThreadPoolExecutor
        success_count = 0
        fail_count = 0

        if show_progress:
            try:
                from tqdm import tqdm
                use_tqdm = True
            except ImportError:
                use_tqdm = False
                logger.info("Install tqdm for progress bar: pip install tqdm")
        else:
            use_tqdm = False

        # Use ThreadPoolExecutor for parallel fetching
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_ticker = {executor.submit(self._fetch_ticker_worker, ticker): ticker for ticker in to_fetch}

            # Process completed tasks with progress tracking
            if use_tqdm:
                with tqdm(total=len(to_fetch), desc="Fetching fundamentals", unit="ticker") as pbar:
                    for future in as_completed(future_to_ticker):
                        ticker, success = future.result()
                        results[ticker] = success
                        if success:
                            success_count += 1
                        else:
                            fail_count += 1
                        pbar.update(1)
            else:
                completed = 0
                for future in as_completed(future_to_ticker):
                    ticker, success = future.result()
                    results[ticker] = success
                    if success:
                        success_count += 1
                    else:
                        fail_count += 1

                    completed += 1
                    # Log progress every 25 tickers
                    if completed % 25 == 0 or completed == len(to_fetch):
                        elapsed = time.time() - start_time
                        rate = completed / elapsed if elapsed > 0 else 0
                        eta_seconds = (len(to_fetch) - completed) / rate if rate > 0 else 0
                        logger.info(
                            f"Progress: {completed}/{len(to_fetch)} ({completed/len(to_fetch)*100:.1f}%) | "
                            f"✓ {success_count} ✗ {fail_count} | "
                            f"Rate: {rate:.1f} tickers/sec | "
                            f"ETA: {eta_seconds/60:.1f} min"
                        )

        # Summary
        elapsed_total = time.time() - start_time
        logger.info(f"Cache update complete: {success_count}/{len(to_fetch)} successful, {fail_count} failed")
        logger.info(f"Total time: {elapsed_total/60:.1f} minutes ({len(to_fetch)/elapsed_total*60:.1f} tickers/min)")

        return results

    def get_available_tickers(self) -> List[str]:
        """
        Get list of tickers that have cached fundamental data.
        
        Returns:
            List of ticker symbols with cached data
        """
        parquet_files = list(self.fundamentals_dir.glob('*.parquet'))
        tickers = [f.stem for f in parquet_files]
        return sorted(tickers)

    def get_cache_stats(self) -> Dict:
        """
        Get statistics about the fundamental data cache.
        
        Returns:
            Dictionary with cache statistics
        """
        available_tickers = self.get_available_tickers()
        total_tickers = len(available_tickers)
        
        if total_tickers == 0:
            return {
                'total_tickers': 0,
                'total_size_mb': 0,
                'avg_size_kb': 0,
                'oldest_cache': None,
                'newest_cache': None
            }
        
        # Calculate total size
        total_size = sum(
            (self.fundamentals_dir / f"{ticker}.parquet").stat().st_size 
            for ticker in available_tickers
        )
        
        # Find oldest and newest cache
        cache_files = [(self.fundamentals_dir / f"{ticker}.parquet") for ticker in available_tickers]
        mtimes = [f.stat().st_mtime for f in cache_files]
        
        return {
            'total_tickers': total_tickers,
            'total_size_mb': total_size / (1024 * 1024),
            'avg_size_kb': (total_size / total_tickers) / 1024,
            'oldest_cache': datetime.fromtimestamp(min(mtimes)),
            'newest_cache': datetime.fromtimestamp(max(mtimes))
        }
