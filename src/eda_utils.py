"""
EDA Utility Functions for Quantamental Trading Analysis
=======================================================
Provides reusable analysis functions for model evaluation and trade forensics.

This module implements industry-standard metrics for:
- Trade excursion analysis (MAE/MFE, E-Ratio)
- Feature discrimination power (KS test, Wasserstein distance)
- Model calibration and reliability (ECE, NPV)
- Error forensics (FOMO trades, Toxic trades)
- SHAP-based explainability

Author: Claude Code
Date: 2026-01-23
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from pathlib import Path
import glob
import os
from scipy.stats import ks_2samp, wasserstein_distance
from sklearn.calibration import calibration_curve
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# SECTION 1: TRADE PHYSICS (Dataset DNA Analysis)
# =============================================================================

def calculate_mae_mfe(d2_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate Maximum Adverse Excursion (MAE) and Maximum Favorable Excursion (MFE)
    for each trade using intra-trade price trajectories.

    Args:
        d2_df: Rehydrated dataset with multi-row trajectories per trade.
               Required columns: trade_id, day_in_trade, High, Low, Close, is_exit_day, return_pct

    Returns:
        DataFrame with columns:
        - trade_id: Unique trade identifier
        - MFE: Maximum favorable excursion (highest high %)
        - MAE: Maximum adverse excursion (lowest low %)
        - E_Ratio: Efficiency ratio (MFE / |MAE|)
        - final_return: Actual exit return %
        - regret: Profit left on table (MFE - final_return)

    Example:
        >>> mae_mfe_df = calculate_mae_mfe(d2_rehydrated)
        >>> print(f"Median E-Ratio: {mae_mfe_df['E_Ratio'].median():.2f}")
    """
    results = []

    for trade_id, group in d2_df.groupby('trade_id'):
        # Entry price is Close of day_in_trade==0
        entry_rows = group[group['day_in_trade'] == 0]
        if len(entry_rows) == 0:
            logger.warning(f"Trade {trade_id}: No entry day found (day_in_trade==0), skipping")
            continue

        entry_price = entry_rows['Close'].iloc[0]

        # MFE: highest high during trade
        highest = group['High'].max()
        MFE = ((highest - entry_price) / entry_price) * 100

        # MAE: lowest low during trade
        lowest = group['Low'].min()
        MAE = ((lowest - entry_price) / entry_price) * 100

        # Final return
        exit_rows = group[group['is_exit_day']]
        if len(exit_rows) == 0:
            logger.warning(f"Trade {trade_id}: No exit day found, skipping")
            continue

        final_return = exit_rows['return_pct'].iloc[0]

        # E-Ratio (efficiency)
        E_Ratio = MFE / abs(MAE) if MAE != 0 else np.nan

        results.append({
            'trade_id': trade_id,
            'MFE': MFE,
            'MAE': MAE,
            'E_Ratio': E_Ratio,
            'final_return': final_return,
            'regret': MFE - final_return  # Profit left on table
        })

    return pd.DataFrame(results)


