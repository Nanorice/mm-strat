# Repository Cleanup Plan

We will systematically clean up the repository by moving legacy scripts and modules identified in `docs/plans/repository_cleanup_plan.md` to `archive/archive May26/`. To ensure we don't break the active pipeline (as defined in `comprehensive_methodology.md`), I have run a dependency check across the entire workspace.

## User Review Required

> [!WARNING]
> While checking for dependencies across the active pipeline, I discovered several files marked for deletion in the cleanup plan that are still actively imported by the current codebase.

1. **`src/evaluation/base_evaluator.py`, `src/evaluation/plotting.py`, and `src/evaluation/classification_report.py`**:
These files are listed as "Legacy ML / Evaluation" in the cleanup plan. However, they are actively imported and used by `src/evaluation/classification_evaluator.py`, which is the core evaluator for the current `train_mfe_classifier.py` script. 
*Recommendation*: **Keep** these three files in `src/evaluation/` and exclude them from archiving.

2. **`src/feature_config.py`**:
Listed under "Legacy Data Processing". However, the `get_model_features()` function inside this file is used by the active `src/backtest/universe_scorer.py` module to load feature definitions.
*Recommendation*: Move the `get_model_features()` function to `src/utils.py`, update the import in `universe_scorer.py`, and then archive `src/feature_config.py`.

3. **`src/evaluation/metrics.py`**:
Listed under "Legacy ML / Evaluation". It is imported by `src/evaluation/m01_evaluator.py` and `notebooks/model_proto.py`. Since `m01_evaluator.py` itself is legacy, we can safely archive both `m01_evaluator.py` and `metrics.py`.

## Proposed Changes

### Root directory
- [DELETE] `daily_scanner_duckdb.py` -> moving to `archive/archive May26/root/`
- [DELETE] `data_curator_duckdb.py` -> moving to `archive/archive May26/root/`

### src/
- [DELETE] `src/features.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/features_stub.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/feature_config.py` -> moving to `archive/archive May26/src/` (after refactoring `get_model_features` to `utils.py`)
- [DELETE] `src/feature_preprocessor.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/feature_rehydrator.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/alpha_factors.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/cross_sectional_features.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/indicators.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/dataset_merger.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/dataset_rehydrator.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/fundamental_merger.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/fundamental_processor.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/fundamental_column_mapping.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/vectorized_screening.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/triple_barrier_labeler.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/database.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/database_duckdb.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/buy_list_manager.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/backtester.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/trade_simulator.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/trade_simulator_fast.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/strategy.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/trading_config.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/ticker_filter.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/temporal_validator.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/evaluate_model.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/ml_scorer.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/model_preparation.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/train_model.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/reporting.py` -> moving to `archive/archive May26/src/`
- [DELETE] `src/dashboard_reports.py` -> moving to `archive/archive May26/src/`

### src/evaluation/
- [DELETE] `src/evaluation/errors.py` -> moving to `archive/archive May26/src/evaluation/`
- [DELETE] `src/evaluation/feature_analyzer.py` -> moving to `archive/archive May26/src/evaluation/`
- [DELETE] `src/evaluation/feature_screener.py` -> moving to `archive/archive May26/src/evaluation/`
- [DELETE] `src/evaluation/m01_evaluator.py` -> moving to `archive/archive May26/src/evaluation/`
- [DELETE] `src/evaluation/m03_grid_search.py` -> moving to `archive/archive May26/src/evaluation/`
- [DELETE] `src/evaluation/metrics.py` -> moving to `archive/archive May26/src/evaluation/`
- [DELETE] `src/evaluation/ranking.py` -> moving to `archive/archive May26/src/evaluation/`
- [DELETE] `src/evaluation/reports.py` -> moving to `archive/archive May26/src/evaluation/`
- [DELETE] `src/evaluation/targets.py` -> moving to `archive/archive May26/src/evaluation/`

### Refactoring
- [MODIFY] `src/utils.py` (add `get_model_features` from `feature_config.py`)
- [MODIFY] `src/backtest/universe_scorer.py` (update import to use `src.utils`)

## Verification Plan

- Run a dry-run check of the active pipeline (e.g., `python scripts/run_daily_pipeline.py --help` or `--dry-run`) to make sure everything imports successfully without `ImportError`.
- Ensure all archived files are properly structured inside `archive/archive May26/`.
