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
from config import (
    DUCKDB_PATH,
    FILING_MIN_REAL_GAP_DAYS,
    PIPELINE_ALERT_THRESHOLDS,
    T1_PLAUSIBILITY_BOUNDS as _B,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
STALE_PRICE_DAYS = 5          # flag tickers with no price data in last N business days
STALE_SHARES_DAYS = 30        # flag tickers with no shares data in last N days
FUNDAMENTAL_NULL_WARN_PCT = 15.0   # warn if key column is >15% null
FUNDAMENTAL_NULL_FAIL_PCT = 50.0   # fail if key column is >50% null
MIN_PRICE_COVERAGE_PCT = PIPELINE_ALERT_THRESHOLDS['t1_price_coverage_warn_pct']  # warn threshold (centralised)
MIN_SHARES_COVERAGE_PCT = 60.0     # warn if shares coverage drops below this
MIN_FUND_COVERAGE_PCT = 60.0       # warn if fundamentals coverage drops below this

# Dates known to be legitimately absent from t1_macro (market closures / extraordinary events).
# Gaps limited to these dates are downgraded from FAIL to INFO — they are expected, not bugs.
KNOWN_MACRO_GAP_DATES: set[str] = {
    "2001-09-11",  # 9/11 — NYSE closed
    "2001-09-12",  # NYSE remained closed
    "2001-09-13",  # NYSE remained closed
    "2001-09-14",  # NYSE remained closed
}

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

    # CP tickers missing entirely from each downstream table — only warn for active tickers.
    # Inactive/delisted tickers are expected to have gaps (e.g. ETFs, preferred shares delisted recently).
    for table in ("price_data", "shares_history", "fundamentals"):
        missing_active = con.execute(f"""
            SELECT COUNT(DISTINCT cp.ticker)
            FROM company_profiles cp
            LEFT JOIN (SELECT DISTINCT ticker FROM {table}) t ON cp.ticker = t.ticker
            WHERE t.ticker IS NULL AND cp.is_active = TRUE
        """).fetchone()[0]
        missing_inactive = con.execute(f"""
            SELECT COUNT(DISTINCT cp.ticker)
            FROM company_profiles cp
            LEFT JOIN (SELECT DISTINCT ticker FROM {table}) t ON cp.ticker = t.ticker
            WHERE t.ticker IS NULL AND cp.is_active = FALSE
        """).fetchone()[0]
        status = "OK" if missing_active == 0 else "WARNING"
        detail = f"Active tickers in company_profiles with NO rows in {table}"
        if missing_inactive:
            detail += f" ({missing_inactive} inactive/delisted tickers also missing — expected)"
        _check("coverage", f"{table}_missing_from_cp", status, missing_active, detail)

    # Orphan tickers: in downstream table but NOT in company_profiles.
    # Warrants (*W, *-WT), preferred (*-PA/PB/etc), rights (*-RI) are expected to remain as
    # historical data after CP cleanup — report as INFO. Unexpected regular equities = WARNING.
    _INSTRUMENT_PATTERN = r".*W$|.*-WT$|.*-P[A-Z]$|.*-RI$|.*-R$"
    for table in ("price_data", "shares_history", "fundamentals"):
        orphans_regular = con.execute(f"""
            SELECT COUNT(DISTINCT t.ticker)
            FROM {table} t
            LEFT JOIN company_profiles cp ON t.ticker = cp.ticker
            WHERE cp.ticker IS NULL
              AND NOT t.ticker SIMILAR TO '{_INSTRUMENT_PATTERN}'
        """).fetchone()[0]
        orphans_instrument = con.execute(f"""
            SELECT COUNT(DISTINCT t.ticker)
            FROM {table} t
            LEFT JOIN company_profiles cp ON t.ticker = cp.ticker
            WHERE cp.ticker IS NULL
              AND t.ticker SIMILAR TO '{_INSTRUMENT_PATTERN}'
        """).fetchone()[0]
        orphans_total = orphans_regular + orphans_instrument
        status = "OK" if orphans_regular == 0 else "WARNING"
        by_source = ""
        if table == "fundamentals" and orphans_total > 0:
            rows = con.execute(f"""
                SELECT f.source, COUNT(DISTINCT f.ticker) cnt
                FROM fundamentals f
                LEFT JOIN company_profiles cp ON f.ticker = cp.ticker
                WHERE cp.ticker IS NULL
                GROUP BY f.source ORDER BY cnt DESC
            """).fetchall()
            by_source = " | by source: " + ", ".join(f"{s}={c}" for s, c in rows)
        detail = f"Unexpected orphan tickers in {table} (purge candidates)"
        if orphans_instrument:
            detail += f" | {orphans_instrument} warrants/preferred/rights excluded from count (expected)"
        detail += by_source
        _check("coverage", f"{table}_orphan_tickers", status, orphans_regular, detail)


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

    # basic_avg_shares scale sanity — this is the table backfill_shares_from_fundamentals.py
    # copies from, so dirt here re-leaks into shares_history. FMP has sporadic multiplicative
    # units errors (1000x typical, 10x seen on OPTT); the backfill's 3e10 absolute bound misses
    # dirt on small tickers (e.g. CALC 15B vs real 15M). Same relative rule as shares_history.
    fund_scale_dirt = con.execute(f"""
        WITH med AS (
            SELECT ticker, MEDIAN(basic_avg_shares) med
            FROM fundamentals WHERE basic_avg_shares > 0 GROUP BY ticker
        )
        SELECT COUNT(*) FROM fundamentals f JOIN med m USING(ticker)
        WHERE f.basic_avg_shares > {_B['shares_scale_abs']}
          AND f.basic_avg_shares > {_B['shares_scale_ratio']} * m.med
    """).fetchone()[0]
    _check("fundamentals", "basic_avg_shares_scale_dirt", "FAIL" if fund_scale_dirt > 0 else "OK",
           fund_scale_dirt,
           f"rows > {_B['shares_scale_abs']:.0e} shares AND > {_B['shares_scale_ratio']}x ticker median "
           "(units dirt; re-leaks via shares backfill)")


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

    # Rows with NULL/non-positive close. Bars with ALL of open/high/low/close NULL are the
    # deliberate clean_dirty_shares_price.py signature (dirt nulled in place, date spine kept)
    # — count them as INFO, not FAIL, or the cleanup permanently reddens this check.
    bad_close, nulled_bars = con.execute("""
        SELECT COUNT(*) FILTER (WHERE close <= 0
                                OR (close IS NULL AND NOT (open IS NULL AND high IS NULL AND low IS NULL))),
               COUNT(*) FILTER (WHERE close IS NULL AND open IS NULL AND high IS NULL AND low IS NULL)
        FROM price_data WHERE close IS NULL OR close <= 0
    """).fetchone()
    pct = _pct(bad_close, total)
    _check("price_data", "null_or_zero_close", "FAIL" if bad_close > 0 else "OK", bad_close,
           f"{pct}% rows with unexplained NULL/non-positive close "
           f"({nulled_bars} fully-nulled bars from deliberate dirt cleanup excluded)")

    # Absolute close ceiling: BRK-A (real US high) tops ~$810k. > $1M/share is not a real
    # price (units/scaling error). This is the Mode B root cause — the delta-based extreme-move
    # check below misses sustained wrong-scale blocks (e.g. MRDN @ $1.6T).
    absurd_px = con.execute(
        f"SELECT COUNT(*) FROM price_data WHERE close > {_B['close_max']}"
    ).fetchone()[0]
    _check("price_data", "absurd_close_price", "FAIL" if absurd_px > 0 else "OK", absurd_px,
           f"rows with close > ${_B['close_max']:,.0f}/share (impossible; BRK-A real max ~$810k)")

    # OHLC ordering: high must bound close/low, low must bound close. Profiled 2026-07: 99.9%
    # of raw violations are <0.1% float-rounding epsilon (legacy import) — not corruption.
    # 0.1-10% = live-feed tape artifacts (recur on quad-witching days; GREATEST/LEAST(close)
    # bounds them downstream) -> WARNING. >10% = genuinely corrupt bars -> FAIL.
    eps, warn_rows, fail_rows = con.execute(f"""
        WITH v AS (
            SELECT GREATEST(CASE WHEN high < close THEN close / NULLIF(high, 0) ELSE 1 END,
                            CASE WHEN low > close THEN low / NULLIF(close, 0) ELSE 1 END,
                            CASE WHEN high < low THEN low / NULLIF(high, 0) ELSE 1 END) - 1 AS excess
            FROM price_data
            WHERE high < close OR low > close OR high < low
        )
        SELECT COUNT(*) FILTER (WHERE excess < {_B['ohlc_excess_warn']}),
               COUNT(*) FILTER (WHERE excess >= {_B['ohlc_excess_warn']} AND excess <= {_B['ohlc_excess_fail']}),
               COUNT(*) FILTER (WHERE excess > {_B['ohlc_excess_fail']})
        FROM v
    """).fetchone()
    status = "FAIL" if fail_rows > 0 else ("WARNING" if warn_rows > 0 else "OK")
    _check("price_data", "ohlc_ordering", status, fail_rows,
           f"bars violating high>=close>=low by >10% (corrupt); {warn_rows} tape artifacts (0.1-10%), "
           f"{eps} rounding-epsilon rows (<0.1%, ignored)")

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
# Section 4b: Filing Date Integrity
# ---------------------------------------------------------------------------
def check_filing_date_integrity(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
    if total == 0:
        return

    # NULL filing_date — expected for pre-yfinance historical rows, but track the rate
    nulls = con.execute("SELECT COUNT(*) FROM fundamentals WHERE filing_date IS NULL").fetchone()[0]
    pct_null = _pct(nulls, total)
    status = "WARNING" if pct_null > 30.0 else "OK"
    _check("filing_date", "null_filing_date", status, pct_null,
           f"{nulls}/{total} rows missing filing_date (historical pre-yfinance rows expected)")

    # filing_date < period_end: physically impossible — report date cannot precede period end
    impossible = con.execute("""
        SELECT COUNT(*) FROM fundamentals
        WHERE filing_date IS NOT NULL AND filing_date < period_end
    """).fetchone()[0]
    _check("filing_date", "filing_before_period_end", "FAIL" if impossible > 0 else "OK", impossible,
           "Rows where filing_date < period_end (bad date mapping)")

    # filing_date < FILING_MIN_REAL_GAP_DAYS after period_end: real 10-Qs take >= 8 days.
    # Threshold shared with fundamental_engine's write-time sanitizer (was 30d here, which
    # flagged 22k legitimate accelerated filers as permanent warn-noise).
    fast = con.execute(f"""
        SELECT COUNT(*) FROM fundamentals
        WHERE filing_date IS NOT NULL
          AND DATE_DIFF('day', period_end, filing_date) < {int(FILING_MIN_REAL_GAP_DAYS)}
          AND filing_date >= period_end
    """).fetchone()[0]
    status = "WARNING" if fast > 0 else "OK"
    _check("filing_date", "filing_before_min_real_gap", status, fast,
           f"Rows filed <{FILING_MIN_REAL_GAP_DAYS} days after period_end (not a real 10-Q date; "
           "pre-fix legacy rows — new ingests are sanitised at the upsert gate)")

    # filing_date > 90 days after period_end: outside legal filing window
    late = con.execute("""
        SELECT COUNT(*) FROM fundamentals
        WHERE filing_date IS NOT NULL
          AND DATE_DIFF('day', period_end, filing_date) > 90
    """).fetchone()[0]
    status = "WARNING" if late > 0 else "OK"
    _check("filing_date", "filing_gt_90d_after_period", status, late,
           "Rows filed >90 days after period_end (outside SEC filing window — possible date mismatch)")

    # Sample worst offenders for fast filings
    if fast > 0:
        rows = con.execute(f"""
            SELECT ticker, period_end, filing_date,
                   DATE_DIFF('day', period_end, filing_date) AS gap_days
            FROM fundamentals
            WHERE filing_date IS NOT NULL
              AND DATE_DIFF('day', period_end, filing_date) < {int(FILING_MIN_REAL_GAP_DAYS)}
              AND filing_date >= period_end
            ORDER BY gap_days
            LIMIT 5
        """).fetchall()
        sample = ", ".join(f"{t} {pe} ({g}d)" for t, pe, fd, g in rows)
        _check("filing_date", "fast_filing_sample", "INFO", fast,
               f"Fastest filers: {sample}")


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
    all_gaps = [str(r[0]) for r in gap_dates]
    unexpected_gaps = [d for d in all_gaps if d not in KNOWN_MACRO_GAP_DATES]
    whitelisted_gaps = [d for d in all_gaps if d in KNOWN_MACRO_GAP_DATES]

    if unexpected_gaps:
        status = "FAIL"
        detail = f"{len(unexpected_gaps)} unexpected trading days in price_data have no t1_macro row (recent: {', '.join(unexpected_gaps[:10])})"
    elif whitelisted_gaps:
        status = "INFO"
        detail = f"All {len(whitelisted_gaps)} gap date(s) are known market closures (whitelisted): {', '.join(whitelisted_gaps)}"
    else:
        status = "OK"
        detail = "No date gaps between price_data and t1_macro"
    _check("t1_macro", "date_gaps_vs_price_data", status, len(unexpected_gaps), detail)


# ---------------------------------------------------------------------------
# Section 5b: Macro Data (macro_data — long FRED/Yale series) Integrity
# ---------------------------------------------------------------------------
# Per-symbol max staleness (calendar days). Daily series should be fresh within a
# week; weekly FRED releases and monthly CAPE legitimately lag further.
MACRO_DATA_EXPECTED: dict[str, int] = {
    "VIX": 5,            # daily (FRED VIXCLS)
    "DGS10": 5,          # daily
    "DGS2": 5,           # daily
    "DFII10": 5,         # daily (10Y real yield)
    "BAMLH0A0HYM2": 5,   # daily (HY OAS)
    "RRPONTSYD": 5,      # daily (overnight RRP)
    "WALCL": 12,         # weekly (Fed balance sheet, Wed release)
    "WTREGEN": 12,       # weekly (TGA)
    "WBAA": 12,          # weekly (Baa yield)
    "CPIAUCSL": 70,      # monthly (CPI, ~1mo release lag; deflator for CAPE_OURS)
    "CAPE_OURS": 40,     # monthly self-computed valuation pillar — recomputes nightly,
                         #   trails only the latest month-start. This is the LIVE pillar.
    "CAPE": 800,         # Yale Shiller ie_data.xls — DORMANT (froze 2024-09), kept only as
                         #   a cross-check vs CAPE_OURS. Not fetchable fresh; see sprint_13
                         #   cape_fred_proxy_findings.md. 800d tolerance = don't alarm on a
                         #   source we've deliberately superseded.
}


def check_macro_data_integrity(con: duckdb.DuckDBPyConnection) -> None:
    has_table = con.execute("""
        SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'macro_data'
    """).fetchone()[0] > 0
    if not has_table:
        _check("macro_data", "table_exists", "FAIL", False, "macro_data table not found")
        return

    total = con.execute("SELECT COUNT(*) FROM macro_data").fetchone()[0]
    _check("macro_data", "total_rows", "INFO", total, "Total rows in macro_data (long format)")
    if total == 0:
        _check("macro_data", "table_empty", "FAIL", 0, "macro_data has no rows")
        return

    today = date.today()
    present = {
        sym: (n, mx)
        for sym, n, mx in con.execute(
            "SELECT symbol, COUNT(*), MAX(date) FROM macro_data GROUP BY symbol"
        ).fetchall()
    }

    for sym, max_stale in MACRO_DATA_EXPECTED.items():
        if sym not in present:
            _check("macro_data", f"symbol_{sym}", "FAIL", "MISSING",
                   f"Expected series '{sym}' absent from macro_data (dashboard pillar will be blank)")
            continue
        n, mx = present[sym]
        days_since = (today - mx).days if mx else 9999
        status = "OK" if days_since <= max_stale else "WARNING"
        _check("macro_data", f"symbol_{sym}", status, str(mx),
               f"{n} rows, {days_since}d stale (tolerance {max_stale}d)")

    # The dashboard reads `close`; `value` is unused. Guard against a regression
    # where a writer populates `value` instead, which silently blanks the gauge.
    null_close = con.execute("SELECT COUNT(*) FROM macro_data WHERE close IS NULL").fetchone()[0]
    pct = _pct(null_close, total)
    status = "FAIL" if pct > 1.0 else "OK"
    _check("macro_data", "null_close", status, null_close,
           f"{pct}% rows with NULL close (dashboard pillars read `close`, not `value`)")


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

    # Absolute upper-bound sanity: real max is ~25B split-adjusted (AAPL); C peaked ~29B
    # pre-2011 reverse split. Delta/percentile checks miss sustained wrong-scale blocks
    # (e.g. PCG 2011-2017); only an absolute bound catches them.
    absurd = con.execute(
        f"SELECT COUNT(*) FROM shares_history WHERE shares_outstanding > {_B['shares_max']}"
    ).fetchone()[0]
    _check("shares_history", "absurd_share_count", "FAIL" if absurd > 0 else "OK", absurd,
           f"rows with shares_outstanding > {_B['shares_max']:.0e} (impossible; likely units/scaling error)")

    # Relative scale sanity: FMP's ~1000x units dirt on a SMALL company lands below any global
    # ceiling (e.g. GTLS 29.9B vs real 30M), so also flag rows that are both >1B AND >500x the
    # ticker's own median. The 500x floor keeps legit pre-reverse-split counts out (EXE was
    # 1.957B = 200x its split-adjusted median before its 1:200 reverse split).
    scale_dirt = con.execute(f"""
        WITH med AS (
            SELECT ticker, MEDIAN(shares_outstanding) med
            FROM shares_history WHERE shares_outstanding > 0 GROUP BY ticker
        )
        SELECT COUNT(*) FROM shares_history s JOIN med m USING(ticker)
        WHERE s.shares_outstanding > {_B['shares_scale_abs']}
          AND s.shares_outstanding > {_B['shares_scale_ratio']} * m.med
    """).fetchone()[0]
    _check("shares_history", "share_scale_dirt_vs_median", "FAIL" if scale_dirt > 0 else "OK", scale_dirt,
           f"rows > {_B['shares_scale_abs']:.0e} shares AND > {_B['shares_scale_ratio']}x ticker median "
           "(multiplicative units dirt below the global ceiling)")

    # Derived market-cap sanity — catches BOTH dirty-shares and dirty-price. NET, not a primary
    # gate: the (ticker,date) join covers only ~60% of shares rows; the per-table ceilings
    # (absurd_share_count, absurd_close_price) are the date-independent guards.
    absurd_cap = con.execute(f"""
        WITH s AS (SELECT ticker, date, shares_outstanding FROM shares_history),
             p AS (SELECT ticker, date, close FROM price_data)
        SELECT COUNT(*) FROM s JOIN p USING(ticker, date)
        WHERE s.shares_outstanding * p.close > {_B['implied_cap_max']}
    """).fetchone()[0]
    _check("shares_history", "absurd_implied_market_cap", "FAIL" if absurd_cap > 0 else "OK", absurd_cap,
           f"ticker-days with implied cap > ${_B['implied_cap_max']:.0e} (dirty shares OR dirty price; largest ever ~$4.7T)")

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
        check_filing_date_integrity(con)
        check_price_integrity(con)
        check_macro_integrity(con)
        check_macro_data_integrity(con)
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
