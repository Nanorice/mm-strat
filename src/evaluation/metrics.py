"""
Core ranking and statistical metrics for ML model evaluation.
=============================================================

Provides finance-standard metrics for evaluating ranking models:
- IC (Information Coefficient) - Spearman rank correlation
- Precision@K / Recall@K - Classification-style ranking metrics
- Decile Lift - Ratio of top decile to overall mean
- Volatility Correlation - Detect vol-detector failure mode
"""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from typing import Dict, List, Tuple, Optional


def calculate_ic(y_true: np.ndarray, y_pred: np.ndarray) -> Tuple[float, float]:
    """
    Calculate Information Coefficient (Spearman rank correlation).
    
    This is THE standard metric for ranking model quality in finance.
    IC measures how well predictions rank observations relative to actuals.
    
    Args:
        y_true: Actual values
        y_pred: Predicted values
        
    Returns:
        (ic, p_value) tuple
        
    Interpretation:
        IC > 0.10: Good signal
        IC > 0.05: Weak but usable signal  
        IC < 0.05: Noise
    """
    if len(y_true) < 3:
        return 0.0, 1.0
    
    # Handle constant predictions
    if np.std(y_pred) == 0 or np.std(y_true) == 0:
        return 0.0, 1.0
    
    ic, p_value = spearmanr(y_true, y_pred)
    
    # Handle NaN from scipy
    if np.isnan(ic):
        return 0.0, 1.0
    
    return float(ic), float(p_value)


def calculate_precision_at_k(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    k: float = 0.1,
    winner_threshold: float = 0.70
) -> float:
    """
    Precision@K: Of top-K predictions, what % are actual winners?
    
    Example: 
        - We predict top 10% of stocks (k=0.1)
        - We define "winners" as top 30% of actual returns (winner_threshold=0.70)
        - Precision = (# of predicted top 10% that are actual top 30%) / (# predicted top 10%)
    
    Args:
        y_true: Actual values
        y_pred: Predicted values
        k: Top fraction to evaluate (0.1 = top 10%)
        winner_threshold: Percentile to classify as winner (0.70 = top 30% are winners)
        
    Returns:
        Precision score (0.0 to 1.0)
    """
    if len(y_true) < 10:
        return 0.0
    
    df = pd.DataFrame({'actual': y_true, 'predicted': y_pred})
    
    # Define predicted top-K
    pred_cutoff = df['predicted'].quantile(1 - k)
    predicted_top_k = df['predicted'] >= pred_cutoff
    
    # Define actual winners
    actual_cutoff = df['actual'].quantile(winner_threshold)
    actual_winners = df['actual'] >= actual_cutoff
    
    # Precision = TP / (TP + FP) = TP / Predicted Positive
    n_predicted_top = predicted_top_k.sum()
    if n_predicted_top == 0:
        return 0.0
    
    n_true_positives = (predicted_top_k & actual_winners).sum()
    precision = n_true_positives / n_predicted_top
    
    return float(precision)


def calculate_recall_at_k(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    k: float = 0.1,
    top_class_pct: float = 0.05
) -> float:
    """
    Recall@K: Of actual top performers, what % captured in top-K predictions?
    
    This answers: "Did we find the super performers?"
    
    Example:
        - Actual top 5% performers = 50 stocks
        - We predicted top 10% = 100 stocks
        - Of those 50 super performers, 29 are in our top 100 predictions
        - Recall = 29/50 = 58%
    
    Args:
        y_true: Actual values
        y_pred: Predicted values
        k: Top fraction of predictions to evaluate (0.1 = top 10%)
        top_class_pct: Percentile to define super performers (0.05 = top 5%)
        
    Returns:
        Recall score (0.0 to 1.0)
    """
    if len(y_true) < 10:
        return 0.0
    
    df = pd.DataFrame({'actual': y_true, 'predicted': y_pred})
    
    # Define predicted top-K
    pred_cutoff = df['predicted'].quantile(1 - k)
    predicted_top_k = df['predicted'] >= pred_cutoff
    
    # Define actual super performers (top_class_pct)
    actual_cutoff = df['actual'].quantile(1 - top_class_pct)
    actual_super_performers = df['actual'] >= actual_cutoff
    
    # Recall = TP / (TP + FN) = TP / Actual Positives
    n_actual_super = actual_super_performers.sum()
    if n_actual_super == 0:
        return 0.0
    
    n_captured = (predicted_top_k & actual_super_performers).sum()
    recall = n_captured / n_actual_super
    
    return float(recall)


