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
        
        # Step 2: Separate income, balance sheet, and cash flow
        income_df = df[df['statement_type'] == 'income'].copy()
        balance_df = df[df['statement_type'] == 'balance_sheet'].copy()
        cash_flow_df = df[df['statement_type'] == 'cash_flow'].copy()
        
        # Step 3: Calculate growth metrics (income statement)
        if not income_df.empty:
            income_df = self._calculate_growth_metrics(income_df)
        
        # Step 4: Calculate safety ratios (balance sheet + income)
        combined_df = self._merge_statements(income_df, balance_df, cash_flow_df)
        
        if not combined_df.empty:
            combined_df = self._calculate_safety_ratios(combined_df)
            combined_df = self._calculate_operating_metrics(combined_df)
            
            # CRITICAL FIX: Remove duplicate fiscal periods (from outer joins)
            # Deduplicate on fiscal_date, keeping first (most complete from merge)
            if 'fiscal_date' in combined_df.columns:
                combined_df = combined_df.drop_duplicates(subset=['fiscal_date'], keep='first')
        
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
            logger.debug(
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
                prior_4q = df[base_col].shift(4)
                
                # Use (Current - Prior) / ABS(Prior) to correctly handle negative bases
                df[growth_col] = np.where(
                    prior_4q.abs() > 1e-6,
                    (df[base_col] - prior_4q) / prior_4q.abs() * 100,
                    np.nan
                )
                # Replace inf with nan (inf growth from division by zero is not meaningful)
                df[growth_col] = df[growth_col].replace([np.inf, -np.inf], np.nan)
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
        
        # LONG-TERM TREND FEATURES - "Proven Winner" Check
        # These help distinguish market leaders from flash-in-the-pan stocks
        
        # 3-Year Revenue CAGR (Compound Annual Growth Rate)
        # CAGR = ((Value_current / Value_3y_ago) ^ (1/3)) - 1
        # For quarterly data: 12 quarters = 3 years
        if 'revenue' in df.columns:
            revenue_3y_ago = df['revenue'].shift(12)
            # Use np.cbrt on (Current - Prior) / ABS(Prior) + 1 to properly handle negative revenue
            ratio = (df['revenue'] - revenue_3y_ago) / revenue_3y_ago.abs() + 1
            df['revenue_cagr_3y'] = np.where(
                revenue_3y_ago.abs() > 1e-6,
                (np.cbrt(ratio) - 1) * 100,
                np.nan
            )
        else:
            df['revenue_cagr_3y'] = np.nan
        
        # EPS Stability Score - Standard Deviation of EPS growth over 8 quarters
        # Lower score = More stable/consistent growth (better for SEPA)
        # Higher score = Volatile/unpredictable growth (risky)
        if 'eps_growth_yoy' in df.columns:
            df['eps_stability_score'] = df['eps_growth_yoy'].rolling(
                window=8, 
                min_periods=4  # Allow calculation with at least 4 quarters
            ).std()
        else:
            df['eps_stability_score'] = np.nan
        
        # NOTE: Inventory metrics moved to _calculate_operating_metrics()
        # because inventory is a balance sheet item, not income statement
        
        # Sort back to original order (newest first)
        df = df.sort_values('filing_date', ascending=False)
        
        return df
    
    def _merge_statements(
        self, 
        income_df: pd.DataFrame, 
        balance_df: pd.DataFrame,
        cash_flow_df: pd.DataFrame = None
    ) -> pd.DataFrame:
        """
        Merge income statement, balance sheet, and cash flow on fiscal_date and filing_date.
        
        Args:
            income_df: Processed income statement
            balance_df: Balance sheet dataframe
            cash_flow_df: Cash flow statement dataframe (optional)
            
        Returns:
            Merged dataframe with all statement types
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
            
            # CRITICAL FIX: Also merge cash_flow if it exists
            if cash_flow_df is not None and not cash_flow_df.empty:
                # Find common columns between merged result and cash_flow
                cf_common_cols = [col for col in common_cols if col in cash_flow_df.columns]
                if cf_common_cols:
                    merged = pd.merge(
                        merged,
                        cash_flow_df,
                        on=cf_common_cols,
                        how='outer',
                        suffixes=('', '_cashflow')
                    )
                    logger.debug(f"Merged cash flow statement with {len(cf_common_cols)} common columns")
                else:
                    logger.warning("Cash flow has no common merge columns, skipping")
        
        # Sort by filing_date if it exists
        if 'filing_date' in merged.columns:
            merged = merged.sort_values('filing_date', ascending=False)
        
        # CRITICAL: Reset index to prevent duplicate label errors in fillna
        merged = merged.reset_index(drop=True)
        
        # Clean up duplicate columns: Combine _income and _balance versions
        # Strategy: For each base column name, coalesce _income and _balance values
        # (revenue from _income, totalAssets from _balance, etc.)
        
        # Find all columns with suffixes
        income_cols = [col for col in merged.columns if col.endswith('_income')]
        balance_cols = [col for col in merged.columns if col.endswith('_balance')]
        cashflow_cols = [col for col in merged.columns if col.endswith('_cashflow')]
        
        # Get base names
        income_bases = {col.replace('_income', '') for col in income_cols}
        balance_bases = {col.replace('_balance', '') for col in balance_cols}
        cashflow_bases = {col.replace('_cashflow', '') for col in cashflow_cols}
        
        # Find ALL columns that have ANY suffix version (not just income+balance)
        all_suffixed_bases = income_bases | balance_bases | cashflow_bases
        
        # Combine them: use fillna to merge (income statement data fills balance sheet NaN and vice versa)
        # CRITICAL: Also handle _cashflow suffix since columns like operatingCashFlow exist in multiple statements
        for base in all_suffixed_bases:
            income_col = f'{base}_income'
            balance_col = f'{base}_balance'
            cashflow_col = f'{base}_cashflow'

            # Collect all versions that exist
            versions_to_combine = []
            if income_col in merged.columns:
                versions_to_combine.append(income_col)
            if balance_col in merged.columns:
                versions_to_combine.append(balance_col)
            if cashflow_col in merged.columns:
                versions_to_combine.append(cashflow_col)

            # If we have multiple versions, combine them
            if len(versions_to_combine) >= 2:
                # CRITICAL: Check if base column already exists (from cash flow without suffix)
                # If it does, we need to include it in the combination
                if base in merged.columns:
                    # Base column exists - combine all versions INCLUDING the base
                    combined_data = merged[base]
                    for ver in versions_to_combine:
                        combined_data = combined_data.fillna(merged[ver])
                    merged[base] = combined_data
                else:
                    # Base doesn't exist - create it from suffixed versions
                    merged[base] = merged[versions_to_combine[0]]
                    for ver in versions_to_combine[1:]:
                        merged[base] = merged[base].fillna(merged[ver])

                # Drop all suffixed versions
                merged = merged.drop(columns=versions_to_combine)
                logger.debug(f"Combined {versions_to_combine} into {base}")
        
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

        # Rename remaining _cashflow columns (exist only in cash flow statement)
        rename_cashflow = {col: col.replace('_cashflow', '') for col in merged.columns if col.endswith('_cashflow')}
        if rename_cashflow:
            merged = merged.rename(columns=rename_cashflow)
            logger.debug(f"Renamed {len(rename_cashflow)} cash flow-only columns")

        # NEW: Standardize cash flow column names from FMP API to internal standard
        from src.fundamental_column_mapping import standardize_cash_flow_columns
        merged = standardize_cash_flow_columns(merged)
        logger.debug("Standardized cash flow column names")
        
        # CRITICAL FIX: Remove duplicate columns (keep first occurrence)
        # This happens when columns like 'operatingCashFlow' exist in multiple statements
        if merged.columns.duplicated().any():
            dup_cols = merged.columns[merged.columns.duplicated()].unique().tolist()
            logger.debug(f"Removing duplicate columns: {dup_cols}")
            merged = merged.loc[:, ~merged.columns.duplicated(keep='first')]
        
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
        # CRITICAL: Reset index to prevent duplicate label errors
        df = df.reset_index(drop=True)
        
        # Prepare new columns as a dict to avoid fragmentation
        new_cols = {}

        # Debt to Equity
        if 'totalDebt' in df.columns and 'totalEquity' in df.columns:
            new_cols['debt_to_equity'] = np.where(
                df['totalEquity'] != 0,
                df['totalDebt'] / df['totalEquity'],
                np.nan
            )
        else:
            new_cols['debt_to_equity'] = np.nan

        # Current Ratio - FMP uses totalCurrentAssets and totalCurrentLiabilities
        current_assets_col = 'totalCurrentAssets' if 'totalCurrentAssets' in df.columns else 'currentAssets'
        current_liab_col = 'totalCurrentLiabilities' if 'totalCurrentLiabilities' in df.columns else 'currentLiabilities'

        if current_assets_col in df.columns and current_liab_col in df.columns:
            new_cols['current_ratio'] = np.where(
                df[current_liab_col] != 0,
                df[current_assets_col] / df[current_liab_col],
                np.nan
            )
        else:
            new_cols['current_ratio'] = np.nan

        # Quick Ratio
        if all(col in df.columns for col in [current_assets_col, 'inventory', current_liab_col]):
            new_cols['quick_ratio'] = np.where(
                df[current_liab_col] != 0,
                (df[current_assets_col] - df['inventory']) / df[current_liab_col],
                np.nan
            )
        else:
            new_cols['quick_ratio'] = np.nan

        # Add all columns at once to avoid fragmentation
        return pd.concat([df, pd.DataFrame(new_cols, index=df.index)], axis=1)
    
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
        # CRITICAL: Reset index to prevent duplicate label errors in numpy/pandas operations
        df = df.reset_index(drop=True)
        
        # Prepare new columns as a dict to avoid fragmentation
        new_cols = {}

        # Gross Margin
        if 'grossProfit' in df.columns and 'revenue' in df.columns:
            new_cols['gross_margin'] = np.where(
                df['revenue'] != 0,
                (df['grossProfit'] / df['revenue']) * 100,
                np.nan
            )
        else:
            new_cols['gross_margin'] = np.nan

        # Operating Margin
        if 'operatingIncome' in df.columns and 'revenue' in df.columns:
            new_cols['operating_margin'] = np.where(
                df['revenue'] != 0,
                (df['operatingIncome'] / df['revenue']) * 100,
                np.nan
            )
        else:
            new_cols['operating_margin'] = np.nan

        # ROE (Return on Equity)
        if 'netIncome' in df.columns and 'totalEquity' in df.columns:
            new_cols['roe'] = np.where(
                df['totalEquity'] != 0,
                (df['netIncome'] / df['totalEquity']) * 100,
                np.nan
            )
        else:
            new_cols['roe'] = np.nan

        # ROA (Return on Assets)
        if 'netIncome' in df.columns and 'totalAssets' in df.columns:
            new_cols['roa'] = np.where(
                df['totalAssets'] != 0,
                (df['netIncome'] / df['totalAssets']) * 100,
                np.nan
            )
        else:
            new_cols['roa'] = np.nan

        # Net Margin (SEPA requirement): netIncome / revenue
        if 'netIncome' in df.columns and 'revenue' in df.columns:
            new_cols['net_margin'] = np.where(
                df['revenue'] != 0,
                (df['netIncome'] / df['revenue']) * 100,
                np.nan
            )
        else:
            new_cols['net_margin'] = np.nan

        # NEW MINERVINI QUALITY CHECK - Inventory vs Sales Spread
        # Positive value = Red flag (inventory growing faster than sales)
        # Negative value = Healthy (sales outpacing inventory growth)
        # NOTE: Moved here from _calculate_growth_metrics because inventory is a balance sheet item
        if 'inventory' in df.columns and 'fiscal_date' in df.columns:
            # Sort by fiscal_date for proper time-series calculations
            df_sorted = df.sort_values('fiscal_date', ascending=True)
            inventory_growth = df_sorted['inventory'].pct_change(periods=4, fill_method=None) * 100
            # Replace inf with nan (inf growth rates from division by zero are not meaningful)
            inventory_growth = inventory_growth.replace([np.inf, -np.inf], np.nan)

            new_cols['inventory_growth_yoy'] = inventory_growth.values

            if 'revenue_growth_yoy' in df.columns:
                # Use sorted df to ensure alignment with inventory_growth
                # Replace inf with nan to avoid invalid subtract warnings (inf - inf = nan)
                revenue_growth_clean = df_sorted['revenue_growth_yoy'].replace([np.inf, -np.inf], np.nan)
                new_cols['inventory_vs_sales_spread'] = new_cols['inventory_growth_yoy'] - revenue_growth_clean.values
            else:
                new_cols['inventory_vs_sales_spread'] = np.nan
        else:
            new_cols['inventory_growth_yoy'] = np.nan
            new_cols['inventory_vs_sales_spread'] = np.nan

        # NEW ADDITIONAL FUNDAMENTAL FEATURES
        # Earnings Quality Score - Operating cash flow relative to reported earnings
        # Higher is better (>1 means cash flow exceeds accounting earnings)
        if 'operatingCashFlow' in df.columns and 'netIncome' in df.columns:
            new_cols['earnings_quality_score'] = np.where(
                df['netIncome'] != 0,
                df['operatingCashFlow'] / df['netIncome'],
                np.nan
            )
        else:
            new_cols['earnings_quality_score'] = np.nan

        # FCF Margin - Free cash flow as % of revenue
        # Measures real cash-generating ability
        if 'freeCashFlow' in df.columns and 'revenue' in df.columns:
            new_cols['fcf_margin'] = np.where(
                df['revenue'] != 0,
                (df['freeCashFlow'] / df['revenue']) * 100,
                np.nan
            )
        else:
            new_cols['fcf_margin'] = np.nan

        # Gross Margin Trend - Measures margin expansion/contraction
        # Formula: Current_Gross_Margin - Avg_Gross_Margin_4Q (trailing 4 quarters)
        # Positive = Expanding margins (good), Negative = Contracting margins (bad)
        # IMPORTANT: gross_margin is in new_cols dict, not yet added to df
        if 'gross_margin' in new_cols and 'fiscal_date' in df.columns:
            # Check if gross_margin is an array (not just a scalar nan)
            gross_margin_values = new_cols['gross_margin']
            if not (isinstance(gross_margin_values, float) and np.isnan(gross_margin_values)):
                # CRITICAL: Must handle both duplicate fiscal_dates AND preserve original row order
                # Strategy: Sort for calculation, then map back using original index

                # Reset index to integer positions for clean sorting
                df_reset = df.reset_index(drop=True).copy()

                # Add gross_margin temporarily for calculation
                df_reset['gross_margin'] = gross_margin_values

                # Sort by fiscal_date for proper time-series calculation
                df_sorted = df_reset.sort_values('fiscal_date', ascending=True).copy()

                # Calculate 4-quarter rolling average (excluding current quarter)
                # shift(1) excludes current value, then take rolling mean of 4 quarters
                gross_margin_4q_avg = df_sorted['gross_margin'].shift(1).rolling(
                    window=4,
                    min_periods=2  # Allow calculation with at least 2 historical quarters
                ).mean()

                # Trend = Current - Historical Average
                df_sorted['gross_margin_trend'] = df_sorted['gross_margin'] - gross_margin_4q_avg

                # Sort back to the original dataframe's order (by original reset index)
                df_sorted = df_sorted.sort_index()

                # Extract the calculated trend values in original order
                new_cols['gross_margin_trend'] = df_sorted['gross_margin_trend'].values
            else:
                new_cols['gross_margin_trend'] = np.nan
        else:
            new_cols['gross_margin_trend'] = np.nan

        # Reset index before concat to prevent duplicate label errors
        df = df.reset_index(drop=True)
        
        # Add all columns at once to avoid fragmentation
        return pd.concat([df, pd.DataFrame(new_cols, index=df.index)], axis=1)
    
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
