"""
M03 Regime Feed Preparation for Backtesting
============================================
Generates daily regime states for BackTrader consumption.

IMPORTANT: No additional T+1 shift is applied here because:
1. M03RegimeCalculator already handles T+1 publication lag for FRED data internally
   ("Wednesday's observation" appears on "Thursday's row")
2. BackTrader's execution model adds another implicit lag:
   - Strategy's next() sees today's Close data
   - Orders execute at tomorrow's Open

Adding a shift here would create DOUBLE LAG and unnecessarily delay regime signals.
"""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
import config
from src.pipeline.m03_regime import M03RegimeCalculator

logger = logging.getLogger(__name__)

BACKTEST_DATA_DIR = config.DATA_DIR / 'backtest'


def prepare_regime_feed(
    start_date: str,
    end_date: str,
    output_path: Optional[Path] = None,
    trading_days_only: bool = True,
) -> pd.DataFrame:
    """
    Prepare M03 regime feed for backtesting.

    Args:
        start_date: Start date (YYYY-MM-DD), should include warm-up buffer
        end_date: End date (YYYY-MM-DD)
        output_path: Where to save the parquet (default: data/backtest/m03_feed.parquet)
        trading_days_only: If True, filter to NYSE trading days only (default True)

    Returns:
        DataFrame with columns:
        - date (index): Trading date
        - regime_cat: Ordinal category (0=strong_bear, 1=bear, 2=neutral, 3=bull, 4=strong_bull)
        - composite_score: Raw M03 score (0-100)
        - trend_pillar: Trend score (0-100)
        - liq_pillar: Liquidity score (0-100)
        - risk_pillar: Risk appetite score (0-100)

    Note:
        NO additional T+1 shift is applied here. The lag chain is:
        1. FRED publication lag (handled in M03RegimeCalculator): T+1
        2. BackTrader execution lag (implicit): today's Close -> tomorrow's Open
        Adding another shift would create double-lagging.
    """
    if output_path is None:
        output_path = BACKTEST_DATA_DIR / 'm03_feed.parquet'

    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Preparing M03 regime feed: {start_date} to {end_date}")

    # Initialize calculator
    calc = M03RegimeCalculator()

    # Calculate vectorized history (T+1 lag applied internally)
    df = calc.calculate_history_vectorized(start_date, end_date, freq='D')

    # Filter to NYSE trading days only to prevent weekend/holiday issues
    if trading_days_only:
        from pandas.tseries.holiday import USFederalHolidayCalendar
        from pandas.tseries.offsets import CustomBusinessDay

        us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
        trading_days = pd.date_range(start=start_date, end=end_date, freq=us_bd)
        df = df[df.index.isin(trading_days)]
        logger.info(f"Filtered to {len(df)} trading days (removed weekends/holidays)")

    # Map category to ordinal (0-4)
    category_map = {
        'strong_bear': 0,
        'bear': 1,
        'neutral': 2,
        'bull': 3,
        'strong_bull': 4,
    }
    df['regime_cat'] = df['category'].map(category_map).astype(int)

    # Select and rename columns for BackTrader feed
    result = df[[
        'regime_cat',
        'score',
        'trend_score',
        'liquidity_score',
        'risk_appetite_score',
    ]].rename(columns={
        'score': 'composite_score',
        'trend_score': 'trend_pillar',
        'liquidity_score': 'liq_pillar',
        'risk_appetite_score': 'risk_pillar',
    })

    # Ensure index is datetime with name 'date'
    result.index = pd.to_datetime(result.index)
    result.index.name = 'date'

    # Save
    result.to_parquet(output_path)
    logger.info(f"Saved M03 feed to {output_path} ({len(result)} rows)")

    # Log regime distribution
    regime_counts = result['regime_cat'].value_counts().sort_index()
    regime_names = ['strong_bear', 'bear', 'neutral', 'bull', 'strong_bull']
    logger.info("Regime distribution:")
    for cat, count in regime_counts.items():
        pct = count / len(result) * 100
        logger.info(f"  {regime_names[cat]}: {count} days ({pct:.1f}%)")

    return result


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    # Prepare 2019-2025 (extra year for warm-up)
    df = prepare_regime_feed('2019-01-01', '2025-12-31')
    print(f"\nSample (last 10 rows):\n{df.tail(10)}")
