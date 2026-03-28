"""
T1 Data Quality Audit
---------------------
Evaluates data quality for all four Phase 1 (T1) ingestion tables:
  company_profiles, price_data, fundamentals, shares_history

Run:
    python tools/audit_t1_data_quality.py
    python tools/audit_t1_data_quality.py --json          # machine-readable output
    python tools/audit_t1_data_quality.py --warn-only     # exit 1 if any WARNING/FAIL
"""

import argparse
import json
import sys
from datetime import date, timedelta
from typing import Any

import duckdb

sys.path.insert(0, ".")
from config import DUCKDB_PATH

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
STALE_PRICE_DAYS = 5          # flag tickers with no price data in last N business days
STALE_SHARES_DAYS = 30        # flag tickers with no shares data in last N days
FUNDAMENTAL_NULL_WARN_PCT = 15.0   # warn if key column is >15% null
FUNDAMENTAL_NULL_FAIL_PCT = 50.0   # fail if key column is >50% null
MIN_PRICE_COVERAGE_PCT = 80.0      # warn if price coverage drops below this
MIN_SHARES_COVERAGE_PCT = 60.0     # warn if shares coverage drops below this
MIN_FUND_COVERAGE_PCT = 60.0       # warn if fundamentals coverage drops below this

FUNDAMENTAL_KEY_COLS = [
    "total_revenue", "net_income", "gross_profit", "operating_income",
    "ebit", "ebitda", "total_assets", "stockholders_equity",
    "operating_cash_flow", "free_cash_flow", "basic_eps", "diluted_eps",
    "filing_date",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_results: list[dict[str, Any]] = []


def _check(section: str, name: str, status: str, value: Any, detail: str = "") -> dict:
    entry = {"section": section, "check": name, "status": status, "value": value, "detail": detail}
    _results.append(entry)
    return entry


def _pct(part: int, total: int) -> float:
    return round(part / total * 100, 1) if total else 0.0


def _status_coverage(pct: float, warn_threshold: float) -> str:
    if pct >= warn_threshold:
        return "OK"
    return "WARNING"


# ---------------------------------------------------------------------------
# Section 1: Coverage
# ---------------------------------------------------------------------------
def check_coverage(con: duckdb.DuckDBPyConnection) -> None:
    total_cp = con.execute("SELECT COUNT(DISTINCT ticker) FROM company_profiles").fetchone()[0]
    _check("coverage", "company_profiles_tickers", "INFO", total_cp, "Total tickers in company_profiles (universe seed)")

    for table, min_pct in [
        ("price_data", MIN_PRICE_COVERAGE_PCT),
        ("shares_history", MIN_SHARES_COVERAGE_PCT),
        ("fundamentals", MIN_FUND_COVERAGE_PCT),
    ]:
        covered = con.execute(f"""
            SELECT COUNT(DISTINCT t.ticker)
            FROM {table} t
            INNER JOIN company_profiles cp ON t.ticker = cp.ticker
        """).fetchone()[0]
        pct = _pct(covered, total_cp)
        status = _status_coverage(pct, min_pct)
        _check("coverage", f"{table}_coverage_pct", status, pct,
               f"{covered}/{total_cp} company_profile tickers present in {table}")

    # CP tickers missing entirely from each downstream table
    for table in ("price_data", "shares_history", "fundamentals"):
        missing = con.execute(f"""
            SELECT COUNT(DISTINCT cp.ticker)
            FROM company_profiles cp
            LEFT JOIN (SELECT DISTINCT ticker FROM {table}) t ON cp.ticker = t.ticker
            WHERE t.ticker IS NULL
        """).fetchone()[0]
        status = "OK" if missing == 0 else "WARNING"
        _check("coverage", f"{table}_missing_from_cp", status, missing,
               f"Tickers in company_profiles with NO rows in {table}")

    # Orphan tickers: in downstream table but NOT in company_profiles
    for table in ("price_data", "shares_history", "fundamentals"):
        orphans = con.execute(f"""
            SELECT COUNT(DISTINCT t.ticker)
            FROM {table} t
            LEFT JOIN company_profiles cp ON t.ticker = cp.ticker
            WHERE cp.ticker IS NULL
        """).fetchone()[0]
        status = "OK" if orphans == 0 else "WARNING"
        by_source = ""
        if table == "fundamentals" and orphans > 0:
            rows = con.execute("""
                SELECT f.source, COUNT(DISTINCT f.ticker) cnt
                FROM fundamentals f
                LEFT JOIN company_profiles cp ON f.ticker = cp.ticker
                WHERE cp.ticker IS NULL
                GROUP BY f.source ORDER BY cnt DESC
            """).fetchall()
            by_source = " | by source: " + ", ".join(f"{s}={c}" for s, c in rows)
        _check("coverage", f"{table}_orphan_tickers", status, orphans,
               f"Tickers in {table} not in company_profiles (historical / purge candidates){by_source}")


# ---------------------------------------------------------------------------
# Section 2: Freshness
# ---------------------------------------------------------------------------
def check_freshness(con: duckdb.DuckDBPyConnection) -> None:
    today = date.today()

    # price_data: overall date range
    mn, mx = con.execute("SELECT MIN(date), MAX(date) FROM price_data").fetchone()
    days_since = (today - mx).days if mx else 9999
    status = "OK" if days_since <= STALE_PRICE_DAYS else "WARNING"
    _check("freshness", "price_data_max_date", status, str(mx),
           f"{days_since} calendar days since last price row")

    # price_data: stale tickers (no data in last STALE_PRICE_DAYS calendar days)
    # Only check is_active=TRUE tickers — delisted tickers are expected to have old last dates
    cutoff = today - timedelta(days=STALE_PRICE_DAYS)
    stale = con.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT ticker, MAX(date) last_date FROM price_data
            INNER JOIN company_profiles cp USING (ticker)
            WHERE cp.is_active = TRUE
            GROUP BY ticker
        ) WHERE last_date < '{cutoff}'
    """).fetchone()[0]
    covered = con.execute("SELECT COUNT(DISTINCT ticker) FROM price_data INNER JOIN company_profiles cp USING (ticker) WHERE cp.is_active = TRUE").fetchone()[0]
    pct_stale = _pct(stale, covered)
    status = "OK" if pct_stale < 5.0 else "WARNING"
    _check("freshness", "price_data_stale_tickers", status, stale,
           f"{pct_stale}% of active universe tickers have no price data since {cutoff} (delisted excluded)")

    # shares_history: max date
    mn_s, mx_s = con.execute("SELECT MIN(date), MAX(date) FROM shares_history").fetchone()
    days_since_s = (today - mx_s).days if mx_s else 9999
    status = "OK" if days_since_s <= STALE_SHARES_DAYS else "WARNING"
    _check("freshness", "shares_history_max_date", status, str(mx_s),
           f"{days_since_s} days since last shares row")

    # fundamentals: max period_end (quarterly filings lag naturally)
    mn_f, mx_f = con.execute("SELECT MIN(period_end), MAX(period_end) FROM fundamentals WHERE period_end <= CURRENT_DATE").fetchone()
    expected_cutoff = today - timedelta(days=120)  # Q filings lag ~90-120 days
    status = "OK" if mx_f and mx_f >= expected_cutoff else "WARNING"
    _check("freshness", "fundamentals_max_period_end", status, str(mx_f),
           f"Latest period_end in fundamentals (historical filings — lag expected)")

    # fundamentals: future period_end (data quality issue)
    future = con.execute("SELECT COUNT(*) FROM fundamentals WHERE period_end > CURRENT_DATE").fetchone()[0]
    status = "OK" if future == 0 else "WARNING"
    _check("freshness", "fundamentals_future_period_end", status, future,
           "Rows with period_end > today (bad estimate data or data entry error)")


# ---------------------------------------------------------------------------
# Section 3: Fundamentals Column Completeness
# ---------------------------------------------------------------------------
def check_fundamental_completeness(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
    _check("fundamentals", "total_rows", "INFO", total, "Total rows in fundamentals table")

    # Null % per key column
    for col in FUNDAMENTAL_KEY_COLS:
        nulls = con.execute(f"SELECT COUNT(*) FROM fundamentals WHERE {col} IS NULL").fetchone()[0]
        pct = _pct(nulls, total)
        if pct >= FUNDAMENTAL_NULL_FAIL_PCT:
            status = "FAIL"
        elif pct >= FUNDAMENTAL_NULL_WARN_PCT:
            status = "WARNING"
        else:
            status = "OK"
        _check("fundamentals", f"null_pct_{col}", status, pct, f"{nulls}/{total} rows null")

    # Source breakdown
    rows = con.execute("SELECT source, COUNT(DISTINCT ticker) tickers, COUNT(*) row_cnt FROM fundamentals GROUP BY source ORDER BY tickers DESC").fetchall()
    for source, tickers, row_cnt in rows:
        _check("fundamentals", f"source_{source}", "INFO", tickers,
               f"{row_cnt} rows from source='{source}'")

    # Tickers with very few periods (< 4 = less than 1 year of quarterly data)
    sparse = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT ticker, COUNT(*) cnt FROM fundamentals
            INNER JOIN company_profiles cp USING (ticker)
            GROUP BY ticker HAVING cnt < 4
        )
    """).fetchone()[0]
    covered_f = con.execute("SELECT COUNT(DISTINCT ticker) FROM fundamentals INNER JOIN company_profiles cp USING (ticker)").fetchone()[0]
    pct_sparse = _pct(sparse, covered_f)
    status = "WARNING" if pct_sparse > 10.0 else "OK"
    _check("fundamentals", "sparse_tickers_lt4_periods", status, sparse,
           f"{pct_sparse}% of covered tickers have <4 fundamental periods")

    # Average periods per ticker
    avg_periods = con.execute("""
        SELECT AVG(cnt) FROM (SELECT ticker, COUNT(*) cnt FROM fundamentals GROUP BY ticker)
    """).fetchone()[0]
    _check("fundamentals", "avg_periods_per_ticker", "INFO", round(avg_periods, 1),
           "Average number of fundamental periods per ticker")


