"""
Date-Coverage Audit — interior gaps in the daily panels
-------------------------------------------------------
The generalisation of the three detectors added 2026-07-19. Phase 3/5 gap-detect
T2/T3 and Phase 1 self-heals t1_macro, but each was written only after a specific
incident. This asks the same question of EVERY daily panel, so the next table to
develop a hole is found by a check rather than by a human noticing months later.

The question: for each panel, is any US trading day missing between the table's own
first and last row? Interior holes are the dangerous kind — the incremental writers
resume from MAX(date) and never look back, so a hole behind the frontier is
permanent and silent. (`t1_macro` carried 5 such dates from June 2026.)

Reference calendar = SPY's own `price_data` rows: the same market calendar the
orchestrator trusts in `_get_last_trading_day`, and it needs no network.

Tolerance is 0 — MEASURED, not guessed (cf audit_serving_tables.py). Verified
2026-07-19 over full history: t2_screener_features 0, t3_sepa_features 0,
t2_regime_scores 0, t1_macro 5 (the known June-2026 holes, now self-healed by
Phase 1). Any nonzero value is a real regression, not noise.

Run:
    python tools/audit_date_coverage.py
    python tools/audit_date_coverage.py --json
    python tools/audit_date_coverage.py --warn-only
    python tools/audit_date_coverage.py --lookback-days 365   # bound the scan
"""

import argparse
import json
import sys
from typing import Any

import duckdb

sys.path.insert(0, ".")
from config import DUCKDB_PATH
from src.orchestrators.phase_registry import label_for

# (table, date_col, phase_id, severity)
# severity: a hole in a panel the model TRAINS or SCORES on is a FAIL; a display
# feed degrades a panel and is a WARNING.
PANELS: list[tuple[str, str, str, str]] = [
    ("t1_macro",             "date", "ingestion",   "WARNING"),
    ("t2_screener_features", "date", "t2_screener", "FAIL"),
    ("t2_regime_scores",     "date", "t2_regime",   "WARNING"),
    ("t3_sepa_features",     "date", "t3_features", "FAIL"),
]

_results: list[dict[str, Any]] = []


def _check(section: str, name: str, status: str, value: Any, detail: str = "") -> None:
    _results.append({"section": section, "check": name, "status": status,
                     "value": value, "detail": detail})


def check_interior_gaps(con: duckdb.DuckDBPyConnection, lookback_days: int | None) -> None:
    """Trading days absent from each panel, bounded by the panel's own date range.

    Bounding by MIN(date) per table matters: the panels start at different dates
    (t3 2001, t2_regime 2003) and days before a panel exists are not gaps.
    """
    for table, col, phase_id, severity in PANELS:
        phase = label_for(phase_id)
        # Lower bound: the panel's own start, optionally tightened by --lookback-days.
        floor = f"(SELECT MIN({col}) FROM {table})"
        if lookback_days is not None:
            floor = f"GREATEST({floor}, CURRENT_DATE - INTERVAL {int(lookback_days)} DAY)"

        try:
            missing = con.execute(f"""
                WITH trading_days AS (
                    SELECT DISTINCT date
                    FROM price_data
                    WHERE ticker = 'SPY'
                      AND date >= {floor}
                      AND date <= (SELECT MAX({col}) FROM {table})
                )
                SELECT td.date
                FROM trading_days td
                LEFT JOIN (SELECT DISTINCT {col} AS d FROM {table}) t ON t.d = td.date
                WHERE t.d IS NULL
                ORDER BY td.date
            """).fetchall()
        except duckdb.Error as e:
            _check(table, f"{table}_queryable", "FAIL", "missing",
                   f"{phase} panel not queryable: {str(e)[:80]}")
            continue

        if not missing:
            _check(table, f"{table}_interior_gaps", "OK", 0,
                   f"no missing trading days ({phase})")
            continue

        dates = [r[0].strftime("%Y-%m-%d") for r in missing]
        sample = ", ".join(dates[:5]) + (f" +{len(dates) - 5} more" if len(dates) > 5 else "")
        _check(table, f"{table}_interior_gaps", severity, len(dates),
               f"{phase} missing {len(dates)} trading day(s): {sample}. "
               f"Incremental writers resume from MAX(date), so interior holes never self-close.")


def _render_text(warn_only: bool) -> int:
    prefix = {"FAIL": "[FAIL]   ", "WARNING": "[WARN]   ", "OK": "[OK]     ", "INFO": "[INFO]   "}
    shown = [r for r in _results if not warn_only or r["status"] in ("FAIL", "WARNING")]
    for r in shown:
        print(f"{prefix[r['status']]}{r['section']:24s} {r['check']:32s} "
              f"{str(r['value']):>8s}  {r['detail']}")
    counts: dict[str, int] = {}
    for r in _results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"\n  SUMMARY: {counts.get('FAIL',0)} FAIL | {counts.get('WARNING',0)} WARNING | "
          f"{counts.get('OK',0)} OK | {counts.get('INFO',0)} INFO")
    return 1 if (warn_only and counts.get("FAIL", 0) + counts.get("WARNING", 0)) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Interior date-coverage audit for daily panels")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--warn-only", action="store_true")
    parser.add_argument("--lookback-days", type=int, default=None,
                        help="Bound the scan to the trailing N days (default: full panel history)")
    args = parser.parse_args()

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        if not args.json:
            print(f"Auditing date coverage in: {DUCKDB_PATH}")
        check_interior_gaps(con, args.lookback_days)
    finally:
        con.close()

    if args.json:
        print(json.dumps(_results, indent=2, default=str))
        sys.exit(0)
    sys.exit(_render_text(args.warn_only))


if __name__ == "__main__":
    main()
