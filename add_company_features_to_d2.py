"""
Add Company Features (sector_id, industry_id) to D2
====================================================

This script:
1. Fetches company profiles for all tickers in D2
2. Adds sector_id and industry_id columns to D2
3. Saves the updated D2 with categorical features
"""

import sys
import logging
import pandas as pd
from pathlib import Path
from src.company_profile_engine import CompanyProfileEngine
from src.features import FeatureEngineer

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def add_company_features_to_d2():
    """Add company features to existing D2."""

    print("\n" + "=" * 70)
    print("ADDING COMPANY FEATURES TO D2")
    print("=" * 70)

    # 1. Load D2
    d2_path = Path('data/ml/d2_features.parquet')
    if not d2_path.exists():
        print(f"❌ D2 not found at {d2_path}")
        print("   Run: python model_runner.py data --steps scan,features")
        return False

    print(f"\n📂 Loading D2 from {d2_path}...")
    d2 = pd.read_parquet(d2_path)
    print(f"   Loaded: {len(d2):,} rows, {len(d2.columns)} columns")

    # 2. Get unique tickers
    if 'ticker' not in d2.columns:
        print("❌ 'ticker' column not found in D2")
        return False

    tickers = sorted(d2['ticker'].unique())
    print(f"\n🎯 Found {len(tickers)} unique tickers in D2")

    # 3. Fetch/load company profiles
    print(f"\n🔍 Fetching company profiles...")
    try:
        profile_engine = CompanyProfileEngine()

        # Try to load from cache first
        profiles_df = profile_engine.get_company_profiles(use_cache=True)

        if profiles_df is None or len(profiles_df) == 0:
            print("   No cached profiles found, fetching from API...")
            print(f"   This will take ~{len(tickers) * 0.3:.0f} seconds (rate limited)")
            profiles_df = profile_engine.fetch_all_profiles(tickers, show_progress=True)

            if profiles_df is None or len(profiles_df) == 0:
                print("❌ Failed to fetch profiles")
                return False
        else:
            print(f"   ✅ Loaded {len(profiles_df)} profiles from cache")

            # Check if we need to fetch missing tickers
            cached_tickers = set(profiles_df['symbol'].unique())
            missing_tickers = [t for t in tickers if t not in cached_tickers]

            if missing_tickers:
                print(f"   ⚠️  {len(missing_tickers)} tickers not in cache, fetching...")
                new_profiles = profile_engine.fetch_all_profiles(missing_tickers, show_progress=True)
                if new_profiles is not None and len(new_profiles) > 0:
                    profiles_df = pd.concat([profiles_df, new_profiles], ignore_index=True)
                    # Update cache
                    profile_engine.profiles_file.parent.mkdir(parents=True, exist_ok=True)
                    profiles_df.to_parquet(profile_engine.profiles_file, index=False)
                    print(f"   ✅ Updated cache with {len(new_profiles)} new profiles")

    except Exception as e:
        print(f"❌ Error fetching profiles: {e}")
        import traceback
        traceback.print_exc()
        return False

    # 4. Check required columns
    required_cols = ['symbol', 'sector_id', 'industry_id']
    missing_cols = [c for c in required_cols if c not in profiles_df.columns]
    if missing_cols:
        print(f"❌ Missing columns in profiles: {missing_cols}")
        return False

    print(f"\n✅ Profiles ready:")
    print(f"   sector_id range: [{profiles_df['sector_id'].min()}, {profiles_df['sector_id'].max()}]")
    print(f"   industry_id range: [{profiles_df['industry_id'].min()}, {profiles_df['industry_id'].max()}]")
    print(f"   Unique sectors: {profiles_df['sector_id'].nunique()}")
    print(f"   Unique industries: {profiles_df['industry_id'].nunique()}")

    # 5. Merge profiles into D2
    print(f"\n🔗 Merging company features into D2...")

    # Prepare profile lookup (ticker -> sector_id, industry_id)
    profile_lookup = profiles_df[['symbol', 'sector_id', 'industry_id']].drop_duplicates('symbol')
    profile_lookup = profile_lookup.rename(columns={'symbol': 'ticker'})

    # Merge
    d2_with_company = d2.merge(
        profile_lookup,
        on='ticker',
        how='left'
    )

    # Fill missing with -1 (unknown category)
    d2_with_company['sector_id'] = d2_with_company['sector_id'].fillna(-1).astype(int)
    d2_with_company['industry_id'] = d2_with_company['industry_id'].fillna(-1).astype(int)

    # Check results
    n_missing_sector = (d2_with_company['sector_id'] == -1).sum()
    n_missing_industry = (d2_with_company['industry_id'] == -1).sum()

    print(f"   ✅ Merged company features:")
    print(f"      Total rows: {len(d2_with_company):,}")
    print(f"      Missing sector_id: {n_missing_sector:,} ({n_missing_sector/len(d2_with_company)*100:.1f}%)")
    print(f"      Missing industry_id: {n_missing_industry:,} ({n_missing_industry/len(d2_with_company)*100:.1f}%)")

    # 6. Save updated D2
    print(f"\n💾 Saving updated D2 with company features...")

    # Backup original
    backup_path = d2_path.with_suffix('.backup.parquet')
    if not backup_path.exists():
        d2.to_parquet(backup_path, index=False)
        print(f"   📦 Backup saved to {backup_path}")

    # Save updated D2
    d2_with_company.to_parquet(d2_path, index=False)
    print(f"   ✅ Saved to {d2_path}")
    print(f"   New shape: {d2_with_company.shape}")
    print(f"   New columns added: sector_id, industry_id")

    # 7. Verification
    print(f"\n✅ VERIFICATION")
    print("=" * 70)
    d2_check = pd.read_parquet(d2_path)
    assert 'sector_id' in d2_check.columns, "sector_id not in saved D2"
    assert 'industry_id' in d2_check.columns, "industry_id not in saved D2"
    print(f"   ✅ sector_id column present: {d2_check['sector_id'].dtype}")
    print(f"   ✅ industry_id column present: {d2_check['industry_id'].dtype}")
    print(f"   ✅ D2 ready for M01_v2 training with categorical features!")

    return True


if __name__ == '__main__':
    try:
        success = add_company_features_to_d2()
        if success:
            print("\n" + "=" * 70)
            print("SUCCESS! Next steps:")
            print("=" * 70)
            print("1. Run the test:")
            print("   python test_categorical_support.py")
            print()
            print("2. Train M01_v2:")
            print("   python model_runner.py train --model m01_v2 --feature-set M01_V2_FEATURES")
            print("=" * 70)
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)
        sys.exit(1)
