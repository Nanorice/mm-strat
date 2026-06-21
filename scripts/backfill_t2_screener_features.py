"""
Backfill t2_screener_features (Phase 3) for the full price_data history.

Delegates to FeaturePipeline.compute_t2_screener_features() which runs:
  Phase A (SQL):  65 window-function columns over full screener universe
  Phase B (Python): 9 cross-sectional alphas (multiprocessing)
  Phase C (SQL):  7 PERCENT_RANK cross-sectional ranks

Chunked by year to avoid OOM — Phase B loads the full date range into RAM.
INSERT OR REPLACE is idempotent: safe to re-run or resume after failure.

Prerequisites (run in order):
  1. python scripts/backfill_screener_membership.py --reset
  2. python scripts/backfill_shares_from_fundamentals.py
  3. python scripts/backfill_t1_macro.py
  4. python scripts/backfill_t2_screener_features.py   <-- this script

Usage:
    python scripts/backfill_t2_screener_features.py
    python scripts/backfill_t2_screener_features.py --start 2005-01-01
    python scripts/backfill_t2_screener_features.py --start 2005-01-01 --end 2010-12-31
    python scripts/backfill_t2_screener_features.py --year 2007   # single year

Expected runtime: ~3-8 min per year (Phase A ~20s, Phase B ~60s, Phase C ~2s).
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DUCKDB_PATH
from src.feature_pipeline import FeaturePipeline

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
        mn, mx, rows, tickers = con.execute(
            "SELECT MIN(date), MAX(date), COUNT(*), COUNT(DISTINCT ticker) FROM t2_screener_features"
        ).fetchone()
    return {'min': mn, 'max': mx, 'rows': rows or 0, 'tickers': tickers or 0}


def _get_price_range(db_path: str) -> tuple:
    with duckdb.connect(str(db_path), read_only=True) as con:
        mn, mx = con.execute("SELECT MIN(date), MAX(date) FROM price_data").fetchone()
    return str(mn), str(mx)


def _year_chunks(start: str, end: str) -> list[tuple[str, str]]:
    """Return list of (year_start, year_end) tuples covering [start, end]."""
    import pandas as pd
    s = pd.to_datetime(start)
    e = pd.to_datetime(end)
    chunks = []
    year = s.year
    while year <= e.year:
        chunk_start = max(s, pd.Timestamp(f'{year}-01-01'))
        chunk_end   = min(e, pd.Timestamp(f'{year}-12-31'))
        chunks.append((chunk_start.strftime('%Y-%m-%d'), chunk_end.strftime('%Y-%m-%d')))
        year += 1
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill t2_screener_features (Phase 3)")
    parser.add_argument("--start", default=DEFAULT_START,
                        help=f"Start date YYYY-MM-DD (default: {DEFAULT_START})")
    parser.add_argument("--end",
                        help="End date YYYY-MM-DD (default: MAX(price_data.date))")
    parser.add_argument("--year", type=int,
                        help="Compute a single year only (overrides --start/--end)")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  T2 SCREENER FEATURES BACKFILL — Phase 3")
    print("=" * 60)

    price_min, price_max = _get_price_range(DUCKDB_PATH)
    stats_before = _get_stats(DUCKDB_PATH)

    if args.year:
        start = f"{args.year}-01-01"
        end   = f"{args.year}-12-31"
    else:
        start = args.start
        end   = args.end or price_max

    print(f"\n  price_data range     : {price_min} -> {price_max}")
    print(f"  t2 existing          : {stats_before['rows']:,} rows | {stats_before['tickers']:,} tickers | "
          f"{stats_before['min']} -> {stats_before['max']}")
    print(f"  Backfill range       : {start} -> {end}")

    chunks = _year_chunks(start, end)
    print(f"  Chunks               : {len(chunks)} year(s)")
    print()

    pipeline = FeaturePipeline(str(DUCKDB_PATH))
    total_start = time.perf_counter()
    total_rows = 0

    for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
        year = chunk_start[:4]
        print(f"  [{i}/{len(chunks)}] Year {year}  ({chunk_start} -> {chunk_end})")
        t0 = time.perf_counter()

        try:
            rows = pipeline.compute_t2_screener_features(
                start_date=chunk_start,
                end_date=chunk_end,
                warmup_days=730,
            )
            elapsed = time.perf_counter() - t0
            total_rows += rows
            print(f"        [OK] {rows:,} rows in {elapsed:.0f}s")
        except Exception as e:
            logger.error(f"  [{i}/{len(chunks)}] FAILED for {year}: {e}", exc_info=True)
            print(f"  Stopping. Re-run with --start {chunk_start} to resume.")
            sys.exit(1)

    total_elapsed = time.perf_counter() - total_start
    stats_after = _get_stats(DUCKDB_PATH)

    print()
    print("=" * 60)
    print(f"  [OK] Backfill complete in {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print(f"       Rows processed  : {total_rows:,}")
    print(f"       Total in table  : {stats_after['rows']:,} rows | {stats_after['tickers']:,} tickers")
    print(f"       Range           : {stats_after['min']} -> {stats_after['max']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
