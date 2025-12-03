"""
SEPA Model Training Pipeline - Master Script

This script orchestrates the complete model training workflow:
1. Load merged training dataset
2. Temporal train/test splitting (Walk-Forward Validation)
3. Feature selection (correlation filter + SHAP)
4. Hyperparameter optimization (Optuna)
5. Model training with XGBoost
6. Comprehensive evaluation and reporting

Usage:
    # Quick training (default parameters)
    python train_sepa_model.py --dataset data/ml/training_dataset_final.parquet

    # Full optimization (50 trials)
    python train_sepa_model.py \
        --dataset data/ml/training_dataset_final.parquet \
        --optimize \
        --n-trials 50

    # Custom fold configuration
    python train_sepa_model.py \
        --dataset data/ml/training_dataset_final.parquet \
        --purge-gap 60 \
        --correlation 0.95 \
        --top-n 50
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
    """Main training pipeline."""
    parser = argparse.ArgumentParser(
        description="Train SEPA ML models with walk-forward validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick training (default parameters)
  python train_sepa_model.py --dataset data/ml/training_dataset_final.parquet

  # Full optimization with 50 trials
  python train_sepa_model.py \\
      --dataset data/ml/training_dataset_final.parquet \\
      --optimize \\
      --n-trials 50

  # Custom feature selection
  python train_sepa_model.py \\
      --dataset data/ml/training_dataset_final.parquet \\
      --correlation 0.85 \\
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

    parser.add_argument(
        '--eval-dir',
        type=str,
        default='evaluation',
        help='Output directory for evaluation reports (default: evaluation)'
    )

    args = parser.parse_args()

    # Print header
    print("=" * 80)
    print(" SEPA ML MODEL TRAINING PIPELINE")
    print("=" * 80)
    print(f"\nConfiguration:")
    print(f"  Dataset: {args.dataset}")
    print(f"  Purge Gap: {args.purge_gap} days")
    print(f"  Correlation Threshold: {args.correlation}")
    print(f"  Top N Features: {args.top_n if args.top_n else 'All (after correlation filter)'}")
    print(f"  Optimize Hyperparameters: {args.optimize}")
    if args.optimize:
        print(f"  Optuna Trials: {args.n_trials}")
    print(f"  Precision@k: Top {int(args.precision_k*100)}%")
    print(f"  Output Directory: {args.output_dir}")
    print(f"  Evaluation Directory: {args.eval_dir}")
    print("\n" + "=" * 80)

    # Step 1: Prepare training data
    logger.info("\n" + "=" * 80)
    logger.info("STEP 1: DATA PREPARATION")
    logger.info("=" * 80)

    prep_result = prepare_training_data(
        dataset_path=args.dataset,
        purge_gap_days=args.purge_gap,
        correlation_threshold=args.correlation,
        keep_top_n=args.top_n
    )

    df = prep_result['df']
    folds = prep_result['folds']
    splitter = prep_result['splitter']
    selector = prep_result['selector']

    logger.info(f"\nPreparation complete:")
    logger.info(f"  Temporal folds: {len(folds)}")
    logger.info(f"  Selected features: {len(selector.selected_features)}")
    logger.info(f"  Dropped features: {sum(len(v) for v in selector.dropped_features.values())}")

    # Step 2: Train models for each fold
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: MODEL TRAINING")
    logger.info("=" * 80)

    all_fold_results = []
    trained_models = []

    for fold_idx, fold in enumerate(folds):
        fold_type = "PRODUCTION" if fold.get('is_production', False) else "Validation"
        logger.info(f"\n{'='*80}")
        logger.info(f"TRAINING FOLD {fold['fold_id']} ({fold_type})")
        logger.info(f"{'='*80}")

        # Get train/test data
        X_train, X_test, y_train, y_test = splitter.get_fold_data(
            df,
            fold_idx=fold_idx,
            feature_columns=selector.selected_features
        )

        # Apply feature selection
        X_train = selector.transform(X_train)
        X_test = selector.transform(X_test)

        # Get corresponding test DataFrame (for returns)
        test_indices = fold['test_indices']
        df_test = df.loc[test_indices] if len(test_indices) > 0 else None

        # For production folds, use all training data (no train/val split)
        if fold.get('is_production', False):
            logger.info("Production fold: Using ALL training data (no validation split)")
            X_train_split = X_train
            y_train_split = y_train
            X_val_split = None
            y_val_split = None
            logger.info(f"Data: Train={len(X_train_split)} (100%)")
        else:
            # Split train into train/val for validation folds
            train_size = int(len(X_train) * 0.8)
            X_train_split = X_train.iloc[:train_size]
            y_train_split = y_train.iloc[:train_size]
            X_val_split = X_train.iloc[train_size:]
            y_val_split = y_train.iloc[train_size:]
            logger.info(f"Data splits: Train={len(X_train_split)}, Val={len(X_val_split)}, Test={len(X_test)}")

        # Initialize trainer
        trainer = SEPAModelTrainer(precision_k_pct=args.precision_k)

        # Optimize hyperparameters (only on first fold to save time)
        logger.info(f"\nFold {fold_idx}: args.optimize={args.optimize}, fold_idx={fold_idx}")
        if args.optimize and fold_idx == 0:
            logger.info(f"\n{'='*80}")
            logger.info(f"STARTING HYPERPARAMETER OPTIMIZATION - {args.n_trials} TRIALS")
            logger.info(f"{'='*80}")
            logger.info(f"\nOptimizing hyperparameters with Optuna...")
            best_params = trainer.optimize_hyperparameters(
                X_train_split,
                y_train_split,
                X_val_split,
                y_val_split,
                n_trials=args.n_trials
            )
            logger.info(f"\n{'='*80}")
            logger.info(f"OPTIMIZATION COMPLETE - Best precision: {trainer.best_params}")
            logger.info(f"{'='*80}")
        elif fold_idx > 0 and args.optimize:
            # Reuse parameters from first fold
            logger.info("Reusing hyperparameters from Fold 1")
            trainer.best_params = trained_models[0].best_params
        else:
            logger.warning(f"SKIPPING OPTIMIZATION - Using default parameters")

        # Train model
        logger.info("\nTraining final model...")
        model = trainer.train_with_best_params(
            X_train_split,
            y_train_split,
            X_val_split,
            y_val_split
        )

        # Save model
        trainer.save_model(args.output_dir, fold_id=fold['fold_id'])
        trained_models.append(trainer)

        logger.info(f"\nFold {fold['fold_id']} training complete")

    # Step 3: Evaluate all folds
    logger.info("\n" + "=" * 80)
    logger.info("STEP 3: MODEL EVALUATION")
    logger.info("=" * 80)

    evaluator = ModelEvaluator(output_dir=args.eval_dir)

    for fold_idx, fold in enumerate(folds):
        # Skip evaluation for production folds (no test data)
        if fold.get('is_production', False):
            logger.info(f"\nSkipping evaluation for Fold {fold['fold_id']} (PRODUCTION - no test data)")
            continue
            
        logger.info(f"\nEvaluating Fold {fold['fold_id']}...")

        # Get test data
        X_train, X_test, y_train, y_test = splitter.get_fold_data(
            df,
            fold_idx=fold_idx,
            feature_columns=selector.selected_features
        )

        X_test = selector.transform(X_test)
        test_indices = fold['test_indices']
        df_test = df.loc[test_indices]

        # Get trained model
        model = trained_models[fold_idx].model

        # Evaluate
        fold_results = evaluator.evaluate_fold(
            model=model,
            X_test=X_test,
            y_test=y_test,
            df_test=df_test,
            fold_id=fold['fold_id'],
            k_values=[0.1, 0.2, 0.3]
        )

        all_fold_results.append(fold_results)

    # Step 4: Generate comprehensive report
    logger.info("\n" + "=" * 80)
    logger.info("STEP 4: GENERATE REPORT")
    logger.info("=" * 80)

    evaluator.generate_report(
        all_fold_results,
        output_path='evaluation_report.json'
    )

    # Final summary
    print("\n" + "=" * 80)
    print(" TRAINING PIPELINE COMPLETE")
    print("=" * 80)
    
    validation_folds = [f for f in folds if not f.get('is_production', False)]
    production_folds = [f for f in folds if f.get('is_production', False)]
    
    print(f"\n✅ Validation models trained: {len(validation_folds)} folds (with evaluation)")
    print(f"✅ Production models trained: {len(production_folds)} folds (no test data)")
    print(f"✅ Total models: {len(trained_models)}")
    print(f"✅ Models saved: {Path(args.output_dir).resolve()}")
    print(f"✅ Evaluation report: {Path(args.eval_dir).resolve()}")
    print(f"✅ Training log: training.log")

    print("\nNext Steps:")
    print("1. Review evaluation report: evaluation/evaluation_report.json")
    print("2. Check feature importance plots: evaluation/feature_importance_fold_*.png")
    print("3. Review ROC curves: evaluation/roc_curve_fold_*.png")
    print("4. Deploy best model for production scanning")

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
