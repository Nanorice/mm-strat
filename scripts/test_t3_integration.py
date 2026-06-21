"""
Test T3 Integration into Daily Pipeline

Validates that T3 SEPA features are correctly populated during daily runs.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import duckdb

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.feature_pipeline import FeaturePipeline

DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"


def test_t3_integration():
    """Test T3 integration with a small date range."""

    print("=" * 80)
    print("T3 Integration Test")
    print("=" * 80)

    # Use a recent date range for testing (last 5 trading days)
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')

    print(f"\nTest Parameters:")
    print(f"  Database: {DB_PATH}")
    print(f"  Date range: {start_date} to {end_date}")
    print(f"  Feature version: v3.1")

    # Get baseline counts
    con = duckdb.connect(str(DB_PATH))

    # Check prerequisites
    print("\n[1/4] Checking prerequisites...")

    df_count = con.execute("SELECT COUNT(*) FROM daily_features").fetchone()[0]
    t2_count = con.execute("SELECT COUNT(*) FROM t2_screener_features").fetchone()[0]

    print(f"  [OK] daily_features: {df_count:,} rows")
    print(f"  [OK] t2_screener_features: {t2_count:,} rows")

    if df_count == 0 or t2_count == 0:
        print("\n[ERR] PREREQUISITE FAILURE: daily_features or t2_screener_features is empty")
        print("   Run: python data_curator_duckdb.py --update-prices --skip-t3")
        con.close()
        return False

    # Get T3 baseline
    t3_before = con.execute("SELECT COUNT(*) FROM t3_sepa_features").fetchone()[0]
    print(f"  [OK] t3_sepa_features (before): {t3_before:,} rows")

    # Check if there are any SEPA candidates in the test range
    sepa_candidates = con.execute(f"""
        SELECT COUNT(*)
        FROM t2_screener_features
        WHERE date BETWEEN '{start_date}' AND '{end_date}'
          AND trend_ok = TRUE
          AND breakout_ok = TRUE
    """).fetchone()[0]

    print(f"  [OK] SEPA candidates in range: {sepa_candidates}")

    con.close()

    # Run T3 computation
    print("\n[2/4] Running T3 computation...")

    pipeline = FeaturePipeline(str(DB_PATH), feature_version='v3.1')
    inserted = pipeline.compute_t3_features(start_date=start_date, end_date=end_date)

    # Verify results
    print("\n[3/4] Verifying results...")

    con = duckdb.connect(str(DB_PATH))

    t3_after = con.execute("SELECT COUNT(*) FROM t3_sepa_features").fetchone()[0]
    t3_in_range = con.execute(f"""
        SELECT COUNT(*)
        FROM t3_sepa_features
        WHERE date BETWEEN '{start_date}' AND '{end_date}'
    """).fetchone()[0]

    print(f"  [OK] t3_sepa_features (after): {t3_after:,} rows")
    print(f"  [OK] t3 rows in test range: {t3_in_range:,}")
    print(f"  [OK] New rows inserted: {inserted:,}")

    # Validate data integrity
    print("\n[4/4] Validating data integrity...")

    # Check for NULLs in critical columns
    null_check = con.execute("""
        SELECT
            COUNT(*) as total_rows,
            SUM(CASE WHEN ticker IS NULL THEN 1 ELSE 0 END) as null_ticker,
            SUM(CASE WHEN date IS NULL THEN 1 ELSE 0 END) as null_date,
            SUM(CASE WHEN close IS NULL THEN 1 ELSE 0 END) as null_close,
            SUM(CASE WHEN rs IS NULL THEN 1 ELSE 0 END) as null_rs
        FROM t3_sepa_features
    """).fetchone()

    total, null_ticker, null_date, null_close, null_rs = null_check

    if null_ticker > 0 or null_date > 0 or null_close > 0:
        print(f"  [ERR] Found NULLs in critical columns:")
        print(f"     ticker: {null_ticker}, date: {null_date}, close: {null_close}")
        con.close()
        return False

    print(f"  [OK] No NULLs in critical columns (ticker, date, close)")
    if total > 0:
        print(f"  [OK] Acceptable NULLs in rs: {null_rs}/{total} ({null_rs/total*100:.1f}%)")

    # Check for duplicates
    dup_check = con.execute("""
        SELECT COUNT(*) as dup_count
        FROM (
            SELECT ticker, date, feature_version, COUNT(*) as cnt
            FROM t3_sepa_features
            GROUP BY ticker, date, feature_version
            HAVING COUNT(*) > 1
        )
    """).fetchone()[0]

    if dup_check > 0:
        print(f"  [ERR] Found {dup_check} duplicate (ticker, date, version) combinations")
        con.close()
        return False

    print(f"  [OK] No duplicate (ticker, date, version) combinations")

    # Sample data
    if t3_after > 0:
        print("\n[SAMPLE] Recent T3 entries:")
        sample = con.execute("""
            SELECT ticker, date, close, rs, trend_ok, breakout_ok
            FROM t3_sepa_features
            ORDER BY date DESC, ticker
            LIMIT 5
        """).fetchall()

        for row in sample:
            print(f"  {row[0]:6s} {row[1]} close={row[2]:7.2f} rs={row[3]:7.2f} trend={row[4]} breakout={row[5]}")

    con.close()

    # Summary
    print("\n" + "=" * 80)
    print("[PASS] T3 Integration Test PASSED")
    print("=" * 80)
    print(f"Summary:")
    print(f"  - Inserted: {inserted:,} rows")
    print(f"  - Total T3 rows: {t3_after:,}")
    print(f"  - SEPA candidates: {sepa_candidates}")
    print(f"  - Data integrity: [OK] No NULLs in critical columns")
    print(f"  - Data integrity: [OK] No duplicates")
    print("=" * 80)

    return True


if __name__ == "__main__":
    success = test_t3_integration()
    sys.exit(0 if success else 1)
