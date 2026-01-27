"""
Price Cache Validation Script
Identifies corrupted, duplicate, and anachronistic price data in cache.
"""

import pandas as pd
import hashlib
from pathlib import Path
from collections import defaultdict
import json
from typing import Dict, List, Tuple
from tqdm import tqdm

# Known IPO dates for validation (expand as needed)
KNOWN_IPO_DATES = {
    'RIVN': '2021-11-10',
    'RKLB': '2021-08-25',
    'RKT': '2020-08-06',
    'RITM': '2015-06-25',
    'LOAR': '2002-07-31',
    'RL': '1997-06-12',
    'SNOW': '2020-09-16',
    'ABNB': '2020-12-10',
    'COIN': '2021-04-14',
    'DDOG': '2019-09-19',
    'ZS': '2018-03-16',
    'CRWD': '2019-06-12',
    'DKNG': '2020-04-24',
    'PLTR': '2020-09-30',
    'U': '2019-04-18',
}


def compute_data_hash(df: pd.DataFrame) -> str:
    """Compute MD5 hash of dataframe for duplicate detection."""
    return hashlib.md5(pd.util.hash_pandas_object(df).values).hexdigest()


def validate_cache(price_dir: Path = Path('data/price')) -> Dict:
    """
    Validate all price cache files.

    Returns:
        Dictionary with validation results
    """
    results = {
        'total_files': 0,
        'valid_files': 0,
        'duplicate_data': [],
        'anachronistic_data': [],
        'corrupted_data': [],
        'suspicious_prices': []
    }

    # Get all parquet files
    cache_files = list(price_dir.glob('*.parquet'))
    results['total_files'] = len(cache_files)

    print(f"Validating {len(cache_files)} cache files...\n")

    # Track data hashes to find duplicates
    hash_registry = {}

    # Validate each file
    for cache_file in tqdm(cache_files, desc="Validating cache"):
        ticker = cache_file.stem

        try:
            # Load data
            df = pd.read_parquet(cache_file)

            # VALIDATION 1: Check for duplicate data
            data_hash = compute_data_hash(df)

            if data_hash in hash_registry:
                results['duplicate_data'].append({
                    'ticker': ticker,
                    'duplicate_of': hash_registry[data_hash],
                    'file': str(cache_file)
                })
            else:
                hash_registry[data_hash] = ticker

            # VALIDATION 2: Check for anachronistic data (before IPO)
            if ticker in KNOWN_IPO_DATES:
                ipo_date = pd.to_datetime(KNOWN_IPO_DATES[ticker])
                data_start = df.index.min()

                if data_start < ipo_date:
                    years_before = (ipo_date - data_start).days / 365.25
                    results['anachronistic_data'].append({
                        'ticker': ticker,
                        'ipo_date': str(ipo_date.date()),
                        'data_starts': str(data_start.date()),
                        'years_before_ipo': round(years_before, 1),
                        'file': str(cache_file)
                    })

            # VALIDATION 3: Check for unrealistic prices
            if df['Close'].min() <= 0:
                results['suspicious_prices'].append({
                    'ticker': ticker,
                    'issue': 'Zero or negative prices',
                    'min_price': float(df['Close'].min()),
                    'file': str(cache_file)
                })

            if df['Close'].max() > 100000:
                results['suspicious_prices'].append({
                    'ticker': ticker,
                    'issue': 'Unrealistically high price',
                    'max_price': float(df['Close'].max()),
                    'file': str(cache_file)
                })

            # VALIDATION 4: Check for data corruption (all zeros, NaNs)
            if df['Close'].isna().all():
                results['corrupted_data'].append({
                    'ticker': ticker,
                    'issue': 'All NaN values',
                    'file': str(cache_file)
                })

            if (df['Close'] == 0).sum() > len(df) * 0.5:
                results['corrupted_data'].append({
                    'ticker': ticker,
                    'issue': 'More than 50% zero values',
                    'file': str(cache_file)
                })

            # Count as valid if no issues found for this ticker
            ticker_issues = sum([
                any(d['ticker'] == ticker for d in results['duplicate_data']),
                any(d['ticker'] == ticker for d in results['anachronistic_data']),
                any(d['ticker'] == ticker for d in results['suspicious_prices']),
                any(d['ticker'] == ticker for d in results['corrupted_data'])
            ])

            if ticker_issues == 0:
                results['valid_files'] += 1

        except Exception as e:
            results['corrupted_data'].append({
                'ticker': ticker,
                'issue': f'Failed to load: {str(e)}',
                'file': str(cache_file)
            })

    return results


