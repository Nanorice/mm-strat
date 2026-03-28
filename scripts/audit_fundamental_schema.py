"""
Audit Fundamental Data Schema - Phase 2.2
==========================================
Checks t1_fundamentals (current: `fundamentals`) for missing columns and data quality.

Tasks:
1. List all columns in fundamentals table
2. Check for missing P/E, P/S, P/B, PEG ratios
3. Sample 10 random tickers and compare against FMP API (if available)
4. Generate report: missing columns, data staleness, variance

Usage:
    python scripts/audit_fundamental_schema.py
    python scripts/audit_fundamental_schema.py --validate-fmp  # Requires FMP API key
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import duckdb
import pandas as pd
from datetime import datetime, timedelta
import argparse

DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"

def audit_schema():
    """Check current schema for fundamentals table."""
    print("=" * 80)
    print("FUNDAMENTALS SCHEMA AUDIT")
    print("=" * 80)

    con = duckdb.connect(str(DB_PATH))

    # Get schema
    schema = con.execute("DESCRIBE fundamentals").fetchdf()
    print("\n[SCHEMA] Current Schema:")
    print(schema.to_string())

    # Check for required ratio columns
    print("\n\n[CHECK] Checking for Ratio Columns:")
    required_ratios = ['pe_ratio', 'ps_ratio', 'pb_ratio', 'peg_ratio', 'market_cap']

    missing = []
    present = []
    for col in required_ratios:
        if col in schema['column_name'].values:
            present.append(col)
            print(f"  [OK] {col}: EXISTS")
        else:
            missing.append(col)
            print(f"  [MISSING] {col}: NOT FOUND")

    # Get row counts
    total_rows = con.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
    unique_tickers = con.execute("SELECT COUNT(DISTINCT ticker) FROM fundamentals").fetchone()[0]
    date_range = con.execute("SELECT MIN(report_date), MAX(report_date) FROM fundamentals").fetchone()

    print(f"\n\n[SUMMARY] Data Summary:")
    print(f"  Total rows: {total_rows:,}")
    print(f"  Unique tickers: {unique_tickers:,}")
    print(f"  Date range: {date_range[0]} to {date_range[1]}")

    # Check for NULL values in existing columns
    print(f"\n\n[NULLS] NULL Value Analysis (sample of existing columns):")
    key_cols = ['revenue', 'net_income', 'eps_diluted', 'total_assets', 'total_equity']
    for col in key_cols:
        if col in schema['column_name'].values:
            null_count = con.execute(f"SELECT COUNT(*) FROM fundamentals WHERE {col} IS NULL").fetchone()[0]
            null_pct = (null_count / total_rows) * 100
            print(f"  {col:20s}: {null_count:7,} NULLs ({null_pct:5.1f}%)")

    # Check staleness (rows > 90 days old)
    cutoff_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    stale_count = con.execute(f"""
        SELECT COUNT(DISTINCT ticker)
        FROM fundamentals f1
        WHERE (ticker, report_date) IN (
            SELECT ticker, MAX(report_date)
            FROM fundamentals
            GROUP BY ticker
        )
        AND report_date < '{cutoff_date}'
    """).fetchone()[0]

    print(f"\n\n[STALE] Staleness Check:")
    print(f"  Tickers with no updates in 90+ days: {stale_count:,} ({stale_count/unique_tickers*100:.1f}%)")

    con.close()

    return {
        'missing_columns': missing,
        'present_columns': present,
        'total_rows': total_rows,
        'unique_tickers': unique_tickers,
        'stale_count': stale_count
    }


def sample_data_quality():
    """Sample 10 random tickers and show their latest fundamental data."""
    print("\n\n" + "=" * 80)
    print("DATA QUALITY SAMPLE (10 Random Tickers)")
    print("=" * 80)

    con = duckdb.connect(str(DB_PATH))

    sample = con.execute("""
        WITH latest_reports AS (
            SELECT
                ticker,
                report_date,
                period_type,
                revenue,
                net_income,
                eps_diluted,
                total_assets,
                total_equity,
                ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY report_date DESC) as rn
            FROM fundamentals
        )
        SELECT
            ticker,
            report_date,
            period_type,
            revenue,
            net_income,
            eps_diluted,
            total_assets,
            total_equity
        FROM latest_reports
        WHERE rn = 1
        ORDER BY RANDOM()
        LIMIT 10
    """).fetchdf()

    print("\n" + sample.to_string())

    con.close()


def validate_against_fmp(api_key: str = None):
    """
    Compare our data against FMP API for 10 random tickers.

    Args:
        api_key: FMP API key (free tier: 250 requests/day)

    Note: This is a PLACEHOLDER - FMP integration not yet implemented.
    """
    print("\n\n" + "=" * 80)
    print("FMP VALIDATION (Not Yet Implemented)")
    print("=" * 80)

    print("\n[WARN] FMP API validation is not yet implemented.")
    print("To add this feature:")
    print("  1. pip install requests")
    print("  2. Get FMP API key from https://financialmodelingprep.com/")
    print("  3. Implement fetch_fmp_fundamentals() function")
    print("  4. Compare revenue, net_income, P/E, P/S for 10 random tickers")
    print("  5. Report variance > 20%")

    print("\n[INFO] Sample FMP API call:")
    print("  https://financialmodelingprep.com/api/v3/ratios/AAPL?apikey=YOUR_KEY")


def generate_report(audit_result: dict):
    """Generate final audit report."""
    print("\n\n" + "=" * 80)
    print("AUDIT SUMMARY & RECOMMENDATIONS")
    print("=" * 80)

    print(f"\n[STATUS] Database Status:")
    print(f"  [OK] {audit_result['total_rows']:,} fundamental records")
    print(f"  [OK] {audit_result['unique_tickers']:,} unique tickers")
    print(f"  [WARN] {audit_result['stale_count']:,} tickers need updates (>90 days old)")

    print(f"\n[SCHEMA] Schema Status:")
    if audit_result['missing_columns']:
        print(f"  [MISSING] Missing columns: {', '.join(audit_result['missing_columns'])}")
        print(f"\n  [ACTION] Recommended Action:")
        print(f"     Add computed columns to fundamentals table:")
        for col in audit_result['missing_columns']:
            if col == 'pe_ratio':
                print(f"       ALTER TABLE fundamentals ADD COLUMN pe_ratio DOUBLE;")
                print(f"       UPDATE fundamentals SET pe_ratio = close / NULLIF(eps_diluted, 0);")
            elif col == 'ps_ratio':
                print(f"       ALTER TABLE fundamentals ADD COLUMN ps_ratio DOUBLE;")
                print(f"       UPDATE fundamentals SET ps_ratio = market_cap / NULLIF(revenue, 0);")
            elif col == 'pb_ratio':
                print(f"       ALTER TABLE fundamentals ADD COLUMN pb_ratio DOUBLE;")
                print(f"       UPDATE fundamentals SET pb_ratio = market_cap / NULLIF(total_equity, 0);")
            elif col == 'market_cap':
                print(f"       ALTER TABLE fundamentals ADD COLUMN market_cap DOUBLE;")
                print(f"       -- Join with t1_price & t1_shares_outstanding to compute")
    else:
        print(f"  [OK] All required ratio columns present!")

    if audit_result['present_columns']:
        print(f"\n  [OK] Present columns: {', '.join(audit_result['present_columns'])}")

    print(f"\n\n[NEXT] Next Steps for Phase 2:")
    print(f"  1. [DONE] Schema audit complete (this script)")
    print(f"  2. [TODO] Document missing columns in reconciliation_plan.md")
    print(f"  3. [TODO] Add missing ratio columns (ALTER TABLE + UPDATE)")
    print(f"  4. [TODO] Validate v_d2r_hydrated stop-loss logic (Milestone 2.3)")
    print(f"  5. [TODO] Weekly FMP validation (Phase 7.1)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit fundamental data schema")
    parser.add_argument('--validate-fmp', action='store_true', help="Validate against FMP API (requires API key)")
    parser.add_argument('--fmp-key', type=str, help="FMP API key")
    args = parser.parse_args()

    # Run audit
    audit_result = audit_schema()

    # Sample data quality
    sample_data_quality()

    # FMP validation (if requested)
    if args.validate_fmp:
        validate_against_fmp(args.fmp_key)

    # Generate report
    generate_report(audit_result)

    print("\n" + "=" * 80)
    print("[DONE] Audit complete! See recommendations above.")
    print("=" * 80 + "\n")
