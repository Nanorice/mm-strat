"""
Macro Engine - DuckDB Macro Data Fetcher
Fetches and writes macroeconomic data (SPY, QQQ, VIX) to t1_macro table.
"""

import pandas as pd
import numpy as np
import requests
import threading
import time
import logging
import duckdb
from src import db
import yfinance as yf
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, List

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL))
logger = logging.getLogger(__name__)


class MacroEngine:
    """
    Fetches and caches macroeconomic data from FRED and FMP APIs.

    Data sources:
    - FRED: Fed balance sheet (WALCL), TGA (WTREGEN), RRP (RRPONTSYD), HY spread (BAMLH0A0HYM2)
    - FMP: VIX (^VIX)

    Caching:
    - Per-series Parquet files in data/macro/
    - Incremental updates (only fetches new data)
    """

    FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(self, db_path: str = None, fred_api_key: str = None, fmp_api_key: str = None):
        self.db_path = db_path or str(config.DUCKDB_PATH)
        self.fred_api_key = fred_api_key or config.FRED_API_KEY
        self.fmp_api_key = fmp_api_key or config.FMP_API_KEY
        self.macro_dir = config.MACRO_DATA_DIR

        # Rate limiting (FRED: 120/min, FMP: 300/min)
        self._call_timestamps: Dict[str, List[float]] = {'fred': [], 'fmp': []}
        self._rate_limit_lock = threading.Lock()
        self._rate_limits = {'fred': 120, 'fmp': 300}

        # Ensure directory exists
        self.macro_dir.mkdir(parents=True, exist_ok=True)

    def _rate_limit_check(self, api: str = 'fred') -> None:
        """Thread-safe rate limiting for API calls."""
        with self._rate_limit_lock:
            now = time.time()
            window_start = now - 60

            # Clean old timestamps
            self._call_timestamps[api] = [
                t for t in self._call_timestamps[api] if t > window_start
            ]

            limit = self._rate_limits[api]
            if len(self._call_timestamps[api]) >= limit:
                sleep_time = self._call_timestamps[api][0] - window_start + 0.1
                logger.info(f"Rate limit reached for {api}, sleeping {sleep_time:.1f}s")
                time.sleep(sleep_time)

            self._call_timestamps[api].append(now)

    def fetch_fred_series(
        self,
        series_id: str,
        start_date: str = '2003-01-01',
        end_date: str = None,
    ) -> pd.DataFrame:
        """
        Fetch a single FRED series.

        Args:
            series_id: FRED series ID (e.g., 'WALCL', 'WTREGEN')
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (defaults to today)

        Returns:
            DataFrame with 'date' index and value column.

        Note:
            Data is indexed by observation date. Publication lag (T+1 for most
            FRED series) is handled at the consumption layer in M03RegimeCalculator.
        """
        if not self.fred_api_key:
            raise ValueError("FRED_API_KEY not configured. Set it in .env file.")

        self._rate_limit_check('fred')

        end_date = end_date or datetime.now().strftime('%Y-%m-%d')

        params = {
            'series_id': series_id,
            'api_key': self.fred_api_key,
            'file_type': 'json',
            'observation_start': start_date,
            'observation_end': end_date,
        }

        try:
            response = requests.get(self.FRED_BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if 'observations' not in data:
                logger.warning(f"No observations in FRED response for {series_id}")
                return pd.DataFrame()

            observations = data['observations']
            if not observations:
                logger.warning(f"Empty observations for {series_id}")
                return pd.DataFrame()

            df = pd.DataFrame(observations)
            df['observation_date'] = pd.to_datetime(df['date'])
            df['value'] = pd.to_numeric(df['value'], errors='coerce')

            df = df[['observation_date', 'value']].dropna()
            df = df.set_index('observation_date').sort_index()
            df.columns = [series_id]
            logger.info(f"Fetched {len(df)} observations for {series_id}")

            return df

        except requests.exceptions.RequestException as e:
            logger.error(f"FRED API error for {series_id}: {e}")
            return pd.DataFrame()

    def fetch_vix(self, start_date: str = '2003-01-01') -> pd.DataFrame:
        """
        Fetch VIX data from FRED API (VIXCLS series).

        Returns:
            DataFrame with 'date' index and 'VIX' column
        """
        df = self.fetch_fred_series('VIXCLS', start_date)
        if not df.empty:
            df = df.rename(columns={'VIXCLS': 'VIX'})
        return df

    # Shiller moved his data off econ.yale.edu (that mirror froze at 2023-09).
    # Current canonical host is the shillerdata.com CDN blob (through ~2024-09,
    # ~9mo stale by design — publisher cadence, not our fetch). See sprint_13
    # cape_fred_proxy_findings.md. Same workbook layout, so fetch_cape is unchanged.
    CAPE_URL = "https://img1.wsimg.com/blobby/go/e5e77e0b-59d1-44d9-ab25-4763ac982e53/downloads/ie_data.xls"

    def fetch_cape(self, start_date: str = '2003-01-01') -> pd.DataFrame:
        """
        Fetch the Shiller CAPE ratio from Yale's ie_data.xls (monthly).

        The 'Date' column is a year.month fraction (e.g. 2023.09 -> 2023-09-01).
        Returns a DataFrame indexed by observation date with a single 'CAPE'
        column, so it flows through update_series / write_to_macro_data like any
        other series.
        """
        import io as _io

        try:
            r = requests.get(self.CAPE_URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            raw = pd.read_excel(_io.BytesIO(r.content), sheet_name="Data", skiprows=7, engine="xlrd")
        except Exception as e:
            logger.error(f"CAPE fetch failed: {e}")
            return pd.DataFrame()

        df = raw[["Date", "CAPE"]].apply(pd.to_numeric, errors="coerce").dropna()
        if df.empty:
            logger.warning("CAPE: no parseable rows from Yale workbook")
            return pd.DataFrame()

        def _frac_to_date(frac: float) -> pd.Timestamp:
            year = int(frac)
            month = min(max(int(round((frac - year) * 100)), 1), 12)
            return pd.Timestamp(year=year, month=month, day=1)

        df['observation_date'] = df['Date'].map(_frac_to_date)
        df = df[['observation_date', 'CAPE']].set_index('observation_date').sort_index()
        df = df[df.index >= pd.Timestamp(start_date)]
        logger.info(f"Fetched {len(df)} CAPE observations from Yale")
        return df

    def _get_cache_path(self, series_id: str) -> Path:
        """Get cache file path for a series."""
        return self.macro_dir / f"{series_id}.parquet"

    def _load_cache(self, series_id: str) -> Optional[pd.DataFrame]:
        """Load cached data for a series."""
        cache_path = self._get_cache_path(series_id)
        if cache_path.exists():
            try:
                df = pd.read_parquet(cache_path)
                return df
            except Exception as e:
                logger.warning(f"Failed to load cache for {series_id}: {e}")
        return None

    def _save_cache(self, series_id: str, df: pd.DataFrame) -> None:
        """Save data to cache."""
        if df.empty:
            return
        cache_path = self._get_cache_path(series_id)
        df.to_parquet(cache_path)
        logger.debug(f"Saved {len(df)} rows to {cache_path}")

    def update_series(self, series_id: str, force: bool = False) -> pd.DataFrame:
        """
        Update a single series (FRED or VIX) with incremental fetching.

        Args:
            series_id: Series ID ('WALCL', 'WTREGEN', 'RRPONTSYD', 'BAMLH0A0HYM2', 'VIX')
            force: If True, re-download all data

        Returns:
            Updated DataFrame
        """
        cached = self._load_cache(series_id)

        if force or cached is None:
            start_date = '2003-01-01'
        else:
            # Incremental: start from last cached date
            last_date = cached.index.max()
            start_date = (last_date - timedelta(days=7)).strftime('%Y-%m-%d')

        # Fetch new data
        if series_id == 'VIX':
            new_data = self.fetch_vix(start_date)
        elif series_id == 'CAPE':
            new_data = self.fetch_cape(start_date)
        else:
            new_data = self.fetch_fred_series(series_id, start_date)

        if new_data.empty:
            return cached if cached is not None else pd.DataFrame()

        # Merge with existing cache
        if cached is not None and not force:
            combined = pd.concat([cached, new_data])
            combined = combined[~combined.index.duplicated(keep='last')]
            combined = combined.sort_index()
        else:
            combined = new_data

        self._save_cache(series_id, combined)
        return combined

    def update_macro_cache(self, force: bool = False, write_db: bool = True) -> Dict[str, int]:
        """
        Update all macro series (FRED + VIX).

        Args:
            force: If True, re-download all data
            write_db: If True, also write to macro_data DuckDB table

        Returns:
            Dict mapping series_id to row count
        """
        results = {}

        # Update FRED series
        for series_id in config.FRED_SERIES.keys():
            logger.info(f"Updating {series_id}...")
            df = self.update_series(series_id, force=force)
            results[series_id] = len(df)
            if write_db and not df.empty:
                self.write_to_macro_data(series_id, df)

        # Update non-FRED series (VIX from FRED VIXCLS, CAPE from Yale XLS)
        for series_id in ('VIX', 'CAPE'):
            logger.info(f"Updating {series_id}...")
            df = self.update_series(series_id, force=force)
            results[series_id] = len(df)
            if write_db and not df.empty:
                self.write_to_macro_data(series_id, df)

        logger.info(f"Macro cache update complete: {results}")
        return results

    def write_to_macro_data(self, series_id: str, df: pd.DataFrame) -> int:
        """
        Write a single FRED/VIX series into the macro_data table (long format).

        Schema: (date, symbol, close, volume, value, unit) with PK (date, symbol).
        Uses INSERT OR IGNORE for idempotency. Existing rows untouched.

        Args:
            series_id: Series symbol (e.g. 'WALCL', 'DGS10', 'VIX')
            df: DataFrame with DatetimeIndex and one value column

        Returns:
            Number of rows inserted
        """
        if df.empty:
            return 0

        # Normalize: DatetimeIndex + single value column
        value_col = series_id if series_id in df.columns else df.columns[0]
        feed = pd.DataFrame({
            'date': pd.to_datetime(df.index).date,
            'symbol': series_id,
            'close': pd.to_numeric(df[value_col], errors='coerce'),
        }).dropna(subset=['close'])

        if feed.empty:
            return 0

        with db.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS macro_data (
                    date    DATE     NOT NULL,
                    symbol  VARCHAR  NOT NULL,
                    close   DOUBLE,
                    volume  UBIGINT,
                    value   DOUBLE,
                    unit    VARCHAR,
                    PRIMARY KEY (date, symbol)
                )
            """)

            before = conn.execute(
                "SELECT COUNT(*) FROM macro_data WHERE symbol = ?", [series_id]
            ).fetchone()[0]

            conn.register('macro_feed', feed)
            conn.execute("""
                INSERT OR IGNORE INTO macro_data (date, symbol, close)
                SELECT date, symbol, close FROM macro_feed
            """)

            after = conn.execute(
                "SELECT COUNT(*) FROM macro_data WHERE symbol = ?", [series_id]
            ).fetchone()[0]

        inserted = after - before
        logger.info(f"  [macro_data] {series_id}: +{inserted} rows (total {after})")
        return inserted

    def get_series(self, series_id: str, use_cache: bool = True) -> pd.DataFrame:
        """
        Get a series (from cache or API).

        Args:
            series_id: Series ID
            use_cache: If True, load from cache without updating

        Returns:
            DataFrame with series data
        """
        if use_cache:
            cached = self._load_cache(series_id)
            if cached is not None:
                return cached

        return self.update_series(series_id)

    def get_net_liquidity(self, as_of_date: str = None) -> pd.DataFrame:
        """
        Calculate Fed Net Liquidity.

        Formula: Net Liquidity = WALCL - WTREGEN - RRPONTSYD (all converted to billions)

        Units from FRED:
        - WALCL: Millions (e.g., 6,587,568 = $6.58 Trillion)
        - WTREGEN: Millions (e.g., 923,042 = $923 Billion)
        - RRPONTSYD: Billions (e.g., 2160 = $2.16 Trillion, or 9.6 = $9.6 Billion)

        Args:
            as_of_date: Calculate up to this date (default: latest available)

        Returns:
            DataFrame with 'net_liquidity' column (in Billions)

        Note:
            Data is indexed by observation date. Publication lag (T+1) is handled
            at the consumption layer in M03RegimeCalculator.
        """
        # Load all required series
        walcl = self.get_series('WALCL')
        wtregen = self.get_series('WTREGEN')
        rrp = self.get_series('RRPONTSYD')

        if walcl.empty or wtregen.empty or rrp.empty:
            logger.warning("Missing data for net liquidity calculation")
            return pd.DataFrame()

        # Combine into single DataFrame
        df = pd.DataFrame({
            'fed_assets': walcl['WALCL'],
            'tga': wtregen['WTREGEN'],
            'rrp': rrp['RRPONTSYD']
        })

        # Forward-fill weekly data to daily
        df = df.ffill()

        # Convert all to billions for consistency
        # WALCL: millions -> billions (divide by 1000)
        # WTREGEN: millions -> billions (divide by 1000)
        # RRPONTSYD: already in billions
        df['fed_assets_b'] = df['fed_assets'] / 1000
        df['tga_b'] = df['tga'] / 1000
        df['rrp_b'] = df['rrp']

        # Calculate net liquidity (all in billions)
        df['net_liquidity'] = df['fed_assets_b'] - df['tga_b'] - df['rrp_b']

        # Filter to as_of_date if specified
        if as_of_date:
            as_of = pd.to_datetime(as_of_date)
            df = df[df.index <= as_of]

        return df[['net_liquidity', 'fed_assets_b', 'tga_b', 'rrp_b']].rename(
            columns={'fed_assets_b': 'fed_assets', 'tga_b': 'tga', 'rrp_b': 'rrp'}
        ).dropna()

    def get_all_macro_data(self, as_of_date: str = None) -> pd.DataFrame:
        """
        Get all macro data combined into single DataFrame.

        Returns DataFrame with columns:
        - net_liquidity (Billions)
        - fed_assets (Millions)
        - tga (Billions)
        - rrp (Billions)
        - hy_spread (%)
        - vix

        Args:
            as_of_date: Filter up to this date

        Returns:
            Combined DataFrame (daily frequency, forward-filled)

        Note:
            Data is indexed by observation date. Publication lag (T+1) is handled
            at the consumption layer in M03RegimeCalculator.
        """
        # Get net liquidity components
        net_liq = self.get_net_liquidity(as_of_date)

        # Get HY spread
        hy_spread = self.get_series('BAMLH0A0HYM2')
        if not hy_spread.empty:
            hy_spread = hy_spread.rename(columns={'BAMLH0A0HYM2': 'hy_spread'})

        # Get VIX
        vix = self.get_series('VIX')
        if not vix.empty:
            vix = vix.rename(columns={'VIX': 'vix'})

        # Merge all
        df = net_liq.copy()

        if not hy_spread.empty:
            df = df.join(hy_spread, how='outer')

        if not vix.empty:
            df = df.join(vix, how='outer')

        # Forward-fill and filter
        df = df.ffill()

        if as_of_date:
            as_of = pd.to_datetime(as_of_date)
            df = df[df.index <= as_of]

        return df.dropna()

    # ------------------------------------------------------------------
    # DuckDB t1_macro table methods (v2 architecture)
    # ------------------------------------------------------------------

    def fetch_daily_macro(self, start_date: str = '2020-01-01', end_date: str = None) -> pd.DataFrame:
        """
        Fetch daily macro data for t1_macro table.

        Fetches:
        - SPY OHLCV
        - QQQ OHLCV
        - VIX close

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (defaults to yesterday)

        Returns:
            DataFrame with columns matching t1_macro schema
        """
        if end_date is None:
            from src.utils import get_latest_trading_day
            end_date = get_latest_trading_day().strftime('%Y-%m-%d')

        # yfinance end is exclusive — add 1 day to include the end_date
        yf_end = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

        logger.info(f"Fetching macro data from yfinance ({start_date} -> {end_date})")

        # Fetch SPY, QQQ, VIX in parallel
        tickers = ['SPY', 'QQQ', '^VIX']
        try:
            data = yf.download(tickers, start=start_date, end=yf_end, progress=False, threads=True, auto_adjust=True)

            if data.empty:
                logger.warning(f"No data returned from yfinance for {tickers}")
                return pd.DataFrame()

            # Handle MultiIndex columns (when multiple tickers)
            df_list = []
            for ticker in tickers:
                prefix = ticker.replace('^', '').lower()
                if len(tickers) == 1:
                    # Single ticker: columns are ['Open', 'High', 'Low', 'Close', 'Volume']
                    ticker_df = data[['Close']].copy()
                    ticker_df.columns = [f'{prefix}_close']
                else:
                    # Multiple tickers: columns are MultiIndex [('Close', 'SPY'), ('Volume', 'SPY'), ...]
                    ticker_df = pd.DataFrame()
                    if ('Close', ticker) in data.columns:
                        ticker_df[f'{prefix}_close'] = data[('Close', ticker)]
                    if ('High', ticker) in data.columns:
                        ticker_df[f'{prefix}_high'] = data[('High', ticker)]
                    if ('Low', ticker) in data.columns:
                        ticker_df[f'{prefix}_low'] = data[('Low', ticker)]
                    if ('Volume', ticker) in data.columns and prefix != 'vix':
                        ticker_df[f'{prefix}_volume'] = data[('Volume', ticker)].astype('Int64')

                df_list.append(ticker_df)

            # Merge all tickers on date index
            result = pd.concat(df_list, axis=1)
            result.index.name = 'date'
            result = result.reset_index()

            # Ensure date is DATE type (not datetime)
            result['date'] = pd.to_datetime(result['date']).dt.date

            logger.info(f"Fetched {len(result)} macro records")
            return result

        except Exception as e:
            logger.error(f"yfinance fetch failed: {e}")
            return pd.DataFrame()

    def write_to_t1_macro(self, df: pd.DataFrame) -> int:
        """
        Write macro data to t1_macro table (INSERT OR IGNORE for idempotency).

        Args:
            df: DataFrame with columns matching t1_macro schema

        Returns:
            Number of rows inserted
        """
        if df.empty:
            logger.warning("Empty DataFrame, nothing to write")
            return 0

        con = db.connect(self.db_path)
        try:
            # Ensure table exists
            con.execute("""
                CREATE TABLE IF NOT EXISTS t1_macro (
                    date DATE PRIMARY KEY,
                    spy_close DOUBLE,
                    spy_volume UBIGINT,
                    spy_high DOUBLE,
                    spy_low DOUBLE,
                    qqq_close DOUBLE,
                    qqq_volume UBIGINT,
                    qqq_high DOUBLE,
                    qqq_low DOUBLE,
                    vix_close DOUBLE,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Register DataFrame
            con.register('macro_feed', df)

            # Count before
            before = con.execute("SELECT COUNT(*) FROM t1_macro").fetchone()[0]

            # Insert (skip duplicates)
            con.execute("""
                INSERT OR IGNORE INTO t1_macro (
                    date, spy_close, spy_high, spy_low, spy_volume,
                    qqq_close, qqq_high, qqq_low, qqq_volume,
                    vix_close
                )
                SELECT
                    date, spy_close, spy_high, spy_low, spy_volume,
                    qqq_close, qqq_high, qqq_low, qqq_volume,
                    vix_close
                FROM macro_feed
            """)

            # Count after
            after = con.execute("SELECT COUNT(*) FROM t1_macro").fetchone()[0]
            inserted = after - before

            logger.info(f"Inserted {inserted} new rows into t1_macro (total: {after})")
            return inserted

        finally:
            con.close()

    def ingest_daily_macro(self, start_date: str = None, force: bool = False) -> int:
        """
        Ingest macro data into t1_macro table (idempotent).

        Args:
            start_date: Start date (defaults to last date in table + 1 day)
            force: If True, re-ingest from 2020-01-01

        Returns:
            Number of rows inserted
        """
        con = db.connect(self.db_path)
        try:
            # Determine start_date
            if force or start_date:
                fetch_start = start_date or '2020-01-01'
            else:
                # Incremental: start from last date in table
                con.execute("CREATE TABLE IF NOT EXISTS t1_macro (date DATE PRIMARY KEY)")
                max_date_result = con.execute("SELECT MAX(date) FROM t1_macro").fetchone()
                if max_date_result[0]:
                    last_date = pd.to_datetime(max_date_result[0])
                    fetch_start = (last_date + timedelta(days=1)).strftime('%Y-%m-%d')
                else:
                    fetch_start = '2020-01-01'

            # Fetch and write
            df = self.fetch_daily_macro(start_date=fetch_start)
            if df.empty:
                logger.info("No new macro data to ingest")
                return 0

            return self.write_to_t1_macro(df)

        finally:
            con.close()
