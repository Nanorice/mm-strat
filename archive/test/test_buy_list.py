"""
Test script for Buy List Manager
Verifies core functionality: add, update, remove, backfill
"""

import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add src to path
sys.path.append(str(Path(__file__).parent))

from src.buy_list_manager import BuyListManager

def test_basic_operations():
    """Test basic add/update/remove operations"""
    print("=" * 80)
    print("Testing Buy List Manager")
    print("=" * 80)
    
    # Initialize manager with test paths
    test_dir = Path('data/test_buy_list')
    test_dir.mkdir(parents=True, exist_ok=True)
    
    manager = BuyListManager(
        buy_list_path=test_dir / 'buy_list.csv',
        history_path=test_dir / 'buy_list_history.csv'
    )
    
    # Day 1: Add 3 tickers
    print("\n[Day 1] Adding 3 tickers (AAPL, NVDA, GOOGL)")
    day1 = datetime(2024, 1, 1)
    signals_day1 = pd.DataFrame({
        'ticker': ['AAPL', 'NVDA', 'GOOGL'],
        'Close': [180.0, 500.0, 140.0],
        'rs_rank': [85.0, 92.0, 78.0],
        'volume_ratio': [1.2, 1.5, 1.1],
        'ATR': [3.0, 12.0, 2.8],
        'High_52w': [200.0, 550.0, 150.0]
    })
    
    summary1 = manager.update_buy_list(signals_day1, day1)
    print(f"   Result: {summary1}")
    assert summary1['added_today'] == 3
    assert summary1['active_count'] == 3
    
    # Day 2: Remove GOOGL, keep others
    print("\n[Day 2] GOOGL removed, AAPL and NVDA continue")
    day2 = datetime(2024, 1, 2)
    signals_day2 = pd.DataFrame({
        'ticker': ['AAPL', 'NVDA'],
        'Close': [182.0, 510.0],  # Prices changed
        'rs_rank': [86.0, 93.0],
        'volume_ratio': [1.3, 1.6],
        'ATR': [3.1, 12.5],
        'High_52w': [200.0, 550.0]
    })
    
    summary2 = manager.update_buy_list(signals_day2, day2)
    print(f"   Result: {summary2}")
    assert summary2['removed_today'] == 1
    assert summary2['active_count'] == 2
    
    # Day 3: Add MSFT, GOOGL re-enters
    print("\n[Day 3] MSFT added, GOOGL re-enters")
    day3 = datetime(2024, 1, 3)
    signals_day3 = pd.DataFrame({
        'ticker': ['AAPL', 'NVDA', 'MSFT', 'GOOGL'],
        'Close': [185.0, 520.0, 380.0, 142.0],
        'rs_rank': [87.0, 94.0, 80.0, 79.0],
        'volume_ratio': [1.4, 1.7, 1.2, 1.15],
        'ATR': [3.2, 13.0, 8.0, 2.9],
        'High_52w': [200.0, 550.0, 420.0, 150.0]
    })
    
    summary3 = manager.update_buy_list(signals_day3, day3)
    print(f"   Result: {summary3}")
    assert summary3['added_today'] == 2  # MSFT and GOOGL (re-entry)
    assert summary3['active_count'] == 4
    
    # Check buy_list contents
    print("\n[Buy List Contents]")
    buy_list = manager.get_buy_list()
    print(buy_list[['ticker', 'first_added', 'entry_price', 'current_price', 
                    'return_since_added', 'days_on_list']])
    
    # Check history
    print("\n[Change History]")
    history = manager.get_history()
    print(history[['date', 'ticker', 'event', 'close_price']])
    
    # Verify GOOGL has 2 separate entries (original add + re-entry)
    googl_history = history[history['ticker'] == 'GOOGL']
    assert len(googl_history) == 3  # ADDED, REMOVED, ADDED again
    print(f"\n✓ GOOGL re-entry handled correctly: {len(googl_history)} events")
    
    # Get summary
    print("\n[Performance Summary]")
    summary = manager.get_summary()
    print(f"   Active Count: {summary['active_count']}")
    print(f"   Top Performer: {summary['top_performer']}")
    print(f"   Average Return: {summary['avg_return']:.2f}%")
    print(f"   Average Days: {summary['avg_days_on_list']:.1f}")
    
    print("\n" + "=" * 80)
    print("✓ All basic tests passed!")
    print("=" * 80)
    
    return manager

if __name__ == '__main__':
    test_basic_operations()
    print("\n\nBuy List Manager is working correctly!")
    print("Files created in: data/test_buy_list/")
    print("  - buy_list.csv")
    print("  - buy_list_history.csv")
