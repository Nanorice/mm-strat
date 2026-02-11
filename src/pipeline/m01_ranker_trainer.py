"""
M01 Ranker Trainer - Learning-to-Rank for SEPA Candidates
==========================================================

Subclass of M01Trainer that uses XGBoost's pairwise ranking objective.

Key Differences from M01Trainer (Regressor):
- Uses XGBRanker with 'rank:pairwise' objective
- Groups samples by date for cross-sectional ranking
- Evaluates using NDCG instead of RMSE
- Optimizes for relative ordering, not absolute prediction

Usage:
    from src.pipeline import DataPipeline, M01RankerTrainer

    pipeline = DataPipeline()
    d2 = pipeline.features(pipeline.scan('2020-01-01', '2023-12-31'))

    trainer = M01RankerTrainer()
    model, metrics = trainer.train(d2)
    trainer.save(model, metrics)

When to use Ranker vs Regressor:
- Ranker: When you only care about relative ordering (top decile selection)
- Regressor: When you need calibrated return predictions
"""

import logging
import time
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .m01_trainer import M01Trainer

logger = logging.getLogger("M01RankerTrainer")


class M01RankerTrainer(M01Trainer):
    """
    M01 Ranker: Learning-to-Rank for SEPA candidates.

    Uses XGBoost's pairwise ranking to optimize for cross-sectional ordering.
    Samples are grouped by date - the model learns to rank candidates
    within each day, not across time.
    """

    def __init__(
        self,
        output_dir: str = 'models',
        feature_set: str = None,
        model_name: str = None
    ):
        super().__init__(output_dir, feature_set, model_name)
        self._is_ranker = True

    @property
    def model_type(self) -> str:
        return 'ranking'

    @property
    def model_name(self) -> str:
        if self._model_name:
            return self._model_name
        return 'M01_RANK'

    def get_model_params(self, tuned_params: Optional[Dict] = None) -> Dict:
        """Get XGBoost Ranker parameters."""
        default_params = {
            'objective': 'rank:pairwise',
            'n_estimators': 300,
            'learning_rate': 0.03,
            'max_depth': 4,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'reg_alpha': 5.0,
            'reg_lambda': 3.0,
            'random_state': 42,
            'n_jobs': -1,
            'enable_categorical': True
        }

        if tuned_params:
            default_params.update(tuned_params)

        return default_params

    def create_model(self, params: Dict):
        """Create XGBoost Ranker."""
        import xgboost as xgb

        if 'enable_categorical' not in params:
            params = {**params, 'enable_categorical': True}

        return xgb.XGBRanker(**params)

    def _compute_group_sizes(self, dates: pd.Series) -> np.ndarray:
        """
        Compute group sizes for ranking from date series.

        XGBRanker needs a 'group' array where each element is the count
        of samples in that query group. For cross-sectional ranking,
        each date is a query group.

        Args:
            dates: Series of dates (must be sorted)

        Returns:
            Array of group sizes
        """
        return dates.value_counts().sort_index().values

    def train(
        self,
        data: pd.DataFrame,
        tune: bool = False,
        tune_trials: int = 50,
        train_years: int = 3,
        test_years: int = 1,
        target: str = 'log_hybrid',
        survivor_model: bool = False,
        stop_multiplier: float = 2.0,
        min_group_size: int = 5
    ) -> Tuple:
        """
        Train ranker using walk-forward validation with date-based grouping.

        Args:
            data: D2 features DataFrame
            tune: Enable Optuna hyperparameter tuning
            tune_trials: Number of Optuna trials
            train_years: Training window size
            test_years: Test window size
            target: Target column for ranking relevance
            survivor_model: Enable survivor model filtering
            stop_multiplier: Structural stop multiplier
            min_group_size: Minimum samples per date to include

        Returns:
            Tuple of (trained_model, metrics_df)
        """
        from scipy.stats import spearmanr
        from src.evaluation import M01Evaluator

        logger.info(f"Training {self.model_name} (RANKER - pairwise)")
        logger.info(f"   Target for relevance: {target}")
        start_time = time.time()

        # Apply feature preprocessing
        from src.feature_preprocessor import FeaturePreprocessor
        preprocessor = FeaturePreprocessor()

        numeric_cols = data.select_dtypes(include=[np.number]).columns.tolist()
        exclude_cols = ['label', 'return_pct', 'days_held', 'year', 'trade_id']
        preprocess_cols = [c for c in numeric_cols if c not in exclude_cols]

        preprocessor.fit(data, preprocess_cols, target='return_pct')
        data = preprocessor.transform(data)

        log_count = sum(1 for f in preprocessor.config.get('features', {}).values()
                       if f.get('transform') == 'log')
        win_count = sum(1 for f in preprocessor.config.get('features', {}).values()
                       if f.get('transform') == 'winsorize')
        logger.info(f"   Preprocessor: {log_count} log-transformed, {win_count} winsorized")

        # Save preprocessing config
        model_dir = self.get_model_dir()
        preprocessor.save(model_dir / 'preprocessing_config.json')

        # Get features
        feature_cols = self.get_features()
        available_cols = [c for c in feature_cols if c in data.columns]
        missing_cols = [c for c in feature_cols if c not in data.columns]

        if missing_cols:
            logger.warning(f"   Missing {len(missing_cols)} features: {missing_cols[:5]}...")
        logger.info(f"   Using {len(available_cols)} features")

        # Convert categorical features
        from src.feature_config import CATEGORICAL_FEATURES
        cat_features = [f for f in CATEGORICAL_FEATURES if f in available_cols]
        if cat_features:
            for col in cat_features:
                data[col] = data[col].astype('category')
            logger.info(f"   Categorical features: {cat_features}")

        # Prepare data
        data = data.copy()

        if 'Date' in data.columns and 'date' not in data.columns:
            data = data.rename(columns={'Date': 'date'})

        data['date'] = pd.to_datetime(data['date'])
        data = data.sort_values('date')
        data['year'] = data['date'].dt.year

        # Compute target for ranking relevance
        if target == 'log_hybrid':
            if 'target' not in data.columns:
                logger.info("   Computing log_hybrid target...")
                data = self._compute_log_hybrid_target(data)
            target_col = 'target'
        elif target == 'log_space':
            if 'target' not in data.columns:
                data = self._compute_log_space_target(data)
            target_col = 'target'
        elif target == 'y_max':
            if 'y_max' not in data.columns:
                data = self.calculate_y_max(data)
            target_col = 'y_max'
        elif target in data.columns:
            target_col = target
        else:
            target_col = 'return_pct'

        logger.info(f"   Using target: {target_col}")

        # Filter dates with minimum group size
        date_counts = data['date'].value_counts()
        valid_dates = date_counts[date_counts >= min_group_size].index
        n_filtered = len(date_counts) - len(valid_dates)
        if n_filtered > 0:
            logger.info(f"   Filtered {n_filtered} dates with < {min_group_size} samples")
        data = data[data['date'].isin(valid_dates)].copy()

        # Clean data
        data = self.clean_data(data, available_cols)
        years = sorted(data['year'].unique())

        # Walk-forward validation
        all_metrics = []
        all_predictions = []
        final_model = None

        self._evaluator = M01Evaluator(
            target_type=target_col,
            output_dir=self.output_dir
        )

        for i, test_year in enumerate(years[train_years:]):
            train_years_range = years[i:i+train_years]

            train_data = data[data['year'].isin(train_years_range)].copy()
            test_data = data[data['year'] == test_year].copy()

            if len(train_data) < 50 or len(test_data) < 10:
                logger.warning(f"   Skipping {test_year} (insufficient data)")
                continue

            # Sort by date for proper grouping
            train_data = train_data.sort_values('date')
            test_data = test_data.sort_values('date')

            X_train = train_data[available_cols]
            y_train = train_data[target_col]
            X_test = test_data[available_cols]
            y_test = test_data[target_col]

            # Compute group sizes
            train_groups = self._compute_group_sizes(train_data['date'])
            test_groups = self._compute_group_sizes(test_data['date'])

            logger.info(f"   Fold {i+1}: Train groups={len(train_groups)}, Test groups={len(test_groups)}")

            # Create and train ranker
            params = self.get_model_params()
            model = self.create_model(params)

            model.fit(
                X_train, y_train,
                group=train_groups,
                verbose=False
            )

            # Predict (scores for ranking, not calibrated returns)
            preds = model.predict(X_test)

            # Evaluate using ranking metrics
            fold_metrics = self._evaluate_ranker_fold(
                y_test, preds, test_data, test_year,
                len(train_data), len(test_data)
            )
            all_metrics.append(fold_metrics)

            # Store predictions
            test_data_copy = test_data.copy()
            test_data_copy['y_pred'] = preds
            test_data_copy['y_true'] = y_test.values
            test_data_copy['test_year'] = test_year
            test_data_copy['fold'] = i + 1
            all_predictions.append(test_data_copy)

            ic_str = f"IC={fold_metrics.get('ic', 0):.3f}"
            ndcg_str = f"NDCG@10={fold_metrics.get('ndcg_10', 0):.3f}"
            edge_str = f"Edge={fold_metrics['selection_edge']:+.2f}%"
            logger.info(f"   Fold {i+1} (Test {test_year}): {ic_str} {ndcg_str} {edge_str}")

            final_model = model

        # Summary
        metrics_df = pd.DataFrame(all_metrics)
        self._print_ranker_summary(metrics_df)

        elapsed = time.time() - start_time
        logger.info(f"   Training complete in {elapsed:.1f}s")

        # Store for saving
        self._feature_cols = available_cols
        self._target_col = target_col
        self._all_predictions = pd.concat(all_predictions, ignore_index=True) if all_predictions else pd.DataFrame()

        return final_model, metrics_df

    def _evaluate_ranker_fold(
        self,
        y_test: pd.Series,
        preds: np.ndarray,
        test_data: pd.DataFrame,
        test_year: int,
        n_train: int,
        n_test: int
    ) -> Dict:
        """Evaluate ranking fold with NDCG and IC metrics."""
        from scipy.stats import spearmanr

        # Information Coefficient (Spearman)
        ic, ic_pval = spearmanr(preds, y_test)

        # Decile analysis
        decile = self.analyze_deciles(y_test, preds)

        # NDCG@k (per-date, then averaged)
        ndcg_scores = []
        test_data = test_data.copy()
        test_data['y_pred'] = preds
        test_data['y_true'] = y_test.values

        for date, group in test_data.groupby('date'):
            if len(group) < 2:
                continue
            ndcg = self._compute_ndcg(group['y_true'].values, group['y_pred'].values, k=10)
            ndcg_scores.append(ndcg)

        avg_ndcg = np.mean(ndcg_scores) if ndcg_scores else 0

        return {
            'test_year': test_year,
            'train_samples': n_train,
            'test_samples': n_test,
            'ic': ic,
            'ic_pval': ic_pval,
            'ndcg_10': avg_ndcg,
            'selection_edge': decile['selection_edge'],
            'top_decile_mean': decile['top_decile_mean'],
            'top2_edge': decile['top2_edge']
        }

    def _compute_ndcg(self, y_true: np.ndarray, y_pred: np.ndarray, k: int = 10) -> float:
        """
        Compute Normalized Discounted Cumulative Gain at k.

        NDCG measures ranking quality:
        - 1.0 = perfect ranking
        - 0.0 = worst ranking
        """
        # Sort by predicted scores (descending)
        order = np.argsort(y_pred)[::-1]
        y_true_sorted = y_true[order]

        # DCG@k
        k = min(k, len(y_true))
        gains = y_true_sorted[:k]
        discounts = np.log2(np.arange(2, k + 2))
        dcg = np.sum(gains / discounts)

        # Ideal DCG (sort by true values)
        ideal_order = np.argsort(y_true)[::-1]
        ideal_gains = y_true[ideal_order][:k]
        idcg = np.sum(ideal_gains / discounts)

        if idcg == 0:
            return 0.0

        return dcg / idcg

    def _print_ranker_summary(self, metrics_df: pd.DataFrame):
        """Print ranking validation summary."""
        if len(metrics_df) == 0:
            logger.warning("No validation folds completed")
            return

        avg_ic = metrics_df['ic'].mean()
        avg_ndcg = metrics_df['ndcg_10'].mean()
        avg_edge = metrics_df['selection_edge'].mean()
        avg_top_decile = metrics_df['top_decile_mean'].mean()

        ic_std = metrics_df['ic'].std()
        ic_sharpe = avg_ic / ic_std if ic_std > 0 else 0
        ic_positive = (metrics_df['ic'] > 0).sum()

        edge_positive = (metrics_df['selection_edge'] > 0).sum()

        print("\n" + "=" * 70)
        print("M01 RANKER WALK-FORWARD VALIDATION RESULTS")
        print("=" * 70)
        print(f"   Objective:             rank:pairwise")
        print(f"   Folds Completed:       {len(metrics_df)}")
        print(f"   Total Test Samples:    {metrics_df['test_samples'].sum():,}")

        print(f"\nRANKING QUALITY")
        print(f"   Average NDCG@10:       {avg_ndcg:>6.3f}")
        print(f"   Average IC:            {avg_ic:>+6.3f}")
        print(f"   IC Sharpe:             {ic_sharpe:>6.2f}")
        print(f"   IC Positive Folds:     {ic_positive} / {len(metrics_df)} ({ic_positive/len(metrics_df)*100:.0f}%)")

        print(f"\nSELECTION EDGE")
        print(f"   Average Edge:          {avg_edge:>+6.2f}%")
        print(f"   Positive Edge Folds:   {edge_positive} / {len(metrics_df)} ({edge_positive/len(metrics_df)*100:.0f}%)")
        print(f"   Top Decile Avg Return: {avg_top_decile:>7.2f}%")
        print("=" * 70 + "\n")

    def _evaluate_fold(self, y_test, preds, model, test_year, n_train, n_test) -> Dict:
        """Override base class method - delegates to ranker evaluation."""
        # This is called by base class, but we override train() so this shouldn't be reached
        raise NotImplementedError("Use _evaluate_ranker_fold for ranking")

    def _format_fold_result(self, metrics: Dict) -> str:
        """Format ranking fold result."""
        return f"NDCG@10={metrics.get('ndcg_10', 0):.3f} IC={metrics.get('ic', 0):.3f}"

    def _print_summary(self, metrics_df: pd.DataFrame):
        """Delegate to ranker summary."""
        self._print_ranker_summary(metrics_df)

    def generate_report(
        self,
        model,
        metrics_df: pd.DataFrame,
        start_date: str = None,
        end_date: str = None
    ) -> str:
        """Generate ranking-specific report."""
        model_dir = self.get_model_dir()
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = model_dir / f"model_report_{self.model_name}_{date_str}.md"

        # Feature importance
        feature_cols = self._feature_cols if hasattr(self, '_feature_cols') else []
        importance_df = self.save_feature_importance(model, feature_cols) if feature_cols else None

        # Metrics
        avg_ic = metrics_df['ic'].mean()
        avg_ndcg = metrics_df['ndcg_10'].mean()
        avg_edge = metrics_df['selection_edge'].mean()
        ic_std = metrics_df['ic'].std()
        ic_sharpe = avg_ic / ic_std if ic_std > 0 else 0

        lines = []
        lines.append(f"# Model Training Report - {self.model_name} (Pairwise Ranker)")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if start_date and end_date:
            lines.append(f"**Training Period:** {start_date} to {end_date}")
        lines.append(f"**Model Type:** RANKING (rank:pairwise)")
        lines.append(f"**Objective:** Cross-sectional ranking by date")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Summary
        lines.append("## Executive Summary")
        lines.append("")
        lines.append("### Key Metrics")
        lines.append("")
        lines.append(f"- **Average NDCG@10:** {avg_ndcg:.3f}")
        lines.append(f"- **Average IC:** {avg_ic:+.3f}")
        lines.append(f"- **IC Sharpe:** {ic_sharpe:.2f}")
        lines.append(f"- **Selection Edge:** {avg_edge:+.2f}%")
        lines.append(f"- **Walk-Forward Folds:** {len(metrics_df)}")
        lines.append("")

        # Comparison note
        lines.append("### Ranker vs Regressor")
        lines.append("")
        lines.append("| Aspect | Ranker (This) | Regressor (M01) |")
        lines.append("|--------|---------------|-----------------|")
        lines.append("| Objective | Relative ordering | Absolute prediction |")
        lines.append("| Metric | NDCG, IC | RMSE, IC |")
        lines.append("| Calibration | Not meaningful | Isotonic regression |")
        lines.append("| Use case | Top-K selection | Return estimation |")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Walk-forward results
        lines.append("## Walk-Forward Validation Results")
        lines.append("")
        lines.append("| Fold | Test Year | Samples | NDCG@10 | IC | Selection Edge |")
        lines.append("|------|-----------|---------|---------|-------|----------------|")

        for i, row in metrics_df.iterrows():
            lines.append(
                f"| {i+1} | {row.get('test_year', 'N/A')} | {row['test_samples']:,} | "
                f"{row['ndcg_10']:.3f} | {row['ic']:+.3f} | {row['selection_edge']:+.2f}% |"
            )

        lines.append("")

        # Feature importance
        if importance_df is not None and len(importance_df) > 0:
            lines.append("---")
            lines.append("")
            lines.append("## Feature Importance (Top 20)")
            lines.append("")
            lines.append("| Rank | Feature | Gain % |")
            lines.append("|------|---------|--------|")

            for _, row in importance_df.head(20).iterrows():
                lines.append(f"| {int(row['rank'])} | {row['feature']} | {row['gain_pct']:.1f}% |")

        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("*Report generated by M01RankerTrainer*")

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"Saved ranker report to {report_path}")
        return str(report_path)
