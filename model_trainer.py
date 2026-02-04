"""
Model Trainer (Optimized) - Event-Driven ML Pipeline
=====================================================
This script implements the optimized ML workflow:
  1. Simulate Trades (D1): Run SEPA screener to get trade candidates.
  2. Enrich with Features (D2): For each trade, extract features at entry date.
  3. Train Model: Join D1+D2, train with walk-forward validation.

PERFORMANCE NOTES:
  - Uses vectorized SEPA simulation (Fast Simulator).
  - Parallelizes feature extraction with joblib.
  - Caches intermediate DataFrames to disk.

Usage:
    python model_trainer.py --start 2020-01-01 --end 2023-12-31
"""

import argparse
import logging
import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Dict
import time

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.data_engine import DataRepository, CacheMode
from src.features import FeatureEngineer
from src.strategy import SEPAStrategy
from src.trading_config import TradingConfig
from src.feature_config import get_model_features, FEATURES_TO_LAG
from src.feature_preprocessor import FeaturePreprocessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("model_trainer.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ModelTrainer")

# Optional: Optuna for hyperparameter tuning
try:
    import optuna
    from optuna.samplers import TPESampler
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False
    logger.warning("Optuna not installed. Hyperparameter tuning disabled. Run: pip install optuna")


# =============================================================================
# STEP 1: SIMULATE TRADES (D1)
# =============================================================================
def simulate_trades(start_date: str, end_date: str, threshold: float = 15.0) -> pd.DataFrame:
    """
    Run SEPA trade simulation to generate labeled trade data (D1).
    
    Uses the FastTradeSimulator for vectorized performance.
    
    Returns:
        DataFrame with columns: [date, ticker, label, return_pct, days_held, exit_reason]
    """
    logger.info(f"Step 1: Simulating trades from {start_date} to {end_date}")
    
    # Calculate outcome window (trades can exit up to 90 days after end_date)
    # BUT cap it at latest available data (for recent backtests)
    from src.utils import get_latest_trading_day
    
    end_dt = pd.to_datetime(end_date)
    ideal_outcome_end = end_dt + timedelta(days=90)
    latest_available = get_latest_trading_day()
    
    # Use whichever is earlier: ideal window or latest available data
    outcome_end = min(ideal_outcome_end, latest_available).strftime('%Y-%m-%d')
    
    if ideal_outcome_end > latest_available:
        logger.warning(f"Outcome window capped at available data: {outcome_end} "
                      f"(ideal: {ideal_outcome_end.strftime('%Y-%m-%d')})")
        logger.warning(f"Recent trades may not have exit outcomes yet")
    
    # Initialize components
    data_repo = DataRepository()
    # Use HISTORICAL mode: only validates date range, does NOT check for latest trading day
    benchmark_data = data_repo.get_benchmark_data(
        mode=CacheMode.HISTORICAL,
        date_range=(start_date, outcome_end)
    )
    
    if benchmark_data is None:
        raise RuntimeError("Failed to load benchmark (SPY) data. Ensure SPY cache covers the date range.")
    
    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    strategy = SEPAStrategy(benchmark_data=benchmark_data)
    trading_config = TradingConfig(success_threshold_pct=threshold)
    
    # Use Fast (Vectorized) Simulator
    from src.trade_simulator_fast import FastTradeSimulator
    
    simulator = FastTradeSimulator(
        data_repo=data_repo,
        strategy=strategy,
        feature_engine=feature_engine,
        start_date=start_date,
        end_date=end_date,
        outcome_end=outcome_end,
        config=trading_config
    )
    
    # Run simulation with all CPUs
    d1 = simulator.run_simulation(show_progress=True, n_jobs=-1)
    
    # Standardize column names
    d1 = d1.rename(columns={'entry_date': 'date'})
    d1['date'] = pd.to_datetime(d1['date'])
    
    logger.info(f"   Generated {len(d1)} trades ({d1['label'].sum()} wins, {len(d1) - d1['label'].sum()} losses)")
    return d1


# =============================================================================
# STEP 2: ENRICH WITH FEATURES (D2) - OPTIMIZED PER-TICKER
# =============================================================================
def enrich_with_features(d1: pd.DataFrame, n_jobs: int = -1) -> pd.DataFrame:
    """
    For each trade in D1, extract features at the entry date (D2).
    
    OPTIMIZED: Precomputes features per ticker (not per trade) for 5-10x speedup.
    - Technical + Fundamental features computed once per ticker
    - Trade dates just lookup their row from precomputed data
    
    Args:
        d1: DataFrame from simulate_trades()
        n_jobs: Number of parallel workers (-1 = all CPUs)
    
    Returns:
        DataFrame with trade info + features.
    """
    from joblib import Parallel, delayed
    from tqdm import tqdm
    from src.fundamental_merger import FundamentalMerger
    
    logger.info(f"Step 2: Extracting features for {len(d1)} trades")
    
    # Suppress verbose logging during processing
    logging.getLogger('src.features').setLevel(logging.WARNING)
    logging.getLogger('src.indicators').setLevel(logging.WARNING)
    logging.getLogger('src.fundamental_merger').setLevel(logging.WARNING)
    
    # =========================================================================
    # PHASE 1: Pre-load price data for all tickers (fast I/O)
    # =========================================================================
    data_repo = DataRepository()
    tickers = d1['ticker'].unique().tolist()
    
    logger.info(f"   Phase 1: Loading price data for {len(tickers)} tickers...")
    price_cache = {}
    failed_tickers = []
    
    for ticker in tqdm(tickers, desc="Loading prices", unit="ticker"):
        try:
            df = data_repo.get_ticker_data(ticker, mode=CacheMode.CACHE_ONLY)
            if df is not None and not df.empty:
                price_cache[ticker] = df
            else:
                failed_tickers.append(ticker)
        except Exception as e:
            logger.debug(f"Failed to load {ticker}: {e}")
            failed_tickers.append(ticker)
    
    if failed_tickers:
        logger.warning(f"   Failed to load {len(failed_tickers)}/{len(tickers)} tickers")
    
    logger.info(f"   Loaded {len(price_cache)}/{len(tickers)} tickers")
    
    # Get benchmark data for RS calculation
    benchmark_data = data_repo.get_benchmark_data(mode=CacheMode.CACHE_ONLY)
    
    # =========================================================================
    # PHASE 2: Compute features per ticker IN PARALLEL (uses all CPUs)
    # This is the KEY OPTIMIZATION: parallelized + fundamentals merged once per ticker
    # =========================================================================
    logger.info(f"   Phase 2: Computing features for {len(price_cache)} tickers (parallel, n_jobs={n_jobs})...")
    
    def _compute_ticker_features(ticker: str, df: pd.DataFrame, benchmark_data: pd.Series) -> tuple:
        """Worker function for parallel feature computation."""
        try:
            # Calculate technical features
            feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
            df_features = feature_engine.calculate_lightweight_features(df)
            
            # Calculate alpha factors (heavyweight features)
            try:
                df_features = feature_engine.calculate_heavyweight_features(df_features, ticker)
            except Exception as e:
                logger.debug(f"Alpha calculation failed for {ticker}: {str(e)[:100]}")
                # Continue without alpha features
            
            # Merge fundamental features
            try:
                fundamental_merger = FundamentalMerger(force_cache_only=True)
                df_enriched = fundamental_merger.merge_ticker_data(ticker, df_features)
            except Exception as e:
                logger.warning(f"Fundamental merge failed for {ticker}: {str(e)[:100]}")
                df_enriched = df_features  # Fall back to technical-only
            
            return ticker, df_enriched, None
        except Exception as e:
            return ticker, None, str(e)
    
    # Run Phase 2 in parallel using all CPUs
    results = Parallel(n_jobs=n_jobs, prefer="processes")(
        delayed(_compute_ticker_features)(ticker, df, benchmark_data)
        for ticker, df in tqdm(price_cache.items(), desc="Computing features", unit="ticker")
    )
    
    # Collect results
    enriched_cache = {}
    failed_enrichment = []
    for ticker, df_enriched, error in results:
        if error:
            failed_enrichment.append(ticker)
        elif df_enriched is not None:
            enriched_cache[ticker] = df_enriched
    
    if failed_enrichment:
        logger.warning(f"   Feature computation failed for {len(failed_enrichment)} tickers")
    
    logger.info(f"   Computed features for {len(enriched_cache)} tickers")
    
    # Check fundamental merge success rate
    if enriched_cache:
        # Sample checking: see if fundamentals are present
        sample_ticker = list(enriched_cache.keys())[0]
        sample_cols = enriched_cache[sample_ticker].columns
        has_fundamentals = any(col in sample_cols for col in ['eps_growth_yoy', 'revenue_growth_yoy', 'pe_ratio'])
        has_alphas = any(col in sample_cols for col in ['alpha_001', 'alpha_002'])
        
        if has_fundamentals:
            logger.info(f"   ✅ Fundamental features detected in enriched data")
        else:
            logger.warning(f"   ⚠️  Fundamental features MISSING - check fundamental cache availability")
        
        if has_alphas:
            logger.info(f"   ✅ Alpha features detected in enriched data")
        else:
            logger.info(f"   ℹ️  Alpha features not present (may be expected if not enabled)")
    
    # =========================================================================
    # PHASE 3: Extract row for each trade date (very fast - just dict lookups)
    # =========================================================================
    logger.info(f"   Phase 3: Extracting {len(d1)} trade rows...")
    
    results = []
    errors = {'not_in_cache': 0, 'date_not_found': 0, 'other': 0}
    
    for _, trade in tqdm(d1.iterrows(), desc="Extracting trades", unit="trade", total=len(d1)):
        ticker = trade['ticker']
        trade_date = pd.to_datetime(trade['date'])
        
        if ticker not in enriched_cache:
            errors['not_in_cache'] += 1
            continue
        
        df_enriched = enriched_cache[ticker]
        
        # Ensure index is DatetimeIndex (might be RangeIndex after fundamental merge)
        if not isinstance(df_enriched.index, pd.DatetimeIndex):
            if 'date' in df_enriched.columns:
                df_enriched = df_enriched.set_index('date')
            else:
                errors['other'] += 1
                continue
        
        # Find the row for trade date
        if trade_date in df_enriched.index:
            row = df_enriched.loc[trade_date].to_dict()
        else:
            # Find closest date on or before trade date
            available = df_enriched.index[df_enriched.index <= trade_date]
            if len(available) == 0:
                errors['date_not_found'] += 1
                continue
            closest_date = available[-1]
            if (trade_date - closest_date).days > 7:
                errors['date_not_found'] += 1
                continue
            row = df_enriched.loc[closest_date].to_dict()
        
        # Add trade identifiers
        row['date'] = trade['date']
        row['ticker'] = ticker
        results.append(row)
    
    if any(errors.values()):
        logger.warning(f"   Errors: {errors}")
    
    logger.info(f"   Successfully extracted features for {len(results)}/{len(d1)} trades")
    
    if not results:
        raise RuntimeError("No features extracted. Check data availability.")
    
    # Convert to DataFrame
    d2 = pd.DataFrame(results)
    
    # Merge with D1 labels
    d1_keys = d1[['date', 'ticker', 'label', 'return_pct', 'days_held', 'exit_reason']]
    merged = pd.merge(d1_keys, d2, on=['date', 'ticker'], how='inner')
    
    logger.info(f"   Final merged dataset: {len(merged)} rows")
    return merged


