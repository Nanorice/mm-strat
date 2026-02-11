import sys
from pathlib import Path
sys.path.append('src')

from src.data_engine import DataRepository

repo = DataRepository()

print("Testing update_universe()...")
tickers = repo.update_universe(source='PRICE_FOLDER')
universe_files = [t for t in tickers if t.startswith('universe_')]

if universe_files:
    print(f"FAILED: Found universe files in tickers: {universe_files}")
else:
    print("PASS: No universe files in update_universe()")

print("\nTesting get_cached_tickers()...")
cached = repo.get_cached_tickers()
cached_universe = [t for t in cached if t.startswith('universe_')]

if cached_universe:
    print(f"FAILED: Found universe files in cached tickers: {cached_universe}")
else:
    print("PASS: No universe files in get_cached_tickers()")

# Check total count
print(f"\nTotal tickers: {len(tickers)}")
