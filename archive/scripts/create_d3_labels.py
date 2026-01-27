"""
Create D3 Dataset with Triple Barrier Labels

Uses best parameters from barrier optimization to generate meta-labels
for M01_3bar model training.

Usage:
    # Static barriers (specify percentages)
    python scripts/create_d3_labels.py --type static --upper-pct 0.20 --lower-pct 0.07 --time-days 30
    
    # Dynamic barriers (specify ATR multipliers)
    python scripts/create_d3_labels.py --type dynamic --upper-atr 2.5 --lower-atr 1.0 --time-days 30
    
    # Hybrid barriers (recommended - specify multipliers)
    python scripts/create_d3_labels.py --type hybrid --k-sl 1.0 --k-tp 3.0 --min-tp 0.20 --max-time 60 --min-time 20
"""

import argparse
import pandas as pd
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent))

from src.triple_barrier_labeler import (
    TripleBarrierLabeler,
    StaticBarrierParams,
    DynamicBarrierParams,
    HybridBarrierParams,
    compute_expectancy
)


def create_d3_dataset(
    d2_path: str,
    barrier_type: str,
    params,
    output_path: str,
    n_jobs: int = -1
):
    """
    Generate D3 dataset with triple barrier labels.

    Args:
        d2_path: Path to d2_fixed_horizon_*.parquet
        barrier_type: 'static', 'dynamic', or 'hybrid'
        params: Best parameters from optimization
        output_path: Where to save D3
        n_jobs: Parallel workers (-1 = all cores)
    """
    print("=" * 70)
    print(" CREATE D3 DATASET - TRIPLE BARRIER LABELS")
    print("=" * 70)
    print(f"Input: {d2_path}")
    print(f"Barrier: {params}")
    print(f"Workers: {n_jobs}")

    # Load data
    d2 = pd.read_parquet(d2_path)
    print(f"\nLoaded: {len(d2):,} rows, {d2['trade_id'].nunique()} trades")

    # Validate required columns
    if 'Close' not in d2.columns:
        raise ValueError("D2 is missing 'Close' column")
    if barrier_type in ('dynamic', 'hybrid') and 'ATR' not in d2.columns:
        raise ValueError(f"D2 is missing 'ATR' column required for {barrier_type} barriers")

    # Apply barriers using labeler
    print(f"\nApplying {barrier_type} barriers...")
    d3 = TripleBarrierLabeler.label_dataset(
        d2_rehydrated=d2,
        params=params,
        binary_labels=True,  # y_meta ∈ {0, 1}
        n_jobs=n_jobs,
        use_vectorized=True
    )

    # Summary statistics
    print(f"\n{'='*70}")
    print(" LABELING COMPLETE")
    print("=" * 70)
    print(f"Total trades: {len(d3):,}")
    print(f"  y_meta=1 (TP): {(d3['y_meta'] == 1).sum()} ({(d3['y_meta'] == 1).mean():.1%})")
    print(f"  y_meta=0 (SL/Time): {(d3['y_meta'] == 0).sum()} ({(d3['y_meta'] == 0).mean():.1%})")

    # Outcome breakdown
    print(f"\nOutcome distribution:")
    outcome_counts = d3['barrier_outcome'].value_counts()
    for outcome, count in outcome_counts.items():
        pct = count / len(d3) * 100
        print(f"  {outcome}: {count:,} ({pct:.1f}%)")

    # Compute expectancy metrics
    metrics = compute_expectancy(d3)
    print(f"\nExpectancy Metrics:")
    print(f"  Expectancy: {metrics['expectancy']:.2%}")
    print(f"  Risk-Adjusted Return (ann.): {metrics['risk_adjusted_return']:.2%}")
    print(f"  Win Rate: {metrics['win_rate']:.1%}")
    print(f"  Avg Win: {metrics['avg_win']:.2%}")
    print(f"  Avg Loss: {metrics['avg_loss']:.2%}")
    print(f"  Risk/Reward: {metrics['risk_reward']:.2f}")
    print(f"  Avg Days: {metrics['avg_days']:.1f}")

    # Hybrid barrier statistics
    if barrier_type == 'hybrid' and 'barrier_target_pct' in d3.columns:
        print(f"\nHybrid Barrier Distribution:")
        print(f"  Stop Loss (mean): -{d3['barrier_stop_pct'].mean():.2%}")
        print(f"  Stop Loss (range): -{d3['barrier_stop_pct'].min():.2%} to -{d3['barrier_stop_pct'].max():.2%}")
        print(f"  Target (mean): +{d3['barrier_target_pct'].mean():.2%}")
        print(f"  Target (range): +{d3['barrier_target_pct'].min():.2%} to +{d3['barrier_target_pct'].max():.2%}")
        print(f"  Time Barrier (mean): {d3['barrier_time_days'].mean():.1f} days")

    # Save D3
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    d3.to_parquet(output_path, index=False)
    size_mb = Path(output_path).stat().st_size / 1e6
    print(f"\nSaved: {output_path}")
    print(f"  Rows: {len(d3):,}")
    print(f"  Columns: {len(d3.columns)}")
    print(f"  Size: {size_mb:.1f} MB")

    # Validation: compare to original labels if available
    if 'label' in d3.columns:
        agreement = (d3['y_meta'] == d3['label']).mean()
        print(f"\nLabel agreement with original d1:")
        print(f"  y_meta == label: {agreement:.1%}")
        print(f"  (Values <100% expected - different labeling logic)")

    return d3


