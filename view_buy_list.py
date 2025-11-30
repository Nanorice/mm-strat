"""
View Current Buy List from Database
Quick script to inspect active buy signals
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.append(str(Path(__file__).parent))
from src.database import DatabaseManager

def main():
    db = DatabaseManager()
    
    # Get active buy list
    buy_list = db.get_buy_list(active_only=True)
    
    if buy_list.empty:
        print("\n📋 No active buy signals in database.\n")
        return
    
    print(f"\n{'='*80}")
    print(f" ACTIVE BUY LIST | {len(buy_list)} signals")
    print(f"{'='*80}\n")
    
    # Calculate days on list and price changes
    buy_list['days_on_list'] = (pd.Timestamp.now() - pd.to_datetime(buy_list['signal_date'])).dt.days
    
    if 'signal_price' in buy_list.columns and 'current_price' in buy_list.columns:
        buy_list['price_change_%'] = ((buy_list['current_price'] - buy_list['signal_price']) / buy_list['signal_price'] * 100)
    
    # Display columns
    display_cols = ['ticker', 'signal_date', 'signal_price', 'current_price', 'price_change_%', 
                   'days_on_list', 'rs', 'volume_ratio', 'ma50', 'ma150', 'ma200', 'last_updated']
    available_cols = [col for col in display_cols if col in buy_list.columns]
    
    # Format for display
    display_df = buy_list[available_cols].copy()
    numeric_cols = ['signal_price', 'current_price', 'price_change_%', 'rs', 'volume_ratio', 
                   'ma50', 'ma150', 'ma200']
    for col in numeric_cols:
        if col in display_df.columns:
            display_df[col] = pd.to_numeric(display_df[col], errors='coerce').round(2)
    
    print(display_df.to_string(index=False))
    
    # Summary stats
    print(f"\n📊 Summary:")
    print(f"   Total signals: {len(buy_list)}")
    print(f"   Average days on list: {buy_list['days_on_list'].mean():.1f}")
    if 'price_change_%' in buy_list.columns:
        avg_change = buy_list['price_change_%'].mean()
        print(f"   Average price change: {avg_change:+.2f}%")
        winners = len(buy_list[buy_list['price_change_%'] > 0])
        print(f"   Winners: {winners}/{len(buy_list)} ({winners/len(buy_list)*100:.1f}%)")
    
    print(f"\n{'='*80}\n")

if __name__ == "__main__":
    main()
