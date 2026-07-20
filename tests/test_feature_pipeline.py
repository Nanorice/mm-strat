"""Tests for src/feature_pipeline.py — T2 screener features + T3 SEPA features."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest

import duckdb
import numpy as np
import pandas as pd

from src.feature_pipeline import (
    ALPHA_COLS_TS,
    ALPHA_COLS_XS,
    EMA_COLS,
    EXPECTED_T3_COLUMN_COUNT,
    RANK_COLS,
    FeaturePipeline,
)

TEST_DB = os.path.join(tempfile.gettempdir(), 'test_feature_pipeline.duckdb')

# Price history starts well before START so T2's SQL windows (sma_200, 52w high) are
# seeded from price_data.
HISTORY_START = '2021-01-04'
HISTORY_DAYS = 900
# The computed window itself must exceed 250 trading days: _load_data_for_alphas INNER
# JOINs price_data against the *target* table, so for T2 the alpha warmup only exists
# where t2 rows already exist. On a first build, alpha019's rolling(250) sum of returns
# can only fill from rows inside [START, END]. (T3 sidesteps this via warmup_table=t2.)
START = '2022-06-01'
END: str = ''  # set in setUpModule once the calendar is generated
WARMED_FROM: str = ''  # START + 250 trading days — past every alpha's lookback

# t2_screener_features has no EXPECTED_*_COLUMN_COUNT constant the way t3 does, so the
# tripwire lives here: DDL columns + the 5 EMA columns compute_ema_features adds.
T2_COLUMN_COUNT = 68

# Fully warmed, every XS alpha is ~100% populated except alpha015, which is inherently
# sparse: it rolls a 3-day correlation of two cross-sectional rank series, which is NaN
# whenever either 3-day window is degenerate, then rolls a 3-day SUM over that — so each
# NaN blanks three days. ~65% on a 12-ticker universe; denser as the universe grows.
ALPHA_XS_FLOORS = {'alpha015': 0.5}

# 12 names across 3 sectors. The XS alphas rank across tickers *within a date* and then
# roll a 3-6 day correlation over that rank — with a 3-ticker universe the rank series
# only takes 3 values, so those windows are constantly degenerate and the alphas come
# back NaN (sanitized to 0). A dozen names is the smallest universe where the
# cross-sectional factors, sector ranks, and industry ranks all mean something.
SECTORS = {
    'Technology': ['Consumer Electronics', 'Software'],
    'Consumer Cyclical': ['Auto Manufacturers', 'Restaurants'],
    'Healthcare': ['Biotechnology', 'Medical Devices'],
}
ACTIVE_TICKERS = [f"TK{i:02d}" for i in range(12)]
T3_TICKERS = ['TK00', 'TK01']  # sepa_watchlist subset — the other 10 must NOT reach t3


def _synthetic_ohlcv(ticker: str, dates: pd.DatetimeIndex, base: float, drift: float = 0.0) -> list:
    """Geometric random walk — over this many days an additive walk drifts below zero,
    and a negative close makes the LN(price_vs_spy) in T2's rs_line_log raise."""
    rows = []
    for d in dates:
        o = base * (1 + np.random.randn() * 0.012 + drift)
        h = o * (1 + abs(np.random.randn()) * 0.010)
        l = o * (1 - abs(np.random.randn()) * 0.010)
        c = (o + h + l) / 3 * (1 + np.random.randn() * 0.005)
        v = int(abs(np.random.randn() * 1_000_000 + 5_000_000))
        rows.append((ticker, d.date(), o, h, l, c, v))
        base = c
    return rows


