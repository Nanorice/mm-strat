"""Check if Dataset A has fundamental values"""
import pandas as pd

df = pd.read_parquet('data/ml/dataset_a_with_fundamentals.parquet')

fund_cols = ['revenue', 'grossProfit', 'netIncome', 'totalAssets']

print('=' * 80)
print('DATASET A FUNDAMENTAL POPULATION')
print('=' * 80)
for col in fund_cols:
    non_null = df[col].notna().sum()
    total = len(df)
    pct = (non_null / total * 100)
    print(f'  {col}: {non_null:,}/{total:,} ({pct:.1f}%)')

print('\nSample non-null revenue rows:')
revenue_data = df[df['revenue'].notna()][['ticker', 'date', 'revenue', 'grossProfit', 'netIncome']]
if not revenue_data.empty:
    print(revenue_data.head(10))
else:
    print('  ❌ NO REVENUE DATA FOUND IN DATASET A!')
    print('\n  This means fundamentals were NOT merged during build.')
    print('  Need to rebuild Dataset A with --include-fundamentals')
