"""
Daily Scanner - Clean Implementation with Date Range Support
Optimized for daily scanning and historical backtesting.

Key features:
1. Single-day mode: Daily scanning with full ML scoring
2. Date-range mode: 2D vectorized scanning for multiple days
3. Batch data loading and feature calculation
4. Optional ML scoring for signals
5. Database-backed buy list management
"""

import pandas as pd
import numpy as np
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import time
import argparse
import logging

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.data_engine import DataRepository
from src.strategy import SEPAStrategy
from src.database import DatabaseManager
from src.features import FeatureEngineer
from src.utils import get_latest_trading_day
from src.ml_scorer import MLScorer
from src.fundamental_merger import FundamentalMerger

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_ml_scorer(model_path: Optional[str] = None) -> Optional[MLScorer]:
    """Load ML scorer if requested."""
    if model_path is None:
        model_path = config.ML_PRODUCTION_MODEL

    try:
        ml_scorer = MLScorer(model_path=model_path, log_predictions=True)
        import os
        model_name = os.path.basename(model_path)
        print(f"\n[ML] Loaded model: {model_name}")
        print(f"[ML] Model type: {'Regressor (Return %)' if ml_scorer.is_regressor else 'Classifier (Probability)'}")
        print(f"[ML] Model version: {ml_scorer.model_version}")
        print(f"[ML] Features required: {len(ml_scorer.feature_names)}")
        return ml_scorer
    except Exception as e:
        print(f"\n[WARN] ML model loading failed: {e}")
        print("        Proceeding without ML scoring...\n")
        return None


def prepare_ml_candidates(tickers: List[str], enriched_data: dict,
                         scan_date_obj: pd.Timestamp, fund_merger: FundamentalMerger) -> pd.DataFrame:
    """Prepare feature DataFrame for ML scoring."""
    ml_candidates = []
    feature_engine = FeatureEngineer(benchmark_data=None)  # Static method doesn't need benchmark

    for ticker in tickers:
        ticker_df = enriched_data.get(ticker)
        if ticker_df is None or len(ticker_df) == 0:
            continue

        # Get row at scan_date or latest available
        if scan_date_obj in ticker_df.index:
            row_date = scan_date_obj
            row = ticker_df.loc[scan_date_obj]
        else:
            available_dates = ticker_df.index[ticker_df.index <= scan_date_obj]
            if len(available_dates) == 0:
                continue
            row_date = available_dates[-1]
            row = ticker_df.loc[row_date]

        # Always calculate heavyweight features (alpha factors) to ensure they're present
        # This is efficient because AlphaEngine will reuse existing columns if present
        ticker_df = feature_engine.calculate_heavyweight_features(ticker_df, ticker)
        enriched_data[ticker] = ticker_df  # Update cache with heavyweight features
        row = ticker_df.loc[row_date]  # Re-extract row with alpha features

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
            logger.warning(f"[{ticker}] Failed to load fundamentals: {e}")
            fund_data = None

        # Merge technical + fundamental features
        candidate_features = {
            'ticker': ticker,
            'date': row_date,
            **row.to_dict(),
        }

        if fund_data is not None:
            candidate_features.update(fund_data.to_dict())

        ml_candidates.append(candidate_features)

    return pd.DataFrame(ml_candidates) if ml_candidates else pd.DataFrame()


def score_with_ml(candidates_df: pd.DataFrame, ml_scorer: MLScorer,
                  scan_date_str: str) -> dict:
    """Score candidates with ML model and return results dict."""
    if len(candidates_df) == 0:
        return {}

    try:
        probabilities, _ = ml_scorer.score_batch(candidates_df, ticker_column='ticker', date_column='date')

        ml_scores = {}
        for idx, ticker in enumerate(candidates_df['ticker']):
            prob = probabilities[idx]

            # Convert NaN to None and numpy types to Python types
            if np.isnan(prob):
                prob = None
            else:
                prob = float(prob)

            # Extract features used by model
            features_dict = {}
            candidate_row = candidates_df.iloc[idx]
            for feature_name in ml_scorer.feature_names:
                if feature_name in candidate_row.index:
                    value = candidate_row[feature_name]
                    if pd.isna(value):
                        features_dict[feature_name] = None
                    elif isinstance(value, (np.integer, np.floating)):
                        features_dict[feature_name] = float(value)
                    else:
                        features_dict[feature_name] = value

            ml_scores[ticker] = {
                'probability': prob,
                'features': features_dict
            }

        return ml_scores
    except Exception as e:
        logger.error(f"ML scoring failed: {e}", exc_info=True)
        return {}


