import pandas as pd

df = pd.read_parquet('data/ml/dataset_a.parquet')

print("FUNDAMENTAL COLUMN CHECK")
print("=" * 60)

# Check key fundamental columns
cols_to_check = ['eps', 'revenue', 'netIncome', 'pe_ratio', 'filing_date_matched', 
                 'revenue_growth_yoy', 'gross_margin', 'has_fundamentals']

for col in cols_to_check:
    if col in df.columns:
        non_null = df[col].notna().sum()
        pct = (non_null / len(df)) * 100
        print(f"{col:25s}: {non_null:8,} / {len(df):,} ({pct:5.1f}% present)")
        
        # Show sample non-null values if any exist
        if non_null > 0:
            sample_values = df[df[col].notna()][col].head(3).tolist()
            print(f"{'':25s}  Sample values: {sample_values}")
    else:
        print(f"{col:25s}: NOT FOUND IN DATASET")
    print()

# Check AAPL specifically
print("\n" + "=" * 60)
print("AAPL SAMPLE DATA (First 10 rows)")
print("=" * 60)
aapl = df[df['ticker'] == 'AAPL'].head(10)
cols_to_show = ['date', 'Close', 'eps', 'revenue', 'pe_ratio', 'filing_date_matched']
available_cols = [c for c in cols_to_show if c in df.columns]
print(aapl[available_cols].to_string(index=False))
