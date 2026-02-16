"""
DuckDB Data Curator - Buffered Fetch + Batch Write Architecture
==================================================================
Phase 2 implementation of data curator with DuckDB-native operations.

Key improvements over file-based curator:
1. Buffered fetch: API calls made once, buffered in memory
2. Batch write: Single transaction to DuckDB (no file I/O overhead)
3. SQL-native features: Window functions for lightweight + heavyweight features
4. Dual-mode support: Write to parquet + DuckDB (validation) or DuckDB only (production)
5. Prioritized queue: Market cap-based fetching for rate-limited APIs

Usage:
    # Validation period (write to both parquet + DuckDB)
    python data_curator_duckdb.py --update-all --dual-mode

    # Production (DuckDB only)
    python data_curator_duckdb.py --update-all

    # Rate-limited API (fetch top 25 by market cap)
    python data_curator_duckdb.py --update-fundamentals --daily-limit 25
"""

import argparse
import concurrent.futures
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import pandas as pd
import numpy as np
import duckdb

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.data_engine import DataRepository
from src.utils import get_latest_trading_day
from src.fundamental_engine import FundamentalEngine
from src.company_profile_engine import CompanyProfileEngine
from src.macro_engine import MacroEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("data_curator_duckdb.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("DuckDBDataCurator")

# Database path
DB_PATH = Path(__file__).parent / "data" / "market_data.duckdb"


class DataAcquisitionQueue:
    """
    Manages prioritized fetching for rate-limited APIs.
    Tickers are ranked by market cap and staleness.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = str(db_path)

    def build_fetch_queue(self, tickers: List[str], data_type: str = 'fundamentals') -> pd.DataFrame:
        """
        Build prioritized queue for fetching.

        Priority tiers:
        1. Never fetched (no data) - HIGHEST priority
        2. Stale (>90 days old) - sorted by market cap descending
        3. Fresh (<90 days old) - LOWEST priority

        Args:
            tickers: List of tickers to evaluate
            data_type: Type of data to check ('fundamentals', 'profiles', etc.)

        Returns:
            DataFrame with columns: ticker, priority_rank, priority_tier, market_cap, last_update
        """
        con = duckdb.connect(self.db_path)

        try:
            if data_type == 'fundamentals':
                query = f"""
                    WITH ticker_list AS (
                        SELECT UNNEST([{','.join([f"'{t}'" for t in tickers])}]) as ticker
                    ),
                    ticker_status AS (
                        SELECT
                            tl.ticker,
                            MAX(f.report_date) as last_update,
                            cp.mktCap as market_cap
                        FROM ticker_list tl
                        LEFT JOIN fundamentals f ON tl.ticker = f.ticker
                        LEFT JOIN company_profiles cp ON tl.ticker = cp.ticker
                        GROUP BY tl.ticker, cp.mktCap
                    )
                    SELECT
                        ticker,
                        market_cap,
                        last_update,
                        CASE
                            WHEN last_update IS NULL THEN 1  -- Never fetched
                            WHEN DATEDIFF('day', last_update, CURRENT_DATE) > 90 THEN 2  -- Stale
                            ELSE 3  -- Fresh
                        END as priority_tier
                    FROM ticker_status
                    ORDER BY
                        priority_tier ASC,           -- Never fetched first
                        market_cap DESC NULLS LAST   -- Then by market cap
                """
            else:
                # For profiles/other data types, check existence only
                query = f"""
                    WITH ticker_list AS (
                        SELECT UNNEST([{','.join([f"'{t}'" for t in tickers])}]) as ticker
                    ),
                    ticker_status AS (
                        SELECT
                            tl.ticker,
                            cp.mktCap as market_cap,
                            CASE WHEN cp.ticker IS NULL THEN NULL ELSE CURRENT_DATE END as last_update
                        FROM ticker_list tl
                        LEFT JOIN company_profiles cp ON tl.ticker = cp.ticker
                    )
                    SELECT
                        ticker,
                        market_cap,
                        last_update,
                        CASE
                            WHEN last_update IS NULL THEN 1  -- Never fetched
                            ELSE 3  -- Exists
                        END as priority_tier
                    FROM ticker_status
                    ORDER BY priority_tier ASC, market_cap DESC NULLS LAST
                """

            queue_df = con.execute(query).df()

        finally:
            con.close()

        # Add priority rank (1 = highest priority)
        queue_df['priority_rank'] = range(1, len(queue_df) + 1)

        return queue_df

    def fetch_daily_batch(self, queue_df: pd.DataFrame, daily_limit: int = 25) -> List[str]:
        """
        Get next batch of tickers to fetch (respecting daily limit).

        Args:
            queue_df: Prioritized queue from build_fetch_queue()
            daily_limit: Max API calls per day

        Returns:
            List of tickers to fetch
        """
        batch = queue_df.nsmallest(daily_limit, 'priority_rank')
        return batch['ticker'].tolist()


class DuckDBDataCurator:
    """
    DuckDB-native data curator with buffered fetch and batch write.
    """

    def __init__(self, dual_mode: bool = False):
        """
        Initialize curator.

        Args:
            dual_mode: If True, write to both parquet + DuckDB (validation period)
                      If False, write to DuckDB only (production)
        """
        self.dual_mode = dual_mode
        self.db_path = str(DB_PATH)

        # Reuse existing engines for API logic (rate limiting, retries, earnings calendar)
        self.data_repo = DataRepository()
        self.fund_engine = FundamentalEngine()
        self.profile_engine = CompanyProfileEngine()
        self.macro_engine = MacroEngine()

        # Queue manager for rate-limited APIs
        self.queue_manager = DataAcquisitionQueue(DB_PATH)

        logger.info(f"Initialized DuckDBDataCurator (dual_mode={dual_mode})")

    def run_update(
        self,
        tickers: List[str],
        update_prices: bool = False,
        update_fundamentals: bool = False,
        update_profiles: bool = False,
        update_macro: bool = False,
        update_features_only: bool = False,
        recompute: bool = False,
        force: bool = False,
        daily_limit: Optional[int] = None,
        start_date: str = '2020-01-01'
    ):
        """
        Main orchestrator - fetch once, write to destinations.

        Args:
            tickers: List of ticker symbols
            update_prices: Whether to update price data
            update_fundamentals: Whether to update fundamentals
            update_profiles: Whether to update company profiles
            update_macro: Whether to update macro data
            update_features_only: If True, skip all fetching and only recompute features
            recompute: If True, force full feature rebuild (ignore last_update)
            force: Force re-download even if cache is fresh
            daily_limit: Max API calls for rate-limited endpoints (fundamentals)
            start_date: Start date for feature computation
        """
        start_time = time.time()

        print("\n" + "=" * 80)
        print("📊 DuckDB Data Curator - Daily Update")
        print("=" * 80)
        print(f"   Mode: {'DUAL (parquet + DuckDB)' if self.dual_mode else 'PRODUCTION (DuckDB only)'}")
        print(f"   Tickers: {len(tickers)}")
        print(f"   Force: {force}")

        # Determine updates
        updates = []
        if update_prices:
            updates.append("prices")
        if update_fundamentals:
            updates.append("fundamentals")
        if update_profiles:
            updates.append("profiles")
        if update_macro:
            updates.append("macro")

        print(f"   Updates: {', '.join(updates) if updates else 'none'}")

        # ============================================================
        # PHASE 1: FETCH (buffer in memory)
        # ============================================================
        price_buffer = pd.DataFrame()
        fundamentals_buffer = pd.DataFrame()
        profiles_buffer = pd.DataFrame()
        macro_buffer = pd.DataFrame()

        if update_features_only:
            print("\n[1/3] Skipping API fetch (--update-features only)")
            print("[2/3] Skipping storage write (--update-features only)")
        else:
            print("\n[1/3] Fetching from APIs...")

            if update_prices:
                price_buffer = self._fetch_prices(tickers, force=force)

            if update_fundamentals:
                if daily_limit is not None:
                    # Use prioritized queue for rate-limited APIs
                    fundamentals_buffer = self._fetch_fundamentals_queued(tickers, daily_limit=daily_limit)
                else:
                    # Full fetch (no rate limit)
                    fundamentals_buffer = self._fetch_fundamentals(tickers, force=force)

            if update_profiles:
                profiles_buffer = self._fetch_profiles(tickers, force=force)

            if update_macro:
                macro_buffer = self._fetch_macro_data(force=force)

            # ============================================================
            # PHASE 2: WRITE (batch to destinations)
            # ============================================================
            print("\n[2/3] Writing to storage...")

            if self.dual_mode:
                # Validation: Write to both (already written by existing engines during fetch)
                print("   [DUAL MODE] Parquet files already written by existing engines")
                print("   [DUAL MODE] Writing to DuckDB...")
                self._write_to_duckdb(price_buffer, fundamentals_buffer, profiles_buffer, macro_buffer)
            else:
                # Production: DuckDB only (parquet written by engines if needed for compatibility)
                print("   [PRODUCTION] Writing to DuckDB...")
                self._write_to_duckdb(price_buffer, fundamentals_buffer, profiles_buffer, macro_buffer)

        # ============================================================
        # PHASE 3: COMPUTE DAILY FEATURES (SQL-native technical indicators)
        # ============================================================
        should_compute = update_prices or update_features_only
        if should_compute:
            mode_label = "FULL RECOMPUTE" if recompute else "incremental"
            print(f"\n[3/5] Computing daily features ({mode_label}, start={start_date})...")
            self._compute_features_incremental(force_full=recompute, start_date=start_date)
        else:
            print("\n[3/5] Skipping daily feature computation (no price update or --update-features)")

        # ============================================================
        # PHASE 4: COMPUTE FUNDAMENTAL FEATURES (derived fundamental metrics)
        # ============================================================
        should_compute_fundamentals = update_fundamentals or update_features_only
        if should_compute_fundamentals:
            print(f"\n[4/5] Computing fundamental features...")
            self._compute_fundamental_features(tickers=tickers)
        else:
            print("\n[4/5] Skipping fundamental feature computation (no fundamental update)")

        # ============================================================
        # PHASE 5: CREATE/REFRESH VIEWS
        # ============================================================
        print(f"\n[5/5] Refreshing views...")
        self._create_views()

        elapsed = time.time() - start_time
        print("\n" + "=" * 80)
        print(f"Update Complete in {elapsed / 60:.1f} minutes")
        print("=" * 80 + "\n")

    def _get_last_dates_from_duckdb(self, tickers: List[str]) -> Dict[str, str]:
        """Query DuckDB for the last price date per ticker. Returns {ticker: 'YYYY-MM-DD'}."""
        con = duckdb.connect(self.db_path)
        try:
            ticker_sql = ','.join([f"'{t}'" for t in tickers])
            rows = con.execute(f"""
                SELECT ticker, MAX(date) as last_date
                FROM price_data
                WHERE ticker IN ({ticker_sql})
                GROUP BY ticker
            """).fetchall()
            return {row[0]: row[1].strftime('%Y-%m-%d') if row[1] else None for row in rows}
        finally:
            con.close()

    def _fetch_price_worker_direct(self, ticker: str, from_date: str) -> Tuple[str, Optional[pd.DataFrame]]:
        """
        Fetch incremental price data for one ticker directly from FMP API.
        Returns (ticker, df_of_new_rows_only) or (ticker, None) on failure.
        Reuses DataRepository's rate limiting, retry logic, and response parsing.
        """
        try:
            fmp_data = self.data_repo._fetch_fmp_historical(
                ticker, from_date=from_date, force_from_date=True
            )
            if not fmp_data or fmp_data.get('already_current', False):
                return (ticker, None)

            df = self.data_repo._parse_fmp_response(fmp_data, ticker)
            if df is None or df.empty:
                return (ticker, None)

            # Normalize: parse_fmp_response returns PascalCase with Date index
            df_reset = df.reset_index()
            df_reset['ticker'] = ticker
            df_reset.columns = [c.lower() for c in df_reset.columns]
            return (ticker, df_reset[['ticker', 'date', 'open', 'high', 'low', 'close', 'volume']])
        except Exception as e:
            logger.warning(f"Direct fetch failed for {ticker}: {e}")
            return (ticker, None)

    def _fetch_prices(self, tickers: List[str], force: bool = False) -> pd.DataFrame:
        """
        Fetch price data from FMP API, buffer ONLY new rows in memory.
        Uses DuckDB for staleness check — no parquet round-trip.
        In dual_mode, falls back to the parquet-based path for compatibility.

        Returns:
            DataFrame with columns: ticker, date, open, high, low, close, volume
        """
        print("   📈 [FETCH] Price data...")

        # Ensure SPY is included
        if self.data_repo.benchmark_ticker and self.data_repo.benchmark_ticker not in tickers:
            tickers = list(tickers) + [self.data_repo.benchmark_ticker]

        if self.dual_mode:
            return self._fetch_prices_legacy(tickers, force=force)

        # --- Direct path: DuckDB staleness → API → buffer new rows only ---
        from src.data_engine import DEFAULT_HISTORICAL_START_DATE

        market_date = get_latest_trading_day()
        last_dates = self._get_last_dates_from_duckdb(tickers)

        # Build work list: (ticker, from_date) — skip tickers already current
        work = []
        skipped = 0
        for t in tickers:
            last = last_dates.get(t)
            if force or last is None:
                work.append((t, DEFAULT_HISTORICAL_START_DATE))
            elif last < market_date.strftime('%Y-%m-%d'):
                next_day = (pd.to_datetime(last) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                work.append((t, next_day))
            else:
                skipped += 1

        if skipped:
            print(f"   ℹ️  {skipped} tickers already current, fetching {len(work)}")

        if not work:
            print(f"   ✅ All {len(tickers)} tickers up to date")
            return pd.DataFrame()

        # Parallel fetch — only new rows returned per ticker
        buffer = []
        success_count = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(self._fetch_price_worker_direct, t, fd): t
                for t, fd in work
            }
            for future in concurrent.futures.as_completed(futures):
                ticker, df = future.result()
                if df is not None and len(df) > 0:
                    buffer.append(df)
                    success_count += 1

        if buffer:
            price_df = pd.concat(buffer, ignore_index=True)
            print(f"   ✅ Fetched {len(price_df):,} new price records for {success_count} tickers")
            return price_df

        print(f"   ⚠️  No new price data fetched")
        return pd.DataFrame()

    def _fetch_prices_legacy(self, tickers: List[str], force: bool = False) -> pd.DataFrame:
        """Legacy parquet-based fetch for dual_mode compatibility."""
        results = self.data_repo.update_cache(tickers, force=force, max_workers=5)
        buffer = []
        for ticker in tickers:
            if results.get(ticker):
                try:
                    df = self.data_repo.get_ticker_data(ticker, use_cache=True)
                    if df is not None and len(df) > 0:
                        df_reset = df.reset_index()
                        df_reset['ticker'] = ticker
                        df_reset.columns = [c.lower() for c in df_reset.columns]
                        buffer.append(df_reset[['ticker', 'date', 'open', 'high', 'low', 'close', 'volume']])
                except Exception as e:
                    logger.warning(f"Failed to load price data for {ticker}: {e}")
        if buffer:
            price_df = pd.concat(buffer, ignore_index=True)
            print(f"   ✅ Fetched {len(price_df):,} price records (legacy) for {len(buffer)} tickers")
            return price_df
        print(f"   ⚠️  No price data fetched")
        return pd.DataFrame()

    def _fetch_fundamentals(self, tickers: List[str], force: bool = False) -> pd.DataFrame:
        """
        Fetch fundamental data from FMP API, buffer in memory.
        Uses earnings calendar intelligence to reduce API calls by 90-95%.

        Returns:
            DataFrame with normalized fundamental data
        """
        print("   📊 [FETCH] Fundamental data (using earnings calendar)...")

        # Reuse FundamentalEngine (handles earnings calendar, API retries)
        results = self.fund_engine.update_fundamentals_cache(
            tickers=tickers,
            force=force,
            max_workers=10,
            use_earnings_calendar=not force  # Disable calendar if force=True
        )

        # Collect fundamentals into buffer
        buffer = []
        success_count = 0

        for ticker in tickers:
            if results.get(ticker):
                try:
                    df = self.fund_engine.get_ticker_fundamentals(ticker, use_cache=True)
                    if df is not None and len(df) > 0:
                        buffer.append(df)
                        success_count += 1
                except Exception as e:
                    logger.warning(f"Failed to load fundamentals for {ticker}: {e}")

        if buffer:
            fund_df = pd.concat(buffer, ignore_index=True)

            # Normalize to match DuckDB schema
            # Map: fiscal_date → report_date, fiscal_period → period_type
            fund_df = fund_df.rename(columns={
                'fiscal_date': 'report_date',
                'fiscal_period': 'period_type',
                'fiscalYear': 'fiscal_year',
                'netIncome': 'net_income',
                'epsDiluted': 'eps_diluted',
                'totalAssets': 'total_assets',
                'totalEquity': 'total_equity',
                'operatingCashFlow': 'operating_cash_flow'
            })

            # Select only columns that exist in DuckDB table
            duckdb_columns = ['ticker', 'report_date', 'filing_date', 'period_type', 'fiscal_year',
                             'revenue', 'net_income', 'eps_diluted', 'total_assets', 'total_equity',
                             'operating_cash_flow']

            # Keep only columns that exist in both
            available_cols = [c for c in duckdb_columns if c in fund_df.columns]
            fund_df = fund_df[available_cols]

            print(f"   ✅ Fetched {len(fund_df):,} fundamental records for {success_count} tickers")
            return fund_df
        else:
            print(f"   ⚠️  No fundamental data fetched")
            return pd.DataFrame()

    def _fetch_fundamentals_queued(self, tickers: List[str], daily_limit: int = 25) -> pd.DataFrame:
        """
        Fetch fundamentals using prioritized queue (for rate-limited APIs).

        Args:
            tickers: Full universe
            daily_limit: Max API calls per day (e.g., 25 for Alpha Vantage free tier)

        Returns:
            DataFrame with fundamental data for today's batch
        """
        print(f"   📊 [FETCH] Fundamental data (prioritized queue, limit={daily_limit})...")

        # Build queue
        queue_df = self.queue_manager.build_fetch_queue(tickers, data_type='fundamentals')

        # Get today's batch
        today_batch = self.queue_manager.fetch_daily_batch(queue_df, daily_limit=daily_limit)

        print(f"   📋 Queue status:")
        print(f"      Total universe: {len(tickers)} tickers")
        print(f"      Fetching today: {len(today_batch)} tickers")
        print(f"      Never fetched: {len(queue_df[queue_df['priority_tier'] == 1])}")
        print(f"      Stale (>90 days): {len(queue_df[queue_df['priority_tier'] == 2])}")
        print(f"      Fresh (<90 days): {len(queue_df[queue_df['priority_tier'] == 3])}")

        # Fetch only today's batch
        return self._fetch_fundamentals(today_batch, force=False)

    def _fetch_profiles(self, tickers: List[str], force: bool = False) -> pd.DataFrame:
        """
        Fetch company profile data, buffer in memory.

        Returns:
            DataFrame with company profiles
        """
        print("   🏢 [FETCH] Company profiles...")

        # Reuse CompanyProfileEngine
        results = self.profile_engine.update_profiles_cache(
            tickers=tickers,
            force=force,
            max_workers=10
        )

        # Get cached profiles
        try:
            profiles_df = self.profile_engine.get_company_profiles(use_cache=True)
            if not profiles_df.empty:
                # Filter to requested tickers
                profiles_df = profiles_df[profiles_df['ticker'].isin(tickers)]
                print(f"   ✅ Fetched {len(profiles_df)} company profiles")
                return profiles_df
            else:
                print(f"   ⚠️  No company profiles fetched")
                return pd.DataFrame()
        except Exception as e:
            logger.warning(f"Failed to load company profiles: {e}")
            return pd.DataFrame()

    def _fetch_macro_data(self, force: bool = False) -> pd.DataFrame:
        """
        Fetch macroeconomic data (FRED + VIX), buffer in memory.

        Smart caching: Only updates if cache is >1 day old (macro data updates weekly/monthly).

        Returns:
            DataFrame with macro observations
        """
        print("   📉 [FETCH] Macro data (FRED + VIX)...")

        # Check cache staleness (macro data doesn't need daily updates)
        if not force:
            cache_fresh = self._is_macro_cache_fresh()
            if cache_fresh:
                print("   ℹ️  Macro cache is fresh (<24h old), using cached data...")
                try:
                    macro_df = self.macro_engine.get_macro_data()
                    if macro_df is not None and not macro_df.empty:
                        print(f"   ✅ Loaded {len(macro_df):,} cached macro observations")
                        return macro_df
                except Exception as e:
                    logger.warning(f"Failed to load cached macro data: {e}")

        # Update macro cache (API calls)
        results = self.macro_engine.update_macro_cache(force=force)

        # Collect macro data
        try:
            macro_df = self.macro_engine.get_macro_data()
            if macro_df is not None and not macro_df.empty:
                print(f"   ✅ Fetched {len(macro_df):,} macro observations ({len(results)} series)")
                return macro_df
            else:
                print(f"   ⚠️  No macro data fetched")
                return pd.DataFrame()
        except Exception as e:
            logger.warning(f"Failed to load macro data: {e}")
            return pd.DataFrame()

    def _is_macro_cache_fresh(self, max_age_hours: int = 24) -> bool:
        """
        Check if macro cache files are fresh enough to skip API calls.

        Args:
            max_age_hours: Max cache age in hours (default 24h)

        Returns:
            True if ALL macro series caches are fresh
        """
        from datetime import datetime, timedelta

        macro_dir = config.MACRO_DATA_DIR
        if not macro_dir.exists():
            return False

        # Check all expected macro series
        series_ids = list(config.FRED_SERIES.keys()) + ['VIX']
        threshold = datetime.now() - timedelta(hours=max_age_hours)

        for series_id in series_ids:
            cache_file = macro_dir / f"{series_id}.parquet"
            if not cache_file.exists():
                return False

            file_mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if file_mtime < threshold:
                return False

        return True

    def _write_to_duckdb(
        self,
        price_buffer: pd.DataFrame,
        fundamentals_buffer: pd.DataFrame,
        profiles_buffer: pd.DataFrame,
        macro_buffer: pd.DataFrame
    ):
        """
        Batch write all buffers to DuckDB in a single transaction.
        Uses INSERT ... ON CONFLICT to handle duplicates.
        """
        con = duckdb.connect(self.db_path)

        try:
            con.execute("BEGIN TRANSACTION")

            # 1. Price data
            if not price_buffer.empty:
                row_count = len(price_buffer)
                con.execute("""
                    INSERT INTO price_data (ticker, date, open, high, low, close, volume)
                    SELECT ticker, date, open, high, low, close, volume
                    FROM price_buffer
                    ON CONFLICT (ticker, date) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                """)
                print(f"   ✅ Wrote {row_count:,} price records to DuckDB")

            # 2. Fundamentals
            if not fundamentals_buffer.empty:
                row_count = len(fundamentals_buffer)
                # Build column list dynamically
                cols = fundamentals_buffer.columns.tolist()
                col_str = ', '.join(cols)
                update_str = ', '.join([f"{c} = EXCLUDED.{c}" for c in cols if c not in ['ticker', 'report_date', 'period_type']])

                con.execute(f"""
                    INSERT INTO fundamentals ({col_str})
                    SELECT {col_str}
                    FROM fundamentals_buffer
                    ON CONFLICT (ticker, report_date, period_type) DO UPDATE SET
                        {update_str}
                """)
                print(f"   ✅ Wrote {row_count:,} fundamental records to DuckDB")

            # 3. Company Profiles
            if not profiles_buffer.empty:
                row_count = len(profiles_buffer)
                cols = profiles_buffer.columns.tolist()
                col_str = ', '.join(cols)
                update_str = ', '.join([f"{c} = EXCLUDED.{c}" for c in cols if c != 'ticker'])

                con.execute(f"""
                    INSERT INTO company_profiles ({col_str})
                    SELECT {col_str}
                    FROM profiles_buffer
                    ON CONFLICT (ticker) DO UPDATE SET
                        {update_str}
                """)
                print(f"   ✅ Wrote {row_count:,} company profiles to DuckDB")

            # 4. Macro Data
            if not macro_buffer.empty:
                row_count = len(macro_buffer)
                cols = macro_buffer.columns.tolist()
                col_str = ', '.join(cols)
                update_str = ', '.join([f"{c} = EXCLUDED.{c}" for c in cols if c not in ['series_id', 'date']])

                con.execute(f"""
                    INSERT INTO macro_data ({col_str})
                    SELECT {col_str}
                    FROM macro_buffer
                    ON CONFLICT (series_id, date) DO UPDATE SET
                        {update_str}
                """)
                print(f"   ✅ Wrote {row_count:,} macro observations to DuckDB")

            con.execute("COMMIT")
            print("   ✅ Transaction committed")

        except Exception as e:
            con.execute("ROLLBACK")
            logger.error(f"DuckDB write failed: {e}")
            print(f"   ❌ Transaction rolled back: {e}")
            raise
        finally:
            con.close()

    def _compute_features_incremental(self, force_full: bool = False, start_date: str = '2020-01-01'):
        """
        Compute daily features in two phases:
          Phase A: SQL window functions (technical, velocity, structure)
          Phase B: Python-computed features (alphas, cross-sectional ranks)

        Args:
            force_full: If True, recompute ALL features from 2020-01-01
            start_date: Start date for the window of data to compute features on
        """
        con = duckdb.connect(self.db_path)

        try:
            if force_full:
                start_date = '2020-01-01'
                print(f"   [RECOMPUTE] Full feature rebuild (from {start_date})...")
            else:
                # Always rebuild from start_date to prevent table truncation and ensure full history
                # DuckDB is fast enough to handle this in seconds
                print(f"   [INCREMENTAL] Full feature rebuild (from {start_date}) to preserve history...")

            # ==================================================================
            # PHASE A: SQL-native features (window functions on price_data)
            # ==================================================================
            print("   [A] Computing SQL features...")
            con.execute(f"""
                CREATE OR REPLACE TABLE daily_features AS
                WITH price_base AS (
                    SELECT
                        ticker, date, open, close, high, low, volume,
                        LAG(close, 1) OVER (PARTITION BY ticker ORDER BY date) as prev_close,
                        LAG(open, 1) OVER (PARTITION BY ticker ORDER BY date) as prev_open
                    FROM price_data
                    WHERE date >= '{start_date}'
                ),
                spy_data AS (
                    SELECT date, close as spy_close
                    FROM price_data
                    WHERE ticker = 'SPY' AND date >= '{start_date}'
                ),
                price_with_spy AS (
                    SELECT
                        p.*,
                        s.spy_close,
                        p.close / NULLIF(s.spy_close, 0) as price_vs_spy
                    FROM price_base p
                    LEFT JOIN spy_data s ON p.date = s.date
                ),
                -- CTE 1: Core window functions
                core_features AS (
                    SELECT
                        ticker, date, open, close, high, low, volume,
                        prev_close, prev_open, spy_close, price_vs_spy,

                        -- Moving Averages
                        AVG(close) OVER w20 as sma_20,
                        AVG(close) OVER w50 as sma_50,
                        AVG(close) OVER w150 as sma_150,
                        AVG(close) OVER w200 as sma_200,

                        -- RS Line MAs
                        AVG(price_vs_spy) OVER w20 as price_vs_spy_ma20,
                        AVG(price_vs_spy) OVER w50 as price_vs_spy_ma50,
                        AVG(price_vs_spy) OVER w63 as price_vs_spy_ma63,
                        AVG(price_vs_spy) OVER w200 as price_vs_spy_ma200,

                        -- RS Line Derived
                        LN(price_vs_spy) as rs_line_log,
                        (price_vs_spy / NULLIF(LAG(price_vs_spy, 1) OVER ticker_date, 0) - 1) as rs_line_delta,

                        -- Volume
                        AVG(volume) OVER w5 as vol_avg_5,
                        AVG(volume) OVER w20 as vol_avg_20,
                        AVG(volume) OVER w50 as vol_avg_50,

                        -- Volatility
                        STDDEV(close) OVER w20 as volatility_20d,

                        -- True Range components (for ATR)
                        GREATEST(high - low, ABS(high - prev_close), ABS(low - prev_close)) as true_range,

                        -- Returns
                        (close / NULLIF(prev_close, 0) - 1) as return_1d,
                        (close / NULLIF(LAG(close, 5) OVER ticker_date, 0) - 1) as return_5d,
                        (close / NULLIF(LAG(close, 20) OVER ticker_date, 0) - 1) as return_20d,
                        (close / NULLIF(LAG(close, 60) OVER ticker_date, 0) - 1) as return_60d,

                        -- Momentum (multi-period ROC)
                        (close / NULLIF(LAG(close, 21) OVER ticker_date, 0) - 1) as mom_21d,
                        (close / NULLIF(LAG(close, 63) OVER ticker_date, 0) - 1) as mom_63d,
                        (close / NULLIF(LAG(close, 126) OVER ticker_date, 0) - 1) as mom_126d,
                        (close / NULLIF(LAG(close, 189) OVER ticker_date, 0) - 1) as mom_189d,
                        (close / NULLIF(LAG(close, 252) OVER ticker_date, 0) - 1) as mom_252d,

                        -- 52-week high/low
                        MAX(high) OVER w252 as high_52w,
                        MIN(low) OVER w252 as low_52w,

                        -- 20-day high/low
                        MAX(high) OVER w20 as highest_high_20d,
                        MIN(low) OVER w20 as lowest_low_20d,
                        -- Breakout reference: previous 20d high (exclude today)
                        MAX(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) as high_20d,

                        -- ADR / ATR
                        AVG((high - low) / NULLIF(close, 0)) OVER w20 as adr_20d

                    FROM price_with_spy
                    WINDOW
                        ticker_date AS (PARTITION BY ticker ORDER BY date),
                        w5 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
                        w10 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),
                        w20 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
                        w50 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
                        w63 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 62 PRECEDING AND CURRENT ROW),
                        w150 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 149 PRECEDING AND CURRENT ROW),
                        w200 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW),
                        w252 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW)
                ),
                -- CTE 2: Derived features that depend on CTE 1
                derived_features AS (
                    SELECT
                        cf.*,

                        -- ATR (SMA of True Range over 14 and 20 days)
                        AVG(true_range) OVER w14 as atr_14,
                        AVG(true_range) OVER w20 as atr_20d,

                        -- Short-term ATR for VCP Ratio
                        AVG(true_range) OVER w10 as atr_10,
                        AVG(true_range) OVER w50 as atr_50,

                        -- RS rating (Minervini-style weighted momentum)
                        0.4 * mom_63d + 0.2 * mom_126d + 0.2 * mom_189d + 0.2 * mom_252d as rs_rating,

                        -- rs_line_lag_delta (cannot nest window in same CTE)
                        LAG(rs_line_delta, 1) OVER (PARTITION BY ticker ORDER BY date) as rs_line_lag_delta,

                        -- SMA_200 lagged 20d (for SEPA C4: rising 200 SMA)
                        LAG(sma_200, 20) OVER (PARTITION BY ticker ORDER BY date) as sma_200_lag20,

                        -- Price vs SMA (normalized %)
                        ((close - sma_50) / NULLIF(sma_50, 0)) * 100 as price_vs_sma_50,
                        ((close - sma_150) / NULLIF(sma_150, 0)) * 100 as price_vs_sma_150,
                        ((close - sma_200) / NULLIF(sma_200, 0)) * 100 as price_vs_sma_200,

                        -- Distance metrics
                        (close - high_52w) / NULLIF(high_52w, 0) as dist_from_52w_high,
                        (close / NULLIF(low_52w, 0)) - 1 as dist_from_52w_low,
                        (close / NULLIF(lowest_low_20d, 0)) - 1 as dist_from_20d_low,
                        (close / NULLIF(highest_high_20d, 0)) - 1 as dist_from_20d_high,
                        (close - high_52w) / NULLIF(high_52w, 0) as pct_from_high_52w,
                        (close - low_52w) / NULLIF(low_52w, 0) as pct_above_low_52w,

                        -- Binary flags
                        CASE WHEN close >= open THEN 1 ELSE 0 END as is_green_day,
                        CASE WHEN close > MAX(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
                             THEN 1 ELSE 0 END as breakout,

                        -- Turnover
                        close * volume as turnover,

                        -- SMA 50 Slope (% change over 10 days, annualized-ish)
                        ((sma_50 - LAG(sma_50, 10) OVER (PARTITION BY ticker ORDER BY date))
                            / NULLIF(LAG(sma_50, 10) OVER (PARTITION BY ticker ORDER BY date), 0)) / 10.0 * 100 as sma_50_slope,

                        -- RSI components (gains/losses for rolling avg)
                        CASE WHEN close > prev_close THEN close - prev_close ELSE 0 END as rsi_gain,
                        CASE WHEN close < prev_close THEN prev_close - close ELSE 0 END as rsi_loss

                    FROM core_features cf
                    WINDOW
                        w10 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),
                        w14 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),
                        w20 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
                        w50 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW)
                ),
                -- CTE 3: Features that depend on CTE 2 (RSI, VCP, velocity, lags, deltas)
                final_features AS (
                    SELECT
                        df.*,

                        -- nATR (price-normalized)
                        (atr_14 / NULLIF(close, 0)) * 100 as natr,

                        -- VCP Ratio (short/long ATR)
                        atr_10 / NULLIF(atr_50, 0) as vcp_ratio,

                        -- Consolidation Width
                        ((highest_high_20d - lowest_low_20d) / NULLIF(close, 0)) * 100 as consolidation_width,

                        -- Vol Ratio (today vs 50d avg)
                        volume / NULLIF(vol_avg_50, 0) as vol_ratio,

                        -- Dry Up Volume (5d avg / 50d avg)
                        vol_avg_5 / NULLIF(vol_avg_50, 0) as dry_up_volume,

                        -- RS and RS_MA (momentum-based, same as Python RS)
                        rs_rating as rs,
                        AVG(rs_rating) OVER w63 as rs_ma,

                        -- RSI 14 (SMA-based approximation)
                        100 - (100 / (1 + (AVG(rsi_gain) OVER w14 / NULLIF(AVG(rsi_loss) OVER w14, 0)))) as rsi_14,

                        -- Green Days Ratio
                        AVG(CAST(is_green_day AS DOUBLE)) OVER w20 as green_days_ratio_20d,

                        -- Turnover MA
                        AVG(turnover) OVER w20 as turnover_ma20,

                        -- Volume MAs
                        vol_avg_20 as vol_ma20,
                        vol_avg_50 as vol_ma50,

                        -- Vol Ratio 50 (legacy name)
                        volume / NULLIF(vol_avg_50, 0) as vol_ratio_50,
                        vol_avg_20 * close as dollar_volume_avg_20,

                        -- RS Line flags
                        CASE WHEN price_vs_spy > price_vs_spy_ma63 THEN TRUE ELSE FALSE END as rs_line_uptrend,
                        CASE WHEN close > sma_200 THEN TRUE ELSE FALSE END as close_above_sma200,

                        -- =====================================================
                        -- VELOCITY FEATURES
                        -- =====================================================
                        -- rs_velocity: (RS - RS_lag5) / 5
                        (rs_rating - LAG(rs_rating, 5) OVER ticker_date) / 5.0 as rs_velocity,

                        -- volume_acceleration: 2nd derivative of volume (cast to allow negative)
                        (CAST(volume AS BIGINT) - LAG(CAST(volume AS BIGINT), 1) OVER ticker_date)
                            - (LAG(CAST(volume AS BIGINT), 1) OVER ticker_date
                               - LAG(CAST(volume AS BIGINT), 2) OVER ticker_date) as volume_acceleration,

                        -- breakout_momentum: (close - high_20d) / ATR
                        CASE WHEN atr_14 > 0
                            THEN (close - high_20d) / atr_14
                            ELSE 0 END as breakout_momentum,

                        -- consolidation_duration: count tight days in 20d window
                        SUM(CASE WHEN (high - low) < 0.5 * atr_14 THEN 1 ELSE 0 END) OVER w20 as consolidation_duration,

                        -- price_momentum_curve: 2nd derivative of price
                        (close - LAG(close, 1) OVER ticker_date)
                            - (LAG(close, 1) OVER ticker_date - LAG(close, 2) OVER ticker_date) as price_momentum_curve,

                        -- log_volume_velocity: 2-day change in ln(volume)
                        LN(NULLIF(volume, 0)) - LAG(LN(NULLIF(volume, 0)), 2) OVER ticker_date as log_volume_velocity,

                        -- price_accel_10d: new slope - old slope
                        ((close - LAG(close, 10) OVER ticker_date) / 10.0)
                            - ((LAG(close, 10) OVER ticker_date - LAG(close, 20) OVER ticker_date) / 10.0) as price_accel_10d,

                        -- immediate_thrust: price 2nd derivative (jerk)
                        close - 2 * LAG(close, 1) OVER ticker_date + LAG(close, 2) OVER ticker_date as immediate_thrust,

                        'v3.0' as feature_version

                    FROM derived_features df
                    WINDOW
                        ticker_date AS (PARTITION BY ticker ORDER BY date),
                        w14 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),
                        w20 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
                        w63 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 62 PRECEDING AND CURRENT ROW)
                )
                SELECT
                    ticker, date, close, open, high, low, volume,

                    -- Moving Averages
                    sma_20, sma_50, sma_150, sma_200, sma_200_lag20,
                    close_above_sma200,

                    -- Price vs SMA (normalized %)
                    price_vs_sma_50, price_vs_sma_150, price_vs_sma_200,

                    -- RS Line features
                    price_vs_spy, price_vs_spy_ma20, price_vs_spy_ma50,
                    price_vs_spy_ma63, price_vs_spy_ma200,
                    rs_line_uptrend, rs_line_log, rs_line_delta, rs_line_lag_delta,

                    -- RS (momentum-based)
                    rs_rating, rs, rs_ma,

                    -- Volume
                    vol_avg_20, vol_avg_50, vol_ratio, vol_ratio_50,
                    vol_ma20, vol_ma50, dollar_volume_avg_20,
                    dry_up_volume,

                    -- Turnover
                    turnover, turnover_ma20,

                    -- Volatility / ATR
                    atr_14, atr_20d, natr, volatility_20d,
                    vcp_ratio, consolidation_width,

                    -- 52-week and 20-day range
                    high_52w, low_52w, highest_high_20d, lowest_low_20d, high_20d,
                    pct_from_high_52w, pct_above_low_52w,
                    dist_from_52w_high, dist_from_52w_low,
                    dist_from_20d_low, dist_from_20d_high,

                    -- Returns / Momentum
                    return_1d, return_5d, return_20d, return_60d,
                    mom_21d, mom_63d, mom_126d, mom_189d, mom_252d,

                    -- Oscillators / Flags
                    rsi_14, sma_50_slope,
                    is_green_day, green_days_ratio_20d, breakout,

                    -- ADR
                    adr_20d,

                    -- Velocity features
                    rs_velocity, volume_acceleration, breakout_momentum,
                    consolidation_duration, price_momentum_curve,
                    log_volume_velocity, price_accel_10d, immediate_thrust,

                    feature_version
                FROM final_features
            """)

            row_count = con.execute("SELECT COUNT(*) FROM daily_features").fetchone()[0]
            print(f"   ✅ [A] Computed {row_count:,} SQL feature records")

        except Exception as e:
            logger.error(f"SQL feature computation failed: {e}")
            print(f"   ❌ SQL feature computation failed: {e}")
            raise
        finally:
            con.close()

        # ==================================================================
        # PHASE B: Python-computed features (alphas + cross-sectional)
        # ==================================================================
        self._compute_python_features()

    def _compute_fundamental_features(self, tickers: List[str] = None):
        """
        Compute fundamental features from parquet files and store in fundamental_features table.
        Uses FundamentalProcessor to apply growth, safety, and operating metrics logic.

        Args:
            tickers: List of tickers to process. If None, processes all available parquet files.

        Process:
            1. Read fundamentals from parquet files (data/fundamentals/*.parquet)
            2. Apply FundamentalProcessor logic to compute derived metrics
            3. Batch write results to fundamental_features table
        """
        from src.fundamental_processor import FundamentalProcessor

        con = duckdb.connect(self.db_path)
        processor = FundamentalProcessor()

        try:
            # Determine which tickers to process
            if tickers is None:
                # Process all available parquet files
                parquet_files = list(config.FUNDAMENTALS_DIR.glob('*.parquet'))
                tickers = [f.stem for f in parquet_files]
            else:
                # Filter to only tickers with parquet files
                tickers = [t for t in tickers if (config.FUNDAMENTALS_DIR / f"{t}.parquet").exists()]

            if not tickers:
                print("   [WARN] No fundamental parquet files found")
                return

            print(f"   Processing {len(tickers)} tickers...")

            all_results = []
            processed_count = 0
            error_count = 0

            for i, ticker in enumerate(tickers, 1):
                try:
                    parquet_file = config.FUNDAMENTALS_DIR / f"{ticker}.parquet"
                    df = pd.read_parquet(parquet_file)

                    # Process using FundamentalProcessor
                    processed = processor.process_ticker_fundamentals(ticker, df)

                    if processed.empty:
                        continue

                    # Extract required columns for fundamental_features table
                    # Map FMP columns to our schema
                    column_mapping = {
                        'ticker': 'ticker',
                        'filing_date': 'filing_date',
                        'fiscal_period': 'fiscal_period',
                        'fiscal_date': 'fiscal_date',
                        'fiscalYear': 'fiscal_year',
                        'period_type': 'period_type',
                        'revenue': 'revenue',
                        'netIncome': 'net_income',
                        'epsDiluted': 'eps_diluted',
                        'totalAssets': 'total_assets',
                        'totalEquity': 'total_equity',
                        'totalDebt': 'total_debt',
                        'operatingCashFlow': 'operating_cash_flow',
                        'freeCashFlow': 'free_cash_flow',
                        'grossProfit': 'gross_profit',
                        'operatingIncome': 'operating_income',
                        'totalCurrentAssets': 'total_current_assets',
                        'totalCurrentLiabilities': 'total_current_liabilities',
                        'inventory': 'inventory',
                        # Derived metrics (already computed by FundamentalProcessor)
                        'revenue_growth_yoy': 'revenue_growth_yoy',
                        'eps_growth_yoy': 'eps_growth_yoy',
                        'net_income_growth_yoy': 'net_income_growth_yoy',
                        'eps_accel': 'eps_accel',
                        'revenue_accel': 'revenue_accel',
                        'revenue_cagr_3y': 'revenue_cagr_3y',
                        'eps_stability_score': 'eps_stability_score',
                        'debt_to_equity': 'debt_to_equity',
                        'current_ratio': 'current_ratio',
                        'quick_ratio': 'quick_ratio',
                        'gross_margin': 'gross_margin',
                        'operating_margin': 'operating_margin',
                        'net_margin': 'net_margin',
                        'roe': 'roe',
                        'roa': 'roa',
                        'fcf_margin': 'fcf_margin',
                        'earnings_quality_score': 'earnings_quality_score',
                        'inventory_growth_yoy': 'inventory_growth_yoy',
                        'inventory_vs_sales_spread': 'inventory_vs_sales_spread',
                        'gross_margin_trend': 'gross_margin_trend'
                    }

                    # Build result dataframe with mapped columns
                    result_df = pd.DataFrame()

                    for fmp_col, db_col in column_mapping.items():
                        if fmp_col in processed.columns:
                            result_df[db_col] = processed[fmp_col]
                        else:
                            # Column doesn't exist, fill with NaN
                            result_df[db_col] = np.nan

                    # Add ticker if not in processed
                    if 'ticker' not in result_df.columns:
                        result_df['ticker'] = ticker

                    # Add feature_version
                    result_df['feature_version'] = 'v1.0'

                    all_results.append(result_df)
                    processed_count += 1

                    if i % 100 == 0:
                        print(f"      Processed {i}/{len(tickers)} tickers...")

                except Exception as e:
                    logger.error(f"Error processing {ticker}: {e}")
                    error_count += 1
                    continue

            if not all_results:
                print("   [WARN] No fundamental features computed")
                return

            # Concatenate all results
            final_df = pd.concat(all_results, ignore_index=True)

            # Drop rows with missing primary key components
            final_df = final_df.dropna(subset=['ticker', 'filing_date', 'fiscal_period'])

            if final_df.empty:
                print("   [WARN] No valid fundamental features after cleaning")
                return

            # Write to DuckDB using ON CONFLICT to handle duplicates
            row_count = len(final_df)

            # Get column list from final_df (excludes updated_at which has a default)
            col_list = ', '.join(final_df.columns.tolist())

            # Build UPDATE SET clause programmatically (exclude primary keys)
            update_cols = [c for c in final_df.columns if c not in ['ticker', 'filing_date', 'fiscal_period']]
            update_set = ', '.join([f"{c} = EXCLUDED.{c}" for c in update_cols])

            query = f"""
                INSERT INTO fundamental_features ({col_list})
                SELECT {col_list} FROM final_df
                ON CONFLICT (ticker, filing_date, fiscal_period) DO UPDATE SET
                    {update_set}
            """

            con.execute(query)

            print(f"   [OK] Wrote {row_count:,} fundamental feature records ({processed_count} tickers, {error_count} errors)")

        except Exception as e:
            logger.error(f"Fundamental feature computation failed: {e}")
            print(f"   [ERROR] Fundamental feature computation failed: {e}")
            raise
        finally:
            con.close()

    def _create_views(self):
        """
        Create/replace all analytical views on top of daily_features.

        Views:
            v_sepa_candidates: Trend template (C1-C9) + metadata. Used by scanner
                for initial universe filtering.
            v_d1_candidates: Full SEPA signal (C1-C11 trend + breakout + volume spike).
                SQL-native equivalent of VectorizedSEPAScreener. Includes lag/delta
                features needed by M01/M02.
        """
        con = duckdb.connect(self.db_path)
        try:
            # ==================================================================
            # VIEW 1: v_sepa_candidates — Trend Template (C1-C9)
            # ==================================================================
            # Replaces the old view that used stale column names and only checked
            # 3 conditions. Now enforces full C1-C9 against v3.0 schema.
            con.execute("""
                CREATE OR REPLACE VIEW v_sepa_candidates AS
                SELECT
                    f.date,
                    f.ticker,
                    f.close,
                    f.sma_50,
                    f.sma_150,
                    f.sma_200,
                    f.sma_200_lag20,
                    f.high_52w,
                    f.low_52w,
                    f.pct_from_high_52w,
                    f.vol_avg_20,
                    f.vol_avg_50,
                    f.vol_ratio,
                    f.natr,
                    f.atr_20d,
                    f.volatility_20d,
                    f.adr_20d,
                    f.rs_rating,
                    f.rs,
                    f.rs_ma,
                    f.price_vs_spy,
                    f.price_vs_spy_ma63,
                    f.rs_line_uptrend,
                    f.rs_line_log,
                    f.rs_line_delta,
                    f.breakout,
                    f.return_20d,
                    f.rsi_14,
                    f.sma_50_slope,
                    c.sector,
                    c.industry
                FROM daily_features f
                INNER JOIN company_profiles c
                    ON f.ticker = c.ticker
                WHERE c.is_active = TRUE
                  AND f.vol_avg_20 > 500000
                  -- C1: Price > 150 SMA
                  AND f.close > f.sma_150
                  -- C2: Price > 200 SMA
                  AND f.close > f.sma_200
                  -- C3: 150 SMA > 200 SMA
                  AND f.sma_150 > f.sma_200
                  -- C4: 200 SMA trending up (current > 20 days ago)
                  AND f.sma_200 > f.sma_200_lag20
                  -- C5: 50 SMA > 150 SMA
                  AND f.sma_50 > f.sma_150
                  -- C6: Price > 50 SMA
                  AND f.close > f.sma_50
                  -- C7: Price > 30% above 52-week low
                  AND f.close > f.low_52w * 1.3
                  -- C8: Price within 15% of 52-week high
                  AND f.close > f.high_52w * 0.85
                  -- C9: RS line uptrend (price_vs_spy > price_vs_spy_ma63)
                  AND f.price_vs_spy > f.price_vs_spy_ma63
            """)
            n_sepa = con.execute(
                "SELECT COUNT(*) FROM v_sepa_candidates WHERE date = (SELECT MAX(date) FROM daily_features)"
            ).fetchone()[0]
            print(f"   [OK] v_sepa_candidates: C1-C9 trend template ({n_sepa} candidates on latest date)")

            # ==================================================================
            # VIEW 2: v_d1_candidates — Full SEPA Signal (C1-C11)
            # ==================================================================
            # Adds breakout (C10) and volume spike (C11) to trend template.
            # Also computes lag/delta features inline for M01/M02 consumption.
            con.execute("""
                CREATE OR REPLACE VIEW v_d1_candidates AS
                WITH sepa AS (
                    SELECT
                        f.*,
                        c.sector,
                        c.industry,
                        -- Lag features (T-1 values via window)
                        LAG(f.natr)              OVER w AS natr_lag1,
                        LAG(f.atr_20d)           OVER w AS atr_lag1,
                        LAG(f.vcp_ratio)         OVER w AS vcp_ratio_lag1,
                        LAG(f.consolidation_width) OVER w AS consolidation_width_lag1,
                        LAG(f.price_vs_sma_50)   OVER w AS price_vs_sma_50_lag1,
                        LAG(f.price_vs_sma_150)  OVER w AS price_vs_sma_150_lag1,
                        LAG(f.price_vs_sma_200)  OVER w AS price_vs_sma_200_lag1,
                        LAG(f.rs)                OVER w AS rs_lag1,
                        LAG(f.rs_ma)             OVER w AS rs_ma_lag1,
                        LAG(f.dry_up_volume)     OVER w AS dry_up_volume_lag1,
                        LAG(f.high_52w)          OVER w AS high_52w_lag1,
                        LAG(f.low_52w)           OVER w AS low_52w_lag1,
                        LAG(f.lowest_low_20d)    OVER w AS lowest_low_20d_lag1,
                        LAG(f.highest_high_20d)  OVER w AS highest_high_20d_lag1,
                        LAG(f.rsi_14)            OVER w AS rsi_14_lag1,
                        LAG(f.dist_from_52w_high) OVER w AS dist_from_52w_high_lag1,
                        LAG(f.dist_from_52w_low) OVER w AS dist_from_52w_low_lag1,
                        LAG(f.dist_from_20d_low) OVER w AS dist_from_20d_low_lag1,
                        LAG(f.dist_from_20d_high) OVER w AS dist_from_20d_high_lag1,
                        -- Previous day breakout status for transition detection
                        LAG(f.breakout)          OVER w AS breakout_prev
                    FROM daily_features f
                    INNER JOIN company_profiles c ON f.ticker = c.ticker
                    WHERE c.is_active = TRUE
                      AND f.vol_avg_20 > 500000
                      -- C1-C8: Trend template
                      AND f.close > f.sma_150
                      AND f.close > f.sma_200
                      AND f.sma_150 > f.sma_200
                      AND f.sma_200 > f.sma_200_lag20
                      AND f.sma_50 > f.sma_150
                      AND f.close > f.sma_50
                      AND f.close > f.low_52w * 1.3
                      AND f.close > f.high_52w * 0.85
                      -- C9: RS line uptrend
                      AND f.price_vs_spy > f.price_vs_spy_ma63
                      -- C10: Breakout (close > 20-day prior high)
                      AND f.breakout = 1
                      -- C11: Volume spike (vol > 1.3x 50d avg)
                      AND f.vol_ratio_50 > 1.3
                    WINDOW w AS (PARTITION BY f.ticker ORDER BY f.date)
                )
                SELECT
                    s.*,
                    -- Delta features: (current - lag) / |lag|
                    CASE WHEN ABS(s.natr_lag1) > 1e-9
                        THEN (s.natr - s.natr_lag1) / ABS(s.natr_lag1) END AS natr_delta,
                    CASE WHEN ABS(s.vcp_ratio_lag1) > 1e-9
                        THEN (s.vcp_ratio - s.vcp_ratio_lag1) / ABS(s.vcp_ratio_lag1) END AS vcp_ratio_delta,
                    CASE WHEN ABS(s.consolidation_width_lag1) > 1e-9
                        THEN (s.consolidation_width - s.consolidation_width_lag1) / ABS(s.consolidation_width_lag1) END AS consolidation_width_delta,
                    CASE WHEN ABS(s.price_vs_sma_50_lag1) > 1e-9
                        THEN (s.price_vs_sma_50 - s.price_vs_sma_50_lag1) / ABS(s.price_vs_sma_50_lag1) END AS price_vs_sma_50_delta,
                    CASE WHEN ABS(s.price_vs_sma_150_lag1) > 1e-9
                        THEN (s.price_vs_sma_150 - s.price_vs_sma_150_lag1) / ABS(s.price_vs_sma_150_lag1) END AS price_vs_sma_150_delta,
                    CASE WHEN ABS(s.price_vs_sma_200_lag1) > 1e-9
                        THEN (s.price_vs_sma_200 - s.price_vs_sma_200_lag1) / ABS(s.price_vs_sma_200_lag1) END AS price_vs_sma_200_delta,
                    CASE WHEN ABS(s.rs_lag1) > 1e-9
                        THEN (s.rs - s.rs_lag1) / ABS(s.rs_lag1) END AS rs_delta,
                    CASE WHEN ABS(s.rs_ma_lag1) > 1e-9
                        THEN (s.rs_ma - s.rs_ma_lag1) / ABS(s.rs_ma_lag1) END AS rs_ma_delta,
                    CASE WHEN ABS(s.dry_up_volume_lag1) > 1e-9
                        THEN (s.dry_up_volume - s.dry_up_volume_lag1) / ABS(s.dry_up_volume_lag1) END AS dry_up_volume_delta,
                    CASE WHEN ABS(s.high_52w_lag1) > 1e-9
                        THEN (s.high_52w - s.high_52w_lag1) / ABS(s.high_52w_lag1) END AS high_52w_delta,
                    CASE WHEN ABS(s.low_52w_lag1) > 1e-9
                        THEN (s.low_52w - s.low_52w_lag1) / ABS(s.low_52w_lag1) END AS low_52w_delta,
                    CASE WHEN ABS(s.lowest_low_20d_lag1) > 1e-9
                        THEN (s.lowest_low_20d - s.lowest_low_20d_lag1) / ABS(s.lowest_low_20d_lag1) END AS lowest_low_20d_delta,
                    CASE WHEN ABS(s.highest_high_20d_lag1) > 1e-9
                        THEN (s.highest_high_20d - s.highest_high_20d_lag1) / ABS(s.highest_high_20d_lag1) END AS highest_high_20d_delta,
                    CASE WHEN ABS(s.rsi_14_lag1) > 1e-9
                        THEN (s.rsi_14 - s.rsi_14_lag1) / ABS(s.rsi_14_lag1) END AS rsi_14_delta,
                    CASE WHEN ABS(s.dist_from_52w_high_lag1) > 1e-9
                        THEN (s.dist_from_52w_high - s.dist_from_52w_high_lag1) / ABS(s.dist_from_52w_high_lag1) END AS dist_from_52w_high_delta,
                    CASE WHEN ABS(s.dist_from_52w_low_lag1) > 1e-9
                        THEN (s.dist_from_52w_low - s.dist_from_52w_low_lag1) / ABS(s.dist_from_52w_low_lag1) END AS dist_from_52w_low_delta,
                    CASE WHEN ABS(s.dist_from_20d_low_lag1) > 1e-9
                        THEN (s.dist_from_20d_low - s.dist_from_20d_low_lag1) / ABS(s.dist_from_20d_low_lag1) END AS dist_from_20d_low_delta,
                    CASE WHEN ABS(s.dist_from_20d_high_lag1) > 1e-9
                        THEN (s.dist_from_20d_high - s.dist_from_20d_high_lag1) / ABS(s.dist_from_20d_high_lag1) END AS dist_from_20d_high_delta,
                    -- New trigger flag: breakout today but NOT yesterday (0->1 transition)
                    CASE WHEN s.breakout = 1 AND COALESCE(s.breakout_prev, 0) = 0
                        THEN 1 ELSE 0 END AS is_new_trigger
                FROM sepa s
            """)
            n_d1 = con.execute(
                "SELECT COUNT(*) FROM v_d1_candidates WHERE date = (SELECT MAX(date) FROM daily_features)"
            ).fetchone()[0]
            print(f"   [OK] v_d1_candidates: C1-C11 full SEPA + lags/deltas ({n_d1} signals on latest date)")

            # ==================================================================
            # VIEW 3: v_d2_features — D1 + Fundamentals for M01 Model
            # ==================================================================
            # Joins D1 candidates with fundamental_features using most recent filing
            # as of each trading date (point-in-time correctness).
            # Also includes company_profiles for sector/industry.
            con.execute("""
                CREATE OR REPLACE VIEW v_d2_features AS
                SELECT
                    d1.*,
                    -- Fundamental features (most recent as of d1.date)
                    ff.revenue,
                    ff.net_income,
                    ff.eps_diluted,
                    ff.total_assets,
                    ff.total_equity,
                    ff.revenue_growth_yoy,
                    ff.eps_growth_yoy,
                    ff.net_income_growth_yoy,
                    ff.eps_accel,
                    ff.revenue_accel,
                    ff.revenue_cagr_3y,
                    ff.eps_stability_score,
                    ff.debt_to_equity,
                    ff.current_ratio,
                    ff.quick_ratio,
                    ff.gross_margin,
                    ff.operating_margin,
                    ff.net_margin,
                    ff.roe,
                    ff.roa,
                    ff.fcf_margin,
                    ff.earnings_quality_score,
                    ff.inventory_growth_yoy,
                    ff.inventory_vs_sales_spread,
                    ff.gross_margin_trend,
                    ff.filing_date as fundamental_filing_date,
                    ff.fiscal_period,
                    -- Company profile (already in d1, but kept for explicit reference)
                    cp.sector,
                    cp.industry,
                    cp.market_cap
                FROM v_d1_candidates d1
                LEFT JOIN company_profiles cp
                    ON d1.ticker = cp.ticker
                LEFT JOIN fundamental_features ff
                    ON d1.ticker = ff.ticker
                    AND ff.filing_date = (
                        -- Get most recent filing before or on d1.date (point-in-time correct)
                        SELECT MAX(filing_date)
                        FROM fundamental_features
                        WHERE ticker = d1.ticker
                        AND filing_date <= d1.date
                    )
                WHERE d1.date >= '2020-01-01'
            """)

            # Count rows
            n_d2 = con.execute(
                "SELECT COUNT(*) FROM v_d2_features WHERE date = (SELECT MAX(date) FROM daily_features)"
            ).fetchone()[0]
            print(f"   [OK] v_d2_features: D1 + fundamentals for M01 ({n_d2} signals on latest date)")

        except Exception as e:
            logger.error(f"View creation failed: {e}")
            print(f"   [ERROR] View creation failed: {e}")
            raise
        finally:
            con.close()

    def _compute_python_features(self):
        """
        Compute features that require Python: alpha factors and cross-sectional ranks.

        Reads OHLCV from daily_features, computes per-ticker alphas and universe-wide
        ranks, then writes columns back via UPDATE. All Python-computed columns are
        managed here — single source of truth for non-SQL features.
        """
        from src.alpha_factors import AlphaEngine

        print("   [B] Computing Python features (alphas + cross-sectional)...")
        con = duckdb.connect(self.db_path)

        try:
            # ── 1. Load OHLCV for alpha computation ──
            # We need Open/High/Low/Close/Volume per ticker, plus RS for cross-sectional
            tickers = [r[0] for r in con.execute(
                "SELECT DISTINCT ticker FROM daily_features ORDER BY ticker"
            ).fetchall()]
            print(f"   Processing {len(tickers)} tickers...")

            alpha_engine = AlphaEngine()
            alpha_cols = alpha_engine.get_alpha_names()

            # Add placeholder columns for alphas + cross-sectional if they don't exist
            all_python_cols = alpha_cols + [
                'RS_Universe_Rank', 'RS_Sector_Rank', 'RS_vs_Sector',
                'Sector_Momentum', 'RS_Industry_Rank', 'RS_vs_Industry',
                'Industry_Momentum',
            ]
            existing_cols = {r[0] for r in con.execute("DESCRIBE daily_features").fetchall()}
            for col in all_python_cols:
                if col not in existing_cols:
                    con.execute(f"ALTER TABLE daily_features ADD COLUMN {col} DOUBLE")

            # ── 2. Compute alphas per ticker ──
            # Process in batches to manage memory
            batch_size = 50
            total_updated = 0

            for i in range(0, len(tickers), batch_size):
                batch_tickers = tickers[i:i + batch_size]
                ticker_list_sql = ','.join([f"'{t}'" for t in batch_tickers])

                # Load price data for this batch
                batch_df = con.execute(f"""
                    SELECT ticker, date, open, high, low, close, volume
                    FROM daily_features
                    WHERE ticker IN ({ticker_list_sql})
                    ORDER BY ticker, date
                """).df()

                if batch_df.empty:
                    continue

                alpha_results = []

                for ticker in batch_tickers:
                    ticker_df = batch_df[batch_df['ticker'] == ticker].copy()
                    if len(ticker_df) < 50:
                        continue

                    # Rename to match AlphaEngine expected columns
                    ticker_df = ticker_df.rename(columns={
                        'open': 'Open', 'high': 'High', 'low': 'Low',
                        'close': 'Close', 'volume': 'Volume'
                    })
                    ticker_df = ticker_df.set_index('date')

                    # Calculate alphas
                    enriched = alpha_engine.calculate_alphas(ticker_df)

                    # Extract only alpha columns + key for join
                    result = enriched[alpha_cols].copy()
                    result['ticker'] = ticker
                    result['date'] = result.index
                    result = result.reset_index(drop=True)
                    alpha_results.append(result)

                if not alpha_results:
                    continue

                # Batch update alpha columns
                alpha_df = pd.concat(alpha_results, ignore_index=True)

                # Write to staging table, then UPDATE daily_features
                con.execute("DROP TABLE IF EXISTS _staging_alphas")
                con.execute("CREATE TEMP TABLE _staging_alphas AS SELECT * FROM alpha_df")

                update_set = ', '.join([f"{col} = s.{col}" for col in alpha_cols])
                con.execute(f"""
                    UPDATE daily_features f
                    SET {update_set}
                    FROM _staging_alphas s
                    WHERE f.ticker = s.ticker AND f.date = s.date
                """)
                con.execute("DROP TABLE IF EXISTS _staging_alphas")

                total_updated += len(alpha_df)

                if (i + batch_size) % 200 == 0 or i + batch_size >= len(tickers):
                    print(f"      Alphas: {min(i + batch_size, len(tickers))}/{len(tickers)} tickers")

            print(f"   ✅ [B1] Alpha factors: {total_updated:,} rows updated ({len(alpha_cols)} columns)")

            # ── 3. Cross-sectional features (universe-wide per date) ──
            # These use SQL PARTITION BY date — cleaner than Python groupby
            con.execute("""
                WITH sector_map AS (
                    SELECT ticker, sector, industry
                    FROM company_profiles
                ),
                ranked AS (
                    SELECT
                        f.ticker,
                        f.date,
                        f.rs,
                        sm.sector,
                        sm.industry,
                        -- Universe-level rank
                        PERCENT_RANK() OVER (PARTITION BY f.date ORDER BY f.rs) as rs_universe_rank,
                        -- Sector-level rank
                        PERCENT_RANK() OVER (PARTITION BY f.date, sm.sector ORDER BY f.rs) as rs_sector_rank,
                        -- Sector stats
                        AVG(f.rs) OVER (PARTITION BY f.date, sm.sector) as sector_momentum,
                        STDDEV(f.rs) OVER (PARTITION BY f.date, sm.sector) as sector_rs_std,
                        -- Industry-level rank
                        PERCENT_RANK() OVER (PARTITION BY f.date, sm.industry ORDER BY f.rs) as rs_industry_rank,
                        -- Industry stats
                        AVG(f.rs) OVER (PARTITION BY f.date, sm.industry) as industry_momentum,
                        STDDEV(f.rs) OVER (PARTITION BY f.date, sm.industry) as industry_rs_std
                    FROM daily_features f
                    LEFT JOIN sector_map sm ON f.ticker = sm.ticker
                    WHERE f.rs IS NOT NULL
                )
                UPDATE daily_features f
                SET
                    RS_Universe_Rank = r.rs_universe_rank,
                    RS_Sector_Rank = r.rs_sector_rank,
                    RS_vs_Sector = CASE WHEN r.sector_rs_std > 0
                        THEN (r.rs - r.sector_momentum) / r.sector_rs_std
                        ELSE 0 END,
                    Sector_Momentum = r.sector_momentum,
                    RS_Industry_Rank = r.rs_industry_rank,
                    RS_vs_Industry = CASE WHEN r.industry_rs_std > 0
                        THEN (r.rs - r.industry_momentum) / r.industry_rs_std
                        ELSE 0 END,
                    Industry_Momentum = r.industry_momentum
                FROM ranked r
                WHERE f.ticker = r.ticker AND f.date = r.date
            """)

            cs_count = con.execute(
                "SELECT COUNT(*) FROM daily_features WHERE RS_Universe_Rank IS NOT NULL"
            ).fetchone()[0]
            print(f"   ✅ [B2] Cross-sectional ranks: {cs_count:,} rows updated (7 columns)")

            # ── Summary ──
            total_cols = len(con.execute("DESCRIBE daily_features").fetchall())
            print(f"   ✅ [B] Python features complete. Total columns: {total_cols}")

        except Exception as e:
            logger.error(f"Python feature computation failed: {e}")
            print(f"   ❌ Python feature computation failed: {e}")
            raise
        finally:
            con.close()


def get_tickers(source: str = 'price_folder', custom_tickers: Optional[str] = None) -> List[str]:
    """
    Get ticker universe.

    Args:
        source: 'sp500', 'fmp_screener', 'price_folder'
        custom_tickers: Comma-separated list of tickers (overrides source)

    Returns:
        List of ticker symbols
    """
    if custom_tickers:
        tickers = [t.strip().upper() for t in custom_tickers.split(',') if t.strip()]
        print(f"   📋 Using {len(tickers)} custom tickers")
        return tickers

    source_map = {
        'price_folder': 'PRICE_FOLDER',
        'fmp_screener': 'FMP_SCREENER',
        'sp500': 'SSGA'
    }

    data_repo = DataRepository()
    tickers = data_repo.update_universe(source=source_map.get(source, 'PRICE_FOLDER'))
    print(f"   📋 Loaded {len(tickers)} tickers from {source}")
    return tickers


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="DuckDB Data Curator - Buffered Fetch + Batch Write",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Ticker selection
    parser.add_argument('--source', choices=['sp500', 'fmp_screener', 'price_folder'],
                        default='price_folder', help="Ticker universe source")
    parser.add_argument('--tickers', type=str, help="Comma-separated ticker list (overrides --source)")

    # Update flags
    parser.add_argument('--update-prices', action='store_true', help="Update price data")
    parser.add_argument('--update-fundamentals', action='store_true', help="Update fundamentals")
    parser.add_argument('--update-profiles', action='store_true', help="Update company profiles")
    parser.add_argument('--update-macro', action='store_true', help="Update macro data")
    parser.add_argument('--update-all', action='store_true', help="Update all data types")

    # Feature computation
    parser.add_argument('--update-features', action='store_true',
                        help="Recompute daily_features table (no API fetch). Use with --recompute for full rebuild.")
    parser.add_argument('--recompute', action='store_true',
                        help="Force full feature rebuild from 2020-01-01 (use after schema changes)")
    parser.add_argument('--incremental', action='store_true',
                        help="Force incremental feature update (last 252 days). This is the default.")

    parser.add_argument('--start-date', type=str, default='2020-01-01',
                        help="Start date for feature computation (YYYY-MM-DD). Defaults to 2020-01-01 to ensure full history.")

    # Behavior
    parser.add_argument('--dual-mode', action='store_true',
                        help="Write to both parquet + DuckDB (validation period)")
    parser.add_argument('--force', action='store_true', help="Force re-download all data")
    parser.add_argument('--daily-limit', type=int, help="Max API calls for rate-limited endpoints (fundamentals)")

    args = parser.parse_args()

    # Parse flags
    update_prices = args.update_prices or args.update_all
    update_fundamentals = args.update_fundamentals or args.update_all
    update_profiles = args.update_profiles or args.update_all
    update_macro = args.update_macro or args.update_all
    update_features_only = args.update_features
    recompute = args.recompute

    # Get tickers
    print("\n" + "=" * 80)
    print("Loading Ticker Universe...")
    tickers = get_tickers(source=args.source, custom_tickers=args.tickers)

    # Run curator
    curator = DuckDBDataCurator(dual_mode=args.dual_mode)
    curator.run_update(
        tickers=tickers,
        update_prices=update_prices,
        update_fundamentals=update_fundamentals,
        update_profiles=update_profiles,
        update_macro=update_macro,
        update_features_only=update_features_only,
        recompute=recompute,
        force=args.force,
        daily_limit=args.daily_limit,
        start_date=args.start_date
    )
