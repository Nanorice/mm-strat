"""
Clear and rebuild buy_list with ML scores for a date range.

This script will:
1. Clear all buy_list and activity records in the specified date range
2. Re-run the scanner for each date to rebuild with corrected ML scores
"""
import sys
import subprocess
from datetime import datetime, timedelta
import sqlite3
sys.path.append('.')
import config

def clear_date_range(start_date: str, end_date: str):
    """Clear buy_list entries in the specified date range."""
    db_path = config.DB_PATH
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Count before
    cursor.execute('SELECT COUNT(*) FROM buy_list WHERE signal_date >= ? AND signal_date <= ?', 
                   (start_date, end_date))
    count_before = cursor.fetchone()[0]
    
    # Delete buy_list entries
    cursor.execute('DELETE FROM buy_list WHERE signal_date >= ? AND signal_date <= ?', 
                   (start_date, end_date))
    
    # Delete activity records  
    cursor.execute('DELETE FROM buy_list_activity WHERE action_date >= ? AND action_date <= ?',
                   (start_date, end_date))
    
    conn.commit()
    conn.close()
    
    print(f"✓ Cleared {count_before} signals from {start_date} to {end_date}")

def rescan_date_range(start_date: str, end_date: str, use_ml: bool = True):
    """Re-run scanner for the date range."""
    print(f"\n{'='*80}")
    print(f"RE-SCANNING: {start_date} to {end_date}")
    print(f"{'='*80}\n")
    
    cmd = ['python', 'optimized_scanner.py', '--date-range', start_date, end_date]
    if use_ml:
        cmd.append('--use-ml')
    
    result = subprocess.run(cmd, capture_output=False)
    
    if result.returncode == 0:
        print(f"\n✓ Re-scan completed successfully")
    else:
        print(f"\n✗ Re-scan failed with exit code {result.returncode}")
    
    return result.returncode == 0

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Clear and rebuild buy_list with ML scores")
    parser.add_argument('--start-date', type=str, required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--no-ml', action='store_true', help='Disable ML scoring')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without deleting')
    
    args = parser.parse_args()
    
    print(f"{'='*80}")
    print(f"REBUILD BUY LIST WITH ML SCORES")
    print(f"{'='*80}")
    print(f"Date range: {args.start_date} to {args.end_date}")
    print(f"ML enabled: {not args.no_ml}")
    print(f"Dry run: {args.dry_run}")
    print()
    
    if args.dry_run:
        db_path = config.DB_PATH
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM buy_list WHERE signal_date >= ? AND signal_date <= ?', 
                       (args.start_date, args.end_date))
        count = cursor.fetchone()[0]
        
        print(f"Would clear {count} signals")
        print("Run without --dry-run to execute")
        conn.close()
    else:
        # Clear old data
        clear_date_range(args.start_date, args.end_date)
        
        # Re-scan
        success = rescan_date_range(args.start_date, args.end_date, use_ml=not args.no_ml)
        
        if success:
            print(f"\n{'='*80}")
            print(f"✓ REBUILD COMPLETE")
            print(f"{'='*80}")
            print("\nRun: python check_new_ml_scores.py")
            print("To verify ML scores are now properly stored")
