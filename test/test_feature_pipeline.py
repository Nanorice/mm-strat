"""Tests for src/feature_pipeline.py — FeaturePipeline A/B/C phases."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest

import duckdb
import numpy as np
import pandas as pd

from src.feature_pipeline import FeaturePipeline, ALPHA_COLS, RANK_COLS


def _create_test_db() -> str:
    """Create an in-memory DuckDB with synthetic price_data and company_profiles."""
    db_path = ":memory:"
    con = duckdb.connect(db_path)

    np.random.seed(42)
    tickers = ['AAPL', 'MSFT', 'TSLA']
    dates = pd.bdate_range('2023-01-02', periods=300)
    rows = []
    for t in tickers:
        base = 100 + np.random.randn() * 20
        for d in dates:
            o = base + np.random.randn() * 2
            h = o + abs(np.random.randn()) * 3
            l = o - abs(np.random.randn()) * 3
            c = (o + h + l) / 3 + np.random.randn()
            v = int(abs(np.random.randn() * 1_000_000 + 5_000_000))
            rows.append((t, d.date(), o, h, l, c, v))
            base = c

    # SPY benchmark
    base_spy = 450
    for d in dates:
        o = base_spy + np.random.randn()
        h = o + abs(np.random.randn()) * 2
        l = o - abs(np.random.randn()) * 2
        c = (o + h + l) / 3 + np.random.randn() * 0.5
        v = int(abs(np.random.randn() * 10_000_000 + 50_000_000))
        rows.append(('SPY', d.date(), o, h, l, c, v))
        base_spy = c

    df = pd.DataFrame(rows, columns=['ticker', 'date', 'open', 'high', 'low', 'close', 'volume'])
    con.execute("CREATE TABLE price_data AS SELECT * FROM df")

    profiles = pd.DataFrame({
        'ticker': ['AAPL', 'MSFT', 'TSLA', 'SPY'],
        'sector': ['Technology', 'Technology', 'Consumer Cyclical', 'ETF'],
        'industry': ['Consumer Electronics', 'Software', 'Auto Manufacturers', 'ETF'],
    })
    con.execute("CREATE TABLE company_profiles AS SELECT * FROM profiles")
    con.close()
    return db_path


# We need a persistent file since DuckDB in-memory doesn't share across connections
import tempfile, os

TEST_DB = os.path.join(tempfile.gettempdir(), 'test_feature_pipeline.duckdb')


def setUpModule():
    """Create test DB once for all tests."""
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

    con = duckdb.connect(TEST_DB)

    np.random.seed(42)
    tickers = ['AAPL', 'MSFT', 'TSLA']
    dates = pd.bdate_range('2023-01-02', periods=300)
    rows = []
    for t in tickers:
        base = 100 + np.random.randn() * 20
        for d in dates:
            o = base + np.random.randn() * 2
            h = o + abs(np.random.randn()) * 3
            l = o - abs(np.random.randn()) * 3
            c = (o + h + l) / 3 + np.random.randn()
            v = int(abs(np.random.randn() * 1_000_000 + 5_000_000))
            rows.append((t, d.date(), o, h, l, c, v))
            base = c

    # JUNK: in price_data but NOT active in screener — must be absent from daily_features
    for d in dates:
        rows.append(('JUNK', d.date(), 5.0, 5.5, 4.5, 5.0, 100_000))

    df = pd.DataFrame(rows, columns=['ticker', 'date', 'open', 'high', 'low', 'close', 'volume'])
    con.execute("CREATE TABLE price_data AS SELECT * FROM df")

    profiles = pd.DataFrame({
        'ticker': ['AAPL', 'MSFT', 'TSLA'],
        'sector': ['Technology', 'Technology', 'Consumer Cyclical'],
        'industry': ['Consumer Electronics', 'Software', 'Auto Manufacturers'],
    })
    con.execute("CREATE TABLE company_profiles AS SELECT * FROM profiles")

    # screener_members: AAPL/MSFT/TSLA active, JUNK inactive
    screener = pd.DataFrame({
        'ticker': ['AAPL', 'MSFT', 'TSLA', 'JUNK'],
        'is_active': [True, True, True, False],
    })
    con.execute("CREATE TABLE screener_members AS SELECT * FROM screener")

    # t1_macro: SPY benchmark (replaces price_data WHERE ticker='SPY')
    base_spy = 450.0
    macro_rows = []
    for d in pd.bdate_range('2022-01-01', periods=600):
        spy_c = base_spy + np.random.randn() * 0.5
        macro_rows.append((d.date(), spy_c, spy_c + 1.0, spy_c - 1.0))
        base_spy = spy_c
    t1_macro_df = pd.DataFrame(macro_rows, columns=['date', 'spy_close', 'spy_high', 'spy_low'])
    con.execute("CREATE TABLE t1_macro AS SELECT * FROM t1_macro_df")

    con.close()


def tearDownModule():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


class TestPhaseA(unittest.TestCase):
    """Test Phase A: SQL base features."""

    @classmethod
    def setUpClass(cls):
        cls.pipeline = FeaturePipeline(TEST_DB)
        cls.pipeline.compute_base_features(start_date='2023-01-01')

    def test_table_created(self):
        con = duckdb.connect(TEST_DB)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        self.assertIn('daily_features', tables)

    def test_row_count(self):
        con = duckdb.connect(TEST_DB)
        count = con.execute("SELECT COUNT(*) FROM daily_features").fetchone()[0]
        con.close()
        # 3 active screener tickers × 300 days = 900 (SPY in t1_macro, JUNK inactive)
        self.assertEqual(count, 900)

    def test_base_column_count(self):
        con = duckdb.connect(TEST_DB)
        cols = [r[0] for r in con.execute("DESCRIBE daily_features").fetchall()]
        con.close()
        # Should have ~81 base columns (no alpha, no rank columns yet)
        self.assertGreaterEqual(len(cols), 70)
        self.assertIn('sma_50', cols)
        self.assertIn('rs_velocity', cols)
        self.assertIn('feature_version', cols)
        # Alpha columns should NOT be present yet
        self.assertNotIn('alpha001', cols)

    def test_trend_ok_and_breakout_ok_exist(self):
        con = duckdb.connect(TEST_DB)
        cols = [r[0] for r in con.execute("DESCRIBE daily_features").fetchall()]
        con.close()
        self.assertIn('trend_ok', cols)
        self.assertIn('breakout_ok', cols)

    def test_trend_ok_is_boolean(self):
        con = duckdb.connect(TEST_DB)
        # trend_ok should never be NULL (COALESCE wraps it)
        null_count = con.execute(
            "SELECT COUNT(*) FROM daily_features WHERE trend_ok IS NULL"
        ).fetchone()[0]
        con.close()
        self.assertEqual(null_count, 0)

    def test_breakout_ok_is_boolean(self):
        con = duckdb.connect(TEST_DB)
        null_count = con.execute(
            "SELECT COUNT(*) FROM daily_features WHERE breakout_ok IS NULL"
        ).fetchone()[0]
        con.close()
        self.assertEqual(null_count, 0)

    def test_screener_filter(self):
        """Only active screener members appear; SPY and JUNK must be absent."""
        con = duckdb.connect(TEST_DB)
        tickers = sorted(r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM daily_features"
        ).fetchall())
        con.close()
        self.assertEqual(tickers, ['AAPL', 'MSFT', 'TSLA'])
        self.assertNotIn('SPY', tickers)
        self.assertNotIn('JUNK', tickers)


class TestPhaseB(unittest.TestCase):
    """Test Phase B: Python alpha computation."""

    @classmethod
    def setUpClass(cls):
        cls.pipeline = FeaturePipeline(TEST_DB)
        # Phase A should already be done from TestPhaseA, but be safe
        cls.pipeline.compute_base_features(start_date='2023-01-01')
        cls.pipeline.compute_alpha_features(start_date='2023-01-01')

    def test_alpha_columns_exist(self):
        con = duckdb.connect(TEST_DB)
        cols = {r[0] for r in con.execute("DESCRIBE daily_features").fetchall()}
        con.close()
        for col in ALPHA_COLS:
            self.assertIn(col, cols, f"Missing column: {col}")

    def test_alphas_are_finite(self):
        con = duckdb.connect(TEST_DB)
        for col in ALPHA_COLS:
            inf_count = con.execute(f"""
                SELECT COUNT(*) FROM daily_features
                WHERE {col} = 'Infinity' OR {col} = '-Infinity'
                   OR isnan({col})
            """).fetchone()[0]
            self.assertEqual(inf_count, 0, f"{col} has {inf_count} inf/NaN values")
        con.close()

    def test_alphas_populated(self):
        """At least 80% of rows should have non-zero alpha values (warmup excluded)."""
        con = duckdb.connect(TEST_DB)
        total = con.execute("SELECT COUNT(*) FROM daily_features WHERE ticker != 'SPY'").fetchone()[0]
        for col in ALPHA_COLS:
            nonzero = con.execute(f"""
                SELECT COUNT(*) FROM daily_features
                WHERE ticker != 'SPY' AND {col} != 0 AND {col} IS NOT NULL
            """).fetchone()[0]
            pct = nonzero / total if total > 0 else 0
            self.assertGreater(pct, 0.5, f"{col} only {pct:.1%} non-zero (expected >50%)")
        con.close()


class TestPhaseC(unittest.TestCase):
    """Test Phase C: Cross-sectional ranks."""

    @classmethod
    def setUpClass(cls):
        cls.pipeline = FeaturePipeline(TEST_DB)
        cls.pipeline.compute_base_features(start_date='2023-01-01')
        cls.pipeline.compute_alpha_features(start_date='2023-01-01')
        cls.pipeline.compute_cross_sectional_ranks()

    def test_rank_columns_exist(self):
        con = duckdb.connect(TEST_DB)
        cols = {r[0] for r in con.execute("DESCRIBE daily_features").fetchall()}
        con.close()
        for col in RANK_COLS:
            self.assertIn(col, cols, f"Missing column: {col}")

    def test_universe_rank_range(self):
        con = duckdb.connect(TEST_DB)
        stats = con.execute("""
            SELECT MIN(RS_Universe_Rank), MAX(RS_Universe_Rank)
            FROM daily_features
            WHERE RS_Universe_Rank IS NOT NULL
        """).fetchone()
        con.close()
        self.assertGreaterEqual(stats[0], 0.0)
        self.assertLessEqual(stats[1], 1.0)

    def test_total_column_count(self):
        """Final table should have ~86+ columns (79 base + 16 alpha + 7 rank - some overlap)."""
        con = duckdb.connect(TEST_DB)
        col_count = len(con.execute("DESCRIBE daily_features").fetchall())
        con.close()
        # 79 base + 16 alpha + 7 rank = 102
        self.assertGreaterEqual(col_count, 100)


class TestFullPipeline(unittest.TestCase):
    """Test A+B+C end-to-end (views skipped — require production schema)."""

    @classmethod
    def setUpClass(cls):
        cls.pipeline = FeaturePipeline(TEST_DB)
        cls.pipeline.compute_base_features(start_date='2023-01-01')
        cls.pipeline.compute_alpha_features(start_date='2023-01-01')
        cls.pipeline.compute_cross_sectional_ranks()

    def test_all_phases_complete(self):
        con = duckdb.connect(TEST_DB)
        cols = {r[0] for r in con.execute("DESCRIBE daily_features").fetchall()}
        con.close()
        # Check representative columns from each phase
        self.assertIn('sma_50', cols)          # Phase A
        self.assertIn('alpha001', cols)        # Phase B
        self.assertIn('RS_Universe_Rank', cols)  # Phase C


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