def setUpModule() -> None:
    """Seed a temp-file DuckDB with the tables T2/T3 read from.

    A file DB (not ':memory:') is required: each duckdb.connect(':memory:') opens a
    *separate* empty database, so the pipeline and the assertions would never see the
    same data.

    Alphas run sequentially — the default multiprocessing path spawns 8 workers and
    pickles the frame to each, which dwarfs the compute at this fixture's size.
    """
    global END, WARMED_FROM
    os.environ['USE_PARALLEL_ALPHAS'] = '0'

    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

    np.random.seed(42)
    dates = pd.bdate_range(HISTORY_START, periods=HISTORY_DAYS)
    END = dates[-1].strftime('%Y-%m-%d')
    WARMED_FROM = pd.bdate_range(START, END)[250].strftime('%Y-%m-%d')

    # Spread of drifts so the universe contains genuine leaders and laggards — trend_ok
    # gates on price_vs_spy > its 63d mean, which a driftless universe never satisfies
    # persistently, and the rank columns need real cross-sectional dispersion.
    rows = []
    for n, ticker in enumerate(ACTIVE_TICKERS):
        drift = (n - (len(ACTIVE_TICKERS) - 1) / 2) * 0.0005
        rows += _synthetic_ohlcv(ticker, dates, base=100 + np.random.rand() * 40, drift=drift)

    # JUNK: in price_data but never active in the screener — must be absent from t2.
    for d in dates:
        rows.append(('JUNK', d.date(), 5.0, 5.5, 4.5, 5.0, 100_000))

    # SPY: the benchmark's own price_data rows define which days are trading days.
    spy_rows = _synthetic_ohlcv('SPY', dates, base=450.0)
    rows += spy_rows

    con = duckdb.connect(TEST_DB)

    df = pd.DataFrame(rows, columns=['ticker', 'date', 'open', 'high', 'low', 'close', 'volume'])
    con.execute("CREATE TABLE price_data AS SELECT * FROM df")

    pairs = [(s, i) for s, inds in SECTORS.items() for i in inds]
    profiles = pd.DataFrame({
        'ticker': ACTIVE_TICKERS,
        'sector': [pairs[n % len(pairs)][0] for n in range(len(ACTIVE_TICKERS))],
        'industry': [pairs[n % len(pairs)][1] for n in range(len(ACTIVE_TICKERS))],
    })
    con.execute("CREATE TABLE company_profiles AS SELECT * FROM profiles")

    n_members = len(ACTIVE_TICKERS) + 1
    screener = pd.DataFrame({
        'ticker': ACTIVE_TICKERS + ['JUNK'],
        'effective_date': pd.to_datetime(['2021-01-01'] * n_members).date,
        'is_active': [True] * len(ACTIVE_TICKERS) + [False],
        'criteria_version': ['v2'] * n_members,
    })
    con.execute("CREATE TABLE screener_membership AS SELECT * FROM screener")

    # t1_macro must carry spy_close for every day SPY traded — a missing row makes
    # price_vs_spy NULL, which COALESCE turns into trend_ok = FALSE universe-wide.
    macro = pd.DataFrame({
        'date': [r[1] for r in spy_rows],
        'spy_close': [r[5] for r in spy_rows],
        'spy_high': [r[3] for r in spy_rows],
        'spy_low': [r[4] for r in spy_rows],
    })
    con.execute("CREATE TABLE t1_macro AS SELECT * FROM macro")

    # T3 universe gate: sepa_watchlist UNION vip_watchlist (active).
    watchlist = pd.DataFrame({'ticker': T3_TICKERS})
    con.execute("CREATE TABLE sepa_watchlist AS SELECT * FROM watchlist")
    con.execute("CREATE TABLE vip_watchlist (ticker VARCHAR, active BOOLEAN)")

    regime = pd.DataFrame({
        'date': [d.date() for d in dates],
        'm03_score': np.random.rand(len(dates)),
        'm03_pillar_trend': np.random.rand(len(dates)),
        'm03_pillar_liq': np.random.rand(len(dates)),
        'm03_pillar_risk': np.random.rand(len(dates)),
        'm03_delta_5d': np.random.randn(len(dates)),
        'm03_delta_20d': np.random.randn(len(dates)),
        'm03_regime_vol': np.random.rand(len(dates)),
    })
    con.execute("CREATE TABLE t2_regime_scores AS SELECT * FROM regime")
    con.close()

    # Run the pipeline once for the whole module — T2 (base + XS alphas + EMAs +
    # ranks) then T3 (per-ticker windows + carry-forward + TS alphas).
    pipeline = FeaturePipeline(TEST_DB)
    pipeline.compute_t2_screener_features(start_date=START, end_date=END, warmup_days=600)

    con = duckdb.connect(TEST_DB)
    try:
        pipeline._create_t3_table(con)
    finally:
        con.close()
    pipeline.compute_t3_features(start_date=START, end_date=END)


def tearDownModule() -> None:
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


