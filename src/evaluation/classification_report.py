"""Classification Report Generator.

Generates comprehensive markdown scorecards for classification models with:
- Executive summary (accuracy, F1, viability assessment)
- Confusion matrix summary
- Per-class performance breakdown
- Feature importance table
- ROC/PR AUC scores
- Calibration quality (Brier score)
- SHAP insights (if available)
- Embedded visualizations
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import pandas as pd

logger = logging.getLogger(__name__)


class ClassificationReportGenerator:
    """Generate comprehensive markdown scorecards for classification models."""

    def __init__(
        self,
        output_dir: Path,
        model_name: str,
        model_version: str,
        class_names: Optional[List[str]] = None
    ):
        """Initialize report generator.

        Args:
            output_dir: Directory for saving report
            model_name: Model identifier (e.g., 'M04')
            model_version: Version string (e.g., 'baseline')
            class_names: List of class labels
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.model_name = model_name
        self.model_version = model_version
        self.class_names = class_names or []

    def generate(
        self,
        metrics: Dict[str, Any],
        plots: Dict[str, Path]
    ) -> Path:
        """Generate complete scorecard report.

        Args:
            metrics: Evaluation metrics dictionary
            plots: Dictionary mapping plot names to file paths

        Returns:
            Path to saved report
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.output_dir / f"report_{timestamp}.md"

        lines = []

        # Header
        lines.extend(self._generate_header())

        # Executive Summary
        lines.extend(self._generate_executive_summary(metrics))

        # Confusion Matrix Analysis
        lines.extend(self._generate_confusion_section(metrics, plots))

        # Per-Class Performance
        lines.extend(self._generate_per_class_section(metrics))

        # ROC/PR Performance
        lines.extend(self._generate_roc_pr_section(metrics, plots))

        # Calibration Analysis
        lines.extend(self._generate_calibration_section(metrics, plots))

        # Feature Importance
        lines.extend(self._generate_feature_importance_section(metrics, plots))

        # SHAP Insights (if available)
        if metrics.get('shap_summary'):
            lines.extend(self._generate_shap_section(metrics))

        # Recommendations
        lines.extend(self._generate_recommendations(metrics))

        # Footer
        lines.extend(self._generate_footer(plots))

        # Write to file (UTF-8 encoding for emojis)
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"📄 Report saved: {report_path}")
        return report_path

    def _generate_header(self) -> List[str]:
        """Generate report header."""
        return [
            f"# {self.model_name} Classification Report",
            f"**Version:** {self.model_version}",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "---",
            ""
        ]

    def _generate_executive_summary(self, metrics: Dict) -> List[str]:
        """Generate executive summary with viability assessment."""
        lines = [
            "## 📊 Executive Summary",
            ""
        ]

        accuracy = metrics.get('accuracy', 0)
        weighted_f1 = metrics.get('weighted_f1', 0)
        macro_f1 = metrics.get('macro_f1', 0)
        test_samples = metrics.get('test_samples', 0)

        # Viability assessment
        viability = self._assess_viability(accuracy, weighted_f1, macro_f1)
        lines.append(f"**Viability:** {viability['emoji']} {viability['status']}")
        lines.append("")

        # Key metrics
        lines.extend([
            "### Key Metrics",
            "",
            f"- **Accuracy:** {accuracy:.3f} ({accuracy * 100:.1f}%)",
            f"- **Weighted F1:** {weighted_f1:.3f}",
            f"- **Macro F1:** {macro_f1:.3f}",
            f"- **Test Samples:** {test_samples:,}",
            "",
            f"**Assessment:** {viability['message']}",
            "",
            "---",
            ""
        ])

        return lines

    def _assess_viability(
        self,
        accuracy: float,
        weighted_f1: float,
        macro_f1: float
    ) -> Dict[str, str]:
        """Assess model viability based on metrics."""

        # Multi-class baseline is 1/n_classes
        n_classes = len(self.class_names) if self.class_names else 4
        baseline_accuracy = 1 / n_classes

        if accuracy < baseline_accuracy * 1.2:
            return {
                'status': 'NOT VIABLE',
                'emoji': '❌',
                'message': f'Accuracy ({accuracy:.1%}) barely exceeds random baseline ({baseline_accuracy:.1%}). Model is not production-ready.'
            }
        elif weighted_f1 < 0.3:
            return {
                'status': 'POOR',
                'emoji': '⚠️',
                'message': f'Weighted F1 ({weighted_f1:.3f}) is too low. Significant improvement needed.'
            }
        elif weighted_f1 < 0.5:
            return {
                'status': 'MARGINAL',
                'emoji': '🟡',
                'message': f'Weighted F1 ({weighted_f1:.3f}) shows promise but needs improvement. Consider feature engineering or hyperparameter tuning.'
            }
        elif weighted_f1 < 0.7:
            return {
                'status': 'ACCEPTABLE',
                'emoji': '✅',
                'message': f'Weighted F1 ({weighted_f1:.3f}) is acceptable for initial deployment. Monitor performance closely.'
            }
        else:
            return {
                'status': 'STRONG',
                'emoji': '🎯',
                'message': f'Weighted F1 ({weighted_f1:.3f}) is strong. Model shows good discriminative power.'
            }

    def _generate_confusion_section(self, metrics: Dict, plots: Dict) -> List[str]:
        """Generate confusion matrix analysis section."""
        lines = [
            "## 🔲 Confusion Matrix Analysis",
            ""
        ]

        # Embed plot if available
        if 'confusion_matrix' in plots:
            rel_path = plots['confusion_matrix'].name
            lines.append(f"![Confusion Matrix]({rel_path})")
            lines.append("")

        if 'confusion_matrix_normalized' in plots:
            rel_path = plots['confusion_matrix_normalized'].name
            lines.append(f"![Confusion Matrix (Normalized)]({rel_path})")
            lines.append("")

        # Confusion matrix table
        cm = metrics.get('confusion_matrix')
        if cm:
            lines.append("### Confusion Matrix (Counts)")
            lines.append("")
            lines.extend(self._format_confusion_matrix_table(cm))
            lines.append("")

        lines.extend([
            "---",
            ""
        ])

        return lines

    def _format_confusion_matrix_table(self, cm: list) -> List[str]:
        """Format confusion matrix as markdown table."""
        lines = []

        # Header
        header = "| True \\ Predicted | " + " | ".join(self.class_names or [f"C{i}" for i in range(len(cm))]) + " |"
        separator = "|" + "|".join(["---"] * (len(cm) + 1)) + "|"

        lines.append(header)
        lines.append(separator)

        # Rows
        for i, row in enumerate(cm):
            class_name = self.class_names[i] if i < len(self.class_names) else f"C{i}"
            row_str = f"| **{class_name}** | " + " | ".join([f"{val:,}" for val in row]) + " |"
            lines.append(row_str)

        return lines

    def _generate_per_class_section(self, metrics: Dict) -> List[str]:
        """Generate per-class performance breakdown."""
        lines = [
            "## 📋 Per-Class Performance",
            ""
        ]

        per_class = metrics.get('per_class_metrics', {})

        if per_class:
            # Table header
            lines.extend([
                "| Class | Precision | Recall | F1-Score | Support |",
                "|-------|-----------|--------|----------|---------|"
            ])

            # Rows
            for class_name, class_metrics in per_class.items():
                precision = class_metrics.get('precision', 0)
                recall = class_metrics.get('recall', 0)
                f1 = class_metrics.get('f1-score', 0)
                support = class_metrics.get('support', 0)

                lines.append(
                    f"| **{class_name}** | {precision:.3f} | {recall:.3f} | {f1:.3f} | {support:,} |"
                )

            lines.append("")

            # Insights
            lines.extend(self._generate_per_class_insights(per_class))

        else:
            lines.append("*Per-class metrics not available*")
            lines.append("")

        lines.extend([
            "---",
            ""
        ])

        return lines

    def _generate_per_class_insights(self, per_class: Dict) -> List[str]:
        """Generate insights from per-class metrics."""
        lines = ["### Insights", ""]

        # Find best and worst classes by F1
        if per_class:
            sorted_by_f1 = sorted(
                per_class.items(),
                key=lambda x: x[1].get('f1-score', 0),
                reverse=True
            )

            best_class, best_metrics = sorted_by_f1[0]
            worst_class, worst_metrics = sorted_by_f1[-1]

            lines.extend([
                f"- **Best Performance:** {best_class} (F1={best_metrics['f1-score']:.3f})",
                f"- **Worst Performance:** {worst_class} (F1={worst_metrics['f1-score']:.3f})",
                ""
            ])

            # Check for imbalanced performance
            f1_scores = [m['f1-score'] for m in per_class.values()]
            f1_std = pd.Series(f1_scores).std()

            if f1_std > 0.2:
                lines.append(
                    f"⚠️  **Warning:** High variance in per-class F1 (std={f1_std:.3f}). "
                    f"Model performance is imbalanced across classes."
                )
                lines.append("")

        return lines

    def _generate_roc_pr_section(self, metrics: Dict, plots: Dict) -> List[str]:
        """Generate ROC/PR curves section."""
        lines = [
            "## 📈 ROC and Precision-Recall Analysis",
            ""
        ]

        # ROC plot
        if 'roc_curves' in plots:
            rel_path = plots['roc_curves'].name
            lines.append(f"![ROC Curves]({rel_path})")
            lines.append("")

        # ROC AUC table
        roc_auc = metrics.get('roc_auc_per_class', {})
        if roc_auc:
            lines.extend([
                "### ROC AUC Scores",
                "",
                "| Class | ROC AUC |",
                "|-------|---------|"
            ])

            for class_name, auc in roc_auc.items():
                auc_str = f"{auc:.3f}" if auc is not None else "N/A"
                lines.append(f"| **{class_name}** | {auc_str} |")

            lines.append("")

        # PR plot
        if 'pr_curves' in plots:
            rel_path = plots['pr_curves'].name
            lines.append(f"![Precision-Recall Curves]({rel_path})")
            lines.append("")

        # PR AUC table
        pr_auc = metrics.get('pr_auc_per_class', {})
        if pr_auc:
            lines.extend([
                "### Average Precision Scores",
                "",
                "| Class | PR AUC (AP) |",
                "|-------|-------------|"
            ])

            for class_name, ap in pr_auc.items():
                ap_str = f"{ap:.3f}" if ap is not None else "N/A"
                lines.append(f"| **{class_name}** | {ap_str} |")

            lines.append("")

        lines.extend([
            "---",
            ""
        ])

        return lines

    def _generate_calibration_section(self, metrics: Dict, plots: Dict) -> List[str]:
        """Generate calibration analysis section."""
        lines = [
            "## 🎯 Calibration Analysis",
            ""
        ]

        # Calibration plot
        if 'calibration_curves' in plots:
            rel_path = plots['calibration_curves'].name
            lines.append(f"![Calibration Curves]({rel_path})")
            lines.append("")

        # Brier score table
        brier = metrics.get('brier_score', {})
        if brier:
            lines.extend([
                "### Brier Score (Lower is Better)",
                "",
                "| Class | Brier Score |",
                "|-------|-------------|"
            ])

            for class_name, score in brier.items():
                if class_name != 'mean':
                    score_str = f"{score:.4f}" if score is not None else "N/A"
                    lines.append(f"| **{class_name}** | {score_str} |")

            # Add mean
            if 'mean' in brier and brier['mean'] is not None:
                lines.append(f"| **Mean** | **{brier['mean']:.4f}** |")

            lines.append("")

            # Interpretation
            mean_brier = brier.get('mean', 0)
            if mean_brier and mean_brier < 0.1:
                lines.append("✅ **Good calibration** - predicted probabilities are well-calibrated.")
            elif mean_brier and mean_brier < 0.2:
                lines.append("🟡 **Moderate calibration** - probabilities are somewhat reliable.")
            else:
                lines.append("⚠️  **Poor calibration** - probabilities may not reflect true likelihood.")

            lines.append("")

        lines.extend([
            "---",
            ""
        ])

        return lines

    def _generate_feature_importance_section(self, metrics: Dict, plots: Dict) -> List[str]:
        """Generate feature importance section."""
        lines = [
            "## 📊 Feature Importance",
            ""
        ]

        # Feature importance plot
        if 'feature_importance' in plots:
            rel_path = plots['feature_importance'].name
            lines.append(f"![Feature Importance]({rel_path})")
            lines.append("")

        # Feature importance table (top 20)
        feature_importance = metrics.get('feature_importance', [])
        if feature_importance:
            lines.extend([
                "### Top 20 Features (XGBoost Gain)",
                "",
                "| Rank | Feature | Gain |",
                "|------|---------|------|"
            ])

            for rank, feat in enumerate(feature_importance[:20], start=1):
                lines.append(f"| {rank} | {feat['feature']} | {feat['gain']:.4f} |")

            lines.append("")

        lines.extend([
            "---",
            ""
        ])

        return lines

    def _generate_shap_section(self, metrics: Dict) -> List[str]:
        """Generate SHAP insights section."""
        lines = [
            "## 🔍 SHAP Feature Impact Analysis",
            ""
        ]

        shap_summary = metrics.get('shap_summary', {})

        if 'mean_abs_shap_per_class' in shap_summary:
            for class_name, top_features in shap_summary['mean_abs_shap_per_class'].items():
                lines.append(f"### {class_name}")
                lines.append("")
                lines.extend([
                    "| Rank | Feature | Mean |SHAP| |",
                    "|------|---------|-------------|"
                ])

                for rank, feat in enumerate(top_features[:10], start=1):
                    lines.append(f"| {rank} | {feat['feature']} | {feat['mean_abs_shap']:.4f} |")

                lines.append("")

        lines.extend([
            "*Note: SHAP values indicate feature impact magnitude. For directionality, see SHAP beeswarm plots.*",
            "",
            "---",
            ""
        ])

        return lines

    def _generate_recommendations(self, metrics: Dict) -> List[str]:
        """Generate actionable recommendations."""
        lines = [
            "## 💡 Recommendations",
            ""
        ]

        accuracy = metrics.get('accuracy', 0)
        weighted_f1 = metrics.get('weighted_f1', 0)
        per_class = metrics.get('per_class_metrics', {})

        recommendations = []

        # Low accuracy
        if accuracy < 0.4:
            recommendations.append("🔴 **Critical:** Accuracy is very low. Consider feature engineering or collecting more data.")

        # Imbalanced class performance
        if per_class:
            f1_scores = [m['f1-score'] for m in per_class.values()]
            if pd.Series(f1_scores).std() > 0.2:
                recommendations.append("🟡 **Class Imbalance:** Performance varies significantly across classes. Consider class-specific feature engineering or oversampling.")

        # Low F1 on important classes
        if per_class and 'Home Run' in per_class:
            home_run_f1 = per_class['Home Run'].get('f1-score', 0)
            if home_run_f1 < 0.3:
                recommendations.append("⚠️  **Home Run Detection:** F1 score is low for the most valuable class. Focus on improving recall for home runs.")

        # Calibration issues
        brier = metrics.get('brier_score', {})
        if brier.get('mean', 0) > 0.2:
            recommendations.append("🎯 **Calibration:** Predicted probabilities are poorly calibrated. Consider Platt scaling or isotonic regression.")

        # General recommendations
        if weighted_f1 < 0.5:
            recommendations.append("📊 **Model Improvement:** Try hyperparameter tuning, ensemble methods, or alternative algorithms.")

        if not recommendations:
            recommendations.append("✅ **Model Performance:** Model shows acceptable performance. Monitor in production and iterate as needed.")

        for rec in recommendations:
            lines.append(f"- {rec}")

        lines.append("")
        lines.extend([
            "---",
            ""
        ])

        return lines

    def _generate_footer(self, plots: Dict) -> List[str]:
        """Generate report footer."""
        lines = [
            "## 📁 Artifacts",
            "",
            "### Generated Plots",
            ""
        ]

        for plot_name, plot_path in plots.items():
            lines.append(f"- `{plot_path.name}` - {plot_name.replace('_', ' ').title()}")

        lines.extend([
            "",
            "---",
            "",
            f"*Report generated by ClassificationEvaluator - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
        ])

        return lines
