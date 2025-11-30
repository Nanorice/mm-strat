import pandas as pd

# Load merged dataset
df = pd.read_parquet('data/ml/merged_dataset.parquet')

print("=" * 80)
print(" MERGE VERIFICATION")
print("=" * 80)

print(f"\nShape: {df.shape}")
print(f"Rows: {len(df):,}")
print(f"Columns: {len(df.columns)}")
print(f"\nLabel distribution: {df['label'].value_counts().to_dict()}")

# Check for key columns
print(f"\nKey Dataset B columns present:")
print(f"  - ticker: {' ticker' in df.columns}")
print(f"  - entry_date: {'entry_date' in df.columns}")
print(f"  - label: {'label' in df.columns}")
print(f"  - return_pct: {'return_pct' in df.columns}")

print(f"\nKey Dataset A features present:")
print(f"  - SMA_50: {'SMA_50' in df.columns}")
print(f"  - ATR: {'ATR' in df.columns}")
print(f"  - RS: {'RS' in df.columns}")
print(f"  - alpha001: {'alpha001' in df.columns}")
print(f"  - revenue_growth_yoy: {'revenue_growth_yoy' in df.columns}")
print(f"  - pe_ratio: {'pe_ratio' in df.columns}")

print(f"\nMissing values: {df.isnull().sum().sum():,} ({df.isnull().sum().sum() / df.size * 100:.2f}%)")

print(f"\nFirst few columns: {list(df.columns[:15])}")

print("\n✅ Merge successful!")