def _describe(table: str) -> list:
    con = duckdb.connect(TEST_DB, read_only=True)
    try:
        return [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    finally:
        con.close()


def _scalar(sql: str):
    con = duckdb.connect(TEST_DB, read_only=True)
    try:
        return con.execute(sql).fetchone()[0]
    finally:
        con.close()


class TestT2Base(unittest.TestCase):
    """T2 Phase A: SQL base features over the active screener universe."""

    def test_table_created(self):
        con = duckdb.connect(TEST_DB, read_only=True)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        self.assertIn('t2_screener_features', tables)

    def test_row_count(self):
        """Every active screener member × every trading day in [START, END]."""
        expected_days = len(pd.bdate_range(START, END))
        count = _scalar(f"SELECT COUNT(*) FROM t2_screener_features WHERE date BETWEEN '{START}' AND '{END}'")
        self.assertEqual(count, len(ACTIVE_TICKERS) * expected_days)

    def test_column_count(self):
        """Tripwire on the T2 schema — bump T2_COLUMN_COUNT when the DDL changes."""
        cols = _describe('t2_screener_features')
        self.assertEqual(len(cols), T2_COLUMN_COUNT)
        self.assertIn('sma_50', cols)
        self.assertIn('rs_line_delta', cols)
        self.assertIn('price_vs_spy', cols)

    def test_trend_ok_and_breakout_ok_exist(self):
        cols = _describe('t2_screener_features')
        self.assertIn('trend_ok', cols)
        self.assertIn('breakout_ok', cols)

    def test_trend_ok_is_boolean(self):
        """COALESCE(..., FALSE) wraps trend_ok — it must never be NULL."""
        self.assertEqual(_scalar("SELECT COUNT(*) FROM t2_screener_features WHERE trend_ok IS NULL"), 0)

    def test_breakout_ok_is_boolean(self):
        self.assertEqual(_scalar("SELECT COUNT(*) FROM t2_screener_features WHERE breakout_ok IS NULL"), 0)

    def test_trend_ok_not_universally_false(self):
        """A NULL benchmark silently zeroes trend_ok for the whole universe.

        t1_macro covers every SPY trading day here, so at least some rows must pass.
        An all-FALSE column is the signature of the June 2026 benchmark-gap bug.
        """
        true_count = _scalar("SELECT COUNT(*) FROM t2_screener_features WHERE trend_ok")
        self.assertGreater(true_count, 0)

    def test_screener_filter(self):
        """Only active screener members appear; SPY and JUNK must be absent."""
        con = duckdb.connect(TEST_DB, read_only=True)
        tickers = sorted(r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM t2_screener_features"
        ).fetchall())
        con.close()
        self.assertEqual(tickers, ACTIVE_TICKERS)


class TestT2Alphas(unittest.TestCase):
    """T2 Phase B: cross-sectional alpha factors + EMAs."""

    def test_alpha_columns_exist(self):
        cols = _describe('t2_screener_features')
        for col in ALPHA_COLS_XS:
            self.assertIn(col, cols, f"Missing column: {col}")

    def test_ts_alphas_not_in_t2(self):
        """Time-series alphas belong to T3 — T2 must not carry them."""
        cols = _describe('t2_screener_features')
        for col in ALPHA_COLS_TS:
            self.assertNotIn(col, cols, f"TS alpha {col} leaked into t2")

    def test_alphas_are_finite(self):
        con = duckdb.connect(TEST_DB, read_only=True)
        try:
            for col in ALPHA_COLS_XS:
                bad = con.execute(f"""
                    SELECT COUNT(*) FROM t2_screener_features
                    WHERE isinf({col}) OR isnan({col})
                """).fetchone()[0]
                self.assertEqual(bad, 0, f"{col} has {bad} inf/NaN values")
        finally:
            con.close()

    def test_alphas_populated(self):
        """_sanitize_alpha fills NaN with 0 — an all-zero column means it never computed.

        Measured past WARMED_FROM so the longest lookback (alpha019's rolling 250-day
        return sum) has filled; inside the warmup a legitimate 0 is indistinguishable
        from a broken alpha.
        """
        total = _scalar(f"SELECT COUNT(*) FROM t2_screener_features WHERE date >= '{WARMED_FROM}'")
        con = duckdb.connect(TEST_DB, read_only=True)
        try:
            for col in ALPHA_COLS_XS:
                nonzero = con.execute(f"""
                    SELECT COUNT(*) FROM t2_screener_features
                    WHERE date >= '{WARMED_FROM}' AND {col} != 0
                """).fetchone()[0]
                pct = nonzero / total
                floor = ALPHA_XS_FLOORS.get(col, 0.9)
                self.assertGreater(pct, floor, f"{col} only {pct:.1%} non-zero (expected >{floor:.0%})")
        finally:
            con.close()

    def test_ema_columns_populated(self):
        cols = _describe('t2_screener_features')
        for col in EMA_COLS:
            self.assertIn(col, cols, f"Missing column: {col}")
        null_count = _scalar(
            f"SELECT COUNT(*) FROM t2_screener_features "
            f"WHERE date BETWEEN '{START}' AND '{END}' AND ema_200 IS NULL"
        )
        self.assertEqual(null_count, 0)


