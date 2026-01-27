"""
Fix Sector Mapping in Existing Company Profiles Cache

This script updates the existing company_profiles.parquet file to use the stable
sector mapping from FMP's /available-sectors endpoint instead of the dynamically
generated sector_id values.

Usage:
    python scripts/fix_sector_mapping.py
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.company_profile_engine import CompanyProfileEngine
import pandas as pd


def main():
    print("=" * 80)
    print(" FIX SECTOR MAPPING IN COMPANY PROFILES")
    print("=" * 80)
    print()

    # Initialize engine
    try:
        engine = CompanyProfileEngine()
    except ValueError as e:
        print(f"[FAIL] Error: {e}")
        sys.exit(1)

    # Check if cache exists
    if not engine.profiles_file.exists():
        print(f"[FAIL] No existing cache found at {engine.profiles_file}")
        print("       Run 'python scripts/init_company_profiles.py' first")
        sys.exit(1)

    # Load existing profiles
    print(f"1. Loading existing profiles from {engine.profiles_file}...")
    try:
        profiles = pd.read_parquet(engine.profiles_file)
        print(f"   [OK] Loaded {len(profiles)} profiles")
        print(f"   Current unique sectors: {profiles['sector'].nunique()}")
        print(f"   Current sector_id range: {profiles['sector_id'].min()} to {profiles['sector_id'].max()}")
    except Exception as e:
        print(f"   [FAIL] Error loading cache: {e}")
        sys.exit(1)

    print()

    # Fetch stable sector mapping
    print("2. Fetching stable sector mapping from FMP...")
    try:
        sector_mapping = engine.get_sector_mapping(use_cache=False)
        if sector_mapping is None or sector_mapping.empty:
            print("   [FAIL] Failed to fetch sector mapping")
            sys.exit(1)
        print(f"   [OK] Fetched {len(sector_mapping)} sectors")
        print(f"   Sectors: {sector_mapping['sector'].tolist()}")
    except Exception as e:
        print(f"   [FAIL] Error: {e}")
        sys.exit(1)

    print()

    # Show mapping
    print("3. Sector ID Mapping:")
    for _, row in sector_mapping.iterrows():
        print(f"   {row['sector_id']:2d} -> {row['sector']}")

    print()

    # Re-merge with stable mapping
    print("4. Re-merging profiles with stable sector mapping...")
    try:
        # Remove old sector_id column
        if 'sector_id' in profiles.columns:
            profiles = profiles.drop(columns=['sector_id'])

        # Reset index for merge
        profiles = profiles.reset_index()

        # Merge with stable sector mapping
        profiles = profiles.merge(
            sector_mapping[['sector', 'sector_id']],
            on='sector',
            how='left'
        )

        # Fill missing sector_ids
        profiles['sector_id'] = profiles['sector_id'].fillna(-1).astype(int)

        # Restore index
        profiles = profiles.set_index('ticker')

        print(f"   [OK] Merged successfully")
        print(f"   New sector_id range: {profiles['sector_id'].min()} to {profiles['sector_id'].max()}")

        # Show sector distribution
        print("\n   Sector distribution:")
        sector_counts = profiles.groupby(['sector', 'sector_id']).size().sort_values(ascending=False)
        for (sector, sector_id), count in sector_counts.items():
            print(f"   [{sector_id:2d}] {sector:25s}: {count:4d} tickers")

    except Exception as e:
        print(f"   [FAIL] Error during merge: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print()

    # Save updated profiles
    print("5. Saving updated profiles...")
    try:
        profiles.to_parquet(engine.profiles_file)
        print(f"   [OK] Saved to {engine.profiles_file}")

        # Verify
        cache_info = engine.get_cache_info()
        print(f"   File size: {cache_info['file_size_kb']:.1f} KB")
        print(f"   Total tickers: {cache_info['total_tickers']}")
    except Exception as e:
        print(f"   [FAIL] Error saving: {e}")
        sys.exit(1)

    print()
    print("=" * 80)
    print(" SECTOR MAPPING FIXED SUCCESSFULLY")
    print("=" * 80)
    print()
    print("The company profiles cache now uses stable sector IDs from FMP.")
    print("sector_id values will remain consistent across future rebuilds.")


if __name__ == "__main__":
    main()
