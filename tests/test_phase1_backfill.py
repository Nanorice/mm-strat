"""Unit tests for Phase 1 Universe Backfill Infrastructure.

Tests verify:
1. company_profiles populated with metadata from yfinance
2. price_data backfilled without filtering (includes penny stocks, etc.)
3. shares_history backfilled idempotently
4. Quarterly refresh discovers new tickers
5. SEC Edgar placeholder raises NotImplementedError
"""

from unittest.mock import MagicMock, patch

import duckdb
import pandas as pd
import pytest

from src.shares_engine import SharesEngine
from src.universe_backfill import UniverseBackfillEngine


@pytest.fixture
def temp_db(tmp_path):
    """Path to a temp DuckDB for testing — deliberately NOT pre-created.

    NamedTemporaryFile is the wrong tool: it leaves a zero-byte file behind, and
    DuckDB refuses to open one ("not a valid DuckDB database file") on Windows.
    Hand DuckDB a free path and let it create the file. tmp_path is cleaned up
    by pytest, so no manual unlink is needed.
    """
    return str(tmp_path / "test.duckdb")


@pytest.fixture
def backfill_engine(temp_db):
    """Create a UniverseBackfillEngine instance with temp database."""
    engine = UniverseBackfillEngine(db_path=temp_db)
    engine.ensure_tables()
    return engine


class TestCompanyProfiles:
    """Test company_profiles table population."""

    def test_company_profiles_schema_exists(self, backfill_engine):
        """Verify company_profiles table has required columns."""
        con = duckdb.connect(backfill_engine.db_path)
        try:
            result = con.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'company_profiles'
            """).fetchall()

            columns = {r[0] for r in result}
            required = {"ticker", "name", "sector", "industry", "exchange", "country", "market_cap", "beta"}
            assert required.issubset(columns), f"Missing columns: {required - columns}"
        finally:
            con.close()

    def test_write_company_profiles_idempotent(self, backfill_engine):
        """Verify INSERT OR IGNORE prevents duplicates."""
        df = pd.DataFrame({
            "ticker": ["AAPL", "MSFT"],
            "name": ["Apple", "Microsoft"],
            "sector": ["Technology", "Technology"],
            "industry": ["Software", "Software"],
            "exchange": ["NASDAQ", "NASDAQ"],
            "country": ["US", "US"],
            "market_cap": [2.9e12, 2.5e12],
            "beta": [1.2, 0.9],
        })

        # Write first time
        rows1 = backfill_engine._write_company_profiles(df)
        assert rows1 == 2

        # Write again (should be idempotent)
        rows2 = backfill_engine._write_company_profiles(df)
        assert rows2 == 2

        # Verify count hasn't increased
        con = duckdb.connect(backfill_engine.db_path)
        try:
            count = con.execute("SELECT COUNT(*) FROM company_profiles").fetchone()[0]
            assert count == 2
        finally:
            con.close()

    def test_company_profiles_no_filtering(self, backfill_engine):
        """Verify no pre-filtering applied (e.g., sector, market cap)."""
        # Write profile with NULL sector (no filtering should prevent this)
        df = pd.DataFrame({
            "ticker": ["PENNY"],
            "name": ["Penny Stock Co"],
            "sector": [None],
            "industry": [None],
            "exchange": ["OTC"],
            "country": ["US"],
            "market_cap": [1e6],  # $1M market cap
            "beta": [None],
        })

        rows = backfill_engine._write_company_profiles(df)
        assert rows == 1

        # Verify it was written
        con = duckdb.connect(backfill_engine.db_path)
        try:
            result = con.execute(
                "SELECT COUNT(*) FROM company_profiles WHERE ticker = 'PENNY'"
            ).fetchone()[0]
            assert result == 1
        finally:
            con.close()


class TestPriceData:
    """Test price_data table backfill."""

    def test_price_data_schema_exists(self, backfill_engine):
        """Verify price_data table has required columns."""
        con = duckdb.connect(backfill_engine.db_path)
        try:
            result = con.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'price_data'
            """).fetchall()

            columns = {r[0] for r in result}
            required = {"ticker", "date", "open", "high", "low", "close", "volume"}
            assert required.issubset(columns), f"Missing columns: {required - columns}"
        finally:
            con.close()

    def test_price_data_volume_ubigint(self, backfill_engine):
        """Verify volume is cast to UBIGINT (handles large volumes)."""
        df = pd.DataFrame({
            "ticker": ["AAPL"],
            "date": [pd.Timestamp("2024-01-01")],
            "open": [150.0],
            "high": [155.0],
            "low": [149.0],
            "close": [152.0],
            "volume": [1e10],  # Large volume
        })

        rows = backfill_engine._write_price_batch(df)
        assert rows == 1

        # Verify volume was written correctly
        con = duckdb.connect(backfill_engine.db_path)
        try:
            vol = con.execute(
                "SELECT volume FROM price_data WHERE ticker = 'AAPL'"
            ).fetchone()[0]
            assert vol == int(1e10)
        finally:
            con.close()

    def test_price_data_no_filtering(self, backfill_engine):
        """Verify price_data includes penny stocks, delisted tickers, etc."""
        # First populate company_profiles with penny stock
        profiles_df = pd.DataFrame({
            "ticker": ["SQQQ"],
            "name": ["Inverse NASDAQ ETF"],
            "sector": ["Financials"],
            "industry": ["Exchange Traded Funds"],
            "exchange": ["NASDAQ"],
            "country": ["US"],
            "market_cap": [100e6],
            "beta": [1.0],
        })
        backfill_engine._write_company_profiles(profiles_df)

        # Write price data for low-price ticker
        price_df = pd.DataFrame({
            "ticker": ["SQQQ"],
            "date": [pd.Timestamp("2024-01-01")],
            "open": [3.5],
            "high": [4.0],
            "low": [3.4],
            "close": [3.8],
            "volume": [1e6],
        })

        rows = backfill_engine._write_price_batch(price_df)
        assert rows == 1

        # Verify low-price ticker exists (no filtering)
        con = duckdb.connect(backfill_engine.db_path)
        try:
            count = con.execute(
                "SELECT COUNT(*) FROM price_data WHERE ticker = 'SQQQ' AND close < 5"
            ).fetchone()[0]
            assert count == 1
        finally:
            con.close()


