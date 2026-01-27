"""
Grid Search for Optimal Triple Barrier Parameters

Performs walk-forward optimization to find best barrier parameters
that generalize to out-of-sample data.

Supports three barrier types:
- static: Fixed percentage thresholds
- dynamic: Pure ATR-based thresholds
- hybrid: MAX(floor%, k×ATR) for targets + ATR-based stops (RECOMMENDED)
"""

import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from tqdm import tqdm
from itertools import product
from joblib import Parallel, delayed
import sys
sys.path.append(str(Path(__file__).parent.parent))

from src.triple_barrier_labeler import (
    TripleBarrierLabeler,
    StaticBarrierParams,
    DynamicBarrierParams,
    HybridBarrierParams,
    compute_expectancy
)


def walk_forward_grid_search(
    d2_path: str,
    barrier_type: str = 'hybrid',
    train_years: int = 3,
    test_years: int = 1,
    n_jobs: int = -1
) -> pd.DataFrame:
    """
    Walk-forward grid search for optimal barriers.

    Strategy:
      Fold 1: Optimize on [2015-2017], validate on [2018]
      Fold 2: Optimize on [2016-2018], validate on [2019]
      ...

    Returns:
        DataFrame with grid results sorted by test_expectancy (descending)
    """
    # Load data
    print(f"Loading {d2_path}...")
    d2 = pd.read_parquet(d2_path)
    d2['year'] = pd.to_datetime(d2['Date']).dt.year
    
    print(f"Loaded: {len(d2):,} rows, {d2['trade_id'].nunique():,} trades")
    print(f"Years: {sorted(d2['year'].unique())}")

    # Define grid based on barrier type
    if barrier_type == 'static':
        grid = {
            'upper_pct': [0.10, 0.15, 0.20, 0.25, 0.30],
            'lower_pct': [0.04, 0.05, 0.07, 0.10],
            'time_days': [10, 20, 30, 60]
        }
        param_combinations = [
            StaticBarrierParams(u, l, t)
            for u, l, t in product(
                grid['upper_pct'], grid['lower_pct'], grid['time_days']
            )
        ]
        print(f"\nStatic Grid: {len(param_combinations)} combinations")
        
    elif barrier_type == 'dynamic':
        grid = {
            'upper_atr_mult': [1.5, 2.0, 2.5, 3.0],
            'lower_atr_mult': [0.5, 0.75, 1.0, 1.5],
            'time_days': [10, 20, 30]
        }
        param_combinations = [
            DynamicBarrierParams(u, l, t)
            for u, l, t in product(
                grid['upper_atr_mult'], grid['lower_atr_mult'], grid['time_days']
            )
        ]
        print(f"\nDynamic Grid: {len(param_combinations)} combinations")
        
    else:  # hybrid (RECOMMENDED)
        grid = {
            'k_sl': [1.0, 1.5, 2.0],            # Stop: How many ATRs? (tighter stops)
            'k_tp': [2.0, 3.0, 4.0],            # Target multiplier
            'min_tp': [0.15, 0.20],             # Floor: 15% vs 20%?
            'max_time': [30, 45, 60],           # Shorter horizons to catch drifters
        }
        param_combinations = [
            HybridBarrierParams(k_sl=ks, k_tp=kt, min_tp=mt, max_time=max_t)
            for ks, kt, mt, max_t in product(
                grid['k_sl'], grid['k_tp'], grid['min_tp'], grid['max_time']
            )
        ]
        print(f"\nHybrid Grid: {len(param_combinations)} combinations")
        print("  k_sl (stop): ", grid['k_sl'])
        print("  k_tp (target mult): ", grid['k_tp'])
        print("  min_tp (floor): ", grid['min_tp'])
        print("  max_time (horizon): ", grid['max_time'])

    # Walk-forward splits
    years = sorted(d2['year'].unique())
    results = []
    
    if len(years) < train_years + 1:
        raise ValueError(f"Not enough years for walk-forward. Have {len(years)}, need {train_years + 1}")

    for i, test_year in enumerate(years[train_years:]):
        train_years_range = years[i:i+train_years]

        train_data = d2[d2['year'].isin(train_years_range)]
        test_data = d2[d2['year'] == test_year]

        train_trades = train_data['trade_id'].nunique()
        test_trades = test_data['trade_id'].nunique()

        print(f"\n{'='*70}")
        print(f"Fold {i+1}: Train {list(train_years_range)} -> Test [{test_year}]")
        print(f"  Train: {train_trades:,} trades")
        print(f"  Test: {test_trades:,} trades")
        print(f"{'='*70}")

        # Pre-group trades for efficiency
        train_grouped = {tid: train_data[train_data['trade_id'] == tid].sort_values('Date')
                         for tid in train_data['trade_id'].unique()}
        test_grouped = {tid: test_data[test_data['trade_id'] == tid].sort_values('Date')
                        for tid in test_data['trade_id'].unique()}

        def evaluate_params(params):
            """Evaluate single parameter set."""
            train_outcomes = apply_barriers_to_trades_fast(train_grouped, params, barrier_type)
            if len(train_outcomes) == 0:
                return None
            train_metrics = compute_expectancy(train_outcomes)

            test_outcomes = apply_barriers_to_trades_fast(test_grouped, params, barrier_type)
            if len(test_outcomes) == 0:
                return None
            test_metrics = compute_expectancy(test_outcomes)

            if barrier_type == 'static':
                param_dict = {
                    'upper_pct': params.upper_pct,
                    'lower_pct': params.lower_pct,
                    'time_days': params.time_days
                }
            elif barrier_type == 'dynamic':
                param_dict = {
                    'upper_atr_mult': params.upper_atr_mult,
                    'lower_atr_mult': params.lower_atr_mult,
                    'time_days': params.time_days
                }
            else:  # hybrid
                param_dict = {
                    'k_sl': params.k_sl,
                    'k_tp': params.k_tp,
                    'min_tp': params.min_tp,
                    'max_time': params.max_time
                }

            return {
                'fold': i + 1,
                'test_year': test_year,
                **param_dict,
                'train_expectancy': train_metrics['expectancy'],
                'train_win_rate': train_metrics['win_rate'],
                'train_ignition_score': train_metrics['ignition_score'],
                'test_expectancy': test_metrics['expectancy'],
                'test_risk_adj_return': test_metrics['risk_adjusted_return'],
                'test_win_rate': test_metrics['win_rate'],
                'test_loss_rate': test_metrics['loss_rate'],
                'test_time_rate': test_metrics['time_rate'],
                'test_avg_days': test_metrics['avg_days'],
                'test_risk_reward': test_metrics['risk_reward'],
                'test_ignition_score': test_metrics['ignition_score'],
                'test_avg_win': test_metrics['avg_win'],
                'test_avg_time': test_metrics['avg_time'],
                'test_trades': len(test_outcomes)
            }

        # Parallel grid search for this fold
        if n_jobs == 1:
            fold_results = []
            for params in tqdm(param_combinations, desc=f"Fold {i+1} grid search"):
                result = evaluate_params(params)
                if result is not None:
                    fold_results.append(result)
        else:
            fold_results = Parallel(n_jobs=n_jobs, prefer="threads")(
                delayed(evaluate_params)(p) for p in tqdm(param_combinations, desc=f"Fold {i+1} grid search")
            )
            fold_results = [r for r in fold_results if r is not None]

        results.extend(fold_results)

    # Convert to DataFrame and sort by ignition_score (primary) and test_expectancy (secondary)
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values(['test_ignition_score', 'test_expectancy'], ascending=[False, False])

    return results_df