# ---------------------------------------------------------------------------
# Section 4: Price Data Integrity
# ---------------------------------------------------------------------------
def check_price_integrity(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM price_data").fetchone()[0]
    _check("price_data", "total_rows", "INFO", total, "Total rows in price_data")

    # Duplicate (ticker, date)
    dupes = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT ticker, date, COUNT(*) c FROM price_data GROUP BY ticker, date HAVING c > 1
        )
    """).fetchone()[0]
    _check("price_data", "duplicate_ticker_date", "FAIL" if dupes > 0 else "OK", dupes,
           "Rows with duplicate (ticker, date) keys")

    # Rows with NULL close price
    null_close = con.execute("SELECT COUNT(*) FROM price_data WHERE close IS NULL OR close <= 0").fetchone()[0]
    pct = _pct(null_close, total)
    _check("price_data", "null_or_zero_close", "FAIL" if null_close > 0 else "OK", null_close,
           f"{pct}% rows with NULL or non-positive close price")

    # Rows with negative/zero volume (excluding weekends/holidays already filtered)
    bad_vol = con.execute("SELECT COUNT(*) FROM price_data WHERE volume = 0").fetchone()[0]
    pct_v = _pct(bad_vol, total)
    status = "WARNING" if pct_v > 1.0 else "OK"
    _check("price_data", "zero_volume_rows", status, bad_vol,
           f"{pct_v}% rows with volume=0 (may indicate halted/thin trading days)")

    # Extreme price outliers: single-day close move > 200%
    outliers = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT ticker, date, close,
                LAG(close) OVER (PARTITION BY ticker ORDER BY date) prev_close
            FROM price_data
        ) WHERE prev_close > 0 AND ABS(close / prev_close - 1) > 2.0
    """).fetchone()[0]
    status = "WARNING" if outliers > 100 else "OK"
    _check("price_data", "extreme_price_moves_gt200pct", status, outliers,
           "Rows with single-day price move >200% (may indicate data errors or reverse splits)")

    # Top tickers with extreme moves — informational breakdown
    rows = con.execute("""
        WITH returns AS (
            SELECT ticker, date, close,
                   LAG(close) OVER (PARTITION BY ticker ORDER BY date) AS prev_close
            FROM price_data WHERE close > 0
        )
        SELECT ticker,
               COUNT(*) AS n_events,
               ROUND(MAX(ABS(close / prev_close - 1) * 100), 0) AS max_move_pct,
               MIN(date) AS first_event,
               MAX(date) AS last_event
        FROM returns
        WHERE prev_close > 0 AND ABS(close / prev_close - 1) > 2.0
        GROUP BY ticker
        ORDER BY n_events DESC
        LIMIT 20
    """).fetchall()
    if rows:
        detail = " | ".join(
            f"{t}:{n}x(max {m:.0f}%)" for t, n, m, _, _ in rows
        )
        _check("price_data", "extreme_movers_top20", "INFO", len(rows),
               f"Top tickers by event count — {detail}")

    # Gap detection: compare each ticker's row count against SPY trading days
    # in the same date range. SPY is the ground truth for expected trading days.
    gap_tickers = con.execute("""
        WITH ticker_stats AS (
            SELECT ticker, COUNT(*) AS actual_rows,
                   MIN(date) AS start_date, MAX(date) AS end_date
            FROM price_data
            INNER JOIN company_profiles cp USING (ticker)
            WHERE cp.is_active = TRUE
            GROUP BY ticker
        ),
        spy_counts AS (
            SELECT ts.ticker, ts.actual_rows, ts.start_date, ts.end_date,
                   COUNT(spy.date) AS spy_rows
            FROM ticker_stats ts
            LEFT JOIN price_data spy
              ON spy.ticker = 'SPY'
             AND spy.date BETWEEN ts.start_date AND ts.end_date
            GROUP BY ts.ticker, ts.actual_rows, ts.start_date, ts.end_date
        )
        SELECT COUNT(*) FROM spy_counts
        WHERE spy_rows > 30
          AND actual_rows < spy_rows * 0.80
    """).fetchone()[0]
    status = "FAIL" if gap_tickers > 0 else "OK"
    _check("price_data", "tickers_with_gaps", status, gap_tickers,
           "Active tickers with >20% fewer rows than SPY in the same date range")

    if gap_tickers > 0:
        rows = con.execute("""
            WITH ticker_stats AS (
                SELECT ticker, COUNT(*) AS actual_rows,
                       MIN(date) AS start_date, MAX(date) AS end_date
                FROM price_data
                INNER JOIN company_profiles cp USING (ticker)
                WHERE cp.is_active = TRUE
                GROUP BY ticker
            ),
            spy_counts AS (
                SELECT ts.ticker, ts.actual_rows, ts.start_date, ts.end_date,
                       COUNT(spy.date) AS spy_rows
                FROM ticker_stats ts
                LEFT JOIN price_data spy
                  ON spy.ticker = 'SPY'
                 AND spy.date BETWEEN ts.start_date AND ts.end_date
                GROUP BY ts.ticker, ts.actual_rows, ts.start_date, ts.end_date
            )
            SELECT ticker, actual_rows, spy_rows,
                   ROUND((1.0 - actual_rows * 1.0 / spy_rows) * 100, 1) AS missing_pct,
                   start_date, end_date
            FROM spy_counts
            WHERE spy_rows > 30
              AND actual_rows < spy_rows * 0.80
            ORDER BY missing_pct DESC
            LIMIT 20
        """).fetchall()
        detail = " | ".join(f"{t}:{m:.0f}%missing({a}/{e}rows)" for t, a, e, m, _, _ in rows)
        _check("price_data", "gap_tickers_top20", "INFO", len(rows),
               f"Top gap tickers vs SPY — {detail}")

    # Date range
    mn, mx = con.execute("SELECT MIN(date), MAX(date) FROM price_data").fetchone()
    _check("price_data", "date_range", "INFO", f"{mn} to {mx}", "Full date range in price_data")


