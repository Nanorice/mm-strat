"""
Backfill fundamentals.filing_date from SEC EDGAR (authoritative source).

For tickers whose 10-Q/10-K filing dates are missing in fundamentals (because
the yfinance earnings_calendar path is sparse/unreliable), look up filings
directly from SEC submissions API and fill the dates.

Refreshes the cik_map table first (quarterly+ data, cheap), then runs the
backfill against all source='yfinance' rows with filing_date IS NULL.

Two modes:
  --dry-run (default): show scope + sample 5 tickers, no writes
  --execute          : runs the backfill
"""

import argparse
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.edgar_engine import EDGAREngine

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
    # How many of those tickers have a CIK?
    with_cik = con.execute("""
        SELECT COUNT(DISTINCT f.ticker)
        FROM fundamentals f
        JOIN cik_map cm ON f.ticker = cm.ticker
        WHERE f.filing_date IS NULL AND f.source = 'yfinance'
    """).fetchone()[0]
    by_year = con.execute("""
        SELECT EXTRACT(YEAR FROM period_end) AS yr, COUNT(*) AS n
        FROM fundamentals
        WHERE filing_date IS NULL AND source = 'yfinance'
        GROUP BY 1 ORDER BY 1 DESC LIMIT 10
    """).df()
    return {
        'null_rows': null_rows,
        'tickers': tickers,
        'tickers_with_cik': with_cik,
        'by_year': by_year,
    }


def _dry_run(eng: EDGAREngine, sample_size: int) -> None:
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        cik_count = con.execute("SELECT COUNT(*) FROM cik_map").fetchone()[0]
        scope = _scope(con)
        sample_tickers = [r[0] for r in con.execute(f"""
            SELECT DISTINCT f.ticker FROM fundamentals f
            JOIN cik_map cm ON f.ticker = cm.ticker
            WHERE f.source = 'yfinance' AND f.filing_date IS NULL
            ORDER BY f.ticker
            LIMIT {int(sample_size)}
        """).fetchall()]
    finally:
        con.close()

    print("=" * 70)
    print("EDGAR FILING-DATE BACKFILL — DRY RUN")
    print("=" * 70)
    print(f"cik_map rows                      : {cik_count:>6}")
    print(f"Eligible NULL filing_date rows    : {scope['null_rows']:>6}")
    print(f"Distinct tickers with NULL        : {scope['tickers']:>6}")
    print(f"  of which have a CIK mapping     : {scope['tickers_with_cik']:>6}")
    print(f"  of which have NO CIK (skip)     : {scope['tickers'] - scope['tickers_with_cik']:>6}")
    print()
    print("Top years missing filing_date:")
    print(scope['by_year'].to_string(index=False))
    print()
    if not sample_tickers:
        print("Nothing to backfill.")
        return
    print(f"Sampling {len(sample_tickers)} tickers from EDGAR to verify...")
    t0 = time.time()
    hits = 0
    for tk in sample_tickers:
        cik = eng.get_cik(tk)
        df = eng.client.get_recent_filings(cik, forms=('10-Q', '10-K'))
        if not df.empty:
            hits += 1
            sample = df.head(1).iloc[0]
            print(f"  {tk:<8} CIK={cik:<8d} {len(df):>2} filings  "
                  f"(latest: {sample.form} report={sample.report_date} filed={sample.filing_date})")
        else:
            print(f"  {tk:<8} CIK={cik:<8d}  no 10-Q/10-K filings returned")
    elapsed = time.time() - t0
    print()
    print(f"Sample yield: {hits}/{len(sample_tickers)} tickers returned filings")
    print(f"Sample time : {elapsed:.1f}s ({elapsed/len(sample_tickers):.2f}s per ticker)")
    if scope['tickers_with_cik'] > 0:
        est = scope['tickers_with_cik'] * elapsed / len(sample_tickers) / 60
        print(f"Estimated full run: ~{est:.1f} min for {scope['tickers_with_cik']} CIK-mapped tickers")
    print()
    print("Re-run with --execute to apply. Only filing_date is touched; numbers preserved.")


def _execute(eng: EDGAREngine) -> None:
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        scope_before = _scope(con)
    finally:
        con.close()

    print(f"Eligible rows: {scope_before['null_rows']}, "
          f"tickers: {scope_before['tickers']} "
          f"({scope_before['tickers_with_cik']} have CIK)")
    if scope_before['null_rows'] == 0:
        print("Nothing to backfill.")
        return

    t0 = time.time()
    results = eng.backfill_filing_dates_from_edgar(tickers=None, only_null=True)
    elapsed = time.time() - t0

    total = sum(results.values())
    tickers_touched = len(results)

    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        scope_after = _scope(con)
    finally:
        con.close()

    print()
    print("=" * 70)
    print("EDGAR BACKFILL COMPLETE")
    print("=" * 70)
    print(f"Wall time            : {elapsed/60:.1f} min")
    print(f"Tickers updated      : {tickers_touched:>6}")
    print(f"Rows updated         : {total:>6}")
    print(f"Remaining NULL rows  : {scope_after['null_rows']:>6}  (was {scope_before['null_rows']})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Actually run the backfill (default: dry-run)')
    parser.add_argument('--sample-size', type=int, default=5, help='Tickers to probe in dry-run (default: 5)')
    parser.add_argument('--skip-cik-refresh', action='store_true',
                        help='Do not refresh cik_map first (use existing rows)')
    args = parser.parse_args()

    eng = EDGAREngine()

    if not args.skip_cik_refresh:
        print("Refreshing cik_map from SEC...")
        n = eng.refresh_cik_map()
        print(f"cik_map: {n} rows")
        print()

    if args.execute:
        _execute(eng)
    else:
        _dry_run(eng, args.sample_size)


if __name__ == '__main__':
    main()
