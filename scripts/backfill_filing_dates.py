"""
Backfill filing_date for source='yfinance' rows where it is currently NULL.

Only the filing_date column is touched. Numbers (revenue, etc.) are never
modified. Rows with filing_date already populated are skipped. Bogus filing
dates (gap < 8 days from period_end) are rejected by the upsert sanitizer
and cannot be reintroduced.

Two modes:
  --dry-run (default): scope preview, sample fetch, no writes
  --execute          : runs the backfill
"""

import argparse
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fundamental_engine import FundamentalEngine


DB_PATH = str(Path(__file__).parent.parent / "data" / "market_data.duckdb")


def _scope(con: duckdb.DuckDBPyConnection) -> dict:
    rows = con.execute("""
        SELECT
            COUNT(*) AS null_rows,
            COUNT(DISTINCT ticker) AS tickers
        FROM fundamentals
        WHERE filing_date IS NULL AND source = 'yfinance'
    """).fetchone()
    null_rows, tickers = rows
    by_year = con.execute("""
        SELECT EXTRACT(YEAR FROM period_end) AS yr, COUNT(*) AS n
        FROM fundamentals
        WHERE filing_date IS NULL AND source = 'yfinance'
        GROUP BY 1 ORDER BY 1 DESC LIMIT 10
    """).df()
    return {'null_rows': null_rows, 'tickers': tickers, 'by_year': by_year}


def _candidate_tickers(con: duckdb.DuckDBPyConnection, limit: int | None) -> list[str]:
    sql = """
        SELECT ticker, COUNT(*) AS missing
        FROM fundamentals
        WHERE filing_date IS NULL AND source = 'yfinance'
        GROUP BY ticker
        ORDER BY missing DESC, ticker
    """
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return [r[0] for r in con.execute(sql).fetchall()]


def _dry_run(sample_size: int) -> None:
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        scope = _scope(con)
        candidates = _candidate_tickers(con, limit=None)
    finally:
        con.close()

    print("=" * 70)
    print("FILING-DATE BACKFILL — DRY RUN")
    print("=" * 70)
    print(f"Eligible rows (source=yfinance, filing_date NULL): {scope['null_rows']:>6}")
    print(f"Distinct tickers                                 : {scope['tickers']:>6}")
    print()
    print("Top years missing filing_date:")
    print(scope['by_year'].to_string(index=False))
    print()

    if not candidates:
        print("Nothing to backfill.")
        return

    print(f"Sampling {min(sample_size, len(candidates))} tickers to verify yfinance returns filing dates...")
    fe = FundamentalEngine.__new__(FundamentalEngine)
    fe.source = 'yfinance'
    fe.db_path = DB_PATH
    fe.last_errors = []

    sample = candidates[:sample_size]
    hits, misses = 0, 0
    for tk in sample:
        result = fe._fetch_filing_dates_for_ticker(tk)
        if result:
            hits += 1
            print(f"  {tk:<8} fetched {len(result):>2} filing dates "
                  f"(e.g. {list(result.items())[0][0]} -> {list(result.items())[0][1]})")
        else:
            misses += 1
            print(f"  {tk:<8} no usable filing dates from yfinance")
        time.sleep(0.2)
    print()
    print(f"Sample yield: {hits}/{len(sample)} tickers returned filing dates")
    print()
    print("Re-run with --execute to apply. Only filing_date is touched; numbers preserved.")


def _execute(max_workers: int, limit: int | None) -> None:
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        scope = _scope(con)
        tickers = _candidate_tickers(con, limit)
    finally:
        con.close()

    print(f"Eligible rows: {scope['null_rows']}, tickers: {scope['tickers']}")
    if limit is not None:
        print(f"--limit {limit} applied: targeting {len(tickers)} tickers")
    if not tickers:
        print("Nothing to backfill.")
        return

    fe = FundamentalEngine()
    results = fe.backfill_filing_dates(tickers, max_workers=max_workers)

    total = sum(results.values())
    with_updates = sum(1 for n in results.values() if n > 0)

    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        post = _scope(con)
    finally:
        con.close()

    print()
    print("=" * 70)
    print("BACKFILL COMPLETE")
    print("=" * 70)
    print(f"Tickers attempted    : {len(results):>6}")
    print(f"Tickers with updates : {with_updates:>6}")
    print(f"Rows updated         : {total:>6}")
    print(f"Remaining NULL rows  : {post['null_rows']:>6}  (was {scope['null_rows']})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Actually run the backfill (default is dry-run)')
    parser.add_argument('--sample-size', type=int, default=10, help='Tickers to probe in dry-run (default: 10)')
    parser.add_argument('--max-workers', type=int, default=4, help='yfinance fetch parallelism (default: 4)')
    parser.add_argument('--limit', type=int, default=None, help='Cap number of tickers (for staged rollout)')
    args = parser.parse_args()

    if args.execute:
        _execute(args.max_workers, args.limit)
    else:
        _dry_run(args.sample_size)


if __name__ == '__main__':
    main()
