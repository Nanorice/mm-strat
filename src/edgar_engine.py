"""
EDGAR Engine — SEC EDGAR client for ticker→CIK lookup and authoritative
filing dates from the submissions API.

Two responsibilities:
  1. CIK map: ticker → CIK (10-digit, zero-padded). Refreshed quarterly from
     https://www.sec.gov/files/company_tickers.json.
  2. Filings fetch: per-ticker recent 10-Q/10-K filings with periodOfReport
     and filingDate, from https://data.sec.gov/submissions/CIK{cik}.json.

SEC requirements:
  - User-Agent header identifying the requester (Name + Email)
  - 10 req/sec rate limit (we throttle conservatively)
  - No API key
"""

import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import duckdb
from src import db
import pandas as pd
import requests

import config

logger = logging.getLogger(__name__)


class EDGARClient:
    """Thin HTTP client for SEC EDGAR with rate limiting + standard headers."""

    def __init__(self, user_agent: str = None, rate_limit_per_sec: int = None):
        self.user_agent = user_agent or config.EDGAR_USER_AGENT
        self.rate_limit = rate_limit_per_sec or config.EDGAR_RATE_LIMIT_PER_SEC
        self._call_timestamps: List[float] = []
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': self.user_agent,
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate',
            'Host': 'data.sec.gov',
        })

    def _throttle(self) -> None:
        """Sliding 1-second window rate limit."""
        with self._lock:
            now = time.time()
            window_start = now - 1.0
            self._call_timestamps = [t for t in self._call_timestamps if t > window_start]
            if len(self._call_timestamps) >= self.rate_limit:
                sleep_time = self._call_timestamps[0] + 1.0 - now + 0.01
                if sleep_time > 0:
                    time.sleep(sleep_time)
            self._call_timestamps.append(time.time())

    def get_company_tickers(self) -> pd.DataFrame:
        """Fetch the SEC ticker→CIK directory. ~13K rows, ~800KB."""
        self._throttle()
        # company_tickers.json lives on www.sec.gov, not data.sec.gov
        resp = requests.get(
            config.EDGAR_TICKERS_URL,
            headers={'User-Agent': self.user_agent},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data.values())
        df['cik'] = df['cik_str'].astype(int)
        df = df.rename(columns={'title': 'company_name'})
        return df[['ticker', 'cik', 'company_name']]

    def get_submissions(self, cik: int) -> Optional[Dict]:
        """Fetch recent filings for one CIK. Returns parsed JSON or None on 404."""
        self._throttle()
        url = config.EDGAR_SUBMISSIONS_URL.format(cik=cik)
        try:
            resp = self._session.get(url, timeout=30)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.debug(f"[EDGAR] submissions fetch failed for CIK={cik}: {e}")
            return None

    def get_recent_filings(
        self,
        cik: int,
        forms: Tuple[str, ...] = ('10-Q', '10-K'),
    ) -> pd.DataFrame:
        """
        Return recent filings for one CIK filtered to the given form types.

        Columns: form, accession_number, filing_date, report_date.
        Empty DataFrame if no submissions data or no matching forms.
        """
        sub = self.get_submissions(cik)
        if sub is None:
            return pd.DataFrame(columns=['form', 'accession_number', 'filing_date', 'report_date'])

        recent = sub.get('filings', {}).get('recent', {})
        if not recent:
            return pd.DataFrame(columns=['form', 'accession_number', 'filing_date', 'report_date'])

        df = pd.DataFrame({
            'form':             recent.get('form', []),
            'accession_number': recent.get('accessionNumber', []),
            'filing_date':      recent.get('filingDate', []),
            'report_date':      recent.get('reportDate', []),
        })
        df = df[df['form'].isin(forms)].copy()
        if df.empty:
            return df
        df['filing_date'] = pd.to_datetime(df['filing_date'], errors='coerce').dt.date
        df['report_date'] = pd.to_datetime(df['report_date'], errors='coerce').dt.date
        # report_date can be NULL for filings that lack a fiscal period anchor;
        # those aren't useful for our period_end mapping — drop them.
        df = df.dropna(subset=['report_date'])
        return df.reset_index(drop=True)


