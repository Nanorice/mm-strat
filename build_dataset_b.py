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

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_summary_statistics(simulator: TradeSimulator, output_path: str = None):
    """
    Prints and optionally saves summary statistics.
    
    Args:
        simulator: TradeSimulator instance
        output_path: Optional path to save JSON report
    """
    stats = simulator.get_summary_statistics()
    
    if not stats:
        print("\n❌ No trades generated - cannot compute statistics")
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
        help='End date for simulation (YYYY-MM-DD)'
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
    
    args = parser.parse_args()
    
    print("=" * 80)
    print(" DATASET B BUILDER - ML Training Data Generation")
    print("=" * 80)
    print(f"\n📅 Simulation Period: {args.start} to {args.end}")
    print(f"🎯 Success Threshold: {args.threshold}%")
    print(f"💾 Output: {args.output}")
    if args.label_rule:
        print(f"🏷️  Custom Label Rule: {args.label_rule}")
    
    # Create output directory if needed
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Initialize components
    logger.info("Initializing components...")
    data_repo = DataRepository()
    benchmark_data = data_repo.get_benchmark_data()
    
    if benchmark_data is None:
        logger.error("Failed to load benchmark data!")
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
    
    # Initialize simulator
    logger.info("Initializing trade simulator...")
    simulator = TradeSimulator(
        data_repo=data_repo,
        strategy=strategy,
        feature_engine=feature_engine,
        start_date=args.start,
        end_date=args.end,
        config=trading_config
    )
    
    # Run simulation
    print("\n🚀 Starting simulation...")
    print("   (This may take several minutes for large date ranges)\n")
    
    dataset_b = simulator.run_simulation()
    
    if dataset_b.empty:
        print("\n❌ No trades generated!")
        return
    
    # Print summary statistics
    print_summary_statistics(
        simulator,
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
