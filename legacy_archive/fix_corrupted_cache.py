"""
Fix Corrupted Cache Files
Deletes corrupted cache files and re-downloads them with validation.
"""

import json
import sys
from pathlib import Path
from typing import List, Dict
import pandas as pd

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.data_engine import DataRepository


def load_corrupted_files_list(json_path: str = 'data/corrupted_cache_files.json') -> List[str]:
    """
    Load list of corrupted files from JSON report.

    Args:
        json_path: Path to corrupted files JSON report

    Returns:
        List of ticker symbols with corrupted cache files
    """
    report_file = Path(json_path)

    if not report_file.exists():
        print(f"Error: Corrupted files report not found at {report_file}")
        print("\nPlease run IPO validation first:")
        print("  python data_health_analyzer.py --ipo-validation")
        return []

    with open(report_file, 'r') as f:
        report = json.load(f)

    # Extract tickers from problematic files (critical issues only)
    corrupted_tickers = []

    for file_info in report['problematic_files']:
        if file_info['severity'] == 'critical':
            corrupted_tickers.append(file_info['ticker'])

    return corrupted_tickers


def delete_corrupted_files(tickers: List[str], dry_run: bool = True) -> Dict:
    """
    Delete corrupted cache files.

    Args:
        tickers: List of ticker symbols to delete
        dry_run: If True, only show what would be deleted

    Returns:
        Dictionary with deletion results
    """
    price_dir = Path(config.PRICE_DATA_DIR)
    deleted = []
    not_found = []

    print("=" * 80)
    print(f" {'[DRY RUN] ' if dry_run else ''}DELETING CORRUPTED CACHE FILES")
    print("=" * 80)

    for ticker in tickers:
        cache_file = price_dir / f"{ticker}.parquet"

        if cache_file.exists():
            print(f"  {'[DRY RUN] ' if dry_run else ''}Deleting: {cache_file.name}")
            if not dry_run:
                cache_file.unlink()
            deleted.append(ticker)
        else:
            not_found.append(ticker)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Summary:")
    print(f"  Files deleted: {len(deleted)}")
    print(f"  Files not found: {len(not_found)}")

    if dry_run:
        print(f"\n⚠️  This was a dry run. Add --confirm to actually delete files.")

    return {
        'deleted': deleted,
        'not_found': not_found
    }


def reinstall_files(tickers: List[str], data_repo: DataRepository = None,
                   max_workers: int = 1, validate: bool = True) -> Dict:
    """
    Re-download deleted cache files with validation.

    Args:
        tickers: List of ticker symbols to re-download
        data_repo: DataRepository instance (creates new if None)
        max_workers: Number of parallel workers (default: 1 for safety)
        validate: Enable IPO validation during download

    Returns:
        Dictionary with download results
    """
    if data_repo is None:
        data_repo = DataRepository()

    print("\n" + "=" * 80)
    print(" RE-DOWNLOADING CACHE FILES WITH VALIDATION")
    print("=" * 80)

    print(f"\nSettings:")
    print(f"  Tickers to download: {len(tickers)}")
    print(f"  Parallel workers: {max_workers}")
    print(f"  IPO validation: {'Enabled' if validate else 'Disabled'}")
    print(f"  Data source: FMP API")

    print(f"\n⬇️  Starting download...\n")

    # Use update_cache with specific ticker list
    results = data_repo.update_cache(
        tickers=tickers,
        force=True,  # Force re-download
        source='fmp',
        max_workers=max_workers
    )

    # Count successes and failures
    successful = [t for t, status in results.items() if status]
    failed = [t for t, status in results.items() if not status]

    print("\n" + "=" * 80)
    print(" DOWNLOAD RESULTS")
    print("=" * 80)

    print(f"\n✅ Successfully downloaded: {len(successful)}/{len(tickers)}")
    print(f"❌ Failed: {len(failed)}/{len(tickers)}")

    if failed:
        print(f"\nFailed tickers:")
        for ticker in failed[:10]:
            print(f"  - {ticker}")
        if len(failed) > 10:
            print(f"  ... and {len(failed) - 10} more")

    return {
        'successful': successful,
        'failed': failed,
        'total': len(tickers)
    }


