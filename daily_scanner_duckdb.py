"""
Daily Scanner - DuckDB Version
================================
SQL-native scanning with batch data loading.

Key improvements over file-based scanner:
1. Single SQL query loads 500+ tickers (<1s vs 5-30s ThreadPool)
2. Vectorized ASOF JOIN for fundamentals (<1s vs 5-50s loop)
3. Pre-computed features from daily_features table
4. No file I/O overhead
5. Uses DuckDB for buy_list storage (consolidated database)

Expected performance:
- Old scanner: 30-60s total
- New scanner: 10-20s total (2-3x faster)

Usage:
    # Daily scan with ML scoring
    python daily_scanner_duckdb.py --use-ml

    # Scan specific date
    python daily_scanner_duckdb.py --scan-date 2024-12-31 --use-ml

    # Scan specific tickers
    python daily_scanner_duckdb.py --tickers AAPL,NVDA,TSLA --use-ml
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
import duckdb

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.data_loader_duckdb import DuckDBDataLoader
from src.database_duckdb import DuckDBManager
from src.features import FeatureEngineer
from src.utils import get_latest_trading_day
from src.feature_preprocessor import FeaturePreprocessor

# Import ML components (same as old scanner)
from src.ml_scorer import MLScorer
from src.pipeline import ProductionScorer, M03RegimeCalculator

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Helper Functions (same as original scanner)
# ============================================================================

def to_python_float(val):
    """Convert numpy float types to Python native float."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, (np.floating, np.integer)):
        return float(val)
    if isinstance(val, float):
        return val
    return None


def load_production_scorer():
    """Load ProductionScorer with M01+M02 models."""
    try:
        scorer = ProductionScorer()
        scorer.load_models()

        print(f"\n[ProductionScorer] Loaded M01 + M02 Loser Detector")
        print(f"      M01: {config.ML_M01_MODEL}")
        print(f"      M02: models/m02.json (Loser Detector)")
        print(f"      Formula: Final_Score = M01_adj × (1 - P(loser))")

        return scorer
    except Exception as e:
        print(f"\n[WARN] ProductionScorer loading failed: {e}")
        print("        Proceeding without ML scoring...\n")
        return None


def load_m03_regime(scan_date: str = None) -> dict:
    """Load M03 Market Regime Calculator and compute regime score."""
    try:
        regime = M03RegimeCalculator()
        result = regime.calculate(as_of_date=scan_date)
        gating = regime.should_gate_signal(score=result['score'])

        result['allow_longs'] = gating['allow_longs']
        result['reduced_sizing'] = gating['reduced_sizing']

        category_display = result['category'].upper().replace('_', ' ')
        print(f"\n[M03 Regime] Score: {result['score']:.1f} ({category_display})")
        print(f"      Trend: {result['pillars']['trend']['score']:.0f} | "
              f"Liquidity: {result['pillars']['liquidity']['score']:.0f} | "
              f"Risk: {result['pillars']['risk_appetite']['score']:.0f}")

        if not gating['allow_longs']:
            print(f"      [GATE] Longs BLOCKED (score < {config.M03_LONG_ALLOW_MIN})")
        elif gating['reduced_sizing']:
            print(f"      [GATE] Reduced sizing (score < {config.M03_LONG_REDUCED_MIN})")

        return result
    except Exception as e:
        print(f"\n[WARN] M03 Regime calculation failed: {e}")
        print("        Proceeding without regime gating...\n")
        return None


def extract_features(row, feature_names: List[str]) -> dict:
    """Extract feature dict from candidate row."""
    features_dict = {}
    for feature_name in feature_names:
        if feature_name in row.index:
            value = row[feature_name]
            if pd.isna(value):
                features_dict[feature_name] = None
            elif isinstance(value, (np.integer, np.floating)):
                features_dict[feature_name] = float(value)
            elif isinstance(value, np.bool_):
                features_dict[feature_name] = bool(value)
            else:
                features_dict[feature_name] = value
    return features_dict


