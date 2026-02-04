"""
Unit tests for FeaturePreprocessor.

Tests the fit/transform pattern for consistent preprocessing between training and inference.
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import tempfile
import json

from src.feature_preprocessor import FeaturePreprocessor, EXPLOSIVE_FEATURES, STANDARD_FEATURES


@pytest.fixture
def sample_data():
    """Create sample data with various feature types."""
    np.random.seed(42)
    n = 2000
    
    return pd.DataFrame({
        # Explosive feature (should get log transform)
        'volume_acceleration': np.concatenate([
            np.random.normal(0, 1, n - 10),
            np.array([50, -50, 100, -100, 150, -150, 200, -200, 250, -250])  # Outliers
        ]),
        # Standard feature (should get winsorized)
        'RSI_14': np.concatenate([
            np.random.normal(50, 10, n - 10),
            np.array([150, -50, 200, -100, 250, -150, 300, -200, 350, -250])  # Outliers
        ]),
        # Unknown feature (TAR-based decision)
        'unknown_feature': np.concatenate([
            np.random.normal(0, 1, n - 10),
            np.array([10, -10, 20, -20, 30, -30, 40, -40, 50, -50])  # Mild outliers
        ]),
        # Target
        'return_pct': np.random.normal(0.01, 0.05, n)
    })


class TestFeaturePreprocessorFit:
    """Tests for the fit() method."""
    
    def test_fit_returns_self(self, sample_data):
        """fit() should return self for method chaining."""
        preprocessor = FeaturePreprocessor()
        result = preprocessor.fit(sample_data, ['volume_acceleration', 'RSI_14'])
        assert result is preprocessor
    
    def test_fit_sets_is_fitted(self, sample_data):
        """fit() should set is_fitted to True."""
        preprocessor = FeaturePreprocessor()
        assert not preprocessor.is_fitted
        preprocessor.fit(sample_data, ['volume_acceleration', 'RSI_14'])
        assert preprocessor.is_fitted
    
    def test_fit_explosive_feature_marked_for_log(self, sample_data):
        """Explosive features should be marked for log transform."""
        preprocessor = FeaturePreprocessor()
        preprocessor.fit(sample_data, ['volume_acceleration'])
        
        assert 'volume_acceleration' in preprocessor.config['features']
        assert preprocessor.config['features']['volume_acceleration']['transform'] == 'log'
    
    def test_fit_standard_feature_marked_for_winsorize(self, sample_data):
        """Standard features should be marked for winsorization."""
        preprocessor = FeaturePreprocessor()
        preprocessor.fit(sample_data, ['RSI_14'])
        
        assert 'RSI_14' in preprocessor.config['features']
        assert preprocessor.config['features']['RSI_14']['transform'] == 'winsorize'
        assert 'lower_bound' in preprocessor.config['features']['RSI_14']
        assert 'upper_bound' in preprocessor.config['features']['RSI_14']


class TestFeaturePreprocessorTransform:
    """Tests for the transform() method."""
    
    def test_transform_requires_fitted(self, sample_data):
        """transform() should raise error if not fitted."""
        preprocessor = FeaturePreprocessor()
        with pytest.raises(ValueError, match="not fitted"):
            preprocessor.transform(sample_data)
    
    def test_transform_creates_log_prefixed_column(self, sample_data):
        """Log-transformed features should get log_ prefix."""
        preprocessor = FeaturePreprocessor()
        preprocessor.fit(sample_data, ['volume_acceleration'])
        
        result = preprocessor.transform(sample_data)
        
        assert 'log_volume_acceleration' in result.columns
        assert 'volume_acceleration' in result.columns  # Original kept
    
    def test_transform_winsorize_clips_values(self, sample_data):
        """Winsorized features should have clipped values."""
        preprocessor = FeaturePreprocessor()
        preprocessor.fit(sample_data, ['RSI_14'])
        
        original_max = sample_data['RSI_14'].max()
        result = preprocessor.transform(sample_data)
        
        # Should be clipped
        assert result['RSI_14'].max() < original_max
    
    def test_transform_returns_new_dataframe(self, sample_data):
        """transform() should return a new DataFrame by default."""
        preprocessor = FeaturePreprocessor()
        preprocessor.fit(sample_data, ['volume_acceleration'])
        
        result = preprocessor.transform(sample_data)
        
        assert result is not sample_data


class TestFeaturePreprocessorSaveLoad:
    """Tests for save() and load() methods."""
    
    def test_save_creates_file(self, sample_data):
        """save() should create a JSON file."""
        preprocessor = FeaturePreprocessor()
        preprocessor.fit(sample_data, ['volume_acceleration', 'RSI_14'])
        
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / 'test_config.json'
            preprocessor.save(str(path))
            
            assert path.exists()
    
    def test_load_restores_config(self, sample_data):
        """load() should restore the configuration."""
        preprocessor = FeaturePreprocessor()
        preprocessor.fit(sample_data, ['volume_acceleration', 'RSI_14'])
        
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / 'test_config.json'
            preprocessor.save(str(path))
            
            loaded = FeaturePreprocessor.load(str(path))
            
            assert loaded.is_fitted
            assert 'volume_acceleration' in loaded.config['features']
            assert 'RSI_14' in loaded.config['features']
    
    def test_roundtrip_produces_same_transform(self, sample_data):
        """Save/load should produce identical transforms."""
        preprocessor = FeaturePreprocessor()
        preprocessor.fit(sample_data, ['volume_acceleration', 'RSI_14'])
        
        original = preprocessor.transform(sample_data)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / 'test_config.json'
            preprocessor.save(str(path))
            
            loaded = FeaturePreprocessor.load(str(path))
            reloaded = loaded.transform(sample_data)
            
            pd.testing.assert_frame_equal(original, reloaded)


class TestGetTransformedFeatureNames:
    """Tests for get_transformed_feature_names() method."""
    
    def test_log_features_get_prefix(self, sample_data):
        """Log-transformed features should get log_ prefix in names."""
        preprocessor = FeaturePreprocessor()
        preprocessor.fit(sample_data, ['volume_acceleration', 'RSI_14'])
        
        result = preprocessor.get_transformed_feature_names(['volume_acceleration', 'RSI_14'])
        
        assert 'log_volume_acceleration' in result
        assert 'RSI_14' in result  # Winsorized, no prefix
    
    def test_untransformed_features_unchanged(self, sample_data):
        """Features not in config should be returned unchanged."""
        preprocessor = FeaturePreprocessor()
        preprocessor.fit(sample_data, ['volume_acceleration'])
        
        result = preprocessor.get_transformed_feature_names(['volume_acceleration', 'other_feature'])
        
        assert 'log_volume_acceleration' in result
        assert 'other_feature' in result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
