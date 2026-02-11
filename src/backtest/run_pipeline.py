"""
Full SEPA Backtest Pipeline
===========================
Runs the entire backtest workflow from data preparation to simulation.

Steps:
1. Score Universe (M01)
2. Prepare Regime Feed (M03)
3. Prepare Price Feeds (Qualifying Tickers)
4. Run Backtest (BackTrader)
"""

import logging
from src.backtest.universe_scorer import score_universe
from src.backtest.regime_feed import prepare_regime_feed
from src.backtest.price_feed import prepare_price_feeds
from src.backtest.runner import run_backtest

def run_pipeline():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Configuration
    START_DATE = '2020-01-01'
    END_DATE = '2025-01-01'
    
    # 1. Score Universe (M01)
    logger.info(">>> STEP 1: Scoring Universe (M01)...")
    # Note: we need earlier start for universe scores to support 10-day trailing rank
    score_universe(start_date='2019-12-01', end_date=END_DATE)

    # 2. Prepare Regime Feed (M03)
    logger.info(">>> STEP 2: Preparing Regime Feed (M03)...")
    # Note: need warm-up for regime calc
    prepare_regime_feed(start_date='2019-01-01', end_date=END_DATE)

    # 3. Prepare Price Feeds
    logger.info(">>> STEP 3: Preparing Price Feeds...")
    # Prepare feeds for backtest period (plus auto-calculated warmup inside)
    # Filter to only tickers that have at least one score >= 30 TO SPEED IT UP
    # (Optional: can set min_score=0 to load everything, but it's slower)
    prepare_price_feeds(
        start_date=START_DATE, 
        end_date=END_DATE, 
        min_score=30.0  # Optimization: Don't prep data for stocks that never qualify
    )

    # 4. Run Backtest
    logger.info(">>> STEP 4: Running Backtest...")
    run_backtest(
        start_date=START_DATE,
        end_date=END_DATE,
        initial_cash=100_000,
        save_results=True,
        run_note="full_pipeline"
    )

if __name__ == '__main__':
    run_pipeline()
