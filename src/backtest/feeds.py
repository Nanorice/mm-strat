"""
BackTrader Custom Data Feed Classes
====================================
- SEPAStockFeed: Stock OHLCV + ATR data
- M03RegimeFeed: Daily regime state (single instrument, no OHLCV)
"""

import backtrader as bt


class SEPAStockFeed(bt.feeds.PandasData):
    """Stock OHLCV + ATR feed for BackTrader.

    Expected DataFrame columns: date (index), open, high, low, close, volume, atr_14.
    """

    lines = ('atr',)

    params = (
        ('datetime', None),
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('openinterest', None),
        ('atr', 'atr_14'),
    )


class M03RegimeFeed(bt.feeds.PandasData):
    """M03 regime state feed for BackTrader.

    Synthetic feed: OHLC lines are filled with composite_score to satisfy BackTrader.
    Real payload is on the custom lines below.

    Expected DataFrame columns:
    - date (index), regime_cat (0-4), composite_score, trend_pillar, liq_pillar, risk_pillar.

    Strategy access:
        regime = int(self.regime_feed.regime_cat[0])
        score = self.regime_feed.composite_score[0]
    """

    lines = (
        'regime_cat',
        'composite_score',
        'trend_pillar',
        'liq_pillar',
        'risk_pillar',
    )

    params = (
        ('datetime', None),
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
