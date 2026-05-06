"""Visualization Library for Model Evaluation.

Standardized plotting utilities for:
- Confusion matrices (heatmaps)
- Feature importance (bar charts)
- SHAP summary plots (bar + beeswarm)
- ROC/PR curves (multi-class)
- Calibration curves
- Class distribution

All plots use consistent styling and save to high-res PNG/SVG.
"""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.figure import Figure

logger = logging.getLogger(__name__)

# Consistent styling
plt.style.use('seaborn-v0_8-darkgrid')
FIGSIZE_SMALL = (8, 6)
FIGSIZE_MEDIUM = (10, 8)
FIGSIZE_LARGE = (12, 10)
DPI = 150


class EvaluationPlotter:
    """Standardized plotting for model evaluation."""

    @staticmethod
    def plot_confusion_matrix(
        cm: np.ndarray,
        class_names: List[str],
        output_path: Path,
        normalize: bool = False,
        title: str = "Confusion Matrix"
    ) -> Path:
        """Plot confusion matrix heatmap.

        Args:
            cm: Confusion matrix (n_classes x n_classes)
            class_names: List of class labels
            output_path: Path to save plot
            normalize: Whether to show percentages (True) or counts (False)
            title: Plot title

        Returns:
            Path to saved plot
        """
        fig, ax = plt.subplots(figsize=FIGSIZE_SMALL)

        if normalize:
            cm_norm = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]
            sns.heatmap(
                cm_norm,
                annot=True,
                fmt='.2%',
                cmap='Blues',
                xticklabels=class_names,
                yticklabels=class_names,
                cbar_kws={'label': 'Percentage'},
                ax=ax
            )
        else:
            sns.heatmap(
                cm,
                annot=True,
                fmt='d',
                cmap='Blues',
                xticklabels=class_names,
                yticklabels=class_names,
                cbar_kws={'label': 'Count'},
                ax=ax
            )

        ax.set_xlabel('Predicted Class', fontsize=12)
        ax.set_ylabel('True Class', fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold')

        plt.tight_layout()
        plt.savefig(output_path, dpi=DPI, bbox_inches='tight')
        plt.close()

        logger.info(f"📊 Confusion matrix saved: {output_path}")
        return output_path

    @staticmethod
    def plot_feature_importance(
        importance_df: pd.DataFrame,
        output_path: Path,
        top_n: int = 20,
        title: str = "Feature Importance"
    ) -> Path:
        """Plot feature importance bar chart.

        Args:
            importance_df: DataFrame with 'feature' and 'gain' columns
            output_path: Path to save plot
            top_n: Number of top features to show
            title: Plot title

        Returns:
            Path to saved plot
        """
        fig, ax = plt.subplots(figsize=FIGSIZE_MEDIUM)

        # Get top N features
        top_features = importance_df.head(top_n).copy()

        # Plot
        colors = plt.cm.viridis(np.linspace(0.3, 0.9, len(top_features)))
        bars = ax.barh(
            range(len(top_features)),
            top_features['gain'],
            color=colors,
            edgecolor='black',
            linewidth=0.5
        )

        # Labels
        ax.set_yticks(range(len(top_features)))
        ax.set_yticklabels(top_features['feature'], fontsize=9)
        ax.invert_yaxis()
        ax.set_xlabel('Gain', fontsize=12)
        ax.set_title(f"{title} (Top {top_n})", fontsize=14, fontweight='bold')

        # Add value labels
        for i, (bar, val) in enumerate(zip(bars, top_features['gain'])):
            ax.text(
                bar.get_width() + 0.01 * max(top_features['gain']),
                bar.get_y() + bar.get_height() / 2,
                f'{val:.3f}',
                va='center',
                fontsize=8
            )

        plt.tight_layout()
        plt.savefig(output_path, dpi=DPI, bbox_inches='tight')
        plt.close()

        logger.info(f"📊 Feature importance saved: {output_path}")
        return output_path

    @staticmethod
    def plot_shap_summary(
        shap_values: np.ndarray,
        X_test: pd.DataFrame,
        class_idx: int,
        class_name: str,
        output_path: Path,
        top_n: int = 20
    ) -> Tuple[Path, Path]:
        """Plot SHAP summary plots (bar + beeswarm).

        Args:
            shap_values: SHAP values for class (n_samples x n_features)
            X_test: Test data (n_samples x n_features)
            class_idx: Index of class
            class_name: Name of class for title
            output_path: Base path (will append _bar.png and _beeswarm.png)
            top_n: Number of top features to show

        Returns:
            Tuple of (bar_plot_path, beeswarm_plot_path)
        """
        try:
            import shap
        except ImportError:
            logger.error("SHAP package not installed. Run: pip install shap")
            raise

        base_path = Path(output_path)
        bar_path = base_path.parent / f"{base_path.stem}_bar.png"
        beeswarm_path = base_path.parent / f"{base_path.stem}_beeswarm.png"

        # Bar plot (importance)
        plt.figure(figsize=FIGSIZE_MEDIUM)
        shap.summary_plot(
            shap_values,
            X_test,
            plot_type='bar',
            max_display=top_n,
            show=False
        )
        plt.title(f"SHAP Feature Importance - {class_name}", fontsize=14, fontweight='bold')
        plt.tight_layout()
        plt.savefig(bar_path, dpi=DPI, bbox_inches='tight')
        plt.close()

        # Beeswarm plot (directionality)
        plt.figure(figsize=FIGSIZE_MEDIUM)
        shap.summary_plot(
            shap_values,
            X_test,
            max_display=top_n,
            show=False
        )
        plt.title(f"SHAP Feature Impact - {class_name}", fontsize=14, fontweight='bold')
        plt.tight_layout()
        plt.savefig(beeswarm_path, dpi=DPI, bbox_inches='tight')
        plt.close()

        logger.info(f"📊 SHAP plots saved: {bar_path}, {beeswarm_path}")
        return bar_path, beeswarm_path

    @staticmethod
    def plot_roc_curve_multiclass(
        y_true: np.ndarray,
        y_pred_proba: np.ndarray,
        class_names: List[str],
        output_path: Path,
        title: str = "ROC Curves (One-vs-Rest)"
    ) -> Path:
        """Plot ROC curves for multi-class classification.

        Args:
            y_true: True labels (n_samples,)
            y_pred_proba: Predicted probabilities (n_samples, n_classes)
            class_names: List of class labels
            output_path: Path to save plot
            title: Plot title

        Returns:
            Path to saved plot
        """
        from sklearn.metrics import roc_curve, auc
        from sklearn.preprocessing import label_binarize

        # Binarize labels for one-vs-rest
        n_classes = len(class_names)
        y_true_bin = label_binarize(y_true, classes=range(n_classes))

        # Compute ROC curve and AUC for each class
        fig, ax = plt.subplots(figsize=FIGSIZE_SMALL)

        colors = plt.cm.tab10(np.linspace(0, 1, n_classes))
        for i, (color, class_name) in enumerate(zip(colors, class_names)):
            fpr, tpr, _ = roc_curve(y_true_bin[:, i], y_pred_proba[:, i])
            roc_auc = auc(fpr, tpr)
            ax.plot(
                fpr,
                tpr,
                color=color,
                lw=2,
                label=f'{class_name} (AUC={roc_auc:.3f})'
            )

        # Diagonal reference line
        ax.plot([0, 1], [0, 1], 'k--', lw=1, label='Random (AUC=0.500)')

        ax.set_xlabel('False Positive Rate', fontsize=12)
        ax.set_ylabel('True Positive Rate', fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.legend(loc='lower right', fontsize=9)
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_path, dpi=DPI, bbox_inches='tight')
        plt.close()

        logger.info(f"📊 ROC curve saved: {output_path}")
        return output_path

    @staticmethod
    def plot_pr_curve_multiclass(
        y_true: np.ndarray,
        y_pred_proba: np.ndarray,
        class_names: List[str],
        output_path: Path,
        title: str = "Precision-Recall Curves (One-vs-Rest)"
    ) -> Path:
        """Plot PR curves for multi-class classification.

        Args:
            y_true: True labels (n_samples,)
            y_pred_proba: Predicted probabilities (n_samples, n_classes)
            class_names: List of class labels
            output_path: Path to save plot
            title: Plot title

        Returns:
            Path to saved plot
        """
        from sklearn.metrics import precision_recall_curve, average_precision_score
        from sklearn.preprocessing import label_binarize

        # Binarize labels
        n_classes = len(class_names)
        y_true_bin = label_binarize(y_true, classes=range(n_classes))

        # Compute PR curve and AP for each class
        fig, ax = plt.subplots(figsize=FIGSIZE_SMALL)

        colors = plt.cm.tab10(np.linspace(0, 1, n_classes))
        for i, (color, class_name) in enumerate(zip(colors, class_names)):
            precision, recall, _ = precision_recall_curve(y_true_bin[:, i], y_pred_proba[:, i])
            ap = average_precision_score(y_true_bin[:, i], y_pred_proba[:, i])
            ax.plot(
                recall,
                precision,
                color=color,
                lw=2,
                label=f'{class_name} (AP={ap:.3f})'
            )

        ax.set_xlabel('Recall', fontsize=12)
        ax.set_ylabel('Precision', fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.legend(loc='best', fontsize=9)
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_path, dpi=DPI, bbox_inches='tight')
        plt.close()

        logger.info(f"📊 PR curve saved: {output_path}")
        return output_path

    @staticmethod
    def plot_calibration_curve(
        y_true: np.ndarray,
        y_pred_proba: np.ndarray,
        class_names: List[str],
        output_path: Path,
        n_bins: int = 10,
        title: str = "Calibration Curves"
    ) -> Path:
        """Plot calibration curves for each class.

        Args:
            y_true: True labels (n_samples,)
            y_pred_proba: Predicted probabilities (n_samples, n_classes)
            class_names: List of class labels
            output_path: Path to save plot
            n_bins: Number of bins for calibration
            title: Plot title

        Returns:
            Path to saved plot
        """
        from sklearn.calibration import calibration_curve
        from sklearn.preprocessing import label_binarize

        # Binarize labels
        n_classes = len(class_names)
        y_true_bin = label_binarize(y_true, classes=range(n_classes))

        fig, ax = plt.subplots(figsize=FIGSIZE_SMALL)

        colors = plt.cm.tab10(np.linspace(0, 1, n_classes))
        for i, (color, class_name) in enumerate(zip(colors, class_names)):
            prob_true, prob_pred = calibration_curve(
                y_true_bin[:, i],
                y_pred_proba[:, i],
                n_bins=n_bins,
                strategy='uniform'
            )
            ax.plot(
                prob_pred,
                prob_true,
                marker='o',
                color=color,
                lw=2,
                label=class_name
            )

        # Perfect calibration line
        ax.plot([0, 1], [0, 1], 'k--', lw=1, label='Perfect Calibration')

        ax.set_xlabel('Mean Predicted Probability', fontsize=12)
        ax.set_ylabel('Fraction of Positives', fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.legend(loc='best', fontsize=9)
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_path, dpi=DPI, bbox_inches='tight')
        plt.close()

        logger.info(f"📊 Calibration curve saved: {output_path}")
        return output_path

    @staticmethod
    def plot_temporal_stability(
        period_metrics: pd.DataFrame,
        output_path: Path,
        title: str = "Temporal Stability"
    ) -> Path:
        """Plot per-period accuracy / weighted F1 / macro F1 to detect decay or split artifacts.

        Args:
            period_metrics: DataFrame with columns [period, accuracy, weighted_f1, macro_f1, n_samples]
            output_path: Path to save plot
            title: Plot title
        """
        fig, ax1 = plt.subplots(figsize=FIGSIZE_MEDIUM)

        x = np.arange(len(period_metrics))
        ax1.plot(x, period_metrics['accuracy'], marker='o', lw=2, label='Accuracy', color='#1f77b4')
        ax1.plot(x, period_metrics['weighted_f1'], marker='s', lw=2, label='Weighted F1', color='#ff7f0e')
        ax1.plot(x, period_metrics['macro_f1'], marker='^', lw=2, label='Macro F1', color='#2ca02c')
        ax1.axhline(0.25, color='red', linestyle='--', alpha=0.5, label='Random (4-class)')

        ax1.set_xticks(x)
        ax1.set_xticklabels(period_metrics['period'], rotation=45, ha='right')
        ax1.set_ylabel('Score', fontsize=12)
        ax1.set_title(title, fontsize=14, fontweight='bold')
        ax1.legend(loc='upper left', fontsize=9)
        ax1.grid(True, alpha=0.3)

        # Secondary axis for sample count bars
        ax2 = ax1.twinx()
        ax2.bar(x, period_metrics['n_samples'], alpha=0.15, color='gray', label='Samples')
        ax2.set_ylabel('Samples', fontsize=12, color='gray')
        ax2.tick_params(axis='y', labelcolor='gray')
        ax2.grid(False)

        plt.tight_layout()
        plt.savefig(output_path, dpi=DPI, bbox_inches='tight')
        plt.close()

        logger.info(f"📊 Temporal stability saved: {output_path}")
        return output_path

    @staticmethod
    def plot_probability_distributions(
        y_true: np.ndarray,
        y_pred_proba: np.ndarray,
        class_names: List[str],
        output_path: Path,
        title: str = "Predicted Probability Distribution by True Class"
    ) -> Path:
        """For each class, plot histogram of predicted p(class) split by whether the true label matches.

        Reveals whether the model assigns higher probability to true positives than negatives.
        """
        n_classes = len(class_names)
        fig, axes = plt.subplots(1, n_classes, figsize=(4 * n_classes, 4), sharey=True)
        if n_classes == 1:
            axes = [axes]

        for i, (ax, class_name) in enumerate(zip(axes, class_names)):
            mask = y_true == i
            p_pos = y_pred_proba[mask, i]
            p_neg = y_pred_proba[~mask, i]

            bins = np.linspace(0, 1, 30)
            ax.hist(p_neg, bins=bins, alpha=0.5, label='True ≠ class', color='#9e9e9e', density=True)
            ax.hist(p_pos, bins=bins, alpha=0.7, label='True = class', color='#42a5f5', density=True)
            ax.set_title(class_name, fontsize=11, fontweight='bold')
            ax.set_xlabel('Predicted P(class)', fontsize=10)
            if i == 0:
                ax.set_ylabel('Density', fontsize=10)
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)

        fig.suptitle(title, fontsize=13, fontweight='bold', y=1.02)
        plt.tight_layout()
        plt.savefig(output_path, dpi=DPI, bbox_inches='tight')
        plt.close()

        logger.info(f"📊 Probability distribution saved: {output_path}")
        return output_path

    @staticmethod
    def plot_topk_precision(
        topk_df: pd.DataFrame,
        class_names: List[str],
        output_path: Path,
        title: str = "Precision @ K (Ranked by Predicted Probability)"
    ) -> Path:
        """Plot precision-at-k curve for each class.

        Args:
            topk_df: DataFrame with columns [k, class_name, precision, lift]
            class_names: classes to plot
            output_path: save path
        """
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=FIGSIZE_LARGE)

        colors = plt.cm.tab10(np.linspace(0, 1, len(class_names)))
        for color, class_name in zip(colors, class_names):
            sub = topk_df[topk_df['class'] == class_name].sort_values('k')
            if sub.empty:
                continue
            ax1.plot(sub['k'], sub['precision'], marker='o', lw=2, label=class_name, color=color)
            ax2.plot(sub['k'], sub['lift'], marker='o', lw=2, label=class_name, color=color)

        ax1.set_xscale('log')
        ax1.set_xlabel('K (top predictions)', fontsize=11)
        ax1.set_ylabel('Precision', fontsize=11)
        ax1.set_title('Precision @ K', fontsize=12, fontweight='bold')
        ax1.legend(fontsize=9)
        ax1.grid(True, alpha=0.3)

        ax2.set_xscale('log')
        ax2.axhline(1.0, color='red', linestyle='--', alpha=0.5, label='Baseline (lift=1)')
        ax2.set_xlabel('K (top predictions)', fontsize=11)
        ax2.set_ylabel('Lift over Random', fontsize=11)
        ax2.set_title('Lift @ K', fontsize=12, fontweight='bold')
        ax2.legend(fontsize=9)
        ax2.grid(True, alpha=0.3)

        fig.suptitle(title, fontsize=13, fontweight='bold', y=1.02)
        plt.tight_layout()
        plt.savefig(output_path, dpi=DPI, bbox_inches='tight')
        plt.close()

        logger.info(f"📊 Top-K precision saved: {output_path}")
        return output_path

    @staticmethod
    def plot_threshold_sweep(
        sweep_df: pd.DataFrame,
        output_path: Path,
        title: str = "Actionable Signal Threshold Sweep"
    ) -> Path:
        """Plot precision/recall/signal-count vs threshold for an actionable-class signal.

        Args:
            sweep_df: DataFrame with columns [threshold, precision, recall, n_signals]
            output_path: save path
        """
        fig, ax1 = plt.subplots(figsize=FIGSIZE_MEDIUM)

        ax1.plot(sweep_df['threshold'], sweep_df['precision'], marker='o', lw=2,
                 label='Precision', color='#1f77b4')
        ax1.plot(sweep_df['threshold'], sweep_df['recall'], marker='s', lw=2,
                 label='Recall', color='#ff7f0e')
        ax1.set_xlabel('Probability Threshold', fontsize=12)
        ax1.set_ylabel('Precision / Recall', fontsize=12)
        ax1.set_ylim(0, 1)
        ax1.legend(loc='upper left', fontsize=10)
        ax1.grid(True, alpha=0.3)

        ax2 = ax1.twinx()
        ax2.bar(sweep_df['threshold'], sweep_df['n_signals'], width=0.04,
                alpha=0.2, color='gray', label='Signals')
        ax2.set_ylabel('Signal Count', fontsize=12, color='gray')
        ax2.tick_params(axis='y', labelcolor='gray')
        ax2.grid(False)

        ax1.set_title(title, fontsize=14, fontweight='bold')
        plt.tight_layout()
        plt.savefig(output_path, dpi=DPI, bbox_inches='tight')
        plt.close()

        logger.info(f"📊 Threshold sweep saved: {output_path}")
        return output_path

    @staticmethod
    def plot_class_distribution(
        y_train: np.ndarray,
        y_val: np.ndarray,
        y_test: np.ndarray,
        class_names: List[str],
        output_path: Path,
        title: str = "Class Distribution Across Splits"
    ) -> Path:
        """Plot class distribution across train/val/test splits.

        Args:
            y_train: Training labels
            y_val: Validation labels
            y_test: Test labels
            class_names: List of class labels
            output_path: Path to save plot
            title: Plot title

        Returns:
            Path to saved plot
        """
        fig, ax = plt.subplots(figsize=FIGSIZE_SMALL)

        # Count class frequencies
        splits = ['Train', 'Val', 'Test']
        datasets = [y_train, y_val, y_test]

        x = np.arange(len(class_names))
        width = 0.25

        for i, (split_name, data) in enumerate(zip(splits, datasets)):
            counts = [np.sum(data == cls) for cls in range(len(class_names))]
            offset = width * (i - 1)
            ax.bar(x + offset, counts, width, label=split_name, alpha=0.8)

        ax.set_xlabel('Class', fontsize=12)
        ax.set_ylabel('Count', fontsize=12)
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(class_names)
        ax.legend(loc='best', fontsize=10)
        ax.grid(True, axis='y', alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_path, dpi=DPI, bbox_inches='tight')
        plt.close()

        logger.info(f"📊 Class distribution saved: {output_path}")
        return output_path
