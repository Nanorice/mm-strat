"""
Model Training Module - XGBoost with Precision Optimization

This module handles:
1. XGBoost model training with class imbalance handling (scale_pos_weight)
2. Hyperparameter optimization using Optuna (Bayesian)
3. Custom evaluation metrics (Precision@Top-20%)
4. Early stopping and validation

Key Principles:
- Optimize for Precision@k (top 20% of predictions)
- Constrain max_depth to 3-4 (prevent overfitting with limited data)
- Use scale_pos_weight for class imbalance (9:1 ratio)
- Output probability scores for ranking
"""

import pandas as pd
import numpy as np
import xgboost as xgb
from typing import Dict, List, Tuple, Optional, Callable
from pathlib import Path
import logging
import pickle
import json
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PrecisionAtK:
    """
    Custom evaluation metric for Precision@Top-K%.

    For SEPA trading:
    - We rank all predictions by probability
    - Take top K% (default: 20%)
    - Calculate precision on this subset
    """

    def __init__(self, k_pct: float = 0.2):
        """
        Initialize Precision@K metric.

        Args:
            k_pct: Percentage of top predictions to evaluate (default: 0.2 = top 20%)
        """
        self.k_pct = k_pct

    def __call__(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray
    ) -> Tuple[str, float]:
        """
        Calculate Precision@K.

        Args:
            y_true: True labels
            y_pred: Predicted probabilities

        Returns:
            (metric_name, precision_score)
        """
        # Determine k (number of top predictions)
        n_samples = len(y_true)
        k = max(1, int(n_samples * self.k_pct))

        # Get top-k indices by predicted probability
        top_k_indices = np.argsort(y_pred)[-k:]

        # Calculate precision on top-k
        precision = y_true[top_k_indices].mean()

        return f'precision@{int(self.k_pct*100)}', precision

    def xgb_metric(self, y_pred: np.ndarray, dtrain: xgb.DMatrix) -> Tuple[str, float]:
        """
        XGBoost-compatible metric function.

        Args:
            y_pred: Predicted probabilities
            dtrain: XGBoost DMatrix with labels

        Returns:
            (metric_name, precision_score)
        """
        y_true = dtrain.get_label()
        return self.__call__(y_true, y_pred)


