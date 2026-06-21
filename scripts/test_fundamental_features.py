"""
Test script for fundamental_features computation.
Tests the new _compute_fundamental_features() method with a small sample.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from data_curator_duckdb import DuckDBDataCurator
import duckdb

# Test with 5 tickers
TEST_TICKERS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']

def main():
    print("=" * 80)
    print("Testing Fundamental Features Computation")
    print("=" * 80)
    print(f"Test tickers: {', '.join(TEST_TICKERS)}")
    print()

    # Initialize curator
    curator = DuckDBDataCurator(dual_mode=False)

    # Test the method
    try:
        curator._compute_fundamental_features(tickers=TEST_TICKERS)
        print("\n[OK] Computation completed successfully")

        # Verify results
        conn = duckdb.connect('data/market_data.duckdb', read_only=True)

        print("\n" + "=" * 80)
        print("Verification")
        print("=" * 80)

        # Count rows per ticker
        result = conn.execute("""
            SELECT ticker, COUNT(*) as row_count
            FROM fundamental_features
            WHERE ticker IN ('AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA')
            GROUP BY ticker
            ORDER BY ticker
        """).fetchdf()

        print("\nRows per ticker:")
        print(result.to_string(index=False))

        # Sample data
        print("\n" + "=" * 80)
        print("Sample Data (AAPL latest 3 quarters)")
        print("=" * 80)
        sample = conn.execute("""
            SELECT
                filing_date,
                fiscal_period,
                revenue,
                eps_diluted,
                revenue_growth_yoy,
                eps_growth_yoy,
                gross_margin,
                operating_margin,
                roe
            FROM fundamental_features
            WHERE ticker = 'AAPL'
            ORDER BY filing_date DESC
            LIMIT 3
        """).fetchdf()

        print(sample.to_string(index=False))

        # Check for NULL values in key columns
        print("\n" + "=" * 80)
        print("Data Quality Check")
        print("=" * 80)
        null_check = conn.execute("""
            SELECT
                COUNT(*) as total_rows,
                SUM(CASE WHEN revenue IS NULL THEN 1 ELSE 0 END) as null_revenue,
                SUM(CASE WHEN eps_growth_yoy IS NULL THEN 1 ELSE 0 END) as null_eps_growth,
                SUM(CASE WHEN gross_margin IS NULL THEN 1 ELSE 0 END) as null_gross_margin,
                SUM(CASE WHEN roe IS NULL THEN 1 ELSE 0 END) as null_roe
            FROM fundamental_features
            WHERE ticker IN ('AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA')
        """).fetchdf()

        print(null_check.to_string(index=False))

        conn.close()

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0

if __name__ == "__main__":
    exit(main())
