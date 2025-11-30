"""
Prepare Training Dataset - Final Pre-Training Checklist

This script performs comprehensive preparation and validation of the full training dataset:
1. Validates time range coverage for Dataset A and Dataset B
2. Checks data availability and quality
3. Merges datasets
4. Performs sanity checks and generates reports

Usage:
    python prepare_training_dataset.py --start 2020-01-01 --end 2025-11-28
"""

import pandas as pd
import numpy as np
import argparse
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
import logging
from typing import Dict, Tuple, List

# Add src to path
sys.path.append(str(Path(__file__).parent))

from src.dataset_merger import DatasetMerger

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DatasetPreparer:
    """Comprehensive dataset preparation and validation."""
    
    def __init__(self, start_date: str, end_date: str):
        self.start_date = pd.to_datetime(start_date)
        self.end_date = pd.to_datetime(end_date)
        self.dataset_a = None
        self.dataset_b = None
        self.merged_dataset = None
        self.validation_report = {}
        
    def check_dataset_a_coverage(self, path: str) -> Dict:
        """
        Check Dataset A time range and data quality.
        
        Args:
            path: Path to Dataset A file
            
        Returns:
            Dictionary with coverage statistics
        """
        logger.info(f"Checking Dataset A coverage: {path}")
        
        if not Path(path).exists():
            return {
                'exists': False,
                'error': f'File not found: {path}'
            }
        
        # Load dataset
        if path.endswith('.parquet'):
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path, parse_dates=['date'])
        
        self.dataset_a = df
        
        # Convert date column to datetime
        df['date'] = pd.to_datetime(df['date'])
        
        # Calculate statistics
        min_date = df['date'].min()
        max_date = df['date'].max()
        total_rows = len(df)
        total_tickers = df['ticker'].nunique()
        total_dates = df['date'].nunique()
        
        # Check if requested range is covered
        range_start_covered = min_date <= self.start_date
        range_end_covered = max_date >= self.end_date
        
        # Calculate missing dates in requested range
        requested_dates = pd.bdate_range(self.start_date, self.end_date)
        actual_dates = df['date'].unique()
        missing_dates = set(requested_dates) - set(actual_dates)
        
        # Calculate missing values percentage
        missing_pct = (df.isnull().sum().sum() / df.size) * 100
        
        # Feature breakdown
        all_cols = df.columns.tolist()
        feature_cols = [c for c in all_cols if c not in ['date', 'ticker', 'Close', 'Volume']]
        
        return {
            'exists': True,
            'path': path,
            'min_date': min_date,
            'max_date': max_date,
            'total_rows': total_rows,
            'total_tickers': total_tickers,
            'total_dates': total_dates,
            'total_features': len(feature_cols),
            'range_start_covered': range_start_covered,
            'range_end_covered': range_end_covered,
            'missing_dates_count': len(missing_dates),
            'missing_values_pct': missing_pct,
            'coverage_pct': ((len(requested_dates) - len(missing_dates)) / len(requested_dates)) * 100,
            'feature_columns': feature_cols
        }
    
    def check_dataset_b_coverage(self, path: str) -> Dict:
        """
        Check Dataset B time range and trade distribution.
        
        Args:
            path: Path to Dataset B file
            
        Returns:
            Dictionary with coverage statistics
        """
        logger.info(f"Checking Dataset B coverage: {path}")
        
        if not Path(path).exists():
            return {
                'exists': False,
                'error': f'File not found: {path}'
            }
        
        # Load dataset
        if path.endswith('.parquet'):
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path, parse_dates=['entry_date', 'exit_date'])
        
        self.dataset_b = df
        
        # Convert date columns
        df['entry_date'] = pd.to_datetime(df['entry_date'])
        df['exit_date'] = pd.to_datetime(df['exit_date'])
        
        # Calculate statistics
        min_entry_date = df['entry_date'].min()
        max_entry_date = df['entry_date'].max()
        min_exit_date = df['exit_date'].min()
        max_exit_date = df['exit_date'].max()
        
        total_trades = len(df)
        total_tickers = df['ticker'].nunique()
        
        # Check if requested range is covered
        range_start_covered = min_entry_date <= self.start_date
        range_end_covered = max_exit_date >= self.end_date
        
        # Label distribution
        if 'label' in df.columns:
            label_dist = df['label'].value_counts().to_dict()
            win_rate = df['label'].mean() if total_trades > 0 else 0
        else:
            label_dist = {}
            win_rate = 0
        
        # Trade metrics
        avg_return = df['return_pct'].mean() if 'return_pct' in df.columns else 0
        avg_days_held = df['days_held'].mean() if 'days_held' in df.columns else 0
        
        # Trades per year
        date_range_years = (max_entry_date - min_entry_date).days / 365.25
        trades_per_year = total_trades / date_range_years if date_range_years > 0 else 0
        
        return {
            'exists': True,
            'path': path,
            'min_entry_date': min_entry_date,
            'max_entry_date': max_entry_date,
            'min_exit_date': min_exit_date,
            'max_exit_date': max_exit_date,
            'total_trades': total_trades,
            'total_tickers': total_tickers,
            'label_distribution': label_dist,
            'win_rate': win_rate,
            'avg_return_pct': avg_return,
            'avg_days_held': avg_days_held,
            'trades_per_year': trades_per_year,
            'range_start_covered': range_start_covered,
            'range_end_covered': range_end_covered
        }
    
    def merge_datasets(self, dataset_a_path: str, dataset_b_path: str, output_path: str) -> pd.DataFrame:
        """
        Merge Dataset A and Dataset B.
        
        Args:
            dataset_a_path: Path to Dataset A
            dataset_b_path: Path to Dataset B
            output_path: Path to save merged dataset
            
        Returns:
            Merged DataFrame
        """
        logger.info("Merging datasets...")
        
        merger = DatasetMerger(
            dataset_a_path=dataset_a_path,
            dataset_b_path=dataset_b_path,
            validate_temporal=True
        )
        
        # Load and validate
        merger.load_datasets()
        merger.validate_compatibility()
        
        # Merge
        merged_df = merger.merge()
        
        # Export
        merger.export(output_path, format='parquet')
        
        # Get statistics
        merge_stats = merger.get_merge_statistics()
        
        self.merged_dataset = merged_df
        self.validation_report['merge_stats'] = merge_stats
        
        logger.info(f"Merged dataset saved to: {output_path}")
        return merged_df
    
    def perform_sanity_checks(self) -> Dict:
        """
        Perform comprehensive sanity checks on merged dataset.
        
        Returns:
            Dictionary with sanity check results
        """
        logger.info("Performing sanity checks...")
        
        if self.merged_dataset is None:
            return {'error': 'No merged dataset available'}
        
        df = self.merged_dataset
        checks = {}
        
        # 1. Check for duplicate rows
        duplicates = df.duplicated().sum()
        checks['duplicate_rows'] = duplicates
        checks['duplicate_check'] = 'PASS' if duplicates == 0 else 'FAIL'
        
        # 2. Check for missing critical columns
        required_cols = ['date', 'ticker', 'entry_date', 'Close', 'Volume', 'label']
        missing_cols = [col for col in required_cols if col not in df.columns]
        checks['missing_critical_columns'] = missing_cols
        checks['critical_columns_check'] = 'PASS' if len(missing_cols) == 0 else 'FAIL'
        
        # 3. Check for infinite values
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        inf_counts = {}
        for col in numeric_cols:
            inf_count = np.isinf(df[col]).sum()
            if inf_count > 0:
                inf_counts[col] = inf_count
        checks['infinite_values'] = inf_counts
        checks['infinite_values_check'] = 'PASS' if len(inf_counts) == 0 else 'WARNING'
        
        # 4. Check label distribution balance
        if 'label' in df.columns:
            label_counts = df['label'].value_counts().to_dict()
            total = len(df)
            balance_ratio = min(label_counts.values()) / max(label_counts.values()) if label_counts else 0
            checks['label_distribution'] = label_counts
            checks['label_balance_ratio'] = balance_ratio
            checks['label_balance_check'] = 'PASS' if balance_ratio >= 0.2 else 'WARNING'  # At least 20% minority class
        
        # 5. Check for missing values by column
        missing_summary = df.isnull().sum()
        missing_summary = missing_summary[missing_summary > 0].sort_values(ascending=False)
        checks['missing_values_by_column'] = missing_summary.to_dict()
        checks['missing_values_pct'] = (df.isnull().sum().sum() / df.size) * 100
        checks['missing_values_check'] = 'PASS' if checks['missing_values_pct'] < 10 else 'WARNING'
        
        # 6. Check date range consistency
        if 'date' in df.columns and 'entry_date' in df.columns:
            date_mismatches = (df['date'] != df['entry_date']).sum()
            checks['date_entry_date_mismatches'] = date_mismatches
            checks['date_consistency_check'] = 'PASS' if date_mismatches == 0 else 'WARNING'
        
        # 7. Check for outliers in key metrics
        if 'return_pct' in df.columns:
            return_stats = df['return_pct'].describe()
            checks['return_pct_stats'] = return_stats.to_dict()
            # Flag extreme returns (>500% or <-100%)
            extreme_returns = ((df['return_pct'] > 500) | (df['return_pct'] < -100)).sum()
            checks['extreme_return_count'] = extreme_returns
            checks['return_outliers_check'] = 'PASS' if extreme_returns == 0 else 'WARNING'
        
        # 8. Check feature completeness
        feature_cols = [c for c in df.columns if c not in ['date', 'ticker', 'entry_date', 'exit_date', 'label']]
        feature_completeness = {}
        for col in feature_cols:
            completeness_pct = (1 - df[col].isnull().sum() / len(df)) * 100
            if completeness_pct < 90:  # Flag features with >10% missing
                feature_completeness[col] = completeness_pct
        checks['low_completeness_features'] = feature_completeness
        checks['feature_completeness_check'] = 'PASS' if len(feature_completeness) == 0 else 'WARNING'
        
        # Overall status
        fail_count = sum(1 for k, v in checks.items() if k.endswith('_check') and v == 'FAIL')
        warning_count = sum(1 for k, v in checks.items() if k.endswith('_check') and v == 'WARNING')
        
        if fail_count > 0:
            checks['overall_status'] = 'FAIL'
        elif warning_count > 0:
            checks['overall_status'] = 'WARNING'
        else:
            checks['overall_status'] = 'PASS'
        
        checks['fail_count'] = fail_count
        checks['warning_count'] = warning_count
        
        return checks
    
    def generate_report(self) -> str:
        """
        Generate comprehensive validation report.
        
        Returns:
            Formatted report string
        """
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append(" TRAINING DATASET PREPARATION REPORT")
        report_lines.append("=" * 80)
        report_lines.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"Requested Period: {self.start_date.date()} to {self.end_date.date()}")
        
        # Dataset A Section
        if 'dataset_a' in self.validation_report:
            da = self.validation_report['dataset_a']
            report_lines.append("\n" + "=" * 80)
            report_lines.append("📊 DATASET A - Feature Store")
            report_lines.append("=" * 80)
            
            if da.get('exists'):
                report_lines.append(f"✅ File found: {da['path']}")
                report_lines.append(f"\nDate Coverage:")
                report_lines.append(f"  Available: {da['min_date'].date()} to {da['max_date'].date()}")
                report_lines.append(f"  Start Date: {'✅ COVERED' if da['range_start_covered'] else '❌ NOT COVERED'}")
                report_lines.append(f"  End Date: {'✅ COVERED' if da['range_end_covered'] else '❌ NOT COVERED'}")
                report_lines.append(f"  Coverage: {da['coverage_pct']:.1f}% ({da['missing_dates_count']} missing dates)")
                
                report_lines.append(f"\nData Statistics:")
                report_lines.append(f"  Total Rows: {da['total_rows']:,}")
                report_lines.append(f"  Unique Tickers: {da['total_tickers']}")
                report_lines.append(f"  Trading Days: {da['total_dates']}")
                report_lines.append(f"  Features: {da['total_features']}")
                report_lines.append(f"  Missing Values: {da['missing_values_pct']:.2f}%")
            else:
                report_lines.append(f"❌ {da.get('error', 'Unknown error')}")
        
        # Dataset B Section
        if 'dataset_b' in self.validation_report:
            db = self.validation_report['dataset_b']
            report_lines.append("\n" + "=" * 80)
            report_lines.append("🎯 DATASET B - Trade Labels")
            report_lines.append("=" * 80)
            
            if db.get('exists'):
                report_lines.append(f"✅ File found: {db['path']}")
                report_lines.append(f"\nDate Coverage:")
                report_lines.append(f"  Entry Dates: {db['min_entry_date'].date()} to {db['max_entry_date'].date()}")
                report_lines.append(f"  Exit Dates: {db['min_exit_date'].date()} to {db['max_exit_date'].date()}")
                report_lines.append(f"  Start Date: {'✅ COVERED' if db['range_start_covered'] else '❌ NOT COVERED'}")
                report_lines.append(f"  End Date: {'✅ COVERED' if db['range_end_covered'] else '❌ NOT COVERED'}")
                
                report_lines.append(f"\nTrade Statistics:")
                report_lines.append(f"  Total Trades: {db['total_trades']:,}")
                report_lines.append(f"  Unique Tickers: {db['total_tickers']}")
                report_lines.append(f"  Win Rate: {db['win_rate']*100:.1f}%")
                report_lines.append(f"  Avg Return: {db['avg_return_pct']:.2f}%")
                report_lines.append(f"  Avg Days Held: {db['avg_days_held']:.1f} days")
                report_lines.append(f"  Trades/Year: {db['trades_per_year']:.1f}")
                
                if db['label_distribution']:
                    report_lines.append(f"\nLabel Distribution:")
                    for label, count in sorted(db['label_distribution'].items()):
                        label_name = "Success" if label == 1 else "Failure"
                        pct = (count / db['total_trades']) * 100
                        report_lines.append(f"  {label_name} ({label}): {count:,} ({pct:.1f}%)")
            else:
                report_lines.append(f"❌ {db.get('error', 'Unknown error')}")
        
        # Merge Section
        if 'merge_stats' in self.validation_report:
            ms = self.validation_report['merge_stats']
            report_lines.append("\n" + "=" * 80)
            report_lines.append("🔗 MERGED DATASET")
            report_lines.append("=" * 80)
            report_lines.append(f"  Total Rows: {ms['merged_rows']:,}")
            report_lines.append(f"  Total Columns: {ms['total_columns']}")
            report_lines.append(f"  Match Rate: {ms['match_rate_pct']:.1f}%")
            report_lines.append(f"  Missing Snapshots: {ms['missing_snapshots']}")
        
        # Sanity Checks Section
        if 'sanity_checks' in self.validation_report:
            sc = self.validation_report['sanity_checks']
            report_lines.append("\n" + "=" * 80)
            report_lines.append("🔍 SANITY CHECKS")
            report_lines.append("=" * 80)
            
            # Overall status
            status_icon = {'PASS': '✅', 'WARNING': '⚠️', 'FAIL': '❌'}
            overall = sc.get('overall_status', 'UNKNOWN')
            report_lines.append(f"\nOverall Status: {status_icon.get(overall, '❓')} {overall}")
            report_lines.append(f"  Failures: {sc.get('fail_count', 0)}")
            report_lines.append(f"  Warnings: {sc.get('warning_count', 0)}")
            
            # Individual checks
            report_lines.append(f"\nDetailed Checks:")
            report_lines.append(f"  Duplicate Rows: {status_icon[sc['duplicate_check']]} {sc['duplicate_check']} ({sc['duplicate_rows']} duplicates)")
            report_lines.append(f"  Critical Columns: {status_icon[sc['critical_columns_check']]} {sc['critical_columns_check']}")
            report_lines.append(f"  Infinite Values: {status_icon[sc['infinite_values_check']]} {sc['infinite_values_check']} ({len(sc['infinite_values'])} columns)")
            report_lines.append(f"  Missing Values: {status_icon[sc['missing_values_check']]} {sc['missing_values_check']} ({sc['missing_values_pct']:.2f}%)")
            
            if 'label_balance_check' in sc:
                report_lines.append(f"  Label Balance: {status_icon[sc['label_balance_check']]} {sc['label_balance_check']} (ratio: {sc['label_balance_ratio']:.2f})")
            
            if 'return_outliers_check' in sc:
                report_lines.append(f"  Return Outliers: {status_icon[sc['return_outliers_check']]} {sc['return_outliers_check']} ({sc['extreme_return_count']} extreme)")
            
            # Show problematic features
            if sc.get('low_completeness_features'):
                report_lines.append(f"\n⚠️  Features with >10% Missing Values:")
                for feat, completeness in list(sc['low_completeness_features'].items())[:10]:
                    report_lines.append(f"    {feat}: {completeness:.1f}% complete")
        
        report_lines.append("\n" + "=" * 80)
        report_lines.append("END OF REPORT")
        report_lines.append("=" * 80)
        
        return "\n".join(report_lines)
    
    def export_report(self, report_path: str, json_path: str = None):
        """
        Export validation report to file.
        
        Args:
            report_path: Path to save text report
            json_path: Optional path to save JSON report
        """
        # Export text report
        report_text = self.generate_report()
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_text)
        logger.info(f"Text report saved to: {report_path}")
        
        # Export JSON report if requested
        if json_path:
            # Convert non-serializable objects
            json_report = {}
            for key, value in self.validation_report.items():
                if isinstance(value, dict):
                    json_report[key] = {k: v for k, v in value.items() if k != 'feature_columns'}
                    # Convert pandas/numpy types
                    for k, v in json_report[key].items():
                        if isinstance(v, (pd.Timestamp, np.datetime64)):
                            json_report[key][k] = str(v)
                        elif isinstance(v, (np.integer, np.floating)):
                            json_report[key][k] = float(v)
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_report, f, indent=2, default=str)
            logger.info(f"JSON report saved to: {json_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Prepare and validate training dataset",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python prepare_training_dataset.py --start 2020-01-01 --end 2025-11-28
        """
    )
    
    parser.add_argument(
        '--start',
        type=str,
        required=True,
        help='Start date for training dataset (YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--end',
        type=str,
        required=True,
        help='End date for training dataset (YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--dataset-a',
        type=str,
        default='data/ml/dataset_a.parquet',
        help='Path to Dataset A file'
    )
    
    parser.add_argument(
        '--dataset-b',
        type=str,
        default='data/ml/dataset_b.parquet',
        help='Path to Dataset B file'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default='data/ml/training_dataset_final.parquet',
        help='Output path for merged training dataset'
    )
    
    parser.add_argument(
        '--report',
        type=str,
        default='data/ml/preparation_report.txt',
        help='Output path for validation report (text)'
    )
    
    parser.add_argument(
        '--report-json',
        type=str,
        default='data/ml/preparation_report.json',
        help='Output path for validation report (JSON)'
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print(" TRAINING DATASET PREPARATION")
    print("=" * 80)
    print(f"\n📅 Target Period: {args.start} to {args.end}")
    print(f"📂 Dataset A: {args.dataset_a}")
    print(f"📂 Dataset B: {args.dataset_b}")
    print(f"💾 Output: {args.output}")
    print(f"📄 Report: {args.report}")
    print("\n" + "=" * 80)
    
    # Initialize preparer
    preparer = DatasetPreparer(start_date=args.start, end_date=args.end)
    
    # Step 1: Check Dataset A
    print("\n🔍 Step 1: Checking Dataset A coverage...")
    dataset_a_stats = preparer.check_dataset_a_coverage(args.dataset_a)
    preparer.validation_report['dataset_a'] = dataset_a_stats
    
    if not dataset_a_stats.get('exists'):
        print(f"❌ Dataset A not found: {args.dataset_a}")
        print("   Please run: python build_dataset_a.py --start {args.start} --end {args.end}")
        sys.exit(1)
    
    if not dataset_a_stats['range_start_covered'] or not dataset_a_stats['range_end_covered']:
        print(f"⚠️  WARNING: Dataset A does not fully cover requested period!")
        print(f"   Available: {dataset_a_stats['min_date'].date()} to {dataset_a_stats['max_date'].date()}")
        print(f"   Requested: {args.start} to {args.end}")
    else:
        print(f"✅ Dataset A covers requested period ({dataset_a_stats['coverage_pct']:.1f}% coverage)")
    
    # Step 2: Check Dataset B
    print("\n🔍 Step 2: Checking Dataset B coverage...")
    dataset_b_stats = preparer.check_dataset_b_coverage(args.dataset_b)
    preparer.validation_report['dataset_b'] = dataset_b_stats
    
    if not dataset_b_stats.get('exists'):
        print(f"❌ Dataset B not found: {args.dataset_b}")
        print(f"   Please run: python build_dataset_b.py --start {args.start} --end {args.end}")
        sys.exit(1)
    
    if not dataset_b_stats['range_start_covered'] or not dataset_b_stats['range_end_covered']:
        print(f"⚠️  WARNING: Dataset B does not fully cover requested period!")
        print(f"   Entry dates: {dataset_b_stats['min_entry_date'].date()} to {dataset_b_stats['max_entry_date'].date()}")
        print(f"   Requested: {args.start} to {args.end}")
    else:
        print(f"✅ Dataset B covers requested period")
    
    # Step 3: Merge datasets
    print("\n🔗 Step 3: Merging datasets...")
    try:
        merged_df = preparer.merge_datasets(
            dataset_a_path=args.dataset_a,
            dataset_b_path=args.dataset_b,
            output_path=args.output
        )
        print(f"✅ Merged dataset saved: {len(merged_df):,} rows")
    except Exception as e:
        logger.error(f"Merge failed: {e}", exc_info=True)
        print(f"❌ Merge failed: {e}")
        sys.exit(1)
    
    # Step 4: Sanity checks
    print("\n🔍 Step 4: Performing sanity checks...")
    sanity_results = preparer.perform_sanity_checks()
    preparer.validation_report['sanity_checks'] = sanity_results
    
    status_icon = {'PASS': '✅', 'WARNING': '⚠️', 'FAIL': '❌'}
    overall = sanity_results.get('overall_status', 'UNKNOWN')
    print(f"\n{status_icon.get(overall, '❓')} Overall Status: {overall}")
    print(f"   Failures: {sanity_results.get('fail_count', 0)}")
    print(f"   Warnings: {sanity_results.get('warning_count', 0)}")
    
    # Step 5: Generate reports
    print("\n📄 Step 5: Generating reports...")
    preparer.export_report(args.report, args.report_json)
    
    # Print summary
    print("\n" + "=" * 80)
    print(" PREPARATION COMPLETE")
    print("=" * 80)
    print(f"\n✅ Training Dataset: {args.output}")
    print(f"   Rows: {len(merged_df):,}")
    print(f"   Features: {len([c for c in merged_df.columns if c not in ['date', 'ticker', 'entry_date', 'exit_date', 'label']])}")
    print(f"   Tickers: {merged_df['ticker'].nunique()}")
    
    print(f"\n📊 Validation Report: {args.report}")
    print(f"📊 JSON Report: {args.report_json}")
    
    if overall == 'FAIL':
        print("\n❌ WARNING: Dataset failed sanity checks. Please review the report!")
        sys.exit(1)
    elif overall == 'WARNING':
        print("\n⚠️  WARNING: Dataset has warnings. Please review the report before training.")
    else:
        print("\n✅ All checks passed! Dataset is ready for model training.")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Preparation interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Preparation failed: {e}", exc_info=True)
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)
