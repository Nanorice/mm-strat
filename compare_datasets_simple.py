"""Compare sequential vs vectorized dataset B results - Simple version"""
import pandas as pd
import sys

# Load both datasets
try:
    df_seq = pd.read_parquet('data/ml/dataset_b.parquet')
    df_vec = pd.read_parquet('data/ml/dataset_b_2d_comp.parquet')
except Exception as e:
    print(f"Error loading data: {e}")
    sys.exit(1)

print("=" * 80)
print("DATASET COMPARISON")
print("=" * 80)

print("\nSEQUENTIAL (dataset_b.parquet):")
print(f"  Total Trades: {len(df_seq)}")
print(f"  Wins: {int(df_seq['label'].sum())}")
print(f"  Losses: {int((df_seq['label'] == 0).sum())}")
print(f"  Win Rate: {df_seq['label'].mean()*100:.2f}%")

print("\nVECTORIZED (dataset_b_2d_comp.parquet):")
print(f"  Total Trades: {len(df_vec)}")
print(f"  Wins: {int(df_vec['label'].sum())}")
print(f"  Losses: {int((df_vec['label'] == 0).sum())}")
print(f"  Win Rate: {df_vec['label'].mean()*100:.2f}%")

print("\nDIFFERENCE:")
trade_diff = len(df_vec) - len(df_seq)
win_diff = int(df_vec['label'].sum() - df_seq['label'].sum())
print(f"  Trade Difference: {trade_diff:+d} ({(trade_diff/len(df_seq))*100:+.1f}%)")
print(f"  Win Difference: {win_diff:+d}")

# Exit reason comparison
print("\n" + "=" * 80)
print("EXIT REASON COMPARISON")
print("=" * 80)

print("\nSequential Exit Reasons:")
seq_exits = df_seq['exit_reason'].value_counts()
for reason, count in seq_exits.items():
    print(f"  {reason}: {count} ({count/len(df_seq)*100:.1f}%)")

print("\nVectorized Exit Reasons:")
vec_exits = df_vec['exit_reason'].value_counts()
for reason, count in vec_exits.items():
    print(f"  {reason}: {count} ({count/len(df_vec)*100:.1f}%)")

# Compare column names
print("\n" + "=" * 80)
print("SCHEMA COMPARISON")
print("=" * 80)
seq_cols = set(df_seq.columns)
vec_cols = set(df_vec.columns)
print(f"\nSequential columns: {len(seq_cols)}")
print(f"Vectorized columns: {len(vec_cols)}")
if seq_cols != vec_cols:
    print(f"\nMissing in Sequential: {vec_cols - seq_cols}")
    print(f"Missing in Vectorized: {seq_cols - vec_cols}")
else:
    print("\nColumn sets are IDENTICAL")

# Key-based comparison
print("\n" + "=" * 80)
print("TRADE OVERLAP ANALYSIS")
print("=" * 80)

# Create unique keys for each trade
df_seq['key'] = df_seq['ticker'] + '_' + df_seq['entry_date'].astype(str)
df_vec['key'] = df_vec['ticker'] + '_' + df_vec['entry_date'].astype(str)

common_keys = set(df_seq['key']) & set(df_vec['key'])
seq_only = set(df_seq['key']) - set(df_vec['key'])
vec_only = set(df_vec['key']) - set(df_seq['key'])

print(f"\nCommon trades (same ticker+entry_date): {len(common_keys)}")
print(f"Sequential-only trades: {len(seq_only)}")
print(f"Vectorized-only trades: {len(vec_only)}")

print(f"\nOverlap percentage: {len(common_keys)/len(df_seq)*100:.1f}%")

# Show examples
if seq_only:
    print("\nExample Sequential-only trades (first 10):")
    sample = df_seq[df_seq['key'].isin(list(seq_only)[:10])][['ticker', 'entry_date', 'exit_date', 'exit_reason', 'label']]
    print(sample.to_string(index=False))

if vec_only:
    print("\nExample Vectorized-only trades (first 10):")
    sample = df_vec[df_vec['key'].isin(list(vec_only)[:10])][['ticker', 'entry_date', 'exit_date', 'exit_reason', 'label']]
    print(sample.to_string(index=False))

# For common trades, check for differences in outcomes
if len(common_keys) > 0:
    print("\n" + "=" * 80)
    print("COMMON TRADE OUTCOME COMPARISON")
    print("=" * 80)
    
    seq_common = df_seq[df_seq['key'].isin(common_keys)].set_index('key').sort_index()
    vec_common = df_vec[df_vec['key'].isin(common_keys)].set_index('key').sort_index()
    
    # Compare labels (wins vs losses)
    label_mismatches = (seq_common['label'] != vec_common['label']).sum()
    print(f"\nLabel mismatches (same entry, different outcome): {label_mismatches} ({label_mismatches/len(common_keys)*100:.1f}%)")
    
    # Compare exit dates
    seq_common['exit_date'] = pd.to_datetime(seq_common['exit_date'])
    vec_common['exit_date'] = pd.to_datetime(vec_common['exit_date'])
    exit_date_mismatches = (seq_common['exit_date'] != vec_common['exit_date']).sum()
    print(f"Exit date mismatches: {exit_date_mismatches} ({exit_date_mismatches/len(common_keys)*100:.1f}%)")
    
    # Compare exit reasons
    exit_reason_mismatches = (seq_common['exit_reason'] != vec_common['exit_reason']).sum()
    print(f"Exit reason mismatches: {exit_reason_mismatches} ({exit_reason_mismatches/len(common_keys)*100:.1f}%)")
    
    # Show examples of mismatches
    if label_mismatches > 0:
        print("\nExample label mismatches (first 5):")
        mismatch_keys = seq_common.index[seq_common['label'] != vec_common['label']][:5]
        for key in mismatch_keys:
            seq_row = seq_common.loc[key]
            vec_row = vec_common.loc[key]
            print(f"\n  {key}:")
            print(f"    Sequential: exit={seq_row['exit_date'].date()}, reason={seq_row['exit_reason']}, return={seq_row.get('return_pct', 'N/A'):.2f}%, label={seq_row['label']}")
            print(f"    Vectorized: exit={vec_row['exit_date'].date()}, reason={vec_row['exit_reason']}, return={vec_row.get('return_pct', 'N/A'):.2f}%, label={vec_row['label']}")

print("\n" + "=" * 80)
print("ANALYSIS COMPLETE")
print("=" * 80)
