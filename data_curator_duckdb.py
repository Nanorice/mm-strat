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
import duckdb

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.data_engine import DataRepository
from src.utils import get_latest_trading_day
from src.fundamental_engine import FundamentalEngine
from src.company_profile_engine import CompanyProfileEngine
from src.macro_engine import MacroEngine
from src.feature_pipeline import FeaturePipeline
from src.managers.view_manager import ViewManager
from src.shares_engine import SharesEngine

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
                            MAX(f.updated_at) as last_update,
                            cp.market_cap
                        FROM ticker_list tl
                        LEFT JOIN fundamentals f ON tl.ticker = f.ticker
                        LEFT JOIN company_profiles cp ON tl.ticker = cp.ticker
                        GROUP BY tl.ticker, cp.market_cap
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
                            cp.market_cap,
                            cp.updated_at as last_update
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
        self.shares_engine = SharesEngine(str(DB_PATH))

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
        update_shares: bool = False,
        update_features_only: bool = False,
        recompute: bool = False,
        force: bool = False,
        daily_limit: Optional[int] = None,
        start_date: str = '2020-01-01',
        warmup_days: int = 730,
        incremental: bool = True,
        skip_t3: bool = False
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
            warmup_days: Days of history to load before start_date for lookback features
            incremental: If True, only compute features for new data (default: True)
            skip_t3: If True, skip T3 SEPA features computation (default: False)
        """
        start_time = time.time()

        print("\n" + "=" * 80)
        print("[DATA] DuckDB Data Curator - Daily Update")
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
        if update_shares:
            updates.append("shares")

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

            if update_shares:
                if force:
                    self.shares_engine.backfill(tickers)
                else:
                    self.shares_engine.update(tickers)

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
            mode_label = "FULL RECOMPUTE" if recompute else ("incremental" if incremental else "full rebuild")
            print(f"\n[3/5] Computing daily features ({mode_label}, start={start_date}, warmup={warmup_days}d)...")
            self._compute_features_incremental(
                start_date=start_date,
                warmup_days=warmup_days,
                skip_t3=skip_t3
            )
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
        ViewManager(self.db_path).create_all()

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
        print("   [FETCH] Price data...")

        # Ensure SPY is included
        if self.data_repo.benchmark_ticker and self.data_repo.benchmark_ticker not in tickers:
            tickers = list(tickers) + [self.data_repo.benchmark_ticker]

        if self.dual_mode:
            return self._fetch_prices_legacy(tickers, force=force)

        # --- Direct path: DuckDB staleness -> API -> buffer new rows only ---
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
            print(f"   [INFO]  {skipped} tickers already current, fetching {len(work)}")

        if not work:
            print(f"   [OK] All {len(tickers)} tickers up to date")
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
            print(f"   [OK] Fetched {len(price_df):,} new price records for {success_count} tickers")
            return price_df

        print(f"   [WARN]  No new price data fetched")
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
            print(f"   [OK] Fetched {len(price_df):,} price records (legacy) for {len(buffer)} tickers")
            return price_df
        print(f"   [WARN]  No price data fetched")
        return pd.DataFrame()

    @staticmethod
    def _merge_statement_types(df: pd.DataFrame) -> pd.DataFrame:
        """Consolidate 3 statement-type rows per quarter into 1 merged row.

        FMP returns separate rows for income/balance_sheet/cash_flow that share
        the same (ticker, fiscal_date, fiscal_period). Each metric is non-null
        in only one statement type, so first-non-null correctly consolidates.
        """
        group_cols = ['ticker', 'fiscal_date', 'fiscal_period']
        available_group = [c for c in group_cols if c in df.columns]
        if not available_group:
            return df

        # first() picks first non-null per group for each column
        return df.groupby(available_group, as_index=False).first()

    def _fetch_fundamentals(self, tickers: List[str], force: bool = False) -> pd.DataFrame:
        """
        Fetch fundamental data from FMP API, buffer in memory.
        Uses earnings calendar intelligence to reduce API calls by 90-95%.

        Returns:
            DataFrame with normalized fundamental data
        """
        print("   [FETCH] Fundamental data (using earnings calendar)...")

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

            # Merge 3 statement-type rows → 1 row per (ticker, fiscal_date, fiscal_period)
            fund_df = self._merge_statement_types(fund_df)

            # Normalize to match DuckDB schema
            fund_df = fund_df.rename(columns={
                'fiscal_date': 'report_date',
                'fiscal_period': 'period_type',
                'fiscalYear': 'fiscal_year',
                'netIncome': 'net_income',
                'epsDiluted': 'eps_diluted',
                'totalAssets': 'total_assets',
                'totalEquity': 'total_equity',
                'operatingCashFlow': 'operating_cash_flow',
                'totalDebt': 'total_debt',
                'freeCashFlow': 'free_cash_flow',
                'grossProfit': 'gross_profit',
                'operatingIncome': 'operating_income',
                'totalCurrentAssets': 'total_current_assets',
                'totalCurrentLiabilities': 'total_current_liabilities',
            })

            # Select only columns that exist in DuckDB table
            duckdb_columns = [
                'ticker', 'report_date', 'filing_date', 'period_type', 'fiscal_year',
                'revenue', 'net_income', 'eps_diluted', 'total_assets', 'total_equity',
                'operating_cash_flow',
                'total_debt', 'free_cash_flow', 'gross_profit', 'operating_income',
                'total_current_assets', 'total_current_liabilities', 'inventory'
            ]

            # Keep only columns that exist in both
            available_cols = [c for c in duckdb_columns if c in fund_df.columns]
            fund_df = fund_df[available_cols]

            print(f"   [OK] Fetched {len(fund_df):,} fundamental records for {success_count} tickers")
            return fund_df
        else:
            print(f"   [WARN]  No fundamental data fetched")
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
        print(f"   [FETCH] Fundamental data (prioritized queue, limit={daily_limit})...")

        # Build queue
        queue_df = self.queue_manager.build_fetch_queue(tickers, data_type='fundamentals')

        # Get today's batch
        today_batch = self.queue_manager.fetch_daily_batch(queue_df, daily_limit=daily_limit)

        print(f"   Queue status:")
        print(f"      Total universe: {len(tickers)} tickers")
        print(f"      Fetching today: {len(today_batch)} tickers")
        print(f"      Never fetched: {len(queue_df[queue_df['priority_tier'] == 1])}")
        print(f"      Stale (>90 days): {len(queue_df[queue_df['priority_tier'] == 2])}")
        print(f"      Fresh (<90 days): {len(queue_df[queue_df['priority_tier'] == 3])}")

        # Fetch only today's batch
        return self._fetch_fundamentals(today_batch, force=False)

    def _fetch_profiles(self, tickers: List[str], force: bool = False) -> pd.DataFrame:
        """
        Fetch company profile data + shares outstanding, buffer in memory.

        Returns:
            DataFrame with company profiles matching DuckDB schema
        """
        print("   [FETCH] Company profiles...")

        # Reuse CompanyProfileEngine
        self.profile_engine.update_profiles_cache(
            tickers=tickers,
            force=force,
            max_workers=10
        )

        try:
            profiles_df = self.profile_engine.get_company_profiles(use_cache=True)
            if profiles_df.empty:
                print("   [WARN] No company profiles fetched")
                return pd.DataFrame()

            # Reset index (ticker is index in parquet cache)
            if profiles_df.index.name == 'ticker':
                profiles_df = profiles_df.reset_index()

            profiles_df = profiles_df[profiles_df['ticker'].isin(tickers)]

            # Rename camelCase → snake_case to match DuckDB schema
            profiles_df = profiles_df.rename(columns={
                'companyName': 'name',
                'mktCap': 'market_cap',
                'ipoDate': 'listing_date',
            })

            # Coerce listing_date: empty strings → None, then to proper date
            if 'listing_date' in profiles_df.columns:
                profiles_df['listing_date'] = profiles_df['listing_date'].replace('', pd.NaT)
                profiles_df['listing_date'] = pd.to_datetime(
                    profiles_df['listing_date'], errors='coerce'
                ).dt.date

            # Fetch shares outstanding from Yahoo Finance
            print("   [FETCH] Shares outstanding (Yahoo Finance)...")
            shares_df = self.profile_engine.fetch_shares_float(tickers)
            if not shares_df.empty:
                profiles_df = profiles_df.merge(shares_df, on='ticker', how='left')
                filled = shares_df['shares_outstanding'].notna().sum()
                print(f"   [OK] Shares data for {filled}/{len(tickers)} tickers")

            # Add defaults
            if 'is_active' not in profiles_df.columns:
                profiles_df['is_active'] = True

            # Keep only columns that match DuckDB schema
            db_cols = [
                'ticker', 'name', 'sector', 'industry', 'market_cap',
                'country', 'exchange', 'is_active', 'listing_date',
                'shares_outstanding', 'float_shares',
            ]
            profiles_df = profiles_df[[c for c in db_cols if c in profiles_df.columns]]

            print(f"   [OK] Fetched {len(profiles_df)} company profiles")
            return profiles_df

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
        print("   [FETCH] Macro data (FRED + VIX)...")

        # Check cache staleness (macro data doesn't need daily updates)
        if not force:
            cache_fresh = self._is_macro_cache_fresh()
            if cache_fresh:
                print("   [INFO]  Macro cache is fresh (<24h old), using cached data...")
                try:
                    macro_df = self.macro_engine.get_all_macro_data()
                    if macro_df is not None and not macro_df.empty:
                        # Transform to narrow format
                        narrow_rows = []
                        for col in macro_df.columns:
                            series_data = macro_df[[col]].reset_index()
                            series_data.columns = ['date', 'close']
                            series_data['symbol'] = col
                            series_data['volume'] = None
                            series_data['value'] = None
                            series_data['unit'] = None
                            narrow_rows.append(series_data)
                        macro_narrow = pd.concat(narrow_rows, ignore_index=True)
                        print(f"   [OK] Loaded {len(macro_narrow):,} cached macro observations")
                        return macro_narrow
                except Exception as e:
                    logger.warning(f"Failed to load cached macro data: {e}")

        # Update macro cache (API calls)
        self.macro_engine.update_macro_cache(force=force)

        # Collect macro data (wide format)
        try:
            macro_df = self.macro_engine.get_all_macro_data()
            if macro_df is not None and not macro_df.empty:
                # Transform from wide to narrow format for DuckDB table
                # Table schema: (date, symbol, close, volume, value, unit)
                narrow_rows = []
                for col in macro_df.columns:
                    series_data = macro_df[[col]].reset_index()
                    series_data.columns = ['date', 'close']
                    series_data['symbol'] = col
                    series_data['volume'] = None
                    series_data['value'] = None
                    series_data['unit'] = None
                    narrow_rows.append(series_data)

                macro_narrow = pd.concat(narrow_rows, ignore_index=True)
                print(f"   [OK] Fetched {len(macro_narrow):,} macro observations ({len(macro_df.columns)} series)")
                return macro_narrow
            else:
                print(f"   [WARN]  No macro data fetched")
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
                        volume = EXCLUDED.volume,
                        updated_at = NOW()
                """)
                print(f"   [OK] Wrote {row_count:,} price records to DuckDB")

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
                        {update_str},
                        updated_at = NOW()
                """)
                print(f"   [OK] Wrote {row_count:,} fundamental records to DuckDB")

                # Compute ratio columns for newly inserted/updated fundamentals
                print(f"   [COMPUTE] Calculating market_cap and valuation ratios...")
                con.execute("""
                    WITH recent_fundamentals AS (
                        SELECT ticker, report_date, period_type, revenue, net_income, total_equity
                        FROM fundamentals_buffer
                    ),
                    with_closest_price AS (
                        SELECT
                            f.ticker, f.report_date, f.period_type, f.revenue, f.net_income, f.total_equity,
                            p.date as price_date, p.close,
                            ROW_NUMBER() OVER (
                                PARTITION BY f.ticker, f.report_date, f.period_type
                                ORDER BY ABS(EPOCH(f.report_date) - EPOCH(p.date))
                            ) as rn
                        FROM recent_fundamentals f
                        LEFT JOIN price_data p ON f.ticker = p.ticker
                            AND p.date BETWEEN f.report_date - INTERVAL '7 days'
                                           AND f.report_date + INTERVAL '7 days'
                    ),
                    with_shares AS (
                        SELECT
                            wp.ticker, wp.report_date, wp.period_type, wp.price_date, wp.close,
                            wp.revenue, wp.net_income, wp.total_equity,
                            s.shares_outstanding,
                            ROW_NUMBER() OVER (
                                PARTITION BY wp.ticker, wp.price_date
                                ORDER BY s.date DESC
                            ) as shares_rn
                        FROM with_closest_price wp
                        LEFT JOIN shares_history s ON wp.ticker = s.ticker AND s.date <= wp.price_date
                        WHERE wp.rn = 1
                    ),
                    with_market_cap AS (
                        SELECT
                            ticker, report_date, period_type,
                            close * shares_outstanding as market_cap,
                            close * shares_outstanding / NULLIF(net_income, 0) as pe_ratio,
                            close * shares_outstanding / NULLIF(revenue, 0) as ps_ratio,
                            close * shares_outstanding / NULLIF(total_equity, 0) as pb_ratio
                        FROM with_shares
                        WHERE shares_rn = 1 AND close IS NOT NULL AND shares_outstanding IS NOT NULL
                    ),
                    with_growth AS (
                        SELECT
                            mc.*, ff.eps_growth_yoy,
                            CASE WHEN ff.eps_growth_yoy > 0 THEN mc.pe_ratio / ff.eps_growth_yoy ELSE NULL END as peg_ratio
                        FROM with_market_cap mc
                        LEFT JOIN fundamental_features ff ON mc.ticker = ff.ticker AND mc.report_date = ff.fiscal_date
                    )
                    UPDATE fundamentals f
                    SET market_cap = wg.market_cap, pe_ratio = wg.pe_ratio,
                        ps_ratio = wg.ps_ratio, pb_ratio = wg.pb_ratio, peg_ratio = wg.peg_ratio
                    FROM with_growth wg
                    WHERE f.ticker = wg.ticker AND f.report_date = wg.report_date AND f.period_type = wg.period_type
                """)
                ratio_count = con.execute("SELECT COUNT(*) FROM fundamentals_buffer WHERE ticker IN (SELECT DISTINCT ticker FROM fundamentals_buffer)").fetchone()[0]
                print(f"   [OK] Updated ratios for {ratio_count:,} records")

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
                        {update_str},
                        updated_at = NOW()
                """)
                print(f"   [OK] Wrote {row_count:,} company profiles to DuckDB")

            # 4. Macro Data
            if not macro_buffer.empty:
                row_count = len(macro_buffer)
                cols = macro_buffer.columns.tolist()
                col_str = ', '.join(cols)
                update_str = ', '.join([f"{c} = EXCLUDED.{c}" for c in cols if c not in ['symbol', 'date']])

                con.execute(f"""
                    INSERT INTO macro_data ({col_str})
                    SELECT {col_str}
                    FROM macro_buffer
                    ON CONFLICT (symbol, date) DO UPDATE SET
                        {update_str}
                """)
                print(f"   [OK] Wrote {row_count:,} macro observations to DuckDB")

            con.execute("COMMIT")
            print("   [OK] Transaction committed")

        except Exception as e:
            con.execute("ROLLBACK")
            logger.error(f"DuckDB write failed: {e}")
            print(f"   [ERROR] Transaction rolled back: {e}")
            raise
        finally:
            con.close()

    def _compute_features_incremental(
        self,
        start_date: str = '2020-01-01',
        warmup_days: int = 365,
        skip_t3: bool = False
    ):
        """
        Delegate feature computation to FeaturePipeline (T2 + T3).

        Args:
            start_date: Start date for feature computation
            warmup_days: Days before start_date to fetch for lookback windows
            skip_t3: If True, skip T3 SEPA features (default: False)
        """
        pipeline = FeaturePipeline(self.db_path)
        pipeline.compute_all(
            start_date=start_date,
            warmup_days=warmup_days,
            skip_t3=skip_t3
        )

    def _compute_fundamental_features(self, tickers: List[str] = None):  # noqa: ARG002
        """Compute fundamental features from DuckDB fundamentals table using SQL window functions.

        Full rebuild from `fundamentals` table. The `tickers` param is kept for
        interface compatibility but the SQL always rebuilds the entire table.
        """
        import time as _t
        t0 = _t.perf_counter()

        con = duckdb.connect(self.db_path)
        try:
            sql = """
            CREATE OR REPLACE TABLE fundamental_features AS
            WITH base AS (
                SELECT ticker, report_date, filing_date,
                       period_type AS fiscal_period, fiscal_year,
                       report_date AS fiscal_date,
                       revenue, net_income, eps_diluted, total_assets, total_equity,
                       total_debt, operating_cash_flow, free_cash_flow, gross_profit,
                       operating_income, total_current_assets, total_current_liabilities, inventory
                FROM fundamentals
                WHERE period_type IN ('Q1','Q2','Q3','Q4')
            ),
            growth AS (
                SELECT *,
                    (revenue / NULLIF(LAG(revenue, 4) OVER w, 0) - 1) * 100 AS revenue_growth_yoy,
                    (eps_diluted / NULLIF(LAG(eps_diluted, 4) OVER w, 0) - 1) * 100 AS eps_growth_yoy,
                    (net_income / NULLIF(LAG(net_income, 4) OVER w, 0) - 1) * 100 AS net_income_growth_yoy,
                    CASE WHEN LAG(revenue, 12) OVER w > 0 AND revenue > 0
                         THEN (POWER(revenue / LAG(revenue, 12) OVER w, 1.0/3) - 1) * 100 END AS revenue_cagr_3y,
                    (inventory / NULLIF(LAG(inventory, 4) OVER w, 0) - 1) * 100 AS inventory_growth_yoy
                FROM base
                WINDOW w AS (PARTITION BY ticker ORDER BY fiscal_date)
            ),
            accel AS (
                SELECT *,
                    eps_growth_yoy - LAG(eps_growth_yoy, 1) OVER w AS eps_accel,
                    revenue_growth_yoy - LAG(revenue_growth_yoy, 1) OVER w AS revenue_accel,
                    inventory_growth_yoy - revenue_growth_yoy AS inventory_vs_sales_spread,
                    STDDEV(eps_growth_yoy) OVER (PARTITION BY ticker ORDER BY fiscal_date
                        ROWS BETWEEN 7 PRECEDING AND CURRENT ROW) AS eps_stability_score
                FROM growth
                WINDOW w AS (PARTITION BY ticker ORDER BY fiscal_date)
            ),
            metrics AS (
                SELECT *,
                    total_debt / NULLIF(total_equity, 0) AS debt_to_equity,
                    total_current_assets / NULLIF(total_current_liabilities, 0) AS current_ratio,
                    (total_current_assets - COALESCE(inventory, 0)) / NULLIF(total_current_liabilities, 0) AS quick_ratio,
                    (gross_profit / NULLIF(revenue, 0)) * 100 AS gross_margin,
                    (operating_income / NULLIF(revenue, 0)) * 100 AS operating_margin,
                    (net_income / NULLIF(revenue, 0)) * 100 AS net_margin,
                    (net_income / NULLIF(total_equity, 0)) * 100 AS roe,
                    (net_income / NULLIF(total_assets, 0)) * 100 AS roa,
                    (free_cash_flow / NULLIF(revenue, 0)) * 100 AS fcf_margin,
                    operating_cash_flow / NULLIF(net_income, 0) AS earnings_quality_score
                FROM accel
            )
            SELECT *,
                gross_margin - AVG(gross_margin) OVER (PARTITION BY ticker ORDER BY fiscal_date
                    ROWS BETWEEN 4 PRECEDING AND 1 PRECEDING) AS gross_margin_trend,
                'v2.0' AS feature_version,
                CURRENT_TIMESTAMP AS updated_at
            FROM metrics
            """
            con.execute(sql)

            row_count = con.execute("SELECT COUNT(*) FROM fundamental_features").fetchone()[0]
            elapsed = _t.perf_counter() - t0
            print(f"   [OK] Computed {row_count:,} fundamental feature records via SQL ({elapsed:.1f}s)")

        except Exception as e:
            logger.error(f"Fundamental feature computation failed: {e}")
            print(f"   [ERROR] Fundamental feature computation failed: {e}")
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
        print(f"   [OK] Using {len(tickers)} custom tickers")
        return tickers

    source_map = {
        'price_folder': 'PRICE_FOLDER',
        'fmp_screener': 'FMP_SCREENER',
        'sp500': 'SSGA'
    }

    data_repo = DataRepository()
    tickers = data_repo.update_universe(source=source_map.get(source, 'PRICE_FOLDER'))
    print(f"   [OK] Loaded {len(tickers)} tickers from {source}")
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
    parser.add_argument('--update-shares', action='store_true',
                        help="Update shares_history table (incremental). Use with --force for full backfill.")
    parser.add_argument('--update-all', action='store_true', help="Update all data types")

    # Feature computation
    parser.add_argument('--update-features', action='store_true',
                        help="Recompute T2/T3 feature tables (no API fetch).")
    parser.add_argument('--recompute', action='store_true',
                        help="Force full feature rebuild from 2020-01-01 (use after schema changes)")
    parser.add_argument('--incremental', action='store_true',
                        help="Force incremental feature update (last 252 days). This is the default.")
    parser.add_argument('--skip-t3', action='store_true',
                        help="Skip T3 SEPA features computation (for testing or manual backfill)")

    parser.add_argument('--start-date', type=str, default='2020-01-01',
                        help="Start date for feature computation (YYYY-MM-DD). Defaults to 2020-01-01 to ensure full history.")
    parser.add_argument('--warmup-days', type=int, default=365,
                        help="Days of history to load before start_date for window functions (default: 365)")

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
    update_shares = args.update_shares or args.update_all
    update_features_only = args.update_features
    recompute = args.recompute
    incremental = not recompute  # Incremental is default unless recompute is forced

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
        update_shares=update_shares,
        update_features_only=update_features_only,
        recompute=recompute,
        force=args.force,
        daily_limit=args.daily_limit,
        start_date=args.start_date,
        warmup_days=args.warmup_days,
        incremental=incremental,
        skip_t3=args.skip_t3
    )
