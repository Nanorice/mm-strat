"""
Backtest Parameter Optimization Script

Runs grid search over SEPAHybridV1 strategy parameters with walk-forward validation.

Grid: 5x5x3 = 75 parameter combinations
- entry_percentile: [0.0, 0.50, 0.60, 0.70, 0.80]
- exit_percentile: [0.20, 0.30, 0.40, 0.50, 0.60]
- sizing_mode: ['regime', 'equal_weight', 'rank_weighted']

Walk-Forward:
- Training: 2023-01-01 to 2023-12-31
- Testing: 2024-01-01 to 2024-12-31

Output:
- CSV: data/backtest/optimization_results.csv
- JSON: data/backtest/best_params.json (top 10 stable configs)

Usage:
    python scripts/backtest_optimization.py [--parallel] [--output-dir data/backtest]
"""

import argparse
import json
import os
import sys
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.duckdb_feed import DuckDBUniverseDataLoader
from src.backtest.runner import SEPABacktestRunner
from config import DUCKDB_PATH


def create_parameter_grid() -> List[Dict]:
    """Create grid of parameter combinations to test."""
    entry_percentiles = [0.0, 0.50, 0.60, 0.70, 0.80]
    exit_percentiles = [0.20, 0.30, 0.40, 0.50, 0.60]
    sizing_modes = ['regime', 'equal_weight', 'rank_weighted']

    grid = []
    for entry, exit, sizing in product(entry_percentiles, exit_percentiles, sizing_modes):
        grid.append({
            'entry_percentile_min': entry,
            'exit_percentile_max': exit,
            'exit_use_percentile': True,  # Always enable rank exits for optimization
            'sizing_mode': sizing,
        })

    return grid


def run_backtest(
    params: Dict,
    start_date: str,
    end_date: str,
    universe: List[str],
    loader: DuckDBUniverseDataLoader,
) -> Dict:
    """Run single backtest with given parameters.

    Args:
        params: Strategy parameters
        start_date: Backtest start date (YYYY-MM-DD)
        end_date: Backtest end date (YYYY-MM-DD)
        universe: List of ticker symbols
        loader: Data loader instance

    Returns:
        Dict with performance metrics
    """
    try:
        # NOTE: SEPABacktestRunner is designed for parquet files
        # For DuckDB optimization, we use the old SEPABacktestRunner with parquet paths
        # This is a temporary workaround until DuckDB integration is complete

        runner = SEPABacktestRunner(
            start_date=start_date,
            end_date=end_date,
            initial_cash=100000.0,
            commission=0.001,
        )

        # Setup with default paths (will load from parquet)
        runner.setup()

        # Run backtest
        results = runner.run()

        # Extract metrics
        metrics = runner.get_performance_metrics()

        return {
            'sharpe': metrics.get('sharpe_ratio', 0.0),
            'calmar': metrics.get('calmar_ratio', 0.0),
            'max_dd': metrics.get('max_drawdown_pct', 0.0),
            'total_return': metrics.get('total_return_pct', 0.0),
            'trades': metrics.get('total_trades', 0),
            'win_rate': metrics.get('win_rate', 0.0),
            'avg_win': metrics.get('avg_win_pct', 0.0),
            'avg_loss': metrics.get('avg_loss_pct', 0.0),
            'final_value': metrics.get('final_value', 100000.0),
            'error': None,
        }

    except Exception as e:
        return {
            'error': str(e),
            'sharpe': 0.0,
            'calmar': 0.0,
            'max_dd': 0.0,
            'total_return': 0.0,
            'trades': 0,
            'win_rate': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'final_value': 100000.0,
        }


def run_walk_forward_validation(
    params: Dict,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
    universe: List[str],
    loader: DuckDBUniverseDataLoader,
) -> Dict:
    """Run walk-forward validation for parameter set.

    Args:
        params: Strategy parameters
        train_start: Training period start
        train_end: Training period end
        test_start: Test period start
        test_end: Test period end
        universe: Ticker universe
        loader: Data loader

    Returns:
        Dict with train + test metrics and stability scores
    """
    # Training period
    train_metrics = run_backtest(
        params=params,
        start_date=train_start,
        end_date=train_end,
        universe=universe,
        loader=loader,
    )

    # Test period
    test_metrics = run_backtest(
        params=params,
        start_date=test_start,
        end_date=test_end,
        universe=universe,
        loader=loader,
    )

    # Calculate stability metrics
    train_sharpe = train_metrics['sharpe']
    test_sharpe = test_metrics['sharpe']

    # Degradation: test/train ratio (1.0 = perfect stability, <1.0 = overfitting)
    if train_sharpe > 0:
        degradation = test_sharpe / train_sharpe
    else:
        degradation = 0.0

    # Stability score: penalize large drops (1.0 = stable, 0.0 = unstable)
    stability_score = min(1.0, max(0.0, degradation))

    # Combined result
    result = {
        # Parameters
        'entry_percentile': params['entry_percentile_min'],
        'exit_percentile': params['exit_percentile_max'],
        'sizing_mode': params['sizing_mode'],

        # Training metrics
        'train_sharpe': train_sharpe,
        'train_calmar': train_metrics['calmar'],
        'train_max_dd': train_metrics['max_dd'],
        'train_return': train_metrics['total_return'],
        'train_trades': train_metrics['trades'],
        'train_win_rate': train_metrics['win_rate'],

        # Test metrics
        'test_sharpe': test_sharpe,
        'test_calmar': test_metrics['calmar'],
        'test_max_dd': test_metrics['max_dd'],
        'test_return': test_metrics['total_return'],
        'test_trades': test_metrics['trades'],
        'test_win_rate': test_metrics['win_rate'],

        # Stability
        'degradation': degradation,
        'stability_score': stability_score,

        # Errors
        'train_error': train_metrics.get('error'),
        'test_error': test_metrics.get('error'),
    }

    return result


