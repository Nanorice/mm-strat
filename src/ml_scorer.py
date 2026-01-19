"""
ML Scorer Module - Production ML Inference for SEPA Scanner

This module provides ML scoring functionality for live scanner integration.
Loads trained models, handles feature alignment, and scores SEPA candidates.

Key Features:
- Strict feature alignment with training data
- Metadata validation (model version, feature names)
- Prediction logging for feedback loop
- Robust error handling

Usage:
    from src.ml_scorer import MLScorer

    scorer = MLScorer(model_path='models/model_fold_1.json')
    probabilities, ranks = scorer.score_batch(candidates_df)
"""

import pandas as pd
import numpy as np
import xgboost as xgb
import json
from pathlib import Path
from typing import Dict, Tuple, Optional, List
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MLScorer:
    """
    ML scoring for SEPA signal ranking.

    Handles:
    - Model loading with metadata validation
    - Feature alignment (reordering, missing feature handling)
    - Batch prediction with ranking
    - Prediction logging for retraining
    """

    def __init__(
        self,
        model_path: str,
        metadata_path: Optional[str] = None,
        log_predictions: bool = True,
        log_path: str = 'data/predictions_log.parquet'
    ):
        """
        Initialize ML scorer.

        Args:
            model_path: Path to trained XGBoost model (.json)
            metadata_path: Path to model metadata (.json), auto-detected if None
            log_predictions: Whether to log predictions for retraining (default: True)
            log_path: Path to prediction log file (default: data/predictions_log.parquet)
        """
        self.model_path = Path(model_path)
        self.log_predictions = log_predictions
        self.log_path = Path(log_path)

        # Auto-detect metadata path
        if metadata_path is None:
            # Handle different naming patterns:
            # models/model_fold_1.json -> models/model_metadata_fold_1.json
            # models/model_m01.json -> models/model_m01_config.json
            # models/model.json -> models/model_metadata.json
            model_name = self.model_path.stem  # e.g., 'model_fold_1' or 'model_m01'
            
            # Try multiple patterns in order of preference
            candidate_patterns = []
            if 'fold' in model_name:
                # Extract fold number and reconstruct metadata name
                candidate_patterns.append(model_name.replace('model_fold_', 'model_metadata_fold_') + '.json')
            # Try *_config.json pattern (e.g., model_m01 -> model_m01_config.json)
            candidate_patterns.append(model_name + '_config.json')
            # Try model_metadata pattern
            candidate_patterns.append(model_name.replace('model', 'model_metadata') + '.json')
            
            # Find first existing metadata file
            for pattern in candidate_patterns:
                candidate_path = self.model_path.parent / pattern
                if candidate_path.exists():
                    metadata_path = candidate_path
                    break
            else:
                # Default to first pattern if none exist (will raise error later)
                metadata_path = self.model_path.parent / candidate_patterns[0]
        self.metadata_path = Path(metadata_path)

        # Load model and metadata
        self.model = None
        self.metadata = None
        self.feature_names = None
        self.model_version = None

        self._load_model()
        self._load_metadata()

        logger.info(f"MLScorer initialized with model: {self.model_path.name}")
        logger.info(f"  Features required: {len(self.feature_names)}")
        logger.info(f"  Model version: {self.model_version}")
        logger.info(f"  Prediction logging: {'ON' if self.log_predictions else 'OFF'}")

    def _load_model(self):
        """Load XGBoost model from file."""
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {self.model_path}")

        self.model = xgb.Booster()
        self.model.load_model(str(self.model_path))
        logger.info(f"Model loaded: {self.model_path}")

    def _load_metadata(self):
        """Load model metadata (feature names, version, etc.)."""
        if not self.metadata_path.exists():
            raise FileNotFoundError(
                f"Model metadata not found: {self.metadata_path}\n"
                f"Run training with save_model() to generate metadata."
            )

        with open(self.metadata_path, 'r') as f:
            self.metadata = json.load(f)

        # Extract critical info - support both naming conventions
        self.feature_names = self.metadata.get('feature_names') or self.metadata.get('feature_columns')
        self.model_version = self.metadata.get('training_date') or self.metadata.get('created_at', 'unknown')

        if not self.feature_names:
            raise ValueError("Metadata missing 'feature_names' or 'feature_columns'. Cannot align features.")

        # Detect model type
        model_type = self.metadata.get('model_type')
        objective = self.metadata.get('objective', '')

        # Determine if this is a regression or classification model
        if model_type == 'regression' or 'reg:' in objective:
            self.is_regressor = True
            self.output_format = 'return_pct'
        else:
            self.is_regressor = False
            self.output_format = 'probability'

        logger.info(f"Metadata loaded: {len(self.feature_names)} features expected")
        logger.info(f"Model type: {'Regression' if self.is_regressor else 'Classification'}")

    def _align_features(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Align input features to match model expectations.

        Critical for XGBoost:
        - Features must be in exact same order as training
        - Missing features are filled with NaN
        - Extra features are ignored

        Args:
            X: Input DataFrame with features

        Returns:
            Aligned DataFrame with correct features and order
        """
        # Check for missing features
        missing_features = set(self.feature_names) - set(X.columns)
        if missing_features:
            logger.warning(f"Missing {len(missing_features)} features: {list(missing_features)[:5]}...")
            for feat in missing_features:
                X[feat] = np.nan

        # Select and reorder to match training
        X_aligned = X[self.feature_names].copy()

        # Handle infinite values (XGBoost requirement)
        X_aligned = X_aligned.replace([np.inf, -np.inf], np.nan)

        return X_aligned

    def score_batch(
        self,
        X: pd.DataFrame,
        ticker_column: str = 'ticker',
        date_column: Optional[str] = None
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Score a batch of SEPA candidates.

        Args:
            X: DataFrame with features (must include all model features)
            ticker_column: Name of ticker column (for logging)
            date_column: Name of date column (for logging), uses today if None

        Returns:
            Tuple of (probabilities, ranks)
            - probabilities: Array of success probabilities (0.0-1.0)
            - ranks: Array of ranks (1=best, 2=second best, etc.)
        """
        if len(X) == 0:
            logger.warning("Empty input DataFrame, returning empty results")
            return np.array([]), np.array([])

        # Align features
        X_aligned = self._align_features(X)

        # Create DMatrix
        dmatrix = xgb.DMatrix(X_aligned, enable_categorical=False)

        # Predict probabilities
        probabilities = self.model.predict(dmatrix)

        # Calculate ranks (1=best)
        ranks = self._calculate_ranks(probabilities)

        # Log predictions if enabled
        if self.log_predictions:
            self._log_predictions(X, probabilities, ranks, ticker_column, date_column)

        logger.info(f"Scored {len(X)} candidates: prob range [{probabilities.min():.3f}, {probabilities.max():.3f}]")

        return probabilities, ranks

    def _calculate_ranks(self, probabilities: np.ndarray) -> np.ndarray:
        """
        Calculate ranks from probabilities (1=best).

        Args:
            probabilities: Array of probabilities

        Returns:
            Array of ranks (1-indexed)
        """
        # argsort gives indices from low to high, reverse for high to low
        sorted_indices = np.argsort(probabilities)[::-1]

        # Create rank array
        ranks = np.empty_like(sorted_indices)
        ranks[sorted_indices] = np.arange(1, len(probabilities) + 1)

        return ranks

    def _log_predictions(
        self,
        X: pd.DataFrame,
        probabilities: np.ndarray,
        ranks: np.ndarray,
        ticker_column: str,
        date_column: Optional[str]
    ):
        """
        Log predictions for future retraining and analysis.

        Logs:
        - Ticker
        - Prediction date
        - ML probability
        - Rank
        - Model version
        - (Actual outcome filled in later when trade closes)

        Args:
            X: Input DataFrame
            probabilities: Predicted probabilities
            ranks: Calculated ranks
            ticker_column: Name of ticker column
            date_column: Name of date column
        """
        # Create log entry
        log_df = pd.DataFrame({
            'ticker': X[ticker_column].values if ticker_column in X.columns else ['UNKNOWN'] * len(X),
            'prediction_date': pd.to_datetime(X[date_column].values) if date_column and date_column in X.columns else pd.Timestamp.now(),
            'ml_probability': probabilities,
            'ml_rank': ranks,
            'model_version': self.model_version,
            'model_path': str(self.model_path.name),
            'actual_return_pct': np.nan,  # Filled in later
            'actual_label': np.nan,        # Filled in later
            'logged_at': pd.Timestamp.now()
        })

        # Append to log file
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        if self.log_path.exists():
            # Append to existing log
            existing_log = pd.read_parquet(self.log_path)
            combined_log = pd.concat([existing_log, log_df], ignore_index=True)
            combined_log.to_parquet(self.log_path, index=False)
        else:
            # Create new log
            log_df.to_parquet(self.log_path, index=False)

        logger.debug(f"Logged {len(log_df)} predictions to {self.log_path}")

    def filter_by_threshold(
        self,
        X: pd.DataFrame,
        probabilities: np.ndarray,
        ranks: np.ndarray,
        threshold: float = 0.6,
        top_n: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Filter candidates by probability threshold and/or top-N ranking.

        Strategy:
        - Filter: probability >= threshold
        - If top_n specified: Take only top N ranked signals
        - Sort by rank (best first)

        Args:
            X: Input DataFrame
            probabilities: Predicted probabilities
            ranks: Calculated ranks
            threshold: Minimum probability to keep (default: 0.6)
            top_n: Maximum number of signals to keep (default: None = no limit)

        Returns:
            Filtered DataFrame with ml_probability and ml_rank columns added
        """
        # Add ML columns
        result_df = X.copy()
        result_df['ml_probability'] = probabilities
        result_df['ml_rank'] = ranks

        # Filter by threshold
        filtered = result_df[result_df['ml_probability'] >= threshold].copy()

        logger.info(f"Threshold filter ({threshold}): {len(result_df)} → {len(filtered)} candidates")

        # Filter by top-N if specified
        if top_n is not None and len(filtered) > top_n:
            filtered = filtered.nsmallest(top_n, 'ml_rank')
            logger.info(f"Top-{top_n} filter: {len(filtered)} candidates selected")

        # Sort by rank (best first)
        filtered = filtered.sort_values('ml_rank')

        return filtered

    def get_model_info(self) -> Dict:
        """
        Get model information for display/logging.

        Returns:
            Dictionary with model metadata
        """
        return {
            'model_path': str(self.model_path),
            'model_version': self.model_version,
            'num_features': len(self.feature_names),
            'feature_names': self.feature_names,
            'metadata': self.metadata
        }


def update_prediction_log_with_outcome(
    ticker: str,
    prediction_date: str,
    actual_return_pct: float,
    actual_label: int,
    log_path: str = 'data/predictions_log.parquet'
):
    """
    Update prediction log with actual trade outcome (for retraining).

    Call this when a trade closes to record actual performance.

    Args:
        ticker: Stock ticker
        prediction_date: Date when prediction was made (YYYY-MM-DD)
        actual_return_pct: Actual return percentage
        actual_label: Actual label (0=failure, 1=success)
        log_path: Path to prediction log file
    """
    log_path = Path(log_path)

    if not log_path.exists():
        logger.warning(f"Prediction log not found: {log_path}")
        return

    # Load log
    log_df = pd.read_parquet(log_path)

    # Find matching prediction
    prediction_date = pd.to_datetime(prediction_date)
    mask = (log_df['ticker'] == ticker) & (log_df['prediction_date'] == prediction_date)

    if mask.sum() == 0:
        logger.warning(f"No prediction found for {ticker} on {prediction_date.date()}")
        return

    # Update outcome
    log_df.loc[mask, 'actual_return_pct'] = actual_return_pct
    log_df.loc[mask, 'actual_label'] = actual_label

    # Save updated log
    log_df.to_parquet(log_path, index=False)

    logger.info(f"Updated outcome for {ticker} ({prediction_date.date()}): {actual_return_pct:.2f}%, label={actual_label}")


def analyze_prediction_accuracy(log_path: str = 'data/predictions_log.parquet') -> Dict:
    """
    Analyze prediction log to assess model performance.

    Metrics:
    - Overall accuracy
    - Precision by probability bucket
    - Calibration (predicted prob vs actual win rate)
    - Top-N precision

    Args:
        log_path: Path to prediction log file

    Returns:
        Dictionary with analysis results
    """
    log_path = Path(log_path)

    if not log_path.exists():
        logger.warning(f"Prediction log not found: {log_path}")
        return {}

    # Load log
    log_df = pd.read_parquet(log_path)

    # Filter to completed predictions (with actual outcomes)
    completed = log_df[log_df['actual_label'].notna()].copy()

    if len(completed) == 0:
        logger.warning("No completed predictions found")
        return {'total_predictions': len(log_df), 'completed_predictions': 0}

    # Overall metrics
    accuracy = (completed['actual_label'] == (completed['ml_probability'] >= 0.5)).mean()
    win_rate = completed['actual_label'].mean()

    # Precision by probability bucket
    completed['prob_bucket'] = pd.cut(
        completed['ml_probability'],
        bins=[0, 0.3, 0.5, 0.7, 0.9, 1.0],
        labels=['0-30%', '30-50%', '50-70%', '70-90%', '90-100%']
    )
    precision_by_bucket = completed.groupby('prob_bucket')['actual_label'].agg(['mean', 'count'])

    # Top-N precision
    top_10_precision = completed.nsmallest(10, 'ml_rank')['actual_label'].mean() if len(completed) >= 10 else np.nan
    top_20_precision = completed.nsmallest(20, 'ml_rank')['actual_label'].mean() if len(completed) >= 20 else np.nan

    # Calibration (predicted vs actual)
    calibration = {}
    for threshold in [0.5, 0.6, 0.7, 0.8]:
        subset = completed[completed['ml_probability'] >= threshold]
        if len(subset) > 0:
            calibration[f'prob>={threshold}'] = {
                'count': len(subset),
                'actual_win_rate': subset['actual_label'].mean()
            }

    return {
        'total_predictions': len(log_df),
        'completed_predictions': len(completed),
        'overall_accuracy': accuracy,
        'overall_win_rate': win_rate,
        'precision_by_bucket': precision_by_bucket.to_dict(),
        'top_10_precision': top_10_precision,
        'top_20_precision': top_20_precision,
        'calibration': calibration
    }


if __name__ == "__main__":
    # Example usage
    import argparse

    parser = argparse.ArgumentParser(description="Test ML scorer")
    parser.add_argument('--model', type=str, default='models/model_fold_1.json', help='Model path')
    parser.add_argument('--test-data', type=str, help='Test data path (parquet)')

    args = parser.parse_args()

    # Initialize scorer
    scorer = MLScorer(model_path=args.model)

    # Show model info
    info = scorer.get_model_info()
    print("\nModel Info:")
    print(f"  Path: {info['model_path']}")
    print(f"  Version: {info['model_version']}")
    print(f"  Features: {info['num_features']}")

    # Test on sample data if provided
    if args.test_data:
        test_df = pd.read_parquet(args.test_data)
        print(f"\nScoring {len(test_df)} candidates...")

        probabilities, ranks = scorer.score_batch(test_df, ticker_column='ticker')

        # Show top 10
        test_df['ml_probability'] = probabilities
        test_df['ml_rank'] = ranks

        top_10 = test_df.nsmallest(10, 'ml_rank')[['ticker', 'ml_probability', 'ml_rank']]
        print("\nTop 10 Candidates:")
        print(top_10)
