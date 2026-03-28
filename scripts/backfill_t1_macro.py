"""
Backfill t1_macro (SPY, QQQ, VIX daily OHLCV) via yfinance.

Delegates to MacroEngine.ingest_daily_macro() which is idempotent (INSERT OR IGNORE).
Default start is 2000-01-01 to align with price_data history.

Usage:
    python scripts/backfill_t1_macro.py
    python scripts/backfill_t1_macro.py --start 2000-01-01
    python scripts/backfill_t1_macro.py --start 2000-01-01 --end 2010-12-31
    python scripts/backfill_t1_macro.py --reset   # truncate and re-run from start

Expected runtime: 5-15s (yfinance bulk download, single request).
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DUCKDB_PATH
from src.macro_engine import MacroEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

DEFAULT_START = '2000-01-01'


def _get_stats(db_path: str) -> dict:
    with duckdb.connect(str(db_path), read_only=True) as con:
        try:
            mn, mx, rows = con.execute(
                "SELECT MIN(date), MAX(date), COUNT(*) FROM t1_macro"
            ).fetchone()
        except Exception:
            mn, mx, rows = None, None, 0
    return {'min': mn, 'max': mx, 'rows': rows}


def _confirm_reset(db_path: str) -> bool:
    with duckdb.connect(str(db_path), read_only=True) as con:
        count = con.execute("SELECT COUNT(*) FROM t1_macro").fetchone()[0]
    if count == 0:
        print("   t1_macro is already empty.")
        return True
    print(f"\n   [WARN] --reset will DELETE all {count:,} existing rows from t1_macro.")
    answer = input("   Confirm? [yes/N]: ").strip().lower()
    return answer == "yes"


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill t1_macro (SPY/QQQ/VIX)")
    parser.add_argument("--start", default=DEFAULT_START,
                        help=f"Start date YYYY-MM-DD (default: {DEFAULT_START})")
    parser.add_argument("--end", help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--reset", action="store_true",
                        help="Truncate t1_macro before backfilling (full rebuild)")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  T1_MACRO BACKFILL — SPY / QQQ / VIX")
    print("=" * 60)

    stats = _get_stats(DUCKDB_PATH)
    print(f"\n  t1_macro current : {stats['rows']:,} rows | "
          f"{stats['min']} -> {stats['max']}")
    print(f"  Backfill range   : {args.start} -> {args.end or 'today'}")

    if args.reset:
        if not _confirm_reset(DUCKDB_PATH):
            print("  Aborted.")
            sys.exit(0)
        with duckdb.connect(str(DUCKDB_PATH)) as con:
            con.execute("DELETE FROM t1_macro")
        print("  [OK] t1_macro truncated.")
    elif stats['rows'] > 0:
        print(f"\n  [INFO] {stats['rows']:,} rows already exist.")
        print("  INSERT OR IGNORE will skip existing dates.")
        print("  Use --reset for a full rebuild.")

    print(f"\n  Fetching from yfinance...")

    engine = MacroEngine(str(DUCKDB_PATH))
    t0 = time.perf_counter()

    try:
        rows_written = engine.ingest_daily_macro(start_date=args.start)
    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
        sys.exit(1)

    elapsed = time.perf_counter() - t0
    stats_after = _get_stats(DUCKDB_PATH)

    print("=" * 60)
    print(f"  [OK] Done in {elapsed:.1f}s")
    print(f"       Rows written : {rows_written:,}")
    print(f"       Total rows   : {stats_after['rows']:,}")
    print(f"       Range        : {stats_after['min']} -> {stats_after['max']}")
    print("=" * 60)

    if stats_after['min'] and str(stats_after['min']) > args.start:
        print(f"\n  [WARN] Coverage starts {stats_after['min']}, expected {args.start}.")
        print("         yfinance may not have SPY data that far back.")


if __name__ == "__main__":
    main()
