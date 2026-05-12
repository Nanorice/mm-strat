"""
Phase 1 — FRED macro series backfill (Parquet + macro_data DuckDB table).

Default behavior:
  - Backfills DGS10, DGS2, WBAA (the three new series for the 5-factor risk model)
    plus refreshes the existing 5 series (WALCL, WTREGEN, RRPONTSYD,
    BAMLH0A0HYM2, VIX) into the macro_data table to catch up the stale window.
  - Writes Parquet cache AND DuckDB.

Usage:
  python scripts/backfill_macro_rates.py                 # default 1990-01-01 start
  python scripts/backfill_macro_rates.py --start 1980-01-01
  python scripts/backfill_macro_rates.py --new-only      # only DGS10/DGS2/WBAA
  python scripts/backfill_macro_rates.py --force         # full re-download
"""

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import duckdb
import pandas as pd

import config
from src.macro_engine import MacroEngine


NEW_SERIES = ['DGS10', 'DGS2', 'WBAA']
EXISTING_SERIES = ['WALCL', 'WTREGEN', 'RRPONTSYD', 'BAMLH0A0HYM2', 'VIX']


def fetch_and_write(engine: MacroEngine, series_id: str, start_date: str, force: bool) -> int:
    """Fetch one series from FRED, save to Parquet, then write to macro_data."""
    print(f"\n  [{series_id}] Fetching from {start_date}...")

    if series_id == 'VIX':
        df = engine.fetch_vix(start_date)
    else:
        df = engine.fetch_fred_series(series_id, start_date)

    if df.empty:
        print(f"  [{series_id}] No data returned")
        return 0

    # Merge with existing Parquet cache (unless --force)
    cached = engine._load_cache(series_id)
    if cached is not None and not force:
        combined = pd.concat([cached, df])
        combined = combined[~combined.index.duplicated(keep='last')].sort_index()
    else:
        combined = df

    engine._save_cache(series_id, combined)
    print(f"  [{series_id}] Parquet: {len(combined):,} rows total "
          f"({combined.index.min().date()} to {combined.index.max().date()})")

    inserted = engine.write_to_macro_data(series_id, combined)
    print(f"  [{series_id}] macro_data: +{inserted} new rows")
    return inserted


def print_summary(db_path: str) -> None:
    with duckdb.connect(db_path, read_only=True) as conn:
        rows = conn.execute("""
            SELECT symbol, COUNT(*) AS n, MIN(date) AS first, MAX(date) AS last
            FROM macro_data
            WHERE symbol IN ('WALCL','WTREGEN','RRPONTSYD','BAMLH0A0HYM2','VIX',
                             'DGS10','DGS2','WBAA')
            GROUP BY symbol
            ORDER BY symbol
        """).fetchall()
    print()
    print("=" * 60)
    print("[SUMMARY] macro_data series coverage")
    print("=" * 60)
    print(f"  {'symbol':<14s} {'rows':>8s}  {'first':<12s} {'last':<12s}")
    for sym, n, first, last in rows:
        print(f"  {sym:<14s} {n:>8,}  {first}  {last}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="FRED macro series backfill")
    parser.add_argument('--start', type=str, default='1990-01-01',
                        help='Start date (YYYY-MM-DD, default 1990-01-01)')
    parser.add_argument('--new-only', action='store_true',
                        help='Only fetch new series (DGS10/DGS2/WBAA)')
    parser.add_argument('--force', action='store_true',
                        help='Force full re-download (ignore Parquet cache)')
    args = parser.parse_args()

    series_list = NEW_SERIES if args.new_only else (NEW_SERIES + EXISTING_SERIES)

    print(f"Backfilling FRED series: {series_list}")
    print(f"Start date: {args.start}, force: {args.force}")

    engine = MacroEngine()
    total_inserted = 0
    for series_id in series_list:
        total_inserted += fetch_and_write(engine, series_id, args.start, args.force)

    print(f"\n[OK] Total rows inserted into macro_data: {total_inserted:,}")
    print_summary(str(config.DUCKDB_PATH))


if __name__ == '__main__':
    main()