class SEPAModelTrainer:
    """
    XGBoost trainer optimized for SEPA signal ranking.

    Features:
    - Class imbalance handling via scale_pos_weight
    - Constrained hyperparameter space (max_depth ≤ 4)
    - Precision@k optimization
    - Probability score output
    """

    def __init__(
        self,
        pos_weight: Optional[float] = None,
        max_depth_limit: int = 4,
        precision_k_pct: float = 0.2,
        random_state: int = 42
    ):
        """
        Initialize trainer.

        Args:
            pos_weight: Weight for positive class (if None, auto-calculated from data)
            max_depth_limit: Maximum tree depth (default: 4)
            precision_k_pct: Top-k% for precision metric (default: 0.2)
            random_state: Random seed (default: 42)
        """
        self.pos_weight = pos_weight
        self.max_depth_limit = max_depth_limit
        self.precision_k_pct = precision_k_pct
        self.random_state = random_state
        self.model = None
        self.best_params = None
        self.feature_names = None
        self.training_history = []

    def calculate_pos_weight(self, y: pd.Series) -> float:
        """
        Calculate scale_pos_weight from label distribution.

        Formula: (count of negative class) / (count of positive class)

        Args:
            y: Training labels

        Returns:
            Positive class weight
        """
        n_negative = (y == 0).sum()
        n_positive = (y == 1).sum()

        if n_positive == 0:
            raise ValueError("No positive samples in training data!")

        pos_weight = n_negative / n_positive
        logger.info(f"Class distribution: {n_negative} negative, {n_positive} positive")
        logger.info(f"Calculated scale_pos_weight: {pos_weight:.2f}")

        return pos_weight

    def train_baseline(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None,
        params: Optional[Dict] = None
    ) -> xgb.Booster:
        """
        Train baseline XGBoost model with default/provided parameters.

        Args:
            X_train: Training features
            y_train: Training labels
            X_val: Validation features (for early stopping)
            y_val: Validation labels
            params: Model parameters (if None, uses defaults)

        Returns:
            Trained XGBoost booster
        """
        logger.info("Training baseline XGBoost model...")

        # Calculate pos_weight if not provided
        if self.pos_weight is None:
            self.pos_weight = self.calculate_pos_weight(y_train)

        # Default parameters
        if params is None:
            params = {
                'objective': 'binary:logistic',
                'eval_metric': 'logloss',
                'max_depth': 3,
                'learning_rate': 0.05,
                'scale_pos_weight': self.pos_weight,
                'subsample': 0.8,
                'colsample_bytree': 0.8,
                'min_child_weight': 5,
                'seed': self.random_state,
                'tree_method': 'hist'
            }

        self.feature_names = X_train.columns.tolist()

        # Handle infinite values (replace with NaN, XGBoost handles NaN natively)
        X_train = X_train.replace([np.inf, -np.inf], np.nan)
        if X_val is not None:
            X_val = X_val.replace([np.inf, -np.inf], np.nan)

        # Create DMatrix
        dtrain = xgb.DMatrix(X_train, label=y_train, enable_categorical=False)

        # Custom eval metric
        precision_metric = PrecisionAtK(k_pct=self.precision_k_pct)

        # Setup validation
        evals = [(dtrain, 'train')]
        if X_val is not None and y_val is not None:
            dval = xgb.DMatrix(X_val, label=y_val, enable_categorical=False)
            evals.append((dval, 'val'))

        # Train (note: XGBoost 2.0+ doesn't support feval, using custom_metric instead)
        self.model = xgb.train(
            params=params,
            dtrain=dtrain,
            num_boost_round=500,
            evals=evals,
            custom_metric=precision_metric.xgb_metric,
            early_stopping_rounds=50,
            verbose_eval=50
        )

        logger.info(f"Training complete. Best iteration: {self.model.best_iteration}")

        return self.model

    def optimize_hyperparameters(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame,
        y_val: pd.Series,
        n_trials: int = 50,
        timeout: Optional[int] = None
    ) -> Dict:
        """
        Optimize hyperparameters using Optuna (Bayesian optimization).

        Search space:
        - max_depth: [2, 3, 4] (constrained)
        - learning_rate: [0.01, 0.1]
        - n_estimators: [100, 500]
        - subsample: [0.6, 1.0]
        - colsample_bytree: [0.6, 1.0]
        - min_child_weight: [1, 10]

        Args:
            X_train, y_train: Training data
            X_val, y_val: Validation data
            n_trials: Number of optimization trials (default: 50)
            timeout: Timeout in seconds (default: None)

        Returns:
            Best hyperparameters
        """
        try:
            import optuna
            from optuna.samplers import TPESampler
        except ImportError:
            logger.error("Optuna not installed. Run: pip install optuna")
            logger.info("Falling back to default parameters...")
            return self._get_default_params()

        logger.info(f"Starting hyperparameter optimization ({n_trials} trials)...")

        # Calculate pos_weight
        if self.pos_weight is None:
            self.pos_weight = self.calculate_pos_weight(y_train)

        # Objective function
        def objective(trial: optuna.Trial) -> float:
            params = {
                'objective': 'binary:logistic',
                'eval_metric': 'logloss',
                'max_depth': trial.suggest_int('max_depth', 2, self.max_depth_limit),
                'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1, log=True),
                'n_estimators': trial.suggest_int('n_estimators', 100, 500, step=100),
                'subsample': trial.suggest_float('subsample', 0.6, 1.0),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
                'min_child_weight': trial.suggest_int('min_child_weight', 1, 10),
                'scale_pos_weight': self.pos_weight,
                'seed': self.random_state,
                'tree_method': 'hist'
            }

            # Handle infinite values
            X_train_clean = X_train.replace([np.inf, -np.inf], np.nan)
            X_val_clean = X_val.replace([np.inf, -np.inf], np.nan)

            # Train model
            dtrain = xgb.DMatrix(X_train_clean, label=y_train)
            dval = xgb.DMatrix(X_val_clean, label=y_val)

            model = xgb.train(
                params=params,
                dtrain=dtrain,
                num_boost_round=params['n_estimators'],
                evals=[(dval, 'val')],
                early_stopping_rounds=30,
                verbose_eval=False
            )

            # Predict on validation
            y_pred_proba = model.predict(dval)

            # Calculate Precision@k
            precision_metric = PrecisionAtK(k_pct=self.precision_k_pct)
            _, precision_score = precision_metric(y_val.values, y_pred_proba)

            return precision_score

        # Run optimization
        study = optuna.create_study(
            direction='maximize',
            sampler=TPESampler(seed=self.random_state)
        )

        study.optimize(
            objective,
            n_trials=n_trials,
            timeout=timeout,
            show_progress_bar=True
        )

        # Get best parameters
        self.best_params = study.best_params
        self.best_params.update({
            'objective': 'binary:logistic',
            'eval_metric': 'logloss',
            'scale_pos_weight': self.pos_weight,
            'seed': self.random_state,
            'tree_method': 'hist'
        })

        logger.info(f"\nOptimization complete!")
        logger.info(f"Best Precision@{int(self.precision_k_pct*100)}: {study.best_value:.4f}")
        logger.info(f"Best parameters: {self.best_params}")

        return self.best_params

    def _get_default_params(self) -> Dict:
        """Get default parameters (fallback)."""
        if self.pos_weight is None:
            self.pos_weight = 9.0  # Typical for SEPA

        return {
            'objective': 'binary:logistic',
            'eval_metric': 'logloss',
            'max_depth': 3,
            'learning_rate': 0.05,
            'n_estimators': 300,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'min_child_weight': 5,
            'scale_pos_weight': self.pos_weight,
            'seed': self.random_state,
            'tree_method': 'hist'
        }

    def train_with_best_params(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None
    ) -> xgb.Booster:
        """
        Train model with best parameters (from optimization).

        Args:
            X_train, y_train: Training data
            X_val, y_val: Validation data

        Returns:
            Trained model
        """
        if self.best_params is None:
            logger.warning("No optimized parameters found. Using defaults.")
            params = self._get_default_params()
        else:
            params = self.best_params.copy()

        # Extract n_estimators (not a param for xgb.train)
        n_estimators = params.pop('n_estimators', 300)

        return self.train_baseline(X_train, y_train, X_val, y_val, params={**params})

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Predict probability scores.

        Args:
            X: Features

        Returns:
            Array of probabilities (0.0 - 1.0)
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train_baseline() or train_with_best_params() first.")

        # Handle infinite values
        X = X.replace([np.inf, -np.inf], np.nan)

        dtest = xgb.DMatrix(X, enable_categorical=False)
        return self.model.predict(dtest)

    def predict(self, X: pd.DataFrame, threshold: float = 0.5) -> np.ndarray:
        """
        Predict binary labels with custom threshold.

        Args:
            X: Features
            threshold: Classification threshold (default: 0.5)

        Returns:
            Array of binary predictions
        """
        proba = self.predict_proba(X)
        return (proba >= threshold).astype(int)

    def save_model(self, output_dir: str, fold_id: Optional[int] = None):
        """
        Save trained model and metadata.

        Args:
            output_dir: Output directory
            fold_id: Optional fold identifier
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Model filename
        if fold_id is not None:
            model_path = output_dir / f'model_fold_{fold_id}.json'
            meta_path = output_dir / f'model_metadata_fold_{fold_id}.json'
        else:
            model_path = output_dir / 'model.json'
            meta_path = output_dir / 'model_metadata.json'

        # Save model
        self.model.save_model(str(model_path))
        logger.info(f"Model saved: {model_path}")

        # Save metadata
        metadata = {
            'feature_names': self.feature_names,
            'best_params': self.best_params if self.best_params else self._get_default_params(),
            'pos_weight': self.pos_weight,
            'max_depth_limit': self.max_depth_limit,
            'precision_k_pct': self.precision_k_pct,
            'training_date': datetime.now().isoformat(),
            'num_features': len(self.feature_names) if self.feature_names else 0,
            'best_iteration': self.model.best_iteration if hasattr(self.model, 'best_iteration') else None
        }

        with open(meta_path, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Metadata saved: {meta_path}")

    def load_model(self, model_path: str, meta_path: Optional[str] = None):
        """
        Load trained model.

        Args:
            model_path: Path to model file
            meta_path: Path to metadata file (optional)
        """
        self.model = xgb.Booster()
        self.model.load_model(model_path)
        logger.info(f"Model loaded: {model_path}")

        # Load metadata if provided
        if meta_path and Path(meta_path).exists():
            with open(meta_path, 'r') as f:
                metadata = json.load(f)

            self.feature_names = metadata.get('feature_names')
            self.best_params = metadata.get('best_params')
            self.pos_weight = metadata.get('pos_weight')
            logger.info(f"Metadata loaded: {meta_path}")


def train_walk_forward_models(
    folds: List[Dict],
    df: pd.DataFrame,
    splitter: object,
    selector: object,
    optimize_hyperparams: bool = True,
    n_trials: int = 50,
    output_dir: str = 'models'
) -> Dict:
    """
    Train models using walk-forward validation.

    Args:
        folds: List of temporal folds
        df: Full dataset
        splitter: TemporalSplitter instance
        selector: FeatureSelector instance
        optimize_hyperparams: Whether to optimize hyperparameters (default: True)
        n_trials: Number of optimization trials (default: 50)
        output_dir: Directory to save models (default: 'models')

    Returns:
        Dictionary with trained models and results
    """
    logger.info("=" * 80)
    logger.info("WALK-FORWARD MODEL TRAINING")
    logger.info("=" * 80)

    results = {
        'models': [],
        'fold_results': [],
        'feature_importance': {}
    }

    for fold_idx, fold in enumerate(folds):
        logger.info(f"\n{'='*80}")
        logger.info(f"Training Fold {fold['fold_id']}")
        logger.info(f"{'='*80}")

        # Get train/test data
        X_train, X_test, y_train, y_test = splitter.get_fold_data(
            df,
            fold_idx=fold_idx,
            feature_columns=selector.selected_features
        )

        # Apply feature selection transform
        X_train = selector.transform(X_train)
        X_test = selector.transform(X_test)

        # Split train into train/val for early stopping
        train_size = int(len(X_train) * 0.8)
        X_train_split = X_train.iloc[:train_size]
        y_train_split = y_train.iloc[:train_size]
        X_val_split = X_train.iloc[train_size:]
        y_val_split = y_train.iloc[train_size:]

        logger.info(f"Train: {len(X_train_split)}, Val: {len(X_val_split)}, Test: {len(X_test)}")

        # Initialize trainer
        trainer = SEPAModelTrainer(precision_k_pct=0.2)

        # Optimize hyperparameters (only on first fold to save time)
        if optimize_hyperparams and fold_idx == 0:
            best_params = trainer.optimize_hyperparameters(
                X_train_split,
                y_train_split,
                X_val_split,
                y_val_split,
                n_trials=n_trials
            )
        elif fold_idx > 0:
            # Reuse parameters from first fold
            trainer.best_params = results['models'][0].best_params

        # Train with best params
        model = trainer.train_with_best_params(
            X_train_split,
            y_train_split,
            X_val_split,
            y_val_split
        )

        # Save model
        trainer.save_model(output_dir, fold_id=fold['fold_id'])

        # Store results
        results['models'].append(trainer)
        results['fold_results'].append({
            'fold_id': fold['fold_id'],
            'train_size': len(X_train),
            'test_size': len(X_test),
            'train_win_rate': y_train.mean(),
            'test_win_rate': y_test.mean()
        })

        logger.info(f"Fold {fold['fold_id']} training complete")

    logger.info("\n" + "=" * 80)
    logger.info("ALL FOLDS TRAINED")
    logger.info("=" * 80)

    return results


if __name__ == "__main__":
    # Example usage
    import argparse
    from model_preparation import prepare_training_data

    parser = argparse.ArgumentParser(description="Train SEPA models with walk-forward validation")
    parser.add_argument('--dataset', type=str, required=True, help='Path to training dataset')
    parser.add_argument('--output-dir', type=str, default='models', help='Output directory')
    parser.add_argument('--optimize', action='store_true', help='Optimize hyperparameters')
    parser.add_argument('--n-trials', type=int, default=50, help='Optuna trials (default: 50)')

    args = parser.parse_args()

    # Prepare data
    prep_result = prepare_training_data(args.dataset)

    # Train models
    train_results = train_walk_forward_models(
        folds=prep_result['folds'],
        df=prep_result['df'],
        splitter=prep_result['splitter'],
        selector=prep_result['selector'],
        optimize_hyperparams=args.optimize,
        n_trials=args.n_trials,
        output_dir=args.output_dir
    )

    print(f"\nTraining complete! Models saved to: {args.output_dir}")
