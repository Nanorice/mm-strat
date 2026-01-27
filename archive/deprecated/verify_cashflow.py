"""Quick script to check for cash flow data in fundamentals and datasets."""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

import pandas as pd
import config

print("=" * 80)
print(" CASH FLOW DATA VERIFICATION")
print("=" * 80)

# 1. Check raw fundamentals cache
print("\n1. FUNDAMENTALS CACHE")
print("-" * 80)
fund_files = list(config.FUNDAMENTALS_DIR.glob('*.parquet'))
if fund_files:
    sample = fund_files[0]
    df = pd.read_parquet(sample)
    print(f"   Sample: {sample.name}")
    print(f"   Shape: {df.shape}")
    
    if 'statement_type' in df.columns:
        types = df['statement_type'].value_counts().to_dict()
        print(f"   Statement types: {types}")
        has_cf = 'cash_flow' in types
        print(f"   Has cash_flow: {'YES ✅' if has_cf else 'NO ❌'}")
    
    cf_cols = ['operatingCashFlow', 'freeCashFlow', 'capitalExpenditure']
    present = [c for c in cf_cols if c in df.columns]
    print(f"   Cash flow columns: {present if present else 'NONE'}")

# 2. Check Dataset A
print("\n2. DATASET A")
print("-" * 80)
ds_a = config.DATA_DIR / 'ml' / 'dataset_a.parquet'
if ds_a.exists():
    df_a = pd.read_parquet(ds_a)
    print(f"   Shape: {df_a.shape}")
    
    cf_related = [c for c in df_a.columns if any(x in c.lower() for x in 
                 ['cash', 'accrual', 'roic', 'reinvest', 'efficient_growth'])]
    if cf_related:
        print(f"   ✅ CF metrics ({len(cf_related)} columns):")
        for col in sorted(cf_related):
            pct = df_a[col].notna().sum() / len(df_a) * 100
            print(f"      {col}: {pct:.1f}%")
    else:
        print(f"   ❌ NO CF metrics")
else:
    print(f"   ❌ Not found")

# 3. Check final
print("\n3. FINAL TRAINING DATASET")
print("-" * 80)
final = config.DATA_DIR / 'ml' / 'final_training_dataset.parquet'
if final.exists():
    df_f = pd.read_parquet(final)
    print(f"   Shape: {df_f.shape}")
    
    cf_related = [c for c in df_f.columns if any(x in c.lower() for x in 
                 ['cash', 'accrual', 'roic', 'reinvest', 'efficient_growth'])]
    if cf_related:
        print(f"   ✅ CF metrics ({len(cf_related)} columns):")
        for col in sorted(cf_related):
            pct = df_f[col].notna().sum() / len(df_f) * 100
            print(f"      {col}: {pct:.1f}%")
    else:
        print(f"   ❌ NO CF metrics")
else:
    print(f"   ❌ Not found")

print("\n" + "=" * 80)
