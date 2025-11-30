import pandas as pd

df = pd.read_parquet('data/ml/dataset_a.parquet')

print("ROOT CAUSE ANALYSIS")
print("=" * 70)

# Critical check: filing_date_matched
print("\n1. Checking filing_date_matched (proves merger ran):")
filing_exists = df['filing_date_matched'].notna().sum()
print(f"   Non-NaT values: {filing_exists:,} / {len(df):,}")
print(f"   Result: {'MERGER RAN' if filing_exists > 0 else 'MERGER DID NOT RUN!'}")

if filing_exists > 0:
    print(f"   Sample filing dates: {df[df['filing_date_matched'].notna()]['filing_date_matched'].head(3).tolist()}")

# Check if values are actually merged or just defaulted to 0
print("\n2. Checking if EPS has real values or just default 0:")
eps_zero = (df['eps'] == 0.0).sum()
eps_nonzero = (df['eps'] != 0.0).sum()
eps_null = df['eps'].isna().sum()

print(f"   EPS == 0.0:  {eps_zero:,}")
print(f"   EPS != 0.0:  {eps_nonzero:,}")
print(f"   EPS is NaN:  {eps_null:,}")
print(f"   Result: {'ALL ZEROS - DATA NOT MERGED!' if eps_nonzero == 0 else 'Has real data'}")

# Check revenue too
print("\n3. Checking revenue:")
rev_zero = (df['revenue'] == 0.0).sum()
rev_nonzero = (df['revenue'] != 0.0).sum()
print(f"   Revenue == 0.0:  {rev_zero:,}")
print(f"   Revenue != 0.0:  {rev_nonzero:,}")

# Sample AAPL data
print("\n4. AAPL sample (first 5 rows):")
aapl = df[df['ticker'] == 'AAPL'].head(5)
print(aapl[['date', 'Close', 'eps', 'revenue', 'pe_ratio', 'filing_date_matched']].to_string(index=False))

print("\n" + "=" * 70)
print("CONCLUSION:")
print("=" * 70)

if filing_exists == 0:
    print("❌ Dataset was built WITHOUT --include-fundamentals flag!")
    print("   Solution: Rebuild with: python build_dataset_a.py --start 2023-01-01 --end 2025-11-28 --include-fundamentals")
elif eps_nonzero == 0:
    print("❌ Merger ran but fundamental data is all zeros!")
    print("   Possible causes:")
    print("   1. Fundamental cache is empty/corrupt")
    print("   2. As-of join failed (no matching filing dates)")
    print("   3. NaN handling filled everything with 0 before merge")
else:
    print("✅ Dataset has real fundamental data")
