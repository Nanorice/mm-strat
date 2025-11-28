"""
Optimized Daily Scanner - Batch Processing
Uses vectorized operations and batch API calls for maximum efficiency.

Performance improvements:
1. Batch data loading (get_batch_data instead of individual ticker calls)
2. Batch feature calculation (FeatureEngine.process_universe_batch)
3. Reduced API calls (FMP batch endpoint - 100 tickers per call)
4. Parallel-friendly architecture
"""

import pandas as pd
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import time

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.data_engine import DataRepository
from src.strategy import SEPAStrategy
from src.database import DatabaseManager
from src.features import FeatureEngineer
import logging

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_optimized_scanner(scan_date: Optional[str] = None):
    """
    Optimized scanner using batch processing and vectorized operations.
    
    Args:
        scan_date: Optional date to scan (YYYY-MM-DD). If None, uses today.
                   Enables historical backtesting by using only data up to scan_date.
    """
    start_time = time.time()
    
    # Determine scan date
    if scan_date:
        scan_date_obj = pd.Timestamp(scan_date)
    else:
        scan_date_obj = pd.Timestamp.now()
    scan_date_str = scan_date_obj.strftime('%Y-%m-%d')
    
    print("=" * 80)
    print(f" QSS OPTIMIZED SCANNER | {scan_date_str}")
    print("=" * 80)

    # Initialize components
    data_repo = DataRepository()
    db = DatabaseManager()

    # Step 1: Get Universe
    print("\n[1/4] Fetching S&P 500 Universe...")
    tickers = data_repo.update_universe()
    print(f"       Loaded {len(tickers)} tickers")

    # Step 2: Batch Cache Update (FMP batches up to 100 tickers per API call)
    print("\n[2/4] Batch Updating Cache...")
    update_start = time.time()
    results = data_repo.update_cache(tickers, force=False, source='yf')
    success_count = sum(results.values())
    update_time = time.time() - update_start
    print(f"       Updated {success_count}/{len(tickers)} tickers in {update_time:.1f}s")

    # Step 3: Batch Load All Data
    print("\n[3/4] Batch Loading Price Data...")
    load_start = time.time()
    ticker_data = data_repo.get_batch_data(tickers)
    load_time = time.time() - load_start
    print(f"       Loaded {len(ticker_data)} tickers in {load_time:.1f}s")
    
    # Filter out tickers with insufficient data
    valid_ticker_data = {
        ticker: df for ticker, df in ticker_data.items() 
        if df is not None and len(df) >= 200
    }
    print(f"       {len(valid_ticker_data)} tickers have sufficient data (200+ bars)")

    # Step 4: Batch Feature Calculation & SEPA Scanning
    print("\n[4/4] Batch Processing Features & SEPA Screening...")
    scan_start = time.time()
    
    # Initialize QSS components
    benchmark_data = data_repo.get_benchmark_data()
    if benchmark_data is None:
        print("       ERROR: Could not load benchmark data!")
        return
    
    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    strategy = SEPAStrategy(benchmark_data=benchmark_data)
    
    # Batch calculate lightweight features
    print("       Calculating features for all tickers...")
    feature_start = time.time()
    enriched_data = feature_engine.process_universe_batch(valid_ticker_data)
    feature_time = time.time() - feature_start
    print(f"       Features calculated in {feature_time:.1f}s ({len(enriched_data)/feature_time:.1f} tickers/sec)")
    
    # Batch SEPA screening using new batch method
    print("       Batch screening for SEPA signals...")
    screen_start = time.time()
    
    results = strategy.batch_scan_universe(enriched_data, scan_date=scan_date_obj)
    
    screen_time = time.time() - screen_start
    scan_time = time.time() - scan_start
    
    # Extract results
    qualifying_stocks = results['qualifying_stocks']
    new_triggers_today = results['new_triggers']
    actual_latest_date = results['summary']['latest_date']
    
    print(f"       Screening complete in {screen_time:.1f}s")
    print(f"       {len(qualifying_stocks)} qualifying stocks ({len(new_triggers_today)} new triggers)")
    print(f"       Total scan time: {scan_time:.1f}s")
    
    
    # Update Database - Buy List Management
    print("\n[5/5] Managing Buy List...")
    
    
    # Step 1: Load current active buy list (as of scan_date for historical accuracy)
    current_buy_list = db.get_buy_list(active_only=True, as_of_date=scan_date_str)
    tickers_in_buy_list = set(current_buy_list['ticker'].tolist()) if not current_buy_list.empty else set()
    
    # Step 2: Determine qualifying tickers (trend_ok = True)
    qualifying_tickers = set([s['ticker'] for s in qualifying_stocks])
    new_trigger_tickers = set([t['ticker'] for t in new_triggers_today])
    
    # Step 3: Determine additions (new triggers not already in buy list)
    tickers_to_add = [t for t in new_triggers_today if t['ticker'] not in tickers_in_buy_list]
    
    # Step 4: Determine removals (in buy_list but no longer trend_ok)
    tickers_to_remove = tickers_in_buy_list - qualifying_tickers
    
    # Step 5: Execute Additions
    for trigger in tickers_to_add:
        ticker = trigger['ticker']
        signal_price = trigger['entry_price']  # Close price on signal date
        
        # Extract indicator values from enriched data
        ticker_df = enriched_data.get(ticker)
        
        # Get indicator values - use scan_date if available, otherwise use last available
        if ticker_df is not None:
            if scan_date_obj in ticker_df.index:
                row = ticker_df.loc[scan_date_obj]
            else:
                # Use last available date before scan_date
                available_dates = ticker_df.index[ticker_df.index <= scan_date_obj]
                if len(available_dates) > 0:
                    row = ticker_df.loc[available_dates[-1]]
                else:
                    row = None
            
            if row is not None:
                ma50 = row.get('SMA_50')
                ma150 = row.get('SMA_150')
                ma200 = row.get('SMA_200')
                high_52w = row.get('High_52W')
                low_52w = row.get('Low_52W')
            else:
                ma50 = ma150 = ma200 = high_52w = low_52w = None
        else:
            ma50 = ma150 = ma200 = high_52w = low_52w = None
        
        db.add_to_buy_list(
            ticker=ticker,
            signal_date=scan_date_str,
            signal_price=signal_price,
            current_price=signal_price,  # Same as signal_price initially
            rs=trigger.get('rs'),
            vol_ratio=trigger.get('vol_ratio'),
            # Indicator values
            ma50=ma50,
            ma150=ma150,
            ma200=ma200,
            high_52w=high_52w,
            low_52w=low_52w
        )
        db.log_buy_list_activity(
            ticker=ticker,
            action='ADDED',
            action_date=scan_date_str,
            reason='new_trigger',
            entry_price=trigger['entry_price'],
            stop_price=trigger.get('stop_price'),
            target_price=trigger.get('target_price'),
            rs=trigger.get('rs'),
            vol_ratio=trigger.get('vol_ratio')
        )
    
    # Step 6: Update existing tickers (those that remain in buy_list)
    tickers_to_update = tickers_in_buy_list & qualifying_tickers  # Intersection: in buy_list AND still qualifying
    for ticker in tickers_to_update:
        # Find the stock in qualifying_stocks
        stock_data = next((s for s in qualifying_stocks if s['ticker'] == ticker), None)
        if stock_data:
            # Extract updated indicator values
            ticker_df = enriched_data.get(ticker)
            
            # Get indicator values - use scan_date if available, otherwise use last available
            actual_update_date = scan_date_str
            if ticker_df is not None:
                if scan_date_obj in ticker_df.index:
                    row = ticker_df.loc[scan_date_obj]
                else:
                    # Use last available date before scan_date
                    available_dates = ticker_df.index[ticker_df.index <= scan_date_obj]
                    if len(available_dates) > 0:
                        last_date = available_dates[-1]
                        row = ticker_df.loc[last_date]
                        actual_update_date = last_date.strftime('%Y-%m-%d')  # Update to actual data date
                    else:
                        row = None
                
                if row is not None:
                    ma50 = row.get('SMA_50')
                    ma150 = row.get('SMA_150')
                    ma200 = row.get('SMA_200')
                    high_52w = row.get('High_52W')
                    low_52w = row.get('Low_52W')
                else:
                    ma50 = ma150 = ma200 = high_52w = low_52w = None
            else:
                ma50 = ma150 = ma200 = high_52w = low_52w = None
            
            db.update_buy_list_metrics(
                ticker=ticker,
                scan_date=actual_update_date,
                current_price=stock_data['price'],
                rs=stock_data.get('rs'),
                vol_ratio=stock_data.get('vol_ratio'),
                # Indicator values (updated)
                ma50=ma50,
                ma150=ma150,
                ma200=ma200,
                high_52w=high_52w,
                low_52w=low_52w
            )
    
    # Step 7: Execute Removals
    for ticker in tickers_to_remove:
        db.remove_from_buy_list(ticker, reason='trend_broken')
        db.log_buy_list_activity(
            ticker=ticker,
            action='REMOVED',
            action_date=scan_date_str,
            reason='trend_broken'
        )
    
    print(f"       +{len(tickers_to_add)} added, -{len(tickers_to_remove)} removed")
    print(f"       Active buy list: {len(tickers_in_buy_list) + len(tickers_to_add) - len(tickers_to_remove)} tickers")

    # Performance Summary
    total_time = time.time() - start_time
    print("\n" + "=" * 80)
    print(" PERFORMANCE METRICS")
    print("=" * 80)
    print(f"Total scan time: {total_time:.1f}s")
    print(f"  - Cache update: {update_time:.1f}s")
    print(f"  - Data loading: {load_time:.1f}s")
    print(f"  - Feature calc: {feature_time:.1f}s ({len(enriched_data)/feature_time:.1f} tickers/sec)")
    print(f"  - SEPA screening: {screen_time:.1f}s ({len(enriched_data)/screen_time:.1f} tickers/sec)")
    print(f"Throughput: {len(valid_ticker_data)/total_time:.1f} tickers/sec overall")
    
    # Display Results
    print("\n" + "=" * 80)
    print(f" ACTIVE BUY SIGNALS | {len(new_triggers_today)} New Today")
    print("=" * 80)

    if new_triggers_today:
        df_new = pd.DataFrame(new_triggers_today)
        print("\n[NEW TRIGGERS TODAY]:\n")
        display_cols = ['ticker', 'date', 'rs', 'vol_ratio', 'signal_strength']
        # Rename entry_price to last_price for display
        if 'entry_price' in df_new.columns:
            df_new['last_price'] = df_new['entry_price']
            display_cols.insert(1, 'last_price')
        available_cols = [col for col in display_cols if col in df_new.columns]
        print(df_new[available_cols].to_string(index=False))
    else:
        print("\nNo new triggers today.")

    # Get and display Buy List from database
    print("\n" + "=" * 80)
    print(" BUY LIST (All Active Signals)")
    print("=" * 80)
    
    buy_list_df = db.get_buy_list(active_only=True, as_of_date=scan_date_str)
    
    if not buy_list_df.empty:
        print(f"\nTotal Active Signals: {len(buy_list_df)}\n")
        
        # Calculate price changes
        if 'signal_price' in buy_list_df.columns and 'current_price' in buy_list_df.columns:
            buy_list_df['price_change_$'] = buy_list_df['current_price'] - buy_list_df['signal_price']
            buy_list_df['price_change_%'] = ((buy_list_df['current_price'] - buy_list_df['signal_price']) / buy_list_df['signal_price'] * 100)
        
        # Select columns to display (basic info + price metrics + indicator values)
        display_cols = ['ticker', 'signal_date', 'signal_price', 'current_price', 'price_change_$', 'price_change_%',
                       'rs', 'volume_ratio', 'ma50', 'ma150', 'ma200', 'high_52w', 'low_52w', 'last_updated']
        available_cols = [col for col in display_cols if col in buy_list_df.columns]
        
        # Round numeric columns for cleaner display
        display_df = buy_list_df[available_cols].copy()
        numeric_cols = ['signal_price', 'current_price', 'price_change_$', 'price_change_%', 
                       'rs', 'volume_ratio', 'ma50', 'ma150', 'ma200', 'high_52w', 'low_52w']
        for col in numeric_cols:
            if col in display_df.columns:
                # Convert to numeric first (handles object dtypes with None/NaN)
                display_df[col] = pd.to_numeric(display_df[col], errors='coerce')
                # Round if the column has any non-null values
                if display_df[col].notna().any():
                    display_df[col] = display_df[col].round(2)
        
        print(display_df.to_string(index=False))
        
        buy_list_df['days_on_list'] = (pd.Timestamp(scan_date_str) - pd.to_datetime(buy_list_df['signal_date'])).dt.days
        
        print(f"\n📊 Statistics:")
        print(f"   Average days on list: {buy_list_df['days_on_list'].mean():.1f}")
        print(f"   Newest signal: {buy_list_df['signal_date'].max()}")
        print(f"   Oldest signal: {buy_list_df['signal_date'].min()}")
    else:
        print("\nNo active buy signals in database.")
    
    if len(tickers_to_add) > 0 or len(tickers_to_remove) > 0:
        print("\n" + "=" * 80)
        print(f" BUY LIST ACTIVITY | {scan_date_str}")
        print("=" * 80)
        
        if tickers_to_add:
            print(f"\n✅ ADDED ({len(tickers_to_add)}):")
            for t in tickers_to_add:
                print(f"   {t['ticker']} @ ${t['entry_price']:.2f}")
        
        if tickers_to_remove:
            print(f"\n❌ REMOVED ({len(tickers_to_remove)}):")
            for ticker in tickers_to_remove:
                print(f"   {ticker} (trend broken)")

    print("\n" + "=" * 80)
    print(f"Scanner complete! (Total time: {total_time:.1f}s)")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    try:
        # Import for date range mode
        from datetime import datetime, timedelta
        
        # === SINGLE DAY MODE ===
        # Uncomment to run for a single date:
        # run_optimized_scanner(scan_date='2025-11-27')
        
        # === DATE RANGE MODE (for backtesting) ===
        start_date = datetime(2025, 11, 17)
        end_date = datetime(2025, 11, 27)
        current = start_date
        
        while current <= end_date:
            date_str = current.strftime('%Y-%m-%d')
            print(f"\n{'='*80}")
            print(f"SCANNING DATE: {date_str}")
            print(f"{'='*80}\n")
            run_optimized_scanner(scan_date=date_str)
            current += timedelta(days=1)
        
    except KeyboardInterrupt:
        print("\n\nScanner interrupted by user.")
    except Exception as e:
        logger.error(f"Scanner failed with error: {e}", exc_info=True)
        print(f"\n[ERROR]: {e}")


