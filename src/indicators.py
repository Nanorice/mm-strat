"""
Technical Indicators - TechnicalAnalysis Class
Vectorized calculation of all SEPA indicators.
"""

import pandas as pd
import numpy as np
from typing import Optional
import logging

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class TechnicalAnalysis:
    """
    Calculates technical indicators for SEPA strategy.
    All methods are vectorized for performance.
    """

    @staticmethod
    def add_sma(df: pd.DataFrame, periods: list = None) -> pd.DataFrame:
        """
        Adds Simple Moving Averages to DataFrame.

        Args:
            df: OHLCV DataFrame
            periods: List of SMA periods (default: [50, 150, 200])

        Returns:
            DataFrame with SMA_{period} and Price_vs_SMA_{period} columns added
        """
        if periods is None:
            periods = [config.SMA_FAST, config.SMA_MEDIUM, config.SMA_SLOW]

        df = df.copy()
        for period in periods:
            # Raw SMA (for ordering comparisons like SMA_50 > SMA_150)
            df[f'SMA_{period}'] = df['Close'].rolling(window=period).mean()
            
            # Normalized distance from SMA (for ML model)
            # Tells model "stock is X% above/below trend"
            df[f'Price_vs_SMA_{period}'] = ((df['Close'] - df[f'SMA_{period}']) / df[f'SMA_{period}']) * 100

        return df

    @staticmethod
    def add_atr(df: pd.DataFrame, period: int = None) -> pd.DataFrame:
        """
        Adds Average True Range (ATR) for volatility measurement.

        Args:
            df: OHLCV DataFrame
            period: ATR period (default from config)

        Returns:
            DataFrame with ATR column added
        """
        if period is None:
            period = config.ATR_PERIOD

        df = df.copy()

        high = df['High']
        low = df['Low']
        close = df['Close']
        prev_close = close.shift(1)

        # True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR'] = true_range.rolling(window=period).mean()

        return df

    @staticmethod
    def add_52_week_highs_lows(df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds 52-week (252 trading days) high and low markers.

        Returns:
            DataFrame with High_52W and Low_52W columns
        """
        df = df.copy()
        df['High_52W'] = df['Close'].rolling(window=252).max()
        df['Low_52W'] = df['Close'].rolling(window=252).min()
        return df

    @staticmethod
    def add_relative_strength(df: pd.DataFrame, benchmark: pd.Series,
                             lookback: int = None) -> pd.DataFrame:
        """
        Calculates Relative Strength vs. benchmark (e.g., SPY).

        Args:
            df: Stock OHLCV DataFrame
            benchmark: Benchmark close prices (aligned by date)
            lookback: Period for RS moving average (default from config)

        Returns:
            DataFrame with RS and RS_MA columns
        """
        if lookback is None:
            lookback = config.RS_LOOKBACK

        df = df.copy()

        # Align benchmark to stock dates
        benchmark_aligned = benchmark.reindex(df.index).ffill()

        # RS Ratio = Stock / Benchmark
        df['RS'] = df['Close'] / benchmark_aligned

        # RS Moving Average for trend detection
        df['RS_MA'] = df['RS'].rolling(window=lookback).mean()

        return df

    @staticmethod
    def add_volume_metrics(df: pd.DataFrame, lookback: int = 50) -> pd.DataFrame:
        """
        Adds volume analysis metrics.

        Args:
            df: OHLCV DataFrame
            lookback: Period for average volume calculation

        Returns:
            DataFrame with Vol_MA and Vol_Ratio columns
        """
        df = df.copy()
        df['Vol_MA'] = df['Volume'].rolling(window=lookback).mean()
        df['Vol_Ratio'] = df['Volume'] / df['Vol_MA']
        return df

    @staticmethod
    def add_breakout_signals(df: pd.DataFrame, period: int = None) -> pd.DataFrame:
        """
        Identifies breakouts above N-day high.

        Args:
            df: OHLCV DataFrame
            period: Consolidation period (default from config)

        Returns:
            DataFrame with High_{period}D and Breakout columns
        """
        if period is None:
            period = config.CONSOLIDATION_PERIOD

        df = df.copy()

        # Rolling high of previous N days (shifted by 1 to exclude current day)
        df[f'High_{period}D'] = df['Close'].shift(1).rolling(window=period).max()

        # Breakout = Close > previous N-day high
        df['Breakout'] = df['Close'] > df[f'High_{period}D']

        return df

    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14, column: str = 'Close') -> pd.Series:
        """
        Calculate Relative Strength Index (RSI).
        
        RSI is a momentum oscillator that measures speed and magnitude of price changes.
        Bounded between 0-100, typically oversold < 30, overbought > 70.
        
        Args:
            df: OHLCV DataFrame
            period: RSI period (default: 14)
            column: Column to calculate RSI on (default: 'Close')
        
        Returns:
            Series with RSI values
        """
        delta = df[column].diff()
        
        # Separate gains and losses
        gain = delta.where(delta > 0, 0)
        loss = (-delta.where(delta < 0, 0))
        
        # Calculate average gain and loss using rolling window
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        # Calculate RS and RSI
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi

    @staticmethod
    def add_normalized_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        Adds Normalized ATR (nATR) - ATR relative to price.
        
        Makes volatility comparable across different price levels.
        Lower values indicate tighter price action (better for VCP setups).
        
        Args:
            df: OHLCV DataFrame
            period: ATR period (default: 14)
        
        Returns:
            DataFrame with nATR column added
        """
        df = df.copy()
        
        # Ensure ATR exists
        if 'ATR' not in df.columns:
            df = TechnicalAnalysis.add_atr(df, period=period)
        
        # nATR = (ATR / Close) * 100
        df['nATR'] = (df['ATR'] / df['Close']) * 100
        
        return df
    
    @staticmethod
    def add_vcp_ratio(df: pd.DataFrame, short: int = 10, long: int = 50) -> pd.DataFrame:
        """
        Adds VCP Ratio - detects volatility contraction (the squeeze).
        
        Ratio of short-term ATR to long-term ATR. Values < 1.0 indicate
        volatility is contracting (ideal for VCP setups).
        
        Args:
            df: OHLCV DataFrame
            short: Short-term ATR period (default: 10)
            long: Long-term ATR periode (default: 50)
        
        Returns:
            DataFrame with VCP_Ratio column added
        """
        df = df.copy()
        
        # Calculate short-term ATR
        high = df['High']
        low = df['Low']
        close = df['Close']
        prev_close = close.shift(1)
        
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        atr_short = true_range.rolling(window=short).mean()
        atr_long = true_range.rolling(window=long).mean()
        
        # VCP Ratio = ATR_short / ATR_long
        df['VCP_Ratio'] = atr_short / atr_long
        df['VCP_Ratio'] = df['VCP_Ratio'].replace([np.inf, -np.inf], np.nan)
        
        return df
    
    @staticmethod
    def add_consolidation_width(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """
        Adds Consolidation Width - measures how tight the base is.
        
        Calculates the price range over N days as a percentage of current price.
        Lower values indicate tighter consolidation (superperformer setups).
        
        Args:
            df: OHLCV DataFrame
            period: Consolidation period (default: 20)
        
        Returns:
            DataFrame with Consolidation_Width column added
        """
        df = df.copy()
        
        # Range = (High_N - Low_N) / Close * 100
        high_period = df['High'].rolling(window=period).max()
        low_period = df['Low'].rolling(window=period).min()
        
        df['Consolidation_Width'] = ((high_period - low_period) / df['Close']) * 100
        
        return df
    
    @staticmethod
    def add_dry_up_volume(df: pd.DataFrame, short: int = 5, long: int = 50) -> pd.DataFrame:
        """
        Adds Dry Up Volume - detects seller exhaustion.
        
        Ratio of short-term to long-term average volume. Low values
        indicate reduced selling pressure before breakout.
        
        Args:
            df: OHLCV DataFrame
            short: Short-term volume period (default: 5)
            long: Long-term volume period (default: 50)
        
        Returns:
            DataFrame with Dry_Up_Volume column added
        """
        df = df.copy()
        
        vol_short = df['Volume'].rolling(window=short).mean()
        vol_long = df['Volume'].rolling(window=long).mean()
        
        df['Dry_Up_Volume'] = vol_short / vol_long
        df['Dry_Up_Volume'] = df['Dry_Up_Volume'].replace([np.inf, -np.inf], np.nan)
        
        return df


    @staticmethod
    def calculate_all_indicators(df: pd.DataFrame, benchmark: Optional[pd.Series] = None) -> pd.DataFrame:
        """
        Convenience method to calculate ALL SEPA indicators at once.

        Args:
            df: OHLCV DataFrame
            benchmark: Optional benchmark series for RS calculation

        Returns:
            DataFrame with all indicators added
        """
        # Add SMAs
        df = TechnicalAnalysis.add_sma(df)

        # Add ATR
        df = TechnicalAnalysis.add_atr(df)

        # Add 52-week highs/lows
        df = TechnicalAnalysis.add_52_week_highs_lows(df)

        # Add volume metrics
        df = TechnicalAnalysis.add_volume_metrics(df)

        # Add breakout detection
        df = TechnicalAnalysis.add_breakout_signals(df)

        # Add RS if benchmark provided
        if benchmark is not None:
            df = TechnicalAnalysis.add_relative_strength(df, benchmark)

        return df

    @staticmethod
    def detect_stage2_uptrend(df: pd.DataFrame) -> pd.Series:
        """
        Minervini's Stage 2 uptrend detection (Trend Template).

        Criteria:
        1. Price > 150 SMA > 200 SMA
        2. 150 SMA > 200 SMA
        3. 200 SMA trending up (current > 20 days ago)
        4. Price > 50 SMA
        5. Price > 30% above 52-week low
        6. Price within 25% of 52-week high

        Returns:
            Boolean Series indicating Stage 2 status
        """
        df = df.copy()

        # Ensure indicators exist
        required_cols = ['Close', 'SMA_50', 'SMA_150', 'SMA_200', 'High_52W', 'Low_52W']
        if not all(col in df.columns for col in required_cols):
            raise ValueError("Missing required indicators. Run calculate_all_indicators() first.")

        # Handle newer stocks (less than 260 days of history)
        if len(df) < 260:
            # Simplified trend for IPOs/newer stocks
            c_trend = (df['Close'] > df['SMA_50']) & \
                     (df['Close'] > df['Close'].rolling(20).mean())
        else:
            # Full Stage 2 template
            c1 = (df['Close'] > df['SMA_150']) & (df['Close'] > df['SMA_200'])
            c2 = df['SMA_150'] > df['SMA_200']
            c3 = df['SMA_200'] > df['SMA_200'].shift(20)  # 200 SMA rising
            c4 = df['Close'] > df['SMA_50']
            c4b = df['SMA_50'] > df['SMA_150']  # MA50 > MA150
            c5 = df['Close'] > df['Low_52W'] * config.WEEKS_52_LOW_THRESHOLD
            c6 = df['Close'] > df['High_52W'] * config.WEEKS_52_HIGH_THRESHOLD

            c_trend = c1 & c2 & c3 & c4 & c4b & c5 & c6

        return c_trend

    @staticmethod
    def detect_vcp_setup(df: pd.DataFrame) -> pd.Series:
        """
        Volatility Contraction Pattern (VCP) detection.

        Combines:
        - Breakout above N-day high
        - Volume spike (> threshold)

        Returns:
            Boolean Series indicating VCP breakout
        """
        required_cols = ['Breakout', 'Vol_Ratio']
        if not all(col in df.columns for col in required_cols):
            raise ValueError("Missing breakout/volume indicators. Run calculate_all_indicators() first.")

        vcp = df['Breakout'] & (df['Vol_Ratio'] > config.VOL_SPIKE_THRESHOLD)
        return vcp

    @staticmethod
    def detect_relative_strength(df: pd.DataFrame) -> pd.Series:
        """
        Checks if stock is outperforming benchmark (RS trending up).

        Returns:
            Boolean Series indicating RS strength
        """
        if 'RS' not in df.columns or 'RS_MA' not in df.columns:
            raise ValueError("Missing RS indicators. Run add_relative_strength() first.")

        rs_strong = df['RS'] > df['RS_MA']
        return rs_strong
