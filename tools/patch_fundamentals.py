"""
Targeted patch tool for the fundamentals table.

Each --fix mode re-fetches data from FMP/EDGAR for affected tickers and surgically
updates only the broken field. New fix modes can be added as functions below.

Usage:
    python tools/patch_fundamentals.py --fix filing_date --dry-run
    python tools/patch_fundamentals.py --fix filing_date
    python tools/patch_fundamentals.py --fix filing_date --tickers KD RCAT NEM
    python tools/patch_fundamentals.py --fix filing_date_zero --dry-run
    python tools/patch_fundamentals.py --fix filing_date_zero
    python tools/patch_fundamentals.py --fix filing_date_stale_historical --dry-run
    python tools/patch_fundamentals.py --fix filing_date_stale_historical
"""

import argparse
import sys
import time
from datetime import date, timedelta
from typing import Optional

import duckdb
import pandas as pd
import requests

sys.path.insert(0, ".")
from config import DUCKDB_PATH


_EDGAR_HEADERS = {"User-Agent": "quantamental-research research@example.com"}
_EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_EDGAR_RATE_LIMIT_SLEEP = 0.12  # SEC allows ~10 req/s


def _load_edgar_ticker_map() -> dict[str, int]:
    """Download SEC ticker -> CIK mapping. Returns {ticker: cik_int}."""
    r = requests.get(_EDGAR_TICKERS_URL, headers=_EDGAR_HEADERS, timeout=15)
    r.raise_for_status()
    return {v["ticker"]: v["cik_str"] for v in r.json().values()}


def _fetch_edgar_filing_dates(cik: int) -> dict[str, str]:
    """
    Fetch all 10-K/10-Q filing dates from EDGAR for a given CIK.
    Returns {period_of_report_str: filing_date_str} e.g. {"2026-01-31": "2026-03-20"}.
    """
    url = _EDGAR_SUBMISSIONS_URL.format(cik=cik)
    r = requests.get(url, headers=_EDGAR_HEADERS, timeout=15)
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    filings = r.json().get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    filing_dates = filings.get("filingDate", [])
    report_dates = filings.get("reportDate", [])
    result: dict[str, str] = {}
    for form, filed, period in zip(forms, filing_dates, report_dates):
        if form in ("10-K", "10-Q") and period and filed:
            result[period] = filed
    return result


# ---------------------------------------------------------------------------
# Fix: filing_date < period_end (legacy bad FMP mapping)
# ---------------------------------------------------------------------------

