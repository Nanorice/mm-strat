#!/usr/bin/env python3
"""
M01 Ablation Study: Compare Target Definitions
===============================================

Trains 5 M01 models with different target definitions and compares results:
- M01_A: Baseline survivor MFE (return_pct)
- M01_B: Hybrid floor (capped loser penalty)
- M01_C: Risk-adjusted (MFE / ATR)
- M01_D: Log-space (tail smoothing)
- M01_E: Log-hybrid (The Golden Target - loser accountability + log compression)

Usage:
    python scripts/run_m01_ablation_study.py --start 2020-01-01 --end 2023-12-31
    
Output:
    - models/model_report_M01_A_*.md
    - models/model_report_M01_B_*.md
    - models/model_report_M01_C_*.md
    - models/model_report_M01_D_*.md
    - models/model_report_M01_E_*.md
    - Comparison table printed to console
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.pipeline import M01Trainer
from src.evaluation import TargetEngineer, M01Evaluator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AblationStudy")


def load_data(start_date: str, end_date: str):
    """Load D2 and D2R datasets."""
    d2_path = Path('data/ml/d2_features.parquet')
    d2r_path = Path('data/ml/d2r_sepa.parquet')
    
    if not d2_path.exists():
        raise FileNotFoundError(f"D2 features not found: {d2_path}")
    
    d2 = pd.read_parquet(d2_path)
    d2['date'] = pd.to_datetime(d2['date'])
    
    # Filter by date range
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    d2 = d2[(d2['date'] >= start) & (d2['date'] <= end)]
    
    logger.info(f"Loaded D2: {len(d2)} trades from {start_date} to {end_date}")
    
    # Load D2R if exists
    d2r = None
    if d2r_path.exists():
        d2r = pd.read_parquet(d2r_path)
        logger.info(f"Loaded D2R: {len(d2r)} bars")
    else:
        logger.warning(f"D2R not found: {d2r_path}, using return_pct as fallback")
    
    return d2, d2r


def run_ablation_study(start_date: str, end_date: str, skip_training: bool = False):
    """
    Run ablation study comparing 5 target definitions.
    
    Args:
        start_date: Training start date
        end_date: Training end date
        skip_training: If True, skip training and just compare existing results
    """
    logger.info("=" * 70)
    logger.info("M01 ABLATION STUDY")
    logger.info("=" * 70)
    
    # Load data
    d2, d2r = load_data(start_date, end_date)
    
    # Define target configurations
    target_configs = [
        {
            'name': 'M01_A',
            'type': 'return_pct',
            'desc': 'Baseline (return_pct)',
            'survivor_model': False
        },
    ]
    
    # Only add advanced targets if D2R exists
    if d2r is not None:
        target_configs.extend([
            {
                'name': 'M01_B',
                'type': 'hybrid_floor',
                'desc': 'Hybrid Floor (capped loser penalty)',
                'survivor_model': False
            },
            {
                'name': 'M01_C',
                'type': 'risk_adjusted',
                'desc': 'Risk-Adjusted (MFE/ATR)',
                'survivor_model': False
            },
            {
                'name': 'M01_D',
                'type': 'log_space',
                'desc': 'Log-Space (tail smoothing)',
                'survivor_model': False
            },
            {
                'name': 'M01_E',
                'type': 'log_hybrid',
                'desc': 'Log-Hybrid (The Golden Target)',
                'survivor_model': False
            }
        ])
    
    results = []
    
    for config in target_configs:
        print(f"\n{'=' * 70}")
        print(f"Training {config['name']}: {config['desc']}")
        print(f"{'=' * 70}\n")
        
        try:
            # Prepare target
            if config['type'] == 'return_pct':
                d2_with_target = d2.copy()
                d2_with_target['target'] = d2_with_target['return_pct']
                target_stats = {'target_type': 'return_pct'}
            else:
                d2_with_target, target_stats = TargetEngineer.prepare_target(
                    d2, d2r, config['type']
                )
            
            if skip_training:
                logger.info(f"Skipping training for {config['name']} (--skip-training flag)")
                continue
            
            # Create trainer with evaluator
            trainer = M01Trainer()
            evaluator = M01Evaluator(
                target_type=config['type'],
                output_dir=Path('models')
            )
            
            # Train (using the standard train method for now)
            # In a full integration, the trainer would use the evaluator directly
            model, metrics_df = trainer.train(
                d2_with_target,
                target='target' if 'target' in d2_with_target.columns else 'return_pct',
                survivor_model=config['survivor_model']
            )

            # Check if training produced results
            if model is None or metrics_df.empty:
                logger.warning(f"No model trained for {config['name']} - insufficient data for walk-forward validation")
                logger.warning(f"   Tip: Need at least 4 years of data (3yr train + 1yr test)")
                continue

            # Generate report
            report_path = trainer.generate_report(model, metrics_df, start_date, end_date)

            # =====================================================================
            # CRITICAL FIX: Evaluate against RETURN_PCT, not the transformed target
            # =====================================================================
            # The metrics_df from trainer evaluates against the transformed target.
            # For a fair comparison, re-evaluate predictions against return_pct.
            # This measures which training target produces the best RANKING for
            # actual trading outcomes.
            from scipy.stats import spearmanr
            from src.evaluation import analyze_deciles

            all_preds = trainer._all_predictions if hasattr(trainer, '_all_predictions') else pd.DataFrame()

            # The predictions DataFrame already contains return_pct from original data
            if not all_preds.empty and 'return_pct' in all_preds.columns and 'y_pred' in all_preds.columns:
                valid_mask = all_preds['return_pct'].notna() & all_preds['y_pred'].notna()
                y_pred = all_preds.loc[valid_mask, 'y_pred'].values
                y_true_return = all_preds.loc[valid_mask, 'return_pct'].values

                # Calculate IC against return_pct
                ic, _ = spearmanr(y_pred, y_true_return)

                # Calculate selection_edge against return_pct
                decile_result = analyze_deciles(y_true_return, y_pred)
                selection_edge = decile_result['selection_edge']

                # Calculate per-fold metrics for edge_sharpe
                fold_edges = []
                for fold_id in all_preds.loc[valid_mask, 'fold'].unique():
                    fold_mask = valid_mask & (all_preds['fold'] == fold_id)
                    if fold_mask.sum() >= 10:
                        fold_preds = all_preds.loc[fold_mask, 'y_pred'].values
                        fold_returns = all_preds.loc[fold_mask, 'return_pct'].values
                        fold_decile = analyze_deciles(fold_returns, fold_preds)
                        fold_edges.append(fold_decile['selection_edge'])

                if len(fold_edges) > 1:
                    edge_sharpe = np.mean(fold_edges) / np.std(fold_edges) if np.std(fold_edges) > 0 else 0
                    avg_edge = np.mean(fold_edges)
                else:
                    edge_sharpe = 0
                    avg_edge = selection_edge

                avg_ic = ic
                logger.info(f"   Re-evaluated against return_pct: IC={avg_ic:.3f}, Edge={avg_edge:.2f}%")
            else:
                # Fall back to trainer metrics
                avg_edge = metrics_df['selection_edge'].mean()
                edge_std = metrics_df['selection_edge'].std()
                edge_sharpe = avg_edge / edge_std if edge_std > 0 else 0
                avg_ic = metrics_df['ic'].mean() if 'ic' in metrics_df.columns else 0

            results.append({
                'model': config['name'],
                'target_type': config['type'],
                'avg_ic': avg_ic,
                'avg_edge': avg_edge,
                'edge_sharpe': edge_sharpe,
                'avg_rmse': metrics_df['rmse'].mean(),
                'report_path': report_path
            })
            
            logger.info(f"Completed {config['name']}: IC={avg_ic:.3f} Edge={avg_edge:+.2f}%")
            
        except Exception as e:
            logger.error(f"Failed to train {config['name']}: {e}")
            import traceback
            traceback.print_exc()
    
    # Print comparison
    if results:
        print("\n" + "=" * 70)
        print("ABLATION STUDY RESULTS")
        print("=" * 70)
        
        comparison_df = pd.DataFrame(results)
        print(comparison_df.to_string(index=False))
        
        # Winner selection based on edge_sharpe
        winner = comparison_df.loc[comparison_df['edge_sharpe'].idxmax()]
        print(f"\n[WINNER] RECOMMENDED TARGET: {winner['model']}")
        print(f"   Target Type: {winner['target_type']}")
        print(f"   Selection Edge: {winner['avg_edge']:+.2f}%")
        print(f"   Edge Sharpe: {winner['edge_sharpe']:.2f}")
        
        return comparison_df
    
    return None


def main():
    parser = argparse.ArgumentParser(
        description="M01 Ablation Study: Compare target definitions"
    )
    parser.add_argument(
        '--start',
        default='2020-01-01',
        help='Start date (default: 2020-01-01)'
    )
    parser.add_argument(
        '--end',
        default='2023-12-31',
        help='End date (default: 2023-12-31)'
    )
    parser.add_argument(
        '--skip-training',
        action='store_true',
        help='Skip training, just show target preparation stats'
    )
    
    args = parser.parse_args()
    
    run_ablation_study(args.start, args.end, args.skip_training)


if __name__ == '__main__':
    main()
