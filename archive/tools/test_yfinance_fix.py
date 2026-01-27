"""Test if yfinance now downloads full historical data"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from src.data_engine import DataRepository

repo = DataRepository()

print("Testing yfinance download with period='max'...")
print("Downloading AAPL (should get data from ~1980s)...\n")

df = repo.get_ticker_data('AAPL', use_cache=False)

if df is not None:
    print(f"✅ Downloaded AAPL")
    print(f"   Date range: {df.index.min()} to {df.index.max()}")
    print(f"   Total rows: {len(df):,}")
    print(f"   Years of data: {(df.index.max() - df.index.min()).days / 365.25:.1f}")
else:
    print("❌ Failed to download AAPL")
