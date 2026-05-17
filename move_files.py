import os
import shutil
from pathlib import Path

# Base archive directory
ARCHIVE_BASE = Path("archive/archive May26")

# Files to move
files_to_move = [
    # Pre-requisite Cleanup
    "src/pipeline/data_pipeline.py",
    "src/universe_engine.py",
    "tools/compare_outputs.py",
    "scripts/benchmark_training_cache.py",
    "scripts/run_m01_ablation_study.py",

    # Root directory
    "daily_scanner_duckdb.py",
    "data_curator_duckdb.py",

    # src/
    "src/features.py",
    "src/features_stub.py",
    "src/feature_config.py",
    "src/feature_preprocessor.py",
    "src/feature_rehydrator.py",
    "src/alpha_factors.py",
    "src/cross_sectional_features.py",
    "src/indicators.py",
    "src/dataset_merger.py",
    "src/dataset_rehydrator.py",
    "src/fundamental_merger.py",
    "src/fundamental_processor.py",
    "src/fundamental_column_mapping.py",
    "src/vectorized_screening.py",
    "src/triple_barrier_labeler.py",
    "src/database.py",
    "src/database_duckdb.py",
    "src/buy_list_manager.py",
    "src/backtester.py",
    "src/trade_simulator.py",
    "src/trade_simulator_fast.py",
    "src/strategy.py",
    "src/trading_config.py",
    "src/ticker_filter.py",
    "src/temporal_validator.py",
    "src/evaluate_model.py",
    "src/ml_scorer.py",
    "src/model_preparation.py",
    "src/train_model.py",
    "src/reporting.py",
    "src/dashboard_reports.py",

    # src/evaluation/
    "src/evaluation/errors.py",
    "src/evaluation/feature_analyzer.py",
    "src/evaluation/feature_screener.py",
    "src/evaluation/m01_evaluator.py",
    "src/evaluation/m03_grid_search.py",
    "src/evaluation/metrics.py",
    "src/evaluation/ranking.py",
    "src/evaluation/reports.py",
    "src/evaluation/targets.py",
]

moved = 0
failed = 0

for file_path_str in files_to_move:
    src_path = Path(file_path_str)
    
    if src_path.exists():
        # Determine destination
        if src_path.parent == Path('.'):
            # Put root files in a 'root' subfolder or just keep them at the base of archive?
            # The prompt said "such as src or scripts to track where they originally come from"
            # We'll put root files in 'root' to keep the archive root clean
            dest_dir = ARCHIVE_BASE / "root"
        else:
            dest_dir = ARCHIVE_BASE / src_path.parent
            
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / src_path.name
        
        try:
            shutil.move(str(src_path), str(dest_path))
            print(f"Moved {src_path} -> {dest_path}")
            moved += 1
        except Exception as e:
            print(f"Failed to move {src_path}: {e}")
            failed += 1
    else:
        print(f"File not found: {src_path}")
        failed += 1

print(f"\nSummary: Moved {moved} files, Failed {failed} files.")