# =============================================================================
# DATA CLEANING
# =============================================================================
def clean_training_data(data: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
    """
    Clean training data for XGBoost.

    Steps:
    1. Replace inf values with NaN
    2. Fill NaN with 0 (XGBoost handles this well)

    NOTE: We do NOT clip values. XGBoost is a tree-based model that naturally
    handles outliers by isolating them into their own leaf nodes when they are
    statistically significant. Clipping destroys signal from legitimately large values.

    Args:
        data: Training DataFrame
        feature_cols: List of feature column names

    Returns:
        Cleaned DataFrame
    """
    logger.info(f"   Cleaning training data")

    # Replace inf
    inf_count_before = data[feature_cols].isin([np.inf, -np.inf]).sum().sum()
    if inf_count_before > 0:
        logger.warning(f"   Found {inf_count_before} inf values, replacing with NaN")

    data[feature_cols] = data[feature_cols].replace([np.inf, -np.inf], np.nan)

    # Fill NaN
    nan_count = data[feature_cols].isna().sum().sum()
    if nan_count > 0:
        logger.info(f"   Filling {nan_count} NaN values with 0")
    data[feature_cols] = data[feature_cols].fillna(0)

    return data


# =============================================================================
# DECILE ANALYSIS
# =============================================================================
def analyze_deciles(y_true: pd.Series, y_pred: np.ndarray, n_deciles: int = 10) -> Dict:
    """
    Analyze model predictions by decile.

    This is THE critical diagnostic for trading models - shows if the model
    can actually rank trade quality.

    Args:
        y_true: Actual returns (or labels)
        y_pred: Predicted returns (or probabilities)
        n_deciles: Number of buckets (default: 10)

    Returns:
        Dict with decile stats
    """
    df = pd.DataFrame({
        'actual': y_true.values,
        'predicted': y_pred
    })

    # Create deciles (0 = worst, 9 = best)
    try:
        df['decile'] = pd.qcut(df['predicted'], n_deciles, labels=False, duplicates='drop')
    except ValueError:
        # If not enough unique values, use fewer deciles
        df['decile'] = pd.qcut(df['predicted'], min(5, n_deciles), labels=False, duplicates='drop')

    # Calculate stats per decile
    decile_stats = df.groupby('decile').agg({
        'actual': ['mean', 'std', 'count'],
        'predicted': 'mean'
    }).round(2)

    # Calculate overall stats
    overall_mean = df['actual'].mean()
    top_decile_mean = df[df['decile'] == df['decile'].max()]['actual'].mean()
    top_2_deciles_mean = df[df['decile'] >= df['decile'].max() - 1]['actual'].mean()

    selection_edge = top_decile_mean - overall_mean
    top2_edge = top_2_deciles_mean - overall_mean

    return {
        'decile_table': decile_stats,
        'overall_mean': overall_mean,
        'top_decile_mean': top_decile_mean,
        'top_2_deciles_mean': top_2_deciles_mean,
        'selection_edge': selection_edge,
        'top2_edge': top2_edge
    }


def print_decile_analysis(decile_results: Dict, metric_name: str = "Return"):
    """
    Pretty print decile analysis results.

    Args:
        decile_results: Output from analyze_deciles()
        metric_name: Name of metric being analyzed (e.g., "Return", "Label")
    """
    print("\n" + "=" * 70)
    print(f"DECILE ANALYSIS ({metric_name})")
    print("=" * 70)

    table = decile_results['decile_table']
    print("\nDecile | Avg {:<10} | Std Dev | Count".format(metric_name))
    print("-" * 70)

    for decile in sorted(table.index):
        avg = table.loc[decile, ('actual', 'mean')]
        std = table.loc[decile, ('actual', 'std')]
        count = int(table.loc[decile, ('actual', 'count')])
        print(f"   {decile}   | {avg:>7.2f}%      | {std:>6.2f}  | {count:>5}")

    print("-" * 70)
    print(f"Overall| {decile_results['overall_mean']:>7.2f}%")
    print("=" * 70)

    print(f"\nSELECTION EDGE:")
    print(f"   Top Decile - Avg:         {decile_results['selection_edge']:>+6.2f}%")
    print(f"   Top 2 Deciles - Avg:      {decile_results['top2_edge']:>+6.2f}%")
    print(f"   Top Decile Mean:          {decile_results['top_decile_mean']:>7.2f}%")
    print("=" * 70 + "\n")


# =============================================================================
# STEP 2.5: HYPERPARAMETER TUNING (OPTUNA)
# =============================================================================
def tune_hyperparameters_optuna(X: pd.DataFrame, y: pd.Series,
                                model_type: str = 'regression',
                                n_trials: int = 50,
                                n_splits: int = 5,
                                random_state: int = 42) -> Dict:
    """
    Tune XGBoost hyperparameters using Optuna with TimeSeriesSplit.

    Uses Bayesian optimization (TPE sampler) to efficiently search
    hyperparameter space with time-series aware cross-validation.

    Args:
        X: Feature matrix
        y: Target variable (return_pct or label)
        model_type: 'regression' or 'classification'
        n_trials: Number of optimization trials (default: 50)
        n_splits: Number of time series CV splits (default: 5)
        random_state: Random seed for reproducibility

    Returns:
        Dict of best parameters found
    """
    if not OPTUNA_AVAILABLE:
        logger.warning("Optuna not available, returning default parameters")
        return {}

    import xgboost as xgb
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import mean_squared_error, roc_auc_score

    logger.info(f"Starting Optuna hyperparameter tuning ({n_trials} trials, {n_splits} CV splits)...")
    logger.info(f"   Search space: n_estimators, max_depth, learning_rate, subsample, colsample_bytree, reg_alpha, reg_lambda")

    def objective(trial):
        """Optuna objective function for single trial."""
        # Define search space
        param = {
            'n_estimators': trial.suggest_int('n_estimators', 100, 500, step=50),
            'max_depth': trial.suggest_int('max_depth', 3, 7),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1, log=True),
            'subsample': trial.suggest_float('subsample', 0.6, 0.95),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 0.95),
            'reg_alpha': trial.suggest_float('reg_alpha', 0.1, 10.0, log=True),  # L1
            'reg_lambda': trial.suggest_float('reg_lambda', 0.1, 10.0, log=True),  # L2
            'n_jobs': -1,
            'random_state': random_state,
            'verbosity': 0
        }

        if model_type == 'regression':
            param['objective'] = 'reg:squarederror'
        else:
            param['objective'] = 'binary:logistic'

        # Time Series Cross-Validation
        tscv = TimeSeriesSplit(n_splits=n_splits)
        scores = []

        for train_idx, val_idx in tscv.split(X):
            X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
            y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

            if model_type == 'regression':
                model = xgb.XGBRegressor(**param)
                model.fit(X_train, y_train, verbose=False)
                preds = model.predict(X_val)
                rmse = np.sqrt(mean_squared_error(y_val, preds))
                scores.append(rmse)
            else:
                model = xgb.XGBClassifier(**param)
                model.fit(X_train, y_train, verbose=False)
                probs = model.predict_proba(X_val)[:, 1]
                # Handle edge case: if only one class in validation set
                if len(y_val.unique()) > 1:
                    auc = roc_auc_score(y_val, probs)
                    scores.append(1 - auc)  # Minimize (1 - AUC)
                else:
                    scores.append(0.5)  # Neutral score if only one class

        return np.mean(scores)

    # Run optimization with progress bar
    optuna.logging.set_verbosity(optuna.logging.WARNING)  # Reduce console noise
    study = optuna.create_study(
        direction='minimize',
        sampler=TPESampler(seed=random_state)
    )

    # Show progress
    print("\n" + "=" * 70)
    print("OPTUNA HYPERPARAMETER OPTIMIZATION")
    print("=" * 70)
    print(f"   Trials: {n_trials}")
    print(f"   CV Splits: {n_splits}")
    print(f"   Metric: {'RMSE' if model_type == 'regression' else '1 - AUC'}")
    print("=" * 70 + "\n")

    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    # Extract best parameters
    best_params = study.best_trial.params

    print("\n" + "=" * 70)
    print("OPTIMIZATION RESULTS")
    print("=" * 70)
    print(f"   Best CV Score: {study.best_trial.value:.4f}")
    print(f"\n   Best Parameters:")
    for k, v in best_params.items():
        if isinstance(v, float):
            print(f"     {k:<20} = {v:.4f}")
        else:
            print(f"     {k:<20} = {v}")
    print("=" * 70 + "\n")

    logger.info(f"Optuna optimization complete - Best CV score: {study.best_trial.value:.4f}")

    return best_params


# =============================================================================
# STEP 3: TRAIN MODEL (WALK-FORWARD)
# =============================================================================
def calculate_y_max_from_rehydrated(d2_features: pd.DataFrame, 
                                     d2r_path: str = 'data/ml/d2_rehydrated.parquet') -> pd.DataFrame:
    """
    Calculate y_max (Maximum Favorable Excursion) for each trade from rehydrated data.
    
    y_max = max return achievable during the trade (peak - entry) / entry * 100
    Also calculates regret = y_max - return_pct (profit left on table)
    
    Args:
        d2_features: D2 features DataFrame with trade entries
        d2r_path: Path to D2 rehydrated parquet file
        
    Returns:
        DataFrame with y_max and regret columns added
    """
    d2r_file = Path(d2r_path)
    if not d2r_file.exists():
        logger.warning(f"D2 rehydrated file not found: {d2r_path}")
        logger.warning("Cannot calculate y_max. Run --steps d2r first.")
        return d2_features
    
    logger.info(f"Calculating y_max from {d2r_path}...")
    d2_rehydrated = pd.read_parquet(d2r_path)
    
    # Calculate y_max per trade
    y_max_results = []
    
    for trade_id, group in d2_rehydrated.groupby('trade_id'):
        # Entry is day 0
        if 'day_in_trade' in group.columns:
            entry_rows = group[group['day_in_trade'] == 0]
        else:
            entry_rows = group.iloc[:1]
            
        if len(entry_rows) == 0:
            continue
            
        entry_price = entry_rows['Close'].iloc[0]
        if entry_price <= 0:
            continue
            
        # y_max = MFE (max return from entry to peak)
        highest = group['High'].max()
        y_max = ((highest - entry_price) / entry_price) * 100
        
        # Get ticker and date for merge
        ticker = group['ticker'].iloc[0] if 'ticker' in group.columns else None
        date = entry_rows['Date'].iloc[0] if 'Date' in entry_rows.columns else None
        
        y_max_results.append({
            'trade_id': trade_id,
            'ticker': ticker,
            'date': pd.to_datetime(date).normalize() if date is not None else None,
            'y_max': y_max
        })
    
    y_max_df = pd.DataFrame(y_max_results)
    logger.info(f"   Calculated y_max for {len(y_max_df)} trades (mean: {y_max_df['y_max'].mean():.2f}%)")
    
    # Merge y_max back to d2_features
    d2_features = d2_features.copy()
    d2_features['date'] = pd.to_datetime(d2_features['date']).dt.normalize()
    
    # Merge on both ticker and date for accuracy
    merged = pd.merge(
        d2_features,
        y_max_df[['ticker', 'date', 'y_max']],
        on=['ticker', 'date'],
        how='left'
    )
    
    # Calculate regret (profit left on table)
    if 'return_pct' in merged.columns:
        merged['regret'] = merged['y_max'] - merged['return_pct']
    
    missing_y_max = merged['y_max'].isna().sum()
    if missing_y_max > 0:
        logger.warning(f"   {missing_y_max} trades missing y_max (no matching rehydrated data)")
        # Fill with return_pct as fallback
        merged['y_max'] = merged['y_max'].fillna(merged['return_pct'])
        merged['regret'] = merged['regret'].fillna(0)
    
    return merged


