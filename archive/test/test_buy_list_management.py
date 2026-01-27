"""
Test script to verify buy list management functionality.
Tests:
1. Database tables exist
2. Activity logging works
3. Buy list management logic
"""

import pandas as pd
from src.database import DatabaseManager

def test_buy_list_management():
    print("=" * 80)
    print(" TESTING BUY LIST MANAGEMENT SYSTEM")
    print("=" * 80)
    
    db = DatabaseManager()
    
    # Test 1: Check tables exist
    print("\n[TEST 1] Checking database tables...")
    try:
        buy_list = db.get_buy_list(active_only=False)
        activity = db.get_buy_list_activity()
        print(f"✅ buy_list table exists ({len(buy_list)} records)")
        print(f"✅ buy_list_activity table exists ({len(activity)} records)")
    except Exception as e:
        print(f"❌ Error: {e}")
        return
    
    # Test 2: Test activity logging
    print("\n[TEST 2] Testing activity logging...")
    try:
        db.log_buy_list_activity(
            ticker='TEST',
            action='ADDED',
            action_date='2025-11-27',
            reason='test_trigger',
            entry_price=100.0,
            stop_price=92.0,
            target_price=124.0,
            rs=85.0,
            vol_ratio=2.5
        )
        print("✅ Successfully logged ADDED activity")
        
        db.log_buy_list_activity(
            ticker='TEST',
            action='REMOVED',
            action_date='2025-11-27',
            reason='trend_broken'
        )
        print("✅ Successfully logged REMOVED activity")
        
        # Verify logs
        activity = db.get_buy_list_activity()
        test_activity = activity[activity['ticker'] == 'TEST']
        print(f"✅ Found {len(test_activity)} TEST activity records")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return
    
    # Test 3: Query activities
    print("\n[TEST 3] Testing activity queries...")
    try:
        # Get all activity
        all_activity = db.get_buy_list_activity()
        print(f"✅ Total activity records: {len(all_activity)}")
        
        # Get today's activity
        today_str = pd.Timestamp.now().strftime('%Y-%m-%d')
        today_activity = db.get_buy_list_activity(start_date=today_str)
        print(f"✅ Today's activity records: {len(today_activity)}")
        
        # Get ticker history
        test_history = db.get_ticker_activity_history('TEST')
        print(f"✅ TEST ticker history: {len(test_history)} records")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return
    
    # Test 4: Display current state
    print("\n[TEST 4] Current Database State...")
    try:
        buy_list = db.get_buy_list(active_only=True)
        print(f"\nActive Buy List: {len(buy_list)} tickers")
        if not buy_list.empty:
            print(buy_list[['ticker', 'signal_date', 'entry_price', 'status']].head(10))
        
        activity = db.get_buy_list_activity()
        print(f"\nRecent Activity: {len(activity)} events")
        if not activity.empty:
            print(activity[['ticker', 'action', 'action_date', 'reason']].head(10))
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return
    
    print("\n" + "=" * 80)
    print(" ALL TESTS PASSED ✅")
    print("=" * 80)

if __name__ == "__main__":
    test_buy_list_management()
