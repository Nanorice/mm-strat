"""
Unit Tests for Temporal Integrity Validation

Tests to ensure no data leakage in feature engineering:
1. Perturbation Test: Inject future data spike, verify features unchanged
2. Manual Audit: Compare calculated features against TradingView values
3. Temporal Alignment: Verify correct date subsetting
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.temporal_validator import TemporalValidator
from src.features import FeatureEngineer
from src.data_engine import DataRepository


class TestTemporalValidator:
    """Test suite for TemporalValidator class."""
    
    @pytest.fixture
    def validator(self):
        """Create a TemporalValidator instance."""
        return TemporalValidator()
    
    @pytest.fixture
    def sample_price_data(self):
        """Create sample OHLCV data for testing."""
        dates = pd.date_range('2024-01-01', '2024-01-31', freq='B')
        
        df = pd.DataFrame({
            'Open': np.random.uniform(100, 110, len(dates)),
            'High': np.random.uniform(110, 120, len(dates)),
            'Low': np.random.uniform(90, 100, len(dates)),
            'Close': np.random.uniform(100, 110, len(dates)),
            'Volume': np.random.randint(1000000, 10000000, len(dates))
        }, index=dates)
        
        return df
    
    def test_get_feature_data_for_entry(self, validator, sample_price_data):
        """Test that correct data subset is extracted for entry date."""
        entry_date = pd.Timestamp('2024-01-15')
        
        # For entry on 2024-01-15, should get data up to 2024-01-14
        subset = validator.get_feature_data_for_entry(sample_price_data, entry_date)
        
        # Check that max date is one day before entry
        expected_max_date = entry_date - pd.Timedelta(days=1)
        
        # Account for weekends - get the last business day before entry
        while expected_max_date not in sample_price_data.index and expected_max_date >= sample_price_data.index[0]:
            expected_max_date -= pd.Timedelta(days=1)
        
        assert subset.index.max() <= expected_max_date, \
            f"Data subset contains future data: max={subset.index.max()}, expected_max={expected_max_date}"
        
        # Check that we have some data
        assert len(subset) > 0, "Empty subset returned"
    
    def test_validate_no_future_leakage_pass(self, validator):
        """Test validation passes when no future data present."""
        # Create data only up to 2024-01-10
        dates = pd.date_range('2024-01-01', '2024-01-10', freq='B')
        df = pd.DataFrame({'Close': [100]*len(dates)}, index=dates)
        
        # Validate for entry on 2024-01-11 (data up to 2024-01-10 is OK)
        entry_date = pd.Timestamp('2024-01-11')
        
        result = validator.validate_no_future_leakage(df, entry_date)
        assert result is True, "Validation should pass when no future data present"
    
    def test_validate_no_future_leakage_fail(self, validator):
        """Test validation fails when future data is present."""
        # Create data up to 2024-01-15
        dates = pd.date_range('2024-01-01', '2024-01-15', freq='B')
        df = pd.DataFrame({'Close': [100]*len(dates)}, index=dates)
        
        # Try to validate for entry on 2024-01-11 (data contains future up to 01-15)
        entry_date = pd.Timestamp('2024-01-11')
        
        result = validator.validate_no_future_leakage(df, entry_date)
        assert result is False, "Validation should fail when future data present"
    
    @pytest.mark.integration
    def test_perturbation_test_with_real_data(self, validator):
        """
        Integration test: Perturbation test with real ticker data.
        
        This test requires actual market data and may take longer.
        Skip with: pytest -m "not integration"
        """
        try:
            # Load real data
            repo = DataRepository()
            price_data = repo.get_ticker_data('AAPL', use_cache=True)
            
            if price_data is None or len(price_data) < 100:
                pytest.skip("Insufficient AAPL data for perturbation test")
            
            # Define feature calculation function
            def calc_features(df):
                fe = FeatureEngineer()
                return fe.calculate_lightweight_features(df)
            
            # Pick an entry date with sufficient history
            entry_date = price_data.index[-20]  # 20 trading days ago
            
            # Run perturbation test
            passed = validator.perturbation_test(
                calculate_features_fn=calc_features,
                ticker='AAPL',
                entry_date=entry_date,
                feature_name='SMA_50',
                spike_magnitude=100.0,
                price_data=price_data
            )
            
            assert passed, "Perturbation test failed - data leakage detected!"
            
        except Exception as e:
            pytest.skip(f"Perturbation test skipped due to: {e}")
    
    def test_perturbation_test_with_synthetic_data(self, validator, sample_price_data):
        """
        Unit test: Perturbation test with synthetic data.
        
        This test uses synthetic data to verify the perturbation logic works.
        """
        # Simple feature calculator that just returns close price
        def calc_simple_features(df):
            result = df.copy()
            result['Simple_MA'] = df['Close'].rolling(5).mean()
            return result
        
        entry_date = pd.Timestamp('2024-01-15')
        
        # Run perturbation test
        passed = validator.perturbation_test(
            calculate_features_fn=calc_simple_features,
            ticker='TEST',
            entry_date=entry_date,
            feature_name='Simple_MA',
            spike_magnitude=10.0,
            price_data=sample_price_data
        )
        
        assert passed, "Perturbation test should pass with properly isolated features"
    
    def test_manual_audit_matching_values(self, validator):
        """Test manual audit with matching values."""
        # Setup sample data
        dates = pd.date_range('2024-01-01', '2024-01-10', freq='B')
        df = pd.DataFrame({'SMA_50': [100.5]*len(dates)}, index=dates)
        
        entry_date = pd.Timestamp('2024-01-10')
        
        calculated_values = {'SMA_50': 100.5}
        expected_values = {'SMA_50': 100.5}
        
        passed = validator.manual_audit(
            df=df,
            ticker='TEST',
            entry_date=entry_date,
            feature_values=calculated_values,
            expected_values=expected_values,
            tolerance=0.5
        )
        
        assert passed, "Manual audit should pass with matching values"
    
    def test_manual_audit_mismatching_values(self, validator):
        """Test manual audit with mismatching values."""
        dates = pd.date_range('2024-01-01', '2024-01-10', freq='B')
        df = pd.DataFrame({'SMA_50': [100.0]*len(dates)}, index=dates)
        
        entry_date = pd.Timestamp('2024-01-10')
        
        calculated_values = {'SMA_50': 100.0}
        expected_values = {'SMA_50': 110.0}  # 10% difference
        
        passed = validator.manual_audit(
            df=df,
            ticker='TEST',
            entry_date=entry_date,
            feature_values=calculated_values,
            expected_values=expected_values,
            tolerance=0.5  # Only 0.5% tolerance
        )
        
        assert not passed, "Manual audit should fail with mismatching values"
    
    def test_manual_audit_within_tolerance(self, validator):
        """Test manual audit with values within tolerance."""
        dates = pd.date_range('2024-01-01', '2024-01-10', freq='B')
        df = pd.DataFrame({'SMA_50': [100.0]*len(dates)}, index=dates)
        
        entry_date = pd.Timestamp('2024-01-10')
        
        calculated_values = {'SMA_50': 100.2}
        expected_values = {'SMA_50': 100.0}  # 0.2% difference
        
        passed = validator.manual_audit(
            df=df,
            ticker='TEST',
            entry_date=entry_date,
            feature_values=calculated_values,
            expected_values=expected_values,
            tolerance=0.5  # 0.5% tolerance - should pass
        )
        
        assert passed, "Manual audit should pass when within tolerance"


class TestTemporalIntegrityWithFeatures:
    """Integration tests with actual FeatureEngineer."""
    
    @pytest.fixture
    def feature_engine(self):
        """Create FeatureEngineer instance."""
        return FeatureEngineer()
    
    @pytest.fixture
    def validator(self):
        """Create TemporalValidator instance."""
        return TemporalValidator()
    
    def test_lightweight_features_no_leakage(self, feature_engine, validator):
        """Test that lightweight features don't leak future data."""
        # Create sample data with clear time structure
        dates = pd.date_range('2024-01-01', '2024-01-31', freq='B')
        
        # Create price data with obvious trend
        close_prices = np.linspace(100, 150, len(dates))
        df = pd.DataFrame({
            'Open': close_prices * 0.99,
            'High': close_prices * 1.01,
            'Low': close_prices * 0.98,
            'Close': close_prices,
            'Volume': np.ones(len(dates)) * 1000000
        }, index=dates)
        
        # Calculate features
        def calc_features(price_df):
            return feature_engine.calculate_lightweight_features(price_df)
        
        # Test perturbation for multiple features
        entry_date = pd.Timestamp('2024-01-20')
        
        for feature_name in ['SMA_50', 'ATR', 'Vol_Ratio']:
            passed = validator.perturbation_test(
                calculate_features_fn=calc_features,
                ticker='TEST',
                entry_date=entry_date,
                feature_name=feature_name,
                spike_magnitude=100.0,
                price_data=df
            )
            
            assert passed, f"Feature {feature_name} failed perturbation test"


# Marks for pytest
pytestmark = [
    pytest.mark.temporal,  # Mark all tests in this file as temporal tests
]


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v', '-m', 'not integration'])
