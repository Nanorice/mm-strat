"""
DuckDB Data Loader - SQL-Native Batch Loading
==============================================
Replaces file-based ThreadPool loading with single SQL queries.

Key improvements:
1. Single SQL query loads 500+ tickers in <1s (vs 5-30s with ThreadPool)
2. Vectorized ASOF JOIN for fundamentals (vs 5-50s loop)
3. Pre-computed features from daily_features table
4. No file I/O overhead

Performance targets:
- Load 500 tickers: <1s (vs 5-30s)
- Merge fundamentals: <1s (vs 5-50s)
- Total speedup: 5-30x
"""

import duckdb
import pandas as pd
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import logging

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

# Database path
DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"


class DuckDBDataLoader:
    """
    SQL-native data loader for scanner operations.

    Replaces:
    - DataRepository.get_batch_data() - ThreadPool file loading
    - FundamentalMerger - Loop-based as-of join
    - UniverseEngine - Pre-computed universe cache
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize data loader.

        Args:
            db_path: Path to DuckDB database
        """
        self.db_path = str(db_path or DB_PATH)
        self._feature_columns_cache = None

    def _get_feature_columns(self, con) -> List[str]:
        """Get actual column names from daily_features table (cached)."""
        if self._feature_columns_cache is None:
            try:
                schema = con.execute("DESCRIBE daily_features").fetchall()
                self._feature_columns_cache = [row[0] for row in schema]
            except Exception:
                self._feature_columns_cache = []
        return self._feature_columns_cache

    def _validate_columns(self, con, required: List[str], table: str = 'daily_features') -> List[str]:
        """Validate that required columns exist in table schema. Returns list of missing columns."""
        actual = set(self._get_feature_columns(con) if table == 'daily_features' else
                     [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()])
        return [c for c in required if c not in actual]

    def get_universe_tickers(
        self,
        min_price: float = 5.0,
        min_volume: int = 500000,
        as_of_date: Optional[str] = None
    ) -> List[str]:
        """
        Get active universe tickers with recent data.

        Args:
            min_price: Minimum stock price
            min_volume: Minimum 20d average volume
            as_of_date: Date to query (default: latest date in database)

        Returns:
            List of ticker symbols meeting criteria
        """
        con = duckdb.connect(self.db_path)

        try:
            if as_of_date is None:
                as_of_date = con.execute("SELECT MAX(date) FROM price_data").fetchone()[0]

            query = f"""
                SELECT DISTINCT ticker
                FROM daily_features
                WHERE date = '{as_of_date}'
                  AND close >= {min_price}
                  AND vol_avg_20 >= {min_volume}
                ORDER BY ticker
            """

            tickers = con.execute(query).df()['ticker'].tolist()

            logger.info(f"Loaded {len(tickers)} tickers from universe (as of {as_of_date})")
            return tickers

        finally:
            con.close()

    def get_sepa_candidates(
        self,
        as_of_date: Optional[str] = None,
        use_view: bool = True
    ) -> pd.DataFrame:
        """
        Get SEPA strategy candidates from pre-computed view.

        Uses v_sepa_candidates view which applies SEPA criteria:
        - Price > $5
        - Volume > 500K (20d avg)
        - Market Cap > $300M
        - SMA(20) > SMA(50) (uptrend)
        - Price within 25% of 52w high
        - Relative strength > 0 (outperforming SPY)

        Args:
            as_of_date: Date to query (default: latest)
            use_view: If True, use v_sepa_candidates view. If False, run inline filter.

        Returns:
            DataFrame with SEPA candidates and features
        """
        con = duckdb.connect(self.db_path)

        try:
            if as_of_date is None:
                as_of_date = con.execute("SELECT MAX(date) FROM price_data").fetchone()[0]

            if use_view:
                # Use pre-computed view (full C1-C9 SEPA trend template)
                query = f"""
                    SELECT *
                    FROM v_sepa_candidates
                    WHERE date = '{as_of_date}'
                    ORDER BY rs_rating DESC
                """
            else:
                # Inline filter (for custom criteria)
                query = f"""
                    SELECT
                        df.*,
                        cp.sector,
                        cp.industry,
                        cp.market_cap
                    FROM daily_features df
                    LEFT JOIN company_profiles cp ON df.ticker = cp.ticker
                    WHERE df.date = '{as_of_date}'
                      AND df.close > 5
                      AND df.vol_avg_20 > 500000
                      AND df.close > df.sma_200
                      AND df.sma_50 > df.sma_200
                      AND df.pct_from_high_52w >= -0.25
                    ORDER BY df.rs_rating DESC
                """

            df = con.execute(query).df()

            logger.info(f"Loaded {len(df)} SEPA candidates (as of {as_of_date})")
            return df

        finally:
            con.close()

    def get_price_data_batch(
        self,
        tickers: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        include_features: bool = True
    ) -> Dict[str, pd.DataFrame]:
        """
        Batch load price data for multiple tickers.

        Replaces DataRepository.get_batch_data() which uses ThreadPool to read parquet files.
        Single SQL query returns all tickers in <1s (vs 5-30s for 500 tickers).

        Args:
            tickers: List of ticker symbols
            start_date: Start date (default: last 252 trading days)
            end_date: End date (default: latest date)
            include_features: If True, include computed features from daily_features table

        Returns:
            Dict mapping ticker to DataFrame with OHLCV data (and features if requested)
        """
        con = duckdb.connect(self.db_path)

        try:
            # Default date range
            if end_date is None:
                end_date = con.execute("SELECT MAX(date) FROM price_data").fetchone()[0]

            if start_date is None:
                # Last 252 trading days
                start_date = con.execute(f"""
                    SELECT MIN(date)
                    FROM (
                        SELECT DISTINCT date
                        FROM price_data
                        WHERE date <= '{end_date}'
                        ORDER BY date DESC
                        LIMIT 252
                    )
                """).fetchone()[0]

            # Build ticker list for SQL IN clause
            ticker_list = ','.join([f"'{t}'" for t in tickers])

            if include_features:
                # Dynamically select all feature columns (no hardcoded list)
                # f.* EXCLUDE avoids duplicate ticker/date/close columns from the join
                query = f"""
                    SELECT
                        p.ticker,
                        p.date,
                        p.open,
                        p.high,
                        p.low,
                        p.close,
                        p.volume,
                        f.* EXCLUDE (ticker, date, close)
                    FROM price_data p
                    LEFT JOIN daily_features f
                        ON p.ticker = f.ticker
                        AND p.date = f.date
                    WHERE p.ticker IN ({ticker_list})
                      AND p.date >= '{start_date}'
                      AND p.date <= '{end_date}'
                    ORDER BY p.ticker, p.date
                """
            else:
                # Just OHLCV
                query = f"""
                    SELECT
                        ticker, date, open, high, low, close, volume
                    FROM price_data
                    WHERE ticker IN ({ticker_list})
                      AND date >= '{start_date}'
                      AND date <= '{end_date}'
                    ORDER BY ticker, date
                """

            # Execute query and pivot into dict
            df_all = con.execute(query).df()

            # Split into dict by ticker
            result = {}
            for ticker in tickers:
                ticker_df = df_all[df_all['ticker'] == ticker].copy()
                if not ticker_df.empty:
                    # Set date as index
                    ticker_df = ticker_df.set_index('date')
                    ticker_df = ticker_df.drop(columns=['ticker'])
                    result[ticker] = ticker_df

            logger.info(f"Loaded price data for {len(result)}/{len(tickers)} tickers ({start_date} to {end_date})")
            return result

        finally:
            con.close()

    def get_fundamentals_batch(
        self,
        tickers: List[str],
        as_of_date: str
    ) -> pd.DataFrame:
        """
        Batch load fundamentals using vectorized ASOF JOIN.

        Replaces FundamentalMerger's loop-based as-of join.
        Single SQL query returns all fundamentals in <1s (vs 5-50s for loop).

        Args:
            tickers: List of ticker symbols
            as_of_date: Date to retrieve fundamentals as-of

        Returns:
            DataFrame with latest fundamentals per ticker (as of as_of_date)
        """
        con = duckdb.connect(self.db_path)

        try:
            ticker_list = ','.join([f"'{t}'" for t in tickers])

            # ASOF JOIN to get latest fundamentals as-of scan_date
            query = f"""
                WITH ticker_dates AS (
                    SELECT UNNEST([{ticker_list}]) as ticker, '{as_of_date}'::DATE as as_of_date
                ),
                latest_fundamentals AS (
                    SELECT
                        td.ticker,
                        f.*
                    FROM ticker_dates td
                    ASOF LEFT JOIN fundamentals f
                        ON td.ticker = f.ticker
                        AND td.as_of_date >= f.report_date
                    WHERE f.ticker IS NOT NULL
                )
                SELECT * FROM latest_fundamentals
            """

            df = con.execute(query).df()

            logger.info(f"Loaded fundamentals for {len(df)} tickers (as of {as_of_date})")
            return df

        finally:
            con.close()

    def get_macro_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Load macroeconomic data for M03 regime calculation.

        Args:
            start_date: Start date (default: last 252 trading days)
            end_date: End date (default: latest)

        Returns:
            DataFrame with macro series (wide format: date, WALCL, WTREGEN, RRPONTSYD, BAMLH0A0HYM2, VIX)
        """
        con = duckdb.connect(self.db_path)

        try:
            if end_date is None:
                end_date = con.execute("SELECT MAX(date) FROM macro_data").fetchone()[0]

            if start_date is None:
                # Last 252 trading days
                start_date = con.execute(f"""
                    SELECT MIN(date)
                    FROM (
                        SELECT DISTINCT date
                        FROM macro_data
                        WHERE date <= '{end_date}'
                        ORDER BY date DESC
                        LIMIT 252
                    )
                """).fetchone()[0]

            # Pivot macro data to wide format
            query = f"""
                SELECT
                    date,
                    MAX(CASE WHEN series_id = 'WALCL' THEN value END) as WALCL,
                    MAX(CASE WHEN series_id = 'WTREGEN' THEN value END) as WTREGEN,
                    MAX(CASE WHEN series_id = 'RRPONTSYD' THEN value END) as RRPONTSYD,
                    MAX(CASE WHEN series_id = 'BAMLH0A0HYM2' THEN value END) as BAMLH0A0HYM2,
                    MAX(CASE WHEN series_id = 'VIX' THEN value END) as VIX
                FROM macro_data
                WHERE date >= '{start_date}' AND date <= '{end_date}'
                GROUP BY date
                ORDER BY date
            """

            df = con.execute(query).df()

            logger.info(f"Loaded macro data ({start_date} to {end_date})")
            return df

        finally:
            con.close()

    def get_latest_trading_day(self) -> str:
        """
        Get the latest trading day in the database.

        Returns:
            Latest date as string (YYYY-MM-DD)
        """
        con = duckdb.connect(self.db_path)

        try:
            latest_date = con.execute("SELECT MAX(date) FROM price_data").fetchone()[0]
            return str(latest_date)

        finally:
            con.close()

    def get_ticker_data_single(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        include_features: bool = True
    ) -> Optional[pd.DataFrame]:
        """
        Load data for a single ticker (convenience method).

        Args:
            ticker: Ticker symbol
            start_date: Start date
            end_date: End date
            include_features: Include computed features

        Returns:
            DataFrame with price data (and features if requested), or None if no data
        """
        result = self.get_price_data_batch(
            [ticker],
            start_date=start_date,
            end_date=end_date,
            include_features=include_features
        )

        return result.get(ticker)

    def get_sepa_stats(self, as_of_date: Optional[str] = None) -> Dict:
        """
        Get statistics about SEPA candidates.

        Args:
            as_of_date: Date to query (default: latest)

        Returns:
            Dict with stats (total_candidates, avg_rs, avg_market_cap, etc.)
        """
        con = duckdb.connect(self.db_path)

        try:
            if as_of_date is None:
                as_of_date = con.execute("SELECT MAX(date) FROM price_data").fetchone()[0]

            result = con.execute(f"""
                SELECT
                    COUNT(*) as total_candidates,
                    AVG(rs_rating) as avg_rs,
                    AVG(volatility_20d) as avg_volatility,
                    AVG(adr_20d) as avg_adr,
                    AVG(pct_from_high_52w) as avg_pct_52w_high
                FROM v_sepa_candidates
                WHERE date = '{as_of_date}'
            """).fetchone()

            return {
                'as_of_date': as_of_date,
                'total_candidates': result[0] or 0,
                'avg_rs': result[1],
                'avg_volatility': result[2],
                'avg_adr': result[3],
                'avg_pct_52w_high': result[4]
            }

        finally:
            con.close()
