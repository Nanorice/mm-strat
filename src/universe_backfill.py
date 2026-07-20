import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import duckdb
from src import db
import pandas as pd
import yfinance as yf
from yfinance import EquityQuery

try:
    from tqdm import tqdm
except ImportError:
    # Fallback if tqdm not installed
    def tqdm(iterable, **kwargs):
        return iterable

import config
from src.shares_engine import SharesEngine

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"
TICKER_CACHE_PATH = Path(__file__).parent.parent / "data" / "ticker_discovery_cache.json"
TICKER_CACHE_TTL_DAYS = 7  # Refresh discovery cache weekly


class UniverseBackfillEngine:
    """Historical data loader for ~10K US-listed tickers.

    Phase 1: Populates company_profiles, price_data, shares_history
    from yfinance (no FMP dependency). Phase 2+ applies screening criteria.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or DEFAULT_DB_PATH)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def ensure_tables(self) -> None:
        con = db.connect(self.db_path)
        try:
            # Phase 1: Production tables (no backfill suffix)
            con.execute("""
                CREATE TABLE IF NOT EXISTS company_profiles (
                    ticker VARCHAR NOT NULL PRIMARY KEY,
                    name VARCHAR,
                    sector VARCHAR,
                    industry VARCHAR,
                    exchange VARCHAR,
                    country VARCHAR,
                    market_cap DOUBLE,
                    beta DOUBLE,
                    is_active BOOLEAN DEFAULT TRUE,
                    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Backward compatibility: DBs created before these columns existed.
            # IF NOT EXISTS is required — a duplicate-column ALTER aborts the DuckDB
            # transaction, taking every later CREATE in this method down with it.
            con.execute("ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS beta DOUBLE")
            con.execute("ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
            con.execute(
                "ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS "
                "discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            )

            con.execute("""
                CREATE TABLE IF NOT EXISTS price_data (
                    ticker VARCHAR NOT NULL,
                    date DATE NOT NULL,
                    open DOUBLE,
                    high DOUBLE,
                    low DOUBLE,
                    close DOUBLE,
                    volume UBIGINT,
                    PRIMARY KEY (ticker, date)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS ticker_blacklist (
                    ticker VARCHAR NOT NULL PRIMARY KEY,
                    reason VARCHAR,
                    blacklisted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    blacklisted_by VARCHAR DEFAULT 'auto'
                )
            """)
        finally:
            con.close()

        # shares_history belongs to SharesEngine — it must own the DDL, or a
        # CREATE TABLE IF NOT EXISTS race here silently wins with a schema its
        # own _upsert (updated_at) can't write to.
        SharesEngine(self.db_path).ensure_table()

    # ------------------------------------------------------------------
    # Blacklist
    # ------------------------------------------------------------------

    def _load_blacklist(self) -> set:
        con = db.connect(self.db_path)
        try:
            rows = con.execute("SELECT ticker FROM ticker_blacklist").fetchall()
            return {r[0] for r in rows}
        finally:
            con.close()

    def add_to_blacklist(self, tickers: List[str], reason: str, blacklisted_by: str = "auto") -> int:
        """Insert tickers into ticker_blacklist (idempotent)."""
        if not tickers:
            return 0
        con = db.connect(self.db_path)
        try:
            df = pd.DataFrame({
                "ticker": tickers,
                "reason": reason,
                "blacklisted_by": blacklisted_by,
            })
            con.execute("""
                INSERT INTO ticker_blacklist (ticker, reason, blacklisted_by)
                SELECT ticker, reason, blacklisted_by FROM df
                ON CONFLICT (ticker) DO NOTHING
            """)
            return len(tickers)
        finally:
            con.close()

    def purge_blacklisted(self) -> Dict[str, int]:
        """Remove blacklisted tickers from all Phase 1 tables.

        Returns counts of rows deleted per table.
        """
        con = db.connect(self.db_path)
        try:
            counts = {}
            for table in ("company_profiles", "price_data", "shares_history"):
                before = con.execute(f"SELECT COUNT(*) FROM {table} WHERE ticker IN (SELECT ticker FROM ticker_blacklist)").fetchone()[0]
                con.execute(f"DELETE FROM {table} WHERE ticker IN (SELECT ticker FROM ticker_blacklist)")
                counts[table] = before
            return counts
        finally:
            con.close()

    def auto_blacklist_no_fundamentals(self) -> int:
        """Blacklist tickers in company_profiles that have no FMP fundamentals.

        These are SPACs, warrants, shells — FMP has no financials for them.
        Returns number of tickers added to blacklist.
        """
        con = db.connect(self.db_path)
        try:
            rows = con.execute("""
                SELECT ticker FROM company_profiles
                WHERE ticker NOT IN (
                    SELECT DISTINCT ticker FROM fundamentals WHERE source = 'fmp'
                )
                AND ticker NOT IN (SELECT ticker FROM ticker_blacklist)
            """).fetchall()
        finally:
            con.close()

        tickers = [r[0] for r in rows]
        if not tickers:
            return 0
        return self.add_to_blacklist(tickers, reason="no_fmp_fundamentals", blacklisted_by="auto")

    # ------------------------------------------------------------------
    # Ticker Discovery Cache (avoids yfinance rate limiting)
    # ------------------------------------------------------------------

    def _load_ticker_cache(self) -> List[str]:
        """Load cached tickers if cache exists and is fresh."""
        if not TICKER_CACHE_PATH.exists():
            return []

        try:
            with open(TICKER_CACHE_PATH) as f:
                cache_data = json.load(f)

            cache_time = datetime.fromisoformat(cache_data.get("cached_at", "1970-01-01"))
            cache_age = datetime.now() - cache_time
            cache_valid = cache_age < timedelta(days=TICKER_CACHE_TTL_DAYS)

            if cache_valid:
                tickers = cache_data.get("tickers", [])
                print(f"   [OK] Cache hit: {len(tickers):,} tickers ({cache_age.days}d old)")
                return tickers
            else:
                print(f"   [STALE] Cache is {cache_age.days}d old (>={TICKER_CACHE_TTL_DAYS}d TTL), refreshing...")
                return []
        except Exception as e:
            logger.debug(f"Failed to load ticker cache: {e}")
            return []

    def _save_ticker_cache(self, tickers: List[str]) -> None:
        """Save discovered tickers to cache."""
        try:
            cache_data = {
                "cached_at": datetime.now().isoformat(),
                "ttl_days": TICKER_CACHE_TTL_DAYS,
                "count": len(tickers),
                "tickers": tickers,
            }
            with open(TICKER_CACHE_PATH, "w") as f:
                json.dump(cache_data, f, indent=2)
            logger.info(f"Saved {len(tickers):,} tickers to cache: {TICKER_CACHE_PATH}")
        except Exception as e:
            logger.warning(f"Failed to save ticker cache: {e}")

    # ------------------------------------------------------------------
    # Step 1: Discover tickers via yfinance screener + populate company_profiles
    # ------------------------------------------------------------------

    def discover_tickers(self, use_cache: bool = True, force_refresh: bool = False) -> int:
        """Discover US-listed tickers via cached yfinance.screen().

        Caches discovered tickers to avoid repeated rate-limited API calls.
        Only re-discovers if cache is stale (>TICKER_CACHE_TTL_DAYS) or force_refresh=True.

        Args:
            use_cache: If True, use cached tickers when available (default True)
            force_refresh: If True, bypass cache and re-discover from yfinance (default False)

        Returns:
            Number of company profiles populated/updated
        """
        print("\n   ========== DISCOVER TICKERS ==========")

        # Try to load cached tickers first
        all_tickers = []
        if use_cache and not force_refresh:
            all_tickers = self._load_ticker_cache()

        # If cache is empty or stale, discover from yfinance
        if not all_tickers:
            print("   Step 1: Paginate yfinance.screen() for US tickers...")
            all_tickers = self._discover_via_yfinance()
            if all_tickers:
                self._save_ticker_cache(all_tickers)
        else:
            print(f"   Step 1: Loaded {len(all_tickers):,} tickers from cache")

        print(f"\n   Step 2: Discovered {len(all_tickers):,} tickers total")

        # Fetch company profiles
        profiles = self._fetch_company_profiles(all_tickers)

        # Write to company_profiles table
        print(f"\n   Step 3: Writing to company_profiles table...")
        rows_written = self._write_company_profiles(profiles)
        print(f"   [OK] Populated {rows_written:,} tickers in company_profiles")
        print("   ========================================\n")

        return rows_written

    def discover_tickers_fmp(self) -> int:
        """Discover US-listed equities via FMP company screener.

        Excludes ETFs and funds only — no price/market-cap/volume filters.
        Screening criteria are applied in Phase 2 (ScreenerManager).
        Profiles written directly from screener response (no second API call).

        Returns:
            Number of company profiles populated/updated
        """
        print("\n   ========== DISCOVER TICKERS (FMP) ==========")

        fmp_rows = self._discover_via_fmp()
        if not fmp_rows:
            print("   [ERR] FMP screener returned no results")
            return 0

        print(f"   Step 2: {len(fmp_rows):,} equities returned (ETFs/funds excluded)")

        df = pd.DataFrame(fmp_rows)
        df = df.rename(columns={
            "symbol": "ticker",
            "companyName": "name",
            "marketCap": "market_cap",
        })
        if "exchangeShortName" in df.columns:
            df["exchange"] = df["exchangeShortName"]

        keep = ["ticker", "name", "sector", "industry", "exchange", "country", "market_cap", "beta"]
        df = df[[c for c in keep if c in df.columns]]

        blacklist = self._load_blacklist()
        if blacklist:
            before = len(df)
            df = df[~df["ticker"].isin(blacklist)]
            skipped = before - len(df)
            if skipped:
                print(f"   [OK] Skipped {skipped:,} blacklisted tickers")

        print(f"   Step 3: Writing to company_profiles table...")
        rows_written = self._write_company_profiles(df)
        print(f"   [OK] Populated {rows_written:,} tickers in company_profiles")
        print("   ============================================\n")
        return rows_written

    def _discover_via_fmp(self) -> List[Dict]:
        """Call FMP /stable/company-screener and return all matching rows."""
        import requests

        api_key = config.FMP_API_KEY
        if not api_key:
            raise ValueError("FMP_API_KEY is required for FMP discovery. Set it in .env file.")

        # Phase 1: broadest possible universe — only exclude non-equity instruments.
        # Screening criteria (price, market cap, volume) are applied in Phase 2 (ScreenerManager).
        params = {
            "isEtf": "false",
            "isFund": "false",
            "isActivelyTrading": "true",
            "country": "US",
            "exchange": "NYSE,NASDAQ,AMEX",
            "limit": 10_000,
            "apikey": api_key,
        }
        url = f"{config.FMP_BASE_URL}/company-screener"

        print(f"   Step 1: Calling FMP /company-screener (US equities, no ETFs/funds)...")
        try:
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                logger.error(f"FMP screener unexpected response type: {type(data)}")
                return []
            return data
        except Exception as e:
            logger.error(f"FMP screener request failed: {e}")
            return []

    def _discover_via_yfinance(self) -> List[str]:
        """Paginate yfinance.screen() to get all US-listed tickers."""
        q = EquityQuery("and", [
            EquityQuery("eq", ["region", "us"]),
            EquityQuery("is-in", ["exchange", "NMS", "NYQ", "ASE"]),  # NASDAQ, NYSE, AMEX
        ])

        all_tickers = []
        offset = 0
        size = 250
        page_num = 0

        print("   Paginating yfinance.screen() (250 tickers/page)...")

        while True:
            try:
                page_num += 1
                print(f"   [Page {page_num:2d}] Fetching offset={offset:5d}...", end=" ", flush=True)

                result = yf.screen(q, size=size, offset=offset, sortField="ticker", sortAsc=True)
                quotes = result.get("quotes", [])
                if not quotes:
                    print("[OK] DONE")
                    break

                page_tickers = [qt["symbol"] for qt in quotes]
                all_tickers.extend(page_tickers)
                print(f"[OK] {len(page_tickers)} tickers")

                logger.info(f"yfinance.screen(): page={page_num}, offset={offset}, size={len(page_tickers)}")

                if len(page_tickers) < size:
                    print(f"   Final page reached. Total: {len(all_tickers):,} tickers")
                    break
                offset += size
            except Exception as e:
                print(f"[ERR]")
                logger.warning(f"yfinance.screen() error at offset {offset}: {e}")
                break

        # Normalize: . -> -
        all_tickers = [t.replace(".", "-") for t in all_tickers]
        return all_tickers

    def _fetch_company_profiles(self, tickers: List[str]) -> pd.DataFrame:
        """Fetch company metadata from yfinance Ticker.info with progress bar.

        Ensures all tickers are included (even with NULL metadata) to achieve
        full universe coverage. Failed fetches are logged but don't exclude tickers.
        Includes exponential backoff retry logic for transient API failures.
        """
        profiles = []
        failed = []

        print(f"   Fetching company profiles for {len(tickers):,} tickers...")
        t0 = time.perf_counter()

        for i, ticker in enumerate(tqdm(tickers, desc="   Profiles", unit="ticker", disable=False)):
            profile = {"ticker": ticker, "name": None, "sector": None, "industry": None,
                       "exchange": None, "country": None, "market_cap": None, "beta": None}

            # Retry logic with exponential backoff
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    info = yf.Ticker(ticker).info
                    profile.update({
                        "name": info.get("longName") or info.get("shortName"),
                        "sector": info.get("sector"),
                        "industry": info.get("industry"),
                        "exchange": info.get("exchange"),
                        "country": info.get("country"),
                        "market_cap": info.get("marketCap"),
                        "beta": info.get("beta"),
                    })
                    break  # Success, exit retry loop
                except Exception as e:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        time.sleep(wait_time)
                    else:
                        logger.debug(f"Failed to fetch metadata for {ticker} (after {max_retries} attempts): {e}")
                        failed.append(ticker)

            profiles.append(profile)

        elapsed = time.perf_counter() - t0
        rate = len(profiles) / max(elapsed, 1)
        print(f"   [OK] Fetched {len(profiles):,} profiles ({len(failed):,} with missing metadata) in {elapsed / 60:.1f} min ({rate:.0f} tickers/sec)")
        if failed and len(failed) <= 20:
            print(f"       Failed ({len(failed)}): {', '.join(failed[:20])}")

        df = pd.DataFrame(profiles)
        logger.info(f"Fetched {len(df)} company profiles from yfinance ({len(failed)} with missing metadata)")
        return df

    def _write_company_profiles(self, df: pd.DataFrame) -> int:
        """Write company profiles to database (idempotent)."""
        if df.empty:
            return 0

        con = db.connect(self.db_path)
        try:
            # Ensure all required columns exist in table
            con.execute("ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS beta DOUBLE")
            con.execute("ALTER TABLE company_profiles ADD COLUMN IF NOT EXISTS discovered_at TIMESTAMP")

            # Prepare dataframe - fill missing columns with NULL
            for col in ['ticker', 'name', 'sector', 'industry', 'exchange', 'country', 'market_cap', 'beta']:
                if col not in df.columns:
                    df[col] = None

            con.execute("""
                INSERT INTO company_profiles
                    (ticker, name, sector, industry, exchange, country, market_cap, beta, is_active)
                SELECT ticker, name, sector, industry, exchange, country, market_cap, beta, TRUE
                FROM df
                ON CONFLICT (ticker) DO UPDATE SET
                    name = EXCLUDED.name,
                    sector = EXCLUDED.sector,
                    industry = EXCLUDED.industry,
                    exchange = EXCLUDED.exchange,
                    country = EXCLUDED.country,
                    market_cap = EXCLUDED.market_cap,
                    beta = EXCLUDED.beta,
                    is_active = TRUE
            """)

            # Mark tickers no longer returned by the screener as delisted
            tickers_in_batch = df["ticker"].tolist()
            placeholders = ", ".join(["?" for _ in tickers_in_batch])
            con.execute(
                f"UPDATE company_profiles SET is_active = FALSE WHERE ticker NOT IN ({placeholders})",
                tickers_in_batch,
            )

            return len(df)
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Step 2: Backfill OHLCV prices via yfinance
    # ------------------------------------------------------------------

    def backfill_prices(self, batch_size: int = 50, start_date: str = "2000-01-01") -> int:
        """Backfill price_data for all tickers in company_profiles.

        Idempotent: uses INSERT OR IGNORE (replace on duplicate key).
        Typical runtime: ~8-15 hours for 10K tickers.
        """
        pending = self._get_pending_tickers("price")
        if not pending:
            print("   [OK] All tickers already have price data")
            return 0

        print(f"   Backfilling prices for {len(pending):,} tickers (batch_size={batch_size})")
        print(f"   Date range: {start_date} to today")
        total_rows = 0
        num_batches = (len(pending) - 1) // batch_size + 1
        t0 = time.perf_counter()

        pbar = tqdm(total=num_batches, desc="   Batches", unit="batch", disable=False)

        for i in range(0, len(pending), batch_size):
            batch = pending[i : i + batch_size]
            batch_num = i // batch_size + 1
            df = self._download_price_batch(batch, start_date)
            rows = self._write_price_batch(df)
            total_rows += rows
            elapsed = time.perf_counter() - t0
            rate = total_rows / max(elapsed, 1)
            rate_min = rate * 60

            pbar.update(1)
            pbar.set_postfix({
                "rows": f"{total_rows:,}",
                "rate": f"{rate_min:,.0f}/min"
            })

        pbar.close()

        elapsed = time.perf_counter() - t0
        print(f"   [OK] Backfill complete: {total_rows:,} rows in {elapsed / 60:.1f} min")
        return total_rows

    def _get_pending_tickers(self, data_type: str) -> List[str]:
        target_table = "price_data" if data_type == "price" else "shares_history"
        con = db.connect(self.db_path)
        try:
            existing = set()
            try:
                rows = con.execute(f"SELECT DISTINCT ticker FROM {target_table}").fetchall()
                existing = {r[0] for r in rows}
            except duckdb.CatalogException:
                pass

            all_tickers = con.execute("""
                SELECT ticker FROM company_profiles
                WHERE ticker NOT IN (SELECT ticker FROM ticker_blacklist)
                ORDER BY ticker
            """).fetchall()
            pending = [r[0] for r in all_tickers if r[0] not in existing]
            return pending
        finally:
            con.close()

    def _download_price_batch(self, tickers: List[str], start_date: str) -> pd.DataFrame:
        try:
            data = yf.download(
                tickers,
                start=start_date,
                auto_adjust=True,
                group_by="ticker",
                progress=True,  # Show yfinance progress bar
                threads=True,
            )
            if data.empty:
                return self._download_individual_fallback(tickers, start_date)
            return self._unstack_yf_batch(data, tickers)
        except Exception as e:
            logger.warning(f"Batch download failed ({len(tickers)} tickers): {e}")
            return self._download_individual_fallback(tickers, start_date)

    def _unstack_yf_batch(self, data: pd.DataFrame, tickers: List[str]) -> pd.DataFrame:
        results = []
        is_multi = isinstance(data.columns, pd.MultiIndex)

        for t in tickers:
            try:
                if is_multi:
                    # yfinance MultiIndex: try (ticker, col) or (col, ticker)
                    level_0 = set(data.columns.get_level_values(0))
                    if t in level_0:
                        df = data[t].copy()
                    else:
                        try:
                            df = data.xs(t, level=1, axis=1).copy()
                        except KeyError:
                            continue
                else:
                    # Single ticker in batch — no MultiIndex
                    if len(tickers) == 1:
                        df = data.copy()
                    else:
                        continue

                close_col = "Close" if "Close" in df.columns else "close"
                df = df.dropna(subset=[close_col])
                if df.empty:
                    continue

                df = df.reset_index()
                df.columns = [c.lower() if isinstance(c, str) else str(c).lower() for c in df.columns]
                df["ticker"] = t

                required = ["ticker", "date", "open", "high", "low", "close", "volume"]
                missing = [c for c in required if c not in df.columns]
                if missing:
                    continue

                results.append(df[required])
            except Exception as e:
                logger.debug(f"Failed to extract {t} from batch: {e}")

        return pd.concat(results, ignore_index=True) if results else pd.DataFrame()

    def _download_individual_fallback(self, tickers: List[str], start_date: str) -> pd.DataFrame:
        from src.data_engine import DataRepository
        repo = DataRepository(enable_validation=False)
        results = []
        for t in tickers:
            df = self._fetch_yf_single(t, start_date)
            if df is None:
                logger.info(f"{t}: yfinance failed, trying FMP fallback")
                df = self._fetch_fmp_single(t, start_date, repo)
            if df is not None:
                results.append(df)
        return pd.concat(results, ignore_index=True) if results else pd.DataFrame()

    def _fetch_yf_single(self, ticker: str, start_date: str) -> Optional[pd.DataFrame]:
        try:
            df = yf.download(ticker, start=start_date, auto_adjust=True, progress=False)
            if df.empty:
                return None
            df = df.reset_index()
            df.columns = [c.lower() if isinstance(c, str) else str(c).lower() for c in df.columns]
            df["ticker"] = ticker
            required = ["ticker", "date", "open", "high", "low", "close", "volume"]
            if any(c not in df.columns for c in required):
                return None
            return df[required]
        except Exception:
            return None

    def _fetch_fmp_single(self, ticker: str, start_date: str, repo) -> Optional[pd.DataFrame]:
        try:
            raw = repo._fetch_fmp_historical(ticker, from_date=start_date)
            df = repo._parse_fmp_response(raw, ticker)
            if df is None or df.empty:
                return None
            df = df.reset_index()
            df.columns = [c.lower() if isinstance(c, str) else str(c).lower() for c in df.columns]
            df["ticker"] = ticker
            required = ["ticker", "date", "open", "high", "low", "close", "volume"]
            if any(c not in df.columns for c in required):
                return None
            return df[required]
        except Exception as e:
            logger.debug(f"FMP fallback failed for {ticker}: {e}")
            return None

    def _write_price_batch(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        con = db.connect(self.db_path)
        try:
            con.execute("""
                INSERT INTO price_data (ticker, date, open, high, low, close, volume)
                SELECT ticker, date, open, high, low, close, CAST(volume AS UBIGINT)
                FROM df
                ON CONFLICT (ticker, date) DO NOTHING
            """)
            return len(df)
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Step 3: Backfill shares outstanding via yfinance
    # ------------------------------------------------------------------

    def backfill_shares(self, max_workers: int = 8) -> int:
        """Backfill shares_history for tickers in company_profiles.

        Delegates to SharesEngine, which owns fetching and the idempotent upsert.
        """
        pending = self._get_pending_tickers("shares")
        if not pending:
            print("   [OK] All tickers already have shares data")
            return 0

        print(f"   Backfilling shares for {len(pending):,} tickers (workers={max_workers})")
        t0 = time.perf_counter()

        rows = SharesEngine(self.db_path).backfill(pending, max_workers=max_workers)

        elapsed = time.perf_counter() - t0
        print(f"   [OK] Shares backfill complete: {rows:,} rows in {elapsed / 60:.1f} min")
        return rows

    # ------------------------------------------------------------------
    # Step 4: Quarterly universe refresh (gated in daily_pipeline_orchestrator)
    # ------------------------------------------------------------------

    def quarterly_refresh(self, last_refresh_date: Optional[str] = None) -> int:
        """Rerun discovery + backfill for newly-listed tickers.

        Gated to run quarterly (called from daily_pipeline_orchestrator Phase 1.1).
        Returns count of new tickers added.
        """
        print("\n   ========== QUARTERLY REFRESH ==========")
        print("   Checking for newly-listed tickers...")

        # Get existing tickers
        print("   Loading existing tickers...", end=" ", flush=True)
        con = db.connect(self.db_path)
        try:
            existing = set(con.execute("SELECT ticker FROM company_profiles").fetchall())
            existing = {r[0] for r in existing}
        finally:
            con.close()
        print(f"[OK] {len(existing):,} existing")

        # Discover current tickers
        print("   Discovering current US tickers...")
        current = set(self._discover_via_yfinance())

        # Find new tickers
        new_tickers = current - existing
        if not new_tickers:
            print("   [OK] No new tickers to add")
            print("   ======================================\n")
            return 0

        print(f"   [OK] Found {len(new_tickers):,} new tickers")

        # Fetch profiles for new tickers only
        profiles = self._fetch_company_profiles(list(new_tickers))
        rows = self._write_company_profiles(profiles)

        # Backfill data for new tickers
        print(f"\n   Backfilling data for {rows} new tickers...")
        self.backfill_prices(batch_size=50, start_date="2000-01-01")
        self.backfill_shares(max_workers=8)

        print(f"\n   [OK] Quarterly refresh complete: {rows} new tickers added")
        print("   ======================================\n")
        return rows

    # ------------------------------------------------------------------
    # Status & Validation
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        con = db.connect(self.db_path)
        try:
            def _safe_count(query: str) -> int:
                try:
                    return con.execute(query).fetchone()[0]
                except duckdb.CatalogException:
                    return 0

            profiles = _safe_count("SELECT COUNT(*) FROM company_profiles")
            price_tickers = _safe_count("SELECT COUNT(DISTINCT ticker) FROM price_data")
            price_rows = _safe_count("SELECT COUNT(*) FROM price_data")
            shares_tickers = _safe_count("SELECT COUNT(DISTINCT ticker) FROM shares_history")
            shares_rows = _safe_count("SELECT COUNT(*) FROM shares_history")

            return {
                "company_profiles": profiles,
                "price_tickers_done": price_tickers,
                "price_rows": price_rows,
                "shares_tickers_done": shares_tickers,
                "shares_rows": shares_rows,
                "price_pct_complete": round(price_tickers / max(profiles, 1) * 100, 1),
                "shares_pct_complete": round(shares_tickers / max(profiles, 1) * 100, 1),
            }
        finally:
            con.close()

    def validate_backfill(self) -> Dict:
        con = db.connect(self.db_path)
        try:
            stats = con.execute("""
                SELECT
                    COUNT(DISTINCT ticker) AS tickers,
                    COUNT(*) AS total_rows,
                    MIN(date) AS earliest_date,
                    MAX(date) AS latest_date
                FROM price_data
            """).df().iloc[0].to_dict()

            sparse = con.execute("""
                SELECT COUNT(*) FROM (
                    SELECT ticker FROM price_data
                    GROUP BY ticker HAVING COUNT(*) < 50
                )
            """).fetchone()[0]
            stats["sparse_tickers"] = sparse

            # Check known delisted tickers
            check_tickers = ["BBBY", "HMNY", "SVB"]
            for t in check_tickers:
                count = con.execute(
                    "SELECT COUNT(*) FROM price_data WHERE ticker = ?", [t]
                ).fetchone()[0]
                stats[f"rows_{t}"] = count

            return stats
        finally:
            con.close()