def main():
    parser = argparse.ArgumentParser(
        description='Create D3 with triple barrier labels',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Static barriers
  python scripts/create_d3_labels.py --type static --upper-pct 0.20 --lower-pct 0.07 --time-days 30
  
  # Dynamic ATR-based barriers
  python scripts/create_d3_labels.py --type dynamic --upper-atr 2.5 --lower-atr 1.0 --time-days 30
  
  # Hybrid barriers (recommended)
  python scripts/create_d3_labels.py --type hybrid --k-sl 1.0 --k-tp 3.0 --min-tp 0.20
        """
    )
    
    # Input/output
    parser.add_argument('--data', default='data/ml/d2_fixed_horizon_90d.parquet',
                        help='Path to rehydrated D2 (default: data/ml/d2_fixed_horizon_90d.parquet)')
    parser.add_argument('--output', default='data/ml/d3_triple_barrier_labels.parquet',
                        help='Output path for D3 (default: data/ml/d3_triple_barrier_labels.parquet)')
    parser.add_argument('--type', choices=['static', 'dynamic', 'hybrid'], default='hybrid',
                        help='Barrier type (default: hybrid)')
    parser.add_argument('--jobs', type=int, default=-1,
                        help='Parallel workers, -1 = all cores (default: -1)')

    # Static barrier params
    parser.add_argument('--upper-pct', type=float, default=0.20,
                        help='Static: profit target %% (default: 0.20 = 20%%)')
    parser.add_argument('--lower-pct', type=float, default=0.07,
                        help='Static: stop loss %% (default: 0.07 = 7%%)')
    parser.add_argument('--time-days', type=int, default=30,
                        help='Static/Dynamic: time barrier days (default: 30)')

    # Dynamic barrier params
    parser.add_argument('--upper-atr', type=float, default=2.5,
                        help='Dynamic: profit target ATR multiplier (default: 2.5)')
    parser.add_argument('--lower-atr', type=float, default=1.0,
                        help='Dynamic: stop loss ATR multiplier (default: 1.0)')

    # Hybrid barrier params
    parser.add_argument('--k-sl', type=float, default=1.0,
                        help='Hybrid: stop loss ATR multiplier (default: 1.0)')
    parser.add_argument('--k-tp', type=float, default=3.0,
                        help='Hybrid: target ATR multiplier for MAX logic (default: 3.0)')
    parser.add_argument('--min-tp', type=float, default=0.20,
                        help='Hybrid: minimum profit target floor (default: 0.20 = 20%%)')
    parser.add_argument('--max-time', type=int, default=60,
                        help='Hybrid: maximum time barrier (default: 60 days)')
    parser.add_argument('--min-time', type=int, default=20,
                        help='Hybrid: minimum time barrier (default: 20 days)')

    args = parser.parse_args()

    # Create params object based on type
    if args.type == 'static':
        params = StaticBarrierParams(
            upper_pct=args.upper_pct,
            lower_pct=args.lower_pct,
            time_days=args.time_days
        )
    elif args.type == 'dynamic':
        params = DynamicBarrierParams(
            upper_atr_mult=args.upper_atr,
            lower_atr_mult=args.lower_atr,
            time_days=args.time_days
        )
    else:  # hybrid
        params = HybridBarrierParams(
            k_sl=args.k_sl,
            k_tp=args.k_tp,
            min_tp=args.min_tp,
            max_time=args.max_time,
            min_time=args.min_time
        )

    # Create D3
    create_d3_dataset(
        d2_path=args.data,
        barrier_type=args.type,
        params=params,
        output_path=args.output,
        n_jobs=args.jobs
    )


if __name__ == '__main__':
    main()
