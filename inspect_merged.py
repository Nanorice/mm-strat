"""
Inspect Merged Dataset - Quality Validation Tool

Analyzes merged dataset (Dataset A + B) to verify merge quality,
feature completeness, and data integrity.

Usage:
    python inspect_merged.py data/ml/merged_dataset.parquet
"""

import pandas as pd
import argparse
import sys
from pathlib import Path
import numpy as np

# Add src to path
sys.path.append(str(Path(__file__).parent))


def load_merged_dataset(path: str) -> pd.DataFrame:
    """Load merged dataset from Parquet or CSV."""
    file_path = Path(path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Merged dataset not found: {path}")
    
    if file_path.suffix == '.parquet':
        df = pd.read_parquet(path)
    elif file_path.suffix == '.csv':
        df = pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported file format: {file_path.suffix}")
    
    # Convert date columns
    date_cols = ['date', 'entry_date', 'exit_date']
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    
    return df


def print_overview(df: pd.DataFrame):
    """Print dataset overview."""
    print("\n" + "=" * 80)
    print(" MERGED DATASET OVERVIEW")
    print("=" * 80)
    
    print(f"\n📊 Dataset Size:")
    print(f"   Total Rows: {len(df):,}")
    print(f"   Total Columns: {len(df.columns)}")
    print(f"   Unique Tickers: {df['ticker'].nunique()}")
    
    if 'entry_date' in df.columns:
        print(f"   Entry Date Range: {df['entry_date'].min().date()} to {df['entry_date'].max().date()}")
    
    # Memory usage
    memory_mb = df.memory_usage(deep=True).sum() / (1024 * 1024)
    print(f"   Memory Usage: {memory_mb:.2f} MB")


def print_label_distribution(df: pd.DataFrame):
    """Print label distribution analysis."""
    print("\n" + "=" * 80)
    print(" LABEL DISTRIBUTION")
    print("=" * 80)
    
    if 'label' not in df.columns:
        print("\n⚠️  No 'label' column found")
        return
    
    label_counts = df['label'].value_counts().sort_index()
    total = len(df)
    
    print(f"\n🏷️  Labels:")
    for label, count in label_counts.items():
        label_name = "Success" if label == 1 else "Failure"
        pct = (count / total) * 100
        print(f"   {label_name} ({label}): {count:4d} trades ({pct:5.1f}%)")
    
    # Class imbalance
    if 0 in label_counts and 1 in label_counts:
        imbalance_ratio = label_counts[0] / label_counts[1]
        print(f"\n   Class Imbalance Ratio: {imbalance_ratio:.2f}:1 (Failure:Success)")


def print_feature_summary(df: pd.DataFrame):
    """Print feature type breakdown."""
    print("\n" + "=" * 80)
    print(" FEATURE SUMMARY")
    print("=" * 80)
    
    # Identify feature types
    all_cols = df.columns.tolist()
    
    # Dataset B metadata columns
    metadata_cols = ['trade_id', 'ticker', 'entry_date', 'exit_date', 'entry_price', 
                     'exit_price', 'return_pct', 'days_held', 'exit_reason', 'label',
                     'max_drawdown_pct', 'max_favorable_excursion_pct', 'r_multiple',
                     'sharpe_ratio', 'initial_risk_pct']
    
    # Feature columns (not metadata)
    feature_cols = [col for col in all_cols if col not in metadata_cols]
    
    # Categorize features
    technical = [c for c in feature_cols if c.startswith(('SMA', 'ATR', 'RS', 'Vol', 'High', 'Low', 'Breakout', 'Price_vs', 'nATR', 'VCP', 'Consolidation', 'Dry_Up', 'Close', 'Volume'))]
    fundamental = [c for c in feature_cols if c in ['revenue', 'eps', 'netIncome', 'totalAssets', 'totalDebt', 'totalEquity', 'cash',
                                                      'revenue_growth_yoy', 'eps_growth_yoy', 'net_income_growth_yoy',
                                                      'debt_to_equity', 'current_ratio', 'quick_ratio',
                                                      'gross_margin', 'operating_margin', 'roe', 'roa',
                                                      'pe_ratio', 'pb_ratio', 'ps_ratio',
                                                      'filing_date_matched', 'days_since_report', 'is_stale', 'has_fundamentals']]
    alphas = [c for c in feature_cols if c.startswith('alpha')]
    other = [c for c in feature_cols if c not in technical and c not in fundamental and c not in alphas]
    
    print(f"\n📋 Feature Breakdown:")
    print(f"   Total Features: {len(feature_cols)}")
    
    if technical:
        print(f"\n   📈 Technical ({len(technical)}): ")
        print(f"      {', '.join(technical[:8])}{' ...' if len(technical) > 8 else ''}")
    
    if fundamental:
        print(f"\n   💰 Fundamental ({len(fundamental)}): ")
        print(f"      {', '.join(fundamental[:8])}{' ...' if len(fundamental) > 8 else ''}")
    
    if alphas:
        print(f"\n   🔢 Alpha Factors ({len(alphas)}): ")
        print(f"      {', '.join(alphas)}")
    
    if other:
        print(f"\n   📊 Other ({len(other)}): ")
        print(f"      {', '.join(other[:8])}{' ...' if len(other) > 8 else ''}")


def print_missing_values_report(df: pd.DataFrame):
    """Print missing value analysis."""
    print("\n" + "=" * 80)
    print(" MISSING VALUES ANALYSIS")
    print("=" * 80)
    
    missing = df.isnull().sum()
    missing_pct = (missing / len(df)) * 100
    
    # Total missing
    total_missing = missing.sum()
    total_values = df.size
    overall_pct = (total_missing / total_values) * 100
    
    print(f"\n⚠️  Overall Missing: {total_missing:,} / {total_values:,} ({overall_pct:.2f}%)")
    
    # Columns with missing values
    cols_with_missing = missing[missing > 0].sort_values(ascending=False)
    
    if len(cols_with_missing) == 0:
        print("\n✅ No missing values found!")
        return
    
    print(f"\n📊 Columns with Missing Values (Top 15):")
    for col, count in cols_with_missing.head(15).items():
        pct = missing_pct[col]
        print(f"   {col:30s}: {count:6,d} ({pct:5.1f}%)")
    
    if len(cols_with_missing) > 15:
        print(f"\n   ... and {len(cols_with_missing) - 15} more columns")


def print_sample_rows(df: pd.DataFrame, n: int = 5):
    """Print sample rows from merged dataset."""
    print("\n" + "=" * 80)
    print(f" SAMPLE ROWS (Random {n})")
    print("=" * 80)
    
    sample = df.sample(min(n, len(df)))
    
    # Select key columns to display
    key_cols = ['ticker', 'entry_date', 'label', 'return_pct', 'days_held']
    
    # Add some feature columns
    feature_samples = []
    if 'SMA_50' in df.columns:
        feature_samples.append('SMA_50')
    if 'ATR' in df.columns:
        feature_samples.append('ATR')
    if 'RS' in df.columns:
        feature_samples.append('RS')
    if 'alpha001' in df.columns:
        feature_samples.append('alpha001')
    if 'revenue_growth_yoy' in df.columns:
        feature_samples.append('revenue_growth_yoy')
    if 'pe_ratio' in df.columns:
        feature_samples.append('pe_ratio')
    
    display_cols = [col for col in key_cols if col in sample.columns] + feature_samples[:5]
    
    display_df = sample[display_cols].copy()
    
    # Format dates
    if 'entry_date' in display_df.columns:
        display_df['entry_date'] = display_df['entry_date'].dt.date
    
    print("\n")
    print(display_df.to_string(index=False))


def print_merge_quality(df: pd.DataFrame):
    """Analyze merge quality."""
    print("\n" + "=" * 80)
    print(" MERGE QUALITY ASSESSMENT")
    print("=" * 80)
    
    # Check for dataset B columns
    required_b_cols = ['ticker', 'entry_date', 'label']
    has_b_cols = all(col in df.columns for col in required_b_cols)
    
    # Check for dataset A feature columns
    feature_indicators = ['SMA_50', 'ATR', 'RS', 'Close', 'Volume']
    has_features = any(col in df.columns for col in feature_indicators)
    
    print(f"\n✅ Merge Validation:")
    print(f"   Dataset B columns present: {has_b_cols}")
    print(f"   Dataset A features present: {has_features}")
    
    # Check for duplicate rows
    duplicates = df.duplicated(subset=['ticker', 'entry_date']).sum()
    print(f"\n📊 Data Quality:")
    print(f"   Duplicate (ticker, entry_date) pairs: {duplicates}")
    
    if duplicates > 0:
        print(f"   ⚠️  Warning: Found {duplicates} duplicate trade entries")
    
    # Feature completeness by ticker
    if 'ticker' in df.columns and len(df) > 0:
        ticker_counts = df['ticker'].value_counts()
        print(f"\n📈 Ticker Distribution:")
        print(f"   Tickers with most trades: {ticker_counts.head(5).to_dict()}")


def main():
    """Main entry point for inspect_merged CLI."""
    parser = argparse.ArgumentParser(
        description="Inspect merged dataset quality and statistics"
    )
    
    parser.add_argument(
        'file',
        type=str,
        help='Path to merged dataset (Parquet or CSV)'
    )
    
    parser.add_argument(
        '--show-missing',
        action='store_true',
        help='Show detailed missing value report'
    )
    
    parser.add_argument(
        '--sample',
        type=int,
        default=5,
        help='Number of sample rows to display (default: 5)'
    )
    
    parser.add_argument(
        '--export-summary',
        type=str,
        default=None,
        help='Export statistics summary to CSV'
    )
    
    args = parser.parse_args()
    
    # Print header
    print("\n" + "=" * 80)
    print(" MERGED DATASET INSPECTOR")
    print("=" * 80)
    print(f"\n📂 Loading: {args.file}")
    
    try:
        # Load dataset
        df = load_merged_dataset(args.file)
        print(f"   ✅ Loaded {len(df):,} rows")
        
        # Print all analyses
        print_overview(df)
        print_label_distribution(df)
        print_feature_summary(df)
        print_merge_quality(df)
        
        if args.show_missing:
            print_missing_values_report(df)
        
        print_sample_rows(df, n=args.sample)
        
        # Export summary if requested
        if args.export_summary:
            summary = df.describe()
            summary.to_csv(args.export_summary)
            print(f"\n   ✅ Summary statistics exported to: {args.export_summary}")
        
        print("\n" + "=" * 80)
        print("✅ Inspection complete!")
        print("=" * 80 + "\n")
        
    except FileNotFoundError as e:
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)
    
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Inspection interrupted by user.")
        sys.exit(1)
