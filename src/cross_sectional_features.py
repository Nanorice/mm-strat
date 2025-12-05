"""
Cross-Sectional Features Module

Calculates features that require data from all tickers on each date:
- RS_Universe_Rank: Percentile rank of RS across all tickers per date
- Sector_Momentum: Mean RS of all stocks in same sector per date
- Industry_Momentum: Mean RS of all stocks in same industry per date

These features are calculated AFTER individual ticker processing via post-processing.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def add_cross_sectional_features(
    dataset: pd.DataFrame,
    company_profile_path: str = 'data/company_info/company_profiles.parquet',
    rs_column: str = 'RS'
) -> pd.DataFrame:
    """
    Add cross-sectional features to Dataset A.

    This function is called AFTER concatenating all individual ticker DataFrames.
    It adds features that require comparing a ticker against all other tickers on each date.

    Args:
        dataset: Concatenated Dataset A with columns ['ticker', 'Date', 'RS', ...]
        company_profile_path: Path to company profiles parquet with sector/industry mapping
        rs_column: Name of Relative Strength column (default: 'RS')

    Returns:
        Dataset with 3 new columns:
        - RS_Universe_Rank: Percentile rank (0-1) of RS across all tickers per date
        - Sector_Momentum: Mean RS of sector on each date
        - Industry_Momentum: Mean RS of industry on each date

    Example:
        >>> dataset_a = pd.concat(individual_ticker_results)
        >>> dataset_a = add_cross_sectional_features(dataset_a)
        >>> print(dataset_a[['ticker', 'Date', 'RS', 'RS_Universe_Rank', 'Sector_Momentum']].head())
    """
    logger.info("Adding cross-sectional features...")

    # Validate inputs
    if dataset.empty:
        logger.warning("Empty dataset provided, returning as-is")
        return dataset

    # Handle both 'date' and 'Date' column names (build_dataset_a uses lowercase 'date')
    date_col = 'date' if 'date' in dataset.columns else 'Date'
    if date_col not in dataset.columns:
        raise ValueError(f"Dataset missing required date column (expected 'date' or 'Date')")

    required_cols = ['ticker', rs_column]
    missing_cols = [col for col in required_cols if col not in dataset.columns]
    if missing_cols:
        raise ValueError(f"Dataset missing required columns: {missing_cols}")
    
    # Load company profiles (sector/industry mapping)
    logger.info(f"Loading company profiles from {company_profile_path}")
    try:
        company_profiles = pd.read_parquet(company_profile_path)
        logger.info(f"Loaded {len(company_profiles)} company profiles")
    except Exception as e:
        logger.error(f"Failed to load company profiles: {e}")
        raise
    
    # Verify company_profiles has required columns
    required_profile_cols = ['sector_id', 'industry_id']
    missing_profile_cols = [col for col in required_profile_cols if col not in company_profiles.columns]
    if missing_profile_cols:
        raise ValueError(f"Company profiles missing required columns: {missing_profile_cols}")
    
    # Merge sector/industry info into dataset
    # company_profiles is indexed by ticker
    logger.info("Merging sector/industry information...")
    dataset = dataset.merge(
        company_profiles[['sector_id', 'industry_id']],
        left_on='ticker',
        right_index=True,
        how='left'
    )
    
    # Check for tickers without sector/industry mapping
    unmapped_count = dataset['sector_id'].isna().sum()
    if unmapped_count > 0:
        unmapped_tickers = dataset[dataset['sector_id'].isna()]['ticker'].unique()
        logger.warning(f"{unmapped_count} rows from {len(unmapped_tickers)} tickers lack sector mapping")
        logger.debug(f"Unmapped tickers: {unmapped_tickers[:10]}")
    
    # Calculate cross-sectional features grouped by date
    logger.info("Calculating cross-sectional features by date...")

    # Feature 1: RS_Universe_Rank (percentile rank across all tickers per date)
    logger.info("  - Calculating RS_Universe_Rank...")
    dataset['RS_Universe_Rank'] = dataset.groupby(date_col)[rs_column].rank(pct=True)

    # Feature 2: Sector_Momentum (mean RS per sector per date)
    logger.info("  - Calculating Sector_Momentum...")
    sector_momentum = dataset.groupby([date_col, 'sector_id'])[rs_column].transform('mean')
    dataset['Sector_Momentum'] = sector_momentum

    # Feature 3: Industry_Momentum (mean RS per industry per date)
    logger.info("  - Calculating Industry_Momentum...")
    industry_momentum = dataset.groupby([date_col, 'industry_id'])[rs_column].transform('mean')
    dataset['Industry_Momentum'] = industry_momentum

    # Handle NaN values for unmapped tickers
    if unmapped_count > 0:
        # Fill NaN sector/industry momentum with universe mean
        universe_mean = dataset.groupby(date_col)[rs_column].transform('mean')
        dataset['Sector_Momentum'].fillna(universe_mean, inplace=True)
        dataset['Industry_Momentum'].fillna(universe_mean, inplace=True)
        logger.info(f"  - Filled NaN momentum values with universe mean for unmapped tickers")
    
    # Clean up: Drop temporary sector_id and industry_id columns
    # (keep them if user wants them for analysis)
    # dataset = dataset.drop(columns=['sector_id', 'industry_id'])
    
    # Summary statistics
    logger.info("\nCross-sectional features summary:")
    logger.info(f"  RS_Universe_Rank: {dataset['RS_Universe_Rank'].notna().sum()}/{len(dataset)} valid")
    logger.info(f"  Sector_Momentum: {dataset['Sector_Momentum'].notna().sum()}/{len(dataset)} valid")
    logger.info(f"  Industry_Momentum: {dataset['Industry_Momentum'].notna().sum()}/{len(dataset)} valid")
    
    # Validation: Check for extreme NaN counts
    for col in ['RS_Universe_Rank', 'Sector_Momentum', 'Industry_Momentum']:
        nan_pct = dataset[col].isna().sum() / len(dataset) * 100
        if nan_pct > 10:
            logger.warning(f"{col} has {nan_pct:.1f}% NaN values")
    
    logger.info("Cross-sectional features added successfully!")
    return dataset


def get_cross_sectional_summary(dataset: pd.DataFrame) -> dict:
    """
    Get summary statistics of cross-sectional features.

    Args:
        dataset: Dataset with cross-sectional features

    Returns:
        Dictionary with summary stats
    """
    if 'RS_Universe_Rank' not in dataset.columns:
        return {'has_cross_sectional': False}

    # Handle both 'date' and 'Date' column names
    date_col = 'date' if 'date' in dataset.columns else 'Date'

    return {
        'has_cross_sectional': True,
        'total_dates': dataset[date_col].nunique(),
        'total_tickers': dataset['ticker'].nunique(),
        'avg_tickers_per_date': len(dataset) / dataset[date_col].nunique(),
        'rs_universe_rank_range': (
            dataset['RS_Universe_Rank'].min(),
            dataset['RS_Universe_Rank'].max()
        ),
        'sector_momentum_range': (
            dataset['Sector_Momentum'].min(),
            dataset['Sector_Momentum'].max()
        ),
        'industry_momentum_range': (
            dataset['Industry_Momentum'].min(),
            dataset['Industry_Momentum'].max()
        ),
        'unique_sectors': dataset['sector_id'].nunique() if 'sector_id' in dataset.columns else None,
        'unique_industries': dataset['industry_id'].nunique() if 'industry_id' in dataset.columns else None
    }
