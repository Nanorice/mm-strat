"""
Simple Buy List Database Viewer
Shows current state and recent activity in a clean format
"""

from src.database import DatabaseManager
import pandas as pd

db = DatabaseManager()

print("\n" + "=" * 80)
print("DATABASE BUY LIST VIEWER".center(80))
print("=" * 80)

# 1. Current Active Buy List
print("\n📊 CURRENT ACTIVE BUY LIST")
print("-" * 80)
active = db.get_buy_list(active_only=True)
if not active.empty:
    print(f"\nActive Signals: {len(active)}\n")
    cols = ['ticker', 'signal_date', 'current_price', 'rs', 'volume_ratio', 'last_updated']
    available_cols = [col for col in cols if col in active.columns]
    print(active[available_cols].to_string(index=False))
    
    # Show SEPA criteria for first few tickers
    if len(active) > 0:
        print("\n\n📊 SEPA CRITERIA (First 3 Tickers)")
        print("-" * 80)
        criteria_cols = ['ticker', 'price_above_ma50', 'price_above_ma150', 'price_above_ma200',
                        'ma50_above_ma150', 'ma150_above_ma200', 'ma200_trending_up',
                        'price_above_52w_low_30pct', 'price_within_25pct_of_52w_high']
        available_criteria = [col for col in criteria_cols if col in active.columns]
        if len(available_criteria) > 1:
            print(active[available_criteria].head(3).to_string(index=False))
else:
    print("\n❌ No active signals")

# 2. Recent Activity (Last 10 events)
print("\n\n📋 RECENT ACTIVITY (Last 10 Events)")
print("-" * 80)
activity = db.get_buy_list_activity()
if not activity.empty:
    recent = activity.head(10)
    cols = ['ticker', 'action', 'action_date', 'reason', 'entry_price']
    print(recent[cols].to_string(index=False))
    
    if len(activity) > 10:
        print(f"\n... {len(activity) - 10} more events in database")
else:
    print("\n❌ No activity recorded")

# 3. Quick Stats
print("\n\n📈 STATISTICS")
print("-" * 80)
all_signals = db.get_buy_list(active_only=False)
if not activity.empty:
    additions = len(activity[activity['action'] == 'ADDED'])
    removals = len(activity[activity['action'] == 'REMOVED'])
    print(f"Total Additions: {additions}")
    print(f"Total Removals:  {removals}")
    print(f"Currently Active: {len(active)}")

print(f"\n💾 Database: {db.db_path}")
print("=" * 80 + "\n")
