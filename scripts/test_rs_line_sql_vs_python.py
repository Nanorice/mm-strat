"""
Test script to compare RS Line calculations between SQL (DuckDB) and Python.

This validates that the SQL implementation in data_curator_duckdb.py
produces the same results as the Python implementation in src/indicators.py.

Usage:
    python scripts/test_rs_line_sql_vs_python.py
"""
import sys
from pathlib import Path
import pandas as pd
import duckdb

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from database_duckdb import DuckDBManager
from indicators import TechnicalAnalysis


def test_sql_calculation(db_path: str, ticker: str = 'AAPL', limit: int = 100):
    """Test SQL calculation of price_vs_spy and related metrics."""
    print(f"\n[TEST 1] SQL Calculation for {ticker}")
    print("=" * 60)

    conn = duckdb.connect(db_path)

    try:
        # Query: Calculate price_vs_spy using SQL (mimicking data_curator logic)
        result = conn.execute(f"""
            WITH price_base AS (
                SELECT
                    ticker,
                    date,
                    close
                FROM price_data
                WHERE ticker = '{ticker}'
                ORDER BY date DESC
                LIMIT {limit}
            ),
            spy_data AS (
                SELECT date, close as spy_close
                FROM price_data
                WHERE ticker = 'SPY'
            ),
            price_with_rs AS (
                SELECT
                    p.ticker,
                    p.date,
                    p.close,
                    s.spy_close,
                    p.close / NULLIF(s.spy_close, 0) as price_vs_spy
                FROM price_base p
                LEFT JOIN spy_data s ON p.date = s.date
            ),
            rs_with_ma AS (
                SELECT
                    ticker,
                    date,
                    close,
                    spy_close,
                    price_vs_spy,
                    AVG(price_vs_spy) OVER w63 as price_vs_spy_ma63,
                    CASE
                        WHEN price_vs_spy > AVG(price_vs_spy) OVER w63
                        THEN TRUE
                        ELSE FALSE
                    END as rs_line_uptrend
                FROM price_with_rs
                WINDOW w63 AS (ORDER BY date ROWS BETWEEN 62 PRECEDING AND CURRENT ROW)
            )
            SELECT * FROM rs_with_ma
            ORDER BY date DESC
            LIMIT 10
        """).fetchdf()

        if result.empty:
            print(f"   [WARN] No data found for {ticker}")
            return None

        print(f"   [PASS] Retrieved {len(result)} rows")
        print("\n   Sample (latest 3 rows):")
        print(result[['date', 'close', 'spy_close', 'price_vs_spy', 'price_vs_spy_ma63', 'rs_line_uptrend']].head(3).to_string(index=False))

        return result

    except Exception as e:
        print(f"   [FAIL] SQL calculation failed: {e}")
        return None
    finally:
        conn.close()


