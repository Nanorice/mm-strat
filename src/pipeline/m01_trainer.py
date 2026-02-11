"""
M01 Trainer - SEPA Return Regressor
===================================

M01 predicts expected return % for SEPA trade candidates.

Features: Uses M01_FEATURES from feature_config.py
Target: log_space (default) - log-compressed MFE for tail smoothing
        Formula: y = sign(MFE) × log(1 + |MFE|)
Model: XGBoost Regressor

Usage:
    from src.pipeline import DataPipeline, M01Trainer

    pipeline = DataPipeline()
    d1 = pipeline.scan('2020-01-01', '2023-12-31')
    d2 = pipeline.features(d1)

    trainer = M01Trainer()
    model, metrics = trainer.train(d2)  # Uses log_space target
    trainer.save(model, metrics)

    # With survivor model
    model, metrics = trainer.train(d2, survivor_model=True)

    # With different target
    model, metrics = trainer.train(d2, target='return_pct')
"""

import logging
import time
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .base_trainer import BaseTrainer
from src.evaluation import M01Evaluator

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
        - Custom feature set (--feature-set): Use different feature lists
        - Custom model name (--model-name): Save with different name
    """
    
    def __init__(self, output_dir: str = 'models', feature_set: str = None, model_name: str = None):
        """
        Initialize M01Trainer.
        
        Args:
            output_dir: Directory to save model files
            feature_set: Name of feature set from feature_config.py (e.g., 'M01_V2_FEATURES')
                        If None, uses default M01_FEATURES
            model_name: Custom model name for saving (e.g., 'm01_v2')
                       If None, uses default 'M01'
        """
        super().__init__(output_dir)
        self._feature_set = feature_set
        self._model_name = model_name
    
    @property
    def model_type(self) -> str:
        return 'regression'
    
    @property
    def model_name(self) -> str:
        return self._model_name if self._model_name else 'M01'
    
    def get_features(self) -> List[str]:
        """Get M01 feature list from centralized config.
        
        Uses custom feature_set if specified, otherwise M01_FEATURES.
        """
        import src.feature_config as fc
        
        if self._feature_set:
            # Try to get the custom feature set
            if hasattr(fc, self._feature_set):
                features = getattr(fc, self._feature_set)
                logger.info(f"Using custom feature set: {self._feature_set} ({len(features)} features)")
                return features
            else:
                logger.warning(f"Feature set '{self._feature_set}' not found in feature_config.py, using M01_FEATURES")
        
        from src.feature_config import M01_FEATURES
        return M01_FEATURES
    
    def get_target_col(self) -> str:
        """M01 default target: log_hybrid (Option E - The Golden Target)."""
        return 'log_hybrid'
    
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
            'n_jobs': -1,
            'enable_categorical': True  # Native categorical support for industry_id, sector_id
        }

        if tuned_params:
            default_params.update(tuned_params)

        return default_params
    
    def create_model(self, params: Dict):
        """Create XGBoost regressor with categorical support."""
        import xgboost as xgb
        # Enable categorical feature support (required for sector_id, industry_id)
        # This does not affect models without categorical features
        if 'enable_categorical' not in params:
            params = {**params, 'enable_categorical': True}
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

    def _compute_log_space_target(
        self,
        data: pd.DataFrame,
        d2r_path: str = 'data/ml/d2r_sepa.parquet'
    ) -> pd.DataFrame:
        """
        Compute log_space target: y = sign(MFE) × log(1 + |MFE|)

        This is the winner from ablation study (IC=0.338, Edge Sharpe=5.48).
        Log compression smooths heavy tails without filtering any trades.

        Args:
            data: D2 features DataFrame
            d2r_path: Path to D2 rehydrated parquet file

        Returns:
            DataFrame with 'target' column added
        """
        from src.evaluation.targets import TargetEngineer

        d2r_file = Path(d2r_path)
        if not d2r_file.exists():
            alt_path = Path('data/ml/d2_rehydrated.parquet')
            if alt_path.exists():
                d2r_file = alt_path
            else:
                logger.warning(f"D2R not found: {d2r_path}")
                logger.warning("Falling back to return_pct with log transform")
                data = data.copy()
                data['target'] = np.sign(data['return_pct']) * np.log1p(np.abs(data['return_pct']))
                return data

        logger.info(f"Computing log_space target from {d2r_file}...")
        d2r = pd.read_parquet(d2r_file)

        # Use TargetEngineer for consistent computation
        data_with_target, stats = TargetEngineer.calculate_log_space(
            data, d2r, stop_multiplier=2.0
        )

        logger.info(f"   Log-space target: mean={stats['mean_target']:.2f}, std={stats['std_target']:.2f}")
        return data_with_target

    def _compute_log_hybrid_target(
        self,
        data: pd.DataFrame,
        d2r_path: str = 'data/ml/d2r_sepa.parquet',
        hard_stop_pct: float = -10.0,
        ma_column: str = 'SMA_50'
    ) -> pd.DataFrame:
        """
        Compute log_hybrid target (Option E - The Golden Target).

        Winners (survivors): y = sign(MFE) × log(1 + |MFE|)
        Losers: y = sign(realized_loss) × log(1 + |realized_loss|)

        Loss is determined by first stop trigger hit:
        1. Structural Stop: Close < Entry × (1 + hard_stop_pct/100)
        2. Technical Stop: Close < (SMA_50 - 1.0 × ATR)

        Args:
            data: D2 features DataFrame
            d2r_path: Path to D2 rehydrated parquet file
            hard_stop_pct: Hard stop loss percentage (default -10%)
            ma_column: Moving average column for technical stop

        Returns:
            DataFrame with 'target' column added
        """
        from src.evaluation.targets import TargetEngineer

        d2r_file = Path(d2r_path)
        if not d2r_file.exists():
            alt_path = Path('data/ml/d2_rehydrated.parquet')
            if alt_path.exists():
                d2r_file = alt_path
            else:
                logger.warning(f"D2R not found: {d2r_path}")
                logger.warning("Falling back to log_space (MFE only)")
                return self._compute_log_space_target(data, d2r_path)

        logger.info(f"Computing log_hybrid target from {d2r_file}...")
        logger.info(f"   Stop triggers: hard_stop={hard_stop_pct}%, MA={ma_column}")
        d2r = pd.read_parquet(d2r_file)

        # Use TargetEngineer for log_hybrid computation
        data_with_target, stats = TargetEngineer.calculate_log_hybrid(
            data, d2r,
            stop_multiplier=2.0,
            hard_stop_pct=hard_stop_pct,
            ma_column=ma_column
        )

        logger.info(f"   Winners: {stats['winners']}, Losers: {stats['losers']} ({stats['loser_rate']:.1%})")
        logger.info(f"   Mean loser loss: {stats['mean_loser_loss']:.2f}%")
        logger.info(f"   Log-hybrid target: mean={stats['mean_target']:.2f}, std={stats['std_target']:.2f}")

        return data_with_target

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
        target: str = 'log_hybrid',
        survivor_model: bool = False,
        stop_multiplier: float = 2.0
    ) -> Tuple:
        """
        Train model using walk-forward validation.

        Default target: log_hybrid (Option E - The Golden Target)
        - Winners: log(1 + MFE)
        - Losers: log(1 + |realized_loss|) with negative sign

        Args:
            data: D2 features DataFrame
            tune: Enable Optuna hyperparameter tuning
            tune_trials: Number of Optuna trials
            train_years: Training window size
            test_years: Test window size
            target: Target type. Options:
                - 'log_hybrid' (default): Option E - loser accountability + log compression
                - 'log_space': Option D - MFE only, no loser penalty
                - 'y_max': Raw MFE/MAE hybrid
                - 'return_pct': Actual realized return
            survivor_model: Enable survivor model filtering (filters crashed trades)
            stop_multiplier: Structural stop multiplier for survivor filtering
            
        Returns:
            Tuple of (trained_model, metrics_df)
        """
        logger.info(f"Training {self.model_name} ({self.model_type})")
        logger.info(f"   Target: {target}")
        start_time = time.time()
        
        # Apply feature preprocessing (creates log_ transformed features)
        from src.feature_preprocessor import FeaturePreprocessor
        preprocessor = FeaturePreprocessor()
        
        # Get all numeric columns for preprocessing (before filtering to feature list)
        numeric_cols = data.select_dtypes(include=[np.number]).columns.tolist()
        exclude_cols = ['label', 'return_pct', 'days_held', 'year', 'trade_id']
        preprocess_cols = [c for c in numeric_cols if c not in exclude_cols]
        
        # Fit preprocessor on all data (learns bounds, TAR-based decisions)
        preprocessor.fit(data, preprocess_cols, target='return_pct')
        
        # Transform data (creates log_ prefixed columns, clips winsorized features)
        data = preprocessor.transform(data)
        log_count = sum(1 for f in preprocessor.config.get('features', {}).values() if f.get('transform') == 'log')
        win_count = sum(1 for f in preprocessor.config.get('features', {}).values() if f.get('transform') == 'winsorize')
        logger.info(f"   Preprocessor: {log_count} log-transformed, {win_count} winsorized")
        
        # Save preprocessing config to model-specific folder
        model_dir = self.get_model_dir()
        preprocessor.save(model_dir / 'preprocessing_config.json')
        
        # Get features (now includes log_ prefixed names)
        feature_cols = self.get_features()
        available_cols = [c for c in feature_cols if c in data.columns]
        missing_cols = [c for c in feature_cols if c not in data.columns]

        if missing_cols:
            logger.warning(f"   Missing {len(missing_cols)} features: {missing_cols[:5]}...")
        logger.info(f"   Using {len(available_cols)} features")

        # Convert categorical features to 'category' dtype for XGBoost native support
        from src.feature_config import CATEGORICAL_FEATURES
        cat_features = [f for f in CATEGORICAL_FEATURES if f in available_cols]
        if cat_features:
            for col in cat_features:
                data[col] = data[col].astype('category')
            logger.info(f"   Categorical features: {cat_features}")
        
        # Prepare data
        data = data.copy()
        
        # Normalize date column
        if 'Date' in data.columns and 'date' not in data.columns:
            data = data.rename(columns={'Date': 'date'})
        
        data['date'] = pd.to_datetime(data['date'])
        data = data.sort_values('date')
        data['year'] = data['date'].dt.year
        
        # Determine target column
        if target == 'log_hybrid':
            # Default: Option E - The Golden Target (loser accountability + log compression)
            if 'target' not in data.columns:
                logger.info("   Computing log_hybrid target (Option E)...")
                data = self._compute_log_hybrid_target(data)
            target_col = 'target'
            logger.info("   Using log_hybrid target (Winners: MFE, Losers: realized loss)")
        elif target == 'y_max':
            if 'y_max' not in data.columns:
                logger.info("   y_max not in data, calculating from D2R...")
                data = self.calculate_y_max(data)
            target_col = 'y_max'
        elif target == 'log_space':
            # Legacy: log-compressed MFE only (no loser penalty)
            if 'target' not in data.columns:
                logger.info("   Computing log_space target from D2R...")
                data = self._compute_log_space_target(data)
            target_col = 'target'
            logger.info("   Using log_space target (MFE only, no loser penalty)")
        elif target in data.columns:
            # Custom target column (e.g., from TargetEngineer)
            target_col = target
            logger.info(f"   Using custom target: {target_col}")
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
        all_predictions = []  # Store predictions for visualization
        final_model = None
        
        # Initialize evaluator for comprehensive metrics
        self._evaluator = M01Evaluator(
            target_type=target_col,
            output_dir=self.output_dir
        )

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

            # Evaluate using the new evaluator (comprehensive metrics)
            preds = model.predict(X_test)
            fold_metrics = self._evaluator.evaluate_fold(
                y_test, preds, test_year,
                len(train_data), len(test_data)
            )
            all_metrics.append(fold_metrics)

            # Store predictions with metadata for visualization
            test_data_copy = test_data.copy()
            test_data_copy['y_pred'] = preds
            test_data_copy['y_true'] = y_test.values
            test_data_copy['test_year'] = test_year
            test_data_copy['fold'] = i + 1
            all_predictions.append(test_data_copy)
            self._evaluator.add_predictions(test_data_copy)

            # Format fold result for logging
            ic_str = f"IC={fold_metrics.get('ic', 0):.3f}"
            edge_str = f"Edge={fold_metrics['selection_edge']:+.2f}%"
            logger.info(f"   Fold {i+1} (Test {test_year}): {ic_str} {edge_str}")
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

    def save_d2_with_scores(
        self,
        model,
        data: pd.DataFrame,
        suffix: str = None
    ) -> str:
        """
        Save D2 dataframe with M01 model scores for analysis.

        Filename: data/ml/d2_{model_name}.parquet
        Example: data/ml/d2_m01.parquet or data/ml/d2_m01_v2.parquet

        Args:
            model: Trained XGBoost model
            data: D2 features DataFrame (full dataset or test predictions)
            suffix: Optional suffix for the filename (e.g., 'test_only')

        Returns:
            Path to saved parquet file
        """
        # Save to model-specific folder: models/{model_name}/d2_scored.parquet
        model_dir = self.get_model_dir()

        if suffix:
            filename = f'd2_scored_{suffix}.parquet'
        else:
            filename = 'd2_scored.parquet'

        output_path = model_dir / filename

        # Get features
        feature_cols = self._feature_cols if hasattr(self, '_feature_cols') else self.get_features()
        available_cols = [c for c in feature_cols if c in data.columns]

        df = data.copy()

        # Add predictions if not already present
        if 'm01_score' not in df.columns:
            X = df[available_cols]
            df['m01_score'] = model.predict(X)

        # Add calibrated score if calibrator available
        if hasattr(self, '_calibrator'):
            df['m01_score_calibrated'] = self._calibrator.predict(df['m01_score'])

        # Add decile based on score
        df['m01_decile'] = pd.qcut(
            df['m01_score'], q=10, labels=False, duplicates='drop'
        ) + 1

        # Save
        df.to_parquet(output_path, index=False)

        logger.info(f"Saved D2 with {self.model_name} scores to {output_path}")
        logger.info(f"   Rows: {len(df):,} | Score range: [{df['m01_score'].min():.2f}, {df['m01_score'].max():.2f}]")

        return str(output_path)

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

        # Save to model-specific folder
        model_dir = self.get_model_dir()
        csv_path = model_dir / 'feature_importance.csv'
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
        # Use model-specific folder with readable filename: model_report_[name]_YYMMDD.md
        model_dir = self.get_model_dir()
        date_str = datetime.now().strftime("%y%m%d")
        report_path = model_dir / f"model_report_{self.model_name.lower()}_{date_str}.md"

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
        
        # =====================================================================
        # NEW: Super Stock Hunter Metrics
        # =====================================================================
        predictions = getattr(self, '_all_predictions', pd.DataFrame())
        
        if not predictions.empty and 'return_pct' in predictions.columns:
            # -----------------------------------------------------------------
            # Regime-Conditional Performance (P0)
            # -----------------------------------------------------------------
            if 'm03_regime_cat' in predictions.columns:
                lines.append("## Regime-Conditional Performance")
                lines.append("")
                lines.append("Performance bucketed by M03 market regime at entry time.")
                lines.append("")
                
                # Map ordinal back to category names
                regime_names = {0: 'Strong Bear', 1: 'Bear', 2: 'Neutral', 3: 'Bull', 4: 'Strong Bull'}
                predictions['regime_name'] = predictions['m03_regime_cat'].map(regime_names)
                
                # Compute per-regime metrics for Top Decile only
                predictions['decile'] = pd.qcut(predictions['y_pred'], q=10, labels=False, duplicates='drop') + 1
                top_decile = predictions[predictions['decile'] == 10]
                
                lines.append("### Top Decile Performance by Regime")
                lines.append("")
                lines.append("| Regime | N Trades | Win Rate | Mean Return | Median Return |")
                lines.append("|--------|----------|----------|-------------|---------------|")
                
                for regime_cat in sorted(predictions['m03_regime_cat'].dropna().unique()):
                    regime_name = regime_names.get(int(regime_cat), f'Cat {regime_cat}')
                    regime_data = top_decile[top_decile['m03_regime_cat'] == regime_cat]
                    
                    if len(regime_data) > 0:
                        n_trades = len(regime_data)
                        win_rate = (regime_data['label'] == 1).mean() * 100 if 'label' in regime_data.columns else 0
                        mean_ret = regime_data['return_pct'].mean()
                        median_ret = regime_data['return_pct'].median()
                        lines.append(f"| {regime_name} | {n_trades} | {win_rate:.1f}% | {mean_ret:+.2f}% | {median_ret:+.2f}% |")
                
                lines.append("")
                lines.append("---")
                lines.append("")
            
            # -----------------------------------------------------------------
            # Decile Win Rate (P1)
            # -----------------------------------------------------------------
            lines.append("## Decile Performance Analysis")
            lines.append("")
            
            if 'decile' not in predictions.columns:
                predictions['decile'] = pd.qcut(predictions['y_pred'], q=10, labels=False, duplicates='drop') + 1
            
            lines.append("### Win Rate and Return by Predicted Decile")
            lines.append("")
            lines.append("| Decile | N Trades | Win Rate | Mean Return | Median | Min | Max |")
            lines.append("|--------|----------|----------|-------------|--------|-----|-----|")
            
            for decile in range(1, 11):
                decile_data = predictions[predictions['decile'] == decile]
                if len(decile_data) > 0:
                    n = len(decile_data)
                    wr = (decile_data['label'] == 1).mean() * 100 if 'label' in decile_data.columns else 0
                    mean_r = decile_data['return_pct'].mean()
                    med_r = decile_data['return_pct'].median()
                    min_r = decile_data['return_pct'].min()
                    max_r = decile_data['return_pct'].max()
                    lines.append(f"| {decile} | {n} | {wr:.1f}% | {mean_r:+.2f}% | {med_r:+.2f}% | {min_r:+.1f}% | {max_r:+.1f}% |")
            
            lines.append("")

            # -----------------------------------------------------------------
            # Detailed Decile Analysis (Granular Percentiles)
            # -----------------------------------------------------------------
            lines.append("### Detailed Decile Statistics")
            lines.append("")
            lines.append("Return distribution percentiles by predicted decile:")
            lines.append("")
            lines.append("| Decile | N | Mean | Std | Min | P1 | P5 | P25 | P50 | P75 | P95 | P99 | Max |")
            lines.append("|--------|---|------|-----|-----|----|----|-----|-----|-----|-----|-----|-----|")

            for decile in range(1, 11):
                decile_data = predictions[predictions['decile'] == decile]['return_pct']
                if len(decile_data) > 0:
                    n = len(decile_data)
                    mean_r = decile_data.mean()
                    std_r = decile_data.std()
                    min_r = decile_data.min()
                    p1 = decile_data.quantile(0.01)
                    p5 = decile_data.quantile(0.05)
                    p25 = decile_data.quantile(0.25)
                    p50 = decile_data.quantile(0.50)
                    p75 = decile_data.quantile(0.75)
                    p95 = decile_data.quantile(0.95)
                    p99 = decile_data.quantile(0.99)
                    max_r = decile_data.max()
                    lines.append(
                        f"| {decile} | {n} | {mean_r:+.1f} | {std_r:.1f} | {min_r:+.0f} | "
                        f"{p1:+.0f} | {p5:+.0f} | {p25:+.0f} | {p50:+.0f} | {p75:+.0f} | "
                        f"{p95:+.0f} | {p99:+.0f} | {max_r:+.0f} |"
                    )

            # Add survivor rate per decile if available
            if 'is_survivor' in predictions.columns:
                lines.append("")
                lines.append("### Survivor Rate by Decile")
                lines.append("")
                lines.append("| Decile | N | Survivor Rate | Crash Rate | Avg MFE | Avg MAE |")
                lines.append("|--------|---|---------------|------------|---------|---------|")

                for decile in range(1, 11):
                    decile_data = predictions[predictions['decile'] == decile]
                    if len(decile_data) > 0:
                        n = len(decile_data)
                        surv_rate = decile_data['is_survivor'].mean() * 100
                        crash_rate = 100 - surv_rate
                        avg_mfe = decile_data['MFE'].mean() if 'MFE' in decile_data.columns else 0
                        avg_mae = decile_data['MAE'].mean() if 'MAE' in decile_data.columns else 0
                        lines.append(
                            f"| {decile} | {n} | {surv_rate:.1f}% | {crash_rate:.1f}% | "
                            f"{avg_mfe:+.1f}% | {avg_mae:+.1f}% |"
                        )

            lines.append("")
            lines.append("---")
            lines.append("")

            # -----------------------------------------------------------------
            # Super Stock Classification Metrics (P1)
            # -----------------------------------------------------------------
            lines.append("## Super Stock Classification")
            lines.append("")
            lines.append("*Super Stock = Return > 50%*")
            lines.append("")
            
            super_threshold = 50.0
            predictions['is_super'] = predictions['return_pct'] > super_threshold
            n_super_total = predictions['is_super'].sum()
            super_rate_market = n_super_total / len(predictions) * 100
            
            lines.append(f"**Market Base Rate:** {n_super_total} Super Stocks ({super_rate_market:.2f}% of all trades)")
            lines.append("")
            
            # Precision: Of top decile, how many are super stocks?
            top_decile = predictions[predictions['decile'] == 10]
            n_super_in_top = top_decile['is_super'].sum()
            precision_top10 = n_super_in_top / len(top_decile) * 100 if len(top_decile) > 0 else 0
            lift_top10 = precision_top10 / super_rate_market if super_rate_market > 0 else 0
            
            # Recall: Of all super stocks, how many are in top decile?
            recall_top10 = n_super_in_top / n_super_total * 100 if n_super_total > 0 else 0
            
            lines.append("### Precision & Recall")
            lines.append("")
            lines.append("| Metric | Value | Interpretation |")
            lines.append("|--------|-------|----------------|")
            lines.append(f"| Precision @ Top 10% | {precision_top10:.2f}% | {n_super_in_top}/{len(top_decile)} top picks are Super Stocks |")
            lines.append(f"| Recall @ Top 10% | {recall_top10:.1f}% | {n_super_in_top}/{n_super_total} Super Stocks found in top decile |")
            lines.append(f"| Lift @ Top 10% | {lift_top10:.1f}x | vs random ({super_rate_market:.2f}% base rate) |")
            lines.append("")
            
            # -----------------------------------------------------------------
            # Percentile Lift Table (P2)
            # -----------------------------------------------------------------
            lines.append("### Percentile Lift (Granular Selection)")
            lines.append("")
            lines.append("| Percentile | N | Super Stocks | Precision | Lift |")
            lines.append("|------------|---|--------------|-----------|------|")
            
            for pct in [99, 98, 95, 90, 80]:
                threshold = np.percentile(predictions['y_pred'], pct)
                top_pct = predictions[predictions['y_pred'] >= threshold]
                n_top = len(top_pct)
                n_super_top = top_pct['is_super'].sum()
                precision = n_super_top / n_top * 100 if n_top > 0 else 0
                lift = precision / super_rate_market if super_rate_market > 0 else 0
                lines.append(f"| Top {100-pct}% | {n_top} | {n_super_top} | {precision:.1f}% | {lift:.1f}x |")
            
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
        """Save M01 visualization data to model-specific config.json."""
        import json

        # Use model-specific folder
        model_dir = self.get_model_dir()
        config_path = model_dir / 'config.json'

        # Load existing config
        config = {}
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = json.load(f)

        # Add visualization data
        config['model_name'] = self.model_name
        config['decile_performance'] = self._calculate_decile_performance()
        config['predictions_sample'] = self._sample_predictions(max_rows=1000)
        config['error_analysis'] = self._analyze_errors()

        # Save
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)

        logger.info(f"Saved {self.model_name} visualization data to {config_path}")
    
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
        
        # Save JSON to model-specific folder
        model_dir = self.get_model_dir()
        json_path = model_dir / 'd1_analysis.json'
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

        # Load existing d1_analysis.json from model-specific folder
        model_dir = self.get_model_dir()
        json_path = model_dir / 'd1_analysis.json'
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
        """Print regression validation summary with comprehensive metrics."""
        if len(metrics_df) == 0:
            logger.warning("No validation folds completed")
            return
        
        avg_rmse = metrics_df['rmse'].mean()
        avg_edge = metrics_df['selection_edge'].mean()
        avg_top_decile = metrics_df['top_decile_mean'].mean()
        min_edge = metrics_df['selection_edge'].min()
        max_edge = metrics_df['selection_edge'].max()
        positive_folds = (metrics_df['selection_edge'] > 0).sum()
        
        # IC metrics (new from evaluator)
        avg_ic = metrics_df['ic'].mean() if 'ic' in metrics_df.columns else 0
        ic_std = metrics_df['ic'].std() if 'ic' in metrics_df.columns else 0
        ic_sharpe = avg_ic / ic_std if ic_std > 0 else 0
        ic_positive = (metrics_df['ic'] > 0).sum() if 'ic' in metrics_df.columns else 0
        
        print("\n" + "=" * 70)
        print("M01 WALK-FORWARD VALIDATION RESULTS (REGRESSION)")
        print("=" * 70)
        print(f"   Folds Completed:       {len(metrics_df)}")
        print(f"   Total Test Samples:    {metrics_df['test_samples'].sum()}")
        print(f"   Average RMSE:          {avg_rmse:.2f}%")
        
        print(f"\nRANKING QUALITY (IC)")
        print(f"   Average IC:            {avg_ic:>+6.3f}")
        print(f"   IC Sharpe:             {ic_sharpe:>6.2f}")
        print(f"   IC Positive Folds:     {ic_positive} / {len(metrics_df)} ({ic_positive/len(metrics_df)*100:.0f}%)")
        
        print(f"\nSELECTION EDGE (The Key Metric)")
        print(f"   Average Edge:          {avg_edge:>+6.2f}%")
        print(f"   Edge Range:            [{min_edge:+.2f}%, {max_edge:+.2f}%]")
        print(f"   Positive Edge Folds:   {positive_folds} / {len(metrics_df)} ({positive_folds/len(metrics_df)*100:.0f}%)")
        print(f"   Top Decile Avg Return: {avg_top_decile:>7.2f}%")
        print("=" * 70 + "\n")

    # =========================================================================
    # CALIBRATION: Isotonic Regression for Production
    # =========================================================================
    def calibrate(
        self,
        predictions: Optional[pd.DataFrame] = None,
        n_bins: int = 10
    ) -> Dict:
        """
        Calibrate model predictions using isotonic regression.

        Creates a monotonic mapping from raw predictions to expected outcomes.
        Uses OOS predictions from walk-forward validation.

        Per M01_fix_plan Step 5:
        1. Collect fully OOS predictions
        2. Bin predictions into deciles
        3. For each bin, compute realized mean of true target
        4. Fit isotonic regression for monotonic mapping

        Args:
            predictions: DataFrame with 'y_pred' and 'y_true' columns.
                        If None, uses self._all_predictions from training.
            n_bins: Number of bins for calibration diagnostics

        Returns:
            Dict with calibration results including the fitted calibrator
        """
        from sklearn.isotonic import IsotonicRegression

        # Use stored predictions if not provided
        if predictions is None:
            if not hasattr(self, '_all_predictions') or self._all_predictions.empty:
                raise ValueError("No predictions available. Run train() first or provide predictions.")
            predictions = self._all_predictions

        df = predictions.copy()
        if 'y_pred' not in df.columns or 'y_true' not in df.columns:
            raise ValueError("predictions must have 'y_pred' and 'y_true' columns")

        logger.info("Calibrating M01 predictions with isotonic regression...")
        logger.info(f"   Total OOS samples: {len(df)}")

        # Fit isotonic regression: monotonic mapping from y_pred -> y_true
        calibrator = IsotonicRegression(
            y_min=df['y_true'].min(),
            y_max=df['y_true'].max(),
            out_of_bounds='clip'
        )
        calibrator.fit(df['y_pred'], df['y_true'])

        # Generate calibrated predictions
        df['y_calibrated'] = calibrator.predict(df['y_pred'])

        # Calculate calibration diagnostics by decile
        df['decile'] = pd.qcut(df['y_pred'], q=n_bins, labels=False, duplicates='drop') + 1

        calibration_table = df.groupby('decile').agg({
            'y_pred': ['mean', 'min', 'max', 'count'],
            'y_true': 'mean',
            'y_calibrated': 'mean'
        }).round(3)

        calibration_table.columns = [
            'pred_mean', 'pred_min', 'pred_max', 'count',
            'true_mean', 'calibrated_mean'
        ]
        calibration_table = calibration_table.reset_index()

        # Check monotonicity of true_mean
        true_means = calibration_table['true_mean'].values
        is_monotonic = all(true_means[i] <= true_means[i+1] for i in range(len(true_means)-1))

        # Calculate calibration error (mean absolute diff between calibrated and true)
        calibration_error = (df['y_calibrated'] - df['y_true']).abs().mean()

        # Store calibrator for later use
        self._calibrator = calibrator
        self._calibration_table = calibration_table

        results = {
            'n_samples': len(df),
            'n_bins': n_bins,
            'is_monotonic': is_monotonic,
            'calibration_error': float(calibration_error),
            'calibration_table': calibration_table.to_dict('records'),
            'calibrator': calibrator
        }

        # Print calibration summary
        print("\n" + "=" * 70)
        print("M01 CALIBRATION RESULTS (Isotonic Regression)")
        print("=" * 70)
        print(f"   OOS Samples:          {len(df)}")
        print(f"   Monotonic Deciles:    {'Yes' if is_monotonic else 'No (WARNING)'}")
        print(f"   Calibration Error:    {calibration_error:.4f}")
        print("\n   Decile Calibration Table:")
        print("   " + "-" * 60)
        print(f"   {'Decile':>6} {'Pred Mean':>10} {'True Mean':>10} {'Calibrated':>10} {'Count':>8}")
        print("   " + "-" * 60)
        for row in calibration_table.to_dict('records'):
            print(f"   {row['decile']:>6} {row['pred_mean']:>10.3f} {row['true_mean']:>10.3f} "
                  f"{row['calibrated_mean']:>10.3f} {row['count']:>8}")
        print("=" * 70 + "\n")

        return results

    def save_calibrator(self, path: Optional[str] = None) -> str:
        """
        Save the fitted calibrator for production use.

        Args:
            path: Output path. If None, uses model-specific folder

        Returns:
            Path to saved calibrator
        """
        import pickle

        if not hasattr(self, '_calibrator'):
            raise ValueError("No calibrator fitted. Run calibrate() first.")

        if path is None:
            model_dir = self.get_model_dir()
            path = model_dir / 'calibrator.pkl'
        else:
            path = Path(path)

        with open(path, 'wb') as f:
            pickle.dump({
                'calibrator': self._calibrator,
                'calibration_table': self._calibration_table.to_dict('records')
            }, f)

        logger.info(f"Saved calibrator to {path}")
        return str(path)

    def load_calibrator(self, path: Optional[str] = None):
        """
        Load a previously saved calibrator.

        Args:
            path: Path to calibrator file. If None, uses model-specific folder

        Returns:
            Fitted IsotonicRegression calibrator
        """
        import pickle

        if path is None:
            model_dir = self.get_model_dir()
            path = model_dir / 'calibrator.pkl'
        else:
            path = Path(path)

        with open(path, 'rb') as f:
            data = pickle.load(f)

        self._calibrator = data['calibrator']
        self._calibration_table = pd.DataFrame(data['calibration_table'])

        logger.info(f"Loaded M01 calibrator from {path}")
        return self._calibrator

    def predict_calibrated(self, X: pd.DataFrame, model) -> np.ndarray:
        """
        Make calibrated predictions for production use.

        Args:
            X: Features DataFrame
            model: Trained XGBoost model

        Returns:
            Calibrated predictions array
        """
        if not hasattr(self, '_calibrator'):
            raise ValueError("No calibrator available. Run calibrate() or load_calibrator() first.")

        raw_preds = model.predict(X)
        calibrated_preds = self._calibrator.predict(raw_preds)

        return calibrated_preds

    def run_volatility_detector_test(
        self,
        predictions: Optional[pd.DataFrame] = None,
        atr_column: str = 'nATR'
    ) -> Dict:
        """
        Test if the model is just a volatility detector (M01_fix_plan Step 3).

        Runs diagnostics:
        1. Correlation of predictions with ATR
        2. Within-ATR-bucket IC
        3. Top decile concentration in high ATR bucket

        Args:
            predictions: DataFrame with 'y_pred', 'y_true', and ATR column.
                        If None, uses self._all_predictions.
            atr_column: Name of ATR column

        Returns:
            Dict with volatility detector diagnostics
        """
        from scipy.stats import spearmanr

        if predictions is None:
            if not hasattr(self, '_all_predictions') or self._all_predictions.empty:
                raise ValueError("No predictions available. Run train() first.")
            predictions = self._all_predictions

        df = predictions.copy()

        if atr_column not in df.columns:
            logger.warning(f"ATR column '{atr_column}' not found. Skipping volatility test.")
            return {'status': 'skipped', 'reason': f'{atr_column} not found'}

        logger.info("Running volatility detector test...")

        # 1. Correlation of predictions with ATR
        pred_atr_corr, pred_atr_pval = spearmanr(df['y_pred'], df[atr_column])

        # 2. Within-ATR-bucket IC
        df['atr_decile'] = pd.qcut(df[atr_column], q=10, labels=False, duplicates='drop') + 1

        within_bucket_ic = []
        for bucket, group in df.groupby('atr_decile'):
            if len(group) >= 10:
                ic, _ = spearmanr(group['y_pred'], group['y_true'])
                within_bucket_ic.append({'atr_decile': bucket, 'ic': ic, 'count': len(group)})

        within_ic_df = pd.DataFrame(within_bucket_ic)
        avg_within_ic = within_ic_df['ic'].mean() if len(within_ic_df) > 0 else 0

        # 3. Top decile concentration in high ATR
        df['pred_decile'] = pd.qcut(df['y_pred'], q=10, labels=False, duplicates='drop') + 1
        top_decile = df[df['pred_decile'] == df['pred_decile'].max()]
        top_decile_high_atr = (top_decile['atr_decile'] >= 8).mean()  # Top 30% ATR

        # Verdict
        is_vol_detector = (
            abs(pred_atr_corr) > 0.5 and
            top_decile_high_atr > 0.5
        )

        results = {
            'pred_atr_correlation': float(pred_atr_corr),
            'pred_atr_pvalue': float(pred_atr_pval),
            'avg_within_bucket_ic': float(avg_within_ic),
            'within_bucket_ic': within_ic_df.to_dict('records') if len(within_ic_df) > 0 else [],
            'top_decile_high_atr_pct': float(top_decile_high_atr),
            'is_volatility_detector': is_vol_detector,
            'verdict': 'FAIL: Volatility Detector' if is_vol_detector else 'PASS: Not a Volatility Detector'
        }

        # Print summary
        print("\n" + "=" * 70)
        print("VOLATILITY DETECTOR TEST (M01)")
        print("=" * 70)
        print(f"   Pred-ATR Correlation:     {pred_atr_corr:>+.3f} (p={pred_atr_pval:.4f})")
        print(f"   Avg Within-Bucket IC:     {avg_within_ic:>+.3f}")
        print(f"   Top Decile High-ATR %:    {top_decile_high_atr*100:.1f}%")
        print(f"\n   Verdict: {results['verdict']}")
        if is_vol_detector:
            print("   WARNING: Model may be selecting high-volatility stocks, not high-quality setups.")
        else:
            print("   Model shows ranking ability independent of volatility.")
        print("=" * 70 + "\n")

        return results

    # =========================================================================
    # PHASE 3: VOLATILITY-ADJUSTED SCORING & M02 INTEGRATION
    # =========================================================================
    def compute_volatility_adjusted_score(
        self,
        predictions: pd.DataFrame,
        atr_column: str = 'nATR',
        penalty_weight: float = 0.5
    ) -> pd.DataFrame:
        """
        Compute volatility-adjusted scores to reduce volatility bias.

        Formula: Adjusted_Score = Rank(M01) × (1 - penalty_weight × ATR_rank)

        This formula was selected from ablation study:
        - IC drop only -8.9% (acceptable)
        - ATR correlation drops from 0.76 → 0.54
        - Top decile ATR drops from 5.82% → 3.14% (almost halved)

        Args:
            predictions: DataFrame with 'y_pred' and ATR column
            atr_column: Name of ATR column (default: 'nATR')
            penalty_weight: Weight for ATR penalty (default: 0.5)

        Returns:
            DataFrame with 'adjusted_score' column added
        """
        df = predictions.copy()

        if atr_column not in df.columns:
            logger.warning(f"ATR column '{atr_column}' not found. Using raw predictions.")
            df['adjusted_score'] = df['y_pred']
            return df

        # Compute prediction rank (0 to 1, higher = better)
        df['pred_rank'] = df['y_pred'].rank(pct=True)

        # Compute ATR rank (0 to 1, higher = more volatile)
        df['atr_rank'] = df[atr_column].rank(pct=True)

        # Apply penalty: high-vol stocks get up to penalty_weight score reduction
        df['adjusted_score'] = df['pred_rank'] * (1 - penalty_weight * df['atr_rank'])

        # Normalize back to prediction scale for interpretability
        df['adjusted_score'] = (
            df['adjusted_score'].rank(pct=True) *
            (df['y_pred'].max() - df['y_pred'].min()) +
            df['y_pred'].min()
        )

        logger.info(f"Computed volatility-adjusted scores (penalty_weight={penalty_weight})")
        logger.info(f"   Original pred-ATR corr: {df['y_pred'].corr(df[atr_column]):.3f}")
        logger.info(f"   Adjusted pred-ATR corr: {df['adjusted_score'].corr(df[atr_column]):.3f}")

        return df

    def compute_combined_score(
        self,
        m01_predictions: pd.DataFrame,
        m02_model,
        m02_features: pd.DataFrame,
        use_volatility_adjustment: bool = True,
        atr_column: str = 'nATR',
        penalty_weight: float = 0.5
    ) -> pd.DataFrame:
        """
        Compute combined M01+M02 score for production ranking.

        Formula: Final_Score = Adjusted_Score × P(success|M02)

        This multiplicative formula:
        - M01 provides expected return ranking
        - M02 provides probability of hitting TP
        - Product naturally down-weights low-probability trades

        Args:
            m01_predictions: DataFrame with 'y_pred' (M01 predictions)
            m02_model: Trained M02 XGBoost classifier
            m02_features: Feature DataFrame for M02 (must have M02 features)
            use_volatility_adjustment: Apply volatility adjustment to M01 scores
            atr_column: ATR column for volatility adjustment
            penalty_weight: Weight for ATR penalty

        Returns:
            DataFrame with 'final_score' and intermediate scores
        """
        from src.feature_config import get_model_features

        df = m01_predictions.copy()

        # Step 1: Volatility adjustment (optional)
        if use_volatility_adjustment and atr_column in df.columns:
            df = self.compute_volatility_adjusted_score(df, atr_column, penalty_weight)
            m01_score_col = 'adjusted_score'
        else:
            m01_score_col = 'y_pred'

        # Step 2: Get M02 probability predictions
        m02_feature_cols = get_model_features('M02')
        available_m02_cols = [c for c in m02_feature_cols if c in m02_features.columns]

        if len(available_m02_cols) < len(m02_feature_cols) * 0.5:
            logger.warning(f"Only {len(available_m02_cols)}/{len(m02_feature_cols)} M02 features available")

        X_m02 = m02_features[available_m02_cols]
        m02_proba = m02_model.predict_proba(X_m02)[:, 1]  # P(success)

        df['m02_proba'] = m02_proba

        # Step 3: Combined score
        df['final_score'] = df[m01_score_col] * df['m02_proba']

        # Normalize final_score to 0-1 range
        df['final_score_normalized'] = df['final_score'].rank(pct=True)

        logger.info("Computed combined M01×M02 scores")
        logger.info(f"   M02 proba mean: {m02_proba.mean():.3f}")
        logger.info(f"   Final score correlation with M01: {df['final_score'].corr(df['y_pred']):.3f}")
        logger.info(f"   Final score correlation with M02: {df['final_score'].corr(df['m02_proba']):.3f}")

        return df

    def run_crisis_simulation(
        self,
        data: pd.DataFrame,
        model,
        crisis_period: tuple = ('2022-01-01', '2022-12-31'),
        m02_model=None,
        use_volatility_adjustment: bool = True
    ) -> Dict:
        """
        Run crisis simulation backtest on a specific period (e.g., 2022).

        Tests model performance during market stress:
        - Bear market drawdowns
        - High volatility regime
        - Sector rotation

        Args:
            data: Full D2 features DataFrame
            model: Trained M01 model
            crisis_period: Tuple of (start_date, end_date)
            m02_model: Optional M02 model for combined scoring
            use_volatility_adjustment: Apply volatility adjustment

        Returns:
            Dict with crisis simulation results
        """
        from scipy.stats import spearmanr

        df = data.copy()
        df['date'] = pd.to_datetime(df['date'])

        # Filter to crisis period
        start_date, end_date = crisis_period
        crisis_mask = (df['date'] >= start_date) & (df['date'] <= end_date)
        crisis_data = df[crisis_mask].copy()

        if len(crisis_data) == 0:
            logger.warning(f"No data in crisis period {crisis_period}")
            return {'status': 'no_data'}

        logger.info(f"Running crisis simulation: {start_date} to {end_date}")
        logger.info(f"   Crisis period samples: {len(crisis_data)}")

        # Get features and make predictions
        feature_cols = self.get_features()
        available_cols = [c for c in feature_cols if c in crisis_data.columns]
        X_crisis = crisis_data[available_cols]

        crisis_data['y_pred'] = model.predict(X_crisis)

        # Apply calibration if available
        if hasattr(self, '_calibrator'):
            crisis_data['y_pred_calibrated'] = self._calibrator.predict(crisis_data['y_pred'])
        else:
            crisis_data['y_pred_calibrated'] = crisis_data['y_pred']

        # Volatility adjustment
        if use_volatility_adjustment and 'nATR' in crisis_data.columns:
            crisis_data = self.compute_volatility_adjusted_score(crisis_data)
            score_col = 'adjusted_score'
        else:
            score_col = 'y_pred'

        # Combined scoring with M02
        if m02_model is not None:
            from src.feature_config import get_model_features
            m02_features = get_model_features('M02')
            available_m02 = [c for c in m02_features if c in crisis_data.columns]
            if len(available_m02) > 0:
                X_m02 = crisis_data[available_m02]
                crisis_data['m02_proba'] = m02_model.predict_proba(X_m02)[:, 1]
                crisis_data['final_score'] = crisis_data[score_col] * crisis_data['m02_proba']
                score_col = 'final_score'

        # Evaluate: IC, decile analysis
        target_col = 'target' if 'target' in crisis_data.columns else 'return_pct'

        if target_col in crisis_data.columns:
            ic, ic_pval = spearmanr(crisis_data[score_col], crisis_data[target_col])

            # Decile analysis
            crisis_data['decile'] = pd.qcut(
                crisis_data[score_col], q=10, labels=False, duplicates='drop'
            ) + 1

            decile_stats = crisis_data.groupby('decile')[target_col].agg(['mean', 'count'])
            top_decile_mean = decile_stats.loc[decile_stats.index.max(), 'mean']
            bottom_decile_mean = decile_stats.loc[decile_stats.index.min(), 'mean']
            selection_edge = top_decile_mean - crisis_data[target_col].mean()

            # Monthly breakdown
            crisis_data['month'] = crisis_data['date'].dt.to_period('M')
            monthly_ic = crisis_data.groupby('month').apply(
                lambda x: spearmanr(x[score_col], x[target_col])[0]
                if len(x) > 10 else np.nan
            )
            positive_months = (monthly_ic > 0).sum()
            total_months = (~monthly_ic.isna()).sum()

            results = {
                'period': f"{start_date} to {end_date}",
                'n_samples': len(crisis_data),
                'ic': float(ic),
                'ic_pvalue': float(ic_pval),
                'selection_edge': float(selection_edge),
                'top_decile_mean': float(top_decile_mean),
                'bottom_decile_mean': float(bottom_decile_mean),
                'baseline_mean': float(crisis_data[target_col].mean()),
                'positive_ic_months': int(positive_months),
                'total_months': int(total_months),
                'monthly_ic': monthly_ic.to_dict(),
                'score_type': score_col,
                'volatility_adjusted': use_volatility_adjustment,
                'm02_integrated': m02_model is not None
            }

            # Print summary
            print("\n" + "=" * 70)
            print(f"CRISIS SIMULATION: {start_date} to {end_date}")
            print("=" * 70)
            print(f"   Samples:              {len(crisis_data)}")
            print(f"   Score Type:           {score_col}")
            print(f"   Volatility Adjusted:  {use_volatility_adjustment}")
            print(f"   M02 Integrated:       {m02_model is not None}")
            print(f"\nPERFORMANCE")
            print(f"   IC:                   {ic:>+.3f} (p={ic_pval:.4f})")
            print(f"   Selection Edge:       {selection_edge:>+.2f}%")
            print(f"   Top Decile Mean:      {top_decile_mean:>.2f}%")
            print(f"   Baseline Mean:        {crisis_data[target_col].mean():.2f}%")
            print(f"   Positive IC Months:   {positive_months}/{total_months}")
            print("=" * 70 + "\n")

            return results
        else:
            logger.warning(f"Target column '{target_col}' not found for evaluation")
            return {'status': 'no_target', 'n_samples': len(crisis_data)}

