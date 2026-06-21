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


FEATURE_VERSION = 'v3.1'


def _build_db(feature_rows: list[dict], profiles: list[dict] | None = None) -> str:
    """Build a minimal DuckDB for view tests, matching the Phase 5.1 view sources.

    v_d1_candidates reads `t2_screener_features` (session/trend/breakout) and
    `t3_sepa_features` (enriched features, LEFT JOIN'd on ticker+date), plus
    `price_data` (entry/exit prices) and `company_profiles`. We seed all four
    from one row spec so a candidate actually materializes.

    Each row in `feature_rows` must have at minimum:
        ticker, date, trend_ok, breakout_ok, close
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
        'feature_version': FEATURE_VERSION,
        # v3.1 pct_chg columns — v_d1_candidates' final SELECT converts each to a
        # *_delta ratio, so they must exist on t3_sepa_features.
        'natr_pct_chg': 0.0, 'vcp_ratio_pct_chg': 0.0,
        'consolidation_width_pct_chg': 0.0,
        'price_vs_sma_50_pct_chg': 0.0, 'price_vs_sma_150_pct_chg': 0.0,
        'price_vs_sma_200_pct_chg': 0.0,
        'rs_pct_chg': 0.0, 'rs_ma_pct_chg': 0.0, 'dry_up_volume_pct_chg': 0.0,
        'high_52w_pct_chg': 0.0, 'low_52w_pct_chg': 0.0,
        'lowest_low_20d_pct_chg': 0.0, 'highest_high_20d_pct_chg': 0.0,
        'rsi_14_pct_chg': 0.0,
        'dist_from_52w_high_pct_chg': 0.0, 'dist_from_52w_low_pct_chg': 0.0,
        'dist_from_20d_low_pct_chg': 0.0, 'dist_from_20d_high_pct_chg': 0.0,
    }

    rows = []
    for r in feature_rows:
        row = {**defaults, **r}
        rows.append(row)

    df = pd.DataFrame(rows)
    # t2_screener_features: session/trend source for v_d1_candidates. The view
    # reads ticker, date, trend_ok, breakout_ok, close, sma_50/150/200.
    con.execute("CREATE TABLE t2_screener_features AS SELECT * FROM df")
    # t3_sepa_features: enriched feature source (INNER JOIN'd in v_d1_candidates'
    # `enriched` CTE on ticker+date+feature_version). Same rows/columns.
    con.execute("CREATE TABLE t3_sepa_features AS SELECT * FROM df")

    # price_data (entry/exit prices + v_d2_hydrated hydration)
    price_rows = [
        {'ticker': r['ticker'], 'date': r['date'],
         'open': r.get('open', 100.0), 'high': r.get('high', 105.0),
         'low': r.get('low', 95.0), 'close': r.get('close', 100.0),
         'volume': r.get('volume', 5_000_000)}
        for r in feature_rows
    ]
    pdf = pd.DataFrame(price_rows)
    con.execute("CREATE TABLE price_data AS SELECT * FROM pdf")

    # company_profiles
    if profiles is None:
        tickers = list({r['ticker'] for r in feature_rows})
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
        try:
            vm._create_v_d1_candidates(con)
            trade_ids = con.execute(
                "SELECT DISTINCT trade_id FROM v_d1_candidates WHERE ticker='AAPL'"
            ).fetchall()
        finally:
            con.close()
        self.assertEqual(len(trade_ids), 1, f"Expected 1 trade, got {len(trade_ids)}: {trade_ids}")

    def test_broken_trend_two_trades(self):
        """Session (C1+C2+C6) breaks between 2 breakouts -> 2 trade_ids.

        Sessions are bounded by trend_c8 = close > sma_50/150/200, NOT by
        trend_ok. To split the session, drop close below sma_50 (=98) on days
        8-9, then recover. A breakout in each session => 2 trades.
        """
        dates = _dates('2024-01-02', 20)
        rows = []
        for i, d in enumerate(dates):
            in_session = not (8 <= i <= 9)        # close dips below SMA on 8-9
            close = 110.0 + i if in_session else 90.0
            rows.append({
                'ticker': 'MSFT', 'date': d, 'close': close,
                'trend_ok': True,
                'breakout_ok': i in (2, 12),       # one breakout per session
            })
        _build_db(rows)

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        try:
            vm._create_v_d1_candidates(con)
            trade_ids = con.execute(
                "SELECT DISTINCT trade_id FROM v_d1_candidates WHERE ticker='MSFT'"
            ).fetchall()
        finally:
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
        try:
            vm._create_v_d1_candidates(con)
            entry = con.execute(
                "SELECT DISTINCT entry_date FROM v_d1_candidates WHERE ticker='TSLA'"
            ).fetchone()[0]
        finally:
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
        try:
            vm._create_v_d1_candidates(con)
            count = con.execute(
                "SELECT COUNT(*) FROM v_d1_candidates WHERE ticker='GOOG'"
            ).fetchone()[0]
        finally:
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

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        try:
            vm._create_v_d1_candidates(con)
            row_count = con.execute(
                "SELECT COUNT(*) FROM v_d1_candidates WHERE ticker='NVDA'"
            ).fetchone()[0]
            trade_count = con.execute(
                "SELECT COUNT(DISTINCT trade_id) FROM v_d1_candidates WHERE ticker='NVDA'"
            ).fetchone()[0]
            min_date = con.execute(
                "SELECT MIN(date) FROM v_d1_candidates WHERE ticker='NVDA'"
            ).fetchone()[0]
        finally:
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
        try:
            vm._create_v_d1_candidates(con)
            trigger_count = con.execute(
                "SELECT COUNT(*) FROM v_d1_candidates WHERE ticker='META' AND is_new_trigger=1"
            ).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(trigger_count, 1, f"Expected 1 trigger row, got {trigger_count}")

    def test_missing_t3_row_keeps_trade_with_null_features(self):
        """A t3 hole on the entry date must NOT delete the trade (LEFT JOIN guard).

        t3_sepa_features is lazily materialized and can have transient (ticker,date)
        holes. The entry-row join is LEFT (not INNER): a missing t3 row yields a
        visible trade with NULL features instead of silently vanishing. Regression
        guard for the v_d1_candidates trade-drop bug (F1).
        """
        dates = _dates('2024-01-02', 12)
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                'ticker': 'HPE', 'date': d, 'close': 100.0 + i,
                'trend_ok': True,
                'breakout_ok': i == 4,           # entry on index 4
                'rsi_14': 55.0,
            })
        _build_db(rows)

        entry_date = dates[4]
        con = duckdb.connect(TEST_DB)
        try:
            # Punch a hole: delete the t3 row on the entry date (t2 row stays).
            con.execute(
                "DELETE FROM t3_sepa_features WHERE ticker='HPE' AND date=?", [entry_date]
            )
        finally:
            con.close()

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        try:
            vm._create_v_d1_candidates(con)
            row = con.execute(
                "SELECT entry_date, rsi_14, return_pct FROM v_d1_candidates "
                "WHERE ticker='HPE'"
            ).fetchall()
        finally:
            con.close()
        self.assertEqual(len(row), 1, f"Trade must survive the t3 hole, got {len(row)} rows")
        self.assertEqual(row[0][0], entry_date, "entry_date must come from candidates, not t3")
        self.assertIsNone(row[0][1], "rsi_14 must be NULL (t3 row absent)")
        self.assertIsNotNone(row[0][2], "return_pct comes from price_data, must be non-NULL")

    def test_no_liquidity_filter_in_view(self):
        """v_d1_candidates has NO liquidity filter (Phase 5.1+).

        Liquidity screening moved upstream to screener_membership, so an
        otherwise-valid breakout still produces a candidate regardless of
        volume. (Previously this view filtered vol_avg_20 < 500k; that filter
        was removed.) Regression guard against silently re-adding it.
        """
        dates = _dates('2024-01-02', 10)
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                'ticker': 'TINY', 'date': d, 'close': 100.0 + i,
                'trend_ok': True,
                'breakout_ok': i == 3,
                'vol_avg_20': 100_000,   # low volume — no longer filtered here
            })
        _build_db(rows)

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        try:
            vm._create_v_d1_candidates(con)
            count = con.execute(
                "SELECT COUNT(*) FROM v_d1_candidates WHERE ticker='TINY'"
            ).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(count, 1, f"Expected 1 candidate (no liquidity filter), got {count}")


class TestTradePrices(unittest.TestCase):
    """Test entry_price, exit_price, exit_date, return_pct on v_d1_candidates.

    Phase 5.1 semantics: entry_price = close ON entry_date (`pe.close`), exit
    is the first trading day AFTER the session (C1+C2+C6) breaks, exit_price =
    that day's close, return_pct = ((exit/entry) - 1) * 100 (percentage).
    Sessions are bounded by close vs sma_50/150/200, so tests break a session
    by dropping close below sma_50 (=98).
    """

    def test_entry_price_is_entry_day_close(self):
        """entry_price should be the close on entry_date (not next-day open)."""
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

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        try:
            vm._create_v_d1_candidates(con)
            entry_price = con.execute(
                "SELECT DISTINCT entry_price FROM v_d1_candidates WHERE ticker='AAPL'"
            ).fetchone()[0]
        finally:
            con.close()
        # Entry at index 3, close = 100.0 + 3 = 103.0
        self.assertAlmostEqual(entry_price, 103.0)

    @staticmethod
    def _session_break_rows(ticker: str, dates: list, break_at: int) -> list[dict]:
        """Rows where close stays above sma_50 (=98) until index `break_at`,
        then drops below — so the C1+C2+C6 session ends at break_at-1. Breakout
        at index 3. open is offset from close so we can tell them apart."""
        rows = []
        for i, d in enumerate(dates):
            in_session = i < break_at
            close = 100.0 + i if in_session else 90.0
            rows.append({
                'ticker': ticker, 'date': d,
                'open': close - 50.0, 'close': close,
                'trend_ok': True,
                'breakout_ok': i == 3,
            })
        return rows

    def test_exit_date_is_next_day_after_session_break(self):
        """exit_date = first trading day after the last in-session day."""
        dates = _dates('2024-01-02', 20)
        _build_db(self._session_break_rows('AAPL', dates, break_at=12))

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        try:
            vm._create_v_d1_candidates(con)
            exit_date = con.execute(
                "SELECT DISTINCT exit_date FROM v_d1_candidates WHERE ticker='AAPL'"
            ).fetchone()[0]
        finally:
            con.close()
        if hasattr(exit_date, 'date'):
            exit_date = exit_date.date()
        # Last in-session day = dates[11], next trading day = dates[12]
        self.assertEqual(exit_date, dates[12])

    def test_exit_price_is_exit_day_close(self):
        """exit_price = close on exit_date (COALESCE(next_close, close))."""
        dates = _dates('2024-01-02', 20)
        _build_db(self._session_break_rows('AAPL', dates, break_at=12))

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        try:
            vm._create_v_d1_candidates(con)
            exit_price = con.execute(
                "SELECT DISTINCT exit_price FROM v_d1_candidates WHERE ticker='AAPL'"
            ).fetchone()[0]
        finally:
            con.close()
        # Exit day = dates[12], close = 90.0 (out-of-session value)
        self.assertAlmostEqual(exit_price, 90.0)

    def test_return_pct_correct(self):
        """return_pct = ((exit_price / entry_price) - 1) * 100."""
        dates = _dates('2024-01-02', 20)
        _build_db(self._session_break_rows('AAPL', dates, break_at=12))

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        try:
            vm._create_v_d1_candidates(con)
            return_pct = con.execute(
                "SELECT DISTINCT return_pct FROM v_d1_candidates WHERE ticker='AAPL'"
            ).fetchone()[0]
        finally:
            con.close()
        # entry_price = close@3 = 103.0, exit_price = close@12 = 90.0
        expected = ((90.0 / 103.0) - 1.0) * 100.0
        self.assertAlmostEqual(return_pct, expected, places=6)

    def test_exit_date_falls_back_when_session_never_breaks(self):
        """If the session runs to the end of data, there's no next day after the
        last in-session date, so exit_date COALESCEs to last_trend_date itself."""
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

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        try:
            vm._create_v_d1_candidates(con)
            exit_date = con.execute(
                "SELECT DISTINCT exit_date FROM v_d1_candidates WHERE ticker='AAPL'"
            ).fetchone()[0]
        finally:
            con.close()
        if hasattr(exit_date, 'date'):
            exit_date = exit_date.date()
        # No next day after the last in-session date -> COALESCE to last_trend_date
        self.assertEqual(exit_date, dates[-1])


class TestHydratedView(unittest.TestCase):
    """Test v_d2_hydrated exit detection."""

    def test_exit_on_session_break(self):
        """sepa_exit_date should propagate v_d1_candidates.exit_date (first day
        after the C1+C2+C6 session breaks)."""
        dates = _dates('2024-01-02', 20)
        rows = []
        for i, d in enumerate(dates):
            in_session = i < 12          # session ends at index 11
            close = 100.0 + i if in_session else 90.0
            rows.append({
                'ticker': 'AAPL', 'date': d, 'close': close,
                'trend_ok': True,
                'breakout_ok': i == 3,
            })
        _build_db(rows)

        vm = ViewManager(TEST_DB)
        con = duckdb.connect(TEST_DB)
        try:
            vm._create_v_d1_candidates(con)
            vm._create_v_d2_hydrated(con)
            exit_date = con.execute(
                "SELECT sepa_exit_date FROM v_d2_hydrated WHERE ticker='AAPL' LIMIT 1"
            ).fetchone()[0]
        finally:
            con.close()
        # Exit = next trading day after last in-session day (11) = day 12
        if hasattr(exit_date, 'date'):
            exit_date = exit_date.date()
        self.assertEqual(exit_date, dates[12])


def tearDownModule():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


if __name__ == '__main__':
    unittest.main()