def apply_barriers_to_trades_fast(
    grouped_trades: dict,
    params,
    barrier_type: str
) -> pd.DataFrame:
    """Apply barriers using pre-grouped trades and vectorized methods."""
    outcomes = []

    for trade_id, trade_df in grouped_trades.items():
        try:
            if barrier_type == 'static':
                outcome, days, return_pct = TripleBarrierLabeler.apply_static_barriers(
                    trade_df, params
                )
            elif barrier_type == 'dynamic':
                outcome, days, return_pct = TripleBarrierLabeler.apply_dynamic_barriers(
                    trade_df, params
                )
            else:  # hybrid - use vectorized version
                outcome, days, return_pct, _ = TripleBarrierLabeler.apply_hybrid_barriers_vectorized(
                    trade_df, params
                )

            outcomes.append({
                'trade_id': trade_id,
                'barrier_outcome': outcome,
                'days_to_outcome': days,
                'return_at_outcome': return_pct
            })
        except (ValueError, KeyError):
            continue

    return pd.DataFrame(outcomes)


def main():
    parser = argparse.ArgumentParser(description='Optimize triple barrier parameters')
    parser.add_argument('--data', default='data/ml/d2_fixed_horizon_90d.parquet',
                        help='Path to rehydrated d2 dataset')
    parser.add_argument('--type', choices=['static', 'dynamic', 'hybrid'], default='hybrid',
                        help='Barrier type (default: hybrid)')
    parser.add_argument('--output', default='barrier_optimization_results.csv',
                        help='Output CSV path')
    parser.add_argument('--train-years', type=int, default=3,
                        help='Number of training years per fold')
    args = parser.parse_args()

    print("=" * 70)
    print(" TRIPLE BARRIER GRID SEARCH")
    print("=" * 70)
    print(f"Data: {args.data}")
    print(f"Barrier type: {args.type}")
    print(f"Train window: {args.train_years} years")

    results = walk_forward_grid_search(
        d2_path=args.data,
        barrier_type=args.type,
        train_years=args.train_years
    )

    # Save results
    results.to_csv(args.output, index=False)
    print(f"\nSaved: {args.output}")

    # Display top 10 parameter sets
    print("\n" + "=" * 70)
    print(" TOP 10 PARAMETER SETS (by ignition score, then expectancy)")
    print("=" * 70)

    # Format for display
    display_cols = results.columns.tolist()
    print(results.head(10).to_string(index=False))

    # Also show top 10 by expectancy for comparison
    print("\n" + "=" * 70)
    print(" TOP 10 BY EXPECTANCY (for comparison)")
    print("=" * 70)
    results_by_exp = results.sort_values('test_expectancy', ascending=False)
    print(results_by_exp.head(10).to_string(index=False))

    # Display best overall params (avg across folds)
    if args.type == 'static':
        group_cols = ['upper_pct', 'lower_pct', 'time_days']
    elif args.type == 'dynamic':
        group_cols = ['upper_atr_mult', 'lower_atr_mult', 'time_days']
    else:  # hybrid
        group_cols = ['k_sl', 'k_tp', 'min_tp', 'max_time']

    avg_results = results.groupby(group_cols).agg({
        'test_expectancy': 'mean',
        'test_risk_adj_return': 'mean',
        'test_win_rate': 'mean',
        'test_time_rate': 'mean',
        'test_avg_days': 'mean',
        'test_risk_reward': 'mean',
        'test_ignition_score': 'mean',
        'test_avg_win': 'mean',
        'test_avg_time': 'mean'
    }).reset_index()

    avg_results = avg_results.sort_values('test_ignition_score', ascending=False)

    print("\n" + "=" * 70)
    print(" BEST PARAMETERS (averaged across all folds, ranked by ignition score)")
    print("=" * 70)

    best = avg_results.iloc[0]

    if args.type == 'static':
        print(f"  TP={best['upper_pct']:.0%}, SL=-{best['lower_pct']:.0%}, Time={best['time_days']:.0f}d")
    elif args.type == 'dynamic':
        print(f"  TP={best['upper_atr_mult']:.1f}×ATR, SL={best['lower_atr_mult']:.1f}×ATR, Time={best['time_days']:.0f}d")
    else:  # hybrid
        print(f"  Stop: {best['k_sl']:.2f}×ATR")
        print(f"  Target: MAX({best['min_tp']:.0%}, {best['k_tp']:.1f}×ATR)")
        print(f"  Max Time: {best['max_time']:.0f}d (dynamic: [20, {best['max_time']:.0f}] based on distance/speed)")

    print(f"\n  Avg Test Ignition Score: {best['test_ignition_score']:.4f} ** (TP vs Time separation)")
    print(f"  Avg Test Expectancy: {best['test_expectancy']:.4f}")
    print(f"  Avg Risk-Adj Return: {best['test_risk_adj_return']:.4f}")
    print(f"  Avg Win Rate (TP): {best['test_win_rate']:.1%}")
    print(f"  Avg Time Rate (drifters): {best['test_time_rate']:.1%}")
    print(f"  Avg Days to Outcome: {best['test_avg_days']:.1f}")
    print(f"  Avg Risk/Reward: {best['test_risk_reward']:.2f}")
    print(f"  Avg TP Return: {best['test_avg_win']:.2%}")
    print(f"  Avg Time Return: {best['test_avg_time']:.2%}")

    # Show all parameter set averages
    print("\n" + "=" * 70)
    print(" ALL PARAMETER SETS (averaged across folds)")
    print("=" * 70)
    print(avg_results.to_string(index=False))


if __name__ == '__main__':
    main()
