"""
T2 Screener Membership Audit
-----------------------------
Evaluates data quality of the screener_membership event log (Phase 2).

Checks:
  1. Event log health — row counts, date range, entry/exit balance
  2. Market cap integrity — zero/null market_cap events (shares_ffill gap issue)
  3. Grace period logic — exits should always have consec_fail_days == 126
  4. State consistency — no ticker should have two consecutive same-polarity events
  5. Current universe — active ticker count vs expected range
  6. Criteria version coverage — all events use a known version

Run:
    python tools/audit_t2_screener_membership.py
    python tools/audit_t2_screener_membership.py --json
    python tools/audit_t2_screener_membership.py --warn-only
    python tools/audit_t2_screener_membership.py --date 2024-01-15  # point-in-time universe
"""

import argparse
import json
import sys
from datetime import date
from typing import Any

import duckdb

sys.path.insert(0, ".")
from config import DUCKDB_PATH

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
EXPECTED_MIN_ACTIVE = 200    # active universe floor — fewer is suspicious
EXPECTED_MAX_ACTIVE = 5000   # active universe ceiling — more suggests criteria bug
ZERO_MCAP_WARN_PCT  = 5.0    # warn if >5% of entry events have market_cap == 0
ZERO_MCAP_FAIL_PCT  = 20.0   # fail if >20%

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_results: list[dict[str, Any]] = []


def _check(section: str, name: str, status: str, value: Any, detail: str = "") -> None:
    _results.append({"section": section, "check": name, "status": status, "value": value, "detail": detail})


def _pct(part: int, total: int) -> float:
    return round(part / total * 100, 1) if total else 0.0


