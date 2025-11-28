"""
View Database Buy List and Activity History

This script shows how to query and view:
1. Current buy list (active signals)
2. All buy list entries (including removed/expired)
3. Buy list activity history (all additions/removals)
"""

from src.database import DatabaseManager
import pandas as pd

db = DatabaseManager()

print("=" * 80)
print(" DATABASE BUY LIST VIEWER")
print("=" * 80)

# 1. Current Active Buy List
print("\n[1] CURRENT ACTIVE BUY LIST")
print("-" * 80)
active_buy_list = db.get_buy_list(active_only=True)
if not active_buy_list.empty:
    print(f"Total Active: {len(active_buy_list)}\n")
    print(active_buy_list.to_string(index=False))
else:
    print("No active signals")

# 2. All Buy List Entries (including removed/expired)
print("\n\n[2] ALL BUY LIST ENTRIES (including removed)")
print("-" * 80)
all_buy_list = db.get_buy_list(active_only=False)
if not all_buy_list.empty:
    print(f"Total Records: {len(all_buy_list)}\n")
    # Show subset of columns for readability
    display_cols = ['ticker', 'signal_date', 'status', 'entry_price', 'volume_ratio']
    available_cols = [col for col in display_cols if col in all_buy_list.columns]
    print(all_buy_list[available_cols].to_string(index=False))
else:
    print("No records")

# 3. Buy List Activity History (all additions/removals)
print("\n\n[3] BUY LIST ACTIVITY HISTORY")
print("-" * 80)
activity = db.get_buy_list_activity()
if not activity.empty:
    print(f"Total Events: {len(activity)}\n")
    # Show most recent 20 events
    recent = activity.head(20)
    display_cols = ['ticker', 'action', 'action_date', 'reason', 'entry_price']
    available_cols = [col for col in display_cols if col in recent.columns]
    print(recent[available_cols].to_string(index=False))
    
    if len(activity) > 20:
        print(f"\n... and {len(activity) - 20} more events")
else:
    print("No activity recorded")

# 4. Activity Summary
print("\n\n[4] ACTIVITY SUMMARY")
print("-" * 80)
if not activity.empty:
    additions = activity[activity['action'] == 'ADDED']
    removals = activity[activity['action'] == 'REMOVED']
    print(f"Total Additions: {len(additions)}")
    print(f"Total Removals: {len(removals)}")
    print(f"\nDate Range: {activity['action_date'].min()} to {activity['action_date'].max()}")
    
    # Most active tickers
    ticker_counts = activity['ticker'].value_counts().head(5)
    print(f"\nMost Active Tickers:")
    for ticker, count in ticker_counts.items():
        print(f"  {ticker}: {count} events")

# 5. Database Location
print("\n\n[5] DATABASE LOCATION")
print("-" * 80)
print(f"SQLite Database: {db.db_path}")
print("\nYou can also:")
print("  1. Open with SQLite browser/viewer")
print("  2. Export to CSV using: db.export_to_csv('buy_list', 'output.csv')")
print("  3. Query directly with SQL")

print("\n" + "=" * 80)