def verify_fixes(tickers: List[str]) -> Dict:
    """
    Verify that fixed files no longer have corruption issues.

    Args:
        tickers: List of ticker symbols to verify

    Returns:
        Dictionary with verification results
    """
    price_dir = Path(config.PRICE_DATA_DIR)

    print("\n" + "=" * 80)
    print(" VERIFYING FIXED FILES")
    print("=" * 80)

    verified = []
    still_corrupted = []
    missing = []

    for ticker in tickers:
        cache_file = price_dir / f"{ticker}.parquet"

        if not cache_file.exists():
            missing.append(ticker)
            continue

        try:
            df = pd.read_parquet(cache_file)

            # Basic checks
            if df.empty:
                still_corrupted.append((ticker, 'Empty dataframe'))
                continue

            if df.index.min().year < 1970:
                still_corrupted.append((ticker, f'Unrealistic start date: {df.index.min()}'))
                continue

            if df['Close'].min() <= 0:
                still_corrupted.append((ticker, 'Zero or negative prices'))
                continue

            verified.append(ticker)

        except Exception as e:
            still_corrupted.append((ticker, f'Load error: {str(e)}'))

    print(f"\n✅ Verified clean: {len(verified)}/{len(tickers)}")
    print(f"❌ Still corrupted: {len(still_corrupted)}/{len(tickers)}")
    print(f"⚠️  Missing files: {len(missing)}/{len(tickers)}")

    if still_corrupted:
        print(f"\nStill corrupted:")
        for ticker, reason in still_corrupted[:5]:
            print(f"  - {ticker}: {reason}")

    if missing:
        print(f"\nMissing files:")
        for ticker in missing[:5]:
            print(f"  - {ticker}")

    return {
        'verified': verified,
        'still_corrupted': [t for t, _ in still_corrupted],
        'missing': missing
    }


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Fix corrupted cache files by deleting and re-downloading"
    )

    parser.add_argument(
        '--confirm',
        action='store_true',
        help='Actually delete files (default is dry run)'
    )

    parser.add_argument(
        '--skip-delete',
        action='store_true',
        help='Skip deletion step (only re-download)'
    )

    parser.add_argument(
        '--skip-download',
        action='store_true',
        help='Skip download step (only delete)'
    )

    parser.add_argument(
        '--max-workers',
        type=int,
        default=1,
        help='Number of parallel workers for download (default: 1 for safety)'
    )

    parser.add_argument(
        '--corrupted-list',
        type=str,
        default='data/corrupted_cache_files.json',
        help='Path to corrupted files JSON report'
    )

    parser.add_argument(
        '--tickers',
        type=str,
        nargs='+',
        help='Specific tickers to fix (overrides JSON list)'
    )

    args = parser.parse_args()

    print("=" * 80)
    print(" CORRUPTED CACHE FILE FIX UTILITY")
    print("=" * 80)

    # Step 1: Load list of corrupted files
    if args.tickers:
        corrupted_tickers = args.tickers
        print(f"\nUsing manually specified tickers: {len(corrupted_tickers)}")
    else:
        print(f"\nLoading corrupted files list from: {args.corrupted_list}")
        corrupted_tickers = load_corrupted_files_list(args.corrupted_list)

    if not corrupted_tickers:
        print("\n❌ No corrupted files to fix. Exiting.")
        return

    print(f"\nFound {len(corrupted_tickers)} corrupted cache files")
    print(f"Corrupted tickers: {', '.join(corrupted_tickers[:10])}")
    if len(corrupted_tickers) > 10:
        print(f"  ... and {len(corrupted_tickers) - 10} more")

    # Step 2: Delete corrupted files
    if not args.skip_delete:
        dry_run = not args.confirm
        delete_results = delete_corrupted_files(corrupted_tickers, dry_run=dry_run)

        if dry_run:
            print("\n⚠️  Dry run complete. Re-run with --confirm to actually delete and re-download.")
            return
    else:
        print("\n⏭️  Skipping deletion step (--skip-delete)")

    # Step 3: Re-download files
    if not args.skip_download:
        data_repo = DataRepository()
        download_results = reinstall_files(
            corrupted_tickers,
            data_repo=data_repo,
            max_workers=args.max_workers,
            validate=True
        )
    else:
        print("\n⏭️  Skipping download step (--skip-download)")
        return

    # Step 4: Verify fixes
    verify_results = verify_fixes(corrupted_tickers)

    # Final summary
    print("\n" + "=" * 80)
    print(" FINAL SUMMARY")
    print("=" * 80)

    if verify_results['still_corrupted']:
        print(f"\n⚠️  {len(verify_results['still_corrupted'])} files are still corrupted!")
        print(f"   Consider running this script again or investigating manually.")
    elif verify_results['missing']:
        print(f"\n⚠️  {len(verify_results['missing'])} files are missing!")
        print(f"   These may have failed to download.")
    else:
        print(f"\n✅ All {len(corrupted_tickers)} files have been successfully fixed!")
        print(f"   Cache is now clean.")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
