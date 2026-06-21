"""
Backfill missing fundamental ratio columns to fundamentals table.

This script adds and computes the following columns:
- market_cap: Computed from price * shares_outstanding
- pe_ratio: Price-to-Earnings (market_cap / net_income)
- ps_ratio: Price-to-Sales (market_cap / revenue)
- pb_ratio: Price-to-Book (market_cap / total_equity)
- peg_ratio: PEG ratio (pe_ratio / revenue_growth_yoy from fundamental_features)

Milestone 3.0 - BLOCKING prerequisite for Phase 3 implementation

Usage:
    python scripts/backfill_fundamental_ratios.py
    python scripts/backfill_fundamental_ratios.py --dry-run
"""

import argparse
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "market_data.duckdb"


def add_columns(conn: duckdb.DuckDBPyConnection, dry_run: bool = False) -> None:
    """Add missing ratio columns to fundamentals table."""
    print("=" * 80)
    print("STEP 1: Adding ratio columns to fundamentals table")
    print("=" * 80)

    columns_to_add = [
        ("market_cap", "DOUBLE"),
        ("pe_ratio", "DOUBLE"),
        ("ps_ratio", "DOUBLE"),
        ("pb_ratio", "DOUBLE"),
        ("peg_ratio", "DOUBLE"),
    ]

    for col_name, col_type in columns_to_add:
        try:
            if dry_run:
                print(f"[DRY RUN] Would add column: {col_name} {col_type}")
            else:
                conn.execute(f"ALTER TABLE fundamentals ADD COLUMN {col_name} {col_type}")
                print(f"[OK] Added column: {col_name}")
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"[SKIP] Column already exists: {col_name}")
            else:
                raise