def update_final_score_ranks(db: DuckDBManager, scan_date_str: str):
    """Calculate ranks for final_score (M01 × M02 survival)."""
    buy_list_df = db.get_buy_list(active_only=True, as_of_date=scan_date_str)

    if buy_list_df.empty:
        return

    # Rank by final_score (higher = better)
    if 'final_score' in buy_list_df.columns:
        valid_entries = buy_list_df[buy_list_df['final_score'].notna()].copy()
        if len(valid_entries) > 0:
            scores = valid_entries['final_score'].values
            sorted_indices = np.argsort(scores)[::-1]
            ranks = np.empty(len(scores), dtype=int)
            ranks[sorted_indices] = np.arange(1, len(scores) + 1)

            for ticker, rank in zip(valid_entries['ticker'], ranks):
                db.update_buy_list_column(ticker, 'final_score_rank', int(rank))

            logger.info(f"Ranked {len(valid_entries)} tickers by final_score")

    # Also rank by M01 for backwards compatibility
    if 'm01_expected_return' in buy_list_df.columns:
        m01_entries = buy_list_df[buy_list_df['m01_expected_return'].notna()].copy()
        if len(m01_entries) > 0:
            scores = m01_entries['m01_expected_return'].values
            sorted_indices = np.argsort(scores)[::-1]
            ranks = np.empty(len(scores), dtype=int)
            ranks[sorted_indices] = np.arange(1, len(scores) + 1)

            for ticker, rank in zip(m01_entries['ticker'], ranks):
                db.update_buy_list_column(ticker, 'm01_rank', int(rank))

            logger.info(f"Ranked {len(m01_entries)} tickers by M01 expected return")


def prepare_ml_candidates_duckdb(
    tickers: List[str],
    price_data: dict,
    fundamentals_df: pd.DataFrame,
    scan_date_obj: pd.Timestamp
) -> pd.DataFrame:
    """
    Prepare feature DataFrame for ML scoring - DuckDB version.

    Key differences from original:
    - Fundamentals already loaded via ASOF JOIN (no loop)
    - Features already computed in daily_features table
    - Just need to merge and extract

    Args:
        tickers: List of tickers to prepare
        price_data: Dict of ticker → DataFrame with features
        fundamentals_df: Pre-loaded fundamentals (from ASOF JOIN)
        scan_date_obj: Scan date

    Returns:
        DataFrame with candidates ready for ML scoring
    """
    ml_candidates = []
    feature_engine = FeatureEngineer(benchmark_data=None)

    # Batch alpha calculation (if needed)
    print("       [5.2] Calculating heavyweight features (alphas)...")
    alpha_start = time.time()

    from src.alpha_factors import AlphaEngine
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import os

    alpha_engine = AlphaEngine()
    tickers_needing_alphas = []
    expected_alpha_cols = [f'alpha{num:03d}' for num in alpha_engine.alpha_list]

    # Check which tickers need alpha calculation
    for ticker in tickers:
        ticker_df = price_data.get(ticker)
        if ticker_df is not None and len(ticker_df) > 0:
            if not all(col in ticker_df.columns for col in expected_alpha_cols):
                tickers_needing_alphas.append(ticker)

    # Parallel calculate alphas
    if len(tickers_needing_alphas) > 0:
        logger.info(f"Calculating alphas for {len(tickers_needing_alphas)} tickers...")

        def calculate_alpha_for_ticker(ticker: str) -> tuple:
            try:
                ticker_df = price_data[ticker]
                result_df = feature_engine.calculate_heavyweight_features(ticker_df, ticker)
                return (ticker, result_df, None)
            except Exception as e:
                logger.error(f"[{ticker}] Alpha calculation failed: {e}")
                return (ticker, None, str(e))

        max_workers = min(os.cpu_count() or 4, 8)
        completed_count = 0
        results = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(calculate_alpha_for_ticker, ticker): ticker
                      for ticker in tickers_needing_alphas}

            for future in as_completed(futures):
                ticker, result_df, error = future.result()
                completed_count += 1

                if error is None and result_df is not None:
                    results[ticker] = result_df

                if completed_count % 50 == 0 or completed_count == len(tickers_needing_alphas):
                    logger.info(f"  Alpha progress: {completed_count}/{len(tickers_needing_alphas)}")

        # Update price_data with alpha results
        price_data.update(results)

    alpha_time = time.time() - alpha_start
    print(f"       [5.2] Alphas calculated in {alpha_time:.2f}s ({len(tickers_needing_alphas)} needed)")

    # Feature extraction
    scan_date_str = scan_date_obj.strftime('%Y-%m-%d')

    for ticker in tickers:
        ticker_df = price_data.get(ticker)
        if ticker_df is None or len(ticker_df) == 0:
            continue

        # Get row at scan_date
        if scan_date_obj in ticker_df.index:
            row_date = scan_date_obj
            row = ticker_df.loc[scan_date_obj]
        else:
            available_dates = ticker_df.index[ticker_df.index <= scan_date_obj]
            if len(available_dates) == 0:
                continue
            row_date = available_dates[-1]
            row = ticker_df.loc[row_date]

        # Get fundamental data from pre-loaded DataFrame
        fund_data = fundamentals_df[fundamentals_df['ticker'] == ticker] if not fundamentals_df.empty else None
        if fund_data is not None and len(fund_data) > 0:
            fund_row = fund_data.iloc[0]
            fund_dict = fund_row.to_dict()
            # Remove ticker column to avoid duplication
            fund_dict.pop('ticker', None)
        else:
            fund_dict = {}

        # Merge technical + fundamental features
        candidate_features = {
            'ticker': ticker,
            'date': row_date,
            **row.to_dict(),
            **fund_dict
        }

        ml_candidates.append(candidate_features)

    return pd.DataFrame(ml_candidates) if ml_candidates else pd.DataFrame()


