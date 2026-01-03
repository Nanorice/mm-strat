"""
Feature Rehydrator Module (Live Mode)
Responsibility: Fetch LATEST data for existing tickers to update their features.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from typing import List, Optional

# Imports from your existing architecture
from src.features import FeatureEngineer
from src.data_engine import DataRepository

logger = logging.getLogger(__name__)

class FeatureRehydrator:
    def __init__(self, data_repo: DataRepository):
        self.data_repo = data_repo
        self.feature_engine = FeatureEngineer()
        
    def rehydrate_batch(self, candidates_df: pd.DataFrame, lookback_days: int = 400) -> pd.DataFrame:
        """
        Fetches the LATEST features for a batch of tickers.
        
        Args:
            candidates_df: DataFrame containing at least ['ticker']
            lookback_days: Window to calculate valid Moving Averages (default 400)
            
        Returns:
            DataFrame with original columns + LATEST calculated features.
        """
        if 'ticker' not in candidates_df.columns:
            logger.error("Rehydration failed: Input missing 'ticker' column")
            return candidates_df

        # 1. Identify Tickers
        tickers = candidates_df['ticker'].unique().tolist()
        if not tickers:
            return candidates_df

        logger.info(f"Feature Rehydration: Fetching LATEST data for {len(tickers)} tickers...")
        
        # 2. Define Time Window (UP TO TODAY)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)
        
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        
        try:
            # 3. Batch Fetch Data
            # This gets the full history for all tickers in one go
            raw_data = self.data_repo.get_batch_data(
                tickers=tickers,
                start_date=start_str,
                end_date=end_str
            )
            
            if raw_data.empty:
                logger.warning("Rehydration: No data returned from repository.")
                return candidates_df

            # 4. Calculate Features (Standard Engine)
            processed_data = self.feature_engine.process_universe_batch(raw_data)
            
            # 5. Extract ONLY the Latest Row for each Ticker
            # We want the most current state of the indicators
            if 'ticker' not in processed_data.columns and processed_data.index.name == 'ticker':
                processed_data = processed_data.reset_index()
            
            # Sort by date and take the last one for each ticker
            latest_features = processed_data.sort_values('date').groupby('ticker').tail(1)
            
            # 6. Merge back to original signals
            # We merge on 'ticker' only, ignoring the signal date
            
            # Drop columns in candidates that might collide (except ticker/date/metadata)
            cols_to_use = latest_features.columns.difference(candidates_df.columns).tolist()
            cols_to_use.append('ticker')
            
            latest_features_clean = latest_features[cols_to_use]
            
            # Left join ensures we keep all signals, even if data fetch failed for some
            result_df = pd.merge(
                candidates_df,
                latest_features_clean,
                on='ticker',
                how='left'
            )
            
            # Check success rate
            # Assuming 'RSI_14' is a standard feature to check coverage
            if 'RSI_14' in result_df.columns:
                filled = result_df['RSI_14'].notna().sum()
                logger.info(f"✅ Rehydration Complete. Features updated for {filled}/{len(result_df)} tickers.")
            
            return result_df

        except Exception as e:
            logger.error(f"Critical Rehydration Error: {e}")
            import traceback
            traceback.print_exc()
            return candidates_df