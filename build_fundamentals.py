"""
Build Fundamental Dataset - Initialize fundamental data for all tickers.

This script fetches income statements and balance sheets from FMP API
and caches them as parquet files for use in Dataset A construction.
"""

import argparse
import sys
import logging
from pathlib import Path
from typing import List

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from src.fundamental_engine import FundamentalEngine
import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_tickers_from_price_folder(price_dir: Path = None) -> List[str]:
    """
    Discover tickers from the price folder.
    
    Args:
        price_dir: Path to price data directory
        
    Returns:
        List of ticker symbols
    """
    price_dir = price_dir or config.PRICE_DATA_DIR
    
    if not price_dir.exists():
        raise FileNotFoundError(f"Price directory not found: {price_dir}")
    
    # Find all parquet files
    parquet_files = list(price_dir.glob('*.parquet'))
    
    if not parquet_files:
        raise ValueError(f"No price data found in {price_dir}")
    
    # Extract ticker symbols (filenames without .parquet)
    tickers = [f.stem for f in parquet_files]
    
    # Filter out benchmark ticker
    tickers = [t for t in tickers if t != config.BENCHMARK_TICKER]
    
    return sorted(tickers)


def print_header():
    """Print script header."""
    print("=" * 80)
    print(" FUNDAMENTAL DATASET BUILDER - FMP API Data Fetcher")
    print("=" * 80)
    print()


def print_summary(results: dict, engine: FundamentalEngine):
    """
    Print summary statistics after completion.
    
    Args:
        results: Dictionary of ticker -> success status
        engine: FundamentalEngine instance
    """
    total = len(results)
    success_count = sum(results.values())
    failed_count = total - success_count
    
    print("\n" + "=" * 80)
    print(" BUILD SUMMARY")
    print("=" * 80)
    print(f"✅ Successful: {success_count}/{total} tickers ({success_count/total*100:.1f}%)")
    
    if failed_count > 0:
        print(f"❌ Failed: {failed_count}/{total} tickers")
        failed_tickers = [ticker for ticker, success in results.items() if not success]
        print(f"   Failed tickers: {', '.join(failed_tickers[:10])}")
        if failed_count > 10:
            print(f"   ... and {failed_count - 10} more")
    
    # Cache statistics
    stats = engine.get_cache_stats()
    print(f"\n📊 Cache Statistics:")
    print(f"   Total tickers cached: {stats['total_tickers']}")
    print(f"   Total cache size: {stats['total_size_mb']:.2f} MB")
    print(f"   Average ticker size: {stats['avg_size_kb']:.2f} KB")
    if stats['oldest_cache']:
        print(f"   Oldest cache: {stats['oldest_cache'].strftime('%Y-%m-%d %H:%M')}")
        print(f"   Newest cache: {stats['newest_cache'].strftime('%Y-%m-%d %H:%M')}")
    
    print("\n💾 Data location: {}".format(config.FUNDAMENTALS_DIR))
    print("=" * 80)


