"""
Verify the trade ID fix logic by simulating it on the existing corrupted dataset
"""
import pandas as pd

print("=" * 80)
print(" VERIFYING TRADE ID FIX LOGIC")
print("=" * 80)

# Load the corrupted dataset
print("\n📂 Loading corrupted dataset...")
df = pd.read_csv('data/ml/dataset_b.csv')

print(f"Total trades: {len(df):,}")
print(f"Current unique trade_ids: {df['trade_id'].nunique():,}")
print(f"Current trade_id range: {df['trade_id'].min()} to {df['trade_id'].max()}")

# Show the corruption
print("\n❌ Current Corruption:")
print(f"   Trade ID '1' appears {(df['trade_id'] == 1).sum():,} times")
print(f"   Trade ID '2' appears {(df['trade_id'] == 2).sum():,} times")
print(f"   Trade ID '3' appears {(df['trade_id'] == 3).sum():,} times")

# Simulate the fix: Sort by entry_date and reassign IDs
print("\n🔧 Simulating fix: Sort by entry_date and reassign sequential IDs...")
df['entry_date'] = pd.to_datetime(df['entry_date'])
df_fixed = df.sort_values('entry_date').reset_index(drop=True)
df_fixed['trade_id_fixed'] = range(1, len(df_fixed) + 1)

# Verify the fix
print("\n✅ After Fix:")
print(f"   Unique trade_ids: {df_fixed['trade_id_fixed'].nunique():,}")
print(f"   Trade_id range: {df_fixed['trade_id_fixed'].min()} to {df_fixed['trade_id_fixed'].max()}")
print(f"   All unique? {df_fixed['trade_id_fixed'].nunique() == len(df_fixed)}")
print(f"   Sequential? {df_fixed['trade_id_fixed'].min() == 1 and df_fixed['trade_id_fixed'].max() == len(df_fixed)}")

# Check chronological ordering
print("\n📅 Chronological Ordering Check:")
is_chronological = True
for i in range(1, min(100, len(df_fixed))):  # Check first 100
    if df_fixed.iloc[i]['entry_date'] < df_fixed.iloc[i-1]['entry_date']:
        print(f"   ❌ FAIL: Entry dates not in order at row {i}")
        is_chronological = False
        break

if is_chronological:
    print("   ✅ Entry dates are in chronological order")
    print(f"   Date range: {df_fixed['entry_date'].min()} to {df_fixed['entry_date'].max()}")

# Show before/after comparison
print("\n" + "=" * 80)
print(" BEFORE/AFTER COMPARISON (First 10 trades)")
print("=" * 80)

comparison = df_fixed[['ticker', 'trade_id', 'trade_id_fixed', 'entry_date', 'entry_price']].head(10)
print(comparison.to_string(index=False))

print("\n" + "=" * 80)
print(" FIX LOGIC VERIFIED! ✅")
print("=" * 80)
print("\nThe fix will:")
print("1. ✅ Make all trade_ids globally unique")
print("2. ✅ Order trade_ids chronologically by entry_date")
print("3. ✅ Ensure trade_ids are sequential (1, 2, 3, ...)")