def audit_filing_date(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("""
        SELECT ticker, period_end, filing_date,
               DATE_DIFF('day', period_end, filing_date) AS days_diff
        FROM fundamentals
        WHERE filing_date < period_end
        ORDER BY ticker, period_end
    """).df()


def fix_filing_date(con: duckdb.DuckDBPyConnection, dry_run: bool, tickers: list[str] = None) -> None:
    """
    NULL out filing_date where filing_date < period_end.

    FMP confirmed it cannot supply correct dates for these rows (bad source data).
    Nulling is safe: XGBoost handles NULL in days_since_report natively, and a
    missing date is less harmful than a wrong one causing look-ahead contamination.
    """
    bad = audit_filing_date(con)
    if bad.empty:
        print("[OK] No rows with filing_date < period_end — nothing to fix.")
        return

    if tickers:
        bad = bad[bad["ticker"].isin(tickers)]

    affected_tickers = sorted(bad["ticker"].unique())
    print(f"\nfiling_date < period_end: {len(bad)} rows across {len(affected_tickers)} tickers")
    print(f"Strategy: NULL out filing_date (FMP source data is permanently incorrect for these rows)")

    if dry_run:
        print(f"\n[DRY RUN] Would NULL filing_date for {len(bad)} rows:")
        for _, row in bad.head(15).iterrows():
            print(f"   {row['ticker']}  period={row['period_end'].date()}  bad_date={row['filing_date'].date()}  ({row['days_diff']}d off)")
        if len(bad) > 15:
            print(f"   ... and {len(bad) - 15} more")
        print("\n[DRY RUN] No changes made.")
        return

    ticker_list = bad["ticker"].tolist()
    period_list = [r.date() for r in bad["period_end"]]
    rows_data = list(zip(ticker_list, period_list))

    updated = 0
    for ticker, period_end in rows_data:
        con.execute(
            "UPDATE fundamentals SET filing_date = NULL WHERE ticker = ? AND period_end = ?",
            [ticker, period_end],
        )
        updated += 1

    print(f"[OK] Nulled filing_date for {updated} rows.")

    remaining = audit_filing_date(con)
    print(f"[OK] Remaining bad rows after patch: {len(remaining)}")


# ---------------------------------------------------------------------------
# Fix: filing_date = period_end (FMP placeholder — look up real date via EDGAR)
# ---------------------------------------------------------------------------

def _audit_filing_date_zero(con: duckdb.DuckDBPyConnection, tickers: Optional[list[str]]) -> pd.DataFrame:
    ticker_filter = f"AND ticker IN ({','.join('?' * len(tickers))})" if tickers else ""
    params = tickers if tickers else []
    return con.execute(f"""
        SELECT ticker, period_end, filing_date, period_type, source
        FROM fundamentals
        WHERE filing_date IS NOT NULL
          AND filing_date = period_end
          {ticker_filter}
        ORDER BY ticker, period_end
    """, params).df()


def fix_filing_date_zero(con: duckdb.DuckDBPyConnection, dry_run: bool, tickers: Optional[list[str]] = None) -> None:
    """
    Fix rows where filing_date = period_end (FMP used period_end as a placeholder).

    Strategy (per ticker):
      1. Fetch real filing date from SEC EDGAR (10-K/10-Q submissions).
      2. If EDGAR has no match, fall back to period_end + 45 days.

    The +45d fallback is conservative: Q filings are due 40-45 days after quarter end
    for large accelerated filers. Better a slight overestimate than look-ahead contamination.
    """
    bad = _audit_filing_date_zero(con, tickers)
    if bad.empty:
        print("[OK] No rows with filing_date = period_end — nothing to fix.")
        return

    affected_tickers = sorted(bad["ticker"].unique())
    print(f"\nfiling_date = period_end: {len(bad)} rows across {len(affected_tickers)} tickers")
    print("Strategy: EDGAR lookup -> fall back to period_end + 45d")

    print("  Loading EDGAR ticker -> CIK map...", end=" ", flush=True)
    ticker_map = _load_edgar_ticker_map()
    print("done.")

    updates: list[tuple[date, str, date]] = []  # (new_filing_date, ticker, period_end)
    stats = {"edgar_hit": 0, "edgar_miss": 0, "fallback": 0, "no_cik": 0}

    for ticker, group in bad.groupby("ticker"):
        cik = ticker_map.get(ticker)
        edgar_dates: dict[str, str] = {}
        if cik:
            try:
                edgar_dates = _fetch_edgar_filing_dates(cik)
                time.sleep(_EDGAR_RATE_LIMIT_SLEEP)
            except Exception as e:
                print(f"  ⚠️  EDGAR fetch failed for {ticker}: {e}")
        else:
            stats["no_cik"] += 1

        for _, row in group.iterrows():
            period_str = str(row["period_end"].date()) if hasattr(row["period_end"], "date") else str(row["period_end"])
            period_dt = row["period_end"].date() if hasattr(row["period_end"], "date") else row["period_end"]

            if period_str in edgar_dates:
                new_date = date.fromisoformat(edgar_dates[period_str])
                stats["edgar_hit"] += 1
            else:
                new_date = period_dt + timedelta(days=45)
                stats["fallback"] += 1
                if edgar_dates:
                    stats["edgar_miss"] += 1

            updates.append((new_date, ticker, period_dt))

    print(f"\n  Results: {stats['edgar_hit']} EDGAR hits | {stats['edgar_miss']} EDGAR misses | "
          f"{stats['fallback']} fallbacks (+45d) | {stats['no_cik']} tickers not in EDGAR")

    if dry_run:
        print(f"\n[DRY RUN] Would update filing_date for {len(updates)} rows:")
        for new_date, ticker, period_end in updates[:15]:
            src = "EDGAR" if (str(period_end) in _fetch_edgar_filing_dates.__doc__ or True) else "+45d"
            print(f"   {ticker}  period={period_end}  new_filing_date={new_date}")
        if len(updates) > 15:
            print(f"   ... and {len(updates) - 15} more")
        print("\n[DRY RUN] No changes made.")
        return

    updated = 0
    for new_date, ticker, period_end in updates:
        con.execute(
            "UPDATE fundamentals SET filing_date = ? WHERE ticker = ? AND period_end = ?",
            [new_date, ticker, period_end],
        )
        updated += 1

    print(f"[OK] Updated filing_date for {updated} rows.")
    remaining = con.execute(
        "SELECT COUNT(*) FROM fundamentals WHERE filing_date IS NOT NULL AND filing_date = period_end"
    ).fetchone()[0]
    print(f"[OK] Remaining filing_date=period_end rows: {remaining}")


# ---------------------------------------------------------------------------
# Fix: filing_date > period_end by >90 days (FMP used download date for historical data)
# ---------------------------------------------------------------------------

def _audit_filing_date_stale_historical(con: duckdb.DuckDBPyConnection, tickers: Optional[list[str]]) -> pd.DataFrame:
    ticker_filter = f"AND ticker IN ({','.join('?' * len(tickers))})" if tickers else ""
    params = tickers if tickers else []
    return con.execute(f"""
        SELECT ticker, period_end, filing_date, period_type, source,
               DATE_DIFF('day', period_end, filing_date) AS gap_days
        FROM fundamentals
        WHERE filing_date IS NOT NULL
          AND DATE_DIFF('day', period_end, filing_date) > 90
          {ticker_filter}
        ORDER BY gap_days DESC, ticker, period_end
    """, params).df()


def fix_filing_date_stale_historical(
    con: duckdb.DuckDBPyConnection, dry_run: bool, tickers: Optional[list[str]] = None
) -> None:
    """
    Fix rows where filing_date is >90 days after period_end.

    Two sub-cases:
      A. Gap > 365 days: almost certainly FMP used its own data-download date as filing_date
         for historical filings it back-populated. These are NULL'd out — there is no way to
         recover the correct date, and a NULL is safer than a misleading date.
      B. Gap 91-365 days: could be legitimate late filers or FMP artifacts. We try EDGAR first;
         if EDGAR has no match, NULL out (don't guess).
    """
    bad = _audit_filing_date_stale_historical(con, tickers)
    if bad.empty:
        print("[OK] No rows with filing_date >90 days after period_end — nothing to fix.")
        return

    very_stale = bad[bad["gap_days"] > 365]
    moderate = bad[(bad["gap_days"] > 90) & (bad["gap_days"] <= 365)]
    affected_tickers = sorted(bad["ticker"].unique())
    print(f"\nfiling_date >90d after period_end: {len(bad)} rows across {len(affected_tickers)} tickers")
    print(f"  Gap >365d (null out directly): {len(very_stale)} rows")
    print(f"  Gap 91-365d (try EDGAR first): {len(moderate)} rows")

    updates_null: list[tuple[str, date]] = []    # (ticker, period_end) -> NULL
    updates_edgar: list[tuple[date, str, date]] = []  # (new_date, ticker, period_end)

    # Sub-case A: definitely stale — null immediately
    for _, row in very_stale.iterrows():
        period_dt = row["period_end"].date() if hasattr(row["period_end"], "date") else row["period_end"]
        updates_null.append((row["ticker"], period_dt))

    # Sub-case B: try EDGAR, fall back to NULL
    if not moderate.empty:
        print("  Loading EDGAR ticker -> CIK map...", end=" ", flush=True)
        ticker_map = _load_edgar_ticker_map()
        print("done.")
        stats = {"edgar_hit": 0, "null_fallback": 0}

        for ticker, group in moderate.groupby("ticker"):
            cik = ticker_map.get(ticker)
            edgar_dates: dict[str, str] = {}
            if cik:
                try:
                    edgar_dates = _fetch_edgar_filing_dates(cik)
                    time.sleep(_EDGAR_RATE_LIMIT_SLEEP)
                except Exception as e:
                    print(f"  ⚠️  EDGAR fetch failed for {ticker}: {e}")

            for _, row in group.iterrows():
                period_dt = row["period_end"].date() if hasattr(row["period_end"], "date") else row["period_end"]
                period_str = str(period_dt)
                if period_str in edgar_dates:
                    new_date = date.fromisoformat(edgar_dates[period_str])
                    updates_edgar.append((new_date, ticker, period_dt))
                    stats["edgar_hit"] += 1
                else:
                    updates_null.append((ticker, period_dt))
                    stats["null_fallback"] += 1

        print(f"  EDGAR: {stats['edgar_hit']} corrected | {stats['null_fallback']} nulled (no EDGAR match)")

    total_changes = len(updates_null) + len(updates_edgar)
    if dry_run:
        print(f"\n[DRY RUN] Would null {len(updates_null)} rows and update {len(updates_edgar)} via EDGAR:")
        for ticker, period_end in updates_null[:10]:
            print(f"   NULL  {ticker}  period={period_end}")
        for new_date, ticker, period_end in updates_edgar[:10]:
            print(f"   SET   {ticker}  period={period_end}  new_date={new_date}")
        if total_changes > 20:
            print(f"   ... and {total_changes - 20} more")
        print("\n[DRY RUN] No changes made.")
        return

    nulled = 0
    for ticker, period_end in updates_null:
        con.execute(
            "UPDATE fundamentals SET filing_date = NULL WHERE ticker = ? AND period_end = ?",
            [ticker, period_end],
        )
        nulled += 1

    edgar_updated = 0
    for new_date, ticker, period_end in updates_edgar:
        con.execute(
            "UPDATE fundamentals SET filing_date = ? WHERE ticker = ? AND period_end = ?",
            [new_date, ticker, period_end],
        )
        edgar_updated += 1

    print(f"[OK] Nulled {nulled} rows | EDGAR-corrected {edgar_updated} rows")
    remaining = con.execute(
        "SELECT COUNT(*) FROM fundamentals WHERE filing_date IS NOT NULL AND DATE_DIFF('day', period_end, filing_date) > 90"
    ).fetchone()[0]
    print(f"[OK] Remaining filing_date >90d rows: {remaining}")


# ---------------------------------------------------------------------------
# Registry — add new fix modes here
# ---------------------------------------------------------------------------

FIX_MODES = {
    "filing_date": {
        "description": "Patch rows where filing_date < period_end (bad FMP date mapping)",
        "fn": fix_filing_date,
    },
    "filing_date_zero": {
        "description": "Patch rows where filing_date = period_end (FMP placeholder) via EDGAR lookup, fallback +45d",
        "fn": fix_filing_date_zero,
    },
    "filing_date_stale_historical": {
        "description": "Patch rows where filing_date >90d after period_end (FMP used download date for old filings)",
        "fn": fix_filing_date_stale_historical,
    },
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Targeted patch tool for fundamentals table")
    parser.add_argument(
        "--fix", required=True, choices=list(FIX_MODES),
        help="Which field/issue to fix: " + ", ".join(f"{k} ({v['description']})" for k, v in FIX_MODES.items()),
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    parser.add_argument("--tickers", nargs="+", metavar="TICKER", help="Limit to specific tickers")
    args = parser.parse_args()

    con = duckdb.connect(str(DUCKDB_PATH), read_only=args.dry_run)
    try:
        FIX_MODES[args.fix]["fn"](con, args.dry_run, args.tickers)
    finally:
        con.close()


if __name__ == "__main__":
    main()