def main():
    """Main entry point for fundamental dataset builder."""
    parser = argparse.ArgumentParser(
        description='Build fundamental dataset from FMP API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize all tickers from price folder
  python build_fundamentals.py
  
  # Force refresh all data
  python build_fundamentals.py --force
  
  # Update specific tickers only
  python build_fundamentals.py --tickers AAPL MSFT GOOGL
  
  # Use custom price folder
  python build_fundamentals.py --from-price-folder data/price
        """
    )
    
    parser.add_argument(
        '--tickers',
        nargs='+',
        help='Specific tickers to fetch (default: all tickers from price folder)'
    )
    
    parser.add_argument(
        '--from-price-folder',
        type=str,
        help='Path to price folder for ticker discovery (default: data/price)'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force refresh all data, ignoring cache'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=config.FMP_FUNDAMENTAL_BATCH_SIZE,
        help=f'Tickers per batch (default: {config.FMP_FUNDAMENTAL_BATCH_SIZE})'
    )
    
    parser.add_argument(
        '--show-stats',
        action='store_true',
        help='Show cache statistics and exit (do not fetch data)'
    )
    
    args = parser.parse_args()
    
    try:
        # Initialize engine
        engine = FundamentalEngine()
        
        # If just showing stats, do that and exit
        if args.show_stats:
            print_header()
            stats = engine.get_cache_stats()
            print(f"📊 Fundamental Data Cache Statistics\n")
            print(f"Total tickers: {stats['total_tickers']}")
            print(f"Total size: {stats['total_size_mb']:.2f} MB")
            print(f"Average size per ticker: {stats['avg_size_kb']:.2f} KB")
            if stats['oldest_cache']:
                print(f"Oldest cache: {stats['oldest_cache'].strftime('%Y-%m-%d %H:%M')}")
                print(f"Newest cache: {stats['newest_cache'].strftime('%Y-%m-%d %H:%M')}")
            print(f"\nAvailable tickers: {', '.join(engine.get_available_tickers()[:20])}")
            if stats['total_tickers'] > 20:
                print(f"... and {stats['total_tickers'] - 20} more")
            return
        
        print_header()
        
        # Determine ticker universe
        if args.tickers:
            tickers = args.tickers
            logger.info(f"Using {len(tickers)} manually specified tickers")
        else:
            price_dir = Path(args.from_price_folder) if args.from_price_folder else None
            tickers = get_tickers_from_price_folder(price_dir)
            logger.info(f"Discovered {len(tickers)} tickers from price folder")
        
        print(f"🎯 Target: {len(tickers)} tickers")
        print(f"📁 Output: {config.FUNDAMENTALS_DIR}")
        print(f"⚙️  Batch size: {args.batch_size} tickers")
        print(f"🔄 Force refresh: {'Yes' if args.force else 'No'}")
        print(f"⏱️  Rate limit: {config.FMP_FUNDAMENTAL_RATE_LIMIT} calls/minute")
        print()
        
        # Estimate time
        to_fetch_count = len(tickers) if args.force else len([
            t for t in tickers 
            if engine._is_cache_stale(config.FUNDAMENTALS_DIR / f"{t}.parquet")
        ])
        
        if to_fetch_count == 0:
            print("✅ All tickers are already cached and up-to-date!")
            print("\nUse --force to refresh all data.")
            return
        
        # Each ticker requires 2 API calls (income + balance sheet)
        total_calls = to_fetch_count * 2
        batches = (to_fetch_count - 1) // args.batch_size + 1
        estimated_time = batches * args.batch_size * 2 / config.FMP_FUNDAMENTAL_RATE_LIMIT * 60
        estimated_time += batches * config.FMP_FUNDAMENTAL_BATCH_DELAY
        
        print(f"📊 Estimated: {to_fetch_count} tickers to fetch ({total_calls} API calls)")
        print(f"⏳ Estimated time: ~{estimated_time/60:.1f} minutes")
        print()
        
        # Confirmation
        if to_fetch_count > 50 and not args.force:
            response = input(f"Proceed with fetching {to_fetch_count} tickers? (y/n): ")
            if response.lower() != 'y':
                print("Cancelled by user.")
                return
        
        print("🚀 Starting fundamental data fetch...\n")
        
        # Update cache
        engine.batch_size = args.batch_size
        results = engine.update_fundamentals_cache(
            tickers=tickers,
            force=args.force,
            show_progress=True
        )
        
        # Print summary
        print_summary(results, engine)
        
        # Exit code based on results
        if sum(results.values()) == len(results):
            print("\n✅ All tickers fetched successfully!")
            sys.exit(0)
        elif sum(results.values()) > 0:
            print("\n⚠️  Some tickers failed (see above)")
            sys.exit(1)
        else:
            print("\n❌ All tickers failed!")
            sys.exit(1)
            
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        print(f"\n❌ ERROR: {e}")
        print("\nPlease check your FMP_API_KEY in .env file.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
