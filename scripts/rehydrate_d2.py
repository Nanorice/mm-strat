"""
Rehydrate D2 Dataset - Phase 1A
Expand d2 snapshots to multi-day trajectories (entry to SEPA exit)

This script creates d2_rehydrated.parquet with full trade trajectories,
enabling backtesting analysis and exit strategy optimization.

Usage:
    .venv/Scripts/python.exe scripts/rehydrate_d2.py
    .venv/Scripts/python.exe scripts/rehydrate_d2.py --n-jobs 4
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import pandas as pd
from src.data_engine import DataRepository, CacheMode
from src.features import FeatureEngineer
from src.fundamental_merger import FundamentalMerger
from src.dataset_rehydrator import DatasetRehydrator
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Rehydrate D2 Dataset (Phase 1A)")
    parser.add_argument('--n-jobs', type=int, default=-1, help='Parallel workers (-1=all CPUs)')
    args = parser.parse_args()

    # Load d1 trades
    d1_path = Path("data/ml/d1_trades.parquet")
    if not d1_path.exists():
        logger.error(f"D1 file not found: {d1_path}")
        logger.error("Run: .venv/Scripts/python.exe model_trainer.py --steps d1")
        return

    logger.info(f"Loading {d1_path}...")
    d1 = pd.read_parquet(d1_path)
    logger.info(f"Loaded {len(d1)} trades")

    # Initialize components
    logger.info("Initializing data engines...")
    data_repo = DataRepository()
    benchmark = data_repo.get_benchmark_data(mode=CacheMode.CACHE_ONLY)
    feature_engine = FeatureEngineer(benchmark_data=benchmark)
    fund_merger = FundamentalMerger(force_cache_only=True)

    # Rehydrate
    logger.info(f"Starting rehydration (n_jobs={args.n_jobs})...")
    rehydrator = DatasetRehydrator(data_repo, feature_engine, fund_merger)
    d2_rehydrated = rehydrator.rehydrate_trades(d1, n_jobs=args.n_jobs)

    # Save
    output_path = Path("data/ml/d2_rehydrated.parquet")
    logger.info(f"Saving to {output_path}...")
    d2_rehydrated.to_parquet(output_path, compression='snappy')

    # Statistics
    logger.info(f"\n{'='*60}")
    logger.info(f"REHYDRATION COMPLETE!")
    logger.info(f"{'='*60}")
    logger.info(f"Total rows: {len(d2_rehydrated):,}")
    logger.info(f"Unique trades: {d2_rehydrated['trade_id'].nunique()}")
    logger.info(f"Avg days per trade: {len(d2_rehydrated) / d2_rehydrated['trade_id'].nunique():.1f}")
    logger.info(f"File size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")

    # Feature count (129 columns = 128 from d2 + trade_id)
    metadata_cols = [
        'trade_id', 'ticker', 'Date',
        'label', 'return_pct', 'days_held', 'exit_reason',
        'Open', 'High', 'Low', 'Close', 'Volume'
    ]
    feature_cols = [c for c in d2_rehydrated.columns if c not in metadata_cols]
    logger.info(f"Features per day: {len(feature_cols)}")

    # Label distribution (across unique trades)
    unique_trades = d2_rehydrated.groupby('trade_id').first()
    logger.info(f"\nLabel Distribution:")
    logger.info(f"  Winners (label=1): {(unique_trades['label'] == 1).sum()} "
                f"({(unique_trades['label'] == 1).sum() / len(unique_trades) * 100:.1f}%)")
    logger.info(f"  Losers (label=0): {(unique_trades['label'] == 0).sum()} "
                f"({(unique_trades['label'] == 0).sum() / len(unique_trades) * 100:.1f}%)")

    logger.info(f"\n{'='*60}")
    logger.info(f"Next steps:")
    logger.info(f"1. Build backtesting system to calculate MDD/MFE from trajectories")
    logger.info(f"2. Test alternative exit strategies (ATR-based, SMA-based, time-based)")
    logger.info(f"3. Identify exit improvement opportunities (Phase 1B)")
    logger.info(f"{'='*60}")


if __name__ == '__main__':
    main()
