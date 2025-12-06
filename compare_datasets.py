"""Compare sequential vs vectorized dataset B results"""
import pandas as pd

# Load both datasets
df_seq = pd.read_parquet('data/ml/dataset_b.parquet')
df_vec = pd.read_parquet('data/ml/dataset_b_2d_comp.parquet')

print("=" * 80)
print(" DATASET COMPARISON")
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

# Compare column names
print("\n" + "=" * 80)
print(" COLUMN COMPARISON")
print("=" * 80)
seq_cols = set(df_seq.columns)
vec_cols = set(df_vec.columns)
print(f"\nSequential columns: {len(seq_cols)}")
print(f"Vectorized columns: {len(vec_cols)}")
if seq_cols != vec_cols:
    print(f"\nMissing in Sequential: {vec_cols - seq_cols}")
    print(f"Missing in Vectorized: {seq_cols - vec_cols}")
else:
    print("\n✓ Column sets are identical")

# Sample comparison
print("\n" + "=" * 80)
print(" SAMPLE TRADE COMPARISON")
print("=" * 80)

# Get common trades by ticker+entry_date
df_seq['key'] = df_seq['ticker'] + '_' + df_seq['entry_date'].astype(str)
df_vec['key'] = df_vec['ticker'] + '_' + df_vec['entry_date'].astype(str)

common_keys = set(df_seq['key']) & set(df_vec['key'])
seq_only = set(df_seq['key']) - set(df_vec['key'])
vec_only = set(df_vec['key']) - set(df_seq['key'])

print(f"\nCommon trades: {len(common_keys)}")
print(f"Sequential-only trades: {len(seq_only)}")
print(f"Vectorized-only trades: {len(vec_only)}")

# Show examples of differences
if seq_only:
    print("\nExample Sequential-only trades:")
    sample_seq = df_seq[df_seq['key'].isin(list(seq_only)[:5])][['ticker', 'entry_date', 'exit_date', 'label']]
    print(sample_seq.to_string(index=False))

if vec_only:
    print("\nExample Vectorized-only trades:")
    sample_vec = df_vec[df_vec['key'].isin(list(vec_only)[:5])][['ticker', 'entry_date', 'exit_date', 'label']]
    print(sample_vec.to_string(index=False))

# Compare matching trades
if common_keys:
    print("\n" + "=" * 80)
    print(" MATCHING TRADE COMPARISON")
    print("=" * 80)
    
    # Get a sample of common trades
    sample_keys = list(common_keys)[:10]
    seq_sample = df_seq[df_seq['key'].isin(sample_keys)].sort_values('key')
    vec_sample = df_vec[df_vec['key'].isin(sample_keys)].sort_values('key')
    
    # Compare key fields
    comparison_cols = ['ticker', 'entry_date', 'exit_date', 'exit_reason', 'return_pct', 'label']
    for col in comparison_cols:
        if col in seq_sample.columns and col in vec_sample.columns:
            mismatches = (seq_sample[col].values != vec_sample[col].values).sum()
            if mismatches > 0:
                print(f"\n⚠️  {col}: {mismatches} mismatches found in sample")
                for idx, (s_val, v_val) in enumerate(zip(seq_sample[col].values, vec_sample[col].values)):
                    if s_val != v_val:
                        ticker = seq_sample.iloc[idx]['ticker']
                        entry = seq_sample.iloc[idx]['entry_date']
                        print(f"    {ticker} {entry}: seq={s_val}, vec={v_val}")

print("\n" + "=" * 80)
