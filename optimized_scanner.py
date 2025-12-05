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
    print(f"\n[1/{total_steps}] Loading Universe...")
    if tickers is None:
        tickers = data_repo.update_universe()
        print(f"       Loaded {len(tickers)} tickers")
    else:
        print(f"       Using specified tickers: {', '.join(tickers)} ({len(tickers)} total)")

    # Step 2: Batch Cache Update (skipped if already done in date-range mode)
    if not skip_cache_update:
        print(f"\n[2/{total_steps}] Batch Updating Cache...")
        update_start = time.time()
        # Scanner only needs recent data for indicator calculation (2 years is sufficient)
        min_date = (pd.Timestamp.now() - pd.DateOffset(years=2)).strftime('%Y-%m-%d')
        results = data_repo.update_cache(tickers, force=False, source='fmp', min_date=min_date)
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
    trend_ok_stocks = results.get('trend_ok_stocks', [])
    breakout_stocks = results.get('breakout_stocks', [])
    qualifying_stocks = results.get('qualifying_stocks', [])
    new_triggers_today = results['new_triggers']
    actual_latest_date = results['summary']['latest_date']

    print(f"       Screening complete in {screen_time:.1f}s")
    print(f"       Trend OK (C1-C8): {len(trend_ok_stocks)} stocks")
    print(f"       Breakout (C9-C11): {len(breakout_stocks)} stocks")
    print(f"       Full SEPA (C1-C11): {len(qualifying_stocks)} stocks")
    print(f"       New triggers (0->1): {len(new_triggers_today)} stocks")
    print(f"       Total scan time: {scan_time:.1f}s")

    # DEBUG MODE: Print detailed metrics for specified tickers
    if debug and tickers:
        print("\n" + "=" * 80)
        print(" DEBUG MODE - Detailed Metrics")
        print("=" * 80)

        for ticker in tickers:
            print(f"\n[{ticker}]")
            print("-" * 80)

            # Check if ticker has data
            if ticker not in enriched_data:
                print(f"  [X] No data available for {ticker}")
                continue

            ticker_df = enriched_data[ticker]

            # Get data at scan_date or latest available
            if scan_date_obj in ticker_df.index:
                row_date = scan_date_obj
                row = ticker_df.loc[scan_date_obj]
            else:
                available_dates = ticker_df.index[ticker_df.index <= scan_date_obj]
                if len(available_dates) > 0:
                    row_date = available_dates[-1]
                    row = ticker_df.loc[row_date]
                else:
                    print(f"  [X] No data available at or before {scan_date_str}")
                    continue

            print(f"  Date: {row_date.strftime('%Y-%m-%d')}")
            print(f"  Close Price: ${row['Close']:.2f}")

            # Check if ticker is in different lists
            trend_ok_tickers_set = set([s['ticker'] for s in trend_ok_stocks])
            breakout_tickers_set = set([s['ticker'] for s in breakout_stocks])
            qualified_tickers_set = set([s['ticker'] for s in qualifying_stocks])
            trigger_tickers_set = set([t['ticker'] for t in new_triggers_today])

            has_trend = ticker in trend_ok_tickers_set
            has_breakout = ticker in breakout_tickers_set
            qualified = ticker in qualified_tickers_set
            triggered = ticker in trigger_tickers_set

            # Get split criteria from centralized source (vectorized_screening.py)
            from src.vectorized_screening import VectorizedSEPAScreener
            trend_mask, breakout_mask = VectorizedSEPAScreener.screen_single_ticker_split(ticker_df)

            # Extract values at scan_date
            trend_ok_at_date = trend_mask.loc[row_date] if row_date in trend_mask.index else False
            breakout_ok_at_date = breakout_mask.loc[row_date] if row_date in breakout_mask.index else False
            full_sepa_at_date = trend_ok_at_date and breakout_ok_at_date

            print(f"\n  SEPA Status:")
            print(f"    Trend (C1-C8):        {'[PASS]' if trend_ok_at_date else '[FAIL]'}")
            print(f"    Breakout (C9-C11):    {'[PASS]' if breakout_ok_at_date else '[FAIL]'}")
            print(f"    Full Qualification:   {'[PASS]' if full_sepa_at_date else '[FAIL]'}")
            if triggered:
                print(f"    New Trigger:          [PASS] (0->1 transition)")

            # Extract price and indicators for detailed display
            price = row['Close']
            ma50 = row.get('SMA_50', np.nan)
            ma150 = row.get('SMA_150', np.nan)
            ma200 = row.get('SMA_200', np.nan)
            high_52w = row.get('High_52W', np.nan)
            low_52w = row.get('Low_52W', np.nan)
            rs = row.get('RS', np.nan)
            volume = row.get('Volume', np.nan)

            # Calculate MA200 20 days ago
            ma200_20d_ago = np.nan
            if 'SMA_200' in ticker_df.columns and len(ticker_df) > 20:
                ma200_series = ticker_df['SMA_200']
                shifted = ma200_series.shift(20)
                if row_date in shifted.index:
                    ma200_20d_ago = shifted.loc[row_date]

            # Trend conditions (C1-C8) - MUST MATCH vectorized_screening.py EXACTLY
            c1 = price > ma150 if pd.notna(ma150) else False
            c2 = price > ma200 if pd.notna(ma200) else False
            c3 = ma150 > ma200 if pd.notna(ma150) and pd.notna(ma200) else False
            c4 = ma200 > ma200_20d_ago if pd.notna(ma200) and pd.notna(ma200_20d_ago) else False
            c5 = ma50 > ma150 if pd.notna(ma50) and pd.notna(ma150) else False
            c6 = price > (high_52w * 0.75) if pd.notna(high_52w) else False
            c7 = price > ma50 if pd.notna(ma50) else False
            c8 = price > (low_52w * 1.3) if pd.notna(low_52w) else False  # FIX: 1.3x not 1.25x

            # Breakout conditions (C9-C11) - MUST MATCH vectorized_screening.py EXACTLY
            # C9: Close > 20-day high
            high_20d_max = np.nan
            if 'High' in ticker_df.columns and len(ticker_df) > 20:
                high_series = ticker_df['High'].shift(1).rolling(20).max()
                if row_date in high_series.index:
                    high_20d_max = high_series.loc[row_date]
            c9 = price > high_20d_max if pd.notna(high_20d_max) else False

            # C10: Volume > 1.2x 50-day average (FIX: 1.2x not 1.5x)
            volume_50d_avg = np.nan
            if 'Volume' in ticker_df.columns and len(ticker_df) > 50:
                volume_series = ticker_df['Volume'].shift(1).rolling(50).mean()
                if row_date in volume_series.index:
                    volume_50d_avg = volume_series.loc[row_date]
            c10 = volume > (volume_50d_avg * 1.2) if pd.notna(volume) and pd.notna(volume_50d_avg) else False

            # C11: RS > 63-day MA of RS (NEW: was missing)
            rs_63d_avg = np.nan
            if 'RS' in ticker_df.columns and len(ticker_df) > 63:
                rs_series = ticker_df['RS'].rolling(63).mean()
                if row_date in rs_series.index:
                    rs_63d_avg = rs_series.loc[row_date]
            c11 = rs > rs_63d_avg if pd.notna(rs) and pd.notna(rs_63d_avg) else False

            # Display all conditions
            print(f"\n  Trend Conditions (C1-C8):")
            print(f"    1. Close > SMA_150:                {'[PASS]' if c1 else '[FAIL]'}  (${price:.2f} > ${ma150:.2f})")
            print(f"    2. Close > SMA_200:                {'[PASS]' if c2 else '[FAIL]'}  (${price:.2f} > ${ma200:.2f})")
            print(f"    3. SMA_150 > SMA_200:              {'[PASS]' if c3 else '[FAIL]'}  (${ma150:.2f} > ${ma200:.2f})")
            print(f"    4. SMA_200 trending up (20d):      {'[PASS]' if c4 else '[FAIL]'}  (${ma200:.2f} > ${ma200_20d_ago:.2f})")
            print(f"    5. SMA_50 > SMA_150:               {'[PASS]' if c5 else '[FAIL]'}  (${ma50:.2f} > ${ma150:.2f})")
            print(f"    6. Close > 75% of 52W High:        {'[PASS]' if c6 else '[FAIL]'}  (${price:.2f} > ${high_52w * 0.75:.2f})")
            print(f"    7. Close > SMA_50:                 {'[PASS]' if c7 else '[FAIL]'}  (${price:.2f} > ${ma50:.2f})")
            print(f"    8. Close > 130% of 52W Low:        {'[PASS]' if c8 else '[FAIL]'}  (${price:.2f} > ${low_52w * 1.3:.2f})")

            print(f"\n  Breakout Conditions (C9-C11):")
            print(f"    9. Close > 20-day High:            {'[PASS]' if c9 else '[FAIL]'}  (${price:.2f} > ${high_20d_max:.2f})")
            print(f"   10. Volume > 1.2x 50-day Avg:       {'[PASS]' if c10 else '[FAIL]'}  ({volume:,.0f} > {volume_50d_avg * 1.2:,.0f})")
            print(f"   11. RS > 63-day Avg:                {'[PASS]' if c11 else '[FAIL]'}  ({rs:.2f} > {rs_63d_avg:.2f})")

            # Additional metrics
            print(f"\n  Additional Metrics:")
            print(f"    52-Week High: ${high_52w:.2f}")
            print(f"    52-Week Low:  ${low_52w:.2f}")
            print(f"    Distance from 52W High: {((price / high_52w - 1) * 100):.1f}%")

            vol_ratio = row.get('Vol_Ratio', np.nan)
            if pd.notna(vol_ratio):
                print(f"    Volume Ratio: {vol_ratio:.2f}x")

            atr = row.get('ATR', np.nan)
            if pd.notna(atr):
                print(f"    ATR: ${atr:.2f}")

            # Summary of failed conditions
            failed_trend = []
            if not c1: failed_trend.append("1")
            if not c2: failed_trend.append("2")
            if not c3: failed_trend.append("3")
            if not c4: failed_trend.append("4")
            if not c5: failed_trend.append("5")
            if not c6: failed_trend.append("6")
            if not c7: failed_trend.append("7")
            if not c8: failed_trend.append("8")

            failed_breakout = []
            if not c9: failed_breakout.append("9")
            if not c10: failed_breakout.append("10")
            if not c11: failed_breakout.append("11")

            trend_conditions_pass = c1 and c2 and c3 and c4 and c5 and c6 and c7 and c8
            breakout_conditions_pass = c9 and c10 and c11
            all_conditions_pass = trend_conditions_pass and breakout_conditions_pass

            # Show summary
            print(f"\n  Summary:")
            if all_conditions_pass:
                print(f"    [PASS] All 11 conditions passed!")
                if not triggered:
                    print(f"           (But not a new trigger - was already qualified)")
            elif trend_conditions_pass and not breakout_conditions_pass:
                print(f"    [PARTIAL] Trend OK but missing breakout")
                print(f"              Failed breakout conditions: {', '.join(failed_breakout)}")
                print(f"              Will STAY in buy list if already added")
            elif failed_trend and not failed_breakout:
                print(f"    [FAIL] Breakout present but trend broken")
                print(f"           Failed trend conditions: {', '.join(failed_trend)}")
                print(f"           Will be REMOVED from buy list")
            else:
                print(f"    [FAIL] Both trend and breakout broken")
                if failed_trend:
                    print(f"           Failed trend conditions: {', '.join(failed_trend)}")
                if failed_breakout:
                    print(f"           Failed breakout conditions: {', '.join(failed_breakout)}")
                print(f"           Will be REMOVED from buy list")

        print("\n" + "=" * 80)

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
                    
                    # Extract feature values for this ticker
                    # Use ml_scorer.feature_names to get only the features used by the model
                    features_dict = {}
                    candidate_row = candidates_df.iloc[i]
                    for feature_name in ml_scorer.feature_names:
                        if feature_name in candidate_row.index:
                            value = candidate_row[feature_name]
                            # Convert numpy types to Python types for JSON serialization
                            if pd.isna(value):
                                features_dict[feature_name] = None
                            elif isinstance(value, (np.integer, np.floating)):
                                features_dict[feature_name] = float(value)
                            else:
                                features_dict[feature_name] = value
                    
                    ml_scores[ticker] = {
                        'probability': prob,
                        'rank': rank,
                        'features': features_dict
                    }
                    
                    logger.debug(f"       [{ticker}] ML Score: prob={prob}, rank={rank}, features={len(features_dict)}")

                ml_time = time.time() - ml_start

                # Calculate valid scores
                valid_probs = probabilities[~np.isnan(probabilities)]
                if len(valid_probs) > 0:
                    print(f"       [OK] Scored {len(candidates_df)} candidates in {ml_time:.1f}s")
                    print(f"       [OK] Valid predictions: {len(valid_probs)}/{len(probabilities)}")
                    print(f"       [OK] Probability range: [{valid_probs.min():.3f}, {valid_probs.max():.3f}]")
                    print(f"       [OK] All SEPA signals retained (ML is informational only)")
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
    
    # Step 2: Extract result lists from scanner
    # - trend_ok_stocks: Pass C1-C8 (used for REMOVAL decisions)
    # - breakout_stocks: Pass C9-C11 (informational)
    # - qualifying_stocks: Pass ALL C1-C11 (backward compat)
    # - new_triggers_today: Pass C1-C11 + 0->1 transition (used for ADDITION)
    trend_ok_stocks = results.get('trend_ok_stocks', [])
    breakout_stocks = results.get('breakout_stocks', [])
    qualifying_stocks = results.get('qualifying_stocks', [])  # Backward compat

    trend_ok_tickers = set([s['ticker'] for s in trend_ok_stocks])
    new_trigger_tickers = set([t['ticker'] for t in new_triggers_today])

    # Step 3: Determine additions (new triggers not already in buy list)
    # Requires BOTH trend + breakout (C1-C11) + 0->1 transition
    tickers_to_add = [t for t in new_triggers_today if t['ticker'] not in tickers_in_buy_list]

    # Step 4: Determine removals (in buy_list but no longer trend_ok)
    # Only checks trend (C1-C8) - allows tickers to stay even if volume weakens
    tickers_to_remove = tickers_in_buy_list - trend_ok_tickers
    
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

        # Get ML scores and features if available
        ml_prob = None
        ml_rank = None
        ml_model_ver = None
        ml_score_date = None
        ml_features_dict = None

        if ticker in ml_scores:
            ml_prob = ml_scores[ticker]['probability']
            ml_rank = ml_scores[ticker]['rank']
            ml_features_dict = ml_scores[ticker].get('features')  # Extract features
            ml_model_ver = ml_scorer.model_version if ml_scorer else None
            ml_score_date = scan_date_str
            logger.debug(f"Adding {ticker} to buy_list with ML: prob={ml_prob}, rank={ml_rank}, features={len(ml_features_dict) if ml_features_dict else 0}")

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
    
    # Step 6: Update existing tickers (those that remain in buy_list)
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
    
    # Step 6.5: Re-score existing tickers with ML (if enabled)
    if use_ml and ml_scorer and len(tickers_to_update) > 0:
        print(f"       Re-scoring {len(tickers_to_update)} existing tickers with ML...")
        ml_rescore_start = time.time()
        
        from src.fundamental_merger import FundamentalMerger
        fund_merger = FundamentalMerger()
        
        # Prepare features for existing tickers
        ml_rescore_candidates = []
        for ticker in tickers_to_update:
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
                
                ml_rescore_time = time.time() - ml_rescore_start
                print(f"       Re-scored {len(candidates_df)} tickers in {ml_rescore_time:.1f}s")
                logger.info(f"ML re-scoring took {ml_rescore_time:.1f}s for {len(candidates_df)} tickers")
                
            except Exception as e:
                logger.error(f"Failed to re-score existing tickers: {e}")
    

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