def update_ml_ranks(db: DatabaseManager, scan_date_str: str):
    """Recalculate ML ranks across entire buy list."""
    buy_list_df = db.get_buy_list(active_only=True, as_of_date=scan_date_str)

    if buy_list_df.empty:
        return

    # Use ml_expected_return for regression models, ml_probability for classification
    # Create a combined score column for ranking
    if 'ml_expected_return' in buy_list_df.columns and buy_list_df['ml_expected_return'].notna().any():
        # Regression model - use expected return for ranking
        ml_entries = buy_list_df[buy_list_df['ml_expected_return'].notna()].copy()
        score_column = 'ml_expected_return'
    elif 'ml_probability' in buy_list_df.columns and buy_list_df['ml_probability'].notna().any():
        # Classification model - use probability for ranking
        ml_entries = buy_list_df[buy_list_df['ml_probability'].notna()].copy()
        score_column = 'ml_probability'
    else:
        return

    if len(ml_entries) == 0:
        return

    # Calculate ranks (higher score = better rank)
    scores = ml_entries[score_column].values
    sorted_indices = np.argsort(scores)[::-1]
    ranks = np.empty(len(scores), dtype=int)
    ranks[sorted_indices] = np.arange(1, len(scores) + 1)

    # Update database
    for ticker, rank in zip(ml_entries['ticker'], ranks):
        db.update_buy_list_ml_rank(ticker, int(rank))

    logger.info(f"Recalculated ML ranks for {len(ml_entries)} buy list entries using {score_column}")