def enrich_d2_with_survivor_labels(d2_features: pd.DataFrame,
                                    d2r_path: str = 'data/ml/d2_rehydrated.parquet',
                                    stop_multiplier: float = 2.0) -> pd.DataFrame:
    """
    Enrich d2_features with survivor model labels (y_max, MAE, MFE, is_survivor).

    Survivor Model Concept:
    - structural_stop = -K × nATR (where K = stop_multiplier, default 2.0)
    - Survivor: MAE > structural_stop (didn't hit stop)
    - Crashed: MAE <= structural_stop (hit stop)
    - y_max = MFE (for survivors), MAE (for crashed)

    Args:
        d2_features: D2 features DataFrame
        d2r_path: Path to D2 rehydrated parquet file
        stop_multiplier: Multiplier for structural stop (default: 2.0)

    Returns:
        DataFrame with added columns: y_max, MAE, MFE, structural_stop, is_survivor
    """
    d2r_file = Path(d2r_path)
    if not d2r_file.exists():
        logger.warning(f"D2 rehydrated file not found: {d2r_path}")
        logger.warning("Cannot calculate survivor labels. Run --steps d2rh first.")
        return d2_features

    logger.info(f"Calculating survivor labels from {d2r_path}...")
    logger.info(f"   Structural stop: -{stop_multiplier}×ATR")

    d2_rehydrated = pd.read_parquet(d2r_path)

    # Add day_in_trade if missing
    if 'day_in_trade' not in d2_rehydrated.columns:
        logger.info("   Adding day_in_trade to rehydrated data...")
        from src import eda_utils
        d2_rehydrated = eda_utils.add_trade_sequence(d2_rehydrated, date_col='Date')

    # Calculate MAE, MFE, and nATR for each trade
    results = []

    for trade_id, group in d2_rehydrated.groupby('trade_id'):
        # Entry is day 0
        entry_rows = group[group['day_in_trade'] == 0]
        if len(entry_rows) == 0:
            continue

        entry_price = entry_rows['Close'].iloc[0]
        if entry_price <= 0:
            continue

        # Get nATR from entry day
        if 'nATR' in entry_rows.columns:
            natr = entry_rows['nATR'].iloc[0]
        else:
            logger.warning(f"   nATR not found for trade {trade_id}, using default 5.0")
            natr = 5.0

        # Calculate MFE (Max Favorable Excursion)
        highest = group['High'].max()
        mfe = ((highest - entry_price) / entry_price) * 100

        # Calculate MAE (Max Adverse Excursion)
        lowest = group['Low'].min()
        mae = ((lowest - entry_price) / entry_price) * 100

        # Structural stop threshold
        structural_stop = -stop_multiplier * natr

        # Determine survivor status
        is_survivor = mae > structural_stop

        # y_max for training
        y_max = mfe if is_survivor else mae

        # Get ticker and date for merge
        ticker = group['ticker'].iloc[0] if 'ticker' in group.columns else None
        date = entry_rows['Date'].iloc[0] if 'Date' in entry_rows.columns else None

        results.append({
            'trade_id': trade_id,
            'ticker': ticker,
            'date': pd.to_datetime(date).normalize() if date is not None else None,
            'MFE': mfe,
            'MAE': mae,
            'nATR': natr,
            'structural_stop': structural_stop,
            'is_survivor': is_survivor,
            'y_max': y_max
        })

    results_df = pd.DataFrame(results)

    # Calculate statistics
    n_total = len(results_df)
    n_crashed = (~results_df['is_survivor']).sum()
    n_survived = results_df['is_survivor'].sum()
    crash_rate = n_crashed / n_total if n_total > 0 else 0

    logger.info(f"   Total trades: {n_total}")
    logger.info(f"   🔴 Crashed: {n_crashed} ({crash_rate:.1%})")
    logger.info(f"   🟢 Survived: {n_survived} ({(1-crash_rate):.1%})")

    crashed_mean = results_df[~results_df['is_survivor']]['y_max'].mean()
    survived_mean = results_df[results_df['is_survivor']]['y_max'].mean()
    logger.info(f"   Mean y_max (crashed): {crashed_mean:.2f}%")
    logger.info(f"   Mean y_max (survived): {survived_mean:.2f}%")

    # Merge back to d2_features
    d2_features = d2_features.copy()
    d2_features['date'] = pd.to_datetime(d2_features['date']).dt.normalize()

    merged = pd.merge(
        d2_features,
        results_df[['ticker', 'date', 'MFE', 'MAE', 'structural_stop', 'is_survivor', 'y_max']],
        on=['ticker', 'date'],
        how='left'
    )

    # Calculate regret
    if 'return_pct' in merged.columns:
        merged['regret'] = merged['MFE'] - merged['return_pct']

    missing = merged['y_max'].isna().sum()
    if missing > 0:
        logger.warning(f"   {missing} trades missing survivor labels (no matching rehydrated data)")
        # Fill with return_pct as fallback
        merged['y_max'] = merged['y_max'].fillna(merged['return_pct'])
        merged['is_survivor'] = merged['is_survivor'].fillna(True)  # Assume survivors if missing

    return merged


def train_model_walk_forward(data: pd.DataFrame,
                              model_type: str = 'regression',
                              tune: bool = False,
                              tune_trials: int = 50,
                              train_years: int = 3,
                              test_years: int = 1,
                              target: str = 'return_pct',
                              survivor_model: bool = False,
                              survivor_stop_multiplier: float = 2.0) -> Tuple:
    """
    Train XGBoost using Walk-Forward validation.

    Strategy:
      Fold 1: Train [2015-2017], Test [2018]
      Fold 2: Train [2016-2018], Test [2019]
      ...

    Args:
        data: Merged D1+D2 DataFrame.
        model_type: 'regression' or 'classification'
        tune: Whether to run Optuna hyperparameter tuning
        tune_trials: Number of Optuna trials
        train_years: Size of training window.
        test_years: Size of test window.
        target: Target column to train on: 'return_pct', 'y_max', or 'label'
        survivor_model: Enable Survivor Model (train only on survivors)
        survivor_stop_multiplier: Structural stop multiplier for survivor filtering

    Returns:
        Tuple of (trained_model, feature_columns, metrics_dict)
    """
    import xgboost as xgb
    from sklearn.metrics import accuracy_score, precision_score, roc_auc_score
    
    logger.info("Step 3: Training Model (Walk-Forward Validation)")
    
    # Get model features from centralized config
    model_feature_cols = get_model_features('M01')
    
    # Filter to only available features
    available_cols = [c for c in model_feature_cols if c in data.columns]
    missing_cols = [c for c in model_feature_cols if c not in data.columns]
    
    if missing_cols:
        logger.warning(f"   Missing {len(missing_cols)} features: {missing_cols[:5]}...")
    
    logger.info(f"   Using {len(available_cols)} features for training")
    logger.info(f"   Model type: {model_type}")
    logger.info(f"   Target: {target}")

    # Prepare data
    data = data.sort_values('date')
    data['year'] = data['date'].dt.year

    # Clean training data
    data = clean_training_data(data, available_cols)

    # Fit/Transform preprocessing (fat-tail handling)
    # Fit on full training data, save config for inference
    preprocessor = FeaturePreprocessor()
    preprocessor.fit(data, available_cols, target='return_pct')
    data = preprocessor.transform(data)
    
    # Update feature list with transformed names (log_ prefix for log-transformed features)
    available_cols = preprocessor.get_transformed_feature_names(available_cols)
    
    # Save preprocessing config for inference
    preprocessor.save('models/preprocessing_config.json')
    logger.info(f"   Saved preprocessing config (use at inference time)")

    years = sorted(data['year'].unique())

    # Determine target column based on target parameter
    # Override model_type based on target to ensure consistency
    if target == 'label':
        target_col = 'label'
        model_type = 'classification'
    elif target == 'y_max':
        target_col = 'y_max'
        if target_col not in data.columns:
            logger.info("   y_max not in data, calculating from D2 rehydrated...")
            data = calculate_y_max_from_rehydrated(data)
        model_type = 'regression'
    else:  # return_pct (default)
        target_col = 'return_pct'
        # model_type remains as specified

    # SURVIVOR MODEL: Enrich with survivor labels and filter
    if survivor_model:
        logger.info("=" * 70)
        logger.info("SURVIVOR MODEL ENABLED")
        logger.info("=" * 70)

        # Calculate survivor labels if not already present
        if 'is_survivor' not in data.columns:
            logger.info("   Enriching with survivor labels...")
            data = enrich_d2_with_survivor_labels(
                data,
                d2r_path='data/ml/d2_rehydrated.parquet',
                stop_multiplier=survivor_stop_multiplier
            )

        # Use y_max as target for survivor model
        if target != 'label':  # Don't override if classification
            target_col = 'y_max'
            logger.info(f"   Target overridden to: {target_col}")
            model_type = 'regression'

        # Filter: Train only on survivors
        n_before = len(data)
        data = data[data['is_survivor'] == True].copy()
        n_after = len(data)
        n_filtered = n_before - n_after

        logger.info(f"   Filtered {n_filtered} crashed trades ({n_filtered/n_before:.1%})")
        logger.info(f"   Training on {n_after} survivor trades")
        logger.info(f"   Expected prediction bias: Mean y_max ≈ {data[target_col].mean():.1f}%")
        logger.info("=" * 70)

    # Optuna tuning (optional, runs once on full dataset before walk-forward)
    best_params = {}
    if tune and OPTUNA_AVAILABLE:
        logger.info("Running hyperparameter tuning on full dataset...")
        X_tune = data[available_cols]
        y_tune = data[target_col]
        best_params = tune_hyperparameters_optuna(
            X_tune, y_tune,
            model_type=model_type,
            n_trials=tune_trials,
            n_splits=5,
            random_state=42
        )
    elif tune and not OPTUNA_AVAILABLE:
        logger.warning("Tuning requested but Optuna not available. Using default parameters.")

    # Walk-forward folds
    all_metrics = []
    final_model = None

    for i, test_year in enumerate(years[train_years:]):
        train_years_range = years[i:i+train_years]

        train_data = data[data['year'].isin(train_years_range)]
        test_data = data[data['year'] == test_year]

        if len(train_data) < 50 or len(test_data) < 10:
            logger.warning(f"   Skipping fold for {test_year} (insufficient data)")
            continue

        X_train = train_data[available_cols]
        y_train = train_data[target_col]
        X_test = test_data[available_cols]
        y_test = test_data[target_col]

        # Train model with tuned or default parameters
        if model_type == 'regression':
            if best_params:
                # Use tuned parameters
                model = xgb.XGBRegressor(
                    objective='reg:squarederror',
                    n_jobs=-1,
                    random_state=42,
                    **best_params
                )
            else:
                # Use default parameters
                model = xgb.XGBRegressor(
                    objective='reg:squarederror',
                    n_estimators=300,
                    learning_rate=0.03,
                    max_depth=4,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    reg_alpha=5.0,  # L1 regularization
                    reg_lambda=3.0,  # L2 regularization
                    random_state=42,
                    n_jobs=-1
            )
        else:  # classification
            if best_params:
                # Use tuned parameters
                model = xgb.XGBClassifier(
                    n_jobs=-1,
                    random_state=42,
                    eval_metric='logloss',
                    **best_params
                )
            else:
                # Use default parameters
                model = xgb.XGBClassifier(
                    n_estimators=500,
                    learning_rate=0.03,
                    max_depth=5,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    min_child_weight=3,
                    random_state=42,
                    n_jobs=-1,
                    eval_metric='logloss'
                )

        model.fit(X_train, y_train, verbose=False)

        # Evaluate
        preds = model.predict(X_test)

        if model_type == 'regression':
            # Regression metrics
            from sklearn.metrics import mean_squared_error, mean_absolute_error
            rmse = np.sqrt(mean_squared_error(y_test, preds))
            mae = mean_absolute_error(y_test, preds)

            # Decile analysis (THE critical metric for trading)
            fold_decile_results = analyze_deciles(y_test, preds)

            all_metrics.append({
                'test_year': test_year,
                'train_samples': len(train_data),
                'test_samples': len(test_data),
                'rmse': rmse,
                'mae': mae,
                'selection_edge': fold_decile_results['selection_edge'],
                'top_decile_mean': fold_decile_results['top_decile_mean'],
                'top2_edge': fold_decile_results['top2_edge']
            })

            logger.info(f"   Fold {i+1} (Test {test_year}): RMSE={rmse:.2f} Edge={fold_decile_results['selection_edge']:+.2f}%")

            # Print decile analysis for first and last fold
            if i == 0 or test_year == years[train_years:][-1]:
                print_decile_analysis(fold_decile_results, "Return%")

        else:  # classification
            probs = model.predict_proba(X_test)[:, 1]
            acc = accuracy_score(y_test, preds)
            prec = precision_score(y_test, preds, zero_division=0)
            auc = roc_auc_score(y_test, probs) if len(y_test.unique()) > 1 else 0.5

            # Decile analysis on probabilities
            fold_decile_results = analyze_deciles(y_test, probs)

            all_metrics.append({
                'test_year': test_year,
                'train_samples': len(train_data),
                'test_samples': len(test_data),
                'accuracy': acc,
                'precision': prec,
                'auc': auc,
                'selection_edge': fold_decile_results['selection_edge']
            })

            logger.info(f"   Fold {i+1} (Test {test_year}): Acc={acc:.2%} Prec={prec:.2%} AUC={auc:.3f}")

        final_model = model  # Keep last model
    
    # Summary
    if all_metrics:
        if model_type == 'regression':
            avg_rmse = np.mean([m['rmse'] for m in all_metrics])
            avg_edge = np.mean([m['selection_edge'] for m in all_metrics])
            avg_top_decile = np.mean([m['top_decile_mean'] for m in all_metrics])
            min_edge = min(m['selection_edge'] for m in all_metrics)
            max_edge = max(m['selection_edge'] for m in all_metrics)
            positive_edge_folds = sum(1 for m in all_metrics if m['selection_edge'] > 0)

            print("\n" + "=" * 70)
            print("WALK-FORWARD VALIDATION RESULTS (REGRESSION)")
            print("=" * 70)
            print(f"   Folds Completed:       {len(all_metrics)}")
            print(f"   Total Test Samples:    {sum(m['test_samples'] for m in all_metrics)}")
            print(f"   Average RMSE:          {avg_rmse:.2f}%")
            print(f"\nSELECTION EDGE (The Key Metric)")
            print(f"   Average Edge:          {avg_edge:>+6.2f}%")
            print(f"   Edge Range:            [{min_edge:+.2f}%, {max_edge:+.2f}%]")
            print(f"   Positive Edge Folds:   {positive_edge_folds} / {len(all_metrics)} ({positive_edge_folds/len(all_metrics)*100:.0f}%)")
            print(f"   Top Decile Avg Return: {avg_top_decile:>7.2f}%")
            print("=" * 70 + "\n")

        else:  # classification
            avg_acc = np.mean([m['accuracy'] for m in all_metrics])
            avg_prec = np.mean([m['precision'] for m in all_metrics])
            avg_auc = np.mean([m['auc'] for m in all_metrics])
            avg_edge = np.mean([m.get('selection_edge', 0) for m in all_metrics])

            print("\n" + "=" * 70)
            print("WALK-FORWARD VALIDATION RESULTS (CLASSIFICATION)")
            print("=" * 70)
            print(f"   Average Accuracy:      {avg_acc:.2%}")
            print(f"   Average Precision:     {avg_prec:.2%}")
            print(f"   Average AUC:           {avg_auc:.3f}")
            print(f"   Average Edge:          {avg_edge:>+6.2f}%")
            print("=" * 70 + "\n")

    return final_model, available_cols, all_metrics


