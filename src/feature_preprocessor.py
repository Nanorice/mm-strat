"""
Feature Preprocessor - Fit/Transform Pattern for Fat-Tail Transformations

This module implements a scikit-learn style fit/transform pattern for feature
preprocessing. It ensures consistent transforms between training and inference.

Key Design:
- fit(): Learn transform bounds from historical (training) data
- transform(): Apply transforms using saved bounds
- save()/load(): Persist config to JSON for inference

Usage:
    # Training
    preprocessor = FeaturePreprocessor()
    preprocessor.fit(d2, features, target='return_pct')
    d2_transformed = preprocessor.transform(d2)
    preprocessor.save('models/preprocessing_config.json')
    
    # Inference
    preprocessor = FeaturePreprocessor.load('models/preprocessing_config.json')
    features_transformed = preprocessor.transform(scanner_features)
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


# Feature taxonomy (same as feature_screener.py)
EXPLOSIVE_FEATURES = [
    # Volume metrics (power law distributions)
    'volume_acceleration', 'Dry_Up_Volume', 'Vol_Ratio', 'volume_ratio',
    # Growth rates (can be extreme positive or negative)
    'revenue_accel', 'eps_accel', 'revenue_growth_yoy', 'eps_growth_yoy',
    # Valuation ratios (can balloon to 500+)
    'pe_ratio', 'ps_ratio', 'pb_ratio',
    # MA distances - SEPA "Power Trend" signals
    'Price_vs_SMA_50', 'Price_vs_SMA_150', 'Price_vs_SMA_200',
    # Distance from 52W extremes - leadership proxy
    'Dist_From_52W_Low', 'Dist_From_52W_High',
    # Volatility and relative strength
    'nATR', 'RS', 'RS_line', 'relative_strength',
    # Momentum features (high kurtosis, extreme outliers)
    'breakout_momentum', 'price_momentum_curve',
    # WorldQuant alphas (extreme outliers)
    'alpha009',
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

BOUNDED_FEATURES = ['RSI_14', 'RSI_5', 'RSI_21', 'earnings_quality_score']


class FeaturePreprocessor:
    """
    Fit/Transform pattern for feature preprocessing.
    
    Implements two transform types:
    - Log: sign(x) * log(1 + |x|) for explosive features
    - Winsorize: clip to fitted percentile bounds for standard features
    
    Features are renamed with prefix:
    - log_: Log-transformed features
    - Original name: Kept for winsorized features (in-place clipping)
    """
    
    def __init__(
        self,
        kurtosis_threshold: float = 10.0,
        tail_alpha_threshold: float = 1.2,
        lower_percentile: float = 1.0,
        upper_percentile: float = 99.0
    ):
        """
        Initialize preprocessor.
        
        Args:
            kurtosis_threshold: Only transform high-kurtosis features (default: 10)
            tail_alpha_threshold: TAR above which to log transform (default: 1.2)
            lower_percentile: Lower percentile for winsorization (default: 1%)
            upper_percentile: Upper percentile for winsorization (default: 99%)
        """
        self.kurtosis_threshold = kurtosis_threshold
        self.tail_alpha_threshold = tail_alpha_threshold
        self.lower_percentile = lower_percentile
        self.upper_percentile = upper_percentile
        
        self.config: Dict = {}
        self.is_fitted = False
        self.created_at: Optional[str] = None
    
    @staticmethod
    def signed_log(x: np.ndarray) -> np.ndarray:
        """Apply signed log: sign(x) * log(1 + |x|)"""
        return np.sign(x) * np.log1p(np.abs(x))
    
    @staticmethod
    def compute_tail_alpha_ratio(
        df: pd.DataFrame,
        feature: str,
        target: str = 'return_pct'
    ) -> float:
        """
        Compute TAR to determine if tail values are predictive.
        
        TAR = Mean |return| in 99-100th pct / Mean |return| in 10-90th pct
        """
        if feature not in df.columns or target not in df.columns:
            return 1.0
            
        subset = df[[feature, target]].dropna()
        if len(subset) < 1000:
            return 1.0
            
        core_low = np.percentile(subset[feature], 10)
        core_high = np.percentile(subset[feature], 90)
        tail_low = np.percentile(subset[feature], 99)
        
        core_mask = (subset[feature] >= core_low) & (subset[feature] <= core_high)
        core_return = subset.loc[core_mask, target].abs().mean()
        
        tail_mask = subset[feature] >= tail_low
        tail_return = subset.loc[tail_mask, target].abs().mean()
        
        if core_return == 0 or np.isnan(core_return):
            return 1.0
            
        return tail_return / core_return
    
    def fit(
        self,
        df: pd.DataFrame,
        features: List[str],
        target: str = 'return_pct'
    ) -> 'FeaturePreprocessor':
        """
        Learn transform bounds from training data.
        
        For each high-kurtosis feature:
        - Explosive → mark for log transform (no bounds needed)
        - Standard → store 1st/99th percentile bounds
        - Unknown → use TAR to decide
        
        Args:
            df: Training DataFrame
            features: Feature column names to consider
            target: Target column for TAR calculation
            
        Returns:
            self (for method chaining)
        """
        from src.feature_config import CATEGORICAL_FEATURES

        self.config = {
            'version': '1.0',
            'kurtosis_threshold': self.kurtosis_threshold,
            'tail_alpha_threshold': self.tail_alpha_threshold,
            'lower_percentile': self.lower_percentile,
            'upper_percentile': self.upper_percentile,
            'requested_features': features,  # Store for validation
            'features': {}
        }

        for feature in features:
            if feature not in df.columns:
                continue

            # Skip categorical features (handled natively by XGBoost)
            if feature in CATEGORICAL_FEATURES:
                continue

            series = df[feature].dropna()
            if len(series) < 100:
                continue

            # Compute kurtosis for all features (used for diagnostics and unknown features)
            kurt = stats.kurtosis(series, fisher=True)
            feature_config = {'original_kurtosis': float(kurt)}

            # Decision tree - Manual curation overrides statistical heuristics
            if feature in BOUNDED_FEATURES:
                # Always winsorize bounded features
                lower = float(np.percentile(series, self.lower_percentile))
                upper = float(np.percentile(series, self.upper_percentile))
                feature_config.update({
                    'transform': 'winsorize',
                    'category': 'bounded',
                    'lower_bound': lower,
                    'upper_bound': upper
                })

            elif feature in EXPLOSIVE_FEATURES:
                # Always log transform explosive features (bypass kurtosis check)
                feature_config.update({
                    'transform': 'log',
                    'category': 'explosive'
                })

            elif feature in STANDARD_FEATURES:
                # Always winsorize standard features
                lower = float(np.percentile(series, self.lower_percentile))
                upper = float(np.percentile(series, self.upper_percentile))
                feature_config.update({
                    'transform': 'winsorize',
                    'category': 'standard',
                    'lower_bound': lower,
                    'upper_bound': upper
                })

            else:
                # Unknown feature - apply kurtosis check and TAR heuristic
                if abs(kurt) <= self.kurtosis_threshold:
                    # Normal distribution, skip preprocessing
                    continue

                tar = self.compute_tail_alpha_ratio(df, feature, target)
                feature_config['tail_alpha_ratio'] = float(tar)

                if tar > self.tail_alpha_threshold:
                    feature_config.update({
                        'transform': 'log',
                        'category': 'tar_based'
                    })
                else:
                    lower = float(np.percentile(series, self.lower_percentile))
                    upper = float(np.percentile(series, self.upper_percentile))
                    feature_config.update({
                        'transform': 'winsorize',
                        'category': 'tar_based',
                        'lower_bound': lower,
                        'upper_bound': upper
                    })
            
            self.config['features'][feature] = feature_config
        
        self.is_fitted = True
        self.created_at = datetime.now().isoformat()
        self.config['created_at'] = self.created_at
        
        log_count = sum(1 for f in self.config['features'].values() if f['transform'] == 'log')
        win_count = sum(1 for f in self.config['features'].values() if f['transform'] == 'winsorize')
        logger.info(f"Fitted preprocessor: {log_count} log transforms, {win_count} winsorizations")

        # Validate that manually curated features were fitted correctly
        self._validate_manual_curation()

        return self

    def _validate_manual_curation(self) -> None:
        """
        Validate that manually curated features (EXPLOSIVE_FEATURES, BOUNDED_FEATURES, STANDARD_FEATURES)
        that were REQUESTED for fitting have the expected transformations.

        Only checks features that:
        1. Are in the curation lists AND
        2. Were requested in the fit() call (i.e., in requested_features)

        Raises:
            ValueError: If any requested curated feature has wrong transform
        """
        fitted_features = set(self.config['features'].keys())
        requested_features = set(self.config.get('requested_features', []))
        errors = []

        # Check EXPLOSIVE_FEATURES (only those that were requested)
        for feature in EXPLOSIVE_FEATURES:
            if feature in requested_features:
                if feature not in fitted_features:
                    errors.append(f"[ERR] EXPLOSIVE feature '{feature}' not fitted (expected log transform)")
                elif self.config['features'][feature]['transform'] != 'log':
                    actual = self.config['features'][feature]['transform']
                    errors.append(f"[ERR] EXPLOSIVE feature '{feature}' has '{actual}' transform (expected log)")

        # Check BOUNDED_FEATURES (only those that were requested)
        for feature in BOUNDED_FEATURES:
            if feature in requested_features:
                if feature not in fitted_features:
                    errors.append(f"[ERR] BOUNDED feature '{feature}' not fitted (expected winsorize)")
                elif self.config['features'][feature]['transform'] != 'winsorize':
                    actual = self.config['features'][feature]['transform']
                    errors.append(f"[ERR] BOUNDED feature '{feature}' has '{actual}' transform (expected winsorize)")

        # Check STANDARD_FEATURES (only those that were requested)
        for feature in STANDARD_FEATURES:
            if feature in requested_features:
                if feature not in fitted_features:
                    errors.append(f"[ERR] STANDARD feature '{feature}' not fitted (expected winsorize)")
                elif self.config['features'][feature]['transform'] != 'winsorize':
                    actual = self.config['features'][feature]['transform']
                    errors.append(f"[ERR] STANDARD feature '{feature}' has '{actual}' transform (expected winsorize)")

        if errors:
            error_msg = "Manual curation validation failed:\n" + "\n".join(errors)
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Count how many curated features were validated
        explosive_count = len([f for f in EXPLOSIVE_FEATURES if f in requested_features])
        bounded_count = len([f for f in BOUNDED_FEATURES if f in requested_features])
        standard_count = len([f for f in STANDARD_FEATURES if f in requested_features])
        logger.info(f"[OK] Validated {explosive_count} explosive, {bounded_count} bounded, {standard_count} standard features")
    
    def transform(self, df: pd.DataFrame, inplace: bool = False) -> pd.DataFrame:
        """
        Apply transforms using fitted bounds.
        
        Log-transformed features get `log_` prefix.
        Winsorized features are clipped in-place (no rename).
        
        Args:
            df: DataFrame to transform
            inplace: If True, modify df in place
            
        Returns:
            Transformed DataFrame
        """
        if not self.is_fitted:
            raise ValueError("Preprocessor not fitted. Call fit() first or load().")
        
        if not inplace:
            df = df.copy()

        # Remove existing log_ columns that will be recreated to prevent duplicates
        log_cols_to_create = [f'log_{f}' for f, fc in self.config['features'].items()
                             if fc['transform'] == 'log' and f in df.columns]
        existing_log_cols = [c for c in log_cols_to_create if c in df.columns]
        if existing_log_cols:
            logger.debug(f"Removing {len(existing_log_cols)} existing log_ columns to prevent duplicates")
            df = df.drop(columns=existing_log_cols)

        # Collect all log-transformed columns first, then concat to avoid fragmentation
        log_columns = {}

        for feature, fconfig in self.config['features'].items():
            if feature not in df.columns:
                continue
            
            transform_type = fconfig['transform']
            
            if transform_type == 'log':
                # Collect log-transformed columns
                new_col = f'log_{feature}'
                log_columns[new_col] = self.signed_log(df[feature].values)
                logger.debug(f"Created {new_col} (log transform)")
                
            elif transform_type == 'winsorize':
                # Clip in place using fitted bounds
                lower = fconfig['lower_bound']
                upper = fconfig['upper_bound']
                df[feature] = df[feature].clip(lower=lower, upper=upper)
                logger.debug(f"Winsorized {feature}: [{lower:.4f}, {upper:.4f}]")
        
        # Add all log columns at once using pd.concat to avoid fragmentation
        if log_columns:
            log_df = pd.DataFrame(log_columns, index=df.index)

            # Double-check for any overlapping columns before concat
            overlapping = set(log_df.columns) & set(df.columns)
            if overlapping:
                logger.warning(f"Found {len(overlapping)} overlapping columns before concat: {list(overlapping)[:5]}")
                df = df.drop(columns=list(overlapping))

            df = pd.concat([df, log_df], axis=1)

        return df
    
    def get_transformed_feature_names(self, original_features: List[str]) -> List[str]:
        """
        Get the transformed feature names for a list of original features.
        
        Use this to update M01_FEATURES after preprocessing.
        
        Args:
            original_features: Original feature names
            
        Returns:
            List with log_ prefixed names where applicable
        """
        result = []
        for feature in original_features:
            if feature in self.config.get('features', {}):
                fconfig = self.config['features'][feature]
                if fconfig['transform'] == 'log':
                    result.append(f'log_{feature}')
                else:
                    result.append(feature)
            else:
                result.append(feature)
        return result
    
    def save(self, path: str) -> None:
        """
        Save config to JSON file.
        
        Args:
            path: Output path for JSON config
        """
        if not self.is_fitted:
            raise ValueError("Cannot save unfitted preprocessor.")
        
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2)
        
        logger.info(f"Saved preprocessing config to {path}")
    
    @classmethod
    def load(cls, path: str) -> 'FeaturePreprocessor':
        """
        Load config from JSON file.
        
        Args:
            path: Path to JSON config
            
        Returns:
            Fitted FeaturePreprocessor instance
        """
        with open(path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        preprocessor = cls(
            kurtosis_threshold=config.get('kurtosis_threshold', 10.0),
            tail_alpha_threshold=config.get('tail_alpha_threshold', 1.2),
            lower_percentile=config.get('lower_percentile', 1.0),
            upper_percentile=config.get('upper_percentile', 99.0)
        )
        preprocessor.config = config
        preprocessor.is_fitted = True
        preprocessor.created_at = config.get('created_at')
        
        log_count = sum(1 for f in config['features'].values() if f['transform'] == 'log')
        win_count = sum(1 for f in config['features'].values() if f['transform'] == 'winsorize')
        logger.info(f"Loaded preprocessing config: {log_count} log, {win_count} winsorize")
        
        return preprocessor
    
    def summary(self) -> pd.DataFrame:
        """
        Get summary DataFrame of fitted transforms.
        
        Returns:
            DataFrame with feature, transform, category, bounds info
        """
        if not self.is_fitted:
            return pd.DataFrame()
        
        rows = []
        for feature, fconfig in self.config['features'].items():
            row = {
                'feature': feature,
                'transform': fconfig['transform'],
                'category': fconfig.get('category', 'unknown'),
                'kurtosis': fconfig.get('original_kurtosis'),
                'tar': fconfig.get('tail_alpha_ratio'),
                'lower_bound': fconfig.get('lower_bound'),
                'upper_bound': fconfig.get('upper_bound'),
                'new_name': f"log_{feature}" if fconfig['transform'] == 'log' else feature
            }
            rows.append(row)
        
        return pd.DataFrame(rows)
