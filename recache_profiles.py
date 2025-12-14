#!/usr/bin/env python
"""
Recache all company profiles with industry_id and sector_id mappings.
This script forces a refresh of all profiles to ensure they have the new ID columns.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.append(str(project_root))

from src.company_profile_engine import CompanyProfileEngine
import config

def main():
    """Recache all company profiles with industry/sector IDs."""

    print("🏢 COMPANY PROFILE RECACHE")
    print("=" * 80)
    print("\nThis will refresh ALL profiles to add industry_id and sector_id columns.\n")

    # Initialize engine
    engine = CompanyProfileEngine()

    # Get all tickers from price folder
    price_files = list(config.PRICE_DATA_DIR.glob('*.parquet'))
    tickers = [f.stem for f in price_files if f.stem != config.BENCHMARK_TICKER]

    print(f"Found {len(tickers)} tickers in price cache")

    # Confirm with user
    response = input(f"\nRecache all {len(tickers)} profiles? (y/N): ")
    if response.lower() != 'y':
        print("Cancelled.")
        return

    print(f"\n🚀 Starting recache with 10 parallel workers...")
    print(f"   Estimated time: ~{len(tickers) / 300:.1f} minutes at 300 calls/min\n")

    # Force refresh all profiles
    results = engine.update_profiles_cache(
        tickers=tickers,
        force=True,
        max_workers=10
    )

    # Summary
    success_count = sum(results.values())
    fail_count = len(results) - success_count

    print(f"\n✅ Recache complete!")
    print(f"\n📊 Results:")
    print(f"   Successful: {success_count}/{len(tickers)} ({success_count/len(tickers)*100:.1f}%)")
    print(f"   Failed: {fail_count}")

    if fail_count > 0:
        failed_tickers = [t for t, success in results.items() if not success]
        print(f"\n⚠️  Failed tickers ({len(failed_tickers)}):")
        print(f"   {', '.join(failed_tickers[:20])}")
        if len(failed_tickers) > 20:
            print(f"   ... and {len(failed_tickers) - 20} more")

    # Verify industry_id/sector_id columns
    print(f"\n🔍 Verifying columns...")
    profiles = engine.get_company_profiles(use_cache=True)

    if 'industry_id' in profiles.columns and 'sector_id' in profiles.columns:
        print(f"   ✓ industry_id column present")
        print(f"   ✓ sector_id column present")
        print(f"\n   Industry IDs: {profiles['industry_id'].nunique()} unique values")
        print(f"   Sector IDs: {profiles['sector_id'].nunique()} unique values")
    else:
        print(f"   ✗ Missing ID columns!")
        print(f"   Available columns: {list(profiles.columns)}")

if __name__ == "__main__":
    main()
