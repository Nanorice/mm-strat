"""Check fundamentals in new Dataset A"""
import pandas as pd

df = pd.read_parquet('data/ml/dataset_a.parquet')
print(f'NEW Dataset A: {len(df):,} rows, {len(df.columns)} columns')

fund_cols = ['revenue', 'grossProfit', 'netIncome', 'totalAssets']
print('\nFundamental columns:')
for col in fund_cols:
    if col in df.columns:
        pop = df[col].notna().sum()
        pct = pop/len(df)*100
        print(f'  {col}: {pop:,}/{len(df):,} ({pct:.1f}%)')
    else:
        print(f'  {col}: NOT FOUND')
