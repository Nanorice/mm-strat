"""
Cross-Sectional Features Module

Calculates features that require data from all tickers on each date:
- RS_Universe_Rank: Percentile rank of rs_rating across all tickers per date
- RS_Sector_Rank: Percentile rank of rs_rating within sector per date
- RS_Industry_Rank: Percentile rank of rs_rating within industry per date
- RS_vs_Sector: Z-score of rs_rating vs sector mean
- RS_vs_Industry: Z-score of rs_rating vs industry mean
- Sector_Momentum: Mean rs_rating of all stocks in same sector per date
- Industry_Momentum: Mean rs_rating of all stocks in same industry per date

These features are calculated AFTER individual ticker processing via post-processing.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Minimum group size for meaningful within-group rankings
MIN_GROUP_SIZE = 3


def add_cross_sectional_features(
    dataset: pd.DataFrame,
    company_profile_path: str = 'data/company_info/company_profiles.parquet',
    rs_column: str = 'rs_rating'
) -> pd.DataFrame:
    """
    Add cross-sectional features to dataset.

    This function is called AFTER concatenating all individual ticker DataFrames.
    It adds features that require comparing a ticker against all other tickers on each date.

    Args:
        dataset: Concatenated dataset with columns ['ticker', 'date', 'rs_rating', ...]
                 May already have 'sector_id'/'industry_id' from add_company_features()
        company_profile_path: Path to company profiles parquet (fallback if sector_id missing)
        rs_column: Name of Relative Strength column (default: 'rs_rating')

    Returns:
        Dataset with cross-sectional features added:
        - RS_Universe_Rank: Percentile rank (0-1) of RS across all tickers per date
        - RS_Sector_Rank: Percentile rank (0-1) of RS within sector per date
        - RS_Industry_Rank: Percentile rank (0-1) of RS within industry per date
        - RS_vs_Sector: Z-score of RS relative to sector mean
        - RS_vs_Industry: Z-score of RS relative to industry mean
        - Sector_Momentum: Mean RS of sector on each date
        - Industry_Momentum: Mean RS of industry on each date
    """
    logger.info("Adding cross-sectional features...")

    if dataset.empty:
        logger.warning("Empty dataset provided, returning as-is")
        return dataset

    # Handle both 'date' and 'Date' column names
    date_col = 'date' if 'date' in dataset.columns else 'Date'
    if date_col not in dataset.columns:
        raise ValueError("Dataset missing required date column (expected 'date' or 'Date')")

    required_cols = ['ticker', rs_column]
    missing_cols = [col for col in required_cols if col not in dataset.columns]
    if missing_cols:
        raise ValueError(f"Dataset missing required columns: {missing_cols}")

    # Check if sector_id/industry_id already exist (from add_company_features)
    has_sector_id = 'sector_id' in dataset.columns
    has_industry_id = 'industry_id' in dataset.columns

    if has_sector_id and has_industry_id:
        logger.info("  Using existing sector_id/industry_id from dataset")
    else:
        # Load from company profiles as fallback
        logger.info(f"  Loading sector/industry from {company_profile_path}")
        try:
            company_profiles = pd.read_parquet(company_profile_path)
            logger.info(f"  Loaded {len(company_profiles)} company profiles")

            # Merge only missing columns
            cols_to_merge = []
            if not has_sector_id:
                cols_to_merge.append('sector_id')
            if not has_industry_id:
                cols_to_merge.append('industry_id')

            dataset = dataset.merge(
                company_profiles[cols_to_merge],
                left_on='ticker',
                right_index=True,
                how='left'
            )
        except Exception as e:
            logger.error(f"Failed to load company profiles: {e}")
            # Fill with -1 to allow function to continue
            if not has_sector_id:
                dataset['sector_id'] = -1
            if not has_industry_id:
                dataset['industry_id'] = -1

    # Check for unmapped tickers
    unmapped_count = (dataset['sector_id'].isna() | (dataset['sector_id'] == -1)).sum()
    if unmapped_count > 0:
        unmapped_tickers = dataset[
            dataset['sector_id'].isna() | (dataset['sector_id'] == -1)
        ]['ticker'].unique()
        logger.warning(f"{unmapped_count} rows from {len(unmapped_tickers)} tickers lack sector mapping")

    # Fill NaN sector/industry with -1 for groupby operations
    dataset['sector_id'] = dataset['sector_id'].fillna(-1).astype(int)
    dataset['industry_id'] = dataset['industry_id'].fillna(-1).astype(int)

    logger.info("  Calculating cross-sectional features by date...")

    # =========================================================================
    # UNIVERSE-LEVEL FEATURES
    # =========================================================================

    # Feature 1: RS_Universe_Rank (percentile rank across all tickers per date)
    dataset['RS_Universe_Rank'] = dataset.groupby(date_col)[rs_column].rank(pct=True)

    # =========================================================================
    # SECTOR-LEVEL FEATURES
    # =========================================================================

    # Feature 2: Sector_Momentum (mean RS per sector per date)
    dataset['Sector_Momentum'] = dataset.groupby([date_col, 'sector_id'])[rs_column].transform('mean')

    # Feature 3: RS_Sector_Rank (percentile rank within sector per date)
    # For small sectors (<MIN_GROUP_SIZE), use universe rank as fallback
    sector_counts = dataset.groupby([date_col, 'sector_id'])['ticker'].transform('count')

    dataset['RS_Sector_Rank'] = np.where(
        sector_counts >= MIN_GROUP_SIZE,
        dataset.groupby([date_col, 'sector_id'])[rs_column].rank(pct=True),
        dataset['RS_Universe_Rank']  # Fallback for small sectors
    )

    # Feature 4: RS_vs_Sector (Z-score relative to sector mean)
    sector_std = dataset.groupby([date_col, 'sector_id'])[rs_column].transform('std')
    sector_std = sector_std.replace(0, np.nan)  # Avoid division by zero

    dataset['RS_vs_Sector'] = np.where(
        (sector_counts >= MIN_GROUP_SIZE) & sector_std.notna(),
        (dataset[rs_column] - dataset['Sector_Momentum']) / sector_std,
        0.0  # Neutral for small/single-stock sectors
    )

    # =========================================================================
    # INDUSTRY-LEVEL FEATURES
    # =========================================================================

    # Feature 5: Industry_Momentum (mean RS per industry per date)
    dataset['Industry_Momentum'] = dataset.groupby([date_col, 'industry_id'])[rs_column].transform('mean')

    # Feature 6: RS_Industry_Rank (percentile rank within industry per date)
    industry_counts = dataset.groupby([date_col, 'industry_id'])['ticker'].transform('count')

    dataset['RS_Industry_Rank'] = np.where(
        industry_counts >= MIN_GROUP_SIZE,
        dataset.groupby([date_col, 'industry_id'])[rs_column].rank(pct=True),
        dataset['RS_Universe_Rank']  # Fallback for small industries
    )

    # Feature 7: RS_vs_Industry (Z-score relative to industry mean)
    industry_std = dataset.groupby([date_col, 'industry_id'])[rs_column].transform('std')
    industry_std = industry_std.replace(0, np.nan)

    dataset['RS_vs_Industry'] = np.where(
        (industry_counts >= MIN_GROUP_SIZE) & industry_std.notna(),
        (dataset[rs_column] - dataset['Industry_Momentum']) / industry_std,
        0.0  # Neutral for small/single-stock industries
    )

    # =========================================================================
    # HANDLE UNMAPPED TICKERS (sector_id == -1)
    # =========================================================================

    if unmapped_count > 0:
        universe_mean = dataset.groupby(date_col)[rs_column].transform('mean')
        mask = dataset['sector_id'] == -1

        dataset.loc[mask, 'Sector_Momentum'] = universe_mean[mask]
        dataset.loc[mask, 'Industry_Momentum'] = universe_mean[mask]
        dataset.loc[mask, 'RS_vs_Sector'] = 0.0
        dataset.loc[mask, 'RS_vs_Industry'] = 0.0

        logger.info(f"  Filled {unmapped_count} unmapped rows with universe defaults")

    # Clip extreme Z-scores to prevent outlier influence
    dataset['RS_vs_Sector'] = dataset['RS_vs_Sector'].clip(-4, 4)
    dataset['RS_vs_Industry'] = dataset['RS_vs_Industry'].clip(-4, 4)

    # Summary statistics
    cross_sectional_cols = [
        'RS_Universe_Rank', 'RS_Sector_Rank', 'RS_Industry_Rank',
        'RS_vs_Sector', 'RS_vs_Industry', 'Sector_Momentum', 'Industry_Momentum'
    ]
    logger.info("  Cross-sectional features summary:")
    for col in cross_sectional_cols:
        valid_count = dataset[col].notna().sum()
        logger.info(f"    {col}: {valid_count}/{len(dataset)} valid")

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

    summary = {
        'has_cross_sectional': True,
        'total_dates': dataset[date_col].nunique(),
        'total_tickers': dataset['ticker'].nunique(),
        'avg_tickers_per_date': len(dataset) / dataset[date_col].nunique(),
        'unique_sectors': dataset['sector_id'].nunique() if 'sector_id' in dataset.columns else None,
        'unique_industries': dataset['industry_id'].nunique() if 'industry_id' in dataset.columns else None,
    }

    # Add range stats for each cross-sectional feature
    cross_sectional_cols = [
        'RS_Universe_Rank', 'RS_Sector_Rank', 'RS_Industry_Rank',
        'RS_vs_Sector', 'RS_vs_Industry', 'Sector_Momentum', 'Industry_Momentum'
    ]

    for col in cross_sectional_cols:
        if col in dataset.columns:
            summary[f'{col}_range'] = (dataset[col].min(), dataset[col].max())
            summary[f'{col}_mean'] = dataset[col].mean()

    return summary
