"""
Strategy Module - SEPA Strategy Implementation
Implements Minervini's SEPA (Specific Entry Point Analysis) methodology.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from abc import ABC, abstractmethod
import logging

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
import config
from src.indicators import TechnicalAnalysis

logger = logging.getLogger(__name__)


class AlphaModel(ABC):
    """
    Abstract base class for trading strategies.
    Defines the interface for entry/exit signal generation.
    """

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame, date: pd.Timestamp) -> Dict:
        """
        Generate buy/sell signals for a given date.

        Args:
            df: DataFrame with OHLCV + indicators
            date: Current date for signal generation

        Returns:
            Dict with 'buy', 'sell', and metadata
        """
        pass


class SEPAStrategy(AlphaModel):
    """
    Implements Mark Minervini's SEPA methodology.

    Signal Generation Pipeline:
    1. Trend Filter (Stage 2 Uptrend)
    2. Structure (VCP Setup)
    3. Trigger (Breakout + Volume)
    4. Confirmation (Relative Strength)
    """

    def __init__(self, benchmark_data: Optional[pd.Series] = None):
        """
        Initialize SEPA strategy.

        Args:
            benchmark_data: Benchmark (SPY) close prices for RS calculation
        """
        self.benchmark_data = benchmark_data
        self.ta = TechnicalAnalysis()

    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds all required indicators to raw OHLCV data.

        Args:
            df: Raw OHLCV DataFrame

        Returns:
            DataFrame with all indicators calculated
        """
        return self.ta.calculate_all_indicators(df, self.benchmark_data)

    def screen_candidates(self, df: pd.DataFrame, date: pd.Timestamp) -> bool:
        """
        Step 1: Broad screening for Stage 2 uptrend (Trend Template).

        Args:
            df: DataFrame with indicators
            date: Current date

        Returns:
            True if stock meets trend criteria
        """
        if date not in df.index:
            return False

        try:
            stage2 = self.ta.detect_stage2_uptrend(df)
            return stage2.loc[date] if date in stage2.index else False
        except Exception as e:
            logger.debug(f"Stage 2 detection failed: {e}")
            return False

    def check_trigger(self, df: pd.DataFrame, date: pd.Timestamp) -> bool:
        """
        Step 2: Check for VCP breakout trigger.

        Args:
            df: DataFrame with indicators
            date: Current date

        Returns:
            True if breakout + volume spike detected
        """
        if date not in df.index:
            return False

        try:
            vcp = self.ta.detect_vcp_setup(df)
            return vcp.loc[date] if date in vcp.index else False
        except Exception as e:
            logger.debug(f"VCP detection failed: {e}")
            return False

    def check_relative_strength(self, df: pd.DataFrame, date: pd.Timestamp) -> bool:
        """
        Step 3: Confirm relative strength vs benchmark.

        Args:
            df: DataFrame with indicators
            date: Current date

        Returns:
            True if RS is strong
        """
        if date not in df.index or self.benchmark_data is None:
            return True  # Skip RS check if no benchmark

        try:
            rs_strong = self.ta.detect_relative_strength(df)
            return rs_strong.loc[date] if date in rs_strong.index else False
        except Exception as e:
            logger.debug(f"RS detection failed: {e}")
            return False

    def check_exit_signal(self, df: pd.DataFrame, date: pd.Timestamp,
                         entry_price: float, stop_price: float) -> Tuple[bool, str]:
        """
        Checks for exit conditions:
        1. Stop loss hit (price drops below stop)
        2. Trend break (close below 50 SMA)

        Args:
            df: DataFrame with indicators
            date: Current date
            entry_price: Entry price of the trade
            stop_price: Stop loss price

        Returns:
            Tuple of (should_exit: bool, exit_reason: str)
        """
        if date not in df.index:
            return False, ''

        row = df.loc[date]

        # Check stop loss (using intraday low)
        if 'Low' in df.columns and row['Low'] < stop_price:
            return True, 'Stop Loss'

        # Check trend break (close below 50 SMA)
        if 'SMA_50' in df.columns and pd.notna(row['SMA_50']):
            if row['Close'] < row['SMA_50']:
                return True, 'Trend Break (50 SMA)'

        return False, ''

    def generate_signals(self, df: pd.DataFrame, date: pd.Timestamp) -> Dict:
        """
        Main signal generation method.
        Combines all SEPA components.

        Args:
            df: DataFrame with OHLCV + indicators
            date: Current date

        Returns:
            Dict with:
                - 'buy': Boolean
                - 'sell': Boolean
                - 'signal_strength': Float (0-1) - placeholder for ML
                - 'metadata': Dict with details
        """
        if date not in df.index:
            return {'buy': False, 'sell': False, 'signal_strength': 0.0, 'metadata': {}}

        # Ensure indicators are calculated
        if 'SMA_50' not in df.columns:
            df = self.prepare_data(df)

        # Check all buy criteria
        trend_ok = self.screen_candidates(df, date)
        trigger_ok = self.check_trigger(df, date)
        rs_ok = self.check_relative_strength(df, date)

        buy_signal = trend_ok and trigger_ok and rs_ok

        # Sell signal (trend break)
        sell_signal = False
        if 'SMA_50' in df.columns and date in df.index:
            sell_signal = df.loc[date, 'Close'] < df.loc[date, 'SMA_50']

        # Signal strength (placeholder - can integrate ML here later)
        signal_strength = 1.0 if buy_signal else 0.0

        # Metadata for logging
        metadata = {
            'trend_ok': trend_ok,
            'trigger_ok': trigger_ok,
            'rs_ok': rs_ok,
            'price': df.loc[date, 'Close'] if date in df.index else None,
            'volume_ratio': df.loc[date, 'Vol_Ratio'] if 'Vol_Ratio' in df.columns and date in df.index else None
        }

        return {
            'buy': buy_signal,
            'sell': sell_signal,
            'signal_strength': signal_strength,
            'metadata': metadata
        }

    def calculate_trade_plan(self, df: pd.DataFrame, date: pd.Timestamp) -> Optional[Dict]:
        """
        Calculates entry, stop, and target prices for a trade.

        Uses fixed percentage stop loss (from config).

        Args:
            df: DataFrame with indicators
            date: Entry date

        Returns:
            Dict with trade plan details, or None if data missing
        """
        if date not in df.index:
            return None

        row = df.loc[date]
        entry_price = row['Close']

        # Fixed percentage stop
        stop_price = entry_price * (1 - config.STOP_LOSS_PCT)
        risk = entry_price - stop_price

        # Profit target (R-multiple)
        target_price = entry_price + (risk * config.PROFIT_TARGET_R)

        # Position sizing (fixed fractional)
        position_size_pct = config.POSITION_SIZE_PCT

        # ATR for reference (optional)
        atr = row['ATR'] if 'ATR' in df.columns and pd.notna(row['ATR']) else None

        return {
            'entry_price': round(entry_price, 2),
            'stop_price': round(stop_price, 2),
            'target_price': round(target_price, 2),
            'risk_per_share': round(risk, 2),
            'risk_pct': round(config.STOP_LOSS_PCT * 100, 2),
            'reward_pct': round(config.STOP_LOSS_PCT * config.PROFIT_TARGET_R * 100, 2),
            'position_size_pct': round(position_size_pct * 100, 1),
            'atr': round(atr, 2) if atr else None
        }

    # TODO: Future enhancement - integrate ML-based signal scoring
    def score_signal_ml(self, df: pd.DataFrame, date: pd.Timestamp) -> float:
        """
        Placeholder for ML-based signal scoring (Meta-Labeling).

        When implemented, this will use a trained Random Forest to predict
        probability of trade success.

        Args:
            df: DataFrame with indicators
            date: Current date

        Returns:
            Confidence score (0.0 to 1.0)
        """
        # TODO: Extract features, load model, predict probability
        # For now, return 1.0 (full confidence) for rule-based signals
        return 1.0
