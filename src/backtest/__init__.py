"""
SEPA Backtest Infrastructure
============================
BackTrader-based backtesting system for SEPA Hybrid V1 strategy.

Usage:
    from src.backtest import SEPABacktestRunner, UniverseScorer

    scorer = UniverseScorer(m01_path='models/m01_prototype/model.json')
    scores_df = scorer.score_from_t3('2020-01-01', '2025-01-01')

    runner = SEPABacktestRunner(start_date='2020-01-01', end_date='2025-01-01')
    runner.setup(scores_df=scores_df)
    metrics = runner.run()
"""

from .universe_scorer import UniverseScorer
from .feeds import SEPAStockFeed, M03RegimeFeed
from .score_lookup import ScoreLookup
from .position_tracker import PositionTracker, SEPAPosition
from .sepa_strategy import SEPAHybridV1
from .runner import SEPABacktestRunner, run_backtest
from .trade_logger import TradeLogger, TradeLog
from .report import generate_report
from .vectorized_backtest import VectorizedSEPABacktest

__all__ = [
    'UniverseScorer',
    'SEPAStockFeed',
    'M03RegimeFeed',
    'ScoreLookup',
    'PositionTracker',
    'SEPAPosition',
    'SEPAHybridV1',
    'SEPABacktestRunner',
    'run_backtest',
    'TradeLogger',
    'TradeLog',
    'generate_report',
    'VectorizedSEPABacktest',
]
