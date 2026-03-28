"""
Backfill screener_membership event log (Phase 2).

Delegates to ScreenerManager.backfill_all() — single SQL pass using
gaps-and-islands window functions. No Python loop over dates.

Usage:
    python scripts/backfill_screener_membership.py
    python scripts/backfill_screener_membership.py --start 2022-01-01
    python scripts/backfill_screener_membership.py --start 2022-01-01 --end 2023-12-31
    python scripts/backfill_screener_membership.py --reset   # truncate and re-run

Expected runtime: 30-120s for full history (~10K tickers, 6 years).
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DUCKDB_PATH
from src.managers.screener_manager import ScreenerManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def _get_price_data_stats(db_path: str, start: str | None, end: str | None) -> dict:
    with duckdb.connect(str(db_path), read_only=True) as conn:
        mn, mx, tickers, rows = conn.execute("""
            SELECT MIN(date), MAX(date), COUNT(DISTINCT ticker), COUNT(*)
            FROM price_data
        """).fetchone()
        existing_events = conn.execute(
            "SELECT COUNT(*) FROM screener_membership"
        ).fetchone()[0]
    return {
        "price_min": mn, "price_max": mx,
        "price_tickers": tickers, "price_rows": rows,
        "existing_events": existing_events,
        "effective_start": start or str(mn),
        "effective_end":   end   or str(mx),
    }


def _confirm_reset(db_path: str) -> bool:
    with duckdb.connect(str(db_path), read_only=True) as conn:
        count = conn.execute("SELECT COUNT(*) FROM screener_membership").fetchone()[0]
    if count == 0:
        print("   screener_membership is already empty.")
        return True
    print(f"\n   [WARN] --reset will DELETE all {count:,} existing events from screener_membership.")
    answer = input("   Confirm? [yes/N]: ").strip().lower()
    return answer == "yes"


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill screener_membership event log (Phase 2)")
    parser.add_argument("--start", help="Start date YYYY-MM-DD (default: MIN(price_data.date))")
    parser.add_argument("--end",   help="End date YYYY-MM-DD (default: MAX(price_data.date))")
    parser.add_argument("--reset", action="store_true",
                        help="Truncate screener_membership before backfilling (full rebuild)")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  PHASE 2 BACKFILL — screener_membership")
    print("=" * 60)

    # Pre-flight stats
    try:
        stats = _get_price_data_stats(DUCKDB_PATH, args.start, args.end)
    except Exception as e:
        logger.error(f"Failed to read database: {e}")
        sys.exit(1)

    print(f"\n  price_data:  {stats['price_tickers']:,} tickers | "
          f"{stats['price_rows']:,} rows | "
          f"{stats['price_min']} -> {stats['price_max']}")
    print(f"  Backfill range:  {stats['effective_start']} -> {stats['effective_end']}")
    print(f"  Existing events: {stats['existing_events']:,}")

    if stats['price_rows'] == 0:
        logger.error("price_data is empty — run Phase 1 backfill first.")
        sys.exit(1)

    # Reset if requested
    if args.reset:
        if not _confirm_reset(DUCKDB_PATH):
            print("  Aborted.")
            sys.exit(0)
        with duckdb.connect(str(DUCKDB_PATH)) as conn:
            conn.execute("DELETE FROM screener_membership")
        print("  [OK] screener_membership truncated.")

    elif stats['existing_events'] > 0:
        print(f"\n  [INFO] {stats['existing_events']:,} events already exist.")
        print("  INSERT OR IGNORE will skip existing (ticker, effective_date) pairs.")
        print("  Use --reset to do a full rebuild.")

    print(f"\n  Running single-pass SQL backfill...")
    print("  (gaps-and-islands window function — no progress bar, expected 30-120s)\n")

    mgr = ScreenerManager(str(DUCKDB_PATH))
    t0 = time.perf_counter()

    try:
        result = mgr.backfill_all(start_date=args.start, end_date=args.end)
    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
        sys.exit(1)

    elapsed = time.perf_counter() - t0

    print("=" * 60)
    print(f"  [OK] Backfill complete in {elapsed:.1f}s")
    print(f"       Events written:  {result['total_events']:,}")
    print(f"       Entry events:    {result['entered']:,}")
    print(f"       Exit events:     {result['exited']:,}")
    print(f"       Active tickers:  {result['active']:,}")
    print("=" * 60)

    if result['total_events'] == 0 and stats['existing_events'] > 0:
        print("\n  [INFO] 0 new events — all rows already existed (idempotent run).")
    elif result['active'] < 200:
        print(f"\n  [WARN] Only {result['active']} active tickers — run the audit to investigate:")
        print("         python tools/audit_t2_membership.py")
    else:
        print("\n  Run audit to validate:")
        print("  python tools/audit_t2_membership.py --warn-only")


if __name__ == "__main__":
    main()
