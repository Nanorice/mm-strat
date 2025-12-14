"""
Build Dataset B - Historical Trade Simulation for ML Training
Generates labeled trade data for meta-labeling model training.
"""

import pandas as pd
import argparse
import sys
from pathlib import Path
from datetime import datetime
import logging
import json

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.data_engine import DataRepository
from src.strategy import SEPAStrategy
from src.features import FeatureEngineer
from src.database import DatabaseManager
from src.trade_simulator import TradeSimulator
from src.trading_config import TradingConfig

# Setup logging - reduced verbosity for long runs
logging.basicConfig(
    level=logging.WARNING,  # Changed from INFO to WARNING for less noise
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Set specific loggers to WARNING to reduce output
logging.getLogger('src.data_engine').setLevel(logging.WARNING)
logging.getLogger('src.features').setLevel(logging.WARNING)
logging.getLogger('src.strategy').setLevel(logging.WARNING)
logging.getLogger('src.trade_simulator').setLevel(logging.INFO)  # Keep simulator messages


def print_summary_statistics(dataset_b: pd.DataFrame, output_path: str = None):
    """
    Prints and optionally saves summary statistics.

    Args:
        dataset_b: DataFrame containing trade results
        output_path: Optional path to save JSON report
    """
    if dataset_b.empty:
        print("\n❌ No trades generated - cannot compute statistics")
        return

    # Compute statistics from dataset_b directly
    wins = dataset_b[dataset_b['label'] == 1]
    losses = dataset_b[dataset_b['label'] == 0]

    stats = {
        'total_trades': len(dataset_b),
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'win_rate': len(wins) / len(dataset_b) if len(dataset_b) > 0 else 0,
        'avg_return': dataset_b['return_pct'].mean(),
        'avg_win': wins['return_pct'].mean() if not wins.empty else 0,
        'avg_loss': losses['return_pct'].mean() if not losses.empty else 0,
        'avg_days_held': dataset_b['days_held'].mean(),
        'max_win': dataset_b['return_pct'].max(),
        'max_loss': dataset_b['return_pct'].min(),
        'label_distribution': dataset_b['label'].value_counts().to_dict(),
        'exit_reasons': dataset_b['exit_reason'].value_counts().to_dict()
    }

    if not stats:
        print("\n❌ Failed to compute statistics")
        return
    
    print("\n" + "=" * 80)
    print(" SIMULATION SUMMARY")
    print("=" * 80)
    
    print(f"\n📊 Trade Statistics:")
    print(f"   Total Trades: {stats['total_trades']}")
    print(f"   Winning Trades: {stats['winning_trades']} ({stats['win_rate']*100:.1f}%)")
    print(f"   Losing Trades: {stats['losing_trades']} ({(1-stats['win_rate'])*100:.1f}%)")
    
    print(f"\n💰 Returns:")
    print(f"   Average Return: {stats['avg_return']:.2f}%")
    print(f"   Average Win: {stats['avg_win']:.2f}%")
    print(f"   Average Loss: {stats['avg_loss']:.2f}%")
    print(f"   Max Win: {stats['max_win']:.2f}%")
    print(f"   Max Loss: {stats['max_loss']:.2f}%")
    
    print(f"\n⏱️  Duration:")
    print(f"   Average Days Held: {stats['avg_days_held']:.1f} days")
    
    print(f"\n🏷️  Label Distribution:")
    for label, count in stats['label_distribution'].items():
        label_name = "Success" if label == 1 else "Failure"
        pct = (count / stats['total_trades']) * 100
        print(f"   {label_name} ({label}): {count} trades ({pct:.1f}%)")
    
    print(f"\n🚪 Exit Reasons:")
    for reason, count in stats['exit_reasons'].items():
        pct = (count / stats['total_trades']) * 100
        print(f"   {reason}: {count} trades ({pct:.1f}%)")
    
    # Save to JSON if path provided
    if output_path:
        with open(output_path, 'w') as f:
            json.dump(stats, f, indent=2, default=str)
        print(f"\n📝 Statistics saved to: {output_path}")


def main():
    """Main entry point for Dataset B builder."""
    parser = argparse.ArgumentParser(
        description="Build Dataset B for ML meta-labeling training"
    )
    
    parser.add_argument(
        '--start',
        type=str,
        required=True,
        help='Start date for simulation (YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--end',
        type=str,
        required=True,
        help='End date for simulation (YYYY-MM-DD) - stops new entries at this date'
    )

    parser.add_argument(
        '--outcome-end',
        type=str,
        default=None,
        help='Extended end date for natural trade exits (YYYY-MM-DD). If not provided, uses --end + 90 days'
    )

    parser.add_argument(
        '--threshold',
        type=float,
        default=15.0,
        help='Return threshold for success label (default: 15.0%%)'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default='data/ml/dataset_b.parquet',
        help='Output path for Dataset B (default: data/ml/dataset_b.parquet)'
    )
    
    parser.add_argument(
        '--format',
        type=str,
        choices=['parquet', 'csv', 'both'],
        default='parquet',
        help='Output format (default: parquet)'
    )
    
    parser.add_argument(
        '--save-to-db',
        action='store_true',
        help='Save trades to database ml_training_trades table'
    )
    
    parser.add_argument(
        '--clear-existing',
        action='store_true',
        help='Clear existing ML training data before saving'
    )
    
    parser.add_argument(
        '--label-rule',
        type=str,
        default=None,
        help='Custom labeling rule (e.g., "trade.return_pct >= 20 and trade.days_held <= 30")'
    )

    parser.add_argument(
        '--slow',
        action='store_true',
        help='Use event-driven TradeSimulator (slower but useful for debugging). Default is fast vectorized simulator.'
    )

    parser.add_argument(
        '--n-jobs',
        type=int,
        default=1,
        help='Number of parallel workers (1=sequential, -1=all CPUs, default: 1). Only used in fast mode (default).'
    )

    args = parser.parse_args()
    
    # Calculate outcome_end if not provided
    if args.outcome_end is None:
        from datetime import timedelta
        end_date = pd.to_datetime(args.end)
        outcome_end = (end_date + timedelta(days=90)).strftime('%Y-%m-%d')
    else:
        outcome_end = args.outcome_end

    print("=" * 80)
    print(" DATASET B BUILDER - ML Training Data Generation")
    print("=" * 80)
    print(f"\n📅 Entry Period: {args.start} to {args.end}")
    print(f"📅 Outcome Window: {args.start} to {outcome_end} (exits allowed until here)")
    print(f"🎯 Success Threshold: {args.threshold}%")
    print(f"💾 Output: {args.output}")
    if args.label_rule:
        print(f"🏷️  Custom Label Rule: {args.label_rule}")
    
    # Show simulator type
    if args.slow:
        print(f"\n⚠️  Mode: Event-Driven Simulator (SLOW - for debugging only)")
        print(f"   Tip: Remove --slow flag for 10-20x speedup")
    else:
        print(f"\n⚡ Mode: Vectorized Fast Simulator (10-20x faster)")
        if args.n_jobs != 1:
            n_jobs_display = "ALL CPUs" if args.n_jobs == -1 else f"{args.n_jobs} workers"
            print(f"   Parallel Processing: {n_jobs_display}")
    
    # Create output directory if needed
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Initialize components
    logger.info("Initializing components...")
    data_repo = DataRepository()

    # Load benchmark data with required end date validation
    # Convert outcome_end to pd.Timestamp for cache validation
    required_end_date = pd.to_datetime(args.end)
    benchmark_data = data_repo.get_benchmark_data(required_end_date=required_end_date)

    if benchmark_data is None:
        logger.error("Failed to load benchmark data!")
        logger.error(f"Make sure SPY data is cached and covers up to {required_end_date}")
        logger.error("Run: python build_dataset_a.py --update-cache to refresh price data")
        return
    
    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    strategy = SEPAStrategy(benchmark_data=benchmark_data)
    
    # Create custom labeling function if provided
    labeling_function = None
    if args.label_rule:
        try:
            # Evaluate user expression as lambda
            labeling_function = eval(f"lambda trade: 1 if ({args.label_rule}) else 0")
            logger.info(f"Using custom labeling rule: {args.label_rule}")
        except Exception as e:
            logger.error(f"Invalid label rule: {e}")
            print(f"\n❌ Error: Invalid label rule syntax")
            return
    
    # Create trading configuration
    trading_config = TradingConfig(
        success_threshold_pct=args.threshold,
        exit_on_trend_break=True,
        exit_on_stop_loss=False,
        allow_reentry=True,
        reentry_cooldown_days=0,
        labeling_function=labeling_function  # Pass custom labeler
    )
    
    print(f"\n⚙️  Trading Configuration:")
    print(f"   {trading_config}")

    # Initialize simulator with outcome window
    logger.info("Initializing trade simulator...")

    if args.slow:
        # Event-driven simulator (for debugging/validation)
        simulator = TradeSimulator(
            data_repo=data_repo,
            strategy=strategy,
            feature_engine=feature_engine,
            start_date=args.start,
            end_date=args.end,
            outcome_end=outcome_end,  # Extended window for natural exits
            config=trading_config
        )

        # Run simulation
        print("\n🚀 Starting event-driven simulation...")
        print("   (This may take several minutes for large date ranges)\n")
        dataset_b = simulator.run_simulation()
    else:
        # Fast vectorized simulator (DEFAULT)
        from src.trade_simulator_fast import FastTradeSimulator
        
        simulator = FastTradeSimulator(
            data_repo=data_repo,
            strategy=strategy,
            feature_engine=feature_engine,
            start_date=args.start,
            end_date=args.end,
            outcome_end=outcome_end,  # Extended window for natural exits
            config=trading_config
        )

        # Run simulation with parallelization
        print("\n🚀 Starting vectorized simulation...\n")
        dataset_b = simulator.run_simulation(show_progress=True, n_jobs=args.n_jobs)
    
    if dataset_b.empty:
        print("\n❌ No trades generated!")
        return

    # Print summary statistics
    print_summary_statistics(
        dataset_b,
        output_path=output_path.parent / 'simulation_stats.json'
    )
    
    # Save to file
    print("\n💾 Saving Dataset B...")
    
    if args.format in ['parquet', 'both']:
        parquet_path = output_path if output_path.suffix == '.parquet' else output_path.with_suffix('.parquet')
        dataset_b.to_parquet(parquet_path, index=False)
        print(f"   ✅ Saved to: {parquet_path}")
    
    if args.format in ['csv', 'both']:
        csv_path = output_path.with_suffix('.csv') if output_path.suffix == '.parquet' else output_path
        dataset_b.to_csv(csv_path, index=False)
        print(f"   ✅ Saved to: {csv_path}")
    
    # Save to database if requested
    if args.save_to_db:
        print("\n💾 Saving to database...")
        db = DatabaseManager()
        
        if args.clear_existing:
            print("   Clearing existing ML training data...")
            db.clear_ml_training_data()
        
        # Log each trade
        for _, row in dataset_b.iterrows():
            db.log_ml_trade(row.to_dict())
        
        print(f"   ✅ Saved {len(dataset_b)} trades to ml_training_trades table")
    
    print("\n" + "=" * 80)
    print(f"✅ Dataset B generation complete!")
    print(f"   {len(dataset_b)} trades | {dataset_b['label'].sum()} wins | {len(dataset_b) - dataset_b['label'].sum()} losses")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Simulation interrupted by user.")
    except Exception as e:
        logger.error(f"Simulation failed: {e}", exc_info=True)
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)
