"""Test fundamental merger on a single ticker"""
from src.fundamental_merger import FundamentalMerger
from src.data_engine import DataRepository
import pandas as pd

# Load AAPL price data
repo = DataRepository()
df = repo.get_ticker_data('AAPL')
print('Price data shape:', df.shape)
print('Price data columns:', list(df.columns))
print('Price data date range:', df.index.min(), 'to', df.index.max())

# Try merging fundamentals
merger = FundamentalMerger()
df_merged = merger.merge_ticker_data('AAPL', df)

print('\n' + '=' * 80)
print('MERGE RESULT')
print('=' * 80)
print('Merged data shape:', df_merged.shape)
print(f'Added {df_merged.shape[1] - df.shape[1]} columns')

# Check for revenue
if 'revenue' in df_merged.columns:
    revenue_count = df_merged['revenue'].notna().sum()
    print(f'\nRevenue column: {revenue_count}/{len(df_merged)} populated ({revenue_count/len(df_merged)*100:.1f}%)')
    if revenue_count > 0:
        print('\nSample revenue data:')
        print(df_merged[df_merged['revenue'].notna()][['revenue', 'grossProfit', 'netIncome', 'filing_date_matched']].head())
    else:
        print('❌ Revenue column exists but all NaN!')
else:
    print('❌ Revenue column NOT in merged data!')

print('\nAll new columns:')
new_cols = [c for c in df_merged.columns if c not in df.columns]
print(new_cols[:20])
