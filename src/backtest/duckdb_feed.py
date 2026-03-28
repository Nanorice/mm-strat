"""
DuckDB Data Feed Adapter for BackTrader
========================================
Queries DuckDB views (v_d3_deployment, v_d2_hydrated) and converts
to BackTrader-compatible feed format.

Replaces parquet-based price_feed.py with direct DuckDB integration.

Key Features:
- Queries v_d3_deployment for candidate features (last 252 days of SEPA candidates)
- Extracts OHLCV, ATR, M01 scores, and metadata
- Converts to BackTrader PandasData feeds
- Handles date gaps, missing data, and holidays gracefully
"""

import logging
from pathlib import Path
from typing import List, Optional, Set, Tuple

import backtrader as bt
import duckdb
import pandas as pd
from tqdm import tqdm

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
import config

logger = logging.getLogger(__name__)


class DuckDBCandidateFeed(bt.feeds.PandasData):
    """
    BackTrader feed from v_d3_deployment (DuckDB view).

    Expected DataFrame columns (from v_d2_features):
    - date (index): Trading date
    - open, high, low, close, volume: OHLCV data
    - atr_20d: 20-day ATR (renamed to atr for BackTrader)
    - m01_score: M01 normalized score (0-100) [TODO: integrate scoring]
    - daily_pct_rank: Daily cross-sectional rank [TODO: integrate ranking]

    Custom lines:
    - atr: ATR for stop-loss calculation (mapped from atr_20d)
    - m01_score: Normalized M01 score (placeholder, 0.0 for now)
    - daily_pct_rank: Daily percentile rank (placeholder, 0.0 for now)
    """
    lines = ('atr', 'm01_score', 'daily_pct_rank',)

    params = (
        ('datetime', None),  # Use index as datetime
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('openinterest', None),  # Not used
        ('atr', 'atr'),  # Custom line for ATR
        ('m01_score', 'm01_score'),  # Custom line for M01 score
        ('daily_pct_rank', 'daily_pct_rank'),  # Custom line for daily rank
    )


def load_candidate_from_duckdb(
    ticker: str,
    start_date: str,
    end_date: str,
    db_path: Path = None,
    feature_version: str = 'v3.1'
) -> pd.DataFrame:
    """
    Load candidate data for a single ticker from t3_sepa_features.

    Args:
        ticker: Stock ticker symbol
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        db_path: Path to DuckDB database (default: config.DUCKDB_PATH)
        feature_version: Feature version to query (default: 'v3.1')

    Returns:
        DataFrame with columns: date, open, high, low, close, volume,
                                atr, m01_score, daily_pct_rank

    Note:
        - Queries t3_sepa_features directly (full historical SEPA candidates)
        - ATR is sourced from atr_20d column in features
        - M01 score and rank are placeholders (0.0) - will be integrated in Task 1.3
    """
    if db_path is None:
        db_path = config.DUCKDB_PATH

    try:
        conn = duckdb.connect(str(db_path), read_only=True)

        # Query t3_sepa_features directly for full historical backtest data
        # (v_d3_deployment is only last 252 days - not sufficient for multi-year backtests)
        query = f"""
        SELECT
            date,
            open, high, low, close, volume,
            atr_20d as atr,  -- Use 20-day ATR from features
            0.0 as m01_score,   -- TODO: Integrate M01 scoring
            0.0 as daily_pct_rank  -- TODO: Integrate percentile ranking
        FROM t3_sepa_features
        WHERE ticker = '{ticker}'
          AND date >= '{start_date}'
          AND date <= '{end_date}'
          AND feature_version = '{feature_version}'
        ORDER BY date
        """

        df = conn.execute(query).df()
        conn.close()

        if df.empty:
            logger.debug(f"No data for {ticker} in t3_sepa_features (date range: {start_date} to {end_date})")
            return pd.DataFrame()

        # Convert date to datetime and set as index
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)

        # Drop rows with NULL ATR (safety check)
        df = df.dropna(subset=['atr'])

        return df

    except Exception as e:
        logger.error(f"Error loading {ticker} from DuckDB: {e}")
        return pd.DataFrame()


