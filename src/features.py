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

        # Initialize company profile engine for sector/industry features
        from src.company_profile_engine import CompanyProfileEngine
        try:
            self.profile_engine = CompanyProfileEngine()
        except ValueError as e:
            logger.warning(f"CompanyProfileEngine initialization failed: {e}")
            self.profile_engine = None

        # Feature definitions
        self.lightweight_features = [
            'SMA_50', 'SMA_150', 'SMA_200',      # Trend indicators (raw for ordering)
            'Price_vs_SMA_50', 'Price_vs_SMA_150', 'Price_vs_SMA_200',  # Normalized distances
            'ATR', 'nATR',                        # Volatility (absolute + normalized)
            'VCP_Ratio',                          # Volatility contraction
            'Consolidation_Width',                # Base tightness
            'RS', 'RS_MA',                        # Relative strength
            'Vol_MA', 'Vol_Ratio',                # Volume metrics
            'Dry_Up_Volume',                      # Seller exhaustion
            'High_52W', 'Low_52W',                # 52-week range
            'High_20D', 'Breakout'                # Breakout detection
        ]

        logger.debug("FeatureEngineer initialized in dual-stage mode")
    
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
            logger.debug(f"Insufficient data ({len(df)} rows). Need 200+ for accurate indicators.")
        
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
        
        # NEW VCP-SPECIFIC FEATURES
        # Normalized ATR (price-relative volatility)
        df = self.ta.add_normalized_atr(df, period=14)
        
        # VCP Ratio (volatility contraction detector)
        df = self.ta.add_vcp_ratio(df, short=10, long=50)
        
        # Consolidation Width (base tightness)
        df = self.ta.add_consolidation_width(df, period=20)
        
        # Dry Up Volume (seller exhaustion)
        df = self.ta.add_dry_up_volume(df, short=5, long=50)
        
        # NEW MINERVINI-ALIGNED FEATURES
        # RSI (Relative Strength Index) - momentum oscillator
        df['RSI_14'] = self.ta.calculate_rsi(df, period=14)
        
        # RSI Regime - context-aware RSI interpretation (bull vs bear market)
        is_bull_market = df['SMA_200'] > df['SMA_200'].shift(20)
        df['RSI_Regime'] = ((df['RSI_14'] > 40) & is_bull_market).astype(int)
        
        # Distance from 52-week high (Minervini's sweet spot: -5% to -15%)
        df['Dist_From_52W_High'] = (df['Close'] - df['High_52W']) / df['High_52W'] * 100
        
        # Green Days Ratio - proportion of green days in last 20 (accumulation indicator)
        df['Is_Green_Day'] = (df['Close'] > df['Open']).astype(int)
        df['Green_Days_Ratio_20D'] = df['Is_Green_Day'].rolling(window=20).mean()
        
        # SMA 50 Slope - trend strength (percentage change per day)
        df['SMA_50_Slope'] = (df['SMA_50'] - df['SMA_50'].shift(10)) / df['SMA_50'].shift(10) / 10 * 100
        
        # NEW: Distance-based pattern detectors
        # Distance from 20-day low (bounce pattern detector)
        df['Lowest_Low_20D'] = df['Low'].rolling(window=20).min()
        df['Dist_From_20D_Low'] = np.where(
            df['Lowest_Low_20D'] > 0,
            (df['Close'] / df['Lowest_Low_20D']) - 1,
            np.nan
        )
        
        # Distance from 20-day high (resistance proximity)
        df['Highest_High_20D'] = df['High'].rolling(window=20).max()
        df['Dist_From_20D_High'] = np.where(
            df['Highest_High_20D'] > 0,
            (df['Close'] / df['Highest_High_20D']) - 1,
            np.nan
        )
        
        # Distance from 52-week low (recovery/reversal detector)
        df['Dist_From_52W_Low'] = np.where(
            df['Low_52W'] > 0,
            (df['Close'] / df['Low_52W']) - 1,
            np.nan
        )

        # Import centralized lag config
        try:
            from src.feature_config import FEATURES_TO_LAG

            for feature in FEATURES_TO_LAG:
                if feature in df.columns:
                    # Create Lag1
                    df[f"{feature}_Lag1"] = df[feature].shift(1)
                    # We can add more lags here if feature_config dictates

            # NEW: Create Delta features (percentage change from T-1 to T)
            # Delta = (Current - Lag1) / Lag1
            # This captures momentum separately from absolute levels
            for feature in FEATURES_TO_LAG:
                if feature in df.columns:
                    lag_col = f"{feature}_Lag1"
                    delta_col = f"{feature}_Delta"

                    # Only create delta if lag was successfully created
                    if lag_col in df.columns:
                        # Vectorized percentage change with edge case handling
                        # Avoid division by zero/near-zero values
                        df[delta_col] = np.where(
                            np.abs(df[lag_col]) > 1e-10,  # Threshold to avoid numerical instability
                            (df[feature] - df[lag_col]) / df[lag_col],
                            np.nan  # Set to NaN when Lag1 is 0 or too small
                        )

                        # Clean up any inf values (defensive)
                        df[delta_col] = df[delta_col].replace([np.inf, -np.inf], np.nan)

        except ImportError:
            # Fallback if config not found
            pass

        return df

    def add_lagged_features(self, df: pd.DataFrame, lag_periods: int = 1) -> pd.DataFrame:
        """
        Add lagged versions of setup features to separate "cause" (T-1) from "effect" (T).

        Strategy: We want to know if the stock was "Quiet, Tight, and Trending"
        BEFORE it exploded, not during. This separates the BASE (setup) from the
        BREAKOUT (trigger).

        Features to Lag (Setup Conditions at T-1):
        - Volatility (The "Coil"): nATR, ATR, VCP_Ratio, Consolidation_Width
        - Trend Structure: Price_vs_SMA_50/150/200
        - Relative Strength: RS, RS_MA
        - Supply Dynamics: Dry_Up_Volume
        - Geometry: High_52W, Low_52W
        - Momentum: RSI_14, Dist_From_52W_High

        Features NOT Lagged (Trigger Conditions at T):
        - Vol_Ratio (today's volume surge - the trigger itself)
        - Close, Volume (current price/volume)
        - Green_Days_Ratio_20D (recent price action)
        - Breakout (today's breakout signal)
        - Alpha factors (fast mean-reversion signals)

        Args:
            df: DataFrame with calculated features (single-ticker context)
            lag_periods: Number of periods to lag (default: 1)

        Returns:
            DataFrame with lagged features added (e.g., nATR_Lag1, RS_Lag1)

        Notes:
            - Uses .shift(lag_periods) for backward shift
            - First N rows will have NaN lags (XGBoost handles this naturally)
            - For multi-ticker DataFrames, use .groupby('ticker').shift() externally
            - This method assumes single-ticker context (as used in calculate_lightweight_features)

        Example:
            >>> # Single ticker
            >>> df = feature_eng.calculate_lightweight_features(aapl_df)
            >>> # Lagged features already included automatically
            >>> print(df[['nATR', 'nATR_Lag1']].tail())
        """
        FEATURES_TO_LAG = [
            # --- VOLATILITY (The "Coil") ---
            'nATR',                 # CRITICAL: Must be measured before the explosion
            'ATR',
            'VCP_Ratio',            # The definition of the pattern
            'Consolidation_Width',  # Depth of the base

            # --- TREND STRUCTURE ---
            'Price_vs_SMA_50',      # Was it extended or properly set up?
            'Price_vs_SMA_150',
            'Price_vs_SMA_200',

            # --- RELATIVE STRENGTH ---
            'RS',                   # Was it a leader leading INTO the breakout?
            'RS_MA',

            # --- SUPPLY DYNAMICS ---
            'Dry_Up_Volume',        # Volume dry up YESTERDAY

            # --- GEOMETRY ---
            'High_52W',             # Context for where we are in the range
            'Low_52W',

            # --- MOMENTUM ---
            'RSI_14',               # Momentum oscillator
            'Dist_From_52W_High'    # Distance from 52-week high
        ]

        df = df.copy()
        lagged_count = 0

        for feature in FEATURES_TO_LAG:
            if feature in df.columns:
                lag_col_name = f"{feature}_Lag{lag_periods}"
                df[lag_col_name] = df[feature].shift(lag_periods)
                lagged_count += 1
                logger.debug(f"  Created {lag_col_name}")
            else:
                logger.warning(f"Feature '{feature}' not found in DataFrame. Skipping lag.")

        logger.debug(f"Added {lagged_count}/{len(FEATURES_TO_LAG)} lagged features with lag={lag_periods}")

        return df

    def calculate_heavyweight_features(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """
        Stage 2: Calculate heavyweight features for qualified candidates.
        
        This method is only called on stocks that pass the SEPA screen (5-10 candidates).
        It calculates computationally expensive features:
        - WorldQuant Alpha Factors (intraday correlations, momentum decay)
        - Future: Fundamental Metrics (EPS growth, sales acceleration, earnings surprises)
        
        Args:
            df: DataFrame with OHLCV + lightweight features
            ticker: Stock symbol (needed for fundamental data lookup)
        
        Returns:
            DataFrame with heavyweight features added
        """
        logger.debug(f"Calculating heavyweight features for {ticker}")
        
        try:
            # Import AlphaEngine (lazy import to avoid circular dependencies)
            from src.alpha_factors import AlphaEngine
            
            # Calculate WorldQuant alpha factors with new enhanced alpha set
            alpha_engine = AlphaEngine()  # Uses default: [2, 4, 11, 13, 15, 54, 60]
            df = alpha_engine.calculate_alphas(df)
            
            logger.debug(f"Heavyweight features calculated for {ticker}: {alpha_engine.get_alpha_names()}")
            
            # Future Phase 2 additions:
            # - Fundamental metrics from FMP API
            # - Earnings surprises
            # - Analyst estimates
            
        except Exception as e:
            logger.error(f"Failed to calculate heavyweight features for {ticker}: {e}")
            # Continue with lightweight features only if alpha calculation fails
        
        return df
    
    def process_universe_batch(self, ticker_data_dict: Dict[str, pd.DataFrame], show_progress: bool = True) -> Dict[str, pd.DataFrame]:
        """
        Batch processing of multiple tickers with lightweight features.
        
        Optimized for scanning the entire S&P 500 universe efficiently.
        
        Args:
            ticker_data_dict: Dict mapping ticker symbol -> raw OHLCV DataFrame
            show_progress: If True, displays progress bar
        
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
        
        # Try to show progress bar
        if show_progress:
            try:
                from tqdm import tqdm
                ticker_iterator = tqdm(ticker_data_dict.items(), desc="Computing Features", unit="ticker",
                                     total=len(ticker_data_dict))
            except ImportError:
                ticker_iterator = ticker_data_dict.items()
                logger.info(f"Processing {len(ticker_data_dict)} tickers...")
        else:
            ticker_iterator = ticker_data_dict.items()
        
        for ticker, df in ticker_iterator:
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

    def add_company_features(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """
        Add company profile features to DataFrame for ML model.

        Adds sector, industry, market cap, and beta features from company profile data.
        These features enable sector-wise analysis and provide fundamental context
        to the technical indicators.

        Args:
            df: DataFrame with OHLCV + technical features
            ticker: Stock symbol

        Returns:
            DataFrame with added company features:
            - sector_id: int (encoded sector, -1 if missing)
            - industry_id: int (encoded industry, -1 if missing)
            - mktCap_log: float (log10 of market cap for scale normalization, 0 if missing)
            - beta: float (volatility vs market, 1.0 if missing)

        Example:
            >>> df = feature_eng.calculate_lightweight_features(price_df)
            >>> df = feature_eng.add_company_features(df, 'AAPL')
            >>> print(df[['Close', 'sector_id', 'industry_id']].tail())
        """
        if self.profile_engine is None:
            logger.warning("CompanyProfileEngine not available, filling with default values")
            df['sector_id'] = -1
            df['industry_id'] = -1
            df['mktCap_log'] = 0.0
            df['beta'] = 1.0
            return df

        # Get profile for ticker
        profile = self.profile_engine.get_ticker_profile(ticker)

        if profile is None:
            logger.debug(f"No profile found for {ticker}, using default values")
            # Fill with neutral/default values
            df['sector_id'] = -1
            df['industry_id'] = -1
            df['mktCap_log'] = 0.0
            df['beta'] = 1.0
        else:
            # Broadcast scalar values to entire DataFrame
            df['sector_id'] = int(profile['sector_id'])
            df['industry_id'] = int(profile['industry_id'])

            # Log scale market cap for better ML feature scaling
            mkt_cap = float(profile['mktCap'])
            df['mktCap_log'] = np.log10(mkt_cap + 1) if mkt_cap > 0 else 0.0

            # Beta (default to 1.0 if missing)
            df['beta'] = float(profile['beta']) if pd.notna(profile['beta']) else 1.0

        return df
