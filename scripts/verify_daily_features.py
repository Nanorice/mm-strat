import duckdb
import pandas as pd
from pathlib import Path

DB_PATH = Path("data/market_data.duckdb")

def verify_db():
    if not DB_PATH.exists():
        print(f"❌ DB not found at {DB_PATH}")
        return

    con = duckdb.connect(str(DB_PATH))
    try:
        # Check tables
        tables = con.execute("SHOW TABLES").fetchall()
        print("Tables:", [t[0] for t in tables])

        if 'daily_features' in [t[0] for t in tables]:
            # Check schema
            columns = con.execute("DESCRIBE daily_features").df()
            print("\nSchema of daily_features:")
            print(columns[['column_name', 'column_type']])
            
            # Check for new columns
            new_cols = ['price_vs_spy', 'price_vs_spy_ma20', 'rs_line_uptrend', 'rs_line_log']
            missing = [c for c in new_cols if c not in columns['column_name'].values]
            if missing:
                print(f"\n❌ Missing columns: {missing}")
            else:
                print(f"\n✅ All new columns present: {new_cols}")

            # Sample Data
            print("\nSample Data (AAPL):")
            df = con.execute("SELECT date, close, price_vs_spy, price_vs_spy_ma20, rs_line_uptrend FROM daily_features WHERE ticker='AAPL' ORDER BY date DESC LIMIT 5").df()
            print(df)
        else:
            print("❌ daily_features table does not exist yet.")

    finally:
        con.close()

if __name__ == "__main__":
    verify_db()
