"""Quick test script for rehydration with 100 trades"""
import pandas as pd
from pathlib import Path
from src.data_engine import DataRepository, CacheMode
from src.features import FeatureEngineer
from src.fundamental_merger import FundamentalMerger
from src.dataset_rehydrator import DatasetRehydrator
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load subset
d1_path = Path("data/ml/d1_trades_subset100.parquet")
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
logger.info("Starting rehydration...")
rehydrator = DatasetRehydrator(data_repo, feature_engine, fund_merger)
d2_rehydrated = rehydrator.rehydrate_trades(d1, n_jobs=2)  # Use 2 jobs for testing

# Quick checks
logger.info(f"\n{'='*60}")
logger.info(f"TEST RESULTS")
logger.info(f"{'='*60}")
logger.info(f"Total rows: {len(d2_rehydrated):,}")
logger.info(f"Unique trades: {d2_rehydrated['trade_id'].nunique()}")
logger.info(f"Avg days per trade: {len(d2_rehydrated) / d2_rehydrated['trade_id'].nunique():.1f}")

# Check columns
logger.info(f"\nColumns: {len(d2_rehydrated.columns)}")
logger.info(f"New columns: trade_id, day_in_trade, is_exit_day, max_drawdown_pct, max_favorable_excursion_pct")

# Check exit days
exit_rows = d2_rehydrated[d2_rehydrated['is_exit_day']]
logger.info(f"\nExit rows: {len(exit_rows)} (should be {len(d1)})")

# Check a single trade
trade_1 = d2_rehydrated[d2_rehydrated['trade_id'] == 1]
logger.info(f"\nTrade 1 trajectory:")
logger.info(f"  Days: {len(trade_1)}")
logger.info(f"  day_in_trade range: {trade_1['day_in_trade'].min()} to {trade_1['day_in_trade'].max()}")
logger.info(f"  Exit day marked: {trade_1['is_exit_day'].sum()} (should be 1)")

logger.info(f"\n{'='*60}")
logger.info("TEST COMPLETE!")
logger.info(f"{'='*60}")
