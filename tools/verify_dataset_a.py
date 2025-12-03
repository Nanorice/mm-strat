import pandas as pd

print("Checking Dataset A date range...")
df = pd.read_parquet('data/ml/dataset_a.parquet')
print(f'Dataset A date range: {df["date"].min()} to {df["date"].max()}')
print(f'Total rows: {len(df):,}')
print(f'Years covered: {(df["date"].max() - df["date"].min()).days / 365.25:.1f}')