def _process_date_range_signals(buy_signals, sell_signals, enriched_data, args, data_repo):
    """
    Process buy/sell signals from 2D vectorized scan and update database.
    
    Groups signals by date and performs database updates for each day.
    Then scores all buy list tickers with ML (if enabled).
    
    Args:
        buy_signals: DataFrame with buy signal rows (from find_signal_transitions)
        sell_signals: DataFrame with sell signal rows (from find_signal_transitions)
        enriched_data: Dict mapping ticker -> DataFrame with features
        args: Command-line arguments
        data_repo: DataRepository instance
    """
    import pandas as pd
    import numpy as np
    from src.strategy import SEPAStrategy
    
    # Get unique dates from signals
    buy_dates = buy_signals['date'].unique() if len(buy_signals) > 0 else []
    sell_dates = sell_signals['date'].unique() if len(sell_signals) > 0 else []
    all_dates = sorted(set(list(buy_dates) + list(sell_dates)))
    
    # Initialize database manager
    db = DatabaseManager()
    
    # Initialize strategy for trade plan calculation
    benchmark_data = data_repo.get_benchmark_data()
    strategy = SEPAStrategy(benchmark_data=benchmark_data)
    
    # Track latest date for final ML scoring
    latest_date = None
    
    # Process each date
    for date in all_dates:
        date_pd = pd.Timestamp(date)
        date_str = date_pd.strftime('%Y-%m-%d')
        
        if latest_date is None or date_pd > latest_date:
            latest_date = date_pd
        
        # Get signals for this date
        buys_today = buy_signals[buy_signals['date'] == date] if len(buy_signals) > 0 else pd.DataFrame()
        sells_today = sell_signals[sell_signals['date'] == date] if len(sell_signals) > 0 else pd.DataFrame()
        
        print(f"  {date_str}: +{len(buys_today)} buys, -{len(sells_today)} sells")
        
        # Process sells first (remove from buy list)
        for _, row in sells_today.iterrows():
            ticker = row['ticker']
            db.remove_from_buy_list(ticker, reason='trend_break')
        
        # Process buys (add to buy list)
        for _, row in buys_today.iterrows():
            ticker = row['ticker']
            
            # Get enriched data for this ticker
            if ticker not in enriched_data:
                continue
            
            df = enriched_data[ticker]
            
            # Calculate trade plan
            trade_plan = strategy.calculate_trade_plan(df, date_pd)
            if trade_plan is None:
                continue
            
            # Get additional metrics
            if date_pd in df.index:
                ticker_row = df.loc[date_pd]
                rs_value = ticker_row.get('RS', None)
                vol_ratio = ticker_row.get('Vol_Ratio', None)
                atr_value = ticker_row.get('ATR', None)
            else:
                rs_value = None
                vol_ratio = None
                atr_value = None
            
            # Add to buy list (without ML scores initially)
            db.add_to_buy_list(
                ticker=ticker,
                signal_date=date_str,
                signal_price=trade_plan['entry_price'],
                current_price=trade_plan['entry_price'],
                entry_price=trade_plan['entry_price'],
                stop_price=trade_plan['stop_price'],
                target_price=trade_plan['target_price'],
                rs=rs_value,
                atr=atr_value,
                vol_ratio=vol_ratio,
                ml_probability=None,  # Will be scored at the end
                ml_rank=None
            )
    
    # ML Scoring: Score all buy list tickers at the latest date
    if args.use_ml and args.model_path and latest_date is not None:
        print(f"\n  Scoring buy list with ML (at {latest_date.strftime('%Y-%m-%d')})...")
        
        try:
            from src.ml_scorer import MLScorer
            from src.fundamental_merger import FundamentalMerger
            
            # Load ML scorer
            ml_scorer = MLScorer(model_path=args.model_path, log_predictions=False)
            fund_merger = FundamentalMerger(force_cache_only=True)  # Use cache only for speed
            
            # Get current buy list from database
            buy_list_df = db.get_buy_list()
            if buy_list_df.empty:
                print("    No tickers in buy list to score")
                return
            
            active_tickers = buy_list_df['ticker'].unique().tolist()
            print(f"    Scoring {len(active_tickers)} tickers...")
            
            # Prepare features for each ticker
            ml_candidates = []
            for ticker in active_tickers:
                if ticker not in enriched_data:
                    continue
                
                ticker_df = enriched_data[ticker]
                
                # Get row at latest_date
                if latest_date in ticker_df.index:
                    row = ticker_df.loc[latest_date]
                else:
                    # Use last available date
                    available = ticker_df.index[ticker_df.index <= latest_date]
                    if len(available) == 0:
                        continue
                    row = ticker_df.loc[available[-1]]
                
                # Get fundamental data
                single_date_df = pd.DataFrame({
                    'Date': [latest_date],
                    'Close': [row.get('Close', np.nan)]
                }).set_index('Date')
                
                try:
                    merged_df = fund_merger.merge_ticker_data(ticker, single_date_df)
                    fund_cols = [c for c in merged_df.columns if c not in ['Date', 'Close', 'Open', 'High', 'Low', 'Volume', 'Adj Close']]
                    
                    # Combine technical + fundamental features
                    feature_dict = row.to_dict()
                    for fcol in fund_cols:
                        if fcol in merged_df.columns:
                            feature_dict[fcol] = merged_df[fcol].iloc[0]
                    
                    feature_dict['ticker'] = ticker
                    feature_dict['Date'] = latest_date
                    ml_candidates.append(feature_dict)
                    
                except Exception as e:
                    logger.debug(f"Failed to get fundamentals for {ticker}: {e}")
                    continue
            
            if len(ml_candidates) == 0:
                print("    No valid candidates for ML scoring")
                return
            
            # Create DataFrame and score
            candidates_df = pd.DataFrame(ml_candidates)
            scores = ml_scorer.score_candidates(candidates_df)
            
            # Update database with ML scores
            for _, score_row in scores.iterrows():
                ticker = score_row['ticker']
                ml_prob = score_row.get('ml_probability', None)
                ml_rank = score_row.get('ml_rank', None)
                
                db.update_ml_scores(ticker, ml_prob, ml_rank)
            
            print(f"    [OK] Scored {len(scores)} tickers successfully")
            
        except Exception as e:
            print(f"    [WARN] ML scoring failed: {e}")
            logger.error(f"ML scoring error: {e}", exc_info=True)



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
            # Scanner only needs recent data for indicator calculation (2 years is sufficient)
            min_date = (pd.Timestamp.now() - pd.DateOffset(years=2)).strftime('%Y-%m-%d')
            results = data_repo.update_cache(tickers, force=False, source='fmp', min_date=min_date)
            success_count = sum(results.values())
            cache_time = time.time() - cache_start
            print(f"            Updated {success_count}/{len(tickers)} tickers in {cache_time:.1f}s")
            print(f"            Cache is now ready for {(end_date - start_date).days + 1} day(s) of scanning\n")
            
            # PRE-LOAD: Load all price data once for entire date range (major optimization)
            print("\n[PRE-SCAN] Loading price data for date range...")
            load_start = time.time()
            # Load data from cache (cache was just updated above)
            all_ticker_data = data_repo.get_batch_data(tickers)
            load_time = time.time() - load_start
            print(f"            Loaded {len(all_ticker_data)} tickers in {load_time:.1f}s")
            print(f"            Data will be filtered by date for each scan (in-memory operation)\n")
            
            # ====================================================================
            # 2D VECTORIZED SCAN - Process entire date range as single matrix
            # ====================================================================
            
            print(f"\n{'='*80}")
            print(f">> 2D VECTORIZED SCAN: {args.date_range[0]} to {args.date_range[1]}")
            print(f"{'='*80}\n")
            
            vectorized_start = time.time()
            
            # Import helper for 2D matrix processing
            from src.vectorized_screening import VectorizedSEPAScreener
            import pandas as pd
            
            # CRITICAL: Include sufficient historical data for technical indicators
            # - SEPA condition 4 needs SMA_200.shift(20) = 20 trading days
            # - SMA_200 itself needs 200 trading days
            # - 52-week high needs ~250 trading days
            # Total: Use 250 trading days (~1 year) to be safe
            # Also add 1 day for boundary detection
            lookback_days = 251  # 250 trading days + 1 for boundary
            data_start_date = start_date - timedelta(days=lookback_days)
            
            # Initialize components needed for processing
            benchmark_data = data_repo.get_benchmark_data()
            feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
            
            # Step 1: Calculate features for all tickers
            print("[Step 1/6] Computing features for all tickers...")
            feature_start = time.time()
            enriched_data = feature_engine.process_universe_batch(all_ticker_data)
            feature_time = time.time() - feature_start
            print(f"            Features computed in {feature_time:.1f}s\n")
            
            # Step 2: Build 2D matrix (all tickers × all dates in range + lookback)
            print("[Step 2/6] Building 2D matrix (tickers × dates)...")
            print(f"            Including {lookback_days} days of historical data for indicators...")
            matrix_start = time.time()
            df_matrix = VectorizedSEPAScreener.build_2d_matrix(
                enriched_data,
                start_date=pd.Timestamp(data_start_date),  # Include historical data
                end_date=pd.Timestamp(end_date)
            )
            matrix_time = time.time() - matrix_start
            print(f"            Matrix built: {df_matrix.shape[0]:,} rows in {matrix_time:.1f}s\n")
            
            # Step 3: Add SEPA_Status column (vectorized across entire matrix)
            print("[Step 3/6] Computing SEPA status (vectorized)...")
            sepa_start = time.time()
            df_matrix = VectorizedSEPAScreener.add_sepa_status_column(df_matrix)
            sepa_time = time.time() - sepa_start
            qualified_count = df_matrix['SEPA_Status'].sum()
            print(f"            SEPA status computed in {sepa_time:.1f}s")
            print(f"            {qualified_count:,} ticker-dates qualified\n")
            
            # Step 4: Find all buy/sell transitions
            print("[Step 4/6] Finding signal transitions...")
            transition_start = time.time()
            buy_signals, sell_signals = VectorizedSEPAScreener.find_signal_transitions(
                df_matrix,
                date_range_start=pd.Timestamp(start_date),
                date_range_end=pd.Timestamp(end_date)
            )
            transition_time = time.time() - transition_start
            print(f"            Transitions found in {transition_time:.1f}s")
            print(f"            Buy signals: {len(buy_signals):,}")
            print(f"            Sell signals: {len(sell_signals):,}\n")
            
            # Step 5: Process signals by date and update database
            print("[Step 5/6] Updating database...")
            _process_date_range_signals(
                buy_signals,
                sell_signals,
                enriched_data,
                args,
                data_repo
            )
            
            # Step 6: Summary
            vectorized_time = time.time() - vectorized_start
            num_days = (end_date - start_date).days + 1
            
            print(f"\n{'='*80}")
            print(f"[OK] 2D VECTORIZED SCAN COMPLETE!")
            print(f"{'='*80}")
            print(f"Total time: {vectorized_time:.1f}s")
            print(f"Dates processed: {num_days}")
            print(f"Speed: {vectorized_time / num_days:.2f}s per day")
            print(f"{'='*80}\n")
        else:
            # Single day mode
            run_optimized_scanner(
                scan_date=args.scan_date,
                csv_output=args.csv_output,
                use_ml=args.use_ml,
                model_path=args.model_path,
                tickers=args.tickers,
                debug=args.debug
            )

    except KeyboardInterrupt:
        print("\n\nScanner interrupted by user.")
    except Exception as e:
        logger.error(f"Scanner failed with error: {e}", exc_info=True)
        print(f"\n[ERROR]: {e}")



