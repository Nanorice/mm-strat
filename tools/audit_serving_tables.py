"""
Serving-Layer Data Quality Audit
--------------------------------
Freshness + sanity for the DERIVED tables the dashboard reads — the phase
outputs that sit below T1/T2/T3 and had no audit until now. A dead Phase
7.4/7.45/7.46/7.47 greys a panel out and says nothing; this is what notices.

Tolerances are MEASURED, not guessed (a guessed tolerance fires false warnings
on healthy feeds — cf the macro_data freq tolerances). Observed worst-case gap
over 2y on a healthy pipeline: weather_gauge 6d, daily_predictions 13d,
sector_breadth is a 1-row-per-night snapshot. Shipped = observed + headroom.

Run:
    python tools/audit_serving_tables.py
    python tools/audit_serving_tables.py --json
    python tools/audit_serving_tables.py --warn-only
"""

import argparse
import json
import sys
from datetime import date
from typing import Any

import duckdb

sys.path.insert(0, ".")
from config import DUCKDB_PATH

# (table, date_col, stale_warn_days, phase) — stale_warn = observed worst gap + headroom.
SERVING_TABLES: list[tuple[str, str, int, str]] = [
    ("daily_predictions", "prediction_date", 20, "Phase 7.4 - Scoring"),
    ("weather_gauge",     "date",            10, "Phase 7.45 - Weather Gauge"),
    ("sector_breadth",    "as_of_date",       5, "Phase 7.46 - Sector Breadth"),
    ("nav_history",       "date",            10, "Phase 7.47 - Portfolio NAV"),
]

_results: list[dict[str, Any]] = []


def _check(section: str, name: str, status: str, value: Any, detail: str = "") -> None:
    _results.append({"section": section, "check": name, "status": status,
                     "value": value, "detail": detail})


def check_freshness(con: duckdb.DuckDBPyConnection) -> None:
    """Staleness of each serving table vs its measured tolerance."""
    for table, col, tol, phase in SERVING_TABLES:
        try:
            # CAST: sector_breadth.as_of_date is a TIMESTAMP, the rest are DATE.
            n, mx = con.execute(
                f"SELECT COUNT(*), CAST(MAX({col}) AS DATE) FROM {table}"
            ).fetchone()
        except duckdb.Error as e:
            _check(table, f"{table}_exists", "FAIL", "missing",
                   f"{phase} output not queryable: {str(e)[:80]}")
            continue

        if not n:
            # Empty is INFO not FAIL: nav_history is legitimately empty until the
            # book has fills. An empty table can't be stale.
            _check(table, f"{table}_rows", "INFO", 0,
                   f"{phase} output is empty (no rows yet)")
            continue

        stale = (date.today() - mx).days
        status = "OK" if stale <= tol else "WARNING"
        _check(table, f"{table}_max_date", status, str(mx),
               f"{stale}d since last row (tolerance {tol}d, {phase})")


def check_sanity(con: duckdb.DuckDBPyConnection) -> None:
    """Cheap per-table invariants — the shape the dashboard assumes."""
    # sector_breadth is rebuilt each night as a single-day snapshot. >1 date means
    # the refresh appended instead of replacing (the Macro heatmap would double-count).
    try:
        n_dates = con.execute("SELECT COUNT(DISTINCT as_of_date) FROM sector_breadth").fetchone()[0]
        if n_dates:
            status = "OK" if n_dates == 1 else "FAIL"
            _check("sector_breadth", "single_snapshot", status, n_dates,
                   "sector_breadth must hold exactly 1 as_of_date (refresh replaces, never appends)")
    except duckdb.Error:
        pass

    # weather_gauge drives the only lever that survived BackTrader (SPY>200d).
    # A NULL posture silently blanks the deploy headline.
    try:
        nulls = con.execute(
            "SELECT COUNT(*) FROM weather_gauge WHERE date >= CURRENT_DATE - 30"
            " AND (spy_above_200d IS NULL OR deploy_posture IS NULL)"
        ).fetchone()[0]
        status = "OK" if nulls == 0 else "WARNING"
        _check("weather_gauge", "null_posture_30d", status, nulls,
               "Rows in last 30d with NULL spy_above_200d/deploy_posture")
    except duckdb.Error:
        pass

    # nav_history: NAV must equal cash + positions. A drift means the derived-cash
    # invariant broke (cash is derived from flows+fills, never stored).
    try:
        bad = con.execute(
            "SELECT COUNT(*) FROM nav_history"
            " WHERE ABS(nav - (cash + positions_value)) > 0.01"
        ).fetchone()[0]
        status = "OK" if bad == 0 else "FAIL"
        _check("nav_history", "nav_equals_cash_plus_positions", status, bad,
               "Rows where nav != cash + positions_value (derived-cash invariant broken)")
    except duckdb.Error:
        pass


def _render_text(warn_only: bool) -> int:
    prefix = {"FAIL": "[FAIL]   ", "WARNING": "[WARN]   ", "OK": "[OK]     ", "INFO": "[INFO]   "}
    shown = [r for r in _results if not warn_only or r["status"] in ("FAIL", "WARNING")]
    for r in shown:
        print(f"{prefix[r['status']]}{r['section']:20s} {r['check']:36s} {str(r['value']):>12s}  {r['detail']}")
    counts: dict[str, int] = {}
    for r in _results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"\n  SUMMARY: {counts.get('FAIL',0)} FAIL | {counts.get('WARNING',0)} WARNING | "
          f"{counts.get('OK',0)} OK | {counts.get('INFO',0)} INFO")
    return 1 if (warn_only and counts.get("FAIL", 0) + counts.get("WARNING", 0)) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Serving-layer data quality audit")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args()

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        if not args.json:
            print(f"Auditing serving tables in: {DUCKDB_PATH}")
        check_freshness(con)
        check_sanity(con)
    finally:
        con.close()

    if args.json:
        print(json.dumps(_results, indent=2, default=str))
        sys.exit(0)
    sys.exit(_render_text(args.warn_only))


if __name__ == "__main__":
    main()
