"""
Unit tests for src/evaluation/metrics.py
=========================================

Tests for IC, Precision@K, Recall@K, Lift, and Volatility Correlation.
"""

import numpy as np
import pandas as pd
import pytest
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.evaluation.metrics import (
    calculate_ic,
    calculate_precision_at_k,
    calculate_recall_at_k,
    calculate_decile_lift,
    calculate_volatility_correlation
)


class TestCalculateIC:
    """Tests for calculate_ic function."""
    
    def test_perfect_positive_correlation(self):
        """IC should be 1.0 for perfectly correlated data."""
        y_true = np.array([1, 2, 3, 4, 5])
        y_pred = np.array([1, 2, 3, 4, 5])
        
        ic, p_value = calculate_ic(y_true, y_pred)
        
        assert ic == pytest.approx(1.0, abs=0.01)
        assert p_value < 0.05
    
    def test_perfect_negative_correlation(self):
        """IC should be -1.0 for inversely correlated data."""
        y_true = np.array([1, 2, 3, 4, 5])
        y_pred = np.array([5, 4, 3, 2, 1])
        
        ic, p_value = calculate_ic(y_true, y_pred)
        
        assert ic == pytest.approx(-1.0, abs=0.01)
    
    def test_random_correlation(self):
        """IC should be near 0 for random data."""
        np.random.seed(42)
        y_true = np.random.randn(100)
        y_pred = np.random.randn(100)
        
        ic, p_value = calculate_ic(y_true, y_pred)
        
        assert abs(ic) < 0.3  # Should be close to 0
    
    def test_constant_predictions(self):
        """IC should be 0 for constant predictions."""
        y_true = np.array([1, 2, 3, 4, 5])
        y_pred = np.array([3, 3, 3, 3, 3])
        
        ic, p_value = calculate_ic(y_true, y_pred)
        
        assert ic == 0.0
        assert p_value == 1.0
    
    def test_too_few_samples(self):
        """IC should handle edge case of too few samples."""
        y_true = np.array([1, 2])
        y_pred = np.array([1, 2])
        
        ic, p_value = calculate_ic(y_true, y_pred)
        
        assert ic == 0.0  # Defaults to 0 for < 3 samples


class TestPrecisionAtK:
    """Tests for calculate_precision_at_k function."""
    
    def test_perfect_precision(self):
        """Precision should be 1.0 when all top predictions are winners."""
        # Create data where top 10% of predictions are all actual top 30%
        y_pred = np.array([10, 9, 8, 7, 6, 5, 4, 3, 2, 1])
        y_true = np.array([100, 90, 80, 70, 60, 50, 40, 30, 20, 10])
        
        precision = calculate_precision_at_k(y_true, y_pred, k=0.1, winner_threshold=0.70)
        
        assert precision == 1.0
    
    def test_low_precision(self):
        """Precision should be < 1.0 when predictions don't match actuals."""
        # Create data where predictions invert actuals
        y_pred = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        y_true = np.array([100, 90, 80, 70, 60, 50, 40, 30, 20, 10])
        
        precision = calculate_precision_at_k(y_true, y_pred, k=0.1, winner_threshold=0.70)
        
        assert precision == 0.0  # Top prediction is worst actual


class TestRecallAtK:
    """Tests for calculate_recall_at_k function."""
    
    def test_high_recall(self):
        """Recall should be high when we capture super performers."""
        # Top super performer (index 0) has high prediction too
        y_pred = np.array([10, 9, 8, 7, 6, 5, 4, 3, 2, 1])
        y_true = np.array([100, 90, 80, 70, 60, 50, 40, 30, 20, 10])
        
        recall = calculate_recall_at_k(y_true, y_pred, k=0.2, top_class_pct=0.1)
        
        assert recall == 1.0  # Captured the 1 super performer in top 20%


class TestDecileLift:
    """Tests for calculate_decile_lift function."""
    
    def test_positive_lift(self):
        """Lift > 1.0 when top decile outperforms average."""
        # Top predictions have highest actuals
        y_pred = np.array([10, 9, 8, 7, 6, 5, 4, 3, 2, 1])
        y_true = np.array([100, 90, 80, 70, 60, 50, 40, 30, 20, 10])
        
        lift = calculate_decile_lift(y_true, y_pred, top_pct=0.1)
        
        assert lift > 1.0
    
    def test_no_differentiation(self):
        """Lift can vary for random predictions, but should be bounded."""
        np.random.seed(42)
        y_true = np.random.randn(100)
        y_pred = np.random.randn(100)
        
        lift = calculate_decile_lift(y_true, y_pred, top_pct=0.1)
        
        # Random data can produce variable lift, just check it's bounded
        assert 0.0 < lift < 5.0  # Reasonable bounds for random data


class TestVolatilityCorrelation:
    """Tests for calculate_volatility_correlation function."""
    
    def test_high_vol_correlation(self):
        """Should detect volatility detector when predictions correlate with ATR."""
        # Need > 10 samples for correlation to be computed
        df = pd.DataFrame({
            'y_pred': list(range(1, 21)),  # 20 samples
            'nATR': list(range(1, 21))  # Same as predictions
        })
        
        result = calculate_volatility_correlation(df)
        
        assert result['is_vol_detector'] == True
        assert result['max_vol_corr'] > 0.9
    
    def test_no_vol_correlation(self):
        """Should not flag as vol detector when low correlation."""
        np.random.seed(42)
        df = pd.DataFrame({
            'y_pred': np.random.randn(100),
            'nATR': np.random.randn(100)
        })
        
        result = calculate_volatility_correlation(df)
        
        assert result['is_vol_detector'] == False
        assert result['max_vol_corr'] < 0.5
    
    def test_missing_columns(self):
        """Should handle missing volatility columns gracefully."""
        df = pd.DataFrame({
            'y_pred': [1, 2, 3],
            'other_col': [1, 2, 3]
        })
        
        result = calculate_volatility_correlation(df)
        
        assert result['is_vol_detector'] == False
        assert result['max_vol_corr'] == 0.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