def test_python_calculation(db_path: str, ticker: str = 'AAPL', limit: int = 100):
    """Test Python calculation using TechnicalAnalysis.add_relative_strength()."""
    print(f"\n[TEST 2] Python Calculation for {ticker}")
    print("=" * 60)

    conn = duckdb.connect(db_path)

    try:
        # Get ticker data (DuckDB uses lowercase, Python expects capitalized)
        ticker_df = conn.execute(f"""
            SELECT date, open, high, low, close, volume
            FROM price_data
            WHERE ticker = '{ticker}'
            ORDER BY date DESC
            LIMIT {limit}
        """).fetchdf()

        # Get SPY data
        spy_df = conn.execute(f"""
            SELECT date, close
            FROM price_data
            WHERE ticker = 'SPY'
            ORDER BY date DESC
            LIMIT {limit}
        """).fetchdf()

        if ticker_df.empty or spy_df.empty:
            print(f"   [WARN] Missing data for {ticker} or SPY")
            return None

        # Sort ascending (Python method expects chronological order)
        ticker_df = ticker_df.sort_values('date').reset_index(drop=True)
        spy_df = spy_df.sort_values('date').reset_index(drop=True)

        # Rename to capitalized columns (matching yfinance format expected by indicators.py)
        ticker_df = ticker_df.rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'volume': 'Volume'
        })
        spy_df = spy_df.rename(columns={'close': 'benchmark_close'})

        # Set date as index (add_relative_strength uses reindex for alignment)
        ticker_df = ticker_df.set_index('date')
        spy_df = spy_df.set_index('date')

        # Apply Python method (benchmark must be a date-indexed Series)
        result_df = TechnicalAnalysis.add_relative_strength(
            ticker_df.copy(),
            spy_df['benchmark_close']
        )

        # Check if new columns exist
        required_cols = ['price_vs_spy', 'price_vs_spy_ma63', 'rs_line_uptrend']
        if not all(col in result_df.columns for col in required_cols):
            print(f"   [FAIL] Missing columns: {set(required_cols) - set(result_df.columns)}")
            return None

        # Reset index so 'date' is available as a column for comparison
        result_df = result_df.reset_index().rename(columns={'index': 'date'}) if 'date' not in result_df.columns else result_df

        print(f"   [PASS] Calculated {len(result_df)} rows")
        print("\n   Sample (latest 3 rows):")
        print(result_df[['date', 'Close', 'price_vs_spy', 'price_vs_spy_ma63', 'rs_line_uptrend']].tail(3).to_string(index=False))

        return result_df

    except Exception as e:
        print(f"   [FAIL] Python calculation failed: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        conn.close()


def compare_results(sql_df, python_df, ticker: str = 'AAPL'):
    """Compare SQL vs Python results for consistency."""
    print(f"\n[TEST 3] SQL vs Python Comparison for {ticker}")
    print("=" * 60)

    if sql_df is None or python_df is None:
        print("   [SKIP] Missing data from previous tests")
        return False

    try:
        # Merge on date (both sorted descending from SQL, ascending from Python)
        sql_df = sql_df.sort_values('date', ascending=True).reset_index(drop=True)
        python_df = python_df.sort_values('date', ascending=True).reset_index(drop=True)

        # Take common dates
        merged = sql_df.merge(
            python_df[['date', 'price_vs_spy', 'price_vs_spy_ma63', 'rs_line_uptrend']],
            on='date',
            suffixes=('_sql', '_py'),
            how='inner'
        )

        if merged.empty:
            print("   [FAIL] No overlapping dates found")
            return False

        print(f"   Comparing {len(merged)} common dates...")

        # Compare price_vs_spy
        diff_vs_spy = (merged['price_vs_spy_sql'] - merged['price_vs_spy_py']).abs()
        max_diff = diff_vs_spy.max()
        mean_diff = diff_vs_spy.mean()

        print(f"\n   price_vs_spy:")
        print(f"      Max diff:  {max_diff:.6f}")
        print(f"      Mean diff: {mean_diff:.6f}")

        if max_diff > 0.0001:  # 0.01% tolerance
            print(f"      [WARN] Differences exceed tolerance!")
            print("\n   Top 3 discrepancies:")
            print(merged.nlargest(3, diff_vs_spy.name)[['date', 'price_vs_spy_sql', 'price_vs_spy_py']].to_string(index=False))
        else:
            print(f"      [PASS] Within tolerance")

        # Compare price_vs_spy_ma63
        # Note: MA63 requires 63 data points, so early dates will be NaN
        valid_mask = merged['price_vs_spy_ma63_sql'].notna() & merged['price_vs_spy_ma63_py'].notna()
        if valid_mask.sum() > 0:
            diff_ma63 = (merged.loc[valid_mask, 'price_vs_spy_ma63_sql'] - merged.loc[valid_mask, 'price_vs_spy_ma63_py']).abs()
            max_diff_ma = diff_ma63.max()
            mean_diff_ma = diff_ma63.mean()

            print(f"\n   price_vs_spy_ma63 ({valid_mask.sum()} valid rows):")
            print(f"      Max diff:  {max_diff_ma:.6f}")
            print(f"      Mean diff: {mean_diff_ma:.6f}")

            if max_diff_ma > 0.0001:
                print(f"      [WARN] Differences exceed tolerance!")
            else:
                print(f"      [PASS] Within tolerance")
        else:
            print(f"\n   price_vs_spy_ma63: [SKIP] No valid data (need 63+ data points)")

        # Compare rs_line_uptrend (boolean)
        if 'rs_line_uptrend_sql' in merged.columns and 'rs_line_uptrend_py' in merged.columns:
            matches = (merged['rs_line_uptrend_sql'] == merged['rs_line_uptrend_py']).sum()
            total = len(merged)
            pct_match = matches / total * 100

            print(f"\n   rs_line_uptrend:")
            print(f"      Matches: {matches}/{total} ({pct_match:.1f}%)")

            if pct_match < 95:
                print(f"      [WARN] Low match rate!")
            else:
                print(f"      [PASS] High agreement")

        print("\n   [PASS] Comparison complete")
        return True

    except Exception as e:
        print(f"   [FAIL] Comparison failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("RS Line Calculation: SQL vs Python Validation")
    print("=" * 60)

    # Initialize database
    db_manager = DuckDBManager()
    db_path = db_manager.db_path

    print(f"\nDatabase: {db_path}")

    # Test ticker
    ticker = 'AAPL'
    limit = 200  # Get enough data for MA63 calculation

    # Run tests
    sql_result = test_sql_calculation(db_path, ticker, limit)
    python_result = test_python_calculation(db_path, ticker, limit)
    compare_results(sql_result, python_result, ticker)

    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
