"""
Analyze missing values in Dataset A to understand fundamental data coverage.
"""
import pandas as pd
import numpy as np

# Load dataset
df = pd.read_parquet('data/ml/dataset_a.parquet')

print("=" * 80)
print("DATASET A - MISSING VALUE ANALYSIS")
print("=" * 80)
print(f"\nDataset Shape: {df.shape[0]:,} rows × {df.shape[1]} columns")
print(f"Date Range: {df['date'].min()} to {df['date'].max()}")
print(f"Tickers: {df['ticker'].nunique()}")

# Overall missing values
total_missing = df.isnull().sum().sum()
total_cells = df.shape[0] * df.shape[1]
missing_pct = (total_missing / total_cells) * 100
print(f"\nTotal Missing Values: {total_missing:,} / {total_cells:,} ({missing_pct:.2f}%)")

print("\n" + "=" * 80)
print("FUNDAMENTAL COLUMNS ANALYSIS")
print("=" * 80)

# Check which fundamental columns exist
fundamental_keywords = ['eps', 'revenue', 'netIncome', 'totalAssets', 'pe_ratio', 
                        'filing_date', 'growth', 'margin', 'ratio', 'roe', 'roa']

fund_cols = []
for keyword in fundamental_keywords:
    matching = [c for c in df.columns if keyword in c.lower()]
    fund_cols.extend(matching)

fund_cols = list(set(fund_cols))  # Remove duplicates
print(f"\nFound {len(fund_cols)} fundamental-related columns")

# Analyze each fundamental column
print("\nColumn-by-Column Analysis:")
print("-" * 80)
print(f"{'Column Name':<40} {'Non-Null':>12} {'Missing':>12} {'Missing %':>12}")
print("-" * 80)

fund_analysis = []
for col in sorted(fund_cols):
    non_null = df[col].notna().sum()
    missing = df[col].isna().sum()
    missing_pct = (missing / len(df)) * 100
    fund_analysis.append({
        'column': col,
        'non_null': non_null,
        'missing': missing,
        'missing_pct': missing_pct
    })
    print(f"{col:<40} {non_null:>12,} {missing:>12,} {missing_pct:>11.2f}%")

print("\n" + "=" * 80)
print("KEY FUNDAMENTAL COLUMNS - DETAILED CHECK")
print("=" * 80)

key_cols = ['eps', 'revenue', 'netIncome', 'pe_ratio', 'revenue_growth_yoy', 
            'eps_growth_yoy', 'debt_to_equity', 'gross_margin', 'filing_date_matched']

for col in key_cols:
    if col in df.columns:
        print(f"\n{col}:")
        print(f"  Data type: {df[col].dtype}")
        print(f"  Non-null values: {df[col].notna().sum():,} ({(df[col].notna().sum()/len(df)*100):.2f}%)")
        print(f"  Unique values: {df[col].nunique():,}")
        if df[col].notna().any():
            print(f"  Sample values: {df[col].dropna().head(3).tolist()}")
    else:
        print(f"\n{col}: COLUMN NOT FOUND")

print("\n" + "=" * 80)
print("ROOT CAUSE INVESTIGATION")
print("=" * 80)

# Check has_fundamentals flag
if 'has_fundamentals' in df.columns:
    has_fund_count = (df['has_fundamentals'] == True).sum()
    print(f"\nRows with has_fundamentals=True: {has_fund_count:,} ({(has_fund_count/len(df)*100):.2f}%)")
    
# Check filing_date_matched
if 'filing_date_matched' in df.columns:
    has_filing_date = df['filing_date_matched'].notna().sum()
    print(f"Rows with filing_date_matched: {has_filing_date:,} ({(has_filing_date/len(df)*100):.2f}%)")

# Sample the data to see what's happening
print("\n" + "=" * 80)
print("SAMPLE DATA INSPECTION")
print("=" * 80)

# Get a sample ticker with data
sample_cols = ['ticker', 'date', 'Close', 'has_fundamentals']
if 'eps' in df.columns:
    sample_cols.append('eps')
if 'revenue' in df.columns:
    sample_cols.append('revenue')
if 'pe_ratio' in df.columns:
    sample_cols.append('pe_ratio')
if 'filing_date_matched' in df.columns:
    sample_cols.append('filing_date_matched')

available_sample_cols = [c for c in sample_cols if c in df.columns]
print(f"\nFirst 10 rows (AAPL if available):")
sample = df[df['ticker'] == 'AAPL'].head(10) if 'AAPL' in df['ticker'].values else df.head(10)
print(sample[available_sample_cols].to_string(index=False))

print("\n" + "=" * 80)
print("RECOMMENDATION")
print("=" * 80)
print("\nBased on analysis, check:")
print("1. Are fundamental columns being created but with wrong names?")
print("2. Is the FundamentalMerger actually being called?")
print("3. Are there ticker-specific issues (some tickers have data, others don't)?")
print("4. Is the fundamental cache populated for these tickers?")
