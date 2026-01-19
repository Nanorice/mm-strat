"""
Complete price cache rebuild using FMP
1. Backup current cache (optional)
2. Delete all corrupted price cache files
3. Rebuild entire cache using FMP parallel queries
"""
import sys
from pathlib import Path
import shutil
from datetime import datetime

sys.path.append(str(Path(__file__).parent))

from src.data_engine import DataRepository
import config

print("=" * 80)
print(" COMPLETE PRICE CACHE REBUILD WITH FMP")
print("=" * 80)

# Initialize
data_repo = DataRepository()
price_dir = Path(config.PRICE_DATA_DIR)

# Get all current tickers
print("\n--- Step 1: Scanning current cache ---")
all_cache_files = list(price_dir.glob("*.parquet"))
all_tickers = [f.stem for f in all_cache_files if f.stem != config.BENCHMARK_TICKER]

print(f"Found {len(all_tickers)} ticker cache files (excluding {config.BENCHMARK_TICKER})")

# Optional: Create backup
backup_choice = input("\nCreate backup of current cache before deletion? (y/n): ").lower()
if backup_choice == 'y':
    backup_dir = price_dir.parent / f"price_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"\nCreating backup at: {backup_dir}")
    shutil.copytree(price_dir, backup_dir)
    print("✅ Backup created")

# Delete all cache files
print("\n" + "=" * 80)
print(" Step 2: Deleting ALL Price Cache Files")
print("=" * 80)

confirm = input(f"\n⚠️  This will delete {len(all_cache_files)} cache files. Continue? (yes/no): ")
if confirm.lower() != 'yes':
    print("Aborted.")
    sys.exit(0)

deleted_count = 0
for cache_file in all_cache_files:
    try:
        cache_file.unlink()
        deleted_count += 1
    except Exception as e:
        print(f"Failed to delete {cache_file.name}: {e}")

print(f"\n✅ Deleted {deleted_count}/{len(all_cache_files)} cache files")

# Rebuild using FMP
print("\n" + "=" * 80)
print(" Step 3: Rebuilding Cache with FMP")
print("=" * 80)

print(f"\nRebuilding {len(all_tickers)} tickers using FMP:")
print(f"  - Parallel workers: 5")
print(f"  - Rate limit: 300 calls/min")
print(f"  - Historical data: from 2003-01-01")
print(f"  - Estimated time: ~{len(all_tickers) / 300:.1f} minutes")

proceed = input("\nProceed with rebuild? (yes/no): ")
if proceed.lower() != 'yes':
    print("Aborted.")
    sys.exit(0)

print("\nStarting rebuild...")
results = data_repo.update_cache(
    tickers=all_tickers,
    force=True,
    source='fmp',
    min_date='1990-01-01',
    max_workers=5
)

# Report results
print("\n" + "=" * 80)
print(" REBUILD COMPLETE")
print("=" * 80)

success_count = sum(results.values())
failed_count = len(results) - success_count

print(f"\n✅ Successful: {success_count}/{len(all_tickers)}")
print(f"❌ Failed: {failed_count}/{len(all_tickers)}")

if failed_count > 0:
    failed_tickers = [t for t, status in results.items() if not status]
    print(f"\nFailed tickers (first 20): {', '.join(failed_tickers[:20])}")
    
    # Save failed list to file
    failed_file = Path("failed_tickers.txt")
    with open(failed_file, 'w') as f:
        f.write('\n'.join(failed_tickers))
    print(f"\nFull failed list saved to: {failed_file}")

print("\n" + "=" * 80)
print(" Next Steps:")
print("  1. Run validate_all_cache.py to verify no more corruption")
print("  2. Rebuild Dataset B with fixed trade simulator")
print("=" * 80)