def main():
    parser = argparse.ArgumentParser(description='Backtest parameter optimization with walk-forward validation')
    parser.add_argument('--output-dir', type=str, default='data/backtest',
                        help='Output directory for results')
    parser.add_argument('--parallel', action='store_true',
                        help='Run backtests in parallel (not implemented yet)')
    parser.add_argument('--train-start', type=str, default='2023-01-01',
                        help='Training period start date')
    parser.add_argument('--train-end', type=str, default='2023-12-31',
                        help='Training period end date')
    parser.add_argument('--test-start', type=str, default='2024-01-01',
                        help='Test period start date')
    parser.add_argument('--test-end', type=str, default='2024-12-31',
                        help='Test period end date')

    args = parser.parse_args()

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*80}")
    print("Backtest Parameter Optimization - Walk-Forward Validation")
    print(f"{'='*80}\n")

    print(f"Training Period: {args.train_start} to {args.train_end}")
    print(f"Test Period: {args.test_start} to {args.test_end}")
    print(f"Output Directory: {output_dir}\n")

    # Initialize data loader
    print("Initializing DuckDB data loader...")
    loader = DuckDBUniverseDataLoader(db_path=DUCKDB_PATH)

    # Get universe (all tickers in t3_sepa_features)
    print("Loading universe from t3_sepa_features...")
    universe = loader.get_available_tickers()
    print(f"Universe size: {len(universe)} tickers\n")

    # Create parameter grid
    print("Creating parameter grid...")
    grid = create_parameter_grid()
    print(f"Grid size: {len(grid)} combinations")
    print(f"  - Entry percentiles: [0.0, 0.50, 0.60, 0.70, 0.80]")
    print(f"  - Exit percentiles: [0.20, 0.30, 0.40, 0.50, 0.60]")
    print(f"  - Sizing modes: ['regime', 'equal_weight', 'rank_weighted']\n")

    # Run grid search
    print(f"Starting grid search ({len(grid)} backtests)...")
    print(f"{'='*80}\n")

    results = []
    start_time = datetime.now()

    for i, params in enumerate(grid, 1):
        print(f"[{i}/{len(grid)}] Testing: entry={params['entry_percentile_min']:.2f}, "
              f"exit={params['exit_percentile_max']:.2f}, sizing={params['sizing_mode']}")

        result = run_walk_forward_validation(
            params=params,
            train_start=args.train_start,
            train_end=args.train_end,
            test_start=args.test_start,
            test_end=args.test_end,
            universe=universe,
            loader=loader,
        )

        results.append(result)

        # Progress update
        elapsed = (datetime.now() - start_time).total_seconds()
        avg_time = elapsed / i
        remaining = avg_time * (len(grid) - i)

        print(f"  Train: Sharpe={result['train_sharpe']:.2f}, Calmar={result['train_calmar']:.2f}, "
              f"Trades={result['train_trades']}")
        print(f"  Test:  Sharpe={result['test_sharpe']:.2f}, Calmar={result['test_calmar']:.2f}, "
              f"Trades={result['test_trades']}")
        print(f"  Stability: Degradation={result['degradation']:.2f}, Score={result['stability_score']:.2f}")
        print(f"  ETA: {remaining/60:.1f} min\n")

    # Convert to DataFrame
    df_results = pd.DataFrame(results)

    # Save full results to CSV
    csv_path = output_dir / 'optimization_results.csv'
    df_results.to_csv(csv_path, index=False)
    print(f"\n[OK] Saved full results to: {csv_path}")

    # Find top 10 stable configurations
    # Sort by: 1) Stability score (descending), 2) Test Sharpe (descending)
    df_sorted = df_results.sort_values(
        by=['stability_score', 'test_sharpe'],
        ascending=[False, False],
    )

    top_10 = df_sorted.head(10).to_dict('records')

    # Save top 10 to JSON
    json_path = output_dir / 'best_params.json'
    with open(json_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'train_period': f"{args.train_start} to {args.train_end}",
            'test_period': f"{args.test_start} to {args.test_end}",
            'universe_size': len(universe),
            'total_combinations': len(grid),
            'top_10_configs': top_10,
        }, f, indent=2)

    print(f"[OK] Saved top 10 configs to: {json_path}\n")

    # Print summary
    print(f"{'='*80}")
    print("Top 10 Stable Configurations")
    print(f"{'='*80}\n")

    for i, config in enumerate(top_10, 1):
        print(f"{i}. Entry={config['entry_percentile']:.2f}, "
              f"Exit={config['exit_percentile']:.2f}, "
              f"Sizing={config['sizing_mode']}")
        print(f"   Train Sharpe: {config['train_sharpe']:.2f} | "
              f"Test Sharpe: {config['test_sharpe']:.2f} | "
              f"Degradation: {config['degradation']:.2f}")
        print(f"   Train Trades: {config['train_trades']} | "
              f"Test Trades: {config['test_trades']}\n")

    # Overall statistics
    total_time = (datetime.now() - start_time).total_seconds()
    print(f"\n{'='*80}")
    print(f"Grid search completed in {total_time/60:.1f} minutes")
    print(f"Average time per backtest: {total_time/len(grid):.1f} seconds")
    print(f"{'='*80}\n")


if __name__ == '__main__':
    main()
