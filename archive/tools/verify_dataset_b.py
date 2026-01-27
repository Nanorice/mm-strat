import pandas as pd

print("Checking Dataset B...")
df = pd.read_parquet('data/ml/dataset_b.parquet')

print(f"\nTotal rows: {len(df):,}")
print(f"Date range: {df['entry_date'].min()} to {df['entry_date'].max()}")
print(f"\nLabel distribution:")
print(df['label'].value_counts())
print(f"\nWin rate: {df['label'].mean():.2%}")
print(f"Columns: {list(df.columns)}")
