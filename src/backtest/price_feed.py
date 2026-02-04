"""
Price Feed Preparation for Backtesting
======================================
Prepares OHLCV + ATR data for BackTrader consumption.

Only loads tickers that have at least one qualifying signal (score >= 70 AND top 5%)
to optimize memory usage.
"""

import logging
from pathlib import Path
from typing import List, Optional, Set

import numpy as np
import pandas as pd
from tqdm import tqdm

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
import config
from src.data_engine import DataRepository, CacheMode

logger = logging.getLogger(__name__)

BACKTEST_DATA_DIR = config.DATA_DIR / 'backtest'
PRICE_OUTPUT_DIR = BACKTEST_DATA_DIR / 'prices'


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Average True Range (ATR).

    Args:
        df: DataFrame with High, Low, Close columns
        period: ATR period (default 14)

    Returns:
        Series with ATR values
    """
    high = df['High']
    low = df['Low']
    close = df['Close']

    # True Range components
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    # True Range = max of the three
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # ATR = exponential moving average of True Range
    atr = true_range.ewm(span=period, adjust=False).mean()

    return atr


def get_qualifying_tickers(
    scores_path: Path,
    min_score: float = 0.0,
    min_percentile: float = 0.0,
) -> Set[str]:
    """
    Get tickers that appear in universe scores.

    Args:
        scores_path: Path to universe_scores.parquet
        min_score: Minimum normalized score (0-100) - set to 0.0 to include all
        min_percentile: Minimum daily percentile rank (0-1) - set to 0.0 to include all

    Returns:
        Set of ticker symbols

    Note:
        Default is to include ALL tickers that ever appear in scores (0.0 filters).
        Use arguments to apply pre-filtering if needed to save space.
    """
    if not scores_path.exists():
        raise FileNotFoundError(f"Universe scores not found: {scores_path}")

    logger.info(f"Loading scores from {scores_path}")
    df = pd.read_parquet(scores_path)

    if min_score > 0 or min_percentile > 0:
        # Apply optional filters
        qualifying = df[
            (df['normalized_score'] >= min_score) &
            (df['daily_pct_rank'] >= min_percentile)
        ]
        tickers = set(qualifying['ticker'].unique())
        logger.info(f"Found {len(tickers)} tickers with qualifying signals "
                   f"(score >= {min_score} AND rank >= {min_percentile})")
    else:
        # Include ALL tickers from universe scores
        tickers = set(df['ticker'].unique())
        logger.info(f"Found {len(tickers)} unique tickers in universe scores (no pre-filter)")

    return tickers


def prepare_price_feeds(
    start_date: str,
    end_date: str,
    scores_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    min_score: float = 0.0,
    min_percentile: float = 0.0,
    atr_period: int = 14,
) -> List[str]:
    """
    Prepare price feeds for BackTrader.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        scores_path: Path to universe_scores.parquet
        output_dir: Where to save price parquets (default: data/backtest/prices/)
        min_score: Minimum normalized score for ticker inclusion (0.0 = all)
        min_percentile: Minimum daily rank for ticker inclusion (0.0 = all)
        atr_period: ATR calculation period

    Returns:
        List of prepared ticker symbols

    Note:
        Default is to prepare ALL tickers from universe scores.
        Pre-filtering reduces coverage and causes "No Price Data" rejections.
    """
    if scores_path is None:
        scores_path = BACKTEST_DATA_DIR / 'universe_scores.parquet'

    if output_dir is None:
        output_dir = PRICE_OUTPUT_DIR

    output_dir.mkdir(parents=True, exist_ok=True)

    # Get qualifying tickers
    qualifying_tickers = get_qualifying_tickers(scores_path, min_score, min_percentile)

    if not qualifying_tickers:
        logger.warning("No qualifying tickers found!")
        return []

    # Load and prepare each ticker
    data_repo = DataRepository()
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)

    # Add warm-up buffer for ATR calculation
    warmup_start = start_dt - pd.Timedelta(days=50)

    prepared_tickers = []

    for ticker in tqdm(qualifying_tickers, desc="Preparing price feeds"):
        try:
            # Load price data
            df = data_repo.get_ticker_data(ticker, mode=CacheMode.CACHE_ONLY)
            if df is None or df.empty:
                continue

            # Filter to date range (with warm-up)
            df = df[(df.index >= warmup_start) & (df.index <= end_dt)]
            if len(df) < 50:  # Need enough for ATR calculation
                continue

            # Standardize column names for BackTrader
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()

            # Calculate ATR
            df['atr_14'] = calculate_atr(df, period=atr_period)

            # Rename columns to lowercase for BackTrader compatibility
            df.columns = ['open', 'high', 'low', 'close', 'volume', 'atr_14']

            # Ensure datetime index
            df.index = pd.to_datetime(df.index)
            df.index.name = 'date'

            # Filter to final date range (after warm-up)
            df = df[df.index >= start_dt]

            # Drop rows with NaN ATR (from warm-up period)
            df = df.dropna(subset=['atr_14'])

            if len(df) < 10:  # Sanity check
                continue

            # Save
            output_path = output_dir / f'{ticker}.parquet'
            df.to_parquet(output_path)
            prepared_tickers.append(ticker)

        except Exception as e:
            logger.debug(f"Error preparing {ticker}: {e}")
            continue

    logger.info(f"Prepared {len(prepared_tickers)} price feeds in {output_dir}")

    return prepared_tickers


def list_prepared_tickers(output_dir: Optional[Path] = None) -> List[str]:
    """List all tickers with prepared price feeds."""
    if output_dir is None:
        output_dir = PRICE_OUTPUT_DIR

    if not output_dir.exists():
        return []

    return [f.stem for f in output_dir.glob('*.parquet')]


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    # Prepare 2020-2025
    tickers = prepare_price_feeds('2020-01-01', '2025-12-31')
    print(f"\nPrepared {len(tickers)} tickers")
    print(f"Sample tickers: {tickers[:10]}")
