"""
Daily Scanner - Simplified QSS Workflow
Scans S&P 500 for SEPA-qualifying stocks and tracks Active Buy Signals.

Simplified Logic:
1. Scan universe for stocks with trend_ok = True (SEPA Stage 1 passed)
2. Database tracks when each stock first triggered (signal_date)
3. Database maintains active buy list (stocks that continue to qualify)
4. Output: Active Buy Signals with original trigger dates
"""

import pandas as pd
import sys
from datetime import datetime
from pathlib import Path

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


def run_daily_scanner():
    """
    Simplified daily scanner workflow.
    
    Outputs:
    - Active Buy Signals (stocks that triggered and still qualify)
    - Signal dates (when each stock first triggered)
    """
    print("=" * 80)
    print(f" QSS DAILY SCANNER | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)

    # Initialize components
    data_repo = DataRepository()
    db = DatabaseManager()

    # Step 1: Get Universe
    print("\n[1/5] Fetching S&P 500 Universe...")
    tickers = data_repo.update_universe()
    print(f"       Loaded {len(tickers)} tickers")

    # Step 2: Update Cache
    print("\n[2/5] Updating Price Data Cache...")
    results = data_repo.update_cache(tickers, force=False)
    success_count = sum(results.values())
    print(f"       Updated {success_count}/{len(tickers)} tickers")

    # Step 3: Initialize QSS Components
    print("\n[3/5] Loading Benchmark & Initializing QSS...")
    benchmark_data = data_repo.get_benchmark_data()
    if benchmark_data is None:
        print("       ERROR: Could not load benchmark data!")
        return

    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    strategy = SEPAStrategy(benchmark_data=benchmark_data)

    # Step 4: Scan for SEPA-Qualifying Stocks
    print("\n[4/5] Scanning for SEPA-Qualifying Stocks...")
    
    qualifying_stocks = []  # Stocks with trend_ok = True
    new_triggers_today = []  # Stocks that triggered TODAY (buy = True)
    today = pd.Timestamp.now()
    actual_latest_date = None

    for i, ticker in enumerate(tickers):
        if i % 100 == 0:
            print(f"       Progress: {i}/{len(tickers)}")

        # Load and enrich data
        df = data_repo.get_ticker_data(ticker, use_cache=True)
        if df is None or len(df) < 200:
            continue

        try:
            df = feature_engine.calculate_lightweight_features(df)
        except Exception as e:
            logger.debug(f"Failed to prepare {ticker}: {e}")
            continue

        # Get latest date
        latest_date = df.index[-1]
        if actual_latest_date is None or latest_date > actual_latest_date:
            actual_latest_date = latest_date

        # Generate SEPA signal
        signal = strategy.generate_signals(df, latest_date)
        
        # Check if stock qualifies (trend_ok = True)
        if signal['metadata'].get('trend_ok', False):
            rs_value = df.loc[latest_date, 'RS'] if 'RS' in df.columns else None
            vol_ratio = df.loc[latest_date, 'Vol_Ratio'] if 'Vol_Ratio' in df.columns else None
            
            # Build qualifying stock record
            stock_data = {
                'ticker': ticker,
                'date': latest_date,
                'price': df.loc[latest_date, 'Close'],
                'rs': rs_value,
                'vol_ratio': vol_ratio,
                'atr': df.loc[latest_date, 'ATR'] if 'ATR' in df.columns else None,
                'is_new_trigger': signal['buy']  # True if triggered today
            }
            
            qualifying_stocks.append(stock_data)
            
            # If triggered TODAY, calculate trade plan and add to database
            if signal['buy']:
                trade_plan = strategy.calculate_trade_plan(df, latest_date)
                if trade_plan:
                    new_triggers_today.append({
                        'ticker': ticker,
                        'entry_price': trade_plan['entry_price'],
                        'stop_price': trade_plan['stop_price'],
                        'target_price': trade_plan['target_price'],
                        'risk_pct': trade_plan['risk_pct'],
                        'reward_pct': trade_plan['reward_pct'],
                        'atr': trade_plan['atr'],
                        'rs': rs_value,
                        'vol_ratio': vol_ratio
                    })

    print(f"       Scan complete: {len(qualifying_stocks)} qualifying stocks")
    print(f"       New triggers today: {len(new_triggers_today)}")
    print(f"       Latest data date: {actual_latest_date.strftime('%Y-%m-%d')}")

    # Step 5: Update Database
    print("\n[5/5] Updating Database...")
    current_date = today.strftime('%Y-%m-%d')
    
    # Add new triggers to database Buy List (signal_date = today)
    for trigger in new_triggers_today:
        db.add_to_buy_list(
            ticker=trigger['ticker'],
            signal_date=current_date,
            entry_price=trigger['entry_price'],
            stop_price=trigger['stop_price'],
            target_price=trigger['target_price'],
            atr=trigger.get('atr'),
            rs=trigger.get('rs'),
            vol_ratio=trigger.get('vol_ratio')
        )
    
    print(f"       Added {len(new_triggers_today)} new triggers to database")

    # Display Results
    print("\n" + "=" * 80)
    print(f" ACTIVE BUY SIGNALS | {len(new_triggers_today)} New Today")
    print("=" * 80)

    if new_triggers_today:
        df_new = pd.DataFrame(new_triggers_today)
        print("\n[NEW TRIGGERS TODAY]:\n")
        display_cols = ['ticker', 'entry_price', 'stop_price', 'target_price', 'risk_pct', 'reward_pct', 'vol_ratio']
        print(df_new[display_cols].to_string(index=False))
    else:
        print("\nNo new triggers today.")

    # Get and display Buy List from database (includes previous triggers still qualifying)
    print("\n" + "=" * 80)
    print(" BUY LIST (All Active Signals)")
    print("=" * 80)
    
    buy_list_df = db.get_buy_list(active_only=True)
    
    if not buy_list_df.empty:
        print(f"\nTotal Active Signals: {len(buy_list_df)}\n")
        display_cols = ['ticker', 'signal_date', 'entry_price', 'stop_price', 'target_price', 'volume_ratio']
        print(buy_list_df[display_cols].to_string(index=False))
        
        # Calculate days on list
        buy_list_df['days_on_list'] = (pd.Timestamp(current_date) - pd.to_datetime(buy_list_df['signal_date'])).dt.days
        
        print(f"\n📊 Statistics:")
        print(f"   Average days on list: {buy_list_df['days_on_list'].mean():.1f}")
        print(f"   Newest signal: {buy_list_df['signal_date'].max()}")
        print(f"   Oldest signal: {buy_list_df['signal_date'].min()}")
        
    else:
        print("\nNo active buy signals in database.")

    print("\n" + "=" * 80)
    print("Scanner complete!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    try:
        run_daily_scanner()
    except KeyboardInterrupt:
        print("\n\nScanner interrupted by user.")
    except Exception as e:
        logger.error(f"Scanner failed with error: {e}", exc_info=True)
        print(f"\n[ERROR]: {e}")
