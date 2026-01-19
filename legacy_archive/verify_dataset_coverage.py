"""Verify training dataset coverage from 2003 with both features and trades."""
import pandas as pd
import sys

# Load dataset
print("Loading training dataset...")
df = pd.read_parquet('data/ml/training_dataset_final.parquet')

print(f"\n{'='*80}")
print("DATASET COVERAGE VERIFICATION")
print(f"{'='*80}")

print(f"\n📊 Dataset Shape: {df.shape[0]:,} rows × {df.shape[1]} columns")

# Date range
print(f"\n📅 Date Range:")
print(f"   First entry_date: {df['entry_date'].min().date()}")
print(f"   Last entry_date:  {df['entry_date'].max().date()}")
years_covered = (df['entry_date'].max() - df['entry_date'].min()).days / 365.25
print(f"   Years covered: {years_covered:.1f} years")

# Check if starts from 2003
starts_from_2003 = df['entry_date'].min().year == 2003
print(f"\n✅ Starts from 2003: {starts_from_2003}")
if not starts_from_2003:
    print(f"   ⚠️  WARNING: Dataset starts from {df['entry_date'].min().year}, not 2003!")

# Trade data verification
print(f"\n🔄 Simulated Trade Data:")
trade_cols = ['entry_date', 'exit_date', 'ticker', 'label', 'return_pct']
has_trade_data = all(c in df.columns for c in trade_cols)
print(f"   Has trade columns: {has_trade_data}")
if has_trade_data:
    print(f"   Total trades: {len(df):,}")
    print(f"   Label distribution:")
    print(f"      Winners (label=1): {(df['label']==1).sum():,} ({df['label'].mean()*100:.1f}%)")
    print(f"      Losers (label=0):  {(df['label']==0).sum():,} ({(1-df['label'].mean())*100:.1f}%)")
    if 'return_pct' in df.columns:
        print(f"   Mean return: {df['return_pct'].mean():.2f}%")

# Feature data verification
print(f"\n📈 Feature Data:")

# Count feature types
alpha_features = [c for c in df.columns if 'alpha' in c.lower()]
technical_features = [c for c in df.columns if any(x in c for x in ['SMA', 'RSI', 'Volume', 'Price'])]
fundamental_features = [c for c in df.columns if any(x in c for x in ['revenue', 'eps', 'PE', 'ROE', 'gross'])]

print(f"   Alpha features: {len(alpha_features)}")
print(f"   Technical indicators: {len(technical_features)}")
print(f"   Fundamental metrics: {len(fundamental_features)}")

# Check for missing data in key features
if alpha_features:
    sample_alpha = alpha_features[0]
    missing_pct = df[sample_alpha].isnull().mean() * 100
    print(f"   Sample alpha feature ({sample_alpha}) missing: {missing_pct:.1f}%")

# Yearly distribution
print(f"\n📊 Yearly Distribution:")
df['year'] = pd.to_datetime(df['entry_date']).dt.year
yearly_counts = df['year'].value_counts().sort_index()
for year in range(2003, 2026):
    if year in yearly_counts.index:
        count = yearly_counts[year]
        print(f"   {year}: {count:,} trades")
    else:
        print(f"   {year}: 0 trades ⚠️")

print(f"\n{'='*80}")
print("SUMMARY")
print(f"{'='*80}")
print(f"✅ Coverage from 2003: {starts_from_2003}")
print(f"✅ Has trade data (entry/exit/label): {has_trade_data}")
print(f"✅ Has alpha features: {len(alpha_features) > 0}")
print(f"✅ Has technical features: {len(technical_features) > 0}")
print(f"✅ Total years: {years_covered:.1f}")

if starts_from_2003 and has_trade_data and len(alpha_features) > 0:
    print(f"\n🎉 Dataset is ready for training from 2003!")
else:
    print(f"\n⚠️  Dataset may have coverage issues - review warnings above")