# =============================================================================
# STEP 3.5: TRAIN M01_3BAR (TRIPLE BARRIER MODEL)
# =============================================================================
def train_triple_barrier_model(
    d3_path: str = 'data/ml/d3_triple_barrier_labels.parquet',
    tune: bool = False,
    tune_trials: int = 50,
    verbose: bool = True,
    feature_version: str = 'M01_3BAR'
) -> Tuple:
    """
    Train M01_3bar model using triple barrier labels.

    This function is nearly identical to train_model_walk_forward() but:
    - Loads D3 instead of D2
    - Uses 'y_meta' as target (triple barrier labels)
    - Always operates in classification mode
    - Adds scale_pos_weight for class imbalance (12% TP rate)
    - Uses 'return_at_outcome' for decile analysis

    Args:
        d3_path: Path to D3 dataset with triple barrier labels
        tune: Whether to run Optuna hyperparameter tuning
        tune_trials: Number of Optuna trials if tuning
        verbose: Print detailed progress
        feature_version: Feature set to use ('M01_3BAR' or 'M01_3BAR_V2')

    Returns:
        Tuple of (trained_model, feature_columns, metrics_dataframe)
    """
    import xgboost as xgb
    from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score

    logger.info("=" * 70)
    logger.info(f"TRAINING {feature_version} (TRIPLE BARRIER META-LABELING MODEL)")
    logger.info("=" * 70)

    # Load D3 dataset
    d3 = pd.read_parquet(d3_path)
    logger.info(f"Loaded D3: {len(d3):,} trades from {d3_path}")

    # Show label distribution
    y_meta_dist = d3['y_meta'].value_counts()
    logger.info(f"Label distribution:")
    logger.info(f"  y_meta=1 (TP):  {y_meta_dist.get(1, 0):,} ({y_meta_dist.get(1, 0)/len(d3)*100:.1f}%)")
    logger.info(f"  y_meta=0 (SL/Time): {y_meta_dist.get(0, 0):,} ({y_meta_dist.get(0, 0)/len(d3)*100:.1f}%)")

    # Show barrier outcome breakdown
    if 'barrier_outcome' in d3.columns:
        barrier_dist = d3['barrier_outcome'].value_counts()
        logger.info(f"Barrier outcomes:")
        for outcome, count in barrier_dist.items():
            logger.info(f"  {outcome}: {count:,} ({count/len(d3)*100:.1f}%)")

    # Get feature set (M01_3BAR or M01_3BAR_V2)
    model_features = get_model_features(feature_version)

    # Filter to available features
    available_cols = [c for c in model_features if c in d3.columns]
    missing_cols = [c for c in model_features if c not in d3.columns]

    if missing_cols:
        logger.warning(f"Missing {len(missing_cols)} features: {missing_cols[:5]}...")

    logger.info(f"Using {len(available_cols)}/{len(model_features)} {feature_version} features")

    # Prepare data for walk-forward
    data = d3.copy()
    data = data.sort_values('Date')
    data['year'] = pd.to_datetime(data['Date']).dt.year

    # Clean training data (reuse existing cleaner)
    data = clean_training_data(data, available_cols)

    years = sorted(data['year'].unique())
    logger.info(f"Years available: {years}")

    # Optuna tuning (if requested)
    best_params = {}
    if tune and OPTUNA_AVAILABLE:
        logger.info("Running hyperparameter tuning...")
        X_tune = data[available_cols]
        y_tune = data['y_meta']  # Triple barrier labels

        best_params = tune_hyperparameters_optuna(
            X_tune, y_tune,
            model_type='classification',  # Always classification for barriers
            n_trials=tune_trials,
            n_splits=5,
            random_state=42
        )
        logger.info(f"Best hyperparameters found: {best_params}")
    elif tune and not OPTUNA_AVAILABLE:
        logger.warning("Tuning requested but Optuna not available. Using default parameters.")

    # Walk-forward training (same structure as M01)
    all_metrics = []
    final_model = None
    train_years_count = 3  # Same as M01

    logger.info(f"\nStarting walk-forward validation ({train_years_count}-year train window)")

    for i, test_year in enumerate(years[train_years_count:]):
        train_years_range = years[i:i+train_years_count]

        train_data = data[data['year'].isin(train_years_range)]
        test_data = data[data['year'] == test_year]

        if len(train_data) < 50 or len(test_data) < 10:
            logger.warning(f"Skipping fold for {test_year} (insufficient data)")
            continue

        X_train = train_data[available_cols]
        y_train = train_data['y_meta']  # Triple barrier labels
        X_test = test_data[available_cols]
        y_test = test_data['y_meta']

        logger.info(f"\nFold {i+1}: Train {train_years_range} → Test [{test_year}]")
        logger.info(f"  Train: {len(X_train):,} trades")
        logger.info(f"  Test: {len(X_test):,} trades")

        # Calculate scale_pos_weight for class imbalance
        n_negative = (y_train == 0).sum()
        n_positive = (y_train == 1).sum()
        scale_pos_weight = n_negative / n_positive if n_positive > 0 else 1.0

        logger.info(f"  Train TP rate: {n_positive/(n_negative+n_positive)*100:.1f}% (scale_pos_weight={scale_pos_weight:.2f})")

        # Train XGBoost
        if best_params:
            model = xgb.XGBClassifier(
                **best_params,
                scale_pos_weight=scale_pos_weight,
                random_state=42,
                n_jobs=-1
            )
        else:
            # Default hyperparameters (same as M01 classification + scale_pos_weight)
            model = xgb.XGBClassifier(
                n_estimators=500,
                learning_rate=0.03,
                max_depth=5,
                subsample=0.8,
                colsample_bytree=0.8,
                min_child_weight=3,
                scale_pos_weight=scale_pos_weight,
                eval_metric='logloss',
                random_state=42,
                n_jobs=-1
            )

        model.fit(X_train, y_train, verbose=False)

        # Predictions
        y_pred_proba = model.predict_proba(X_test)[:, 1]
        y_pred = (y_pred_proba >= 0.5).astype(int)

        # Standard classification metrics
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)
        auc = roc_auc_score(y_test, y_pred_proba) if len(y_test.unique()) > 1 else 0.5

        # Decile analysis (KEY METRIC for trading)
        # Use return_at_outcome instead of return_pct
        if 'return_at_outcome' in test_data.columns:
            fold_decile_results = analyze_deciles(
                test_data['return_at_outcome'],
                y_pred_proba
            )
            selection_edge = fold_decile_results['selection_edge']
            top_decile_mean = fold_decile_results['top_decile_mean']
        else:
            logger.warning("  'return_at_outcome' not in D3 - using y_meta for decile analysis")
            fold_decile_results = analyze_deciles(y_test, y_pred_proba)
            selection_edge = fold_decile_results['selection_edge']
            top_decile_mean = fold_decile_results['top_decile_mean']

        logger.info(f"  Accuracy:  {accuracy:.3f}")
        logger.info(f"  Precision: {precision:.3f}")
        logger.info(f"  Recall:    {recall:.3f}")
        logger.info(f"  AUC:       {auc:.3f}")
        logger.info(f"  Top Decile Avg Return: {top_decile_mean:.2f}%")
        logger.info(f"  Selection Edge: {selection_edge:+.2f}%")

        all_metrics.append({
            'fold': i + 1,
            'test_year': test_year,
            'train_samples': len(train_data),
            'test_samples': len(test_data),
            'accuracy': accuracy,
            'precision': precision,
            'recall': recall,
            'auc': auc,
            'top_decile_mean': top_decile_mean,
            'selection_edge': selection_edge
        })

        final_model = model  # Keep last fold model

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info(" WALK-FORWARD RESULTS (M01_3BAR)")
    logger.info("=" * 70)

    if all_metrics:
        metrics_df = pd.DataFrame(all_metrics)
        print(metrics_df.to_string(index=False))

        avg_accuracy = metrics_df['accuracy'].mean()
        avg_precision = metrics_df['precision'].mean()
        avg_recall = metrics_df['recall'].mean()
        avg_auc = metrics_df['auc'].mean()
        avg_edge = metrics_df['selection_edge'].mean()
        avg_top_decile = metrics_df['top_decile_mean'].mean()

        print("\n" + "=" * 70)
        print("SUMMARY STATISTICS")
        print("=" * 70)
        print(f"   Folds Completed:          {len(all_metrics)}")
        print(f"   Average Accuracy:         {avg_accuracy:.3f}")
        print(f"   Average Precision:        {avg_precision:.3f}")
        print(f"   Average Recall:           {avg_recall:.3f}")
        print(f"   Average AUC:              {avg_auc:.3f}")
        print(f"   Average Selection Edge:   {avg_edge:+.2f}%")
        print(f"   Average Top Decile Mean:  {avg_top_decile:+.2f}%")
        print("=" * 70)

        # Viability assessment
        if avg_edge > 2.5 and avg_auc > 0.60:
            print("\n[SUCCESS] STRONG SIGNAL - Model shows consistent edge across folds")
        elif avg_edge > 1.5 and avg_auc > 0.55:
            print("\n[OK] MODERATE SIGNAL - Model has edge but may need refinement")
        else:
            print("\n[WARNING] WEAK SIGNAL - Consider adjusting barrier params or features")

        print("\n")

        return final_model, available_cols, metrics_df
    else:
        logger.error("No folds completed - check data availability")
        return None, available_cols, pd.DataFrame()


