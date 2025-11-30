"""Quick diagnostic script to investigate dataset issues."""
import pandas as pd

print("=" * 80)
print("DATASET DIAGNOSTICS")
print("=" * 80)

# Load merged dataset
print("\n1. Loading merged dataset...")
df = pd.read_parquet('data/ml/training_dataset_final.parquet')
print(f"   Rows: {len(df):,}")
print(f"   Columns: {len(df.columns)}")

# Check critical columns
print("\n2. Critical Columns Check:")
required = ['date', 'ticker', 'entry_date', 'Close', 'Volume', 'label']
for col in required:
    if col in df.columns:
        print(f"   ✅ {col}")
    else:
        print(f"   ❌ {col} - MISSING!")

# Check label distribution
print("\n3. Label Distribution:")
if 'label' in df.columns:
    label_counts = df['label'].value_counts()
    total = len(df)
    for label, count in label_counts.items():
        pct = (count / total) * 100
        label_name = "Success" if label == 1 else "Failure"
        print(f"   {label_name} ({label}): {count:,} ({pct:.1f}%)")
    
    balance_values = list(label_counts.values)
    ratio = min(balance_values) / max(balance_values)
    print(f"   Balance ratio: {ratio:.2f} (minority/majority)")

# Check missing values in key features
print("\n4. Features with High Missing Values (>10%):")
missing_pct = (df.isnull().sum() / len(df)) * 100
high_missing = missing_pct[missing_pct > 10].sort_values(ascending=False)
for col, pct in high_missing.head(15).items():
    completeness = 100 - pct
    print(f"   {col}: {completeness:.1f}% complete ({pct:.1f}% missing)")

# Check fundamental columns
print("\n5. Fundamental Columns:")
fund_cols = [c for c in df.columns if c in ['revenue', 'costOfRevenue', 'grossProfit', 'netIncome', 'totalAssets']]
if fund_cols:
    for col in fund_cols:
        non_null = df[col].notna().sum()
        pct = (non_null / len(df)) * 100
        print(f"   {col}: {non_null}/{len(df)} ({pct:.1f}% populated)")
else:
    print("   ❌ No fundamental columns found in merged dataset!")

# Check Dataset B
print("\n6. Dataset B Analysis:")
df_b = pd.read_parquet('data/ml/dataset_b.parquet')
print(f"   Total trades: {len(df_b):,}")
print(f"   First entry: {df_b['entry_date'].min()}")
print(f"   Last entry: {df_b['entry_date'].max()}")
print(f"\n   First 5 trades by date:")
df_b_sorted = df_b.copy()
df_b_sorted['entry_date'] = pd.to_datetime(df_b_sorted['entry_date'])
first_trades = df_b_sorted.nsmallest(5, 'entry_date')[['ticker', 'entry_date', 'entry_price', 'return_pct', 'label']]
print(first_trades.to_string(index=False))

# Check entry_vol_ratio issue
print("\n7. Entry Volume Ratio Issue:")
if 'entry_vol_ratio' in df.columns:
    non_null = df['entry_vol_ratio'].notna().sum()
    print(f"   Found in merged dataset: {non_null}/{len(df)} populated")
else:
    print("   ❌ entry_vol_ratio not in merged dataset")

if 'entry_vol_ratio' in df_b.columns:
    non_null_b = df_b['entry_vol_ratio'].notna().sum()
    print(f"   Found in Dataset B: {non_null_b}/{len(df_b)} populated")
else:
    print("   ❌ entry_vol_ratio not in Dataset B")

# Check SMA columns
print("\n8. SMA Columns Completeness:")
for sma_col in ['SMA_50', 'SMA_150', 'SMA_200']:
    if sma_col in df.columns:
        non_null = df[sma_col].notna().sum()
        pct = (non_null / len(df)) * 100
        print(f"   {sma_col}: {pct:.1f}% complete")

print("\n" + "=" * 80)
print("DIAGNOSIS COMPLETE")
print("=" * 80)
