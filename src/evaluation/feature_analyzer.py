"""
Feature Analyzer - Quant-Standard 4-Pillar Evaluation
======================================================

Multi-dimensional feature quality analysis:
1. Distributional Health - Stationarity, kurtosis, missingness
2. Predictive Power - IC, Mutual Information, decile monotonicity
3. Temporal Stability - IC stability over time, PSI
4. Interaction - Correlation clusters

This module provides pure analysis; FeatureScreener handles selection logic.
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.feature_selection import mutual_info_regression

logger = logging.getLogger(__name__)


class FeatureAnalyzer:
    """Quant-standard feature evaluation across 4 pillars."""

    # =========================================================================
    # PILLAR 1: DISTRIBUTIONAL HEALTH
    # =========================================================================

    @staticmethod
    def check_stationarity(
        df: pd.DataFrame,
        features: List[str],
        significance: float = 0.05
    ) -> pd.DataFrame:
        """
        ADF stationarity test per feature.

        Args:
            df: DataFrame with feature columns
            features: List of feature names to test
            significance: p-value threshold for stationarity (default: 0.05)

        Returns:
            DataFrame with columns: feature, adf_statistic, p_value, is_stationary
        """
        try:
            from statsmodels.tsa.stattools import adfuller
        except ImportError:
            logger.warning("statsmodels not installed, skipping stationarity check")
            return pd.DataFrame(columns=['feature', 'adf_statistic', 'p_value', 'is_stationary'])

        results = []
        for feature in features:
            if feature not in df.columns:
                continue

            series = df[feature].dropna()
            if len(series) < 20:
                results.append({
                    'feature': feature,
                    'adf_statistic': np.nan,
                    'p_value': np.nan,
                    'is_stationary': False
                })
                continue

            try:
                adf_result = adfuller(series, autolag='AIC')
                results.append({
                    'feature': feature,
                    'adf_statistic': adf_result[0],
                    'p_value': adf_result[1],
                    'is_stationary': adf_result[1] < significance
                })
            except Exception as e:
                logger.warning(f"ADF test failed for {feature}: {e}")
                results.append({
                    'feature': feature,
                    'adf_statistic': np.nan,
                    'p_value': np.nan,
                    'is_stationary': False
                })

        return pd.DataFrame(results)

    @staticmethod
    def compute_kurtosis(
        df: pd.DataFrame,
        features: List[str],
        extreme_threshold: float = 10.0
    ) -> pd.DataFrame:
        """
        Compute kurtosis and flag extreme fat tails.

        Args:
            df: DataFrame with feature columns
            features: List of feature names
            extreme_threshold: Kurtosis threshold for flagging (default: 10)

        Returns:
            DataFrame with columns: feature, kurtosis, skewness, is_extreme
        """
        results = []
        for feature in features:
            if feature not in df.columns:
                continue

            series = df[feature].dropna()
            if len(series) < 10:
                continue

            kurt = stats.kurtosis(series, fisher=True)  # Excess kurtosis
            skew = stats.skew(series)

            results.append({
                'feature': feature,
                'kurtosis': kurt,
                'skewness': skew,
                'is_extreme': abs(kurt) > extreme_threshold
            })

        return pd.DataFrame(results)

    @staticmethod
    def analyze_missingness(
        df: pd.DataFrame,
        features: List[str],
        target: str = 'return_pct'
    ) -> pd.DataFrame:
        """
        Analyze missing value patterns per feature.

        Args:
            df: DataFrame with feature columns and target
            features: List of feature names
            target: Target column for systematic missingness check

        Returns:
            DataFrame with columns: feature, missing_pct, is_systematic, mean_return_when_missing
        """
        results = []
        has_target = target in df.columns

        for feature in features:
            if feature not in df.columns:
                continue

            missing_mask = df[feature].isna()
            missing_pct = missing_mask.mean() * 100

            # Check if missingness is systematic (correlated with target)
            is_systematic = False
            mean_return_when_missing = np.nan

            if has_target and missing_pct > 0 and missing_pct < 100:
                missing_returns = df.loc[missing_mask, target].dropna()
                present_returns = df.loc[~missing_mask, target].dropna()

                if len(missing_returns) >= 10 and len(present_returns) >= 10:
                    # t-test for mean difference
                    _, p_val = stats.ttest_ind(missing_returns, present_returns)
                    is_systematic = p_val < 0.05
                    mean_return_when_missing = missing_returns.mean()

            results.append({
                'feature': feature,
                'missing_pct': missing_pct,
                'is_systematic': is_systematic,
                'mean_return_when_missing': mean_return_when_missing
            })

        return pd.DataFrame(results)

    # =========================================================================
    # PILLAR 2: PREDICTIVE POWER
    # =========================================================================

    @staticmethod
    def compute_ic(
        df: pd.DataFrame,
        features: List[str],
        target: str = 'return_pct'
    ) -> pd.DataFrame:
        """
        Compute Information Coefficient (Spearman rank correlation) with target.

        Args:
            df: DataFrame with features and target
            features: List of feature names
            target: Target column name

        Returns:
            DataFrame with columns: feature, ic, ic_abs, p_value
        """
        if target not in df.columns:
            raise ValueError(f"Target column '{target}' not found")

        results = []
        target_series = df[target]

        for feature in features:
            if feature not in df.columns:
                continue

            # Drop rows where either feature or target is NaN
            mask = df[feature].notna() & target_series.notna()
            if mask.sum() < 30:
                continue

            feature_vals = df.loc[mask, feature]
            target_vals = target_series[mask]

            ic, p_value = stats.spearmanr(feature_vals, target_vals)

            results.append({
                'feature': feature,
                'ic': ic,
                'ic_abs': abs(ic),
                'p_value': p_value
            })

        return pd.DataFrame(results).sort_values('ic_abs', ascending=False)

    @staticmethod
    def compute_mutual_information(
        df: pd.DataFrame,
        features: List[str],
        target: str = 'return_pct',
        n_neighbors: int = 5
    ) -> pd.DataFrame:
        """
        Compute mutual information (captures non-linear relationships).

        Args:
            df: DataFrame with features and target
            features: List of feature names
            target: Target column name
            n_neighbors: Number of neighbors for MI estimation

        Returns:
            DataFrame with columns: feature, mutual_info, mi_normalized
        """
        if target not in df.columns:
            raise ValueError(f"Target column '{target}' not found")

        # Filter valid features
        valid_features = [f for f in features if f in df.columns]
        if not valid_features:
            return pd.DataFrame()

        # Prepare data (drop any rows with NaN in features or target)
        subset = df[valid_features + [target]].dropna()
        if len(subset) < 100:
            logger.warning(f"Insufficient data for MI calculation: {len(subset)} rows")
            return pd.DataFrame()

        X = subset[valid_features]
        y = subset[target]

        # Compute MI
        mi_scores = mutual_info_regression(X, y, n_neighbors=n_neighbors, random_state=42)

        # Normalize by max MI for interpretability
        max_mi = mi_scores.max() if mi_scores.max() > 0 else 1.0

        results = pd.DataFrame({
            'feature': valid_features,
            'mutual_info': mi_scores,
            'mi_normalized': mi_scores / max_mi
        })

        return results.sort_values('mutual_info', ascending=False)

    @staticmethod
    def analyze_decile_monotonicity(
        df: pd.DataFrame,
        features: List[str],
        target: str = 'return_pct',
        n_bins: int = 10
    ) -> pd.DataFrame:
        """
        Analyze decile monotonicity - does target increase/decrease monotonically with feature?

        Args:
            df: DataFrame with features and target
            features: List of feature names
            target: Target column name
            n_bins: Number of bins (default: 10 for deciles)

        Returns:
            DataFrame with columns:
                - feature: Feature name
                - monotonicity_score: 0-1 score (1 = perfect monotonicity)
                - signal_type: 'linear_pos', 'linear_neg', 'kinked', or 'flat'
                - d1_mean: Mean target in lowest decile
                - d10_mean: Mean target in highest decile
                - decile_returns: List of mean returns per decile
        """
        if target not in df.columns:
            raise ValueError(f"Target column '{target}' not found")

        results = []

        for feature in features:
            if feature not in df.columns:
                continue

            # Drop NaN rows
            subset = df[[feature, target]].dropna()
            if len(subset) < n_bins * 10:
                continue

            # Create deciles
            try:
                subset['decile'] = pd.qcut(
                    subset[feature], q=n_bins,
                    labels=range(1, n_bins + 1),
                    duplicates='drop'
                )
            except ValueError:
                # Not enough unique values for binning
                continue

            # Mean return per decile
            decile_means = subset.groupby('decile', observed=True)[target].mean()

            if len(decile_means) < 3:
                continue

            # Calculate monotonicity score
            # Count increasing pairs vs decreasing pairs
            diffs = np.diff(decile_means.values)
            n_increasing = (diffs > 0).sum()
            n_decreasing = (diffs < 0).sum()
            total_diffs = len(diffs)

            if total_diffs == 0:
                monotonicity_score = 0
                signal_type = 'flat'
            else:
                # Score: proportion of consistent direction
                monotonicity_score = max(n_increasing, n_decreasing) / total_diffs

                # Determine signal type
                if n_increasing > n_decreasing * 2:
                    signal_type = 'linear_pos'
                elif n_decreasing > n_increasing * 2:
                    signal_type = 'linear_neg'
                elif monotonicity_score < 0.6:
                    signal_type = 'kinked'
                else:
                    signal_type = 'linear_pos' if n_increasing > n_decreasing else 'linear_neg'

            results.append({
                'feature': feature,
                'monotonicity_score': monotonicity_score,
                'signal_type': signal_type,
                'd1_mean': decile_means.iloc[0] if len(decile_means) > 0 else np.nan,
                'd10_mean': decile_means.iloc[-1] if len(decile_means) > 0 else np.nan,
                'decile_returns': decile_means.tolist()
            })

        return pd.DataFrame(results).sort_values('monotonicity_score', ascending=False)

    # =========================================================================
    # PILLAR 3: TEMPORAL STABILITY
    # =========================================================================

    @staticmethod
    def compute_ic_stability(
        df: pd.DataFrame,
        features: List[str],
        target: str = 'return_pct',
        date_col: str = 'entry_date'
    ) -> pd.DataFrame:
        """
        Compute IC stability over time (IC_mean / IC_std across years).

        Args:
            df: DataFrame with features, target, and date column
            features: List of feature names
            target: Target column name
            date_col: Date column for temporal grouping

        Returns:
            DataFrame with columns:
                - feature: Feature name
                - ic_mean: Mean IC across years
                - ic_std: Std of IC across years
                - ic_stability: ic_mean / ic_std (higher = more stable)
                - yearly_ics: Dict of {year: IC}
                - is_regime_conditional: Flag for high variance features
        """
        if date_col not in df.columns:
            # Try alternative date columns
            for alt_col in ['Date', 'date', 'entry_date']:
                if alt_col in df.columns:
                    date_col = alt_col
                    break
            else:
                raise ValueError(f"No date column found in DataFrame")

        # Extract year
        df = df.copy()
        df['_year'] = pd.to_datetime(df[date_col]).dt.year

        results = []

        for feature in features:
            if feature not in df.columns:
                continue

            yearly_ics = {}
            for year, year_df in df.groupby('_year'):
                if len(year_df) < 100:
                    continue

                subset = year_df[[feature, target]].dropna()
                if len(subset) < 50:
                    continue

                # Check for constant input (avoids ConstantInputWarning)
                if subset[feature].nunique() < 2 or subset[target].nunique() < 2:
                    continue

                ic, _ = stats.spearmanr(subset[feature], subset[target])
                yearly_ics[year] = ic

            if len(yearly_ics) < 2:
                continue

            ic_values = list(yearly_ics.values())
            ic_mean = np.mean(ic_values)
            ic_std = np.std(ic_values)

            # Stability: mean/std (avoid division by zero)
            ic_stability = ic_mean / ic_std if ic_std > 0.01 else ic_mean * 100

            # Flag regime-conditional features (high variance relative to mean)
            is_regime_conditional = ic_std > abs(ic_mean) * 0.5 if ic_mean != 0 else True

            results.append({
                'feature': feature,
                'ic_mean': ic_mean,
                'ic_std': ic_std,
                'ic_stability': ic_stability,
                'yearly_ics': yearly_ics,
                'is_regime_conditional': is_regime_conditional
            })

        return pd.DataFrame(results).sort_values('ic_stability', ascending=False)

    @staticmethod
    def compute_psi(
        df: pd.DataFrame,
        features: List[str],
        date_col: str = 'entry_date',
        baseline_years: int = 2,
        n_bins: int = 10
    ) -> pd.DataFrame:
        """
        Compute Population Stability Index (PSI) for distribution drift detection.

        PSI < 0.1: No significant change
        PSI 0.1-0.25: Moderate change
        PSI > 0.25: Significant shift

        Args:
            df: DataFrame with features and date column
            features: List of feature names
            date_col: Date column for temporal grouping
            baseline_years: Years to use as baseline (default: 2)
            n_bins: Number of bins for distribution comparison

        Returns:
            DataFrame with columns: feature, psi, drift_level
        """
        if date_col not in df.columns:
            for alt_col in ['Date', 'date', 'entry_date']:
                if alt_col in df.columns:
                    date_col = alt_col
                    break
            else:
                raise ValueError("No date column found")

        df = df.copy()
        df['_year'] = pd.to_datetime(df[date_col]).dt.year

        years = sorted(df['_year'].unique())
        if len(years) < baseline_years + 1:
            logger.warning("Not enough years for PSI calculation")
            return pd.DataFrame()

        baseline_years_list = years[:baseline_years]
        recent_years = years[baseline_years:]

        baseline_df = df[df['_year'].isin(baseline_years_list)]
        recent_df = df[df['_year'].isin(recent_years)]

        results = []

        for feature in features:
            if feature not in df.columns:
                continue

            baseline_vals = baseline_df[feature].dropna()
            recent_vals = recent_df[feature].dropna()

            if len(baseline_vals) < 100 or len(recent_vals) < 100:
                continue

            # Create bins from baseline
            try:
                _, bin_edges = pd.qcut(baseline_vals, q=n_bins, retbins=True, duplicates='drop')
            except ValueError:
                continue

            # Calculate proportions in each bin
            baseline_counts = pd.cut(baseline_vals, bins=bin_edges, include_lowest=True).value_counts(normalize=True)
            recent_counts = pd.cut(recent_vals, bins=bin_edges, include_lowest=True).value_counts(normalize=True)

            # Align indices
            all_bins = baseline_counts.index.union(recent_counts.index)
            baseline_counts = baseline_counts.reindex(all_bins, fill_value=0.0001)
            recent_counts = recent_counts.reindex(all_bins, fill_value=0.0001)

            # PSI formula: sum((actual - expected) * ln(actual/expected))
            psi = np.sum(
                (recent_counts - baseline_counts) * np.log(recent_counts / baseline_counts)
            )

            # Classify drift level
            if psi < 0.1:
                drift_level = 'stable'
            elif psi < 0.25:
                drift_level = 'moderate_drift'
            else:
                drift_level = 'significant_drift'

            results.append({
                'feature': feature,
                'psi': psi,
                'drift_level': drift_level
            })

        return pd.DataFrame(results).sort_values('psi', ascending=False)

    # =========================================================================
    # PILLAR 4: INTERACTION (CORRELATION CLUSTERS)
    # =========================================================================

    @staticmethod
    def cluster_features(
        df: pd.DataFrame,
        features: List[str],
        threshold: float = 0.7
    ) -> Dict[str, List[str]]:
        """
        Hierarchical clustering of correlated features.

        Args:
            df: DataFrame with feature columns
            features: List of feature names
            threshold: Correlation threshold for clustering (default: 0.7)

        Returns:
            Dict mapping cluster_id to list of feature names
        """
        valid_features = [f for f in features if f in df.columns]
        if len(valid_features) < 2:
            return {'cluster_0': valid_features}

        # Compute correlation matrix
        corr_matrix = df[valid_features].corr().fillna(0)

        # Convert to distance matrix (1 - |correlation|)
        distance_matrix = 1 - np.abs(corr_matrix.values)
        np.fill_diagonal(distance_matrix, 0)

        # Ensure symmetry
        distance_matrix = (distance_matrix + distance_matrix.T) / 2

        # Hierarchical clustering
        condensed_dist = squareform(distance_matrix)
        linkage_matrix = linkage(condensed_dist, method='average')

        # Form clusters at threshold
        cluster_labels = fcluster(linkage_matrix, t=1 - threshold, criterion='distance')

        # Group features by cluster
        clusters = {}
        for feature, cluster_id in zip(valid_features, cluster_labels):
            cluster_name = f'cluster_{cluster_id}'
            if cluster_name not in clusters:
                clusters[cluster_name] = []
            clusters[cluster_name].append(feature)

        return clusters

    @staticmethod
    def get_cluster_recommendations(
        clusters: Dict[str, List[str]],
        ic_stability_df: pd.DataFrame,
        ic_df: pd.DataFrame = None
    ) -> List[Dict]:
        """
        Recommend which feature to keep from each cluster based on weighted score.

        Uses: Score = 0.7 * IC_Mean + 0.3 * Stability (normalized)
        This prevents pruning high-alpha features just because they're more volatile.

        Args:
            clusters: Dict from cluster_features()
            ic_stability_df: DataFrame from compute_ic_stability()
            ic_df: DataFrame from compute_ic() with raw IC values

        Returns:
            List of dicts with cluster info and recommendation
        """
        if ic_stability_df.empty:
            return []

        # Build lookups
        stability_lookup = dict(zip(
            ic_stability_df['feature'],
            ic_stability_df['ic_stability']
        ))
        ic_mean_lookup = dict(zip(
            ic_stability_df['feature'],
            ic_stability_df['ic_mean']
        ))

        # Fallback to ic_df if ic_mean not in stability
        if ic_df is not None and not ic_df.empty:
            ic_abs_lookup = dict(zip(ic_df['feature'], ic_df['ic_abs']))
        else:
            ic_abs_lookup = {}

        # Normalize stability and IC across all features for fair comparison
        all_stabilities = [abs(stability_lookup.get(f, 0)) for f in stability_lookup]
        all_ics = [abs(ic_mean_lookup.get(f, ic_abs_lookup.get(f, 0))) for f in stability_lookup]
        
        max_stability = max(all_stabilities) if all_stabilities and max(all_stabilities) > 0 else 1
        max_ic = max(all_ics) if all_ics and max(all_ics) > 0 else 1

        recommendations = []

        for cluster_name, members in clusters.items():
            if len(members) == 1:
                recommendations.append({
                    'cluster': cluster_name,
                    'members': members,
                    'keep': members[0],
                    'drop': [],
                    'reason': 'single member'
                })
                continue

            # Compute weighted score for each member: 0.7*IC + 0.3*Stability
            member_scores = []
            for m in members:
                ic_mean = abs(ic_mean_lookup.get(m, ic_abs_lookup.get(m, 0)))
                stability = abs(stability_lookup.get(m, 0))
                
                # Normalize to 0-1 scale
                ic_norm = ic_mean / max_ic if max_ic > 0 else 0
                stab_norm = stability / max_stability if max_stability > 0 else 0
                
                # Weighted score: 70% IC, 30% Stability
                weighted_score = 0.7 * ic_norm + 0.3 * stab_norm
                member_scores.append((m, weighted_score, ic_mean, stability))
            
            member_scores.sort(key=lambda x: x[1], reverse=True)

            keep = member_scores[0][0]
            keep_ic = member_scores[0][2]
            keep_stab = member_scores[0][3]
            drop = [m for m, _, _, _ in member_scores[1:]]

            recommendations.append({
                'cluster': cluster_name,
                'members': members,
                'keep': keep,
                'drop': drop,
                'reason': f'highest weighted score (IC={keep_ic:.3f}, Stab={keep_stab:.2f})'
            })

        return recommendations

    # =========================================================================
    # COMBINED ANALYSIS
    # =========================================================================

    @classmethod
    def run_full_analysis(
        cls,
        df: pd.DataFrame,
        features: List[str],
        target: str = 'return_pct',
        date_col: str = 'entry_date'
    ) -> Dict:
        """
        Run all 4 pillars of analysis.

        Args:
            df: DataFrame with features, target, and date column
            features: List of feature names to analyze
            target: Target column name
            date_col: Date column for temporal analysis

        Returns:
            Dict with all analysis results:
                - pillar1_health: {stationarity, kurtosis, missingness}
                - pillar2_power: {ic, mutual_info, monotonicity}
                - pillar3_stability: {ic_stability, psi}
                - pillar4_interaction: {clusters, recommendations}
                - composite_scores: Combined scoring DataFrame
        """
        valid_features = [f for f in features if f in df.columns]
        logger.info(f"Running full analysis on {len(valid_features)} features")

        results = {}

        # Pillar 1: Distributional Health
        logger.info("Pillar 1: Distributional Health")
        results['pillar1_health'] = {
            'stationarity': cls.check_stationarity(df, valid_features),
            'kurtosis': cls.compute_kurtosis(df, valid_features),
            'missingness': cls.analyze_missingness(df, valid_features, target)
        }

        # Pillar 2: Predictive Power
        logger.info("Pillar 2: Predictive Power")
        results['pillar2_power'] = {
            'ic': cls.compute_ic(df, valid_features, target),
            'mutual_info': cls.compute_mutual_information(df, valid_features, target),
            'monotonicity': cls.analyze_decile_monotonicity(df, valid_features, target)
        }

        # Pillar 3: Temporal Stability
        logger.info("Pillar 3: Temporal Stability")
        try:
            results['pillar3_stability'] = {
                'ic_stability': cls.compute_ic_stability(df, valid_features, target, date_col),
                'psi': cls.compute_psi(df, valid_features, date_col)
            }
        except ValueError as e:
            logger.warning(f"Skipping temporal analysis: {e}")
            results['pillar3_stability'] = {
                'ic_stability': pd.DataFrame(),
                'psi': pd.DataFrame()
            }

        # Pillar 4: Interaction
        logger.info("Pillar 4: Feature Interaction")
        clusters = cls.cluster_features(df, valid_features)
        ic_stability_df = results['pillar3_stability']['ic_stability']
        ic_df = results['pillar2_power']['ic']
        recommendations = cls.get_cluster_recommendations(clusters, ic_stability_df, ic_df)

        results['pillar4_interaction'] = {
            'clusters': clusters,
            'recommendations': recommendations
        }

        # Composite Scores (40% IC + 30% Stability + 30% KS)
        logger.info("Computing composite scores")
        results['composite_scores'] = cls._compute_composite_scores(results)

        return results

    @classmethod
    def _compute_composite_scores(cls, analysis_results: Dict) -> pd.DataFrame:
        """
        Compute composite score: 40% IC + 30% Stability + 30% KS equivalent.

        Uses ic_abs for predictive power, ic_stability for stability,
        and monotonicity_score as KS proxy.
        """
        ic_df = analysis_results['pillar2_power']['ic']
        stability_df = analysis_results['pillar3_stability']['ic_stability']
        mono_df = analysis_results['pillar2_power']['monotonicity']

        if ic_df.empty:
            return pd.DataFrame()

        # Start with IC data
        composite = ic_df[['feature', 'ic_abs']].copy()
        composite = composite.rename(columns={'ic_abs': 'ic_score'})

        # Normalize IC to 0-1
        max_ic = composite['ic_score'].max()
        if max_ic > 0:
            composite['ic_score'] = composite['ic_score'] / max_ic

        # Merge stability
        if not stability_df.empty:
            stability_lookup = dict(zip(stability_df['feature'], stability_df['ic_stability']))
            composite['stability_score'] = composite['feature'].map(stability_lookup).fillna(0)

            # Normalize stability to 0-1
            max_stab = composite['stability_score'].abs().max()
            if max_stab > 0:
                composite['stability_score'] = composite['stability_score'].abs() / max_stab
        else:
            composite['stability_score'] = 0.5  # Default if no temporal data

        # Merge monotonicity (as KS proxy)
        if not mono_df.empty:
            mono_lookup = dict(zip(mono_df['feature'], mono_df['monotonicity_score']))
            composite['ks_score'] = composite['feature'].map(mono_lookup).fillna(0)
        else:
            composite['ks_score'] = 0.5

        # Composite: 40% IC + 30% Stability + 30% KS
        composite['composite'] = (
            0.4 * composite['ic_score'] +
            0.3 * composite['stability_score'] +
            0.3 * composite['ks_score']
        )

        # Add signal type from monotonicity
        if not mono_df.empty:
            signal_lookup = dict(zip(mono_df['feature'], mono_df['signal_type']))
            composite['signal_type'] = composite['feature'].map(signal_lookup).fillna('unknown')
        else:
            composite['signal_type'] = 'unknown'

        return composite.sort_values('composite', ascending=False)