def print_validation_report(results: Dict):
    """Print human-readable validation report."""

    print("\n" + "="*80)
    print(" PRICE CACHE VALIDATION REPORT")
    print("="*80)

    print(f"\nSummary:")
    print(f"   Total cache files: {results['total_files']}")
    print(f"   Valid files: {results['valid_files']} ({results['valid_files']/results['total_files']*100:.1f}%)")
    print(f"   Files with issues: {results['total_files'] - results['valid_files']}")

    # Duplicate data
    if results['duplicate_data']:
        print(f"\n[CRITICAL] DUPLICATE DATA ({len(results['duplicate_data'])} tickers):")
        print("   These tickers have identical price data (cache corruption):")

        # Group duplicates
        dup_groups = defaultdict(list)
        for dup in results['duplicate_data']:
            dup_groups[dup['duplicate_of']].append(dup['ticker'])

        for original, duplicates in dup_groups.items():
            print(f"\n   {original} data duplicated in: {', '.join(duplicates)}")

    # Anachronistic data
    if results['anachronistic_data']:
        print(f"\n[CRITICAL] ANACHRONISTIC DATA ({len(results['anachronistic_data'])} tickers):")
        print("   These tickers have data before their IPO date:")
        for item in results['anachronistic_data'][:10]:
            print(f"   {item['ticker']}: Data starts {item['data_starts']}, "
                  f"IPO was {item['ipo_date']} ({item['years_before_ipo']} years before)")
        if len(results['anachronistic_data']) > 10:
            print(f"   ... and {len(results['anachronistic_data']) - 10} more")

    # Suspicious prices
    if results['suspicious_prices']:
        print(f"\n[WARNING] SUSPICIOUS PRICES ({len(results['suspicious_prices'])} tickers):")
        for item in results['suspicious_prices'][:5]:
            print(f"   {item['ticker']}: {item['issue']}")
        if len(results['suspicious_prices']) > 5:
            print(f"   ... and {len(results['suspicious_prices']) - 5} more")

    # Corrupted data
    if results['corrupted_data']:
        print(f"\n[CRITICAL] CORRUPTED DATA ({len(results['corrupted_data'])} files):")
        for item in results['corrupted_data'][:5]:
            print(f"   {item['ticker']}: {item['issue']}")
        if len(results['corrupted_data']) > 5:
            print(f"   ... and {len(results['corrupted_data']) - 5} more")

    print("\n" + "="*80)

    # Recommendations
    total_issues = (len(results['duplicate_data']) +
                   len(results['anachronistic_data']) +
                   len(results['corrupted_data']))

    if total_issues > 0:
        print("\n[!] RECOMMENDED ACTIONS:")
        print("\n1. Delete corrupted cache files:")
        print("   python validate_price_cache.py --delete-corrupted")
        print("\n2. Rebuild cache with validation:")
        print("   python build_dataset_a.py --update-cache")
        print("\n3. Verify cache is clean:")
        print("   python validate_price_cache.py")
        print("\n4. Regenerate Dataset B:")
        print("   python build_dataset_b.py --start 2020-01-01 --end 2024-12-31")
    else:
        print("\n[OK] Cache validation PASSED - No issues found!")

    print("="*80 + "\n")


def delete_corrupted_files(results: Dict, dry_run: bool = True):
    """Delete corrupted cache files."""

    files_to_delete = []

    # Collect all corrupted files
    for item in results['duplicate_data']:
        files_to_delete.append(item['file'])

    for item in results['anachronistic_data']:
        files_to_delete.append(item['file'])

    for item in results['corrupted_data']:
        files_to_delete.append(item['file'])

    # Remove duplicates
    files_to_delete = list(set(files_to_delete))

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Deleting {len(files_to_delete)} corrupted cache files...\n")

    for file_path in files_to_delete:
        ticker = Path(file_path).stem
        print(f"  {'[DRY RUN] ' if dry_run else ''}Deleting {ticker}.parquet")

        if not dry_run:
            Path(file_path).unlink()

    if dry_run:
        print(f"\nDry run complete. Add --confirm to actually delete files.")
    else:
        print(f"\n✅ Deleted {len(files_to_delete)} corrupted cache files")


def save_report(results: Dict, output_file: str = 'cache_validation_report.json'):
    """Save validation results to JSON file."""
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n📝 Full report saved to: {output_file}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate price cache for corruption")
    parser.add_argument('--delete-corrupted', action='store_true',
                       help='Delete corrupted cache files (dry run by default)')
    parser.add_argument('--confirm', action='store_true',
                       help='Actually delete files (use with --delete-corrupted)')
    parser.add_argument('--output', type=str, default='cache_validation_report.json',
                       help='Output file for detailed report')

    args = parser.parse_args()

    # Run validation
    results = validate_cache()

    # Print report
    print_validation_report(results)

    # Save detailed report
    save_report(results, args.output)

    # Delete corrupted files if requested
    if args.delete_corrupted:
        dry_run = not args.confirm
        delete_corrupted_files(results, dry_run=dry_run)