def backfill_ratios(conn: duckdb.DuckDBPyConnection, dry_run: bool = False) -> dict:
    """Compute and backfill ratio columns."""
    print("\n" + "=" * 80)
    print("STEP 2: Computing market_cap and valuation ratios")
    print("=" * 80)
    print("Strategy:")
    print("  1. Find closest price within ±7 days of report_date")
    print("  2. Find most recent shares_outstanding <= price_date")
    print("  3. Compute market_cap = price * shares")
    print("  4. Compute P/E, P/S, P/B ratios")
    print("  5. Join with fundamental_features to get growth rates for PEG")
    print()

    start = time.time()

    # Strategy: For each fundamental record, find closest price (±7 days)
    # and most recent shares_outstanding data
    sql = """
    WITH fundamentals_to_update AS (
        SELECT
            ticker,
            report_date,
            period_type,
            revenue,
            net_income,
            total_equity
        FROM fundamentals
        WHERE revenue IS NOT NULL
    ),
    with_closest_price AS (
        SELECT
            f.ticker,
            f.report_date,
            f.period_type,
            f.revenue,
            f.net_income,
            f.total_equity,
            p.date as price_date,
            p.close,
            ROW_NUMBER() OVER (
                PARTITION BY f.ticker, f.report_date, f.period_type
                ORDER BY ABS(EPOCH(f.report_date) - EPOCH(p.date))
            ) as rn
        FROM fundamentals_to_update f
        LEFT JOIN price_data p ON f.ticker = p.ticker
            AND p.date BETWEEN f.report_date - INTERVAL '7 days'
                           AND f.report_date + INTERVAL '7 days'
    ),
    with_shares AS (
        SELECT
            wp.ticker,
            wp.report_date,
            wp.period_type,
            wp.price_date,
            wp.close,
            wp.revenue,
            wp.net_income,
            wp.total_equity,
            s.shares_outstanding,
            ROW_NUMBER() OVER (
                PARTITION BY wp.ticker, wp.price_date
                ORDER BY s.date DESC
            ) as shares_rn
        FROM with_closest_price wp
        LEFT JOIN shares_history s ON wp.ticker = s.ticker
            AND s.date <= wp.price_date
        WHERE wp.rn = 1
    ),
    with_market_cap AS (
        SELECT
            ticker,
            report_date,
            period_type,
            close * shares_outstanding as market_cap,
            close * shares_outstanding / NULLIF(net_income, 0) as pe_ratio,
            close * shares_outstanding / NULLIF(revenue, 0) as ps_ratio,
            close * shares_outstanding / NULLIF(total_equity, 0) as pb_ratio
        FROM with_shares
        WHERE shares_rn = 1
          AND close IS NOT NULL
          AND shares_outstanding IS NOT NULL
    ),
    with_growth AS (
        SELECT
            mc.*,
            ff.eps_growth_yoy,
            CASE
                WHEN ff.eps_growth_yoy > 0 THEN mc.pe_ratio / ff.eps_growth_yoy
                ELSE NULL
            END as peg_ratio
        FROM with_market_cap mc
        LEFT JOIN fundamental_features ff
            ON mc.ticker = ff.ticker
           AND mc.report_date = ff.fiscal_date
    )
    UPDATE fundamentals f
    SET market_cap = wg.market_cap,
        pe_ratio = wg.pe_ratio,
        ps_ratio = wg.ps_ratio,
        pb_ratio = wg.pb_ratio,
        peg_ratio = wg.peg_ratio
    FROM with_growth wg
    WHERE f.ticker = wg.ticker
      AND f.report_date = wg.report_date
      AND f.period_type = wg.period_type
    """

    if dry_run:
        print("[DRY RUN] Would execute UPDATE query. Skipping.")
        elapsed = 0.0
        stats_df = conn.execute("""
            SELECT
                COUNT(*) as total_rows,
                0 as market_cap_count,
                0 as pe_ratio_count,
                0 as ps_ratio_count,
                0 as pb_ratio_count,
                0 as peg_ratio_count,
                0.0 as market_cap_pct,
                0.0 as pe_ratio_pct,
                0.0 as ps_ratio_pct,
                0.0 as pb_ratio_pct,
                0.0 as peg_ratio_pct
            FROM fundamentals
        """).fetchdf()
    else:
        result = conn.execute(sql)
        elapsed = time.time() - start

        # Check coverage
        stats_df = conn.execute("""
            SELECT
                COUNT(*) as total_rows,
                COUNT(market_cap) as market_cap_count,
                COUNT(pe_ratio) as pe_ratio_count,
                COUNT(ps_ratio) as ps_ratio_count,
                COUNT(pb_ratio) as pb_ratio_count,
                COUNT(peg_ratio) as peg_ratio_count,
                ROUND(100.0 * COUNT(market_cap) / COUNT(*), 2) as market_cap_pct,
                ROUND(100.0 * COUNT(pe_ratio) / COUNT(*), 2) as pe_ratio_pct,
                ROUND(100.0 * COUNT(ps_ratio) / COUNT(*), 2) as ps_ratio_pct,
                ROUND(100.0 * COUNT(pb_ratio) / COUNT(*), 2) as pb_ratio_pct,
                ROUND(100.0 * COUNT(peg_ratio) / COUNT(*), 2) as peg_ratio_pct
            FROM fundamentals
        """).fetchdf()

        print(f"\n[OK] Backfill completed in {elapsed:.1f} seconds")

    print("\nCoverage Statistics:")
    print(stats_df.to_string(index=False))

    return {
        "elapsed_seconds": elapsed,
        "market_cap_count": int(stats_df["market_cap_count"].iloc[0]),
        "pe_ratio_count": int(stats_df["pe_ratio_count"].iloc[0]),
        "ps_ratio_count": int(stats_df["ps_ratio_count"].iloc[0]),
        "pb_ratio_count": int(stats_df["pb_ratio_count"].iloc[0]),
        "peg_ratio_count": int(stats_df["peg_ratio_count"].iloc[0]),
    }