def calculate_decile_lift(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    top_pct: float = 0.1
) -> float:
    """
    Decile Lift: (Top decile mean) / (Overall mean)
    
    Measures how much better the top predictions perform vs random.
    
    Args:
        y_true: Actual values
        y_pred: Predicted values
        top_pct: Top fraction to evaluate (0.1 = top 10%)
        
    Returns:
        Lift ratio (>1.0 = model adds value)
        
    Interpretation:
        Lift = 2.0 means top decile returns 2x the average
        Lift = 1.0 means no differentiation (random)
        Lift < 1.0 means model is inverse (predicting wrong direction)
    """
    if len(y_true) < 10:
        return 1.0
    
    df = pd.DataFrame({'actual': y_true, 'predicted': y_pred})
    
    overall_mean = df['actual'].mean()
    if overall_mean == 0:
        return 1.0
    
    # Top decile by predictions
    pred_cutoff = df['predicted'].quantile(1 - top_pct)
    top_decile_actuals = df[df['predicted'] >= pred_cutoff]['actual']
    top_decile_mean = top_decile_actuals.mean()
    
    lift = top_decile_mean / overall_mean
    
    return float(lift)


def calculate_volatility_correlation(
    predictions_df: pd.DataFrame,
    pred_col: str = 'y_pred',
    vol_cols: Optional[List[str]] = None
) -> Dict:
    """
    Test if model is a volatility detector (failure mode).
    
    A model that simply predicts "high volatility = high return" will have 
    high correlation between predictions and ATR/volatility measures.
    This is a degenerate solution - we want alpha, not vol exposure.
    
    Args:
        predictions_df: DataFrame with predictions and volatility columns
        pred_col: Column name for predictions
        vol_cols: List of volatility column names to check
        
    Returns:
        {
            'pred_vs_atr': float,
            'pred_vs_natr': float,
            'max_vol_corr': float,
            'is_vol_detector': bool  # True if any corr > 0.5
        }
    """
    if vol_cols is None:
        vol_cols = ['ATR', 'nATR', 'atr_14', 'natr_14']
    
    result = {
        'pred_vs_atr': 0.0,
        'pred_vs_natr': 0.0,
        'max_vol_corr': 0.0,
        'is_vol_detector': False,
        'correlations': {}
    }
    
    if pred_col not in predictions_df.columns:
        return result
    
    y_pred = predictions_df[pred_col].values
    
    correlations = []
    for vol_col in vol_cols:
        if vol_col in predictions_df.columns:
            vol_values = predictions_df[vol_col].values
            
            # Filter out NaN/inf
            mask = ~(np.isnan(y_pred) | np.isnan(vol_values) | 
                     np.isinf(y_pred) | np.isinf(vol_values))
            
            if mask.sum() > 10:
                corr, _ = spearmanr(y_pred[mask], vol_values[mask])
                if not np.isnan(corr):
                    correlations.append(abs(corr))
                    result['correlations'][vol_col] = float(corr)
                    
                    # Map to standard names
                    if vol_col.lower() in ['atr', 'atr_14']:
                        result['pred_vs_atr'] = float(corr)
                    elif vol_col.lower() in ['natr', 'natr_14']:
                        result['pred_vs_natr'] = float(corr)
    
    if correlations:
        result['max_vol_corr'] = float(max(correlations))
        result['is_vol_detector'] = result['max_vol_corr'] > 0.5
    
    return result
