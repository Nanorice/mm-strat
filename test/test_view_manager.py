"""Tests for src/view_manager.py — session-based trade_id logic."""

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, str(os.path.join(os.path.dirname(__file__), '..')))

import duckdb
import pandas as pd

from src.managers.view_manager import ViewManager

TEST_DB = os.path.join(tempfile.gettempdir(), 'test_view_manager.duckdb')


def _build_db(daily_features_rows: list[dict], profiles: list[dict] | None = None) -> str:
    """Build a minimal DuckDB with daily_features + company_profiles for view tests.

    Each row in daily_features_rows must have at minimum:
        ticker, date, trend_ok, breakout_ok, close, vol_avg_20
    Missing feature columns are filled with safe defaults.
    """
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

    con = duckdb.connect(TEST_DB)

    # Default column values for all the columns the views reference
    defaults = {
        'open': 100.0, 'high': 105.0, 'low': 95.0, 'close': 100.0,
        'volume': 5_000_000,
        'sma_20': 99.0, 'sma_50': 98.0, 'sma_150': 95.0, 'sma_200': 93.0,
        'sma_200_lag20': 92.0,
        'price_vs_sma_50': 2.0, 'price_vs_sma_150': 5.0, 'price_vs_sma_200': 7.0,
        'price_vs_spy': 1.1, 'price_vs_spy_ma20': 1.05, 'price_vs_spy_ma50': 1.03,
        'price_vs_spy_ma63': 1.02, 'price_vs_spy_ma200': 1.0,
        'rs_line_uptrend': True, 'rs_line_log': 0.1, 'rs_line_delta': 0.01,
        'rs_line_lag_delta': 0.01,
        'rs_rating': 80.0, 'rs': 0.5, 'rs_ma': 0.45,
        'vol_avg_20': 1_000_000, 'vol_avg_50': 900_000,
        'vol_ratio': 1.5, 'vol_ratio_50': 1.5,
        'vol_ma20': 1_000_000, 'vol_ma50': 900_000,
        'dollar_volume_avg_20': 100_000_000.0,
        'dry_up_volume': 0.8,
        'turnover': 500_000_000.0, 'turnover_ma20': 480_000_000.0,
        'atr_14': 2.0, 'atr_20d': 2.1, 'natr': 2.0, 'volatility_20d': 3.0,
        'vcp_ratio': 0.8, 'consolidation_width': 5.0,
        'high_52w': 110.0, 'low_52w': 70.0,
        'highest_high_20d': 105.0, 'lowest_low_20d': 95.0, 'high_20d': 104.0,
        'pct_from_high_52w': -0.05, 'pct_above_low_52w': 0.4,
        'dist_from_52w_high': -0.05, 'dist_from_52w_low': 0.4,
        'dist_from_20d_low': 0.05, 'dist_from_20d_high': -0.02,
        'return_1d': 0.01, 'return_5d': 0.03, 'return_20d': 0.08, 'return_60d': 0.15,
        'mom_21d': 0.08, 'mom_63d': 0.15, 'mom_126d': 0.25,
        'mom_189d': 0.30, 'mom_252d': 0.35,
        'rsi_14': 60.0, 'sma_50_slope': 0.5,
        'is_green_day': 1, 'green_days_ratio_20d': 0.6, 'breakout': 0,
        'adr_20d': 0.03,
        'rs_velocity': 0.02, 'volume_acceleration': 100,
        'breakout_momentum': 0.5, 'consolidation_duration': 5,
        'price_momentum_curve': 0.01, 'log_volume_velocity': 0.05,
        'price_accel_10d': 0.005, 'immediate_thrust': 0.3,
        'close_above_sma200': True,
        'trend_ok': False, 'breakout_ok': False,
        'feature_version': 'v3.0',
    }

    rows = []
    for r in daily_features_rows:
        row = {**defaults, **r}
        rows.append(row)

    df = pd.DataFrame(rows)
    con.execute("CREATE TABLE daily_features AS SELECT * FROM df")

    # price_data (needed by v_d2r_hydrated)
    price_rows = [
        {'ticker': r['ticker'], 'date': r['date'],
         'open': r.get('open', 100.0), 'high': r.get('high', 105.0),
         'low': r.get('low', 95.0), 'close': r.get('close', 100.0),
         'volume': r.get('volume', 5_000_000)}
        for r in daily_features_rows
    ]
    pdf = pd.DataFrame(price_rows)
    con.execute("CREATE TABLE price_data AS SELECT * FROM pdf")

    # company_profiles
    if profiles is None:
        tickers = list({r['ticker'] for r in daily_features_rows})
        profiles = [
            {'ticker': t, 'sector': 'Tech', 'industry': 'Software',
             'is_active': True, 'market_cap': 1e9, 'shares_outstanding': 1e7}
            for t in tickers
        ]
    cp = pd.DataFrame(profiles)
    con.execute("CREATE TABLE company_profiles AS SELECT * FROM cp")

    # fundamental_features (empty but required by v_d2_features)
    con.execute("""
        CREATE TABLE fundamental_features (
            ticker VARCHAR, filing_date DATE, fiscal_period VARCHAR,
            revenue DOUBLE, net_income DOUBLE, eps_diluted DOUBLE,
            total_assets DOUBLE, total_equity DOUBLE,
            revenue_growth_yoy DOUBLE, eps_growth_yoy DOUBLE,
            net_income_growth_yoy DOUBLE, eps_accel DOUBLE,
            revenue_accel DOUBLE, revenue_cagr_3y DOUBLE,
            eps_stability_score DOUBLE, debt_to_equity DOUBLE,
            current_ratio DOUBLE, quick_ratio DOUBLE,
            gross_margin DOUBLE, operating_margin DOUBLE,
            net_margin DOUBLE, roe DOUBLE, roa DOUBLE,
            fcf_margin DOUBLE, earnings_quality_score DOUBLE,
            inventory_growth_yoy DOUBLE, inventory_vs_sales_spread DOUBLE,
            gross_margin_trend DOUBLE
        )
    """)

    con.close()
    return TEST_DB


