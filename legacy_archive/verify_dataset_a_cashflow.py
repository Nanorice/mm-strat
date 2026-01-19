import pandas as pd

df = pd.read_parquet('data/ml/dataset_a.parquet')
print(f'Dataset A Shape: {df.shape}')
print(f'Total columns: {len(df.columns)}')

# Look for cash flow related columns
cf_related = [c for c in df.columns if any(x in c.lower() for x in 
             ['cash', 'accrual', 'roic', 'reinvest', 'efficient', 'operating_leverage'])]

print(f'\n✅ Cash Flow Related Columns Found: {len(cf_related)}')
if cf_related:
    print('\nColumn names:')
    for col in sorted(cf_related):
        non_null = df[col].notna().sum()
        pct = (non_null / len(df)) * 100
        print(f'  - {col}: {non_null}/{len(df)} ({pct:.1f}% populated)')
    
    print(f'\nSample values (first 5 rows):')
    print(df[sorted(cf_related)].head())
else:
    print('❌ NO CASH FLOW COLUMNS FOUND!')

# Check all fundamental columns
fund_cols = [c for c in df.columns if c in [
    'revenue', 'netIncome', 'eps', 'totalAssets', 'totalDebt',
    'operatingCashFlow', 'freeCashFlow', 'capitalExpenditure',
    'accruals_ratio', 'roic', 'reinvestment_rate', 'efficient_growth',
    'debt_to_equity', 'current_ratio', 'roe', 'roa'
]]

print(f'\n📊 All Fundamental Columns Present: {len(fund_cols)}')
for col in sorted(fund_cols):
    non_null = df[col].notna().sum()
    pct = (non_null / len(df)) * 100
    print(f'  - {col}: {pct:.1f}% populated')