def run_daily_scanner(scan_date: Optional[str] = None,
                      csv_output: bool = False,
                      use_ml: bool = False,
                      model_path: Optional[str] = None,
                      tickers: Optional[List[str]] = None):
    """
    Run daily scanner for single day.

    Args:
        scan_date: Optional date to scan (YYYY-MM-DD). If None, uses latest trading day
        csv_output: If True, exports buy_list and activity to CSV files
        use_ml: If True, adds ML probability scores to SEPA candidates
        model_path: Path to ML model (default: from config.ML_PRODUCTION_MODEL)
        tickers: Optional list of specific tickers to scan
    """
    start_time = time.time()

    # Initialize ML scorer
    ml_scorer = load_ml_scorer(model_path) if use_ml else None
    use_ml = ml_scorer is not None  # Update flag if loading failed

    # Determine scan date
    if scan_date:
        scan_date_obj = pd.Timestamp(scan_date)
    else:
        scan_date_obj = get_latest_trading_day()
    scan_date_str = scan_date_obj.strftime('%Y-%m-%d')

    print("=" * 80)
    print(f" DAILY SCANNER | {scan_date_str}")
    print("=" * 80)

    total_steps = 5 if use_ml else 4

    # Initialize components
    data_repo = DataRepository()
    db = DatabaseManager()

    # ========================================================================
    # STEP 1: Load Universe
    # ========================================================================
    print(f"\n[1/{total_steps}] Loading Ticker Universe...")
    if tickers is None:
        tickers = data_repo.update_universe()
        tickers.append(config.BENCHMARK_TICKER)
        print(f"       Loaded {len(tickers)} tickers")
    else:
        print(f"       Using specified tickers: {', '.join(tickers)} ({len(tickers)} total)")

    # ========================================================================
    # STEP 2: Update Cache
    # ========================================================================
    print(f"\n[2/{total_steps}] Updating Price Cache...")
    update_start = time.time()
    min_date = (pd.Timestamp.now() - pd.DateOffset(years=2)).strftime('%Y-%m-%d')
    results = data_repo.update_cache(tickers, force=False, source='fmp')
    success_count = sum(results.values())
    update_time = time.time() - update_start
    print(f"       Updated {success_count}/{len(tickers)} tickers in {update_time:.1f}s")

    # ========================================================================
    # STEP 3: Load and Filter Data
    # ========================================================================
    print(f"\n[3/{total_steps}] Loading Price Data...")
    load_start = time.time()
    ticker_data = data_repo.get_batch_data(
        tickers,
        min_date=min_date,
        check_min_date=False,
        force_cache_only=True
    )
    load_time = time.time() - load_start
    print(f"       Loaded {len(ticker_data)} tickers in {load_time:.1f}s")

    # Filter by scan_date
    valid_ticker_data = {}
    for ticker, df in ticker_data.items():
        if df is not None and len(df) > 0:
            mask = df.index <= scan_date_obj
            filtered_df = df[mask]
            if len(filtered_df) > 0:
                valid_ticker_data[ticker] = filtered_df

    print(f"       {len(valid_ticker_data)} tickers have data available")

    # ========================================================================
    # STEP 4: Feature Calculation & SEPA Screening
    # ========================================================================
    print(f"\n[4/{total_steps}] Batch Processing Features & SEPA Screening...")
    scan_start = time.time()

    # Load benchmark
    benchmark_data = data_repo.get_benchmark_data(
        check_min_date=False,
        required_end_date=scan_date_str,
        force_cache_only=True
    )
    if benchmark_data is None:
        print("       ERROR: Could not load benchmark data!")
        return

    # Calculate features
    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    strategy = SEPAStrategy(benchmark_data=benchmark_data)

    print("       Calculating features...")
    feature_start = time.time()
    enriched_data = feature_engine.process_universe_batch(valid_ticker_data)
    feature_time = time.time() - feature_start
    print(f"       Features calculated in {feature_time:.1f}s")

    # SEPA screening
    print("       Screening for SEPA signals...")
    screen_start = time.time()
    results = strategy.batch_scan_universe(enriched_data, scan_date=scan_date_obj)
    screen_time = time.time() - screen_start

    trend_ok_stocks = results.get('trend_ok_stocks', [])
    new_triggers_today = results['new_triggers']

    print(f"       Screening complete in {screen_time:.1f}s")
    print(f"       Trend OK (C1-C8): {len(trend_ok_stocks)} stocks")
    print(f"       New triggers: {len(new_triggers_today)} stocks")

    # ========================================================================
    # STEP 5 (Optional): ML Scoring
    # ========================================================================
    ml_scores = {}
    if use_ml and ml_scorer:
        print(f"\n[5/{total_steps}] ML Scoring...")
        ml_start = time.time()

        # Get all tickers to score (new triggers + existing buy list)
        current_buy_list = db.get_buy_list(active_only=True, as_of_date=scan_date_str)
        tickers_in_buy_list = set(current_buy_list['ticker'].tolist()) if not current_buy_list.empty else set()
        new_trigger_tickers = set([t['ticker'] for t in new_triggers_today])
        trend_ok_tickers = set([s['ticker'] for s in trend_ok_stocks])

        # Score new triggers + existing tickers that are still trend_ok
        tickers_to_score = list(new_trigger_tickers | (tickers_in_buy_list & trend_ok_tickers))

        if len(tickers_to_score) > 0:
            print(f"       Preparing {len(tickers_to_score)} candidates...")
            fund_merger = FundamentalMerger()
            candidates_df = prepare_ml_candidates(tickers_to_score, enriched_data, scan_date_obj, fund_merger)

            if len(candidates_df) > 0:
                print(f"       Scoring {len(candidates_df)} candidates...")
                ml_scores = score_with_ml(candidates_df, ml_scorer, scan_date_str)
                ml_time = time.time() - ml_start

                valid_scores = sum(1 for s in ml_scores.values() if s['probability'] is not None)
                print(f"       [OK] Scored {len(candidates_df)} candidates in {ml_time:.1f}s")
                print(f"       [OK] Valid predictions: {valid_scores}/{len(candidates_df)}")
            else:
                print("       [WARN] No candidates with sufficient data")
        else:
            print("       No candidates to score")

    # ========================================================================
    # FINAL STEP: Update Buy List
    # ========================================================================
    step_num = total_steps
    print(f"\n[{step_num}/{total_steps}] Managing Buy List...")

    # Temporal consistency check
    all_signals = db.get_buy_list(active_only=False)
    if not all_signals.empty:
        earliest_signal_date = pd.to_datetime(all_signals['signal_date']).min()
        if pd.Timestamp(scan_date_str) < earliest_signal_date:
            print(f"\n       [WARN] BACKWARD SCAN DETECTED")
            print(f"       Clearing future signals...")
            deleted = db.clear_future_signals(scan_date_str)
            print(f"       [OK] Cleared {deleted['buy_list_deleted']} signals")

    # Load current buy list
    current_buy_list = db.get_buy_list(active_only=True, as_of_date=scan_date_str)
    tickers_in_buy_list = set(current_buy_list['ticker'].tolist()) if not current_buy_list.empty else set()
    trend_ok_tickers = set([s['ticker'] for s in trend_ok_stocks])

    # Determine additions and removals
    tickers_to_add = [t for t in new_triggers_today if t['ticker'] not in tickers_in_buy_list]
    tickers_to_remove = tickers_in_buy_list - trend_ok_tickers
    tickers_to_update = tickers_in_buy_list & trend_ok_tickers

    # Execute additions
    for trigger in tickers_to_add:
        ticker = trigger['ticker']
        signal_price = trigger['entry_price']

        # Get indicator values
        ticker_df = enriched_data.get(ticker)
        if ticker_df is not None:
            if scan_date_obj in ticker_df.index:
                row = ticker_df.loc[scan_date_obj]
            else:
                # Use last available date
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

        # Get ML scores
        ml_prob = None
        ml_expected_return = None
        ml_model_type_str = None
        ml_features_dict = None
        ml_model_ver = None
        if ticker in ml_scores:
            score_value = ml_scores[ticker]['probability']
            ml_features_dict = ml_scores[ticker].get('features')  # Get features dict
            ml_model_ver = ml_scorer.model_version if ml_scorer else None
            
            # Determine model type and set appropriate column
            if ml_scorer and ml_scorer.is_regressor:
                ml_expected_return = score_value
                ml_model_type_str = 'regression'
            else:
                ml_prob = score_value
                ml_model_type_str = 'classification'

        db.add_to_buy_list(
            ticker=ticker,
            signal_date=scan_date_str,
            signal_price=signal_price,
            current_price=signal_price,
            entry_price=trigger.get('entry_price'),
            stop_price=trigger.get('stop_price'),
            target_price=trigger.get('target_price'),
            rs=trigger.get('rs'),
            vol_ratio=trigger.get('vol_ratio'),
            ma50=ma50,
            ma150=ma150,
            ma200=ma200,
            high_52w=high_52w,
            low_52w=low_52w,
            ml_probability=ml_prob,
            ml_expected_return=ml_expected_return,
            ml_model_type=ml_model_type_str,
            ml_rank=None,  # Will be calculated later
            ml_model_version=ml_model_ver,
            ml_score_date=scan_date_str if (ml_prob or ml_expected_return) else None,
            ml_features=ml_features_dict
        )
        db.log_buy_list_activity(
            ticker=ticker,
            action='ADDED',
            action_date=scan_date_str,
            reason='new_trigger',
            entry_price=trigger.get('entry_price'),
            stop_price=trigger.get('stop_price'),
            target_price=trigger.get('target_price'),
            rs=trigger.get('rs'),
            vol_ratio=trigger.get('vol_ratio')
        )

    # Execute updates
    for ticker in tickers_to_update:
        stock_data = next((s for s in trend_ok_stocks if s['ticker'] == ticker), None)
        if stock_data:
            ticker_df = enriched_data.get(ticker)

            # Get actual update date and row
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
                        actual_update_date = last_date.strftime('%Y-%m-%d')
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

            # Get ML scores
            ml_prob = None
            ml_expected_return = None
            ml_model_type_str = None
            ml_features_dict = None
            ml_model_ver = None
            if ticker in ml_scores:
                score_value = ml_scores[ticker]['probability']
                ml_features_dict = ml_scores[ticker].get('features')
                ml_model_ver = ml_scorer.model_version if ml_scorer else None
                
                # Determine model type and set appropriate column
                if ml_scorer and ml_scorer.is_regressor:
                    ml_expected_return = score_value
                    ml_model_type_str = 'regression'
                else:
                    ml_prob = score_value
                    ml_model_type_str = 'classification'

            import json
            db.update_buy_list_metrics(
                ticker=ticker,
                scan_date=actual_update_date,
                current_price=stock_data['price'],
                rs=stock_data.get('rs'),
                vol_ratio=stock_data.get('vol_ratio'),
                ma50=ma50,
                ma150=ma150,
                ma200=ma200,
                high_52w=high_52w,
                low_52w=low_52w,
                ml_probability=ml_prob,
                ml_expected_return=ml_expected_return,
                ml_model_type=ml_model_type_str,
                ml_model_version=ml_model_ver,
                ml_score_date=scan_date_str if (ml_prob or ml_expected_return) else None,
                ml_features=json.dumps(ml_features_dict) if ml_features_dict else None
            )

    # Execute removals
    for ticker in tickers_to_remove:
        db.remove_from_buy_list(ticker, reason='trend_broken')
        db.log_buy_list_activity(
            ticker=ticker,
            action='REMOVED',
            action_date=scan_date_str,
            reason='trend_broken'
        )

    # Recalculate ML ranks
    if use_ml and ml_scorer:
        update_ml_ranks(db, scan_date_str)

    print(f"       +{len(tickers_to_add)} added, -{len(tickers_to_remove)} removed")
    print(f"       Active buy list: {len(tickers_in_buy_list) + len(tickers_to_add) - len(tickers_to_remove)} tickers")

    # ========================================================================
    # CSV Export
    # ========================================================================
    if csv_output:
        output_dir = Path(config.DATA_DIR) / 'scanner_output'
        output_dir.mkdir(parents=True, exist_ok=True)

        buy_list_path = output_dir / f'buy_list_{scan_date_str}.csv'
        activity_path = output_dir / f'buy_list_activity_{scan_date_str}.csv'

        buy_list_current = db.get_buy_list(active_only=True, as_of_date=scan_date_str)
        buy_list_current.to_csv(buy_list_path, index=False)
        db.export_to_csv('buy_list_activity', str(activity_path))

        print(f"\n       [FILE] Exported to CSV:")
        print(f"          {buy_list_path}")
        print(f"          {activity_path}")

    # ========================================================================
    # Display Results
    # ========================================================================
    total_time = time.time() - start_time

    print(f"\n{'=' * 80}")
    print(" PERFORMANCE METRICS")
    print("=" * 80)
    print(f"Total scan time: {total_time:.1f}s")
    print(f"  - Cache update: {update_time:.1f}s")
    print(f"  - Data loading: {load_time:.1f}s")
    print(f"  - Feature calc: {feature_time:.1f}s")
    print(f"  - SEPA screening: {screen_time:.1f}s")
    if use_ml and 'ml_time' in locals():
        print(f"  - ML scoring: {ml_time:.1f}s")

    print(f"\n{'=' * 80}")
    print(f" NEW TRIGGERS | {len(new_triggers_today)} Today")
    print("=" * 80)

    if new_triggers_today:
        df_new = pd.DataFrame(new_triggers_today)
        print("\n")
        display_cols = ['ticker', 'date', 'entry_price', 'rs', 'vol_ratio']
        available_cols = [col for col in display_cols if col in df_new.columns]
        print(df_new[available_cols].to_string(index=False))
    else:
        print("\nNo new triggers today.")

    print(f"\n{'=' * 80}")
    print(" BUY LIST (All Active Signals)")
    print("=" * 80)

    buy_list_df = db.get_buy_list(active_only=True, as_of_date=scan_date_str)

    if not buy_list_df.empty:
        print(f"\nTotal Active Signals: {len(buy_list_df)}\n")

        # Calculate price changes
        if 'signal_price' in buy_list_df.columns and 'current_price' in buy_list_df.columns:
            buy_list_df['price_chg_%'] = ((buy_list_df['current_price'] - buy_list_df['signal_price']) / buy_list_df['signal_price'] * 100)

        # Display columns - show ml_expected_return for regression, ml_probability for classification
        display_cols = ['ticker', 'signal_date', 'signal_price', 'current_price', 'price_chg_%',
                       'rs', 'volume_ratio', 'ml_expected_return', 'ml_probability', 'ml_rank', 'last_updated']
        available_cols = [col for col in display_cols if col in buy_list_df.columns]

        display_df = buy_list_df[available_cols].copy()
        
        # Rename columns based on model type for clearer display
        rename_map = {}
        if 'ml_expected_return' in display_df.columns and display_df['ml_expected_return'].notna().any():
            rename_map['ml_expected_return'] = 'Exp_Return_%'
            # Drop ml_probability if we have expected_return (regression model)
            if 'ml_probability' in display_df.columns:
                display_df = display_df.drop(columns=['ml_probability'])
        elif 'ml_probability' in display_df.columns:
            rename_map['ml_probability'] = 'ML_Prob'
            # Drop ml_expected_return if we have probability (classification model)
            if 'ml_expected_return' in display_df.columns:
                display_df = display_df.drop(columns=['ml_expected_return'])
        
        if rename_map:
            display_df = display_df.rename(columns=rename_map)
        
        numeric_cols = ['signal_price', 'current_price', 'price_chg_%', 'rs', 'volume_ratio', 'ml_probability', 'Exp_Return_%', 'ML_Prob']
        for col in numeric_cols:
            if col in display_df.columns:
                display_df[col] = pd.to_numeric(display_df[col], errors='coerce')
                if display_df[col].notna().any():
                    display_df[col] = display_df[col].round(2)

        print(display_df.to_string(index=False))

        buy_list_df['days_on_list'] = (pd.Timestamp(scan_date_str) - pd.to_datetime(buy_list_df['signal_date'])).dt.days
        print(f"\n[STATS]")
        print(f"   Average days on list: {buy_list_df['days_on_list'].mean():.1f}")
        print(f"   Newest signal: {buy_list_df['signal_date'].max()}")
        print(f"   Oldest signal: {buy_list_df['signal_date'].min()}")
    else:
        print("\nNo active buy signals.")

    if len(tickers_to_add) > 0 or len(tickers_to_remove) > 0:
        print(f"\n{'=' * 80}")
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

    print(f"\n{'=' * 80}")
    print(f"Scanner complete! (Total time: {total_time:.1f}s)")
    print("=" * 80 + "\n")


