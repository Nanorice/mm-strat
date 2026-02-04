"""
Unit tests for M03 feature engineering for M01 integration.
Tests generate_m01_features() and verify_m03_features().
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline.m03_regime import M03RegimeCalculator, verify_m03_features


class TestGenerateM01Features(unittest.TestCase):
    """Tests for generate_m01_features method."""

    @classmethod
    def setUpClass(cls):
        """Initialize calculator once for all tests."""
        cls.calc = M03RegimeCalculator()
        # Use a short date range for fast tests
        cls.features_df = cls.calc.generate_m01_features(
            start_date='2024-01-01',
            end_date='2024-01-31',
            freq='D'
        )

    def test_all_columns_exist(self):
        """Verify all 8 expected columns are present."""
        expected = M03RegimeCalculator.M01_FEATURE_COLUMNS
        for col in expected:
            self.assertIn(col, self.features_df.columns, f"Missing column: {col}")

    def test_m03_score_range(self):
        """Verify m03_score is normalized between 0.0 and 1.0."""
        score = self.features_df['m03_score'].dropna()
        self.assertTrue((score >= 0.0).all(), "m03_score should be >= 0.0")
        self.assertTrue((score <= 1.0).all(), "m03_score should be <= 1.0")

    def test_m03_regime_cat_values(self):
        """Verify m03_regime_cat contains only ordinal values 0-4."""
        cat = self.features_df['m03_regime_cat'].dropna()
        valid_values = {0, 1, 2, 3, 4}
        actual_values = set(cat.unique())
        self.assertTrue(actual_values.issubset(valid_values),
                        f"Invalid category values: {actual_values - valid_values}")

    def test_m03_delta_range(self):
        """Verify delta features are within -1.0 to 1.0 range."""
        for col in ['m03_delta_5d', 'm03_delta_20d']:
            data = self.features_df[col].dropna()
            self.assertTrue((data >= -1.0).all(), f"{col} should be >= -1.0")
            self.assertTrue((data <= 1.0).all(), f"{col} should be <= 1.0")

    def test_m03_regime_vol_clipped(self):
        """Verify m03_regime_vol is clipped between 0.0 and 1.0."""
        vol = self.features_df['m03_regime_vol'].dropna()
        self.assertTrue((vol >= 0.0).all(), "m03_regime_vol should be >= 0.0")
        self.assertTrue((vol <= 1.0).all(), "m03_regime_vol should be <= 1.0")

    def test_pillar_ranges(self):
        """Verify pillar features are between 0.0 and 1.0."""
        for col in ['m03_pillar_trend', 'm03_pillar_liq', 'm03_pillar_risk']:
            data = self.features_df[col].dropna()
            self.assertTrue((data >= 0.0).all(), f"{col} should be >= 0.0")
            self.assertTrue((data <= 1.0).all(), f"{col} should be <= 1.0")


class TestVerifyM03Features(unittest.TestCase):
    """Tests for verify_m03_features function."""

    def test_existence_check_passes(self):
        """Verify existence check passes with all columns present."""
        df = pd.DataFrame({
            'm03_score': [0.5],
            'm03_regime_cat': [2],
            'm03_delta_5d': [0.0],
            'm03_delta_20d': [0.0],
            'm03_regime_vol': [0.1],
            'm03_pillar_trend': [0.6],
            'm03_pillar_liq': [0.5],
            'm03_pillar_risk': [0.7],
        })
        result = verify_m03_features(df, raise_on_error=False)
        self.assertTrue(result['existence']['passed'])

    def test_existence_check_fails(self):
        """Verify existence check catches missing columns."""
        df = pd.DataFrame({
            'm03_score': [0.5],
            # Missing all other columns
        })
        result = verify_m03_features(df, raise_on_error=False)
        self.assertFalse(result['existence']['passed'])
        self.assertEqual(len(result['existence']['missing']), 7)

    def test_existence_check_raises(self):
        """Verify existence check raises ValueError when requested."""
        df = pd.DataFrame({'m03_score': [0.5]})
        with self.assertRaises(ValueError):
            verify_m03_features(df, raise_on_error=True)

    def test_null_check_reports_nans(self):
        """Verify null check reports NaN counts."""
        df = pd.DataFrame({
            'm03_score': [0.5, np.nan, 0.6],
            'm03_regime_cat': [2, 3, np.nan],
            'm03_delta_5d': [0.0, 0.0, 0.0],
            'm03_delta_20d': [0.0, 0.0, 0.0],
            'm03_regime_vol': [0.1, 0.1, 0.1],
            'm03_pillar_trend': [0.6, 0.6, 0.6],
            'm03_pillar_liq': [0.5, 0.5, 0.5],
            'm03_pillar_risk': [0.7, 0.7, 0.7],
        })
        result = verify_m03_features(df, raise_on_error=False)
        self.assertFalse(result['nulls']['passed'])
        self.assertEqual(result['nulls']['total'], 2)
        self.assertIn('m03_score', result['nulls']['counts'])
        self.assertIn('m03_regime_cat', result['nulls']['counts'])

    def test_range_check_catches_out_of_bounds(self):
        """Verify range check catches values outside expected bounds."""
        df = pd.DataFrame({
            'm03_score': [1.5],  # Out of range!
            'm03_regime_cat': [2],
            'm03_delta_5d': [0.0],
            'm03_delta_20d': [0.0],
            'm03_regime_vol': [0.1],
            'm03_pillar_trend': [0.6],
            'm03_pillar_liq': [0.5],
            'm03_pillar_risk': [0.7],
        })
        result = verify_m03_features(df, raise_on_error=False)
        self.assertFalse(result['range']['passed'])
        self.assertIn('m03_score', result['range']['violations'])

    def test_range_check_raises(self):
        """Verify range check raises ValueError when requested."""
        df = pd.DataFrame({
            'm03_score': [65.0],  # Not normalized!
            'm03_regime_cat': [2],
            'm03_delta_5d': [0.0],
            'm03_delta_20d': [0.0],
            'm03_regime_vol': [0.1],
            'm03_pillar_trend': [0.6],
            'm03_pillar_liq': [0.5],
            'm03_pillar_risk': [0.7],
        })
        with self.assertRaises(ValueError):
            verify_m03_features(df, raise_on_error=True)

    def test_all_checks_pass(self):
        """Verify all checks pass with valid data."""
        df = pd.DataFrame({
            'm03_score': [0.5, 0.6, 0.7],
            'm03_regime_cat': [2, 3, 3],
            'm03_delta_5d': [0.0, 0.01, -0.02],
            'm03_delta_20d': [0.0, 0.05, -0.03],
            'm03_regime_vol': [0.1, 0.15, 0.12],
            'm03_pillar_trend': [0.6, 0.65, 0.7],
            'm03_pillar_liq': [0.5, 0.5, 0.5],
            'm03_pillar_risk': [0.7, 0.75, 0.8],
        })
        result = verify_m03_features(df, raise_on_error=True)
        self.assertTrue(result['passed'])
        self.assertTrue(result['existence']['passed'])
        self.assertTrue(result['nulls']['passed'])
        self.assertTrue(result['range']['passed'])


if __name__ == '__main__':
    unittest.main()
