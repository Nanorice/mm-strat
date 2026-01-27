#!/usr/bin/env python3
"""
Model Training CLI (Clean Interface)
=====================================

Simplified CLI for ML model training using the pipeline module.

Usage:
    # M01 (Regression - predicts expected return %)
    python model.py m01 --start 2020-01-01 --end 2023-12-31
    
    # M02 (Classification - predicts ignition probability)
    python model.py m02 --start 2020-01-01 --end 2023-12-31 --horizon 120
    
    # Run specific steps only
    python model.py m01 --steps scan features  # Data prep only
    python model.py m02 --steps train          # Train using existing data

For legacy CLI with more options, use: python model_trainer.py
"""

import argparse
import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("model.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("model")


def run_m01_pipeline(args):
    """Run M01 (regression) training pipeline."""
    from src.pipeline import DataPipeline, M01Trainer
    
    print("\n" + "=" * 70)
    print(" M01 PIPELINE (Return Regressor)")
    print("=" * 70)
    print(f"   Date Range: {args.start} to {args.end}")
    print(f"   Steps: {args.steps}")
    print(f"   Target: {args.target}")
    if args.survivor:
        print(f"   Survivor Model: ENABLED (stop mult: {getattr(args, 'stop_mult', 2.0)})")
    print("=" * 70 + "\n")
    
    pipeline = DataPipeline()
    
    # Step 1: Scan (generate D1)
    if 'scan' in args.steps:
        d1 = pipeline.scan(args.start, args.end, threshold=args.threshold)
    elif 'features' in args.steps or 'train' in args.steps:
        d1 = pipeline.load_d1()
    
    # Step 2: Features (generate D2)
    if 'features' in args.steps:
        d2 = pipeline.features(d1, n_jobs=args.jobs)
    elif 'train' in args.steps:
        d2 = pipeline.load_d2()
    
    # Step 3: Train M01
    if 'train' in args.steps:
        trainer = M01Trainer()
        model, metrics = trainer.train(
            d2, 
            tune=args.tune,
            target=args.target,
            survivor_model=args.survivor,
            stop_multiplier=getattr(args, 'stop_mult', 2.0)
        )
        trainer.save(model, metrics)
        print("\n✅ M01 model saved to models/m01.json")
        
        # Generate report if requested
        if args.report:
            report_path = trainer.generate_report(
                model, metrics,
                start_date=args.start,
                end_date=args.end
            )
            print(f"✅ Report saved to {report_path}")


def run_m02_pipeline(args):
    """Run M02 (classification) training pipeline."""
    from src.pipeline import DataPipeline, M02Trainer
    
    print("\n" + "=" * 70)
    print(" M02 PIPELINE (Ignition Classifier)")
    print("=" * 70)
    print(f"   Date Range: {args.start} to {args.end}")
    print(f"   Horizon: {args.horizon} days")
    print(f"   Steps: {args.steps}")
    print("=" * 70 + "\n")
    
    pipeline = DataPipeline()
    
    # Step 1: Scan (generate D1)
    if 'scan' in args.steps:
        d1 = pipeline.scan(args.start, args.end)  # Uses default threshold
    elif 'hydrate' in args.steps or 'label' in args.steps or 'train' in args.steps:
        d1 = pipeline.load_d1()
    
    # Step 2: Hydrate (generate D2R with fixed horizon)
    if 'hydrate' in args.steps:
        d2r = pipeline.hydrate(d1, horizon_days=args.horizon, n_jobs=args.jobs)
    elif 'label' in args.steps or 'train' in args.steps:
        d2r = pipeline.load_d2r(horizon_days=args.horizon)
    
    # Step 3: Label (generate D3 with triple barriers)
    if 'label' in args.steps:
        d3 = pipeline.label(d2r, horizon_days=args.horizon, n_jobs=args.jobs)
    elif 'train' in args.steps:
        d3 = pipeline.load_d3(horizon_days=args.horizon)
    
    # Step 4: Train M02
    if 'train' in args.steps:
        trainer = M02Trainer()
        model, metrics = trainer.train(d3, tune=args.tune)
        trainer.save(model, metrics)
        print("\n✅ M02 model saved to models/m02.json")
        
        # Generate report if requested
        if hasattr(args, 'report') and args.report:
            report_path = trainer.generate_report(
                model, metrics,
                start_date=args.start,
                end_date=args.end
            )
            print(f"✅ Report saved to {report_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Model Training CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python model.py m01 --start 2020-01-01 --end 2023-12-31
  python model.py m02 --start 2020-01-01 --end 2023-12-31 --horizon 120
  python model.py m01 --steps train --tune  # Tune existing data
        """
    )
    
    subparsers = parser.add_subparsers(dest='model', help='Model to train')
    
    # M01 subcommand
    m01_parser = subparsers.add_parser('m01', help='Train M01 (Return Regressor)')
    m01_parser.add_argument('--start', default='2018-01-01', help='Start date')
    m01_parser.add_argument('--end', default='2023-12-31', help='End date')
    m01_parser.add_argument('--threshold', type=float, default=15.0, help='Success threshold %%')
    m01_parser.add_argument('--steps', nargs='+', default=['scan', 'features', 'train'],
                           choices=['scan', 'features', 'train'],
                           help='Pipeline steps to run')
    m01_parser.add_argument('--tune', action='store_true', help='Enable Optuna tuning')
    m01_parser.add_argument('--jobs', type=int, default=-1, help='Parallel workers (-1=all)')
    m01_parser.add_argument('--survivor', action='store_true', 
                           help='Enable survivor model (filter crashed trades)')
    m01_parser.add_argument('--stop-mult', type=float, default=2.0, 
                           help='Survivor stop multiplier (default: 2.0)')
    m01_parser.add_argument('--target', choices=['return_pct', 'y_max'], default='return_pct',
                           help='Target variable for training')
    m01_parser.add_argument('--report', action='store_true', 
                           help='Generate markdown training report')
    
    # M02 subcommand
    m02_parser = subparsers.add_parser('m02', help='Train M02 (Ignition Classifier)')
    m02_parser.add_argument('--start', default='2018-01-01', help='Start date')
    m02_parser.add_argument('--end', default='2023-12-31', help='End date')
    m02_parser.add_argument('--horizon', type=int, default=120, help='Fixed horizon in days')
    m02_parser.add_argument('--steps', nargs='+', default=['scan', 'hydrate', 'label', 'train'],
                           choices=['scan', 'hydrate', 'label', 'train'],
                           help='Pipeline steps to run')
    m02_parser.add_argument('--tune', action='store_true', help='Enable Optuna tuning')
    m02_parser.add_argument('--jobs', type=int, default=-1, help='Parallel workers (-1=all)')
    m02_parser.add_argument('--report', action='store_true',
                           help='Generate markdown training report')
    
    args = parser.parse_args()
    
    if args.model is None:
        parser.print_help()
        print("\n❌ Please specify a model: m01 or m02")
        sys.exit(1)
    
    if args.model == 'm01':
        run_m01_pipeline(args)
    elif args.model == 'm02':
        run_m02_pipeline(args)


if __name__ == "__main__":
    main()
