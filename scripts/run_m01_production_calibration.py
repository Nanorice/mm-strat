#!/usr/bin/env python3
"""
M01 Production Calibration Pipeline
====================================

Runs the full M01 production pipeline:
1. Train M01 with log_space target (the ablation study winner)
2. Run volatility detector test
3. Calibrate with isotonic regression
4. Save calibrator and generate curves for production

Usage:
    python scripts/run_m01_production_calibration.py --start 2018-01-01 --end 2025-12-31

Output:
    - models/m01_model.pkl           (trained model)
    - models/m01_calibrator.pkl      (isotonic calibrator)
    - models/m01_calibration.json    (calibration curves data)
    - models/model_report_M01_*.md   (training report)
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.pipeline import M01Trainer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("M01Production")


def load_data(start_date: str, end_date: str):
    """Load D2 features dataset."""
    d2_path = Path('data/ml/d2_features.parquet')

    if not d2_path.exists():
        raise FileNotFoundError(f"D2 features not found: {d2_path}")

    d2 = pd.read_parquet(d2_path)
    d2['date'] = pd.to_datetime(d2['date'])

    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    d2 = d2[(d2['date'] >= start) & (d2['date'] <= end)]

    logger.info(f"Loaded D2: {len(d2)} trades from {start_date} to {end_date}")
    return d2


def generate_calibration_curves(trainer: M01Trainer, output_path: Path):
    """
    Generate calibration curves JSON for production monitoring.

    Creates a JSON file with:
    - Decile boundaries (prediction thresholds)
    - Expected returns per decile
    - Count per decile
    """
    if not hasattr(trainer, '_calibration_table'):
        logger.warning("No calibration table found. Run calibrate() first.")
        return None

    cal_table = trainer._calibration_table

    calibration_data = {
        'generated_at': datetime.now().isoformat(),
        'target_type': 'log_space',
        'n_samples': int(cal_table['count'].sum()),
        'deciles': cal_table.to_dict('records'),
        'usage': {
            'interpretation': 'Higher decile = higher predicted upside potential',
            'production_threshold': 'Select decile >= 8 for high-conviction picks',
            'note': 'Predictions are log-compressed MFE, not raw returns'
        }
    }

    with open(output_path, 'w') as f:
        json.dump(calibration_data, f, indent=2)

    logger.info(f"Saved calibration curves to {output_path}")
    return calibration_data


def run_production_pipeline(start_date: str, end_date: str, save_model: bool = True):
    """
    Run the full M01 production calibration pipeline.

    Args:
        start_date: Training start date
        end_date: Training end date
        save_model: Whether to save the trained model
    """
    print("\n" + "=" * 70)
    print("M01 PRODUCTION CALIBRATION PIPELINE")
    print("=" * 70)
    print(f"Target: log_space (IC=0.338 winner from ablation study)")
    print(f"Period: {start_date} to {end_date}")
    print("=" * 70 + "\n")

    # Step 1: Load data
    logger.info("Step 1: Loading data...")
    d2 = load_data(start_date, end_date)

    # Step 2: Train M01 with log_space target
    logger.info("Step 2: Training M01 with log_space target...")
    trainer = M01Trainer()

    model, metrics_df = trainer.train(
        d2,
        target='log_space',  # The winner from ablation study
        train_years=3,
        test_years=1
    )

    if model is None or metrics_df.empty:
        logger.error("Training failed - insufficient data or error")
        return None

    # Step 3: Run volatility detector test
    logger.info("Step 3: Running volatility detector test...")
    vol_results = trainer.run_volatility_detector_test()

    # Step 4: Calibrate predictions
    logger.info("Step 4: Calibrating predictions with isotonic regression...")
    cal_results = trainer.calibrate()

    # Step 5: Save artifacts
    logger.info("Step 5: Saving artifacts...")
    output_dir = Path('models')

    if save_model:
        # Save model
        model_path = trainer.save(model, metrics_df)
        logger.info(f"   Model saved to {model_path}")

        # Save calibrator
        calibrator_path = trainer.save_calibrator()
        logger.info(f"   Calibrator saved to {calibrator_path}")

        # Generate calibration curves JSON
        cal_curves_path = output_dir / 'm01_calibration.json'
        generate_calibration_curves(trainer, cal_curves_path)

        # Generate report
        report_path = trainer.generate_report(model, metrics_df, start_date, end_date)
        logger.info(f"   Report saved to {report_path}")

    # Print summary
    print("\n" + "=" * 70)
    print("M01 PRODUCTION PIPELINE COMPLETE")
    print("=" * 70)

    avg_ic = metrics_df['ic'].mean() if 'ic' in metrics_df.columns else 0
    avg_edge = metrics_df['selection_edge'].mean()
    edge_std = metrics_df['selection_edge'].std()
    edge_sharpe = avg_edge / edge_std if edge_std > 0 else 0

    print(f"\nMODEL PERFORMANCE:")
    print(f"   Average IC:        {avg_ic:+.3f}")
    print(f"   Selection Edge:    {avg_edge:+.2f}%")
    print(f"   Edge Sharpe:       {edge_sharpe:.2f}")

    print(f"\nVOLATILITY TEST:")
    print(f"   Verdict:           {vol_results.get('verdict', 'N/A')}")
    print(f"   Pred-ATR Corr:     {vol_results.get('pred_atr_correlation', 0):+.3f}")

    print(f"\nCALIBRATION:")
    print(f"   Monotonic:         {'Yes' if cal_results['is_monotonic'] else 'No'}")
    print(f"   Cal Error:         {cal_results['calibration_error']:.4f}")

    print(f"\nOUTPUT FILES:")
    if save_model:
        print(f"   Model:             models/m01_model.pkl")
        print(f"   Calibrator:        models/m01_calibrator.pkl")
        print(f"   Calibration Data:  models/m01_calibration.json")

    print("=" * 70 + "\n")

    return {
        'model': model,
        'metrics': metrics_df,
        'volatility_test': vol_results,
        'calibration': cal_results,
        'trainer': trainer
    }


def main():
    parser = argparse.ArgumentParser(
        description="M01 Production Calibration Pipeline"
    )
    parser.add_argument(
        '--start',
        default='2018-01-01',
        help='Start date (default: 2018-01-01)'
    )
    parser.add_argument(
        '--end',
        default='2025-12-31',
        help='End date (default: 2025-12-31)'
    )
    parser.add_argument(
        '--no-save',
        action='store_true',
        help='Do not save model artifacts'
    )

    args = parser.parse_args()

    run_production_pipeline(args.start, args.end, save_model=not args.no_save)


if __name__ == '__main__':
    main()
