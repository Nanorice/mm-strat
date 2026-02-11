import pandas as pd
from pathlib import Path
import config
from tqdm import tqdm

data_dir = config.PRICE_DATA_DIR
print(f"Checking files in {data_dir}")

files = list(data_dir.glob('*.parquet'))
print(f"Found {len(files)} parquet files")

count_multi = 0
count_other = 0

for f in tqdm(files):
    try:
        # Read index only for speed
        df = pd.read_parquet(f, columns=[])
        
        if isinstance(df.index, pd.MultiIndex):
            print(f"\n[MULTI-INDEX] {f.name}")
            print(f"Levels: {df.index.names}")
            print(f"Example: {df.index[0]}")
            count_multi += 1
            
        elif not isinstance(df.index, pd.DatetimeIndex):
            print(f"\n[NOT DATETIME] {f.name}")
            print(f"Type: {type(df.index)}")
            print(f"Example: {df.index[0]}")
            count_other += 1
            
    except Exception as e:
        print(f"\n[ERROR] {f.name}: {e}")

print(f"\nScan complete.")
print(f"MultiIndex files: {count_multi}")
print(f"Non-DatetimeIndex files: {count_other}")