def _dates(start: str, n: int) -> list[date]:
    """Generate n consecutive business dates from start."""
    d = date.fromisoformat(start)
    result = []
    while len(result) < n:
        if d.weekday() < 5:
            result.append(d)
        d += timedelta(days=1)
    return result


class TestSessionStateMachine(unittest.TestCase):
    """Core session logic tests for v_d1_candidates."""

    def test_single_session_one_trade(self):
        """Trend always true, 2 breakout events separated by non-breakout days -> 1 trade_id."""
        dates = _dates('2024-01-02', 20)
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                'ticker': 'AAPL', 'date': d, 'close': 100.0 + i,
                'trend_ok': True,
                'breakout_ok': i in (3, 10),  # Two breakout days
            })
        _build_db(rows)

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        vm._create_v_d1_candidates(con)
        trade_ids = con.execute(
            "SELECT DISTINCT trade_id FROM v_d1_candidates WHERE ticker='AAPL'"
        ).fetchall()
        con.close()
        self.assertEqual(len(trade_ids), 1, f"Expected 1 trade, got {len(trade_ids)}: {trade_ids}")

    def test_broken_trend_two_trades(self):
        """Trend breaks between 2 breakout events -> 2 trade_ids."""
        dates = _dates('2024-01-02', 20)
        rows = []
        for i, d in enumerate(dates):
            # trend_ok: True for first 8 days, False for day 9-10, True for 11-20
            trend = i < 8 or i >= 10
            rows.append({
                'ticker': 'MSFT', 'date': d, 'close': 100.0 + i,
                'trend_ok': trend,
                'breakout_ok': i in (2, 12),  # One breakout in each session
            })
        _build_db(rows)

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        vm._create_v_d1_candidates(con)
        trade_ids = con.execute(
            "SELECT DISTINCT trade_id FROM v_d1_candidates WHERE ticker='MSFT'"
        ).fetchall()
        con.close()
        self.assertEqual(len(trade_ids), 2, f"Expected 2 trades, got {len(trade_ids)}: {trade_ids}")

    def test_entry_date_is_first_breakout(self):
        """Entry date should be the first breakout_ok date within the session."""
        dates = _dates('2024-01-02', 15)
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                'ticker': 'TSLA', 'date': d, 'close': 100.0 + i,
                'trend_ok': True,
                'breakout_ok': i in (5, 8),  # First breakout at index 5
            })
        _build_db(rows)

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        vm._create_v_d1_candidates(con)
        entry = con.execute(
            "SELECT DISTINCT entry_date FROM v_d1_candidates WHERE ticker='TSLA'"
        ).fetchone()[0]
        con.close()
        expected = dates[5]
        self.assertEqual(entry, expected, f"Entry should be {expected}, got {entry}")

    def test_no_breakout_no_trade(self):
        """Trend always true but breakout never fires -> 0 trade_ids."""
        dates = _dates('2024-01-02', 15)
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                'ticker': 'GOOG', 'date': d, 'close': 100.0 + i,
                'trend_ok': True,
                'breakout_ok': False,
            })
        _build_db(rows)

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        vm._create_v_d1_candidates(con)
        count = con.execute(
            "SELECT COUNT(*) FROM v_d1_candidates WHERE ticker='GOOG'"
        ).fetchone()[0]
        con.close()
        self.assertEqual(count, 0, f"Expected 0 rows, got {count}")

    def test_only_entry_row_in_candidates(self):
        """v_d1_candidates should contain exactly one row per trade (the entry row)."""
        dates = _dates('2024-01-02', 15)
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                'ticker': 'NVDA', 'date': d, 'close': 100.0 + i,
                'trend_ok': True,
                'breakout_ok': i == 7,
            })
        _build_db(rows)

        con = duckdb.connect(TEST_DB)
        ViewManager._create_v_d1_candidates(con)
        row_count = con.execute(
            "SELECT COUNT(*) FROM v_d1_candidates WHERE ticker='NVDA'"
        ).fetchone()[0]
        trade_count = con.execute(
            "SELECT COUNT(DISTINCT trade_id) FROM v_d1_candidates WHERE ticker='NVDA'"
        ).fetchone()[0]
        min_date = con.execute(
            "SELECT MIN(date) FROM v_d1_candidates WHERE ticker='NVDA'"
        ).fetchone()[0]
        con.close()
        self.assertEqual(row_count, 1, f"Expected 1 row, got {row_count}")
        self.assertEqual(trade_count, 1, f"Expected 1 trade, got {trade_count}")
        self.assertEqual(min_date, dates[7], f"Entry row should be {dates[7]}, got {min_date}")

    def test_is_new_trigger_only_on_entry_date(self):
        """is_new_trigger should be 1 only on the entry_date row."""
        dates = _dates('2024-01-02', 15)
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                'ticker': 'META', 'date': d, 'close': 100.0 + i,
                'trend_ok': True,
                'breakout_ok': i in (3, 9),
            })
        _build_db(rows)

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        vm._create_v_d1_candidates(con)
        trigger_count = con.execute(
            "SELECT COUNT(*) FROM v_d1_candidates WHERE ticker='META' AND is_new_trigger=1"
        ).fetchone()[0]
        con.close()
        self.assertEqual(trigger_count, 1, f"Expected 1 trigger row, got {trigger_count}")

    def test_liquidity_filter_applied(self):
        """Rows with vol_avg_20 < 500000 should be excluded even if trend_ok."""
        dates = _dates('2024-01-02', 10)
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                'ticker': 'TINY', 'date': d, 'close': 100.0 + i,
                'trend_ok': True,
                'breakout_ok': i == 3,
                'vol_avg_20': 100_000,  # Below threshold
            })
        _build_db(rows)

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        vm._create_v_d1_candidates(con)
        count = con.execute(
            "SELECT COUNT(*) FROM v_d1_candidates WHERE ticker='TINY'"
        ).fetchone()[0]
        con.close()
        self.assertEqual(count, 0, f"Expected 0 (illiquid), got {count}")


