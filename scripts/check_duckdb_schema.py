"""
Quick script to check current DuckDB schema and sample data.

Usage:
    python scripts/check_duckdb_schema.py
"""
import sys
from pathlib import Path
import duckdb

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from database_duckdb import DuckDBManager


def main():
    print("=" * 60)
    print("DuckDB Schema Check")
    print("=" * 60)

    db_manager = DuckDBManager()
    db_path = db_manager.db_path

    print(f"\nDatabase: {db_path}\n")

    conn = duckdb.connect(db_path)

    try:
        # Check tables
        print("[1] Available Tables:")
        tables = conn.execute("""
            SELECT table_name, COUNT(*) as count
            FROM (
                SELECT DISTINCT table_name
                FROM information_schema.columns
            )
            GROUP BY table_name
            ORDER BY table_name
        """).fetchall()

        for table, col_count in tables:
            print(f"   - {table}: {col_count} columns")

        # Check daily_features columns
        print("\n[2] daily_features Schema:")
        cols = conn.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'daily_features'
            ORDER BY column_name
        """).fetchall()

        print(f"   Total: {len(cols)} columns\n")

        # Check for RS Line columns
        rs_cols = [col for col, _ in cols if 'price_vs_spy' in col or 'rs_line' in col]

        if rs_cols:
            print("   RS Line columns found:")
            for col in rs_cols:
                dtype = [dt for c, dt in cols if c == col][0]
                print(f"      [OK] {col} ({dtype})")
        else:
            print("   [WARN] No RS Line columns found (need migration)")

        # Check row count
        print("\n[3] Data Sample (AAPL latest 3 rows):")

        # Get all columns for display
        all_cols = ', '.join([c for c, _ in cols])

        try:
            sample = conn.execute(f"""
                SELECT date, close, sma_50, sma_200,
                       {'price_vs_spy, price_vs_spy_ma63, rs_line_uptrend' if rs_cols else 'NULL as price_vs_spy'}
                FROM daily_features
                WHERE ticker = 'AAPL'
                ORDER BY date DESC
                LIMIT 3
            """).fetchdf()

            if not sample.empty:
                print(sample.to_string(index=False))
            else:
                print("   No data for AAPL")

        except Exception as e:
            print(f"   Error querying sample: {e}")

        # Check total row count
        total_rows = conn.execute("SELECT COUNT(*) FROM daily_features").fetchone()[0]
        print(f"\n[4] Total rows in daily_features: {total_rows:,}")

        # Check distinct tickers
        ticker_count = conn.execute("SELECT COUNT(DISTINCT ticker) FROM daily_features").fetchone()[0]
        print(f"    Distinct tickers: {ticker_count:,}")

        print("\n" + "=" * 60)
        print("[OK] Schema Check Complete")
        print("=" * 60)

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
