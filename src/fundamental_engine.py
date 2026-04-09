"""
Fundamental Engine - FundamentalEngine Class

Two sources:
  source='yfinance' (default): Fetches IS/BS/CF from yfinance, stores in DuckDB fundamentals table.
  source='fmp'               : Legacy FMP API path, stores in parquet cache.

The merger and downstream code call get_ticker_fundamentals() — which reads from DuckDB
when source='yfinance', from parquet when source='fmp'.
"""

import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import duckdb
import pandas as pd
import yfinance as yf

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL))
logger = logging.getLogger(__name__)

# yfinance column → DuckDB column mapping for income statement
_INCOME_MAP = {
    'TotalRevenue':                    'total_revenue',
    'CostOfRevenue':                   'cost_of_revenue',
    'GrossProfit':                     'gross_profit',
    'OperatingIncome':                 'operating_income',
    'OperatingExpense':                'operating_expense',
    'EBIT':                            'ebit',
    'EBITDA':                          'ebitda',
    'NetIncome':                       'net_income',
    'BasicEPS':                        'basic_eps',
    'DilutedEPS':                      'diluted_eps',
    'BasicAverageShares':              'basic_avg_shares',
    'DilutedAverageShares':            'diluted_avg_shares',
    'ResearchAndDevelopment':          'r_and_d',
    'SellingGeneralAndAdministration': 'sga',
    'TaxProvision':                    'tax_provision',
}

# yfinance column → DuckDB column mapping for balance sheet
_BALANCE_MAP = {
    'TotalAssets':          'total_assets',
    'CurrentAssets':        'current_assets',
    'CashAndCashEquivalents': 'cash_and_equivalents',
    'Inventory':            'inventory',
    'AccountsReceivable':   'accounts_receivable',
    'TotalDebt':            'total_debt',
    'NetDebt':              'net_debt',
    'CurrentLiabilities':   'current_liabilities',
    'LongTermDebt':         'long_term_debt',
    'StockholdersEquity':   'stockholders_equity',
    'RetainedEarnings':     'retained_earnings',
    'WorkingCapital':       'working_capital',
    'InvestedCapital':      'invested_capital',
    'TangibleBookValue':    'tangible_book_value',
}

# yfinance column → DuckDB column mapping for cash flow
_CASHFLOW_MAP = {
    'OperatingCashFlow':        'operating_cash_flow',
    'FreeCashFlow':             'free_cash_flow',
    'CapitalExpenditure':       'capex',
    'StockBasedCompensation':   'stock_based_comp',
    'ChangeInWorkingCapital':   'change_in_working_capital',
    'DepreciationAndAmortization': 'depreciation_amortization',
}

# All DuckDB fundamental columns (excluding PK + metadata)
_ALL_FUNDAMENTAL_COLS = list(_INCOME_MAP.values()) + list(_BALANCE_MAP.values()) + list(_CASHFLOW_MAP.values())