class TestSharesHistory:
    """Test shares_history table backfill."""

    def test_shares_history_schema_exists(self, backfill_engine):
        """Verify shares_history table has required columns."""
        con = duckdb.connect(backfill_engine.db_path)
        try:
            result = con.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'shares_history'
            """).fetchall()

            columns = {r[0] for r in result}
            required = {"ticker", "date", "shares_outstanding"}
            assert required.issubset(columns), f"Missing columns: {required - columns}"
        finally:
            con.close()

    def test_shares_history_idempotent(self, backfill_engine):
        """Re-writing the same shares rows must not duplicate them.

        SharesEngine owns this upsert; backfill_shares delegates to it.
        """
        engine = SharesEngine(backfill_engine.db_path)
        df = pd.DataFrame({
            "ticker": ["AAPL", "AAPL"],
            "date": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")],
            "shares_outstanding": [17.3e9, 17.3e9],
        })

        rows1 = engine._upsert(df)
        assert rows1 == 2

        # Write same data again
        rows2 = engine._upsert(df)
        assert rows2 == 2

        # Verify count is still 2
        con = duckdb.connect(backfill_engine.db_path)
        try:
            count = con.execute("SELECT COUNT(*) FROM shares_history").fetchone()[0]
            assert count == 2
        finally:
            con.close()


class TestQuarterlyRefresh:
    """Test quarterly universe expansion mechanism."""

    @patch("src.universe_backfill.yf.screen")
    def test_quarterly_refresh_discovers_new_tickers(self, mock_screen, backfill_engine):
        """Verify quarterly_refresh identifies newly-listed tickers."""
        # Mock yfinance.screen() to return initial set
        mock_screen.return_value = {
            "quotes": [
                {"symbol": "AAPL"},
                {"symbol": "MSFT"},
            ]
        }

        # Populate initial tickers
        initial_tickers = backfill_engine._discover_via_yfinance()
        profiles_df = pd.DataFrame({
            "ticker": initial_tickers,
            "name": [f"Company {t}" for t in initial_tickers],
            "sector": ["Tech"] * len(initial_tickers),
            "industry": ["Software"] * len(initial_tickers),
            "exchange": ["NASDAQ"] * len(initial_tickers),
            "country": ["US"] * len(initial_tickers),
            "market_cap": [1e12] * len(initial_tickers),
            "beta": [1.0] * len(initial_tickers),
        })
        backfill_engine._write_company_profiles(profiles_df)

        # Mock yfinance.screen() to return new set (includes new ticker)
        mock_screen.return_value = {
            "quotes": [
                {"symbol": "AAPL"},
                {"symbol": "MSFT"},
                {"symbol": "GOOG"},  # New ticker
            ]
        }

        # Run quarterly refresh
        new_count = backfill_engine.quarterly_refresh()

        # Verify new ticker was added
        con = duckdb.connect(backfill_engine.db_path)
        try:
            count = con.execute(
                "SELECT COUNT(*) FROM company_profiles WHERE ticker = 'GOOG'"
            ).fetchone()[0]
            assert count == 1
        finally:
            con.close()


class TestEdgarPlaceholder:
    """SEC Edgar fundamentals.

    The placeholder tests that lived here asserted `backfill_fundamentals_edgar`
    and `normalize_edgar_metrics` raise NotImplementedError. Both methods were
    removed when FundamentalEdgarEngine gained a real XBRL implementation
    (`backfill()`), so the tests pinned a contract that no longer exists.
    Coverage for the live path belongs with that engine, not this backfill suite.
    """


class TestStatusAndValidation:
    """Test status and validation methods."""

    def test_get_status_empty_backfill(self, backfill_engine):
        """Verify get_status returns 0s for empty backfill."""
        status = backfill_engine.get_status()

        assert status["company_profiles"] == 0
        assert status["price_tickers_done"] == 0
        assert status["shares_tickers_done"] == 0
        assert status["price_pct_complete"] == 0.0

    def test_get_status_partial_backfill(self, backfill_engine):
        """Verify get_status shows progress correctly."""
        # Add profiles
        profiles_df = pd.DataFrame({
            "ticker": ["AAPL", "MSFT"],
            "name": ["Apple", "Microsoft"],
            "sector": ["Tech", "Tech"],
            "industry": ["Software", "Software"],
            "exchange": ["NASDAQ", "NASDAQ"],
            "country": ["US", "US"],
            "market_cap": [2.9e12, 2.5e12],
            "beta": [1.2, 0.9],
        })
        backfill_engine._write_company_profiles(profiles_df)

        # Add price data for only one ticker
        price_df = pd.DataFrame({
            "ticker": ["AAPL"],
            "date": [pd.Timestamp("2024-01-01")],
            "open": [150.0],
            "high": [155.0],
            "low": [149.0],
            "close": [152.0],
            "volume": [1e8],
        })
        backfill_engine._write_price_batch(price_df)

        status = backfill_engine.get_status()

        assert status["company_profiles"] == 2
        assert status["price_tickers_done"] == 1
        assert status["price_pct_complete"] == 50.0

    def test_validate_backfill_returns_stats(self, backfill_engine):
        """Verify validate_backfill returns expected statistics."""
        # Add sample price data
        price_df = pd.DataFrame({
            "ticker": ["AAPL"] * 10,
            "date": pd.date_range("2024-01-01", periods=10),
            "open": [150.0] * 10,
            "high": [155.0] * 10,
            "low": [149.0] * 10,
            "close": [152.0] * 10,
            "volume": [1e8] * 10,
        })
        backfill_engine._write_price_batch(price_df)

        stats = backfill_engine.validate_backfill()

        assert stats["tickers"] == 1
        assert stats["total_rows"] == 10
        assert stats["earliest_date"] is not None
        assert stats["latest_date"] is not None