def calculate_time_to_peak(d2_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate the day when each trade reached its maximum profit.

    Args:
        d2_df: Rehydrated dataset with multi-row trajectories.
               Required columns: trade_id, day_in_trade, High, Close, is_exit_day, days_held, return_pct

    Returns:
        DataFrame with columns:
        - trade_id: Unique trade identifier
        - days_to_peak: Day number when trade peaked
        - peak_return: Maximum return achieved (%)
        - total_days_held: Total days in trade
        - held_after_peak: Days held after peak
        - peak_to_exit_fade: Return fade from peak to exit

    Example:
        >>> ttp_df = calculate_time_to_peak(d2_rehydrated)
        >>> print(f"Median days to peak: {ttp_df['days_to_peak'].median():.0f}")
    """
    results = []

    for trade_id, group in d2_df.groupby('trade_id'):
        # Entry price
        entry_rows = group[group['day_in_trade'] == 0]
        if len(entry_rows) == 0:
            continue

        entry_price = entry_rows['Close'].iloc[0]

        # Calculate return for each day
        group = group.copy()
        group['intraday_return'] = ((group['High'] - entry_price) / entry_price) * 100

        # Find day of peak
        peak_idx = group['intraday_return'].idxmax()
        peak_day = group.loc[peak_idx, 'day_in_trade']
        peak_return = group['intraday_return'].max()

        # Total days held
        exit_rows = group[group['is_exit_day']]
        if len(exit_rows) == 0:
            continue

        total_days = exit_rows['days_held'].iloc[0]
        final_return = exit_rows['return_pct'].iloc[0]

        results.append({
            'trade_id': trade_id,
            'days_to_peak': peak_day,
            'peak_return': peak_return,
            'total_days_held': total_days,
            'held_after_peak': total_days - peak_day,
            'peak_to_exit_fade': peak_return - final_return
        })

    return pd.DataFrame(results)


def analyze_failures(d2_df: pd.DataFrame, loss_threshold: float = -3.0) -> pd.DataFrame:
    """
    Analyze losing trades to understand failure patterns.

    Args:
        d2_df: Rehydrated dataset with multi-row trajectories.
               Required columns: trade_id, day_in_trade, Low, Close, is_exit_day, return_pct, exit_reason
        loss_threshold: Return threshold to classify as "loser" (default: -3%)

    Returns:
        DataFrame with columns:
        - trade_id: Unique trade identifier
        - final_return: Exit return %
        - days_to_stop: Day when price broke -5% stop
        - max_drawdown: Deepest drawdown during trade
        - exit_reason: Reason for exit

    Example:
        >>> failures_df = analyze_failures(d2_rehydrated)
        >>> print(f"Avg days to stop: {failures_df['days_to_stop'].mean():.1f}")
    """
    # Filter losing trades
    losers = d2_df[d2_df.groupby('trade_id')['return_pct'].transform('first') < loss_threshold]

    results = []
    for trade_id, group in losers.groupby('trade_id'):
        # Entry price
        entry_rows = group[group['day_in_trade'] == 0]
        if len(entry_rows) == 0:
            continue

        entry_price = entry_rows['Close'].iloc[0]

        # Calculate drawdown
        group = group.copy()
        group['drawdown'] = ((group['Low'] - entry_price) / entry_price) * 100

        # Find when it broke below -5% (typical stop)
        stop_triggered_day = group[group['drawdown'] < -5].head(1)
        if len(stop_triggered_day) > 0:
            days_to_stop = stop_triggered_day['day_in_trade'].iloc[0]
        else:
            days_to_stop = np.nan

        # Exit info
        exit_rows = group[group['is_exit_day']]
        if len(exit_rows) == 0:
            continue

        final_return = exit_rows['return_pct'].iloc[0]
        exit_reason = exit_rows['exit_reason'].iloc[0] if 'exit_reason' in exit_rows.columns else 'unknown'

        results.append({
            'trade_id': trade_id,
            'final_return': final_return,
            'days_to_stop': days_to_stop,
            'max_drawdown': group['drawdown'].min(),
            'exit_reason': exit_reason
        })

    return pd.DataFrame(results)


# =============================================================================
# SECTION 2: M01 ANALYSIS (Signal Regressor)
# =============================================================================

def analyze_feature_separation(
    df: pd.DataFrame,
    features: List[str],
    target: str = 'return_pct'
) -> pd.DataFrame:
    """
    Compare feature distributions between return quartiles using KS test.

    Tests discriminative power of features by comparing top vs bottom quartiles.

    Args:
        df: Training dataset
        features: List of feature column names to test
        target: Target variable (default: 'return_pct')

    Returns:
        DataFrame sorted by KS_statistic with columns:
        - feature: Feature name
        - KS_statistic: Kolmogorov-Smirnov statistic (higher = better separation)
        - p_value: Statistical significance
        - wasserstein_distance: Earth Mover's Distance
        - q1_mean: Mean value in Q1 (losers)
        - q4_mean: Mean value in Q4 (winners)
        - mean_diff: Difference (Q4 - Q1)

    Example:
        >>> sep_df = analyze_feature_separation(df, M01_FEATURES)
        >>> print(sep_df.head(10))  # Top 10 discriminative features
    """
    # Split into quartiles
    df = df.copy()
    df['return_quartile'] = pd.qcut(
        df[target], q=4,
        labels=['Q1_Losers', 'Q2', 'Q3', 'Q4_Winners'],
        duplicates='drop'
    )

    q1_data = df[df['return_quartile'] == 'Q1_Losers']
    q4_data = df[df['return_quartile'] == 'Q4_Winners']

    results = []
    for feature in features:
        if feature not in df.columns:
            logger.warning(f"Feature '{feature}' not found in DataFrame, skipping")
            continue

        # Drop NaNs
        q1_vals = q1_data[feature].dropna()
        q4_vals = q4_data[feature].dropna()

        if len(q1_vals) < 10 or len(q4_vals) < 10:
            logger.warning(f"Feature '{feature}' has insufficient non-null values, skipping")
            continue

        # KS test
        ks_stat, p_value = ks_2samp(q1_vals, q4_vals)

        # Wasserstein distance (Earth Mover's Distance)
        wass_dist = wasserstein_distance(q1_vals, q4_vals)

        results.append({
            'feature': feature,
            'KS_statistic': ks_stat,
            'p_value': p_value,
            'wasserstein_distance': wass_dist,
            'q1_mean': q1_vals.mean(),
            'q4_mean': q4_vals.mean(),
            'mean_diff': q4_vals.mean() - q1_vals.mean()
        })

    return pd.DataFrame(results).sort_values('KS_statistic', ascending=False)


def analyze_prediction_errors(
    df: pd.DataFrame,
    predictions: np.ndarray,
    features: List[str],
    toxic_threshold: float = 15.0,
    fomo_threshold: float = 5.0,
    fomo_return_threshold: float = 20.0,
    accuracy_tolerance: float = 5.0
) -> pd.DataFrame:
    """
    Classify prediction errors into FOMO and Toxic categories.

    Args:
        df: Dataset with actual returns
        predictions: Predicted returns from model
        features: Feature columns (for forensic analysis)
        toxic_threshold: Min predicted return for toxic classification (default: 15%)
        fomo_threshold: Max predicted return for FOMO classification (default: 5%)
        fomo_return_threshold: Min actual return for FOMO classification (default: 20%)
        accuracy_tolerance: Tolerance for accurate predictions (default: ±5%)

    Returns:
        DataFrame with added columns:
        - predicted_return: Model predictions
        - error_type: 'Toxic', 'FOMO', 'Accurate', or 'Normal'

    Example:
        >>> error_df = analyze_prediction_errors(df, predictions, M01_FEATURES)
        >>> print(error_df['error_type'].value_counts())
    """
    df = df.copy()
    df['predicted_return'] = predictions

    # Define error types
    df['error_type'] = 'Normal'

    # Toxic: Predicted high (>15%), Actual negative
    toxic_mask = (df['predicted_return'] > toxic_threshold) & (df['return_pct'] < 0)
    df.loc[toxic_mask, 'error_type'] = 'Toxic'

    # FOMO: Predicted low (<5%), Actual very high (>20%)
    fomo_mask = (df['predicted_return'] < fomo_threshold) & (df['return_pct'] > fomo_return_threshold)
    df.loc[fomo_mask, 'error_type'] = 'FOMO'

    # Accurate: Within tolerance of actual
    good_mask = np.abs(df['predicted_return'] - df['return_pct']) < accuracy_tolerance
    df.loc[good_mask, 'error_type'] = 'Accurate'

    return df


def event_study_analysis(
    d2_rehydrated: pd.DataFrame,
    predictions_df: pd.DataFrame
) -> Tuple[pd.Series, pd.Series]:
    """
    Aggregate price paths for top vs bottom decile predictions (Event Study).

    Args:
        d2_rehydrated: Rehydrated dataset with multi-row trajectories.
                       Required columns: trade_id, day_in_trade, Close
        predictions_df: DataFrame with predictions.
                        Required columns: trade_id, predicted_return, prediction_decile

    Returns:
        Tuple of (top_path, bottom_path):
        - top_path: Average normalized price path for top decile (pd.Series indexed by day_in_trade)
        - bottom_path: Average normalized price path for bottom decile

    Example:
        >>> top, bottom = event_study_analysis(d2_rehydrated, predictions_df)
        >>> plt.plot(top.index, top.values, label='Top Decile')
        >>> plt.plot(bottom.index, bottom.values, label='Bottom Decile')
    """
    # Merge predictions with rehydrated data
    merged = d2_rehydrated.merge(
        predictions_df[['trade_id', 'predicted_return', 'prediction_decile']],
        on='trade_id', how='left'
    )

    # Filter top and bottom deciles
    top_decile = merged[merged['prediction_decile'] == 10]
    bottom_decile = merged[merged['prediction_decile'] == 1]

    # Calculate average price path (normalized to entry=100)
    def normalize_price_path(group):
        entry_rows = group[group['day_in_trade'] == 0]
        if len(entry_rows) == 0:
            return group

        entry_price = entry_rows['Close'].iloc[0]
        group = group.copy()
        group['normalized_price'] = (group['Close'] / entry_price) * 100
        return group

    top_decile = top_decile.groupby('trade_id', group_keys=False).apply(normalize_price_path)
    bottom_decile = bottom_decile.groupby('trade_id', group_keys=False).apply(normalize_price_path)

    # Aggregate by day_in_trade
    top_path = top_decile.groupby('day_in_trade')['normalized_price'].mean()
    bottom_path = bottom_decile.groupby('day_in_trade')['normalized_price'].mean()

    return top_path, bottom_path


# =============================================================================
# SECTION 3: M01_3BAR ANALYSIS (Ignition Engine)
# =============================================================================

def analyze_calibration(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10
) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Calculate Expected Calibration Error (ECE) and calibration curve.

    Args:
        y_true: True binary labels (0 or 1)
        y_prob: Predicted probabilities [0, 1]
        n_bins: Number of bins for calibration (default: 10)

    Returns:
        Tuple of (fraction_of_positives, mean_predicted_value, ECE):
        - fraction_of_positives: Actual positive rate per bin
        - mean_predicted_value: Average predicted probability per bin
        - ECE: Expected Calibration Error (lower is better, <0.1 is well-calibrated)

    Example:
        >>> frac_pos, mean_pred, ece = analyze_calibration(y_true, y_prob)
        >>> print(f"Expected Calibration Error: {ece:.3f}")
    """
    # Calibration curve
    fraction_of_positives, mean_predicted_value = calibration_curve(
        y_true, y_prob, n_bins=n_bins, strategy='quantile'
    )

    # ECE calculation
    bin_edges = np.quantile(y_prob, np.linspace(0, 1, n_bins + 1))
    ece = 0

    for i in range(n_bins):
        # Handle edge cases for first and last bins
        if i == 0:
            bin_mask = (y_prob >= bin_edges[i]) & (y_prob <= bin_edges[i+1])
        else:
            bin_mask = (y_prob > bin_edges[i]) & (y_prob <= bin_edges[i+1])

        if bin_mask.sum() > 0:
            bin_accuracy = y_true[bin_mask].mean()
            bin_confidence = y_prob[bin_mask].mean()
            ece += np.abs(bin_accuracy - bin_confidence) * bin_mask.sum() / len(y_true)

    return fraction_of_positives, mean_predicted_value, ece


def validate_negative_filter(
    df: pd.DataFrame,
    probabilities: np.ndarray,
    threshold: float = 0.4
) -> Tuple[Dict, pd.DataFrame, pd.DataFrame]:
    """
    Analyze performance of trades with score < threshold (Negative Filter validation).

    Args:
        df: Dataset with actual outcomes.
            Required columns: y_meta, return_at_outcome, barrier_outcome
        probabilities: Model predicted probabilities
        threshold: Score threshold for filtering (default: 0.4)

    Returns:
        Tuple of (metrics_dict, low_score_df, high_score_df):
        - metrics_dict: Summary statistics including NPV
        - low_score_df: Trades below threshold
        - high_score_df: Trades above threshold

    Example:
        >>> metrics, low, high = validate_negative_filter(df, probs, threshold=0.4)
        >>> print(f"NPV @ 0.4: {metrics['NPV']:.1%}")
    """
    df = df.copy()
    df['ignition_score'] = probabilities

    # Filter low and high scores
    low_score = df[df['ignition_score'] < threshold]
    high_score = df[df['ignition_score'] >= threshold]

    # Metrics
    results = {
        'total_trades': len(df),
        'low_score_count': len(low_score),
        'low_score_pct': len(low_score) / len(df) * 100,
        'low_score_win_rate': (low_score['y_meta'] == 1).mean() if len(low_score) > 0 else 0,
        'low_score_avg_return': low_score['return_at_outcome'].mean() if len(low_score) > 0 else 0,
        'low_score_toxic_rate': (low_score['barrier_outcome'] == 'SL').mean() if len(low_score) > 0 else 0,
        'high_score_count': len(high_score),
        'high_score_pct': len(high_score) / len(df) * 100,
        'high_score_win_rate': (high_score['y_meta'] == 1).mean() if len(high_score) > 0 else 0,
        'high_score_avg_return': high_score['return_at_outcome'].mean() if len(high_score) > 0 else 0,
    }

    # Negative Predictive Value (NPV)
    # NPV = P(y=0 | score < threshold) = 1 - low_score_win_rate
    results['NPV'] = 1 - results['low_score_win_rate']

    return results, low_score, high_score


def analyze_high_scores_shap(
    model,
    X: pd.DataFrame,
    y_prob: np.ndarray,
    threshold: float = 0.8,
    sample_size: Optional[int] = 500
) -> Tuple[np.ndarray, pd.DataFrame, pd.DataFrame]:
    """
    Run SHAP analysis on high-confidence predictions to understand drivers.

    Args:
        model: Trained XGBoost model
        X: Feature matrix
        y_prob: Predicted probabilities
        threshold: Score threshold for "high confidence" (default: 0.8)
        sample_size: Max samples for SHAP (for performance, default: 500)

    Returns:
        Tuple of (shap_values, feature_importance, X_high):
        - shap_values: SHAP values for high-score trades
        - feature_importance: Mean absolute SHAP per feature (sorted)
        - X_high: Feature matrix for high-score trades

    Example:
        >>> shap_vals, importance, X_high = analyze_high_scores_shap(model, X, probs)
        >>> print(importance.head(10))  # Top 10 SHAP drivers

    Note:
        Requires `pip install shap`
    """
    try:
        import shap
    except ImportError:
        raise ImportError("SHAP not installed. Run: pip install shap")

    # Filter high scores
    high_score_mask = y_prob > threshold
    X_high = X[high_score_mask]

    # Sample if too large (SHAP is slow)
    if sample_size and len(X_high) > sample_size:
        X_high = X_high.sample(n=sample_size, random_state=42)
        logger.info(f"Sampled {sample_size} high-score trades for SHAP analysis")

    # SHAP explainer
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_high)

    # Mean absolute SHAP per feature
    mean_shap = np.abs(shap_values).mean(axis=0)
    feature_importance = pd.DataFrame({
        'feature': X.columns,
        'mean_abs_shap': mean_shap
    }).sort_values('mean_abs_shap', ascending=False)

    return shap_values, feature_importance, X_high


