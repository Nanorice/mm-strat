"""
Phase 2 — Price history backfill for benchmark/sector/commodity/FI ETFs + indices.

Relies on UniverseBackfillEngine.backfill_prices() which already targets
"tickers in company_profiles but not yet in price_data". Since add_benchmark_tickers.py
inserted ~40 new rows into company_profiles, those are the only pending tickers
(assuming the existing 4,135 equity tickers all have price_data — which is the
current production state).

Usage:
  python scripts/backfill_benchmark_prices.py --test            # 2 tickers (SPY, XLE)
  python scripts/backfill_benchmark_prices.py --tickers SPY XLE
  python scripts/backfill_benchmark_prices.py                   # all pending
  python scripts/backfill_benchmark_prices.py --start 1990-01-01
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import duckdb
import pandas as pd

import config
from src.universe_backfill import UniverseBackfillEngine


DB_PATH = config.DATA_DIR / 'market_data.duckdb'


def get_pending_non_equity_tickers(db_path: str, filter_tickers: list[str] = None) -> list[str]:
    """
    Non-equity tickers in company_profiles that have no price_data yet.
    """
    with duckdb.connect(db_path, read_only=True) as conn:
        existing = {r[0] for r in conn.execute(
            "SELECT DISTINCT ticker FROM price_data"
        ).fetchall()}

        rows = conn.execute("""
            SELECT ticker FROM company_profiles
            WHERE ticker_type IN ('ETF', 'INDEX')
            ORDER BY ticker
        """).fetchall()
        all_non_eq = [r[0] for r in rows]

    pending = [t for t in all_non_eq if t not in existing]

    if filter_tickers:
        wanted = set(filter_tickers)
        pending = [t for t in pending if t in wanted]
        missing = wanted - set(all_non_eq)
        if missing:
            print(f"  [WARN] Tickers not in company_profiles: {sorted(missing)}")
            print(f"         Run scripts/add_benchmark_tickers.py first.")

    return pending


def fetch_one_batch(engine: UniverseBackfillEngine, tickers: list[str], start_date: str) -> int:
    """Bypass _get_pending_tickers and call the batch fetch directly on our list."""
    print(f"\n  Fetching {len(tickers)} tickers from yfinance (start={start_date})")
    print(f"  Tickers: {tickers}")
    t0 = time.perf_counter()
    df = engine._download_price_batch(tickers, start_date)
    if df.empty:
        print("  [ERR]  No data returned from yfinance batch")
        return 0
    print(f"  Downloaded {len(df):,} rows in {time.perf_counter()-t0:.1f}s")

    rows = engine._write_price_batch(df)
    print(f"  Wrote {rows:,} rows (INSERT OR IGNORE)")
    return rows


def print_coverage(db_path: str, tickers: list[str]) -> None:
    if not tickers:
        return
    placeholders = ",".join(f"'{t}'" for t in tickers)
    with duckdb.connect(db_path, read_only=True) as conn:
        rows = conn.execute(f"""
            SELECT
                cp.ticker,
                cp.ticker_type,
                COUNT(p.date) AS n_rows,
                MIN(p.date)   AS first_date,
                MAX(p.date)   AS last_date
            FROM company_profiles cp
            LEFT JOIN price_data p ON cp.ticker = p.ticker
            WHERE cp.ticker IN ({placeholders})
            GROUP BY cp.ticker, cp.ticker_type
            ORDER BY cp.ticker_type, cp.ticker
        """).fetchall()
    print()
    print("=" * 70)
    print("[COVERAGE] price_data for requested tickers")
    print("=" * 70)
    print(f"  {'ticker':<10s} {'type':<6s} {'rows':>8s}  {'first':<12s} {'last':<12s}")
    for ticker, tt, n, first, last in rows:
        first_s = str(first) if first else "(no data)"
        last_s = str(last) if last else "(no data)"
        flag = "" if n > 0 else " [MISSING]"
        print(f"  {ticker:<10s} {tt:<6s} {n:>8,}  {first_s:<12s} {last_s:<12s}{flag}")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description="ETF/INDEX price backfill")
    parser.add_argument('--tickers', nargs='+', default=None,
                        help='Specific tickers to backfill (default: all pending non-equity)')
    parser.add_argument('--start', type=str, default='1990-01-01',
                        help='Start date (YYYY-MM-DD, default 1990-01-01)')
    parser.add_argument('--test', action='store_true',
                        help='Test mode: only SPY and XLE')
    parser.add_argument('--batch-size', type=int, default=40,
                        help='Batch size for yfinance (default 40)')
    args = parser.parse_args()

    if args.test:
        filter_tickers = ['SPY', 'XLE']
    else:
        filter_tickers = args.tickers

    pending = get_pending_non_equity_tickers(str(DB_PATH), filter_tickers)
    if not pending:
        print("[OK] No pending non-equity tickers — all already have price_data")
        if filter_tickers:
            print_coverage(str(DB_PATH), filter_tickers)
        return

    print(f"Pending: {len(pending)} ticker(s)")

    engine = UniverseBackfillEngine(str(DB_PATH))

    # Single batch (yfinance handles <=50 well)
    total = 0
    for i in range(0, len(pending), args.batch_size):
        batch = pending[i:i + args.batch_size]
        total += fetch_one_batch(engine, batch, args.start)

    print(f"\n[OK] Total rows inserted: {total:,}")
    print_coverage(str(DB_PATH), pending)


if __name__ == '__main__':
    main()
