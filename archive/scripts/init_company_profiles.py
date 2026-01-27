"""
Initialize Company Profile Dataset

Fetches company profile data (sector, industry, market cap, etc.) for all
tickers in the price folder. Stores in a single consolidated parquet file.

Usage:
    # Initial build (all tickers)
    python scripts/init_company_profiles.py

    # Force refresh all data
    python scripts/init_company_profiles.py --force

    # Update only stale tickers (>30 days old)
    python scripts/init_company_profiles.py --update
"""

import sys
from pathlib import Path
import argparse

sys.path.append(str(Path(__file__).parent.parent))

from src.company_profile_engine import CompanyProfileEngine
import config


def main():
    parser = argparse.ArgumentParser(description="Initialize company profile dataset")
    parser.add_argument('--force', action='store_true',
                       help='Force refresh all profiles')
    parser.add_argument('--update', action='store_true',
                       help='Update only stale profiles (>30 days)')
    args = parser.parse_args()

    print("=" * 80)
    print(" COMPANY PROFILE INITIALIZATION")
    print("=" * 80)
    print()

    # Initialize engine
    try:
        engine = CompanyProfileEngine()
    except ValueError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    # Get ticker universe from price folder
    print("🔍 Discovering tickers from price folder...")
    price_files = list(config.PRICE_DATA_DIR.glob('*.parquet'))

    if not price_files:
        print(f"❌ No price data found in {config.PRICE_DATA_DIR}")
        sys.exit(1)

    tickers = sorted([f.stem for f in price_files if f.stem != config.BENCHMARK_TICKER])
    print(f"✅ Found {len(tickers)} tickers")
    print()

    # Check cache status
    cache_exists = engine.profiles_file.exists()
    if cache_exists and not args.force:
        cache_info = engine.get_cache_info()
        print(f"📦 Existing cache: {cache_info['total_tickers']} tickers, "
              f"{cache_info['cache_age_days']} days old")

        if not args.update and cache_info['cache_age_days'] < config.COMPANY_PROFILE_CACHE_DAYS:
            print("✅ Cache is up-to-date!")
            print("\nUse --force to refresh all data")
            return

    # Estimate time
    estimated_minutes = len(tickers) / 300  # 300 calls/minute
    print(f"📊 Estimated time: ~{estimated_minutes:.1f} minutes ({len(tickers)} API calls)")
    print()

    # Confirm for large batches
    if len(tickers) > 100 and not args.update:
        response = input(f"⚠️  Proceed with fetching {len(tickers)} profiles? (y/n): ")
        if response.lower() != 'y':
            print("Cancelled.")
            return
        print()

    # Run the fetch
    print("🚀 Fetching company profiles...")
    print()

    results = engine.update_profiles_cache(tickers=tickers, force=args.force)

    # Summary
    print()
    print("=" * 80)
    print(" SUMMARY")
    print("=" * 80)

    success_count = sum(results.values())
    total = len(results)

    print(f"✅ Success: {success_count}/{total} tickers ({success_count/total*100:.1f}%)")

    if success_count < total:
        failed_count = total - success_count
        print(f"❌ Failed: {failed_count} tickers")
        failed_tickers = [t for t, success in results.items() if not success]
        print(f"   {', '.join(failed_tickers[:10])}")
        if failed_count > 10:
            print(f"   ... and {failed_count - 10} more")

    # Cache info
    cache_info = engine.get_cache_info()
    print()
    print(f"📊 Dataset Statistics:")
    print(f"   Total tickers: {cache_info['total_tickers']}")
    print(f"   File size: {cache_info['file_size_kb']:.1f} KB")
    print(f"   Unique sectors: {cache_info['unique_sectors']}")
    print(f"   Unique industries: {cache_info['unique_industries']}")
    print(f"   Last updated: {cache_info['last_updated']}")

    print()
    print(f"💾 Location: {config.COMPANY_INFO_DIR}")
    print("=" * 80)


if __name__ == "__main__":
    main()
