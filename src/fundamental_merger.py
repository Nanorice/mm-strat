"""
Fundamental Merger - Phase 2 & 3 of Fundamental Enrichment Pipeline

Merges sparse quarterly fundamentals with dense daily price data using as-of join.
Calculates hybrid features that combine price and fundamental data.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Tuple
import logging

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config

from src.fundamental_engine import FundamentalEngine
from src.fundamental_processor import FundamentalProcessor

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL))
logger = logging.getLogger(__name__)


class FundamentalMerger:
    """
    Merges fundamental data with price data using as-of join.
    
    Phase 2: As-Of Join (Sparse → Dense)
    - Performs temporal as-of join on filing_date
    - Forward fills fundamental values
    - Calculates staleness metrics
    
    Phase 3: Hybrid Features
    - Calculates P/E, P/S, P/B ratios
    - Combines dynamic price with static fundamentals
    """
    
    def __init__(
        self,
        fundamental_engine: Optional[FundamentalEngine] = None,
        fundamental_processor: Optional[FundamentalProcessor] = None,
        staleness_threshold_days: int = 400
    ):
        """
        Initialize Fundamental Merger.
        
        Args:
            fundamental_engine: Engine for loading fundamental data
            fundamental_processor: Processor for calculating growth/ratios
            staleness_threshold_days: Days before data is considered stale
        """
        self.fundamental_engine = fundamental_engine or FundamentalEngine()
        self.fundamental_processor = fundamental_processor or FundamentalProcessor()
        self.staleness_threshold_days = staleness_threshold_days
    
    def merge_ticker_data(
        self,
        ticker: str,
        price_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Merge daily price data with fundamentals using as-of join.
        
        Args:
            ticker: Stock symbol
            price_df: Daily price dataframe with 'Date' index or column
            
        Returns:
            Merged dataframe with price + fundamental + hybrid features
        """
        logger.debug(f"Merging fundamentals for {ticker}...")
        
        # Step 1: Load and process fundamental data
        fund_raw = self.fundamental_engine.get_ticker_fundamentals(ticker, use_cache=True)
        
        if fund_raw is None or fund_raw.empty:
            logger.warning(f"{ticker}: No fundamental data available, adding NaN columns")
            return self._add_empty_fundamental_columns(price_df, ticker)
        
        fund_processed = self.fundamental_processor.process_ticker_fundamentals(ticker, fund_raw)
        
        if fund_processed.empty:
            logger.warning(f"{ticker}: Fundamental processing failed, adding NaN columns")
            return self._add_empty_fundamental_columns(price_df, ticker)
        
        # Step 2: Prepare price dataframe (returns tuple now)
        price_df_prepared, was_index = self._prepare_price_dataframe(price_df)
        
        # Step 3: Perform as-of join
        merged_df = self._as_of_join(price_df_prepared, fund_processed, ticker)
        
        # Step 4: Calculate staleness metrics
        merged_df = self._calculate_staleness(merged_df)
        
        # Step 5: Handle missing fundamentals
        merged_df = self._handle_missing_fundamentals(merged_df)
        
        # Step 6: Calculate hybrid features (Phase 3)
        merged_df = self.calculate_hybrid_features(merged_df)
        
        # Step 7: Restore Date as index if it was originally an index
        if was_index and 'Date' in merged_df.columns:
            merged_df = merged_df.set_index('Date')
        
        logger.debug(f"{ticker}: Merged {len(merged_df)} rows with fundamentals")
        
        return merged_df
    
    def _prepare_price_dataframe(self, price_df: pd.DataFrame) -> tuple:
        """
        Prepare price dataframe for merging.
        
        Ensures 'Date' is a column (not index) for merge_asof.
        
        Args:
            price_df: Price dataframe
            
        Returns:
            Tuple of (prepared dataframe, was_index flag)
        """
        df = price_df.copy()
        was_index = False
        
        # If Date is the index, reset it
        if df.index.name == 'Date' or isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
            was_index = True
        
        # Ensure Date column exists and is datetime
        if 'Date' not in df.columns:
            raise ValueError("Price dataframe must have a 'Date' column or DatetimeIndex")
        
        df['Date'] = pd.to_datetime(df['Date'])
        
        # Sort by Date for merge_asof
        df = df.sort_values('Date')
        
        return df, was_index
    
    def _as_of_join(
        self,
        price_df: pd.DataFrame,
        fund_df: pd.DataFrame,
        ticker: str
    ) -> pd.DataFrame:
        """
        Perform temporal as-of join.
        
        CRITICAL: Joins on filing_date (report release) NOT fiscal_date
        to prevent look-ahead bias.
        
        Logic: For each price date, find the most recent filing_date <= price date
        
        Args:
            price_df: Daily price data (sorted by Date)
            fund_df: Processed fundamental data (sorted by filing_date)
            ticker: Stock symbol for logging
            
        Returns:
            Merged dataframe
        """
        # Ensure fund_df is sorted by filing_date
        fund_df = fund_df.sort_values('filing_date')
        
        # Perform as-of join
        # This matches each price date with the last available fundamental report
        merged = pd.merge_asof(
            price_df,
            fund_df,
            left_on='Date',
            right_on='filing_date',
            direction='backward',  # Use last available report (no look-ahead!)
            allow_exact_matches=True
        )
        
        # Rename filing_date to filing_date_matched for clarity
        if 'filing_date' in merged.columns:
            merged = merged.rename(columns={'filing_date': 'filing_date_matched'})
        
        logger.debug(
            f"{ticker}: As-of join completed. "
            f"Unique filing dates matched: {merged['filing_date_matched'].nunique() if 'filing_date_matched' in merged.columns else 0}"
        )
        
        return merged
    
    def _calculate_staleness(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate days since last fundamental report.
        
        Adds:
        - days_since_report: (Date - filing_date_matched).days
        - is_stale: True if days_since_report > threshold
        
        Args:
            df: Merged dataframe
            
        Returns:
            Dataframe with staleness columns
        """
        if 'filing_date_matched' in df.columns and 'Date' in df.columns:
            # Calculate days since report
            df['days_since_report'] = (
                df['Date'] - df['filing_date_matched']
            ).dt.days
            
            # Flag stale data
            df['is_stale'] = df['days_since_report'] > self.staleness_threshold_days
            
            # Replace negative days (shouldn't happen) with NaN
            df.loc[df['days_since_report'] < 0, 'days_since_report'] = np.nan
            df.loc[df['days_since_report'] < 0, 'is_stale'] = True
        else:
            df['days_since_report'] = np.nan
            df['is_stale'] = True
        
        return df
    
    def _handle_missing_fundamentals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Handle NaN values in fundamental columns.
        
        Strategy:
        1. Growth metrics: Fill NaN with 0 (assume no growth)
        2. Ratios: Fill NaN with median (sector-neutral assumption)
        3. Raw values: Fill NaN with 0
        4. Add has_fundamentals flag
        
        Args:
            df: Merged dataframe
            
        Returns:
            Dataframe with NaN handling applied
        """
        # Check if any fundamental data exists
        fundamental_cols = [
            'revenue', 'eps', 'netIncome', 'totalAssets', 'totalDebt'
        ]
        
        has_any_fundamental = any(
            col in df.columns and not df[col].isna().all()
            for col in fundamental_cols
        )
        
        df['has_fundamentals'] = has_any_fundamental
        
        # Growth metrics: fill with 0
        growth_cols = ['revenue_growth_yoy', 'eps_growth_yoy', 'net_income_growth_yoy']
        for col in growth_cols:
            if col in df.columns:
                df[col] = df[col].fillna(0)
        
        # Ratios: fill with median (or 0 if all NaN)
        ratio_cols = [
            'debt_to_equity', 'current_ratio', 'quick_ratio',
            'gross_margin', 'operating_margin', 'roe', 'roa'
        ]
        for col in ratio_cols:
            if col in df.columns:
                median_val = df[col].median()
                fill_val = median_val if not pd.isna(median_val) else 0
                df[col] = df[col].fillna(fill_val)
        
        # Raw values: fill with 0
        raw_cols = [
            'revenue', 'netIncome', 'eps', 'totalAssets', 'totalLiabilities',
            'totalEquity', 'totalDebt', 'cash', 'currentAssets', 'currentLiabilities'
        ]
        for col in raw_cols:
            if col in df.columns:
                df[col] = df[col].fillna(0)
        
        return df
    
    def calculate_hybrid_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate features that combine price + fundamentals.
        
        Phase 3: Hybrid Features
        - pe_ratio: Close / EPS
        - ps_ratio: Market Cap / Revenue (if market cap available)
        - pb_ratio: Market Cap / Book Value
        
        Args:
            df: Merged dataframe with price and fundamentals
            
        Returns:
            Dataframe with hybrid features added
        """
        # P/E Ratio: Close / EPS
        if 'Close' in df.columns and 'eps' in df.columns:
            df['pe_ratio'] = np.where(
                df['eps'] != 0,
                df['Close'] / df['eps'],
                np.nan
            )
            
            # Cap extreme P/E values (> 1000 is unrealistic noise)
            df.loc[df['pe_ratio'] > 1000, 'pe_ratio'] = np.nan
            df.loc[df['pe_ratio'] < -1000, 'pe_ratio'] = np.nan
        else:
            df['pe_ratio'] = np.nan
        
        # P/B Ratio: Close / Book Value per Share
        # Note: We'd need shares outstanding for this. For now, use proxy.
        if all(col in df.columns for col in ['Close', 'totalEquity', 'eps']):
            # Approximate shares outstanding: if we have EPS and netIncome
            if 'netIncome' in df.columns:
                shares_approx = np.where(
                    df['eps'] != 0,
                    df['netIncome'] / df['eps'],
                    np.nan
                )
                
                book_value_per_share = np.where(
                    shares_approx != 0,
                    df['totalEquity'] / shares_approx,
                    np.nan
                )
                
                df['pb_ratio'] = np.where(
                    book_value_per_share != 0,
                    df['Close'] / book_value_per_share,
                    np.nan
                )
                
                # Cap extreme P/B values
                df.loc[df['pb_ratio'] > 100, 'pb_ratio'] = np.nan
                df.loc[df['pb_ratio'] < -100, 'pb_ratio'] = np.nan
            else:
                df['pb_ratio'] = np.nan
        else:
            df['pb_ratio'] = np.nan
        
        # For P/S ratio, we'd need market cap which requires shares outstanding
        # Skip for now unless data is available
        df['ps_ratio'] = np.nan
        
        return df
    
    def _add_empty_fundamental_columns(
        self,
        price_df: pd.DataFrame,
        ticker: str
    ) -> pd.DataFrame:
        """
        Add empty fundamental columns when no data is available.
        
        Args:
            price_df: Price dataframe
            ticker: Stock symbol
            
        Returns:
            Price dataframe with NaN fundamental columns
        """
        df = price_df.copy()
        
        # Ensure Date column exists
        if df.index.name == 'Date' or isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
        
        # Add metadata columns
        df['filing_date_matched'] = pd.NaT
        df['days_since_report'] = np.nan
        df['is_stale'] = True
        df['has_fundamentals'] = False
        
        # Add raw fundamental columns
        raw_cols = [
            'revenue', 'netIncome', 'eps', 'grossProfit', 'operatingIncome',
            'totalAssets', 'totalLiabilities', 'totalEquity', 'totalDebt',
            'cash', 'currentAssets', 'currentLiabilities'
        ]
        for col in raw_cols:
            df[col] = 0.0
        
        # Add growth columns
        growth_cols = ['revenue_growth_yoy', 'eps_growth_yoy', 'net_income_growth_yoy']
        for col in growth_cols:
            df[col] = 0.0
        
        # Add ratio columns
        ratio_cols = [
            'debt_to_equity', 'current_ratio', 'quick_ratio',
            'gross_margin', 'operating_margin', 'roe', 'roa'
        ]
        for col in ratio_cols:
            df[col] = 0.0
        
        # Add hybrid columns
        df['pe_ratio'] = np.nan
        df['pb_ratio'] = np.nan
        df['ps_ratio'] = np.nan
        
        logger.debug(f"{ticker}: Added empty fundamental columns")
        
        return df
    
    def get_merge_statistics(self, df: pd.DataFrame) -> Dict:
        """
        Get statistics about the merged dataframe.
        
        Args:
            df: Merged dataframe
            
        Returns:
            Dictionary with merge statistics
        """
        if df.empty:
            return {
                'total_rows': 0,
                'has_fundamentals': False,
                'unique_filing_dates': 0,
                'avg_days_since_report': np.nan,
                'pct_stale': 0.0,
                'pe_ratio_median': np.nan
            }
        
        stats = {
            'total_rows': len(df),
            'has_fundamentals': df['has_fundamentals'].any() if 'has_fundamentals' in df.columns else False,
            'unique_filing_dates': df['filing_date_matched'].nunique() if 'filing_date_matched' in df.columns else 0,
            'avg_days_since_report': df['days_since_report'].mean() if 'days_since_report' in df.columns else np.nan,
            'pct_stale': (df['is_stale'].sum() / len(df) * 100) if 'is_stale' in df.columns else 0.0,
            'pe_ratio_median': df['pe_ratio'].median() if 'pe_ratio' in df.columns else np.nan
        }
        
        return stats
