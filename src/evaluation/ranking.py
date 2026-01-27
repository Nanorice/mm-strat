"""
Ranking analysis utilities for regression models.
==================================================

Provides decile analysis and quantile ranking utilities.
These are THE critical diagnostics for trading models.
"""

import pandas as pd
import numpy as np
from typing import Dict, List


def analyze_deciles(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    n_deciles: int = 10
) -> Dict:
    """
    Analyze predictions by decile - THE critical trading model diagnostic.
    
    Groups predictions into deciles and measures actual performance of each.
    A good model should show monotonically increasing returns from D1 to D10.
    
    Args:
        y_true: Actual values
        y_pred: Predicted values
        n_deciles: Number of quantile bins (default 10 = deciles)
        
    Returns:
        {
            'overall_mean': float,
            'top_decile_mean': float,
            'top_2_deciles_mean': float,
            'selection_edge': float,  # Top decile - Overall
            'top2_edge': float,
            'decile_breakdown': pd.DataFrame  # Per-decile stats
        }
    """
    df = pd.DataFrame({
        'actual': y_true if isinstance(y_true, np.ndarray) else y_true.values,
        'predicted': y_pred
    })
    
    # Handle edge cases
    if len(df) < n_deciles:
        return {
            'overall_mean': float(df['actual'].mean()),
            'top_decile_mean': float(df['actual'].mean()),
            'top_2_deciles_mean': float(df['actual'].mean()),
            'selection_edge': 0.0,
            'top2_edge': 0.0,
            'decile_breakdown': pd.DataFrame()
        }
    
    # Create deciles with duplicate handling
    try:
        df['decile'] = pd.qcut(df['predicted'], n_deciles, labels=False, duplicates='drop')
    except ValueError:
        # Fall back to fewer bins if needed
        try:
            df['decile'] = pd.qcut(df['predicted'], min(5, n_deciles), labels=False, duplicates='drop')
        except ValueError:
            df['decile'] = 0
    
    # Calculate statistics
    overall_mean = df['actual'].mean()
    max_decile = df['decile'].max()
    
    top_decile = df[df['decile'] == max_decile]
    top_decile_mean = top_decile['actual'].mean() if len(top_decile) > 0 else overall_mean
    
    top_2_deciles = df[df['decile'] >= max_decile - 1]
    top_2_mean = top_2_deciles['actual'].mean() if len(top_2_deciles) > 0 else overall_mean
    
    # Calculate per-decile breakdown
    decile_breakdown = df.groupby('decile').agg({
        'actual': ['mean', 'median', 'std', 'count']
    }).reset_index()
    decile_breakdown.columns = ['decile', 'mean', 'median', 'std', 'count']
    decile_breakdown['decile'] = decile_breakdown['decile'] + 1  # 1-indexed for display
    
    return {
        'overall_mean': float(overall_mean),
        'top_decile_mean': float(top_decile_mean),
        'top_2_deciles_mean': float(top_2_mean),
        'selection_edge': float(top_decile_mean - overall_mean),
        'top2_edge': float(top_2_mean - overall_mean),
        'decile_breakdown': decile_breakdown
    }


def calculate_quantile_stats(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    quantiles: List[float] = None
) -> pd.DataFrame:
    """
    Calculate return statistics for prediction quantiles.
    
    Useful for understanding model behavior at different threshold levels.
    
    Args:
        y_true: Actual values
        y_pred: Predicted values
        quantiles: List of quantile thresholds (default: [0.1, 0.2, 0.3, 0.5])
        
    Returns:
        DataFrame with columns: quantile, threshold, mean_return, count, edge
    """
    if quantiles is None:
        quantiles = [0.1, 0.2, 0.3, 0.5]
    
    df = pd.DataFrame({
        'actual': y_true if isinstance(y_true, np.ndarray) else y_true.values,
        'predicted': y_pred
    })
    
    overall_mean = df['actual'].mean()
    
    results = []
    for q in quantiles:
        threshold = df['predicted'].quantile(1 - q)
        selected = df[df['predicted'] >= threshold]
        
        if len(selected) > 0:
            mean_return = selected['actual'].mean()
            results.append({
                'quantile': f'Top {int(q*100)}%',
                'threshold': float(threshold),
                'mean_return': float(mean_return),
                'count': int(len(selected)),
                'edge': float(mean_return - overall_mean)
            })
    
    return pd.DataFrame(results)


def calculate_monotonicity_score(decile_means: List[float]) -> float:
    """
    Calculate monotonicity score for decile performance.
    
    A perfect model has strictly increasing returns from D1 to D10.
    This measures how close to perfect monotonicity we are.
    
    Args:
        decile_means: List of mean returns per decile (D1 to D10)
        
    Returns:
        Score from 0.0 (no monotonicity) to 1.0 (perfect monotonicity)
    """
    if len(decile_means) < 2:
        return 0.0
    
    n_pairs = len(decile_means) - 1
    n_correct = sum(
        1 for i in range(n_pairs) 
        if decile_means[i+1] > decile_means[i]
    )
    
    return float(n_correct / n_pairs)
