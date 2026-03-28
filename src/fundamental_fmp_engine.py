"""FMP fundamentals backfill engine.

Delegates HTTP fetch + rate-limiting to FundamentalEngine(source='fmp'), which
already has the proven endpoint logic from data_curator.py. This layer only adds:
  - per-period pivoting (three stacked statements → one wide row per period)
  - column mapping (FMP JSON names → DuckDB schema names)
  - DuckDB write via INSERT OR REPLACE (FMP wins over yfinance on conflict)

Also exposes fetch_screener_universe() reusing the FMP_SCREENER_PARAMS from config.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import duckdb
import pandas as pd
import requests

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from src.fundamental_engine import FundamentalEngine

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"

# FMP JSON field → DuckDB column (income statement)
# Field names verified against /stable/income-statement response.
_INCOME_MAP: Dict[str, str] = {
    "revenue":                                  "total_revenue",
    "costOfRevenue":                            "cost_of_revenue",
    "grossProfit":                              "gross_profit",
    "operatingIncome":                          "operating_income",
    "operatingExpenses":                        "operating_expense",
    "ebit":                                     "ebit",
    "ebitda":                                   "ebitda",
    "netIncome":                                "net_income",
    "eps":                                      "basic_eps",
    "epsDiluted":                               "diluted_eps",
    "weightedAverageShsOut":                    "basic_avg_shares",
    "weightedAverageShsOutDil":                 "diluted_avg_shares",
    "researchAndDevelopmentExpenses":           "r_and_d",
    "sellingGeneralAndAdministrativeExpenses":  "sga",
    "incomeTaxExpense":                         "tax_provision",
}

# FMP JSON field → DuckDB column (balance sheet)
_BALANCE_MAP: Dict[str, str] = {
    "totalAssets":              "total_assets",
    "totalCurrentAssets":       "current_assets",
    "cashAndCashEquivalents":   "cash_and_equivalents",
    "inventory":                "inventory",
    "netReceivables":           "accounts_receivable",
    "totalDebt":                "total_debt",
    "netDebt":                  "net_debt",
    "totalCurrentLiabilities":  "current_liabilities",
    "longTermDebt":             "long_term_debt",
    "totalStockholdersEquity":  "stockholders_equity",
    "retainedEarnings":         "retained_earnings",
    # FMP field names for columns yfinance also provides
    "workingCapital":           "working_capital",
    "tangibleAssetValue":       "tangible_book_value",   # primary FMP field name
    "netTangibleAssets":        "tangible_book_value",   # fallback field name
    "investedCapital":          "invested_capital",
}

# FMP JSON field → DuckDB column (cash flow)
_CASHFLOW_MAP: Dict[str, str] = {
    "operatingCashFlow":                      "operating_cash_flow",
    "freeCashFlow":                           "free_cash_flow",
    "capitalExpenditure":                     "capex",
    "stockBasedCompensation":                 "stock_based_comp",
    "changeInWorkingCapital":                 "change_in_working_capital",
    "depreciationAndAmortization":            "depreciation_amortization",
    # field name variants seen across FMP plan versions
    "netCashProvidedByOperatingActivities":   "operating_cash_flow",
    "investmentsInPropertyPlantAndEquipment": "capex",
}

# All numeric columns that exist in the DuckDB fundamentals table
_ALL_NUMERIC_COLS = [
    "total_revenue", "cost_of_revenue", "gross_profit", "operating_income",
    "operating_expense", "ebit", "ebitda", "net_income",
    "basic_eps", "diluted_eps", "basic_avg_shares", "diluted_avg_shares",
    "r_and_d", "sga", "tax_provision",
    "total_assets", "current_assets", "cash_and_equivalents",
    "inventory", "accounts_receivable",
    "total_debt", "net_debt", "current_liabilities", "long_term_debt",
    "stockholders_equity", "retained_earnings",
    "working_capital", "invested_capital", "tangible_book_value",
    "operating_cash_flow", "free_cash_flow", "capex",
    "stock_based_comp", "change_in_working_capital", "depreciation_amortization",
]


class FundamentalFmpEngine:
    """Fetches FMP quarterly fundamentals and writes to the DuckDB fundamentals table.

    Delegates all HTTP + rate-limiting to FundamentalEngine(source='fmp') — the
    same engine used by data_curator.py — then reshapes and writes to DuckDB.
    """

    def __init__(self, db_path: Optional[str] = None, api_key: Optional[str] = None):
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        # FundamentalEngine(source='fmp') owns API key, rate limiter, retry logic
        self._fmp = FundamentalEngine(source="fmp", api_key=api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def backfill(
        self,
        tickers: List[str],
        start_date: str = "1995-01-01",
        workers: int = 4,
        overwrite: bool = False,
    ) -> Dict[str, int]:
        """Fetch FMP fundamentals for tickers and write to DuckDB.

        Args:
            overwrite: If True, DO UPDATE on conflict (explicit backfill).
                       If False, DO NOTHING (safe re-runs / daily forward).

        Returns:
            {'fundamentals': rows_written}
        """
        fund_frames: List[pd.DataFrame] = []

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._fetch_ticker, t, start_date): t
                for t in tickers
            }
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    df = future.result()
                except Exception as exc:
                    logger.warning(f"{ticker}: fetch error — {exc}")
                    continue
                if df is not None:
                    fund_frames.append(df)

        if not fund_frames:
            return {"fundamentals": 0}

        combined = pd.concat(fund_frames, ignore_index=True)
        rows_written = self._upsert(combined, overwrite=overwrite)
        return {"fundamentals": rows_written}

    def fetch_screener_universe(self) -> List[str]:
        """Return tickers from the FMP screener (uses FMP_SCREENER_PARAMS from config).

        Useful as a second opinion on which tickers should have fundamentals.
        """
        params = {**config.FMP_SCREENER_PARAMS, "apikey": self._fmp.api_key}
        try:
            r = requests.get(
                f"{config.FMP_BASE_URL}/stock-screener",
                params=params,
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list):
                logger.warning(f"FMP screener returned unexpected type: {type(data)}")
                return []
            tickers = [row["symbol"] for row in data if row.get("symbol")]
            logger.info(f"FMP screener returned {len(tickers)} tickers")
            return tickers
        except Exception as exc:
            logger.error(f"FMP screener fetch failed: {exc}")
            return []

    # ------------------------------------------------------------------
    # Fetch + reshape
    # ------------------------------------------------------------------

    def _fetch_ticker(self, ticker: str, start_date: str) -> Optional[pd.DataFrame]:
        """Fetch IS + BS + CF via the existing FundamentalEngine fetch layer.

        _fmp_fetch_statement returns a DataFrame of raw FMP rows for one statement.
        We pivot the three statements into one wide row per fiscal period.
        """
        income   = self._fmp._fmp_fetch_statement(ticker, "income-statement")
        balance  = self._fmp._fmp_fetch_statement(ticker, "balance-sheet-statement")
        cashflow = self._fmp._fmp_fetch_statement(ticker, "cash-flow-statement")

        if income is None or income.empty:
            logger.debug(f"{ticker}: no income statement from FMP")
            return None

        # FMP uses 'date' for fiscal period end, 'filingDate' or 'fillingDate' for filing
        income = income[income["date"] >= start_date]
        if income.empty:
            return None

        # Index balance/cashflow by date for O(1) lookups
        bs_by_date  = _index_by_date(balance)
        cf_by_date  = _index_by_date(cashflow)

        rows = []
        for _, inc in income.iterrows():
            period_end  = inc["date"]
            period_type = "annual" if inc.get("period") == "FY" else "quarterly"
            filing_date = inc.get("fillingDate") or inc.get("filingDate")

            row: Dict = {
                "ticker":       ticker,
                "period_end":   period_end,
                "period_type":  period_type,
                "filing_date":  filing_date,
                "source":       "fmp",
            }

            _apply_map(row, inc,                  _INCOME_MAP)
            _apply_map(row, bs_by_date.get(period_end,  {}), _BALANCE_MAP)
            _apply_map(row, cf_by_date.get(period_end,  {}), _CASHFLOW_MAP)

            rows.append(row)

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df["period_end"]  = pd.to_datetime(df["period_end"],  errors="coerce").dt.date
        df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce").dt.date
        logger.info(
            f"{ticker}: {len(df)} periods "
            f"({df['period_end'].min()} -> {df['period_end'].max()})"
        )
        return df

    # ------------------------------------------------------------------
    # DuckDB write
    # ------------------------------------------------------------------

    def _upsert(self, df: pd.DataFrame, overwrite: bool = False) -> int:
        """Write FMP rows to fundamentals table.

        overwrite=True  → DO UPDATE (explicit backfill — overwrites edgar/yfinance)
        overwrite=False → DO NOTHING (idempotent re-runs, never clobbers existing FMP rows)
        """
        all_cols = (
            ["ticker", "period_end", "period_type", "filing_date"]
            + _ALL_NUMERIC_COLS
            + ["source"]
        )
        for c in all_cols:
            if c not in df.columns:
                df[c] = None
        df = df[all_cols].drop_duplicates(subset=["ticker", "period_end"], keep="last")
        now = datetime.utcnow()
        df["fetched_at"] = now
        df["updated_at"] = now

        write_cols = all_cols + ["fetched_at", "updated_at"]
        col_list = ", ".join(write_cols)

        con = duckdb.connect(self.db_path)
        try:
            # Add fetched_at if it doesn't exist yet (one-time migration)
            con.execute("ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMP")

            con.register("_fmp_fund_batch", df)
            if overwrite:
                set_clause = ",\n                ".join(
                    f"{c} = EXCLUDED.{c}"
                    for c in write_cols
                    if c not in ("ticker", "period_end")
                )
                con.execute(f"""
                    INSERT INTO fundamentals ({col_list})
                    SELECT {col_list} FROM _fmp_fund_batch
                    ON CONFLICT (ticker, period_end) DO UPDATE SET
                        {set_clause}
                """)
            else:
                con.execute(f"""
                    INSERT INTO fundamentals ({col_list})
                    SELECT {col_list} FROM _fmp_fund_batch
                    ON CONFLICT (ticker, period_end) DO NOTHING
                """)
            return len(df)
        finally:
            con.close()


# ------------------------------------------------------------------
# Module helpers
# ------------------------------------------------------------------

def _index_by_date(df: Optional[pd.DataFrame]) -> Dict[str, pd.Series]:
    """Return {date_str: row_series} for fast period_end lookups."""
    if df is None or df.empty or "date" not in df.columns:
        return {}
    return {row["date"]: row for _, row in df.iterrows()}


def _apply_map(target: Dict, source, field_map: Dict[str, str]) -> None:
    """Copy fields from source (Series or dict) into target using field_map.

    First mapping wins — later entries in the map only fill gaps.
    """
    for fmp_col, db_col in field_map.items():
        if db_col in target:
            continue  # already populated by a higher-priority mapping
        try:
            v = source.get(fmp_col) if hasattr(source, "get") else None
            if v is None or (isinstance(v, float) and v != v):  # NaN check
                continue
            target[db_col] = float(v)
        except (TypeError, ValueError):
            pass
