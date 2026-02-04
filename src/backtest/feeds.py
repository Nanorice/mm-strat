"""
BackTrader Custom Data Feed Classes
====================================
Custom data feeds for SEPA backtest infrastructure.

- SEPAStockFeed: Stock OHLCV + ATR data
- M03RegimeFeed: Daily regime state (single instrument, no OHLCV)
"""

import backtrader as bt
import pandas as pd


class SEPAStockFeed(bt.feeds.PandasData):
    """
    Stock OHLCV + ATR feed for BackTrader.

    Expected DataFrame columns:
    - date (index): Trading date
    - open, high, low, close, volume: Standard OHLCV
    - atr_14: 14-day Average True Range

    Usage:
        df = pd.read_parquet('data/backtest/prices/AAPL.parquet')
        feed = SEPAStockFeed(dataname=df, name='AAPL')
        cerebro.adddata(feed, name='AAPL')
    """

    # Add custom line for ATR
    lines = ('atr',)

    # Map DataFrame columns to BackTrader lines
    params = (
        ('datetime', None),  # Use index as datetime
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('openinterest', None),  # Not used
        ('atr', 'atr_14'),  # Map atr_14 column to atr line
    )


class M03RegimeFeed(bt.feeds.PandasData):
    """
    M03 Regime state feed for BackTrader.

    This is a "synthetic" data feed that provides daily regime information.
    It does NOT have real OHLCV data - the price lines are filled with the
    composite score to satisfy BackTrader's requirements.

    Expected DataFrame columns:
    - date (index): Trading date
    - regime_cat: Ordinal category (0=strong_bear to 4=strong_bull)
    - composite_score: Raw M03 score (0-100)
    - trend_pillar: Trend score (0-100)
    - liq_pillar: Liquidity score (0-100)
    - risk_pillar: Risk appetite score (0-100)

    Usage:
        df = pd.read_parquet('data/backtest/m03_feed.parquet')
        feed = M03RegimeFeed(dataname=df, name='regime')
        cerebro.adddata(feed, name='regime')

    In strategy:
        regime = int(self.regime_feed.regime_cat[0])  # 0-4
        score = self.regime_feed.composite_score[0]   # 0-100
    """

    # Custom lines for regime data
    lines = (
        'regime_cat',
        'composite_score',
        'trend_pillar',
        'liq_pillar',
        'risk_pillar',
    )

    # Map DataFrame columns to BackTrader lines
    # Use composite_score for OHLC to satisfy BackTrader (not used in strategy)
    params = (
        ('datetime', None),  # Use index as datetime
        ('open', 'composite_score'),
        ('high', 'composite_score'),
        ('low', 'composite_score'),
        ('close', 'composite_score'),
        ('volume', None),
        ('openinterest', None),
        ('regime_cat', 'regime_cat'),
        ('composite_score', 'composite_score'),
        ('trend_pillar', 'trend_pillar'),
        ('liq_pillar', 'liq_pillar'),
        ('risk_pillar', 'risk_pillar'),
    )


def load_stock_feed(ticker: str, prices_dir: str = 'data/backtest/prices') -> SEPAStockFeed:
    """
    Load a stock feed from prepared parquet file.

    Args:
        ticker: Stock ticker symbol
        prices_dir: Directory containing price parquets

    Returns:
        SEPAStockFeed instance ready for cerebro.adddata()
    """
    from pathlib import Path

    path = Path(prices_dir) / f'{ticker}.parquet'
    if not path.exists():
        raise FileNotFoundError(f"Price data not found: {path}")

    df = pd.read_parquet(path)
    return SEPAStockFeed(dataname=df, name=ticker)


def load_regime_feed(regime_path: str = 'data/backtest/m03_feed.parquet') -> M03RegimeFeed:
    """
    Load the M03 regime feed from prepared parquet file.

    Args:
        regime_path: Path to regime parquet

    Returns:
        M03RegimeFeed instance ready for cerebro.adddata()
    """
    from pathlib import Path

    path = Path(regime_path)
    if not path.exists():
        raise FileNotFoundError(f"Regime data not found: {path}")

    df = pd.read_parquet(path)
    return M03RegimeFeed(dataname=df, name='regime')