def process_date_range_signals(buy_signals: pd.DataFrame, sell_signals: pd.DataFrame,
                               enriched_data: dict, ml_scorer: Optional[MLScorer],
                               data_repo: DataRepository):
    """
    Process buy/sell signals from 2D vectorized scan and update database.

    Args:
        buy_signals: DataFrame with buy signal rows
        sell_signals: DataFrame with sell signal rows
        enriched_data: Dict mapping ticker -> DataFrame with features
        ml_scorer: Optional ML scorer for final scoring
        data_repo: DataRepository instance
    """
    # Get unique dates
    buy_dates = buy_signals['date'].unique() if len(buy_signals) > 0 else []
    sell_dates = sell_signals['date'].unique() if len(sell_signals) > 0 else []
    all_dates = sorted(set(list(buy_dates) + list(sell_dates)))

    db = DatabaseManager()
    benchmark_data = data_repo.get_benchmark_data(check_min_date=False)
    strategy = SEPAStrategy(benchmark_data=benchmark_data)

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

        # Process sells first
        for _, row in sells_today.iterrows():
            db.remove_from_buy_list(row['ticker'], reason='trend_broken')

        # Process buys
        for _, row in buys_today.iterrows():
            ticker = row['ticker']
            if ticker not in enriched_data:
                continue

            df = enriched_data[ticker]
            trade_plan = strategy.calculate_trade_plan(df, date_pd)
            if trade_plan is None:
                continue

            # Get metrics
            if date_pd in df.index:
                ticker_row = df.loc[date_pd]
                rs_value = ticker_row.get('RS')
                vol_ratio = ticker_row.get('Vol_Ratio')
            else:
                rs_value = vol_ratio = None

            # Add to buy list (ML scores added later)
            db.add_to_buy_list(
                ticker=ticker,
                signal_date=date_str,
                signal_price=trade_plan['entry_price'],
                current_price=trade_plan['entry_price'],
                rs=rs_value,
                vol_ratio=vol_ratio,
                ml_probability=None,
                ml_rank=None
            )

    # Final ML scoring at latest date
    if ml_scorer and latest_date:
        print(f"\n  Scoring buy list with ML (at {latest_date.strftime('%Y-%m-%d')})...")

        buy_list_df = db.get_buy_list(active_only=True)
        if not buy_list_df.empty:
            tickers_to_score = buy_list_df['ticker'].unique().tolist()
            fund_merger = FundamentalMerger()

            candidates_df = prepare_ml_candidates(
                tickers_to_score, enriched_data, latest_date, fund_merger
            )

            if len(candidates_df) > 0:
                ml_scores = score_with_ml(candidates_df, ml_scorer, latest_date.strftime('%Y-%m-%d'))

                # Update database with scores
                import json
                for ticker, score_data in ml_scores.items():
                    if score_data['probability'] is not None:
                        db.update_buy_list_metrics(
                            ticker=ticker,
                            scan_date=latest_date.strftime('%Y-%m-%d'),
                            current_price=None,  # Keep existing
                            ml_probability=score_data['probability'],
                            ml_model_version=ml_scorer.model_version,
                            ml_score_date=latest_date.strftime('%Y-%m-%d'),
                            ml_features=json.dumps(score_data['features'])
                        )

                # Recalculate ranks
                update_ml_ranks(db, latest_date.strftime('%Y-%m-%d'))
                print(f"    [OK] Scored {len(ml_scores)} tickers successfully")


