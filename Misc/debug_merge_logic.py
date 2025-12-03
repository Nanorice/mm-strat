"""Debug the _merge_statements logic"""
import pandas as pd

# Load raw data
df = pd.read_parquet('data/fundamentals/AAPL.parquet')
income_df = df[df['statement_type'] == 'income'].copy()
balance_df = df[df['statement_type'] == 'balance_sheet'].copy()

print(f'Income: {len(income_df)} rows')
print(f'Balance: {len(balance_df)} rows')

# Check common columns
preferred_merge_cols = ['ticker', 'fiscal_date', 'filing_date', 'fiscal_period', 'fiscal_year']
common_cols = [col for col in preferred_merge_cols 
              if col in income_df.columns and col in balance_df.columns]
print(f'\nCommon merge columns: {common_cols}')

# Try the merge
merged = pd.merge(
    income_df,
    balance_df,
    on=common_cols,
    how='outer',
    suffixes=('_income', '_balance')
)

print(f'\nMerged: {len(merged)} rows')
print(f'\nMerged columns: {len(merged.columns)}')

# Check if revenue and totalAssets are in same rows
print(f'\nRevenue column exists: {"revenue" in merged.columns}')
print(f'TotalAssets column exists: {"totalAssets" in merged.columns}')

if 'revenue' in merged.columns:
    print(f'Revenue populated: {merged["revenue"].notna().sum()}')
if 'totalAssets' in merged.columns:
    print(f'TotalAssets populated: {merged["totalAssets"].notna().sum()}')
    
# Check the first few rows
print('\nFirst 3 rows (fiscal_date, filing_date, revenue, totalAssets):')
print(merged[['fiscal_date', 'filing_date', 'revenue', 'totalAssets']].head(3))
