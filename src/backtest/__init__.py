"""
SEPA Backtest Infrastructure
============================
BackTrader-based backtesting system for SEPA Hybrid V1 strategy.

Components:
- regime_feed: M03 daily regime state preparation
- universe_scorer: Batch M01 scoring for entire universe
- price_feed: OHLCV + ATR data preparation
- feeds: BackTrader custom data feed classes
- score_lookup: Fast daily candidate filtering
- position_tracker: Multi-tranche position state management
- sepa_strategy: Main BackTrader strategy implementation
- runner: Backtest execution orchestration
- trade_logger: Trade event logging
- report: Performance reporting

Usage:
    # Full backtest
    python scripts/run_backtest.py --full

    # Or programmatically
    from src.backtest import SEPABacktestRunner
    runner = SEPABacktestRunner()
    runner.setup()
    results = runner.run()
"""

from .regime_feed import prepare_regime_feed
from .universe_scorer import UniverseScorer, score_universe
from .price_feed import prepare_price_feeds, list_prepared_tickers
from .feeds import SEPAStockFeed, M03RegimeFeed, load_stock_feed, load_regime_feed
from .score_lookup import ScoreLookup
from .position_tracker import PositionTracker, SEPAPosition
from .sepa_strategy import SEPAHybridV1
from .runner import SEPABacktestRunner, run_backtest
from .trade_logger import TradeLogger, TradeLog
from .report import generate_report

__all__ = [
    # Data preparation
    'prepare_regime_feed',
    'UniverseScorer',
    'score_universe',
    'prepare_price_feeds',
    'list_prepared_tickers',

    # BackTrader feeds
    'SEPAStockFeed',
    'M03RegimeFeed',
    'load_stock_feed',
    'load_regime_feed',

    # Utilities
    'ScoreLookup',
    'PositionTracker',
    'SEPAPosition',

    # Strategy
    'SEPAHybridV1',

    # Runner
    'SEPABacktestRunner',
    'run_backtest',

    # Reporting
    'TradeLogger',
    'TradeLog',
    'generate_report',
]
