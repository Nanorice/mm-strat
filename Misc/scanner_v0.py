"""
Main Scanner Script - Daily Job
Scans S&P 500 for SEPA setups and updates watchlist database.
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
from src.buy_list_manager import BuyListManager
from src.features import FeatureEngineer  # NEW: QSS Module B
import logging

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_daily_scanner():
    """
    Main scanner routine (QSS Two-Stage Funnel):
    1. Fetch S&P 500 universe
    2. Update data cache
    3. [STAGE 1] Lightweight feature calculation (universe-wide)
    4. [STAGE 2] SEPA screening (Trend → VCP → Trigger)
    5. [FUTURE] Heavyweight feature enrichment for candidates (Phase 2)
    6. Update watchlist database
    7. Display results
    """
    print("=" * 80)
    print(f" SEPA DAILY SCANNER (QSS Architecture) | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)

    # Initialize components
    data_repo = DataRepository()
    db = DatabaseManager()

    # Step 1: Get Universe
    print("\n[1/6] Fetching S&P 500 Universe...")
    tickers = data_repo.update_universe()
    print(f"       Loaded {len(tickers)} tickers")

    # Step 2: Update Cache
    print("\n[2/6] Updating Price Data Cache...")
    results = data_repo.update_cache(tickers, force=False)
    success_count = sum(results.values())
    print(f"       Updated {success_count}/{len(tickers)} tickers")

    # Step 3: Get Benchmark
    print("\n[3/6] Loading Benchmark (SPY)...")
    benchmark_data = data_repo.get_benchmark_data()
    if benchmark_data is None:
        print("       ERROR: Could not load benchmark data!")
        return

    # Initialize QSS components
    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    strategy = SEPAStrategy(benchmark_data=benchmark_data)

    # Step 4: Scan for Setups (QSS Two-Stage Funnel)
    print("\n[4/6] QSS Two-Stage Scanner...")
    print("       Stage 1: Lightweight feature calculation (universe-wide)")
    
    candidates = []  # Buy signals (triggered)
    setup_watchlist = []  # Stage 2 setups (not triggered yet)
    sepa_qualifying = []  # ALL stocks that pass SEPA criteria (for buy_list_manager)
    today = pd.Timestamp.now()
    actual_latest_date = None  # Track the actual latest date in data

    for i, ticker in enumerate(tickers):
        if i % 100 == 0:
            print(f"       Progress: {i}/{len(tickers)}")

        # Load data
        df = data_repo.get_ticker_data(ticker, use_cache=True)
        if df is None or len(df) < 200:
            continue

        # QSS STAGE 1: Calculate lightweight features using FeatureEngine
        try:
            df = feature_engine.calculate_lightweight_features(df)
        except Exception as e:
            logger.debug(f"Failed to prepare {ticker}: {e}")
            continue

        # Get latest date in data
        latest_date = df.index[-1]

        
        # Track the actual latest date across all tickers
        if actual_latest_date is None or latest_date > actual_latest_date:
            actual_latest_date = latest_date

        # QSS STAGE 2: SEPA Three-Stage Screening
        signal = strategy.generate_signals(df, latest_date)

        rs_value = df.loc[latest_date, 'RS'] if 'RS' in df.columns else None
        vol_ratio = df.loc[latest_date, 'Vol_Ratio'] if 'Vol_Ratio' in df.columns else None

        # Check if triggered (buy signal) - add to candidates for display/database
        if signal['buy']:
            # QSS STAGE 3 (Phase 2 TODO): Heavyweight feature enrichment
            # df_enriched = feature_engine.calculate_heavyweight_features(df, ticker)
            # This will add: WorldQuant Alphas, EPS Growth, Sales Acceleration
            
            trade_plan = strategy.calculate_trade_plan(df, latest_date)
            if trade_plan:
                # Add to candidates list for display
                candidates.append({
                    'Ticker': ticker,
                    'Price': trade_plan['entry_price'],
                    'Stop': trade_plan['stop_price'],
                    'Target': trade_plan['target_price'],
                    'Risk %': trade_plan['risk_pct'],
                    'Reward %': trade_plan['reward_pct'],
                    'Vol Ratio': f"{signal['metadata'].get('volume_ratio', 0):.1f}x",
                    'ATR': trade_plan['atr'],
                    'rs': rs_value,
                    'vol_ratio': vol_ratio,
                    'entry_price': trade_plan['entry_price'],
                    'stop_price': trade_plan['stop_price'],
                    'target_price': trade_plan['target_price']
                })
        
        # For buy_list: Track ALL stocks that meet SEPA trend criteria
        # This includes both NEW triggers and CONTINUING qualifiers
        # Stocks persist on buy_list as long as trend_ok = True
        if signal['metadata'].get('trend_ok', False):
            sepa_qualifying.append({
                'ticker': ticker,
                'Close': df.loc[latest_date, 'Close'],
                'rs_rank': rs_value if rs_value is not None else 0.0,
                'volume_ratio': vol_ratio if vol_ratio is not None else 1.0,
                'ATR': df.loc[latest_date, 'ATR'] if 'ATR' in df.columns else 0.0,
                'High_52w': df['High'].rolling(252).max().loc[latest_date]
            })

        # Check if in Stage 2 setup (but NOT triggered) - add to setup watchlist
        elif signal['metadata'].get('trend_ok', False):
            setup_watchlist.append({
                'ticker': ticker,
                'rs': rs_value,
                'vol_ratio': vol_ratio
            })

    print(f"       Scan complete: {len(candidates)} buy signals, {len(setup_watchlist)} in setup phase")

    print(f"       Latest data date: {actual_latest_date.strftime('%Y-%m-%d')}")

    # Step 5: Update Database - Both Lists
    print("\n[5/6] Updating Database...")

    current_date = today.strftime('%Y-%m-%d')

    # Update Setup Watchlist (Stage 2 stocks not triggered yet)
    for setup in setup_watchlist:
        db.add_to_watchlist(
            ticker=setup['ticker'],
            current_date=current_date,
            rs=setup.get('rs'),
            vol_ratio=setup.get('vol_ratio')
        )

    # Update Buy List (stocks with active buy signals)
    for candidate in candidates:
        db.add_to_buy_list(
            ticker=candidate['Ticker'],
            signal_date=current_date,
            entry_price=candidate['entry_price'],
            stop_price=candidate['stop_price'],
            target_price=candidate['target_price'],
            atr=candidate.get('ATR'),
            rs=candidate.get('rs'),
            vol_ratio=candidate.get('vol_ratio')
        )

    # Clean stale entries
    db.clean_stale_watchlist(days_threshold=60)

    # NEW: Update Buy List Manager (CSV-based tracking)
    print("       Updating Buy List CSV tracker...")
    buy_list_mgr = BuyListManager()
    
    # Use actual latest date from data, not 'today'
    update_date = actual_latest_date if actual_latest_date else today
    
    # Prepare signals DataFrame for buy_list_manager (ALL SEPA-qualifying stocks)
    if sepa_qualifying:
        signals_df = pd.DataFrame(sepa_qualifying)
        
        # Update buy_list with performance tracking
        summary = buy_list_mgr.update_buy_list(signals_df, update_date)
        print(f"       Buy List: {summary['active_count']} active | "
              f"+{summary['added_today']} added, -{summary['removed_today']} removed")
    else:
        # Even if no signals today, still update to detect removals
        empty_df = pd.DataFrame(columns=['ticker', 'Close', 'rs_rank', 'volume_ratio'])
        summary = buy_list_mgr.update_buy_list(empty_df, update_date)
        if summary['removed_today'] > 0:
            print(f"       Buy List: {summary['removed_today']} removed (no longer qualify)")

    # Display Results
    print("\n" + "=" * 80)
    print(f" SCAN RESULTS | {len(candidates)} ACTIONABLE SETUPS")
    print("=" * 80)

    if candidates:
        df_results = pd.DataFrame(candidates)
        print("\n[BUY SIGNALS] Triggered Today:\n")
        print(df_results.to_string(index=False))

        print("\n" + "-" * 80)
        print("EXECUTION PLAN:")
        print("1. ENTRY:  Market buy at open OR limit order near close price")
        print("2. STOP:   Hard stop at 'Stop' price (8% fixed)")
        print("3. TARGET: Take profit at 'Target' price (3R = 24%)")
        print("4. SIZE:   12.5% of portfolio per position (max 8 positions)")
        print("-" * 80)

    else:
        print("\n[NO SIGNALS] No triggered setups today.")
        print("   Market may be consolidating or lacking volume.")

    # Display Setup Watchlist (Stage 2 stocks building base)
    print("\n" + "=" * 80)
    print(" SETUP WATCHLIST (Stage 2 - Not Triggered Yet)")
    print("=" * 80)

    watchlist_df = db.get_watchlist(active_only=True)
    if not watchlist_df.empty:
        # Show top 10 by days on watchlist
        top_watchlist = watchlist_df.nlargest(10, 'days_on_watchlist')
        print(f"\nTop 10 by Days Building Base (Total: {len(watchlist_df)}):\n")
        print(top_watchlist[['ticker', 'days_on_watchlist', 'avg_rs', 'avg_volume_ratio']].to_string(index=False))
    else:
        print("\n[EMPTY] No stocks currently in setup phase.")

    # Display Buy List (Active buy signals)
    print("\n" + "=" * 80)
    print(" BUY LIST (Active Signals - Ready to Trade)")
    print("=" * 80)

    buy_list_df = db.get_buy_list(active_only=True)
    if not buy_list_df.empty:
        print(f"\nActive Buy Signals (Total: {len(buy_list_df)}):\n")
        display_cols = ['ticker', 'signal_date', 'entry_price', 'stop_price', 'target_price', 'volume_ratio']
        print(buy_list_df[display_cols].to_string(index=False))
    else:
        print("\n[EMPTY] No active buy signals.")

    # NEW: Display Buy List Performance Summary
    print("\n" + "=" * 80)
    print(" BUY LIST PERFORMANCE TRACKER (CSV)")
    print("=" * 80)
    
    buy_list_summary = buy_list_mgr.get_summary()
    if buy_list_summary['active_count'] > 0:
        print(f"\nActive Candidates: {buy_list_summary['active_count']}")
        print(f"Average Return: {buy_list_summary['avg_return']:.2f}%")
        print(f"Average Days on List: {buy_list_summary['avg_days_on_list']:.1f}")
        
        if buy_list_summary['top_performer']:
            top = buy_list_summary['top_performer']
            print(f"\n🏆 Top Performer: {top['ticker']} "
                  f"({top['return']:.2f}% in {top['days']} days)")
        
        if buy_list_summary['worst_performer']:
            worst = buy_list_summary['worst_performer']
            print(f"📉 Needs Attention: {worst['ticker']} "
                  f"({worst['return']:.2f}% in {worst['days']} days)")
    else:
        print("\n[EMPTY] No active candidates being tracked.")

    print("\n" + "=" * 80)
    print("Scanner complete! Database + Buy List CSV updated.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    try:
        run_daily_scanner()
    except KeyboardInterrupt:
        print("\n\nScanner interrupted by user.")
    except Exception as e:
        logger.error(f"Scanner failed with error: {e}", exc_info=True)
        print(f"\n[ERROR]: {e}")
