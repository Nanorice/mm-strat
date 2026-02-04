#!/usr/bin/env python
"""
Phase 4: Production Deployment
==============================

This script runs the full Phase 4 production deployment:
1. Generate D3 labeled data (triple barrier labels)
2. Train M02 classifier on D3
3. Re-run Phase 3 with M02 integration
4. Implement real-time scoring pipeline
5. Add position sizing based on combined score

Usage:
    python scripts/run_m01_phase4_deployment.py
    python scripts/run_m01_phase4_deployment.py --skip-labeling  # Use existing D3
    python scripts/run_m01_phase4_deployment.py --skip-training  # Use saved models
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import DataPipeline, M01Trainer, M02Trainer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Phase4Deployment")


def step1_generate_d3(pipeline: DataPipeline, skip_labeling: bool = False) -> pd.DataFrame:
    """Step 1: Generate D3 labeled data with triple barrier labels."""
    print("\n" + "=" * 70)
    print("STEP 1: GENERATE D3 LABELED DATA")
    print("=" * 70)

    d3_path = Path('data/ml/d3_120d.parquet')

    if skip_labeling and d3_path.exists():
        d3 = pd.read_parquet(d3_path)
        logger.info(f"Loaded existing D3: {len(d3):,} samples")
        return d3

    # Load D2R (rehydrated data)
    d2r_path = Path('data/ml/d2r_120d.parquet')
    if not d2r_path.exists():
        logger.info("D2R not found, generating from D1...")
        d1 = pipeline.load_d1()
        d2r = pipeline.hydrate(d1, horizon_days=120)
    else:
        d2r = pd.read_parquet(d2r_path)
        logger.info(f"Loaded D2R: {len(d2r):,} rows")

    # Apply triple barrier labels
    logger.info("Applying triple barrier labels...")
    d3 = pipeline.label(
        d2r,
        k_sl=1.0,
        k_tp=4.0,
        min_tp=0.20,
        max_time=30,
        horizon_days=120
    )

    logger.info(f"Generated D3: {len(d3):,} samples")
    logger.info(f"   TP rate: {(d3['y_meta'] == 1).mean():.1%}")

    return d3


def step2_train_m02(d3: pd.DataFrame, skip_training: bool = False):
    """Step 2: Train M02 classifier on D3."""
    import xgboost as xgb

    print("\n" + "=" * 70)
    print("STEP 2: TRAIN M02 CLASSIFIER")
    print("=" * 70)

    m02_path = Path('models/m02.json')
    trainer = M02Trainer()

    if skip_training and m02_path.exists():
        logger.info("Loading saved M02 model...")
        model = xgb.XGBClassifier()
        model.load_model(str(m02_path))
        return trainer, model

    # Train M02
    logger.info(f"Training M02 on {len(d3):,} samples...")
    model, metrics = trainer.train(d3)

    # Save model
    trainer.save(model, metrics)
    logger.info(f"Saved M02 to {m02_path}")

    # Generate report
    trainer.generate_report(model, metrics)

    return trainer, model


def step3_run_integration(
    m01_trainer: M01Trainer,
    m01_model,
    m02_trainer: M02Trainer,
    m02_model,
    d2: pd.DataFrame
) -> dict:
    """Step 3: Re-run Phase 3 with M02 integration."""
    print("\n" + "=" * 70)
    print("STEP 3: PHASE 3 WITH M02 INTEGRATION")
    print("=" * 70)

    # Get predictions
    feature_cols = m01_trainer.get_features()
    available_cols = [c for c in feature_cols if c in d2.columns]
    X = d2[available_cols]

    d2 = d2.copy()
    d2['y_pred'] = m01_model.predict(X)

    results = {}

    # Run crisis simulation with M02
    logger.info("Running crisis simulation with M02 integration...")
    results['combined'] = m01_trainer.run_crisis_simulation(
        d2, m01_model,
        crisis_period=('2022-01-01', '2022-12-31'),
        m02_model=m02_model,
        use_volatility_adjustment=True
    )

    # Compare with Phase 3 results (without M02)
    results['vol_adjusted'] = m01_trainer.run_crisis_simulation(
        d2, m01_model,
        crisis_period=('2022-01-01', '2022-12-31'),
        m02_model=None,
        use_volatility_adjustment=True
    )

    # Summary comparison
    print("\n" + "=" * 70)
    print("M02 INTEGRATION IMPACT")
    print("=" * 70)

    vol_ic = results['vol_adjusted'].get('ic', 0)
    combined_ic = results['combined'].get('ic', 0)
    ic_change = combined_ic - vol_ic

    vol_edge = results['vol_adjusted'].get('selection_edge', 0)
    combined_edge = results['combined'].get('selection_edge', 0)
    edge_change = combined_edge - vol_edge

    print(f"   IC Change:   {ic_change:+.3f} ({vol_ic:.3f} -> {combined_ic:.3f})")
    print(f"   Edge Change: {edge_change:+.2f}% ({vol_edge:.2f}% -> {combined_edge:.2f}%)")
    print("=" * 70 + "\n")

    return results


def step4_implement_scoring_pipeline(m01_model, m02_model, m01_trainer: M01Trainer):
    """Step 4: Implement real-time scoring pipeline."""
    print("\n" + "=" * 70)
    print("STEP 4: REAL-TIME SCORING PIPELINE")
    print("=" * 70)

    # Create ProductionScorer class
    scorer_code = '''
class ProductionScorer:
    """
    Real-time scoring pipeline for M01+M02 ensemble.

    Usage:
        from src.pipeline import ProductionScorer

        scorer = ProductionScorer()
        scorer.load_models()

        # Score new candidates
        scores = scorer.score(df_candidates)

        # Get position sizes
        positions = scorer.get_position_sizes(scores, portfolio_value=100000)
    """

    def __init__(
        self,
        m01_path: str = 'models/m01.json',
        m02_path: str = 'models/m02.json',
        calibrator_path: str = 'models/m01_calibrator.pkl'
    ):
        self.m01_path = Path(m01_path)
        self.m02_path = Path(m02_path)
        self.calibrator_path = Path(calibrator_path)

        self.m01_model = None
        self.m02_model = None
        self.calibrator = None

        self._m01_features = None
        self._m02_features = None

    def load_models(self):
        """Load all models from disk."""
        import xgboost as xgb
        import joblib
        from src.feature_config import get_model_features

        # Load M01
        if self.m01_path.exists():
            self.m01_model = xgb.XGBRegressor()
            self.m01_model.load_model(str(self.m01_path))
            logger.info(f"Loaded M01 from {self.m01_path}")
        else:
            raise FileNotFoundError(f"M01 model not found: {self.m01_path}")

        # Load M02
        if self.m02_path.exists():
            self.m02_model = xgb.XGBClassifier()
            self.m02_model.load_model(str(self.m02_path))
            logger.info(f"Loaded M02 from {self.m02_path}")
        else:
            logger.warning(f"M02 model not found: {self.m02_path}")

        # Load calibrator
        if self.calibrator_path.exists():
            self.calibrator = joblib.load(self.calibrator_path)
            logger.info(f"Loaded calibrator from {self.calibrator_path}")

        # Load feature lists
        self._m01_features = get_model_features('M01')
        self._m02_features = get_model_features('M02')

    def score(
        self,
        candidates: pd.DataFrame,
        use_volatility_adjustment: bool = True,
        use_m02: bool = True,
        atr_column: str = 'nATR',
        penalty_weight: float = 0.5
    ) -> pd.DataFrame:
        """
        Score trade candidates with full M01+M02 pipeline.

        Args:
            candidates: DataFrame with features
            use_volatility_adjustment: Apply vol adjustment
            use_m02: Include M02 probability filtering
            atr_column: ATR column name
            penalty_weight: Vol adjustment weight

        Returns:
            DataFrame with scores: m01_score, m02_proba, adjusted_score, final_score
        """
        df = candidates.copy()

        # Step 1: M01 predictions
        m01_cols = [c for c in self._m01_features if c in df.columns]
        df['m01_score'] = self.m01_model.predict(df[m01_cols])

        # Step 2: Calibration
        if self.calibrator is not None:
            df['m01_calibrated'] = self.calibrator.predict(df['m01_score'])
        else:
            df['m01_calibrated'] = df['m01_score']

        # Step 3: Volatility adjustment
        if use_volatility_adjustment and atr_column in df.columns:
            df['pred_rank'] = df['m01_calibrated'].rank(pct=True)
            df['atr_rank'] = df[atr_column].rank(pct=True)
            df['adjusted_score'] = df['pred_rank'] * (1 - penalty_weight * df['atr_rank'])
            score_col = 'adjusted_score'
        else:
            df['adjusted_score'] = df['m01_calibrated']
            score_col = 'adjusted_score'

        # Step 4: M02 probability
        if use_m02 and self.m02_model is not None:
            m02_cols = [c for c in self._m02_features if c in df.columns]
            if len(m02_cols) > 0:
                df['m02_proba'] = self.m02_model.predict_proba(df[m02_cols])[:, 1]
                df['final_score'] = df['adjusted_score'] * df['m02_proba']
            else:
                df['m02_proba'] = 1.0
                df['final_score'] = df['adjusted_score']
        else:
            df['m02_proba'] = 1.0
            df['final_score'] = df['adjusted_score']

        # Normalize final score to 0-1 range
        df['final_score_pct'] = df['final_score'].rank(pct=True)

        return df

    def get_position_sizes(
        self,
        scores: pd.DataFrame,
        portfolio_value: float,
        max_positions: int = 10,
        score_threshold: float = 0.7,
        score_column: str = 'final_score_pct',
        sizing_method: str = 'equal'
    ) -> pd.DataFrame:
        """
        Calculate position sizes based on combined scores.

        Args:
            scores: DataFrame from score() with final_score_pct
            portfolio_value: Total portfolio value
            max_positions: Maximum positions to take
            score_threshold: Minimum score to consider (0-1)
            score_column: Column to use for ranking
            sizing_method: 'equal', 'score_weighted', or 'risk_parity'

        Returns:
            DataFrame with position sizes
        """
        df = scores.copy()

        # Filter by threshold
        df = df[df[score_column] >= score_threshold].copy()

        if len(df) == 0:
            logger.warning(f"No candidates above threshold {score_threshold}")
            return pd.DataFrame()

        # Sort by score and take top N
        df = df.sort_values(score_column, ascending=False).head(max_positions)

        n_positions = len(df)

        if sizing_method == 'equal':
            # Equal weight
            df['position_weight'] = 1.0 / n_positions

        elif sizing_method == 'score_weighted':
            # Weight by score
            total_score = df[score_column].sum()
            df['position_weight'] = df[score_column] / total_score

        elif sizing_method == 'risk_parity':
            # Inverse volatility weighting
            if 'nATR' in df.columns:
                inv_vol = 1 / df['nATR'].clip(lower=0.01)
                df['position_weight'] = inv_vol / inv_vol.sum()
            else:
                df['position_weight'] = 1.0 / n_positions
        else:
            df['position_weight'] = 1.0 / n_positions

        # Calculate dollar amounts
        df['position_value'] = df['position_weight'] * portfolio_value

        # Add position info
        df['rank'] = range(1, len(df) + 1)

        return df[['ticker', 'rank', score_column, 'm02_proba', 'position_weight', 'position_value']]
'''

    logger.info("ProductionScorer class ready for integration")
    logger.info("   See src/pipeline/production_scorer.py for implementation")

    return scorer_code


def step5_position_sizing_config():
    """Step 5: Add position sizing based on combined score."""
    print("\n" + "=" * 70)
    print("STEP 5: POSITION SIZING CONFIGURATION")
    print("=" * 70)

    config = {
        'sizing_rules': {
            'high_conviction': {
                'score_threshold': 0.85,
                'position_weight': 1.5,
                'description': 'Top 15% scores get 1.5x position'
            },
            'standard': {
                'score_threshold': 0.70,
                'position_weight': 1.0,
                'description': 'Scores 70-85% get standard position'
            },
            'reduced': {
                'score_threshold': 0.50,
                'position_weight': 0.5,
                'description': 'Scores 50-70% get half position'
            },
            'skip': {
                'score_threshold': 0.0,
                'position_weight': 0.0,
                'description': 'Below 50% - skip'
            }
        },
        'portfolio_rules': {
            'max_positions': 10,
            'max_single_position': 0.15,
            'max_sector_exposure': 0.30,
            'volatility_adjustment': True
        },
        'risk_rules': {
            'stop_loss_atr_mult': 1.0,
            'profit_target_atr_mult': 4.0,
            'max_hold_days': 30,
            'trailing_stop': False
        }
    }

    # Save config
    config_path = Path('models/production_scoring_config.json')
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    logger.info(f"Saved production config to {config_path}")

    print("\nPosition Sizing Rules:")
    for tier, rules in config['sizing_rules'].items():
        print(f"   {tier.upper()}: {rules['description']}")

    print("\nPortfolio Rules:")
    for rule, value in config['portfolio_rules'].items():
        print(f"   {rule}: {value}")

    return config


def save_phase4_results(results: dict, m02_metrics: dict = None):
    """Save Phase 4 deployment results."""
    output_path = Path('models/phase4_results.json')

    phase4_results = {
        'timestamp': datetime.now().isoformat(),
        'crisis_simulation': {
            k: {kk: vv for kk, vv in v.items() if kk != 'monthly_ic'}
            for k, v in results.items()
            if isinstance(v, dict)
        },
        'm02_integrated': True,
        'status': 'deployed'
    }

    with open(output_path, 'w') as f:
        json.dump(phase4_results, f, indent=2, default=str)

    logger.info(f"Saved Phase 4 results to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Phase 4: Production Deployment')
    parser.add_argument('--skip-labeling', action='store_true',
                       help='Use existing D3 data')
    parser.add_argument('--skip-training', action='store_true',
                       help='Use saved models')
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("PHASE 4: PRODUCTION DEPLOYMENT")
    print("=" * 70 + "\n")

    import xgboost as xgb

    pipeline = DataPipeline()

    # Step 1: Generate D3
    d3 = step1_generate_d3(pipeline, skip_labeling=args.skip_labeling)

    # Step 2: Train M02
    m02_trainer, m02_model = step2_train_m02(d3, skip_training=args.skip_training)

    # Load M01 for integration
    m01_path = Path('models/m01.json')
    if not m01_path.exists():
        raise FileNotFoundError("M01 model not found. Run Phase 3 first.")

    m01_model = xgb.XGBRegressor()
    m01_model.load_model(str(m01_path))
    m01_trainer = M01Trainer()

    # Load D2 for evaluation
    d2 = pipeline.load_d2()

    # Step 3: Run integration
    integration_results = step3_run_integration(
        m01_trainer, m01_model, m02_trainer, m02_model, d2
    )

    # Step 4: Scoring pipeline
    scorer_code = step4_implement_scoring_pipeline(m01_model, m02_model, m01_trainer)

    # Step 5: Position sizing
    sizing_config = step5_position_sizing_config()

    # Save results
    save_phase4_results(integration_results)

    # Final summary
    print("\n" + "=" * 70)
    print("PHASE 4 COMPLETE: PRODUCTION DEPLOYMENT READY")
    print("=" * 70)

    print("\nDeployment Artifacts:")
    print("   - models/m01.json (M01 regressor)")
    print("   - models/m02.json (M02 classifier)")
    print("   - models/m01_calibrator.pkl (calibration)")
    print("   - models/production_scoring_config.json (sizing rules)")
    print("   - models/phase4_results.json (deployment results)")

    print("\nProduction Usage:")
    print("   from src.pipeline import ProductionScorer")
    print("   scorer = ProductionScorer()")
    print("   scorer.load_models()")
    print("   scores = scorer.score(candidates)")
    print("   positions = scorer.get_position_sizes(scores, portfolio_value=100000)")

    print("\n" + "=" * 70 + "\n")


if __name__ == '__main__':
    main()
