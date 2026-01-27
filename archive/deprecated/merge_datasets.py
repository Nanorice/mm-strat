"""
Merge Datasets - CLI Tool for Merging Dataset A and Dataset B

Combines Dataset A (daily feature snapshots) and Dataset B (trade labels)
using snapshot join logic for ML model training preparation.

Usage:
    python merge_datasets.py \
      --dataset-a data/ml/dataset_a_with_fundamentals.parquet \
      --dataset-b data/ml/dataset_b.parquet \
      --output data/ml/merged_dataset.parquet
"""

import pandas as pd
import argparse
import sys
import json
from pathlib import Path
import logging

# Add src to path
sys.path.append(str(Path(__file__).parent))

from src.dataset_merger import DatasetMerger

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_merge_summary(stats: dict):
    """
    Print formatted merge summary statistics.
    
    Args:
        stats: Statistics dictionary from merger.get_merge_statistics()
    """
    print("\n" + "=" * 80)
    print(" DATASET MERGE SUMMARY")
    print("=" * 80)
    
    # Input datasets
    print(f"\n📊 Input Datasets:")
    print(f"   Dataset A: {stats['dataset_a_rows']:,} rows × {stats['feature_count']} features")
    print(f"   Dataset B: {stats['dataset_b_trades']:,} trades")
    
    # Merge results
    print(f"\n🔗 Merge Results:")
    print(f"   Matched Trades: {stats['merged_rows']:,} / {stats['dataset_b_trades']:,} ({stats['match_rate_pct']:.1f}%)")
    print(f"   Missing Snapshots: {stats['missing_snapshots']}")
    print(f"   Total Columns: {stats['total_columns']}")
    
    # Label distribution
    if 'label_distribution' in stats:
        print(f"\n🏷️  Label Distribution:")
        for label, count in sorted(stats['label_distribution'].items()):
            label_name = "Success" if label == 1 else "Failure"
            pct = (count / stats['merged_rows']) * 100 if stats['merged_rows'] > 0 else 0
            print(f"   {label_name} ({label}): {count:,} trades ({pct:.1f}%)")
    
    # Missing values
    if 'missing_values_pct' in stats:
        print(f"\n⚠️  Missing Values: {stats['missing_values_pct']:.2f}%")
    
    # Feature summary
    if 'feature_columns' in stats:
        feature_cols = stats['feature_columns']
        
        # Categorize features
        technical = [c for c in feature_cols if c.startswith(('SMA', 'ATR', 'RS', 'Vol', 'High', 'Low', 'Breakout', 'Price_vs', 'nATR', 'VCP', 'Consolidation', 'Dry_Up'))]
        fundamental = [c for c in feature_cols if c in ['revenue', 'eps', 'netIncome', 'totalAssets', 'totalDebt', 'revenue_growth_yoy', 'eps_growth_yoy', 'debt_to_equity', 'current_ratio', 'gross_margin', 'operating_margin', 'roe', 'roa', 'pe_ratio', 'pb_ratio']]
        alphas = [c for c in feature_cols if c.startswith('alpha')]
        
        print(f"\n📋 Feature Summary:")
        if technical:
            print(f"   Technical: {len(technical)} features")
        if fundamental:
            print(f"   Fundamental: {len(fundamental)} features")
        if alphas:
            print(f"   Alphas: {len(alphas)} features")
        print(f"   Total: {len(feature_cols)} features")
    
    print("\n" + "=" * 80)
    print("✅ Merge complete!")
    print("=" * 80 + "\n")


def export_report(stats: dict, output_path: str):
    """
    Export merge statistics to JSON file.
    
    Args:
        stats: Statistics dictionary
        output_path: Path to save JSON report
    """
    # Convert to JSON-serializable format
    report = {k: v for k, v in stats.items() if k != 'feature_columns'}
    
    # Add feature column names as list
    if 'feature_columns' in stats:
        report['feature_columns'] = stats['feature_columns']
    
    # Save to file
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"📄 Merge report exported to: {output_path}")


def main():
    """Main entry point for merge_datasets CLI."""
    parser = argparse.ArgumentParser(
        description="Merge Dataset A (features) and Dataset B (labels) for ML training",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic merge
  python merge_datasets.py \\
    --dataset-a data/ml/dataset_a_with_fundamentals.parquet \\
    --dataset-b data/ml/dataset_b.parquet \\
    --output data/ml/merged_dataset.parquet

  # With validation report
  python merge_datasets.py \\
    --dataset-a data/ml/dataset_a_with_fundamentals.parquet \\
    --dataset-b data/ml/dataset_b.parquet \\
    --output data/ml/merged_dataset.parquet \\
    --export-report data/ml/merge_report.json \\
    --format both
        """
    )
    
    parser.add_argument(
        '--dataset-a',
        type=str,
        default='data/ml/dataset_a.parquet',
        help='Path to Dataset A (feature store) - Parquet or CSV'
    )
    
    parser.add_argument(
        '--dataset-b',
        type=str,
        default='data/ml/dataset_b.parquet',
        help='Path to Dataset B (trade labels) - Parquet or CSV'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default='data/ml/merged_dataset.parquet',
        help='Output path for merged dataset'
    )
    
    parser.add_argument(
        '--format',
        type=str,
        choices=['parquet', 'csv', 'both'],
        default='parquet',
        help='Output format (default: parquet)'
    )
    
    parser.add_argument(
        '--export-report',
        type=str,
        default=None,
        help='Optional: Export merge statistics to JSON file'
    )
    
    parser.add_argument(
        '--no-validate',
        action='store_true',
        help='Skip temporal validation checks'
    )
    
    args = parser.parse_args()
    
    # Print header
    print("=" * 80)
    print(" DATASET MERGER - Combine Features + Labels")
    print("=" * 80)
    print(f"\n📂 Dataset A: {args.dataset_a}")
    print(f"📂 Dataset B: {args.dataset_b}")
    print(f"💾 Output: {args.output}")
    print(f"📄 Format: {args.format}")
    
    # Initialize merger
    logger.info("\n🚀 Initializing DatasetMerger...")
    merger = DatasetMerger(
        dataset_a_path=args.dataset_a,
        dataset_b_path=args.dataset_b,
        validate_temporal=not args.no_validate
    )
    
    try:
        # Step 1: Load datasets
        merger.load_datasets()
        
        # Step 2: Validate compatibility
        if not args.no_validate:
            merger.validate_compatibility()
        else:
            logger.info("\n⚠️  Skipping validation (--no-validate flag)")
        
        # Step 3: Merge
        merged_df = merger.merge()
        
        # Step 4: Export
        merger.export(args.output, format=args.format)
        
        # Step 5: Print summary
        stats = merger.get_merge_statistics()
        print_merge_summary(stats)
        
        # Step 6: Export report if requested
        if args.export_report:
            export_report(stats, args.export_report)
        
        print("\n✅ SUCCESS! Merged dataset ready for model training.")
        
    except FileNotFoundError as e:
        logger.error(f"\n❌ File not found: {e}")
        print(f"\n❌ ERROR: {e}")
        print("\nPlease check that both dataset files exist.")
        sys.exit(1)
    
    except ValueError as e:
        logger.error(f"\n❌ Validation error: {e}")
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)
    
    except Exception as e:
        logger.error(f"\n❌ Unexpected error: {e}", exc_info=True)
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Merge interrupted by user.")
        sys.exit(1)
