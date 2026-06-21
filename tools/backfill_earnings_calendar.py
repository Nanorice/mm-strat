"""
One-off backfill: insert missing earnings_calendar rows that the pre-fix
_fetch_one filter discarded (future unconfirmed rows).

Contract: this tool only INSERTs rows that don't already exist.
Existing rows are never updated, regardless of whether yfinance now reports
different values. Promotion of FALSE->TRUE on existing rows is left to the
normal monthly refresh path.

Strategy:
  1. Pick tickers missing a future unconfirmed row.
  2. Fetch yfinance earnings dates in-memory.
  3. Classify each fetched row as:
       - NEW       : (ticker, earnings_date) not in DB           [WRITTEN on --apply]
       - PROMOTION : existing row, FALSE->TRUE                   [reported, skipped]
       - OVERWRITE : existing row with different numerics        [reported, skipped]
       - NOOP      : existing row, identical                     [reported, skipped]

Usage:
    python tools/backfill_earnings_calendar.py --dry-run   # default: report only
    python tools/backfill_earnings_calendar.py --apply     # write NEW rows only
"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import yfinance as yf

sys.path.append(str(Path(__file__).parent.parent))

from src.fundamental_engine import FundamentalEngine, _nan_to_none


def _fetch_one(ticker: str) -> pd.DataFrame:
    try:
        ed = yf.Ticker(ticker).get_earnings_dates(limit=10)
    except Exception:
        return pd.DataFrame()
    if ed is None or ed.empty:
        return pd.DataFrame()

    rows = []
    for dt, row in ed.iterrows():
        reported = row.get('Reported EPS')
        rows.append({
            'ticker':           ticker,
            'earnings_date':    pd.Timestamp(dt).tz_localize(None).date(),
            'eps_estimate':     _nan_to_none(row.get('EPS Estimate')),
            'reported_eps':     _nan_to_none(reported),
            'eps_surprise_pct': _nan_to_none(row.get('Surprise(%)')),
            'is_confirmed':     bool(pd.notna(reported)),
        })
    return pd.DataFrame(rows)


def _classify(fetched: pd.DataFrame, current: pd.DataFrame) -> dict:
    """Return {'new': df, 'promotion': df, 'overwrite': df, 'noop': df}."""
    if fetched.empty:
        return {k: pd.DataFrame() for k in ('new', 'promotion', 'overwrite', 'noop')}

    fetched = fetched.copy()
    current = current.copy()
    fetched['earnings_date'] = pd.to_datetime(fetched['earnings_date'])
    current['earnings_date'] = pd.to_datetime(current['earnings_date'])

    merged = fetched.merge(
        current,
        on=['ticker', 'earnings_date'],
        how='left',
        suffixes=('_new', '_old'),
        indicator=True,
    )

    new = merged[merged['_merge'] == 'left_only'].copy()
    existing = merged[merged['_merge'] == 'both'].copy()

    def _close(a, b):
        # NaN-safe equality for floats; treat both-null as equal
        a_null = pd.isna(a)
        b_null = pd.isna(b)
        eq = (a_null & b_null) | ((~a_null) & (~b_null) & (a == b))
        return eq

    promotion_mask = (
        (existing['is_confirmed_old'] == False)
        & (existing['is_confirmed_new'] == True)
    )

    value_diff = (
        (~_close(existing['eps_estimate_new'],     existing['eps_estimate_old']))
        | (~_close(existing['reported_eps_new'],     existing['reported_eps_old']))
        | (~_close(existing['eps_surprise_pct_new'], existing['eps_surprise_pct_old']))
    )

    overwrite_mask = (~promotion_mask) & value_diff
    noop_mask = (~promotion_mask) & (~value_diff) & (
        existing['is_confirmed_new'] == existing['is_confirmed_old']
    )

    return {
        'new':       new,
        'promotion': existing[promotion_mask].copy(),
        'overwrite': existing[overwrite_mask].copy(),
        'noop':      existing[noop_mask].copy(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Insert NEW rows (existing rows never updated)')
    parser.add_argument('--dry-run', action='store_true', help='Report only (default)')
    parser.add_argument('--max-workers', type=int, default=8)
    parser.add_argument('--limit', type=int, default=None,
                        help='Limit ticker count (for testing)')
    args = parser.parse_args()

    if args.apply and args.dry_run:
        print("Cannot pass both --apply and --dry-run")
        return 1
    write = args.apply

    fe = FundamentalEngine()
    db_path = fe.db_path

    conn = duckdb.connect(db_path, read_only=True)
    try:
        active = [r[0] for r in conn.execute(
            "SELECT ticker FROM company_profiles WHERE is_active = TRUE ORDER BY ticker"
        ).fetchall()]
    finally:
        conn.close()

    targets = fe._get_tickers_needing_earnings_refresh(active)
    if args.limit:
        targets = targets[:args.limit]
    print(f"Active tickers: {len(active)}")
    print(f"Targets (missing future unconfirmed row): {len(targets)}")
    if not targets:
        print("Nothing to do.")
        return 0

    # Snapshot current rows for diff (only for target tickers, both past + future)
    conn = duckdb.connect(db_path, read_only=True)
    try:
        conn.register('_t', pd.DataFrame({'ticker': targets}))
        current = conn.execute("""
            SELECT ec.ticker, ec.earnings_date, ec.eps_estimate, ec.reported_eps,
                   ec.eps_surprise_pct, ec.is_confirmed
            FROM earnings_calendar ec
            JOIN _t USING (ticker)
        """).df()
    finally:
        conn.close()

    print(f"Existing rows for these tickers: {len(current)}")
    print(f"Fetching from yfinance ({args.max_workers} workers)...")

    fetched_parts = []
    failed = 0
    with ThreadPoolExecutor(max_workers=args.max_workers) as ex:
        futures = {ex.submit(_fetch_one, t): t for t in targets}
        done = 0
        for fut in as_completed(futures):
            df = fut.result()
            if df.empty:
                failed += 1
            else:
                fetched_parts.append(df)
            done += 1
            if done % 500 == 0:
                print(f"  {done}/{len(targets)}")

    if not fetched_parts:
        print("No data fetched.")
        return 1

    fetched = pd.concat(fetched_parts, ignore_index=True)
    print(f"Fetched {len(fetched)} rows across {fetched['ticker'].nunique()} tickers "
          f"({failed} fetch failures)")

    buckets = _classify(fetched, current)
    n_new       = len(buckets['new'])
    n_promotion = len(buckets['promotion'])
    n_overwrite = len(buckets['overwrite'])
    n_noop      = len(buckets['noop'])

    print()
    print("Diff classification:")
    print(f"  NEW       (will insert):         {n_new}")
    print(f"  PROMOTION (existing, skipped):   {n_promotion}")
    print(f"  OVERWRITE (existing, skipped):   {n_overwrite}")
    print(f"  NOOP      (existing, identical): {n_noop}")

    if n_new:
        new = buckets['new'].copy()
        new['earnings_date'] = pd.to_datetime(new['earnings_date'])
        today = pd.Timestamp.today().normalize()

        # Past vs future split
        past   = new[new['earnings_date'] <  today]
        future = new[new['earnings_date'] >= today]
        confirmed_past   = (past['is_confirmed_new'] == True).sum()
        unconfirmed_past = (past['is_confirmed_new'] == False).sum()

        print()
        print(f"NEW row breakdown:")
        print(f"  Future dates (expected, the bug's gap): {len(future)}")
        print(f"  Past dates:                              {len(past)} "
              f"(confirmed={confirmed_past}, unconfirmed={unconfirmed_past})")

        # Per-ticker count: how many NEW rows per ticker?
        per_tkr = new.groupby('ticker').size()
        print()
        print(f"NEW rows per ticker (distribution):")
        print(f"  tickers with 1  NEW row:  {(per_tkr == 1).sum()}")
        print(f"  tickers with 2+ NEW rows: {(per_tkr >= 2).sum()}")
        if (per_tkr >= 2).any():
            print(f"  Top 10 tickers by NEW row count:")
            top = per_tkr.sort_values(ascending=False).head(10)
            for t, n in top.items():
                print(f"    {t}: {n}")

        # Sample rows
        print()
        print(f"=== Sample NEW rows (10) ===")
        sample_cols = ['ticker', 'earnings_date',
                       'eps_estimate_new', 'reported_eps_new',
                       'eps_surprise_pct_new', 'is_confirmed_new']
        print(new[sample_cols].head(10).to_string(index=False))

        # CSV dump of the full NEW bucket for offline review
        artifact_dir = Path(__file__).parent / '_artifacts'
        artifact_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        csv_path = artifact_dir / f'earnings_backfill_new_{ts}.csv'
        new[sample_cols].rename(columns={
            'eps_estimate_new':     'eps_estimate',
            'reported_eps_new':     'reported_eps',
            'eps_surprise_pct_new': 'eps_surprise_pct',
            'is_confirmed_new':     'is_confirmed',
        }).to_csv(csv_path, index=False)
        print(f"\nFull NEW bucket written to: {csv_path}")

    if not write:
        print()
        print("Dry-run only. Pass --apply to insert NEW rows.")
        return 0

    if not n_new:
        print("\nNo NEW rows to write.")
        return 0

    new_df = buckets['new'][['ticker', 'earnings_date',
                             'eps_estimate_new', 'reported_eps_new',
                             'eps_surprise_pct_new', 'is_confirmed_new']].rename(columns={
        'eps_estimate_new':     'eps_estimate',
        'reported_eps_new':     'reported_eps',
        'eps_surprise_pct_new': 'eps_surprise_pct',
        'is_confirmed_new':     'is_confirmed',
    })
    new_df['updated_at'] = datetime.utcnow()
    print(f"\nInserting {len(new_df)} NEW rows (existing rows untouched)...")

    conn = duckdb.connect(db_path)
    try:
        conn.register('_ec_batch', new_df)
        conn.execute("""
            INSERT INTO earnings_calendar
            SELECT * FROM _ec_batch
            ON CONFLICT (ticker, earnings_date) DO NOTHING
        """)
        conn.commit()
    finally:
        conn.close()

    print("[OK] Done.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
