"""
Debug script to test FundamentalMerger and identify why data isn't being merged.
"""
import pandas as pd
import numpy as np
from src.fundamental_merger import FundamentalMerger
from src.fundamental_processor import FundamentalProcessor
from src.fundamental_engine import FundamentalEngine
from src.data_engine import DataRepository

print("=" * 80)
print("FUNDAMENTAL MERGER DEBUG TEST - AAPL")
print("=" * 80)

# Step 1: Load raw fundamental data from cache
print("\n[Step 1] Loading AAPL fundamental data from cache...")
fund_engine = FundamentalEngine()
fund_raw = fund_engine.get_ticker_fundamentals('AAPL', use_cache=True)

if fund_raw is None or fund_raw.empty:
    print("❌ ERROR: No fundamental data found for AAPL!")
    exit(1)

print(f"✅ Loaded {len(fund_raw)} rows of raw fundamental data")
print(f"   Columns: {fund_raw.columns.tolist()[:10]}...")
print(f"   Date range: {fund_raw['fiscal_date'].min()} to {fund_raw['fiscal_date'].max()}")
print(f"\n   Sample data:")
print(fund_raw[['fiscal_date', 'filing_date', 'revenue', 'netIncome', 'eps']].head(3))

# Step 2: Process fundamentals
print("\n[Step 2] Processing fundamentals (growth, ratios)...")
processor = FundamentalProcessor()
fund_processed = processor.process_ticker_fundamentals('AAPL', fund_raw)

if fund_processed.empty:
    print("❌ ERROR: Fundamental processing failed!")
    exit(1)

print(f"✅ Processed {len(fund_processed)} rows")
print(f"   Columns: {len(fund_processed.columns)} total")
print(f"\n   Sample processed data:")
sample_cols = ['filing_date', 'revenue', 'eps', 'revenue_growth_yoy', 'gross_margin']
available_cols = [c for c in sample_cols if c in fund_processed.columns]
print(fund_processed[available_cols].head(3))

# Step 3: Load price data
print("\n[Step 3] Loading AAPL price data...")
repo = DataRepository()
price_df = repo.get_ticker_data('AAPL')

if price_df is None or price_df.empty:
    print("❌ ERROR: No price data found for AAPL!")
    exit(1)

print(f"✅ Loaded {len(price_df)} days of price data")
print(f"   Date range: {price_df.index.min()} to {price_df.index.max()}")
print(f"   Index type: {type(price_df.index)}")

# Filter to Q1 2024 for testing
test_price_df = price_df.loc['2024-01-01':'2024-03-31'].copy()
print(f"\n   Filtered to Q1 2024: {len(test_price_df)} rows")

# Step 4: Perform merge
print("\n[Step 4] Merging fundamentals with price data...")
merger = FundamentalMerger()

# Test the merge
merged_df = merger.merge_ticker_data('AAPL', test_price_df)

print(f"✅ Merge completed: {len(merged_df)} rows")
print(f"   Columns: {len(merged_df.columns)} total")

# Step 5: Inspect results
print("\n[Step 5] Inspecting merge results...")
print("\n   Fundamental columns in merged data:")
fund_check_cols = ['eps', 'revenue', 'netIncome', 'pe_ratio', 'filing_date_matched', 
                   'revenue_growth_yoy', 'gross_margin', 'has_fundamentals']

for col in fund_check_cols:
    if col in merged_df.columns:
        non_null = merged_df[col].notna().sum()
        non_zero = (merged_df[col] != 0).sum() if merged_df[col].dtype in [np.float64, np.int64] else 0
        unique = merged_df[col].nunique()
        print(f"   {col:25s}: {non_null:3d} non-null, {non_zero:3d} non-zero, {unique:3d} unique")
        
        # Show sample values
        if non_null > 0:
            sample = merged_df[merged_df[col].notna()][col].head(3).tolist()
            print(f"   {'':25s}  Sample: {sample}")

# Step 6: Check if filing_date_matched is populated
print("\n[Step 6] Checking filing_date_matched...")
if 'filing_date_matched' in merged_df.columns:
    matched_dates = merged_df['filing_date_matched'].dropna()
    print(f"   Rows with filing_date: {len(matched_dates)} / {len(merged_df)}")
    
    if len(matched_dates) > 0:
        print(f"   Unique filing dates: {matched_dates.nunique()}")
        print(f"   Filing dates: {matched_dates.unique().tolist()}")
        
        # Show rows with filing dates
        print("\n   Sample rows WITH filing dates:")
        sample_with_filing = merged_df[merged_df['filing_date_matched'].notna()][
            ['Close', 'eps', 'revenue', 'pe_ratio', 'filing_date_matched']
        ].head(5)
        print(sample_with_filing)
    else:
        print("   ❌ NO filing dates matched! This is the problem.")
        print("\n   Debugging as-of join...")
        print(f"   Price date range: {merged_df.index.min()} to {merged_df.index.max()}")
        print(f"   Fund filing dates: {fund_processed['filing_date'].min()} to {fund_processed['filing_date'].max()}")
        print(f"   Fund filing dates dtype: {fund_processed['filing_date'].dtype}")
else:
    print("   ❌ filing_date_matched column not found!")

# Step 7: Manual as-of join test
print("\n[Step 7] Manual as-of join test...")
print("   Testing merge_asof directly...")

# Prepare data for merge_asof
price_test = merged_df.reset_index() if isinstance(merged_df.index, pd.DatetimeIndex) else merged_df.copy()
if 'Date' not in price_test.columns:
    price_test.rename(columns={'date': 'Date'}, inplace=True)

# Get filing dates
filing_dates = fund_processed['filing_date'].sort_values().unique()
print(f"   Available filing dates ({len(filing_dates)}):")
for fd in filing_dates[:5]:
    print(f"      {fd}")

# Check which price dates would match
print("\n   Price dates vs filing dates:")
for i, price_date in enumerate(price_test['Date'].head(10)):
    matching_filing = fund_processed[fund_processed['filing_date'] <= price_date]['filing_date'].max()
    print(f"      {price_date.date()}: would match filing {matching_filing if pd.notna(matching_filing) else 'NONE'}")

print("\n" + "=" * 80)
print("DIAGNOSIS COMPLETE")
print("=" * 80)
