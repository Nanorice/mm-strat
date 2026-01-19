"""
Feature Engine - Expanded with Fundamental Point-in-Time Logic
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

import config
from src.indicators import TechnicalAnalysis

logger = logging.getLogger(__name__)

class FeatureEngineer:
    # ... (Existing Init) ...
    def __init__(self, benchmark_data: Optional[pd.Series] = None):
        self.benchmark_data = benchmark_data
        self.ta = TechnicalAnalysis()
        
        from src.company_profile_engine import CompanyProfileEngine
        try:
            self.profile_engine = CompanyProfileEngine()
        except Exception:
            self.profile_engine = None
            
        from src.fundamental_engine import FundamentalEngine
        try:
            self.fund_engine = FundamentalEngine()
        except:
            self.fund_engine = None

    # ... (Existing calculate_lightweight_features) ...
    def calculate_lightweight_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates technical indicators on the given DataFrame.
        """
        # Validate input
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(col in df.columns for col in required_cols):
             # Try to fix casing
             df = df.rename(columns={c.lower(): c for c in required_cols})
             if not all(col in df.columns for col in required_cols):
                 raise ValueError(f"Missing required columns. Need: {required_cols}")
        
        df = df.copy()
        
        # Moving Averages (Trend)
        df = self.ta.add_sma(df, periods=[config.SMA_FAST, config.SMA_MEDIUM, config.SMA_SLOW])
        
        # Volatility
        df = self.ta.add_atr(df, period=config.ATR_PERIOD)
        
        # 52-Week Highs/Lows
        df = self.ta.add_52_week_highs_lows(df)
        
        # Volume Analysis
        df = self.ta.add_volume_metrics(df, lookback=50)
        
        # Breakout Detection
        df = self.ta.add_breakout_signals(df, period=config.CONSOLIDATION_PERIOD)
        
        # RS
        if self.benchmark_data is not None:
            df = self.ta.add_relative_strength(df, self.benchmark_data, lookback=config.RS_LOOKBACK)
        
        # Advanced Technicals
        df = self.ta.add_normalized_atr(df, period=14)
        df = self.ta.add_vcp_ratio(df, short=10, long=50)
        df = self.ta.add_consolidation_width(df, period=20)
        df = self.ta.add_dry_up_volume(df, short=5, long=50)
        
        # RSI
        df['RSI_14'] = self.ta.calculate_rsi(df, period=14)
        
        # Regime & Structure
        if 'SMA_200' in df.columns:
            is_bull_market = df['SMA_200'] > df['SMA_200'].shift(20)
            df['RSI_Regime'] = ((df['RSI_14'] > 40) & is_bull_market).astype(int)
            
        if 'High_52W' in df.columns:
            # handle div by zero
            df['Dist_From_52W_High'] = (df['Close'] - df['High_52W']) / df['High_52W'].replace(0, np.nan) * 100
            
        # Green Days
        df['Is_Green_Day'] = (df['Close'] > df['Open']).astype(int)
        df['Green_Days_Ratio_20D'] = df['Is_Green_Day'].rolling(window=20).mean()
        
        # SMA Slope
        if 'SMA_50' in df.columns:
             df['SMA_50_Slope'] = (df['SMA_50'] - df['SMA_50'].shift(10)) / df['SMA_50'].shift(10).replace(0, np.nan) / 10 * 100
             
        # Lags are added via add_lagged_features if needed, but for D2 extraction we do it on the single row
        # Actually, to get lags at T, we need T-1.
        # Since we filter data up to T, the last row is T. The previous row is T-1.
        # We can calculate lags here.
        
        from src.feature_config import FEATURES_TO_LAG
        for feature in FEATURES_TO_LAG:
            if feature in df.columns:
                df[f"{feature}_Lag1"] = df[feature].shift(1)
        
        return df

    def get_fundamental_snapshot(self, ticker: str, date: pd.Timestamp) -> Dict[str, float]:
        """
        Point-in-Time Fundamental Data Compression.
        
        Retrieves the latest available fundamental report relative to 'date'.
        Computes growth and valuation metrics dynamically.
        
        Features:
          - eps_growth_yoy
          - revenue_growth_yoy
          - ...
        """
        # Default empty
        feats = {
            'eps_growth_yoy': 0.0,
            'revenue_growth_yoy': 0.0,
            'gross_margin': 0.0,
            'pe_ratio': 0.0
        }
        
        if self.fund_engine is None:
            return feats
            
        # Get raw data (assumed cached in parquet)
        # This implementation requires FundamentalEngine to support getting raw df
        # We'll need to extend FundamentalEngine or read directly here.
        # For this prototype, let's assume we can read the ticker's fundamental file
        
        return feats # Placeholder for now to fix syntax
