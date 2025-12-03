"""
Production Model Training Script - Fold 16

This script trains the production model using all available historical data (Fold 16).
Unlike the main training pipeline which trains on multiple folds, this focuses on
creating the single production model for deployment.

Usage:
    # Quick training (default parameters)
    python train_production_model.py --dataset data/ml/training_dataset_final.parquet

    # With hyperparameter optimization
    python train_production_model.py \
        --dataset data/ml/training_dataset_final.parquet \
        --optimize \
        --n-trials 50
"""

import sys
from pathlib import Path
import argparse
import logging
from datetime import datetime

# Add src to path
sys.path.append(str(Path(__file__).parent))

from src.model_preparation import prepare_training_data, TemporalSplitter, FeatureSelector
from src.train_model import SEPAModelTrainer, PrecisionAtK
from src.evaluate_model import ModelEvaluator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('training.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def main():
    """Main production training pipeline."""
    parser = argparse.ArgumentParser(
        description="Train production SEPA model (Fold 16) on all historical data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick training (default parameters)
  python train_production_model.py --dataset data/ml/training_dataset_final.parquet

  # With hyperparameter optimization (50 trials)
  python train_production_model.py \\
      --dataset data/ml/training_dataset_final.parquet \\
      --optimize \\
      --n-trials 50

  # Custom feature selection
  python train_production_model.py \\
      --dataset data/ml/training_dataset_final.parquet \\
      --correlation 0.90 \\
      --top-n 50
        """
    )

    # Data arguments
    parser.add_argument(
        '--dataset',
        type=str,
        required=True,
        help='Path to merged training dataset (parquet or csv)'
    )

    # Temporal splitting arguments
    parser.add_argument(
        '--purge-gap',
        type=int,
        default=60,
        help='Purge gap between train/test in days (default: 60)'
    )

    # Feature selection arguments
    parser.add_argument(
        '--correlation',
        type=float,
        default=0.95,
        help='Correlation threshold for feature removal (default: 0.95)'
    )

    parser.add_argument(
        '--top-n',
        type=int,
        default=None,
        help='Keep top N features by SHAP importance (default: None = keep all)'
    )

    # Training arguments
    parser.add_argument(
        '--optimize',
        action='store_true',
        help='Optimize hyperparameters with Optuna (default: False)'
    )

    parser.add_argument(
        '--n-trials',
        type=int,
        default=50,
        help='Number of Optuna trials for hyperparameter optimization (default: 50)'
    )

    parser.add_argument(
        '--precision-k',
        type=float,
        default=0.2,
        help='Top-k percentage for Precision@k metric (default: 0.2 = top 20%%)'
    )

    # Output arguments
    parser.add_argument(
        '--output-dir',
        type=str,
        default='models',
        help='Output directory for trained models (default: models)'
    )

    args = parser.parse_args()

    # Print header
    print("=" * 80)
    print(" PRODUCTION MODEL TRAINING")
    print("=" * 80)
    print(f"\nConfiguration:")
    print(f"  Dataset: {args.dataset}")
    print(f"  Training Period: 2003-01-01 to 2025-11-28 (ALL historical data - 22.9 years)")
    print(f"  Purge Gap: {args.purge_gap} days")
    print(f"  Correlation Threshold: {args.correlation}")
    print(f"  Top N Features: {args.top_n if args.top_n else 'All (after correlation filter)'}")
    print(f"  Optimize Hyperparameters: {args.optimize}")
    if args.optimize:
        print(f"  Optuna Trials: {args.n_trials}")
    print(f"  Precision@k: Top {int(args.precision_k*100)}%")
    print(f"  Output Directory: {args.output_dir}")
    print("\n" + "=" * 80)

    # Step 1: Prepare training data for production
    logger.info("\n" + "=" * 80)
    logger.info("STEP 1: DATA PREPARATION - PRODUCTION MODEL")
    logger.info("=" * 80)

    # Specify production fold (all available data from 2003)
    production_fold_spec = [('2003-01-01', '2025-11-28', '2025-12-31')]

    prep_result = prepare_training_data(
        dataset_path=args.dataset,
        purge_gap_days=args.purge_gap,
        correlation_threshold=args.correlation,
        keep_top_n=args.top_n,
        fold_specs=production_fold_spec
    )

    df = prep_result['df']
    folds = prep_result['folds']
    splitter = prep_result['splitter']
    selector = prep_result['selector']

    if len(folds) != 1:
        logger.error(f"Expected 1 production fold, but got {len(folds)} folds!")
        sys.exit(1)

    fold = folds[0]
    logger.info(f"\nProduction Fold:")
    logger.info(f"  Training samples: {fold['train_size']:,}")
    logger.info(f"  Training period: {fold['train_start'].date()} to {fold['train_end'].date()}")
    logger.info(f"  Training years: {fold['train_years']:.1f}")
    logger.info(f"  Selected features: {len(selector.selected_features)}")

    # Step 2: Train production model
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: PRODUCTION MODEL TRAINING")
    logger.info("=" * 80)

    # Get train data
    X_train, X_test, y_train, y_test = splitter.get_fold_data(
        df,
        fold_idx=0,
        feature_columns=selector.selected_features
    )

    # Apply feature selection
    X_train = selector.transform(X_train)
    X_test = selector.transform(X_test)

    # Split train into train/val (80/20)
    train_size = int(len(X_train) * 0.8)
    X_train_split = X_train.iloc[:train_size]
    y_train_split = y_train.iloc[:train_size]
    X_val_split = X_train.iloc[train_size:]
    y_val_split = y_train.iloc[train_size:]

    logger.info(f"Data splits: Train={len(X_train_split):,}, Val={len(X_val_split):,}")
    logger.info(f"Label distribution - Train: {y_train_split.mean():.1%}, Val: {y_val_split.mean():.1%}")

    # Initialize trainer
    trainer = SEPAModelTrainer(precision_k_pct=args.precision_k)

    # Optimize hyperparameters if requested
    if args.optimize:
        logger.info("\nOptimizing hyperparameters with Optuna...")
        best_params = trainer.optimize_hyperparameters(
            X_train_split,
            y_train_split,
            X_val_split,
            y_val_split,
            n_trials=args.n_trials
        )
        logger.info(f"\nBest parameters found:")
        for param, value in best_params.items():
            logger.info(f"  {param}: {value}")

    # Train production model
    logger.info("\nTraining production model with full historical data...")
    model = trainer.train_with_best_params(
        X_train_split,
        y_train_split,
        X_val_split,
        y_val_split
    )

    # Save production model with custom name
    model_filename = "model_prod.json"
    metadata_filename = "model_prod_metadata.json"
    
    # Save using custom filenames
    from pathlib import Path as PathlibPath
    output_dir_path = PathlibPath(args.output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    
    model.save_model(str(output_dir_path / model_filename))
    
    # Save metadata
    import json
    metadata = {
        'model_type': 'production',
        'train_start': str(fold['train_start'].date()),
        'train_end': str(fold['train_end'].date()),
        'train_years': fold['train_years'],
        'train_samples': fold['train_size'],
        'feature_names': selector.selected_features,
        'feature_count': len(selector.selected_features),
        'training_date': datetime.now().isoformat(),
        'hyperparameters': trainer.best_params if trainer.best_params else None
    }
    
    with open(output_dir_path / metadata_filename, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    logger.info(f"\n✅ Production model saved to: {output_dir_path.resolve()}")
    logger.info(f"   - Model: {model_filename}")
    logger.info(f"   - Metadata: {metadata_filename}")

    # Step 3: Quick evaluation on validation set
    logger.info("\n" + "=" * 80)
    logger.info("STEP 3: VALIDATION METRICS")
    logger.info("=" * 80)

    # Predict on validation set
    y_pred_proba = trainer.predict_proba(X_val_split)
    
    # Calculate metrics
    from sklearn.metrics import roc_auc_score, precision_recall_curve, auc
    
    val_auc = roc_auc_score(y_val_split, y_pred_proba)
    precision, recall, thresholds = precision_recall_curve(y_val_split, y_pred_proba)
    pr_auc = auc(recall, precision)
    
    # Calculate Precision@Top-20%
    k = int(len(y_pred_proba) * 0.2)
    top_k_indices = y_pred_proba.argsort()[-k:][::-1]
    precision_at_20 = y_val_split.iloc[top_k_indices].mean()

    logger.info(f"\nValidation Set Metrics:")
    logger.info(f"  ROC-AUC: {val_auc:.3f}")
    logger.info(f"  PR-AUC: {pr_auc:.3f}")
    logger.info(f"  Precision@Top-20%: {precision_at_20:.1%}")
    logger.info(f"  Baseline (overall win rate): {y_val_split.mean():.1%}")
    logger.info(f"  Improvement: {(precision_at_20 / y_val_split.mean()):.2f}x")

    # Final summary
    print("\n" + "=" * 80)
    print(" PRODUCTION MODEL TRAINING COMPLETE")
    print("=" * 80)
    print(f"\n✅ Model trained on {fold['train_years']:.1f} years of data (2003-2025)")
    print(f"✅ Training period: {fold['train_start'].date()} to {fold['train_end'].date()}")
    print(f"✅ Model saved: {Path(args.output_dir).resolve()}/{model_filename}")
    print(f"✅ Features: {len(selector.selected_features)}")
    print(f"✅ Validation metrics: ROC-AUC={val_auc:.3f}, Precision@20%={precision_at_20:.1%}")

    print("\nNext Steps:")
    print("1. Run scanner with production model:")
    print("   python optimized_scanner.py --scan-date 2025-12-01")
    print("2. View buy signals:")
    print("   python view_buy_list.py")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    try:
        start_time = datetime.now()
        main()
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds() / 60
        logger.info(f"\nTotal training time: {duration:.1f} minutes")
    except KeyboardInterrupt:
        logger.warning("\n\nTraining interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\nTraining failed: {e}", exc_info=True)
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)
