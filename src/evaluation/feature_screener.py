"""
Feature Screener for Automated EDA (Quant-Standard Pipeline)
=============================================================

Screens features using multi-pillar evaluation framework:

KS-Only Pipeline (fast):
    1. Pre-filter: Remove raw/non-stationary columns
    2. KS discrimination test (Q1 vs Q4)
    3. Correlation removal (|r| >= 0.9)

Quant-Standard Pipeline (comprehensive):
    1. Distributional Health - Stationarity, kurtosis, missingness
    2. Predictive Power - IC, Mutual Information, decile monotonicity
    3. Temporal Stability - IC stability over time, PSI
    4. Interaction - Correlation clusters with intelligent pruning
    5. Composite scoring: 40% IC + 30% Stability + 30% KS
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.eda_utils import analyze_feature_separation
from src.feature_config import FEATURE_EXCLUSION_LIST, CATEGORICAL_FEATURES, LEAKAGE_FEATURES
from .feature_analyzer import FeatureAnalyzer

logger = logging.getLogger(__name__)


def target_encode_categorical(
    df: pd.DataFrame,
    categorical_col: str,
    target_col: str = 'return_pct',
    smoothing: float = 10.0,
    min_samples: int = 30
) -> pd.Series:
    """
    Apply target encoding to a categorical column.

    Replaces category IDs with the smoothed mean target value for that category.
    Uses Bayesian smoothing to handle categories with few samples.

    Formula: encoded = (n * category_mean + m * global_mean) / (n + m)
    Where n = samples in category, m = smoothing factor

    Args:
        df: DataFrame with categorical and target columns
        categorical_col: Name of categorical column (e.g., 'industry_id')
        target_col: Target variable for encoding (default: 'return_pct')
        smoothing: Bayesian smoothing factor (higher = more regularization)
        min_samples: Categories with fewer samples use global mean

    Returns:
        Series with encoded values (same index as input)
    """
    if categorical_col not in df.columns or target_col not in df.columns:
        logger.warning(f"Cannot target encode {categorical_col}: column not found")
        return pd.Series(index=df.index, dtype=float)

    # Global mean
    global_mean = df[target_col].mean()

    # Category statistics
    cat_stats = df.groupby(categorical_col)[target_col].agg(['mean', 'count'])

    # Bayesian smoothed encoding
    cat_stats['smoothed'] = (
        cat_stats['count'] * cat_stats['mean'] + smoothing * global_mean
    ) / (cat_stats['count'] + smoothing)

    # For categories with too few samples, use global mean
    cat_stats.loc[cat_stats['count'] < min_samples, 'smoothed'] = global_mean

    # Map back to original dataframe
    encoded = df[categorical_col].map(cat_stats['smoothed'])

    # Fill any unmapped values with global mean
    encoded = encoded.fillna(global_mean)

    logger.info(
        f"Target encoded {categorical_col}: {len(cat_stats)} categories, "
        f"global_mean={global_mean:.2f}%, smoothing={smoothing}"
    )

    return encoded


class FeatureScreener:
    """Automated feature screening using KS discrimination test."""

    @staticmethod
    def pre_filter_features(
        df: pd.DataFrame,
        candidate_features: Optional[List[str]] = None,
        exclusion_list: Optional[List[str]] = None
    ) -> Tuple[List[str], List[str]]:
        """
        Remove raw/non-stationary columns before statistical screening.

        Args:
            df: DataFrame with all columns
            candidate_features: Explicit list of candidates (if None, uses all numeric cols)
            exclusion_list: Columns to exclude (if None, uses FEATURE_EXCLUSION_LIST)

        Returns:
            Tuple of (filtered_features, excluded_features)
        """
        exclusion_list = exclusion_list or FEATURE_EXCLUSION_LIST
        exclusion_set = set(exclusion_list)

        if candidate_features is None:
            # Use all numeric columns
            numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
            candidate_features = numeric_cols

        filtered = [f for f in candidate_features if f not in exclusion_set and f in df.columns]
        excluded = [f for f in candidate_features if f in exclusion_set]

        logger.info(f"Pre-filter: {len(candidate_features)} candidates -> {len(filtered)} after removing {len(excluded)} raw/excluded columns")
        return filtered, excluded

    # Feature transform taxonomy: categorize features by appropriate treatment
    # Based on SEPA principles - preserving "Tier 0" (Super Performer) signals
    
    EXPLOSIVE_FEATURES = [
        # Volume metrics (power law distributions)
        'volume_acceleration', 'Dry_Up_Volume', 'Vol_Ratio', 'volume_ratio',
        # Growth rates (can be extreme positive or negative)
        'revenue_accel', 'eps_accel', 'revenue_growth_yoy', 'eps_growth_yoy',
        # Valuation ratios (can balloon to 500+)
        'pe_ratio', 'ps_ratio', 'pb_ratio',
        # MA distances - SEPA "Power Trend" signals (leaders run 200-300% above MA)
        'Price_vs_SMA_50', 'Price_vs_SMA_150', 'Price_vs_SMA_200',
        # Distance from 52W extremes - leadership proxy
        'Dist_From_52W_Low', 'Dist_From_52W_High',
        # Volatility and relative strength
        'nATR', 'RS', 'RS_line', 'relative_strength', 
    ]

    STANDARD_FEATURES = [
        # True oscillators (bounded 0-100 or similar)
        'RSI_14', 'earnings_quality_score',
        # Margins (values > 100% are accounting anomalies)
        'operating_margin', 'gross_margin', 'roe', 'roa', 'net_margin',
        # Slopes (extremely vertical slopes are unstable noise)
        'SMA_50_Slope', 'SMA_200_Slope',
        # VCP metrics (ratio of ratios, usually bounded)
        'VCP_Ratio', 'volatility_contraction',
        # Alphas (rank-based or neutralized)
        'alpha011', 'alpha013', 'alpha034', 'alpha054',
    ]

    # Known bounded features (automatic winsorize regardless of kurtosis)
    BOUNDED_FEATURES = [
        'RSI_14', 'RSI_5', 'RSI_21',  # 0-100
        'earnings_quality_score',      # Usually 0-1 or 0-100
    ]

    # SEPA C1-C11 related features for the SEPA Audit section
    SEPA_AUDIT_FEATURES = [
        'rs_rating',             # C9 - Core RS score
        'RS_Universe_Rank',      # C9 - Percentile rank
        'Price_vs_SMA_200',      # C1-C6 - Trend structure
        'Dist_From_52W_High',    # C8 - Proximity to highs
        'Dist_From_52W_Low',     # C7 - Distance from lows
        'Vol_Ratio',             # C11 - Volume confirmation
    ]

    # Features to skip in monotonicity section (categorical encoded features)
    SKIP_MONOTONICITY = [
        'industry_id_encoded',
        'sector_id_encoded',
    ]

    @staticmethod
    def encode_categorical_features(
        df: pd.DataFrame,
        categorical_features: Optional[List[str]] = None,
        target_col: str = 'return_pct',
        smoothing: float = 10.0
    ) -> Tuple[pd.DataFrame, Dict[str, Dict]]:
        """
        Apply target encoding to categorical features.

        Creates new columns with '_encoded' suffix containing the target-encoded values.
        Original columns are preserved for reference.

        Args:
            df: DataFrame with categorical columns
            categorical_features: List of categorical columns (default: CATEGORICAL_FEATURES)
            target_col: Target variable for encoding
            smoothing: Bayesian smoothing factor

        Returns:
            Tuple of (modified DataFrame, encoding_stats dict)
        """
        if categorical_features is None:
            categorical_features = CATEGORICAL_FEATURES

        df = df.copy()
        encoding_stats = {}

        for cat_col in categorical_features:
            if cat_col not in df.columns:
                continue

            encoded_col = f"{cat_col}_encoded"
            encoded_values = target_encode_categorical(
                df, cat_col, target_col, smoothing
            )

            if len(encoded_values) > 0:
                df[encoded_col] = encoded_values

                # Compute stats for reporting
                global_mean = df[target_col].mean()
                cat_stats = df.groupby(cat_col)[target_col].agg(['mean', 'count'])
                encoding_stats[cat_col] = {
                    'encoded_col': encoded_col,
                    'n_categories': len(cat_stats),
                    'global_mean': global_mean,
                    'category_stats': cat_stats.to_dict('index')
                }

                logger.info(f"Created {encoded_col} from {cat_col} ({len(cat_stats)} categories)")

        return df, encoding_stats

    @staticmethod
    def signed_log(x: np.ndarray) -> np.ndarray:
        """
        Apply signed log transform: sign(x) * log(1 + |x|)
        
        Preserves sign while compressing magnitude for fat-tailed distributions.
        Works for negative values (e.g., negative growth rates).
        """
        return np.sign(x) * np.log1p(np.abs(x))

    @staticmethod
    def compute_tail_alpha_ratio(
        df: pd.DataFrame,
        feature: str,
        target: str = 'return_pct',
        core_range: Tuple[float, float] = (10, 90),
        tail_range: Tuple[float, float] = (99, 100)
    ) -> float:
        """
        Compute Tail Alpha Ratio to determine if tail values are predictive.
        
        Ratio = Mean |return| in tail / Mean |return| in core
        
        Args:
            df: DataFrame with feature and target columns
            feature: Feature column name
            target: Target column name (return_pct)
            core_range: Percentile range for core (default: 10-90)
            tail_range: Percentile range for tail (default: 99-100)
            
        Returns:
            Tail Alpha Ratio (>1.2 suggests log transform, <=1.2 suggests winsorize)
        """
        if feature not in df.columns or target not in df.columns:
            return 1.0  # Default to neutral
            
        subset = df[[feature, target]].dropna()
        if len(subset) < 1000:
            return 1.0  # Insufficient data
            
        # Compute percentile thresholds
        core_low = np.percentile(subset[feature], core_range[0])
        core_high = np.percentile(subset[feature], core_range[1])
        tail_low = np.percentile(subset[feature], tail_range[0])
        
        # Core: stocks in 10th-90th percentile
        core_mask = (subset[feature] >= core_low) & (subset[feature] <= core_high)
        core_return = subset.loc[core_mask, target].abs().mean()
        
        # Tail: stocks in 99th-100th percentile (the outliers)
        tail_mask = subset[feature] >= tail_low
        tail_return = subset.loc[tail_mask, target].abs().mean()
        
        if core_return == 0 or np.isnan(core_return):
            return 1.0
            
        return tail_return / core_return

    @classmethod
    def transform_fat_tails(
        cls,
        df: pd.DataFrame,
        features: List[str],
        target: str = 'return_pct',
        kurtosis_threshold: float = 10.0,
        tail_alpha_threshold: float = 1.2,
        lower_percentile: float = 1.0,
        upper_percentile: float = 99.0
    ) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
        """
        Apply appropriate fat-tail treatment based on feature taxonomy and Tail Alpha Ratio.

        Decision tree:
        1. Is feature in BOUNDED_FEATURES? → Winsorize
        2. Is feature in EXPLOSIVE_FEATURES? → Log transform
        3. Is feature in STANDARD_FEATURES? → Winsorize
        4. Unknown feature:
           - Compute Tail Alpha Ratio (tail return / core return)
           - If ratio > 1.2 → Log transform (tail is predictive)
           - If ratio <= 1.2 → Winsorize (tail is noise)

        Args:
            df: DataFrame with feature columns
            features: List of feature names to potentially transform
            target: Target column for Tail Alpha Ratio calculation
            kurtosis_threshold: Only transform features with kurtosis above this (default: 10)
            tail_alpha_threshold: Ratio above which to log transform unknown features (default: 1.2)
            lower_percentile: Lower percentile for winsorization (default: 1%)
            upper_percentile: Upper percentile for winsorization (default: 99%)

        Returns:
            Tuple of (modified DataFrame, dict with 'log', 'winsorized', and 'tail_alpha_ratios')
        """
        from scipy import stats

        df = df.copy()
        transforms_applied = {
            'log': [],
            'winsorized': [],
            'skipped': [],
            'tail_alpha_ratios': {}  # Track ratios for reporting
        }

        for feature in features:
            if feature not in df.columns:
                continue

            series = df[feature].dropna()
            if len(series) < 100:
                continue

            # Check if transformation is needed (high kurtosis)
            kurt = stats.kurtosis(series, fisher=True)
            if abs(kurt) <= kurtosis_threshold:
                transforms_applied['skipped'].append(feature)
                continue

            # Ensure column can hold float values (for winsorization/log)
            # This handles Int32, Int64, and other numeric types that might reject float assignment
            if pd.api.types.is_numeric_dtype(df[feature]) and not pd.api.types.is_float_dtype(df[feature]):
                df[feature] = df[feature].astype(float)

            # Decision tree for treatment
            if feature in cls.BOUNDED_FEATURES:
                # Known bounded feature - always winsorize
                lower_bound = np.percentile(series, lower_percentile)
                upper_bound = np.percentile(series, upper_percentile)
                df[feature] = df[feature].clip(lower=lower_bound, upper=upper_bound)
                transforms_applied['winsorized'].append(feature)
                logger.info(f"Winsorized {feature} (bounded, kurtosis={kurt:.1f})")

            elif feature in cls.EXPLOSIVE_FEATURES:
                # Known explosive feature - log transform
                df[feature] = cls.signed_log(df[feature].values)
                transforms_applied['log'].append(feature)
                logger.info(f"Log-transformed {feature} (explosive, kurtosis={kurt:.1f})")

            elif feature in cls.STANDARD_FEATURES:
                # Known standard feature - winsorize
                lower_bound = np.percentile(series, lower_percentile)
                upper_bound = np.percentile(series, upper_percentile)
                df[feature] = df[feature].clip(lower=lower_bound, upper=upper_bound)
                transforms_applied['winsorized'].append(feature)
                logger.info(f"Winsorized {feature} (standard, kurtosis={kurt:.1f})")

            else:
                # Unknown feature - use Tail Alpha Ratio to decide
                tar = cls.compute_tail_alpha_ratio(df, feature, target)
                transforms_applied['tail_alpha_ratios'][feature] = tar

                if tar > tail_alpha_threshold:
                    # Tail is predictive - log transform
                    df[feature] = cls.signed_log(df[feature].values)
                    transforms_applied['log'].append(feature)
                    logger.info(f"Log-transformed {feature} (TAR={tar:.2f}>1.2, kurtosis={kurt:.1f})")
                else:
                    # Tail is noise - winsorize
                    lower_bound = np.percentile(series, lower_percentile)
                    upper_bound = np.percentile(series, upper_percentile)
                    df[feature] = df[feature].clip(lower=lower_bound, upper=upper_bound)
                    transforms_applied['winsorized'].append(feature)
                    logger.info(f"Winsorized {feature} (TAR={tar:.2f}<=1.2, kurtosis={kurt:.1f})")

        log_count = len(transforms_applied['log'])
        win_count = len(transforms_applied['winsorized'])
        if log_count > 0 or win_count > 0:
            logger.info(f"Fat-tail treatment: {log_count} log-transformed, {win_count} winsorized")

        return df, transforms_applied

    # Keep legacy method for backward compatibility
    @classmethod
    def winsorize_features(
        cls,
        df: pd.DataFrame,
        features: List[str],
        lower_percentile: float = 1.0,
        upper_percentile: float = 99.0,
        kurtosis_threshold: float = 10.0,
        auto_detect: bool = True
    ) -> Tuple[pd.DataFrame, List[str]]:
        """
        Legacy method - wraps transform_fat_tails for backward compatibility.
        Prefer using transform_fat_tails for new code.
        """
        df, transforms = cls.transform_fat_tails(
            df=df,
            features=features,
            target='return_pct',
            kurtosis_threshold=kurtosis_threshold,
            lower_percentile=lower_percentile,
            upper_percentile=upper_percentile
        )
        # Return combined list for backward compatibility
        all_transformed = transforms['log'] + transforms['winsorized']
        return df, all_transformed


    @staticmethod
    def remove_correlated_features(
        df: pd.DataFrame,
        features: List[str],
        ks_scores: Optional[pd.DataFrame] = None,
        correlation_threshold: float = 0.9
    ) -> Tuple[List[str], List[Dict]]:
        """
        Remove highly correlated features, keeping the one with higher KS score.

        Args:
            df: DataFrame with feature columns
            features: List of feature names to check
            ks_scores: DataFrame with 'feature' and 'KS_statistic' columns (for tie-breaking)
            correlation_threshold: Correlation above which to remove (default: 0.9)

        Returns:
            Tuple of (retained_features, removed_pairs) where removed_pairs contains
            dicts with {feature_1, feature_2, correlation, removed, reason}
        """
        if len(features) < 2:
            return features, []

        # Compute correlation matrix
        valid_features = [f for f in features if f in df.columns]
        corr_matrix = df[valid_features].corr()

        # Build KS lookup for tie-breaking
        ks_lookup = {}
        if ks_scores is not None and len(ks_scores) > 0:
            ks_lookup = dict(zip(ks_scores['feature'], ks_scores['KS_statistic']))

        # Find correlated pairs
        removed_pairs = []
        to_remove = set()

        for i in range(len(valid_features)):
            for j in range(i + 1, len(valid_features)):
                f1, f2 = valid_features[i], valid_features[j]
                corr = corr_matrix.iloc[i, j]

                if abs(corr) >= correlation_threshold:
                    # Decide which to remove based on KS score
                    ks1 = ks_lookup.get(f1, 0)
                    ks2 = ks_lookup.get(f2, 0)

                    if ks1 >= ks2:
                        removed = f2
                        reason = f"KS({f1})={ks1:.3f} >= KS({f2})={ks2:.3f}"
                    else:
                        removed = f1
                        reason = f"KS({f2})={ks2:.3f} > KS({f1})={ks1:.3f}"

                    to_remove.add(removed)
                    removed_pairs.append({
                        'feature_1': f1,
                        'feature_2': f2,
                        'correlation': corr,
                        'removed': removed,
                        'reason': reason
                    })

        retained = [f for f in valid_features if f not in to_remove]
        logger.info(f"Correlation filter: removed {len(to_remove)} features (|r| >= {correlation_threshold})")

        return retained, removed_pairs

    @staticmethod
    def screen_features(
        df: pd.DataFrame,
        candidate_features: List[str],
        target_col: str = 'return_pct',
        ks_threshold: float = 0.15,
        p_value_threshold: float = 0.05
    ) -> Dict:
        """
        Screen features for discrimination power using KS test.

        Features with KS statistic > threshold and p-value < threshold are kept.

        Args:
            df: Training dataset with features and target
            candidate_features: List of feature column names to screen
            target_col: Target variable for quartile separation (default: return_pct)
            ks_threshold: Minimum KS statistic to pass (default: 0.15)
            p_value_threshold: Maximum p-value to be significant (default: 0.05)

        Returns:
            Dict with keys:
                - 'passed': List of features that passed screening
                - 'failed': List of features that failed
                - 'missing': List of features not found in DataFrame
                - 'scores': DataFrame with full KS scores for all features
        """
        # Identify missing features
        available = [f for f in candidate_features if f in df.columns]
        missing = [f for f in candidate_features if f not in df.columns]

        if missing:
            logger.warning(f"Missing features (will skip): {missing}")

        if not available:
            logger.error("No valid features to screen")
            return {
                'passed': [],
                'failed': [],
                'missing': missing,
                'scores': pd.DataFrame()
            }

        # Run KS discrimination analysis
        scores_df = analyze_feature_separation(df, available, target=target_col)

        # Apply thresholds
        passed_mask = (
            (scores_df['KS_statistic'] >= ks_threshold) &
            (scores_df['p_value'] <= p_value_threshold)
        )

        passed = scores_df[passed_mask]['feature'].tolist()
        failed = scores_df[~passed_mask]['feature'].tolist()

        logger.info(f"Feature screening: {len(passed)} passed, {len(failed)} failed, {len(missing)} missing")

        return {
            'passed': passed,
            'failed': failed,
            'missing': missing,
            'scores': scores_df
        }

    @classmethod
    def run_pipeline(
        cls,
        df: pd.DataFrame,
        candidate_features: Optional[List[str]] = None,
        target_col: str = 'return_pct',
        ks_threshold: float = 0.15,
        correlation_threshold: float = 0.9,
        p_value_threshold: float = 0.05
    ) -> Dict:
        """
        Run the full feature selection pipeline:
        1. Pre-filter raw/excluded columns
        2. KS discrimination screening
        3. Remove highly correlated features (keeps higher KS)

        Args:
            df: Training dataset with features and target
            candidate_features: List to screen (if None, uses all numeric cols)
            target_col: Target variable for quartile separation
            ks_threshold: Minimum KS statistic to pass
            correlation_threshold: Correlation above which to remove features
            p_value_threshold: Maximum p-value to be significant

        Returns:
            Dict with keys:
                - 'passed': Final list of features after all filtering
                - 'failed_ks': Features that failed KS threshold
                - 'excluded_raw': Features removed by pre-filter
                - 'excluded_correlation': Features removed by correlation filter
                - 'correlation_pairs': Details of correlated pairs found
                - 'missing': Features not found in DataFrame
                - 'scores': DataFrame with KS scores for all screened features
        """
        # Step 1: Pre-filter raw/excluded columns
        filtered, excluded_raw = cls.pre_filter_features(df, candidate_features)

        if not filtered:
            logger.error("No features remaining after pre-filter")
            return {
                'passed': [],
                'failed_ks': [],
                'excluded_raw': excluded_raw,
                'excluded_correlation': [],
                'correlation_pairs': [],
                'missing': [],
                'scores': pd.DataFrame()
            }

        # Step 2: KS screening on filtered features
        ks_results = cls.screen_features(
            df, filtered, target_col, ks_threshold, p_value_threshold
        )

        # Step 3: Remove highly correlated features from those that passed KS
        after_corr, correlation_pairs = cls.remove_correlated_features(
            df,
            ks_results['passed'],
            ks_results['scores'],
            correlation_threshold
        )

        # Determine which were removed by correlation
        excluded_correlation = [f for f in ks_results['passed'] if f not in after_corr]

        logger.info(
            f"Pipeline complete: {len(candidate_features or [])} -> "
            f"{len(filtered)} (pre-filter) -> {len(ks_results['passed'])} (KS) -> "
            f"{len(after_corr)} (correlation)"
        )

        return {
            'passed': after_corr,
            'failed_ks': ks_results['failed'],
            'excluded_raw': excluded_raw,
            'excluded_correlation': excluded_correlation,
            'correlation_pairs': correlation_pairs,
            'missing': ks_results['missing'],
            'scores': ks_results['scores']
        }

    @classmethod
    def run_quant_pipeline(
        cls,
        df: pd.DataFrame,
        candidate_features: Optional[List[str]] = None,
        target_col: str = 'return_pct',
        date_col: str = 'entry_date',
        ks_threshold: float = 0.15,
        correlation_threshold: float = 0.7,
        p_value_threshold: float = 0.05,
        winsorize: bool = True,
        encode_categoricals: bool = True
    ) -> Dict:
        """
        Run the full quant-standard 4-pillar feature evaluation pipeline.

        Pipeline:
            1. Pre-filter raw/excluded columns (incl. leakage features)
            2. Target-encode categorical features (sector_id, industry_id)
            3. Winsorize high-kurtosis features (optional)
            4. Run 4-pillar analysis (FeatureAnalyzer)
            5. Compute composite scores (40% IC + 30% Stability + 30% KS)
            6. Correlation clustering with weighted pruning (0.7*IC + 0.3*Stability)
            7. Apply composite threshold for final selection

        Args:
            df: Training dataset with features and target
            candidate_features: List to screen (if None, uses all numeric cols)
            target_col: Target variable for analysis
            date_col: Date column for temporal stability analysis
            ks_threshold: Minimum KS/composite threshold (default: 0.15)
            correlation_threshold: Threshold for clustering (default: 0.7)
            p_value_threshold: Maximum p-value (default: 0.05)
            winsorize: If True, auto-winsorize high-kurtosis features (default: True)
            encode_categoricals: If True, target-encode categorical features (default: True)

        Returns:
            Dict with keys:
                - passed: Final list of features after all filtering
                - failed_composite: Features that failed composite threshold
                - excluded_raw: Features removed by pre-filter
                - excluded_correlation: Features removed by cluster pruning
                - fat_tail_transforms: Dict of log/winsorized features
                - categorical_encoding: Stats about encoded categorical features
                - analysis: Full 4-pillar analysis results
                - composite_scores: DataFrame with all scores
                - cluster_recommendations: Cluster pruning recommendations
        """
        # Step 1: Pre-filter raw/excluded columns (now includes LEAKAGE_FEATURES)
        filtered, excluded_raw = cls.pre_filter_features(df, candidate_features)
        fat_tail_transforms = {'log': [], 'winsorized': [], 'skipped': []}
        categorical_encoding = {}

        if not filtered:
            logger.error("No features remaining after pre-filter")
            return {
                'passed': [],
                'failed_composite': [],
                'excluded_raw': excluded_raw,
                'excluded_correlation': [],
                'fat_tail_transforms': fat_tail_transforms,
                'categorical_encoding': {},
                'analysis': {},
                'composite_scores': pd.DataFrame(),
                'cluster_recommendations': []
            }

        # Step 2: Target-encode categorical features (if present)
        if encode_categoricals:
            df, categorical_encoding = cls.encode_categorical_features(
                df, target_col=target_col
            )
            # Add encoded columns to feature list
            for cat_col, stats in categorical_encoding.items():
                encoded_col = stats['encoded_col']
                if encoded_col not in filtered:
                    filtered.append(encoded_col)
                    logger.info(f"Added {encoded_col} to feature candidates")

        # Step 3: Apply fat-tail treatment (log for explosive, winsorize for standard)
        if winsorize:
            df, fat_tail_transforms = cls.transform_fat_tails(df, filtered)
        else:
            fat_tail_transforms = {'log': [], 'winsorized': [], 'skipped': []}

        # Step 4: Run 4-pillar analysis
        logger.info(f"Running 4-pillar analysis on {len(filtered)} features...")
        analysis = FeatureAnalyzer.run_full_analysis(
            df, filtered, target=target_col, date_col=date_col
        )

        composite_df = analysis['composite_scores']

        if composite_df.empty:
            logger.warning("No composite scores generated, falling back to KS-only")
            return cls.run_pipeline(
                df, candidate_features, target_col,
                ks_threshold, correlation_threshold, p_value_threshold
            )

        # Step 5: Apply composite threshold
        # Use normalized threshold (composite is 0-1 scale)
        normalized_threshold = ks_threshold / 0.5  # Scale 0.15 -> 0.3 composite
        normalized_threshold = min(normalized_threshold, 0.5)  # Cap at 0.5

        passed_composite_mask = composite_df['composite'] >= normalized_threshold
        passed_features = composite_df[passed_composite_mask]['feature'].tolist()
        failed_features = composite_df[~passed_composite_mask]['feature'].tolist()

        logger.info(f"Composite filter: {len(passed_features)} passed, {len(failed_features)} failed")

        # Step 6: Cluster-based pruning (using composite score for tie-breaking)
        cluster_recommendations = analysis['pillar4_interaction']['recommendations']
        features_to_drop = set()

        for rec in cluster_recommendations:
            if len(rec['members']) > 1:
                # Only keep the recommended feature if it passed composite
                keep = rec['keep']
                if keep in passed_features:
                    for drop in rec['drop']:
                        if drop in passed_features:
                            features_to_drop.add(drop)

        # Final feature list
        final_passed = [f for f in passed_features if f not in features_to_drop]
        excluded_correlation = list(features_to_drop)

        logger.info(
            f"Quant pipeline complete: {len(filtered)} -> "
            f"{len(passed_features)} (composite) -> {len(final_passed)} (cluster pruning)"
        )

        return {
            'passed': final_passed,
            'failed_composite': failed_features,
            'excluded_raw': excluded_raw,
            'excluded_correlation': excluded_correlation,
            'fat_tail_transforms': fat_tail_transforms,
            'categorical_encoding': categorical_encoding,
            'analysis': analysis,
            'composite_scores': composite_df,
            'cluster_recommendations': cluster_recommendations,
            'dataset': df  # Include raw dataset for EDA stats
        }

    @staticmethod
    def generate_eda_report(
        screening_results: Dict,
        output_path: Path,
        target_col: str = 'return_pct',
        ks_threshold: float = 0.15,
        correlation_threshold: float = 0.9
    ) -> str:
        """
        Generate markdown EDA report from screening results.

        Supports both KS-only pipeline and quant-standard pipeline results.

        Args:
            screening_results: Output from run_pipeline() or run_quant_pipeline()
            output_path: Path to save the report
            target_col: Target variable used for screening
            ks_threshold: Threshold used for pass/fail
            correlation_threshold: Threshold used for correlation removal

        Returns:
            Path to saved report
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Detect if this is quant pipeline (has 'analysis' key)
        is_quant_pipeline = 'analysis' in screening_results and screening_results['analysis']

        if is_quant_pipeline:
            return FeatureScreener._generate_quant_report(
                screening_results, output_path, target_col, ks_threshold, correlation_threshold
            )
        else:
            return FeatureScreener._generate_ks_report(
                screening_results, output_path, target_col, ks_threshold, correlation_threshold
            )

    @staticmethod
    def _compute_dataset_stats(
        df: pd.DataFrame,
        target_col: str = 'return_pct',
        date_col: str = 'entry_date'
    ) -> Dict:
        """
        Compute comprehensive dataset statistics for EDA report.
        
        Args:
            df: D2 features dataset
            target_col: Target variable column name
            date_col: Date column for temporal analysis
            
        Returns:
            Dict with keys: target_stats, temporal_stats, ticker_stats, sector_stats, industry_stats
        """
        from scipy import stats as scipy_stats
        
        result = {}
        
        # --- Target Distribution ---
        if target_col in df.columns:
            target = df[target_col].dropna()
            result['target_stats'] = {
                'count': len(target),
                'mean': target.mean(),
                'std': target.std(),
                'min': target.min(),
                'max': target.max(),
                'median': target.median(),
                'q1': target.quantile(0.25),
                'q3': target.quantile(0.75),
                'skewness': scipy_stats.skew(target),
                'kurtosis': scipy_stats.kurtosis(target),
                'pct_positive': (target > 0).mean() * 100,
                'pct_negative': (target < 0).mean() * 100,
                'pct_gt_10': (target > 10).mean() * 100,
                'pct_gt_20': (target > 20).mean() * 100,
                'pct_lt_neg10': (target < -10).mean() * 100,
            }
            
            # Return buckets (5% increments)
            buckets = []
            edges = list(range(-50, 55, 5))  # -50 to +50 in 5% steps
            for i in range(len(edges) - 1):
                low, high = edges[i], edges[i + 1]
                count = ((target >= low) & (target < high)).sum()
                buckets.append({'low': low, 'high': high, 'count': count, 'pct': count / len(target) * 100})
            # Add overflow buckets
            buckets.insert(0, {'low': float('-inf'), 'high': -50, 'count': (target < -50).sum(), 'pct': (target < -50).mean() * 100})
            buckets.append({'low': 50, 'high': float('inf'), 'count': (target >= 50).sum(), 'pct': (target >= 50).mean() * 100})
            result['return_buckets'] = buckets
        
        # --- Days Held Statistics ---
        if 'days_held' in df.columns:
            days = df['days_held'].dropna()
            result['days_held_stats'] = {
                'mean': days.mean(),
                'std': days.std(),
                'min': days.min(),
                'max': days.max(),
                'median': days.median(),
            }
        
        # --- Temporal Coverage ---
        # Try both 'entry_date' and 'date' column names
        actual_date_col = date_col if date_col in df.columns else 'date'
        if actual_date_col in df.columns:
            dates = pd.to_datetime(df[actual_date_col])
            years = dates.dt.year
            year_counts = years.value_counts().sort_index()
            result['temporal_stats'] = {
                'date_min': dates.min().strftime('%Y-%m-%d'),
                'date_max': dates.max().strftime('%Y-%m-%d'),
                'n_unique_dates': dates.nunique(),
                'year_distribution': year_counts.to_dict()
            }
        
        # --- Ticker Distribution ---
        if 'ticker' in df.columns:
            ticker_counts = df['ticker'].value_counts()
            top_10 = ticker_counts.head(10)
            result['ticker_stats'] = {
                'n_unique': df['ticker'].nunique(),
                'top_10': top_10.to_dict(),
                'top_10_pct': top_10.sum() / len(df) * 100 if len(df) > 0 else 0
            }
        
        # --- Sector Distribution ---
        if 'sector_id' in df.columns:
            try:
                sector_map = pd.read_parquet('data/company_info/sector_mapping.parquet')
                sector_lookup = dict(zip(sector_map['sector_id'], sector_map['sector']))
            except Exception:
                sector_lookup = {}
            
            sector_counts = df['sector_id'].value_counts().sort_values(ascending=False)
            sector_data = []
            for sid, count in sector_counts.items():
                name = sector_lookup.get(sid, f'Unknown ({sid})')
                sector_data.append({'name': name, 'count': count, 'pct': count / len(df) * 100})
            result['sector_stats'] = sector_data
        
        # --- Industry Distribution ---
        if 'industry_id' in df.columns:
            try:
                industry_map = pd.read_parquet('data/company_info/industry_mapping.parquet')
                industry_lookup = dict(zip(industry_map['industry_id'], industry_map['industry']))
            except Exception:
                industry_lookup = {}
            
            industry_counts = df['industry_id'].value_counts().sort_values(ascending=False).head(15)
            industry_data = []
            for iid, count in industry_counts.items():
                name = industry_lookup.get(iid, f'Unknown ({iid})')
                industry_data.append({'name': name, 'count': count, 'pct': count / len(df) * 100})
            result['industry_stats'] = industry_data
        
        # --- MFE/MAE Statistics (if enriched from D2R) ---
        if 'MFE' in df.columns:
            mfe = df['MFE'].dropna()
            result['mfe_stats'] = {
                'count': len(mfe),
                'mean': mfe.mean(),
                'std': mfe.std(),
                'min': mfe.min(),
                'max': mfe.max(),
                'median': mfe.median(),
                'pct_gt_20': (mfe > 20).mean() * 100,
                'pct_gt_50': (mfe > 50).mean() * 100,
            }
        
        if 'MAE' in df.columns:
            mae = df['MAE'].dropna()
            result['mae_stats'] = {
                'mean': mae.mean(),
                'median': mae.median(),
                'min': mae.min(),
                'max': mae.max(),
            }
        
        if 'regret' in df.columns:
            regret = df['regret'].dropna()
            result['regret_stats'] = {
                'mean': regret.mean(),
                'median': regret.median(),
            }

        return result

    @staticmethod
    def _compute_candidate_profile(df: pd.DataFrame, target_col: str = 'return_pct') -> Dict:
        """
        Compute D1/D2 Candidate Profile stats for dashboard.

        Returns dict with:
        - filter_sensitivity: RS threshold vs win rate/candidate count
        - sector_efficiency: Sector frequency vs avg return scatter
        - industry_efficiency: Top 20 industries efficiency
        - fundamental_sanity: Price/mktCap/beta distributions
        """
        result = {}

        if len(df) == 0:
            logger.warning("Empty dataset for candidate profile")
            return result

        # --- 1. Filter Sensitivity (RS threshold yield curve) ---
        if 'rs_rating' in df.columns and target_col in df.columns:
            thresholds = [0, 20, 40, 50, 60, 70, 80, 90]
            filter_data = []
            for thresh in thresholds:
                # rs_rating is 0-1 scale
                subset = df[df['rs_rating'] >= thresh / 100.0]
                if len(subset) > 0:
                    win_rate = (subset[target_col] > 0).mean() * 100
                    avg_return = subset[target_col].mean()
                    filter_data.append({
                        'threshold': thresh,
                        'candidate_count': len(subset),
                        'win_rate': round(win_rate, 1),
                        'avg_return': round(avg_return, 2)
                    })
            result['filter_sensitivity'] = filter_data
            logger.info(f"Computed filter sensitivity for {len(thresholds)} RS thresholds")

        # --- 2. Sector Efficiency (Freq vs Return scatter) ---
        if 'sector_id' in df.columns:
            try:
                sector_map = pd.read_parquet('data/company_info/sector_mapping.parquet')
                sector_lookup = dict(zip(sector_map['sector_id'], sector_map['sector']))
            except Exception:
                sector_lookup = {}

            sector_stats = []
            total_trades = len(df)
            for sid, group in df.groupby('sector_id'):
                name = sector_lookup.get(sid, f'Unknown ({sid})')
                freq_pct = len(group) / total_trades * 100
                avg_return = group[target_col].mean() if target_col in group.columns else 0
                win_rate = (group[target_col] > 0).mean() * 100 if target_col in group.columns else 0

                sector_stats.append({
                    'sector': name,
                    'freq_pct': round(freq_pct, 1),
                    'avg_mfe': round(avg_return, 1),  # Using return as proxy for MFE
                    'avg_return': round(avg_return, 2),
                    'win_rate': round(win_rate, 1),
                    'count': len(group)
                })

            result['sector_efficiency'] = sorted(sector_stats, key=lambda x: x['freq_pct'], reverse=True)
            logger.info(f"Computed sector efficiency for {len(sector_stats)} sectors")

        # --- 3. Industry Efficiency (Top 20) ---
        if 'industry_id' in df.columns:
            try:
                industry_map = pd.read_parquet('data/company_info/industry_mapping.parquet')
                industry_lookup = dict(zip(industry_map['industry_id'], industry_map['industry']))
            except Exception:
                industry_lookup = {}

            industry_stats = []
            total_trades = len(df)
            for iid, group in df.groupby('industry_id'):
                name = industry_lookup.get(iid, f'Unknown ({iid})')
                freq_pct = len(group) / total_trades * 100
                avg_return = group[target_col].mean() if target_col in group.columns else 0
                win_rate = (group[target_col] > 0).mean() * 100 if target_col in group.columns else 0

                industry_stats.append({
                    'industry': name,
                    'freq_pct': round(freq_pct, 1),
                    'avg_mfe': round(avg_return, 1),
                    'avg_return': round(avg_return, 2),
                    'win_rate': round(win_rate, 1),
                    'count': len(group)
                })

            result['industry_efficiency'] = sorted(industry_stats, key=lambda x: x['count'], reverse=True)[:20]

        # --- 4. Fundamental Sanity Check ---
        sanity = {}

        # Price distribution
        if 'Close' in df.columns:
            prices = df['Close'].dropna()
            if len(prices) > 0:
                bins = [0, 5, 10, 20, 50, 100, 200, 500, float('inf')]
                labels = ['0-5', '5-10', '10-20', '20-50', '50-100', '100-200', '200-500', '>500']
                counts, _ = np.histogram(prices, bins=bins)
                histogram = [{'label': l, 'count': int(c)} for l, c in zip(labels, counts)]

                sanity['price_distribution'] = {
                    'median': round(float(prices.median()), 2),
                    'mean': round(float(prices.mean()), 2),
                    'pct_under_5': round(float((prices < 5).mean() * 100), 1),
                    'pct_under_10': round(float((prices < 10).mean() * 100), 1),
                    'pct_under_20': round(float((prices < 20).mean() * 100), 1),
                    'histogram': histogram
                }

        # Market Cap distribution
        if 'mktCap_log' in df.columns:
            mktcap = df['mktCap_log'].dropna()
            if len(mktcap) > 0:
                # Convert log back to billions
                mktcap_billions = (10 ** mktcap) / 1e9
                sanity['mktcap_distribution'] = {
                    'median_b': round(float(mktcap_billions.median()), 2),
                    'pct_micro': round(float((mktcap_billions < 0.3).mean() * 100), 1),
                    'pct_small': round(float(((mktcap_billions >= 0.3) & (mktcap_billions < 2)).mean() * 100), 1),
                    'pct_mid': round(float(((mktcap_billions >= 2) & (mktcap_billions < 10)).mean() * 100), 1),
                    'pct_large': round(float((mktcap_billions >= 10).mean() * 100), 1),
                }

        # Beta distribution
        if 'beta' in df.columns:
            beta = df['beta'].dropna()
            if len(beta) > 0:
                sanity['beta_distribution'] = {
                    'median': round(float(beta.median()), 2),
                    'mean': round(float(beta.mean()), 2),
                    'pct_low': round(float((beta < 0.8).mean() * 100), 1),
                    'pct_normal': round(float(((beta >= 0.8) & (beta <= 1.2)).mean() * 100), 1),
                    'pct_high': round(float((beta > 1.2).mean() * 100), 1),
                }

        if sanity:
            result['fundamental_sanity'] = sanity

        return result

    @staticmethod
    def _compute_sepa_analysis(
        df: pd.DataFrame,
        target_col: str = 'return_pct',
        rs_col: str = 'rs_rating'
    ) -> Dict:
        """
        Compute SEPA criteria analysis for dashboard.

        Returns dict with:
        - decile_box_data: Raw return arrays per decile for each feature (for proper box plots)
        - industry_box_data: Raw return arrays per industry
        - super_performer_analysis: Return histogram by RS decile (all 10 deciles)
        """
        result = {}

        if len(df) == 0 or target_col not in df.columns:
            return result

        # --- 1. Decile Box Plot Data (RAW DATA for proper Plotly rendering) ---
        key_features = [rs_col, 'RS_Universe_Rank', 'Price_vs_SMA_200', 'alpha011']
        decile_box_data = {}

        for feature in key_features:
            if feature not in df.columns:
                continue

            subset = df[[feature, target_col]].dropna()
            if len(subset) < 100:
                continue

            try:
                # Create deciles
                subset['decile'] = pd.qcut(subset[feature], 10, labels=False, duplicates='drop') + 1

                # Store RAW data arrays for each decile
                decile_arrays = {}
                for decile in range(1, 11):
                    decile_returns = subset[subset['decile'] == decile][target_col].tolist()
                    if len(decile_returns) > 0:
                        decile_arrays[f'D{decile}'] = decile_returns

                if len(decile_arrays) >= 5:  # At least 5 deciles
                    decile_box_data[feature] = decile_arrays
                    logger.debug(f"Stored raw box plot data for {feature}: {len(decile_arrays)} deciles")

            except Exception as e:
                logger.warning(f"Could not compute decile box data for {feature}: {e}")

        if decile_box_data:
            result['decile_box_data'] = decile_box_data

        # --- 2. Per-Industry Box Plot Data (RAW DATA) ---
        if 'industry_id' in df.columns:
            try:
                industry_map = pd.read_parquet('data/company_info/industry_mapping.parquet')
                industry_lookup = dict(zip(industry_map['industry_id'], industry_map['industry']))
            except Exception:
                industry_lookup = {}

            industry_box_data = []
            # Get top 20 industries by frequency
            top_industries = df['industry_id'].value_counts().head(20).index.tolist()

            for iid in top_industries:
                returns = df[df['industry_id'] == iid][target_col].dropna().tolist()
                if len(returns) < 10:
                    continue

                name = industry_lookup.get(iid, f'Unknown ({iid})')
                industry_box_data.append({
                    'industry': name,
                    'industry_id': str(iid),
                    'returns': returns,  # Raw data array
                    'count': len(returns)
                })

            if industry_box_data:
                result['industry_box_data'] = sorted(
                    industry_box_data, key=lambda x: x['count'], reverse=True
                )
                logger.info(f"Stored raw industry box data for {len(industry_box_data)} industries")

        # --- 3. Super-Performer Analysis (Fat-tail histogram by RS decile - ALL 10) ---
        if rs_col in df.columns:
            super_performer = {}
            subset = df[[rs_col, target_col]].dropna()

            if len(subset) >= 100:
                try:
                    subset['rs_decile'] = pd.qcut(subset[rs_col], 10, labels=False, duplicates='drop') + 1

                    # Define return bins
                    bins = [-float('inf'), 0, 20, 50, 100, float('inf')]
                    bin_labels = ['<0%', '0-20%', '20-50%', '50-100%', '>100%']

                    for decile in range(1, 11):  # ALL 10 DECILES
                        decile_returns = subset[subset['rs_decile'] == decile][target_col]
                        if len(decile_returns) < 10:
                            continue

                        # Compute histogram
                        counts = []
                        for i in range(len(bins) - 1):
                            low, high = bins[i], bins[i + 1]
                            count = ((decile_returns >= low) & (decile_returns < high)).sum()
                            counts.append(int(count))

                        # Compute home run stats
                        n_home_runs = (decile_returns >= 100).sum()
                        pct_home_runs = n_home_runs / len(decile_returns) * 100
                        n_super = (decile_returns >= 50).sum()
                        pct_super = n_super / len(decile_returns) * 100

                        super_performer[f'decile_{decile}'] = {
                            'return_bins': bin_labels,
                            'counts': counts,
                            'total_trades': int(len(decile_returns)),
                            'n_home_runs': int(n_home_runs),
                            'pct_home_runs': round(pct_home_runs, 2),
                            'n_super_performers': int(n_super),
                            'pct_super_performers': round(pct_super, 2),
                            'mean_return': round(float(decile_returns.mean()), 2),
                            'median_return': round(float(decile_returns.median()), 2),
                            'max_return': round(float(decile_returns.max()), 2)
                        }

                    if super_performer:
                        result['super_performer_analysis'] = super_performer
                        logger.info(f"Computed super-performer analysis for {len(super_performer)} deciles")

                except Exception as e:
                    logger.warning(f"Could not compute super-performer analysis: {e}")

        return result

    @staticmethod
    def _generate_dataset_section(stats: Dict, target_col: str = 'return_pct') -> List[str]:
        """Generate markdown section for dataset overview."""
        lines = []
        lines.append("## Section 0: Dataset Overview")
        lines.append("")
        
        # Target variable stats
        if 'target_stats' in stats:
            ts = stats['target_stats']
            lines.append(f"### Target Variable Distribution (`{target_col}`)")
            lines.append("")
            lines.append("| Statistic | Value |")
            lines.append("|-----------|-------|")
            lines.append(f"| Count | {ts['count']:,} |")
            lines.append(f"| Mean | {ts['mean']:+.2f}% |")
            lines.append(f"| Std Dev | {ts['std']:.2f}% |")
            lines.append(f"| Min | {ts['min']:+.2f}% |")
            lines.append(f"| Max | {ts['max']:+.2f}% |")
            lines.append(f"| Median | {ts['median']:+.2f}% |")
            lines.append(f"| Q1 (25%) | {ts['q1']:+.2f}% |")
            lines.append(f"| Q3 (75%) | {ts['q3']:+.2f}% |")
            lines.append(f"| Skewness | {ts['skewness']:+.2f} |")
            lines.append(f"| Kurtosis | {ts['kurtosis']:.1f} |")
            lines.append("")
            
            lines.append("| Outcome | Count | % |")
            lines.append("|---------|-------|---|")
            lines.append(f"| Positive (> 0%) | {int(ts['count'] * ts['pct_positive'] / 100):,} | {ts['pct_positive']:.1f}% |")
            lines.append(f"| > +10% | {int(ts['count'] * ts['pct_gt_10'] / 100):,} | {ts['pct_gt_10']:.1f}% |")
            lines.append(f"| > +20% | {int(ts['count'] * ts['pct_gt_20'] / 100):,} | {ts['pct_gt_20']:.1f}% |")
            lines.append(f"| Negative (< 0%) | {int(ts['count'] * ts['pct_negative'] / 100):,} | {ts['pct_negative']:.1f}% |")
            lines.append(f"| < -10% | {int(ts['count'] * ts['pct_lt_neg10'] / 100):,} | {ts['pct_lt_neg10']:.1f}% |")
            lines.append("")
        
        # Return buckets
        if 'return_buckets' in stats:
            lines.append("### Return Distribution (5% Buckets)")
            lines.append("")
            lines.append("| Bucket | Count | % | Bar |")
            lines.append("|--------|-------|---|-----|")
            max_pct = max(b['pct'] for b in stats['return_buckets']) or 1
            for b in stats['return_buckets']:
                if b['count'] == 0:
                    continue
                bar_len = int(b['pct'] / max_pct * 20)
                bar = '█' * bar_len
                if b['low'] == float('-inf'):
                    label = f"< {b['high']}%"
                elif b['high'] == float('inf'):
                    label = f">= {b['low']}%"
                else:
                    label = f"[{b['low']}, {b['high']})%"
                lines.append(f"| {label} | {b['count']:,} | {b['pct']:.1f}% | {bar} |")
            lines.append("")
        
        # Days held stats
        if 'days_held_stats' in stats:
            dh = stats['days_held_stats']
            lines.append("### Holding Period (`days_held`)")
            lines.append("")
            lines.append("| Statistic | Value |")
            lines.append("|-----------|-------|")
            lines.append(f"| Mean | {dh['mean']:.1f} days |")
            lines.append(f"| Std Dev | {dh['std']:.1f} days |")
            lines.append(f"| Min | {dh['min']:.0f} days |")
            lines.append(f"| Max | {dh['max']:.0f} days |")
            lines.append(f"| Median | {dh['median']:.1f} days |")
            lines.append("")
        
        # Temporal coverage
        if 'temporal_stats' in stats:
            ts = stats['temporal_stats']
            lines.append("### Temporal Coverage")
            lines.append("")
            lines.append(f"- **Date Range:** {ts['date_min']} to {ts['date_max']}")
            lines.append(f"- **Unique Entry Dates:** {ts['n_unique_dates']:,}")
            lines.append("")
            lines.append("| Year | Samples | % |")
            lines.append("|------|---------|---|")
            total = sum(ts['year_distribution'].values())
            for year, count in sorted(ts['year_distribution'].items()):
                pct = count / total * 100 if total > 0 else 0
                lines.append(f"| {year} | {count:,} | {pct:.1f}% |")
            lines.append("")
        
        # Ticker stats
        if 'ticker_stats' in stats:
            tk = stats['ticker_stats']
            lines.append("### Ticker Distribution")
            lines.append("")
            lines.append(f"- **Unique Tickers:** {tk['n_unique']:,}")
            lines.append(f"- **Top 10 Concentration:** {tk['top_10_pct']:.1f}% of samples")
            lines.append("")
            lines.append("| Ticker | Samples |")
            lines.append("|--------|---------|")
            for ticker, count in tk['top_10'].items():
                lines.append(f"| {ticker} | {count:,} |")
            lines.append("")
        
        # Sector distribution
        if 'sector_stats' in stats:
            lines.append("### Sector Distribution")
            lines.append("")
            lines.append("| Sector | Samples | % |")
            lines.append("|--------|---------|---|")
            for s in stats['sector_stats']:
                lines.append(f"| {s['name']} | {s['count']:,} | {s['pct']:.1f}% |")
            lines.append("")
        
        # Industry distribution (top 15)
        if 'industry_stats' in stats:
            lines.append("### Top 15 Industries")
            lines.append("")
            lines.append("| Industry | Samples | % |")
            lines.append("|----------|---------|---|")
            for i in stats['industry_stats']:
                lines.append(f"| {i['name']} | {i['count']:,} | {i['pct']:.1f}% |")
            lines.append("")
        
        # MFE/MAE Statistics (if enriched from D2R)
        if 'mfe_stats' in stats:
            mfe = stats['mfe_stats']
            lines.append("### MFE Analysis (Maximum Favorable Excursion)")
            lines.append("")
            lines.append("*Peak return % during trade (best possible exit)*")
            lines.append("")
            lines.append("| Statistic | Value |")
            lines.append("|-----------|-------|")
            lines.append(f"| Count | {mfe['count']:,} |")
            lines.append(f"| Mean | {mfe['mean']:+.1f}% |")
            lines.append(f"| Std Dev | {mfe['std']:.1f}% |")
            lines.append(f"| Min | {mfe['min']:+.1f}% |")
            lines.append(f"| Max | {mfe['max']:+.1f}% |")
            lines.append(f"| Median | {mfe['median']:+.1f}% |")
            lines.append(f"| > 20% | {mfe['pct_gt_20']:.1f}% of trades |")
            lines.append(f"| > 50% | {mfe['pct_gt_50']:.1f}% of trades |")
            lines.append("")
            
            # MAE stats
            if 'mae_stats' in stats:
                mae = stats['mae_stats']
                lines.append("### MAE Analysis (Maximum Adverse Excursion)")
                lines.append("")
                lines.append("*Largest drawdown % during trade*")
                lines.append("")
                lines.append("| Statistic | Value |")
                lines.append("|-----------|-------|")
                lines.append(f"| Mean | {mae['mean']:+.1f}% |")
                lines.append(f"| Median | {mae['median']:+.1f}% |")
                lines.append(f"| Min (worst DD) | {mae['min']:+.1f}% |")
                lines.append(f"| Max (best case) | {mae['max']:+.1f}% |")
                lines.append("")
            
            # Regret stats
            if 'regret_stats' in stats:
                regret = stats['regret_stats']
                lines.append("### Regret Analysis (MFE - Actual Return)")
                lines.append("")
                lines.append("*How much return was left on the table*")
                lines.append("")
                lines.append(f"- **Mean Regret:** {regret['mean']:+.1f}%")
                lines.append(f"- **Median Regret:** {regret['median']:+.1f}%")
                lines.append("")
        
        return lines

    @staticmethod
    def _compute_sepa_audit_stats(
        df: pd.DataFrame,
        target_col: str = 'return_pct'
    ) -> Dict:
        """
        Compute SEPA audit statistics for the text report.
        
        For each SEPA-related feature (C1-C11), compute decile-based statistics:
        - Count, Mean, Median, Min, Max, Std, Win%
        
        Returns:
            Dict with feature -> list of decile stats dicts
        """
        result = {}
        
        if len(df) == 0 or target_col not in df.columns:
            return result
        
        for feature in FeatureScreener.SEPA_AUDIT_FEATURES:
            if feature not in df.columns:
                continue
            
            subset = df[[feature, target_col]].dropna()
            if len(subset) < 100:
                continue
            
            try:
                # Create deciles
                subset['decile'] = pd.qcut(subset[feature], 10, labels=False, duplicates='drop') + 1
                
                decile_stats = []
                for decile in range(1, 11):
                    decile_data = subset[subset['decile'] == decile][target_col]
                    if len(decile_data) == 0:
                        continue
                    
                    win_rate = (decile_data > 0).mean() * 100
                    
                    decile_stats.append({
                        'decile': decile,
                        'count': len(decile_data),
                        'mean': decile_data.mean(),
                        'median': decile_data.median(),
                        'min': decile_data.min(),
                        'max': decile_data.max(),
                        'std': decile_data.std(),
                        'win_pct': win_rate
                    })
                
                if len(decile_stats) >= 5:
                    result[feature] = decile_stats
                    
            except Exception as e:
                logger.warning(f"Could not compute SEPA audit for {feature}: {e}")
        
        return result

    @staticmethod
    def _generate_sepa_audit_section(sepa_stats: Dict, target_col: str = 'return_pct') -> List[str]:
        """
        Generate markdown section for SEPA Audit (Section 1).
        
        Displays decile statistics for key SEPA-related features.
        """
        lines = []
        
        lines.append("## Section 1: SEPA Audit (Entry Criteria Validation)")
        lines.append("")
        lines.append("> **Purpose:** Validate SEPA C1-C11 criteria effectiveness by examining")
        lines.append("> how key entry features relate to trade outcomes across deciles.")
        lines.append("")
        
        if not sepa_stats:
            lines.append("*SEPA audit features not available in dataset*")
            lines.append("")
            return lines
        
        # SEPA criteria descriptions
        criteria_desc = {
            'rs_rating': 'C9 - Relative Strength (core ranking)',
            'RS_Universe_Rank': 'C9 - RS Percentile (cross-sectional)',
            'Price_vs_SMA_200': 'C1-C6 - Trend Structure',
            'Dist_From_52W_High': 'C8 - Proximity to 52W High',
            'Dist_From_52W_Low': 'C7 - Distance from 52W Low',
            'Vol_Ratio': 'C11 - Volume Confirmation',
        }
        
        for feature, stats in sepa_stats.items():
            desc = criteria_desc.get(feature, 'SEPA-related')
            lines.append(f"### {feature}")
            lines.append(f"*{desc}*")
            lines.append("")
            
            # Create table
            lines.append("| Decile | Count | Mean | Median | Min | Max | Std | Win% |")
            lines.append("|--------|-------|------|--------|-----|-----|-----|------|")
            
            for s in stats:
                lines.append(
                    f"| D{s['decile']} | {s['count']:,} | "
                    f"{s['mean']:+.1f}% | {s['median']:+.1f}% | "
                    f"{s['min']:+.1f}% | {s['max']:+.1f}% | "
                    f"{s['std']:.1f}% | {s['win_pct']:.0f}% |"
                )
            
            lines.append("")
            
            # Add interpretation
            if len(stats) >= 2:
                d1 = stats[0]
                d10 = stats[-1]
                spread = d10['mean'] - d1['mean']
                win_spread = d10['win_pct'] - d1['win_pct']
                
                if spread > 5:
                    lines.append(f"> **Strong monotonicity:** D10 outperforms D1 by {spread:+.1f}% (Win%: {win_spread:+.0f}pp)")
                elif spread > 0:
                    lines.append(f"> **Weak monotonicity:** D10 vs D1 spread of {spread:+.1f}%")
                else:
                    lines.append(f"> **⚠️ Inverted:** D1 outperforms D10 by {-spread:+.1f}%")
                lines.append("")
        
        return lines

    @staticmethod
    def _generate_ks_report(
        screening_results: Dict,
        output_path: Path,
        target_col: str,
        ks_threshold: float,
        correlation_threshold: float
    ) -> str:
        """Generate KS-only pipeline report (legacy format)."""
        lines = []
        scores_df = screening_results.get('scores', pd.DataFrame())
        passed = screening_results['passed']
        failed = screening_results.get('failed_ks', screening_results.get('failed', []))
        missing = screening_results.get('missing', [])
        excluded_raw = screening_results.get('excluded_raw', [])
        excluded_correlation = screening_results.get('excluded_correlation', [])
        correlation_pairs = screening_results.get('correlation_pairs', [])

        # Header
        lines.append("# Feature Screening Report (KS-Only)")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Target Variable:** `{target_col}`")
        lines.append(f"**KS Threshold:** {ks_threshold}")
        lines.append(f"**Correlation Threshold:** {correlation_threshold}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        total_screened = len(passed) + len(failed) + len(excluded_correlation)
        lines.append("| Stage | Count |")
        lines.append("|-------|-------|")
        if excluded_raw:
            lines.append(f"| Pre-filtered (raw/excluded) | {len(excluded_raw)} |")
        lines.append(f"| Screened with KS test | {total_screened} |")
        lines.append(f"| Failed KS threshold | {len(failed)} |")
        if excluded_correlation:
            lines.append(f"| Removed (high correlation) | {len(excluded_correlation)} |")
        lines.append(f"| **Final passed** | **{len(passed)}** |")
        if missing:
            lines.append(f"| Missing (not in data) | {len(missing)} |")
        lines.append("")

        # Passed features
        lines.append("## Passed Features")
        lines.append("")
        if passed and len(scores_df) > 0:
            passed_df = scores_df[scores_df['feature'].isin(passed)].copy()
            passed_df = passed_df.sort_values('KS_statistic', ascending=False)

            lines.append("| Rank | Feature | KS Stat | p-value | Q4-Q1 Diff |")
            lines.append("|------|---------|---------|---------|------------|")

            for rank, (_, row) in enumerate(passed_df.iterrows(), 1):
                ks = row['KS_statistic']
                pval = row['p_value']
                diff = row['mean_diff']
                lines.append(f"| {rank} | `{row['feature']}` | {ks:.3f} | {pval:.4f} | {diff:+.3f} |")
        else:
            lines.append("*No features passed screening*")
        lines.append("")

        # Failed features
        if failed and len(scores_df) > 0:
            lines.append("## Failed Features")
            lines.append("")
            failed_df = scores_df[scores_df['feature'].isin(failed)].copy()
            failed_df = failed_df.sort_values('KS_statistic', ascending=False)

            lines.append("| Feature | KS Stat | p-value | Reason |")
            lines.append("|---------|---------|---------|--------|")

            for _, row in failed_df.iterrows():
                ks = row['KS_statistic']
                pval = row['p_value']
                if ks < ks_threshold:
                    reason = f"KS ({ks:.3f}) < {ks_threshold}"
                else:
                    reason = f"p-value ({pval:.4f}) > 0.05"
                lines.append(f"| `{row['feature']}` | {ks:.3f} | {pval:.4f} | {reason} |")
            lines.append("")

        # Correlation removals
        if correlation_pairs:
            lines.append("## Removed (High Correlation)")
            lines.append("")
            lines.append(f"Features removed due to |r| >= {correlation_threshold}:")
            lines.append("")
            lines.append("| Feature 1 | Feature 2 | Correlation | Removed | Reason |")
            lines.append("|-----------|-----------|-------------|---------|--------|")
            for pair in correlation_pairs:
                lines.append(
                    f"| `{pair['feature_1']}` | `{pair['feature_2']}` | "
                    f"{pair['correlation']:.3f} | `{pair['removed']}` | {pair['reason']} |"
                )
            lines.append("")

        # Recommended feature list
        lines.extend(FeatureScreener._generate_feature_list_section(passed))
        lines.extend(FeatureScreener._generate_next_steps_section())

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"Saved EDA report to {output_path}")
        return str(output_path)

    @staticmethod
    def _generate_quant_report(
        screening_results: Dict,
        output_path: Path,
        target_col: str,
        ks_threshold: float,
        correlation_threshold: float
    ) -> str:
        """Generate quant-standard 4-pillar report."""
        lines = []
        passed = screening_results['passed']
        failed = screening_results.get('failed_composite', [])
        excluded_raw = screening_results.get('excluded_raw', [])
        excluded_correlation = screening_results.get('excluded_correlation', [])
        composite_df = screening_results.get('composite_scores', pd.DataFrame())
        analysis = screening_results.get('analysis', {})
        cluster_recs = screening_results.get('cluster_recommendations', [])

        # Header
        lines.append("# Feature Evaluation Report (Quant-Standard)")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Target Variable:** `{target_col}`")
        lines.append(f"**Composite Weights:** 40% IC + 30% Stability + 30% KS")
        lines.append(f"**Correlation Threshold:** {correlation_threshold}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Section 0: Dataset Overview (if dataset available)
        dataset = screening_results.get('dataset')
        if dataset is not None and len(dataset) > 0:
            dataset_stats = FeatureScreener._compute_dataset_stats(dataset, target_col)
            lines.extend(FeatureScreener._generate_dataset_section(dataset_stats, target_col))
            
            # Section 1: SEPA Audit
            sepa_stats = FeatureScreener._compute_sepa_audit_stats(dataset, target_col)
            lines.extend(FeatureScreener._generate_sepa_audit_section(sepa_stats, target_col))

        # Executive Summary
        lines.append("## Executive Summary")
        lines.append("")
        total_candidates = len(passed) + len(failed) + len(excluded_raw) + len(excluded_correlation)
        lines.append(f"- **Total candidates:** {total_candidates}")
        lines.append(f"- **Final passed:** {len(passed)}")

        # Count regime-conditional features
        stability_df = analysis.get('pillar3_stability', {}).get('ic_stability', pd.DataFrame())
        if not stability_df.empty:
            regime_count = stability_df['is_regime_conditional'].sum()
            if regime_count > 0:
                lines.append(f"- **Regime-conditional features:** {regime_count} (flagged for monitoring)")
        lines.append("")

        # Section 2: Feature Leaderboard
        lines.append("## Section 2: Feature Leaderboard")
        lines.append("")
        lines.append("> **Note:** All scores are normalized 0-1 for comparability. IC (Norm) = raw Spearman IC divided by max IC in dataset.")
        lines.append("")
        if not composite_df.empty:
            passed_df = composite_df[composite_df['feature'].isin(passed)].head(30)

            lines.append("| Rank | Feature | Composite | IC (Norm) | Stability | KS | Signal Type |")
            lines.append("|------|---------|-----------|-----------|-----------|-----|-------------|")

            for rank, (_, row) in enumerate(passed_df.iterrows(), 1):
                lines.append(
                    f"| {rank} | `{row['feature']}` | "
                    f"{row['composite']:.3f} | {row['ic_score']:.3f} | "
                    f"{row['stability_score']:.3f} | {row['ks_score']:.3f} | "
                    f"{row.get('signal_type', 'N/A')} |"
                )
        else:
            lines.append("*No composite scores available*")
        lines.append("")

        # Section 3: Monotonicity Deep Dive
        lines.append("## Section 3: Monotonicity Deep Dive")
        lines.append("")
        mono_df = analysis.get('pillar2_power', {}).get('monotonicity', pd.DataFrame())
        if not mono_df.empty:
            # Show top 10 features with decile info (skip categorical encoded features)
            valid_mono = mono_df[
                mono_df['feature'].isin(passed) & 
                ~mono_df['feature'].isin(FeatureScreener.SKIP_MONOTONICITY)
            ]
            top_mono = valid_mono.head(10)

            for _, row in top_mono.iterrows():
                feature = row['feature']
                signal_type = row['signal_type']
                d1_mean = row['d1_mean']
                d10_mean = row['d10_mean']
                decile_returns = row.get('decile_returns', [])

                lines.append(f"### {feature}")
                lines.append(f"- **Signal Type:** {signal_type}")
                lines.append(f"- **D1 Mean Return:** {d1_mean:+.2f}%")
                lines.append(f"- **D10 Mean Return:** {d10_mean:+.2f}%")

                # ASCII bar chart for decile returns
                if decile_returns:
                    lines.append("- **Decile Returns:**")
                    lines.append("  ```")
                    max_val = max(abs(r) for r in decile_returns) if decile_returns else 1
                    for i, ret in enumerate(decile_returns, 1):
                        bar_len = int(abs(ret) / max_val * 20) if max_val > 0 else 0
                        bar_char = '+' if ret >= 0 else '-'
                        bar = bar_char * bar_len
                        lines.append(f"  D{i:2d}: {ret:+6.2f}% |{bar}")
                    lines.append("  ```")

                # M02 Warning for bad D1
                if d1_mean < -2 and signal_type == 'linear_pos':
                    lines.append(f"  > **M02 Warning:** D1 has negative avg return ({d1_mean:+.2f}%)")
                lines.append("")
        else:
            lines.append("*Monotonicity analysis not available*")
            lines.append("")

        # Section 4: Stability Analysis
        lines.append("## Section 4: Stability Analysis (Per-Year IC)")
        lines.append("")
        if not stability_df.empty:
            # Build year columns dynamically
            all_years = set()
            for _, row in stability_df.iterrows():
                if isinstance(row['yearly_ics'], dict):
                    all_years.update(row['yearly_ics'].keys())

            if all_years:
                years = sorted(all_years)
                year_cols = " | ".join(f"IC_{y}" for y in years)
                lines.append(f"| Feature | {year_cols} | Stability | Regime? |")
                lines.append("|---------|" + "|".join(["-------"] * (len(years) + 2)) + "|")

                for _, row in stability_df[stability_df['feature'].isin(passed)].head(15).iterrows():
                    yearly = row['yearly_ics'] if isinstance(row['yearly_ics'], dict) else {}
                    year_vals = " | ".join(f"{yearly.get(y, 0):.3f}" for y in years)
                    regime_flag = "Yes" if row['is_regime_conditional'] else "No"
                    lines.append(
                        f"| `{row['feature']}` | {year_vals} | "
                        f"{row['ic_stability']:.2f} | {regime_flag} |"
                    )
            lines.append("")

            # Highlight regime-conditional
            regime_features = stability_df[
                stability_df['is_regime_conditional'] &
                stability_df['feature'].isin(passed)
            ]['feature'].tolist()
            if regime_features:
                lines.append("### Regime-Conditional Features (High IC Variance)")
                lines.append("")
                lines.append("These features have inconsistent IC across years. Monitor closely:")
                lines.append("")
                for f in regime_features[:10]:
                    lines.append(f"- `{f}`")
                lines.append("")
        else:
            lines.append("*Stability analysis not available (insufficient date data)*")
            lines.append("")

        # Section 5: Correlation Clusters
        lines.append("## Section 5: Correlation Clusters")
        lines.append("")
        if cluster_recs:
            multi_member_clusters = [c for c in cluster_recs if len(c['members']) > 1]
            if multi_member_clusters:
                for rec in multi_member_clusters[:10]:
                    cluster_name = rec['cluster'].replace('cluster_', 'Cluster ')
                    lines.append(f"### {cluster_name}")
                    lines.append(f"- **Members:** {', '.join(f'`{m}`' for m in rec['members'])}")
                    lines.append(f"- **Keep:** `{rec['keep']}` ({rec['reason']})")
                    if rec['drop']:
                        lines.append(f"- **Drop:** {', '.join(f'`{d}`' for d in rec['drop'])}")
                    lines.append("")
            else:
                lines.append("*No highly correlated clusters found*")
                lines.append("")
        else:
            lines.append("*Cluster analysis not available*")
            lines.append("")

        # Section 6: Distributional Warnings
        lines.append("## Section 6: Distributional Warnings")
        lines.append("")
        health = analysis.get('pillar1_health', {})

        warnings = []

        # Kurtosis warnings
        kurtosis_df = health.get('kurtosis', pd.DataFrame())
        if not kurtosis_df.empty:
            extreme = kurtosis_df[kurtosis_df['is_extreme'] & kurtosis_df['feature'].isin(passed)]
            for _, row in extreme.iterrows():
                warnings.append({
                    'feature': row['feature'],
                    'issue': f"Kurtosis={row['kurtosis']:.1f}",
                    'action': "Consider winsorizing at 1/99%"
                })

        # Missingness warnings
        missing_df = health.get('missingness', pd.DataFrame())
        if not missing_df.empty:
            high_missing = missing_df[
                (missing_df['missing_pct'] > 10) &
                missing_df['feature'].isin(passed)
            ]
            for _, row in high_missing.iterrows():
                action = "May be signal (unprofitable)" if row['is_systematic'] else "Check data source"
                warnings.append({
                    'feature': row['feature'],
                    'issue': f"{row['missing_pct']:.1f}% missing",
                    'action': action
                })

        # Stationarity warnings
        stationarity_df = health.get('stationarity', pd.DataFrame())
        if not stationarity_df.empty:
            non_stationary = stationarity_df[
                ~stationarity_df['is_stationary'] &
                stationarity_df['feature'].isin(passed)
            ]
            for _, row in non_stationary.iterrows():
                warnings.append({
                    'feature': row['feature'],
                    'issue': f"Non-stationary (p={row['p_value']:.3f})",
                    'action': "May need differencing"
                })

        if warnings:
            lines.append("| Feature | Issue | Action |")
            lines.append("|---------|-------|--------|")
            for w in warnings[:20]:
                lines.append(f"| `{w['feature']}` | {w['issue']} | {w['action']} |")
        else:
            lines.append("*No distributional warnings*")
        lines.append("")

        # Section 7: Transformation Summary
        lines.append("## Section 7: Transformation Summary")
        lines.append("")
        fat_tail_transforms = screening_results.get('fat_tail_transforms', {})
        log_features = fat_tail_transforms.get('log', [])
        winsorized_features = fat_tail_transforms.get('winsorized', [])

        if log_features or winsorized_features:
            lines.append("> Features with high kurtosis were automatically transformed during EDA:")
            lines.append("> - **Log Transform** (`sign(x) * log(1+|x|)`): Preserves magnitude (explosive/TAR>1.2)")
            lines.append("> - **Winsorization** (1%/99%): Clips outliers as noise (bounded/standard/TAR<=1.2)")
            lines.append("")
            
            # Get TAR values for unknown features
            tar_values = fat_tail_transforms.get('tail_alpha_ratios', {})
            
            lines.append("| Feature | Transform | Category | TAR |")
            lines.append("|---------|-----------|----------|-----|")
            
            for f in log_features:
                tar = tar_values.get(f, None)
                if tar is not None:
                    lines.append(f"| `{f}` | Log | TAR-based | {tar:.2f} |")
                elif f in FeatureScreener.EXPLOSIVE_FEATURES:
                    lines.append(f"| `{f}` | Log | Explosive | - |")
                else:
                    lines.append(f"| `{f}` | Log | Unknown | - |")
                    
            for f in winsorized_features:
                tar = tar_values.get(f, None)
                if tar is not None:
                    lines.append(f"| `{f}` | Winsorize | TAR-based | {tar:.2f} |")
                elif f in FeatureScreener.BOUNDED_FEATURES:
                    lines.append(f"| `{f}` | Winsorize | Bounded | - |")
                elif f in FeatureScreener.STANDARD_FEATURES:
                    lines.append(f"| `{f}` | Winsorize | Standard | - |")
                else:
                    lines.append(f"| `{f}` | Winsorize | Unknown | - |")
            
            lines.append("")
            lines.append(f"**Total:** {len(log_features)} log-transformed, {len(winsorized_features)} winsorized")
            
            if tar_values:
                lines.append("")
                lines.append("> **TAR (Tail Alpha Ratio):** Ratio of mean |return| in 99-100th percentile vs 10-90th percentile.")
                lines.append("> TAR > 1.2 suggests tail values are predictive (log transform); TAR <= 1.2 suggests noise (winsorize).")
        else:
            lines.append("*No fat-tail transformations applied (all features had normal kurtosis)*")
        lines.append("")

        # Recommended Feature List (with transformed names)
        lines.extend(FeatureScreener._generate_feature_list_section(passed, fat_tail_transforms))
        lines.extend(FeatureScreener._generate_next_steps_section())

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"Saved quant-standard EDA report to {output_path}")
        return str(output_path)

    @staticmethod
    def _generate_feature_list_section(passed: List[str], fat_tail_transforms: dict = None) -> List[str]:
        """Generate recommended feature list section with transformed names.
        
        Log-transformed features get log_ prefix in the output.
        fat_tail_transforms structure: {'log': [features], 'winsorized': [features]}
        """
        lines = []
        lines.append("## Recommended Feature List")
        lines.append("")
        lines.append("Copy this to `src/feature_config.py` → `M01_FEATURES` after review:")
        lines.append("")
        lines.append("> **Note:** Features with `log_` prefix are log-transformed during preprocessing.")
        lines.append("> The preprocessor will apply these transforms automatically at training/inference.")
        lines.append("")
        lines.append("```python")
        lines.append("M01_FEATURES = [")
        
        # Get list of log-transformed features
        log_features = fat_tail_transforms.get('log', []) if fat_tail_transforms else []
        
        for f in passed:
            # Check if this feature was log-transformed
            if f in log_features:
                # Avoid double prefix (e.g., log_log_volume_velocity)
                if f.startswith('log_'):
                    lines.append(f"    '{f}',  # already log-transformed")
                else:
                    lines.append(f"    'log_{f}',  # log-transformed")
            else:
                lines.append(f"    '{f}',")
        lines.append("]")
        lines.append("```")
        lines.append("")
        return lines

    @staticmethod
    def _generate_next_steps_section() -> List[str]:
        """Generate next steps section."""
        lines = []
        lines.append("---")
        lines.append("")
        lines.append("## Next Steps (User Action Required)")
        lines.append("")
        lines.append("**The workflow does NOT auto-save models.** To deploy new features:")
        lines.append("")
        lines.append("1. **Review** this report and the passed/failed features")
        lines.append("2. **Copy** the recommended feature list above to `src/feature_config.py` → `M01_FEATURES`")
        lines.append("3. **Train** the production model:")
        lines.append("   ```bash")
        lines.append("   python model_runner.py m01 --steps train")
        lines.append("   ```")
        lines.append("4. **Verify** the model works with `daily_scanner.py --ml`")
        lines.append("")
        lines.append("> **Why manual approval?** Auto-saving overwrote production models during testing.")
        lines.append("> This safeguard ensures only reviewed features reach production.")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("*Report generated by FeatureScreener (Quant-Standard Pipeline)*")
        return lines

    @staticmethod
    def export_dashboard_json(
        screening_results: Dict,
        output_path: Path,
        target_col: str = 'return_pct'
    ) -> str:
        """
        Export EDA results as JSON for dashboard consumption.

        Creates a structured JSON file that can be loaded by the Streamlit dashboard
        for visualization without re-computing the analysis.

        Args:
            screening_results: Output from run_quant_pipeline()
            output_path: Path to save JSON file
            target_col: Target variable used for screening

        Returns:
            Path to saved JSON file
        """
        import json
        from datetime import datetime

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Extract data from screening results
        passed = screening_results.get('passed', [])
        failed = screening_results.get('failed_composite', [])
        composite_df = screening_results.get('composite_scores', pd.DataFrame())
        analysis = screening_results.get('analysis', {})
        fat_tail_transforms = screening_results.get('fat_tail_transforms', {})
        categorical_encoding = screening_results.get('categorical_encoding', {})
        cluster_recs = screening_results.get('cluster_recommendations', [])
        dataset = screening_results.get('dataset')

        # Build JSON structure
        dashboard_data = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'target_col': target_col,
                'n_passed': len(passed),
                'n_failed': len(failed),
                'composite_weights': {'ic': 0.4, 'stability': 0.3, 'ks': 0.3}
            },
            'feature_scores': [],
            'ks_distributions': {},
            'decile_stats': {},
            'ic_time_series': {},
            'correlation_clusters': [],
            'transform_summary': {
                'log': fat_tail_transforms.get('log', []),
                'winsorized': fat_tail_transforms.get('winsorized', []),
                'tail_alpha_ratios': fat_tail_transforms.get('tail_alpha_ratios', {})
            },
            'categorical_encoding': {}
        }

        # Feature scores (for leaderboard)
        if not composite_df.empty:
            for _, row in composite_df.iterrows():
                dashboard_data['feature_scores'].append({
                    'feature': row['feature'],
                    'composite': float(row['composite']),
                    'ic_score': float(row['ic_score']),
                    'stability_score': float(row['stability_score']),
                    'ks_score': float(row['ks_score']),
                    'signal_type': row.get('signal_type', 'unknown'),
                    'passed': row['feature'] in passed
                })

        # Monotonicity / Decile stats (for decile plots)
        mono_df = analysis.get('pillar2_power', {}).get('monotonicity', pd.DataFrame())
        if not mono_df.empty:
            for _, row in mono_df.iterrows():
                feature = row['feature']
                decile_returns = row.get('decile_returns', [])
                if decile_returns:
                    dashboard_data['decile_stats'][feature] = {
                        'decile_returns': [float(x) for x in decile_returns],
                        'd1_mean': float(row['d1_mean']),
                        'd10_mean': float(row['d10_mean']),
                        'signal_type': row['signal_type']
                    }

        # IC time series (for stability plots)
        stability_df = analysis.get('pillar3_stability', {}).get('ic_stability', pd.DataFrame())
        if not stability_df.empty:
            for _, row in stability_df.iterrows():
                feature = row['feature']
                yearly_ics = row.get('yearly_ics', {})
                if isinstance(yearly_ics, dict) and yearly_ics:
                    dashboard_data['ic_time_series'][feature] = {
                        'yearly_ics': {str(k): float(v) for k, v in yearly_ics.items()},
                        'ic_stability': float(row['ic_stability']),
                        'is_regime_conditional': bool(row['is_regime_conditional'])
                    }

        # KS distributions (for Q1/Q4 histogram comparisons)
        # Extract from pillar2 if available
        ks_results = analysis.get('pillar2_power', {}).get('ks_discrimination', pd.DataFrame())
        if not ks_results.empty and dataset is not None:
            # Compute Q1/Q4 distributions for top features
            top_features = passed[:20] if passed else []
            for feature in top_features:
                if feature in dataset.columns and target_col in dataset.columns:
                    try:
                        q1_thresh = dataset[target_col].quantile(0.25)
                        q4_thresh = dataset[target_col].quantile(0.75)

                        q1_values = dataset.loc[dataset[target_col] <= q1_thresh, feature].dropna()
                        q4_values = dataset.loc[dataset[target_col] >= q4_thresh, feature].dropna()

                        # Sample if too large (for JSON size)
                        if len(q1_values) > 500:
                            q1_values = q1_values.sample(500, random_state=42)
                        if len(q4_values) > 500:
                            q4_values = q4_values.sample(500, random_state=42)

                        dashboard_data['ks_distributions'][feature] = {
                            'q1': q1_values.tolist(),
                            'q4': q4_values.tolist(),
                            'q1_median': float(q1_values.median()),
                            'q4_median': float(q4_values.median())
                        }
                    except Exception as e:
                        logger.warning(f"Could not compute KS distribution for {feature}: {e}")

        # Correlation clusters
        for rec in cluster_recs:
            if len(rec.get('members', [])) > 1:
                dashboard_data['correlation_clusters'].append({
                    'cluster_id': rec.get('cluster', 'unknown'),
                    'members': rec.get('members', []),
                    'keep': rec.get('keep', ''),
                    'drop': rec.get('drop', []),
                    'reason': rec.get('reason', '')
                })

        # Categorical encoding stats
        for cat_col, stats in categorical_encoding.items():
            dashboard_data['categorical_encoding'][cat_col] = {
                'encoded_col': stats.get('encoded_col', ''),
                'n_categories': stats.get('n_categories', 0),
                'global_mean': float(stats.get('global_mean', 0))
            }

        # Dataset stats (if available)
        if dataset is not None and len(dataset) > 0:
            dataset_stats = FeatureScreener._compute_dataset_stats(dataset, target_col)
            dashboard_data['dataset_stats'] = {
                'n_samples': int(dataset_stats.get('target_stats', {}).get('count', 0)),
                'target_mean': float(dataset_stats.get('target_stats', {}).get('mean', 0)),
                'target_median': float(dataset_stats.get('target_stats', {}).get('median', 0)),
                'pct_positive': float(dataset_stats.get('target_stats', {}).get('pct_positive', 0)),
                'date_range': {
                    'min': dataset_stats.get('temporal_stats', {}).get('date_min', ''),
                    'max': dataset_stats.get('temporal_stats', {}).get('date_max', '')
                }
            }

            # Candidate Profile Analysis (for D1 Analysis page)
            candidate_profile = FeatureScreener._compute_candidate_profile(dataset, target_col)
            dashboard_data.update(candidate_profile)

            # SEPA Criteria Analysis (box plots, industry performance, super-performer)
            sepa_analysis = FeatureScreener._compute_sepa_analysis(dataset, target_col)
            dashboard_data.update(sepa_analysis)

        # Write JSON
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(dashboard_data, f, indent=2, default=str)

        logger.info(f"Saved dashboard JSON to {output_path}")
        return str(output_path)

    @staticmethod
    def generate_all_outputs(
        screening_results: Dict,
        output_dir: Path,
        target_col: str = 'return_pct',
        ks_threshold: float = 0.15,
        correlation_threshold: float = 0.7
    ) -> Dict[str, str]:
        """
        Generate both markdown report and JSON dashboard data.

        This is the unified output method that ensures both outputs
        are generated from the same underlying data.

        Args:
            screening_results: Output from run_quant_pipeline()
            output_dir: Directory to save outputs
            target_col: Target variable used for screening
            ks_threshold: KS threshold used
            correlation_threshold: Correlation threshold used

        Returns:
            Dict with paths: {'markdown': path, 'json': path}
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Generate markdown report
        md_path = FeatureScreener.generate_eda_report(
            screening_results,
            output_dir / 'eda_report.md',
            target_col,
            ks_threshold,
            correlation_threshold
        )

        # Generate JSON for dashboard
        json_path = FeatureScreener.export_dashboard_json(
            screening_results,
            output_dir / 'eda_dashboard.json',
            target_col
        )

        logger.info(f"Generated unified EDA outputs: {md_path}, {json_path}")

        return {
            'markdown': md_path,
            'json': json_path
        }
