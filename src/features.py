"""
Feature Engine - FeatureEngineer Class
Implements dual-stage feature calculation (Lightweight + Heavyweight modes)
as specified in QSS Module B.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
import logging

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
import config
from src.indicators import TechnicalAnalysis

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """
    Dual-stage feature calculation engine.
    
    Architecture:
    - Lightweight Mode: Fast, vectorized indicators for universe-wide scanning (500+ stocks)
    - Heavyweight Mode: Expensive features (Alpha factors, fundamentals) for qualified candidates only
    
    This design optimizes computational resources by applying expensive calculations
    only to stocks that pass the initial SEPA screen.
    """
    
    def __init__(self, benchmark_data: Optional[pd.Series] = None):
        """
        Initialize the Feature Engineer.
        
        Args:
            benchmark_data: Benchmark (SPY) close prices for relative strength calculation
        """
        self.benchmark_data = benchmark_data
        self.ta = TechnicalAnalysis()
        
        # Feature definitions
        self.lightweight_features = [
            'SMA_50', 'SMA_150', 'SMA_200',      # Trend indicators
            'ATR',                                # Volatility
            'RS', 'RS_MA',                        # Relative strength
            'Vol_MA', 'Vol_Ratio',                # Volume metrics
            'High_52W', 'Low_52W',                # 52-week range
            'High_20D', 'Breakout'                # Breakout detection
        ]
        
        logger.info("FeatureEngineer initialized in dual-stage mode")
    
    def calculate_lightweight_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Stage 1: Calculate lightweight features for broad scanning.
        
        Applied to the entire universe (500+ stocks) to identify SEPA candidates.
        All operations are vectorized for maximum performance.
        
        Args:
            df: Raw OHLCV DataFrame with columns ['Open', 'High', 'Low', 'Close', 'Volume']
        
        Returns:
            DataFrame with lightweight indicators added
            
        Raises:
            ValueError: If required OHLCV columns are missing
        """
        # Validate input
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"Missing required columns. Need: {required_cols}")
        
        if len(df) < 200:
            logger.warning(f"Insufficient data ({len(df)} rows). Need 200+ for accurate indicators.")
        
        df = df.copy()
        
        # Moving Averages (Trend)
        df = self.ta.add_sma(df, periods=[config.SMA_FAST, config.SMA_MEDIUM, config.SMA_SLOW])
        
        # Volatility (ATR for stop loss calculation)
        df = self.ta.add_atr(df, period=config.ATR_PERIOD)
        
        # 52-Week Highs/Lows (Stage 2 criteria)
        df = self.ta.add_52_week_highs_lows(df)
        
        # Volume Analysis (VCP detection)
        df = self.ta.add_volume_metrics(df, lookback=50)
        
        # Breakout Detection (20-day high)
        df = self.ta.add_breakout_signals(df, period=config.CONSOLIDATION_PERIOD)
        
        # Relative Strength vs. Benchmark
        if self.benchmark_data is not None:
            df = self.ta.add_relative_strength(df, self.benchmark_data, lookback=config.RS_LOOKBACK)
        else:
            logger.warning("No benchmark data provided. RS indicators will be missing.")
        
        logger.debug(f"Lightweight features calculated: {len(df)} rows, {len(df.columns)} columns")
        
        return df
    
    def calculate_heavyweight_features(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """
        Stage 2: Calculate heavyweight features for qualified candidates.
        
        This method is only called on stocks that pass the SEPA screen (5-10 candidates).
        It calculates computationally expensive features:
        - WorldQuant Alpha Factors (intraday correlations, momentum decay)
        - Fundamental Metrics (EPS growth, sales acceleration, earnings surprises)
        
        Args:
            df: DataFrame with OHLCV + lightweight features
            ticker: Stock symbol (needed for fundamental data lookup)
        
        Returns:
            DataFrame with heavyweight features added
            
        Note:
            This is a PLACEHOLDER for Phase 2 implementation.
            Current version returns the input DataFrame unmodified.
        """
        logger.info(f"[PHASE 2 TODO] Heavyweight features for {ticker} - Not yet implemented")
        
        # Phase 2 will add:
        # - WorldQuant Alpha#101 (intraday strength)
        # - WorldQuant Alpha#9 (momentum decay)
        # - EPS Growth (QoQ, YoY) from FMP API
        # - Sales Acceleration
        # - Earnings Surprises
        
        # For now, return df as-is
        return df
    
    def process_universe_batch(self, ticker_data_dict: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """
        Batch processing of multiple tickers with lightweight features.
        
        Optimized for scanning the entire S&P 500 universe efficiently.
        
        Args:
            ticker_data_dict: Dict mapping ticker symbol -> raw OHLCV DataFrame
        
        Returns:
            Dict mapping ticker symbol -> enriched DataFrame with lightweight features
        
        Example:
            >>> data = {
            ...     'AAPL': aapl_df,
            ...     'MSFT': msft_df,
            ...     'NVDA': nvda_df
            ... }
            >>> enriched = feature_engine.process_universe_batch(data)
            >>> print(enriched['AAPL'].columns)  # Shows lightweight features
        """
        enriched_data = {}
        failed_tickers = []
        
        for ticker, df in ticker_data_dict.items():
            try:
                enriched_data[ticker] = self.calculate_lightweight_features(df)
            except Exception as e:
                logger.warning(f"Failed to process {ticker}: {e}")
                failed_tickers.append(ticker)
        
        logger.info(f"Batch processed {len(enriched_data)}/{len(ticker_data_dict)} tickers successfully")
        
        if failed_tickers:
            logger.warning(f"Failed tickers: {failed_tickers}")
        
        return enriched_data
    
    def validate_features(self, df: pd.DataFrame, mode: str = 'lightweight') -> bool:
        """
        Validate that expected features are present in the DataFrame.
        
        Args:
            df: DataFrame to validate
            mode: 'lightweight' or 'heavyweight'
        
        Returns:
            True if all expected features are present
        """
        if mode == 'lightweight':
            expected = self.lightweight_features
        elif mode == 'heavyweight':
            # Phase 2: Add heavyweight feature list
            expected = self.lightweight_features
        else:
            raise ValueError(f"Unknown mode: {mode}. Use 'lightweight' or 'heavyweight'")
        
        missing = [col for col in expected if col not in df.columns]
        
        if missing:
            logger.error(f"Missing features in {mode} mode: {missing}")
            return False
        
        return True
    
    def get_feature_summary(self, df: pd.DataFrame) -> Dict:
        """
        Generate a summary of calculated features for debugging.
        
        Args:
            df: DataFrame with calculated features
        
        Returns:
            Dict with feature statistics
        """
        summary = {
            'total_rows': len(df),
            'total_columns': len(df.columns),
            'date_range': f"{df.index[0]} to {df.index[-1]}" if len(df) > 0 else None,
            'lightweight_present': self.validate_features(df, mode='lightweight'),
            'null_counts': df[self.lightweight_features].isnull().sum().to_dict()
        }
        
        return summary
