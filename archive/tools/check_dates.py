import pandas as pd

df = pd.read_parquet('data/ml/training_dataset_final.parquet')
print(f'Date range: {df["entry_date"].min()} to {df["entry_date"].max()}')
print(f'Total rows: {len(df):,}')
print(f'\nLatest 10 entry dates:')
print(df['entry_date'].sort_values().tail(10).values)
