"""
M01 Model Evaluator - Orchestrates all evaluation components.
==============================================================

Comprehensive evaluation framework for M01 regression models.

Tracks predictions across walk-forward folds and generates:
- Fold-level metrics (RMSE, IC, Edge, Precision@K)
- Aggregate metrics (IC Sharpe, Edge Sharpe, Volatility Correlation)
- Error analysis (FOMO vs Toxic)
- Markdown scorecards
- Visualization data (JSON)
"""

import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional

from sklearn.metrics import mean_squared_error, mean_absolute_error

from .metrics import (
    calculate_ic,
    calculate_precision_at_k,
    calculate_recall_at_k,
    calculate_decile_lift,
    calculate_volatility_correlation
)
from .ranking import analyze_deciles
from .errors import analyze_prediction_errors
from .reports import ReportGenerator

logger = logging.getLogger("M01Evaluator")


class M01Evaluator:
    """
    Comprehensive evaluation framework for M01 regression models.
    
    Usage:
        evaluator = M01Evaluator(target_type='return_pct')
        
        # During training loop:
        for fold in folds:
            fold_metrics = evaluator.evaluate_fold(y_test, preds, test_year, n_train, n_test)
            evaluator.add_predictions(test_data)
        
        # After training:
        full_metrics = evaluator.evaluate_full()
        report_path = evaluator.generate_scorecard(model, feature_cols)
    """
    
    def __init__(
        self,
        target_type: str = 'return_pct',
        output_dir: Path = None
    ):
        """
        Initialize M01 Evaluator.
        
        Args:
            target_type: Type of target being evaluated
            output_dir: Directory for saving reports (default: 'models')
        """
        self.target_type = target_type
        self.output_dir = Path(output_dir) if output_dir else Path('models')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.fold_metrics_list = []
        self.predictions_df = pd.DataFrame()
        self.report_gen = ReportGenerator(self.output_dir)
    
    def add_predictions(self, fold_predictions: pd.DataFrame):
        """
        Store predictions from one fold.
        
        Args:
            fold_predictions: DataFrame with 'y_pred', 'y_true' columns
        """
        self.predictions_df = pd.concat(
            [self.predictions_df, fold_predictions],
            ignore_index=True
        )
    
    def evaluate_fold(
        self,
        y_true: pd.Series,
        y_pred: np.ndarray,
        test_year: int,
        n_train: int,
        n_test: int
    ) -> Dict:
        """
        Evaluate single fold with comprehensive metrics.
        
        Args:
            y_true: Actual values
            y_pred: Predicted values
            test_year: Year being tested
            n_train: Number of training samples
            n_test: Number of test samples
            
        Returns:
            Dict with all fold metrics
        """
        # Basic regression metrics
        rmse = np.sqrt(mean_squared_error(y_true, y_pred))
        mae = mean_absolute_error(y_true, y_pred)
        
        # Ranking metrics
        ic, ic_pvalue = calculate_ic(y_true.values, y_pred)
        decile_result = analyze_deciles(y_true.values, y_pred)
        lift = calculate_decile_lift(y_true.values, y_pred)
        precision_at_10 = calculate_precision_at_k(y_true.values, y_pred, k=0.1)
        recall_at_10 = calculate_recall_at_k(y_true.values, y_pred, k=0.1)
        
        metrics = {
            'test_year': test_year,
            'train_samples': n_train,
            'test_samples': n_test,
            'rmse': float(rmse),
            'mae': float(mae),
            'ic': float(ic),
            'ic_pvalue': float(ic_pvalue),
            'selection_edge': float(decile_result['selection_edge']),
            'top_decile_mean': float(decile_result['top_decile_mean']),
            'top2_edge': float(decile_result['top2_edge']),
            'top_decile_lift': float(lift),
            'precision_at_10': float(precision_at_10),
            'recall_at_10_for_top5': float(recall_at_10)
        }
        
        self.fold_metrics_list.append(metrics)
        return metrics
    
    def evaluate_full(self) -> Dict:
        """
        Aggregate metrics across all folds.
        
        Returns:
            Dict with aggregate metrics including:
            - avg_ic, ic_std, ic_sharpe, ic_consistency
            - avg_selection_edge, edge_sharpe
            - avg_top_decile_lift
            - volatility_correlation
            - error_analysis
        """
        if not self.fold_metrics_list:
            return {}
        
        fold_df = pd.DataFrame(self.fold_metrics_list)
        
        # IC statistics
        avg_ic = fold_df['ic'].mean()
        ic_std = fold_df['ic'].std()
        ic_sharpe = avg_ic / ic_std if ic_std > 0 else 0
        ic_consistency = (fold_df['ic'] > 0).mean()
        
        # Edge statistics
        avg_edge = fold_df['selection_edge'].mean()
        edge_std = fold_df['selection_edge'].std()
        edge_sharpe = avg_edge / edge_std if edge_std > 0 else 0
        
        # Other averages
        avg_lift = fold_df['top_decile_lift'].mean()
        avg_precision = fold_df['precision_at_10'].mean()
        avg_recall = fold_df['recall_at_10_for_top5'].mean()
        avg_rmse = fold_df['rmse'].mean()
        avg_top_decile = fold_df['top_decile_mean'].mean()
        
        # Volatility correlation (only if we have predictions)
        vol_correlation = {}
        if not self.predictions_df.empty and 'y_pred' in self.predictions_df.columns:
            vol_correlation = calculate_volatility_correlation(
                self.predictions_df,
                pred_col='y_pred'
            )
        
        # Error analysis
        error_analysis = {}
        if not self.predictions_df.empty:
            error_analysis = analyze_prediction_errors(
                self.predictions_df,
                pred_col='y_pred',
                actual_col='y_true'
            )
        
        return {
            # IC metrics
            'avg_ic': float(avg_ic),
            'ic_std': float(ic_std),
            'ic_sharpe': float(ic_sharpe),
            'ic_consistency': float(ic_consistency),
            
            # Edge metrics
            'avg_selection_edge': float(avg_edge),
            'edge_std': float(edge_std),
            'edge_sharpe': float(edge_sharpe),
            
            # Other metrics
            'avg_top_decile_lift': float(avg_lift),
            'avg_precision_at_10': float(avg_precision),
            'avg_recall_at_10_for_top5': float(avg_recall),
            'avg_rmse': float(avg_rmse),
            'avg_top_decile_mean': float(avg_top_decile),
            
            # Analysis
            'volatility_correlation': vol_correlation,
            'error_analysis': error_analysis,
            
            # Summary
            'n_folds': len(self.fold_metrics_list),
            'total_test_samples': int(fold_df['test_samples'].sum())
        }
    
    def generate_scorecard(
        self,
        model,
        feature_cols: List[str],
        model_name: str = 'M01'
    ) -> str:
        """
        Generate complete markdown scorecard report.
        
        Args:
            model: Trained XGBoost model (for feature importance)
            feature_cols: List of feature column names
            model_name: Name of the model
            
        Returns:
            Path to saved report
        """
        full_metrics = self.evaluate_full()
        fold_df = pd.DataFrame(self.fold_metrics_list)
        
        # Extract feature importance
        feature_importance = self._extract_feature_importance(model, feature_cols)
        
        return self.report_gen.generate_scorecard(
            model_name=model_name,
            target_type=self.target_type,
            metrics_summary=full_metrics,
            fold_metrics=fold_df,
            feature_importance=feature_importance,
            error_analysis=full_metrics.get('error_analysis'),
            vol_correlation=full_metrics.get('volatility_correlation')
        )
    
    def _extract_feature_importance(
        self,
        model,
        feature_cols: List[str]
    ) -> pd.DataFrame:
        """Extract feature importance from trained model."""
        if model is None or not hasattr(model, 'feature_importances_'):
            return pd.DataFrame()
        
        importance = model.feature_importances_
        
        df = pd.DataFrame({
            'feature': feature_cols,
            'gain': importance
        }).sort_values('gain', ascending=False).reset_index(drop=True)
        
        df['rank'] = range(1, len(df) + 1)
        total_gain = df['gain'].sum()
        df['gain_pct'] = (df['gain'] / total_gain * 100).round(2) if total_gain > 0 else 0
        df['cumulative_pct'] = df['gain_pct'].cumsum().round(2)
        
        return df
    
    def export_viz_data(self) -> Dict:
        """
        Export visualization data for dashboard.
        
        Returns:
            {
                'decile_performance': list,
                'scatter_sample': list,
                'error_breakdown': dict
            }
        """
        result = {
            'decile_performance': [],
            'scatter_sample': [],
            'error_breakdown': {}
        }
        
        if self.predictions_df.empty:
            return result
        
        df = self.predictions_df.copy()
        
        # Decile performance
        try:
            df['decile'] = pd.qcut(df['y_pred'], q=10, labels=False, duplicates='drop') + 1
            decile_stats = df.groupby('decile').agg({
                'y_true': ['mean', 'count']
            }).reset_index()
            decile_stats.columns = ['decile', 'mean_return', 'count']
            result['decile_performance'] = decile_stats.to_dict('records')
        except Exception:
            pass
        
        # Scatter sample (max 1000 points)
        sample_df = df.sample(n=min(1000, len(df)), random_state=42)
        sample_df = sample_df[['y_pred', 'y_true']].round(2)
        result['scatter_sample'] = sample_df.to_dict('records')
        
        # Error breakdown
        full_metrics = self.evaluate_full()
        result['error_breakdown'] = full_metrics.get('error_analysis', {})
        
        return result
    
    def get_fold_metrics_df(self) -> pd.DataFrame:
        """Get fold metrics as DataFrame."""
        return pd.DataFrame(self.fold_metrics_list)
    
    def reset(self):
        """Reset evaluator state for new training run."""
        self.fold_metrics_list = []
        self.predictions_df = pd.DataFrame()
