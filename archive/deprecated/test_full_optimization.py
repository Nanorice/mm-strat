"""
Comprehensive test of all optimizations with larger sample.

Tests the full optimization stack with a realistic sample size.
"""

import pandas as pd
import sys
from pathlib import Path
import time
import psutil
import gc

sys.path.append(str(Path(__file__).parent))


def main():
    """Run comprehensive optimization test."""
    print("="*80)
    print(" COMPREHENSIVE OPTIMIZATION TEST")
    print("="*80)

    from build_dataset_a import build_dataset_a
    from src.data_engine import DataRepository
    from src.utils import filter_etfs

    # Get larger sample
    data_repo = DataRepository()
    all_tickers = data_repo.update_universe()
    all_tickers = filter_etfs(all_tickers)

    # Use first 100 tickers for more realistic test
    sample_size = min(100, len(all_tickers))
    sample_tickers = all_tickers[:sample_size]

    print(f"\nTest Configuration:")
    print(f"  Tickers: {sample_size}")
    print(f"  Date range: 2024-01-01 to 2025-01-10 (1+ year)")
    print(f"  Mode: Lightweight + Fundamentals")
    print(f"  Workers: 10")

    # Measure baseline
    process = psutil.Process()
    gc.collect()  # Clean up before test
    mem_before = process.memory_info().rss / (1024 * 1024)

    print(f"\nMemory before: {mem_before:.1f} MB")
    print("\nStarting build...")
    print("-"*80)

    start_time = time.time()

    try:
        df_result = build_dataset_a(
            start_date='2024-01-01',
            end_date='2025-01-10',
            mode='lightweight',
            tickers=sample_tickers,
            validate_temporal=False,
            include_fundamentals=True,
            include_cross_sectional=False,
            n_jobs=10,  # Use 10 workers for realistic performance
            skip_data_updates=True
        )

        elapsed = time.time() - start_time
        mem_after = process.memory_info().rss / (1024 * 1024)
        mem_delta = mem_after - mem_before

        print("\n" + "="*80)
        print(" RESULTS")
        print("="*80)

        if df_result is not None and not df_result.empty:
            # Calculate statistics
            rows = len(df_result)
            cols = len(df_result.columns)
            tickers_processed = df_result['ticker'].nunique()
            date_min = df_result['date'].min()
            date_max = df_result['date'].max()
            days_covered = (date_max - date_min).days

            memory_mb = df_result.memory_usage(deep=True).sum() / (1024 * 1024)

            print(f"\n[SUCCESS] Dataset Generated")
            print(f"\n  Dataset Size:")
            print(f"    Rows: {rows:,}")
            print(f"    Columns: {cols}")
            print(f"    Memory: {memory_mb:.1f} MB")
            print(f"\n  Coverage:")
            print(f"    Tickers: {tickers_processed} / {sample_size}")
            print(f"    Date Range: {date_min.date()} to {date_max.date()}")
            print(f"    Trading Days: {days_covered}")

            print(f"\n  Performance:")
            print(f"    Total Time: {elapsed:.2f}s ({elapsed/60:.2f} min)")
            print(f"    Throughput: {tickers_processed/elapsed:.2f} tickers/sec")
            print(f"    Per-Ticker: {elapsed/tickers_processed:.2f}s")

            print(f"\n  Memory:")
            print(f"    Before: {mem_before:.1f} MB")
            print(f"    After: {mem_after:.1f} MB")
            print(f"    Delta: {mem_delta:+.1f} MB")
            print(f"    Peak Ratio: {mem_delta/memory_mb:.2f}x dataset size")

            # Data quality checks
            print(f"\n  Data Quality:")
            null_critical = df_result[['date', 'ticker', 'Close', 'Volume']].isnull().sum().sum()
            dupes = df_result.duplicated(subset=['date', 'ticker']).sum()

            if null_critical == 0:
                print("    [OK] No nulls in critical columns")
            else:
                print(f"    [WARN] {null_critical} nulls in critical columns")

            if dupes == 0:
                print("    [OK] No duplicate (date, ticker) pairs")
            else:
                print(f"    [WARN] {dupes} duplicate rows")

            # Check sorting
            is_sorted = (df_result.groupby('ticker')['date'].apply(lambda x: x.is_monotonic_increasing).all())
            if is_sorted:
                print("    [OK] Data properly sorted within each ticker")
            else:
                print("    [WARN] Data not properly sorted")

            # Extrapolate to full dataset
            print(f"\n  Projected Full Build (2,350 tickers):")
            scaling_factor = 2350 / tickers_processed
            projected_time = elapsed * scaling_factor
            projected_mem_delta = mem_delta * scaling_factor

            print(f"    Estimated Time: {projected_time:.0f}s ({projected_time/60:.1f} min)")
            print(f"    Estimated Memory Delta: {projected_mem_delta:.0f} MB ({projected_mem_delta/1024:.1f} GB)")
            print(f"    Estimated Throughput: {2350/projected_time:.2f} tickers/sec")

            print(f"\n[OK] COMPREHENSIVE TEST PASSED")

        else:
            print("\n[FAIL] No data generated")

    except Exception as e:
        print(f"\n[FAIL] Error: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "="*80)


if __name__ == '__main__':
    main()
