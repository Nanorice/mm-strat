"""
T2 Screener Features Audit (Phase 3 — t2_screener_features table)
------------------------------------------------------------------
Evaluates data quality of t2_screener_features after Phase 3 compute.

Checks:
  1. Coverage      — row counts, date range, ticker count vs screener_membership
  2. SEPA flags    — trend_ok / breakout_ok null rate and candidate yield
  3. Key column nulls — critical features that must be non-null for models
  4. Cross-sectional ranks — alpha/rank columns populated (Phase B/C ran)
  5. Staleness     — most recent date vs today
  6. Referential   — tickers in t2 not in screener_membership (orphans)

Run:
    python tools/audit_t2_screener_features.py
    python tools/audit_t2_screener_features.py --json
    python tools/audit_t2_screener_features.py --warn-only
    python tools/audit_t2_screener_features.py --date 2024-06-01   # spot-check one date
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
# Thresholds
# ---------------------------------------------------------------------------
STALE_DAYS           = 5      # warn if latest date is older than N calendar days
NULL_WARN_PCT        = 5.0    # warn if key column is >5% null
NULL_FAIL_PCT        = 20.0   # fail if key column is >20% null
SEPA_YIELD_MIN_PCT   = 0.5    # warn if SEPA candidates < 0.5% of universe rows
SEPA_YIELD_MAX_PCT   = 30.0   # warn if SEPA candidates > 30% of universe rows (criteria too loose)
COVERAGE_WARN_PCT    = 80.0   # warn if t2 ticker coverage vs screener_membership drops below this

# Columns that must be non-null for SEPA filtering to work
SEPA_CRITICAL_COLS = [
    "price_vs_sma_50", "price_vs_sma_150", "price_vs_sma_200",
    "close_above_sma200", "dist_from_52w_high", "dist_from_52w_low",
    "rs", "rs_ma", "rs_rating",
    "atr_20d", "natr", "vcp_ratio",
    "vol_avg_20", "dry_up_volume",
    "trend_ok", "breakout_ok",
]

# Cross-sectional columns — populated by Phase B (alphas) and Phase C (ranks)
RANK_COLS  = ["RS_Universe_Rank", "RS_Sector_Rank", "RS_vs_Sector", "Sector_Momentum"]
ALPHA_COLS = ["alpha001", "alpha002", "alpha004", "alpha011"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_results: list[dict[str, Any]] = []


def _check(section: str, name: str, status: str, value: Any, detail: str = "") -> None:
    _results.append({"section": section, "check": name, "status": status, "value": value, "detail": detail})


def _pct(part: int, total: int) -> float:
    return round(part / total * 100, 1) if total else 0.0


def _null_status(pct: float) -> str:
    if pct >= NULL_FAIL_PCT:
        return "FAIL"
    if pct >= NULL_WARN_PCT:
        return "WARNING"
    return "OK"


# ---------------------------------------------------------------------------
# Section 1: Coverage
# ---------------------------------------------------------------------------
def check_coverage(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM t2_screener_features").fetchone()[0]
    _check("coverage", "total_rows", "INFO", total, "Total rows in t2_screener_features")

    if total == 0:
        _check("coverage", "table_empty", "FAIL", 0,
               "t2_screener_features has no rows — Phase 3 compute not run yet")
        return

    distinct_tickers, distinct_dates = con.execute("""
        SELECT COUNT(DISTINCT ticker), COUNT(DISTINCT date) FROM t2_screener_features
    """).fetchone()
    _check("coverage", "distinct_tickers", "INFO", distinct_tickers, "Unique tickers in t2_screener_features")
    _check("coverage", "distinct_dates",   "INFO", distinct_dates,   "Unique dates in t2_screener_features")

    mn, mx = con.execute("SELECT MIN(date), MAX(date) FROM t2_screener_features").fetchone()
    _check("coverage", "date_range", "INFO", f"{mn} to {mx}", "Date range covered")

    # Compare ticker count against screener_membership active universe (as of latest t2 date)
    try:
        membership_active = con.execute(f"""
            WITH latest AS (
                SELECT ticker, is_active,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY effective_date DESC) AS rn
                FROM screener_membership
                WHERE effective_date <= '{mx}'
            )
            SELECT COUNT(*) FROM latest WHERE rn = 1 AND is_active = TRUE
        """).fetchone()[0]

        t2_on_last_date = con.execute(f"""
            SELECT COUNT(DISTINCT ticker) FROM t2_screener_features WHERE date = '{mx}'
        """).fetchone()[0]

        if membership_active > 0:
            pct_covered = _pct(t2_on_last_date, membership_active)
            status = "OK" if pct_covered >= COVERAGE_WARN_PCT else "WARNING"
            _check("coverage", "t2_vs_membership_pct", status, pct_covered,
                   f"t2 tickers on {mx} ({t2_on_last_date}) vs active screener_membership ({membership_active})")
    except Exception:
        _check("coverage", "membership_comparison", "INFO", "N/A",
               "screener_membership not available — skipping coverage comparison")


# ---------------------------------------------------------------------------
# Section 2: SEPA Flags
# ---------------------------------------------------------------------------
def check_sepa_flags(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM t2_screener_features").fetchone()[0]
    if total == 0:
        return

    null_trend    = con.execute("SELECT COUNT(*) FROM t2_screener_features WHERE trend_ok IS NULL").fetchone()[0]
    null_breakout = con.execute("SELECT COUNT(*) FROM t2_screener_features WHERE breakout_ok IS NULL").fetchone()[0]
    _check("sepa_flags", "null_trend_ok",    _null_status(_pct(null_trend, total)),    _pct(null_trend, total),
           f"{null_trend} rows with NULL trend_ok")
    _check("sepa_flags", "null_breakout_ok", _null_status(_pct(null_breakout, total)), _pct(null_breakout, total),
           f"{null_breakout} rows with NULL breakout_ok")

    candidates = con.execute("""
        SELECT COUNT(*) FROM t2_screener_features WHERE trend_ok = TRUE AND breakout_ok = TRUE
    """).fetchone()[0]
    yield_pct = _pct(candidates, total)

    if yield_pct < SEPA_YIELD_MIN_PCT:
        status = "WARNING"
    elif yield_pct > SEPA_YIELD_MAX_PCT:
        status = "WARNING"
    else:
        status = "OK"
    _check("sepa_flags", "sepa_candidate_yield_pct", status, yield_pct,
           f"{candidates:,}/{total:,} rows pass trend_ok AND breakout_ok "
           f"(expected {SEPA_YIELD_MIN_PCT}–{SEPA_YIELD_MAX_PCT}%)")

    # trend_ok breakdown
    trend_true  = con.execute("SELECT COUNT(*) FROM t2_screener_features WHERE trend_ok = TRUE").fetchone()[0]
    trend_false = con.execute("SELECT COUNT(*) FROM t2_screener_features WHERE trend_ok = FALSE").fetchone()[0]
    _check("sepa_flags", "trend_ok_true_pct",  "INFO", _pct(trend_true,  total), f"{trend_true:,} rows with trend_ok=TRUE")
    _check("sepa_flags", "trend_ok_false_pct", "INFO", _pct(trend_false, total), f"{trend_false:,} rows with trend_ok=FALSE")


# RS requires 252 trading days of history to compute; rank columns depend on RS.
# Nulls confined to a ticker's first ~252 rows are expected (warmup window) and should
# not trigger a WARNING. We use 270 rows as a conservative warmup boundary.
_RS_WARMUP_ROWS = 270
# Columns whose nulls are expected during the warmup window
_WARMUP_NULL_COLS = {"rs", "rs_ma", "rs_rating", "RS_Universe_Rank", "RS_Sector_Rank", "RS_vs_Sector", "Sector_Momentum"}


def _warmup_null_split(con: duckdb.DuckDBPyConnection, col: str) -> tuple[int, int]:
    """
    Returns (nulls_in_warmup, nulls_after_warmup) for a column.
    Warmup = first _RS_WARMUP_ROWS rows per ticker (ordered by date).
    """
    row = con.execute(f"""
        WITH ranked AS (
            SELECT {col},
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date) AS rn
            FROM t2_screener_features
        )
        SELECT
            COUNT(*) FILTER (WHERE {col} IS NULL AND rn <= {_RS_WARMUP_ROWS}),
            COUNT(*) FILTER (WHERE {col} IS NULL AND rn >  {_RS_WARMUP_ROWS})
        FROM ranked
    """).fetchone()
    return row[0], row[1]


# ---------------------------------------------------------------------------
# Section 3: Key Column Null Rates
# ---------------------------------------------------------------------------
def check_column_nulls(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM t2_screener_features").fetchone()[0]
    if total == 0:
        return

    for col in SEPA_CRITICAL_COLS:
        try:
            nulls = con.execute(f"SELECT COUNT(*) FROM t2_screener_features WHERE {col} IS NULL").fetchone()[0]
            pct   = _pct(nulls, total)
            if col in _WARMUP_NULL_COLS and nulls > 0:
                in_warmup, after_warmup = _warmup_null_split(con, col)
                if after_warmup == 0:
                    # All nulls are in warmup — expected, downgrade to INFO
                    _check("key_columns", f"null_pct_{col}", "INFO", pct,
                           f"{nulls:,}/{total:,} rows null — all within warmup window (first {_RS_WARMUP_ROWS} rows/ticker, expected)")
                else:
                    # Some nulls outside warmup — that's unexpected
                    status = _null_status(_pct(after_warmup, total))
                    _check("key_columns", f"null_pct_{col}", status, _pct(after_warmup, total),
                           f"{after_warmup:,} rows null OUTSIDE warmup window — possible pipeline gap "
                           f"({in_warmup:,} warmup nulls excluded)")
            else:
                _check("key_columns", f"null_pct_{col}", _null_status(pct), pct,
                       f"{nulls:,}/{total:,} rows null")
        except Exception:
            _check("key_columns", f"missing_col_{col}", "FAIL", "N/A", f"Column {col} not found in t2_screener_features")


# ---------------------------------------------------------------------------
# Section 4: Cross-Sectional Ranks and Alphas
# ---------------------------------------------------------------------------
def check_ranks_and_alphas(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM t2_screener_features").fetchone()[0]
    if total == 0:
        return

    for col in RANK_COLS:
        try:
            nulls = con.execute(f"SELECT COUNT(*) FROM t2_screener_features WHERE {col} IS NULL").fetchone()[0]
            pct   = _pct(nulls, total)
            if col in _WARMUP_NULL_COLS and nulls > 0:
                in_warmup, after_warmup = _warmup_null_split(con, col)
                if after_warmup == 0:
                    _check("ranks_alphas", f"null_pct_{col}", "INFO", pct,
                           f"{nulls:,}/{total:,} rows null — all within warmup window (first {_RS_WARMUP_ROWS} rows/ticker, expected)")
                else:
                    status = "WARNING" if after_warmup > 0 else "OK"
                    _check("ranks_alphas", f"null_pct_{col}", status, _pct(after_warmup, total),
                           f"{after_warmup:,} rows null OUTSIDE warmup — Phase C may not have run for some dates "
                           f"({in_warmup:,} warmup nulls excluded)")
            else:
                _check("ranks_alphas", f"null_pct_{col}", _null_status(pct), pct,
                       f"{nulls:,}/{total:,} rows null — Phase C (cross-sectional ranks) may not have run")
        except Exception:
            _check("ranks_alphas", f"missing_col_{col}", "WARNING", "N/A",
                   f"Column {col} not in t2_screener_features schema yet")

    for col in ALPHA_COLS:
        try:
            nulls = con.execute(f"SELECT COUNT(*) FROM t2_screener_features WHERE {col} IS NULL").fetchone()[0]
            pct   = _pct(nulls, total)
            _check("ranks_alphas", f"null_pct_{col}", _null_status(pct), pct,
                   f"{nulls:,}/{total:,} rows null — Phase B (alpha factors) may not have run")
        except Exception:
            _check("ranks_alphas", f"missing_col_{col}", "WARNING", "N/A",
                   f"Column {col} not in t2_screener_features schema yet")


# ---------------------------------------------------------------------------
# Section 5: Staleness
# ---------------------------------------------------------------------------
def check_staleness(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM t2_screener_features").fetchone()[0]
    if total == 0:
        return

    mx = con.execute("SELECT MAX(date) FROM t2_screener_features").fetchone()[0]
    days_since = (date.today() - mx).days
    status = "OK" if days_since <= STALE_DAYS else "WARNING"
    _check("staleness", "latest_date", status, str(mx),
           f"{days_since} calendar days since last t2 row (threshold: {STALE_DAYS}d)")

    # Rows on the latest date
    latest_count = con.execute(f"SELECT COUNT(*) FROM t2_screener_features WHERE date = '{mx}'").fetchone()[0]
    _check("staleness", "rows_on_latest_date", "INFO", latest_count,
           f"Tickers computed on {mx}")


# ---------------------------------------------------------------------------
# Section 6: Referential Integrity
# ---------------------------------------------------------------------------
def check_referential(con: duckdb.DuckDBPyConnection) -> None:
    # Tickers in t2 with no price_data (orphaned compute)
    orphans_price = con.execute("""
        SELECT COUNT(DISTINCT t2.ticker)
        FROM t2_screener_features t2
        LEFT JOIN price_data p ON t2.ticker = p.ticker
        WHERE p.ticker IS NULL
    """).fetchone()[0]
    _check("referential", "orphan_tickers_no_price_data", "FAIL" if orphans_price > 0 else "OK",
           orphans_price, "Tickers in t2_screener_features with no rows in price_data")

    # Tickers in t2 with no entry in screener_membership (computed outside active universe)
    try:
        orphans_membership = con.execute("""
            SELECT COUNT(DISTINCT t2.ticker)
            FROM t2_screener_features t2
            LEFT JOIN (SELECT DISTINCT ticker FROM screener_membership WHERE is_active = TRUE) sm
                ON t2.ticker = sm.ticker
            WHERE sm.ticker IS NULL
        """).fetchone()[0]
        _check("referential", "orphan_tickers_not_in_membership", "WARNING" if orphans_membership > 0 else "OK",
               orphans_membership,
               "Tickers in t2_screener_features never active in screener_membership (stale or pre-membership compute)")
    except Exception:
        _check("referential", "membership_check", "INFO", "N/A", "screener_membership not available")


# ---------------------------------------------------------------------------
# Section 7: Per-Date Continuity (trend_ok anomalies)
# ---------------------------------------------------------------------------
TREND_DROP_WARN_PCT = 50.0   # warn if trend_ok count drops >50% day-over-day
TREND_ZERO_IS_FAIL  = True   # fail if any date has 0 trend_ok tickers

# Dates before this are in the SMA warmup period — RS/trend_ok requires 252d of history.
# Zero trend_ok during warmup is expected and should not be flagged.
WARMUP_CUTOFF_DATE = "2001-01-01"

# Dates where price_vs_spy NULL is expected (SPY missing from t1_macro — known market closures).
KNOWN_SPY_NULL_DATES: set[str] = {
    "2001-09-11",  # 9/11 — NYSE closed
    "2001-09-12",
    "2001-09-13",
    "2001-09-14",
}


def check_trend_continuity(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM t2_screener_features").fetchone()[0]
    if total == 0:
        return

    # Find dates where trend_ok=0 (all tickers lost trend — almost certainly a data issue).
    # Exclude warmup period: RS/SMA require 252d history so early dates are expected to have
    # zero trend_ok candidates.
    zero_dates = con.execute(f"""
        SELECT date, COUNT(*) AS total_rows
        FROM t2_screener_features
        WHERE date >= '{WARMUP_CUTOFF_DATE}'
        GROUP BY date
        HAVING SUM(CASE WHEN trend_ok THEN 1 ELSE 0 END) = 0
           AND COUNT(*) > 100
        ORDER BY date DESC
        LIMIT 20
    """).fetchall()
    status = "FAIL" if (zero_dates and TREND_ZERO_IS_FAIL) else "OK"
    detail = f"{len(zero_dates)} dates with 0 trend_ok tickers (likely upstream data gap) — warmup period before {WARMUP_CUTOFF_DATE} excluded"
    if zero_dates:
        dates_str = ", ".join(f"{r[0]}({r[1]} rows)" for r in zero_dates[:10])
        detail += f" — {dates_str}"
    _check("trend_continuity", "zero_trend_ok_dates", status, len(zero_dates), detail)

    # Find dates with >50% drop in trend_ok count vs previous date
    drop_dates = con.execute(f"""
        WITH daily_trend AS (
            SELECT date,
                   SUM(CASE WHEN trend_ok THEN 1 ELSE 0 END) AS trend_count
            FROM t2_screener_features
            GROUP BY date
        ),
        with_lag AS (
            SELECT date, trend_count,
                   LAG(trend_count) OVER (ORDER BY date) AS prev_count
            FROM daily_trend
        )
        SELECT date, trend_count, prev_count,
               ROUND((1.0 - trend_count * 1.0 / NULLIF(prev_count, 0)) * 100, 1) AS drop_pct
        FROM with_lag
        WHERE prev_count > 50
          AND trend_count < prev_count * (1.0 - {TREND_DROP_WARN_PCT} / 100.0)
        ORDER BY date DESC
        LIMIT 10
    """).fetchall()
    status = "WARNING" if drop_dates else "OK"
    detail = f"{len(drop_dates)} dates with >{TREND_DROP_WARN_PCT:.0f}% drop in trend_ok count"
    if drop_dates:
        dates_str = ", ".join(f"{r[0]}({r[2]}->{r[1]}, -{r[3]}%)" for r in drop_dates[:5])
        detail += f" — {dates_str}"
    _check("trend_continuity", "trend_ok_large_drops", status, len(drop_dates), detail)

    # Check price_vs_spy NULLs per date (the specific root cause of this bug).
    # Whitelisted dates (known market closures) are excluded from FAIL logic.
    pvs_null_dates = con.execute("""
        SELECT date, COUNT(*) AS total,
               SUM(CASE WHEN price_vs_spy IS NULL THEN 1 ELSE 0 END) AS null_count
        FROM t2_screener_features
        GROUP BY date
        HAVING SUM(CASE WHEN price_vs_spy IS NULL THEN 1 ELSE 0 END) > 0
        ORDER BY date DESC
        LIMIT 10
    """).fetchall()
    unexpected = [(d, total, nulls) for d, total, nulls in pvs_null_dates if str(d) not in KNOWN_SPY_NULL_DATES]
    whitelisted = [(d, total, nulls) for d, total, nulls in pvs_null_dates if str(d) in KNOWN_SPY_NULL_DATES]

    if unexpected:
        status = "FAIL"
        dates_str = ", ".join(f"{d}({n}/{t})" for d, t, n in unexpected[:5])
        detail = f"{len(unexpected)} dates with NULL price_vs_spy (missing SPY in t1_macro) — {dates_str}"
    elif whitelisted:
        status = "INFO"
        dates_str = ", ".join(str(d) for d, _, _ in whitelisted)
        detail = f"All NULL price_vs_spy dates are known market closures (whitelisted): {dates_str}"
    else:
        status = "OK"
        detail = "No dates with NULL price_vs_spy"
    _check("trend_continuity", "price_vs_spy_null_dates", status, len(unexpected), detail)


# ---------------------------------------------------------------------------
# Section 8: Spot-check a single date (optional)
# ---------------------------------------------------------------------------
def check_spot_date(con: duckdb.DuckDBPyConnection, check_date: str) -> None:
    count = con.execute(f"""
        SELECT COUNT(*) FROM t2_screener_features WHERE date = '{check_date}'
    """).fetchone()[0]

    status = "OK" if count > 0 else "WARNING"
    _check("spot_date", f"rows_on_{check_date}", status, count,
           f"Rows in t2_screener_features on {check_date}")

    if count > 0:
        candidates = con.execute(f"""
            SELECT COUNT(*) FROM t2_screener_features
            WHERE date = '{check_date}' AND trend_ok = TRUE AND breakout_ok = TRUE
        """).fetchone()[0]
        _check("spot_date", f"sepa_candidates_on_{check_date}", "INFO", candidates,
               f"SEPA candidates (trend_ok AND breakout_ok) on {check_date}")

        # Null rate for one key column on this date
        null_rs = con.execute(f"""
            SELECT COUNT(*) FROM t2_screener_features WHERE date = '{check_date}' AND rs IS NULL
        """).fetchone()[0]
        _check("spot_date", f"null_rs_on_{check_date}", "FAIL" if null_rs > 0 else "OK", null_rs,
               f"Rows with NULL rs on {check_date}")


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
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
        line = f"  {prefix}{r['check']:<52} {val}"
        if r["detail"]:
            line += f"\n           {r['detail']}"
        if not warn_only or r["status"] in ("FAIL", "WARNING"):
            print(line)
        if r["status"] in ("FAIL", "WARNING"):
            exit_code = 1
    return exit_code


def _summary() -> None:
    counts: dict[str, int] = {"FAIL": 0, "WARNING": 0, "OK": 0, "INFO": 0}
    for r in _results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"\n{'='*60}")
    print(f"  SUMMARY: {counts['FAIL']} FAIL | {counts['WARNING']} WARNING | {counts['OK']} OK | {counts['INFO']} INFO")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="T3 screener features audit (t2_screener_features table)")
    parser.add_argument("--json",      action="store_true", help="Output results as JSON")
    parser.add_argument("--warn-only", action="store_true", help="Only print warnings/failures; exit 1 if any found")
    parser.add_argument("--date",      type=str, help="Spot-check a specific date (YYYY-MM-DD)")
    args = parser.parse_args()

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        print(f"Auditing t2_screener_features in: {DUCKDB_PATH}")
        check_coverage(con)
        check_sepa_flags(con)
        check_column_nulls(con)
        check_ranks_and_alphas(con)
        check_staleness(con)
        check_referential(con)
        check_trend_continuity(con)
        if args.date:
            check_spot_date(con, args.date)
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