class EDGAREngine:
    """
    Manages the ticker→CIK map (DuckDB `cik_map` table) and provides a
    higher-level filings API on top of EDGARClient.
    """

    def __init__(self, db_path: str = None, user_agent: str = None):
        self.db_path = db_path or str(config.DUCKDB_PATH)
        self.client = EDGARClient(user_agent=user_agent)
        self._ensure_tables()

    # =========================================================================
    # CIK map persistence
    # =========================================================================

    def _ensure_tables(self) -> None:
        conn = db.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cik_map (
                    ticker        VARCHAR NOT NULL PRIMARY KEY,
                    cik           BIGINT  NOT NULL,
                    company_name  VARCHAR,
                    refreshed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS cik_map_cik_idx ON cik_map (cik)")
        finally:
            conn.close()

    def refresh_cik_map(self) -> int:
        """
        Fetch the SEC ticker→CIK directory and UPSERT into `cik_map`.
        Returns number of rows in the table after refresh.
        """
        df = self.client.get_company_tickers()
        if df.empty:
            logger.warning("[EDGAR] company_tickers.json returned empty")
            return 0

        df['refreshed_at'] = datetime.utcnow()
        conn = db.connect(self.db_path)
        try:
            conn.register('_cik_batch', df)
            conn.execute("""
                INSERT INTO cik_map (ticker, cik, company_name, refreshed_at)
                SELECT ticker, cik, company_name, refreshed_at FROM _cik_batch
                ON CONFLICT (ticker) DO UPDATE SET
                    cik          = EXCLUDED.cik,
                    company_name = EXCLUDED.company_name,
                    refreshed_at = EXCLUDED.refreshed_at
            """)
            conn.commit()
            total = conn.execute("SELECT COUNT(*) FROM cik_map").fetchone()[0]
        finally:
            try:
                conn.unregister('_cik_batch')
            except Exception:
                pass
            conn.close()

        logger.info(f"[EDGAR] cik_map refreshed: {total} rows")
        return total

    def get_cik(self, ticker: str) -> Optional[int]:
        """Look up CIK for one ticker. Returns None if not in the map."""
        conn = db.connect(self.db_path, read_only=True)
        try:
            row = conn.execute(
                "SELECT cik FROM cik_map WHERE ticker = ?", [ticker]
            ).fetchone()
        finally:
            conn.close()
        return int(row[0]) if row else None

    def get_ciks(self, tickers: List[str]) -> Dict[str, int]:
        """Bulk CIK lookup. Returns {ticker: cik} only for tickers in the map."""
        if not tickers:
            return {}
        conn = db.connect(self.db_path, read_only=True)
        try:
            conn.register('_t', pd.DataFrame({'ticker': tickers}))
            rows = conn.execute(
                "SELECT t.ticker, m.cik FROM _t t JOIN cik_map m ON t.ticker = m.ticker"
            ).fetchall()
        finally:
            try:
                conn.unregister('_t')
            except Exception:
                pass
            conn.close()
        return {tk: int(cik) for tk, cik in rows}

    # =========================================================================
    # Instrument classification (form-type → ticker_type)
    # =========================================================================

    # EDGAR form types that identify a non-operating-company instrument. A ticker
    # filing these (and NOT 10-Q/10-K) cannot have quarterly fundamentals by design,
    # so it should not sit in the EQUITY cohort fed to the yfinance fundamentals path.
    _FOREIGN_FORMS = frozenset({'20-F', '40-F', '6-K'})
    _FUND_FORMS    = frozenset({
        'N-CSR', 'N-CSRS', 'N-CEN', 'NPORT-P', 'NPORT-EX',
        '25-NSE', '40-17G', 'N-2', 'N-30D', 'N-Q',
    })
    # Domestic operating-company forms — presence keeps a ticker EQUITY regardless
    # of any incidental N-/foreign filing.
    _EQUITY_FORMS = frozenset({'10-Q', '10-K', '10-Q/A', '10-K/A'})

    def classify_ticker_type(self, cik: int) -> Optional[str]:
        """
        Classify one CIK by the form types in its recent EDGAR filings.

        Returns 'EQUITY' (files 10-Q/10-K), 'FOREIGN' (20-F/40-F/6-K, no 10-x),
        'FUND' (N-CSR/NPORT/etc., no 10-x), or None when submissions are
        unavailable or the form set is inconclusive (caller leaves type unchanged).
        """
        sub = self.client.get_submissions(cik)
        if sub is None:
            return None
        forms = set(sub.get('filings', {}).get('recent', {}).get('form', []))
        if not forms:
            return None

        # Operating company takes precedence: a 10-Q/10-K filer is EQUITY even if it
        # also filed an incidental N-/foreign form.
        if forms & self._EQUITY_FORMS:
            return 'EQUITY'
        if forms & self._FOREIGN_FORMS:
            return 'FOREIGN'
        if forms & self._FUND_FORMS:
            return 'FUND'
        return None

    def classify_ticker_types(self, tickers: List[str]) -> Dict[str, str]:
        """
        Bulk-classify tickers by EDGAR form type. Returns {ticker: ticker_type}
        only for tickers with a CIK and a conclusive classification. Tickers with
        no CIK or inconclusive submissions are omitted (caller leaves them as-is).
        """
        cik_map = self.get_ciks(tickers)
        out: Dict[str, str] = {}
        for tk in tickers:
            cik = cik_map.get(tk)
            if cik is None:
                continue
            ttype = self.classify_ticker_type(cik)
            if ttype is not None:
                out[tk] = ttype
        return out

    # =========================================================================
    # Filing-date backfill
    # =========================================================================

    # A filing_date within this many days of period_end is suspect (real 10-Q
    # filings take ≥8 days; matches fundamental_engine._MIN_REAL_FILING_GAP_DAYS).
    MIN_FILING_GAP_DAYS = 8

    # How far apart period_end and EDGAR reportDate can drift before we reject
    # the match. Most issuers align exactly; fiscal-calendar non-aligned filers
    # (AZO Aug-FY, COST May-FY, retail 4-5-4 calendars) can drift 20-30d. 35d
    # is safe because quarters are 90d apart — a 35d half-window can never
    # reach an adjacent quarter (needs >45d).
    REPORT_DATE_TOLERANCE_DAYS = 35

    def backfill_filing_dates_from_edgar(
        self,
        tickers: Optional[List[str]] = None,
        only_null: bool = True,
    ) -> Dict[str, int]:
        """
        Fill fundamentals.filing_date from authoritative SEC EDGAR data.

        For each (ticker, period_end) requested, fetches the ticker's recent
        10-Q/10-K filings from EDGAR and picks the one whose reportDate is
        closest to period_end (within REPORT_DATE_TOLERANCE_DAYS). The matched
        filingDate is written.

        Args:
            tickers: Restrict to these tickers (None = all tickers in
                     fundamentals with NULL filing_date).
            only_null: If True (default), only touch rows where filing_date
                       IS NULL. Set False to overwrite existing values
                       (e.g. to replace yfinance-derived dates with SEC).

        Returns {ticker: rows_updated}. Tickers with 0 updates are omitted.
        """
        # 1) Identify (ticker, period_end) targets
        conn = db.connect(self.db_path, read_only=True)
        try:
            where_null = "AND filing_date IS NULL" if only_null else ""
            if tickers:
                conn.register('_t', pd.DataFrame({'ticker': tickers}))
                ticker_filter = "AND ticker IN (SELECT ticker FROM _t)"
            else:
                ticker_filter = ""
            targets = conn.execute(f"""
                SELECT ticker, period_end
                FROM fundamentals
                WHERE source = 'yfinance'
                  {where_null}
                  {ticker_filter}
                ORDER BY ticker, period_end
            """).fetchdf()
        finally:
            try:
                conn.unregister('_t')
            except Exception:
                pass
            conn.close()

        if targets.empty:
            logger.info("[EDGAR/Backfill] No target rows")
            return {}

        # 2) Look up CIKs (skip tickers with no SEC mapping — ETFs, foreign, etc.)
        target_tickers = sorted(targets['ticker'].unique().tolist())
        cik_map = self.get_ciks(target_tickers)
        no_cik = [t for t in target_tickers if t not in cik_map]
        if no_cik:
            logger.info(
                f"[EDGAR/Backfill] {len(no_cik)}/{len(target_tickers)} tickers "
                f"have no CIK mapping — skipped (sample: {no_cik[:5]})"
            )

        # 3) For each ticker, fetch filings and map period_end → filing_date
        all_mappings: List[Dict] = []
        done = 0
        for ticker in target_tickers:
            cik = cik_map.get(ticker)
            if cik is None:
                done += 1
                continue

            filings = self.client.get_recent_filings(cik, forms=('10-Q', '10-K'))
            if filings.empty:
                done += 1
                continue

            # For each NULL period_end, find the EDGAR filing with the closest
            # report_date within tolerance, gap guard >= MIN_FILING_GAP_DAYS.
            ticker_targets = targets[targets['ticker'] == ticker]
            for _, t_row in ticker_targets.iterrows():
                pe = t_row['period_end']
                pe_ts = pd.Timestamp(pe)
                gaps = (pd.to_datetime(filings['report_date']) - pe_ts).abs()
                within_tol = gaps <= pd.Timedelta(days=self.REPORT_DATE_TOLERANCE_DAYS)
                if not within_tol.any():
                    continue
                # Best match = smallest |report_date - period_end|
                best_idx = gaps[within_tol].idxmin()
                fd = filings.at[best_idx, 'filing_date']
                # Gap guard: filing_date must be at least MIN_FILING_GAP_DAYS
                # after period_end (real 10-Qs take time to file)
                gap_days = (pd.Timestamp(fd) - pe_ts).days
                if gap_days < self.MIN_FILING_GAP_DAYS:
                    continue
                all_mappings.append({
                    'ticker': ticker,
                    'period_end': pe,
                    'filing_date': fd,
                })

            done += 1
            if done % 200 == 0:
                logger.info(f"[EDGAR/Backfill] Processed {done}/{len(target_tickers)} tickers")

        if not all_mappings:
            logger.info("[EDGAR/Backfill] No matches produced")
            return {}

        # 4) Apply updates in one UPDATE
        update_df = pd.DataFrame(all_mappings)
        conn = db.connect(self.db_path)
        try:
            conn.register('_edgar_fd', update_df)
            where_null = "AND f.filing_date IS NULL" if only_null else ""
            conn.execute(f"""
                UPDATE fundamentals f
                SET filing_date = m.filing_date,
                    updated_at = CURRENT_TIMESTAMP
                FROM _edgar_fd m
                WHERE f.ticker     = m.ticker
                  AND f.period_end = m.period_end
                  AND f.source     = 'yfinance'
                  {where_null}
            """)
            conn.commit()
        finally:
            try:
                conn.unregister('_edgar_fd')
            except Exception:
                pass
            conn.close()

        per_ticker = update_df.groupby('ticker').size().to_dict()
        total = int(update_df.shape[0])
        logger.info(
            f"[EDGAR/Backfill] Updated {total} rows across {len(per_ticker)} tickers"
        )
        return per_ticker
