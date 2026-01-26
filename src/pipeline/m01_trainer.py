"""
M01 Trainer - SEPA Return Regressor
===================================

M01 predicts expected return % for SEPA trade candidates.

Features: Uses M01_FEATURES from feature_config.py
Target: return_pct (actual % return of trade)
Model: XGBoost Regressor

Usage:
    from src.pipeline import DataPipeline, M01Trainer
    
    pipeline = DataPipeline()
    d1 = pipeline.scan('2020-01-01', '2023-12-31')
    d2 = pipeline.features(d1)
    
    trainer = M01Trainer()
    model, metrics = trainer.train(d2)
    trainer.save(model, metrics)
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from .base_trainer import BaseTrainer

logger = logging.getLogger("M01Trainer")


class M01Trainer(BaseTrainer):
    """
    M01: SEPA Return Regressor.
    
    Predicts expected return % for SEPA trade candidates.
    Higher scores = higher expected returns.
    """
    
    @property
    def model_type(self) -> str:
        return 'regression'
    
    @property
    def model_name(self) -> str:
        return 'M01'
    
    def get_features(self) -> List[str]:
        """Get M01 feature list from centralized config."""
        from src.feature_config import M01_FEATURES
        return M01_FEATURES
    
    def get_target_col(self) -> str:
        """M01 predicts actual return %."""
        return 'return_pct'
    
    def get_model_params(self, tuned_params: Optional[Dict] = None) -> Dict:
        """Get XGBoost regressor parameters."""
        default_params = {
            'objective': 'reg:squarederror',
            'n_estimators': 300,
            'learning_rate': 0.03,
            'max_depth': 4,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'reg_alpha': 5.0,   # L1 regularization
            'reg_lambda': 3.0,  # L2 regularization
            'random_state': 42,
            'n_jobs': -1
        }
        
        if tuned_params:
            default_params.update(tuned_params)
        
        return default_params
    
    def create_model(self, params: Dict):
        """Create XGBoost regressor."""
        import xgboost as xgb
        return xgb.XGBRegressor(**params)
    
    def _evaluate_fold(
        self, 
        y_test: pd.Series, 
        preds: np.ndarray, 
        model,
        test_year: int,
        n_train: int,
        n_test: int
    ) -> Dict:
        """Evaluate regression fold."""
        from sklearn.metrics import mean_squared_error, mean_absolute_error
        
        rmse = np.sqrt(mean_squared_error(y_test, preds))
        mae = mean_absolute_error(y_test, preds)
        decile = self.analyze_deciles(y_test, preds)
        
        return {
            'test_year': test_year,
            'train_samples': n_train,
            'test_samples': n_test,
            'rmse': rmse,
            'mae': mae,
            'selection_edge': decile['selection_edge'],
            'top_decile_mean': decile['top_decile_mean'],
            'top2_edge': decile['top2_edge']
        }
    
    def _format_fold_result(self, metrics: Dict) -> str:
        """Format regression fold result."""
        return f"RMSE={metrics['rmse']:.2f} Edge={metrics['selection_edge']:+.2f}%"
    
    def _print_summary(self, metrics_df: pd.DataFrame):
        """Print regression validation summary."""
        if len(metrics_df) == 0:
            logger.warning("No validation folds completed")
            return
        
        avg_rmse = metrics_df['rmse'].mean()
        avg_edge = metrics_df['selection_edge'].mean()
        avg_top_decile = metrics_df['top_decile_mean'].mean()
        min_edge = metrics_df['selection_edge'].min()
        max_edge = metrics_df['selection_edge'].max()
        positive_folds = (metrics_df['selection_edge'] > 0).sum()
        
        print("\n" + "=" * 70)
        print("M01 WALK-FORWARD VALIDATION RESULTS (REGRESSION)")
        print("=" * 70)
        print(f"   Folds Completed:       {len(metrics_df)}")
        print(f"   Total Test Samples:    {metrics_df['test_samples'].sum()}")
        print(f"   Average RMSE:          {avg_rmse:.2f}%")
        print(f"\nSELECTION EDGE (The Key Metric)")
        print(f"   Average Edge:          {avg_edge:>+6.2f}%")
        print(f"   Edge Range:            [{min_edge:+.2f}%, {max_edge:+.2f}%]")
        print(f"   Positive Edge Folds:   {positive_folds} / {len(metrics_df)} ({positive_folds/len(metrics_df)*100:.0f}%)")
        print(f"   Top Decile Avg Return: {avg_top_decile:>7.2f}%")
        print("=" * 70 + "\n")
