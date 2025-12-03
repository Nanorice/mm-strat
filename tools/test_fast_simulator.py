"""
Quick test script to verify FastTradeSimulator works correctly.
Tests on a small date range with a few tickers.
"""

import sys
from pathlib import Path
import logging
import pandas as pd

# Add src to path
sys.path.append(str(Path(__file__).parent))

from src.data_engine import DataRepository
from src.strategy import SEPAStrategy
from src.features import FeatureEngineer
from src.trade_simulator import TradeSimulator
from src.trade_simulator_fast import FastTradeSimulator
from src.trading_config import TradingConfig

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_fast_simulator():
    """Test FastTradeSimulator on small dataset."""

    print("=" * 80)
    print(" TESTING FAST TRADE SIMULATOR")
    print("=" * 80)

    # Initialize components
    print("\n1. Initializing components...")
    data_repo = DataRepository()
    benchmark_data = data_repo.get_benchmark_data()

    if benchmark_data is None:
        print("❌ Failed to load benchmark data!")
        return

    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    strategy = SEPAStrategy(benchmark_data=benchmark_data)

    # Create trading configuration
    trading_config = TradingConfig(
        success_threshold_pct=15.0,
        exit_on_trend_break=True,
        exit_on_stop_loss=False,
        allow_reentry=True,
        reentry_cooldown_days=0
    )

    # Test on small date range (1 month only)
    start_date = '2024-06-01'
    end_date = '2024-06-30'
    outcome_end = '2024-09-30'

    print(f"\n2. Test Configuration:")
    print(f"   Entry Period: {start_date} to {end_date}")
    print(f"   Outcome Window: {start_date} to {outcome_end}")

    # Test 1: Original TradeSimulator (baseline)
    print("\n3. Running ORIGINAL TradeSimulator (baseline)...")

    simulator_original = TradeSimulator(
        data_repo=data_repo,
        strategy=strategy,
        feature_engine=feature_engine,
        start_date=start_date,
        end_date=end_date,
        outcome_end=outcome_end,
        config=trading_config
    )

    import time
    start_time = time.time()
    dataset_b_original = simulator_original.run_simulation()
    time_original = time.time() - start_time

    print(f"   [OK] Original: {len(dataset_b_original)} trades in {time_original:.2f}s")

    # Test 2: FastTradeSimulator (sequential)
    print("\n4. Running FastTradeSimulator (sequential)...")

    simulator_fast = FastTradeSimulator(
        data_repo=data_repo,
        strategy=strategy,
        feature_engine=feature_engine,
        start_date=start_date,
        end_date=end_date,
        outcome_end=outcome_end,
        config=trading_config
    )

    start_time = time.time()
    dataset_b_fast = simulator_fast.run_simulation(show_progress=False, n_jobs=1)
    time_fast = time.time() - start_time

    print(f"   [OK] Fast (sequential): {len(dataset_b_fast)} trades in {time_fast:.2f}s")

    # Test 3: FastTradeSimulator (parallel)
    print("\n5. Running FastTradeSimulator (parallel -1)...")

    simulator_parallel = FastTradeSimulator(
        data_repo=data_repo,
        strategy=strategy,
        feature_engine=feature_engine,
        start_date=start_date,
        end_date=end_date,
        outcome_end=outcome_end,
        config=trading_config
    )

    start_time = time.time()
    dataset_b_parallel = simulator_parallel.run_simulation(show_progress=False, n_jobs=-1)
    time_parallel = time.time() - start_time

    print(f"   [OK] Fast (parallel): {len(dataset_b_parallel)} trades in {time_parallel:.2f}s")

    # Compare results
    print("\n6. Performance Comparison:")
    print(f"   Original:         {time_original:.2f}s (baseline)")
    print(f"   Fast (sequential): {time_fast:.2f}s ({time_original/time_fast:.2f}x speedup)")
    print(f"   Fast (parallel):   {time_parallel:.2f}s ({time_original/time_parallel:.2f}x speedup)")

    # Validate results match
    print("\n7. Validation:")

    if len(dataset_b_original) == len(dataset_b_fast) == len(dataset_b_parallel):
        print(f"   [OK] Trade count matches: {len(dataset_b_original)} trades")
    else:
        print(f"   [WARN] Trade count mismatch:")
        print(f"      Original: {len(dataset_b_original)}")
        print(f"      Fast (seq): {len(dataset_b_fast)}")
        print(f"      Fast (par): {len(dataset_b_parallel)}")

    # Check if columns match
    if set(dataset_b_original.columns) == set(dataset_b_fast.columns):
        print(f"   [OK] Columns match: {len(dataset_b_original.columns)} columns")
    else:
        print(f"   [WARN] Column mismatch:")
        print(f"      Original: {dataset_b_original.columns.tolist()}")
        print(f"      Fast: {dataset_b_fast.columns.tolist()}")

    # Compare a few sample trades
    if len(dataset_b_original) > 0 and len(dataset_b_fast) > 0:
        # Sort both by entry_date and ticker to ensure same order
        df_orig = dataset_b_original.sort_values(['entry_date', 'ticker']).reset_index(drop=True)
        df_fast = dataset_b_fast.sort_values(['entry_date', 'ticker']).reset_index(drop=True)

        # Check first 5 trades
        n_check = min(5, len(df_orig))
        matches = 0
        for i in range(n_check):
            if (df_orig.loc[i, 'ticker'] == df_fast.loc[i, 'ticker'] and
                df_orig.loc[i, 'entry_date'] == df_fast.loc[i, 'entry_date'] and
                abs(df_orig.loc[i, 'return_pct'] - df_fast.loc[i, 'return_pct']) < 0.01):
                matches += 1

        print(f"   Sample trades match: {matches}/{n_check} trades")

    print("\n" + "=" * 80)
    print("[OK] TEST COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    try:
        test_fast_simulator()
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        print(f"\n[ERROR] {e}")
        sys.exit(1)
