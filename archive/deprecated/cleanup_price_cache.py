"""
Clean up price cache by removing ETF/REIT tickers (except SPY).

This ensures the price cache only contains operating companies,
eliminating the need for filtering during Dataset A/B creation.
"""
from pathlib import Path
from typing import Set

def get_etf_reit_tickers(etf_list_path: str = 'data/etf_fund_tickers.txt') -> Set[str]:
    """Load the ETF/REIT exclusion list."""
    etf_list_file = Path(etf_list_path)

    if not etf_list_file.exists():
        print(f"❌ ETF exclusion list not found: {etf_list_path}")
        return set()

    etf_tickers = set()
    with open(etf_list_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            # Extract ticker (first word before any whitespace or tab)
            ticker = line.split()[0] if line.split() else None
            if ticker:
                etf_tickers.add(ticker)

    print(f"Loaded {len(etf_tickers)} ETF/REIT tickers from exclusion list")
    return etf_tickers

def cleanup_price_cache(dry_run: bool = True, keep_spy: bool = True) -> None:
    """
    Remove ETF/REIT ticker files from price cache.

    Args:
        dry_run: If True, only show what would be deleted (don't actually delete)
        keep_spy: If True, preserve SPY (benchmark ticker)
    """
    price_cache_dir = Path('data/price')

    if not price_cache_dir.exists():
        print(f"❌ Price cache directory not found: {price_cache_dir}")
        return

    # Get ETF/REIT tickers to remove
    etf_tickers = get_etf_reit_tickers()

    if not etf_tickers:
        print("⚠️  No ETF tickers to remove")
        return

    # Scan price cache
    all_files = list(price_cache_dir.glob('*.parquet'))
    print(f"📂 Found {len(all_files)} ticker files in price cache")

    # Identify files to remove
    to_remove = []
    for file in all_files:
        ticker = file.stem  # Remove .parquet extension

        # Skip SPY if requested
        if keep_spy and ticker == 'SPY':
            continue

        # Check if ticker is in ETF/REIT list
        if ticker in etf_tickers:
            to_remove.append(file)

    # Report findings
    print("\n" + "=" * 80)
    print(f"CLEANUP SUMMARY")
    print("=" * 80)
    print(f"Total files in cache: {len(all_files)}")
    print(f"ETF/REIT files to remove: {len(to_remove)}")
    print(f"Operating company files to keep: {len(all_files) - len(to_remove)}")

    if keep_spy:
        print(f"Benchmark ticker (SPY): ✅ PRESERVED")

    if to_remove:
        print(f"\n📋 Files to remove (first 20):")
        for file in sorted(to_remove)[:20]:
            file_size_kb = file.stat().st_size / 1024
            print(f"  {file.name:<15} ({file_size_kb:>8.1f} KB)")

        if len(to_remove) > 20:
            print(f"  ... and {len(to_remove) - 20} more")

        # Calculate space savings
        total_size_kb = sum(f.stat().st_size for f in to_remove) / 1024
        total_size_mb = total_size_kb / 1024
        print(f"\n💾 Disk space to reclaim: {total_size_mb:.2f} MB")

    # Execute or dry run
    if dry_run:
        print("\n" + "=" * 80)
        print("🔍 DRY RUN MODE - No files were deleted")
        print("=" * 80)
        print("To actually delete these files, run:")
        print("  python cleanup_price_cache.py --execute")
    else:
        print("\n" + "=" * 80)
        print("⚠️  EXECUTING CLEANUP")
        print("=" * 80)

        deleted_count = 0
        failed_count = 0

        for file in to_remove:
            try:
                file.unlink()
                deleted_count += 1
            except Exception as e:
                print(f"❌ Failed to delete {file.name}: {e}")
                failed_count += 1

        print(f"\n✅ Cleanup complete!")
        print(f"  Deleted: {deleted_count} files")
        if failed_count > 0:
            print(f"  Failed: {failed_count} files")
        print(f"  Remaining: {len(all_files) - deleted_count} files")

def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Clean up price cache by removing ETF/REIT tickers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (show what would be deleted)
  python cleanup_price_cache.py

  # Actually delete the files
  python cleanup_price_cache.py --execute

  # Delete everything including SPY (not recommended)
  python cleanup_price_cache.py --execute --remove-spy
        """
    )

    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually delete files (default: dry run only)'
    )

    parser.add_argument(
        '--remove-spy',
        action='store_true',
        help='Also remove SPY benchmark ticker (not recommended)'
    )

    args = parser.parse_args()

    print("=" * 80)
    print(" PRICE CACHE CLEANUP - Remove ETF/REIT Tickers")
    print("=" * 80)

    if args.execute:
        print("\n⚠️  WARNING: This will permanently delete files!")
        response = input("Are you sure you want to continue? (yes/no): ")
        if response.lower() != 'yes':
            print("\n❌ Cleanup cancelled")
            return

    cleanup_price_cache(
        dry_run=not args.execute,
        keep_spy=not args.remove_spy
    )

    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
