"""
Scanner - Fast SEPA screening using cached universe parquet.

Zero network I/O for SEPA filtering. On-demand loading only for ML scoring.

Modes:
1. Single-day: Load snapshot + 20-day window for C4, filter SEPA C1-C11
2. Batch (date range): Load universe segment, vectorized SEPA screening

SEPA Criteria (C1-C11):
    C1. Price > 150 SMA
    C2. Price > 200 SMA
    C3. 150 SMA > 200 SMA
    C4. 200 SMA trending up (> 20 days ago)
    C5. 50 SMA > 150 SMA
    C6. Price > 50 SMA
    C7. Price > 30% above 52-week low
    C8. Price within 15% of 52-week high
    C9. rs_rating in top 30% of universe
    C10. Close > 20-day high (breakout)
    C11. Volume > average (Vol_Ratio > 1.0)
"""

import pandas as pd
import numpy as np
import argparse
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Tuple

import config
from src.universe_engine import UniverseEngine
from src.database import DatabaseManager

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Column mapping: universe (lowercase) -> screener (mixed case)
COLUMN_MAP = {
    'close': 'Close',
    'open': 'Open',
    'high': 'High',
    'low': 'Low',
    'volume': 'Volume',
    'sma_50': 'SMA_50',
    'sma_150': 'SMA_150',
    'sma_200': 'SMA_200',
    'high_52w': 'High_52W',
    'low_52w': 'Low_52W',
    'high_20d': 'High_20D',
    'vol_ratio': 'Vol_Ratio',
    'vol_ma': 'Vol_MA',
    'atr': 'ATR',
}


def to_python_float(val):
    """Convert numpy types to Python float for SQLite."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, (np.floating, np.integer)):
        return float(val)
    if isinstance(val, float):
        return val
    return None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names from universe format to screener format."""
    return df.rename(columns=COLUMN_MAP)


def load_m03_regime(scan_date: str) -> Optional[dict]:
    """Load M03 Market Regime score."""
    try:
        from src.pipeline import M03RegimeCalculator
        regime = M03RegimeCalculator()
        result = regime.calculate(as_of_date=scan_date)
        gating = regime.should_gate_signal(score=result['score'])
        result['allow_longs'] = gating['allow_longs']
        result['reduced_sizing'] = gating['reduced_sizing']

        category_display = result['category'].upper().replace('_', ' ')
        print(f"\n[M03 Regime] Score: {result['score']:.1f} ({category_display})")
        if not gating['allow_longs']:
            print(f"      [GATE] Longs BLOCKED (score < {config.M03_LONG_ALLOW_MIN})")
        return result
    except Exception as e:
        logger.warning(f"M03 Regime calculation failed: {e}")
        return None


def load_production_scorer():
    """Load ProductionScorer with M01+M02 models."""
    try:
        from src.pipeline import ProductionScorer
        scorer = ProductionScorer()
        scorer.load_models()
        print(f"\n[ML] Loaded M01 + M02 Loser Detector")
        return scorer
    except Exception as e:
        logger.warning(f"ProductionScorer loading failed: {e}")
        return None


