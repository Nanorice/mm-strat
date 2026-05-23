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
from .calibration import calibration_audit
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
        dates_test: Optional[pd.Series] = None,
        actionable_classes: Optional[List[int]] = None,
        compute_shap: bool = True,
        shap_sample_size: int = 1000,
        compute_permutation_importance: bool = False,
        permutation_n_repeats: int = 5,
        permutation_sample_size: int = 2000,
        regimes_test: Optional[pd.Series] = None,
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

        # 7. Calibration (Brier score + ECE gate)
        logger.info("🎯 Computing calibration metrics...")
        brier = self._compute_brier_score(y_test, y_pred_proba)
        metrics['brier_score'] = brier

        # ECE per class, with a blocking gate on the production class. Convention:
        # production_class = last actionable class (matches threshold_sweep).
        actionable_for_calib = (
            actionable_classes if actionable_classes is not None
            else self._default_actionable_classes()
        )
        production_class_idx = actionable_for_calib[-1]
        try:
            calib = calibration_audit(
                y_true=np.asarray(y_test),
                y_pred_proba=y_pred_proba,
                class_names=self.class_names or [f"Class_{i}" for i in range(y_pred_proba.shape[1])],
                production_class_idx=int(production_class_idx),
                ece_threshold=0.05,
            )
            metrics['ece_per_class'] = {
                name: d["ece"] for name, d in calib["ece_per_class"].items()
            }
            metrics['production_class_ece'] = calib["production_class_ece"]
            metrics.setdefault('gates', []).append(calib['gate'])
        except Exception as e:  # pragma: no cover — best-effort
            logger.warning(f"calibration_audit skipped: {e}")

        # 8. Class distribution (train/val/test)
        logger.info("📊 Computing class distribution...")
        metrics['class_distribution'] = self._compute_class_distribution(y_train, y_val, y_test)

        # 9. Temporal stability (per-period metrics)
        if dates_test is not None:
            logger.info("📅 Computing temporal stability...")
            metrics['temporal_stability'] = self._compute_temporal_stability(
                np.asarray(y_test), y_pred, dates_test
            )
        else:
            metrics['temporal_stability'] = None

        # 10. Probability distribution stats
        logger.info("📊 Computing probability distribution stats...")
        metrics['probability_stats'] = self._compute_probability_stats(
            np.asarray(y_test), y_pred_proba
        )

        # 11. Top-K precision / lift per class
        logger.info("🎯 Computing top-K precision...")
        metrics['topk_precision'] = self._compute_topk_precision(
            np.asarray(y_test), y_pred_proba
        )

        # 12. Threshold sweep (actionable signal)
        actionable = actionable_classes if actionable_classes is not None else self._default_actionable_classes()
        metrics['actionable_classes'] = actionable
        logger.info(f"🎯 Computing threshold sweep for actionable classes {actionable}...")
        metrics['threshold_sweep'] = self._compute_threshold_sweep(
            np.asarray(y_test), y_pred_proba, actionable
        )

        # 13. SHAP analysis (optional - can be slow)
        if compute_shap:
            logger.info(f"🔍 Computing SHAP values (sample_size={shap_sample_size})...")
            shap_results = self._compute_shap(model, X_test_clean, shap_sample_size)
            metrics['shap_summary'] = shap_results
        else:
            logger.info("⏭️  Skipping SHAP computation (compute_shap=False)")
            metrics['shap_summary'] = None

        # 13b. Permutation importance (§3.3.1). Diagnostic, no gate.
        if compute_permutation_importance:
            logger.info(f"🔀 Computing permutation importance "
                        f"(n_repeats={permutation_n_repeats}, sample_size={permutation_sample_size})...")
            try:
                perm_df = self._compute_permutation_importance(
                    model=model,
                    X_test=X_test_clean,
                    y_test=np.asarray(y_test),
                    n_repeats=permutation_n_repeats,
                    sample_size=permutation_sample_size,
                )
                metrics['permutation_importance'] = perm_df.to_dict(orient='records')
            except Exception as e:
                logger.warning(f"permutation_importance skipped: {e}")
                metrics['permutation_importance'] = None
        else:
            metrics['permutation_importance'] = None

        # 13c. Regime decomposition (§3.2). Blocking gate on production class.
        if regimes_test is not None:
            try:
                from .regime_decomposition import metrics_by_regime, regime_decomposition_gate
                regime_df = pd.DataFrame({
                    "regime_cat": np.asarray(regimes_test).astype(int),
                    "y": np.asarray(y_test).astype(int),
                    "y_pred": y_pred,
                    "y_prob": y_pred_proba[:, int(production_class_idx)],
                })
                by_regime = metrics_by_regime(
                    df=regime_df,
                    y_col="y", y_pred_col="y_pred", y_prob_col="y_prob",
                    production_class_idx=int(production_class_idx),
                )
                gate = regime_decomposition_gate(by_regime)
                metrics['regime_decomposition'] = {
                    "by_regime": by_regime,
                    "gate": gate.to_dict(),
                }
                metrics.setdefault('gates', []).append(gate.to_dict())
            except Exception as e:
                logger.warning(f"regime_decomposition skipped: {e}")
                metrics['regime_decomposition'] = None
        else:
            metrics['regime_decomposition'] = None

        # 14. Generate visualizations
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
            y_val,
            metrics.get('temporal_stability'),
            metrics['topk_precision'],
            metrics['threshold_sweep'],
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
        """Extract per-class precision, recall, F1 from classification report.

        sklearn keys by class name when `target_names` is set, else by stringified index.
        """
        per_class = {}
        for class_idx, class_name in enumerate(self.class_names or []):
            key = class_name if class_name in report else str(class_idx)
            if key in report:
                per_class[class_name] = {
                    'precision': report[key]['precision'],
                    'recall': report[key]['recall'],
                    'f1-score': report[key]['f1-score'],
                    'support': report[key]['support']
                }
        return per_class

    def _default_actionable_classes(self) -> List[int]:
        """Last two classes are 'actionable' by default (Strong + Home Run for MFE)."""
        n = len(self.class_names) if self.class_names else 4
        return [n - 2, n - 1] if n >= 2 else [n - 1]

    def _compute_class_distribution(
        self,
        y_train: Optional[np.ndarray],
        y_val: Optional[np.ndarray],
        y_test: np.ndarray,
    ) -> Dict[str, Dict[str, int]]:
        """Counts and proportions per class across splits."""
        n_classes = len(self.class_names) if self.class_names else int(np.max(y_test)) + 1
        names = self.class_names or [f"Class_{i}" for i in range(n_classes)]

        def split_counts(y: Optional[np.ndarray]) -> Dict[str, Any]:
            if y is None or len(y) == 0:
                return {name: {'count': 0, 'pct': 0.0} for name in names}
            y_arr = np.asarray(y)
            total = len(y_arr)
            return {
                name: {
                    'count': int(np.sum(y_arr == i)),
                    'pct': float(np.sum(y_arr == i) / total),
                }
                for i, name in enumerate(names)
            }

        return {
            'train': split_counts(y_train),
            'val': split_counts(y_val),
            'test': split_counts(y_test),
        }

    def _compute_temporal_stability(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        dates: pd.Series,
    ) -> List[Dict[str, Any]]:
        """Per-period (year or quarter) accuracy / weighted_f1 / macro_f1.

        Auto-pick period: if span <= 3 years, group by quarter; else by year.
        """
        d = pd.to_datetime(pd.Series(dates).reset_index(drop=True))
        span_years = (d.max() - d.min()).days / 365.25 if len(d) > 0 else 0
        period = d.dt.to_period('Q' if span_years <= 3 else 'Y').astype(str)

        rows = []
        for p in sorted(period.unique()):
            mask = (period == p).to_numpy()
            if mask.sum() < 30:  # skip thin periods
                continue
            yt = y_true[mask]
            yp = y_pred[mask]
            rows.append({
                'period': p,
                'n_samples': int(mask.sum()),
                'accuracy': float(accuracy_score(yt, yp)),
                'weighted_f1': float(f1_score(yt, yp, average='weighted', zero_division=0)),
                'macro_f1': float(f1_score(yt, yp, average='macro', zero_division=0)),
            })
        return rows

    def _compute_probability_stats(
        self,
        y_true: np.ndarray,
        y_pred_proba: np.ndarray,
    ) -> Dict[str, Dict[str, float]]:
        """Mean predicted probability for true positives vs negatives, per class."""
        n_classes = y_pred_proba.shape[1]
        names = self.class_names or [f"Class_{i}" for i in range(n_classes)]
        stats = {}
        for i, name in enumerate(names):
            mask = y_true == i
            p_pos = y_pred_proba[mask, i] if mask.any() else np.array([])
            p_neg = y_pred_proba[~mask, i] if (~mask).any() else np.array([])
            stats[name] = {
                'mean_p_when_true': float(p_pos.mean()) if p_pos.size else 0.0,
                'mean_p_when_false': float(p_neg.mean()) if p_neg.size else 0.0,
                'separation': float(p_pos.mean() - p_neg.mean()) if p_pos.size and p_neg.size else 0.0,
                'support_positive': int(mask.sum()),
            }
        return stats

    def _compute_topk_precision(
        self,
        y_true: np.ndarray,
        y_pred_proba: np.ndarray,
        ks: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """For each class, precision among top-K samples ranked by p(class).

        Lift = precision@k / base rate of class in test set.
        """
        n_classes = y_pred_proba.shape[1]
        names = self.class_names or [f"Class_{i}" for i in range(n_classes)]
        n = len(y_true)

        if ks is None:
            ks = [k for k in [10, 50, 100, 250, 500, 1000] if k <= n]
            if not ks:
                ks = [max(1, n // 10)]

        rows = []
        for i, name in enumerate(names):
            base_rate = float(np.mean(y_true == i))
            if base_rate == 0:
                continue
            order = np.argsort(-y_pred_proba[:, i])
            for k in ks:
                top = order[:k]
                hits = int(np.sum(y_true[top] == i))
                precision = hits / k
                rows.append({
                    'class': name,
                    'k': k,
                    'precision': float(precision),
                    'lift': float(precision / base_rate) if base_rate > 0 else None,
                    'hits': hits,
                    'base_rate': base_rate,
                })
        return rows

    def _compute_threshold_sweep(
        self,
        y_true: np.ndarray,
        y_pred_proba: np.ndarray,
        actionable_classes: List[int],
        thresholds: Optional[List[float]] = None,
    ) -> List[Dict[str, Any]]:
        """Sweep p-threshold for the union of actionable classes.

        Signal = max p over actionable classes >= threshold.
        Precision = signals where true label is in actionable_classes / signals.
        Recall = signals where true is actionable / total actuals in actionable.
        """
        if thresholds is None:
            thresholds = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70]

        true_actionable = np.isin(y_true, actionable_classes)
        total_actionable = int(true_actionable.sum())
        max_actionable_p = y_pred_proba[:, actionable_classes].max(axis=1)

        rows = []
        for thr in thresholds:
            signal = max_actionable_p >= thr
            n_signals = int(signal.sum())
            tp = int((signal & true_actionable).sum())
            precision = tp / n_signals if n_signals > 0 else 0.0
            recall = tp / total_actionable if total_actionable > 0 else 0.0
            rows.append({
                'threshold': float(thr),
                'n_signals': n_signals,
                'true_positives': tp,
                'precision': float(precision),
                'recall': float(recall),
            })
        return rows

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

        # SHAP's TreeExplainer builds DMatrix internally without enable_categorical,
        # so pandas `category` dtype raises KeyError. Encode categoricals as int codes
        # for SHAP only (model still trained on real categoricals).
        cat_cols = X_sample.select_dtypes(include='category').columns
        if len(cat_cols) > 0:
            X_sample = X_sample.copy()
            for col in cat_cols:
                X_sample[col] = X_sample[col].cat.codes.astype('int32')

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

    def _compute_permutation_importance(
        self,
        model: xgb.Booster,
        X_test: pd.DataFrame,
        y_test: np.ndarray,
        n_repeats: int = 5,
        sample_size: int = 2000,
        random_state: int = 42,
    ) -> pd.DataFrame:
        """Permutation importance using log-loss as the scorer (§3.3.1).

        Wraps `sklearn.inspection.permutation_importance` with an XGBoost adapter.
        Returns DataFrame[feature, mean_importance, std_importance] sorted
        descending by mean_importance.
        """
        from sklearn.inspection import permutation_importance
        from sklearn.base import BaseEstimator, ClassifierMixin

        y_arr = np.asarray(y_test)
        if len(X_test) > sample_size:
            rng = np.random.default_rng(random_state)
            idx = rng.choice(len(X_test), size=sample_size, replace=False)
            X_use = X_test.iloc[idx].reset_index(drop=True)
            y_use = y_arr[idx]
        else:
            X_use = X_test
            y_use = y_arr

        n_classes = len(self.class_names) if self.class_names else int(np.max(y_use)) + 1

        class _XGBAdapter(BaseEstimator, ClassifierMixin):
            """Adapter so sklearn.permutation_importance can call predict_proba on a Booster."""
            def __init__(self, booster, n_classes: int):
                self.booster = booster
                self.classes_ = np.arange(n_classes)

            def fit(self, X, y):
                return self  # already trained

            def predict_proba(self, X):
                X_clean = X.replace([np.inf, -np.inf], np.nan) if hasattr(X, "replace") else X
                dmat = xgb.DMatrix(X_clean, enable_categorical=True)
                return self.booster.predict(dmat)

            def predict(self, X):
                proba = self.predict_proba(X)
                return np.argmax(proba, axis=1)

        adapter = _XGBAdapter(model, n_classes)
        result = permutation_importance(
            adapter,
            X_use,
            y_use,
            n_repeats=n_repeats,
            random_state=random_state,
            scoring="neg_log_loss",
            n_jobs=1,  # XGBoost predict is already parallel
        )

        df = pd.DataFrame({
            "feature": list(X_use.columns),
            "mean_importance": result.importances_mean,
            "std_importance": result.importances_std,
        })
        return df.sort_values("mean_importance", ascending=False).reset_index(drop=True)

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
        y_val: Optional[np.ndarray],
        temporal_stability: Optional[List[Dict]] = None,
        topk_precision: Optional[List[Dict]] = None,
        threshold_sweep: Optional[List[Dict]] = None,
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

        # 9. Probability distributions (true vs false per class)
        prob_dist_path = self.get_output_path('probability_distributions.png')
        self.plotter.plot_probability_distributions(
            y_test, y_pred_proba,
            self.class_names or [f"Class {i}" for i in range(y_pred_proba.shape[1])],
            prob_dist_path,
        )
        self.add_plot('probability_distributions', prob_dist_path)

        # 10. Temporal stability
        if temporal_stability:
            ts_df = pd.DataFrame(temporal_stability)
            ts_path = self.get_output_path('temporal_stability.png')
            self.plotter.plot_temporal_stability(ts_df, ts_path)
            self.add_plot('temporal_stability', ts_path)

        # 11. Top-K precision / lift
        if topk_precision:
            tk_df = pd.DataFrame(topk_precision)
            tk_path = self.get_output_path('topk_precision.png')
            self.plotter.plot_topk_precision(
                tk_df,
                self.class_names or [f"Class {i}" for i in range(y_pred_proba.shape[1])],
                tk_path,
            )
            self.add_plot('topk_precision', tk_path)

        # 12. Threshold sweep
        if threshold_sweep:
            ts_sweep_df = pd.DataFrame(threshold_sweep)
            sweep_path = self.get_output_path('threshold_sweep.png')
            self.plotter.plot_threshold_sweep(ts_sweep_df, sweep_path)
            self.add_plot('threshold_sweep', sweep_path)

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
