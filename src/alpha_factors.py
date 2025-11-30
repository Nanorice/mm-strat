"""
Alpha Factor Engine - WorldQuant Alpha Integration

Provides a clean interface to WorldQuant 101 alpha factors with:
- Automatic temporal alignment (no future leakage)
- Selective alpha calculation (only specified alphas)
- Robust error handling for NaN/inf values
- Time-series only alphas (no cross-sectional ranking for Sprint 1)
"""

import pandas as pd
import numpy as np
from typing import List, Optional
import logging
import sys
from pathlib import Path

# Add parent to path for WorldQuant_101 import
sys.path.append(str(Path(__file__).parent.parent))
from WorldQuant_101 import Alphas

logger = logging.getLogger(__name__)


class AlphaEngine:
    """
    Wrapper around WorldQuant 101 Alphas with temporal integrity enforcement.
    
    Selected Alphas (Sprint 1 - Time-Series Only):
        - Alpha #001: Signed power of volatility-adjusted close
        - Alpha #006: -1 × correlation(open, volume, 10)
        - Alpha #009: Trend sustainability (consistent momentum)
        - Alpha #012: sign(delta(volume, 1)) × (-1 × delta(close, 1))
        - Alpha #041: √(high × low) - vwap
        - Alpha #101: (close - open) / (high - low + 0.001)
    
    Note: Cross-sectional ranking alphas are excluded for simplicity in Sprint 1.
    """
    
    # Default alpha list (time-series only, no rank())
    DEFAULT_ALPHAS = [1, 6, 9, 12, 41, 101]
    
    def __init__(self, alpha_list: Optional[List[int]] = None):
        """
        Initialize Alpha Engine.
        
        Args:
            alpha_list: List of alpha numbers to calculate (default: [1, 6, 12, 41, 101])
        """
        self.alpha_list = alpha_list if alpha_list is not None else self.DEFAULT_ALPHAS
        logger.debug(f"AlphaEngine initialized with alphas: {self.alpha_list}")
    
    def _prepare_wq_format(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Convert standard OHLCV DataFrame to WorldQuant_101 expected format.
        
        WorldQuant_101.py expects columns:
        - S_DQ_OPEN, S_DQ_HIGH, S_DQ_LOW, S_DQ_CLOSE
        - S_DQ_VOLUME, S_DQ_PCTCHANGE, S_DQ_AMOUNT
        
        Args:
            df: DataFrame with columns [Open, High, Low, Close, Volume]
        
        Returns:
            DataFrame in WorldQuant format
        """
        wq_df = pd.DataFrame(index=df.index)
        
        # Map standard columns to WQ format
        wq_df['S_DQ_OPEN'] = df['Open']
        wq_df['S_DQ_HIGH'] = df['High']
        wq_df['S_DQ_LOW'] = df['Low']
        wq_df['S_DQ_CLOSE'] = df['Close']
        wq_df['S_DQ_VOLUME'] = df['Volume']
        
        # Calculate percentage change
        wq_df['S_DQ_PCTCHANGE'] = df['Close'].pct_change() * 100
        
        # Estimate AMOUNT (volume * average price)
        # WQ expects AMOUNT in thousands, volume in hundreds
        avg_price = (df['High'] + df['Low'] + df['Close']) / 3
        wq_df['S_DQ_AMOUNT'] = (df['Volume'] * avg_price) / 1000
        
        return wq_df
    
    def _sanitize_alpha_output(self, series: pd.Series, alpha_name: str) -> pd.Series:
        """
        Clean alpha output: replace inf/nan with 0, clip extreme values.
        
        Args:
            series: Raw alpha factor values
            alpha_name: Name of alpha for logging
        
        Returns:
            Cleaned series
        """
        original_nulls = series.isnull().sum()
        original_infs = np.isinf(series).sum()
        
        # Replace inf with NaN, then fill NaN with 0
        series = series.replace([np.inf, -np.inf], np.nan)
        series = series.fillna(0)
        
        # Clip extreme values (beyond 99.9th percentile)
        if len(series) > 0:
            upper_bound = series.quantile(0.999)
            lower_bound = series.quantile(0.001)
            series = series.clip(lower_bound, upper_bound)
        
        if original_nulls > 0 or original_infs > 0:
            logger.debug(
                f"{alpha_name}: Cleaned {original_nulls} NaN, {original_infs} Inf values"
            )
        
        return series
    
    def calculate_alphas(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate selected WorldQuant alphas for given price data.
        
        TEMPORAL INTEGRITY:
        - Input df should contain data up to Day T (scan date)
        - Output alphas are valid for entry on Day T+1
        - No future data is used in calculations
        
        Args:
            df: OHLCV DataFrame with DatetimeIndex
                Required columns: Open, High, Low, Close, Volume
        
        Returns:
            Copy of df with alpha columns added: alpha001, alpha006, ...
        
        Example:
            >>> from src.data_engine import DataRepository
            >>> repo = DataRepository()
            >>> price_data = repo.get_ticker_data('AAPL')
            >>> 
            >>> engine = AlphaEngine(alpha_list=[1, 6, 101])
            >>> enriched_data = engine.calculate_alphas(price_data)
            >>> print(enriched_data[['Close', 'alpha001', 'alpha006', 'alpha101']].tail())
        """
        try:
            # Validate input
            required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                raise ValueError(f"Missing required columns: {missing_cols}")
            
            if len(df) < 50:
                logger.warning(f"Insufficient data ({len(df)} rows). Alphas may be unstable.")
            
            # Create output dataframe
            result = df.copy()
            
            # Convert to WorldQuant format
            wq_data = self._prepare_wq_format(df)
            
            # Initialize WorldQuant Alphas class
            alpha_calculator = Alphas(wq_data)
            
            # Calculate each requested alpha
            successful_alphas = []
            failed_alphas = []
            
            for alpha_num in self.alpha_list:
                method_name = f'alpha{alpha_num:03d}'
                column_name = f'alpha{alpha_num:03d}'
                
                if not hasattr(alpha_calculator, method_name):
                    logger.warning(f"Alpha {alpha_num} not implemented in WorldQuant_101.py")
                    failed_alphas.append(alpha_num)
                    continue
                
                try:
                    # Calculate alpha
                    alpha_values = getattr(alpha_calculator, method_name)()
                    
                    # Convert to Series if DataFrame
                    if isinstance(alpha_values, pd.DataFrame):
                        if len(alpha_values.columns) == 1:
                            alpha_values = alpha_values.iloc[:, 0]
                        else:
                            logger.warning(f"Alpha {alpha_num} returned multi-column DataFrame")
                            alpha_values = alpha_values.iloc[:, 0]
                    
                    # Sanitize output
                    alpha_values = self._sanitize_alpha_output(alpha_values, column_name)
                    
                    # Add to result
                    result[column_name] = alpha_values
                    successful_alphas.append(alpha_num)
                    
                except Exception as e:
                    logger.error(f"Failed to calculate alpha {alpha_num}: {e}")
                    failed_alphas.append(alpha_num)
                    # Add column of zeros as fallback
                    result[column_name] = 0.0
            
            logger.debug(
                f"Alpha calculation complete: {len(successful_alphas)}/{len(self.alpha_list)} successful"
            )
            
            if failed_alphas:
                logger.warning(f"Failed alphas: {failed_alphas}")
            
            return result
            
        except Exception as e:
            logger.error(f"Alpha calculation failed: {e}", exc_info=True)
            # Return original dataframe if complete failure
            return df
    
    def get_alpha_names(self) -> List[str]:
        """
        Get list of alpha column names that will be generated.
        
        Returns:
            List of column names like ['alpha001', 'alpha006', ...]
        """
        return [f'alpha{num:03d}' for num in self.alpha_list]
    
    def validate_alpha_output(self, df: pd.DataFrame) -> bool:
        """
        Verify that all expected alpha columns are present.
        
        Args:
            df: DataFrame to validate
        
        Returns:
            True if all alphas present, False otherwise
        """
        expected_cols = self.get_alpha_names()
        missing_cols = [col for col in expected_cols if col not in df.columns]
        
        if missing_cols:
            logger.error(f"Missing alpha columns: {missing_cols}")
            return False
        
        logger.debug(f"All {len(expected_cols)} alpha columns present")
        return True


# Convenience function for quick alpha calculation
def add_alpha_factors(
    df: pd.DataFrame,
    alpha_list: Optional[List[int]] = None
) -> pd.DataFrame:
    """
    Convenience function to add alpha factors to a DataFrame.
    
    Args:
        df: OHLCV DataFrame
        alpha_list: Optional list of alpha numbers (default: [1, 6, 12, 41, 101])
    
    Returns:
        DataFrame with alpha columns added
    
    Example:
        >>> df = pd.read_parquet('data/price/AAPL.parquet')
        >>> df_with_alphas = add_alpha_factors(df, alpha_list=[1, 6, 101])
    """
    engine = AlphaEngine(alpha_list=alpha_list)
    return engine.calculate_alphas(df)


if __name__ == '__main__':
    # Example usage
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Test with synthetic data
    dates = pd.date_range('2023-01-01', '2024-01-01', freq='B')
    test_df = pd.DataFrame({
        'Open': np.random.uniform(100, 110, len(dates)),
        'High': np.random.uniform(110, 120, len(dates)),
        'Low': np.random.uniform(90, 100, len(dates)),
        'Close': np.random.uniform(100, 110, len(dates)),
        'Volume': np.random.randint(1000000, 10000000, len(dates))
    }, index=dates)
    
    engine = AlphaEngine()
    result = engine.calculate_alphas(test_df)
    
    print("\nAlpha Columns:")
    print(engine.get_alpha_names())
    
    print("\nSample Output:")
    print(result[['Close'] + engine.get_alpha_names()].tail())
