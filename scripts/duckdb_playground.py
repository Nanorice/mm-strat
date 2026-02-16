import duckdb
import pandas as pd
import os

# Set pandas display options
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

DB_PATH = 'data/market_data.duckdb'

def inspect_database():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    print(f"Connecting to {DB_PATH}...\n")
    con = duckdb.connect(DB_PATH, read_only=True)

    try:
        # List tables AND views
        tables = con.execute("SHOW TABLES").df()
        print("=== Objects in Database ===")
        print(tables)
        print("\n" + "="*50 + "\n")

        # Iterate through tables and views
        for _, row in tables.iterrows():
            obj_name = row['name']
            print(f"=== Inspecting: {obj_name} ===")
            
            # Schema
            try:
                schema = con.execute(f"DESCRIBE {obj_name}").df()
                print("Schema:")
                print(schema[['column_name', 'column_type']])
            except:
                print("Could not describe object.")
            
            # Count
            try:
                count = con.execute(f"SELECT COUNT(*) FROM {obj_name}").fetchone()[0]
                print(f"\nTotal Rows: {count:,}")
            except:
                print("\nCould not count rows.")
            
            # Sample
            print("\nSample Data (First 5 rows):")
            try:
                sample = con.execute(f"SELECT * FROM {obj_name} LIMIT 5").df()
                print(sample)
            except:
                print("Could not fetch sample.")
            print("\n" + "-"*50 + "\n")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        con.close()

if __name__ == "__main__":
    inspect_database()