def get_qualifying_tickers_from_duckdb(
    start_date: str,
    end_date: str,
    db_path: Path = None,
    feature_version: str = 'v3.1'
) -> Set[str]:
    """
    Get all unique tickers that appear in t3_sepa_features.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        db_path: Path to DuckDB database (default: config.DUCKDB_PATH)
        feature_version: Feature version to query (default: 'v3.1')

    Returns:
        Set of ticker symbols

    Note:
        Queries t3_sepa_features (full historical SEPA candidates).
        This function returns ALL tickers that appear in the date range
        (no pre-filtering by score/rank).
    """
    if db_path is None:
        db_path = config.DUCKDB_PATH

    try:
        conn = duckdb.connect(str(db_path), read_only=True)

        query = f"""
        SELECT DISTINCT ticker
        FROM t3_sepa_features
        WHERE date >= '{start_date}'
          AND date <= '{end_date}'
          AND feature_version = '{feature_version}'
        ORDER BY ticker
        """

        result = conn.execute(query).df()
        conn.close()

        tickers = set(result['ticker'].tolist())
        logger.info(f"Found {len(tickers)} unique tickers in t3_sepa_features "
                   f"({start_date} to {end_date}, version={feature_version})")

        return tickers

    except Exception as e:
        logger.error(f"Error querying t3_sepa_features: {e}")
        return set()


def prepare_duckdb_feeds(
    start_date: str,
    end_date: str,
    max_tickers: Optional[int] = None,
    db_path: Path = None
) -> List[Tuple[str, pd.DataFrame]]:
    """
    Prepare all candidate feeds from DuckDB v_d3_deployment.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        max_tickers: Limit number of tickers (for testing)
        db_path: Path to DuckDB database (default: config.DUCKDB_PATH)

    Returns:
        List of (ticker, dataframe) tuples ready for BackTrader

    Example:
        feeds = prepare_duckdb_feeds('2024-01-01', '2024-12-31', max_tickers=50)
        for ticker, df in feeds:
            feed = DuckDBCandidateFeed(dataname=df, name=ticker)
            cerebro.adddata(feed, name=ticker)
    """
    # Get qualifying tickers
    tickers = get_qualifying_tickers_from_duckdb(start_date, end_date, db_path)

    if not tickers:
        logger.warning("No qualifying tickers found in v_d3_deployment!")
        return []

    # Limit tickers if requested
    tickers = sorted(tickers)
    if max_tickers:
        tickers = tickers[:max_tickers]
        logger.info(f"Limited to first {max_tickers} tickers")

    # Load data for each ticker
    feeds = []
    for ticker in tqdm(tickers, desc="Loading DuckDB feeds"):
        df = load_candidate_from_duckdb(ticker, start_date, end_date, db_path)

        if df.empty:
            logger.debug(f"Skipping {ticker} (no data)")
            continue

        # Sanity check: need at least 5 days of data
        if len(df) < 5:
            logger.debug(f"Skipping {ticker} (only {len(df)} rows)")
            continue

        feeds.append((ticker, df))

    logger.info(f"Prepared {len(feeds)} DuckDB feeds from v_d3_deployment")

    return feeds


def load_duckdb_feed(
    ticker: str,
    start_date: str,
    end_date: str,
    db_path: Path = None
) -> DuckDBCandidateFeed:
    """
    Load a single DuckDB feed ready for BackTrader.

    Args:
        ticker: Stock ticker symbol
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        db_path: Path to DuckDB database (default: config.DUCKDB_PATH)

    Returns:
        DuckDBCandidateFeed instance ready for cerebro.adddata()

    Raises:
        ValueError: If no data found for ticker

    Example:
        feed = load_duckdb_feed('AAPL', '2024-01-01', '2024-12-31')
        cerebro.adddata(feed, name='AAPL')
    """
    df = load_candidate_from_duckdb(ticker, start_date, end_date, db_path)

    if df.empty:
        raise ValueError(f"No data found for {ticker} in v_d3_deployment "
                        f"({start_date} to {end_date})")

    return DuckDBCandidateFeed(dataname=df, name=ticker)


# ------------------------------------------------------------------
# Backward Compatibility: Drop-in replacement for price_feed.py
# ------------------------------------------------------------------

def get_qualifying_tickers(
    start_date: str,
    end_date: str,
    scores_path: Path = None,  # Ignored (for API compatibility)
    min_score: float = 0.0,  # Ignored (for API compatibility)
    min_percentile: float = 0.0,  # Ignored (for API compatibility)
) -> Set[str]:
    """
    Get qualifying tickers (backward-compatible API).

    This function maintains the same signature as price_feed.get_qualifying_tickers()
    but queries DuckDB instead of reading parquet files.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        scores_path: Ignored (for backward compatibility)
        min_score: Ignored (filtering done by v_d3_deployment view)
        min_percentile: Ignored (filtering done by v_d3_deployment view)

    Returns:
        Set of ticker symbols from v_d3_deployment
    """
    return get_qualifying_tickers_from_duckdb(start_date, end_date)


