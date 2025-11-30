"""
Data Engine - DataRepository Class
Handles universe management, data downloading, and Parquet caching.
"""

import pandas as pd
import numpy as np
import yfinance as yf
import requests
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Dict
import logging

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config

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

    def update_universe(self) -> List[str]:
        """
        Fetches the current S&P 500 ticker list from SSGA.

        Returns:
            List of clean ticker symbols
        """
        logger.info("Fetching S&P 500 universe from SSGA...")

        try:
            df = pd.read_excel(config.SSGA_URL, engine='openpyxl', skiprows=4)
            tickers = df['Ticker'].dropna().tolist()

            # Clean tickers (remove cash, fix formatting)
            clean_tickers = []
            for t in tickers:
                t = str(t).strip()
                if len(t) > 0 and t != 'CASH_USD' and len(t) <= 5:
                    clean_tickers.append(t.replace('.', '-'))

            unique_tickers = list(set(clean_tickers))
            logger.info(f"Successfully loaded {len(unique_tickers)} unique tickers")
            return unique_tickers

        except Exception as e:
            logger.warning(f"Failed to fetch SSGA data: {e}")
            
            # Fallback 1: Scan data/price folder for existing tickers
            logger.info("Attempting to scan data/price folder for tickers...")
            try:
                price_files = list(self.price_dir.glob('*.parquet'))
                if price_files:
                    tickers_from_files = [f.stem for f in price_files]
                    # Filter out benchmark if present
                    tickers_from_files = [t for t in tickers_from_files if t != self.benchmark_ticker]
                    logger.info(f"Found {len(tickers_from_files)} tickers from price folder")
                    return tickers_from_files
            except Exception as scan_error:
                logger.warning(f"Failed to scan price folder: {scan_error}")
            
            # Fallback 2: Use hardcoded tech-heavy subset
            logger.warning("Using hardcoded fallback ticker list")
            return ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'TSLA',
                    'AMD', 'PLTR', 'SMCI', 'JPM', 'V', 'MA', 'LLY', 'AVGO']

    def _is_cache_stale(self, file_path: Path) -> bool:
        """Check if cached Parquet file is older than cache_days."""
        if not file_path.exists():
            return True

        file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
        age_days = (datetime.now() - file_mtime).days
        return age_days >= self.cache_days

    def _fetch_fmp_historical(self, tickers: List[str]) -> Dict[str, any]:
        """
        Batch fetch historical OHLCV data from FMP API.
        
        Args:
            tickers: List of ticker symbols (up to 100)
            
        Returns:
            Dict mapping ticker -> historical data (JSON response)
        """
        if not config.FMP_API_KEY:
            raise ValueError("FMP_API_KEY not set in environment")
        
        # FMP accepts comma-separated tickers
        tickers_str = ','.join(tickers[:100])  # Limit to 100 per API docs
        
        url = f"{config.FMP_BASE_URL}/historical-price-full/{tickers_str}"
        params = {'apikey': config.FMP_API_KEY}
        
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # FMP returns different structure for single vs multiple tickers
            if isinstance(data, dict) and 'historical' in data:
                # Single ticker response
                ticker = tickers[0]
                return {ticker: data}
            elif isinstance(data, list):
                # Multiple tickers response - each is a dict with 'symbol' and 'historical'
                return {item['symbol']: item for item in data if 'symbol' in item}
            else:
                logger.warning(f"Unexpected FMP response format: {type(data)}")
                return {}
                
        except requests.exceptions.RequestException as e:
            logger.error(f"FMP API request failed: {e}")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse FMP response: {e}")
            return {}
    
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
            if 'historical' not in response_data:
                return None
            
            historical = response_data['historical']
            if not historical:
                return None
            
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
            logger.warning(f"Failed to parse FMP data for {ticker}: {e}")
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

    def get_ticker_data(self, ticker: str, use_cache: bool = True, source: str = 'yfinance') -> Optional[pd.DataFrame]:
        """
        Returns OHLCV data for a single ticker.
        First checks Parquet cache, then downloads if needed.

        Args:
            ticker: Stock symbol
            use_cache: If True, uses cached data when available
            source: Data source - 'yfinance' (default) or 'fmp'

        Returns:
            DataFrame with OHLCV data (adjusted), or None if failed
        """
        cache_file = self.price_dir / f"{ticker}.parquet"

        # Try cache first
        if use_cache and cache_file.exists() and not self._is_cache_stale(cache_file):
            try:
                df = pd.read_parquet(cache_file)
                logger.debug(f"Loaded {ticker} from cache")
                return df
            except Exception as e:
                logger.warning(f"Cache read failed for {ticker}: {e}")

        # Download fresh data with source selection and fallback
        if source == 'fmp' and config.FMP_API_KEY:
            try:
                logger.debug(f"Downloading {ticker} from FMP...")
                data = self._get_ticker_data_fmp(ticker)
                if data is not None:
                    # Save to cache
                    data.to_parquet(cache_file)
                    logger.debug(f"Cached {ticker} to {cache_file}")
                    return data
                else:
                    logger.warning(f"FMP returned no data for {ticker}, falling back to yfinance")
            except Exception as e:
                logger.warning(f"FMP failed for {ticker}: {e}, falling back to yfinance")
        
        # Use yfinance (either explicitly requested or as fallback)
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
            # Fetch from FMP
            fmp_data = self._fetch_fmp_historical([ticker])
            
            if ticker not in fmp_data:
                return None
            
            # Parse response
            df = self._parse_fmp_response(fmp_data[ticker], ticker)
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
                period=config.LOOKBACK_PERIOD,
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

    def update_cache(self, tickers: List[str], force: bool = False, source: str = 'yfinance') -> Dict[str, bool]:
        """
        Smart batch update of Parquet cache.
        Only downloads tickers that are missing or stale.

        Args:
            tickers: List of ticker symbols to update
            force: If True, re-downloads all tickers regardless of cache
            source: Data source - 'yfinance' (default) or 'fmp'

        Returns:
            Dict mapping ticker -> success status
        """
        results = {}
        to_download = []

        # Determine which tickers need updating
        for ticker in tickers:
            cache_file = self.price_dir / f"{ticker}.parquet"
            if force or self._is_cache_stale(cache_file):
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
                logger.error(f"FMP batch update failed: {e}, falling back to yfinance")
        
        # Use yfinance batch download (fallback or explicit)
        logger.info(f"Using yfinance for batch update...")
        yf_results = self._update_cache_yfinance(to_download)
        results.update(yf_results)
        
        success_count = sum(yf_results.values())
        logger.info(f"Cache update complete: {success_count}/{len(to_download)} successful")
        return results
    
    def _update_cache_fmp(self, tickers: List[str]) -> Dict[str, bool]:
        """
        Update cache using FMP API batch requests.
        
        Args:
            tickers: List of ticker symbols
            
        Returns:
            Dict mapping ticker -> success status
        """
        results = {}
        batch_size = config.FMP_BATCH_SIZE
        
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(tickers) - 1) // batch_size + 1
            logger.info(f"Processing FMP batch {batch_num}/{total_batches} ({len(batch)} tickers)")
            
            try:
                # Fetch batch from FMP
                fmp_data = self._fetch_fmp_historical(batch)
                
                # Save each ticker
                for ticker in batch:
                    try:
                        if ticker in fmp_data:
                            df = self._parse_fmp_response(fmp_data[ticker], ticker)
                            if df is not None and not df.empty:
                                cache_file = self.price_dir / f"{ticker}.parquet"
                                df.to_parquet(cache_file)
                                results[ticker] = True
                            else:
                                logger.debug(f"No data parsed for {ticker}")
                                results[ticker] = False
                        else:
                            logger.debug(f"{ticker} not in FMP response")
                            results[ticker] = False
                    except Exception as e:
                        logger.debug(f"Failed to cache {ticker}: {e}")
                        results[ticker] = False
                        
            except Exception as e:
                logger.error(f"FMP batch {batch_num} failed: {e}")
                for ticker in batch:
                    results[ticker] = False
        
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
                # Batch download
                data = yf.download(
                    batch,
                    period=config.LOOKBACK_PERIOD,
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

    def get_batch_data(self, tickers: List[str]) -> Dict[str, pd.DataFrame]:
        """
        Loads multiple tickers from cache efficiently.

        Args:
            tickers: List of ticker symbols

        Returns:
            Dict mapping ticker -> DataFrame
        """
        data = {}
        for ticker in tickers:
            df = self.get_ticker_data(ticker, use_cache=True)
            if df is not None:
                data[ticker] = df
        return data