# =============================================================================
# STEP 4: SAVE PRODUCTION MODEL (M01)
# =============================================================================
def save_production_model(model, feature_cols: List[str], metrics: List[Dict]):
    """
    Save the trained model and its configuration.
    
    Artifacts:
      - models/model_m01.json (XGBoost Booster)
      - models/model_m01_config.json (Feature list, metrics)
    """
    import json
    
    output_dir = Path("models")
    output_dir.mkdir(exist_ok=True)
    
    # Save model
    model_path = output_dir / "model_m01.json"
    model.save_model(str(model_path))
    logger.info(f"Saved model to {model_path}")
    
    # Save config
    config_data = {
        'model_name': 'M01',
        'description': 'SEPA Signal Quality Model',
        'created_at': datetime.now().isoformat(),
        'feature_columns': feature_cols,
        'validation_metrics': metrics
    }
    
    config_path = output_dir / "model_m01_config.json"
    with open(config_path, 'w') as f:
        json.dump(config_data, f, indent=2, default=str)
    
    logger.info(f"Saved config to {config_path}")
    print(f"\n[SUCCESS] Production Model M01 saved to {output_dir}/")


# =============================================================================
# STEP 5: GENERATE MODEL REPORT
# =============================================================================
def save_feature_importance(model, feature_cols: List[str], output_dir: Path) -> pd.DataFrame:
    """
    Extract and save feature importance from trained XGBoost model.

    Args:
        model: Trained XGBoost model
        feature_cols: List of feature names
        output_dir: Directory to save CSV

    Returns:
        DataFrame with feature importance rankings
    """
    logger.info("Extracting feature importance...")

    # Get importance scores (gain = average gain across all splits)
    importance_dict = model.get_booster().get_score(importance_type='gain')

    # Create DataFrame
    importance_df = pd.DataFrame([
        {'feature': k, 'gain': v}
        for k, v in importance_dict.items()
    ]).sort_values('gain', ascending=False).reset_index(drop=True)

    # Add rank
    importance_df['rank'] = range(1, len(importance_df) + 1)

    # Calculate percentage contribution
    total_gain = importance_df['gain'].sum()
    importance_df['gain_pct'] = (importance_df['gain'] / total_gain * 100).round(2)
    importance_df['cumulative_pct'] = importance_df['gain_pct'].cumsum().round(2)

    # Reorder columns
    importance_df = importance_df[['rank', 'feature', 'gain', 'gain_pct', 'cumulative_pct']]

    # Save to CSV
    importance_path = output_dir / "feature_importance.csv"
    importance_df.to_csv(importance_path, index=False)

    logger.info(f"Saved feature importance to {importance_path}")

    # Print top 20
    print("\n" + "=" * 80)
    print("FEATURE IMPORTANCE - TOP 20 (by Gain)")
    print("=" * 80)
    print(f"{'Rank':<6} {'Feature':<30} {'Gain':>12} {'% Total':>10} {'Cumulative':>12}")
    print("-" * 80)

    for _, row in importance_df.head(20).iterrows():
        print(f"{int(row['rank']):<6} {row['feature']:<30} {row['gain']:>12.0f} {row['gain_pct']:>9.1f}% {row['cumulative_pct']:>11.1f}%")

    print("=" * 80)
    print(f"Total features used: {len(importance_df)} / {len(feature_cols)} available")
    print(f"Top 10 features contribute: {importance_df.head(10)['gain_pct'].sum():.1f}% of total gain")
    print(f"Top 20 features contribute: {importance_df.head(20)['gain_pct'].sum():.1f}% of total gain")
    print("=" * 80 + "\n")

    return importance_df


def generate_model_report(model, feature_cols: List[str], metrics: List[Dict],
                         model_type: str, importance_df: pd.DataFrame,
                         start_date: str, end_date: str) -> str:
    """
    Generate comprehensive markdown report for model training results.

    Args:
        model: Trained XGBoost model
        feature_cols: List of feature names
        metrics: List of fold metrics from walk-forward validation
        model_type: 'regression' or 'classification'
        importance_df: Feature importance DataFrame
        start_date: Training start date
        end_date: Training end date

    Returns:
        Path to saved report
    """
    from datetime import datetime

    output_dir = Path("models")
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"model_report_M01_{timestamp}.md"

    # Calculate summary statistics
    if model_type == 'regression':
        avg_rmse = np.mean([m['rmse'] for m in metrics])
        avg_edge = np.mean([m['selection_edge'] for m in metrics])
        avg_top_decile = np.mean([m['top_decile_mean'] for m in metrics])
        min_edge = min(m['selection_edge'] for m in metrics)
        max_edge = max(m['selection_edge'] for m in metrics)
        positive_edge_folds = sum(1 for m in metrics if m['selection_edge'] > 0)

        # Calculate edge consistency
        edge_std = np.std([m['selection_edge'] for m in metrics])
        edge_sharpe = avg_edge / edge_std if edge_std > 0 else 0
    else:
        avg_acc = np.mean([m['accuracy'] for m in metrics])
        avg_prec = np.mean([m['precision'] for m in metrics])
        avg_auc = np.mean([m['auc'] for m in metrics])
        avg_edge = np.mean([m.get('selection_edge', 0) for m in metrics])

    # Build report
    report_lines = []
    report_lines.append("# Model Training Report - M01 (SEPA Signal Quality Model)")
    report_lines.append("")
    report_lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"**Training Period:** {start_date} to {end_date}")
    report_lines.append(f"**Model Type:** {model_type.upper()}")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")

    # Executive Summary
    report_lines.append("## Executive Summary")
    report_lines.append("")

    if model_type == 'regression':
        viability = "VIABLE" if avg_edge > 1.5 else "MARGINAL" if avg_edge > 0.5 else "NOT VIABLE"
        report_lines.append(f"**Trading Viability:** {viability}")
        report_lines.append("")
        report_lines.append("### Key Metrics")
        report_lines.append("")
        report_lines.append(f"- **Selection Edge:** {avg_edge:+.2f}% (range: [{min_edge:+.2f}%, {max_edge:+.2f}%])")
        report_lines.append(f"- **Edge Consistency:** {positive_edge_folds}/{len(metrics)} folds positive ({positive_edge_folds/len(metrics)*100:.0f}%)")
        report_lines.append(f"- **Edge Sharpe Ratio:** {edge_sharpe:.2f} (higher = more consistent)")
        report_lines.append(f"- **Top Decile Return:** {avg_top_decile:.2f}%")
        report_lines.append(f"- **RMSE:** {avg_rmse:.2f}%")
        report_lines.append(f"- **Walk-Forward Folds:** {len(metrics)}")
        report_lines.append(f"- **Total Test Samples:** {sum(m['test_samples'] for m in metrics):,}")
        report_lines.append("")

        # Interpretation
        report_lines.append("### Interpretation")
        report_lines.append("")
        if avg_edge > 1.5:
            report_lines.append(f"The model demonstrates **strong predictive power** with a {avg_edge:+.2f}% selection edge. ")
            report_lines.append(f"This means trades ranked in the top decile (top 10%) outperform the average by {avg_edge:.2f}%. ")
            report_lines.append("After typical transaction costs (0.2-0.5%), this edge is **tradeable**.")
        elif avg_edge > 0.5:
            report_lines.append(f"The model shows **marginal predictive power** with a {avg_edge:+.2f}% selection edge. ")
            report_lines.append("This may be tradeable but requires careful cost management and execution.")
        else:
            report_lines.append(f"The model shows **weak predictive power** with a {avg_edge:+.2f}% selection edge. ")
            report_lines.append("Further optimization or feature engineering is recommended before deployment.")
        report_lines.append("")

        if positive_edge_folds == len(metrics):
            report_lines.append(f"**Consistency:** Excellent - positive edge in all {len(metrics)} folds indicates robust performance.")
        elif positive_edge_folds >= len(metrics) * 0.8:
            report_lines.append(f"**Consistency:** Good - positive edge in {positive_edge_folds}/{len(metrics)} folds.")
        else:
            report_lines.append(f"**Consistency:** Concerning - only {positive_edge_folds}/{len(metrics)} folds show positive edge.")
        report_lines.append("")

    else:  # classification
        report_lines.append("### Key Metrics")
        report_lines.append("")
        report_lines.append(f"- **Average Accuracy:** {avg_acc:.2%}")
        report_lines.append(f"- **Average Precision:** {avg_prec:.2%}")
        report_lines.append(f"- **Average AUC:** {avg_auc:.3f}")
        report_lines.append(f"- **Selection Edge:** {avg_edge:+.2f}%")
        report_lines.append(f"- **Walk-Forward Folds:** {len(metrics)}")
        report_lines.append("")

    report_lines.append("---")
    report_lines.append("")

    # Walk-Forward Results
    report_lines.append("## Walk-Forward Validation Results")
    report_lines.append("")
    report_lines.append("| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |")
    report_lines.append("|------|-----------|--------------|------|----------------|-----------------|")

    for i, m in enumerate(metrics, 1):
        if model_type == 'regression':
            report_lines.append(
                f"| {i} | {m.get('test_year', 'N/A')} | {m['test_samples']:,} | "
                f"{m['rmse']:.2f}% | {m['selection_edge']:+.2f}% | {m['top_decile_mean']:.2f}% |"
            )
        else:
            report_lines.append(
                f"| {i} | {m.get('test_year', 'N/A')} | {m['test_samples']:,} | "
                f"{m.get('accuracy', 0):.2%} | {m.get('selection_edge', 0):+.2f}% | N/A |"
            )

    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")

    # Feature Importance
    report_lines.append("## Feature Importance Analysis")
    report_lines.append("")
    report_lines.append(f"**Total Features:** {len(feature_cols)} available, {len(importance_df)} used by model")
    report_lines.append("")

    # Group features by type
    alpha_features = [f for f in importance_df['feature'].values if f.startswith('alpha')]
    fundamental_features = [f for f in importance_df['feature'].values
                           if any(x in f for x in ['eps', 'revenue', 'margin', 'pe_ratio', 'ps_ratio', 'roe', 'roa'])]
    technical_features = [f for f in importance_df['feature'].values
                         if f not in alpha_features and f not in fundamental_features]

    report_lines.append(f"- **Alpha Factors:** {len(alpha_features)} features")
    report_lines.append(f"- **Fundamental Features:** {len(fundamental_features)} features")
    report_lines.append(f"- **Technical Features:** {len(technical_features)} features")
    report_lines.append("")

    # Top 20 features
    report_lines.append("### Top 20 Features by Gain")
    report_lines.append("")
    report_lines.append("| Rank | Feature | Gain | % Total | Cumulative % |")
    report_lines.append("|------|---------|------|---------|--------------|")

    for _, row in importance_df.head(20).iterrows():
        report_lines.append(
            f"| {int(row['rank'])} | {row['feature']} | {row['gain']:.0f} | "
            f"{row['gain_pct']:.1f}% | {row['cumulative_pct']:.1f}% |"
        )

    report_lines.append("")

    # Feature insights
    report_lines.append("### Feature Insights")
    report_lines.append("")
    top_10_pct = importance_df.head(10)['gain_pct'].sum()
    top_20_pct = importance_df.head(20)['gain_pct'].sum()

    report_lines.append(f"- Top 10 features contribute **{top_10_pct:.1f}%** of total gain")
    report_lines.append(f"- Top 20 features contribute **{top_20_pct:.1f}%** of total gain")
    report_lines.append("")

    # Identify feature categories in top 10
    top_10_features = importance_df.head(10)['feature'].values
    top_10_alpha = sum(1 for f in top_10_features if f.startswith('alpha'))
    top_10_fundamental = sum(1 for f in top_10_features
                             if any(x in f for x in ['eps', 'revenue', 'margin', 'pe_ratio', 'roe', 'roa']))
    top_10_technical = 10 - top_10_alpha - top_10_fundamental

    report_lines.append("**Top 10 Feature Composition:**")
    report_lines.append(f"- Alpha factors: {top_10_alpha}/10")
    report_lines.append(f"- Fundamental: {top_10_fundamental}/10")
    report_lines.append(f"- Technical: {top_10_technical}/10")
    report_lines.append("")

    report_lines.append("---")
    report_lines.append("")

    # Model Configuration
    report_lines.append("## Model Configuration")
    report_lines.append("")
    report_lines.append("### XGBoost Parameters")
    report_lines.append("")
    report_lines.append("```python")

    if model_type == 'regression':
        report_lines.append("XGBRegressor(")
        report_lines.append("    objective='reg:squarederror',")
        report_lines.append("    n_estimators=300,")
        report_lines.append("    learning_rate=0.03,")
        report_lines.append("    max_depth=4,")
        report_lines.append("    subsample=0.8,")
        report_lines.append("    colsample_bytree=0.8,")
        report_lines.append("    reg_alpha=5.0,  # L1 regularization")
        report_lines.append("    reg_lambda=3.0,  # L2 regularization")
        report_lines.append("    random_state=42")
        report_lines.append(")")
    else:
        report_lines.append("XGBClassifier(")
        report_lines.append("    n_estimators=500,")
        report_lines.append("    learning_rate=0.03,")
        report_lines.append("    max_depth=5,")
        report_lines.append("    subsample=0.8,")
        report_lines.append("    colsample_bytree=0.8,")
        report_lines.append("    min_child_weight=3,")
        report_lines.append("    random_state=42")
        report_lines.append(")")

    report_lines.append("```")
    report_lines.append("")

    report_lines.append("### Validation Strategy")
    report_lines.append("")
    report_lines.append("- **Method:** Walk-Forward Validation")
    report_lines.append("- **Train Window:** 3 years")
    report_lines.append("- **Test Window:** 1 year")
    report_lines.append("- **Data Cleaning:** Replace inf with NaN, fill NaN with 0 (no clipping - XGBoost handles outliers naturally)")
    report_lines.append("")

    report_lines.append("---")
    report_lines.append("")

    # Recommendations
    report_lines.append("## Recommendations")
    report_lines.append("")

    if model_type == 'regression':
        if avg_edge > 2.0:
            report_lines.append("### Deployment")
            report_lines.append("")
            report_lines.append("- **Status:** Ready for conservative deployment")
            report_lines.append("- **Strategy:** Use top 2 deciles (top 20% predictions) for trade selection")
            report_lines.append(f"- **Expected Edge:** ~{avg_edge:.2f}% after costs")
            report_lines.append("- **Position Sizing:** Start with reduced size (50%) to verify live performance")
            report_lines.append("")
        elif avg_edge > 1.0:
            report_lines.append("### Optimization Recommended")
            report_lines.append("")
            report_lines.append("- Consider Optuna hyperparameter tuning (target: +10-20% improvement)")
            report_lines.append("- Review feature engineering - check correlation analysis")
            report_lines.append("- Test longer training period (5 years vs 3 years)")
            report_lines.append("- Paper trade for 1-2 months before live deployment")
            report_lines.append("")
        else:
            report_lines.append("### Further Development Needed")
            report_lines.append("")
            report_lines.append("- Edge too small for reliable trading")
            report_lines.append("- Recommend feature engineering improvements")
            report_lines.append("- Consider ensemble methods or alternative algorithms")
            report_lines.append("- Review data quality and labeling strategy")
            report_lines.append("")

        report_lines.append("### Next Steps")
        report_lines.append("")
        report_lines.append("1. Run Optuna hyperparameter tuning (`--tune --trials 50`)")
        report_lines.append("2. Analyze feature importance for redundant features")
        report_lines.append("3. Test on extended date range (2018-2025)")
        report_lines.append("4. Implement paper trading to validate out-of-sample performance")
        report_lines.append("5. Monitor edge degradation over time")

    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("*Report generated by model_trainer.py*")

    # Write report
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))

    logger.info(f"Saved model report to {report_path}")

    return str(report_path)


