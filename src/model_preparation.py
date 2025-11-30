"""
Model Preparation Module - Temporal Splitting & Feature Selection

This module handles:
1. Temporal train/test splitting with purge gap (Walk-Forward Validation)
2. Feature selection (correlation filter + SHAP importance)
3. Data preprocessing and validation

Key Principles:
- NO random shuffling (prevents look-ahead bias)
- Expanding window validation (train on all history, test on future)
- Purge gap to prevent trade overlap leakage
- Split on entry_date (simulates reality)
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from pathlib import Path
import logging
from datetime import timedelta
from scipy.stats import spearmanr
import warnings

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TemporalSplitter:
    """
    Walk-Forward Validation with Expanding Window and Purge Gap.

    Implements the "Time Trap" prevention strategy:
    - Expanding window: Train on all history before test period
    - Purge gap: Remove buffer period between train and test
    - Entry date splitting: Simulates real trading decisions
    """

    def __init__(
        self,
        purge_gap_days: int = 60,
        min_train_years: float = 2.0
    ):
        """
        Initialize temporal splitter.

        Args:
            purge_gap_days: Gap between train and test to prevent overlap (default: 60)
            min_train_years: Minimum training period in years (default: 2.0)
        """
        self.purge_gap_days = purge_gap_days
        self.min_train_years = min_train_years
        self.folds = []

    def create_folds(
        self,
        df: pd.DataFrame,
        date_column: str = 'entry_date',
        fold_specs: Optional[List[Tuple[str, str, str]]] = None
    ) -> List[Dict]:
        """
        Create temporal train/test folds with expanding window.

        Args:
            df: DataFrame with trades
            date_column: Column to use for temporal splitting (default: 'entry_date')
            fold_specs: List of (train_start, train_end, test_end) tuples
                       If None, uses default: [(2021, 2022, 2023), (2021, 2023, 2025)]

        Returns:
            List of fold dictionaries with train/test indices
        """
        # Ensure date column is datetime
        df[date_column] = pd.to_datetime(df[date_column])

        # Default fold specification
        if fold_specs is None:
            fold_specs = [
                ('2021-01-01', '2022-12-31', '2023-12-31'),  # Fold 1: 2y train → 1y test
                ('2021-01-01', '2023-12-31', '2025-12-31')   # Fold 2: 3y train → 1.9y test
            ]

        logger.info(f"Creating {len(fold_specs)} temporal folds with {self.purge_gap_days}-day purge gap")

        self.folds = []

        for fold_idx, (train_start, train_end, test_end) in enumerate(fold_specs, 1):
            train_start_dt = pd.to_datetime(train_start)
            train_end_dt = pd.to_datetime(train_end)
            test_end_dt = pd.to_datetime(test_end)

            # Calculate test start with purge gap
            test_start_dt = train_end_dt + timedelta(days=self.purge_gap_days)

            # Get train indices (entry_date <= train_end)
            train_mask = (df[date_column] >= train_start_dt) & (df[date_column] <= train_end_dt)
            train_indices = df[train_mask].index.tolist()

            # Get test indices (test_start < entry_date <= test_end)
            test_mask = (df[date_column] > test_start_dt) & (df[date_column] <= test_end_dt)
            test_indices = df[test_mask].index.tolist()

            # Validate fold
            if len(train_indices) == 0:
                logger.warning(f"Fold {fold_idx}: No training samples!")
                continue

            if len(test_indices) == 0:
                logger.warning(f"Fold {fold_idx}: No test samples!")
                continue

            # Check minimum training period
            train_years = (train_end_dt - train_start_dt).days / 365.25
            if train_years < self.min_train_years:
                logger.warning(
                    f"Fold {fold_idx}: Training period ({train_years:.1f}y) "
                    f"< minimum ({self.min_train_years}y)"
                )

            # Sanity check: Ensure no overlap
            train_max_date = df.loc[train_indices, date_column].max()
            test_min_date = df.loc[test_indices, date_column].min()
            actual_gap = (test_min_date - train_max_date).days

            if actual_gap < self.purge_gap_days:
                logger.error(
                    f"Fold {fold_idx}: Actual gap ({actual_gap} days) "
                    f"< purge gap ({self.purge_gap_days} days)!"
                )
                raise ValueError("Temporal leakage detected! Check fold specifications.")

            # Store fold
            fold = {
                'fold_id': fold_idx,
                'train_start': train_start_dt,
                'train_end': train_end_dt,
                'test_start': test_start_dt,
                'test_end': test_end_dt,
                'train_indices': train_indices,
                'test_indices': test_indices,
                'train_size': len(train_indices),
                'test_size': len(test_indices),
                'train_years': train_years,
                'actual_gap_days': actual_gap
            }

            self.folds.append(fold)

            logger.info(
                f"Fold {fold_idx}: Train {train_start_dt.date()} to {train_end_dt.date()} "
                f"({len(train_indices)} samples) → "
                f"Test {test_start_dt.date()} to {test_end_dt.date()} "
                f"({len(test_indices)} samples) | Gap: {actual_gap} days"
            )

        return self.folds

    def get_fold_data(
        self,
        df: pd.DataFrame,
        fold_idx: int = 0,
        feature_columns: Optional[List[str]] = None
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        """
        Get train/test data for a specific fold.

        Args:
            df: Full dataset
            fold_idx: Fold index (0-based)
            feature_columns: List of feature columns (if None, auto-detect)

        Returns:
            X_train, X_test, y_train, y_test
        """
        if fold_idx >= len(self.folds):
            raise ValueError(f"Fold {fold_idx} not found. Only {len(self.folds)} folds available.")

        fold = self.folds[fold_idx]

        # Auto-detect feature columns if not provided
        if feature_columns is None:
            # Exclude metadata, labels, and outcomes
            exclude_cols = [
                # Core metadata
                'date', 'ticker', 'trade_id', 'entry_date', 'exit_date',
                # Labels and outcomes
                'label', 'return_pct', 'days_held', 'exit_reason',
                # Trade details
                'entry_price', 'exit_price', 'stop_price',
                'max_drawdown_pct', 'max_favorable_excursion_pct',
                'r_multiple', 'sharpe_ratio', 'initial_risk_pct',
                # Simulation metadata
                'simulation_start', 'simulation_end', 'success_threshold_pct',
                # Fundamental metadata (dates, identifiers)
                'fiscal_date', 'filing_date_matched', 'fiscal_period',
                'symbol', 'fiscalYear', 'accepted_date', 'reportedCurrency',
                'cik', 'statement_type'
            ]

            # Get all numeric columns only
            numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
            feature_columns = [col for col in numeric_cols if col not in exclude_cols]

        # Get train/test splits
        train_indices = fold['train_indices']
        test_indices = fold['test_indices']

        X_train = df.loc[train_indices, feature_columns]
        X_test = df.loc[test_indices, feature_columns]
        y_train = df.loc[train_indices, 'label']
        y_test = df.loc[test_indices, 'label']

        logger.info(
            f"Fold {fold_idx}: X_train {X_train.shape}, X_test {X_test.shape}, "
            f"Win rate (train): {y_train.mean():.1%}, Win rate (test): {y_test.mean():.1%}"
        )

        return X_train, X_test, y_train, y_test


class FeatureSelector:
    """
    Feature selection with correlation filter and SHAP importance.

    Implements:
    1. Drop columns with 100% missing values
    2. Correlation filter (remove redundant features at 0.95 threshold)
    3. SHAP-based feature importance ranking
    """

    def __init__(
        self,
        correlation_threshold: float = 0.95,
        missing_threshold: float = 0.99,
        keep_top_n: Optional[int] = None
    ):
        """
        Initialize feature selector.

        Args:
            correlation_threshold: Drop features with correlation > threshold (default: 0.95)
            missing_threshold: Drop features with missing % > threshold (default: 0.99)
            keep_top_n: Keep top N features by importance (default: None = keep all)
        """
        self.correlation_threshold = correlation_threshold
        self.missing_threshold = missing_threshold
        self.keep_top_n = keep_top_n
        self.selected_features = None
        self.dropped_features = {}

    def remove_missing_features(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Remove features with excessive missing values.

        Args:
            X: Feature DataFrame

        Returns:
            Cleaned DataFrame
        """
        missing_pct = X.isnull().mean()
        high_missing = missing_pct[missing_pct > self.missing_threshold].index.tolist()

        if high_missing:
            logger.info(f"Dropping {len(high_missing)} features with >{self.missing_threshold*100}% missing:")
            for feat in high_missing:
                logger.info(f"  - {feat}: {missing_pct[feat]*100:.1f}% missing")

            self.dropped_features['high_missing'] = high_missing
            X = X.drop(columns=high_missing)

        return X

    def remove_infinite_values(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Replace infinite values with NaN (will be handled by XGBoost).

        Args:
            X: Feature DataFrame

        Returns:
            Cleaned DataFrame
        """
        # Make a copy to avoid SettingWithCopyWarning
        X = X.copy()

        # Select only numeric columns
        numeric_cols = X.select_dtypes(include=[np.number]).columns

        if len(numeric_cols) == 0:
            return X

        # Check for infinite values
        inf_mask = np.isinf(X[numeric_cols])
        inf_counts = inf_mask.sum()
        inf_cols = inf_counts[inf_counts > 0].index.tolist()

        if inf_cols:
            logger.warning(f"Found infinite values in {len(inf_cols)} columns:")
            for col in inf_cols:
                logger.warning(f"  - {col}: {inf_counts[col]} infinite values")

            # Replace inf with NaN
            X = X.replace([np.inf, -np.inf], np.nan)

        return X

    def remove_correlated_features(
        self,
        X: pd.DataFrame,
        method: str = 'spearman'
    ) -> pd.DataFrame:
        """
        Remove highly correlated features (keep simpler/standard ones).

        Strategy:
        - If SMA_50 and SMA_150 are >0.95 correlated, keep SMA_50 (simpler)
        - If alpha001 and alpha006 are correlated, keep lower-numbered alpha

        Args:
            X: Feature DataFrame
            method: Correlation method ('spearman' or 'pearson')

        Returns:
            DataFrame with redundant features removed
        """
        logger.info(f"Removing features with >{self.correlation_threshold} correlation...")

        # Calculate correlation matrix
        numeric_cols = X.select_dtypes(include=[np.number]).columns.tolist()

        if method == 'spearman':
            # Spearman is more robust to outliers
            corr_matrix = X[numeric_cols].corr(method='spearman')
        else:
            corr_matrix = X[numeric_cols].corr(method='pearson')

        # Find correlated pairs
        to_drop = set()

        for i in range(len(corr_matrix.columns)):
            for j in range(i + 1, len(corr_matrix.columns)):
                col_i = corr_matrix.columns[i]
                col_j = corr_matrix.columns[j]
                corr_value = abs(corr_matrix.iloc[i, j])

                if corr_value > self.correlation_threshold:
                    # Decide which to keep based on simplicity/standard
                    drop_col = self._choose_feature_to_drop(col_i, col_j)
                    to_drop.add(drop_col)
                    logger.info(
                        f"  Dropping {drop_col} (corr={corr_value:.3f} with {col_i if drop_col == col_j else col_j})"
                    )

        if to_drop:
            self.dropped_features['high_correlation'] = list(to_drop)
            X = X.drop(columns=list(to_drop))
            logger.info(f"Dropped {len(to_drop)} correlated features. Remaining: {len(X.columns)}")
        else:
            logger.info("No highly correlated features found.")

        return X

    def _choose_feature_to_drop(self, col_a: str, col_b: str) -> str:
        """
        Choose which feature to drop from a correlated pair.

        Strategy:
        - Keep simpler/standard features (SMA_50 over SMA_150)
        - Keep lower-numbered alphas (alpha001 over alpha006)
        - Keep shorter names (as proxy for simplicity)

        Args:
            col_a, col_b: Feature names

        Returns:
            Name of feature to drop
        """
        # Rule 1: Keep standard SMA periods (50, 150, 200)
        standard_sma = ['SMA_50', 'SMA_150', 'SMA_200']
        if col_a in standard_sma and col_b not in standard_sma:
            return col_b
        if col_b in standard_sma and col_a not in standard_sma:
            return col_a

        # Rule 2: Keep lower-numbered alphas
        if col_a.startswith('alpha') and col_b.startswith('alpha'):
            alpha_num_a = int(col_a.replace('alpha', ''))
            alpha_num_b = int(col_b.replace('alpha', ''))
            return col_a if alpha_num_a > alpha_num_b else col_b

        # Rule 3: Keep shorter names (simpler features)
        return col_a if len(col_a) > len(col_b) else col_b

    def select_by_importance(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        model: Optional[object] = None,
        method: str = 'shap'
    ) -> pd.DataFrame:
        """
        Select top features using SHAP importance.

        Args:
            X: Feature DataFrame
            y: Target labels
            model: Pre-trained model (if None, trains simple XGBoost)
            method: Importance method ('shap', 'gain', 'permutation')

        Returns:
            DataFrame with top features selected
        """
        if self.keep_top_n is None or self.keep_top_n >= len(X.columns):
            logger.info("No feature importance selection (keep_top_n not set or >= feature count)")
            return X

        logger.info(f"Selecting top {self.keep_top_n} features using {method}...")

        # Train simple model if not provided
        if model is None:
            import xgboost as xgb

            # Handle missing values for training
            X_filled = X.fillna(X.median())

            model = xgb.XGBClassifier(
                n_estimators=100,
                max_depth=3,
                learning_rate=0.1,
                random_state=42,
                eval_metric='logloss'
            )
            model.fit(X_filled, y)

        # Calculate importance
        if method == 'shap':
            importance_scores = self._calculate_shap_importance(model, X, y)
        elif method == 'gain':
            importance_scores = pd.Series(
                model.feature_importances_,
                index=X.columns
            ).sort_values(ascending=False)
        else:
            raise ValueError(f"Unknown importance method: {method}")

        # Select top features
        top_features = importance_scores.head(self.keep_top_n).index.tolist()

        logger.info(f"Top {self.keep_top_n} features selected:")
        for rank, (feat, score) in enumerate(importance_scores.head(self.keep_top_n).items(), 1):
            logger.info(f"  {rank}. {feat}: {score:.4f}")

        self.selected_features = top_features
        return X[top_features]

    def _calculate_shap_importance(
        self,
        model: object,
        X: pd.DataFrame,
        y: pd.Series,
        sample_size: int = 500
    ) -> pd.Series:
        """
        Calculate SHAP feature importance (mean absolute SHAP value).

        Args:
            model: Trained model
            X: Features
            y: Labels
            sample_size: Sample size for SHAP calculation (faster)

        Returns:
            Series with feature importance scores
        """
        try:
            import shap

            # Sample data for speed (SHAP can be slow)
            if len(X) > sample_size:
                sample_indices = np.random.choice(len(X), sample_size, replace=False)
                X_sample = X.iloc[sample_indices]
            else:
                X_sample = X

            # Fill missing values for SHAP
            X_sample_filled = X_sample.fillna(X.median())

            # Calculate SHAP values using TreeExplainer
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_sample_filled)

            # Mean absolute SHAP value per feature
            importance_scores = pd.Series(
                np.abs(shap_values).mean(axis=0),
                index=X.columns
            ).sort_values(ascending=False)

            return importance_scores

        except ImportError:
            logger.warning("SHAP not installed. Falling back to gain importance.")
            return pd.Series(
                model.feature_importances_,
                index=X.columns
            ).sort_values(ascending=False)

    def fit_transform(
        self,
        X: pd.DataFrame,
        y: Optional[pd.Series] = None
    ) -> pd.DataFrame:
        """
        Apply all feature selection steps.

        Args:
            X: Feature DataFrame
            y: Target labels (required for importance selection)

        Returns:
            Cleaned and selected features
        """
        logger.info(f"Starting feature selection: {len(X.columns)} features")

        # Step 1: Remove missing features
        X = self.remove_missing_features(X)
        logger.info(f"After missing removal: {len(X.columns)} features")

        # Step 2: Remove infinite values
        X = self.remove_infinite_values(X)

        # Step 3: Remove correlated features
        X = self.remove_correlated_features(X)
        logger.info(f"After correlation filter: {len(X.columns)} features")

        # Step 4: Select by importance (if y provided and keep_top_n set)
        if y is not None and self.keep_top_n is not None:
            X = self.select_by_importance(X, y)
            logger.info(f"After importance selection: {len(X.columns)} features")

        self.selected_features = X.columns.tolist()

        logger.info(f"Feature selection complete: {len(self.selected_features)} features selected")
        return X

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Apply feature selection to new data (using previously selected features).

        Args:
            X: Feature DataFrame

        Returns:
            DataFrame with selected features only
        """
        if self.selected_features is None:
            raise ValueError("Must call fit_transform() before transform()")

        missing_features = set(self.selected_features) - set(X.columns)
        if missing_features:
            logger.warning(f"Missing {len(missing_features)} features in new data: {missing_features}")

        available_features = [f for f in self.selected_features if f in X.columns]
        X_selected = X[available_features].copy()

        # CRITICAL: Remove infinite values (same as in fit_transform)
        X_selected = X_selected.replace([np.inf, -np.inf], np.nan)

        return X_selected


def prepare_training_data(
    dataset_path: str,
    purge_gap_days: int = 60,
    correlation_threshold: float = 0.95,
    keep_top_n: Optional[int] = None,
    fold_specs: Optional[List[Tuple[str, str, str]]] = None
) -> Dict:
    """
    Main entry point for data preparation.

    Args:
        dataset_path: Path to merged training dataset
        purge_gap_days: Gap between train/test (default: 60)
        correlation_threshold: Correlation threshold for feature selection (default: 0.95)
        keep_top_n: Keep top N features by SHAP importance (default: None)
        fold_specs: Custom fold specifications (default: None)

    Returns:
        Dictionary with folds, feature selector, and metadata
    """
    logger.info("=" * 80)
    logger.info("TRAINING DATA PREPARATION")
    logger.info("=" * 80)

    # Load data
    logger.info(f"Loading dataset: {dataset_path}")
    if dataset_path.endswith('.parquet'):
        df = pd.read_parquet(dataset_path)
    else:
        df = pd.read_csv(dataset_path, parse_dates=['entry_date', 'exit_date', 'date'])

    logger.info(f"Loaded {len(df):,} rows × {len(df.columns)} columns")
    logger.info(f"Date range: {df['entry_date'].min().date()} to {df['entry_date'].max().date()}")
    logger.info(f"Label distribution: {df['label'].value_counts().to_dict()}")

    # Create temporal folds
    splitter = TemporalSplitter(purge_gap_days=purge_gap_days)
    folds = splitter.create_folds(df, date_column='entry_date', fold_specs=fold_specs)

    # Feature selection on first fold (to get selected features)
    logger.info("\nPerforming feature selection on Fold 1...")
    X_train, _, y_train, _ = splitter.get_fold_data(df, fold_idx=0)

    selector = FeatureSelector(
        correlation_threshold=correlation_threshold,
        keep_top_n=keep_top_n
    )
    X_train_selected = selector.fit_transform(X_train, y_train)

    logger.info("\n" + "=" * 80)
    logger.info("PREPARATION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Folds created: {len(folds)}")
    logger.info(f"Features selected: {len(selector.selected_features)}")
    logger.info(f"Purge gap: {purge_gap_days} days")

    return {
        'df': df,
        'folds': folds,
        'splitter': splitter,
        'selector': selector,
        'selected_features': selector.selected_features,
        'dropped_features': selector.dropped_features
    }


if __name__ == "__main__":
    # Example usage
    import argparse

    parser = argparse.ArgumentParser(description="Prepare training data with temporal splitting")
    parser.add_argument('--dataset', type=str, required=True, help='Path to training dataset')
    parser.add_argument('--purge-gap', type=int, default=60, help='Purge gap in days (default: 60)')
    parser.add_argument('--correlation', type=float, default=0.95, help='Correlation threshold (default: 0.95)')
    parser.add_argument('--top-n', type=int, default=None, help='Keep top N features (default: None)')

    args = parser.parse_args()

    result = prepare_training_data(
        dataset_path=args.dataset,
        purge_gap_days=args.purge_gap,
        correlation_threshold=args.correlation,
        keep_top_n=args.top_n
    )

    print(f"\nSelected {len(result['selected_features'])} features:")
    print(result['selected_features'][:20], "...")
