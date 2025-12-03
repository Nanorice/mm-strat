import pandas as pd

print("Checking Dataset B...")
df = pd.read_parquet('data/ml/dataset_b.parquet')

print(f"\nTotal rows: {len(df):,}")
print(f"Date range: {df['entry_date'].min()} to {df['entry_date'].max()}")
print(f"\nLabel distribution:")
print(df['label'].value_counts())
print(f"\nWin rate: {df['label'].mean():.2%}")

# Check if it covers 2003
min_date = df['entry_date'].min()
covers_2003 = min_date <= pd.Timestamp('2003-12-31')

if covers_2003:
    print(f"\n✅ Dataset B COVERS 2003!")
    print(f"   Earliest trade: {min_date}")
else:
    print(f"\n❌ Dataset B does NOT cover 2003")
    print(f"   Earliest trade: {min_date}")
    print(f"   Gap: {(min_date - pd.Timestamp('2003-01-01')).days} days after 2003-01-01")