def generate_model_report_m01_3bar(
    model,
    metrics_df: pd.DataFrame,
    features: List[str],
    config: dict
):
    """Generate markdown report for M01_3bar model."""

    output_dir = Path("models")
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = output_dir / f'model_report_M01_3bar_{timestamp}.md'

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(f"# M01_3bar Model Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        # Executive Summary
        f.write("## Executive Summary\n\n")

        avg_edge = metrics_df['selection_edge'].mean()
        avg_auc = metrics_df['auc'].mean()
        avg_precision = metrics_df['precision'].mean()
        avg_recall = metrics_df['recall'].mean()
        avg_accuracy = metrics_df['accuracy'].mean()

        f.write(f"- **Average Selection Edge:** {avg_edge:.2f}%\n")
        f.write(f"- **Average AUC:** {avg_auc:.3f}\n")
        f.write(f"- **Average Precision:** {avg_precision:.3f}\n")
        f.write(f"- **Average Recall:** {avg_recall:.3f}\n")
        f.write(f"- **Average Accuracy:** {avg_accuracy:.3f}\n")
        f.write(f"- **Barrier Type:** Hybrid (ATR-based)\n")
        f.write(f"- **Barrier Params:** k_sl={config['barrier_params']['k_sl']}, ")
        f.write(f"k_tp={config['barrier_params']['k_tp']}, ")
        f.write(f"min_tp={config['barrier_params']['min_tp']}\n\n")

        # Viability Assessment
        f.write("## Viability Assessment\n\n")
        if avg_edge > 2.5 and avg_auc > 0.60:
            f.write("**STRONG SIGNAL** - Model shows consistent edge across folds.\n\n")
            f.write("The model demonstrates strong predictive power for identifying trades that hit profit targets before stop-losses. ")
            f.write(f"With a {avg_edge:.2f}% selection edge and {avg_auc:.3f} AUC, this model is ready for live testing.\n\n")
        elif avg_edge > 1.5 and avg_auc > 0.55:
            f.write("**MODERATE SIGNAL** - Model has edge but may need refinement.\n\n")
            f.write(f"The model shows {avg_edge:.2f}% selection edge with {avg_auc:.3f} AUC. ")
            f.write("Consider combining with M01 in an ensemble or using stricter thresholds (score > 0.7).\n\n")
        else:
            f.write("**WEAK SIGNAL** - Model edge is marginal. Consider:\n")
            f.write("- Adjusting barrier parameters (run grid search again)\n")
            f.write("- Adding barrier-specific features (e.g., volatility_regime, sector_tp_rate)\n")
            f.write("- Ensemble with M01 predictions\n")
            f.write("- Increasing training data or tuning hyperparameters\n\n")

        # Walk-Forward Results
        f.write("## Walk-Forward Validation Results\n\n")
        f.write("```\n")
        f.write(metrics_df.to_string(index=False))
        f.write("\n```\n\n")

        # Feature Importance (Top 20)
        f.write("## Feature Importance (Top 20)\n\n")

        importance = model.get_booster().get_score(importance_type='gain')
        if importance:
            importance_sorted = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:20]

            f.write("| Rank | Feature | Gain | % Total |\n")
            f.write("|------|---------|------|----------|\n")

            total_gain = sum(v for k, v in importance.items())
            for i, (feat, gain) in enumerate(importance_sorted, 1):
                pct = (gain / total_gain) * 100
                f.write(f"| {i} | {feat} | {gain:.0f} | {pct:.2f}% |\n")

            f.write("\n")

            # Feature insights
            top_10_pct = sum(g for f, g in importance_sorted[:10]) / total_gain * 100
            f.write(f"**Insight:** Top 10 features contribute {top_10_pct:.1f}% of total gain.\n\n")
        else:
            f.write("*No feature importance available*\n\n")

        # Usage Recommendations
        f.write("## Usage Recommendations\n\n")
        f.write("### Trade Selection Thresholds\n\n")

        if avg_edge > 2.5:
            f.write("- **High Confidence (Score > 0.7):** Position size 1.5x\n")
            f.write("- **Medium Confidence (Score > 0.5):** Position size 1.0x\n")
            f.write("- **Low Confidence (Score < 0.5):** Skip\n\n")
        elif avg_edge > 1.5:
            f.write("- **Conservative (Score > 0.8):** Position size 1.0x\n")
            f.write("- **Moderate (Score > 0.6):** Position size 0.5x\n")
            f.write("- **Low (Score < 0.6):** Skip\n\n")
        else:
            f.write("- **Very Conservative (Score > 0.85):** Position size 0.5x\n")
            f.write("- **All others:** Skip until model is improved\n\n")

        f.write("### Comparison with M01\n\n")
        f.write("M01_3bar uses path-dependent triple barrier labels instead of M01's final return threshold. ")
        f.write("The key difference: M01 asks \"will this trade return 15%+?\", while M01_3bar asks \"will this trade hit ")
        f.write("the profit target before the stop-loss?\"\n\n")

        f.write("**Integration Strategies:**\n\n")
        f.write("1. **Ensemble Approach:** Combine scores\n")
        f.write("   ```python\n")
        f.write("   final_score = 0.6 × M01_score + 0.4 × M01_3bar_score\n")
        f.write("   ```\n\n")

        f.write("2. **Filter Approach:** Require both models to agree\n")
        f.write("   ```python\n")
        f.write("   take_trade = (M01_score > 0.6) AND (M01_3bar_score > 0.6)\n")
        f.write("   ```\n\n")

        f.write("3. **Position Sizing:** Use M01_3bar confidence to scale M01 positions\n")
        f.write("   ```python\n")
        f.write("   if M01_score > 0.7:\n")
        f.write("       if M01_3bar_score > 0.8:\n")
        f.write("           position_size = base_size × 1.5  # High conviction\n")
        f.write("       elif M01_3bar_score > 0.6:\n")
        f.write("           position_size = base_size × 1.0  # Normal\n")
        f.write("       else:\n")
        f.write("           position_size = base_size × 0.5  # Reduced\n")
        f.write("   ```\n\n")

        # Barrier Configuration
        f.write("## Barrier Configuration\n\n")
        f.write(f"- **Stop Loss:** k_sl = {config['barrier_params']['k_sl']} × ATR\n")
        f.write(f"- **Profit Target:** MAX({config['barrier_params']['min_tp']:.0%}, {config['barrier_params']['k_tp']} × ATR)\n")
        f.write(f"- **Max Time Barrier:** {config['barrier_params']['max_time']} days (give up waiting for TP/SL)\n")
        f.write(f"- **Rehydration Horizon:** {config['barrier_params'].get('horizon_days', 'N/A')} days (for feature calculation only)\n\n")

        f.write("**Interpretation:**\n")
        f.write("- Stop losses are volatility-adaptive (tighter for low-vol stocks, wider for high-vol)\n")
        f.write(f"- Profit targets have a {config['barrier_params']['min_tp']:.0%} floor but expand with volatility\n")
        f.write(f"- Max time barrier = {config['barrier_params']['max_time']} days (not {config['barrier_params'].get('horizon_days', 'N/A')} - that's just for features)\n")
        f.write("- These parameters were optimized via walk-forward grid search (Phase 1)\n\n")

        # Model Configuration
        f.write("## Model Configuration\n\n")
        f.write("### XGBoost Parameters\n\n")
        f.write("```python\n")
        f.write("XGBClassifier(\n")
        f.write("    n_estimators=500,\n")
        f.write("    learning_rate=0.03,\n")
        f.write("    max_depth=5,\n")
        f.write("    subsample=0.8,\n")
        f.write("    colsample_bytree=0.8,\n")
        f.write("    min_child_weight=3,\n")
        f.write("    scale_pos_weight=<calculated per fold>,  # Handles class imbalance\n")
        f.write("    eval_metric='logloss',\n")
        f.write("    random_state=42\n")
        f.write(")\n")
        f.write("```\n\n")

        f.write("### Validation Strategy\n\n")
        f.write("- **Method:** Walk-Forward Validation\n")
        f.write("- **Train Window:** 3 years\n")
        f.write("- **Test Window:** 1 year\n")
        f.write("- **Class Imbalance:** Handled via scale_pos_weight (auto-calculated per fold)\n\n")

        # Next Steps
        f.write("## Next Steps\n\n")

        if avg_edge > 2.5:
            f.write("1. **Backtest with VectorBT:** Use d3_rehydrated.parquet to compare equity curves vs M01\n")
            f.write("2. **Live Testing:** Paper trade top 10% predictions for 1-2 months\n")
            f.write("3. **Ensemble Testing:** Compare M01 vs M01_3bar vs Ensemble performance\n")
            f.write("4. **Monitor Degradation:** Track edge over time in production\n")
        elif avg_edge > 1.5:
            f.write("1. **Hyperparameter Tuning:** Run Optuna with 50-100 trials\n")
            f.write("2. **Feature Engineering:** Add barrier-specific features (volatility regime, sector TP rates)\n")
            f.write("3. **Ensemble with M01:** Test weighted combinations\n")
            f.write("4. **Barrier Re-optimization:** Try different k_sl/k_tp/min_tp values\n")
        else:
            f.write("1. **Barrier Re-optimization:** Run grid search with wider parameter ranges\n")
            f.write("2. **Feature Engineering:** Add domain-specific features for barrier prediction\n")
            f.write("3. **Alternative Models:** Test LightGBM or CatBoost\n")
            f.write("4. **Data Quality:** Review D3 label generation for potential issues\n")

        f.write("\n\n")
        f.write("---\n\n")
        f.write(f"Report generated by model_trainer.py at {timestamp}\n")

    logger.info(f"Generated report: {report_path}")