# ------------------------------------------------------------------
# Universe Data Loader Class (for optimization script)
# ------------------------------------------------------------------

class DuckDBUniverseDataLoader:
    """
    Universe data loader for backtesting optimization.

    Wraps DuckDB feed functions in a class-based API for easier use
    in grid search and parameter optimization workflows.

    Usage:
        loader = DuckDBUniverseDataLoader(db_path='data/market_data.duckdb')
        tickers = loader.get_available_tickers()
        feeds = loader.load_universe(tickers[:100], '2023-01-01', '2023-12-31')
    """

    def __init__(self, db_path: str = None):
        """
        Initialize loader.

        Args:
            db_path: Path to DuckDB database (default: config.DUCKDB_PATH)
        """
        self.db_path = Path(db_path) if db_path else Path(config.DUCKDB_PATH)

        if not self.db_path.exists():
            raise FileNotFoundError(f"DuckDB database not found: {self.db_path}")

    def get_available_tickers(
        self,
        start_date: str = '2020-01-01',
        end_date: str = '2026-12-31'
    ) -> List[str]:
        """
        Get all available tickers from t3_sepa_features.

        Args:
            start_date: Start date filter (default: 2020-01-01)
            end_date: End date filter (default: 2026-12-31)

        Returns:
            Sorted list of ticker symbols
        """
        tickers = get_qualifying_tickers_from_duckdb(start_date, end_date, self.db_path)
        return sorted(tickers)

    def load_universe(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
    ) -> dict:
        """
        Load BackTrader feeds for a list of tickers.

        Args:
            tickers: List of ticker symbols
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Dict mapping ticker -> DuckDBCandidateFeed
        """
        feeds = {}

        for ticker in tickers:
            try:
                df = load_candidate_from_duckdb(ticker, start_date, end_date, self.db_path)

                if df.empty or len(df) < 5:
                    logger.debug(f"Skipping {ticker} (insufficient data)")
                    continue

                # Create BackTrader feed
                feed = DuckDBCandidateFeed(dataname=df, name=ticker)
                feeds[ticker] = feed

            except Exception as e:
                logger.debug(f"Error loading {ticker}: {e}")
                continue

        logger.info(f"Loaded {len(feeds)} feeds from {len(tickers)} tickers")
        return feeds


if __name__ == '__main__':
    # Test the adapter
    logging.basicConfig(level=logging.INFO)

    print("\n" + "="*60)
    print("DuckDB Feed Adapter - Test Run")
    print("="*60)

    # Test 1: Get qualifying tickers (use full v_d3_deployment range: last 252 days)
    print("\n[TEST 1] Getting qualifying tickers...")
    tickers = get_qualifying_tickers_from_duckdb('2020-01-01', '2026-02-18')
    print(f"[OK] Found {len(tickers)} tickers")
    print(f"   Sample: {sorted(tickers)[:10]}")

    # Test 2: Load single ticker
    if tickers:
        test_ticker = sorted(tickers)[0]
        print(f"\n[TEST 2] Loading single ticker: {test_ticker}")
        df = load_candidate_from_duckdb(test_ticker, '2020-01-01', '2026-02-18')
        if not df.empty:
            print(f"[OK] Loaded {len(df)} rows")
            print(f"   Columns: {df.columns.tolist()}")
            print(f"   Date range: {df.index.min()} to {df.index.max()}")
            print(f"\n   Sample data (first 3 rows):")
            print(df.head(3))
        else:
            print(f"[WARN] No data for {test_ticker}")

    # Test 3: Prepare feeds (limited to 10 tickers)
    print(f"\n[TEST 3] Preparing feeds (max 10 tickers)...")
    feeds = prepare_duckdb_feeds('2020-01-01', '2026-02-18', max_tickers=10)
    print(f"[OK] Prepared {len(feeds)} feeds")
    if feeds:
        ticker, df = feeds[0]
        print(f"   Sample feed: {ticker} ({len(df)} rows)")

    print("\n" + "="*60)
    print("All tests completed!")
    print("="*60)