# =============================================================================
# UTILITIES
# =============================================================================

def find_latest_model(model_name: str = 'M01') -> Path:
    """
    Find the most recent model file by timestamp.

    Args:
        model_name: Model directory name (e.g., 'M01', 'M01_3BAR_V2')

    Returns:
        Path to the latest model file

    Raises:
        FileNotFoundError: If no models found in directory

    Example:
        >>> model_path = find_latest_model('M01_3BAR_V2')
        >>> print(model_path)
    """
    model_dir = Path('data/models') / model_name

    if not model_dir.exists():
        raise FileNotFoundError(f"Model directory not found: {model_dir}")

    # Find all .json files (XGBoost model format)
    model_files = list(model_dir.glob('*.json'))

    if not model_files:
        raise FileNotFoundError(f"No model files (.json) found in {model_dir}")

    # Return most recent by modification time
    latest_model = max(model_files, key=os.path.getmtime)
    logger.info(f"Found latest model: {latest_model}")
    return latest_model


def align_features(X: pd.DataFrame, model_feature_names: List[str]) -> pd.DataFrame:
    """
    Reorder and fill missing features to match model's training feature order.

    Critical for XGBoost predictions - features must be in exact training order.

    Args:
        X: Input feature DataFrame
        model_feature_names: List of feature names in model's training order

    Returns:
        DataFrame with features aligned to model order (missing features filled with NaN)

    Example:
        >>> X_aligned = align_features(X, model.feature_names)
        >>> predictions = model.predict(xgb.DMatrix(X_aligned))
    """
    X = X.copy()

    # Add missing features as NaN
    for feature in model_feature_names:
        if feature not in X.columns:
            X[feature] = np.nan
            logger.warning(f"Feature '{feature}' not in input data, filled with NaN")

    # Reorder to match model
    X_aligned = X[model_feature_names]

    return X_aligned