# =============================================================================
# STEP 2R: REHYDRATE D2 (Multi-Day Trajectories)
# =============================================================================
def rehydrate_d2(d1: pd.DataFrame, n_jobs: int = -1, horizon_days: int = None) -> pd.DataFrame:
    """
    Rehydrate d2 from snapshot to multi-day trajectories.

    Phase 1A: Expands each trade from entry to SEPA exit with daily OHLCV + features.
    Phase 1B: Uses fixed horizon if horizon_days is set.

    Args:
        d1: Trade simulation results from simulate_trades()
        n_jobs: Number of parallel workers for feature computation
        horizon_days: Optional fixed horizon (None = use SEPA exit, else fixed horizon)

    Returns:
        Long-format DataFrame with one row per trade-day
    """
    horizon_msg = f"with {horizon_days}-day fixed horizon" if horizon_days else "using SEPA exits"
    logger.info(f"Step 2R: Rehydrating D2 dataset ({len(d1)} trades) {horizon_msg}")

    from src.dataset_rehydrator import DatasetRehydrator
    from src.fundamental_merger import FundamentalMerger

    # Initialize components (reuse same pattern as enrich_with_features)
    data_repo = DataRepository()
    benchmark_data = data_repo.get_benchmark_data(mode=CacheMode.CACHE_ONLY)
    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    fund_merger = FundamentalMerger(force_cache_only=True)

    # Rehydrate with optional fixed horizon
    rehydrator = DatasetRehydrator(data_repo, feature_engine, fund_merger, horizon_days=horizon_days)
    d2_rehydrated = rehydrator.rehydrate_trades(d1, n_jobs=n_jobs)

    logger.info(f"Rehydration complete: {len(d2_rehydrated):,} rows "
                f"({len(d2_rehydrated) / len(d1):.1f} days/trade avg)")

    return d2_rehydrated


# =============================================================================
# STEP D3: TRIPLE BARRIER LABEL GENERATION
# =============================================================================
def generate_d3_labels(
    d2_path: str = 'data/ml/d2_fixed_horizon_90d.parquet',
    k_sl: float = 2.0,
    k_tp: float = 3.0,
    min_tp: float = 0.15,
    max_time: int = 60,
    min_time: int = 20,
    n_jobs: int = -1
) -> pd.DataFrame:
    """
    Generate D3 dataset with triple barrier labels.

    Uses hybrid barrier logic: ATR-based stops + MAX(floor, ATR) targets.

    Args:
        d2_path: Path to d2_fixed_horizon_90d.parquet
        k_sl: Stop loss ATR multiplier (default: 2.0)
        k_tp: Target ATR multiplier (default: 3.0)
        min_tp: Minimum profit target floor (default: 0.15 = 15%)
        max_time: Maximum time barrier (default: 60 days)
        min_time: Minimum time barrier (default: 20 days)
        n_jobs: Parallel workers

    Returns:
        D3 DataFrame with y_meta labels and barrier outcomes
    """
    from src.triple_barrier_labeler import (
        TripleBarrierLabeler,
        HybridBarrierParams,
        compute_expectancy
    )

    logger.info(f"Step D3: Generating triple barrier labels")
    logger.info(f"   Params: k_sl={k_sl}, k_tp={k_tp}, min_tp={min_tp:.0%}")

    # Load D2 fixed horizon data
    d2 = pd.read_parquet(d2_path)
    logger.info(f"   Loaded {len(d2):,} rows, {d2['trade_id'].nunique()} trades")

    # Create hybrid barrier params
    params = HybridBarrierParams(
        k_sl=k_sl,
        k_tp=k_tp,
        min_tp=min_tp,
        max_time=max_time,
        min_time=min_time
    )

    # Apply barriers
    d3 = TripleBarrierLabeler.label_dataset(
        d2_rehydrated=d2,
        params=params,
        binary_labels=True,
        n_jobs=n_jobs,
        use_vectorized=True
    )

    # Log results
    metrics = compute_expectancy(d3)
    logger.info(f"   Labeled {len(d3):,} trades")
    logger.info(f"   y_meta=1 (TP): {(d3['y_meta'] == 1).sum()} ({(d3['y_meta'] == 1).mean():.1%})")
    logger.info(f"   Expectancy: {metrics['expectancy']:.2%}, Risk/Reward: {metrics['risk_reward']:.2f}")

    return d3


# =============================================================================
# STEP D3R: REHYDRATE D3 (Trajectories with Barrier Exits)
# =============================================================================
def rehydrate_d3(
    d1: pd.DataFrame,
    d3: pd.DataFrame,
    n_jobs: int = -1
) -> pd.DataFrame:
    """
    Rehydrate D3 using barrier exit days instead of SEPA exits.

    Creates multi-day trajectories truncated to barrier outcomes for backtesting.

    Args:
        d1: D1 trades DataFrame
        d3: D3 labels DataFrame (with days_to_outcome)
        n_jobs: Parallel workers

    Returns:
        Rehydrated DataFrame with trajectories ending at barrier exit
    """
    from src.dataset_rehydrator import DatasetRehydrator
    from src.fundamental_merger import FundamentalMerger

    logger.info(f"Step D3R: Rehydrating with barrier exits ({len(d3)} trades)")

    # Filter D1 to only trades in D3
    d3_trade_ids = set(d3['trade_id'])
    d1_filtered = d1[d1['trade_id'].isin(d3_trade_ids)].copy()
    logger.info(f"   Filtered D1 to {len(d1_filtered):,} trades")

    # Initialize components
    data_repo = DataRepository()
    benchmark_data = data_repo.get_benchmark_data(mode=CacheMode.CACHE_ONLY)
    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
    fund_merger = FundamentalMerger(force_cache_only=True)

    # Rehydrate with D3 exits
    rehydrator = DatasetRehydrator(
        data_repo, feature_engine, fund_merger,
        d3_exits=d3  # Use barrier exits from D3
    )
    d3_rehydrated = rehydrator.rehydrate_trades(d1_filtered, n_jobs=n_jobs)

    logger.info(f"   Rehydrated: {len(d3_rehydrated):,} rows "
                f"({len(d3_rehydrated) / len(d1_filtered):.1f} days/trade avg)")

    return d3_rehydrated


