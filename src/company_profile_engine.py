"""
Company Profile Engine - CompanyProfileEngine Class
Handles company profile data fetching from FMP API and Parquet caching.
Provides sector, industry, and company metadata for the ticker universe.
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


class CompanyProfileEngine:
    """
    Manages company profile data from Financial Modeling Prep API.
    Fetches sector, industry, market cap, and other company metadata.
    Stores in consolidated parquet file for efficient access.
    """

    def __init__(self, api_key: str = None, company_info_dir: Path = None):
        """
        Initialize Company Profile Engine.

        Args:
            api_key: FMP API key (defaults to config.FMP_API_KEY)
            company_info_dir: Directory for parquet storage (defaults to config.COMPANY_INFO_DIR)
        """
        self.api_key = api_key or config.FMP_API_KEY
        if not self.api_key:
            raise ValueError("FMP_API_KEY is required. Set it in .env file or pass to constructor.")

        self.company_info_dir = company_info_dir or config.COMPANY_INFO_DIR
        self.company_info_dir.mkdir(parents=True, exist_ok=True)

        self.profiles_file = self.company_info_dir / 'company_profiles.parquet'
        self.industry_mapping_file = self.company_info_dir / 'industry_mapping.parquet'
        self.sector_mapping_file = self.company_info_dir / 'sector_mapping.parquet'

        self.base_url = config.FMP_BASE_URL
        self.cache_days = config.COMPANY_PROFILE_CACHE_DAYS
        self.rate_limit = config.FMP_FUNDAMENTAL_RATE_LIMIT

        # API call tracking for rate limiting
        self._call_timestamps = []

    def _is_cache_stale(self, file_path: Path) -> bool:
        """
        Check if cached company profile data is stale and needs refresh.

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

    def _fetch_company_profile(self, ticker: str) -> Optional[Dict]:
        """
        Fetch company profile from FMP API for a single ticker.

        Args:
            ticker: Stock symbol

        Returns:
            Dict with profile data, or None if failed
        """
        # Rate limiting
        self._rate_limit_check()

        # Build URL
        url = f"{self.base_url}/profile"
        params = {
            'symbol': ticker,
            'apikey': self.api_key
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data or not isinstance(data, list) or len(data) == 0:
                logger.debug(f"No profile data for {ticker}")
                return None

            # Extract first element (API returns array with single object)
            profile = data[0]
            return profile

        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed for {ticker}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse response for {ticker}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching {ticker}: {e}")
            return None

    def _fetch_industry_list(self) -> Optional[List[Dict]]:
        """
        Fetch complete industry list from FMP API.

        Returns:
            List of dicts with 'industry' key, or None if failed
        """
        # Rate limiting
        self._rate_limit_check()

        # Build URL
        url = f"{self.base_url}/available-industries"
        params = {'apikey': self.api_key}

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data or not isinstance(data, list):
                logger.error("Failed to fetch industry list")
                return None

            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed for industry list: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse industry list response: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching industry list: {e}")
            return None

    def _fetch_sector_list(self) -> Optional[List[Dict]]:
        """
        Fetch complete sector list from FMP API.

        Returns:
            List of dicts with 'sector' key, or None if failed
        """
        # Rate limiting
        self._rate_limit_check()

        # Build URL
        url = f"{self.base_url}/available-sectors"
        params = {'apikey': self.api_key}

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data or not isinstance(data, list):
                logger.error("Failed to fetch sector list")
                return None

            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed for sector list: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse sector list response: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching sector list: {e}")
            return None

    def _parse_profile_response(self, profile_data: Dict, ticker: str) -> Optional[Dict]:
        """
        Extract relevant fields from FMP profile response.

        Args:
            profile_data: Raw API response
            ticker: Stock symbol

        Returns:
            Dict with cleaned fields
        """
        try:
            # Handle mktCap which might be under different names
            mkt_cap = profile_data.get('mktCap') or profile_data.get('marketCap') or 0

            return {
                'ticker': ticker,
                'companyName': profile_data.get('companyName', ''),
                'sector': profile_data.get('sector', ''),
                'industry': profile_data.get('industry', ''),
                'exchange': profile_data.get('exchangeShortName', ''),
                'country': profile_data.get('country', ''),
                'mktCap': float(mkt_cap),
                'beta': float(profile_data.get('beta', 1.0)),
                'price': float(profile_data.get('price', 0)),
                'ipoDate': profile_data.get('ipoDate', ''),
                'last_updated': datetime.now()
            }
        except Exception as e:
            logger.error(f"Failed to parse profile for {ticker}: {e}")
            return None

    def _build_industry_mapping(self, industries: List[Dict]) -> pd.DataFrame:
        """
        Build industry mapping with sequential IDs.

        Args:
            industries: List of industry dicts from FMP

        Returns:
            DataFrame with industry_id and industry columns
        """
        # Extract industry names
        industry_names = [item['industry'] for item in industries]

        # Create DataFrame with sequential IDs
        df = pd.DataFrame({
            'industry_id': range(len(industry_names)),
            'industry': industry_names
        })

        return df

    def _build_sector_mapping(self, sectors: List[Dict]) -> pd.DataFrame:
        """
        Build sector mapping with sequential IDs.

        Args:
            sectors: List of sector dicts from FMP

        Returns:
            DataFrame with sector_id and sector columns
        """
        # Extract sector names
        sector_names = [item['sector'] for item in sectors]

        # Create DataFrame with sequential IDs (sorted for consistency)
        df = pd.DataFrame({
            'sector_id': range(len(sector_names)),
            'sector': sector_names
        })

        return df

    def _merge_with_industry_ids(self, profiles_df: pd.DataFrame) -> pd.DataFrame:
        """
        Merge profile data with industry and sector IDs for encoding.

        Args:
            profiles_df: DataFrame with company profiles (ticker as index)

        Returns:
            Enhanced DataFrame with industry_id and sector_id columns (ticker as index preserved)
        """
        # Load industry mapping
        industry_mapping = self.get_industry_mapping(use_cache=True)
        # Load sector mapping
        sector_mapping = self.get_sector_mapping(use_cache=True)

        # If both mappings missing, add default IDs and return
        if (industry_mapping is None or industry_mapping.empty) and \
           (sector_mapping is None or sector_mapping.empty):
            logger.warning("Industry and sector mappings not available, filling with -1")
            profiles_df['industry_id'] = -1
            profiles_df['sector_id'] = -1
            return profiles_df

        # Reset index temporarily for merge, keeping ticker as a column
        profiles_df = profiles_df.reset_index()

        # Merge profiles with industry mapping
        if industry_mapping is not None and not industry_mapping.empty:
            profiles_df = profiles_df.merge(
                industry_mapping[['industry', 'industry_id']],
                on='industry',
                how='left'
            )
            # Fill missing industry_ids
            profiles_df['industry_id'] = profiles_df['industry_id'].fillna(-1).astype(int)
        else:
            # No industry mapping available
            logger.warning("Industry mapping not available, filling with -1")
            profiles_df['industry_id'] = -1

        # Merge profiles with sector mapping (stable from FMP API)
        if sector_mapping is not None and not sector_mapping.empty:
            profiles_df = profiles_df.merge(
                sector_mapping[['sector', 'sector_id']],
                on='sector',
                how='left'
            )
            # Fill missing sector_ids
            profiles_df['sector_id'] = profiles_df['sector_id'].fillna(-1).astype(int)
        else:
            # No sector mapping available
            logger.warning("Sector mapping not available, filling with -1")
            profiles_df['sector_id'] = -1

        # Restore ticker as index
        profiles_df = profiles_df.set_index('ticker')

        return profiles_df

    def get_industry_mapping(self, use_cache: bool = True) -> Optional[pd.DataFrame]:
        """
        Get or fetch industry mapping table.

        Args:
            use_cache: If True, use cached mapping if available

        Returns:
            DataFrame with industry_id and industry columns
        """
        # Try cache first
        if use_cache and self.industry_mapping_file.exists():
            try:
                df = pd.read_parquet(self.industry_mapping_file)
                logger.debug("Loaded industry mapping from cache")
                return df
            except Exception as e:
                logger.warning(f"Failed to load industry mapping cache: {e}")

        # Fetch from API
        logger.info("Fetching industry list from FMP API...")
        industries = self._fetch_industry_list()

        if industries is None:
            logger.error("Failed to fetch industry list")
            return None

        # Build mapping
        df = self._build_industry_mapping(industries)

        # Save to cache
        try:
            df.to_parquet(self.industry_mapping_file)
            logger.info(f"Cached {len(df)} industries to {self.industry_mapping_file}")
        except Exception as e:
            logger.warning(f"Failed to cache industry mapping: {e}")

        return df

    def get_sector_mapping(self, use_cache: bool = True) -> Optional[pd.DataFrame]:
        """
        Get or fetch sector mapping table.

        Args:
            use_cache: If True, use cached mapping if available

        Returns:
            DataFrame with sector_id and sector columns
        """
        # Try cache first
        if use_cache and self.sector_mapping_file.exists():
            try:
                df = pd.read_parquet(self.sector_mapping_file)
                logger.debug("Loaded sector mapping from cache")
                return df
            except Exception as e:
                logger.warning(f"Failed to load sector mapping cache: {e}")

        # Fetch from API
        logger.info("Fetching sector list from FMP API...")
        sectors = self._fetch_sector_list()

        if sectors is None:
            logger.error("Failed to fetch sector list")
            return None

        # Build mapping
        df = self._build_sector_mapping(sectors)

        # Save to cache
        try:
            df.to_parquet(self.sector_mapping_file)
            logger.info(f"Cached {len(df)} sectors to {self.sector_mapping_file}")
        except Exception as e:
            logger.warning(f"Failed to cache sector mapping: {e}")

        return df

    def _fetch_single_profile(self, ticker: str) -> Optional[Dict]:
        """
        Fetch and parse a single company profile.

        Args:
            ticker: Stock symbol

        Returns:
            Parsed profile dict or None if failed
        """
        profile_data = self._fetch_company_profile(ticker)
        if profile_data:
            return self._parse_profile_response(profile_data, ticker)
        return None

    def fetch_all_profiles(self, tickers: List[str], show_progress: bool = True, max_workers: int = 10) -> pd.DataFrame:
        """
        Batch fetch company profiles for multiple tickers using parallel processing.

        Args:
            tickers: List of ticker symbols
            show_progress: Display progress bar
            max_workers: Number of parallel workers (default 10 for 300 calls/min rate limit)

        Returns:
            DataFrame with all company profiles (without industry IDs)
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        profiles = []
        success_count = 0
        failed_count = 0
        start_time = time.time()

        total = len(tickers)

        # Use tqdm progress bar if available
        try:
            from tqdm import tqdm
            use_tqdm = show_progress
        except ImportError:
            use_tqdm = False

        # Parallel processing with ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_ticker = {executor.submit(self._fetch_single_profile, ticker): ticker
                               for ticker in tickers}

            # Process completed tasks with progress bar
            if use_tqdm:
                from tqdm import tqdm
                pbar = tqdm(total=total, desc="Fetching profiles", unit="ticker")

            for future in as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                try:
                    result = future.result()
                    if result:
                        profiles.append(result)
                        success_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"Exception fetching {ticker}: {e}")
                    failed_count += 1

                if use_tqdm:
                    pbar.update(1)

            if use_tqdm:
                pbar.close()

        # Final summary
        elapsed = time.time() - start_time
        logger.info(f"Fetched {success_count}/{total} profiles successfully in {elapsed/60:.1f} min "
                   f"({success_count/elapsed:.1f} profiles/sec)")

        # Convert to DataFrame
        if not profiles:
            logger.warning("No profiles fetched")
            return pd.DataFrame()

        df = pd.DataFrame(profiles)
        df = df.set_index('ticker')

        return df

    def get_company_profiles(self, use_cache: bool = True, tickers: List[str] = None) -> pd.DataFrame:
        """
        Get company profiles from cache or API.

        Args:
            use_cache: If True, use cached data when available
            tickers: List of tickers (if None, uses all from cache or price folder)

        Returns:
            DataFrame with company profiles + industry encoding
        """
        # Try cache first
        if use_cache and self.profiles_file.exists() and not self._is_cache_stale(self.profiles_file):
            try:
                df = pd.read_parquet(self.profiles_file)
                logger.debug(f"Loaded {len(df)} company profiles from cache")

                # Filter by tickers if specified
                if tickers:
                    df = df[df.index.isin(tickers)]

                return df
            except Exception as e:
                logger.warning(f"Failed to load profiles cache: {e}")

        # Determine tickers to fetch
        if tickers is None:
            # Get from price folder
            price_files = list(config.PRICE_DATA_DIR.glob('*.parquet'))
            tickers = [f.stem for f in price_files if f.stem != config.BENCHMARK_TICKER]

        if not tickers:
            logger.warning("No tickers to fetch")
            return pd.DataFrame()

        # Fetch from API
        logger.info(f"Fetching profiles for {len(tickers)} tickers...")
        df = self.fetch_all_profiles(tickers, show_progress=True)

        if df.empty:
            return df

        # Merge with industry IDs
        df = self._merge_with_industry_ids(df)

        # Save to cache
        try:
            df.to_parquet(self.profiles_file)
            logger.info(f"Cached {len(df)} profiles to {self.profiles_file}")
        except Exception as e:
            logger.warning(f"Failed to cache profiles: {e}")

        return df

    def update_profiles_cache(self, tickers: List[str] = None, force: bool = False,
                             max_workers: int = 10) -> Dict[str, bool]:
        """
        Update company profiles cache.

        Note: Company profiles (sector, industry, market cap) rarely change.
        Therefore, this method only checks for MISSING tickers, not stale data.
        Use force=True to re-download existing profiles.

        Args:
            tickers: List of tickers to update (None = all from price folder)
            force: If True, refresh all tickers regardless of cache
            max_workers: Number of parallel workers (default 10 for 300 calls/min rate limit)

        Returns:
            Dict mapping ticker -> success status
        """
        # Determine tickers to fetch
        if tickers is None:
            price_files = list(config.PRICE_DATA_DIR.glob('*.parquet'))
            tickers = [f.stem for f in price_files if f.stem != config.BENCHMARK_TICKER]

        # Check if force refresh
        if force:
            logger.info(f"Force refresh enabled, fetching all {len(tickers)} tickers")
            df = self.fetch_all_profiles(tickers, show_progress=True, max_workers=max_workers)
            # Merge with industry IDs
            df = self._merge_with_industry_ids(df)
        else:
            # Load existing cache
            try:
                df = pd.read_parquet(self.profiles_file)
                logger.info(f"Loaded {len(df)} profiles from cache")

                # Identify missing tickers
                missing_tickers = [t for t in tickers if t not in df.index]

                if missing_tickers:
                    logger.info(f"Fetching {len(missing_tickers)} missing tickers")
                    new_df = self.fetch_all_profiles(missing_tickers, show_progress=True, max_workers=max_workers)

                    if not new_df.empty:
                        # Merge new profiles with industry IDs
                        new_df = self._merge_with_industry_ids(new_df)

                        # Ensure old cache has the same columns as new data
                        for col in ['industry_id', 'sector_id']:
                            if col not in df.columns:
                                df[col] = -1

                        # Merge with existing cache
                        df = pd.concat([df, new_df])
                else:
                    logger.info("All tickers already in cache")
                    # Ensure cache has industry_id and sector_id columns
                    for col in ['industry_id', 'sector_id']:
                        if col not in df.columns:
                            df[col] = -1
            except Exception as e:
                logger.warning(f"Failed to load existing cache: {e}, fetching all")
                df = self.fetch_all_profiles(tickers, show_progress=True, max_workers=max_workers)
                # Merge with industry IDs
                df = self._merge_with_industry_ids(df)

        if df.empty:
            return {ticker: False for ticker in tickers}

        # Save to cache
        try:
            df.to_parquet(self.profiles_file)
            logger.info(f"Cached {len(df)} profiles to {self.profiles_file}")
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")
            return {ticker: False for ticker in tickers}

        # Build results
        results = {ticker: (ticker in df.index) for ticker in tickers}
        return results

    def get_ticker_profile(self, ticker: str) -> Optional[pd.Series]:
        """
        Get profile for a single ticker.

        Args:
            ticker: Stock symbol

        Returns:
            Series with profile data, or None if not found
        """
        # Load full profiles
        profiles = self.get_company_profiles(use_cache=True)

        if profiles.empty or ticker not in profiles.index:
            logger.debug(f"Profile not found for {ticker}")
            return None

        return profiles.loc[ticker]

    def fetch_shares_float(self, tickers: List[str], batch_size: int = 200) -> pd.DataFrame:
        """Fetch shares outstanding and float from Yahoo Finance.

        Uses yf.Tickers() for shared session/cookie, processes in batches
        with pauses to avoid rate limiting.

        Args:
            tickers: List of ticker symbols
            batch_size: Tickers per batch (pause between batches)

        Returns:
            DataFrame with columns: ticker, shares_outstanding, float_shares
        """
        import yfinance as yf

        results = []
        total = len(tickers)

        try:
            from tqdm import tqdm
            pbar = tqdm(total=total, desc="Fetching shares float", unit="ticker")
        except ImportError:
            pbar = None

        for batch_start in range(0, total, batch_size):
            batch = tickers[batch_start:batch_start + batch_size]
            batch_str = " ".join(batch)

            try:
                yf_batch = yf.Tickers(batch_str)
                for symbol, ticker_obj in yf_batch.tickers.items():
                    try:
                        info = ticker_obj.info
                        outstanding = info.get("sharesOutstanding")
                        float_val = info.get("floatShares")
                        if outstanding is not None or float_val is not None:
                            results.append({
                                "ticker": symbol,
                                "shares_outstanding": int(outstanding) if outstanding else None,
                                "float_shares": int(float_val) if float_val else None,
                            })
                    except Exception as e:
                        logger.debug(f"yfinance shares failed for {symbol}: {e}")
                    if pbar:
                        pbar.update(1)
            except Exception as e:
                logger.warning(f"yfinance batch failed (offset {batch_start}): {e}")
                if pbar:
                    pbar.update(len(batch))

            # Pause between batches
            if batch_start + batch_size < total:
                time.sleep(2)

        if pbar:
            pbar.close()

        success = len(results)
        logger.info(f"Shares float: {success}/{total} tickers fetched")

        if not results:
            return pd.DataFrame(columns=["ticker", "shares_outstanding", "float_shares"])

        return pd.DataFrame(results)

    def get_cache_info(self) -> Dict:
        """
        Get information about cached company profiles.

        Returns:
            Dict with cache statistics
        """
        if not self.profiles_file.exists():
            return {
                'total_tickers': 0,
                'file_size_kb': 0,
                'last_updated': None,
                'cache_age_days': None,
                'unique_sectors': 0,
                'unique_industries': 0
            }

        try:
            # Load profiles
            df = pd.read_parquet(self.profiles_file)

            # File stats
            file_size = self.profiles_file.stat().st_size / 1024  # KB
            file_mtime = datetime.fromtimestamp(self.profiles_file.stat().st_mtime)
            age_days = (datetime.now() - file_mtime).days

            return {
                'total_tickers': len(df),
                'file_size_kb': file_size,
                'last_updated': file_mtime,
                'cache_age_days': age_days,
                'unique_sectors': df['sector'].nunique(),
                'unique_industries': df['industry'].nunique()
            }
        except Exception as e:
            logger.error(f"Failed to get cache info: {e}")
            return {
                'total_tickers': 0,
                'file_size_kb': 0,
                'last_updated': None,
                'cache_age_days': None,
                'unique_sectors': 0,
                'unique_industries': 0
            }
