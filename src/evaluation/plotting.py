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
