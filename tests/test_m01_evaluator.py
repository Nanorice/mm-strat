"""
Unit tests for src/evaluation/m01_evaluator.py
==============================================

Tests for M01Evaluator class including fold evaluation and full metrics.
"""

import numpy as np
import pandas as pd
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.evaluation.m01_evaluator import M01Evaluator


class TestM01Evaluator:
    """Tests for M01Evaluator class."""
    
    @pytest.fixture
    def evaluator(self, tmp_path):
        """Create evaluator with temporary output directory."""
        return M01Evaluator(target_type='return_pct', output_dir=tmp_path)
    
    @pytest.fixture
    def sample_data(self):
        """Create sample predictions data."""
        np.random.seed(42)
        n = 100
        return {
            'y_true': pd.Series(np.random.randn(n) * 5 + 2),  # Mean ~2%
            'y_pred': np.random.randn(n) * 3 + 2
        }
    
    def test_evaluate_fold_returns_metrics(self, evaluator, sample_data):
        """Fold evaluation should return expected metrics."""
        metrics = evaluator.evaluate_fold(
            y_true=sample_data['y_true'],
            y_pred=sample_data['y_pred'],
            test_year=2023,
            n_train=500,
            n_test=100
        )
        
        # Check all expected keys are present
        expected_keys = [
            'test_year', 'train_samples', 'test_samples',
            'rmse', 'mae', 'ic', 'ic_pvalue',
            'selection_edge', 'top_decile_mean', 'top2_edge',
            'top_decile_lift', 'precision_at_10', 'recall_at_10_for_top5'
        ]
        
        for key in expected_keys:
            assert key in metrics, f"Missing key: {key}"
        
        assert metrics['test_year'] == 2023
        assert metrics['train_samples'] == 500
        assert metrics['test_samples'] == 100
    
    def test_evaluate_fold_stores_metrics(self, evaluator, sample_data):
        """Fold evaluation should store metrics in list."""
        evaluator.evaluate_fold(
            y_true=sample_data['y_true'],
            y_pred=sample_data['y_pred'],
            test_year=2023,
            n_train=500,
            n_test=100
        )
        
        assert len(evaluator.fold_metrics_list) == 1
    
    def test_add_predictions(self, evaluator):
        """add_predictions should accumulate prediction data."""
        df1 = pd.DataFrame({'y_pred': [1, 2], 'y_true': [1.1, 2.1]})
        df2 = pd.DataFrame({'y_pred': [3, 4], 'y_true': [3.1, 4.1]})
        
        evaluator.add_predictions(df1)
        evaluator.add_predictions(df2)
        
        assert len(evaluator.predictions_df) == 4
    
    def test_evaluate_full_returns_aggregates(self, evaluator, sample_data):
        """Full evaluation should return aggregate metrics."""
        # Add multiple folds
        for year in [2021, 2022, 2023]:
            evaluator.evaluate_fold(
                y_true=sample_data['y_true'],
                y_pred=sample_data['y_pred'],
                test_year=year,
                n_train=500,
                n_test=100
            )
        
        full_metrics = evaluator.evaluate_full()
        
        # Check aggregate keys
        assert 'avg_ic' in full_metrics
        assert 'ic_sharpe' in full_metrics
        assert 'ic_consistency' in full_metrics
        assert 'avg_selection_edge' in full_metrics
        assert 'edge_sharpe' in full_metrics
        assert 'n_folds' in full_metrics
        
        assert full_metrics['n_folds'] == 3
        assert full_metrics['total_test_samples'] == 300
    
    def test_evaluate_full_empty_returns_empty(self, evaluator):
        """Full evaluation with no folds should return empty dict."""
        result = evaluator.evaluate_full()
        assert result == {}
    
    def test_get_fold_metrics_df(self, evaluator, sample_data):
        """get_fold_metrics_df should return DataFrame."""
        evaluator.evaluate_fold(
            y_true=sample_data['y_true'],
            y_pred=sample_data['y_pred'],
            test_year=2023,
            n_train=500,
            n_test=100
        )
        
        df = evaluator.get_fold_metrics_df()
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert 'test_year' in df.columns
    
    def test_reset_clears_state(self, evaluator, sample_data):
        """reset should clear all stored data."""
        evaluator.evaluate_fold(
            y_true=sample_data['y_true'],
            y_pred=sample_data['y_pred'],
            test_year=2023,
            n_train=500,
            n_test=100
        )
        evaluator.add_predictions(pd.DataFrame({'y_pred': [1], 'y_true': [1]}))
        
        evaluator.reset()
        
        assert len(evaluator.fold_metrics_list) == 0
        assert len(evaluator.predictions_df) == 0
    
    def test_export_viz_data(self, evaluator, sample_data):
        """export_viz_data should return visualization data."""
        # Add predictions
        df = pd.DataFrame({
            'y_pred': sample_data['y_pred'],
            'y_true': sample_data['y_true'].values
        })
        evaluator.add_predictions(df)
        
        viz_data = evaluator.export_viz_data()
        
        assert 'decile_performance' in viz_data
        assert 'scatter_sample' in viz_data
        assert 'error_breakdown' in viz_data
    
    def test_extract_feature_importance(self, evaluator):
        """_extract_feature_importance should work with mock model."""
        mock_model = MagicMock()
        mock_model.feature_importances_ = np.array([0.5, 0.3, 0.2])
        
        features = ['feature_a', 'feature_b', 'feature_c']
        
        importance_df = evaluator._extract_feature_importance(mock_model, features)
        
        assert len(importance_df) == 3
        assert 'feature' in importance_df.columns
        assert 'gain' in importance_df.columns
        assert 'rank' in importance_df.columns


class TestM01EvaluatorIntegration:
    """Integration tests for M01Evaluator."""
    
    def test_full_evaluation_pipeline(self, tmp_path):
        """Test complete evaluation pipeline."""
        evaluator = M01Evaluator(target_type='return_pct', output_dir=tmp_path)
        
        np.random.seed(42)
        
        # Simulate walk-forward validation
        for year in [2020, 2021, 2022, 2023]:
            n = 200
            y_true = pd.Series(np.random.randn(n) * 5 + 3)
            y_pred = y_true.values + np.random.randn(n) * 2  # Correlated predictions
            
            metrics = evaluator.evaluate_fold(
                y_true=y_true,
                y_pred=y_pred,
                test_year=year,
                n_train=600,
                n_test=n
            )
            
            # Store predictions
            df = pd.DataFrame({
                'y_pred': y_pred,
                'y_true': y_true.values,
                'year': year
            })
            evaluator.add_predictions(df)
        
        # Get full metrics
        full_metrics = evaluator.evaluate_full()
        
        # Validate metrics make sense
        assert full_metrics['n_folds'] == 4
        assert full_metrics['avg_ic'] > 0  # Should be positive since correlated
        assert 0 <= full_metrics['ic_consistency'] <= 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
