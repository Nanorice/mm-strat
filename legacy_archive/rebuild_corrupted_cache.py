"""
Rebuild corrupted price cache files using FMP
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from src.data_engine import DataRepository

print("=" * 80)
print(" REBUILDING CORRUPTED PRICE CACHE WITH FMP")
print("=" * 80)

# The 8 corrupted tickers
corrupted_tickers = ['ICE', 'ICFI', 'ICHR', 'IBP', 'IAS', 'IBTA', 'HYT', 'IBKR']

print(f"\nCorrupted tickers to rebuild: {', '.join(corrupted_tickers)}")

# Initialize data repository
data_repo = DataRepository()

# Delete corrupted cache files
print("\n" + "=" * 80)
print(" STEP 1: Deleting Corrupted Cache Files")
print("=" * 80)

for ticker in corrupted_tickers:
    cache_file = data_repo.price_dir / f"{ticker}.parquet"
    if cache_file.exists():
        cache_file.unlink()
        print(f"  ✓ Deleted: {ticker}.parquet")
    else:
        print(f"  - Not found: {ticker}.parquet")

# Rebuild using FMP
print("\n" + "=" * 80)
print(" STEP 2: Rebuilding with FMP (Parallel)")
print("=" * 80)

print("\nFMP parallel query settings:")
print(f"  - Workers: 5 (to stay under 300/min rate limit)")
print(f"  - Rate limit: 300 calls/min")
print(f"  - Historical data: from 1990-01-01")

results = data_repo.update_cache(
    tickers=corrupted_tickers,
    force=True,  # Force download even if cache exists
    source='fmp',  # Use FMP
    min_date='2003-01-01',  # Match Dataset B requirements
    max_workers=5  # Parallel workers
)

# Report results
print("\n" + "=" * 80)
print(" REBUILD RESULTS")
print("=" * 80)

success = [t for t, status in results.items() if status]
failed = [t for t, status in results.items() if not status]

print(f"\n✓ Successful: {len(success)}/{len(corrupted_tickers)}")
if success:
    print(f"  {', '.join(success)}")

if failed:
    print(f"\n✗ Failed: {len(failed)}/{len(corrupted_tickers)}")
    print(f"  {', '.join(failed)}")

# Verify the rebuilt data
if success:
    print("\n" + "=" * 80)
    print(" STEP 3: Verifying Rebuilt Data")
    print("=" * 80)
    
    import pandas as pd
    
    test_date = pd.Timestamp('2024-01-03')
    prices_on_date = {}
    
    for ticker in success:
        cache_file = data_repo.price_dir / f"{ticker}.parquet"
        if cache_file.exists():
            df = pd.read_parquet(cache_file)
            size = cache_file.stat().st_size
            
            print(f"\n  {ticker}:")
            print(f"    File size: {size:,} bytes")
            print(f"    Rows: {len(df)}")
            print(f"    Date range: {df.index.min().date()} to {df.index.max().date()}")
            
            if test_date in df.index:
                price = df.loc[test_date, 'Close']
                prices_on_date[ticker] = price
                print(f"    Price on {test_date.date()}: ${price:.2f}")
    
    # Check if all prices are different (not corrupted)
    if len(prices_on_date) > 1:
        unique_prices = len(set(prices_on_date.values()))
        if unique_prices == len(prices_on_date):
            print(f"\n✅ SUCCESS: All {len(prices_on_date)} tickers have different prices - NOT corrupted!")
        else:
            print(f"\n❌ WARNING: Only {unique_prices} unique prices across {len(prices_on_date)} tickers")

print("\n" + "=" * 80)
print(" REBUILD COMPLETE")
print("=" * 80)
