"""
M02 Trainer - Ignition Classifier (Triple Barrier)
===================================================

M02 predicts ignition probability - likelihood of hitting profit target
before stop-loss (triple barrier method).

Features: Uses M02_FEATURES from feature_config.py (velocity-focused)
Target: y_meta (1 = hit TP, 0 = hit SL or Time)
Model: XGBoost Classifier

Usage:
    from src.pipeline import DataPipeline, M02Trainer
    
    pipeline = DataPipeline()
    d1 = pipeline.scan('2020-01-01', '2023-12-31')
    d2r = pipeline.hydrate(d1, horizon_days=120)
    d3 = pipeline.label(d2r)
    
    trainer = M02Trainer()
    model, metrics = trainer.train(d3)
    trainer.save(model, metrics)
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from .base_trainer import BaseTrainer

logger = logging.getLogger("M02Trainer")


# Default barrier parameters (Phase 1 optimized)
DEFAULT_BARRIER_PARAMS = {
    'k_sl': 1.0,
    'k_tp': 4.0,
    'min_tp': 0.20,
    'max_time': 30
}


class M02Trainer(BaseTrainer):
    """
    M02: Ignition Classifier.
    
    Predicts probability of hitting profit target before stop-loss.
    Uses triple barrier labels from d3 dataset.
    
    Higher scores = higher probability of hitting TP first.
    """
    
    def __init__(
        self, 
        output_dir: str = 'models',
        barrier_params: Optional[Dict] = None
    ):
        super().__init__(output_dir)
        self.barrier_params = barrier_params or DEFAULT_BARRIER_PARAMS.copy()
    
    @property
    def model_type(self) -> str:
        return 'classification'
    
    @property
    def model_name(self) -> str:
        return 'M02'
    
    def get_features(self) -> List[str]:
        """Get M02 feature list from centralized config."""
        from src.feature_config import get_model_features
        # M02 uses velocity-focused features
        return get_model_features('M02')
    
    def get_target_col(self) -> str:
        """M02 predicts triple barrier label."""
        return 'y_meta'
    
    def get_model_params(self, tuned_params: Optional[Dict] = None) -> Dict:
        """Get XGBoost classifier parameters."""
        default_params = {
            'objective': 'binary:logistic',
            'n_estimators': 500,
            'learning_rate': 0.03,
            'max_depth': 5,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'min_child_weight': 3,
            'random_state': 42,
            'n_jobs': -1,
            'eval_metric': 'logloss'
        }
        
        if tuned_params:
            default_params.update(tuned_params)
        
        return default_params
    
    def create_model(self, params: Dict):
        """Create XGBoost classifier with class weight handling."""
        import xgboost as xgb
        return xgb.XGBClassifier(**params)
    
    def train(
        self,
        data: pd.DataFrame,
        tune: bool = False,
        tune_trials: int = 50,
        train_years: int = 3,
        test_years: int = 1
    ):
        """
        Train M02 with automatic class weight handling.
        
        Overrides base train() to handle imbalanced classes.
        """
        # Calculate scale_pos_weight for imbalanced classes
        target_col = self.get_target_col()
        if target_col in data.columns:
            pos_ratio = data[target_col].mean()
            if pos_ratio > 0 and pos_ratio < 1:
                scale_pos_weight = (1 - pos_ratio) / pos_ratio
                logger.info(f"   Class imbalance: {pos_ratio:.1%} positive")
                logger.info(f"   scale_pos_weight: {scale_pos_weight:.2f}")
                self._scale_pos_weight = scale_pos_weight
        
        return super().train(data, tune, tune_trials, train_years, test_years)
    
    def get_model_params(self, tuned_params: Optional[Dict] = None) -> Dict:
        """Get XGBoost classifier parameters with class weight."""
        params = {
            'objective': 'binary:logistic',
            'n_estimators': 500,
            'learning_rate': 0.03,
            'max_depth': 5,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'min_child_weight': 3,
            'random_state': 42,
            'n_jobs': -1,
            'eval_metric': 'logloss'
        }
        
        # Add scale_pos_weight if calculated
        if hasattr(self, '_scale_pos_weight'):
            params['scale_pos_weight'] = self._scale_pos_weight
        
        if tuned_params:
            params.update(tuned_params)
        
        return params
    
    def _evaluate_fold(
        self, 
        y_test: pd.Series, 
        preds: np.ndarray, 
        model,
        test_year: int,
        n_train: int,
        n_test: int
    ) -> Dict:
        """Evaluate classification fold."""
        from sklearn.metrics import accuracy_score, precision_score, recall_score
        
        acc = accuracy_score(y_test, preds)
        prec = precision_score(y_test, preds, zero_division=0)
        recall = recall_score(y_test, preds, zero_division=0)
        
        # Decile analysis using predictions
        try:
            decile = self.analyze_deciles(y_test, preds.astype(float))
            selection_edge = decile['selection_edge']
        except Exception:
            selection_edge = 0
        
        return {
            'test_year': test_year,
            'train_samples': n_train,
            'test_samples': n_test,
            'accuracy': acc,
            'precision': prec,
            'recall': recall,
            'selection_edge': selection_edge
        }
    
    def _format_fold_result(self, metrics: Dict) -> str:
        """Format classification fold result."""
        return f"Acc={metrics['accuracy']:.2%} Prec={metrics['precision']:.2%}"
    
    def _print_summary(self, metrics_df: pd.DataFrame):
        """Print classification validation summary."""
        if len(metrics_df) == 0:
            logger.warning("No validation folds completed")
            return
        
        avg_acc = metrics_df['accuracy'].mean()
        avg_prec = metrics_df['precision'].mean()
        avg_recall = metrics_df['recall'].mean()
        avg_edge = metrics_df['selection_edge'].mean()
        
        print("\n" + "=" * 70)
        print("M02 WALK-FORWARD VALIDATION RESULTS (CLASSIFICATION)")
        print("=" * 70)
        print(f"   Folds Completed:       {len(metrics_df)}")
        print(f"   Total Test Samples:    {metrics_df['test_samples'].sum()}")
        print(f"   Average Accuracy:      {avg_acc:.2%}")
        print(f"   Average Precision:     {avg_prec:.2%}")
        print(f"   Average Recall:        {avg_recall:.2%}")
        print(f"   Average Edge:          {avg_edge:>+6.2f}%")
        print("=" * 70 + "\n")
    
    def save(self, model, metrics_df: pd.DataFrame, config: Optional[Dict] = None):
        """Save M02 model with barrier parameters."""
        if config is None:
            config = {}
        
        config['barrier_params'] = self.barrier_params
        
        return super().save(model, metrics_df, config)
