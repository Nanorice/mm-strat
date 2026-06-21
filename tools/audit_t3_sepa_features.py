"""
T3 SEPA Features Audit (Phase 5 — t3_sepa_features table)
----------------------------------------------------------
Evaluates data quality of t3_sepa_features after Phase 5 compute.

Checks:
  1. Coverage         — row counts, date range, ticker count, t3 vs t2 SEPA candidates
  2. Feature version  — distribution of feature_version values
  3. Key column nulls — core SEPA features that must be non-null
  4. Pct change deltas— v3.1 percentage change columns
  5. TS alphas        — time-series alphas computed only in T3
  6. XS alphas/ranks  — cross-sectional alphas + ranks (copied from T2)
  7. M03 regime       — regime features joined from t2_regime_scores
  8. Staleness        — most recent date vs today
  9. Referential      — orphan tickers, missing SEPA candidates

Run:
    python tools/audit_t3_sepa_features.py
    python tools/audit_t3_sepa_features.py --json
    python tools/audit_t3_sepa_features.py --warn-only
    python tools/audit_t3_sepa_features.py --date 2024-06-01
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
STALE_DAYS           = 5
NULL_WARN_PCT        = 5.0
NULL_FAIL_PCT        = 20.0
COVERAGE_WARN_PCT    = 80.0

# Core SEPA features (Phase A SQL)
SEPA_CRITICAL_COLS = [
    "close", "volume",
    "sma_50", "sma_150", "sma_200",
    "price_vs_sma_50", "price_vs_sma_150", "price_vs_sma_200",
    "close_above_sma200",
    "dist_from_52w_high", "dist_from_52w_low",
    "rs", "rs_ma", "rs_rating",
    "atr_20d", "natr", "vcp_ratio",
    "vol_avg_20", "dry_up_volume",
    "rsi_14", "mom_63d", "mom_252d",
]

# v3.1 percentage change features (19 base columns)
PCT_CHG_COLS = [
    "price_vs_sma_50_pct_chg", "price_vs_sma_150_pct_chg", "price_vs_sma_200_pct_chg",
    "rs_pct_chg", "rs_ma_pct_chg", "dry_up_volume_pct_chg",
    "natr_pct_chg", "atr_pct_chg", "vcp_ratio_pct_chg",
    "consolidation_width_pct_chg", "rsi_14_pct_chg",
    "dist_from_52w_high_pct_chg", "dist_from_52w_low_pct_chg",
    "low_52w_pct_chg", "high_52w_pct_chg",
    "dist_from_20d_high_pct_chg", "dist_from_20d_low_pct_chg",
    "lowest_low_20d_pct_chg", "highest_high_20d_pct_chg",
]

# Time-series alphas (T3-only, Phase B Python)
TS_ALPHA_COLS = [
    "alpha006", "alpha009", "alpha012", "alpha041",
    "alpha046", "alpha049", "alpha051", "alpha054", "alpha101",
]

# EMAs (copied from T2)
EMA_COLS = ["ema_8", "ema_21", "ema_50", "ema_100", "ema_200"]

# Cross-sectional alphas (copied from T2)
XS_ALPHA_COLS = [
    "alpha001", "alpha002", "alpha004", "alpha008",
    "alpha011", "alpha013", "alpha015", "alpha019", "alpha060",
]

# Cross-sectional ranks (copied from T2)
RANK_COLS = [
    "RS_Universe_Rank", "RS_Sector_Rank", "RS_vs_Sector", "Sector_Momentum",
    "RS_Industry_Rank", "RS_vs_Industry", "Industry_Momentum",
]

# M03 regime features (Phase D+E join)
M03_COLS = [
    "m03_score", "m03_pillar_trend", "m03_pillar_liq", "m03_pillar_risk",
    "m03_delta_5d", "m03_delta_20d", "m03_regime_vol",
]

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


def _check_null_rate(con: duckdb.DuckDBPyConnection, table: str, col: str, total: int, section: str, hint: str = "") -> None:
    try:
        nulls = con.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL").fetchone()[0]
        pct = _pct(nulls, total)
        detail = f"{nulls:,}/{total:,} rows null"
        if hint:
            detail += f" — {hint}"
        _check(section, f"null_pct_{col}", _null_status(pct), pct, detail)
    except Exception:
        _check(section, f"missing_col_{col}", "FAIL", "N/A", f"Column {col} not found in {table}")


# ---------------------------------------------------------------------------
# Section 1: Coverage
# ---------------------------------------------------------------------------
def check_coverage(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM t3_sepa_features").fetchone()[0]
    _check("coverage", "total_rows", "INFO", f"{total:,}", "Total rows in t3_sepa_features")

    if total == 0:
        _check("coverage", "table_empty", "FAIL", 0, "t3_sepa_features has no rows — Phase 5 not run yet")
        return

    distinct_tickers, distinct_dates = con.execute("""
        SELECT COUNT(DISTINCT ticker), COUNT(DISTINCT date) FROM t3_sepa_features
    """).fetchone()
    _check("coverage", "distinct_tickers", "INFO", distinct_tickers, "Unique tickers in t3_sepa_features")
    _check("coverage", "distinct_dates",   "INFO", distinct_dates,   "Unique dates in t3_sepa_features")

    mn, mx = con.execute("SELECT MIN(date), MAX(date) FROM t3_sepa_features").fetchone()
    _check("coverage", "date_range", "INFO", f"{mn} to {mx}", "Date range covered")

    # Average rows per date (SEPA candidates typically 13-100/day)
    avg_per_date = con.execute("""
        SELECT ROUND(AVG(cnt), 1) FROM (SELECT COUNT(*) AS cnt FROM t3_sepa_features GROUP BY date)
    """).fetchone()[0]
    _check("coverage", "avg_rows_per_date", "INFO", avg_per_date, "Average SEPA candidates per trading day")

    # Compare t3 vs t2 SEPA candidates on latest date
    try:
        t2_sepa = con.execute(f"""
            SELECT COUNT(*) FROM t2_screener_features
            WHERE date = '{mx}' AND trend_ok = TRUE AND breakout_ok = TRUE
        """).fetchone()[0]
        t3_on_last = con.execute(f"""
            SELECT COUNT(*) FROM t3_sepa_features WHERE date = '{mx}'
        """).fetchone()[0]
        if t2_sepa > 0:
            pct = _pct(t3_on_last, t2_sepa)
            status = "OK" if pct >= COVERAGE_WARN_PCT else "WARNING"
            _check("coverage", "t3_vs_t2_sepa_pct", status, pct,
                   f"t3 rows on {mx} ({t3_on_last}) vs t2 SEPA candidates ({t2_sepa})")
        else:
            _check("coverage", "t3_vs_t2_sepa_pct", "INFO", "N/A",
                   f"No t2 SEPA candidates on {mx}")
    except Exception:
        _check("coverage", "t3_vs_t2_comparison", "INFO", "N/A",
               "t2_screener_features not available — skipping comparison")


# ---------------------------------------------------------------------------
# Section 2: Feature Version
# ---------------------------------------------------------------------------
def check_feature_version(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM t3_sepa_features").fetchone()[0]
    if total == 0:
        return

    versions = con.execute("""
        SELECT feature_version, COUNT(*) AS cnt
        FROM t3_sepa_features
        GROUP BY feature_version
        ORDER BY cnt DESC
    """).fetchall()

    for ver, cnt in versions:
        pct = _pct(cnt, total)
        _check("feature_version", f"version_{ver}", "INFO", pct, f"{cnt:,} rows ({pct}%)")

    # Warn if multiple versions
    if len(versions) > 1:
        _check("feature_version", "multiple_versions", "WARNING", len(versions),
               "Multiple feature versions found — may need cleanup")
    else:
        _check("feature_version", "single_version", "OK", versions[0][0], "All rows use same feature_version")


# ---------------------------------------------------------------------------
# Section 3: Key Column Nulls
# ---------------------------------------------------------------------------
def check_column_nulls(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM t3_sepa_features").fetchone()[0]
    if total == 0:
        return

    for col in SEPA_CRITICAL_COLS:
        _check_null_rate(con, "t3_sepa_features", col, total, "key_columns")


# ---------------------------------------------------------------------------
# Section 4: Pct Change Deltas (v3.1)
# ---------------------------------------------------------------------------
def check_pct_chg(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM t3_sepa_features").fetchone()[0]
    if total == 0:
        return

    for col in PCT_CHG_COLS:
        _check_null_rate(con, "t3_sepa_features", col, total, "pct_chg_deltas",
                         "first row per ticker expected NULL")


# ---------------------------------------------------------------------------
# Section 5: TS Alphas (T3-only)
# ---------------------------------------------------------------------------
def check_ts_alphas(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM t3_sepa_features").fetchone()[0]
    if total == 0:
        return

    for col in TS_ALPHA_COLS:
        _check_null_rate(con, "t3_sepa_features", col, total, "ts_alphas",
                         "Phase B (TS alpha) may not have run")


# ---------------------------------------------------------------------------
# Section 6: XS Alphas + Ranks (from T2)
# ---------------------------------------------------------------------------
def check_xs_alphas_and_ranks(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM t3_sepa_features").fetchone()[0]
    if total == 0:
        return

    for col in EMA_COLS:
        _check_null_rate(con, "t3_sepa_features", col, total, "xs_alphas_ranks",
                         "EMA (from T2)")

    for col in XS_ALPHA_COLS:
        _check_null_rate(con, "t3_sepa_features", col, total, "xs_alphas_ranks",
                         "XS alpha (from T2)")

    for col in RANK_COLS:
        _check_null_rate(con, "t3_sepa_features", col, total, "xs_alphas_ranks",
                         "rank column (from T2)")


# ---------------------------------------------------------------------------
# Section 7: M03 Regime Features
# ---------------------------------------------------------------------------
def check_m03_regime(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM t3_sepa_features").fetchone()[0]
    if total == 0:
        return

    for col in M03_COLS:
        _check_null_rate(con, "t3_sepa_features", col, total, "m03_regime",
                         "M03 regime join may have gaps")


# ---------------------------------------------------------------------------
# Section 8: Staleness
# ---------------------------------------------------------------------------
def check_staleness(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM t3_sepa_features").fetchone()[0]
    if total == 0:
        return

    mx = con.execute("SELECT MAX(date) FROM t3_sepa_features").fetchone()[0]
    days_since = (date.today() - mx).days
    status = "OK" if days_since <= STALE_DAYS else "WARNING"
    _check("staleness", "latest_date", status, str(mx),
           f"{days_since} calendar days since last t3 row (threshold: {STALE_DAYS}d)")

    latest_count = con.execute(f"SELECT COUNT(*) FROM t3_sepa_features WHERE date = '{mx}'").fetchone()[0]
    _check("staleness", "rows_on_latest_date", "INFO", latest_count, f"SEPA candidates on {mx}")


# ---------------------------------------------------------------------------
# Section 9: Referential Integrity
# ---------------------------------------------------------------------------
def check_referential(con: duckdb.DuckDBPyConnection) -> None:
    # Tickers in t3 with no price_data
    orphans_price = con.execute("""
        SELECT COUNT(DISTINCT t3.ticker)
        FROM t3_sepa_features t3
        LEFT JOIN price_data p ON t3.ticker = p.ticker
        WHERE p.ticker IS NULL
    """).fetchone()[0]
    _check("referential", "orphan_tickers_no_price_data",
           "FAIL" if orphans_price > 0 else "OK", orphans_price,
           "Tickers in t3 with no rows in price_data")

    # Tickers in t3 with no t2 record
    try:
        orphans_t2 = con.execute("""
            SELECT COUNT(DISTINCT t3.ticker)
            FROM t3_sepa_features t3
            LEFT JOIN (SELECT DISTINCT ticker FROM t2_screener_features) t2
                ON t3.ticker = t2.ticker
            WHERE t2.ticker IS NULL
        """).fetchone()[0]
        _check("referential", "orphan_tickers_no_t2",
               "WARNING" if orphans_t2 > 0 else "OK", orphans_t2,
               "Tickers in t3 never in t2_screener_features")
    except Exception:
        _check("referential", "t2_comparison", "INFO", "N/A", "t2_screener_features not available")

    # Date gaps: dates in t2 with SEPA candidates but no t3 rows
    try:
        mx = con.execute("SELECT MAX(date) FROM t3_sepa_features").fetchone()[0]
        mn = con.execute("SELECT MIN(date) FROM t3_sepa_features").fetchone()[0]
        missing_dates = con.execute(f"""
            SELECT COUNT(DISTINCT t2.date)
            FROM t2_screener_features t2
            LEFT JOIN (SELECT DISTINCT date FROM t3_sepa_features) t3 ON t2.date = t3.date
            WHERE t2.trend_ok = TRUE AND t2.breakout_ok = TRUE
              AND t2.date BETWEEN '{mn}' AND '{mx}'
              AND t3.date IS NULL
        """).fetchone()[0]
        status = "WARNING" if missing_dates > 0 else "OK"
        _check("referential", "t2_sepa_dates_missing_from_t3", status, missing_dates,
               f"Trading days with t2 SEPA candidates but no t3 rows (within t3 date range)")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Section 10: Spot-check a single date (optional)
# ---------------------------------------------------------------------------
def check_spot_date(con: duckdb.DuckDBPyConnection, check_date: str) -> None:
    count = con.execute(f"SELECT COUNT(*) FROM t3_sepa_features WHERE date = '{check_date}'").fetchone()[0]
    status = "OK" if count > 0 else "WARNING"
    _check("spot_date", f"rows_on_{check_date}", status, count, f"Rows in t3 on {check_date}")

    if count > 0:
        # Check TS alpha population on this date
        null_a006 = con.execute(f"""
            SELECT COUNT(*) FROM t3_sepa_features WHERE date = '{check_date}' AND alpha006 IS NULL
        """).fetchone()[0]
        _check("spot_date", f"null_alpha006_on_{check_date}",
               "WARNING" if null_a006 > 0 else "OK", null_a006,
               f"Rows with NULL alpha006 (TS alpha) on {check_date}")

        # Check M03 join on this date
        null_m03 = con.execute(f"""
            SELECT COUNT(*) FROM t3_sepa_features WHERE date = '{check_date}' AND m03_score IS NULL
        """).fetchone()[0]
        _check("spot_date", f"null_m03_on_{check_date}",
               "WARNING" if null_m03 > 0 else "OK", null_m03,
               f"Rows with NULL m03_score on {check_date}")


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
    parser = argparse.ArgumentParser(description="T3 SEPA features audit (t3_sepa_features table)")
    parser.add_argument("--json",      action="store_true", help="Output results as JSON")
    parser.add_argument("--warn-only", action="store_true", help="Only print warnings/failures; exit 1 if any found")
    parser.add_argument("--date",      type=str, help="Spot-check a specific date (YYYY-MM-DD)")
    args = parser.parse_args()

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        print(f"Auditing t3_sepa_features in: {DUCKDB_PATH}")
        check_coverage(con)
        check_feature_version(con)
        check_column_nulls(con)
        check_pct_chg(con)
        check_ts_alphas(con)
        check_xs_alphas_and_ranks(con)
        check_m03_regime(con)
        check_staleness(con)
        check_referential(con)
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