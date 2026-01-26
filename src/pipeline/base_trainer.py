"""
Base Trainer - Abstract base class for ML model trainers
========================================================

Provides shared functionality for M01 (regression) and M02 (classification) trainers:
    - Walk-forward validation
    - Data cleaning
    - Hyperparameter tuning (Optuna)
    - Model saving
    - Report generation
"""

import logging
import time
import numpy as np
import pandas as pd
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger("BaseTrainer")

# Optional: Optuna for hyperparameter tuning
try:
    import optuna
    from optuna.samplers import TPESampler
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False


class BaseTrainer(ABC):
    """
    Abstract base class for model trainers.
    
    Subclasses must implement:
        - get_features(): Returns list of feature column names
        - get_target_col(): Returns name of target column
        - get_model_params(): Returns default XGBoost parameters
        - create_model(): Creates XGBoost model instance
    """
    
    def __init__(self, output_dir: str = 'models'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    @abstractmethod
    def get_features(self) -> List[str]:
        """Returns list of feature column names for this model."""
        pass
    
    @abstractmethod
    def get_target_col(self) -> str:
        """Returns name of target column."""
        pass
    
    @abstractmethod
    def get_model_params(self, tuned_params: Optional[Dict] = None) -> Dict:
        """Returns XGBoost parameters."""
        pass
    
    @abstractmethod
    def create_model(self, params: Dict):
        """Creates XGBoost model instance."""
        pass
    
    @property
    @abstractmethod
    def model_type(self) -> str:
        """Returns 'regression' or 'classification'."""
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Returns model identifier (e.g., 'M01', 'M02')."""
        pass
    
    # =========================================================================
    # SHARED: Data Cleaning
    # =========================================================================
    def clean_data(self, data: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
        """
        Clean training data for XGBoost.
        
        Steps:
        1. Replace inf values with NaN
        2. Fill NaN with 0 (XGBoost handles this well)
        
        NOTE: We do NOT clip values. XGBoost naturally handles outliers.
        """
        logger.info(f"   Cleaning data ({len(feature_cols)} features)")
        
        # Replace inf
        inf_count = data[feature_cols].isin([np.inf, -np.inf]).sum().sum()
        if inf_count > 0:
            logger.warning(f"   Found {inf_count} inf values, replacing with NaN")
        data[feature_cols] = data[feature_cols].replace([np.inf, -np.inf], np.nan)
        
        # Fill NaN
        nan_count = data[feature_cols].isna().sum().sum()
        if nan_count > 0:
            logger.info(f"   Filling {nan_count} NaN values with 0")
        data[feature_cols] = data[feature_cols].fillna(0)
        
        return data
    
    # =========================================================================
    # SHARED: Decile Analysis
    # =========================================================================
    def analyze_deciles(
        self, 
        y_true: pd.Series, 
        y_pred: np.ndarray, 
        n_deciles: int = 10
    ) -> Dict:
        """
        Analyze model predictions by decile.
        
        This is THE critical diagnostic for trading models.
        """
        df = pd.DataFrame({
            'actual': y_true.values,
            'predicted': y_pred
        })
        
        try:
            df['decile'] = pd.qcut(df['predicted'], n_deciles, labels=False, duplicates='drop')
        except ValueError:
            df['decile'] = pd.qcut(df['predicted'], min(5, n_deciles), labels=False, duplicates='drop')
        
        overall_mean = df['actual'].mean()
        top_decile_mean = df[df['decile'] == df['decile'].max()]['actual'].mean()
        top_2_mean = df[df['decile'] >= df['decile'].max() - 1]['actual'].mean()
        
        return {
            'overall_mean': overall_mean,
            'top_decile_mean': top_decile_mean,
            'top_2_deciles_mean': top_2_mean,
            'selection_edge': top_decile_mean - overall_mean,
            'top2_edge': top_2_mean - overall_mean
        }
    
    # =========================================================================
    # SHARED: Hyperparameter Tuning
    # =========================================================================
    def tune_hyperparameters(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        n_trials: int = 50,
        n_splits: int = 5
    ) -> Dict:
        """
        Tune hyperparameters using Optuna with TimeSeriesSplit.
        """
        if not OPTUNA_AVAILABLE:
            logger.warning("Optuna not available, using default parameters")
            return {}
        
        import xgboost as xgb
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.metrics import mean_squared_error, roc_auc_score
        
        logger.info(f"Starting Optuna tuning ({n_trials} trials)...")
        
        def objective(trial):
            param = {
                'n_estimators': trial.suggest_int('n_estimators', 100, 500, step=50),
                'max_depth': trial.suggest_int('max_depth', 3, 7),
                'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1, log=True),
                'subsample': trial.suggest_float('subsample', 0.6, 0.95),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 0.95),
                'reg_alpha': trial.suggest_float('reg_alpha', 0.1, 10.0, log=True),
                'reg_lambda': trial.suggest_float('reg_lambda', 0.1, 10.0, log=True),
                'n_jobs': -1,
                'random_state': 42,
                'verbosity': 0
            }
            
            tscv = TimeSeriesSplit(n_splits=n_splits)
            scores = []
            
            for train_idx, val_idx in tscv.split(X):
                X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
                y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]
                
                if self.model_type == 'regression':
                    param['objective'] = 'reg:squarederror'
                    model = xgb.XGBRegressor(**param)
                    model.fit(X_train, y_train, verbose=False)
                    preds = model.predict(X_val)
                    rmse = np.sqrt(mean_squared_error(y_val, preds))
                    scores.append(rmse)
                else:
                    param['objective'] = 'binary:logistic'
                    model = xgb.XGBClassifier(**param)
                    model.fit(X_train, y_train, verbose=False)
                    probs = model.predict_proba(X_val)[:, 1]
                    if len(y_val.unique()) > 1:
                        auc = roc_auc_score(y_val, probs)
                        scores.append(1 - auc)
                    else:
                        scores.append(0.5)
            
            return np.mean(scores)
        
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(
            direction='minimize',
            sampler=TPESampler(seed=42)
        )
        study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
        
        logger.info(f"Best CV score: {study.best_trial.value:.4f}")
        return study.best_trial.params
    
    # =========================================================================
    # CORE: Walk-Forward Validation
    # =========================================================================
    def train(
        self,
        data: pd.DataFrame,
        tune: bool = False,
        tune_trials: int = 50,
        train_years: int = 3,
        test_years: int = 1
    ) -> Tuple:
        """
        Train model using walk-forward validation.
        
        Strategy:
            Fold 1: Train [2015-2017], Test [2018]
            Fold 2: Train [2016-2018], Test [2019]
            ...
        
        Returns:
            Tuple of (trained_model, metrics_df)
        """
        import xgboost as xgb
        from sklearn.metrics import accuracy_score, precision_score, roc_auc_score
        
        logger.info(f"Training {self.model_name} ({self.model_type})")
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
        
        # Normalize date column (D2 uses 'date', D3 uses 'Date')
        if 'Date' in data.columns and 'date' not in data.columns:
            data = data.rename(columns={'Date': 'date'})
        
        data['date'] = pd.to_datetime(data['date'])
        data = data.sort_values('date')
        data['year'] = data['date'].dt.year
        data = self.clean_data(data, available_cols)
        
        target_col = self.get_target_col()
        years = sorted(data['year'].unique())
        
        # Optuna tuning
        best_params = {}
        if tune:
            X_tune = data[available_cols]
            y_tune = data[target_col]
            best_params = self.tune_hyperparameters(X_tune, y_tune, n_trials=tune_trials)
        
        # Walk-forward validation
        all_metrics = []
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
            
            logger.info(f"   Fold {i+1} (Test {test_year}): {self._format_fold_result(fold_metrics)}")
            final_model = model
        
        # Summary
        metrics_df = pd.DataFrame(all_metrics)
        self._print_summary(metrics_df)
        
        elapsed = time.time() - start_time
        logger.info(f"   Training complete in {elapsed:.1f}s")
        
        # Store feature columns for saving
        self._feature_cols = available_cols
        
        return final_model, metrics_df
    
    @abstractmethod
    def _evaluate_fold(
        self, 
        y_test: pd.Series, 
        preds: np.ndarray, 
        model,
        test_year: int,
        n_train: int,
        n_test: int
    ) -> Dict:
        """Evaluate a single fold - implemented by subclass."""
        pass
    
    @abstractmethod
    def _format_fold_result(self, metrics: Dict) -> str:
        """Format fold result for logging - implemented by subclass."""
        pass
    
    @abstractmethod
    def _print_summary(self, metrics_df: pd.DataFrame):
        """Print validation summary - implemented by subclass."""
        pass
    
    # =========================================================================
    # SHARED: Save Model
    # =========================================================================
    def save(self, model, metrics_df: pd.DataFrame, config: Optional[Dict] = None):
        """
        Save trained model and configuration.
        
        Creates:
            - models/{model_name}.json - XGBoost model
            - models/{model_name}_config.json - Configuration
        """
        import json
        
        model_path = self.output_dir / f'{self.model_name.lower()}.json'
        config_path = self.output_dir / f'{self.model_name.lower()}_config.json'
        
        # Save model
        model.save_model(str(model_path))
        logger.info(f"   Saved model to {model_path}")
        
        # Save config
        save_config = {
            'model_name': self.model_name,
            'model_type': self.model_type,
            'created_at': datetime.now().isoformat(),
            'feature_columns': self._feature_cols if hasattr(self, '_feature_cols') else [],
            'validation_metrics': metrics_df.to_dict('records')
        }
        if config:
            save_config.update(config)
        
        with open(config_path, 'w') as f:
            json.dump(save_config, f, indent=2)
        logger.info(f"   Saved config to {config_path}")
        
        return model_path, config_path
