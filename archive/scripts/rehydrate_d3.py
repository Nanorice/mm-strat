"""
Rehydrate D3 Dataset with Triple Barrier Exits

Uses the existing DatasetRehydrator but with D3's barrier exit days
instead of SEPA exits or fixed horizon.

Output: data/ml/d3_rehydrated.parquet - Multi-day trajectories truncated to barrier exits.
"""

import pandas as pd
import argparse
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent))

from src.data_engine import DataRepository, CacheMode
from src.features import FeatureEngineer
from src.fundamental_merger import FundamentalMerger
from src.dataset_rehydrator import DatasetRehydrator


def rehydrate_d3(
    d1_path: str = 'data/ml/d1_trades.parquet',
    d3_path: str = 'data/ml/d3_triple_barrier_labels.parquet',
    output_path: str = 'data/ml/d3_rehydrated.parquet',
    n_jobs: int = -1
):
    """
    Create d3_rehydrated by applying D3 barrier exit days to rehydration.
    
    Args:
        d1_path: Path to D1 trades (entry info)
        d3_path: Path to D3 labels (barrier exit info)
        output_path: Where to save rehydrated D3
        n_jobs: Parallel workers
    """
    print("=" * 70)
    print(" REHYDRATE D3 - TRIPLE BARRIER EXITS")
    print("=" * 70)
    
    # Load data
    print(f"\nLoading D1: {d1_path}")
    d1 = pd.read_parquet(d1_path)
    print(f"  {len(d1):,} trades")
    
    print(f"Loading D3: {d3_path}")
    d3 = pd.read_parquet(d3_path)
    print(f"  {len(d3):,} trades with barrier exits")
    
    # Filter D1 to only trades that exist in D3
    d3_trade_ids = set(d3['trade_id'])
    d1_filtered = d1[d1['trade_id'].isin(d3_trade_ids)].copy()
    print(f"\nFiltered D1 to D3 trades: {len(d1_filtered):,}")
    
    # Initialize components
    print("\nInitializing rehydrator...")
    data_repo = DataRepository()
    benchmark_data = data_repo.get_benchmark_data()
    if benchmark_data is None:
        raise RuntimeError("Failed to load benchmark data")
    
    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    fund_merger = FundamentalMerger(force_cache_only=True)
    
    # Create rehydrator with D3 exits
    rehydrator = DatasetRehydrator(
        data_repo=data_repo,
        feature_engine=feature_engine,
        fund_merger=fund_merger,
        d3_exits=d3  # Use barrier exits from D3
    )
    
    # Rehydrate trades
    print(f"\nRehydrating {len(d1_filtered):,} trades with barrier exits...")
    d3_rehydrated = rehydrator.rehydrate_trades(d1_filtered, n_jobs=n_jobs)
    
    # Summary
    print("\n" + "=" * 70)
    print(" REHYDRATION COMPLETE")
    print("=" * 70)
    print(f"Rows: {len(d3_rehydrated):,}")
    print(f"Trades: {d3_rehydrated['trade_id'].nunique():,}")
    print(f"Columns: {len(d3_rehydrated.columns)}")
    
    # Barrier outcome breakdown
    if 'barrier_outcome' in d3_rehydrated.columns:
        print(f"\nBarrier Outcomes:")
        for outcome in ['TP', 'SL', 'Time']:
            count = (d3_rehydrated.groupby('trade_id')['barrier_outcome'].first() == outcome).sum()
            print(f"  {outcome}: {count:,}")
    
    # Days held stats
    days_per_trade = d3_rehydrated.groupby('trade_id').size()
    print(f"\nDays Held (per trade):")
    print(f"  Mean: {days_per_trade.mean():.1f}")
    print(f"  Median: {days_per_trade.median():.1f}")
    print(f"  Max: {days_per_trade.max()}")
    
    # Save
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    d3_rehydrated.to_parquet(output_path, index=False)
    size_mb = Path(output_path).stat().st_size / 1e6
    print(f"\nSaved: {output_path} ({size_mb:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description='Rehydrate D3 with barrier exits')
    parser.add_argument('--d1', default='data/ml/d1_trades.parquet', help='D1 trades path')
    parser.add_argument('--d3', default='data/ml/d3_triple_barrier_labels.parquet', help='D3 labels path')
    parser.add_argument('--output', default='data/ml/d3_rehydrated.parquet', help='Output path')
    parser.add_argument('--jobs', type=int, default=-1, help='Parallel workers')
    args = parser.parse_args()
    
    rehydrate_d3(
        d1_path=args.d1,
        d3_path=args.d3,
        output_path=args.output,
        n_jobs=args.jobs
    )


if __name__ == '__main__':
    main()
