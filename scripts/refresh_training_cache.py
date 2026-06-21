#!/usr/bin/env python3
"""
Refresh d2_training_cache table manually.

Usage:
    python scripts/refresh_training_cache.py
    python scripts/refresh_training_cache.py --db data/market_data.duckdb
    python scripts/refresh_training_cache.py --stats
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.managers.view_manager import ViewManager


def main():
    parser = argparse.ArgumentParser(description='Refresh d2_training_cache table')
    parser.add_argument(
        '--db',
        type=str,
        default='data/market_data.duckdb',
        help='Path to DuckDB database (default: data/market_data.duckdb)'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show cache statistics instead of refreshing'
    )
    args = parser.parse_args()

    vm = ViewManager(db_path=args.db)

    if args.stats:
        # Show cache statistics
        stats = vm.get_cache_stats()
        print("\n[STATS] Cache Statistics:")
        print(f"   Rows: {stats['row_count']:,}" if stats['row_count'] else "   Rows: 0 (cache empty)")
        if stats['cached_at']:
            print(f"   Last refreshed: {stats['cached_at']}")
            print(f"   Age: {stats['age_hours']:.1f} hours")
        else:
            print("   Last refreshed: Never")
        print()
    else:
        # Refresh cache
        print("\n[REFRESH] Refreshing d2_training_cache...")
        vm.refresh_cache(verbose=True)
        print()

        # Show updated stats
        stats = vm.get_cache_stats()
        print(f"[OK] Cache ready: {stats['row_count']:,} rows")
        print()


if __name__ == '__main__':
    main()