# ---------------------------------------------------------------------------
# Section 1: Event Log Health
# ---------------------------------------------------------------------------
def check_event_log(con: duckdb.DuckDBPyConnection) -> None:
    total = con.execute("SELECT COUNT(*) FROM screener_membership").fetchone()[0]
    _check("event_log", "total_events", "INFO", total, "Total rows in screener_membership")

    if total == 0:
        _check("event_log", "table_empty", "FAIL", 0, "screener_membership has no rows — Phase 2 backfill not run yet")
        return

    entries, exits = con.execute("""
        SELECT
            COUNT(*) FILTER (WHERE is_active = TRUE),
            COUNT(*) FILTER (WHERE is_active = FALSE)
        FROM screener_membership
    """).fetchone()
    _check("event_log", "entry_events",  "INFO", entries, "Rows with is_active=TRUE (entry events)")
    _check("event_log", "exit_events",   "INFO", exits,   "Rows with is_active=FALSE (exit events)")

    # Exits must never exceed entries per ticker (exit without prior entry = bug)
    bad_exit_tickers = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT ticker,
                   COUNT(*) FILTER (WHERE is_active = TRUE)  AS n_entries,
                   COUNT(*) FILTER (WHERE is_active = FALSE) AS n_exits
            FROM screener_membership
            GROUP BY ticker
            HAVING n_exits > n_entries
        )
    """).fetchone()[0]
    _check("event_log", "exits_exceed_entries", "FAIL" if bad_exit_tickers > 0 else "OK",
           bad_exit_tickers, "Tickers where exit events outnumber entry events (state machine bug)")

    mn, mx = con.execute("SELECT MIN(effective_date), MAX(effective_date) FROM screener_membership").fetchone()
    _check("event_log", "date_range", "INFO", f"{mn} to {mx}", "Date range covered by event log")

    distinct_tickers = con.execute("SELECT COUNT(DISTINCT ticker) FROM screener_membership").fetchone()[0]
    _check("event_log", "distinct_tickers", "INFO", distinct_tickers, "Unique tickers that ever appeared in event log")


# ---------------------------------------------------------------------------
# Section 2: Market Cap Integrity (the shares_ffill gap issue)
# ---------------------------------------------------------------------------
def check_market_cap(con: duckdb.DuckDBPyConnection) -> None:
    total_entries = con.execute(
        "SELECT COUNT(*) FROM screener_membership WHERE is_active = TRUE"
    ).fetchone()[0]

    if total_entries == 0:
        _check("market_cap", "skipped", "INFO", 0, "No entry events — skipping market_cap checks")
        return

    # Zero market_cap on entry events means shares_ffill was NULL (no shares data for that ticker)
    zero_mcap = con.execute("""
        SELECT COUNT(*) FROM screener_membership
        WHERE is_active = TRUE AND (market_cap IS NULL OR market_cap = 0)
    """).fetchone()[0]
    pct = _pct(zero_mcap, total_entries)
    if pct >= ZERO_MCAP_FAIL_PCT:
        status = "FAIL"
    elif pct >= ZERO_MCAP_WARN_PCT:
        status = "WARNING"
    else:
        status = "OK"
    _check("market_cap", "zero_or_null_market_cap_pct", status, pct,
           f"{zero_mcap}/{total_entries} entry events have market_cap=0 or NULL "
           f"(ticker had no shares_history — failed market_cap filter correctly, "
           f"but signals missing shares data)")

    # Which tickers are affected — top 20 by event count
    if zero_mcap > 0:
        rows = con.execute("""
            SELECT ticker, COUNT(*) AS n_events,
                   MIN(effective_date) AS first_seen,
                   MAX(effective_date) AS last_seen
            FROM screener_membership
            WHERE is_active = TRUE AND (market_cap IS NULL OR market_cap = 0)
            GROUP BY ticker
            ORDER BY n_events DESC
            LIMIT 20
        """).fetchall()
        detail = " | ".join(f"{t}({n})" for t, n, _, _ in rows)
        _check("market_cap", "zero_mcap_tickers_top20", "INFO", len(rows),
               f"Tickers with zero/null market_cap on entry — {detail}")

    # Tickers that NEVER entered the universe solely because of missing shares
    # (they pass price + volume but always have market_cap=0 → never hit 150M threshold)
    # Proxy: in price_data with max close >= 5 and avg volume OK, but never in screener_membership
    never_entered = con.execute("""
        WITH price_eligible AS (
            SELECT DISTINCT p.ticker
            FROM price_data p
            INNER JOIN company_profiles cp ON p.ticker = cp.ticker
            WHERE p.close >= 5
              AND cp.ticker NOT IN (SELECT DISTINCT ticker FROM shares_history)
              AND cp.ticker NOT IN (SELECT DISTINCT ticker FROM screener_membership WHERE is_active = TRUE)
        )
        SELECT COUNT(*) FROM price_eligible
    """).fetchone()[0]
    status = "WARNING" if never_entered > 50 else "OK"
    _check("market_cap", "price_eligible_never_entered_no_shares", status, never_entered,
           "Tickers passing price>=5 but never entered universe AND have no shares_history "
           "(excluded by market_cap filter due to missing shares data)")


# ---------------------------------------------------------------------------
# Section 3: Grace Period Logic
# ---------------------------------------------------------------------------
def check_grace_period(con: duckdb.DuckDBPyConnection) -> None:
    total_exits = con.execute(
        "SELECT COUNT(*) FROM screener_membership WHERE is_active = FALSE"
    ).fetchone()[0]

    if total_exits == 0:
        _check("grace_period", "no_exits", "INFO", 0, "No exit events yet")
        return

    # All exit events must have consec_fail_days == 126
    bad_exits = con.execute("""
        SELECT COUNT(*) FROM screener_membership
        WHERE is_active = FALSE AND consec_fail_days != 126
    """).fetchone()[0]
    _check("grace_period", "exits_with_wrong_consec_fail_days", "FAIL" if bad_exits > 0 else "OK",
           bad_exits, f"Exit events where consec_fail_days != 126 (expected exactly 126 for all exits)")

    # Entry events must have consec_fail_days == 0
    bad_entries = con.execute("""
        SELECT COUNT(*) FROM screener_membership
        WHERE is_active = TRUE AND consec_fail_days != 0
    """).fetchone()[0]
    _check("grace_period", "entries_with_nonzero_consec_fail_days", "FAIL" if bad_entries > 0 else "OK",
           bad_entries, "Entry events where consec_fail_days != 0 (should always be 0 on entry)")


# ---------------------------------------------------------------------------
# Section 4: State Consistency (no duplicate consecutive same-polarity events)
# ---------------------------------------------------------------------------
def check_state_consistency(con: duckdb.DuckDBPyConnection) -> None:
    # Two consecutive TRUE events for the same ticker = entry written twice without an exit
    dup_entries = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT ticker, effective_date, is_active,
                   LAG(is_active) OVER (PARTITION BY ticker ORDER BY effective_date) AS prev_active
            FROM screener_membership
        )
        WHERE is_active = TRUE AND prev_active = TRUE
    """).fetchone()[0]
    _check("state_consistency", "duplicate_entry_events", "FAIL" if dup_entries > 0 else "OK",
           dup_entries, "Consecutive entry (TRUE) events for same ticker — missing exit in between")

    # Two consecutive FALSE events = exit written twice
    dup_exits = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT ticker, effective_date, is_active,
                   LAG(is_active) OVER (PARTITION BY ticker ORDER BY effective_date) AS prev_active
            FROM screener_membership
        )
        WHERE is_active = FALSE AND prev_active = FALSE
    """).fetchone()[0]
    _check("state_consistency", "duplicate_exit_events", "FAIL" if dup_exits > 0 else "OK",
           dup_exits, "Consecutive exit (FALSE) events for same ticker — grace period logic error")


# ---------------------------------------------------------------------------
# Section 5: Current Universe Size
# ---------------------------------------------------------------------------
def check_current_universe(con: duckdb.DuckDBPyConnection, as_of_date: str) -> None:
    active = con.execute(f"""
        WITH latest AS (
            SELECT ticker, is_active,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY effective_date DESC) AS rn
            FROM screener_membership
            WHERE effective_date <= '{as_of_date}'
        )
        SELECT COUNT(*) FROM latest WHERE rn = 1 AND is_active = TRUE
    """).fetchone()[0]

    if active < EXPECTED_MIN_ACTIVE:
        status = "WARNING"
    elif active > EXPECTED_MAX_ACTIVE:
        status = "WARNING"
    else:
        status = "OK"
    _check("current_universe", "active_tickers", status, active,
           f"Active tickers as of {as_of_date} (expected {EXPECTED_MIN_ACTIVE}–{EXPECTED_MAX_ACTIVE})")

    # Breakdown: tickers active today that have no price_data in last 5 days (ghost tickers).
    # Exclude tickers where cp.is_active=FALSE — those are confirmed delisted and expected to
    # have no recent price; screener exit events should be (or will be) logged for them.
    ghost = con.execute(f"""
        WITH latest AS (
            SELECT ticker, is_active,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY effective_date DESC) AS rn
            FROM screener_membership
            WHERE effective_date <= '{as_of_date}'
        ),
        active_now AS (
            SELECT sm.ticker FROM latest sm
            JOIN company_profiles cp ON sm.ticker = cp.ticker
            WHERE sm.rn = 1 AND sm.is_active = TRUE AND cp.is_active = TRUE
        )
        SELECT COUNT(*) FROM active_now a
        WHERE NOT EXISTS (
            SELECT 1 FROM price_data p
            WHERE p.ticker = a.ticker
              AND p.date >= DATE '{as_of_date}' - INTERVAL 5 DAY
        )
    """).fetchone()[0]
    status = "WARNING" if ghost > 10 else "OK"
    _check("current_universe", "active_tickers_no_recent_price", status, ghost,
           f"Active tickers (cp.is_active=TRUE) with no price data in last 5 days before {as_of_date}")


# ---------------------------------------------------------------------------
# Section 6: Criteria Version Coverage
# ---------------------------------------------------------------------------
def check_criteria_versions(con: duckdb.DuckDBPyConnection) -> None:
    try:
        known_versions = {r[0] for r in con.execute(
            "SELECT version_id FROM screener_criteria_versions"
        ).fetchall()}
    except Exception:
        _check("criteria_versions", "criteria_table_missing", "FAIL", 0,
               "screener_criteria_versions table not found")
        return

    rows = con.execute("""
        SELECT criteria_version, COUNT(*) AS event_count
        FROM screener_membership
        GROUP BY criteria_version
        ORDER BY criteria_version
    """).fetchall()

    for version_id, event_count in rows:
        status = "OK" if version_id in known_versions else "FAIL"
        _check("criteria_versions", f"version_{version_id}_events", status, event_count,
               f"Events using criteria_version={version_id} "
               f"({'known' if status == 'OK' else 'UNKNOWN — not in screener_criteria_versions'})")

    if not rows:
        _check("criteria_versions", "no_events", "INFO", 0, "No events in screener_membership")


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
STATUS_ORDER  = {"FAIL": 0, "WARNING": 1, "OK": 2, "INFO": 3}
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
        line = f"  {prefix}{r['check']:<48} {val}"
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
    parser = argparse.ArgumentParser(description="T2 screener membership audit")
    parser.add_argument("--json",      action="store_true", help="Output results as JSON")
    parser.add_argument("--warn-only", action="store_true", help="Only print warnings/failures; exit 1 if any found")
    parser.add_argument("--date",      type=str, default=str(date.today()),
                        help="Point-in-time date for current universe check (default: today)")
    args = parser.parse_args()

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        print(f"Auditing screener_membership in: {DUCKDB_PATH}")
        print(f"Point-in-time date: {args.date}")
        check_event_log(con)
        check_market_cap(con)
        check_grace_period(con)
        check_state_consistency(con)
        check_current_universe(con, args.date)
        check_criteria_versions(con)
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