def apply_sepa_filter(df: pd.DataFrame, c4_lookback: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    Apply SEPA C1-C11 filtering to a DataFrame.

    Args:
        df: DataFrame with normalized columns (Close, SMA_50, etc.)
            Must have 'ticker' as index or column.
        c4_lookback: Optional DataFrame with SMA_200 from 20 days ago per ticker.
            If None, C4 is assumed True.

    Returns:
        DataFrame with boolean columns: trend_ok, breakout_ok, sepa_qualified
    """
    result = df.copy()

    # C1-C3: Price/MA relationships
    c1 = result['Close'] > result['SMA_150']
    c2 = result['Close'] > result['SMA_200']
    c3 = result['SMA_150'] > result['SMA_200']

    # C4: SMA_200 trending up (requires lookback data)
    if c4_lookback is not None and 'SMA_200_20d' in result.columns:
        c4 = result['SMA_200'] > result['SMA_200_20d']
    else:
        c4 = pd.Series(True, index=result.index)

    # C5-C6: More MA conditions
    c5 = result['SMA_50'] > result['SMA_150']
    c6 = result['Close'] > result['SMA_50']

    # C7-C8: 52-week range
    c7 = result['Close'] > result['Low_52W'] * 1.30  # 30% above 52W low
    c8 = result['Close'] > result['High_52W'] * 0.85  # Within 15% of 52W high

    # C9: RS rank in top 30%
    if 'rs_rating' in result.columns:
        rs_threshold = result['rs_rating'].quantile(0.70)
        c9 = result['rs_rating'] >= rs_threshold
    else:
        c9 = pd.Series(True, index=result.index)

    # Trend OK = C1-C9
    result['trend_ok'] = c1 & c2 & c3 & c4 & c5 & c6 & c7 & c8 & c9

    # C10-C11: Breakout conditions
    if 'High_20D' in result.columns:
        c10 = result['Close'] > result['High_20D']
    else:
        c10 = pd.Series(False, index=result.index)

    if 'Vol_Ratio' in result.columns:
        c11 = result['Vol_Ratio'] > 1.0
    else:
        c11 = pd.Series(False, index=result.index)

    result['breakout_ok'] = c10 & c11
    result['sepa_qualified'] = result['trend_ok'] & result['breakout_ok']

    return result


def get_snapshot_with_c4(engine: UniverseEngine, scan_date: pd.Timestamp,
                          lookback_days: int = 20) -> pd.DataFrame:
    """
    Load snapshot with C4 lookback data.

    Loads current date snapshot plus data from lookback_days ago
    to enable C4 (SMA_200 trending up) check.

    Args:
        engine: UniverseEngine instance
        scan_date: Date to scan
        lookback_days: Days back for C4 check (default: 20)

    Returns:
        DataFrame indexed by ticker with SMA_200_20d column added
    """
    # Get current snapshot
    snapshot = engine.get_snapshot(scan_date)
    if len(snapshot) == 0:
        return pd.DataFrame()

    # Normalize column names
    snapshot = normalize_columns(snapshot)

    # Get lookback date snapshot for C4
    lookback_date = scan_date - pd.Timedelta(days=lookback_days + 10)  # Buffer for weekends

    # Load segment and find actual trading day ~20 days ago
    year = scan_date.year
    segment_name = engine._get_segment_name(year)
    segment_df = engine._load_segment(segment_name)

    if len(segment_df) > 0:
        # Get all dates in segment
        dates = segment_df.index.get_level_values('date').unique().sort_values()
        # Find dates before scan_date
        prior_dates = dates[dates < scan_date]

        if len(prior_dates) >= lookback_days:
            lookback_actual = prior_dates[-lookback_days]
            lookback_snapshot = engine.get_snapshot(lookback_actual)
            lookback_snapshot = normalize_columns(lookback_snapshot)

            # Add SMA_200 from 20 trading days ago
            if 'SMA_200' in lookback_snapshot.columns:
                snapshot['SMA_200_20d'] = lookback_snapshot['SMA_200']
                logger.info(f"C4 lookback: {lookback_actual.date()} ({lookback_days} trading days ago)")

    return snapshot


def prepare_ml_candidates(tickers: List[str], scan_date: pd.Timestamp) -> pd.DataFrame:
    """
    Prepare heavyweight features for ML scoring.

    Loads full ticker data and calculates alpha factors for ML candidates.
    This is the on-demand loading step - only called for SEPA-qualified tickers.

    Uses parallel alpha calculation for performance.

    Args:
        tickers: List of ticker symbols to prepare
        scan_date: Date to score

    Returns:
        DataFrame ready for ProductionScorer.score()
    """
    from src.data_engine import DataRepository
    from src.features import FeatureEngineer
    from src.fundamental_merger import FundamentalMerger
    from src.alpha_factors import AlphaEngine
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import os

    if not tickers:
        return pd.DataFrame()

    logger.info(f"Preparing ML features for {len(tickers)} candidates...")
    start_time = time.time()

    # Load data
    data_repo = DataRepository()
    benchmark_data = data_repo.get_benchmark_data(check_min_date=False, force_cache_only=True)
    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    fund_merger = FundamentalMerger()

    # Load ticker data
    min_date = (scan_date - pd.DateOffset(years=2)).strftime('%Y-%m-%d')
    ticker_data = data_repo.get_batch_data(
        tickers=tickers,
        min_date=min_date,
        check_min_date=False,
        force_cache_only=True
    )

    # Calculate lightweight features
    enriched = feature_engine.process_universe_batch(ticker_data)

    # PARALLEL ALPHA CALCULATION
    alpha_engine = AlphaEngine()
    expected_alpha_cols = [f'alpha{num:03d}' for num in alpha_engine.alpha_list]

    # Find tickers needing alpha calculation
    tickers_needing_alphas = []
    for ticker in tickers:
        df = enriched.get(ticker)
        if df is not None and len(df) > 0:
            if not all(col in df.columns for col in expected_alpha_cols):
                tickers_needing_alphas.append(ticker)

    if tickers_needing_alphas:
        logger.info(f"Calculating alphas for {len(tickers_needing_alphas)} tickers (parallel)...")

        def calc_alpha(ticker: str) -> tuple:
            try:
                df = enriched[ticker]
                fe = FeatureEngineer(benchmark_data=None)
                result = fe.calculate_heavyweight_features(df, ticker)
                return (ticker, result, None)
            except Exception as e:
                return (ticker, None, str(e))

        max_workers = min(os.cpu_count() or 4, 8)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(calc_alpha, t): t for t in tickers_needing_alphas}
            for future in as_completed(futures):
                ticker, result, error = future.result()
                if error is None and result is not None:
                    enriched[ticker] = result

    alpha_time = time.time() - start_time
    logger.info(f"Alpha calculation done in {alpha_time:.1f}s")

    # Build candidate rows
    candidates = []
    for ticker in tickers:
        df = enriched.get(ticker)
        if df is None or len(df) == 0:
            continue

        # Get row at scan_date
        if scan_date in df.index:
            row = df.loc[scan_date]
        else:
            available = df.index[df.index <= scan_date]
            if len(available) == 0:
                continue
            row = df.loc[available[-1]]

        # Merge fundamentals - use DatetimeIndex with name='Date' as required by FundamentalMerger
        try:
            close_val = row.get('Close', np.nan) if isinstance(row, dict) else row.get('Close', np.nan)
            single_df = pd.DataFrame(
                {'Close': [close_val]},
                index=pd.DatetimeIndex([scan_date], name='Date')
            )
            merged = fund_merger.merge_ticker_data(ticker, single_df)
            if len(merged) > 0:
                fund_cols = [c for c in merged.columns if c not in ['Close', 'Open', 'High', 'Low', 'Volume']]
                # Convert row to dict to avoid SettingWithCopyWarning
                row = row.to_dict() if hasattr(row, 'to_dict') else dict(row)
                for col in fund_cols:
                    row[col] = merged[col].iloc[0]
        except Exception as e:
            logger.debug(f"[{ticker}] Fundamentals failed: {e}")

        # Build candidate dict (row may be dict or Series)
        if isinstance(row, dict):
            candidate = {'ticker': ticker, 'date': scan_date, **row}
        else:
            candidate = {'ticker': ticker, 'date': scan_date, **row.to_dict()}
        candidates.append(candidate)

    elapsed = time.time() - start_time
    logger.info(f"ML features prepared in {elapsed:.1f}s ({elapsed/max(len(tickers),1)*1000:.0f}ms/ticker)")

    return pd.DataFrame(candidates)


def run_scanner(scan_date: Optional[str] = None,
                use_ml: bool = False,
                csv_output: bool = False):
    """
    Run single-day scanner using cached universe.

    Workflow:
    1. Load snapshot + 20-day window for C4
    2. Apply SEPA C1-C11 filter
    3. Optionally score with M01+M02
    4. Update buy list database

    Args:
        scan_date: Date to scan (YYYY-MM-DD). Default: latest in universe
        use_ml: Enable M01/M02 scoring
        csv_output: Export results to CSV
    """
    start_time = time.time()

    print("=" * 80)
    print(" SCANNER (Universe Cache Mode)")
    print("=" * 80)

    # Initialize
    engine = UniverseEngine()
    db = DatabaseManager()

    # Get universe stats
    stats = engine.get_universe_stats()
    if stats.get('status') == 'empty':
        print("\n[ERROR] Universe not built. Run: python data_curator.py --universe")
        return

    # Determine scan date
    if scan_date:
        scan_date_obj = pd.Timestamp(scan_date)
    else:
        date_range = stats['date_range']
        latest_str = date_range.split(' to ')[1]
        scan_date_obj = pd.Timestamp(latest_str)

    scan_date_str = scan_date_obj.strftime('%Y-%m-%d')
    print(f"\nScan Date: {scan_date_str}")

    # Load M03 Regime
    m03_result = load_m03_regime(scan_date_str)
    m03_allow_longs = m03_result['allow_longs'] if m03_result else True

    # ========================================================================
    # STEP 1: Load Snapshot with C4 Lookback
    # ========================================================================
    print(f"\n[1/4] Loading Universe Snapshot...")
    load_start = time.time()

    snapshot = get_snapshot_with_c4(engine, scan_date_obj, lookback_days=20)
    if len(snapshot) == 0:
        print(f"[ERROR] No data for {scan_date_str}")
        return

    load_time = time.time() - load_start
    has_c4 = 'SMA_200_20d' in snapshot.columns
    print(f"       Loaded {len(snapshot)} tickers in {load_time:.2f}s")
    print(f"       C4 lookback: {'Yes' if has_c4 else 'No (assuming True)'}")

    # ========================================================================
    # STEP 2: SEPA Screening (C1-C11)
    # ========================================================================
    print(f"\n[2/4] SEPA Screening (C1-C11)...")
    screen_start = time.time()

    # Check required columns
    required = ['Close', 'SMA_50', 'SMA_150', 'SMA_200', 'High_52W', 'Low_52W']
    missing = [c for c in required if c not in snapshot.columns]
    if missing:
        print(f"[ERROR] Missing columns: {missing}")
        return

    # Apply SEPA filter
    screened = apply_sepa_filter(snapshot)

    trend_ok_tickers = screened[screened['trend_ok']].index.tolist()
    sepa_qualified = screened[screened['sepa_qualified']].index.tolist()

    screen_time = time.time() - screen_start
    print(f"       Trend OK (C1-C9): {len(trend_ok_tickers)} tickers")
    print(f"       SEPA Qualified (C1-C11): {len(sepa_qualified)} tickers")
    print(f"       Screening time: {screen_time:.2f}s")

    # ========================================================================
    # STEP 3: ML Scoring (Optional)
    # ========================================================================
    ml_scores_df = None
    ml_time = 0

    if use_ml and sepa_qualified:
        print(f"\n[3/4] M01 + M02 Scoring...")
        ml_start = time.time()

        scorer = load_production_scorer()
        if scorer:
            # Prepare heavyweight features for candidates
            candidates_df = prepare_ml_candidates(sepa_qualified, scan_date_obj)

            if len(candidates_df) > 0:
                # Apply preprocessing if available
                preprocess_path = Path('models/preprocessing_config.json')
                if preprocess_path.exists():
                    try:
                        from src.feature_preprocessor import FeaturePreprocessor
                        preprocessor = FeaturePreprocessor.load(str(preprocess_path))
                        candidates_df = preprocessor.transform(candidates_df)
                    except Exception as e:
                        logger.warning(f"Preprocessing failed: {e}")

                # Score
                ml_scores_df = scorer.score(
                    candidates_df,
                    use_volatility_adjustment=True,
                    use_m02=True
                )

                ml_time = time.time() - ml_start
                valid = ml_scores_df['final_score'].notna().sum() if 'final_score' in ml_scores_df.columns else 0
                print(f"       Scored {valid} candidates in {ml_time:.2f}s")
    else:
        print(f"\n[3/4] ML Scoring: {'Skipped (no candidates)' if not sepa_qualified else 'Disabled'}")

    # ========================================================================
    # STEP 4: Update Buy List
    # ========================================================================
    print(f"\n[4/4] Updating Buy List...")

    # Get current buy list
    current_buy_list = db.get_buy_list(active_only=True, as_of_date=scan_date_str)
    tickers_in_list = set(current_buy_list['ticker'].tolist()) if not current_buy_list.empty else set()
    trend_ok_set = set(trend_ok_tickers)
    sepa_set = set(sepa_qualified)

    # New triggers (SEPA qualified, not already in list)
    new_triggers = sepa_set - tickers_in_list

    # M03 gating
    if not m03_allow_longs and new_triggers:
        print(f"       [M03 GATE] Blocking {len(new_triggers)} signal(s)")
        new_triggers = set()

    # Removals (in list but no longer trend OK)
    tickers_to_remove = tickers_in_list - trend_ok_set

    # Execute additions
    for ticker in new_triggers:
        row = snapshot.loc[ticker]

        # Get ML scores
        m01_score = None
        m02_loser = None
        final_score = None

        if ml_scores_df is not None and len(ml_scores_df) > 0:
            ticker_row = ml_scores_df[ml_scores_df['ticker'] == ticker]
            if len(ticker_row) > 0:
                data = ticker_row.iloc[0]
                m01_score = to_python_float(data.get('m01_score'))
                m02_loser = to_python_float(data.get('m02_loser_proba'))
                final_score = to_python_float(data.get('final_score'))

        db.add_to_buy_list(
            ticker=ticker,
            signal_date=scan_date_str,
            signal_price=float(row['Close']),
            current_price=float(row['Close']),
            rs=to_python_float(row.get('RS')),
            vol_ratio=to_python_float(row.get('Vol_Ratio')),
            ma50=to_python_float(row.get('SMA_50')),
            ma150=to_python_float(row.get('SMA_150')),
            ma200=to_python_float(row.get('SMA_200')),
            high_52w=to_python_float(row.get('High_52W')),
            low_52w=to_python_float(row.get('Low_52W')),
            ml_probability=to_python_float(row.get('m02_survival')),
            ml_expected_return=m01_score,
            m01_expected_return=m01_score
        )

        if m02_loser is not None:
            db.update_buy_list_column(ticker, 'm02_loser_proba', m02_loser)
        if final_score is not None:
            db.update_buy_list_column(ticker, 'final_score', final_score)
        if m03_result:
            db.update_buy_list_column(ticker, 'm03_regime_score', m03_result['score'])
            db.update_buy_list_column(ticker, 'm03_regime_category', m03_result['category'])

        db.log_buy_list_activity(
            ticker=ticker,
            action='ADDED',
            action_date=scan_date_str,
            reason='sepa_qualified'
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

    print(f"       +{len(new_triggers)} added, -{len(tickers_to_remove)} removed")

    # ========================================================================
    # Summary
    # ========================================================================
    total_time = time.time() - start_time

    print(f"\n{'=' * 80}")
    print(f" SCAN COMPLETE | {scan_date_str}")
    print("=" * 80)
    print(f"Total time: {total_time:.2f}s")
    print(f"  - Universe load: {load_time:.2f}s")
    print(f"  - SEPA screening: {screen_time:.2f}s")
    if use_ml:
        print(f"  - ML scoring: {ml_time:.2f}s")

    # Display buy list
    buy_list = db.get_buy_list(active_only=True, as_of_date=scan_date_str)
    print(f"\nActive Buy List: {len(buy_list)} tickers")

    if not buy_list.empty and len(buy_list) <= 30:
        cols = ['ticker', 'signal_date', 'signal_price', 'rs', 'final_score']
        available = [c for c in cols if c in buy_list.columns]
        print(buy_list[available].to_string(index=False))

    if csv_output:
        output_dir = Path(config.DATA_DIR) / 'scanner_output'
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f'scan_{scan_date_str}.csv'
        buy_list.to_csv(path, index=False)
        print(f"\n[FILE] Exported: {path}")

    print("=" * 80 + "\n")


def run_batch_scanner(start_date: str, end_date: str,
                      use_ml: bool = False):
    """
    Run batch scanner for date range using vectorized operations.

    Workflow:
    1. Load universe segment for date range
    2. Apply vectorized SEPA screening
    3. Find 0->1 and 1->0 transitions
    4. Update buy list for each transition date

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        use_ml: Enable M01/M02 scoring for final buy list
    """
    from datetime import datetime

    start_dt = pd.Timestamp(start_date)
    end_dt = pd.Timestamp(end_date)

    print(f"\n{'=' * 80}")
    print(f" BATCH SCANNER | {start_date} to {end_date}")
    print("=" * 80)

    start_time = time.time()

    # Initialize
    engine = UniverseEngine()
    db = DatabaseManager()

    # ========================================================================
    # STEP 1: Load Universe Segment
    # ========================================================================
    print(f"\n[1/4] Loading Universe Segment...")
    load_start = time.time()

    # Include 30-day lookback for C4 and indicators
    lookback_date = start_dt - pd.Timedelta(days=40)

    # Load segments
    start_str = lookback_date.strftime('%Y-%m-%d')
    end_str = end_dt.strftime('%Y-%m-%d')

    df = engine._load_segments_for_range(start_str, end_str)

    if len(df) == 0:
        print("[ERROR] No universe data for date range")
        return

    # Convert to long format
    df = df.reset_index()
    df = normalize_columns(df)

    load_time = time.time() - load_start
    print(f"       Loaded {len(df):,} rows in {load_time:.2f}s")

    # ========================================================================
    # STEP 2: Vectorized SEPA Screening
    # ========================================================================
    print(f"\n[2/4] Vectorized SEPA Screening...")
    screen_start = time.time()

    # Sort for groupby operations
    df = df.sort_values(['ticker', 'date'])

    # C1-C3: Price/MA
    c1 = df['Close'] > df['SMA_150']
    c2 = df['Close'] > df['SMA_200']
    c3 = df['SMA_150'] > df['SMA_200']

    # C4: SMA_200 trending up (vs 20 trading days ago)
    df['SMA_200_20d'] = df.groupby('ticker')['SMA_200'].shift(20)
    c4 = df['SMA_200'] > df['SMA_200_20d']

    # C5-C6
    c5 = df['SMA_50'] > df['SMA_150']
    c6 = df['Close'] > df['SMA_50']

    # C7-C8: 52W range
    c7 = df['Close'] > df['Low_52W'] * 1.30
    c8 = df['Close'] > df['High_52W'] * 0.85

    # C9: RS rank top 30% per date
    if 'rs_rating' in df.columns:
        df['rs_pct70'] = df.groupby('date')['rs_rating'].transform(lambda x: x.quantile(0.70))
        c9 = df['rs_rating'] >= df['rs_pct70']
        df = df.drop(columns=['rs_pct70'])
    else:
        c9 = pd.Series(True, index=df.index)

    # Trend OK (C1-C9)
    df['trend_ok'] = c1 & c2 & c3 & c4 & c5 & c6 & c7 & c8 & c9

    # C10-C11: Breakout
    if 'High_20D' in df.columns:
        c10 = df['Close'] > df['High_20D']
    else:
        c10 = pd.Series(False, index=df.index)

    if 'Vol_Ratio' in df.columns:
        c11 = df['Vol_Ratio'] > 1.0
    else:
        c11 = pd.Series(False, index=df.index)

    df['sepa_qualified'] = df['trend_ok'] & c10 & c11

    # Clean up
    df = df.drop(columns=['SMA_200_20d'], errors='ignore')

    screen_time = time.time() - screen_start
    qualified_count = df['sepa_qualified'].sum()
    print(f"       {qualified_count:,} qualified rows in {screen_time:.2f}s")

    # ========================================================================
    # STEP 3: Find Transitions
    # ========================================================================
    print(f"\n[3/4] Finding Signal Transitions...")
    trans_start = time.time()

    # Previous day status per ticker
    df['sepa_prev'] = df.groupby('ticker')['sepa_qualified'].shift(1)

    # Buy: False -> True
    df['is_buy'] = (df['sepa_qualified'] == True) & (df['sepa_prev'] == False)

    # Sell: True -> False (trend break)
    df['is_sell'] = (df['trend_ok'] == False) & (df.groupby('ticker')['trend_ok'].shift(1) == True)

    # Filter to scan range only
    in_range = (df['date'] >= start_dt) & (df['date'] <= end_dt)

    buy_signals = df[df['is_buy'] & in_range][['ticker', 'date', 'Close']].copy()
    sell_signals = df[df['is_sell'] & in_range][['ticker', 'date']].copy()

    trans_time = time.time() - trans_start
    print(f"       {len(buy_signals)} buy signals, {len(sell_signals)} sell signals")
    print(f"       Transition detection: {trans_time:.2f}s")

    # ========================================================================
    # STEP 4: Update Database
    # ========================================================================
    print(f"\n[4/4] Updating Database...")
    db_start = time.time()

    # Process sells first (by date order)
    for _, row in sell_signals.sort_values('date').iterrows():
        ticker = row['ticker']
        date_str = row['date'].strftime('%Y-%m-%d')
        db.remove_from_buy_list(ticker, reason='trend_broken')
        db.log_buy_list_activity(ticker, 'REMOVED', date_str, 'trend_broken')

    # Process buys
    for _, row in buy_signals.sort_values('date').iterrows():
        ticker = row['ticker']
        date_str = row['date'].strftime('%Y-%m-%d')
        price = float(row['Close'])

        # Get full row from df for this ticker/date
        mask = (df['ticker'] == ticker) & (df['date'] == row['date'])
        if mask.any():
            full_row = df[mask].iloc[0]
            db.add_to_buy_list(
                ticker=ticker,
                signal_date=date_str,
                signal_price=price,
                current_price=price,
                rs=to_python_float(full_row.get('RS')),
                vol_ratio=to_python_float(full_row.get('Vol_Ratio')),
                ma50=to_python_float(full_row.get('SMA_50')),
                ma150=to_python_float(full_row.get('SMA_150')),
                ma200=to_python_float(full_row.get('SMA_200')),
                high_52w=to_python_float(full_row.get('High_52W')),
                low_52w=to_python_float(full_row.get('Low_52W'))
            )
            db.log_buy_list_activity(ticker, 'ADDED', date_str, 'sepa_qualified')

    db_time = time.time() - db_start
    print(f"       Database updated in {db_time:.2f}s")

    # ========================================================================
    # Optional: ML Scoring at End Date
    # ========================================================================
    if use_ml:
        print(f"\n[5/5] ML Scoring (at {end_date})...")
        buy_list = db.get_buy_list(active_only=True, as_of_date=end_date)

        if not buy_list.empty:
            tickers = buy_list['ticker'].tolist()
            scorer = load_production_scorer()

            if scorer:
                candidates_df = prepare_ml_candidates(tickers, end_dt)

                if len(candidates_df) > 0:
                    preprocess_path = Path('models/preprocessing_config.json')
                    if preprocess_path.exists():
                        try:
                            from src.feature_preprocessor import FeaturePreprocessor
                            preprocessor = FeaturePreprocessor.load(str(preprocess_path))
                            candidates_df = preprocessor.transform(candidates_df)
                        except Exception:
                            pass

                    ml_scores = scorer.score(candidates_df, use_volatility_adjustment=True, use_m02=True)

                    # Update database with scores
                    for _, row in ml_scores.iterrows():
                        ticker = row['ticker']
                        db.update_buy_list_column(ticker, 'm01_expected_return',
                                                  to_python_float(row.get('m01_score')))
                        db.update_buy_list_column(ticker, 'final_score',
                                                  to_python_float(row.get('final_score')))

                    print(f"       Scored {len(ml_scores)} tickers")

    # ========================================================================
    # Summary
    # ========================================================================
    total_time = time.time() - start_time
    num_days = (end_dt - start_dt).days + 1

    print(f"\n{'=' * 80}")
    print(f" BATCH SCAN COMPLETE")
    print("=" * 80)
    print(f"Date range: {start_date} to {end_date} ({num_days} days)")
    print(f"Total time: {total_time:.1f}s ({total_time/num_days:.2f}s/day)")
    print(f"Buy signals: {len(buy_signals)}")
    print(f"Sell signals: {len(sell_signals)}")

    buy_list = db.get_buy_list(active_only=True, as_of_date=end_date)
    print(f"Final buy list: {len(buy_list)} tickers")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fast SEPA Scanner (Universe Cache)")
    parser.add_argument('--scan-date', type=str, help='Scan date (YYYY-MM-DD)')
    parser.add_argument('--date-range', nargs=2, metavar=('START', 'END'),
                        help='Batch scan date range')
    parser.add_argument('--use-ml', action='store_true', help='Enable ML scoring')
    parser.add_argument('--csv-output', action='store_true', help='Export to CSV')

    args = parser.parse_args()

    try:
        if args.date_range:
            run_batch_scanner(
                start_date=args.date_range[0],
                end_date=args.date_range[1],
                use_ml=args.use_ml
            )
        else:
            run_scanner(
                scan_date=args.scan_date,
                use_ml=args.use_ml,
                csv_output=args.csv_output
            )
    except KeyboardInterrupt:
        print("\n\nScanner interrupted.")
    except Exception as e:
        logger.error(f"Scanner failed: {e}", exc_info=True)
        print(f"\n[ERROR]: {e}")
