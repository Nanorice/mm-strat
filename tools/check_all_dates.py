import pandas as pd

print("=" * 80)
print("CHECKING DATASET DATE RANGES")
print("=" * 80)

# Check Dataset A
print("\n1. Dataset A:")
try:
    df_a = pd.read_parquet('data/ml/dataset_a.parquet')
    print(f"   Date range: {df_a['date'].min()} to {df_a['date'].max()}")
    print(f"   Total rows: {len(df_a):,}")
    print(f"   Unique dates: {df_a['date'].nunique():,}")
except Exception as e:
    print(f"   Error: {e}")

# Check Dataset B
print("\n2. Dataset B:")
try:
    df_b = pd.read_parquet('data/ml/dataset_b.parquet')
    print(f"   Entry date range: {df_b['entry_date'].min()} to {df_b['entry_date'].max()}")
    print(f"   Total rows: {len(df_b):,}")
    print(f"   Unique entry dates: {df_b['entry_date'].nunique():,}")
except Exception as e:
    print(f"   Error: {e}")

# Check Merged Dataset
print("\n3. Merged Dataset:")
try:
    df_merged = pd.read_parquet('data/ml/merged_dataset.parquet')
    if 'entry_date' in df_merged.columns:
        print(f"   Entry date range: {df_merged['entry_date'].min()} to {df_merged['entry_date'].max()}")
    if 'date' in df_merged.columns:
        print(f"   Date range: {df_merged['date'].min()} to {df_merged['date'].max()}")
    print(f"   Total rows: {len(df_merged):,}")
except Exception as e:
    print(f"   Error: {e}")

# Check Final Training Dataset
print("\n4. Final Training Dataset:")
try:
    df_final = pd.read_parquet('data/ml/training_dataset_final.parquet')
    print(f"   Entry date range: {df_final['entry_date'].min()} to {df_final['entry_date'].max()}")
    print(f"   Total rows: {len(df_final):,}")
except Exception as e:
    print(f"   Error: {e}")

# Check merge report
print("\n5. Merge Report:")
try:
    import json
    with open('data/ml/merge_report.json', 'r') as f:
        report = json.load(f)
    print(f"   Dataset A rows: {report.get('dataset_a_rows', 'N/A'):,}")
    print(f"   Dataset B rows: {report.get('dataset_b_rows', 'N/A'):,}")
    print(f"   Merged rows: {report.get('merged_rows', 'N/A'):,}")
    if 'date_range' in report:
        print(f"   Date range: {report['date_range']}")
except Exception as e:
    print(f"   Error: {e}")

print("\n" + "=" * 80)
