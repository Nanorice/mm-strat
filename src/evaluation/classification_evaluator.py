"""Classification Model Evaluator.

Comprehensive evaluation for multi-class classification models with:
- Confusion matrix analysis
- Per-class metrics (precision, recall, F1)
- SHAP feature importance and directionality
- ROC/PR curves (one-vs-rest)
- Calibration analysis (Brier score, reliability diagrams)
- Feature importance (XGBoost gain)

Integrates with:
- BaseEvaluator (common infrastructure)
- EvaluationPlotter (visualization)
- ModelRegistry (DuckDB persistence)
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    brier_score_loss
)

from .base_evaluator import BaseEvaluator
from .plotting import EvaluationPlotter
from .leakage_guard import LeakageGuard

logger = logging.getLogger(__name__)


class ClassificationEvaluator(BaseEvaluator):
    """Multi-class classification evaluator with SHAP and calibration analysis."""

    def __init__(
        self,
        model_name: str,
        model_version: str,
        output_dir: Path,
        class_names: Optional[List[str]] = None,
        db_path: Optional[Path] = None
    ):
        """Initialize classification evaluator.

        Args:
            model_name: Model identifier (e.g., 'M04')
            model_version: Version string (e.g., 'baseline')
            output_dir: Base directory for outputs
            class_names: List of class labels (e.g., ['Noise', 'Moderate', 'Strong', 'Home Run'])
            db_path: Path to DuckDB database
        """
        super().__init__(model_name, model_version, output_dir, db_path)
        self.class_names = class_names
        self.plotter = EvaluationPlotter()

    def evaluate(
        self,
        model: xgb.Booster,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        feature_names: List[str],
        X_train: Optional[pd.DataFrame] = None,
        y_train: Optional[np.ndarray] = None,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[np.ndarray] = None,
        compute_shap: bool = True,
        shap_sample_size: int = 1000
    ) -> Dict[str, Any]:
        """Execute comprehensive classification evaluation.

        Args:
            model: Trained XGBoost booster
            X_test: Test features
            y_test: Test labels
            feature_names: List of feature names
            X_train: Training features (for class distribution plot)
            y_train: Training labels
            X_val: Validation features
            y_val: Validation labels
            compute_shap: Whether to compute SHAP values (slow for large datasets)
            shap_sample_size: Max samples to use for SHAP (subsampled if larger)

        Returns:
            Dictionary with all evaluation metrics
        """
        logger.info(f"🚀 Starting evaluation for {self.model_name}/{self.model_version}")

        # Handle infinite values
        X_test_clean = X_test.replace([np.inf, -np.inf], np.nan)

        # 1. Generate predictions
        logger.info("📊 Generating predictions...")
        dtest = xgb.DMatrix(X_test_clean, enable_categorical=True)
        y_pred_proba = model.predict(dtest)
        y_pred = np.argmax(y_pred_proba, axis=1)

        # 2. Basic metrics
        logger.info("📈 Computing basic metrics...")
        metrics = self._compute_basic_metrics(y_test, y_pred, y_pred_proba)

        # 3. Confusion matrix
        logger.info("🔲 Computing confusion matrix...")
        cm = confusion_matrix(y_test, y_pred)
        metrics['confusion_matrix'] = cm.tolist()

        # 4. Classification report (per-class metrics)
        logger.info("📋 Generating classification report...")
        report = classification_report(
            y_test,
            y_pred,
            target_names=self.class_names,
            output_dict=True,
            zero_division=0
        )
        metrics['classification_report'] = report
        metrics['per_class_metrics'] = self._extract_per_class_metrics(report)

        # 5. Feature importance (XGBoost gain)
        logger.info("📊 Extracting feature importance...")
        importance_df = self._get_feature_importance(model, feature_names)
        metrics['feature_importance'] = importance_df.to_dict(orient='records')

        # 6. ROC/PR curves
        logger.info("📈 Computing ROC and PR curves...")
        roc_auc = self._compute_roc_auc(y_test, y_pred_proba)
        pr_auc = self._compute_pr_auc(y_test, y_pred_proba)
        metrics['roc_auc_per_class'] = roc_auc
        metrics['pr_auc_per_class'] = pr_auc

        # 7. Calibration (Brier score)
        logger.info("🎯 Computing calibration metrics...")
        brier = self._compute_brier_score(y_test, y_pred_proba)
        metrics['brier_score'] = brier

        # 8. SHAP analysis (optional - can be slow)
        if compute_shap:
            logger.info(f"🔍 Computing SHAP values (sample_size={shap_sample_size})...")
            shap_results = self._compute_shap(model, X_test_clean, shap_sample_size)
            metrics['shap_summary'] = shap_results
        else:
            logger.info("⏭️  Skipping SHAP computation (compute_shap=False)")
            metrics['shap_summary'] = None

        # 9. Generate visualizations
        logger.info("🎨 Generating visualizations...")
        self._generate_plots(
            y_test,
            y_pred,
            y_pred_proba,
            cm,
            importance_df,
            metrics.get('shap_summary'),
            X_test_clean,
            y_train,
            y_val
        )

        # 10. Save results
        logger.info("💾 Saving evaluation results...")
        self.save_results(metrics, self.plots, update_registry=True)

        logger.info(f"✅ Evaluation complete for {self.model_name}/{self.model_version}")
        return metrics

    def _compute_basic_metrics(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        y_pred_proba: np.ndarray
    ) -> Dict[str, float]:
        """Compute basic classification metrics."""
        return {
            'accuracy': float(accuracy_score(y_true, y_pred)),
            'weighted_f1': float(f1_score(y_true, y_pred, average='weighted', zero_division=0)),
            'macro_f1': float(f1_score(y_true, y_pred, average='macro', zero_division=0)),
            'micro_f1': float(f1_score(y_true, y_pred, average='micro', zero_division=0)),
            'test_samples': int(len(y_true))
        }

    def _extract_per_class_metrics(self, report: Dict) -> Dict[str, Dict]:
        """Extract per-class precision, recall, F1 from classification report."""
        per_class = {}
        for class_idx, class_name in enumerate(self.class_names or []):
            if str(class_idx) in report:
                per_class[class_name] = {
                    'precision': report[str(class_idx)]['precision'],
                    'recall': report[str(class_idx)]['recall'],
                    'f1-score': report[str(class_idx)]['f1-score'],
                    'support': report[str(class_idx)]['support']
                }
        return per_class

    def _get_feature_importance(
        self,
        model: xgb.Booster,
        feature_names: List[str]
    ) -> pd.DataFrame:
        """Extract XGBoost feature importance (gain-based)."""
        importance_dict = model.get_score(importance_type='gain')

        # Map feature indices to names
        importance_data = []
        for feat, gain in importance_dict.items():
            # XGBoost can use f0, f1, ... or actual feature names
            if feat.startswith('f') and feat[1:].isdigit():
                # Indexed feature (f0, f1, ...)
                try:
                    idx = int(feat[1:])
                    if idx < len(feature_names):
                        importance_data.append({
                            'feature': feature_names[idx],
                            'gain': gain
                        })
                except (ValueError, IndexError):
                    pass
            elif feat in feature_names:
                # Named feature
                importance_data.append({
                    'feature': feat,
                    'gain': gain
                })
            else:
                # Unknown feature - log warning but skip
                logger.warning(f"Unknown feature in importance: {feat}")

        df = pd.DataFrame(importance_data)
        if len(df) > 0:
            df = df.sort_values('gain', ascending=False).reset_index(drop=True)

        return df

    def _compute_roc_auc(
        self,
        y_true: np.ndarray,
        y_pred_proba: np.ndarray
    ) -> Dict[str, float]:
        """Compute ROC AUC for each class (one-vs-rest)."""
        from sklearn.metrics import roc_auc_score
        from sklearn.preprocessing import label_binarize

        n_classes = y_pred_proba.shape[1]
        y_true_bin = label_binarize(y_true, classes=range(n_classes))

        roc_auc = {}
        for i, class_name in enumerate(self.class_names or [f"Class_{i}" for i in range(n_classes)]):
            try:
                auc = roc_auc_score(y_true_bin[:, i], y_pred_proba[:, i])
                roc_auc[class_name] = float(auc)
            except ValueError as e:
                logger.warning(f"Could not compute ROC AUC for {class_name}: {e}")
                roc_auc[class_name] = None

        return roc_auc

    def _compute_pr_auc(
        self,
        y_true: np.ndarray,
        y_pred_proba: np.ndarray
    ) -> Dict[str, float]:
        """Compute PR AUC (Average Precision) for each class."""
        from sklearn.metrics import average_precision_score
        from sklearn.preprocessing import label_binarize

        n_classes = y_pred_proba.shape[1]
        y_true_bin = label_binarize(y_true, classes=range(n_classes))

        pr_auc = {}
        for i, class_name in enumerate(self.class_names or [f"Class_{i}" for i in range(n_classes)]):
            try:
                ap = average_precision_score(y_true_bin[:, i], y_pred_proba[:, i])
                pr_auc[class_name] = float(ap)
            except ValueError as e:
                logger.warning(f"Could not compute PR AUC for {class_name}: {e}")
                pr_auc[class_name] = None

        return pr_auc

    def _compute_brier_score(
        self,
        y_true: np.ndarray,
        y_pred_proba: np.ndarray
    ) -> Dict[str, float]:
        """Compute Brier score for calibration quality."""
        from sklearn.preprocessing import label_binarize

        n_classes = y_pred_proba.shape[1]
        y_true_bin = label_binarize(y_true, classes=range(n_classes))

        brier_scores = {}
        for i, class_name in enumerate(self.class_names or [f"Class_{i}" for i in range(n_classes)]):
            try:
                brier = brier_score_loss(y_true_bin[:, i], y_pred_proba[:, i])
                brier_scores[class_name] = float(brier)
            except ValueError as e:
                logger.warning(f"Could not compute Brier score for {class_name}: {e}")
                brier_scores[class_name] = None

        # Overall Brier score (mean across classes)
        valid_scores = [v for v in brier_scores.values() if v is not None]
        brier_scores['mean'] = float(np.mean(valid_scores)) if valid_scores else None

        return brier_scores

    def _compute_shap(
        self,
        model: xgb.Booster,
        X_test: pd.DataFrame,
        sample_size: int = 1000
    ) -> Dict:
        """Compute SHAP values for feature importance and directionality.

        Args:
            model: XGBoost model
            X_test: Test features
            sample_size: Max samples to use (subsampled if larger)

        Returns:
            Dictionary with SHAP summary statistics
        """
        try:
            import shap
        except ImportError:
            logger.error("SHAP package not installed. Run: pip install shap")
            return {'error': 'SHAP not installed'}

        # Subsample if needed
        if len(X_test) > sample_size:
            logger.info(f"📉 Subsampling from {len(X_test):,} to {sample_size:,} for SHAP")
            X_sample = X_test.sample(n=sample_size, random_state=42)
        else:
            X_sample = X_test

        # Compute SHAP values
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_sample)

        # SHAP values are per-class for multi-class models
        # Shape: (n_classes, n_samples, n_features)

        # Get mean absolute SHAP values per class
        mean_shap_per_class = {}
        for i, class_name in enumerate(self.class_names or [f"Class_{i}" for i in range(len(shap_values))]):
            mean_abs_shap = np.abs(shap_values[i]).mean(axis=0)
            top_features_idx = np.argsort(mean_abs_shap)[::-1][:10]
            top_features = [
                {
                    'feature': X_sample.columns[idx],
                    'mean_abs_shap': float(mean_abs_shap[idx])
                }
                for idx in top_features_idx
            ]
            mean_shap_per_class[class_name] = top_features

        return {
            'base_value': float(explainer.expected_value[0]) if hasattr(explainer.expected_value, '__len__') else float(explainer.expected_value),
            'mean_abs_shap_per_class': mean_shap_per_class,
            'sample_size': len(X_sample),
            'shap_values_shape': [len(shap_values), len(X_sample), len(X_sample.columns)]
        }

    def _generate_plots(
        self,
        y_test: np.ndarray,
        y_pred: np.ndarray,
        y_pred_proba: np.ndarray,
        cm: np.ndarray,
        importance_df: pd.DataFrame,
        shap_summary: Optional[Dict],
        X_test: pd.DataFrame,
        y_train: Optional[np.ndarray],
        y_val: Optional[np.ndarray]
    ) -> None:
        """Generate all evaluation plots."""

        # 1. Confusion matrix (counts)
        cm_path = self.get_output_path('confusion_matrix.png')
        self.plotter.plot_confusion_matrix(
            cm,
            self.class_names or [f"Class {i}" for i in range(len(cm))],
            cm_path,
            normalize=False,
            title="Confusion Matrix (Counts)"
        )
        self.add_plot('confusion_matrix', cm_path)

        # 2. Confusion matrix (percentages)
        cm_norm_path = self.get_output_path('confusion_matrix_normalized.png')
        self.plotter.plot_confusion_matrix(
            cm,
            self.class_names or [f"Class {i}" for i in range(len(cm))],
            cm_norm_path,
            normalize=True,
            title="Confusion Matrix (Normalized)"
        )
        self.add_plot('confusion_matrix_normalized', cm_norm_path)

        # 3. Feature importance
        if len(importance_df) > 0:
            fi_path = self.get_output_path('feature_importance.png')
            self.plotter.plot_feature_importance(
                importance_df,
                fi_path,
                top_n=20,
                title="Feature Importance (XGBoost Gain)"
            )
            self.add_plot('feature_importance', fi_path)

        # 4. ROC curves
        roc_path = self.get_output_path('roc_curves.png')
        self.plotter.plot_roc_curve_multiclass(
            y_test,
            y_pred_proba,
            self.class_names or [f"Class {i}" for i in range(y_pred_proba.shape[1])],
            roc_path
        )
        self.add_plot('roc_curves', roc_path)

        # 5. PR curves
        pr_path = self.get_output_path('pr_curves.png')
        self.plotter.plot_pr_curve_multiclass(
            y_test,
            y_pred_proba,
            self.class_names or [f"Class {i}" for i in range(y_pred_proba.shape[1])],
            pr_path
        )
        self.add_plot('pr_curves', pr_path)

        # 6. Calibration curves
        cal_path = self.get_output_path('calibration_curves.png')
        self.plotter.plot_calibration_curve(
            y_test,
            y_pred_proba,
            self.class_names or [f"Class {i}" for i in range(y_pred_proba.shape[1])],
            cal_path
        )
        self.add_plot('calibration_curves', cal_path)

        # 7. Class distribution (if train/val provided)
        if y_train is not None and y_val is not None:
            dist_path = self.get_output_path('class_distribution.png')
            self.plotter.plot_class_distribution(
                y_train,
                y_val,
                y_test,
                self.class_names or [f"Class {i}" for i in range(y_pred_proba.shape[1])],
                dist_path
            )
            self.add_plot('class_distribution', dist_path)

        # 8. SHAP plots (if computed)
        if shap_summary and 'error' not in shap_summary:
            logger.info("📊 SHAP plots skipped (use external SHAP library for plotting)")
            # Note: SHAP plotting requires the actual shap_values array,
            # which we don't store to avoid memory issues.
            # For full SHAP plots, recompute in a separate script.

    def generate_report(self, metrics: Dict[str, Any], plots: Dict[str, Path]) -> Path:
        """Generate markdown evaluation report.

        Args:
            metrics: Evaluation metrics
            plots: Dictionary of plot paths

        Returns:
            Path to generated report
        """
        from .classification_report import ClassificationReportGenerator

        report_gen = ClassificationReportGenerator(
            self.eval_dir,
            self.model_name,
            self.model_version,
            self.class_names
        )

        report_path = report_gen.generate(metrics, plots)
        logger.info(f"📄 Report generated: {report_path}")
        return report_path

    def _update_registry(self, metrics: Dict[str, Any], report_path: Path) -> None:
        """Update model registry with classification metrics.

        Note: Current registry schema supports regression metrics only.
        This is a placeholder for future schema updates.
        """
        logger.info(f"📝 Model registry update skipped (classification schema not yet implemented)")
        # TODO: Update registry schema to support classification metrics
        # For now, metrics are saved to JSON only
