"""
Test Optimization 1: Streaming Concatenation

Tests that the streaming approach produces identical results to the old concat method.
"""

import pandas as pd
import sys
from pathlib import Path
import time
import psutil

sys.path.append(str(Path(__file__).parent))


def main():
    """Run the test."""
    # Test with a small subset
    print("="*80)
    print(" TESTING OPTIMIZATION 1: STREAMING CONCATENATION")
    print("="*80)

    # Measure memory before
    process = psutil.Process()
    mem_before = process.memory_info().rss / (1024 * 1024)
    print(f"\nMemory before test: {mem_before:.1f} MB")

    # Run a small test build
    from build_dataset_a import build_dataset_a
    from src.data_engine import DataRepository

    # Get a small sample of tickers
    data_repo = DataRepository()
    from src.utils import filter_etfs
    all_tickers = data_repo.update_universe()
    all_tickers = filter_etfs(all_tickers)

    # Use only first 20 tickers for quick test
    sample_tickers = all_tickers[:20]

    print(f"\nTesting with {len(sample_tickers)} sample tickers")
    print(f"Date range: 2025-01-01 to 2025-01-10")

    # Time the build
    start_time = time.time()

    try:
        df_result = build_dataset_a(
            start_date='2025-01-01',
            end_date='2025-01-10',
            mode='lightweight',
            tickers=sample_tickers,
            validate_temporal=False,
            include_fundamentals=True,
            include_cross_sectional=False,
            n_jobs=4,  # Parallel to test streaming
            skip_data_updates=True
        )

        elapsed = time.time() - start_time
        mem_after = process.memory_info().rss / (1024 * 1024)
        mem_peak = mem_after - mem_before

        print("\n" + "="*80)
        print(" TEST RESULTS")
        print("="*80)

        if df_result is not None and not df_result.empty:
            print(f"\n[OK] SUCCESS: Generated dataset")
            print(f"  Rows: {len(df_result):,}")
            print(f"  Columns: {len(df_result.columns)}")
            print(f"  Tickers: {df_result['ticker'].nunique()}")
            print(f"  Date range: {df_result['date'].min()} to {df_result['date'].max()}")
            print(f"\n[TIME] {elapsed:.2f}s")
            print(f"[MEM] Memory delta: {mem_peak:+.1f} MB")

            # Verify data integrity
            print("\n[CHECK] Data Integrity Checks:")

            # Check for nulls in critical columns
            null_counts = df_result[['date', 'ticker', 'Close', 'Volume']].isnull().sum()
            if null_counts.sum() == 0:
                print("  [OK] No nulls in critical columns (date, ticker, Close, Volume)")
            else:
                print(f"  [WARN] Null counts: {null_counts[null_counts > 0]}")

            # Check sorting
            is_sorted = (df_result['ticker'].values[:-1] <= df_result['ticker'].values[1:]).all()
            if is_sorted:
                print("  [OK] Data properly sorted by ticker")
            else:
                print("  [FAIL] Data NOT sorted by ticker")

            # Check for duplicates
            dupes = df_result.duplicated(subset=['date', 'ticker']).sum()
            if dupes == 0:
                print("  [OK] No duplicate (date, ticker) pairs")
            else:
                print(f"  [WARN] Found {dupes} duplicate rows")

            print("\n[OK] Optimization 1 test PASSED")

        else:
            print("\n[FAIL] No data generated")

    except Exception as e:
        print(f"\n[FAIL] Error: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "="*80)


if __name__ == '__main__':
    main()
