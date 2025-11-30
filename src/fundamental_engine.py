"""
Fundamental Engine - FundamentalEngine Class
Handles fundamental data fetching from FMP API and Parquet caching.
"""

import pandas as pd
import requests
import json
import time
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

    def __init__(self, api_key: str = None, fundamentals_dir: Path = None):
        """
        Initialize Fundamental Engine.
        
        Args:
            api_key: FMP API key (defaults to config.FMP_API_KEY)
            fundamentals_dir: Directory for parquet storage (defaults to config.FUNDAMENTALS_DIR)
        """
        self.api_key = api_key or config.FMP_API_KEY
        if not self.api_key:
            raise ValueError("FMP_API_KEY is required. Set it in .env file or pass to constructor.")
        
        self.fundamentals_dir = fundamentals_dir or config.FUNDAMENTALS_DIR
        self.fundamentals_dir.mkdir(parents=True, exist_ok=True)
        
        self.base_url = config.FMP_BASE_URL
        self.cache_days = config.FUNDAMENTAL_CACHE_DAYS
        self.lookback_years = config.FUNDAMENTAL_LOOKBACK_YEARS
        self.rate_limit = config.FMP_FUNDAMENTAL_RATE_LIMIT
        self.batch_size = config.FMP_FUNDAMENTAL_BATCH_SIZE
        self.batch_delay = config.FMP_FUNDAMENTAL_BATCH_DELAY
        
        # API call tracking for rate limiting
        self._call_timestamps = []

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
        Pauses execution if approaching rate limit.
        """
        now = time.time()
        # Keep only timestamps from last 60 seconds
        self._call_timestamps = [ts for ts in self._call_timestamps if now - ts < 60]
        
        # If approaching limit, wait
        if len(self._call_timestamps) >= self.rate_limit - 5:  # 5-call buffer
            sleep_time = 60 - (now - self._call_timestamps[0])
            if sleep_time > 0:
                logger.warning(f"Rate limit approaching, sleeping {sleep_time:.1f}s...")
                time.sleep(sleep_time)
                self._call_timestamps = []
        
        self._call_timestamps.append(now)

    def _fetch_statement(self, ticker: str, statement_type: str) -> Optional[pd.DataFrame]:
        """
        Fetch a single financial statement from FMP API.
        
        Args:
            ticker: Stock symbol
            statement_type: 'income-statement' or 'balance-sheet-statement'
            
        Returns:
            DataFrame with financial statement data, or None if failed
        """
        # Rate limiting
        self._rate_limit_check()
        
        # Build URL - FMP stable endpoint uses query parameters
        url = f"{self.base_url}/{statement_type}"
        params = {
            'symbol': ticker,
            'apikey': self.api_key,
            'limit': self.lookback_years * 4  # Quarterly reports: 4 per year
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if not data or not isinstance(data, list):
                logger.debug(f"No {statement_type} data for {ticker}")
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame(data)
            
            # Add statement type column
            df['statement_type'] = 'income' if 'income' in statement_type else 'balance_sheet'
            
            return df
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed for {ticker} {statement_type}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse response for {ticker} {statement_type}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching {ticker} {statement_type}: {e}")
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

    def fetch_all_fundamentals(self, ticker: str) -> Optional[pd.DataFrame]:
        """
        Fetch both income statement and balance sheet, merge into single DataFrame.
        
        Args:
            ticker: Stock symbol
            
        Returns:
            Combined DataFrame with all fundamental data
        """
        logger.debug(f"Fetching fundamentals for {ticker}...")
        
        # Fetch both statements
        income_df = self.fetch_income_statement(ticker)
        balance_df = self.fetch_balance_sheet(ticker)
        
        # Handle missing data
        if income_df is None and balance_df is None:
            logger.warning(f"No fundamental data available for {ticker}")
            return None
        
        if income_df is None:
            logger.warning(f"Missing income statement for {ticker}, using balance sheet only")
            combined = balance_df
        elif balance_df is None:
            logger.warning(f"Missing balance sheet for {ticker}, using income statement only")
            combined = income_df
        else:
            # Merge on date and period
            combined = pd.concat([income_df, balance_df], axis=0, ignore_index=True)
        
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
        if use_cache and cache_file.exists() and not self._is_cache_stale(cache_file):
            try:
                df = pd.read_parquet(cache_file)
                logger.debug(f"Loaded {ticker} fundamentals from cache")
                return df
            except Exception as e:
                logger.warning(f"Cache read failed for {ticker}: {e}")
        
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

    def update_fundamentals_cache(
        self, 
        tickers: List[str], 
        force: bool = False,
        show_progress: bool = True
    ) -> Dict[str, bool]:
        """
        Batch update fundamental data cache for multiple tickers.
        
        Args:
            tickers: List of ticker symbols
            force: If True, re-fetch all tickers regardless of cache
            show_progress: If True, display progress information
            
        Returns:
            Dict mapping ticker -> success status
        """
        results = {}
        to_fetch = []
        
        # Determine which tickers need updating
        for ticker in tickers:
            cache_file = self.fundamentals_dir / f"{ticker}.parquet"
            if force or self._is_cache_stale(cache_file):
                to_fetch.append(ticker)
            else:
                results[ticker] = True  # Already cached
        
        if not to_fetch:
            logger.info("All tickers are up to date in cache")
            return results
        
        logger.info(f"Updating fundamental cache for {len(to_fetch)}/{len(tickers)} tickers...")
        
        # Process in batches
        total_batches = (len(to_fetch) - 1) // self.batch_size + 1
        
        for i in range(0, len(to_fetch), self.batch_size):
            batch = to_fetch[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            
            if show_progress:
                logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} tickers)")
            
            # Fetch each ticker in batch
            for ticker in batch:
                try:
                    df = self.get_ticker_fundamentals(ticker, use_cache=False)
                    if df is not None and not df.empty:
                        results[ticker] = True
                    else:
                        results[ticker] = False
                except Exception as e:
                    logger.error(f"Failed to fetch {ticker}: {e}")
                    results[ticker] = False
            
            # Delay between batches (except for last batch)
            if batch_num < total_batches:
                if show_progress:
                    logger.info(f"Batch {batch_num} complete. Waiting {self.batch_delay}s before next batch...")
                time.sleep(self.batch_delay)
        
        # Summary
        success_count = sum(results.values())
        logger.info(f"Cache update complete: {success_count}/{len(to_fetch)} successful")
        
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
