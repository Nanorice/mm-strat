"""Quick check of Dataset A date range"""
import pandas as pd

df_a = pd.read_parquet('data/ml/dataset_a.parquet')
df_b = pd.read_parquet('data/ml/dataset_b.parquet')

print('='*80)
print('DATE RANGE MISMATCH')
print('='*80)
print(f'\nDataset A (features):')
print(f'  Date range: {df_a["date"].min()} to {df_a["date"].max()}')
print(f'  Total rows: {len(df_a):,}')

print(f'\nDataset B (trades):')
print(f'  Date range: {df_b["entry_date"].min()} to {df_b["entry_date"].max()}')
print(f'  Total trades: {len(df_b):,}')

print(f'\n⚠️  PROBLEM:')
print(f'  Dataset B needs features from {df_b["entry_date"].min().strftime("%Y-%m-%d")}')
print(f'  But Dataset A only has features from {df_a["date"].min().strftime("%Y-%m-%d")}')
print(f'\n  Missing {(df_a["date"].min() - df_b["entry_date"].min()).days} days of features!')
print(f'\n✅ SOLUTION: Rebuild Dataset A with --start 2021-01-01')