class TestT2Ranks(unittest.TestCase):
    """T2 Phase C: cross-sectional ranks."""

    def test_rank_columns_exist(self):
        cols = _describe('t2_screener_features')
        for col in RANK_COLS:
            self.assertIn(col, cols, f"Missing column: {col}")

    def test_universe_rank_range(self):
        con = duckdb.connect(TEST_DB, read_only=True)
        lo, hi = con.execute("""
            SELECT MIN(RS_Universe_Rank), MAX(RS_Universe_Rank)
            FROM t2_screener_features
            WHERE RS_Universe_Rank IS NOT NULL
        """).fetchone()
        con.close()
        self.assertGreaterEqual(lo, 0.0)
        self.assertLessEqual(hi, 1.0)

    def test_universe_rank_populated(self):
        """rs is non-NULL once the 252d momentum windows are seeded, so is the rank."""
        null_count = _scalar(
            f"SELECT COUNT(*) FROM t2_screener_features "
            f"WHERE date BETWEEN '{START}' AND '{END}' AND RS_Universe_Rank IS NULL"
        )
        self.assertEqual(null_count, 0)

    def test_rs_rating_rescaled_to_1_99(self):
        """Phase C overwrites rs_rating with ROUND(rank * 98) + 1."""
        lo, hi = duckdb.connect(TEST_DB, read_only=True).execute(f"""
            SELECT MIN(rs_rating), MAX(rs_rating) FROM t2_screener_features
            WHERE date BETWEEN '{START}' AND '{END}'
        """).fetchone()
        self.assertGreaterEqual(lo, 1.0)
        self.assertLessEqual(hi, 99.0)


class TestT3SepaFeatures(unittest.TestCase):
    """T3: per-ticker windows + T2 carry-forward + TS alphas + M03 join."""

    def test_universe_is_sepa_watchlist(self):
        """T3 is gated on sepa_watchlist — TSLA is in T2 but not on the watchlist."""
        con = duckdb.connect(TEST_DB, read_only=True)
        tickers = sorted(r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM t3_sepa_features"
        ).fetchall())
        con.close()
        self.assertEqual(tickers, T3_TICKERS)

    def test_row_count(self):
        expected_days = len(pd.bdate_range(START, END))
        count = _scalar("SELECT COUNT(*) FROM t3_sepa_features")
        self.assertEqual(count, len(T3_TICKERS) * expected_days)

    def test_column_count_matches_tripwire(self):
        self.assertEqual(len(_describe('t3_sepa_features')), EXPECTED_T3_COLUMN_COUNT)

    def test_ts_alpha_columns_exist(self):
        cols = _describe('t3_sepa_features')
        for col in ALPHA_COLS_TS:
            self.assertIn(col, cols, f"Missing column: {col}")

    def test_ts_alphas_are_finite(self):
        con = duckdb.connect(TEST_DB, read_only=True)
        try:
            for col in ALPHA_COLS_TS:
                bad = con.execute(f"""
                    SELECT COUNT(*) FROM t3_sepa_features
                    WHERE isinf({col}) OR isnan({col})
                """).fetchone()[0]
                self.assertEqual(bad, 0, f"{col} has {bad} inf/NaN values")
        finally:
            con.close()

    def test_ts_alphas_populated(self):
        total = _scalar("SELECT COUNT(*) FROM t3_sepa_features")
        con = duckdb.connect(TEST_DB, read_only=True)
        try:
            for col in ALPHA_COLS_TS:
                nonzero = con.execute(
                    f"SELECT COUNT(*) FROM t3_sepa_features WHERE {col} != 0"
                ).fetchone()[0]
                pct = nonzero / total
                self.assertGreater(pct, 0.9, f"{col} only {pct:.1%} non-zero (expected >90%)")
        finally:
            con.close()

    def test_t2_carry_forward_matches_source(self):
        """Carried columns must equal T2 row-for-row — a shifted INSERT list would not."""
        mismatches = _scalar("""
            SELECT COUNT(*)
            FROM t3_sepa_features t3
            JOIN t2_screener_features t2 ON t3.ticker = t2.ticker AND t3.date = t2.date
            WHERE t3.trend_ok IS DISTINCT FROM t2.trend_ok
               OR t3.breakout_ok IS DISTINCT FROM t2.breakout_ok
               OR t3.sma_50 IS DISTINCT FROM t2.sma_50
               OR t3.RS_Universe_Rank IS DISTINCT FROM t2.RS_Universe_Rank
               OR t3.alpha001 IS DISTINCT FROM t2.alpha001
        """)
        self.assertEqual(mismatches, 0)

    def test_all_stages_present(self):
        """One representative column from each stage that feeds T3."""
        cols = set(_describe('t3_sepa_features'))
        self.assertIn('sma_50', cols)              # T2 base carry-forward
        self.assertIn('alpha001', cols)            # T2 XS alpha carry-forward
        self.assertIn('RS_Universe_Rank', cols)    # T2 rank carry-forward
        self.assertIn('rs_velocity', cols)         # T3 per-ticker window
        self.assertIn('alpha101', cols)            # T3 TS alpha
        self.assertIn('mom_21d_vol_adj', cols)     # T3 vol-adjusted (Group B)
        self.assertIn('m03_score', cols)           # M03 regime join

    def test_m03_joined(self):
        null_count = _scalar("SELECT COUNT(*) FROM t3_sepa_features WHERE m03_score IS NULL")
        self.assertEqual(null_count, 0)


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
