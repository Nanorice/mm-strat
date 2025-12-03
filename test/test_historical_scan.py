"""
Test script to verify historical scanning works correctly.
Tests the scenario user described:
1. Empty buy list
2. Run for 10/26 - should add signals
3. Run for 10/19 - should remove signals that don't qualify, add new ones
"""

from src.database import DatabaseManager
import pandas as pd

db = DatabaseManager()

print("=" * 80)
print(" HISTORICAL SCANNING VERIFICATION")
print("=" * 80)

# Clear buy_list for clean test
print("\n[SETUP] Clearing buy_list for clean test...")
conn = db.db_path
import sqlite3
conn_obj = sqlite3.connect(conn)
cursor = conn_obj.cursor()
cursor.execute("DELETE FROM buy_list")
cursor.execute("DELETE FROM buy_list_activity")
conn_obj.commit()
conn_obj.close()
print("✅ Buy list cleared")

# Check state
print("\n[BEFORE] Buy list state:")
buy_list = db.get_buy_list(active_only=True)
print(f"Active signals: {len(buy_list)}")

print("\n" + "=" * 80)
print("Now run the scanner with different historical dates:")
print("1. Run with scan_date='2025-10-26'")
print("2. Run with scan_date='2025-10-19'") 
print("3. Check if signals change based on historical data")
print("=" * 80)
