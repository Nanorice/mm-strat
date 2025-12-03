import pandas as pd
from pathlib import Path
from datetime import datetime

print("Checking recently updated price cache files...\n")

price_dir = Path('data/price')
parquet_files = list(price_dir.glob('*.parquet'))

# Sort by modification time, get 5 most recent
recent_files = sorted(parquet_files, key=lambda f: f.stat().st_mtime, reverse=True)[:10]

print(f"Checking {len(recent_files)} most recently modified files:\n")

for file in recent_files:
    try:
        df = pd.read_parquet(file)
        mod_time = datetime.fromtimestamp(file.stat().st_mtime)
        years = (df.index.max() - df.index.min()).days / 365.25
        
        # Check if it covers 2003
        covers_2003 = df.index.min() <= pd.Timestamp('2003-01-01')
        status = "✅" if covers_2003 else "❌"
        
        print(f"{status} {file.name}")
        print(f"   Date range: {df.index.min().date()} to {df.index.max().date()} ({years:.1f} years)")
        print(f"   Modified: {mod_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print()
    except Exception as e:
        print(f"❌ {file.name}: Error - {e}\n")
