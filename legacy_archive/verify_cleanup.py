"""
Quick verification script to confirm cleanup was successful.
Run this before rebuilding datasets to verify the changes.
"""
from pathlib import Path

def verify_cleanup():
    print("=" * 80)
    print(" CLEANUP VERIFICATION")
    print("=" * 80)

    # 1. Check price cache
    price_cache_dir = Path('data/price')
    ticker_files = list(price_cache_dir.glob('*.parquet'))

    print(f"\n1. PRICE CACHE")
    print(f"   Total ticker files: {len(ticker_files)}")

    # Check for SPY
    spy_exists = (price_cache_dir / 'SPY.parquet').exists()
    print(f"   SPY (benchmark): {'✓ PRESENT' if spy_exists else '✗ MISSING (PROBLEM!)'}")

    # Load ETF list and check for remaining ETFs
    etf_list_path = Path('data/etf_fund_tickers.txt')
    etf_tickers = set()
    if etf_list_path.exists():
        with open(etf_list_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    ticker = line.split()[0] if line.split() else None
                    if ticker:
                        etf_tickers.add(ticker)

        remaining_etfs = [f.stem for f in ticker_files if f.stem in etf_tickers and f.stem != 'SPY']
        print(f"   ETF/REIT tickers remaining: {len(remaining_etfs)}")
        if remaining_etfs:
            print(f"   WARNING: {remaining_etfs[:10]}")
        else:
            print(f"   ✓ All ETFs/REITs removed")

    # 2. Check build_dataset_a.py
    print(f"\n2. BUILD_DATASET_A.PY")
    build_script = Path('build_dataset_a.py')
    if build_script.exists():
        content = build_script.read_text(encoding='utf-8')

        # Check if filter is commented out
        if '# from src.utils import filter_etfs' in content or '# tickers = filter_etfs(tickers)' in content:
            print(f"   ✓ filter_etfs() is DISABLED (commented out)")
        elif 'from src.utils import filter_etfs' in content and 'tickers = filter_etfs(tickers)' in content:
            print(f"   ✗ filter_etfs() is still ACTIVE (not commented)")
        else:
            print(f"   ? Cannot determine filter status")

    # 3. Verify problematic tickers
    print(f"\n3. PROBLEMATIC TICKERS")
    problematic = {
        'UTHR': 'United Therapeutics (biotech, should be KEPT)',
        'NTRS': 'Northern Trust (REIT, should be REMOVED)',
        'ESS': 'Essex Property Trust (REIT, should be REMOVED)',
        'AKR': 'Acadia Realty Trust (REIT, should be REMOVED)',
        'DLR': 'Digital Realty Trust (REIT, should be REMOVED)'
    }

    for ticker, description in problematic.items():
        ticker_file = price_cache_dir / f'{ticker}.parquet'
        exists = ticker_file.exists()
        expected = 'KEPT' in description

        status = '✓' if exists == expected else '✗'
        state = 'PRESENT' if exists else 'REMOVED'
        print(f"   {status} {ticker}: {state} ({description})")

    # Summary
    print("\n" + "=" * 80)
    print(" SUMMARY")
    print("=" * 80)

    all_good = (
        spy_exists and
        len(remaining_etfs) == 0 and
        (price_cache_dir / 'UTHR.parquet').exists() and
        not (price_cache_dir / 'NTRS.parquet').exists()
    )

    if all_good:
        print("✓ All checks passed!")
        print("\nYou can now rebuild Dataset A with:")
        print("  python build_dataset_a.py --start 2020-01-01 --end 2026-01-11 --include-fundamentals --n-jobs -1")
        print("\nExpected result: 0 missing snapshots when merging with Dataset B")
    else:
        print("✗ Some checks failed - please review the issues above")

    print("=" * 80)

if __name__ == "__main__":
    verify_cleanup()
