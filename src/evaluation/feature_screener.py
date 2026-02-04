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
from src.feature_config import FEATURE_EXCLUSION_LIST
from .feature_analyzer import FeatureAnalyzer

logger = logging.getLogger(__name__)


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
        winsorize: bool = True
    ) -> Dict:
        """
        Run the full quant-standard 4-pillar feature evaluation pipeline.

        Pipeline:
            1. Pre-filter raw/excluded columns
            2. Winsorize high-kurtosis features (optional)
            3. Run 4-pillar analysis (FeatureAnalyzer)
            4. Compute composite scores (40% IC + 30% Stability + 30% KS)
            5. Correlation clustering with weighted pruning (0.7*IC + 0.3*Stability)
            6. Apply composite threshold for final selection

        Args:
            df: Training dataset with features and target
            candidate_features: List to screen (if None, uses all numeric cols)
            target_col: Target variable for analysis
            date_col: Date column for temporal stability analysis
            ks_threshold: Minimum KS/composite threshold (default: 0.15)
            correlation_threshold: Threshold for clustering (default: 0.7)
            p_value_threshold: Maximum p-value (default: 0.05)
            winsorize: If True, auto-winsorize high-kurtosis features (default: True)

        Returns:
            Dict with keys:
                - passed: Final list of features after all filtering
                - failed_composite: Features that failed composite threshold
                - excluded_raw: Features removed by pre-filter
                - excluded_correlation: Features removed by cluster pruning
                - winsorized_features: List of features that were winsorized
                - analysis: Full 4-pillar analysis results
                - composite_scores: DataFrame with all scores
                - cluster_recommendations: Cluster pruning recommendations
        """
        # Step 1: Pre-filter raw/excluded columns
        filtered, excluded_raw = cls.pre_filter_features(df, candidate_features)
        fat_tail_transforms = {'log': [], 'winsorized': [], 'skipped': []}

        if not filtered:
            logger.error("No features remaining after pre-filter")
            return {
                'passed': [],
                'failed_composite': [],
                'excluded_raw': excluded_raw,
                'excluded_correlation': [],
                'fat_tail_transforms': fat_tail_transforms,
                'analysis': {},
                'composite_scores': pd.DataFrame(),
                'cluster_recommendations': []
            }

        # Step 2: Apply fat-tail treatment (log for explosive, winsorize for standard)
        if winsorize:
            df, fat_tail_transforms = cls.transform_fat_tails(df, filtered)
        else:
            fat_tail_transforms = {'log': [], 'winsorized': [], 'skipped': []}


        # Step 3: Run 4-pillar analysis
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

        # Step 3: Apply composite threshold
        # Use normalized threshold (composite is 0-1 scale)
        normalized_threshold = ks_threshold / 0.5  # Scale 0.15 -> 0.3 composite
        normalized_threshold = min(normalized_threshold, 0.5)  # Cap at 0.5

        passed_composite_mask = composite_df['composite'] >= normalized_threshold
        passed_features = composite_df[passed_composite_mask]['feature'].tolist()
        failed_features = composite_df[~passed_composite_mask]['feature'].tolist()

        logger.info(f"Composite filter: {len(passed_features)} passed, {len(failed_features)} failed")

        # Step 4: Cluster-based pruning (using composite score for tie-breaking)
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
            'analysis': analysis,
            'composite_scores': composite_df,
            'cluster_recommendations': cluster_recommendations
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

        # Section 1: Feature Leaderboard
        lines.append("## Section 1: Feature Leaderboard")
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

        # Section 2: Monotonicity Deep Dive
        lines.append("## Section 2: Monotonicity Deep Dive")
        lines.append("")
        mono_df = analysis.get('pillar2_power', {}).get('monotonicity', pd.DataFrame())
        if not mono_df.empty:
            # Show top 10 features with decile info
            top_mono = mono_df[mono_df['feature'].isin(passed)].head(10)

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

        # Section 3: Stability Analysis
        lines.append("## Section 3: Stability Analysis (Per-Year IC)")
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

        # Section 4: Correlation Clusters
        lines.append("## Section 4: Correlation Clusters")
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

        # Section 5: Distributional Warnings
        lines.append("## Section 5: Distributional Warnings")
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

        # Section 6: Transformation Summary
        lines.append("## Section 6: Transformation Summary")
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
