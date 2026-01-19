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
        staleness_threshold_days: int = 400,
        force_cache_only: bool = False,
        include_raw_fundamentals: bool = False
    ):
        """
        Initialize Fundamental Merger.

        Args:
            fundamental_engine: Engine for loading fundamental data
            fundamental_processor: Processor for calculating growth/ratios
            staleness_threshold_days: Days before data is considered stale
            force_cache_only: If True, only use cached fundamental data (no API updates)
            include_raw_fundamentals: If True, include all raw fundamental columns.
                                     If False (default), only include derived metrics.
        """
        self.fundamental_engine = fundamental_engine or FundamentalEngine(force_cache_only=force_cache_only)
        self.fundamental_processor = fundamental_processor or FundamentalProcessor()
        self.staleness_threshold_days = staleness_threshold_days
        self.force_cache_only = force_cache_only
        self.include_raw_fundamentals = include_raw_fundamentals
    
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
        
        # Step 7: Filter columns based on include_raw_fundamentals flag
        merged_df = self._filter_fundamental_columns(merged_df)
        
        # Step 8: Restore Date as index if it was originally an index
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
            # Check if 'Date' column already exists before reset_index
            if 'Date' in df.columns:
                # Date column already exists, drop it to avoid duplicates
                df = df.drop(columns=['Date'])
            df = df.reset_index()
            was_index = True

        # Ensure Date column exists and is datetime
        if 'Date' not in df.columns:
            raise ValueError("Price dataframe must have a 'Date' column or DatetimeIndex")

        df['Date'] = pd.to_datetime(df['Date'])

        # Sort by Date for merge_asof
        df = df.sort_values('Date')

        # Validate no duplicate columns
        self._check_duplicate_columns(df, "after _prepare_price_dataframe")

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
            
            # Add intuitive alias for ML/analysis
            df['days_since_earnings'] = df['days_since_report']
            
            # Flag stale data
            df['is_stale'] = df['days_since_report'] > self.staleness_threshold_days
            
            # Replace negative days (shouldn't happen) with NaN
            df['days_since_report'] = np.where(df['days_since_report'] < 0, np.nan, df['days_since_report'])
            df['is_stale'] = np.where(df['days_since_report'] < 0, True, df['is_stale'])
        else:
            df['days_since_report'] = np.nan
            df['days_since_earnings'] = np.nan
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
        import warnings
        
        # Check if any fundamental data exists
        fundamental_cols = [
            'revenue', 'eps', 'netIncome', 'totalAssets', 'totalDebt'
        ]
        
        has_any_fundamental = any(
            col in df.columns and not df[col].isna().all()
            for col in fundamental_cols
        )
        
        df['has_fundamentals'] = has_any_fundamental
        
        # Determine which rows truly have no fundamental data
        no_fund_mask = df['has_fundamentals'] == False
        
        # Growth metrics: fill with 0 (only for rows without fundamentals)
        growth_cols = ['revenue_growth_yoy', 'eps_growth_yoy', 'net_income_growth_yoy']
        for col in growth_cols:
            if col in df.columns:
                # Use np.where to safely handle potential duplicate indices
                df[col] = np.where(no_fund_mask & df[col].isna(), 0, df[col])
        
        # Ratios: fill with median (or 0 if all NaN)
        # Suppress warnings for empty slice (when all values are NaN)
        ratio_cols = [
            'debt_to_equity', 'current_ratio', 'quick_ratio',
            'gross_margin', 'operating_margin', 'roe', 'roa'
        ]
        for col in ratio_cols:
            if col in df.columns:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=RuntimeWarning)
                    median_val = df[col].median()
                fill_val = median_val if not pd.isna(median_val) else 0
                df[col] = np.where(no_fund_mask & df[col].isna(), fill_val, df[col])
        
        # Raw values: fill with 0 (ONLY for rows without fundamentals)
        # This prevents overwriting real merged data with zeros
        raw_cols = [
            'revenue', 'netIncome', 'eps', 'totalAssets', 'totalLiabilities',
            'totalEquity', 'totalDebt', 'cash', 'totalCurrentAssets', 'totalCurrentLiabilities'
        ]
        for col in raw_cols:
            if col in df.columns:
                # Only fill rows that have NO fundamental data
                df[col] = np.where(no_fund_mask & df[col].isna(), 0, df[col])
        
        return df
    
    def calculate_hybrid_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate features that combine price + fundamentals.
        
        Phase 3: Hybrid Features
        - pe_ratio: Close / EPS
        - ps_ratio: Market Cap / Revenue = (Close × Shares Outstanding) / Revenue
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
            
            # Cap extreme P/E values (>1000 is unrealistic noise)
            df['pe_ratio'] = np.where(df['pe_ratio'] > 1000, np.nan, df['pe_ratio'])
            df['pe_ratio'] = np.where(df['pe_ratio'] < -1000, np.nan, df['pe_ratio'])
        else:
            df['pe_ratio'] = np.nan
        
        # P/S Ratio: Market Cap / Revenue
        # Market Cap = Close × Shares Outstanding
        shares_col = None
        if 'weightedAverageShsOut' in df.columns:
            shares_col = 'weightedAverageShsOut'
        elif 'weightedAverageShsOutDil' in df.columns:
            shares_col = 'weightedAverageShsOutDil'
        
        if shares_col and 'Close' in df.columns and 'revenue' in df.columns:
            # Calculate market cap
            market_cap = df['Close'] * df[shares_col]
            
            # Calculate P/S ratio
            df['ps_ratio'] = np.where(
                df['revenue'] != 0,
                market_cap / df['revenue'],
                np.nan
            )
            
            # Cap extreme P/S values (>100 is unrealistic)
            df['ps_ratio'] = np.where(df['ps_ratio'] > 100, np.nan, df['ps_ratio'])
            df['ps_ratio'] = np.where(df['ps_ratio'] < 0, np.nan, df['ps_ratio'])
        else:
            df['ps_ratio'] = np.nan
        
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
                df['pb_ratio'] = np.where(df['pb_ratio'] > 100, np.nan, df['pb_ratio'])
                df['pb_ratio'] = np.where(df['pb_ratio'] < -100, np.nan, df['pb_ratio'])
            else:
                df['pb_ratio'] = np.nan
        else:
            df['pb_ratio'] = np.nan
        
        # NEW MINERVINI VALUATION - PEG Ratio (Price/Earnings to Growth)
        # Peter Lynch's favorite: PEG < 1.0-1.5 = undervalued growth
        # Only calculated for stocks with positive growth (> 0%)
        if 'pe_ratio' in df.columns and 'eps_growth_yoy' in df.columns:
            df['peg_adjusted'] = np.where(
                df['eps_growth_yoy'] > 0,
                np.clip(df['pe_ratio'] / df['eps_growth_yoy'], 0, 10),
                np.nan
            )
        else:
            df['peg_adjusted'] = np.nan
        
        # Separate flag for declining earnings (model can branch on this)
        if 'eps_growth_yoy' in df.columns:
            df['is_declining_earnings'] = (df['eps_growth_yoy'] <= 0).astype(int)
        else:
            df['is_declining_earnings'] = 0
        
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
            # Check if 'Date' column already exists before reset_index
            if 'Date' in df.columns:
                df = df.drop(columns=['Date'])
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
            'cash', 'totalCurrentAssets', 'totalCurrentLiabilities'
        ]
        for col in raw_cols:
            df[col] = 0.0
        
        # Add cash flow columns (RAW)
        cash_flow_cols = [
            'operatingCashFlow', 'freeCashFlow', 'capitalExpenditure',
            'changeInWorkingCapital', 'cashFlowFromInvesting', 'cashFlowFromFinancing'
        ]
        for col in cash_flow_cols:
            df[col] = 0.0
        
        # Add growth columns
        growth_cols = ['revenue_growth_yoy', 'eps_growth_yoy', 'net_income_growth_yoy']
        for col in growth_cols:
            df[col] = 0.0
        
        # Add additional growth/quality metrics
        additional_growth_cols = [
            'eps_accel', 'revenue_accel',
            'inventory_growth_yoy', 'inventory_vs_sales_spread'
        ]
        for col in additional_growth_cols:
            df[col] = 0.0
        
        # Add ratio columns
        ratio_cols = [
            'debt_to_equity', 'current_ratio', 'quick_ratio',
            'gross_margin', 'operating_margin', 'roe', 'roa'
        ]
        for col in ratio_cols:
            df[col] = 0.0
        
        # Add advanced fundamental metrics (cash flow based)
        advanced_cols = [
            'operating_leverage', 'accruals_ratio', 'roic',
            'reinvestment_rate', 'efficient_growth'
        ]
        for col in advanced_cols:
            df[col] = 0.0
        
        # Add hybrid columns
        df['pe_ratio'] = np.nan
        df['pb_ratio'] = np.nan
        df['ps_ratio'] = np.nan
        df['peg_adjusted'] = np.nan
        df['is_declining_earnings'] = 0
        
        logger.debug(f"{ticker}: Added empty fundamental columns")

        return df

    def _filter_fundamental_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Filter fundamental columns based on include_raw_fundamentals flag.
        
        If include_raw_fundamentals is False (default), only keep derived metrics
        and drop raw fundamental columns to keep feature set lean.
        
        Args:
            df: Merged dataframe
            
        Returns:
            DataFrame with appropriate fundamental columns
        """
        if self.include_raw_fundamentals:
            # Keep all columns
            logger.debug("Keeping all fundamental columns (raw + derived)")
            return df
        
        # Get list of columns to drop (raw fundamentals)
        from src.fundamental_column_mapping import get_columns_to_merge, RAW_FUNDAMENTAL_COLUMNS
        
        # Get current columns
        current_cols = set(df.columns)
        
        # Get raw columns that exist in the dataframe
        columns_to_drop = [col for col in RAW_FUNDAMENTAL_COLUMNS if col in current_cols]
        
        if columns_to_drop:
            df = df.drop(columns=columns_to_drop)
            logger.debug(f"Dropped {len(columns_to_drop)} raw fundamental columns (keeping only derived metrics)")
        
        return df

    def _check_duplicate_columns(self, df: pd.DataFrame, context: str = "") -> None:
        """
        Check for duplicate column names and raise error if found.

        Args:
            df: DataFrame to check
            context: Context string for error message

        Raises:
            ValueError: If duplicate columns are detected
        """
        duplicate_cols = df.columns[df.columns.duplicated()].tolist()
        if duplicate_cols:
            error_msg = f"Duplicate columns detected {context}: {duplicate_cols}"
            logger.error(error_msg)
            raise ValueError(error_msg)

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
