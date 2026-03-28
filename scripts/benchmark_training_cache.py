#!/usr/bin/env python3
"""
Benchmark d2_training_cache vs v_d2_training view performance.

Measures load time for training data using both methods:
1. Direct view query (5-10s expected)
2. Cached table query (<1s expected)

Usage:
    python scripts/benchmark_training_cache.py
    python scripts/benchmark_training_cache.py --db data/market_data.duckdb --runs 5
"""

import argparse
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.pipeline.data_pipeline import DataPipeline


def benchmark_load(use_cache: bool, runs: int = 3) -> tuple:
    """
    Benchmark training data load performance.

    Args:
        use_cache: If True, use d2_training_cache; else use v_d2_training
        runs: Number of runs to average

    Returns:
        (avg_time, row_count, col_count)
    """
    times = []
    row_count = 0
    col_count = 0

    dp = DataPipeline()

    for i in range(runs):
        start = time.time()
        df = dp.load_training_data_from_db(use_cache=use_cache)
        elapsed = time.time() - start
        times.append(elapsed)

        if i == 0:
            row_count = len(df)
            col_count = len(df.columns)

        # Print individual run time
        method = "CACHE" if use_cache else "VIEW "
        print(f"   [{method}] Run {i+1}/{runs}: {elapsed:.3f}s")

    avg_time = sum(times) / len(times)
    return avg_time, row_count, col_count


def main():
    parser = argparse.ArgumentParser(description='Benchmark training data load performance')
    parser.add_argument(
        '--db',
        type=str,
        default='data/market_data.duckdb',
        help='Path to DuckDB database (default: data/market_data.duckdb)'
    )
    parser.add_argument(
        '--runs',
        type=int,
        default=3,
        help='Number of runs to average (default: 3)'
    )
    args = parser.parse_args()

    print("\n[BENCHMARK] Training Data Load Benchmark")
    print("=" * 60)

    # Benchmark VIEW (direct query)
    print("\n[1] Benchmarking v_d2_training (direct view query)...")
    view_time, rows, cols = benchmark_load(use_cache=False, runs=args.runs)
    print(f"   Average: {view_time:.3f}s ({rows:,} rows, {cols} columns)")

    # Benchmark CACHE (materialized table)
    print("\n[2] Benchmarking d2_training_cache (materialized table)...")
    cache_time, _, _ = benchmark_load(use_cache=True, runs=args.runs)
    print(f"   Average: {cache_time:.3f}s ({rows:,} rows, {cols} columns)")

    # Results
    print("\n" + "=" * 60)
    print("[RESULTS]")
    print(f"   View:  {view_time:.3f}s")
    print(f"   Cache: {cache_time:.3f}s")
    speedup = view_time / cache_time if cache_time > 0 else 0
    print(f"   Speedup: {speedup:.1f}x faster")
    time_saved = view_time - cache_time
    print(f"   Time saved: {time_saved:.2f}s ({time_saved/view_time*100:.0f}% reduction)")

    # Validate speedup
    if speedup >= 3.0:
        print("\n[OK] Cache performance is EXCELLENT (>=3x speedup)")
    elif speedup >= 2.0:
        print("\n[OK] Cache performance is GOOD (>=2x speedup)")
    elif speedup >= 1.5:
        print("\n[WARN] Cache performance is OK (>=1.5x speedup)")
    else:
        print("\n[ERROR] Cache performance is POOR (<1.5x speedup)")
        print("   Possible issues:")
        print("   - Cache not refreshed (run scripts/refresh_training_cache.py)")
        print("   - DuckDB not using indexes")
        print("   - Disk I/O bottleneck")

    print()


if __name__ == '__main__':
    main()
