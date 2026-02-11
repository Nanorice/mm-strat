"""
Data Curator - Daily Data Maintenance Script
=============================================
This script handles the entire data lifecycle for the Quantamental SEPA System.
It consolidates ticker universe updates, price/fundamental data refreshing,
and data health checks into a single maintenance interface.

Usage Examples:
    # Daily price update for S&P 500 (after market close)
    python data_curator.py --source sp500 --update-prices

    # Update specific tickers only
    python data_curator.py --tickers AAPL,NVDA,TSLA --update-all

    # Quarterly fundamental refresh (force update)
    python data_curator.py --source sp500 --update-fundamentals --force

    # Run only health check (earnings staleness, coverage, quality)
    python data_curator.py --health-check

    # Run from watchlist file
    python data_curator.py --tickers-file my_watchlist.txt --update-prices

    # Full refresh with all data types
    python data_curator.py --source sp500 --update-all --force

    # Use FMP screener with custom criteria
    python data_curator.py --source fmp_screener --market-cap-min 5000000000 --price-min 10 --update-prices

Universe Commands:
    # Update universe (append new data if exists, build if not)
    python data_curator.py --universe

    # Force full rebuild (for data quality issues)
    python data_curator.py --universe --force

    # Full rebuild with custom date range
    python data_curator.py --universe --force --universe-start-date 2020-01-01

    # Show universe statistics
    python data_curator.py --universe-stats

    # Get snapshot for a specific date (top 10 by RS rating)
    python data_curator.py --universe-snapshot 2024-01-15
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.data_engine import DataRepository
from src.fundamental_engine import FundamentalEngine
from src.company_profile_engine import CompanyProfileEngine
from data_health_analyzer import DataHealthAnalyzer
from src.macro_engine import MacroEngine
from src.universe_engine import UniverseEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("data_curator.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("DataCurator")


def get_tickers(
    source: str = 'sp500',
    custom_tickers: Optional[str] = None,
    tickers_file: Optional[str] = None,
    market_cap_min: int = 1_000_000_000,
    price_min: float = 5.0,
    volume_min: int = 100_000
) -> list:
    """
    Get tickers from various sources with priority:
    1. Custom tickers (--tickers) - highest priority
    2. Tickers file (--tickers-file)
    3. Universe source (--source)
    
    Args:
        source: Universe source ('sp500', 'fmp_screener', 'price_folder')
        custom_tickers: Comma-separated list of tickers
        tickers_file: Path to file containing tickers (one per line)
        market_cap_min: FMP screener minimum market cap
        price_min: FMP screener minimum price
        volume_min: FMP screener minimum volume
    
    Returns:
        List of ticker symbols
    """
    # Priority 1: Custom tickers from CLI
    if custom_tickers:
        tickers = [t.strip().upper() for t in custom_tickers.split(',') if t.strip()]
        print(f"   📋 Using {len(tickers)} custom tickers: {', '.join(tickers[:10])}{'...' if len(tickers) > 10 else ''}")
        return tickers
    
    # Priority 2: Tickers from file
    if tickers_file:
        file_path = Path(tickers_file)
        if not file_path.exists():
            raise FileNotFoundError(f"Tickers file not found: {tickers_file}")
        
        with open(file_path, 'r') as f:
            tickers = [line.strip().upper() for line in f if line.strip() and not line.startswith('#')]
        print(f"   📋 Loaded {len(tickers)} tickers from {tickers_file}")
        return tickers
    
    # Priority 3: Universe source
    source_map = {
        'price_folder': 'PRICE_FOLDER',
        'fmp_screener': 'FMP_SCREENER',
        'sp500': 'SSGA'
    }
    
    data_repo = DataRepository()
    
    # Configure FMP screener parameters if using that source
    if source == 'fmp_screener':
        config.FMP_SCREENER_PARAMS.update({
            'marketCapMoreThan': market_cap_min,
            'priceMoreThan': price_min,
            'volumeMoreThan': volume_min
        })
        print(f"   📋 FMP Screener filters: MarketCap>${market_cap_min:,}, Price>${price_min}, Volume>{volume_min:,}")
    
    tickers = data_repo.update_universe(source=source_map.get(source, 'SSGA'))
    print(f"   📋 Loaded {len(tickers)} tickers from {source}")
    return tickers


def update_prices(
    tickers: list,
    force: bool = False,
    skip_market_check: bool = False,
    max_workers: int = 5,
    from_date: Optional[str] = None
) -> dict:
    """
    Update price data cache for given tickers.
    
    Args:
        tickers: List of ticker symbols
        force: Force re-download all data
        skip_market_check: Bypass market hours safety check
        max_workers: Number of parallel workers
        from_date: Override start date for fetching (bypasses incremental logic)
                   Use when tickers have insufficient historical data.
                   Format: 'YYYY-MM-DD'. Default: None (use incremental fetching)
    
    Returns:
        Dict mapping ticker to success status
    """
    print("\n2️⃣  Updating Price Data...")
    
    # Check market hours safety
    from src.utils import get_latest_trading_day
    import pytz
    
    now_et = datetime.now(pytz.timezone('US/Eastern'))
    is_market_hours = 9 <= now_et.hour < 16 and now_et.weekday() < 5
    
    if is_market_hours and not skip_market_check and not force:
        print(f"   ⚠️  Market is OPEN ({now_et.strftime('%H:%M')} ET). Skipping price update to prevent incomplete daily bars.")
        print(f"      (Use --skip-market-check or --force to override)")
        return {t: False for t in tickers}
    
    if from_date:
        print(f"   📅 Using custom from_date: {from_date} (full historical fetch)")
    
    print(f"   🔧 Parallel workers: {max_workers}")
    print(f"   ⏱️  FMP rate limit: 300 calls/min (~5 tickers/sec max)")
    
    data_repo = DataRepository()
    
    # Ensure benchmark (SPY) is included in price updates
    # (It's often excluded from universe scans since it's an ETF/benchmark)
    if data_repo.benchmark_ticker and data_repo.benchmark_ticker not in tickers:
        tickers = list(tickers) + [data_repo.benchmark_ticker]

    results = data_repo.update_cache(
        tickers,
        force=force,
        max_workers=max_workers,
        from_date=from_date
    )
    success_count = sum(results.values())
    print(f"   ✅ Price update complete: {success_count}/{len(tickers)} updated")
    return results


def update_fundamentals(
    tickers: list,
    force: bool = False,
    max_workers: int = 10,
    use_earnings_calendar: bool = True
) -> dict:
    """
    Update fundamental data cache for given tickers.

    Smart Update (use_earnings_calendar=True):
    - Uses earnings calendar to detect new quarterly reports
    - Only fetches fundamentals for tickers with earnings after last cache update
    - Reduces API calls by 90-95% for steady-state maintenance

    Legacy Mode (use_earnings_calendar=False):
    - Only checks for missing cache files
    - No time-based staleness checks

    Args:
        tickers: List of ticker symbols
        force: Force re-download all data (disables earnings calendar)
        max_workers: Number of parallel workers
        use_earnings_calendar: Use earnings calendar for intelligent updates (default: True)

    Returns:
        Dict mapping ticker to success status
    """
    print("\n3️⃣  Updating Fundamental Data...")

    if use_earnings_calendar and not force:
        print("   📅 Using earnings calendar for intelligent updates...")

    fund_engine = FundamentalEngine()
    results = fund_engine.update_fundamentals_cache(
        tickers=tickers,
        force=force,
        max_workers=max_workers,
        use_earnings_calendar=use_earnings_calendar
    )
    success_count = sum(results.values())
    print(f"   ✅ Fundamentals update complete: {success_count}/{len(tickers)} updated")
    return results


def update_profiles(
    tickers: list,
    force: bool = False,
    max_workers: int = 10
) -> dict:
    """
    Update company profile cache for given tickers.
    
    Args:
        tickers: List of ticker symbols
        force: Force re-download all data
        max_workers: Number of parallel workers
    
    Returns:
        Dict mapping ticker to success status
    """
    print("\n4️⃣  Updating Company Profiles...")
    
    profile_engine = CompanyProfileEngine()
    results = profile_engine.update_profiles_cache(
        tickers=tickers,
        force=force,
        max_workers=max_workers
    )
    
    # Validation check
    cached_profiles = profile_engine.get_company_profiles(use_cache=True)
    if cached_profiles.empty:
        print("   ⚠️  Warning: Company profiles cache is empty!")
    else:
        missing_sector = cached_profiles['sector'].replace('', pd.NA).isna().sum()
        missing_mktcap = (cached_profiles['mktCap'] == 0).sum()
        print(f"   ✅ Profiles update complete. Cache size: {len(cached_profiles)}")
        print(f"      Missing Sectors: {missing_sector}")
        print(f"      Missing Market Cap: {missing_mktcap}")
    
    return results


def update_macro_data(force: bool = False) -> dict:
    """
    Update macroeconomic data cache (FRED series + VIX).

    Data includes:
    - WALCL: Fed Total Assets
    - WTREGEN: Treasury General Account
    - RRPONTSYD: Reverse Repo
    - BAMLH0A0HYM2: HY Credit Spread
    - VIX: Volatility Index

    Args:
        force: Force re-download all data

    Returns:
        Dict mapping series_id to row count
    """
    print("\n[5/6] Updating Macroeconomic Data...")

    macro_engine = MacroEngine()
    results = macro_engine.update_macro_cache(force=force)

    total_series = len(results)
    total_rows = sum(results.values())
    print(f"   [OK] Macro update complete: {total_series} series, {total_rows:,} total observations")

    for series_id, count in results.items():
        print(f"      {series_id}: {count:,} rows")

    return results


def run_health_check():
    """Run comprehensive data health analysis."""
    print("\n[6/6] Running Data Health Analysis...")
    analyzer = DataHealthAnalyzer()
    analyzer.run_full_analysis()


def update_universe(
    start_date: str = '2021-01-01',
    end_date: Optional[str] = None,
    max_workers: int = 8,
    force: bool = False
) -> None:
    """
    Update universe.parquet - smart mode with incremental append.

    Behavior:
    - If universe doesn't exist OR --force: Full rebuild from start_date
    - If universe exists: Append new data since last date in file

    Args:
        start_date: Start date for full rebuild (default: 2021-01-01)
        end_date: End date (default: today)
        max_workers: Parallel workers for loading (default: 8)
        force: Force full rebuild even if file exists
    """
    engine = UniverseEngine()
    stats = engine.get_universe_stats()
    file_exists = stats.get('status') != 'empty'

    if force or not file_exists:
        # Full rebuild
        mode = "REBUILD (--force)" if force else "BUILD (new file)"
        print(f"\n[UNIVERSE] {mode}")
        print(f"   Date range: {start_date} to {end_date or 'today'}")

        # Show which segments will be affected
        end_for_segments = end_date or datetime.now().strftime('%Y-%m-%d')
        segments = engine._get_segments_for_range(start_date, end_for_segments)
        print(f"   Segments to build: {', '.join(segments)}")

        if file_exists:
            print(f"   Existing: {stats['total_rows']:,} rows, {stats['unique_tickers']} tickers")
            print(f"   [WARN] This will overwrite affected segments!")

        start_time = time.time()
        results = engine.build_universe(
            start_date=start_date,
            end_date=end_date,
            max_workers=max_workers
        )
        elapsed = time.time() - start_time
        stats = engine.get_universe_stats()

        print(f"\n   [OK] Universe built successfully!")
        print(f"   Total rows: {stats['total_rows']:,}")
        print(f"   Tickers: {stats['unique_tickers']}")
        print(f"   Date range: {stats['date_range']}")
        print(f"   Total size: {stats['total_size_mb']:.1f} MB")
        print(f"   Time: {elapsed/60:.1f} minutes")

        # Show segment breakdown
        print(f"\n   Segments built:")
        for seg_name, row_count in sorted(results.items()):
            print(f"      {seg_name}: {row_count:,} rows")

    else:
        # Incremental append
        print(f"\n[UNIVERSE] APPEND (incremental update)")
        print(f"   Existing: {stats['total_rows']:,} rows, {stats['unique_tickers']} tickers")
        print(f"   Date range: {stats['date_range']}")

        # Get last date in universe
        last_date = pd.to_datetime(stats['date_range'].split(' to ')[1])
        append_start = (last_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        append_end = end_date or datetime.now().strftime('%Y-%m-%d')

        if append_start > append_end:
            print(f"   [OK] Universe is already up to date!")
            return

        print(f"   Appending: {append_start} to {append_end}")

        # Load new data and append
        from src.data_engine import DataRepository, CacheMode
        from src.features import FeatureEngineer

        repo = DataRepository(enable_validation=False)
        tickers = repo.update_universe(source='PRICE_FOLDER')
        benchmark = repo.get_benchmark_data(mode=CacheMode.CACHE_ONLY)
        feature_engine = FeatureEngineer(benchmark_data=benchmark)

        start_time = time.time()
        batch_data = repo.get_batch_data(tickers, max_workers=max_workers, mode=CacheMode.CACHE_ONLY)

        # Process and collect new data
        new_data = {}
        for ticker, df in batch_data.items():
            try:
                df_slice = df.loc[append_start:append_end]
                if len(df_slice) > 0:
                    new_data[ticker] = df_slice
            except Exception:
                continue

        if new_data:
            engine.append_daily(new_data)
            elapsed = time.time() - start_time
            new_stats = engine.get_universe_stats()
            rows_added = new_stats['total_rows'] - stats['total_rows']
            print(f"\n   [OK] Appended {rows_added:,} rows in {elapsed:.1f}s")
            print(f"   New total: {new_stats['total_rows']:,} rows")
            print(f"   Date range: {new_stats['date_range']}")
        else:
            print(f"   [OK] No new data to append")


def universe_stats() -> None:
    """Display universe.parquet statistics."""
    print("\n[UNIVERSE] Statistics...")

    engine = UniverseEngine()
    stats = engine.get_universe_stats()

    if stats.get('status') == 'empty':
        print("   [WARN] Universe is empty. Run --universe to create it.")
        return

    print(f"   Total rows: {stats['total_rows']:,}")
    print(f"   Unique tickers: {stats['unique_tickers']}")
    print(f"   Date range: {stats['date_range']}")
    print(f"   Total size: {stats['total_size_mb']:.1f} MB")

    # Show segment breakdown
    if 'segments' in stats:
        print(f"\n   Segments:")
        for seg_name, seg_stats in sorted(stats['segments'].items()):
            print(f"      {seg_name}: {seg_stats['rows']:,} rows, {seg_stats['size_mb']:.1f} MB ({seg_stats['date_range']})")


def universe_snapshot(query_date: str) -> None:
    """
    Get universe snapshot for a specific date.

    Args:
        query_date: Date to query (YYYY-MM-DD)
    """
    print(f"\n[UNIVERSE] Snapshot for {query_date}...")

    engine = UniverseEngine()
    stats = engine.get_universe_stats()

    if stats.get('status') == 'empty':
        print("   [WARN] Universe is empty. Run --build-universe to create it.")
        return

    try:
        snapshot = engine.get_snapshot(pd.to_datetime(query_date).date())

        if len(snapshot) == 0:
            print(f"   [WARN] No data for date {query_date}")
            return

        print(f"   Tickers: {len(snapshot)}")

        # Show top 10 by rs_rating
        if 'rs_rating' in snapshot.columns:
            top_10 = snapshot.nlargest(10, 'rs_rating')[['rs_rating', 'mom_63d', 'turnover_ma20']]
            print(f"\n   Top 10 by RS Rating:")
            print(top_10.to_string())

    except Exception as e:
        print(f"   [ERR] Error: {e}")


def run_curation(
    source: str = 'sp500',
    custom_tickers: Optional[str] = None,
    tickers_file: Optional[str] = None,
    update_prices_flag: bool = False,
    update_fundamentals_flag: bool = False,
    update_profiles_flag: bool = False,
    update_macro_flag: bool = False,
    force: bool = False,
    skip_market_check: bool = False,
    skip_health_check: bool = False,
    max_workers: int = 10,
    market_cap_min: int = 1_000_000_000,
    price_min: float = 5.0,
    volume_min: int = 100_000,
    from_date: Optional[str] = None,
    use_earnings_calendar: bool = True
):
    """
    Run the data curation pipeline.
    
    Args:
        source: Ticker universe source
        custom_tickers: Comma-separated list of specific tickers
        tickers_file: Path to file containing tickers
        update_prices_flag: Whether to update price data
        update_fundamentals_flag: Whether to update fundamental data
        update_profiles_flag: Whether to update company profiles
        update_macro_flag: Whether to update macroeconomic data (FRED + VIX)
        force: Force re-download even if cache is fresh
        skip_market_check: Bypass market hours safety check
        skip_health_check: Skip data health analysis
        max_workers: Number of parallel workers
        market_cap_min: FMP screener minimum market cap
        price_min: FMP screener minimum price
        volume_min: FMP screener minimum volume
        from_date: Override start date for price fetching (bypasses incremental logic)
        use_earnings_calendar: Use earnings calendar for intelligent fundamental updates (default: True)
    """
    start_time = time.time()
    
    # Determine what's being updated
    updates = []
    if update_prices_flag:
        updates.append("prices")
    if update_fundamentals_flag:
        updates.append("fundamentals")
    if update_profiles_flag:
        updates.append("profiles")
    if update_macro_flag:
        updates.append("macro")

    update_desc = ", ".join(updates) if updates else "none (health check only)"
    
    logger.info(f"Starting Data Curation (Updates: {update_desc})")
    print("=" * 80)
    print(f"📊 DATA CURATOR - Daily Maintenance")
    print("=" * 80)
    print(f"   Updates: {update_desc}")
    print(f"   Force: {force}")

    # 1. Get Ticker Universe
    # --------------------------------------------------------------------------
    print("\n1️⃣  Loading Ticker Universe...")
    
    try:
        tickers = get_tickers(
            source=source,
            custom_tickers=custom_tickers,
            tickers_file=tickers_file,
            market_cap_min=market_cap_min,
            price_min=price_min,
            volume_min=volume_min
        )
        print(f"   ✅ Universe loaded: {len(tickers)} tickers")
    except Exception as e:
        logger.error(f"Failed to load tickers: {e}")
        print(f"   ❌ Failed to load tickers: {e}")
        return

    # 2. Update Price Cache (if requested)
    # --------------------------------------------------------------------------
    if update_prices_flag:
        update_prices(tickers, force=force, skip_market_check=skip_market_check, max_workers=max_workers, from_date=from_date)

    # 3. Update Fundamentals (if requested)
    # --------------------------------------------------------------------------
    if update_fundamentals_flag:
        update_fundamentals(tickers, force=force, max_workers=max_workers, use_earnings_calendar=use_earnings_calendar)

    # 4. Update Company Profiles (if requested)
    # --------------------------------------------------------------------------
    if update_profiles_flag:
        update_profiles(tickers, force=force, max_workers=max_workers)

    # 5. Update Macroeconomic Data (if requested)
    # --------------------------------------------------------------------------
    if update_macro_flag:
        update_macro_data(force=force)

    # 6. Data Health Check (unless skipped)
    # --------------------------------------------------------------------------
    if not skip_health_check:
        run_health_check()
    
    elapsed = time.time() - start_time
    print("\n" + "=" * 80)
    print(f"✅ Data Curation Complete in {elapsed/60:.1f} minutes")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Data Curator - Daily Maintenance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Daily price update for S&P 500
  python data_curator.py --source sp500 --update-prices

  # Update specific tickers
  python data_curator.py --tickers AAPL,NVDA,TSLA --update-all

  # Quarterly fundamental refresh
  python data_curator.py --source sp500 --update-fundamentals --force

  # Run only health check (earnings staleness, coverage, quality)
  python data_curator.py --health-check

  # Use FMP screener with custom criteria
  python data_curator.py --source fmp_screener --market-cap-min 5000000000 --update-prices
        """
    )
    
    # Ticker selection
    ticker_group = parser.add_argument_group('Ticker Selection')
    ticker_group.add_argument('--source', choices=['sp500', 'fmp_screener', 'price_folder'], default='price_folder',
                              help="Source for ticker universe (default: price_folder)")
    ticker_group.add_argument('--tickers', type=str, default=None,
                              help="Comma-separated list of specific tickers (overrides --source)")
    ticker_group.add_argument('--tickers-file', type=str, default=None,
                              help="Path to file containing tickers (one per line)")
    
    # FMP Screener criteria
    screener_group = parser.add_argument_group('FMP Screener Criteria (only used with --source fmp_screener)')
    screener_group.add_argument('--market-cap-min', type=int, default=1_000_000_000,
                                help="Minimum market cap (default: 1,000,000,000)")
    screener_group.add_argument('--price-min', type=float, default=5.0,
                                help="Minimum stock price (default: 5.0)")
    screener_group.add_argument('--volume-min', type=int, default=100_000,
                                help="Minimum daily volume (default: 100,000)")
    
    # Update flags
    update_group = parser.add_argument_group('Update Selection')
    update_group.add_argument('--update-prices', action='store_true',
                              help="Update price data cache")
    update_group.add_argument('--update-fundamentals', action='store_true',
                              help="Update fundamental data cache")
    update_group.add_argument('--update-profiles', action='store_true',
                              help="Update company profile cache")
    update_group.add_argument('--update-macro', action='store_true',
                              help="Update macroeconomic data (FRED series + VIX for M03 regime)")
    update_group.add_argument('--update-all', action='store_true',
                              help="Update all data types (prices, fundamentals, profiles, macro)")
    update_group.add_argument('--health-check', action='store_true',
                              help="Run only data health analysis (earnings staleness detection, coverage, quality)")

    # Universe commands
    universe_group = parser.add_argument_group('Universe Commands')
    universe_group.add_argument('--universe', action='store_true',
                                help="Update universe.parquet (append if exists, build if not). Use --force to rebuild.")
    universe_group.add_argument('--universe-stats', action='store_true',
                                help="Show universe.parquet statistics")
    universe_group.add_argument('--universe-snapshot', type=str, default=None, metavar='DATE',
                                help="Get universe snapshot for a date (YYYY-MM-DD)")
    universe_group.add_argument('--universe-start-date', type=str, default='2020-01-01',
                                help="Start date for rebuild (default: 2020-01-01). Only affected segments are rebuilt.")
    universe_group.add_argument('--universe-end-date', type=str, default=None,
                                help="End date for universe (default: today)")
    
    # Behavior flags
    behavior_group = parser.add_argument_group('Behavior Options')
    behavior_group.add_argument('--force', action='store_true',
                                help="Force re-download even if cache is fresh")
    behavior_group.add_argument('--skip-market-check', action='store_true',
                                help="Bypass market hours safety check for price updates")
    behavior_group.add_argument('--skip-health-check', action='store_true',
                                help="Skip the data health analysis at the end")
    behavior_group.add_argument('--max-workers', type=int, default=5,
                                help="Number of parallel workers for API calls (default: 5)")
    behavior_group.add_argument('--from-date', type=str, default=None,
                                help="Override start date for price fetching (YYYY-MM-DD). "
                                     "Bypasses incremental fetch logic. Use when tickers have insufficient history.")
    behavior_group.add_argument('--no-earnings-calendar', dest='use_earnings_calendar',
                                action='store_false', default=True,
                                help="Disable earnings calendar intelligence for fundamental updates (use legacy mode)")

    args = parser.parse_args()

    # Handle --health-check shortcut (runs only health analysis)
    if args.health_check:
        print("=" * 80)
        print(f"DATA CURATOR - Health Check Only")
        print("=" * 80)
        run_health_check()
        print("\n" + "=" * 80)
        print("Health Check Complete")
        print("=" * 80 + "\n")
        sys.exit(0)

    # Handle universe commands
    if args.universe:
        print("=" * 80)
        print("DATA CURATOR - Universe Update")
        print("=" * 80)
        update_universe(
            start_date=args.universe_start_date,
            end_date=args.universe_end_date,
            max_workers=args.max_workers,
            force=args.force
        )
        print("=" * 80 + "\n")
        sys.exit(0)

    if args.universe_stats:
        print("=" * 80)
        print("DATA CURATOR - Universe Statistics")
        print("=" * 80)
        universe_stats()
        print("=" * 80 + "\n")
        sys.exit(0)

    if args.universe_snapshot:
        print("=" * 80)
        print("DATA CURATOR - Universe Snapshot")
        print("=" * 80)
        universe_snapshot(args.universe_snapshot)
        print("=" * 80 + "\n")
        sys.exit(0)

    # Handle --update-all shortcut
    update_prices_flag = args.update_prices or args.update_all
    update_fundamentals_flag = args.update_fundamentals or args.update_all
    update_profiles_flag = args.update_profiles or args.update_all
    update_macro_flag = args.update_macro or args.update_all

    run_curation(
        source=args.source,
        custom_tickers=args.tickers,
        tickers_file=args.tickers_file,
        update_prices_flag=update_prices_flag,
        update_fundamentals_flag=update_fundamentals_flag,
        update_profiles_flag=update_profiles_flag,
        update_macro_flag=update_macro_flag,
        force=args.force,
        skip_market_check=args.skip_market_check,
        skip_health_check=args.skip_health_check,
        max_workers=args.max_workers,
        market_cap_min=args.market_cap_min,
        price_min=args.price_min,
        volume_min=args.volume_min,
        from_date=args.from_date,
        use_earnings_calendar=args.use_earnings_calendar
    )
