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
import numpy as np
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
import time
import argparse

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.data_engine import DataRepository
from src.strategy import SEPAStrategy
from src.database import DatabaseManager
from src.features import FeatureEngineer
from src.utils import get_latest_trading_day
from src.fundamental_merger import FundamentalMerger
from src.ml_scorer import MLScorer
import logging

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_optimized_scanner(scan_date: Optional[str] = None, csv_output: bool = False,
                         use_ml: bool = False, model_path: Optional[str] = None,
                         skip_cache_update: bool = False, preloaded_data: Optional[Dict[str, pd.DataFrame]] = None,
                         tickers: Optional[List[str]] = None, debug: bool = False):
    """
    Optimized scanner using batch processing and vectorized operations.

    Args:
        scan_date: Optional date to scan (YYYY-MM-DD). If None, uses today.
                   Enables historical backtesting by using only data up to scan_date.
        csv_output: If True, exports buy_list and activity to CSV files
        use_ml: If True, adds ML probability scores to SEPA candidates (informational only)
        model_path: Path to ML model (default: models/model_fold_1.json)
        skip_cache_update: If True, skips cache update step (for date-range mode optimization)
        preloaded_data: Optional pre-loaded price data dict (for date-range mode optimization)
    """
    start_time = time.time()

    # Initialize ML scorer if requested
    ml_scorer = None
    if use_ml:

        if model_path is None:
            model_path = 'models/model_prod.json'

        try:
            ml_scorer = MLScorer(model_path=model_path, log_predictions=True)
            # Extract just filename from path
            import os
            model_name = os.path.basename(model_path)
            print(f"\n[ML] Loaded model: {model_name}")
            print(f"[ML] Model version: {ml_scorer.model_version}")
            print(f"[ML] Features required: {len(ml_scorer.feature_names)}")
            print(f"[ML] Scoring mode: Informational (all SEPA signals retained)")
        except Exception as e:
            print(f"\n[WARN] ML model loading failed: {e}")
            print("        Proceeding without ML scoring...\n")
            use_ml = False
            ml_scorer = None
    
    # Determine scan date
    if scan_date:
        scan_date_obj = pd.Timestamp(scan_date)
    else:
        # Use the most recent completed trading day
        scan_date_obj = get_latest_trading_day()
    scan_date_str = scan_date_obj.strftime('%Y-%m-%d')
    
    print("=" * 80)
    print(f" QSS OPTIMIZED SCANNER | {scan_date_str}")
    print("=" * 80)
    
    # Determine total steps based on ML usage
    total_steps = 6 if use_ml else 4

    # Initialize components
    data_repo = DataRepository()
    db = DatabaseManager()

    # Step 1: Get Universe
    print(f"\n[1/{total_steps}] Loading Ticker Universe...")
    if tickers is None:
        tickers = data_repo.update_universe()
        tickers.append(config.BENCHMARK_TICKER)
        print(f"       Loaded {len(tickers)} tickers")
    else:
        print(f"       Using specified tickers: {', '.join(tickers)} ({len(tickers)} total)")

    # Step 2: Batch Cache Update (skipped if already done in date-range mode)
    # Scanner only needs recent data for indicator calculation (2 years is sufficient)
    # This allows recent IPOs with <2 years of history to still be scanned
    # NOTE: check_min_date=False means we only check if latest data is current, not if it goes back to min_date
    min_date = (pd.Timestamp.now() - pd.DateOffset(years=2)).strftime('%Y-%m-%d')

    if not skip_cache_update:
        print(f"\n[2/{total_steps}] Batch Updating Cache...")
        update_start = time.time()
        results = data_repo.update_cache(tickers, force=False, source='fmp')
        success_count = sum(results.values())
        update_time = time.time() - update_start
        print(f"       Updated {success_count}/{len(tickers)} tickers in {update_time:.1f}s")
    else:
        print(f"\n[2/{total_steps}] Cache Update: Skipped (already updated in pre-scan)")
        update_time = 0.0

    # Step 3: Batch Load All Data (or use preloaded data for date-range mode)
    if preloaded_data is None:
        print(f"\n[3/{total_steps}] Batch Loading Price Data...")
        load_start = time.time()
        # Load data from cache (cache was just updated above)
        # check_min_date=False: Only check latest data is current, skip historical range validation
        ticker_data = data_repo.get_batch_data(
            tickers, 
            min_date=min_date, 
            check_min_date=False,
            force_cache_only=True
        )
        load_time = time.time() - load_start
        print(f"       Loaded {len(ticker_data)} tickers in {load_time:.1f}s")
    
    # Filter data by scan_date if specified (for historical accuracy)
    if scan_date:
        filtered_data = {}
        for ticker, df in ticker_data.items():
            if df is not None and len(df) > 0:
                # Only include data up to scan_date
                mask = df.index <= pd.Timestamp(scan_date)
                filtered_df = df[mask]
                if len(filtered_df) > 0:
                    filtered_data[ticker] = filtered_df
        valid_ticker_data = filtered_data
    else:
        # No date filtering for live scans
        valid_ticker_data = {
            ticker: df for ticker, df in ticker_data.items() 
            if df is not None and len(df) > 0
        }
    
    print(f"       {len(valid_ticker_data)} tickers have data available (filtered to {scan_date_str})")


    # Step 4: Lightweight Feature Calculation & SEPA Screening
    print(f"\n[4/{total_steps}] Batch Processing Lightweight Features & SEPA Screening...")
    scan_start = time.time()
    
    # Initialize QSS components
    benchmark_data = data_repo.get_benchmark_data(
        check_min_date=False,
        required_end_date=scan_date,
        force_cache_only=True
    )
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
    trend_ok_stocks = results.get('trend_ok_stocks', [])
    breakout_stocks = results.get('breakout_stocks', [])
    qualifying_stocks = results.get('qualifying_stocks', [])
    new_triggers_today = results['new_triggers']

    print(f"       Screening complete in {screen_time:.1f}s")
    print(f"       Trend OK (C1-C8): {len(trend_ok_stocks)} stocks")
    print(f"       Breakout (C9-C11): {len(breakout_stocks)} stocks")
    print(f"       Full SEPA (C1-C11): {len(qualifying_stocks)} stocks")
    print(f"       New triggers (0->1): {len(new_triggers_today)} stocks")
    print(f"       Total scan time: {scan_time:.1f}s")

    
    # Update Database - Buy List Management  
    print(f"\n[5/{total_steps}] Managing Buy List...")
    
    # Temporal Consistency Check - Detect backward scans
    all_signals = db.get_buy_list(active_only=False)
    if not all_signals.empty:
        earliest_signal_date = pd.to_datetime(all_signals['signal_date']).min()
        
        if pd.Timestamp(scan_date_str) < earliest_signal_date:
            print(f"\n       [WARN]  BACKWARD SCAN DETECTED")
            print(f"       Scan date: {scan_date_str} is before earliest signal: {earliest_signal_date.date()}")
            print(f"       Clearing future signals to maintain temporal consistency...")
            
            # Optional: Backup to CSV before clearing
            if csv_output:
                from pathlib import Path
                backup_dir = Path(config.DATA_DIR) / 'scanner_output' / 'backups'
                backup_dir.mkdir(parents=True, exist_ok=True)
                
                backup_path = backup_dir / f'buy_list_activity_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
                db.export_to_csv('buy_list_activity', str(backup_path))
                print(f"       [FILE] Activity backup saved: {backup_path.name}")
            
            # Clear future signals
            deleted = db.clear_future_signals(scan_date_str)
            print(f"       [OK] Cleared {deleted['buy_list_deleted']} signals and {deleted['activity_deleted']} activity records")
    
    # Load current active buy list (as of scan_date for historical accuracy)
    current_buy_list = db.get_buy_list(active_only=True, as_of_date=scan_date_str)

    tickers_in_buy_list = set(current_buy_list['ticker'].tolist()) if not current_buy_list.empty else set()
    trend_ok_tickers = set([s['ticker'] for s in trend_ok_stocks])
    new_trigger_tickers = set([t['ticker'] for t in new_triggers_today])

    tickers_to_add = set([t['ticker'] for t in new_triggers_today if t['ticker'] not in tickers_in_buy_list])
    tickers_to_remove = tickers_in_buy_list - trend_ok_tickers

    active_tickers = (tickers_to_add | tickers_in_buy_list) - tickers_to_remove
    
    # Execute Removals
    for ticker in tickers_to_remove:
        db.remove_from_buy_list(ticker, reason='trend_broken')
        db.log_buy_list_activity(
            ticker=ticker,
            action='REMOVED',
            action_date=scan_date_str,
            reason='trend_broken'
        )

    # Execute Additions
    for trigger in new_triggers_today:
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

        # Get ML scores and features if available
        ml_prob = None
        ml_rank = None
        ml_model_ver = None
        ml_score_date = None
        ml_features_dict = None

        # if ticker in ml_scores:
        #     ml_prob = ml_scores[ticker]['probability']
        #     ml_rank = ml_scores[ticker]['rank']
        #     ml_features_dict = ml_scores[ticker].get('features')  # Extract features
        #     ml_model_ver = ml_scorer.model_version if ml_scorer else None
        #     ml_score_date = scan_date_str
        #     logger.debug(f"Adding {ticker} to buy_list with ML: prob={ml_prob}, rank={ml_rank}, features={len(ml_features_dict) if ml_features_dict else 0}")

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
            low_52w=low_52w,
            # ML scores and features
            ml_probability=ml_prob,
            ml_rank=ml_rank,
            ml_model_version=ml_model_ver,
            ml_score_date=ml_score_date,
            ml_features=ml_features_dict
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
    
    # Update existing tickers (those that remain in buy_list)
    # Only check trend_ok (C1-C8) - allows tickers with weak volume to stay
    tickers_to_update = tickers_in_buy_list & trend_ok_tickers  # Intersection: in buy_list AND still trend OK
    for ticker in tickers_to_update:
        # Find the stock in trend_ok_stocks
        stock_data = next((s for s in trend_ok_stocks if s['ticker'] == ticker), None)
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

    print(f"       Preparing scoring for {len(active_tickers)} existing tickers with ML...")
    ml_rescore_start = time.time()
    fund_merger = FundamentalMerger()

    # Prepare features for existing tickers
    ml_rescore_candidates = []
    for ticker in active_tickers:
        ticker_df = enriched_data.get(ticker)
        
        if ticker_df is None or len(ticker_df) == 0:
            continue
        
        # get heavyweight features
        ticker_df = feature_engine.calculate_heavyweight_features(ticker_df, ticker)

        # Get latest row (or row at scan_date)
        if scan_date_obj in ticker_df.index:
            row_date = scan_date_obj
            row = ticker_df.loc[scan_date_obj]
        else:
            # Use last available date
            available_dates = ticker_df.index[ticker_df.index <= scan_date_obj]
            if len(available_dates) > 0:
                row_date = available_dates[-1]
                row = ticker_df.loc[row_date]
            else:
                continue
        
        # Get fundamental data
        single_date_df = pd.DataFrame({
            'Date': [row_date],
            'Close': [row.get('Close', np.nan)]
        }).set_index('Date')

        
        try:
            merged_df = fund_merger.merge_ticker_data(ticker, single_date_df)
            fund_cols = [c for c in merged_df.columns if c not in ['Date', 'Close', 'Open', 'High', 'Low', 'Volume', 'Adj Close']]
            fund_data = merged_df[fund_cols].iloc[0] if len(merged_df) > 0 else None
        except Exception as e:
            logger.warning(f"       [{ticker}] Failed to load fundamentals for re-scoring: {e}")
            fund_data = None
        
        # Merge technical + fundamental features
        candidate_features = {
            'ticker': ticker,
            'date': scan_date_obj,
            **row.to_dict(),
        }
        
        if fund_data is not None:
            candidate_features.update(fund_data.to_dict())
        
        ml_rescore_candidates.append(candidate_features)


    # Score existing tickers with ML (if enabled)
    if use_ml and ml_scorer:
        print(f"       Scoring {len(tickers_to_update)} existing tickers with ML...")
        ml_rescore_start = time.time()
        
        from src.fundamental_merger import FundamentalMerger
        fund_merger = FundamentalMerger()
        
        # Prepare features for existing tickers
        ml_rescore_candidates = []
        for ticker in active_tickers:
            ticker_df = enriched_data.get(ticker)
            
            if ticker_df is None or len(ticker_df) == 0:
                continue
            
            # Get latest row (or row at scan_date)
            if scan_date_obj in ticker_df.index:
                row_date = scan_date_obj
                row = ticker_df.loc[scan_date_obj]
            else:
                # Use last available date
                available_dates = ticker_df.index[ticker_df.index <= scan_date_obj]
                if len(available_dates) > 0:
                    row_date = available_dates[-1]
                    row = ticker_df.loc[row_date]
                else:
                    continue
            
            # Get fundamental data
            single_date_df = pd.DataFrame({
                'Date': [row_date],
                'Close': [row.get('Close', np.nan)]
            }).set_index('Date')
            
            try:
                merged_df = fund_merger.merge_ticker_data(ticker, single_date_df)
                fund_cols = [c for c in merged_df.columns if c not in ['Date', 'Close', 'Open', 'High', 'Low', 'Volume', 'Adj Close']]
                fund_data = merged_df[fund_cols].iloc[0] if len(merged_df) > 0 else None
            except Exception as e:
                logger.warning(f"       [{ticker}] Failed to load fundamentals for re-scoring: {e}")
                fund_data = None
            
            # Merge technical + fundamental features
            candidate_features = {
                'ticker': ticker,
                'date': scan_date_obj,
                **row.to_dict(),
            }
            
            if fund_data is not None:
                candidate_features.update(fund_data.to_dict())
            
            ml_rescore_candidates.append(candidate_features)
        
        # Score existing tickers
        if len(ml_rescore_candidates) > 0:
            candidates_df = pd.DataFrame(ml_rescore_candidates)
            
            try:
                probabilities, _ = ml_scorer.score_batch(
                    candidates_df,
                    scan_date=scan_date_str
                )
                
                # Update ML scores in database (ranks will be recalculated in Step 8)
                for idx, ticker in enumerate(candidates_df['ticker']):
                    ml_prob = float(probabilities[idx])
                    
                    # Get existing entry to preserve other data
                    buy_list_df = db.get_buy_list(active_only=True, as_of_date=scan_date_str)
                    ticker_entry = buy_list_df[buy_list_df['ticker'] == ticker]
                    
                    if not ticker_entry.empty:
                        # Update with ML scores
                        import json
                        ml_features_dict = candidates_df.iloc[idx].drop(['ticker', 'date']).to_dict()
                        
                        db.update_buy_list_metrics(
                            ticker=ticker,
                            scan_date=scan_date_str,
                            current_price=ticker_entry.iloc[0]['current_price'],
                            rs=ticker_entry.iloc[0].get('rs'),
                            vol_ratio=ticker_entry.iloc[0].get('volume_ratio'),
                            ma50=ticker_entry.iloc[0].get('ma50'),
                            ma150=ticker_entry.iloc[0].get('ma150'),
                            ma200=ticker_entry.iloc[0].get('ma200'),
                            high_52w=ticker_entry.iloc[0].get('high_52w'),
                            low_52w=ticker_entry.iloc[0].get('low_52w'),
                            ml_probability=ml_prob,
                            ml_model_version=ml_scorer.model_version,
                            ml_score_date=scan_date_str,
                            ml_features=json.dumps(ml_features_dict)
                        )
                # calculate and sort by ml rank

                ml_rescore_time = time.time() - ml_rescore_start
                print(f"       Re-scored {len(candidates_df)} tickers in {ml_rescore_time:.1f}s")
                logger.info(f"ML re-scoring took {ml_rescore_time:.1f}s for {len(candidates_df)} tickers")
                
            except Exception as e:
                logger.error(f"Failed to re-score existing tickers: {e}")
    
    
    print(f"       +{len(tickers_to_add)} added, -{len(tickers_to_remove)} removed")
    print(f"       Active buy list: {len(tickers_in_buy_list) + len(tickers_to_add) - len(tickers_to_remove)} tickers")
    
    # CSV Export (optional)
    if csv_output:
        from pathlib import Path
        output_dir = Path(config.DATA_DIR) / 'scanner_output'
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Export buy_list
        buy_list_path = output_dir / f'buy_list_{scan_date_str}.csv'
        buy_list_current = db.get_buy_list(active_only=True, as_of_date=scan_date_str)
        buy_list_current.to_csv(buy_list_path, index=False)
        
        # Export buy_list_activity (all history)
        activity_path = output_dir / f'buy_list_activity_{scan_date_str}.csv'
        db.export_to_csv('buy_list_activity', str(activity_path))
        
        print(f"\n       [FILE] Exported to CSV:")
        print(f"          {buy_list_path}")
        print(f"          {activity_path}")

    # Performance Summary
    total_time = time.time() - start_time
    print(f"\n[OK] Scan Complete!\n")
    print("=" * 80)
    print(" PERFORMANCE METRICS")
    print("=" * 80)
    print(f"Total scan time: {total_time:.1f}s")
    print(f"  - Cache update: {update_time:.1f}s")
    print(f"  - Data loading: {load_time:.1f}s")
    print(f"  - Feature calc: {feature_time:.1f}s ({len(enriched_data)/feature_time:.1f} tickers/sec)")
    print(f"  - SEPA screening: {screen_time:.1f}s ({len(enriched_data)/screen_time:.1f} tickers/sec)")
    if use_ml and 'ml_time' in locals():
        print(f"  - ML scoring: {ml_time:.1f}s")
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
    
    if len(tickers_to_add) > 0 or len(tickers_to_remove) > 0:
        print("\n" + "=" * 80)
        print(f" BUY LIST ACTIVITY | {scan_date_str}")
        print("=" * 80)
        
        if tickers_to_add:
            print(f"\n[+] ADDED ({len(tickers_to_add)}):")
            for t in tickers_to_add:
                print(f"   {t['ticker']} @ ${t['entry_price']:.2f}")
        
        if tickers_to_remove:
            print(f"\n[-] REMOVED ({len(tickers_to_remove)}):")
            for ticker in tickers_to_remove:
                print(f"   {ticker} (trend broken)")

    print("\n" + "=" * 80)
    print(f"Scanner complete! (Total time: {total_time:.1f}s)")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QSS Optimized Scanner with ML Integration")
    parser.add_argument('--scan-date', type=str, help='Scan date (YYYY-MM-DD). Default: today')
    parser.add_argument('--csv-output', action='store_true', help='Export results to CSV')
    parser.add_argument('--use-ml', action='store_true', help='Enable ML scoring')
    parser.add_argument('--model-path', type=str, default='models/model_fold_1.json',
                       help='Path to ML model (default: models/model_fold_1.json)')
    parser.add_argument('--date-range', nargs=2, metavar=('START', 'END'),
                       help='Scan date range (YYYY-MM-DD YYYY-MM-DD)')
    parser.add_argument('--tickers', nargs='+', metavar='TICKER',
                       help='Specific tickers to scan (e.g., --tickers WMT NUE AAPL)')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug mode to show detailed metrics for specified tickers')

    args = parser.parse_args()

    # Single day mode
    run_optimized_scanner(
        scan_date=args.scan_date,
        csv_output=args.csv_output,
        use_ml=args.use_ml,
        model_path=args.model_path,
        tickers=args.tickers,
        debug=args.debug,
        skip_cache_update=True
    )




