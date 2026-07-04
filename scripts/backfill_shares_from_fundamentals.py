"""
Backfill shares_history from fundamentals.basic_avg_shares.

Fills the gap between the start of fundamental data and the first yfinance
snapshot per ticker. After this, screener_membership backfill will have
market cap data for the full price_data history.

Logic:
  - For each ticker, find MIN(date) in shares_history (first yfinance snapshot)
  - Insert all fundamentals rows where period_end < that date
  - Tickers with no shares_history at all are excluded (none exist per audit)
  - Uses period_end as the date key — screener_manager forward-fills via
    LAST_VALUE(shares_outstanding IGNORE NULLS) so quarterly cadence is fine

Usage:
    python scripts/backfill_shares_from_fundamentals.py
    python scripts/backfill_shares_from_fundamentals.py --dry-run
"""

import argparse
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DUCKDB_PATH, T1_PLAUSIBILITY_BOUNDS

SHARES_MAX = T1_PLAUSIBILITY_BOUNDS['shares_max']  # FMP has 1000x-scaled dirt above this


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill shares_history from fundamentals")
    parser.add_argument("--dry-run", action="store_true", help="Show row count without writing")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  SHARES BACKFILL — fundamentals.basic_avg_shares -> shares_history")
    print("=" * 60)

    con = duckdb.connect(str(DUCKDB_PATH))

    # Pre-flight: count rows to insert
    rows_to_insert = con.execute(f"""
        WITH first_yf AS (
            SELECT ticker, MIN(date) AS first_yf_date
            FROM shares_history
            GROUP BY ticker
        )
        SELECT COUNT(*)
        FROM fundamentals f
        JOIN first_yf fy ON f.ticker = fy.ticker
        WHERE f.period_end < fy.first_yf_date
          AND f.basic_avg_shares IS NOT NULL
          AND f.basic_avg_shares > 0
          AND f.basic_avg_shares < {SHARES_MAX}
    """).fetchone()[0]

    tickers_affected = con.execute(f"""
        WITH first_yf AS (
            SELECT ticker, MIN(date) AS first_yf_date
            FROM shares_history
            GROUP BY ticker
        )
        SELECT COUNT(DISTINCT f.ticker)
        FROM fundamentals f
        JOIN first_yf fy ON f.ticker = fy.ticker
        WHERE f.period_end < fy.first_yf_date
          AND f.basic_avg_shares IS NOT NULL
          AND f.basic_avg_shares > 0
          AND f.basic_avg_shares < {SHARES_MAX}
    """).fetchone()[0]

    existing = con.execute("SELECT COUNT(*) FROM shares_history").fetchone()[0]

    print(f"\n  shares_history existing rows : {existing:,}")
    print(f"  Rows to insert from fundamentals: {rows_to_insert:,}")
    print(f"  Tickers affected                : {tickers_affected:,}")

    if args.dry_run:
        print("\n  [DRY RUN] No changes written.")
        con.close()
        return

    print(f"\n  Inserting...")
    t0 = time.perf_counter()

    con.execute(f"""
        INSERT OR IGNORE INTO shares_history (ticker, date, shares_outstanding)
        WITH first_yf AS (
            SELECT ticker, MIN(date) AS first_yf_date
            FROM shares_history
            GROUP BY ticker
        )
        SELECT
            f.ticker,
            f.period_end        AS date,
            f.basic_avg_shares  AS shares_outstanding
        FROM fundamentals f
        JOIN first_yf fy ON f.ticker = fy.ticker
        WHERE f.period_end < fy.first_yf_date
          AND f.basic_avg_shares IS NOT NULL
          AND f.basic_avg_shares > 0
          AND f.basic_avg_shares < {SHARES_MAX}
        ORDER BY f.ticker, f.period_end
    """)

    after = con.execute("SELECT COUNT(*) FROM shares_history").fetchone()[0]
    inserted = after - existing
    elapsed = time.perf_counter() - t0

    print("=" * 60)
    print(f"  [OK] Done in {elapsed:.1f}s")
    print(f"       Rows inserted : {inserted:,}")
    print(f"       Total rows    : {after:,}")
    print("=" * 60)

    if inserted < rows_to_insert * 0.9:
        print(f"\n  [WARN] Expected ~{rows_to_insert:,} inserts but got {inserted:,}.")
        print("         Some rows may have had duplicate (ticker, period_end) keys.")

    con.close()


if __name__ == "__main__":
    main()
