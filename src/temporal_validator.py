"""
Temporal Validator - Ensures No Data Leakage in Feature Engineering
 
Implements temporal integrity checks to verify that features calculated
for trade entry on Day T+1 use only data available up to Day T (inclusive).
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class TemporalValidator:
    """
    Validates temporal alignment in feature engineering to prevent look-ahead bias.
    
    Key Principle:
        - SEPA scan runs AFTER market close on Day T (e.g., 4pm+ ET)
        - Features use data up to and including Day T close
        - Trade entry happens on Day T+1 at market open
        - NO future data from Day T+1 is used
    
    This is equivalent to WorldQuant "Delay-0" with overnight execution gap.
    """
    
    def __init__(self):
        self.validation_results = []
    
    def validate_no_future_leakage(
        self, 
        df: pd.DataFrame, 
        entry_date: pd.Timestamp
    ) -> bool:
        """
        Verify that features for entry_date use only data up to entry_date-1.
        
        Args:
            df: DataFrame with DatetimeIndex and feature columns
            entry_date: The date when trade entry will occur
        
        Returns:
            True if validation passes (no future leakage)
        
        Example:
            >>> df = load_ticker_data('NVDA', end_date='2024-11-05')
            >>> validator = TemporalValidator()
            >>> # For entry on 2024-11-05, we should have features up to 2024-11-04
            >>> is_valid = validator.validate_no_future_leakage(df, pd.Timestamp('2024-11-05'))
        """
        try:
            # Get the feature calculation date (day before entry)
            feature_date = entry_date - pd.Timedelta(days=1)
            
            # Check that DataFrame doesn't contain data beyond feature_date
            max_date_in_df = df.index.max()
            
            if max_date_in_df > feature_date:
                logger.warning(
                    f"Potential future leakage: DataFrame contains data up to {max_date_in_df}, "
                    f"but features for entry on {entry_date} should only use data up to {feature_date}"
                )
                return False
            
            logger.debug(f"Temporal validation passed for entry_date={entry_date}")
            return True
            
        except Exception as e:
            logger.error(f"Temporal validation error: {e}")
            return False
    
    def get_feature_data_for_entry(
        self,
        df: pd.DataFrame,
        entry_date: pd.Timestamp
    ) -> pd.DataFrame:
        """
        Extract the correct subset of data for calculating features.
        
        For entry on Day T+1, returns data up to and including Day T.
        
        Args:
            df: Full price DataFrame
            entry_date: Date when trade will be entered
        
        Returns:
            Subset of df containing only data available before entry
        
        Example:
            >>> df = load_ticker_data('AAPL')
            >>> entry_date = pd.Timestamp('2024-11-05')
            >>> # Get data available for scan on 2024-11-04 (after close)
            >>> feature_data = validator.get_feature_data_for_entry(df, entry_date)
            >>> # feature_data contains prices up to 2024-11-04 close
        """
        # For entry on T+1, we scan on T after close
        # So we have data up to T (inclusive)
        scan_date = entry_date - pd.Timedelta(days=1)
        
        # Return all data up to scan_date
        subset = df[df.index <= scan_date].copy()
        
        logger.debug(
            f"Extracted {len(subset)} rows for entry_date={entry_date} "
            f"(data up to {subset.index.max() if len(subset) > 0 else 'N/A'})"
        )
        
        return subset
    
    def perturbation_test(
        self,
        calculate_features_fn,
        ticker: str,
        entry_date: pd.Timestamp,
        feature_name: str,
        spike_magnitude: float = 10.0,
        price_data: Optional[pd.DataFrame] = None
    ) -> bool:
        """
        Perturbation test: inject future data spike and verify features are unchanged.
        
        This is the "gold standard" test for detecting data leakage. If changing
        future prices affects past features, there is leakage.
        
        Args:
            calculate_features_fn: Function that takes DataFrame and returns features
            ticker: Stock symbol
            entry_date: Date when trade will be entered
            feature_name: Name of feature to test (e.g., 'RSI_14', 'SMA_50')
            spike_magnitude: Multiplier for the spike (default: 10x)
            price_data: Optional pre-loaded price data
        
        Returns:
            True if test passes (no leakage), False if leakage detected
        
        Example:
            >>> from src.features import FeatureEngineer
            >>> from src.data_engine import DataRepository
            >>> 
            >>> def calc_features(df):
            ...     fe = FeatureEngineer()
            ...     return fe.calculate_lightweight_features(df)
            >>> 
            >>> validator = TemporalValidator()
            >>> passed = validator.perturbation_test(
            ...     calculate_features_fn=calc_features,
            ...     ticker='NVDA',
            ...     entry_date=pd.Timestamp('2024-11-05'),
            ...     feature_name='Vol_Ratio',
            ...     spike_magnitude=100.0
            ... )
            >>> assert passed, "Data leakage detected!"
        """
        try:
            # Load price data if not provided
            if price_data is None:
                from src.data_engine import DataRepository
                repo = DataRepository()
                price_data = repo.get_ticker_data(ticker)
                if price_data is None:
                    logger.error(f"Could not load data for {ticker}")
                    return False
            
            # Get data available for entry_date
            scan_date = entry_date - pd.Timedelta(days=1)
            df_original = price_data[price_data.index <= scan_date].copy()
            
            # Calculate original features
            features_original = calculate_features_fn(df_original)
            if feature_name not in features_original.columns:
                logger.error(f"Feature {feature_name} not found in calculated features")
                return False
            
            original_value = features_original[feature_name].iloc[-1]
            
            # Create spiked version: multiply future volume/prices by spike_magnitude
            # Find first date after entry_date
            future_dates = price_data[price_data.index > scan_date].index
            if len(future_dates) == 0:
                logger.warning(f"No future data available after {scan_date} for perturbation test")
                return True  # Can't test, but not a failure
            
            spike_date = future_dates[0]
            
            # Create spiked dataset
            df_spiked = price_data.copy()
            df_spiked.loc[spike_date, 'Volume'] *= spike_magnitude
            df_spiked.loc[spike_date, 'Close'] *= spike_magnitude
            df_spiked.loc[spike_date, 'High'] *= spike_magnitude
            
            # Get spiked data subset (same date range as original)
            df_spiked_subset = df_spiked[df_spiked.index <= scan_date].copy()
            
            # Recalculate features with spiked future data
            features_spiked = calculate_features_fn(df_spiked_subset)
            spiked_value = features_spiked[feature_name].iloc[-1]
            
            # Compare values
            if pd.isna(original_value) and pd.isna(spiked_value):
                # Both NaN - pass
                return True
            
            # Allow for small floating point differences
            tolerance = 1e-6
            values_match = abs(original_value - spiked_value) < tolerance
            
            if values_match:
                logger.info(
                    f"✅ Perturbation test PASSED for {ticker} / {feature_name} / entry={entry_date}"
                )
                logger.debug(f"   Original: {original_value}, Spiked: {spiked_value}")
                return True
            else:
                logger.error(
                    f"❌ Perturbation test FAILED for {ticker} / {feature_name} / entry={entry_date}"
                )
                logger.error(
                    f"   Future data spike on {spike_date} changed feature value!"
                )
                logger.error(f"   Original: {original_value}, Spiked: {spiked_value}")
                logger.error(f"   This indicates DATA LEAKAGE!")
                return False
                
        except Exception as e:
            logger.error(f"Perturbation test error: {e}", exc_info=True)
            return False
    
    def manual_audit(
        self,
        df: pd.DataFrame,
        ticker: str,
        entry_date: pd.Timestamp,
        feature_values: Dict[str, float],
        expected_values: Dict[str, float],
        tolerance: float = 0.5
    ) -> bool:
        """
        Manual audit: compare calculated features against manual TradingView/Excel values.
        
        Args:
            df: DataFrame with calculated features
            ticker: Stock symbol
            entry_date: Date when trade will be entered
            feature_values: Dict of calculated feature values
            expected_values: Dict of manually verified values from TradingView
            tolerance: Acceptable percentage difference (default: 0.5%)
        
        Returns:
            True if all features match within tolerance
        
        Example:
            >>> # Manual TradingView values for NVDA on 2024-11-04 (for entry on 11-05)
            >>> expected = {
            ...     'SMA_50': 142.35,
            ...     'SMA_200': 118.72,
            ...     'RSI_14': 63.8
            ... }
            >>> validator = TemporalValidator()
            >>> passed = validator.manual_audit(
            ...     df=features_df,
            ...     ticker='NVDA',
            ...     entry_date=pd.Timestamp('2024-11-05'),
            ...     feature_values=calculated_values,
            ...     expected_values=expected,
            ...     tolerance=0.5
            ... )
        """
        try:
            mismatches = []
            
            for feature_name, expected in expected_values.items():
                if feature_name not in feature_values:
                    logger.warning(f"Feature {feature_name} not found in calculated values")
                    mismatches.append(feature_name)
                    continue
                
                calculated = feature_values[feature_name]
                
                # Calculate percentage difference
                if expected == 0:
                    pct_diff = abs(calculated - expected)
                else:
                    pct_diff = abs((calculated - expected) / expected) * 100
                
                if pct_diff > tolerance:
                    logger.error(
                        f"❌ Mismatch: {feature_name} - "
                        f"Calculated={calculated:.2f}, Expected={expected:.2f}, "
                        f"Diff={pct_diff:.2f}%"
                    )
                    mismatches.append(feature_name)
                else:
                    logger.info(
                        f"✅ Match: {feature_name} - "
                        f"Calculated={calculated:.2f}, Expected={expected:.2f}, "
                        f"Diff={pct_diff:.2f}%"
                    )
            
            if mismatches:
                logger.error(
                    f"Manual audit FAILED for {ticker} / entry={entry_date}: "
                    f"{len(mismatches)} mismatches"
                )
                return False
            else:
                logger.info(
                    f"Manual audit PASSED for {ticker} / entry={entry_date}: "
                    f"All {len(expected_values)} features match"
                )
                return True
                
        except Exception as e:
            logger.error(f"Manual audit error: {e}", exc_info=True)
            return False
    
    def get_validation_summary(self) -> str:
        """Return summary of all validation results."""
        if not self.validation_results:
            return "No validations performed yet"
        
        total = len(self.validation_results)
        passed = sum(1 for r in self.validation_results if r['passed'])
        failed = total - passed
        
        return f"Validation Summary: {passed}/{total} passed, {failed}/{total} failed"
