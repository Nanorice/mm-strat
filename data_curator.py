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


def run_health_check():
    """Run comprehensive data health analysis."""
    print("\n5️⃣  Running Data Health Analysis...")
    analyzer = DataHealthAnalyzer()
    analyzer.run_full_analysis()


def run_curation(
    source: str = 'sp500',
    custom_tickers: Optional[str] = None,
    tickers_file: Optional[str] = None,
    update_prices_flag: bool = False,
    update_fundamentals_flag: bool = False,
    update_profiles_flag: bool = False,
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

    # 5. Data Health Check (unless skipped)
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
    update_group.add_argument('--update-all', action='store_true',
                              help="Update all data types (prices, fundamentals, profiles)")
    update_group.add_argument('--health-check', action='store_true',
                              help="Run only data health analysis (earnings staleness detection, coverage, quality)")
    
    # Behavior flags
    behavior_group = parser.add_argument_group('Behavior Options')
    behavior_group.add_argument('--force', action='store_true',
                                help="Force re-download even if cache is fresh")
    behavior_group.add_argument('--skip-market-check', action='store_true',
                                help="Bypass market hours safety check for price updates")
    behavior_group.add_argument('--skip-health-check', action='store_true',
                                help="Skip the data health analysis at the end")
    behavior_group.add_argument('--max-workers', type=int, default=5,
                                help="Number of parallel workers for API calls (default: 10)")
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

    # Handle --update-all shortcut
    update_prices_flag = args.update_prices or args.update_all
    update_fundamentals_flag = args.update_fundamentals or args.update_all
    update_profiles_flag = args.update_profiles or args.update_all

    run_curation(
        source=args.source,
        custom_tickers=args.tickers,
        tickers_file=args.tickers_file,
        update_prices_flag=update_prices_flag,
        update_fundamentals_flag=update_fundamentals_flag,
        update_profiles_flag=update_profiles_flag,
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
