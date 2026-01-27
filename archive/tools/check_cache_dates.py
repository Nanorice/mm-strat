import pandas as pd
from pathlib import Path

print("Checking price data cache date ranges...\n")

price_dir = Path('data/price')
parquet_files = list(price_dir.glob('*.parquet'))[:5]  # Check first 5

for file in parquet_files:
    try:
        df = pd.read_parquet(file)
        print(f"{file.name}: {df.index.min()} to {df.index.max()}")
    except Exception as e:
        print(f"{file.name}: Error - {e}")
