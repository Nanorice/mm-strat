"""
Model Evaluation Module - Comprehensive Performance Assessment

This module handles:
1. Precision@k metrics (Top 10, Top 20, etc.)
2. ROC-AUC and classification metrics
3. Feature importance analysis (SHAP)
4. Baseline comparison (unfiltered SEPA vs ML-filtered)
5. Temporal stability assessment across folds
6. Visualization and reporting

Key Metrics:
- Precision@Top-k: Precision on top-k% of predictions (primary metric)
- Simulated Returns: What would returns be if we bought top-k?
- ROC-AUC: Overall discrimination ability
- Feature Importance: SHAP values for interpretability
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Dict, List, Tuple, Optional
from pathlib import Path
import logging
import json
from sklearn.metrics import (
    roc_auc_score, roc_curve, precision_recall_curve,
    confusion_matrix, classification_report, average_precision_score
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set plot style
sns.set_style('whitegrid')
plt.rcParams['figure.figsize'] = (12, 6)


class ModelEvaluator:
    """
    Comprehensive model evaluation for SEPA ranking system.
    """

    def __init__(self, output_dir: str = 'evaluation'):
        """
        Initialize evaluator.

        Args:
            output_dir: Directory for saving plots and reports
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results = {}

    def calculate_precision_at_k(
        self,
        y_true: np.ndarray,
        y_pred_proba: np.ndarray,
        k_values: List[float] = [0.1, 0.2, 0.3]
    ) -> Dict[str, float]:
        """
        Calculate Precision@k for multiple k values.

        Args:
            y_true: True labels
            y_pred_proba: Predicted probabilities
            k_values: List of k percentages (e.g., [0.1, 0.2] for top 10%, 20%)

        Returns:
            Dictionary with precision scores
        """
        precision_scores = {}

        for k_pct in k_values:
            # Number of top predictions
            n_samples = len(y_true)
            k = max(1, int(n_samples * k_pct))

            # Get top-k indices
            top_k_indices = np.argsort(y_pred_proba)[-k:]

            # Calculate precision
            precision = y_true[top_k_indices].mean()

            metric_name = f'precision@top{int(k_pct*100)}%'
            precision_scores[metric_name] = precision

            logger.info(f"{metric_name}: {precision:.4f} (n={k})")

        return precision_scores

    def calculate_classification_metrics(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        y_pred_proba: np.ndarray
    ) -> Dict:
        """
        Calculate standard classification metrics.

        Args:
            y_true: True labels
            y_pred: Predicted labels (binary)
            y_pred_proba: Predicted probabilities

        Returns:
            Dictionary with metrics
        """
        metrics = {}

        # ROC-AUC
        if len(np.unique(y_true)) > 1:  # Need both classes
            metrics['roc_auc'] = roc_auc_score(y_true, y_pred_proba)
            metrics['pr_auc'] = average_precision_score(y_true, y_pred_proba)
        else:
            metrics['roc_auc'] = np.nan
            metrics['pr_auc'] = np.nan

        # Confusion matrix
        cm = confusion_matrix(y_true, y_pred)
        if cm.shape == (2, 2):
            tn, fp, fn, tp = cm.ravel()
            metrics['true_positive'] = int(tp)
            metrics['false_positive'] = int(fp)
            metrics['true_negative'] = int(tn)
            metrics['false_negative'] = int(fn)

            # Derived metrics
            metrics['precision'] = tp / (tp + fp) if (tp + fp) > 0 else 0
            metrics['recall'] = tp / (tp + fn) if (tp + fn) > 0 else 0
            metrics['specificity'] = tn / (tn + fp) if (tn + fp) > 0 else 0
            metrics['f1_score'] = (2 * metrics['precision'] * metrics['recall'] /
                                  (metrics['precision'] + metrics['recall'])
                                  if (metrics['precision'] + metrics['recall']) > 0 else 0)

        return metrics

    def simulate_trading_returns(
        self,
        df: pd.DataFrame,
        y_pred_proba: np.ndarray,
        k_pct: float = 0.2,
        return_col: str = 'return_pct'
    ) -> Dict:
        """
        Simulate what returns would be if we bought top-k% predictions.

        Args:
            df: DataFrame with test data (must have return_pct column)
            y_pred_proba: Predicted probabilities
            k_pct: Top-k percentage to simulate (default: 0.2)
            return_col: Column name for returns (default: 'return_pct')

        Returns:
            Dictionary with simulated trading statistics
        """
        # Get top-k indices
        k = max(1, int(len(y_pred_proba) * k_pct))
        top_k_indices = np.argsort(y_pred_proba)[-k:]

        # Get returns for top-k
        top_k_returns = df.iloc[top_k_indices][return_col].values

        # Calculate statistics
        stats = {
            'n_trades': k,
            'avg_return': top_k_returns.mean(),
            'median_return': np.median(top_k_returns),
            'total_return': top_k_returns.sum(),
            'win_rate': (top_k_returns > 0).mean(),
            'avg_winner': top_k_returns[top_k_returns > 0].mean() if (top_k_returns > 0).any() else 0,
            'avg_loser': top_k_returns[top_k_returns < 0].mean() if (top_k_returns < 0).any() else 0,
            'best_trade': top_k_returns.max(),
            'worst_trade': top_k_returns.min(),
            'sharpe_ratio': top_k_returns.mean() / top_k_returns.std() if top_k_returns.std() > 0 else 0
        }

        logger.info(f"\nSimulated Trading (Top {int(k_pct*100)}%):")
        logger.info(f"  Trades: {stats['n_trades']}")
        logger.info(f"  Avg Return: {stats['avg_return']:.2f}%")
        logger.info(f"  Win Rate: {stats['win_rate']*100:.1f}%")
        logger.info(f"  Sharpe: {stats['sharpe_ratio']:.2f}")

        return stats

    def compare_to_baseline(
        self,
        y_true: np.ndarray,
        df: pd.DataFrame,
        y_pred_proba: np.ndarray,
        k_pct: float = 0.2,
        return_col: str = 'return_pct'
    ) -> Dict:
        """
        Compare ML model to unfiltered SEPA baseline.

        Baseline: All trades that passed SEPA criteria
        Model: Top-k% by ML probability score

        Args:
            y_true: True labels
            df: DataFrame with test data
            y_pred_proba: Model probabilities
            k_pct: Top-k percentage
            return_col: Return column name

        Returns:
            Dictionary with comparison statistics
        """
        # Baseline (all SEPA signals)
        baseline_win_rate = y_true.mean()
        baseline_avg_return = df[return_col].mean()

        # Model (top-k)
        k = max(1, int(len(y_pred_proba) * k_pct))
        top_k_indices = np.argsort(y_pred_proba)[-k:]

        model_win_rate = y_true[top_k_indices].mean()
        model_avg_return = df.iloc[top_k_indices][return_col].mean()

        # Improvement
        comparison = {
            'baseline_win_rate': baseline_win_rate,
            'baseline_avg_return': baseline_avg_return,
            'model_win_rate': model_win_rate,
            'model_avg_return': model_avg_return,
            'win_rate_improvement': model_win_rate - baseline_win_rate,
            'return_improvement': model_avg_return - baseline_avg_return,
            'win_rate_lift': (model_win_rate / baseline_win_rate - 1) if baseline_win_rate > 0 else 0,
            'return_lift': (model_avg_return / baseline_avg_return - 1) if baseline_avg_return != 0 else 0
        }

        logger.info(f"\nBaseline vs Model (Top {int(k_pct*100)}%):")
        logger.info(f"  Win Rate: {baseline_win_rate*100:.1f}% → {model_win_rate*100:.1f}% "
                   f"({comparison['win_rate_lift']*100:+.1f}%)")
        logger.info(f"  Avg Return: {baseline_avg_return:.2f}% → {model_avg_return:.2f}% "
                   f"({comparison['return_lift']*100:+.1f}%)")

        return comparison

    def calculate_feature_importance_shap(
        self,
        model: object,
        X: pd.DataFrame,
        top_n: int = 20,
        sample_size: int = 500
    ) -> pd.DataFrame:
        """
        Calculate SHAP feature importance.

        Args:
            model: Trained XGBoost model
            X: Features
            top_n: Number of top features to show (default: 20)
            sample_size: Sample size for SHAP (default: 500)

        Returns:
            DataFrame with feature importance
        """
        try:
            import shap

            logger.info("Calculating SHAP feature importance...")

            # Sample for speed
            if len(X) > sample_size:
                X_sample = X.sample(n=sample_size, random_state=42)
            else:
                X_sample = X

            # Fill missing values
            X_sample_filled = X_sample.fillna(X.median())

            # Calculate SHAP values
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_sample_filled)

            # Mean absolute SHAP value per feature
            importance_df = pd.DataFrame({
                'feature': X.columns,
                'importance': np.abs(shap_values).mean(axis=0)
            }).sort_values('importance', ascending=False)

            logger.info(f"\nTop {top_n} Features by SHAP Importance:")
            for idx, row in importance_df.head(top_n).iterrows():
                logger.info(f"  {row['feature']}: {row['importance']:.4f}")

            return importance_df

        except ImportError:
            logger.warning("SHAP not installed. Using XGBoost gain importance instead.")
            return self._get_gain_importance(model, X.columns, top_n)

    def _get_gain_importance(
        self,
        model: object,
        feature_names: List[str],
        top_n: int = 20
    ) -> pd.DataFrame:
        """
        Get feature importance from XGBoost gain (fallback).

        Args:
            model: XGBoost model
            feature_names: List of feature names
            top_n: Number of top features

        Returns:
            DataFrame with importance
        """
        importance_dict = model.get_score(importance_type='gain')

        importance_df = pd.DataFrame({
            'feature': list(importance_dict.keys()),
            'importance': list(importance_dict.values())
        }).sort_values('importance', ascending=False)

        logger.info(f"\nTop {top_n} Features by Gain:")
        for idx, row in importance_df.head(top_n).iterrows():
            logger.info(f"  {row['feature']}: {row['importance']:.2f}")

        return importance_df

    def plot_roc_curve(
        self,
        y_true: np.ndarray,
        y_pred_proba: np.ndarray,
        fold_id: Optional[int] = None,
        save: bool = True
    ):
        """
        Plot ROC curve.

        Args:
            y_true: True labels
            y_pred_proba: Predicted probabilities
            fold_id: Fold identifier (for filename)
            save: Whether to save plot
        """
        if len(np.unique(y_true)) < 2:
            logger.warning("Cannot plot ROC curve: only one class in y_true")
            return

        fpr, tpr, thresholds = roc_curve(y_true, y_pred_proba)
        auc_score = roc_auc_score(y_true, y_pred_proba)

        plt.figure(figsize=(8, 6))
        plt.plot(fpr, tpr, label=f'ROC Curve (AUC = {auc_score:.3f})', linewidth=2)
        plt.plot([0, 1], [0, 1], 'k--', label='Random Baseline', linewidth=1)
        plt.xlabel('False Positive Rate', fontsize=12)
        plt.ylabel('True Positive Rate', fontsize=12)
        plt.title(f'ROC Curve - Fold {fold_id}' if fold_id else 'ROC Curve', fontsize=14)
        plt.legend(loc='lower right', fontsize=11)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()

        if save:
            filename = f'roc_curve_fold_{fold_id}.png' if fold_id else 'roc_curve.png'
            plt.savefig(self.output_dir / filename, dpi=300, bbox_inches='tight')
            logger.info(f"ROC curve saved: {self.output_dir / filename}")

        plt.close()

    def plot_precision_recall_curve(
        self,
        y_true: np.ndarray,
        y_pred_proba: np.ndarray,
        fold_id: Optional[int] = None,
        save: bool = True
    ):
        """
        Plot Precision-Recall curve.

        Args:
            y_true, y_pred_proba: Labels and probabilities
            fold_id: Fold identifier
            save: Whether to save
        """
        if len(np.unique(y_true)) < 2:
            logger.warning("Cannot plot PR curve: only one class in y_true")
            return

        precision, recall, thresholds = precision_recall_curve(y_true, y_pred_proba)
        pr_auc = average_precision_score(y_true, y_pred_proba)

        plt.figure(figsize=(8, 6))
        plt.plot(recall, precision, label=f'PR Curve (AUC = {pr_auc:.3f})', linewidth=2)
        plt.xlabel('Recall', fontsize=12)
        plt.ylabel('Precision', fontsize=12)
        plt.title(f'Precision-Recall Curve - Fold {fold_id}' if fold_id else 'Precision-Recall Curve',
                 fontsize=14)
        plt.legend(loc='upper right', fontsize=11)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()

        if save:
            filename = f'pr_curve_fold_{fold_id}.png' if fold_id else 'pr_curve.png'
            plt.savefig(self.output_dir / filename, dpi=300, bbox_inches='tight')
            logger.info(f"PR curve saved: {self.output_dir / filename}")

        plt.close()

    def plot_feature_importance(
        self,
        importance_df: pd.DataFrame,
        top_n: int = 20,
        fold_id: Optional[int] = None,
        save: bool = True
    ):
        """
        Plot feature importance bar chart.

        Args:
            importance_df: DataFrame with 'feature' and 'importance' columns
            top_n: Number of top features to show
            fold_id: Fold identifier
            save: Whether to save
        """
        top_features = importance_df.head(top_n)

        plt.figure(figsize=(10, 8))
        plt.barh(range(len(top_features)), top_features['importance'].values, color='steelblue')
        plt.yticks(range(len(top_features)), top_features['feature'].values)
        plt.xlabel('Importance (Mean |SHAP|)', fontsize=12)
        plt.ylabel('Feature', fontsize=12)
        plt.title(f'Top {top_n} Features by SHAP Importance' +
                 (f' - Fold {fold_id}' if fold_id else ''), fontsize=14)
        plt.gca().invert_yaxis()
        plt.grid(axis='x', alpha=0.3)
        plt.tight_layout()

        if save:
            filename = f'feature_importance_fold_{fold_id}.png' if fold_id else 'feature_importance.png'
            plt.savefig(self.output_dir / filename, dpi=300, bbox_inches='tight')
            logger.info(f"Feature importance plot saved: {self.output_dir / filename}")

        plt.close()

    def evaluate_fold(
        self,
        model: object,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        df_test: pd.DataFrame,
        fold_id: int,
        k_values: List[float] = [0.1, 0.2, 0.3]
    ) -> Dict:
        """
        Comprehensive evaluation for a single fold.

        Args:
            model: Trained model
            X_test: Test features
            y_test: Test labels
            df_test: Test DataFrame (with returns)
            fold_id: Fold identifier
            k_values: List of k percentages for Precision@k

        Returns:
            Dictionary with all evaluation metrics
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"EVALUATING FOLD {fold_id}")
        logger.info(f"{'='*80}")

        # Predictions
        import xgboost as xgb
        dtest = xgb.DMatrix(X_test)
        y_pred_proba = model.predict(dtest)
        y_pred = (y_pred_proba >= 0.5).astype(int)

        # 1. Precision@k
        precision_at_k = self.calculate_precision_at_k(y_test.values, y_pred_proba, k_values)

        # 2. Classification metrics
        classification_metrics = self.calculate_classification_metrics(
            y_test.values, y_pred, y_pred_proba
        )

        # 3. Trading simulation
        trading_sim = self.simulate_trading_returns(df_test, y_pred_proba, k_pct=0.2)

        # 4. Baseline comparison
        baseline_comp = self.compare_to_baseline(y_test.values, df_test, y_pred_proba, k_pct=0.2)

        # 5. Feature importance
        importance_df = self.calculate_feature_importance_shap(model, X_test, top_n=20)

        # 6. Plots
        self.plot_roc_curve(y_test.values, y_pred_proba, fold_id)
        self.plot_precision_recall_curve(y_test.values, y_pred_proba, fold_id)
        self.plot_feature_importance(importance_df, top_n=20, fold_id=fold_id)

        # Compile results
        fold_results = {
            'fold_id': fold_id,
            'test_size': len(y_test),
            'precision_at_k': precision_at_k,
            'classification_metrics': classification_metrics,
            'trading_simulation': trading_sim,
            'baseline_comparison': baseline_comp,
            'top_features': importance_df.head(20).to_dict('records')
        }

        return fold_results

    def generate_report(
        self,
        all_fold_results: List[Dict],
        output_path: str = 'evaluation_report.json'
    ):
        """
        Generate comprehensive evaluation report.

        Args:
            all_fold_results: List of fold evaluation results
            output_path: Path to save report
        """
        report = {
            'timestamp': pd.Timestamp.now().isoformat(),
            'n_folds': len(all_fold_results),
            'fold_results': all_fold_results,
            'summary': self._summarize_folds(all_fold_results)
        }

        # Save JSON
        output_file = self.output_dir / output_path
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        logger.info(f"\nEvaluation report saved: {output_file}")

        # Print summary
        self._print_summary(report['summary'])

    def _summarize_folds(self, fold_results: List[Dict]) -> Dict:
        """
        Summarize metrics across all folds.

        Args:
            fold_results: List of fold results

        Returns:
            Summary statistics
        """
        summary = {}

        # Average Precision@k across folds
        precision_keys = fold_results[0]['precision_at_k'].keys()
        for key in precision_keys:
            values = [fr['precision_at_k'][key] for fr in fold_results]
            summary[f'avg_{key}'] = np.mean(values)
            summary[f'std_{key}'] = np.std(values)

        # Average ROC-AUC
        roc_aucs = [fr['classification_metrics']['roc_auc'] for fr in fold_results]
        summary['avg_roc_auc'] = np.mean(roc_aucs)
        summary['std_roc_auc'] = np.std(roc_aucs)

        # Average trading simulation results
        avg_return = np.mean([fr['trading_simulation']['avg_return'] for fr in fold_results])
        avg_win_rate = np.mean([fr['trading_simulation']['win_rate'] for fr in fold_results])
        summary['avg_trading_return'] = avg_return
        summary['avg_trading_win_rate'] = avg_win_rate

        # Average baseline comparison
        avg_lift = np.mean([fr['baseline_comparison']['win_rate_lift'] for fr in fold_results])
        summary['avg_win_rate_lift'] = avg_lift

        return summary

    def _print_summary(self, summary: Dict):
        """Print formatted summary."""
        logger.info("\n" + "=" * 80)
        logger.info("EVALUATION SUMMARY (All Folds)")
        logger.info("=" * 80)

        logger.info(f"\nPrecision@k:")
        for key, value in summary.items():
            if 'precision@top' in key and 'avg_' in key:
                metric_name = key.replace('avg_', '')
                std_key = key.replace('avg_', 'std_')
                logger.info(f"  {metric_name}: {value:.4f} ± {summary[std_key]:.4f}")

        logger.info(f"\nROC-AUC: {summary['avg_roc_auc']:.4f} ± {summary['std_roc_auc']:.4f}")

        logger.info(f"\nTrading Simulation:")
        logger.info(f"  Avg Return: {summary['avg_trading_return']:.2f}%")
        logger.info(f"  Avg Win Rate: {summary['avg_trading_win_rate']*100:.1f}%")

        logger.info(f"\nModel Improvement:")
        logger.info(f"  Win Rate Lift: {summary['avg_win_rate_lift']*100:+.1f}%")

        logger.info("\n" + "=" * 80)


if __name__ == "__main__":
    # Example usage
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate trained SEPA models")
    parser.add_argument('--dataset', type=str, required=True, help='Path to test dataset')
    parser.add_argument('--model-dir', type=str, default='models', help='Model directory')
    parser.add_argument('--output-dir', type=str, default='evaluation', help='Output directory')

    args = parser.parse_args()

    evaluator = ModelEvaluator(output_dir=args.output_dir)

    print(f"Evaluation tools ready. Output directory: {args.output_dir}")