# ---------------------------------------------------------------------------
# Section 5: Macro Data (t1_macro) Integrity
# ---------------------------------------------------------------------------
def check_macro_integrity(con: duckdb.DuckDBPyConnection) -> None:
    has_table = con.execute("""
        SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 't1_macro'
    """).fetchone()[0] > 0
    if not has_table:
        _check("t1_macro", "table_exists", "FAIL", False, "t1_macro table not found")
        return

    total = con.execute("SELECT COUNT(*) FROM t1_macro").fetchone()[0]
    _check("t1_macro", "total_rows", "INFO", total, "Total rows in t1_macro")

    if total == 0:
        _check("t1_macro", "table_empty", "FAIL", 0, "t1_macro has no rows")
        return

    # Freshness
    today = date.today()
    mn, mx = con.execute("SELECT MIN(date), MAX(date) FROM t1_macro").fetchone()
    days_since = (today - mx).days if mx else 9999
    status = "OK" if days_since <= STALE_PRICE_DAYS else "WARNING"
    _check("t1_macro", "max_date", status, str(mx),
           f"{days_since} calendar days since last t1_macro row")
    _check("t1_macro", "date_range", "INFO", f"{mn} to {mx}", "Full date range")

    # NULL checks on critical columns (spy_close drives price_vs_spy -> trend_ok)
    for col in ["spy_close", "qqq_close", "vix_close"]:
        nulls = con.execute(f"SELECT COUNT(*) FROM t1_macro WHERE {col} IS NULL").fetchone()[0]
        pct = _pct(nulls, total)
        _check("t1_macro", f"null_{col}", "FAIL" if nulls > 0 else "OK", nulls,
               f"{pct}% rows with NULL {col}")

    # Date gaps: find dates in price_data that are missing from t1_macro
    # This is the exact bug that broke trend_ok across all tickers
    gap_dates = con.execute("""
        SELECT pd_date FROM (
            SELECT DISTINCT date AS pd_date FROM price_data
            WHERE date >= (SELECT MIN(date) FROM t1_macro)
              AND date <= (SELECT MAX(date) FROM t1_macro)
        ) pd
        LEFT JOIN t1_macro m ON pd.pd_date = m.date
        WHERE m.date IS NULL
        ORDER BY pd_date DESC
        LIMIT 20
    """).fetchall()
    gap_count = len(gap_dates)
    status = "FAIL" if gap_count > 0 else "OK"
    detail = f"{gap_count} trading days in price_data have no t1_macro row"
    if gap_count > 0:
        dates_str = ", ".join(str(r[0]) for r in gap_dates[:10])
        detail += f" (recent: {dates_str})"
    _check("t1_macro", "date_gaps_vs_price_data", status, gap_count, detail)


