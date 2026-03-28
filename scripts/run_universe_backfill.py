"""
Phase 1 Universe Backfill CLI — historical data loader with yfinance and FMP support.

Usage:
    # Discover US tickers via yfinance screener (uses cache by default, ~100ms if cached)
    python scripts/run_universe_backfill.py --discover

    # Discover via FMP screener (recommended — excludes ETFs/funds, ~2,000 clean equities)
    python scripts/run_universe_backfill.py --discover-fmp

    # Force re-discovery from yfinance (if cache is outdated, ~1-2 hours)
    python scripts/run_universe_backfill.py --discover --force-refresh

    # Backfill OHLCV for all pending tickers (8-15 hours for all tickers)
    python scripts/run_universe_backfill.py --backfill-prices

    # Backfill shares outstanding history
    python scripts/run_universe_backfill.py --backfill-shares

    # Discover new tickers (quarterly gated)
    python scripts/run_universe_backfill.py --quarterly-refresh

    # Progress report
    python scripts/run_universe_backfill.py --status

    # Sanity checks
    python scripts/run_universe_backfill.py --validate

FMP Discovery Filters (--discover-fmp):
    - isEtf=false, isFund=false (clean equities only — no price/mktcap/vol filters)
    - isActivelyTrading=true
    - US stocks on NYSE/NASDAQ/AMEX
    - Phase 2 screening (price >= $15, vol >= 500K) handled by ScreenerManager
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.universe_backfill import UniverseBackfillEngine

DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"


def print_status(engine: UniverseBackfillEngine) -> None:
    s = engine.get_status()
    print("\n" + "=" * 60)
    print("[STATUS] UNIVERSE BACKFILL STATUS")
    print("=" * 60)
    print(f"  Company Profiles:    {s['company_profiles']:>10,} tickers")
    print(f"  Price Data:          {s['price_tickers_done']:>10,} / {s['company_profiles']:,} ({s['price_pct_complete']:>5.1f}%)")
    print(f"                       {s['price_rows']:>10,} total rows")
    print(f"  Shares History:      {s['shares_tickers_done']:>10,} / {s['company_profiles']:,} ({s['shares_pct_complete']:>5.1f}%)")
    print(f"                       {s['shares_rows']:>10,} total rows")
    print("=" * 60 + "\n")


def print_validation(engine: UniverseBackfillEngine) -> None:
    v = engine.validate_backfill()
    print("\n" + "=" * 60)
    print("[OK] BACKFILL VALIDATION RESULTS")
    print("=" * 60)
    print(f"  Tickers with data:   {v['tickers']:>10,}")
    print(f"  Total rows:          {v['total_rows']:>10,}")
    print(f"  Date range:          {v['earliest_date']} to {v['latest_date']}")
    print(f"  Sparse tickers (<50):{v['sparse_tickers']:>10,}")
    print()
    print("  Sample delisted tickers:")
    for key, val in v.items():
        if key.startswith("rows_"):
            ticker = key.replace("rows_", "")
            status = "[OK]" if val > 0 else "[ERR]"
            print(f"    {status} {ticker}: {val:>8,} rows")
    print("=" * 60 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1 Universe Backfill")
    parser.add_argument("--discover", action="store_true", help="Discover US tickers via yfinance screener (uses cache)")
    parser.add_argument("--discover-fmp", action="store_true", help="Discover US equities via FMP screener (no ETFs/funds, recommended)")
    parser.add_argument("--backfill-prices", action="store_true", help="Backfill OHLCV for all tickers")
    parser.add_argument("--backfill-shares", action="store_true", help="Backfill shares outstanding history")
    parser.add_argument("--quarterly-refresh", action="store_true", help="Discover new tickers (quarterly gated)")
    parser.add_argument("--blacklist-no-fundamentals", action="store_true", help="Auto-blacklist tickers with no FMP fundamentals (SPACs/warrants/shells)")
    parser.add_argument("--purge-blacklisted", action="store_true", help="Delete blacklisted tickers from company_profiles, price_data, shares_history")
    parser.add_argument("--status", action="store_true", help="Print progress report")
    parser.add_argument("--validate", action="store_true", help="Run validation checks")
    parser.add_argument("--batch-size", type=int, default=50, help="Tickers per batch (default 50)")
    parser.add_argument("--workers", type=int, default=8, help="Thread pool workers (default 8)")
    parser.add_argument("--start-date", type=str, default="2000-01-01", help="OHLCV start date (default 2000-01-01)")
    parser.add_argument("--force-refresh", action="store_true", help="Force re-discovery from yfinance (bypass cache)")
    args = parser.parse_args()

    engine = UniverseBackfillEngine(str(DB_PATH))
    engine.ensure_tables()

    if args.status:
        print_status(engine)
        return

    if args.validate:
        print_validation(engine)
        return

    if not any([args.discover, args.discover_fmp, args.backfill_prices, args.backfill_shares,
                args.quarterly_refresh, args.blacklist_no_fundamentals, args.purge_blacklisted]):
        parser.print_help()
        return

    t0 = time.perf_counter()

    if args.discover:
        print("\n" + "=" * 60)
        print("STEP 1: DISCOVER TICKERS (yfinance)")
        print("=" * 60)
        count = engine.discover_tickers(use_cache=True, force_refresh=args.force_refresh)
        print(f"Results: {count:,} company profiles populated")

    if args.discover_fmp:
        print("\n" + "=" * 60)
        print("STEP 1: DISCOVER TICKERS (FMP — no ETFs/funds)")
        print("=" * 60)
        count = engine.discover_tickers_fmp()
        print(f"Results: {count:,} company profiles populated")

    if args.backfill_prices:
        print("\n" + "=" * 60)
        print("STEP 2: BACKFILL PRICE DATA")
        print("=" * 60)
        rows = engine.backfill_prices(batch_size=args.batch_size, start_date=args.start_date)
        print(f"Results: {rows:,} price records written")

    if args.backfill_shares:
        print("\n" + "=" * 60)
        print("STEP 3: BACKFILL SHARES OUTSTANDING")
        print("=" * 60)
        rows = engine.backfill_shares(max_workers=args.workers)
        print(f"Results: {rows:,} shares records written")

    if args.quarterly_refresh:
        print("\n" + "=" * 60)
        print("STEP 4: QUARTERLY UNIVERSE REFRESH")
        print("=" * 60)
        count = engine.quarterly_refresh()
        print(f"Results: {count} new tickers added")

    if args.blacklist_no_fundamentals:
        print("\n" + "=" * 60)
        print("BLACKLIST: TICKERS WITH NO FMP FUNDAMENTALS")
        print("=" * 60)
        count = engine.auto_blacklist_no_fundamentals()
        print(f"Results: {count:,} tickers added to blacklist")

    if args.purge_blacklisted:
        print("\n" + "=" * 60)
        print("PURGE: REMOVE BLACKLISTED TICKERS FROM PHASE 1 TABLES")
        print("=" * 60)
        counts = engine.purge_blacklisted()
        for table, n in counts.items():
            print(f"  {table}: {n:,} rows deleted")
        print(f"Results: {sum(counts.values()):,} total rows deleted")

    elapsed = time.perf_counter() - t0
    print("\n" + "=" * 60)
    print(f"TOTAL ELAPSED: {elapsed / 60:.1f} minutes")
    print("=" * 60)
    print_status(engine)


if __name__ == "__main__":
    main()
