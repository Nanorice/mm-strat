"""
M01 Trainer - SEPA Return Regressor
===================================

M01 predicts expected return % for SEPA trade candidates.

Features: Uses M01_FEATURES from feature_config.py
Target: return_pct (default) or y_max (Maximum Favorable Excursion)
Model: XGBoost Regressor

Usage:
    from src.pipeline import DataPipeline, M01Trainer
    
    pipeline = DataPipeline()
    d1 = pipeline.scan('2020-01-01', '2023-12-31')
    d2 = pipeline.features(d1)
    
    trainer = M01Trainer()
    model, metrics = trainer.train(d2)
    trainer.save(model, metrics)
    
    # With survivor model
    model, metrics = trainer.train(d2, survivor_model=True)
    
    # With y_max target (requires D2R)
    model, metrics = trainer.train(d2, target='y_max')
"""

import logging
import time
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .base_trainer import BaseTrainer

logger = logging.getLogger("M01Trainer")


class M01Trainer(BaseTrainer):
    """
    M01: SEPA Return Regressor.
    
    Predicts expected return % for SEPA trade candidates.
    Higher scores = higher expected returns.
    
    Supports:
        - Survivor model (--survivor): Filter crashed trades, train on y_max
        - Dual-target (--target): Train on return_pct or y_max
        - Report generation (--report): Generate markdown training report
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
    
    # =========================================================================
    # SURVIVOR MODEL: MAE/MFE Analysis
    # =========================================================================
    def enrich_with_survivor_labels(
        self,
        data: pd.DataFrame,
        d2r_path: str = 'data/ml/d2r_sepa.parquet',
        stop_multiplier: float = 2.0
    ) -> pd.DataFrame:
        """
        Enrich data with survivor model labels (y_max, MAE, MFE, is_survivor).
        
        Survivor Model Concept:
        - structural_stop = -K × nATR (where K = stop_multiplier)
        - Survivor: MAE > structural_stop (didn't hit stop)
        - Crashed: MAE <= structural_stop (hit stop)
        - y_max = MFE (for survivors), MAE (for crashed)
        
        Args:
            data: D2 features DataFrame
            d2r_path: Path to D2 rehydrated parquet file
            stop_multiplier: Multiplier for structural stop (default: 2.0)
            
        Returns:
            DataFrame with added columns: y_max, MAE, MFE, is_survivor
        """
        d2r_file = Path(d2r_path)
        if not d2r_file.exists():
            # Try alternative path
            alt_path = Path('data/ml/d2_rehydrated.parquet')
            if alt_path.exists():
                d2r_file = alt_path
            else:
                logger.warning(f"D2R not found: {d2r_path}")
                logger.warning("Cannot calculate survivor labels. Run hydrate() first.")
                return data
        
        logger.info(f"Calculating survivor labels from {d2r_file}...")
        logger.info(f"   Structural stop: -{stop_multiplier}×nATR")
        
        d2r = pd.read_parquet(d2r_file)
        
        # Add day_in_trade if missing
        if 'day_in_trade' not in d2r.columns:
            logger.info("   Adding day_in_trade to rehydrated data...")
            d2r = d2r.sort_values(['trade_id', 'Date'])
            d2r['day_in_trade'] = d2r.groupby('trade_id').cumcount()
        
        # Calculate MAE, MFE, and nATR for each trade
        results = []
        
        for trade_id, group in d2r.groupby('trade_id'):
            entry_rows = group[group['day_in_trade'] == 0]
            if len(entry_rows) == 0:
                continue
            
            entry_price = entry_rows['Close'].iloc[0]
            if entry_price <= 0:
                continue
            
            # Get nATR from entry day
            natr = entry_rows['nATR'].iloc[0] if 'nATR' in entry_rows.columns else 5.0
            
            # MFE (Max Favorable Excursion)
            highest = group['High'].max()
            mfe = ((highest - entry_price) / entry_price) * 100
            
            # MAE (Max Adverse Excursion)
            lowest = group['Low'].min()
            mae = ((lowest - entry_price) / entry_price) * 100
            
            # Structural stop threshold
            structural_stop = -stop_multiplier * natr
            
            # Survivor status
            is_survivor = mae > structural_stop
            
            # y_max for training
            y_max = mfe if is_survivor else mae
            
            ticker = group['ticker'].iloc[0] if 'ticker' in group.columns else None
            date = entry_rows['Date'].iloc[0] if 'Date' in entry_rows.columns else None
            
            results.append({
                'ticker': ticker,
                'date': pd.to_datetime(date).normalize() if date else None,
                'MFE': mfe,
                'MAE': mae,
                'structural_stop': structural_stop,
                'is_survivor': is_survivor,
                'y_max': y_max
            })
        
        results_df = pd.DataFrame(results)
        
        # Calculate statistics
        n_total = len(results_df)
        n_crashed = (~results_df['is_survivor']).sum()
        n_survived = results_df['is_survivor'].sum()
        crash_rate = n_crashed / n_total if n_total > 0 else 0
        
        logger.info(f"   Total trades: {n_total}")
        logger.info(f"   [X] Crashed: {n_crashed} ({crash_rate:.1%})")
        logger.info(f"   [O] Survived: {n_survived} ({(1-crash_rate):.1%})")
        
        # Merge back to data
        data = data.copy()
        data['date'] = pd.to_datetime(data['date']).dt.normalize()
        
        merged = pd.merge(
            data,
            results_df[['ticker', 'date', 'MFE', 'MAE', 'structural_stop', 'is_survivor', 'y_max']],
            on=['ticker', 'date'],
            how='left'
        )
        
        # Calculate regret
        if 'return_pct' in merged.columns:
            merged['regret'] = merged['MFE'] - merged['return_pct']
        
        missing = merged['y_max'].isna().sum()
        if missing > 0:
            logger.warning(f"   {missing} trades missing survivor labels")
            merged['y_max'] = merged['y_max'].fillna(merged['return_pct'])
            merged['is_survivor'] = merged['is_survivor'].fillna(True)
        
        return merged
    
    def calculate_y_max(
        self,
        data: pd.DataFrame,
        d2r_path: str = 'data/ml/d2r_sepa.parquet'
    ) -> pd.DataFrame:
        """
        Calculate y_max (Maximum Favorable Excursion) for each trade.
        
        y_max = max return achievable during the trade (peak - entry) / entry * 100
        
        Args:
            data: D2 features DataFrame
            d2r_path: Path to D2 rehydrated parquet file
            
        Returns:
            DataFrame with y_max column added
        """
        d2r_file = Path(d2r_path)
        if not d2r_file.exists():
            alt_path = Path('data/ml/d2_rehydrated.parquet')
            if alt_path.exists():
                d2r_file = alt_path
            else:
                logger.warning(f"D2R not found: {d2r_path}")
                return data
        
        logger.info(f"Calculating y_max from {d2r_file}...")
        d2r = pd.read_parquet(d2r_file)
        
        if 'day_in_trade' not in d2r.columns:
            d2r = d2r.sort_values(['trade_id', 'Date'])
            d2r['day_in_trade'] = d2r.groupby('trade_id').cumcount()
        
        y_max_results = []
        
        for trade_id, group in d2r.groupby('trade_id'):
            entry_rows = group[group['day_in_trade'] == 0]
            if len(entry_rows) == 0:
                continue
            
            entry_price = entry_rows['Close'].iloc[0]
            if entry_price <= 0:
                continue
            
            highest = group['High'].max()
            y_max = ((highest - entry_price) / entry_price) * 100
            
            ticker = group['ticker'].iloc[0] if 'ticker' in group.columns else None
            date = entry_rows['Date'].iloc[0] if 'Date' in entry_rows.columns else None
            
            y_max_results.append({
                'ticker': ticker,
                'date': pd.to_datetime(date).normalize() if date else None,
                'y_max': y_max
            })
        
        y_max_df = pd.DataFrame(y_max_results)
        logger.info(f"   Calculated y_max for {len(y_max_df)} trades (mean: {y_max_df['y_max'].mean():.2f}%)")
        
        # Merge
        data = data.copy()
        data['date'] = pd.to_datetime(data['date']).dt.normalize()
        
        merged = pd.merge(
            data,
            y_max_df[['ticker', 'date', 'y_max']],
            on=['ticker', 'date'],
            how='left'
        )
        
        if 'return_pct' in merged.columns:
            merged['regret'] = merged['y_max'] - merged['return_pct']
        
        missing = merged['y_max'].isna().sum()
        if missing > 0:
            logger.warning(f"   {missing} trades missing y_max")
            merged['y_max'] = merged['y_max'].fillna(merged['return_pct'])
        
        return merged
    
    # =========================================================================
    # OVERRIDE: Enhanced Train Method
    # =========================================================================
    def train(
        self,
        data: pd.DataFrame,
        tune: bool = False,
        tune_trials: int = 50,
        train_years: int = 3,
        test_years: int = 1,
        target: str = 'return_pct',
        survivor_model: bool = False,
        stop_multiplier: float = 2.0
    ) -> Tuple:
        """
        Train model using walk-forward validation.
        
        Enhanced with survivor model and dual-target support.
        
        Args:
            data: D2 features DataFrame
            tune: Enable Optuna hyperparameter tuning
            tune_trials: Number of Optuna trials
            train_years: Training window size
            test_years: Test window size
            target: Target column ('return_pct' or 'y_max')
            survivor_model: Enable survivor model filtering
            stop_multiplier: Structural stop multiplier for survivor filtering
            
        Returns:
            Tuple of (trained_model, metrics_df)
        """
        logger.info(f"Training {self.model_name} ({self.model_type})")
        logger.info(f"   Target: {target}")
        start_time = time.time()
        
        # Get features
        feature_cols = self.get_features()
        available_cols = [c for c in feature_cols if c in data.columns]
        missing_cols = [c for c in feature_cols if c not in data.columns]
        
        if missing_cols:
            logger.warning(f"   Missing {len(missing_cols)} features: {missing_cols[:5]}...")
        logger.info(f"   Using {len(available_cols)} features")
        
        # Prepare data
        data = data.copy()
        
        # Normalize date column
        if 'Date' in data.columns and 'date' not in data.columns:
            data = data.rename(columns={'Date': 'date'})
        
        data['date'] = pd.to_datetime(data['date'])
        data = data.sort_values('date')
        data['year'] = data['date'].dt.year
        
        # Determine target column
        if target == 'y_max':
            if 'y_max' not in data.columns:
                logger.info("   y_max not in data, calculating from D2R...")
                data = self.calculate_y_max(data)
            target_col = 'y_max'
        else:
            target_col = 'return_pct'
        
        # SURVIVOR MODEL
        if survivor_model:
            print("\n" + "=" * 70)
            print("SURVIVOR MODEL ENABLED")
            print("=" * 70)
            
            if 'is_survivor' not in data.columns:
                logger.info("   Enriching with survivor labels...")
                data = self.enrich_with_survivor_labels(
                    data,
                    stop_multiplier=stop_multiplier
                )
            
            # Use y_max as target for survivor model
            target_col = 'y_max'
            logger.info(f"   Target overridden to: {target_col}")
            
            # Filter to survivors only
            n_before = len(data)
            data = data[data['is_survivor'] == True].copy()
            n_after = len(data)
            n_filtered = n_before - n_after
            
            logger.info(f"   Filtered {n_filtered} crashed trades ({n_filtered/n_before:.1%})")
            logger.info(f"   Training on {n_after} survivor trades")
            logger.info(f"   Expected prediction bias: Mean y_max ~ {data[target_col].mean():.1f}%")
            print("=" * 70 + "\n")
        
        # Clean data
        data = self.clean_data(data, available_cols)
        years = sorted(data['year'].unique())
        
        # Optuna tuning
        best_params = {}
        if tune:
            X_tune = data[available_cols]
            y_tune = data[target_col]
            best_params = self.tune_hyperparameters(X_tune, y_tune, n_trials=tune_trials)
        
        # Walk-forward validation
        all_metrics = []
        all_predictions = []  # NEW: Store predictions for visualization
        final_model = None

        for i, test_year in enumerate(years[train_years:]):
            train_years_range = years[i:i+train_years]

            train_data = data[data['year'].isin(train_years_range)]
            test_data = data[data['year'] == test_year]

            if len(train_data) < 50 or len(test_data) < 10:
                logger.warning(f"   Skipping {test_year} (insufficient data)")
                continue

            X_train = train_data[available_cols]
            y_train = train_data[target_col]
            X_test = test_data[available_cols]
            y_test = test_data[target_col]

            # Create and train model
            params = self.get_model_params(best_params)
            model = self.create_model(params)
            model.fit(X_train, y_train, verbose=False)

            # Evaluate
            preds = model.predict(X_test)
            fold_metrics = self._evaluate_fold(
                y_test, preds, model, test_year,
                len(train_data), len(test_data)
            )
            all_metrics.append(fold_metrics)

            # NEW: Store predictions with metadata for visualization
            test_data_copy = test_data.copy()
            test_data_copy['y_pred'] = preds
            test_data_copy['y_true'] = y_test.values
            test_data_copy['test_year'] = test_year
            test_data_copy['fold'] = i + 1
            all_predictions.append(test_data_copy)

            logger.info(f"   Fold {i+1} (Test {test_year}): {self._format_fold_result(fold_metrics)}")
            final_model = model

        # Summary
        metrics_df = pd.DataFrame(all_metrics)
        self._print_summary(metrics_df)

        elapsed = time.time() - start_time
        logger.info(f"   Training complete in {elapsed:.1f}s")

        # Store for saving and report generation
        self._feature_cols = available_cols
        self._target_col = target_col
        self._survivor_model = survivor_model
        self._stop_multiplier = stop_multiplier
        self._all_predictions = pd.concat(all_predictions, ignore_index=True) if all_predictions else pd.DataFrame()

        return final_model, metrics_df
    
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
        
        # Save to CSV
        csv_path = self.output_dir / 'feature_importance_m01.csv'
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
        Generate comprehensive markdown report for training results.
        
        Args:
            model: Trained XGBoost model
            metrics_df: Walk-forward validation metrics
            start_date: Training start date
            end_date: Training end date
            
        Returns:
            Path to saved report
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.output_dir / f"model_report_M01_{timestamp}.md"
        
        # Get feature importance
        feature_cols = self._feature_cols if hasattr(self, '_feature_cols') else []
        importance_df = self.save_feature_importance(model, feature_cols) if feature_cols else None
        
        # Calculate summary statistics
        avg_rmse = metrics_df['rmse'].mean()
        avg_edge = metrics_df['selection_edge'].mean()
        avg_top_decile = metrics_df['top_decile_mean'].mean()
        min_edge = metrics_df['selection_edge'].min()
        max_edge = metrics_df['selection_edge'].max()
        positive_folds = (metrics_df['selection_edge'] > 0).sum()
        edge_std = metrics_df['selection_edge'].std()
        edge_sharpe = avg_edge / edge_std if edge_std > 0 else 0
        
        # Build report
        lines = []
        lines.append("# Model Training Report - M01 (SEPA Signal Quality Model)")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if start_date and end_date:
            lines.append(f"**Training Period:** {start_date} to {end_date}")
        lines.append(f"**Model Type:** REGRESSION")
        
        # Survivor model info
        if hasattr(self, '_survivor_model') and self._survivor_model:
            lines.append(f"**Survivor Model:** Enabled (stop multiplier: {self._stop_multiplier})")
        if hasattr(self, '_target_col'):
            lines.append(f"**Target:** {self._target_col}")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Executive Summary
        viability = "VIABLE" if avg_edge > 1.5 else "MARGINAL" if avg_edge > 0.5 else "NOT VIABLE"
        lines.append("## Executive Summary")
        lines.append("")
        lines.append(f"**Trading Viability:** {viability}")
        lines.append("")
        lines.append("### Key Metrics")
        lines.append("")
        lines.append(f"- **Selection Edge:** {avg_edge:+.2f}% (range: [{min_edge:+.2f}%, {max_edge:+.2f}%])")
        lines.append(f"- **Edge Consistency:** {positive_folds}/{len(metrics_df)} folds positive ({positive_folds/len(metrics_df)*100:.0f}%)")
        lines.append(f"- **Edge Sharpe Ratio:** {edge_sharpe:.2f}")
        lines.append(f"- **Top Decile Return:** {avg_top_decile:.2f}%")
        lines.append(f"- **RMSE:** {avg_rmse:.2f}%")
        lines.append(f"- **Walk-Forward Folds:** {len(metrics_df)}")
        lines.append(f"- **Total Test Samples:** {metrics_df['test_samples'].sum():,}")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Walk-Forward Results
        lines.append("## Walk-Forward Validation Results")
        lines.append("")
        lines.append("| Fold | Test Year | Test Samples | RMSE | Selection Edge | Top Decile Mean |")
        lines.append("|------|-----------|--------------|------|----------------|-----------------|")
        
        for i, row in metrics_df.iterrows():
            lines.append(
                f"| {i+1} | {row.get('test_year', 'N/A')} | {row['test_samples']:,} | "
                f"{row['rmse']:.2f}% | {row['selection_edge']:+.2f}% | {row['top_decile_mean']:.2f}% |"
            )
        
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Feature Importance
        if importance_df is not None and len(importance_df) > 0:
            lines.append("## Feature Importance Analysis")
            lines.append("")
            lines.append(f"**Total Features:** {len(feature_cols)}")
            lines.append("")
            lines.append("### Top 20 Features by Gain")
            lines.append("")
            lines.append("| Rank | Feature | Gain | % Total | Cumulative % |")
            lines.append("|------|---------|------|---------|--------------|")
            
            for _, row in importance_df.head(20).iterrows():
                lines.append(
                    f"| {int(row['rank'])} | {row['feature']} | {row['gain']:.0f} | "
                    f"{row['gain_pct']:.1f}% | {row['cumulative_pct']:.1f}% |"
                )
            
            lines.append("")
            lines.append("---")
            lines.append("")
        
        # Model Configuration
        lines.append("## Model Configuration")
        lines.append("")
        lines.append("```python")
        lines.append("XGBRegressor(")
        lines.append("    objective='reg:squarederror',")
        lines.append("    n_estimators=300,")
        lines.append("    learning_rate=0.03,")
        lines.append("    max_depth=4,")
        lines.append("    subsample=0.8,")
        lines.append("    colsample_bytree=0.8,")
        lines.append("    reg_alpha=5.0,")
        lines.append("    reg_lambda=3.0,")
        lines.append("    random_state=42")
        lines.append(")")
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("*Report generated by M01Trainer*")
        
        # Write report
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"Saved model report to {report_path}")

        # Also generate D1 analysis JSON for dashboard
        self._generate_d1_analysis_json()

        # NEW: Save M01 visualization data to m01_config.json
        self._save_visualization_data_to_config()

        return str(report_path)

    def _save_visualization_data_to_config(self):
        """Save M01 visualization data to m01_config.json."""
        import json

        config_path = self.output_dir / 'm01_config.json'

        # Load existing config
        config = {}
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = json.load(f)

        # Add visualization data
        config['decile_performance'] = self._calculate_decile_performance()
        config['predictions_sample'] = self._sample_predictions(max_rows=1000)
        config['error_analysis'] = self._analyze_errors()

        # Save
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)

        logger.info(f"Saved M01 visualization data to {config_path}")
    
    def _generate_d1_analysis_json(self, stop_multiplier: float = 2.0):
        """
        Generate D1 analysis JSON with pre-computed trade physics stats.
        This file is used by the dashboard for fast loading.
        """
        import json
        
        d1_report = {
            'generated_at': datetime.now().isoformat(),
            'stop_multiplier': stop_multiplier,
            'total_trades': 0,
            'median_mfe': 0,
            'median_mae': 0,
            'median_e_ratio': 0,
            'crash_rate': 0,
            'survived_rate': 0
        }
        
        # Try to load D2 rehydrated and compute stats
        d2r_paths = [
            Path('data/ml/d2_rehydrated.parquet'),
            Path('data/ml/d2r_sepa.parquet')
        ]
        
        d2r = None
        for path in d2r_paths:
            if path.exists():
                d2r = pd.read_parquet(path)
                break
        
        if d2r is not None:
            # Add day_in_trade if missing
            if 'day_in_trade' not in d2r.columns:
                d2r = d2r.sort_values(['trade_id', 'Date'])
                d2r['day_in_trade'] = d2r.groupby('trade_id').cumcount()
            
            # Calculate metrics per trade
            trade_metrics = []
            for trade_id, group in d2r.groupby('trade_id'):
                entry_rows = group[group['day_in_trade'] == 0]
                if len(entry_rows) == 0:
                    continue
                
                entry_price = entry_rows['Close'].iloc[0]
                if entry_price <= 0:
                    continue
                
                natr = entry_rows['nATR'].iloc[0] if 'nATR' in entry_rows.columns else 5.0
                highest = group['High'].max()
                lowest = group['Low'].min()
                
                mfe = ((highest - entry_price) / entry_price) * 100
                mae = ((lowest - entry_price) / entry_price) * 100
                e_ratio = mfe / abs(mae) if mae != 0 else 0
                structural_stop = -stop_multiplier * natr
                is_survivor = mae > structural_stop
                
                trade_metrics.append({
                    'MFE': mfe,
                    'MAE': mae,
                    'E_Ratio': e_ratio,
                    'is_survivor': is_survivor
                })
            
            if trade_metrics:
                metrics_df = pd.DataFrame(trade_metrics)
                n_total = len(metrics_df)
                n_crashed = (~metrics_df['is_survivor']).sum()
                
                d1_report.update({
                    'total_trades': n_total,
                    'median_mfe': float(metrics_df['MFE'].median()),
                    'median_mae': float(metrics_df['MAE'].median()),
                    'mean_mfe': float(metrics_df['MFE'].mean()),
                    'mean_mae': float(metrics_df['MAE'].mean()),
                    'median_e_ratio': float(metrics_df['E_Ratio'].median()),
                    'mean_e_ratio': float(metrics_df['E_Ratio'].mean()),
                    'crash_rate': float(n_crashed / n_total * 100),
                    'survived_rate': float((n_total - n_crashed) / n_total * 100),
                    'e_ratio_gt_3_pct': float((metrics_df['E_Ratio'] > 3).mean() * 100)
                })
        
        # Save JSON
        json_path = self.output_dir / 'd1_analysis.json'
        with open(json_path, 'w') as f:
            json.dump(d1_report, f, indent=2)

        logger.info(f"Saved D1 analysis to {json_path}")

        # NEW: Generate enhanced D1 visualization data
        self._generate_d1_visualization_data(d2r, stop_multiplier)

    def _generate_d1_visualization_data(self, d2r: pd.DataFrame = None, stop_multiplier: float = 2.0):
        """
        Generate detailed D1 visualization data for dashboard charts.
        Includes: MAE/MFE scatter, E-Ratio distribution, Time-to-peak.
        """
        import json

        # Try to load D2R if not provided
        if d2r is None:
            d2r_paths = [
                Path('data/ml/d2_rehydrated.parquet'),
                Path('data/ml/d2r_sepa.parquet')
            ]
            for path in d2r_paths:
                if path.exists():
                    d2r = pd.read_parquet(path)
                    break

        if d2r is None:
            logger.warning("D2R not found, skipping D1 visualization data generation")
            return

        # Add day_in_trade if missing
        if 'day_in_trade' not in d2r.columns:
            d2r = d2r.sort_values(['trade_id', 'Date'])
            d2r['day_in_trade'] = d2r.groupby('trade_id').cumcount()

        # Calculate MAE/MFE/E-Ratio per trade
        mae_mfe_data = []
        e_ratio_list = []
        time_to_peak_list = []

        for trade_id, group in d2r.groupby('trade_id'):
            entry_rows = group[group['day_in_trade'] == 0]
            if len(entry_rows) == 0:
                continue

            entry_price = entry_rows['Close'].iloc[0]
            if entry_price <= 0:
                continue

            natr = entry_rows['nATR'].iloc[0] if 'nATR' in entry_rows.columns else 5.0
            highest = group['High'].max()
            lowest = group['Low'].min()

            mfe = ((highest - entry_price) / entry_price) * 100
            mae = ((lowest - entry_price) / entry_price) * 100
            e_ratio = mfe / abs(mae) if mae != 0 else 0
            structural_stop = -stop_multiplier * natr
            is_survivor = mae > structural_stop

            # Time to peak (days to reach MFE)
            peak_day = group[group['High'] == highest]['day_in_trade'].iloc[0]

            mae_mfe_data.append({
                'MAE': round(mae, 2),
                'MFE': round(mfe, 2),
                'E_Ratio': round(e_ratio, 2),
                'is_survivor': bool(is_survivor)
            })

            e_ratio_list.append(e_ratio)
            time_to_peak_list.append(int(peak_day))

        # Load existing d1_analysis.json and add visualization data
        json_path = self.output_dir / 'd1_analysis.json'
        d1_report = {}
        if json_path.exists():
            with open(json_path, 'r') as f:
                d1_report = json.load(f)

        # Add visualization arrays (sample to max 1000 for performance)
        sample_size = min(1000, len(mae_mfe_data))
        if sample_size > 0:
            import random
            sampled_indices = random.sample(range(len(mae_mfe_data)), sample_size)
            d1_report['mae_mfe_scatter'] = [mae_mfe_data[i] for i in sampled_indices]
            d1_report['e_ratio_distribution'] = e_ratio_list
            d1_report['time_to_peak'] = time_to_peak_list

        # Save enhanced JSON
        with open(json_path, 'w') as f:
            json.dump(d1_report, f, indent=2)

        logger.info(f"Enhanced D1 analysis with {len(mae_mfe_data)} trades visualization data")

    def _calculate_decile_performance(self) -> List[Dict]:
        """Calculate decile-level performance from stored predictions."""
        if not hasattr(self, '_all_predictions') or self._all_predictions.empty:
            return []

        df = self._all_predictions.copy()

        # Calculate deciles
        df['decile'] = pd.qcut(df['y_pred'], q=10, labels=False, duplicates='drop') + 1

        # Aggregate by decile
        decile_stats = df.groupby('decile').agg({
            'y_true': ['mean', 'count']
        }).reset_index()

        decile_stats.columns = ['decile', 'mean_return', 'count']

        return decile_stats.to_dict('records')

    def _sample_predictions(self, max_rows: int = 1000) -> List[Dict]:
        """Sample predictions for scatter plot visualization."""
        if not hasattr(self, '_all_predictions') or self._all_predictions.empty:
            return []

        df = self._all_predictions.copy()

        # Calculate decile
        df['decile'] = pd.qcut(df['y_pred'], q=10, labels=False, duplicates='drop') + 1

        # Sample
        if len(df) > max_rows:
            df = df.sample(n=max_rows, random_state=42)

        # Select relevant columns
        required_cols = ['y_pred', 'y_true', 'decile']
        optional_cols = ['ticker', 'date']

        cols = required_cols + [c for c in optional_cols if c in df.columns]
        df_sample = df[cols].copy()

        # Round for JSON serialization
        df_sample['y_pred'] = df_sample['y_pred'].round(2)
        df_sample['y_true'] = df_sample['y_true'].round(2)

        # Convert date to string if present
        if 'date' in df_sample.columns:
            df_sample['date'] = df_sample['date'].astype(str)

        return df_sample.to_dict('records')

    def _analyze_errors(self) -> Dict:
        """Analyze prediction errors: FOMO vs Toxic."""
        if not hasattr(self, '_all_predictions') or self._all_predictions.empty:
            return {}

        df = self._all_predictions.copy()

        # Define thresholds (top/bottom 30%)
        pred_threshold_high = df['y_pred'].quantile(0.70)
        pred_threshold_low = df['y_pred'].quantile(0.30)
        actual_threshold_high = df['y_true'].quantile(0.70)
        actual_threshold_low = df['y_true'].quantile(0.30)

        # Classify predictions
        df['pred_class'] = 'mid'
        df.loc[df['y_pred'] >= pred_threshold_high, 'pred_class'] = 'high'
        df.loc[df['y_pred'] <= pred_threshold_low, 'pred_class'] = 'low'

        df['actual_class'] = 'mid'
        df.loc[df['y_true'] >= actual_threshold_high, 'actual_class'] = 'high'
        df.loc[df['y_true'] <= actual_threshold_low, 'actual_class'] = 'low'

        # Calculate error types
        fomo = df[(df['pred_class'] == 'low') & (df['actual_class'] == 'high')]  # Missed winners
        toxic = df[(df['pred_class'] == 'high') & (df['actual_class'] == 'low')]  # False positives
        true_positive = df[(df['pred_class'] == 'high') & (df['actual_class'] == 'high')]
        true_negative = df[(df['pred_class'] == 'low') & (df['actual_class'] == 'low')]

        return {
            'FOMO': {
                'count': int(len(fomo)),
                'avg_missed_return': float(fomo['y_true'].mean()) if len(fomo) > 0 else 0
            },
            'Toxic': {
                'count': int(len(toxic)),
                'avg_loss': float(toxic['y_true'].mean()) if len(toxic) > 0 else 0
            },
            'True_Positive': {
                'count': int(len(true_positive)),
                'avg_return': float(true_positive['y_true'].mean()) if len(true_positive) > 0 else 0
            },
            'True_Negative': {
                'count': int(len(true_negative)),
                'avg_return': float(true_negative['y_true'].mean()) if len(true_negative) > 0 else 0
            }
        }
    
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
