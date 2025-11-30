import pandas as pd

df = pd.read_parquet('data/ml/dataset_a_with_fundamentals.parquet')

print("=" * 80)
print("DATASET A WITH FUNDAMENTALS - VERIFICATION")
print("=" * 80)

print(f"\nDataset Shape: {df.shape[0]:,} rows × {df.shape[1]} columns")
print(f"Date Range: {df['date'].min()} to {df['date'].max()}")
print(f"Tickers: {df['ticker'].nunique()}")

# Check fundamental columns
print("\n" + "=" * 80)
print("FUNDAMENTAL COLUMN VERIFICATION")
print("=" * 80)

key_cols = ['eps', 'revenue', 'netIncome', 'pe_ratio', 'revenue_growth_yoy', 
            'gross_margin', 'debt_to_equity', 'filing_date_matched']

for col in key_cols:
    if col in df.columns:
        non_null = df[col].notna().sum()
        non_zero = (df[col] != 0.0).sum() if df[col].dtype in [float, int] else 0
        pct = (non_null / len(df)) * 100
        
        print(f"\n{col}:")
        print(f"  Non-null: {non_null:,} ({pct:.1f}%)")
        print(f"  Non-zero: {non_zero:,}")
        
        if non_zero > 0:
            # Show sample real values
            real_values = df[df[col] != 0.0][col].dropna().head(5).tolist()
            print(f"  ✅ Sample REAL values: {real_values}")
        else:
            print(f"  ❌ All values are zero or NaN!")

# AAPL specific check
print("\n" + "=" * 80)
print("AAPL SAMPLE (2024 data)")
print("=" * 80)

aapl_2024 = df[(df['ticker'] == 'AAPL') & (df['date'] >= '2024-01-01')].head(10)
cols_to_show = ['date', 'Close', 'eps', 'revenue', 'pe_ratio', 'revenue_growth_yoy']
print(aapl_2024[cols_to_show].to_string(index=False))

print("\n" + "=" * 80)
print("FINAL VERDICT")
print("=" * 80)

eps_has_real_data = (df['eps'] != 0.0).any()
revenue_has_real_data = (df['revenue'] != 0.0).any()

if eps_has_real_data and revenue_has_real_data:
    print("✅ SUCCESS! Dataset A now has REAL fundamental data!")
    print(f"   - EPS has non-zero values: {(df['eps'] != 0.0).sum():,} rows")
    print(f"   - Revenue has non-zero values: {(df['revenue'] != 0.0).sum():,} rows")
else:
    print("❌ FAILED! Fundamental data still all zeros")
