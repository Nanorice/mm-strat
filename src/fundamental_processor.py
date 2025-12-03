"""
Fundamental Processor - Phase 1 of Fundamental Enrichment Pipeline

Processes sparse quarterly fundamental data before merging with daily price data.
Handles growth calculations, safety ratios, and operating metrics.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, Dict
import logging

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL))
logger = logging.getLogger(__name__)


class FundamentalProcessor:
    """
    Prepares sparse fundamental data for merging with dense price data.
    
    Phase 1 Operations:
    1. Date standardization (filing_date as primary index)
    2. Growth calculations (YoY revenue, EPS, net income)
    3. Safety ratios (debt-to-equity, current ratio, etc.)
    4. Operating metrics (margins, ROE, ROA)
    """
    
    def __init__(self):
        """Initialize Fundamental Processor."""
        self.income_statement_cols = [
            'revenue', 'netIncome', 'eps', 'grossProfit', 
            'operatingIncome', 'ebitda', 'costOfRevenue'
        ]
        self.balance_sheet_cols = [
            'totalAssets', 'totalLiabilities', 'totalEquity', 
            'totalDebt', 'cash', 'totalCurrentAssets', 'totalCurrentLiabilities',
            'inventory', 'cashAndCashEquivalents'
        ]
    
    def process_ticker_fundamentals(
        self, 
        ticker: str, 
        df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Process a single ticker's fundamental data.
        
        Args:
            ticker: Stock symbol
            df: Raw fundamental dataframe from FundamentalEngine
            
        Returns:
            Processed dataframe with growth metrics and ratios
        """
        if df is None or df.empty:
            logger.warning(f"No fundamental data for {ticker}, returning empty")
            return pd.DataFrame()
        
        # Step 1: Standardize dates
        df = self._standardize_dates(df, ticker)
        
        if df.empty:
            return df
        
        # Step 2: Separate income and balance sheet
        income_df = df[df['statement_type'] == 'income'].copy()
        balance_df = df[df['statement_type'] == 'balance_sheet'].copy()
        
        # Step 3: Calculate growth metrics (income statement)
        if not income_df.empty:
            income_df = self._calculate_growth_metrics(income_df)
        
        # Step 4: Calculate safety ratios (balance sheet + income)
        combined_df = self._merge_statements(income_df, balance_df)
        
        if not combined_df.empty:
            combined_df = self._calculate_safety_ratios(combined_df)
            combined_df = self._calculate_operating_metrics(combined_df)
        
        return combined_df
    
    def _standardize_dates(
        self, 
        df: pd.DataFrame, 
        ticker: str
    ) -> pd.DataFrame:
        """
        Standardize dates - ensure filing_date is primary.
        
        CRITICAL: We use filing_date (report release) NOT fiscal_date
        to prevent look-ahead bias (fiscal year trap).
        
        Args:
            df: Raw fundamental dataframe
            ticker: Stock symbol for logging
            
        Returns:
            Dataframe sorted by filing_date
        """
        # Verify filing_date exists
        if 'filing_date' not in df.columns:
            logger.error(f"{ticker}: Missing filing_date column, cannot process")
            return pd.DataFrame()
        
        # Convert to datetime if needed
        if not pd.api.types.is_datetime64_any_dtype(df['filing_date']):
            df['filing_date'] = pd.to_datetime(df['filing_date'], errors='coerce')
        
        # Drop rows with NaN filing_date
        before_count = len(df)
        df = df.dropna(subset=['filing_date'])
        after_count = len(df)
        
        if before_count > after_count:
            logger.warning(
                f"{ticker}: Dropped {before_count - after_count} rows with missing filing_date"
            )
        
        if df.empty:
            return df
        
        # Sort by filing_date (newest first for consistency with FundamentalEngine)
        df = df.sort_values('filing_date', ascending=False).reset_index(drop=True)
        
        logger.debug(f"{ticker}: Standardized {len(df)} fundamental records")
        
        return df
    
    def _calculate_growth_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate period-over-period growth metrics.
        
        YoY Growth = (Value_t / Value_t-4) - 1
        (4 quarters back = 1 year for quarterly data)
        
        Args:
            df: Income statement dataframe
            
        Returns:
            Dataframe with growth columns added
        """
        # Ensure fiscal_date is datetime for sorting
        if 'fiscal_date' in df.columns:
            if not pd.api.types.is_datetime64_any_dtype(df['fiscal_date']):
                df['fiscal_date'] = pd.to_datetime(df['fiscal_date'], errors='coerce')
        
        # Sort by fiscal_date for proper time-series calculations
        df = df.sort_values('fiscal_date', ascending=True)
        
        # Calculate YoY growth for key metrics
        growth_metrics = {
            'revenue': 'revenue_growth_yoy',
            'netIncome': 'net_income_growth_yoy',
            'eps': 'eps_growth_yoy'
        }
        
        for base_col, growth_col in growth_metrics.items():
            if base_col in df.columns:
                # YoY: compare to 4 quarters ago
                df[growth_col] = df[base_col].pct_change(periods=4, fill_method=None) * 100
            else:
                df[growth_col] = np.nan
        
        # NEW MINERVINI ACCELERATION FEATURES
        # Acceleration = Change in growth rate (current quarter vs previous quarter)
        # Example: If Q1 growth was 10% and Q2 is 30%, acceleration = +20
        
        if 'eps_growth_yoy' in df.columns:
            df['eps_accel'] = df['eps_growth_yoy'].diff(periods=1)
        else:
            df['eps_accel'] = np.nan
        
        if 'revenue_growth_yoy' in df.columns:
            df['revenue_accel'] = df['revenue_growth_yoy'].diff(periods=1)
        else:
            df['revenue_accel'] = np.nan
        
        # NEW MINERVINI QUALITY CHECK - Inventory vs Sales Spread
        # Positive value = Red flag (inventory growing faster than sales)
        # Negative value = Healthy (sales outpacing inventory growth)
        if 'inventory' in df.columns:
            df['inventory_growth_yoy'] = df['inventory'].pct_change(periods=4, fill_method=None) * 100
            
            if 'revenue_growth_yoy' in df.columns:
                df['inventory_vs_sales_spread'] = df['inventory_growth_yoy'] - df['revenue_growth_yoy']
            else:
                df['inventory_vs_sales_spread'] = np.nan
        else:
            df['inventory_growth_yoy'] = np.nan
            df['inventory_vs_sales_spread'] = np.nan
        
        # Sort back to original order (newest first)
        df = df.sort_values('filing_date', ascending=False)
        
        return df
    
    def _merge_statements(
        self, 
        income_df: pd.DataFrame, 
        balance_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Merge income statement and balance sheet on fiscal_date and filing_date.
        
        Args:
            income_df: Processed income statement
            balance_df: Balance sheet dataframe
            
        Returns:
            Merged dataframe with both statement types
        """
        if income_df.empty and balance_df.empty:
            return pd.DataFrame()
        
        if income_df.empty:
            return balance_df
        
        if balance_df.empty:
            return income_df
        
        # Determine common columns to merge on (robust to missing columns)
        preferred_merge_cols = ['ticker', 'fiscal_date', 'filing_date', 'fiscal_period', 'fiscal_year']
        common_cols = [col for col in preferred_merge_cols 
                      if col in income_df.columns and col in balance_df.columns]
        
        if not common_cols:
            # Fallback: if no common columns, just concatenate
            logger.warning("No common merge columns found, concatenating statements")
            merged = pd.concat([income_df, balance_df], axis=0, ignore_index=True)
        else:
            # Merge on common columns
            merged = pd.merge(
                income_df,
                balance_df,
                on=common_cols,
                how='outer',
                suffixes=('_income', '_balance')
            )
        
        # Sort by filing_date if it exists
        if 'filing_date' in merged.columns:
            merged = merged.sort_values('filing_date', ascending=False)
        
        # Clean up duplicate columns: Combine _income and _balance versions
        # Strategy: For each base column name, coalesce _income and _balance values
        # (revenue from _income, totalAssets from _balance, etc.)
        
        # Find all columns with suffixes
        income_cols = [col for col in merged.columns if col.endswith('_income')]
        balance_cols = [col for col in merged.columns if col.endswith('_balance')]
        
        # Get base names
        income_bases = {col.replace('_income', '') for col in income_cols}
        balance_bases = {col.replace('_balance', '') for col in balance_cols}
        
        # Find columns that have both _income and _balance versions
        duplicate_bases = income_bases & balance_bases
        
        # Combine them: use fillna to merge (income statement data fills balance sheet NaN and vice versa)
        for base in duplicate_bases:
            income_col = f'{base}_income'
            balance_col = f'{base}_balance'
            
            if income_col in merged.columns and balance_col in merged.columns:
                # Combine: take non-null values from either column
                merged[base] = merged[income_col].fillna(merged[balance_col])
                # Drop the suffixed versions
                merged = merged.drop(columns=[income_col, balance_col])
                logger.debug(f"Combined {income_col} and {balance_col} into {base}")
        
        # Rename remaining _income columns (exist only in income statement)
        rename_income = {col: col.replace('_income', '') for col in merged.columns if col.endswith('_income')}
        if rename_income:
            merged = merged.rename(columns=rename_income)
            logger.debug(f"Renamed {len(rename_income)} income-only columns")
        
        # Rename remaining _balance columns (exist only in balance sheet)
        rename_balance = {col: col.replace('_balance', '') for col in merged.columns if col.endswith('_balance')}
        if rename_balance:
            merged = merged.rename(columns=rename_balance)
            logger.debug(f"Renamed {len(rename_balance)} balance-only columns")
        
        return merged
    
    def _calculate_safety_ratios(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate fundamental safety ratios.
        
        Ratios:
        - debt_to_equity: totalDebt / totalEquity
        - current_ratio: totalCurrentAssets / totalCurrentLiabilities
        - quick_ratio: (totalCurrentAssets - inventory) / totalCurrentLiabilities
        
        Args:
            df: Merged fundamental dataframe
            
        Returns:
            Dataframe with ratio columns added
        """
        # Debt to Equity
        if 'totalDebt' in df.columns and 'totalEquity' in df.columns:
            df['debt_to_equity'] = np.where(
                df['totalEquity'] != 0,
                df['totalDebt'] / df['totalEquity'],
                np.nan
            )
        else:
            df['debt_to_equity'] = np.nan
        
        # Current Ratio - FMP uses totalCurrentAssets and totalCurrentLiabilities
        current_assets_col = 'totalCurrentAssets' if 'totalCurrentAssets' in df.columns else 'currentAssets'
        current_liab_col = 'totalCurrentLiabilities' if 'totalCurrentLiabilities' in df.columns else 'currentLiabilities'
        
        if current_assets_col in df.columns and current_liab_col in df.columns:
            df['current_ratio'] = np.where(
                df[current_liab_col] != 0,
                df[current_assets_col] / df[current_liab_col],
                np.nan
            )
        else:
            df['current_ratio'] = np.nan
        
        # Quick Ratio
        if all(col in df.columns for col in [current_assets_col, 'inventory', current_liab_col]):
            df['quick_ratio'] = np.where(
                df[current_liab_col] != 0,
                (df[current_assets_col] - df['inventory']) / df[current_liab_col],
                np.nan
            )
        else:
            df['quick_ratio'] = np.nan
        
        # Defragment DataFrame after adding multiple columns
        return df.copy()
    
    def _calculate_operating_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate operating performance metrics.
        
        Metrics:
        - gross_margin: grossProfit / revenue
        - operating_margin: operatingIncome / revenue
        - roe: netIncome / totalEquity (Return on Equity)
        - roa: netIncome / totalAssets (Return on Assets)
        
        Args:
            df: Merged fundamental dataframe
            
        Returns:
            Dataframe with operating metric columns added
        """
        # Gross Margin
        if 'grossProfit' in df.columns and 'revenue' in df.columns:
            df['gross_margin'] = np.where(
                df['revenue'] != 0,
                (df['grossProfit'] / df['revenue']) * 100,
                np.nan
            )
        else:
            df['gross_margin'] = np.nan
        
        # Operating Margin
        if 'operatingIncome' in df.columns and 'revenue' in df.columns:
            df['operating_margin'] = np.where(
                df['revenue'] != 0,
                (df['operatingIncome'] / df['revenue']) * 100,
                np.nan
            )
        else:
            df['operating_margin'] = np.nan
        
        # ROE (Return on Equity)
        if 'netIncome' in df.columns and 'totalEquity' in df.columns:
            df['roe'] = np.where(
                df['totalEquity'] != 0,
                (df['netIncome'] / df['totalEquity']) * 100,
                np.nan
            )
        else:
            df['roe'] = np.nan
        
        # ROA (Return on Assets)
        if 'netIncome' in df.columns and 'totalAssets' in df.columns:
            df['roa'] = np.where(
                df['totalAssets'] != 0,
                (df['netIncome'] / df['totalAssets']) * 100,
                np.nan
            )
        else:
            df['roa'] = np.nan
        
        # Defragment DataFrame after adding multiple columns
        return df.copy()
    
    def get_processed_fundamentals_summary(self, df: pd.DataFrame) -> Dict:
        """
        Get summary statistics of processed fundamentals.
        
        Args:
            df: Processed fundamental dataframe
            
        Returns:
            Dictionary with summary stats
        """
        if df.empty:
            return {
                'total_periods': 0,
                'date_range': None,
                'has_growth_metrics': False,
                'has_safety_ratios': False,
                'has_operating_metrics': False
            }
        
        growth_cols = ['revenue_growth_yoy', 'eps_growth_yoy', 'net_income_growth_yoy']
        safety_cols = ['debt_to_equity', 'current_ratio', 'quick_ratio']
        operating_cols = ['gross_margin', 'operating_margin', 'roe', 'roa']
        
        return {
            'total_periods': len(df),
            'date_range': (df['filing_date'].min(), df['filing_date'].max()),
            'has_growth_metrics': any(col in df.columns for col in growth_cols),
            'has_safety_ratios': any(col in df.columns for col in safety_cols),
            'has_operating_metrics': any(col in df.columns for col in operating_cols),
            'columns': df.columns.tolist()
        }
