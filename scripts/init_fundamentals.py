"""
Initialize Full Fundamental Dataset

Simple wrapper script to fetch fundamental data for all tickers in price folder.
Runs with sensible defaults and provides clear progress feedback.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from src.fundamental_engine import FundamentalEngine
import config


def main():
    """Initialize fundamental data for all tickers in price folder."""
    
    print("=" * 80)
    print(" FUNDAMENTAL DATA INITIALIZATION")
    print("=" * 80)
    print()
    
    # Initialize engine
    try:
        engine = FundamentalEngine()
    except ValueError as e:
        print(f"❌ Error: {e}")
        print("\nPlease set FMP_API_KEY in your .env file.")
        sys.exit(1)
    
    # Get tickers from price folder
    print("🔍 Discovering tickers from price folder...")
    price_files = list(config.PRICE_DATA_DIR.glob('*.parquet'))
    
    if not price_files:
        print(f"❌ No price data found in {config.PRICE_DATA_DIR}")
        print("\nPlease run data update first:")
        print("  python -c \"from src.data_engine import DataRepository; repo = DataRepository(); repo.update_cache(repo.update_universe())\"")
        sys.exit(1)
    
    # Extract tickers (exclude benchmark)
    tickers = [f.stem for f in price_files if f.stem != config.BENCHMARK_TICKER]
    tickers = sorted(tickers)
    
    print(f"✅ Found {len(tickers)} tickers")
    print()
    
    # Show what will be fetched
    already_cached = [t for t in tickers if not engine._is_cache_stale(config.FUNDAMENTALS_DIR / f"{t}.parquet")]
    to_fetch = [t for t in tickers if engine._is_cache_stale(config.FUNDAMENTALS_DIR / f"{t}.parquet")]
    
    if already_cached:
        print(f"📦 Already cached: {len(already_cached)} tickers")
    if to_fetch:
        print(f"🚀 Will fetch: {len(to_fetch)} tickers")
    else:
        print("✅ All tickers are already up-to-date!")
        print("\nUse --force flag to refresh all data:")
        print("  python build_fundamentals.py --force")
        return
    
    # Estimate time
    total_calls = len(to_fetch) * 2  # 2 calls per ticker (income + balance)
    batches = (len(to_fetch) - 1) // config.FMP_FUNDAMENTAL_BATCH_SIZE + 1
    estimated_minutes = (batches * config.FMP_FUNDAMENTAL_BATCH_DELAY) / 60
    
    print()
    print(f"📊 Estimated:")
    print(f"   API calls: {total_calls}")
    print(f"   Batches: {batches}")
    print(f"   Time: ~{estimated_minutes:.1f} minutes")
    print()
    
    # Confirm for large batches
    if len(to_fetch) > 50:
        response = input(f"⚠️  Proceed with fetching {len(to_fetch)} tickers? (y/n): ")
        if response.lower() != 'y':
            print("Cancelled.")
            return
        print()
    
    # Run the fetch
    print("🚀 Starting fundamental data fetch...")
    print()
    
    results = engine.update_fundamentals_cache(
        tickers=tickers,
        force=False,
        show_progress=True
    )
    
    # Summary
    print()
    print("=" * 80)
    print(" SUMMARY")
    print("=" * 80)
    
    success_count = sum(results.values())
    failed_count = len(results) - success_count
    
    print(f"✅ Success: {success_count}/{len(results)} tickers ({success_count/len(results)*100:.1f}%)")
    
    if failed_count > 0:
        print(f"❌ Failed: {failed_count} tickers")
        failed_tickers = [t for t, success in results.items() if not success]
        print(f"   {', '.join(failed_tickers[:10])}")
        if failed_count > 10:
            print(f"   ... and {failed_count - 10} more")
    
    # Cache stats
    stats = engine.get_cache_stats()
    print()
    print(f"📊 Cache Statistics:")
    print(f"   Total tickers: {stats['total_tickers']}")
    print(f"   Total size: {stats['total_size_mb']:.2f} MB")
    print(f"   Average size: {stats['avg_size_kb']:.2f} KB/ticker")
    
    print()
    print(f"💾 Location: {config.FUNDAMENTALS_DIR}")
    print()
    
    # Next steps
    if success_count == len(results):
        print("✅ All done! Next steps:")
        print("   1. View data: python view_fundamentals.py AAPL")
        print("   2. Check stats: python build_fundamentals.py --show-stats")
        print("   3. Integrate with Dataset A: python build_dataset_a.py --include-fundamentals")
    else:
        print("⚠️  Some tickers failed. This is normal for:")
        print("   - ETFs (SPY, QQQ, etc.)")
        print("   - REITs (different reporting)")
        print("   - Foreign companies")
        print("   - Recently IPO'd stocks")
    
    print("=" * 80)


if __name__ == "__main__":
    main()
