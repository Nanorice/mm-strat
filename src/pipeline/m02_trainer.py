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
    M02: Loser Detector (Inverted Ignition Classifier).

    Predicts probability of hitting STOP-LOSS before profit target.
    Uses triple barrier labels from d3 dataset.

    Higher scores = higher probability of hitting SL first (LOSER).

    Rationale:
        - TP rate is only 5.4%, making it nearly impossible to learn
        - SL rate is 61.6%, providing much better signal-to-noise
        - Filtering out losers is as valuable as finding winners

    Usage:
        # Train on inverted labels (y_loser = 1 if SL hit)
        trainer = M02Trainer()
        model, metrics = trainer.train(d3)

        # In production, PENALIZE high P(loser):
        # Final_Score = M01_Adj × (1 - P(loser))
    """

    def __init__(
        self,
        output_dir: str = 'models',
        barrier_params: Optional[Dict] = None,
        feature_set: str = None,
        model_name: str = None
    ):
        super().__init__(output_dir)
        self.barrier_params = barrier_params or self._load_barrier_params_from_d3()
        self._feature_set = feature_set  # Custom feature set name (e.g., 'M01_FEATURES')
        self._custom_model_name = model_name  # Custom model name for AB testing

    def _load_barrier_params_from_d3(self) -> Dict:
        """Load barrier params from d3_summary.json if available, else use defaults."""
        import json
        from pathlib import Path

        summary_path = Path('data/ml/d3_summary.json')
        if summary_path.exists():
            try:
                with open(summary_path) as f:
                    summary = json.load(f)
                if 'barrier_params' in summary:
                    logger.info(f"   Loaded barrier params from {summary_path}")
                    return summary['barrier_params']
            except Exception as e:
                logger.warning(f"   Failed to load barrier params from {summary_path}: {e}")

        return DEFAULT_BARRIER_PARAMS.copy()
    
    @property
    def model_type(self) -> str:
        return 'classification'
    
    @property
    def model_name(self) -> str:
        return self._custom_model_name or 'M02'
    
    def get_features(self) -> List[str]:
        """Get M02 feature list from centralized config.
        
        Uses custom feature_set if specified, otherwise M02_FEATURES.
        """
        from src.feature_config import get_model_features
        import src.feature_config as fc
        
        if self._feature_set:
            # Try to load from feature_config registry first
            try:
                return get_model_features(self._feature_set)
            except ValueError:
                # Fall back to loading the attribute directly
                if hasattr(fc, self._feature_set):
                    features = getattr(fc, self._feature_set)
                    logger.info(f"   Using custom feature set: {self._feature_set} ({len(features)} features)")
                    return features
                else:
                    raise ValueError(f"Feature set '{self._feature_set}' not found in feature_config.py")
        
        # Default: M02 velocity-focused features
        return get_model_features('M02')
    
    def get_target_col(self) -> str:
        """M02 predicts LOSER label (inverted: 1 = SL hit)."""
        return 'y_loser'
    
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
        """Create XGBoost classifier with class weight handling and categorical support."""
        import xgboost as xgb
        if 'enable_categorical' not in params:
            params = {**params, 'enable_categorical': True}
        return xgb.XGBClassifier(**params)
    
    def prepare_data(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare D3 data with inverted labels (y_loser).

        Creates y_loser column:
            1 = SL hit (loser) - we want to DETECT these
            0 = TP or Time hit (not a loser)
        """
        df = data.copy()

        if 'barrier_outcome' in df.columns:
            # Use barrier_outcome for precise labeling
            df['y_loser'] = (df['barrier_outcome'] == 'SL').astype(int)
            logger.info(f"   Created y_loser from barrier_outcome")
        elif 'y_meta' in df.columns:
            # Fallback: invert y_meta (0 becomes potential loser)
            # But this includes Time exits, so less precise
            df['y_loser'] = (df['y_meta'] == 0).astype(int)
            logger.info(f"   Created y_loser from inverted y_meta (includes Time exits)")
        else:
            raise ValueError("D3 must have 'barrier_outcome' or 'y_meta' column")

        loser_rate = df['y_loser'].mean()
        logger.info(f"   Loser rate (SL hits): {loser_rate:.1%}")

        return df

    def train(
        self,
        data: pd.DataFrame,
        tune: bool = False,
        tune_trials: int = 50,
        train_years: int = 3,
        test_years: int = 1
    ):
        """
        Train M02 Loser Detector with automatic class weight handling.

        Overrides base train() to:
        1. Create y_loser target (inverted labels)
        2. Handle class imbalance
        """
        # Step 1: Prepare data with inverted labels
        data = self.prepare_data(data)

        # Step 2: Calculate scale_pos_weight for imbalanced classes
        target_col = self.get_target_col()
        if target_col in data.columns:
            pos_ratio = data[target_col].mean()
            if pos_ratio > 0 and pos_ratio < 1:
                scale_pos_weight = (1 - pos_ratio) / pos_ratio
                logger.info(f"   Class imbalance: {pos_ratio:.1%} positive (losers)")
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
    
    # =========================================================================
    # REPORT GENERATION
    # =========================================================================
    def save_feature_importance(self, model, feature_cols: List[str]) -> pd.DataFrame:
        """Extract and save feature importance from trained model."""
        importance = model.feature_importances_
        
        importance_df = pd.DataFrame({
            'feature': feature_cols,
            'gain': importance
        }).sort_values('gain', ascending=False).reset_index(drop=True)
        
        importance_df['rank'] = range(1, len(importance_df) + 1)
        total_gain = importance_df['gain'].sum()
        importance_df['gain_pct'] = (importance_df['gain'] / total_gain * 100).round(2)
        importance_df['cumulative_pct'] = importance_df['gain_pct'].cumsum().round(2)
        
        # Save to CSV (use model name for distinct files)
        model_lower = self.model_name.lower()
        csv_path = self.output_dir / f'feature_importance_{model_lower}.csv'
        importance_df.to_csv(csv_path, index=False)
        logger.info(f"   Saved feature importance to {csv_path}")
        
        return importance_df
    
    def generate_report(
        self,
        model,
        metrics_df: pd.DataFrame,
        start_date: str = None,
        end_date: str = None
    ) -> str:
        """
        Generate comprehensive markdown report for M02 training results.
        
        Args:
            model: Trained XGBoost classifier
            metrics_df: Walk-forward validation metrics
            start_date: Training start date
            end_date: Training end date
            
        Returns:
            Path to saved report
        """
        from datetime import datetime
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_lower = self.model_name.lower()
        report_path = self.output_dir / f"model_report_{self.model_name}_{timestamp}.md"
        
        # Get feature set info for report
        feature_set_name = self._feature_set or 'M02_FEATURES'
        feature_count = len(self.get_features())
        
        # Get feature importance
        feature_cols = self._feature_cols if hasattr(self, '_feature_cols') else []
        importance_df = self.save_feature_importance(model, feature_cols) if feature_cols else None
        
        # Calculate summary statistics
        avg_edge = metrics_df['selection_edge'].mean()
        avg_acc = metrics_df['accuracy'].mean()
        avg_prec = metrics_df['precision'].mean()
        avg_recall = metrics_df['recall'].mean()
        
        # Build report
        lines = []
        lines.append(f"# Model Training Report - {self.model_name} (Loser Detector)")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if start_date and end_date:
            lines.append(f"**Training Period:** {start_date} to {end_date}")
        lines.append(f"**Model Type:** CLASSIFICATION")
        lines.append(f"**Feature Set:** {feature_set_name} ({feature_count} features)")
        lines.append(f"**Barrier Type:** Hybrid (ATR-based)")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Executive Summary
        lines.append("## Executive Summary")
        lines.append("")
        lines.append(f"- **Average Selection Edge:** {avg_edge:.2f}%")
        lines.append(f"- **Average Accuracy:** {avg_acc:.2%}")
        lines.append(f"- **Average Precision:** {avg_prec:.2%}")
        lines.append(f"- **Average Recall:** {avg_recall:.2%}")
        lines.append(f"- **Barrier Params:** k_sl={self.barrier_params['k_sl']}, k_tp={self.barrier_params['k_tp']}, min_tp={self.barrier_params['min_tp']}")
        lines.append("")
        
        # Viability Assessment
        lines.append("## Viability Assessment")
        lines.append("")
        if avg_edge > 2.5 and avg_prec > 0.10:
            lines.append("**STRONG SIGNAL** - Model shows consistent edge across folds.")
            lines.append("")
            lines.append(f"The model demonstrates strong predictive power for identifying trades that hit profit targets before stop-losses. With a {avg_edge:.2f}% selection edge and {avg_prec:.2%} precision, this model is ready for live testing.")
        elif avg_edge > 1.5 and avg_prec > 0.05:
            lines.append("**MODERATE SIGNAL** - Model has edge but may need refinement.")
            lines.append("")
            lines.append(f"The model shows {avg_edge:.2f}% selection edge with {avg_prec:.2%} precision. Consider combining with M01 in an ensemble or using stricter thresholds (score > 0.7).")
        else:
            lines.append("**WEAK SIGNAL** - Model edge is marginal. Consider:")
            lines.append("- Adjusting barrier parameters (run grid search again)")
            lines.append("- Adding barrier-specific features (e.g., volatility_regime, sector_tp_rate)")
            lines.append("- Ensemble with M01 predictions")
            lines.append("- Increasing training data or tuning hyperparameters")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Walk-Forward Results
        lines.append("## Walk-Forward Validation Results")
        lines.append("")
        lines.append("| Fold | Test Year | Test Samples | Accuracy | Precision | Recall | Edge |")
        lines.append("|------|-----------|--------------|----------|-----------|--------|------|")
        
        for i, row in metrics_df.iterrows():
            lines.append(
                f"| {i+1} | {row.get('test_year', 'N/A')} | {row['test_samples']:,} | "
                f"{row['accuracy']:.2%} | {row['precision']:.2%} | {row['recall']:.2%} | {row['selection_edge']:+.2f}% |"
            )
        
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Feature Importance
        if importance_df is not None and len(importance_df) > 0:
            lines.append("## Feature Importance (Top 20)")
            lines.append("")
            lines.append("| Rank | Feature | Gain | % Total |")
            lines.append("|------|---------|------|---------|")
            
            for _, row in importance_df.head(20).iterrows():
                lines.append(f"| {int(row['rank'])} | {row['feature']} | {row['gain']:.0f} | {row['gain_pct']:.2f}% |")
            
            lines.append("")
            top_10_pct = importance_df.head(10)['gain_pct'].sum()
            lines.append(f"**Insight:** Top 10 features contribute {top_10_pct:.1f}% of total gain.")
            lines.append("")
            lines.append("---")
            lines.append("")
        
        # Usage Recommendations
        lines.append("## Usage Recommendations")
        lines.append("")
        lines.append("### Trade Selection Thresholds")
        lines.append("")
        
        if avg_edge > 2.5:
            lines.append("- **High Confidence (Score > 0.7):** Position size 1.5x")
            lines.append("- **Medium Confidence (Score > 0.5):** Position size 1.0x")
            lines.append("- **Low Confidence (Score < 0.5):** Skip")
        elif avg_edge > 1.5:
            lines.append("- **Conservative (Score > 0.8):** Position size 1.0x")
            lines.append("- **Moderate (Score > 0.6):** Position size 0.5x")
            lines.append("- **Low (Score < 0.6):** Skip")
        else:
            lines.append("- **Very Conservative (Score > 0.85):** Position size 0.5x")
            lines.append("- **All others:** Skip until model is improved")
        lines.append("")
        
        lines.append("### Integration with M01")
        lines.append("")
        lines.append("**Ensemble Approach:**")
        lines.append("```python")
        lines.append("final_score = 0.6 × M01_score + 0.4 × M02_score")
        lines.append("```")
        lines.append("")
        lines.append("**Filter Approach:**")
        lines.append("```python")
        lines.append("take_trade = (M01_score > 0.6) AND (M02_score > 0.6)")
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Barrier Configuration
        lines.append("## Barrier Configuration")
        lines.append("")
        lines.append(f"- **Stop Loss:** k_sl = {self.barrier_params['k_sl']} × ATR")
        lines.append(f"- **Profit Target:** MAX({self.barrier_params['min_tp']:.0%}, {self.barrier_params['k_tp']} × ATR)")
        lines.append(f"- **Max Time Barrier:** {self.barrier_params['max_time']} days")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Model Configuration
        lines.append("## Model Configuration")
        lines.append("")
        lines.append("```python")
        lines.append("XGBClassifier(")
        lines.append("    objective='binary:logistic',")
        lines.append("    n_estimators=500,")
        lines.append("    learning_rate=0.03,")
        lines.append("    max_depth=5,")
        lines.append("    subsample=0.8,")
        lines.append("    colsample_bytree=0.8,")
        lines.append("    min_child_weight=3,")
        if hasattr(self, '_scale_pos_weight'):
            lines.append(f"    scale_pos_weight={self._scale_pos_weight:.2f},")
        lines.append("    random_state=42")
        lines.append(")")
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("*Report generated by M02Trainer*")
        
        # Write report
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        logger.info(f"Saved model report to {report_path}")
        
        return str(report_path)
    
    def save(self, model, metrics_df: pd.DataFrame, config: Optional[Dict] = None):
        """Save M02 model with barrier parameters."""
        if config is None:
            config = {}
        
        config['barrier_params'] = self.barrier_params
        
        return super().save(model, metrics_df, config)