def validate_random_sample(conn: duckdb.DuckDBPyConnection, n: int = 10) -> pd.DataFrame:
    """Validate computed ratios on random sample."""
    print("\n" + "=" * 80)
    print(f"STEP 3: Validating {n} random tickers")
    print("=" * 80)

    sample = conn.execute(f"""
        SELECT
            ticker,
            report_date,
            ROUND(revenue / 1e9, 2) as revenue_billions,
            ROUND(net_income / 1e9, 2) as net_income_billions,
            ROUND(total_equity / 1e9, 2) as equity_billions,
            ROUND(market_cap / 1e9, 2) as market_cap_billions,
            ROUND(pe_ratio, 2) as pe_ratio,
            ROUND(ps_ratio, 2) as ps_ratio,
            ROUND(pb_ratio, 2) as pb_ratio,
            ROUND(peg_ratio, 2) as peg_ratio
        FROM fundamentals
        WHERE market_cap IS NOT NULL
          AND report_date >= '2024-01-01'
        ORDER BY RANDOM()
        LIMIT {n}
    """).fetchdf()

    print("\nSample Results:")
    print(sample.to_string(index=False))

    # Sanity checks
    print("\n" + "-" * 80)
    print("Sanity Checks:")
    print("-" * 80)

    # Check for extreme outliers
    issues = []
    for idx, row in sample.iterrows():
        ticker = row["ticker"]
        pe = row["pe_ratio"]
        ps = row["ps_ratio"]
        pb = row["pb_ratio"]
        peg = row["peg_ratio"]

        # Flag extreme values (likely errors or special cases)
        if pd.notna(pe) and abs(pe) > 1000:
            issues.append(f"{ticker}: P/E = {pe:.1f} (extreme - likely loss-making or low earnings)")
        if pd.notna(ps) and ps > 100:
            issues.append(f"{ticker}: P/S = {ps:.1f} (very high growth/speculative)")
        if pd.notna(pb) and pb > 50:
            issues.append(f"{ticker}: P/B = {pb:.1f} (asset-light business or overvalued)")
        if pd.notna(peg) and abs(peg) > 10:
            issues.append(f"{ticker}: PEG = {peg:.1f} (extreme - low growth or high PE)")

    if issues:
        print("[WARN] Potential outliers found (may be valid for certain stocks):")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("[OK] All ratios within reasonable ranges")

    return sample


def print_summary(stats: dict, dry_run: bool = False) -> None:
    """Print final summary."""
    print("\n" + "=" * 80)
    print("BACKFILL SUMMARY")
    print("=" * 80)

    if dry_run:
        print("[DRY RUN] No changes made to database")
    else:
        print(f"Elapsed Time: {stats['elapsed_seconds']:.1f} seconds")
        print(f"\nRows Updated:")
        print(f"  - market_cap: {stats['market_cap_count']:,}")
        print(f"  - pe_ratio:   {stats['pe_ratio_count']:,}")
        print(f"  - ps_ratio:   {stats['ps_ratio_count']:,}")
        print(f"  - pb_ratio:   {stats['pb_ratio_count']:,}")
        print(f"  - peg_ratio:  {stats['peg_ratio_count']:,}")
        print(f"\n[OK] Milestone 3.0 COMPLETE - Phase 3 no longer blocked")


def main() -> None:
    """Main execution."""
    parser = argparse.ArgumentParser(description="Backfill fundamental ratio columns")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without modifying database")
    args = parser.parse_args()

    print("=" * 80)
    print("MILESTONE 3.0: Backfill Fundamental Ratio Columns")
    print("=" * 80)
    print()

    if not DB_PATH.exists():
        print(f"[ERR] Database not found: {DB_PATH}")
        sys.exit(1)

    conn = duckdb.connect(str(DB_PATH))

    try:
        # Step 1: Add columns
        add_columns(conn, dry_run=args.dry_run)

        # Step 2: Backfill market_cap and ratios
        stats = backfill_ratios(conn, dry_run=args.dry_run)

        # Step 3: Validate random sample (only if not dry run)
        if not args.dry_run:
            validate_random_sample(conn, n=10)

        # Summary
        print_summary(stats, dry_run=args.dry_run)

    except Exception as e:
        print(f"\n[ERR] Backfill failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