# =============================================================================
# MAIN PIPELINE
# =============================================================================
def run_pipeline(start_date: str, end_date: str, threshold: float = 15.0,
                steps: List[str] = None,
                model_type: str = 'regression',
                tune: bool = False,
                tune_trials: int = 50,
                horizon_days: int = 90,
                feature_version: str = 'M01_3BAR',
                target: str = 'return_pct',
                survivor_model: bool = False,
                survivor_stop_multiplier: float = 2.0):
    """
    Run the full model training pipeline.

    Args:
        start_date: Start date for simulation
        end_date: End date for simulation
        threshold: Success threshold for trades
        steps: Pipeline steps to run
        model_type: 'regression' or 'classification'
        tune: Whether to run Optuna hyperparameter tuning
        horizon_days: Fixed horizon in days for rehydration
        feature_version: Feature set version for M01_3bar ('M01_3BAR' or 'M01_3BAR_V2')
        tune_trials: Number of Optuna trials
        target: Target column for M01 training ('return_pct', 'y_max', 'label')
        survivor_model: Enable Survivor Model (train only on non-crashed trades)
        survivor_stop_multiplier: Structural stop multiplier for survivor filtering (default: 2.0)
    """
    if steps is None:
        steps = ['d1', 'd2', 'train']

    print("\n" + "=" * 70)
    print(" MODEL TRAINER (Optimized Event-Driven Pipeline)")
    print("=" * 70)
    print(f"   Date Range: {start_date} to {end_date}")
    print(f"   Model Type: {model_type}")
    print(f"   Steps to Run: {steps}")
    if tune:
        print(f"   Hyperparameter Tuning: Enabled ({tune_trials} trials)")
    print("=" * 70 + "\n")

    start_time = time.time()

    d1_path = Path("data/ml/d1_trades.parquet")
    d2_path = Path("data/ml/d2_features.parquet")
    d2r_path = Path("data/ml/d2_rehydrated.parquet")
    # Dynamic path based on horizon parameter
    d2r90_path = Path(f"data/ml/d2_fixed_horizon_{horizon_days}d.parquet")

    # Step 1: Simulate Trades (D1)
    if 'd1' in steps:
        d1 = simulate_trades(start_date, end_date, threshold)
        d1.to_parquet(d1_path, index=False)
    else:
        if d1_path.exists():
            print(f"   Skipping Step 1. Loading existing D1 from {d1_path}")
            d1 = pd.read_parquet(d1_path)
        elif 'd2' in steps or 'd2r' in steps or 'd2rh' in steps or 'train' in steps:
            print("   Step 1 (D1) skipped but file missing. Cannot proceed.")
            return

    # Step 2: Enrich with Features (D2)
    if 'd2' in steps:
        merged = enrich_with_features(d1, n_jobs=-1)
        merged.to_parquet(d2_path, index=False)
    else:
        if d2_path.exists():
            print(f"   Skipping Step 2. Loading existing D2 from {d2_path}")
            merged = pd.read_parquet(d2_path)
        elif 'train' in steps:
             print("   Step 2 (D2) skipped but file missing. Cannot proceed.")
             return

    # Step 2R: Rehydrate D2 (Multi-Day Trajectories)
    if 'd2r' in steps:
        d2_rehydrated = rehydrate_d2(d1, n_jobs=-1)
        d2_rehydrated.to_parquet(d2r_path, index=False)
        logger.info(f"Saved rehydrated dataset to {d2r_path} "
                    f"({d2r_path.stat().st_size / 1024 / 1024:.1f} MB)")

    # Step 2R-90: Rehydrate D2 with Fixed Horizon (for Triple Barrier)
    if 'd2rh' in steps:
        logger.info(f"Step D2RH: Rehydrating with {horizon_days}-day fixed horizon")

        # CRITICAL: Filter out trades that don't have enough forward-looking data
        # If end_date is 2023-12-31 and horizon is 90 days, we can't test trades after 2023-10-02
        end_date_dt = pd.to_datetime(end_date)
        cutoff_date = end_date_dt - pd.Timedelta(days=horizon_days)

        d1_filtered = d1[pd.to_datetime(d1['date']) <= cutoff_date].copy()
        trades_excluded = len(d1) - len(d1_filtered)

        if trades_excluded > 0:
            logger.warning(f"Excluded {trades_excluded} trades after {cutoff_date.strftime('%Y-%m-%d')} "
                          f"(insufficient {horizon_days}-day forward window)")
            logger.info(f"Remaining trades for rehydration: {len(d1_filtered):,}")

        # Rehydrate with filtered trades
        d2_90d = rehydrate_d2(d1_filtered, n_jobs=-1, horizon_days=horizon_days)

        d2_90d.to_parquet(d2r90_path, index=False)
        logger.info(f"Saved {horizon_days}-day horizon dataset to {d2r90_path}")
        logger.info(f"  Size: {d2r90_path.stat().st_size / 1024 / 1024:.1f} MB")
        logger.info(f"  Rows: {len(d2_90d):,}")
        logger.info(f"  Avg days/trade: {len(d2_90d) / len(d1_filtered):.1f}")

    # Step D3: Generate Triple Barrier Labels
    d3_path = Path(f"data/ml/d3_triple_barrier_{horizon_days}d.parquet")
    if 'd3' in steps:
        # Requires d2rh data
        if not d2r90_path.exists():
            logger.error(f"D3 requires d2rh data. Run with --steps d2rh first.")
            return

        d3 = generate_d3_labels(
            d2_path=str(d2r90_path),
            k_sl=1.0,   # Phase 1 optimized (was 2.0)
            k_tp=4.0,   # Phase 1 optimized (was 3.0)
            min_tp=0.20,  # Phase 1 optimized (was 0.15)
            max_time=30,  # Phase 1 optimized (was 60)
            n_jobs=-1
        )
        d3.to_parquet(d3_path, index=False)
        logger.info(f"Saved D3 labels to {d3_path} ({d3_path.stat().st_size / 1024 / 1024:.1f} MB)")
    else:
        if d3_path.exists() and ('d3r' in steps):
            logger.info(f"Loading existing D3 from {d3_path}")
            d3 = pd.read_parquet(d3_path)

    # Step D3R: Rehydrate D3 with Barrier Exits
    d3r_path = Path(f"data/ml/d3_rehydrated_{horizon_days}d.parquet")
    if 'd3r' in steps:
        # Requires D3 labels
        if not d3_path.exists():
            logger.error(f"D3R requires D3 labels. Run with --steps d3 first.")
            return
        if 'd3' not in steps:
            d3 = pd.read_parquet(d3_path)

        d3_rehydrated = rehydrate_d3(d1, d3, n_jobs=-1)
        d3_rehydrated.to_parquet(d3r_path, index=False)
        logger.info(f"Saved D3 rehydrated to {d3r_path} ({d3r_path.stat().st_size / 1024 / 1024:.1f} MB)")

    # Step 3: Train Model (Walk-Forward)
    if 'train' in steps:
        model, feature_cols, metrics = train_model_walk_forward(
            merged,
            model_type=model_type,
            tune=tune,
            tune_trials=tune_trials,
            target=target,
            survivor_model=survivor_model,
            survivor_stop_multiplier=survivor_stop_multiplier
        )

        # Step 4: Save Production Model
        if model is not None:
            save_production_model(model, feature_cols, metrics)

            # Step 5: Generate Feature Importance & Report
            output_dir = Path("models")
            importance_df = save_feature_importance(model, feature_cols, output_dir)
            report_path = generate_model_report(
                model, feature_cols, metrics, model_type,
                importance_df, start_date, end_date
            )

            print(f"\n[SUCCESS] Model report saved to: {report_path}")
            print(f"[SUCCESS] Feature importance saved to: models/feature_importance.csv\n")

    # Step D3-TRAIN: Train M01_3bar (Triple Barrier Model)
    if 'd3train' in steps:
        logger.info("=" * 70)
        logger.info("Step D3-TRAIN: Training M01_3bar (Triple Barrier Model)")
        logger.info("=" * 70)

        # Check if D3 exists
        if not d3_path.exists():
            logger.error(f"D3 dataset not found: {d3_path}")
            logger.error(f"Run --steps d3 first to generate triple barrier labels")
            return

        # Train M01_3bar
        model, features, metrics_df = train_triple_barrier_model(
            d3_path=str(d3_path),
            tune=tune,
            tune_trials=tune_trials,
            verbose=True,
            feature_version=feature_version
        )

        if model is not None:
            # Save model (include version suffix for V2)
            model_name = 'M01_3bar' if feature_version == 'M01_3BAR' else 'M01_3bar_v2'
            model_path = Path('models') / f'model_{model_name.lower()}.json'
            model.save_model(str(model_path))
            logger.info(f"Saved model to {model_path}")

            # Save config
            import json
            config = {
                'model_name': model_name,
                'feature_version': feature_version,
                'created_at': datetime.now().isoformat(),
                'feature_columns': features,
                'barrier_params': {
                    'k_sl': 1.0,  # Phase 1 optimized
                    'k_tp': 4.0,  # Phase 1 optimized
                    'min_tp': 0.20,  # Phase 1 optimized
                    'max_time': 30,  # Phase 1 optimized
                    'horizon_days': horizon_days
                },
                'validation_metrics': metrics_df.to_dict('records')
            }

            config_path = Path('models') / f'model_{model_name.lower()}_config.json'
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            logger.info(f"Saved config to {config_path}")

            # Generate feature importance
            output_dir = Path("models")
            importance_df = save_feature_importance(model, features, output_dir)

            # Rename feature importance file to avoid overwriting M01's
            default_importance = output_dir / "feature_importance.csv"
            m01_3bar_importance = output_dir / "feature_importance_m01_3bar.csv"
            if default_importance.exists():
                default_importance.replace(m01_3bar_importance)
                logger.info(f"Saved feature importance to {m01_3bar_importance}")

            # Generate report
            generate_model_report_m01_3bar(model, metrics_df, features, config)

            print(f"\n[SUCCESS] M01_3bar model trained and saved to models/")
            print(f"[SUCCESS] Check models/model_report_M01_3bar_*.md for detailed results\n")

    elapsed = time.time() - start_time
    print(f"\nTotal Pipeline Time: {elapsed/60:.1f} minutes\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Model Trainer - Optimized Pipeline")
    parser.add_argument('--start', default='2018-01-01', help='Start Date (YYYY-MM-DD)')
    parser.add_argument('--end', default='2023-12-31', help='End Date (YYYY-MM-DD)')
    parser.add_argument('--threshold', type=float, default=15.0, help='Success threshold (%)')
    parser.add_argument('--steps', nargs='+',
                       choices=['d1', 'd2', 'd2r', 'd2rh', 'd3', 'd3r', 'train', 'd3train'],
                       default=['d1', 'd2', 'train'],
                       help='Pipeline steps (d1=trades, d2=features, d2r=rehydrate, d2rh=horizon, d3=labels, d3r=rehydrate_d3, train=M01, d3train=M01_3bar)')

    # MODEL TRAINING OPTIONS
    parser.add_argument('--model-type', choices=['regression', 'classification'],
                       default='regression',
                       help='Model type (default: regression for return prediction)')

    # HYPERPARAMETER TUNING OPTIONS
    parser.add_argument('--tune', action='store_true',
                       help='Enable Optuna hyperparameter tuning (adds ~15-20 min)')
    parser.add_argument('--trials', type=int, default=50,
                       help='Number of Optuna trials (default: 50, use 10 for quick test)')

    # REHYDRATION OPTIONS (for Triple Barrier)
    parser.add_argument('--horizon', type=int, default=90,
                       choices=[30, 60, 90, 120, 180],
                       help='Fixed horizon in days for d2rh/d3/d3r steps (default: 90)')

    # FEATURE VERSION (for M01_3bar)
    parser.add_argument('--feature-version', type=str, default='M01_3BAR',
                       choices=['M01_3BAR', 'M01_3BAR_V2'],
                       help='Feature set version for M01_3bar model (default: M01_3BAR, V2: includes velocity features)')

    # TARGET SELECTION (for M01 dual labels - Option B)
    parser.add_argument('--target', type=str, default='return_pct',
                       choices=['return_pct', 'y_max', 'label'],
                       help='Target column for M01 training (default: return_pct, y_max: max favorable excursion, label: binary)')

    # SURVIVOR MODEL OPTIONS
    parser.add_argument('--survivor-model', action='store_true',
                       help='Enable Survivor Model: Train only on trades that do not hit structural stop (-K×ATR)')
    parser.add_argument('--survivor-stop-multiplier', type=float, default=2.0,
                       help='Structural stop multiplier for survivor model (default: 2.0, meaning -2×ATR)')

    args = parser.parse_args()

    run_pipeline(args.start, args.end, args.threshold, args.steps,
                model_type=args.model_type,
                tune=args.tune, tune_trials=args.trials,
                horizon_days=args.horizon,
                feature_version=args.feature_version,
                target=args.target,
                survivor_model=args.survivor_model,
                survivor_stop_multiplier=args.survivor_stop_multiplier)