def run_date_range_scanner(start_date: str, end_date: str,
                           use_ml: bool = False,
                           model_path: Optional[str] = None):
    """
    Run 2D vectorized scanner for date range.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        use_ml: If True, adds ML scoring at the end
        model_path: Path to ML model
    """
    from datetime import datetime, timedelta
    from src.vectorized_screening import VectorizedSEPAScreener

    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')

    print(f"\n{'='*80}")
    print(f"DATE RANGE MODE: {start_date} to {end_date}")
    print(f"{'='*80}")

    total_start = time.time()

    # Initialize
    data_repo = DataRepository()
    ml_scorer = load_ml_scorer(model_path) if use_ml else None

    # PRE-SCAN: Update cache once
    print("\n[PRE-SCAN] Updating cache...")
    tickers = data_repo.update_universe()
    tickers.append(config.BENCHMARK_TICKER)

    min_date = (pd.Timestamp.now() - pd.DateOffset(years=2)).strftime('%Y-%m-%d')
    results = data_repo.update_cache(tickers, force=False, source='fmp')
    print(f"            Updated {sum(results.values())}/{len(tickers)} tickers")

    # Load all data once
    print("\n[PRE-SCAN] Loading price data...")
    all_ticker_data = data_repo.get_batch_data(tickers, min_date=min_date, check_min_date=False)
    print(f"            Loaded {len(all_ticker_data)} tickers")

    # 2D VECTORIZED SCAN
    print(f"\n{'='*80}")
    print(f"2D VECTORIZED SCAN")
    print(f"{'='*80}\n")

    vectorized_start = time.time()

    # Include lookback for indicators
    lookback_days = 251
    data_start_date = start_dt - timedelta(days=lookback_days)

    # Load benchmark and calculate features
    benchmark_data = data_repo.get_benchmark_data(check_min_date=False)
    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)

    print("[Step 1/5] Computing features...")
    enriched_data = feature_engine.process_universe_batch(all_ticker_data)
    print(f"            Done\n")

    print("[Step 2/5] Building 2D matrix...")
    df_matrix = VectorizedSEPAScreener.build_2d_matrix(
        enriched_data,
        start_date=pd.Timestamp(data_start_date),
        end_date=pd.Timestamp(end_dt)
    )
    print(f"            {df_matrix.shape[0]:,} rows\n")

    print("[Step 3/5] Computing SEPA status...")
    df_matrix = VectorizedSEPAScreener.add_sepa_status_column(df_matrix)
    print(f"            {df_matrix['SEPA_Status'].sum():,} qualified\n")

    print("[Step 4/5] Finding transitions...")
    buy_signals, sell_signals = VectorizedSEPAScreener.find_signal_transitions(
        df_matrix,
        date_range_start=pd.Timestamp(start_dt),
        date_range_end=pd.Timestamp(end_dt)
    )
    print(f"            {len(buy_signals):,} buys, {len(sell_signals):,} sells\n")

    print("[Step 5/5] Updating database...")
    process_date_range_signals(buy_signals, sell_signals, enriched_data, ml_scorer, data_repo)

    # Summary
    total_time = time.time() - total_start
    num_days = (end_dt - start_dt).days + 1

    print(f"\n{'='*80}")
    print(f"[OK] SCAN COMPLETE!")
    print(f"{'='*80}")
    print(f"Total time: {total_time:.1f}s")
    print(f"Dates processed: {num_days}")
    print(f"Speed: {total_time / num_days:.2f}s per day")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QSS Daily Scanner with Date Range Support")
    parser.add_argument('--scan-date', type=str, help='Scan date (YYYY-MM-DD). Default: latest trading day')
    parser.add_argument('--date-range', nargs=2, metavar=('START', 'END'),
                       help='Scan date range (YYYY-MM-DD YYYY-MM-DD)')
    parser.add_argument('--csv-output', action='store_true', help='Export results to CSV')
    parser.add_argument('--use-ml', action='store_true', help='Enable ML scoring')
    parser.add_argument('--model-path', type=str, default=None,
                       help=f'Path to ML model (default: {config.ML_PRODUCTION_MODEL})')
    parser.add_argument('--tickers', nargs='+', metavar='TICKER',
                       help='Specific tickers to scan (e.g., --tickers WMT NUE AAPL)')

    args = parser.parse_args()

    try:
        if args.date_range:
            # Date range mode
            run_date_range_scanner(
                start_date=args.date_range[0],
                end_date=args.date_range[1],
                use_ml=args.use_ml,
                model_path=args.model_path
            )
        else:
            # Single day mode
            run_daily_scanner(
                scan_date=args.scan_date,
                csv_output=args.csv_output,
                use_ml=args.use_ml,
                model_path=args.model_path,
                tickers=args.tickers
            )
    except KeyboardInterrupt:
        print("\n\nScanner interrupted by user.")
    except Exception as e:
        logger.error(f"Scanner failed: {e}", exc_info=True)
        print(f"\n[ERROR]: {e}")
