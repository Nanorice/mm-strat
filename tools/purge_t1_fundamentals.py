"""
T1 Fundamentals Cleanup — F1, F6, F7
-------------------------------------
Removes two categories of rows from the fundamentals table:

  1. Orphan tickers (F1): any source, ticker NOT in company_profiles
  2. All edgar rows (F6 + F7): source='edgar', all period_types
     Rationale: edgar field mapping is not comprehensive enough to distinguish
     industry nuances; FMP/yfinance provide better-normalised coverage for
     all active universe members.

Run (dry-run first):
    python tools/purge_t1_fundamentals.py --dry-run
    python tools/purge_t1_fundamentals.py
"""

import argparse
import sys

import duckdb

sys.path.insert(0, ".")
from config import DUCKDB_PATH


def _count(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    return con.execute(sql).fetchone()[0]


def audit(con: duckdb.DuckDBPyConnection) -> dict:
    total = _count(con, "SELECT COUNT(*) FROM fundamentals")

    orphan_rows = _count(con, """
        SELECT COUNT(*) FROM fundamentals f
        LEFT JOIN company_profiles cp ON f.ticker = cp.ticker
        WHERE cp.ticker IS NULL
    """)
    orphan_tickers = _count(con, """
        SELECT COUNT(DISTINCT f.ticker) FROM fundamentals f
        LEFT JOIN company_profiles cp ON f.ticker = cp.ticker
        WHERE cp.ticker IS NULL
    """)

    edgar_rows = _count(con, "SELECT COUNT(*) FROM fundamentals WHERE source = 'edgar'")
    edgar_tickers = _count(con, "SELECT COUNT(DISTINCT ticker) FROM fundamentals WHERE source = 'edgar'")

    # Edgar rows that are NOT already captured by orphan purge
    # (i.e. edgar rows belonging to tickers that ARE in company_profiles)
    edgar_in_cp_rows = _count(con, """
        SELECT COUNT(*) FROM fundamentals f
        INNER JOIN company_profiles cp ON f.ticker = cp.ticker
        WHERE f.source = 'edgar'
    """)

    # Total unique rows to delete (union of both conditions)
    total_delete = _count(con, """
        SELECT COUNT(*) FROM fundamentals f
        LEFT JOIN company_profiles cp ON f.ticker = cp.ticker
        WHERE cp.ticker IS NULL OR f.source = 'edgar'
    """)

    return {
        "total_rows": total,
        "orphan_rows": orphan_rows,
        "orphan_tickers": orphan_tickers,
        "edgar_rows": edgar_rows,
        "edgar_tickers": edgar_tickers,
        "edgar_in_cp_rows": edgar_in_cp_rows,
        "total_delete": total_delete,
        "remaining": total - total_delete,
    }


def print_plan(stats: dict) -> None:
    print("\nPurge plan:")
    print(f"  Current fundamentals rows    : {stats['total_rows']:>8,}")
    print(f"  Orphan rows (not in CP)      : {stats['orphan_rows']:>8,}  ({stats['orphan_tickers']} tickers)")
    print(f"  Edgar rows (all)             : {stats['edgar_rows']:>8,}  ({stats['edgar_tickers']} tickers)")
    print(f"    of which in active universe: {stats['edgar_in_cp_rows']:>8,}  (these tickers retain FMP/yfinance rows)")
    print(f"  Total rows to DELETE         : {stats['total_delete']:>8,}  ({stats['total_delete']/stats['total_rows']*100:.1f}%)")
    print(f"  Rows remaining               : {stats['remaining']:>8,}")


def purge(con: duckdb.DuckDBPyConnection, before: int) -> int:
    con.execute("""
        DELETE FROM fundamentals
        WHERE source = 'edgar'
           OR ticker NOT IN (SELECT ticker FROM company_profiles)
    """)
    after = _count(con, "SELECT COUNT(*) FROM fundamentals")
    return before - after


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge edgar + orphan rows from fundamentals")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without making changes")
    args = parser.parse_args()

    con = duckdb.connect(str(DUCKDB_PATH), read_only=args.dry_run)
    try:
        stats = audit(con)
        print_plan(stats)

        if args.dry_run:
            print("\n[DRY RUN] No changes made.")
            return

        print("\nProceeding with delete...")
        deleted = purge(con, stats["total_rows"])
        print(f"[OK] Deleted {deleted:,} rows.")

        remaining = _count(con, "SELECT COUNT(*) FROM fundamentals")
        print(f"[OK] fundamentals now has {remaining:,} rows.")

        # Sanity: confirm no edgar rows remain
        edgar_left = _count(con, "SELECT COUNT(*) FROM fundamentals WHERE source = 'edgar'")
        orphans_left = _count(con, """
            SELECT COUNT(*) FROM fundamentals f
            LEFT JOIN company_profiles cp ON f.ticker = cp.ticker
            WHERE cp.ticker IS NULL
        """)
        print(f"[OK] Edgar rows remaining : {edgar_left}")
        print(f"[OK] Orphan rows remaining: {orphans_left}")

    finally:
        con.close()


if __name__ == "__main__":
    main()
