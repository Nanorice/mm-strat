"""
Test backward scan detection
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.append(str(Path(__file__).parent))
from src.database import DatabaseManager

db = DatabaseManager()

# Check current state
all_signals = db.get_buy_list(active_only=False)
print(f"\n📊 Current Database State:")
print(f"   Total signals: {len(all_signals)}")

if not all_signals.empty:
    earliest = pd.to_datetime(all_signals['signal_date']).min()
    latest = pd.to_datetime(all_signals['signal_date']).max()
    print(f"   Earliest signal: {earliest.date()}")
    print(f"   Latest signal: {latest.date()}")
    
    # Show all signals
    print(f"\n   Signals by date:")
    signal_counts = all_signals.groupby('signal_date').size()
    for date, count in signal_counts.items():
        print(f"      {date}: {count} signals")
else:
    print("   (empty)")

print("\n")
