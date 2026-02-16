"""
Earnings Engine - Tracks earnings release dates and estimates
Enables intelligent fundamental data updates based on earnings calendar

Key Features:
1. Per-ticker earnings history and forecasts (data/earnings/{TICKER}.parquet)
2. Smart cache invalidation based on earnings actuals being filled in
3. Integration with FundamentalEngine to trigger updates only when new reports available
"""

import pandas as pd
import requests
import time
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class EarningsEngine:
    """
    Manages earnings calendar and surprise data from FMP API.
    Stores per-ticker earnings history and forecasts.

    Cache Invalidation Rules:
    1. Cache older than EARNINGS_CACHE_DAYS (default: 7 days)
    2. Next earnings date within EARNINGS_ALERT_DAYS (default: 14 days)
    3. Latest 3 fundamental reports have same dates as cached earnings but actuals are still null
       (indicates FMP has updated actuals since we last cached)
    """

    def __init__(self, api_key: str = None, earnings_dir: Path = None):
        """
        Initialize Earnings Engine.

        Args:
            api_key: FMP API key (defaults to config.FMP_API_KEY)
            earnings_dir: Directory for earnings cache (defaults to config.EARNINGS_DIR)
        """
        self.api_key = api_key or config.FMP_API_KEY
        if not self.api_key:
            raise ValueError("FMP_API_KEY required. Set in .env file or pass to constructor.")

        self.earnings_dir = earnings_dir or config.EARNINGS_DIR
        self.earnings_dir.mkdir(parents=True, exist_ok=True)

        self.base_url = config.FMP_BASE_URL
        self.rate_limit = config.FMP_FUNDAMENTAL_RATE_LIMIT
        self.cache_days = config.EARNINGS_CACHE_DAYS

        # Rate limiting (thread-safe)
        self._call_timestamps = []
        self._rate_limit_lock = threading.Lock()

        # Quota exhaustion tracking (shared across all workers)
        self._quota_exhausted = False
        self._quota_lock = threading.Lock()

    def _rate_limit_check(self):
        """
        Enforce rate limiting for FMP API (300 calls/minute for Starter tier).
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
                oldest_call = self._call_timestamps[0]
                sleep_time = 60.0 - (now - oldest_call) + 0.1  # Add 0.1s buffer
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
            self._call_timestamps.append(now)

    def _fetch_ticker_earnings(self, ticker: str, limit: int = 1000, max_retries: int = 2) -> Optional[pd.DataFrame]:
        """
        Fetch earnings history + future schedule from FMP.

        API: GET /earnings?symbol={ticker}&limit={limit}

        Args:
            ticker: Stock symbol
            limit: Max number of earnings records to fetch
            max_retries: Maximum number of retry attempts (default: 2)

        Returns:
            DataFrame with earnings data, or None if failed
        """
        # Check if quota is exhausted (shared flag across all workers)
        with self._quota_lock:
            if self._quota_exhausted:
                logger.debug(f"{ticker}: Skipping earnings fetch due to quota exhaustion")
                return None

        url = f"{self.base_url}/earnings"
        params = {
            'symbol': ticker,
            'apikey': self.api_key,
            'limit': limit
        }

        for attempt in range(max_retries):
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
                        wait_time = (2 ** attempt) * 10  # 10s, 20s
                        logger.warning(f"{ticker}: Rate limit (429), retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"{ticker}: Rate limit (429), max retries exceeded")
                        return None

                response.raise_for_status()
                data = response.json()

                if not data or not isinstance(data, list):
                    logger.debug(f"No earnings data for {ticker}")
                    return None

                df = pd.DataFrame(data)
                df = self._parse_earnings_response(df, ticker)
                return df

            except requests.exceptions.Timeout as e:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 5  # 5s, 10s
                    logger.warning(f"{ticker}: Timeout, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"API timeout for {ticker}: {e}")
                    return None
            except requests.exceptions.RequestException as e:
                # Don't retry on client errors (400-499 except 429)
                if hasattr(e, 'response') and e.response is not None and 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                    logger.error(f"API client error for {ticker}: {e}")
                    return None
                # Retry on server errors (500+) and network errors
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 5  # 5s, 10s
                    logger.warning(f"{ticker}: Request error, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"API request failed for {ticker}: {e}")
                    return None
            except Exception as e:
                logger.error(f"Unexpected error fetching earnings for {ticker}: {e}")
                return None

        return None

    def _parse_earnings_response(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """
        Parse FMP earnings response and add derived fields.

        Derived fields:
        - is_future: True if earnings date > today
        - eps_surprise_pct: (actual - estimate) / |estimate| * 100
        - revenue_surprise_pct: (actual - estimate) / |estimate| * 100
        - cache_timestamp: When we cached this data

        Args:
            df: Raw DataFrame from FMP API
            ticker: Stock symbol

        Returns:
            Parsed and enriched DataFrame
        """
        # Convert dates
        df['date'] = pd.to_datetime(df['date'])
        df['lastUpdated'] = pd.to_datetime(df['lastUpdated'])

        # Add ticker column
        df['symbol'] = ticker

        # Mark future vs past earnings
        df['is_future'] = df['date'] > pd.Timestamp.now()

        # Calculate surprise percentages (only for past earnings with actuals)
        # Use abs() safely by checking for non-null values first
        eps_mask = (
            df['epsEstimated'].notna() &
            df['epsActual'].notna() &
            (df['epsEstimated'] != 0) &  # Avoid division by zero
            ~df['is_future']
        )
        df['eps_surprise_pct'] = None
        df.loc[eps_mask, 'eps_surprise_pct'] = (
            (df.loc[eps_mask, 'epsActual'] - df.loc[eps_mask, 'epsEstimated']) /
            df.loc[eps_mask, 'epsEstimated'].abs() * 100
        )

        revenue_mask = (
            df['revenueEstimated'].notna() &
            df['revenueActual'].notna() &
            (df['revenueEstimated'] != 0) &  # Avoid division by zero
            ~df['is_future']
        )
        df['revenue_surprise_pct'] = None
        df.loc[revenue_mask, 'revenue_surprise_pct'] = (
            (df.loc[revenue_mask, 'revenueActual'] - df.loc[revenue_mask, 'revenueEstimated']) /
            df.loc[revenue_mask, 'revenueEstimated'].abs() * 100
        )

        # Add cache timestamp
        df['cache_timestamp'] = datetime.now()

        # Sort by date descending (newest first)
        df = df.sort_values('date', ascending=False)

        return df

    def _check_actuals_updated(self, cached_df: pd.DataFrame, fund_cache_path: Path) -> bool:
        """
        Check if latest 3 fundamental reports in cache have actuals filled in.

        Logic:
        - Get latest 3 past earnings from cached data
        - If any have null epsActual/revenueActual, FMP might have updated them
        - Return True if we should refresh to get latest actuals

        Args:
            cached_df: Cached earnings DataFrame
            fund_cache_path: Path to fundamental cache file (to check if update needed)

        Returns:
            True if earnings cache should be refreshed to get updated actuals
        """
        # Get past earnings (sorted newest first)
        past_earnings = cached_df[~cached_df['is_future']].sort_values('date', ascending=False)

        if past_earnings.empty:
            return False  # No past earnings to check

        # Check latest 3 past earnings
        latest_3 = past_earnings.head(3)

        # If any of the latest 3 have null actuals, we should refresh
        # This means FMP likely has filled in the actuals since we last cached
        has_null_actuals = (
            latest_3['epsActual'].isna().any() or
            latest_3['revenueActual'].isna().any()
        )

        if has_null_actuals:
            logger.debug(f"{cached_df['symbol'].iloc[0]}: Latest earnings have null actuals, refreshing cache")
            return True

        return False

    def _is_cache_stale(self, file_path: Path, fund_cache_path: Path = None) -> bool:
        """
        Check if earnings cache needs refresh.

        Refresh rules:
        1. Cache older than EARNINGS_CACHE_DAYS (default: 7 days)
        2. Next earnings date within EARNINGS_ALERT_DAYS (default: 14 days)
        3. Latest 3 earnings have null actuals (FMP likely has updated them)

        Args:
            file_path: Path to earnings cache file
            fund_cache_path: Optional path to fundamental cache (for actuals check)

        Returns:
            True if cache should be refreshed
        """
        if not file_path.exists():
            return True

        try:
            df = pd.read_parquet(file_path)

            # Rule 1: Check cache age
            cache_age = (datetime.now() - df['cache_timestamp'].iloc[0]).days
            if cache_age >= self.cache_days:
                logger.debug(f"{file_path.stem}: Cache is {cache_age} days old (limit: {self.cache_days})")
                return True

            # Rule 2: Check if earnings imminent
            future_earnings = df[df['is_future']].sort_values('date')
            if not future_earnings.empty:
                next_earnings = future_earnings.iloc[0]['date']
                days_until = (next_earnings - pd.Timestamp.now()).days

                if days_until <= config.EARNINGS_ALERT_DAYS:
                    logger.debug(f"{file_path.stem}: Next earnings in {days_until} days (alert threshold: {config.EARNINGS_ALERT_DAYS})")
                    return True

            # Rule 3: Check if FMP has updated actuals since we cached
            if fund_cache_path and self._check_actuals_updated(df, fund_cache_path):
                return True

            return False  # Cache is fresh

        except Exception as e:
            logger.warning(f"Error checking cache staleness for {file_path.stem}: {e}")
            return True  # Treat errors as stale

    def get_ticker_earnings(self, ticker: str, use_cache: bool = True) -> Optional[pd.DataFrame]:
        """
        Get earnings data from cache or API.

        Args:
            ticker: Stock symbol
            use_cache: If True, use cached data when available and fresh

        Returns:
            DataFrame with earnings data, or None if unavailable
        """
        cache_file = self.earnings_dir / f"{ticker}.parquet"

        # Try cache first
        if use_cache and cache_file.exists():
            # Check staleness (pass fundamental cache path if exists)
            fund_cache_path = config.FUNDAMENTALS_DIR / f"{ticker}.parquet"

            if not self._is_cache_stale(cache_file, fund_cache_path):
                try:
                    df = pd.read_parquet(cache_file)
                    logger.debug(f"Loaded {ticker} earnings from cache")
                    return df
                except Exception as e:
                    logger.warning(f"Cache read failed for {ticker}: {e}")

        # Fetch from API
        df = self._fetch_ticker_earnings(ticker)

        if df is not None and not df.empty:
            try:
                df.to_parquet(cache_file)
                logger.debug(f"Cached {ticker} earnings to {cache_file}")
            except Exception as e:
                logger.warning(f"Failed to cache {ticker} earnings: {e}")

        return df

    def get_latest_earnings_date(self, ticker: str) -> Optional[datetime]:
        """
        Get the most recent past earnings date for a ticker.

        Args:
            ticker: Stock symbol

        Returns:
            Datetime of latest earnings, or None if no past earnings found
        """
        df = self.get_ticker_earnings(ticker, use_cache=True)

        if df is None or df.empty:
            return None

        past_earnings = df[~df['is_future']]
        if past_earnings.empty:
            return None

        return past_earnings['date'].max()

    def has_new_earnings_since(self, ticker: str, since_date: datetime) -> bool:
        """
        Check if ticker has had earnings release since given date.
        Used by FundamentalEngine to determine if update needed.

        Args:
            ticker: Stock symbol
            since_date: Datetime to compare against

        Returns:
            True if ticker has earnings after since_date
        """
        latest_earnings = self.get_latest_earnings_date(ticker)

        if latest_earnings is None:
            return False  # No earnings data, assume no new earnings

        return latest_earnings > since_date

    def _update_ticker_worker(self, ticker: str) -> tuple[str, bool]:
        """
        Worker function for parallel earnings cache updates.

        Args:
            ticker: Stock symbol to update

        Returns:
            Tuple of (ticker, success_status)
        """
        try:
            df = self.get_ticker_earnings(ticker, use_cache=False)
            return (ticker, df is not None and not df.empty)
        except Exception as e:
            logger.error(f"Failed to update earnings for {ticker}: {e}")
            return (ticker, False)

    def update_earnings_cache(
        self,
        tickers: List[str],
        force: bool = False,
        max_workers: int = 10,
        show_progress: bool = True
    ) -> Dict[str, bool]:
        """
        Batch update earnings cache for multiple tickers.

        Args:
            tickers: List of ticker symbols
            force: If True, re-download all regardless of cache freshness
            max_workers: Number of parallel workers (default: 10)
            show_progress: If True, display progress bar (default: True)

        Returns:
            Dict mapping ticker -> success status
        """
        results = {}
        to_fetch = []

        if force:
            logger.info("Force mode: re-downloading all earnings")
            to_fetch = tickers
        else:
            # Only fetch missing or stale caches
            for ticker in tickers:
                cache_file = self.earnings_dir / f"{ticker}.parquet"
                fund_cache_file = config.FUNDAMENTALS_DIR / f"{ticker}.parquet"

                if not cache_file.exists() or self._is_cache_stale(cache_file, fund_cache_file):
                    to_fetch.append(ticker)
                else:
                    results[ticker] = True  # Already cached and fresh

        if not to_fetch:
            logger.info("All earnings caches are up to date")
            return results

        logger.info(f"Updating earnings cache for {len(to_fetch)}/{len(tickers)} tickers...")

        # Check if tqdm is available
        if show_progress:
            try:
                from tqdm import tqdm
                use_tqdm = True
            except ImportError:
                use_tqdm = False
                logger.info("Install tqdm for progress bar: pip install tqdm")
        else:
            use_tqdm = False

        # Parallel fetch with progress tracking
        success_count = 0
        fail_count = 0

        start_time = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ticker = {
                executor.submit(self._update_ticker_worker, ticker): ticker
                for ticker in to_fetch
            }

            if use_tqdm:
                with tqdm(total=len(to_fetch), desc="Fetching earnings", unit="ticker") as pbar:
                    for future in as_completed(future_to_ticker):
                        ticker, success = future.result()
                        results[ticker] = success
                        if success:
                            success_count += 1
                        else:
                            fail_count += 1
                        pbar.update(1)
            else:
                # No progress bar, just log periodically
                completed = 0
                for future in as_completed(future_to_ticker):
                    ticker, success = future.result()
                    results[ticker] = success
                    if success:
                        success_count += 1
                    else:
                        fail_count += 1

                    completed += 1
                    # Log every 50 tickers
                    if completed % 50 == 0 or completed == len(to_fetch):
                        logger.info(f"Progress: {completed}/{len(to_fetch)} (✓ {success_count} ✗ {fail_count})")

        elapsed = time.time() - start_time
        logger.info(
            f"Earnings update complete: {success_count}/{len(to_fetch)} successful, "
            f"{fail_count} failed in {elapsed:.1f}s"
        )

        return results

    def get_tickers_needing_fundamental_update(
        self,
        tickers: List[str],
        fundamentals_dir: Path
    ) -> List[str]:
        """
        Identify tickers that need fundamental update based on earnings calendar.

        Optimized vectorized implementation using pandas for fast batch processing.

        Logic:
        - Compare latest earnings date against the latest fiscal_date in fundamental cache
        - If earnings occurred AFTER the latest fiscal period we have cached, update needed
        - This is more reliable than file mtime (which changes on every write)

        Args:
            tickers: List of tickers to check
            fundamentals_dir: Path to fundamentals cache directory

        Returns:
            List of tickers needing fundamental update
        """
        logger.info(f"Analyzing {len(tickers)} tickers for fundamental update needs...")

        needs_update = []

        # Step 1: Build fundamental cache metadata
        # Read filing_date from cache - this is when the company filed their earnings report
        # We compare this against the earnings calendar to see if we're missing a newer filing
        fund_metadata = []
        for ticker in tickers:
            fund_cache = fundamentals_dir / f"{ticker}.parquet"
            if fund_cache.exists():
                try:
                    # Read filing_date column - this matches earnings announcement dates
                    fund_df = pd.read_parquet(fund_cache, columns=['filing_date'])
                    if not fund_df.empty and 'filing_date' in fund_df.columns:
                        # Get the most recent filing date
                        latest_filing = pd.to_datetime(fund_df['filing_date']).max()
                        if pd.notna(latest_filing):
                            fund_metadata.append({
                                'ticker': ticker,
                                'latest_filing_date': latest_filing
                            })
                            continue
                except Exception as e:
                    logger.debug(f"{ticker}: Could not read filing_date from cache: {e}")
                # Fallback: file mtime
                fund_metadata.append({
                    'ticker': ticker,
                    'latest_filing_date': pd.Timestamp(datetime.fromtimestamp(fund_cache.stat().st_mtime))
                })
            else:
                # No fundamental cache -> needs update
                needs_update.append(ticker)

        logger.info(f"{len(needs_update)} tickers missing fundamental cache")

        if not fund_metadata:
            logger.info("No fundamental metadata to analyze")
            return needs_update

        # Early return: If no earnings cache exists for ANY ticker with fundamentals,
        # skip the earnings comparison (avoids reading all earnings files)
        has_any_earnings_cache = any(
            (self.earnings_dir / f"{row['ticker']}.parquet").exists()
            for row in fund_metadata
        )
        if not has_any_earnings_cache:
            logger.info("No earnings cache available, skipping earnings-based staleness check")
            return needs_update

        # Step 2: Build earnings metadata (parallel batch read for speed)
        fund_df = pd.DataFrame(fund_metadata)

        def _read_latest_earnings(ticker: str) -> Optional[tuple]:
            """Helper to read latest earnings date for a ticker."""
            earnings_cache = self.earnings_dir / f"{ticker}.parquet"
            if not earnings_cache.exists():
                return None
            try:
                earnings_df = pd.read_parquet(earnings_cache, columns=['date', 'is_future'])
                past_earnings = earnings_df[~earnings_df['is_future']]
                if not past_earnings.empty:
                    return (ticker, past_earnings['date'].max())
            except Exception as e:
                logger.warning(f"Failed to read earnings for {ticker}: {e}")
            return None

        # Parallel read of earnings files (much faster for large universes)
        from concurrent.futures import ThreadPoolExecutor, as_completed

        logger.info(f"Reading earnings metadata for {len(fund_df)} tickers (parallel)...")

        earnings_metadata = []
        completed = 0
        total_to_read = len(fund_df)

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(_read_latest_earnings, ticker): ticker
                      for ticker in fund_df['ticker']}

            for future in as_completed(futures):
                result = future.result()
                if result:
                    ticker, latest_date = result
                    earnings_metadata.append({
                        'ticker': ticker,
                        'latest_earnings_date': latest_date
                    })

                completed += 1
                # Log every 500 tickers
                if completed % 500 == 0 or completed == total_to_read:
                    logger.info(f"Earnings metadata: {completed}/{total_to_read} read")

        if not earnings_metadata:
            logger.info("No earnings metadata found")
            return needs_update

        # Step 3: Vectorized comparison (pandas merge)
        earnings_df = pd.DataFrame(earnings_metadata)

        # Merge fundamental and earnings metadata
        merged = fund_df.merge(earnings_df, on='ticker', how='inner')

        # Compare: If earnings calendar shows a date more recent than our latest filing_date,
        # it means there's a new earnings report we don't have yet
        stale_mask = merged['latest_earnings_date'] > merged['latest_filing_date']
        stale_tickers = merged.loc[stale_mask, 'ticker'].tolist()

        needs_update.extend(stale_tickers)

        logger.info(
            f"Earnings calendar analysis complete: "
            f"{len(stale_tickers)} tickers with new earnings + "
            f"{len(needs_update) - len(stale_tickers)} missing cache = "
            f"{len(needs_update)} total needing update"
        )

        return needs_update

    def get_cache_stats(self) -> Dict:
        """
        Get earnings cache statistics.

        Returns:
            Dict with cache stats (total_tickers, total_size_mb, avg_size_kb)
        """
        files = list(self.earnings_dir.glob('*.parquet'))

        if not files:
            return {
                'total_tickers': 0,
                'total_size_mb': 0,
                'avg_size_kb': 0
            }

        total_size = sum(f.stat().st_size for f in files)

        return {
            'total_tickers': len(files),
            'total_size_mb': total_size / (1024 * 1024),
            'avg_size_kb': (total_size / len(files)) / 1024
        }

    def get_available_tickers(self) -> List[str]:
        """
        Get list of tickers with cached earnings data.

        Returns:
            Sorted list of ticker symbols
        """
        files = list(self.earnings_dir.glob('*.parquet'))
        tickers = [f.stem for f in files]
        return sorted(tickers)
