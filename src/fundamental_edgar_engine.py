"""SEC EDGAR XBRL fundamentals backfill engine.

Fetches 10-K/10-Q filings from SEC EDGAR and inserts into the `fundamentals`
and `shares_history` tables. Uses INSERT OR IGNORE so yfinance rows (2024+)
take precedence.

Taxonomy validated on AAPL, JPM, NOW (see tools/test_edgar_fundamentals.py).
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as _date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import duckdb
import pandas as pd
import requests

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"
SEC_HEADERS = {"User-Agent": "SEPA_Research_Tool research@quantamental.dev"}
SEC_RATE_LIMIT_SLEEP = 0.15  # ~6 req/s, safely under 10 req/s limit
VALID_FORMS = {"10-K", "10-Q"}

# Priority-ordered XBRL tag lists per fundamentals column.
# (unit_type, [tag_priority_list]) — first tag with data wins.
TAXONOMY: Dict[str, Tuple[str, List[str]]] = {
    "total_revenue": ("USD", [
        "RevenueFromContractWithCustomerExcludingAssessedTax",   # ASC 606 (post-2018 standard)
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",                                       # pre-2018 (AAPL, JNJ, etc.)
        "SalesRevenueGoodsNet",                                  # semiconductors/goods (AMD pre-2012)
        "RevenuesNetOfInterestExpense",                          # banks (JPM, BAC)
        "InterestAndDividendIncomeOperating",                    # insurance/finance
        "RevenueMineralSales",                                   # mining (NEM, FCX)
        "RevenueFromContractsWithCustomers",
    ]),
    "gross_profit": ("USD", ["GrossProfit"]),
    "operating_income": ("USD", [
        "OperatingIncomeLoss",
        # Note: energy (CVX), pharma (JNJ), mining (NEM) don't file this tag —
        # they go revenue → pre-tax income with no operating subtotal. Null is expected.
    ]),
    "net_income": ("USD", [
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "ProfitLoss",
    ]),
    "r_and_d": ("USD", [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
        "ResearchAndDevelopmentExpenseIncludingAcquiredInProcessCost",
    ]),
    "sga": ("USD", [
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
        "SellingAndMarketingExpense",                            # some SaaS/retail split SG&A
        "MarketingAndAdvertisingExpense",                        # media/cable (CMCSA)
    ]),
    "total_assets": ("USD", ["Assets"]),
    "current_assets": ("USD", ["AssetsCurrent"]),
    "cash_and_equivalents": ("USD", [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
        "CashAndCashEquivalentsAtCarryingValueIncludingDiscontinuedOperations",
        "Cash",
    ]),
    "total_debt": ("USD", [
        "DebtLongtermAndShorttermCombinedAmount",
        "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
        "LongTermDebtAndCapitalLeaseObligations",               # REITs
        "LongTermDebt",
        "NotesPayable",                                         # some industrials
        "SeniorNotes",                                          # REITs (DLR) — unsecured senior bonds
        "UnsecuredDebt",                                        # REITs alternative
    ]),
    "long_term_debt": ("USD", [
        "LongTermDebt",
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermNotesPayable",
        "SeniorNotes",                                          # REITs
    ]),
    "current_liabilities": ("USD", ["LiabilitiesCurrent"]),
    "stockholders_equity": ("USD", [
        "StockholdersEquity",
        "StockholdersEquityAttributableToParent",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",  # AVGO, post-acquisition
        "PartnersCapital",                                       # MLPs / partnerships (energy)
        "MembersEquity",                                         # LLCs
    ]),
    "operating_cash_flow": ("USD", [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ]),
    "capex": ("USD", [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForCapitalImprovements",
        "PaymentsToAcquireProductiveAssets",                    # oil & gas (CVX, XOM)
        "PaymentsToAcquireAndDevelopRealEstate",                # REITs (development capex)
        "PaymentsForProceedsFromProductiveAssets",
    ]),
}

# Shares tag for shares_history bonus insert
_SHARES_TAG = ("shares", ["CommonStockSharesOutstanding"])

# INSTANT facts: point-in-time balance sheet items (no `start` date in EDGAR).
# These are keyed by (end_date, form) just like duration facts, but they anchor
# to the same quarter-end as the balance sheet snapshot.
_INSTANT_COLS = {
    "total_assets",
    "current_assets",
    "cash_and_equivalents",
    "total_debt",
    "long_term_debt",
    "current_liabilities",
    "stockholders_equity",
}

# DURATION facts: flow over a period (have `start` + `end` in EDGAR).
# These define which periods actually have a P&L filing — used as row anchors.
_DURATION_COLS = {
    "total_revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "r_and_d",
    "sga",
    "operating_cash_flow",
    "capex",
}


class FundamentalEdgarEngine:
    """Backfills fundamentals from SEC EDGAR XBRL for historical periods."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or DEFAULT_DB_PATH)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def backfill(
        self,
        tickers: List[str],
        start_date: str = "2009-01-01",
        workers: int = 2,
        overwrite_edgar: bool = False,
    ) -> Dict[str, int]:
        """Fetch EDGAR facts for tickers and INSERT OR IGNORE into DuckDB.

        Args:
            overwrite_edgar: If True, DELETE existing source='edgar' rows for
                these tickers before inserting. yfinance rows are never touched.
                Use this when re-running after a taxonomy/logic fix.

        Returns:
            {'fundamentals': rows_inserted, 'shares_history': rows_inserted}
        """
        cik_map = self._fetch_cik_map()
        ticker_cik_pairs = [
            (t, cik_map[t]) for t in tickers if t in cik_map
        ]
        missing = [t for t in tickers if t not in cik_map]
        if missing:
            logger.warning(f"{len(missing)} tickers not in SEC CIK map: {missing[:10]}")

        fund_frames: List[pd.DataFrame] = []
        shares_frames: List[pd.DataFrame] = []

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._fetch_company_facts, cik): ticker
                for ticker, cik in ticker_cik_pairs
            }
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    facts = future.result()
                except Exception as exc:
                    logger.warning(f"{ticker}: fetch error — {exc}")
                    continue

                if facts is None:
                    continue

                fund_df = self._resolve_fundamentals(ticker, facts, start_date)
                if fund_df is not None:
                    fund_frames.append(fund_df)

                shares_df = self._resolve_shares(ticker, facts, start_date)
                if shares_df is not None:
                    shares_frames.append(shares_df)

        fund_rows = 0
        shares_rows = 0

        con = duckdb.connect(self.db_path)
        try:
            if overwrite_edgar and (fund_frames or shares_frames):
                ticker_list = "', '".join(tickers)
                con.execute(f"DELETE FROM fundamentals WHERE source = 'edgar' AND ticker IN ('{ticker_list}')")
                con.execute(f"DELETE FROM shares_history WHERE ticker IN ('{ticker_list}')")
                logger.info(f"🧹 Deleted existing edgar rows for {len(tickers)} tickers")

            if fund_frames:
                combined = pd.concat(fund_frames, ignore_index=True)
                fund_rows = self._upsert_fundamentals(con, combined)
                logger.info(f"✅ fundamentals: {fund_rows} rows inserted (INSERT OR IGNORE)")

            if shares_frames:
                combined_shares = pd.concat(shares_frames, ignore_index=True)
                shares_rows = self._upsert_shares_history(con, combined_shares)
                logger.info(f"✅ shares_history: {shares_rows} rows inserted (INSERT OR IGNORE)")
        finally:
            con.close()

        return {"fundamentals": fund_rows, "shares_history": shares_rows}

    # ------------------------------------------------------------------
    # SEC fetch helpers
    # ------------------------------------------------------------------

    def _fetch_cik_map(self) -> Dict[str, str]:
        """Return {ticker: zero-padded-10-digit-CIK}."""
        logger.info("Fetching SEC ticker→CIK map...")
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        return {
            v["ticker"]: str(v["cik_str"]).zfill(10)
            for v in r.json().values()
        }

    def _fetch_company_facts(self, cik: str) -> Optional[Dict]:
        """Fetch raw XBRL company facts for one CIK (includes rate-limit sleep)."""
        time.sleep(SEC_RATE_LIMIT_SLEEP)
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        r = requests.get(url, headers=SEC_HEADERS, timeout=30)
        if r.status_code != 200:
            logger.warning(f"HTTP {r.status_code} for CIK {cik}")
            return None
        return r.json()

    # ------------------------------------------------------------------
    # Taxonomy resolution
    # ------------------------------------------------------------------

    def _resolve_tag(
        self,
        us_gaap: Dict,
        unit_type: str,
        tags: List[str],
    ) -> Dict[Tuple[str, str], float]:
        """Resolve priority tag list → {(end_date, form): value}.

        Uses the `end` date (fiscal period end) as the key.

        Priority strategy:
        - Iterates tags in priority order. Higher-priority tags win for any
          period they cover. Lower-priority tags fill in gaps (earlier history
          or missing quarters) that higher-priority tags don't cover.
        - This handles companies that switched XBRL tags mid-history
          (e.g. AAPL used SalesRevenueNet pre-2017, then switched to
          RevenueFromContractWithCustomerExcludingAssessedTax).

        Dedup strategy for duration facts (items with a `start` date):
        - Multiple entries can share the same (end, form) with different `start`
          dates — e.g. Q3 standalone (90-day) vs Q3 YTD cumulative (270-day).
        - We keep the SHORTEST period (standalone quarterly) per (end, form).
        - Among identical-span entries, keep the most recently filed (amendments).

        For instant facts (no `start`), tiebreak by last-filed per (end, form).
        """
        # Accumulated result across all tags: higher-priority tags fill first,
        # lower-priority tags backfill only for keys not yet covered.
        result: Dict[Tuple[str, str], float] = {}

        for tag in tags:
            entry = us_gaap.get(tag)
            if entry is None:
                continue
            periods = entry.get("units", {}).get(unit_type, [])
            if not periods:
                continue

            # Best candidate per (end, form) from this tag: (span_days, filed, val)
            tag_best: Dict[Tuple[str, str], Tuple[int, str, float]] = {}

            for p in periods:
                if p.get("form") not in VALID_FORMS:
                    continue
                key = (p["end"], p["form"])
                filed = p.get("filed", "")
                start = p.get("start")

                if start:
                    end_d = _date.fromisoformat(p["end"])
                    start_d = _date.fromisoformat(start)
                    span = (end_d - start_d).days
                else:
                    span = 0

                if key not in tag_best:
                    tag_best[key] = (span, filed, p["val"])
                else:
                    prev_span, prev_filed, _ = tag_best[key]
                    if span < prev_span or (span == prev_span and filed > prev_filed):
                        tag_best[key] = (span, filed, p["val"])

            # Higher-priority tags already in result win; lower-priority fills gaps
            for key, (_, _, val) in tag_best.items():
                if key not in result:
                    result[key] = val

        if result:
            logger.debug(f"  Tags={tags[:1]}+{len(tags)-1}more resolved {len(result)} periods")
        return result

    def _resolve_fundamentals(
        self,
        ticker: str,
        facts: Dict,
        start_date: str,
    ) -> Optional[pd.DataFrame]:
        """Extract fundamental rows from company facts, filtered by start_date.

        Row anchoring strategy:
        - Duration facts (income stmt / cash flow) define which periods exist.
          A row is only created when at least one duration column has data for
          that (end_date, form) — i.e., when a P&L was actually filed.
        - Instant facts (balance sheet) are filled in by (end_date, form) lookup.
          They may be null if the balance sheet snapshot doesn't align exactly
          (e.g., some balance sheet tags file on slightly different dates).

        This prevents the union-of-all-keys problem where balance-sheet-only
        quarterly snapshots create rows with 100% null income statement columns.
        """
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        if not us_gaap:
            logger.warning(f"{ticker}: no us-gaap facts")
            return None

        resolved: Dict[str, Dict] = {}
        duration_keys: set = set()

        for col, (unit_type, tags) in TAXONOMY.items():
            tag_data = self._resolve_tag(us_gaap, unit_type, tags)
            resolved[col] = tag_data
            if col in _DURATION_COLS:
                duration_keys.update(tag_data.keys())

        if not duration_keys:
            logger.warning(f"{ticker}: no duration (income/cashflow) data resolved")
            return None

        rows = []
        for (end_date, form) in sorted(duration_keys):
            if end_date < start_date:
                continue
            row: Dict = {
                "ticker": ticker,
                "period_end": end_date,
                "period_type": "annual" if form == "10-K" else "quarterly",
            }
            for col in TAXONOMY:
                row[col] = resolved[col].get((end_date, form))
            rows.append(row)

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df["period_end"] = pd.to_datetime(df["period_end"]).dt.date
        df["source"] = "edgar"
        logger.info(
            f"{ticker}: {len(df)} periods "
            f"({df['period_end'].min()} → {df['period_end'].max()})"
        )
        return df

    def _resolve_shares(
        self,
        ticker: str,
        facts: Dict,
        start_date: str,
    ) -> Optional[pd.DataFrame]:
        """Extract shares_outstanding history from company facts."""
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        if not us_gaap:
            return None

        unit_type, tags = _SHARES_TAG
        tag_data = self._resolve_tag(us_gaap, unit_type, tags)
        if not tag_data:
            return None

        rows = [
            {"ticker": ticker, "date": end_date, "shares_outstanding": int(val)}
            for (end_date, form), val in tag_data.items()
            if end_date >= start_date and val and val > 0
        ]
        if not rows:
            return None

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    # ------------------------------------------------------------------
    # DuckDB writes
    # ------------------------------------------------------------------

    def _upsert_fundamentals(self, con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
        """INSERT OR IGNORE into fundamentals (yfinance rows take precedence)."""
        fund_cols = ["ticker", "period_end", "period_type"] + list(TAXONOMY.keys()) + ["source"]
        for c in fund_cols:
            if c not in df.columns:
                df[c] = None
        df = df[fund_cols].drop_duplicates(subset=["ticker", "period_end"], keep="last")

        con.register("_edgar_fund_batch", df)
        col_list = ", ".join(fund_cols)
        con.execute(f"""
            INSERT OR IGNORE INTO fundamentals ({col_list})
            SELECT {col_list} FROM _edgar_fund_batch
        """)
        return len(df)

    def _upsert_shares_history(self, con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
        """INSERT OR IGNORE into shares_history."""
        df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
        con.register("_edgar_shares_batch", df)
        con.execute("""
            INSERT OR IGNORE INTO shares_history (ticker, date, shares_outstanding)
            SELECT ticker, date, shares_outstanding FROM _edgar_shares_batch
        """)
        return len(df)