def add_prediction_deciles(df: pd.DataFrame, predictions: np.ndarray, col_name: str = 'predicted_return') -> pd.DataFrame:
    """
    Add prediction decile column for stratified analysis.

    Args:
        df: Input DataFrame
        predictions: Model predictions
        col_name: Name for prediction column (default: 'predicted_return')

    Returns:
        DataFrame with added columns:
        - {col_name}: Model predictions
        - prediction_decile: Decile (1=lowest, 10=highest)

    Example:
        >>> df = add_prediction_deciles(df, predictions)
        >>> df.groupby('prediction_decile')['return_pct'].mean()
    """
    df = df.copy()
    df[col_name] = predictions

    # Create deciles
    df['prediction_decile'] = pd.qcut(
        df[col_name],
        q=10,
        labels=range(1, 11),
        duplicates='drop'
    )

    return df


def add_trade_sequence(df: pd.DataFrame, date_col: str = 'Date') -> pd.DataFrame:
    """
    Add day_in_trade and is_exit_day columns to rehydrated dataset.

    Computes the chronological sequence within each trade and identifies the last day.

    Args:
        df: Rehydrated DataFrame with multi-row trajectories per trade.
            Required columns: trade_id, {date_col}
        date_col: Name of date column (default: 'Date')

    Returns:
        DataFrame with added columns:
        - day_in_trade: Sequential day number (0, 1, 2, ...)
        - is_exit_day: Boolean flag for last day of trade

    Example:
        >>> df = pd.read_parquet('data/ml/d2_rehydrated.parquet')
        >>> df = add_trade_sequence(df)
        >>> print(df[df['trade_id']==1][['trade_id', 'day_in_trade', 'is_exit_day']])
    """
    if 'trade_id' not in df.columns:
        raise ValueError("DataFrame must have 'trade_id' column")

    if date_col not in df.columns:
        raise ValueError(f"DataFrame must have '{date_col}' column")

    df = df.copy()

    # Sort by trade_id and date to ensure chronological order
    df = df.sort_values(['trade_id', date_col])

    # Add day_in_trade (sequential numbering within each trade)
    df['day_in_trade'] = df.groupby('trade_id').cumcount()

    # Add is_exit_day (last row of each trade)
    df['is_exit_day'] = False
    last_day_idx = df.groupby('trade_id').tail(1).index
    df.loc[last_day_idx, 'is_exit_day'] = True

    logger.info(f"Added day_in_trade and is_exit_day columns to {len(df)} rows ({df['trade_id'].nunique()} trades)")

    return df
