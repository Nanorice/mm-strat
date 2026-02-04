#!/usr/bin/env python
"""
Phase 3: M01+M02 Integration & Crisis Simulation
=================================================

This script runs the full Phase 3 evaluation:
1. Train M01 with log_space target
2. Apply volatility-adjusted scoring
3. Integrate M02 probability filtering
4. Run crisis simulation (2022)
5. Compare raw vs adjusted vs combined scores

Usage:
    python scripts/run_m01_phase3_integration.py
    python scripts/run_m01_phase3_integration.py --skip-training  # Use saved models
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd
import numpy as np
from scipy.stats import spearmanr

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import DataPipeline, M01Trainer, M02Trainer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Phase3Integration")


def load_or_train_models(skip_training: bool = False):
    """Load saved models or train new ones."""
    import xgboost as xgb

    m01_path = Path('models/m01.json')
    m02_path = Path('models/m02.json')

    m01_trainer = M01Trainer()
    m02_trainer = M02Trainer()

    # Load data
    logger.info("Loading data pipeline...")
    pipeline = DataPipeline()

    d2_path = Path('data/ml/d2_features.parquet')
    d3_path = Path('data/ml/d3_labeled.parquet')

    if not d2_path.exists():
        logger.info("D2 features not found, running pipeline...")
        d1 = pipeline.scan('2020-01-01', '2024-12-31')
        d2 = pipeline.features(d1)
    else:
        d2 = pd.read_parquet(d2_path)
        logger.info(f"Loaded D2 features: {len(d2)} samples")

    # Train or load M01
    if skip_training and m01_path.exists():
        logger.info("Loading saved M01 model...")
        m01_model = xgb.XGBRegressor()
        m01_model.load_model(str(m01_path))
    else:
        logger.info("Training M01 model...")
        m01_model, m01_metrics = m01_trainer.train(d2, target='log_space')
        m01_trainer.save(m01_model, m01_metrics)

        # Calibrate
        logger.info("Calibrating M01...")
        m01_trainer.calibrate()
        m01_trainer.save_calibrator()

    # Load calibrator if available
    calibrator_path = Path('models/m01_calibrator.pkl')
    if calibrator_path.exists():
        logger.info("Loading M01 calibrator...")
        m01_trainer.load_calibrator()

    # Train or load M02
    m02_model = None
    if d3_path.exists():
        d3 = pd.read_parquet(d3_path)
        logger.info(f"Loaded D3 labeled data: {len(d3)} samples")

        if skip_training and m02_path.exists():
            logger.info("Loading saved M02 model...")
            m02_model = xgb.XGBClassifier()
            m02_model.load_model(str(m02_path))
        else:
            logger.info("Training M02 model...")
            m02_model, m02_metrics = m02_trainer.train(d3)
            m02_trainer.save(m02_model, m02_metrics)
    else:
        logger.warning("D3 labeled data not found. M02 integration will be skipped.")
        logger.warning("Run pipeline.label() to generate D3 data.")

    return m01_trainer, m01_model, m02_trainer, m02_model, d2


def run_scoring_comparison(
    m01_trainer: M01Trainer,
    m01_model,
    m02_model,
    data: pd.DataFrame
) -> pd.DataFrame:
    """Compare different scoring methods."""
    logger.info("\n" + "=" * 70)
    logger.info("SCORING METHOD COMPARISON")
    logger.info("=" * 70)

    # Get M01 features
    feature_cols = m01_trainer.get_features()
    available_cols = [c for c in feature_cols if c in data.columns]
    X = data[available_cols]

    # Raw predictions
    data = data.copy()
    data['y_pred'] = m01_model.predict(X)

    # Target column
    target_col = 'target' if 'target' in data.columns else 'return_pct'

    results = []

    # Method 1: Raw M01 predictions
    ic_raw, _ = spearmanr(data['y_pred'], data[target_col])
    results.append({
        'method': 'Raw M01',
        'ic': ic_raw,
        'atr_corr': data['y_pred'].corr(data['nATR']) if 'nATR' in data.columns else None
    })

    # Method 2: Volatility-adjusted M01
    if 'nATR' in data.columns:
        data_adj = m01_trainer.compute_volatility_adjusted_score(data)
        ic_adj, _ = spearmanr(data_adj['adjusted_score'], data_adj[target_col])
        results.append({
            'method': 'Vol-Adjusted M01',
            'ic': ic_adj,
            'atr_corr': data_adj['adjusted_score'].corr(data_adj['nATR'])
        })

    # Method 3: Combined M01×M02
    if m02_model is not None:
        data_combined = m01_trainer.compute_combined_score(
            data, m02_model, data, use_volatility_adjustment=True
        )
        ic_combined, _ = spearmanr(data_combined['final_score'], data_combined[target_col])
        results.append({
            'method': 'Combined M01×M02',
            'ic': ic_combined,
            'atr_corr': data_combined['final_score'].corr(data_combined['nATR']) if 'nATR' in data_combined.columns else None
        })

    # Print comparison
    print("\n" + "=" * 70)
    print("SCORING METHOD COMPARISON")
    print("=" * 70)
    print(f"{'Method':<25} {'IC':>10} {'ATR Corr':>12}")
    print("-" * 50)
    for r in results:
        atr_str = f"{r['atr_corr']:+.3f}" if r['atr_corr'] is not None else "N/A"
        print(f"{r['method']:<25} {r['ic']:>+10.3f} {atr_str:>12}")
    print("=" * 70 + "\n")

    return pd.DataFrame(results)


def run_crisis_simulation(
    m01_trainer: M01Trainer,
    m01_model,
    m02_model,
    data: pd.DataFrame
) -> dict:
    """Run crisis simulation for 2022."""
    logger.info("\n" + "=" * 70)
    logger.info("CRISIS SIMULATION (2022)")
    logger.info("=" * 70)

    # Run with different configurations
    results = {}

    # Config 1: Raw M01 only
    logger.info("Running raw M01 simulation...")
    results['raw_m01'] = m01_trainer.run_crisis_simulation(
        data, m01_model,
        crisis_period=('2022-01-01', '2022-12-31'),
        m02_model=None,
        use_volatility_adjustment=False
    )

    # Config 2: Vol-adjusted M01
    logger.info("Running vol-adjusted M01 simulation...")
    results['vol_adjusted'] = m01_trainer.run_crisis_simulation(
        data, m01_model,
        crisis_period=('2022-01-01', '2022-12-31'),
        m02_model=None,
        use_volatility_adjustment=True
    )

    # Config 3: Combined M01×M02
    if m02_model is not None:
        logger.info("Running combined M01×M02 simulation...")
        results['combined'] = m01_trainer.run_crisis_simulation(
            data, m01_model,
            crisis_period=('2022-01-01', '2022-12-31'),
            m02_model=m02_model,
            use_volatility_adjustment=True
        )

    # Summary comparison
    print("\n" + "=" * 70)
    print("CRISIS SIMULATION SUMMARY (2022)")
    print("=" * 70)
    print(f"{'Configuration':<25} {'IC':>8} {'Edge':>10} {'Top Decile':>12}")
    print("-" * 60)

    for name, r in results.items():
        if r.get('status') not in ['no_data', 'no_target']:
            print(f"{name:<25} {r['ic']:>+8.3f} {r['selection_edge']:>+10.2f}% {r['top_decile_mean']:>12.2f}%")

    print("=" * 70 + "\n")

    return results


def save_results(scoring_comparison: pd.DataFrame, crisis_results: dict):
    """Save Phase 3 results to JSON."""
    output_path = Path('models/phase3_results.json')

    results = {
        'scoring_comparison': scoring_comparison.to_dict('records'),
        'crisis_simulation': {
            k: {kk: vv for kk, vv in v.items() if kk != 'monthly_ic'}
            for k, v in crisis_results.items()
            if isinstance(v, dict)
        }
    }

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    logger.info(f"Saved Phase 3 results to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Phase 3: M01+M02 Integration')
    parser.add_argument('--skip-training', action='store_true',
                       help='Use saved models instead of training')
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("PHASE 3: M01+M02 INTEGRATION & CRISIS SIMULATION")
    print("=" * 70 + "\n")

    # Load or train models
    m01_trainer, m01_model, m02_trainer, m02_model, d2 = load_or_train_models(
        skip_training=args.skip_training
    )

    # Run scoring comparison
    scoring_comparison = run_scoring_comparison(m01_trainer, m01_model, m02_model, d2)

    # Run crisis simulation
    crisis_results = run_crisis_simulation(m01_trainer, m01_model, m02_model, d2)

    # Save results
    save_results(scoring_comparison, crisis_results)

    # Final summary
    print("\n" + "=" * 70)
    print("PHASE 3 COMPLETE")
    print("=" * 70)
    print("\nKey Findings:")

    if 'vol_adjusted' in crisis_results and crisis_results['vol_adjusted'].get('ic'):
        raw_ic = crisis_results.get('raw_m01', {}).get('ic', 0)
        adj_ic = crisis_results.get('vol_adjusted', {}).get('ic', 0)
        ic_change = adj_ic - raw_ic
        print(f"  - Volatility adjustment IC change: {ic_change:+.3f}")

    if 'combined' in crisis_results and crisis_results['combined'].get('ic'):
        adj_ic = crisis_results.get('vol_adjusted', {}).get('ic', 0)
        combined_ic = crisis_results.get('combined', {}).get('ic', 0)
        ic_change = combined_ic - adj_ic
        print(f"  - M02 integration IC change: {ic_change:+.3f}")

    print("\nFiles generated:")
    print("  - models/phase3_results.json")
    print("=" * 70 + "\n")


if __name__ == '__main__':
    main()
