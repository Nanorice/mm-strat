import pandas as pd
from pathlib import Path
from datetime import datetime
import config

earnings_dir = config.EARNINGS_DIR
files = list(earnings_dir.glob('*.parquet'))

print(f"Found {len(files)} earnings files")

count_stale = 0
tickers_with_null_actuals = []

def check_actuals_updated(cached_df):
    past_earnings = cached_df[~cached_df['is_future']].sort_values('date', ascending=False)
    if past_earnings.empty:
        return False
    
    latest_3 = past_earnings.head(3)
    
    has_null_actuals = (
        latest_3['epsActual'].isna().any() or
        latest_3['revenueActual'].isna().any()
    )
    return has_null_actuals

print("\nChecking a sample of 20 files...")
for f in files[:20]: # Check first 20
    try:
        df = pd.read_parquet(f)
        ticker = f.stem
        
        # Check staleness logic from earnings_engine.py
        
        # Rule 1: Age
        age = (datetime.now() - df['cache_timestamp'].iloc[0]).days
        
        # Rule 3: Null actuals
        null_actuals = check_actuals_updated(df)
        
        if null_actuals:
            count_stale += 1
            tickers_with_null_actuals.append(ticker)
            print(f"[{ticker}] Stale due to NULL ACTUALS. (Age: {age} days)")
            
            # Show the offending rows
            past = df[~df['is_future']].sort_values('date', ascending=False).head(3)
            print(past[['date', 'epsActual', 'revenueActual']].to_string())
            print("-" * 40)
            
    except Exception as e:
        print(f"Error reading {f.name}: {e}")

print(f"\nTotal sample checked: 20")
print(f"Stale due to null actuals: {count_stale}")
