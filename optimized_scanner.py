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
from typing import Optional, Dict
import time
import argparse

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


def run_optimized_scanner(scan_date: Optional[str] = None, csv_output: bool = False,
                         use_ml: bool = False, model_path: Optional[str] = None,
                         skip_cache_update: bool = False, preloaded_data: Optional[Dict[str, pd.DataFrame]] = None):
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
        from src.ml_scorer import MLScorer

        if model_path is None:
            model_path = 'models/model_fold_1.json'

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
        scan_date_obj = pd.Timestamp.now()
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
    print(f"\n[1/{total_steps}] Loading Universe...")
    tickers = data_repo.update_universe()
    print(f"       Loaded {len(tickers)} tickers")

    # Step 2: Batch Cache Update (skipped if already done in date-range mode)
    if not skip_cache_update:
        print(f"\n[2/{total_steps}] Batch Updating Cache...")
        update_start = time.time()
        results = data_repo.update_cache(tickers, force=False, source='yf')
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
        ticker_data = data_repo.get_batch_data(tickers)
        load_time = time.time() - load_start
        print(f"       Loaded {len(ticker_data)} tickers in {load_time:.1f}s")
    else:
        # Use pre-loaded data (date-range optimization)
        ticker_data = preloaded_data
        load_time = 0.0
        print(f"\n[3/{total_steps}] Using Pre-loaded Price Data...")
        print(f"       {len(ticker_data)} tickers available")
    
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


    # Step 4: Batch Feature Calculation & SEPA Scanning
    print(f"\n[4/{total_steps}] Batch Processing Features & SEPA Screening...")
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

    # ML Scoring (if enabled)
    ml_scores = {}  # Dictionary: ticker -> {'probability': float, 'rank': int}
    if use_ml and ml_scorer and len(new_triggers_today) > 0:
        print("\n" + "="*80)
        print(" ML SCORING LAYER")
        print("="*80)
        print(f"\n[5/{total_steps}] ML Model Inference...")
        print(f"       Candidates to score: {len(new_triggers_today)}")
        ml_start = time.time()

        try:
            # Prepare feature DataFrame for ML scoring
            # Need to load fundamental data for ML features
            from src.fundamental_merger import FundamentalMerger

            print("       Loading fundamental data merger...")
            fund_merger = FundamentalMerger()

            # Create feature DataFrame (matching training dataset structure)
            print("       Extracting features for ML candidates...")
            ml_candidates = []
            for trigger in new_triggers_today:
                ticker = trigger['ticker']
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

                # Get fundamental data by creating a small price DataFrame for this single date
                # This allows the merger to do an as-of join
                single_date_df = pd.DataFrame({
                    'Date': [row_date],
                    'Close': [row.get('Close', np.nan)]
                }).set_index('Date')

                # Merge with fundamentals
                try:
                    merged_df = fund_merger.merge_ticker_data(ticker, single_date_df)
                    # Extract fundamental columns (exclude Date and price columns)
                    fund_cols = [c for c in merged_df.columns if c not in ['Date', 'Close', 'Open', 'High', 'Low', 'Volume', 'Adj Close']]
                    fund_data = merged_df[fund_cols].iloc[0] if len(merged_df) > 0 else None
                    if fund_data is None:
                        logger.debug(f"       [{ticker}] No fundamental data available")
                    else:
                        logger.debug(f"       [{ticker}] Fundamental data loaded: {len(fund_cols)} features")
                except Exception as e:
                    logger.warning(f"       [{ticker}] Failed to load fundamentals: {e}")
                    fund_data = None

                # Merge technical + fundamental features
                candidate_features = {
                    'ticker': ticker,
                    'date': scan_date_obj,
                    **row.to_dict(),  # All technical indicators
                }

                # Add fundamental features if available
                if fund_data is not None:
                    candidate_features.update(fund_data.to_dict())

                ml_candidates.append(candidate_features)

            if len(ml_candidates) > 0:
                candidates_df = pd.DataFrame(ml_candidates)
                print(f"       Successfully prepared {len(candidates_df)} candidates for scoring")
                logger.debug(f"       Feature count per candidate: {len(candidates_df.columns) - 2}")  # Exclude ticker, date

                # Score batch
                print("       Running ML model predictions...")
                probabilities, ranks = ml_scorer.score_batch(
                    candidates_df,
                    ticker_column='ticker',
                    date_column='date'
                )
                
                # Check for NaN values
                nan_prob_count = np.isnan(probabilities).sum()
                nan_rank_count = np.isnan(ranks).sum()
                if nan_prob_count > 0 or nan_rank_count > 0:
                    print(f"       [WARN]  NaN values detected - Prob: {nan_prob_count}, Rank: {nan_rank_count}")
                    logger.warning(f"ML scoring produced {nan_prob_count} NaN probabilities and {nan_rank_count} NaN ranks")

                # Store scores (no filtering - all SEPA signals are kept)
                for i, ticker in enumerate(candidates_df['ticker']):
                    prob = probabilities[i]
                    rank = ranks[i]
                    
                    # Convert NaN to None AND numpy types to Python types
                    # SQLite stores numpy.float64 as bytes, causing display issues
                    if np.isnan(prob):
                        prob = None
                    else:
                        prob = float(prob)  # Convert numpy.float64 -> Python float
                    
                    if np.isnan(rank):
                        rank = None
                    else:
                        rank = int(rank)  # Convert numpy.int64 -> Python int
                    
                    ml_scores[ticker] = {
                        'probability': prob,
                        'rank': rank
                    }
                    
                    logger.debug(f"       [{ticker}] ML Score: prob={prob}, rank={rank}")

                ml_time = time.time() - ml_start

                # Calculate valid scores
                valid_probs = probabilities[~np.isnan(probabilities)]
                if len(valid_probs) > 0:
                    print(f"       ✓ Scored {len(candidates_df)} candidates in {ml_time:.1f}s")
                    print(f"       ✓ Valid predictions: {len(valid_probs)}/{len(probabilities)}")
                    print(f"       ✓ Probability range: [{valid_probs.min():.3f}, {valid_probs.max():.3f}]")
                    print(f"       ✓ All SEPA signals retained (ML is informational only)")
                else:
                    print(f"       [WARN]  All {len(probabilities)} predictions resulted in NaN")
                    print(f"       [WARN]  This may indicate missing features or model incompatibility")
            else:
                print("       [WARN]  No candidates with sufficient data for ML scoring")

        except Exception as e:
            print(f"\n       [ERROR] ML scoring failed: {e}")
            print(f"       Proceeding with all SEPA signals (no ML filter)...")
            logger.error(f"ML scoring error: {e}", exc_info=True)
    elif use_ml and ml_scorer and len(new_triggers_today) == 0:
        print(f"\n[5/{total_steps}] ML Scoring: Skipped (no new triggers)")
    
    
    # Update Database - Buy List Management  
    print(f"\n[{total_steps}/{total_steps}] Managing Buy List...")
    
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

        # Get ML scores if available
        ml_prob = None
        ml_rank = None
        ml_model_ver = None
        ml_score_date = None

        if ticker in ml_scores:
            ml_prob = ml_scores[ticker]['probability']
            ml_rank = ml_scores[ticker]['rank']
            ml_model_ver = ml_scorer.model_version if ml_scorer else None
            ml_score_date = scan_date_str
            logger.debug(f"Adding {ticker} to buy_list with ML: prob={ml_prob}, rank={ml_rank}")

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
            # ML scores
            ml_probability=ml_prob,
            ml_rank=ml_rank,
            ml_model_version=ml_model_ver,
            ml_score_date=ml_score_date
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
    
    # Step 8: Recalculate ML Ranks Across Entire Buy List (if ML enabled)
    if use_ml and ml_scorer:
        # Get all active buy list entries
        buy_list_df = db.get_buy_list(active_only=True, as_of_date=scan_date_str)
        
        if not buy_list_df.empty and 'ml_probability' in buy_list_df.columns:
            # Filter to entries that have ML probabilities
            ml_entries = buy_list_df[buy_list_df['ml_probability'].notna()].copy()
            
            if len(ml_entries) > 0:
                # Extract probabilities and calculate ranks
                # Higher probability = lower/better rank (1 = highest probability)
                probabilities = ml_entries['ml_probability'].values
                
                # argsort gives indices from low to high, reverse for high to low
                sorted_indices = np.argsort(probabilities)[::-1]
                
                # Create rank array
                ranks = np.empty(len(probabilities), dtype=int)
                ranks[sorted_indices] = np.arange(1, len(probabilities) + 1)
                
                # Update ranks in database
                for ticker, rank in zip(ml_entries['ticker'], ranks):
                    db.update_buy_list_ml_rank(ticker, int(rank))
                
                logger.info(f"Recalculated ML ranks for {len(ml_entries)} buy list entries")

    
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
    print(f"\n[✓] Scan Complete!\n")
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
    
    if not buy_list_df.empty:
        print(f"\nTotal Active Signals: {len(buy_list_df)}\n")

        # Calculate price changes
        if 'signal_price' in buy_list_df.columns and 'current_price' in buy_list_df.columns:
            buy_list_df['price_change_$'] = buy_list_df['current_price'] - buy_list_df['signal_price']
            buy_list_df['price_change_%'] = ((buy_list_df['current_price'] - buy_list_df['signal_price']) / buy_list_df['signal_price'] * 100)

        # Select columns to display (basic info + price metrics + indicator values + ML)
        display_cols = ['ticker', 'signal_date', 'signal_price', 'current_price', 'price_change_$', 'price_change_%',
                       'rs', 'volume_ratio', 'ml_probability', 'ml_rank', 'ma50', 'ma150', 'ma200', 'high_52w', 'low_52w', 'last_updated']
        available_cols = [col for col in display_cols if col in buy_list_df.columns]
        
        # Round numeric columns for cleaner display
        display_df = buy_list_df[available_cols].copy()
        numeric_cols = ['signal_price', 'current_price', 'price_change_$', 'price_change_%',
                       'rs', 'volume_ratio', 'ml_probability', 'ma50', 'ma150', 'ma200', 'high_52w', 'low_52w']
        for col in numeric_cols:
            if col in display_df.columns:
                # Convert to numeric first (handles object dtypes with None/NaN)
                display_df[col] = pd.to_numeric(display_df[col], errors='coerce')
                # Round if the column has any non-null values
                if display_df[col].notna().any():
                    display_df[col] = display_df[col].round(2)
        
        print(display_df.to_string(index=False))
        
        buy_list_df['days_on_list'] = (pd.Timestamp(scan_date_str) - pd.to_datetime(buy_list_df['signal_date'])).dt.days
        
        print(f"\n[STATS] Statistics:")
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

    args = parser.parse_args()

    try:
        if args.date_range:
            # Date range mode - optimize by updating cache once before scanning all dates
            from datetime import datetime, timedelta

            start_date = datetime.strptime(args.date_range[0], '%Y-%m-%d')
            end_date = datetime.strptime(args.date_range[1], '%Y-%m-%d')
            
            print(f"\n{'='*80}")
            print(f"DATE RANGE MODE: {args.date_range[0]} to {args.date_range[1]}")
            print(f"{'='*80}")
            
            # PRE-SCAN: Update cache once for all dates (major performance improvement)
            print("\n[PRE-SCAN] Updating cache for date range...")
            data_repo = DataRepository()
            tickers = data_repo.update_universe()
            cache_start = time.time()
            results = data_repo.update_cache(tickers, force=False, source='yf')
            success_count = sum(results.values())
            cache_time = time.time() - cache_start
            print(f"            Updated {success_count}/{len(tickers)} tickers in {cache_time:.1f}s")
            print(f"            Cache is now ready for {(end_date - start_date).days + 1} day(s) of scanning\n")
            
            # PRE-LOAD: Load all price data once for entire date range (major optimization)
            print("\n[PRE-SCAN] Loading price data for date range...")
            load_start = time.time()
            all_ticker_data = data_repo.get_batch_data(tickers)
            load_time = time.time() - load_start
            print(f"            Loaded {len(all_ticker_data)} tickers in {load_time:.1f}s")
            print(f"            Data will be filtered by date for each scan (in-memory operation)\n")
            
            # Scan each date in range
            current = start_date
            while current <= end_date:
                date_str = current.strftime('%Y-%m-%d')
                print(f"\n{'='*80}")
                print(f"SCANNING DATE: {date_str}")
                print(f"{'='*80}\n")
                run_optimized_scanner(
                    scan_date=date_str,
                    csv_output=args.csv_output,
                    use_ml=args.use_ml,
                    model_path=args.model_path,
                    skip_cache_update=True,  # Cache already updated in pre-scan
                    preloaded_data=all_ticker_data  # Pass pre-loaded data
                )
                current += timedelta(days=1)
        else:
            # Single day mode
            run_optimized_scanner(
                scan_date=args.scan_date,
                csv_output=args.csv_output,
                use_ml=args.use_ml,
                model_path=args.model_path
            )

    except KeyboardInterrupt:
        print("\n\nScanner interrupted by user.")
    except Exception as e:
        logger.error(f"Scanner failed with error: {e}", exc_info=True)
        print(f"\n[ERROR]: {e}")



