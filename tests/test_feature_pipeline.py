"""Tests for src/feature_pipeline.py pure helpers.

The A/B/C phase tests were deleted 2026-07-19: they drove `compute_base_features`
into a `daily_features` table, both of which were removed when the pipeline split
into t2_screener_features + t3_sepa_features. See the replacement plan in
docs/session_logs/sprint_15/.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest

import numpy as np
import pandas as pd

from src.feature_pipeline import FeaturePipeline


class TestSanitizeAlpha(unittest.TestCase):
    """Test alpha sanitization logic."""

    def test_removes_inf(self):
        s = pd.Series([1.0, np.inf, -np.inf, 2.0, np.nan])
        result = FeaturePipeline._sanitize_alpha(s, 'test')
        self.assertTrue(np.all(np.isfinite(result)))

    def test_fills_nan_with_zero(self):
        s = pd.Series([np.nan, np.nan, 1.0])
        result = FeaturePipeline._sanitize_alpha(s, 'test')
        self.assertEqual(result.isna().sum(), 0)

    def test_clips_outliers(self):
        s = pd.Series(list(range(1000)) + [999999])
        result = FeaturePipeline._sanitize_alpha(s, 'test')
        self.assertLess(result.max(), 999999)


class TestHelpers(unittest.TestCase):
    """Test ts_rank, ts_argmax, scale helpers."""

    def test_ts_argmax(self):
        s = pd.Series([1, 3, 2, 5, 4])
        result = FeaturePipeline._ts_argmax(s, 3)
        # Window [2, 5, 4]: max=5 at position 2 (1-indexed)
        self.assertEqual(result.iloc[4], 2.0)

    def test_ts_rank(self):
        s = pd.Series([10, 20, 30, 40, 50])
        result = FeaturePipeline._ts_rank(s, 5)
        # Last value (50) is largest in window → rank should be 1.0
        self.assertEqual(result.iloc[4], 1.0)

    def test_scale(self):
        s = pd.Series([1.0, -2.0, 3.0])
        result = FeaturePipeline._scale(s)
        self.assertAlmostEqual(result.abs().sum(), 1.0, places=5)

    def test_scale_zero(self):
        s = pd.Series([0.0, 0.0, 0.0])
        result = FeaturePipeline._scale(s)
        self.assertEqual(result.sum(), 0.0)


if __name__ == '__main__':
    unittest.main()