# ---------------------------------------------------------------------------
# Section 6: Shares History Integrity
# ---------------------------------------------------------------------------
def check_shares_integrity(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM shares_history").fetchone()[0]
    _check("shares_history", "total_rows", "INFO", total, "Total rows in shares_history")

    dupes = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT ticker, date, COUNT(*) c FROM shares_history GROUP BY ticker, date HAVING c > 1
        )
    """).fetchone()[0]
    _check("shares_history", "duplicate_ticker_date", "FAIL" if dupes > 0 else "OK", dupes,
           "Duplicate (ticker, date) keys")

    null_shares = con.execute("SELECT COUNT(*) FROM shares_history WHERE shares_outstanding IS NULL OR shares_outstanding <= 0").fetchone()[0]
    pct = _pct(null_shares, total)
    status = "WARNING" if pct > 1.0 else "OK"
    _check("shares_history", "null_or_zero_shares", status, null_shares,
           f"{pct}% rows with NULL or non-positive shares_outstanding")

    mn, mx = con.execute("SELECT MIN(date), MAX(date) FROM shares_history").fetchone()
    _check("shares_history", "date_range", "INFO", f"{mn} to {mx}", "Full date range in shares_history")


# ---------------------------------------------------------------------------
# Render output
# ---------------------------------------------------------------------------
STATUS_ORDER = {"FAIL": 0, "WARNING": 1, "OK": 2, "INFO": 3}
STATUS_PREFIX = {"FAIL": "[FAIL]   ", "WARNING": "[WARN]   ", "OK": "[OK]     ", "INFO": "[INFO]   "}


def _render_text(warn_only: bool) -> int:
    exit_code = 0
    current_section = None
    for r in _results:
        if r["section"] != current_section:
            current_section = r["section"]
            print(f"\n{'='*60}")
            print(f"  {current_section.upper()}")
            print(f"{'='*60}")
        prefix = STATUS_PREFIX.get(r["status"], "[?]      ")
        val = str(r["value"])
        if isinstance(r["value"], float):
            val = f"{r['value']:.1f}%"
        line = f"  {prefix}{r['check']:<42} {val}"
        if r["detail"]:
            line += f"\n           {r['detail']}"
        if not warn_only or r["status"] in ("FAIL", "WARNING"):
            print(line)
        if r["status"] in ("FAIL", "WARNING"):
            exit_code = 1
    return exit_code


def _summary() -> None:
    counts = {"FAIL": 0, "WARNING": 0, "OK": 0, "INFO": 0}
    for r in _results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"\n{'='*60}")
    print(f"  SUMMARY: {counts['FAIL']} FAIL | {counts['WARNING']} WARNING | {counts['OK']} OK | {counts['INFO']} INFO")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="T1 data quality audit")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--warn-only", action="store_true", help="Only print warnings/failures; exit 1 if any found")
    args = parser.parse_args()

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        print(f"Auditing T1 tables in: {DUCKDB_PATH}")
        check_coverage(con)
        check_freshness(con)
        check_fundamental_completeness(con)
        check_price_integrity(con)
        check_macro_integrity(con)
        check_shares_integrity(con)
    finally:
        con.close()

    if args.json:
        print(json.dumps(_results, indent=2, default=str))
        sys.exit(0)

    exit_code = _render_text(args.warn_only)
    _summary()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
