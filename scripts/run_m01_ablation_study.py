#!/usr/bin/env python3
"""
M01 Ablation Study: Compare Target Definitions
===============================================

Trains M01 models with different target definitions and compares results
to determine which target produces the best ranking for actual trading outcomes.

Target Definitions
------------------

M01_A: return_pct (Baseline)
    Formula: y = realized_return_pct
    Description: Uses the actual realized return as the target.
    Pros: Simple, no data leakage, direct optimization of returns.
    Cons: Doesn't account for unrealized potential (MFE) or path dependency.

M01_B: hybrid_floor (Capped Loser Penalty)
    Formula:
        if is_survivor: y = MFE
        else: y = max(max_penalty, -stop_multiplier * nATR)
    Where:
        - is_survivor: MAE > -stop_multiplier * nATR (didn't hit structural stop)
        - max_penalty: -10% (default cap)
        - MFE: Maximum Favorable Excursion = (highest_price - entry) / entry * 100
    Description: Survivors get credited for upside potential (MFE), while losers
                 get a capped penalty to prevent extreme losses from dominating.
    Pros: Keeps all trades, limits impact of outlier losses.
    Cons: Artificial cap may lose information about severity of losses.

M01_C: risk_adjusted (MFE / ATR)
    Formula: y = MFE / (nATR + 0.01)
    Where:
        - MFE: Maximum Favorable Excursion (%)
        - nATR: Normalized ATR (%) at entry
    Description: Normalizes returns by entry volatility. High-vol stocks need
                 proportionally higher MFE to score well.
    Pros: Prevents "volatility detector" trap where model just picks high-vol stocks.
    Cons: May underweight genuinely good high-vol setups.

M01_D: log_space (Tail Smoothing)
    Formula: y = sign(MFE) * log(1 + |MFE|)
    Description: Applies signed log transform to compress extreme tails.
                 A 100% MFE becomes ~4.6, a 10% MFE becomes ~2.4.
    Pros: Prevents outlier returns from dominating gradient updates.
    Cons: Uses MFE only, doesn't penalize losers.

M01_E: log_hybrid (The Golden Target)
    Formula: y = sign(x) * log(1 + |x|)
    Where x is determined by stop loss triggers:
        - Winners (no stop triggered): x = MFE
        - Losers (stop triggered): x = realized_loss_at_stop
    Stop Loss Triggers (first one hit):
        1. Structural: Close < Entry * (1 - 10%)
        2. Technical: Close < (SMA_50 - 1.0 * ATR)
    Description: Combines loser accountability with log compression.
                 Winners get MFE, losers get their realistic stop-loss exit.
    Pros: Best of both worlds - rewards upside, penalizes realistic losses.
    Cons: Requires D2R data with SMA_50 and ATR columns.

Key Metrics
-----------
- IC (Information Coefficient): Spearman correlation between predictions and return_pct
- Selection Edge: Top decile mean return - overall mean return
- Edge Sharpe: Selection Edge / std(Edge) across folds (measures consistency)

Usage
-----
    python scripts/run_m01_ablation_study.py --start 2020-01-01 --end 2023-12-31

Output
------
    models/ablation_study/
    ├── ablation_summary.md              # Comparison summary with winner
    ├── return_pct/
    │   └── model_report_return_pct_YYMMDD.md
    ├── hybrid_floor/
    │   └── model_report_hybrid_floor_YYMMDD.md
    ├── risk_adjusted/
    │   └── model_report_risk_adjusted_YYMMDD.md
    ├── log_space/
    │   └── model_report_log_space_YYMMDD.md
    └── log_hybrid/
        └── model_report_log_hybrid_YYMMDD.md

Dependencies
------------
- D2: Feature dataset from DataPipeline.load_d2()
- D2R: Rehydrated OHLC data from DataPipeline.load_d2r() (required for MFE-based targets)

See Also
--------
- src/evaluation/targets.py: TargetEngineer class with calculation details
- src/pipeline/m01_trainer.py: M01Trainer with training logic
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

from src.pipeline import DataPipeline, M01Trainer
from src.evaluation import TargetEngineer, M01Evaluator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AblationStudy")


def load_data(start_date: str, end_date: str):
    """Load D2 and D2R datasets using DataPipeline (same as M01 training)."""
    pipeline = DataPipeline()

    # Load D2 (same method as M01 training workflow)
    d2 = pipeline.load_d2()
    d2['date'] = pd.to_datetime(d2['date'])

    # Filter by date range
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    d2 = d2[(d2['date'] >= start) & (d2['date'] <= end)]

    logger.info(f"Loaded D2: {len(d2)} trades from {start_date} to {end_date}")

    # Load D2R if exists
    d2r = None
    try:
        d2r = pipeline.load_d2r()
        logger.info(f"Loaded D2R: {len(d2r)} bars")
    except FileNotFoundError:
        logger.warning("D2R not found, using return_pct as fallback")

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

    # Create ablation study output directory
    ablation_dir = Path('models/ablation_study')
    ablation_dir.mkdir(parents=True, exist_ok=True)

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

            # Create output directory for this target type: models/ablation_study/{target_type}/
            target_output_dir = ablation_dir / config['type']
            target_output_dir.mkdir(parents=True, exist_ok=True)

            # Create trainer with model name matching target type
            # output_dir=ablation_dir, model_name=config['type'] -> models/ablation_study/{type}/
            trainer = M01Trainer(
                output_dir=str(ablation_dir),
                model_name=config['type']
            )
            evaluator = M01Evaluator(
                target_type=config['type'],
                output_dir=target_output_dir
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
    
    # Print and save comparison
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

        # Save summary comparison report
        summary_path = ablation_dir / 'ablation_summary.md'
        _save_summary_report(comparison_df, winner, summary_path, start_date, end_date)
        print(f"\n   Summary saved: {summary_path}")

        return comparison_df

    return None


def _save_summary_report(
    comparison_df: pd.DataFrame,
    winner: pd.Series,
    output_path: Path,
    start_date: str,
    end_date: str
):
    """Save ablation study summary as markdown report."""
    from datetime import datetime

    lines = [
        "# M01 Ablation Study Summary",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Period:** {start_date} to {end_date}",
        "",
        "## Target Definitions Compared",
        "",
        "| Code | Target Type | Description |",
        "|------|-------------|-------------|",
        "| M01_A | return_pct | Baseline (realized return) |",
        "| M01_B | hybrid_floor | Capped loser penalty |",
        "| M01_C | risk_adjusted | MFE / ATR |",
        "| M01_D | log_space | Log-compressed MFE |",
        "| M01_E | log_hybrid | Log MFE + loser accountability |",
        "",
        "---",
        "",
        "## Results Comparison",
        "",
        "| Model | Target Type | IC | Edge | Edge Sharpe | RMSE |",
        "|-------|-------------|----:|-----:|------------:|-----:|",
    ]

    for _, row in comparison_df.iterrows():
        lines.append(
            f"| {row['model']} | {row['target_type']} | "
            f"{row['avg_ic']:.3f} | {row['avg_edge']:+.2f}% | "
            f"{row['edge_sharpe']:.2f} | {row['avg_rmse']:.2f} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## Recommendation",
        "",
        f"**Winner: {winner['model']}** ({winner['target_type']})",
        "",
        f"- IC: {winner['avg_ic']:.3f}",
        f"- Selection Edge: {winner['avg_edge']:+.2f}%",
        f"- Edge Sharpe: {winner['edge_sharpe']:.2f}",
        "",
        "Edge Sharpe = Edge / std(Edge) across folds, measuring consistency.",
        "",
        "---",
        "",
        "*Generated by run_m01_ablation_study.py*"
    ])

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


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