class FundamentalEngine:
    """
    Manages fundamental data.

    source='yfinance': fetches from yfinance API, persists to DuckDB fundamentals table.
    source='fmp':      legacy FMP API path, persists to parquet cache.
    """

    def __init__(
        self,
        db_path: str = None,
        source: str = 'yfinance',
        # Legacy FMP params (ignored when source='yfinance')
        api_key: str = None,
        fundamentals_dir: Path = None,
        force_cache_only: bool = False,
    ):
        self.source = source
        self.db_path = str(db_path) if db_path else str(
            Path(__file__).parent.parent / "data" / "market_data.duckdb"
        )
        self.last_errors: List[Tuple[str, Optional[str]]] = []

        if source == 'yfinance':
            self._ensure_tables()

        elif source == 'fmp':
            # Legacy FMP init
            import requests, json
            self.api_key = api_key or config.FMP_API_KEY
            if not self.api_key and not force_cache_only:
                raise ValueError("FMP_API_KEY required for source='fmp'.")
            self.fundamentals_dir = fundamentals_dir or config.FUNDAMENTALS_DIR
            self.fundamentals_dir.mkdir(parents=True, exist_ok=True)
            self.base_url = config.FMP_BASE_URL
            self.cache_days = config.FUNDAMENTAL_CACHE_DAYS
            self.lookback_years = config.FUNDAMENTAL_LOOKBACK_YEARS
            self.rate_limit = config.FMP_FUNDAMENTAL_RATE_LIMIT
            self.batch_size = config.FMP_FUNDAMENTAL_BATCH_SIZE
            self.batch_delay = config.FMP_FUNDAMENTAL_BATCH_DELAY
            self.force_cache_only = force_cache_only
            self._call_timestamps = []
            self._rate_limit_lock = threading.Lock()
            self._quota_exhausted = False
            self._quota_lock = threading.Lock()

        else:
            raise ValueError(f"Unknown source: {source!r}. Use 'yfinance' or 'fmp'.")

    # =========================================================================
    # yfinance: Schema
    # =========================================================================

    def _ensure_tables(self) -> None:
        """Create fundamentals and earnings_calendar tables if not exist."""
        conn = duckdb.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fundamentals (
                    ticker              VARCHAR NOT NULL,
                    period_end          DATE    NOT NULL,
                    filing_date         DATE,
                    -- Earnings estimates (from get_earnings_dates)
                    eps_estimate        DOUBLE,
                    reported_eps        DOUBLE,
                    eps_surprise_pct    DOUBLE,
                    -- Income Statement
                    total_revenue       DOUBLE,
                    cost_of_revenue     DOUBLE,
                    gross_profit        DOUBLE,
                    operating_income    DOUBLE,
                    operating_expense   DOUBLE,
                    ebit                DOUBLE,
                    ebitda              DOUBLE,
                    net_income          DOUBLE,
                    basic_eps           DOUBLE,
                    diluted_eps         DOUBLE,
                    basic_avg_shares    DOUBLE,
                    diluted_avg_shares  DOUBLE,
                    r_and_d             DOUBLE,
                    sga                 DOUBLE,
                    tax_provision       DOUBLE,
                    -- Balance Sheet
                    total_assets        DOUBLE,
                    current_assets      DOUBLE,
                    cash_and_equivalents DOUBLE,
                    inventory           DOUBLE,
                    accounts_receivable DOUBLE,
                    total_debt          DOUBLE,
                    net_debt            DOUBLE,
                    current_liabilities DOUBLE,
                    long_term_debt      DOUBLE,
                    stockholders_equity DOUBLE,
                    retained_earnings   DOUBLE,
                    working_capital     DOUBLE,
                    invested_capital    DOUBLE,
                    tangible_book_value DOUBLE,
                    -- Cash Flow
                    operating_cash_flow DOUBLE,
                    free_cash_flow      DOUBLE,
                    capex               DOUBLE,
                    stock_based_comp    DOUBLE,
                    change_in_working_capital DOUBLE,
                    depreciation_amortization DOUBLE,
                    -- Metadata
                    source              VARCHAR DEFAULT 'yfinance',
                    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (ticker, period_end)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS earnings_calendar (
                    ticker              VARCHAR NOT NULL,
                    earnings_date       DATE    NOT NULL,
                    eps_estimate        DOUBLE,
                    reported_eps        DOUBLE,
                    eps_surprise_pct    DOUBLE,
                    is_confirmed        BOOLEAN DEFAULT FALSE,
                    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (ticker, earnings_date)
                )
            """)
            logger.debug("[FundamentalEngine] DuckDB tables ready (fundamentals, earnings_calendar)")
        finally:
            conn.close()

    # =========================================================================
    # yfinance: Fetch helpers
    # =========================================================================

    def _fetch_from_yfinance(self, ticker: str) -> Optional[pd.DataFrame]:
        """
        Fetch IS + BS + CF + earnings dates from yfinance for one ticker.

        Returns a DataFrame indexed by period_end with filing_date mapped,
        or None on failure.
        """
        try:
            t = yf.Ticker(ticker)
            income   = t.get_income_stmt(freq='quarterly')
            balance  = t.get_balance_sheet(freq='quarterly')
            cashflow = t.get_cashflow(freq='quarterly')
        except Exception as e:
            logger.warning(f"[FundamentalEngine] yfinance fetch failed for {ticker}: {e}")
            return None
        finally:
            time.sleep(0.5)  # Yahoo rate limit: ~2 req/s per thread

        try:
            earnings_dates = t.get_earnings_dates(limit=40)
        except Exception:
            earnings_dates = None

        if income is None or income.empty:
            logger.debug(f"[FundamentalEngine] No yfinance income data for {ticker}")
            return None

        # Transpose: columns become period_end index
        income   = income.T
        balance  = balance.T if (balance is not None and not balance.empty) else pd.DataFrame()
        cashflow = cashflow.T if (cashflow is not None and not cashflow.empty) else pd.DataFrame()

        # Map period_end → filing_date
        period_ends = income.index.tolist()
        filing_map  = self._map_period_end_to_filing_date(period_ends, earnings_dates)

        rows = []
        for pe in period_ends:
            row: Dict = {'period_end': pd.Timestamp(pe).date(), 'period_type': 'quarterly'}
            row['filing_date'] = filing_map.get(pd.Timestamp(pe), pd.NaT)
            if pd.isna(row['filing_date']):
                row['filing_date'] = None

            # Income statement
            for yf_col, db_col in _INCOME_MAP.items():
                row[db_col] = _safe_float(income, pe, yf_col)

            # Derive operating_income from components (gross_profit - sga - r_and_d).
            # Cross-validation shows yfinance's headline OperatingIncome is inconsistent:
            #   - sometimes strips non-recurring charges (adjusted, not GAAP)
            #   - sometimes maps to a different XBRL tag than expected
            # The component-derived figure is arithmetically stable and matches
            # the component fields exactly in 82% of cases vs FMP.
            # Fall back to the raw yfinance value only when components are missing.
            gp   = row.get('gross_profit')
            sga  = row.get('sga')
            rd   = row.get('r_and_d') or 0.0
            if gp is not None and sga is not None:
                row['operating_income'] = gp - sga - rd

            # Balance sheet
            for yf_col, db_col in _BALANCE_MAP.items():
                row[db_col] = _safe_float(balance, pe, yf_col)

            # Cash flow
            for yf_col, db_col in _CASHFLOW_MAP.items():
                row[db_col] = _safe_float(cashflow, pe, yf_col)

            rows.append(row)

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df['ticker'] = ticker
        df['source'] = 'yfinance'
        return df

    def _map_period_end_to_filing_date(
        self,
        period_ends: List,
        earnings_dates_df: Optional[pd.DataFrame],
    ) -> Dict[pd.Timestamp, pd.Timestamp]:
        """
        Map fiscal period end dates to actual announcement dates.

        Rule: filing_date = first earnings date strictly AFTER period_end, within 90 days.
        """
        if earnings_dates_df is None or earnings_dates_df.empty:
            return {}

        mapping: Dict[pd.Timestamp, pd.Timestamp] = {}
        ed_dates = pd.to_datetime(earnings_dates_df.index).tz_localize(None).sort_values()

        for pe in sorted(period_ends):
            pe_ts = pd.Timestamp(pe).tz_localize(None)
            candidates = ed_dates[
                (ed_dates > pe_ts) & (ed_dates <= pe_ts + pd.Timedelta(days=90))
            ]
            if len(candidates):
                mapping[pe_ts] = candidates[0]

        return mapping

    # =========================================================================
    # yfinance: DuckDB persistence
    # =========================================================================

    def _upsert_to_duckdb(
        self,
        ticker: str,
        df: pd.DataFrame,
        conn: duckdb.DuckDBPyConnection = None,
    ) -> int:
        """UPSERT fundamental rows for one ticker. Accepts shared conn to avoid re-opening."""
        if df is None or df.empty:
            return 0

        df = df.copy()
        df['updated_at'] = datetime.utcnow()

        all_cols = ['ticker', 'period_end', 'period_type', 'filing_date'] + _ALL_FUNDAMENTAL_COLS + ['source', 'updated_at']
        for col in all_cols:
            if col not in df.columns:
                df[col] = None
        df = df[all_cols]

        set_clause = ',\n                    '.join(
            f'{c} = EXCLUDED.{c}'
            for c in all_cols
            if c not in ('ticker', 'period_end')
        )
        col_list = ', '.join(all_cols)
        # Never overwrite FMP rows with yfinance data — FMP is the authoritative backfill source.
        sql = f"""
            INSERT INTO fundamentals ({col_list})
            SELECT {col_list} FROM _fund_batch
            ON CONFLICT (ticker, period_end) DO UPDATE SET
                {set_clause}
            WHERE fundamentals.source != 'fmp'
        """

        own_conn = conn is None
        if own_conn:
            conn = duckdb.connect(self.db_path)
        try:
            conn.register('_fund_batch', df)
            conn.execute(sql)
            return len(df)
        finally:
            if own_conn:
                conn.close()

    # =========================================================================
    # yfinance: Earnings calendar
    # =========================================================================

    def _get_tickers_needing_earnings_refresh(self, tickers: List[str]) -> List[str]:
        """Return tickers that don't already have a known future unconfirmed earnings date."""
        conn = duckdb.connect(self.db_path, read_only=True)
        try:
            conn.register('_all_tickers', pd.DataFrame({'ticker': tickers}))
            rows = conn.execute("""
                SELECT t.ticker
                FROM _all_tickers t
                WHERE t.ticker NOT IN (
                    SELECT DISTINCT ticker FROM earnings_calendar
                    WHERE NOT is_confirmed AND earnings_date > CURRENT_DATE
                )
            """).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    def refresh_earnings_calendar(self, tickers: List[str], max_workers: int = 8) -> int:
        """
        Refresh upcoming earnings dates for tickers missing a future earnings date.

        Skips tickers that already have a known future unconfirmed earnings date
        in the calendar (no need to re-fetch). Fetches in parallel (network I/O),
        then writes sequentially with a single DuckDB connection.
        Returns total rows written.
        """
        # Filter to tickers that actually need a refresh
        tickers_to_fetch = self._get_tickers_needing_earnings_refresh(tickers)
        skipped = len(tickers) - len(tickers_to_fetch)
        logger.debug(f"Earnings calendar: {len(tickers_to_fetch)} to refresh, {skipped} skipped")
        if not tickers_to_fetch:
            return 0

        errors = 0

        def _fetch_one(ticker: str) -> Optional[pd.DataFrame]:
            nonlocal errors
            try:
                t = yf.Ticker(ticker)
                ed = t.get_earnings_dates(limit=10)
                if ed is None or ed.empty:
                    return None

                rows = []
                for dt, row in ed.iterrows():
                    dt_clean = pd.Timestamp(dt).tz_localize(None).date()
                    # Only keep confirmed (reported) earnings rows
                    if not pd.notna(row.get('Reported EPS')):
                        continue
                    rows.append({
                        'ticker':           ticker,
                        'earnings_date':    dt_clean,
                        'eps_estimate':     _nan_to_none(row.get('EPS Estimate')),
                        'reported_eps':     _nan_to_none(row.get('Reported EPS')),
                        'eps_surprise_pct': _nan_to_none(row.get('Surprise(%)')),
                        'is_confirmed':     True,
                        'updated_at':       datetime.utcnow(),
                    })
                return pd.DataFrame(rows) if rows else None

            except Exception as e:
                errors += 1
                logger.debug(f"[FundamentalEngine] earnings fetch failed for {ticker}: {e}")
                return None

        # Phase 1: Parallel fetch (network I/O only, no DB access)
        fetched: List[pd.DataFrame] = []
        done = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_one, t): t for t in tickers_to_fetch}
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    fetched.append(result)
                done += 1
                if done % 500 == 0:
                    logger.debug(f"Earnings calendar progress: {done}/{len(tickers_to_fetch)}")

        if not fetched:
            return 0

        # Phase 2: Sequential write (single DuckDB connection)
        combined = pd.concat(fetched, ignore_index=True)
        total = len(combined)
        conn = duckdb.connect(self.db_path)
        try:
            conn.register('_ec_batch', combined)
            conn.execute("""
                INSERT INTO earnings_calendar
                SELECT * FROM _ec_batch
                ON CONFLICT (ticker, earnings_date) DO UPDATE SET
                    eps_estimate     = EXCLUDED.eps_estimate,
                    reported_eps     = EXCLUDED.reported_eps,
                    eps_surprise_pct = EXCLUDED.eps_surprise_pct,
                    is_confirmed     = EXCLUDED.is_confirmed,
                    updated_at       = EXCLUDED.updated_at
            """)
            conn.commit()
        finally:
            conn.close()

        logger.debug(f"Earnings calendar: {total} rows upserted across {len(fetched)} tickers")
        return total

    def _get_stale_fundamental_tickers(self, tickers: List[str], max_age_days: int = 90) -> List[str]:
        """Return tickers with no fundamentals row newer than max_age_days."""
        conn = duckdb.connect(self.db_path)
        try:
            conn.register('_ticker_list', pd.DataFrame({'ticker': tickers}))
            rows = conn.execute(f"""
                SELECT tl.ticker
                FROM _ticker_list tl
                LEFT JOIN (
                    SELECT ticker, MAX(updated_at) AS last_update
                    FROM fundamentals
                    GROUP BY ticker
                ) f ON tl.ticker = f.ticker
                WHERE f.last_update IS NULL
                   OR f.last_update < CURRENT_TIMESTAMP - INTERVAL {int(max_age_days)} DAY
                ORDER BY tl.ticker
            """).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    def get_tickers_with_pending_earnings(self, target_date: str) -> List[str]:
        """
        Return tickers with unconfirmed earnings on or before target_date.

        These are the tickers that need a fundamental data pull today.
        """
        conn = duckdb.connect(self.db_path)
        try:
            rows = conn.execute("""
                SELECT DISTINCT ticker
                FROM earnings_calendar
                WHERE earnings_date <= ?
                  AND is_confirmed = FALSE
                ORDER BY ticker
            """, [target_date]).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    # =========================================================================
    # yfinance: Main update entry point
    # =========================================================================

    def update_fundamentals(
        self,
        tickers: List[str],
        target_date: str = None,
        max_workers: int = 8,
        force: bool = False,
    ) -> Dict[str, bool]:
        """
        Update fundamentals for tickers that have pending earnings as of target_date.

        Strategy (per plan section 3.4):
          1. Check earnings_calendar for tickers with unconfirmed earnings <= today.
          2. Fetch IS + BS + CF from yfinance for those tickers only.
          3. UPSERT into fundamentals table + mark earnings_calendar confirmed.

        force=True fetches all tickers regardless of earnings calendar.
        """
        if target_date is None:
            target_date = datetime.now().strftime('%Y-%m-%d')

        if force:
            to_fetch = tickers
            reason = "force"
        else:
            pending = set(self.get_tickers_with_pending_earnings(target_date))
            to_fetch = [t for t in tickers if t in pending]

            if not to_fetch:
                stale = set(self._get_stale_fundamental_tickers(tickers, max_age_days=90))
                to_fetch = [t for t in tickers if t in stale]
                reason = "staleness (>90d)" if to_fetch else None
            else:
                reason = "pending earnings"

        if not to_fetch:
            logger.debug(f"Fundamentals: all {len(tickers)} tickers up-to-date")
            return {t: True for t in tickers}

        logger.debug(f"Fundamentals: {len(to_fetch)}/{len(tickers)} to fetch ({reason})")

        results: Dict[str, bool] = {}
        fetched: Dict[str, object] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self._fetch_from_yfinance, t): t for t in to_fetch}
            done = 0
            for future in as_completed(futures):
                ticker = futures[future]
                fetched[ticker] = future.result()
                done += 1
                if done % 100 == 0:
                    logger.debug(f"Fundamentals fetch progress: {done}/{len(to_fetch)}")

        conn = duckdb.connect(self.db_path)
        try:
            for ticker, df in fetched.items():
                if df is None:
                    results[ticker] = False
                    continue
                rows_written = self._upsert_to_duckdb(ticker, df, conn=conn)
                if rows_written > 0:
                    self._mark_earnings_confirmed(ticker, target_date, conn=conn)
                results[ticker] = rows_written > 0
            conn.commit()
        finally:
            conn.close()

        for t in tickers:
            if t not in results:
                results[t] = True

        self.last_errors = [
            (t, 'yfinance fetch returned None') for t, ok in results.items() if not ok
        ]

        return results

    def _mark_earnings_confirmed(
        self,
        ticker: str,
        target_date: str,
        conn: duckdb.DuckDBPyConnection = None,
    ) -> None:
        """Mark all unconfirmed earnings on or before target_date as confirmed."""
        own_conn = conn is None
        if own_conn:
            conn = duckdb.connect(self.db_path)
        try:
            conn.execute("""
                UPDATE earnings_calendar
                SET is_confirmed = TRUE, updated_at = CURRENT_TIMESTAMP
                WHERE ticker = ? AND earnings_date <= ? AND is_confirmed = FALSE
            """, [ticker, target_date])
        finally:
            if own_conn:
                conn.close()

    # =========================================================================
    # Shared read API (called by FundamentalMerger)
    # =========================================================================

    def get_ticker_fundamentals(self, ticker: str, use_cache: bool = True) -> Optional[pd.DataFrame]:
        """
        Load fundamental data for one ticker.

        source='yfinance': reads from DuckDB fundamentals table.
        source='fmp':      reads from parquet cache (legacy path).

        Returns a DataFrame with columns matching what FundamentalMerger expects:
          fiscal_date (period_end), filing_date, and all numeric columns.
        """
        if self.source == 'yfinance':
            return self._get_from_duckdb(ticker)
        else:
            return self._get_from_parquet(ticker, use_cache)

    def _get_from_duckdb(self, ticker: str) -> Optional[pd.DataFrame]:
        """Read fundamental rows for ticker from DuckDB, formatted for FundamentalMerger."""
        conn = duckdb.connect(self.db_path)
        try:
            df = conn.execute("""
                SELECT
                    period_end  AS fiscal_date,
                    filing_date,
                    *
                FROM fundamentals
                WHERE ticker = ?
                ORDER BY period_end DESC
            """, [ticker]).df()
        finally:
            conn.close()

        if df.empty:
            return None

        # Align to the column naming FundamentalMerger/Processor expect
        df['fiscal_date'] = pd.to_datetime(df['fiscal_date'])
        df['filing_date'] = pd.to_datetime(df['filing_date'])
        df['statement_type'] = 'combined'  # merged format — no separate statement rows

        return df

    # =========================================================================
    # Legacy FMP path (source='fmp') — unchanged
    # =========================================================================

    def update_fundamentals_cache(
        self,
        tickers: List[str],
        force: bool = False,
        show_progress: bool = True,
        max_workers: int = 10,
        use_earnings_calendar: bool = True,
    ) -> Dict[str, bool]:
        """
        Legacy FMP cache update. Only used when source='fmp'.
        """
        if self.source != 'fmp':
            raise RuntimeError("update_fundamentals_cache() requires source='fmp'")
        return self._fmp_update_cache(tickers, force, show_progress, max_workers, use_earnings_calendar)

    def _get_from_parquet(self, ticker: str, use_cache: bool) -> Optional[pd.DataFrame]:
        """Legacy: load from parquet cache."""
        cache_file = self.fundamentals_dir / f"{ticker}.parquet"

        if use_cache and cache_file.exists() and (self.force_cache_only or not self._is_cache_stale(cache_file)):
            try:
                return pd.read_parquet(cache_file)
            except Exception as e:
                logger.warning(f"Cache read failed for {ticker}: {e}")

        if self.force_cache_only:
            logger.warning(f"{ticker}: Cache-only mode but no cached data found")
            return None

        df = self._fmp_fetch_all(ticker)
        if df is not None and not df.empty:
            df['last_api_fetch_date'] = pd.Timestamp.now()
            try:
                df.to_parquet(cache_file)
            except Exception as e:
                logger.warning(f"Failed to cache {ticker}: {e}")
        return df

    def _is_cache_stale(self, file_path: Path) -> bool:
        if not file_path.exists():
            return True
        age_days = (datetime.now() - datetime.fromtimestamp(file_path.stat().st_mtime)).days
        return age_days >= self.cache_days

    def _rate_limit_check(self):
        with self._rate_limit_lock:
            now = time.time()
            self._call_timestamps = [ts for ts in self._call_timestamps if now - ts < 60]
            if len(self._call_timestamps) >= self.rate_limit:
                oldest = self._call_timestamps[0]
                sleep_time = 60.0 - (now - oldest) + 0.1
            else:
                sleep_time = 0
        if sleep_time > 0:
            time.sleep(sleep_time)
        with self._rate_limit_lock:
            now = time.time()
            self._call_timestamps = [ts for ts in self._call_timestamps if now - ts < 60]
            self._call_timestamps.append(now)

    def _fmp_fetch_statement(self, ticker: str, statement_type: str, max_retries: int = 2) -> Optional[pd.DataFrame]:
        import requests, json as json_mod

        with self._quota_lock:
            if self._quota_exhausted:
                return None

        url = f"{self.base_url}/{statement_type}"
        params = {'symbol': ticker, 'period': 'quarter', 'apikey': self.api_key, 'limit': 500}

        for attempt in range(max_retries):
            self._rate_limit_check()
            try:
                response = requests.get(url, params=params, timeout=30)
                if response.status_code == 429:
                    try:
                        msg = response.json().get('message', '').lower()
                    except Exception:
                        msg = ''
                    if any(k in msg for k in ['limit reached', 'quota', 'subscription', 'upgrade', 'plan']):
                        with self._quota_lock:
                            self._quota_exhausted = True
                        return None
                    if attempt < max_retries - 1:
                        time.sleep((2 ** attempt) * 10)
                        continue
                    return None
                response.raise_for_status()
                data = response.json()
                if not data or not isinstance(data, list):
                    return None
                df = pd.DataFrame(data)
                df['statement_type'] = 'income' if 'income' in statement_type else (
                    'cash_flow' if 'cash' in statement_type else 'balance_sheet'
                )
                return df
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep((2 ** attempt) * 3)
                    continue
                logger.error(f"FMP fetch failed {ticker} {statement_type}: {e}")
                return None
        return None

    def _fmp_fetch_all(self, ticker: str) -> Optional[pd.DataFrame]:
        import json as json_mod
        income   = self._fmp_fetch_statement(ticker, 'income-statement')
        balance  = self._fmp_fetch_statement(ticker, 'balance-sheet-statement')
        cashflow = self._fmp_fetch_statement(ticker, 'cash-flow-statement')
        parts = [df for df in [income, balance, cashflow] if df is not None]
        if not parts:
            return None
        combined = pd.concat(parts, axis=0, ignore_index=True)
        col_map = {
            'date': 'fiscal_date', 'filingDate': 'filing_date',
            'acceptedDate': 'accepted_date', 'period': 'fiscal_period',
            'calendarYear': 'fiscal_year',
        }
        combined = combined.rename(columns=col_map)
        combined['ticker'] = ticker
        for col in ['fiscal_date', 'filing_date', 'accepted_date']:
            if col in combined.columns:
                combined[col] = pd.to_datetime(combined[col], errors='coerce')
        return combined

    def _fmp_update_cache(self, tickers, force, show_progress, max_workers, use_earnings_calendar):
        """Internal FMP bulk update — same logic as original update_fundamentals_cache body."""
        results = {}
        to_fetch = []

        if force:
            to_fetch = tickers
        elif use_earnings_calendar:
            try:
                from src.earnings_engine import EarningsEngine
                earnings_engine = EarningsEngine()
                missing = [t for t in tickers if not (self.fundamentals_dir / f"{t}.parquet").exists()]
                if missing:
                    earnings_engine.update_earnings_cache(missing, force=False, max_workers=max_workers)
                to_fetch = earnings_engine.get_tickers_needing_fundamental_update(tickers, self.fundamentals_dir)
                for t in set(tickers) - set(to_fetch):
                    results[t] = True
            except Exception as e:
                logger.warning(f"Earnings calendar failed ({e}), falling back to legacy mode")
                use_earnings_calendar = False

        if not use_earnings_calendar and not force:
            for t in tickers:
                if not (self.fundamentals_dir / f"{t}.parquet").exists():
                    to_fetch.append(t)
                else:
                    results[t] = True

        if not to_fetch:
            return results

        def _worker(ticker):
            try:
                df = self._get_from_parquet(ticker, use_cache=False)
                return ticker, df is not None and not df.empty
            except Exception as e:
                logger.error(f"Failed to fetch {ticker}: {e}")
                return ticker, False

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for future in as_completed({executor.submit(_worker, t): t for t in to_fetch}):
                ticker, ok = future.result()
                results[ticker] = ok

        return results

    # =========================================================================
    # Utility (source-independent)
    # =========================================================================

    def get_available_tickers(self) -> List[str]:
        """Return tickers that have fundamental data (DuckDB or parquet depending on source)."""
        if self.source == 'yfinance':
            conn = duckdb.connect(self.db_path)
            try:
                rows = conn.execute("SELECT DISTINCT ticker FROM fundamentals ORDER BY ticker").fetchall()
                return [r[0] for r in rows]
            finally:
                conn.close()
        else:
            return sorted(f.stem for f in self.fundamentals_dir.glob('*.parquet'))


# =========================================================================
# Module-level helpers
# =========================================================================

def _safe_float(df: pd.DataFrame, idx, col: str) -> Optional[float]:
    """Extract a float value from a transposed yfinance DataFrame; return None if missing."""
    try:
        if df.empty or col not in df.columns or idx not in df.index:
            return None
        val = df.at[idx, col]
        if pd.isna(val):
            return None
        return float(val)
    except Exception:
        return None


def _nan_to_none(val) -> Optional[float]:
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
        return float(val)
    except Exception:
        return None
