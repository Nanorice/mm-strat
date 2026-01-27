"""
Debug script to check which fundamental fields are missing and why.

This will help diagnose the missing columns issue:
- entry_vol_ratio (should be Vol_Ratio)
- current_ratio
- quick_ratio  
- ps_ratio
"""

import pandas as pd
import numpy as np
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent))

from src.fundamental_engine import FundamentalEngine
from src.fundamental_processor import FundamentalProcessor

def check_fundamental_columns():
    """Check what columns are available in fundamental data."""
    
    print("=" * 80)
    print(" FUNDAMENTAL COLUMNS DIAGNOSTIC")
    print("=" * 80)
    
    # Test with a few tickers
    test_tickers = ['AAPL', 'MSFT', 'NVDA']
    
    engine = FundamentalEngine()
    processor = FundamentalProcessor()
    
    for ticker in test_tickers:
        print(f"\n{'='*80}")
        print(f"Ticker: {ticker}")
        print(f"{'='*80}")
        
        # Load raw data
        raw_data = engine.get_ticker_fundamentals(ticker, use_cache=True)
        
        if raw_data is None or raw_data.empty:
            print(f"❌ No fundamental data for {ticker}")
            continue
        
        print(f"\n📊 Raw Data Shape: {raw_data.shape}")
        print(f"Columns: {list(raw_data.columns)}")
        print(f"Statement types: {raw_data['statement_type'].unique() if 'statement_type' in raw_data.columns else 'N/A'}")
        
        #Check for balance sheet fields
        balance_fields = ['currentAssets', 'currentLiabilities', 'inventory']
        print(f"\n🔍 Checking balance sheet fields:")
        for field in balance_fields:
            exists = field in raw_data.columns
            has_data = exists and not raw_data[field].isna().all()
            print(f"   {field}: {'✓' if exists else '✗'} exists, {'✓' if has_data else '✗'} has data")
        
        # Process data
        processed_data = processor.process_ticker_fundamentals(ticker, raw_data)
        
        if processed_data.empty:
            print(f"❌ Processing failed for {ticker}")
            continue
        
        print(f"\n📊 Processed Data Shape: {processed_data.shape}")
        print(f"Columns: {list(processed_data.columns)}")
        
        # Check for ratio fields
        ratio_fields = ['current_ratio', 'quick_ratio', 'debt_to_equity']
        print(f"\n🔍 Checking calculated ratios:")
        for field in ratio_fields:
            exists = field in processed_data.columns
            has_data = exists and not processed_data[field].isna().all()
            count_non_nan = processed_data[field].notna().sum() if exists else 0
            print(f"   {field}: {'✓' if exists else '✗'} exists, {count_non_nan}/{len(processed_data)} non-NaN values")
        
        # Show a sample row
        if not processed_data.empty:
            print(f"\n📋 Sample Row (most recent):")
            sample = processed_data.iloc[0]
            for col in ['currentAssets', 'currentLiabilities', 'inventory', 'current_ratio', 'quick_ratio']:
                if col in processed_data.columns:
                    print(f"   {col}: {sample[col]}")

def check_dataset_a():
    """Check what columns exist in Dataset A."""
    
    dataset_a_path = 'data/ml/dataset_a.parquet'
    
    if not Path(dataset_a_path).exists():
        print(f"\n❌ Dataset A not found at: {dataset_a_path}")
        return
    
    print(f"\n{'='*80}")
    print(" DATASET A ANALYSIS")
    print(f"{'='*80}")
    
    ds_a = pd.read_parquet(dataset_a_path)
    
    print(f"\nShape: {ds_a.shape}")
    print(f"Columns ({len(ds_a.columns)}): {list(ds_a.columns)}")
    
    # Check for missing columns
    missing_cols = ['current_ratio', 'quick_ratio', 'ps_ratio', 'Vol_Ratio']
    
    print(f"\n🔍 Checking for potentially missing columns:")
    for col in missing_cols:
        if col in ds_a.columns:
            non_nan = ds_a[col].notna().sum()
            pct = (non_nan / len(ds_a)) * 100
            print(f"   ✓ {col}: {non_nan:,}/{len(ds_a):,} ({pct:.2f}%) non-NaN")
        else:
            print(f"   ✗ {col}: MISSING")

def check_merged_dataset():
    """Check what columns exist in merged dataset."""
    
    merged_path = 'data/ml/merged_dataset.parquet'
    
    if not Path(merged_path).exists():
        print(f"\n❌ Merged dataset not found at: {merged_path}")
        return
    
    print(f"\n{'='*80}")
    print(" MERGED DATASET ANALYSIS")
    print(f"{'='*80}")
    
    ds_merged = pd.read_parquet(merged_path)
    
    print(f"\nShape: {ds_merged.shape}")
    
    # Check for missing columns
    missing_cols = ['current_ratio', 'quick_ratio', 'ps_ratio', 'Vol_Ratio', 'entry_vol_ratio']
    
    print(f"\n🔍 Checking for potentially missing columns:")
    for col in missing_cols:
        if col in ds_merged.columns:
            non_nan = ds_merged[col].notna().sum()
            pct = (non_nan / len(ds_merged)) * 100
            print(f"   ✓ {col}: {non_nan:,}/{len(ds_merged):,} ({pct:.2f}%) non-NaN")
        else:
            print(f"   ✗ {col}: MISSING")
    
    # Show all columns
    print(f"\n📋 All Columns ({len(ds_merged.columns)}):")
    for i, col in enumerate(ds_merged.columns, 1):
        print(f"   {i:3d}. {col}")

if __name__ == "__main__":
    try:
        check_fundamental_columns()
        check_dataset_a()
        check_merged_dataset()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
