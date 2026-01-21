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
def train_model_walk_forward(data: pd.DataFrame,
                              model_type: str = 'regression',
                              tune: bool = False,
                              tune_trials: int = 50,
                              train_years: int = 3,
                              test_years: int = 1) -> Tuple:
    """
    Train XGBoost using Walk-Forward validation.
    
    Strategy:
      Fold 1: Train [2015-2017], Test [2018]
      Fold 2: Train [2016-2018], Test [2019]
      ...
    
    Args:
        data: Merged D1+D2 DataFrame.
        train_years: Size of training window.
        test_years: Size of test window.
    
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

    # Prepare data
    data = data.sort_values('date')
    data['year'] = data['date'].dt.year

    # Clean training data
    data = clean_training_data(data, available_cols)

    years = sorted(data['year'].unique())

    # Determine target column based on model type
    target_col = 'return_pct' if model_type == 'regression' else 'label'

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
# MAIN PIPELINE
# =============================================================================
def run_pipeline(start_date: str, end_date: str, threshold: float = 15.0,
                steps: List[str] = None,
                model_type: str = 'regression',
                tune: bool = False,
                tune_trials: int = 50,
                horizon_days: int = 90):
    """
    Run the full model training pipeline.

    Args:
        start_date: Start date for simulation
        end_date: End date for simulation
        threshold: Success threshold for trades
        steps: Pipeline steps to run
        model_type: 'regression' or 'classification'
        tune: Whether to run Optuna hyperparameter tuning
        tune_trials: Number of Optuna trials
        horizon_days: Fixed horizon for d2r_fixed step (default: 90)
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
        elif 'd2' in steps or 'd2r' in steps or 'd2r90' in steps or 'train' in steps:
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
    if 'd2r90' in steps:
        logger.info(f"Step 2R-{horizon_days}: Rehydrating with {horizon_days}-day fixed horizon")

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

    # Step 3: Train Model (Walk-Forward)
    if 'train' in steps:
        model, feature_cols, metrics = train_model_walk_forward(
            merged,
            model_type=model_type,
            tune=tune,
            tune_trials=tune_trials
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

    elapsed = time.time() - start_time
    print(f"\nTotal Pipeline Time: {elapsed/60:.1f} minutes\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Model Trainer - Optimized Pipeline")
    parser.add_argument('--start', default='2018-01-01', help='Start Date (YYYY-MM-DD)')
    parser.add_argument('--end', default='2023-12-31', help='End Date (YYYY-MM-DD)')
    parser.add_argument('--threshold', type=float, default=15.0, help='Success threshold (%)')
    parser.add_argument('--steps', nargs='+', choices=['d1', 'd2', 'd2r', 'd2r90', 'train'],
                       default=['d1', 'd2', 'train'],
                       help='Pipeline steps to execute (d1=trades, d2=features, d2r=rehydrate, d2r90=90-day horizon, train=model)')

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
                       help='Fixed horizon in days for d2r90 step (default: 90, options: 30/60/90/120/180)')

    args = parser.parse_args()

    run_pipeline(args.start, args.end, args.threshold, args.steps,
                model_type=args.model_type,
                tune=args.tune, tune_trials=args.trials,
                horizon_days=args.horizon)