class TestTradePrices(unittest.TestCase):
    """Test entry_price, exit_price, exit_date, return_pct on v_d1_candidates."""

    def test_entry_price_is_next_day_open(self):
        """entry_price should be the open of the day after entry_date."""
        dates = _dates('2024-01-02', 15)
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                'ticker': 'AAPL', 'date': d,
                'open': 50.0 + i, 'close': 100.0 + i,
                'trend_ok': True,
                'breakout_ok': i == 3,
            })
        _build_db(rows)

        con = duckdb.connect(TEST_DB)
        ViewManager._create_v_d1_candidates(con)
        entry_price = con.execute(
            "SELECT DISTINCT entry_price FROM v_d1_candidates WHERE ticker='AAPL'"
        ).fetchone()[0]
        con.close()
        # Entry at index 3, next-day open = 50.0 + 4 = 54.0
        self.assertAlmostEqual(entry_price, 54.0)

    def test_exit_date_is_next_day_after_last_trend(self):
        """exit_date should be the next trading day after the last trend_ok day."""
        dates = _dates('2024-01-02', 20)
        rows = []
        for i, d in enumerate(dates):
            trend = i < 12  # Last trend_ok day is index 11
            rows.append({
                'ticker': 'AAPL', 'date': d,
                'open': 50.0 + i, 'close': 100.0 + i,
                'trend_ok': trend,
                'breakout_ok': i == 3,
            })
        _build_db(rows)

        con = duckdb.connect(TEST_DB)
        ViewManager._create_v_d1_candidates(con)
        exit_date = con.execute(
            "SELECT DISTINCT exit_date FROM v_d1_candidates WHERE ticker='AAPL'"
        ).fetchone()[0]
        con.close()
        if hasattr(exit_date, 'date'):
            exit_date = exit_date.date()
        # Last trend_ok day = dates[11], next trading day = dates[12]
        self.assertEqual(exit_date, dates[12])

    def test_exit_price_is_exit_day_open(self):
        """exit_price should be the open on exit_date."""
        dates = _dates('2024-01-02', 20)
        rows = []
        for i, d in enumerate(dates):
            trend = i < 12
            rows.append({
                'ticker': 'AAPL', 'date': d,
                'open': 50.0 + i, 'close': 100.0 + i,
                'trend_ok': trend,
                'breakout_ok': i == 3,
            })
        _build_db(rows)

        con = duckdb.connect(TEST_DB)
        ViewManager._create_v_d1_candidates(con)
        exit_price = con.execute(
            "SELECT DISTINCT exit_price FROM v_d1_candidates WHERE ticker='AAPL'"
        ).fetchone()[0]
        con.close()
        # Exit day = dates[12] (index 12), open = 50.0 + 12 = 62.0
        self.assertAlmostEqual(exit_price, 62.0)

    def test_return_pct_correct(self):
        """return_pct = (exit_price / entry_price) - 1."""
        dates = _dates('2024-01-02', 20)
        rows = []
        for i, d in enumerate(dates):
            trend = i < 12
            rows.append({
                'ticker': 'AAPL', 'date': d,
                'open': 50.0 + i, 'close': 100.0 + i,
                'trend_ok': trend,
                'breakout_ok': i == 3,
            })
        _build_db(rows)

        con = duckdb.connect(TEST_DB)
        ViewManager._create_v_d1_candidates(con)
        return_pct = con.execute(
            "SELECT DISTINCT return_pct FROM v_d1_candidates WHERE ticker='AAPL'"
        ).fetchone()[0]
        con.close()
        # entry_price = 54.0 (index 4 open), exit_price = 62.0 (index 12 open)
        expected = (62.0 / 54.0) - 1.0
        self.assertAlmostEqual(return_pct, expected, places=6)

    def test_exit_date_null_when_trend_never_breaks(self):
        """If trend_ok is True through end of data, exit_date should be NULL."""
        dates = _dates('2024-01-02', 15)
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                'ticker': 'AAPL', 'date': d,
                'open': 50.0 + i, 'close': 100.0 + i,
                'trend_ok': True,
                'breakout_ok': i == 3,
            })
        _build_db(rows)

        con = duckdb.connect(TEST_DB)
        ViewManager._create_v_d1_candidates(con)
        exit_date = con.execute(
            "SELECT DISTINCT exit_date FROM v_d1_candidates WHERE ticker='AAPL'"
        ).fetchone()[0]
        con.close()
        # No day after last trend_ok in price_data -> NULL
        self.assertIsNone(exit_date)


class TestHydratedView(unittest.TestCase):
    """Test v_d2r_hydrated exit detection."""

    def test_exit_on_trend_break(self):
        """Trade should exit when trend_ok goes False."""
        dates = _dates('2024-01-02', 20)
        rows = []
        for i, d in enumerate(dates):
            trend = i < 12
            rows.append({
                'ticker': 'AAPL', 'date': d, 'close': 100.0 + i,
                'trend_ok': trend,
                'breakout_ok': i == 3,
            })
        _build_db(rows)

        con = duckdb.connect(TEST_DB)
        ViewManager._create_v_d1_candidates(con)
        ViewManager._create_v_d2r_hydrated(con)
        exit_date = con.execute(
            "SELECT sepa_exit_date FROM v_d2r_hydrated WHERE ticker='AAPL' LIMIT 1"
        ).fetchone()[0]
        con.close()
        # Exit = next trading day after last trend_ok (day 11) = day 12
        if hasattr(exit_date, 'date'):
            exit_date = exit_date.date()
        self.assertEqual(exit_date, dates[12])


def tearDownModule():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


if __name__ == '__main__':
    unittest.main()