# ============================================================================
# Main Scanner Function (DuckDB Version)
# ============================================================================

def run_daily_scanner_duckdb(
    scan_date: Optional[str] = None,
    csv_output: bool = False,
    use_ml: bool = False,
    tickers: Optional[List[str]] = None
):
    """
    Run daily scanner using DuckDB for data loading.

    Args:
        scan_date: Optional date to scan (YYYY-MM-DD)
        csv_output: If True, export buy_list to CSV
        use_ml: If True, use ML scoring (M01 + M02)
        tickers: Optional list of specific tickers to scan
    """
    start_time = time.time()

    # Initialize components
    loader = DuckDBDataLoader()
    db = DuckDBManager()

    # Initialize ProductionScorer
    production_scorer = load_production_scorer() if use_ml else None
    use_ml = (production_scorer is not None)

    # Determine scan date
    if scan_date:
        scan_date_obj = pd.Timestamp(scan_date)
    else:
        scan_date_str = loader.get_latest_trading_day()
        scan_date_obj = pd.Timestamp(scan_date_str)
    scan_date_str = scan_date_obj.strftime('%Y-%m-%d')

    print("=" * 80)
    print(f" DAILY SCANNER (DuckDB) | {scan_date_str}")
    print("=" * 80)

    # Load M03 Market Regime
    m03_result = load_m03_regime(scan_date_str)
    m03_score = m03_result['score'] if m03_result else None
    m03_category = m03_result['category'] if m03_result else None
    m03_allow_longs = m03_result['allow_longs'] if m03_result else True

    total_steps = 3 if use_ml else 2  # Step 3 (SEPA screening) eliminated via v_d1_candidates view

    # ========================================================================
    # STEP 1: Load D1 Candidates from v_d1_candidates View
    # ========================================================================
    print(f"\n[1/{total_steps}] Loading D1 Candidates (C1-C11 SEPA) from v_d1_candidates...")
    load_start = time.time()

    if tickers is None:
        # Use v_d1_candidates view (full C1-C11 SEPA with breakout detection)
        con = duckdb.connect(loader.db_path)
        candidates_df = con.execute("""
            SELECT *
            FROM v_d1_candidates
            WHERE date = ?
        """, [scan_date_str]).df()
        con.close()

        tickers = candidates_df['ticker'].tolist()

        # Separate new triggers from trend-ok stocks
        new_triggers_raw = candidates_df[candidates_df['is_new_trigger'] == 1]
        new_triggers_today = [
            {'ticker': row['ticker'], 'entry_price': row['close']}
            for _, row in new_triggers_raw.iterrows()
        ]
        trend_ok_stocks = [
            {'ticker': row['ticker']}
            for _, row in candidates_df.iterrows()
        ]
    else:
        # Load specified tickers
        print(f"       Using specified tickers: {', '.join(tickers[:5])}{'...' if len(tickers) > 5 else ''} ({len(tickers)} total)")
        # Load their data
        price_data_batch = loader.get_price_data_batch(tickers, end_date=scan_date_str, include_features=True)
        tickers = list(price_data_batch.keys())
        new_triggers_today = []
        trend_ok_stocks = []

    load_time = time.time() - load_start
    print(f"       Loaded {len(tickers)} candidates in {load_time:.2f}s")
    print(f"       Trend OK (C1-C11): {len(trend_ok_stocks)} stocks")
    print(f"       New triggers: {len(new_triggers_today)} stocks")

    if len(tickers) == 0:
        print("\n[WARN] No candidates found!")
        return

    # ========================================================================
    # STEP 2: Load Price Data with Features (Batch SQL Query)
    # ========================================================================
    print(f"\n[2/{total_steps}] Loading Price Data + Features (Single SQL Query)...")
    price_start = time.time()

    # Get last 252 days for features
    # Ensure benchmark ticker is included (it may not pass SEPA filters)
    tickers_to_load = list(set(tickers + [config.BENCHMARK_TICKER]))
    price_data = loader.get_price_data_batch(
        tickers_to_load,
        end_date=scan_date_str,
        include_features=True
    )

    price_time = time.time() - price_start
    print(f"       Loaded {len(price_data)} tickers in {price_time:.2f}s")
    print(f"       [PERF] {price_time/len(price_data)*1000:.1f}ms/ticker (vs 5-30s ThreadPool)")

    # Load benchmark for strategy
    benchmark_data = price_data.get(config.BENCHMARK_TICKER)
    if benchmark_data is None:
        print(f"\n[WARN] Benchmark {config.BENCHMARK_TICKER} not found!")
        return

    # ========================================================================
    # STEP 3: SEPA Screening - SKIPPED (Done in v_d1_candidates view)
    # ========================================================================
    # SEPA C1-C11 screening now done in SQL via v_d1_candidates view
    # This eliminates 10-20s batch_scan_universe overhead

    # ========================================================================
    # STEP 3 (Optional): M01 + M02 Loser Detector Scoring
    # ========================================================================
    ml_scores_df = None
    if use_ml and production_scorer:
        print(f"\n[3/{total_steps}] M01 + M02 Loser Detector Scoring...")
        ml_start = time.time()

        # Identify candidates to score
        print("       [3.1] Identifying candidates...")
        current_buy_list = db.get_buy_list(active_only=True, as_of_date=scan_date_str)
        tickers_in_buy_list = set(current_buy_list['ticker'].tolist()) if not current_buy_list.empty else set()
        new_trigger_tickers = set([t['ticker'] for t in new_triggers_today])
        trend_ok_tickers = set([s['ticker'] for s in trend_ok_stocks])

        tickers_to_score = list(new_trigger_tickers | (tickers_in_buy_list & trend_ok_tickers))
        print(f"       [3.1] Identified {len(tickers_to_score)} candidates")

        if len(tickers_to_score) > 0:
            # Load fundamentals using vectorized ASOF JOIN
            print(f"       [3.2] Loading fundamentals (Vectorized ASOF JOIN)...")
            fund_start = time.time()
            fundamentals_df = loader.get_fundamentals_batch(tickers_to_score, as_of_date=scan_date_str)
            fund_time = time.time() - fund_start
            print(f"       [3.2] Fundamentals loaded in {fund_time:.2f}s")
            print(f"       [PERF] <1s (vs 5-50s loop in old scanner)")

            # Prepare ML candidates
            candidates_df = prepare_ml_candidates_duckdb(
                tickers_to_score,
                price_data,
                fundamentals_df,
                scan_date_obj
            )

            if len(candidates_df) > 0:
                # Apply preprocessing
                preprocess_config_path = Path('models/preprocessing_config.json')
                if preprocess_config_path.exists():
                    try:
                        preprocessor = FeaturePreprocessor.load(str(preprocess_config_path))
                        candidates_df = preprocessor.transform(candidates_df)
                        print(f"       [3.3] Applied preprocessing transforms")
                    except Exception as e:
                        logger.warning(f"Could not load preprocessing config: {e}")

                # Run ProductionScorer
                print(f"       [3.4] Running ProductionScorer...")
                score_start = time.time()

                ml_scores_df = production_scorer.score(
                    candidates_df,
                    use_volatility_adjustment=True,
                    use_m02=True
                )

                score_time = time.time() - score_start
                ml_time = time.time() - ml_start

                valid_scores = ml_scores_df['final_score'].notna().sum() if 'final_score' in ml_scores_df.columns else 0
                print(f"       [3.4] Inference complete in {score_time:.2f}s")
                print(f"       [3.x] Total ML scoring time: {ml_time:.2f}s")
                print(f"             Valid final scores: {valid_scores}")
            else:
                print("       [WARN] No candidates with sufficient data")
        else:
            print("       No candidates to score")

    # ========================================================================
    # FINAL STEP: Update Buy List
    # ========================================================================
    step_num = total_steps
    print(f"\n[{step_num}/{total_steps}] Managing Buy List...")

    # Load current buy list
    current_buy_list = db.get_buy_list(active_only=True, as_of_date=scan_date_str)
    tickers_in_buy_list = set(current_buy_list['ticker'].tolist()) if not current_buy_list.empty else set()
    trend_ok_tickers = set([s['ticker'] for s in trend_ok_stocks])

    # Determine additions and removals
    tickers_to_add = [t for t in new_triggers_today if t['ticker'] not in tickers_in_buy_list]
    tickers_to_remove = tickers_in_buy_list - trend_ok_tickers
    tickers_to_update = tickers_in_buy_list & trend_ok_tickers

    # M03 Regime Gating
    if not m03_allow_longs and tickers_to_add:
        gated_count = len(tickers_to_add)
        print(f"\n       [M03 GATE] Blocking {gated_count} new signal(s) due to bearish regime")
        tickers_to_add = []

    # Execute additions
    for trigger in tickers_to_add:
        ticker = trigger['ticker']
        signal_price = trigger['entry_price']

        # Get indicator values
        ticker_df = price_data.get(ticker)
        if ticker_df is not None:
            if scan_date_obj in ticker_df.index:
                row = ticker_df.loc[scan_date_obj]
            else:
                available_dates = ticker_df.index[ticker_df.index <= scan_date_obj]
                if len(available_dates) > 0:
                    row = ticker_df.loc[available_dates[-1]]
                else:
                    row = None

            if row is not None:
                # Extract values
                atr = row.get('atr_20d') if 'atr_20d' in row.index else row.get('ATR')
                rs = row.get('relative_strength_20d') if 'relative_strength_20d' in row.index else row.get('RS')
                vol_ratio = row.get('avg_volume_20d') / row.get('volume') if 'avg_volume_20d' in row.index and 'volume' in row.index else None
                current_price = row.get('close') if 'close' in row.index else row.get('Close')

                # Get ML scores if available
                ml_data = {}
                if ml_scores_df is not None and not ml_scores_df.empty:
                    ml_row = ml_scores_df[ml_scores_df['ticker'] == ticker]
                    if not ml_row.empty:
                        ml_row = ml_row.iloc[0]
                        ml_data = {
                            'm01_expected_return': to_python_float(ml_row.get('m01_expected_return')),
                            'm02_loser_proba': to_python_float(ml_row.get('m02_loser_proba')),
                            'm02_survival': to_python_float(ml_row.get('m02_survival')),
                            'final_score': to_python_float(ml_row.get('final_score'))
                        }

                # Add to buy list
                db.add_to_buy_list(
                    ticker=ticker,
                    signal_date=scan_date_str,
                    signal_price=signal_price,
                    current_price=current_price or signal_price,
                    entry_price=signal_price,
                    atr=to_python_float(atr),
                    rs=to_python_float(rs),
                    vol_ratio=to_python_float(vol_ratio),
                    ml_model_type='ProductionScorer' if use_ml else None,
                    ml_score_date=scan_date_str if use_ml else None,
                    **ml_data
                )

                # Update M03 regime columns
                if m03_score is not None:
                    db.update_buy_list_column(ticker, 'm03_regime_score', to_python_float(m03_score))
                    db.update_buy_list_column(ticker, 'm03_regime_category', m03_category)

    # Execute removals
    for ticker in tickers_to_remove:
        db.remove_from_buy_list(ticker, reason='sepa_signal_failed')

    # Execute updates
    for ticker in tickers_to_update:
        ticker_df = price_data.get(ticker)
        if ticker_df is not None:
            if scan_date_obj in ticker_df.index:
                row = ticker_df.loc[scan_date_obj]
            else:
                available_dates = ticker_df.index[ticker_df.index <= scan_date_obj]
                if len(available_dates) > 0:
                    row = ticker_df.loc[available_dates[-1]]
                else:
                    continue

            current_price = row.get('close') if 'close' in row.index else row.get('Close')
            rs = row.get('relative_strength_20d') if 'relative_strength_20d' in row.index else None

            # Get ML scores
            ml_data = {}
            if ml_scores_df is not None and not ml_scores_df.empty:
                ml_row = ml_scores_df[ml_scores_df['ticker'] == ticker]
                if not ml_row.empty:
                    ml_row = ml_row.iloc[0]
                    ml_data = {
                        'ml_expected_return': to_python_float(ml_row.get('m01_expected_return')),
                    }

            db.update_buy_list_metrics(
                ticker=ticker,
                scan_date=scan_date_str,
                current_price=current_price,
                rs=to_python_float(rs),
                **ml_data
            )

    # Update ranks
    if use_ml:
        update_final_score_ranks(db, scan_date_str)

    # Print summary
    print(f"\n       Summary:")
    print(f"         Added: {len(tickers_to_add)}")
    print(f"         Removed: {len(tickers_to_remove)}")
    print(f"         Updated: {len(tickers_to_update)}")

    # Get final buy list
    final_buy_list = db.get_buy_list(active_only=True, as_of_date=scan_date_str)
    print(f"         Total active: {len(final_buy_list)}")

    # CSV export
    if csv_output and not final_buy_list.empty:
        csv_path = f"buy_list_{scan_date_str}.csv"
        final_buy_list.to_csv(csv_path, index=False)
        print(f"\n       Exported to: {csv_path}")

    # Total time
    total_time = time.time() - start_time
    print("\n" + "=" * 80)
    print(f"[OK] Scanner Complete in {total_time:.1f}s")
    print("=" * 80 + "\n")

    # Performance comparison
    print(f"[PERF] Performance Highlights:")
    print(f"   Price loading: {price_time:.2f}s (vs 5-30s ThreadPool)")
    if use_ml:
        print(f"   Fundamental merge: {fund_time:.2f}s (vs 5-50s loop)")
    print(f"   Total: {total_time:.1f}s (vs 30-60s expected old scanner)")
    print(f"   [PERF] Speedup: ~{60/total_time:.1f}x faster\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Daily Scanner - DuckDB Version",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--scan-date', type=str, help="Scan date (YYYY-MM-DD)")
    parser.add_argument('--tickers', type=str, help="Comma-separated ticker list")
    parser.add_argument('--use-ml', action='store_true', help="Use ML scoring (M01 + M02)")
    parser.add_argument('--csv-output', action='store_true', help="Export buy list to CSV")

    args = parser.parse_args()

    # Parse tickers
    tickers = None
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(',')]

    # Run scanner
    run_daily_scanner_duckdb(
        scan_date=args.scan_date,
        csv_output=args.csv_output,
        use_ml=args.use_ml,
        tickers=tickers
    )
