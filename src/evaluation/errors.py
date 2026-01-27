"""
Error analysis: Classify prediction errors by type.
====================================================

Classifies prediction errors as:
- FOMO (False Negative): Missed winners - predicted low, actual high
- Toxic (False Positive): False positives - predicted high, actual low
- True Positive: Correctly predicted winners
- True Negative: Correctly avoided losers
"""

import pandas as pd
import numpy as np
from typing import Dict


def analyze_prediction_errors(
    predictions_df: pd.DataFrame,
    pred_col: str = 'y_pred',
    actual_col: str = 'y_true',
    high_threshold: float = 0.70,
    low_threshold: float = 0.30
) -> Dict:
    """
    Classify errors as FOMO (missed winners) vs Toxic (false positives).
    
    Uses percentile thresholds for high/low classification:
    - High: >= 70th percentile (top 30%)
    - Low: <= 30th percentile (bottom 30%)
    - Mid: Between 30th and 70th percentiles
    
    Args:
        predictions_df: DataFrame with predictions and actuals
        pred_col: Column name for predictions
        actual_col: Column name for actual values
        high_threshold: Percentile for high classification (0.70 = top 30%)
        low_threshold: Percentile for low classification (0.30 = bottom 30%)
        
    Returns:
        {
            'FOMO': {'count': int, 'avg_missed_return': float},
            'Toxic': {'count': int, 'avg_loss': float},
            'True_Positive': {'count': int, 'avg_return': float},
            'True_Negative': {'count': int, 'avg_return': float},
            'confusion_matrix': pd.DataFrame,
            'summary': str
        }
    """
    df = predictions_df.copy()
    
    if pred_col not in df.columns or actual_col not in df.columns:
        return {
            'FOMO': {'count': 0, 'avg_missed_return': 0.0},
            'Toxic': {'count': 0, 'avg_loss': 0.0},
            'True_Positive': {'count': 0, 'avg_return': 0.0},
            'True_Negative': {'count': 0, 'avg_return': 0.0},
            'confusion_matrix': pd.DataFrame(),
            'summary': 'No data'
        }
    
    # Calculate thresholds
    pred_high = df[pred_col].quantile(high_threshold)
    pred_low = df[pred_col].quantile(low_threshold)
    actual_high = df[actual_col].quantile(high_threshold)
    actual_low = df[actual_col].quantile(low_threshold)
    
    # Classify predictions and actuals
    df['pred_class'] = classify_by_percentile(df[pred_col], pred_high, pred_low)
    df['actual_class'] = classify_by_percentile(df[actual_col], actual_high, actual_low)
    
    # Identify error types
    fomo = df[(df['pred_class'] == 'low') & (df['actual_class'] == 'high')]
    toxic = df[(df['pred_class'] == 'high') & (df['actual_class'] == 'low')]
    true_positive = df[(df['pred_class'] == 'high') & (df['actual_class'] == 'high')]
    true_negative = df[(df['pred_class'] == 'low') & (df['actual_class'] == 'low')]
    
    # Build confusion matrix
    confusion = pd.crosstab(
        df['pred_class'], 
        df['actual_class'],
        margins=True
    )
    
    result = {
        'FOMO': {
            'count': int(len(fomo)),
            'avg_missed_return': float(fomo[actual_col].mean()) if len(fomo) > 0 else 0.0,
            'total_missed_return': float(fomo[actual_col].sum()) if len(fomo) > 0 else 0.0
        },
        'Toxic': {
            'count': int(len(toxic)),
            'avg_loss': float(toxic[actual_col].mean()) if len(toxic) > 0 else 0.0,
            'total_loss': float(toxic[actual_col].sum()) if len(toxic) > 0 else 0.0
        },
        'True_Positive': {
            'count': int(len(true_positive)),
            'avg_return': float(true_positive[actual_col].mean()) if len(true_positive) > 0 else 0.0
        },
        'True_Negative': {
            'count': int(len(true_negative)),
            'avg_return': float(true_negative[actual_col].mean()) if len(true_negative) > 0 else 0.0
        },
        'confusion_matrix': confusion
    }
    
    # Add summary
    total = len(df)
    if total > 0:
        tp_rate = len(true_positive) / total * 100
        fomo_rate = len(fomo) / total * 100
        toxic_rate = len(toxic) / total * 100
        result['summary'] = (
            f"TP: {tp_rate:.1f}% | FOMO: {fomo_rate:.1f}% | Toxic: {toxic_rate:.1f}%"
        )
    else:
        result['summary'] = 'No data'
    
    return result


def classify_by_percentile(
    values: pd.Series,
    high_threshold: float,
    low_threshold: float
) -> pd.Series:
    """
    Classify values as 'high', 'mid', or 'low' based on thresholds.
    
    Args:
        values: Series to classify
        high_threshold: Threshold for high classification
        low_threshold: Threshold for low classification
        
    Returns:
        Series with 'high', 'mid', or 'low' labels
    """
    result = pd.Series(['mid'] * len(values), index=values.index)
    result[values >= high_threshold] = 'high'
    result[values <= low_threshold] = 'low'
    return result


def calculate_error_cost(error_analysis: Dict) -> float:
    """
    Calculate total error cost (FOMO cost + Toxic cost).
    
    A simple cost function for comparing models:
    - FOMO cost = missed returns we could have captured
    - Toxic cost = losses from false positives
    
    Args:
        error_analysis: Result from analyze_prediction_errors()
        
    Returns:
        Total cost (lower is better)
    """
    fomo_cost = error_analysis['FOMO']['total_missed_return'] if 'total_missed_return' in error_analysis['FOMO'] else 0
    toxic_cost = abs(error_analysis['Toxic']['total_loss']) if 'total_loss' in error_analysis['Toxic'] else 0
    
    return float(fomo_cost + toxic_cost)
