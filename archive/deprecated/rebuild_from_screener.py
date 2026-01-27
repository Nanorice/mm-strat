"""
Rebuild price cache using FMP screener to get ticker universe
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from src.data_engine import DataRepository

print("=" * 80)
print(" REBUILD PRICE CACHE FROM FMP SCREENER")
print("=" * 80)

# Initialize
data_repo = DataRepository()

# Get ticker universe from FMP screener
print("\nFetching ticker universe from FMP screener...")
tickers = data_repo.get_screener_universe()

if not tickers:
    print("❌ Failed to get tickers from FMP screener")
    print("\nAlternative: Get tickers from backup directory")
    
    backup_dirs = list(Path('data').glob('price_backup_*'))
    if backup_dirs:
        latest_backup = sorted(backup_dirs)[-1]
        print(f"Found backup: {latest_backup}")
        backup_files = list(latest_backup.glob("*.parquet"))
        tickers = [f.stem for f in backup_files if f.stem != 'SPY']
        print(f"Loaded {len(tickers)} tickers from backup")
    else:
        print("No backup found either. Exiting.")
        sys.exit(1)

print(f"\nTotal tickers to rebuild: {len(tickers)}")
print(f"Estimated time: ~{len(tickers) / 300:.1f} minutes")

# Rebuild
proceed = input("\nProceed with FMP rebuild? (yes/no): ")
if proceed.lower() != 'yes':
    print("Aborted.")
    sys.exit(0)

print("\nRebuilding cache with FMP...")
results = data_repo.update_cache(
    tickers=tickers,
    force=True,
    source='fmp',
    min_date='2003-01-01',
    max_workers=3  # Reduced from 5 to prevent 429 errors
)

# Results
success_count = sum(results.values())
failed_count = len(results) - success_count

print("\n" + "=" * 80)
print(" REBUILD COMPLETE")
print("=" * 80)
print(f"\n✅ Successful: {success_count}/{len(tickers)}")
print(f"❌ Failed: {failed_count}/{len(tickers)}")

if failed_count > 0:
    failed_tickers = [t for t, status in results.items() if not status]
    print(f"\nFailed tickers (first 50): {', '.join(failed_tickers[:50])}")
    
    with open("failed_tickers.txt", 'w') as f:
        f.write('\n'.join(failed_tickers))
    print(f"Full list saved to: failed_tickers.txt")

print("\nRun validate_all_cache.py to verify the rebuild")
