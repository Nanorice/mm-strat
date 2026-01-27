import pandas as pd

# Load test dataset
df = pd.read_parquet('data/ml/test_fix.parquet')

# Check for new features
new_features = [
    'RSI_14', 'RSI_Regime', 'Dist_From_52W_High', 
    'Green_Days_Ratio_20D', 'SMA_50_Slope'
]

print("=" * 80)
print(" NEW FEATURE VERIFICATION")
print("=" * 80)

print("\nTechnical Features:")
for f in new_features:
    exists = f in df.columns
    if exists:
        non_nan = df[f].notna().sum()
        pct = (non_nan / len(df)) * 100
        print(f"  ✓ {f}: {non_nan:,}/{len(df):,} ({pct:.2f}%) non-NaN")
    else:
        print(f"  ✗ {f}: MISSING")

print(f"\nTotal columns: {len(df.columns)}")
print(f"Sample data shape: {df.shape}")

# Show sample values
if 'RSI_14' in df.columns:
    print(f"\nSample RSI_14 values:")
    print(df[['ticker', 'date', 'RSI_14']].dropna(subset=['RSI_14']).head(10))
