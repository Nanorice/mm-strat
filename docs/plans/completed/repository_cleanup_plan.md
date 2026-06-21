# Repository Cleanup & Management Plan

Based on the `docs/manual_for_me.md` and a dependency analysis of your `src/`, `scripts/`, and `tools/` directories, the repository has accumulated a significant number of legacy files that are no longer part of the current active framework. 

The current framework heavily relies on the DuckDB-based data engines (`src/data_engine.py`, `src/feature_pipeline.py`, etc.), the orchestrator (`run_daily_pipeline.py`), and the new evaluation/backtest structures.

## Proposed Changes

The following files are disjoint from the main entrypoints and are relics of previous pipeline iterations (e.g., pre-DuckDB, pandas-heavy data merges, old simulation engines).

### 1. Root & Orchestration (Legacy)
These were replaced by `scripts/run_daily_pipeline.py` and the `managers/` module.
- `daily_scanner_duckdb.py`
- `data_curator_duckdb.py`

### 2. Legacy Data Processing & Feature Engineering
Before `src/feature_pipeline.py` unified T2/T3 features, the feature pipeline was scattered across these files.
- `src/features.py`
- `src/features_stub.py`
- `src/feature_config.py`
- `src/feature_preprocessor.py`
- `src/feature_rehydrator.py`
- `src/alpha_factors.py`
- `src/cross_sectional_features.py`
- `src/indicators.py`
- `src/dataset_merger.py`
- `src/dataset_rehydrator.py`
- `src/fundamental_merger.py`
- `src/fundamental_processor.py`
- `src/fundamental_column_mapping.py`
- `src/vectorized_screening.py`
- `src/triple_barrier_labeler.py`

### 3. Legacy Database Managers
Replaced by native DuckDB execution in the data engines and `managers/view_manager.py`.
- `src/database.py`
- `src/database_duckdb.py`
- `src/buy_list_manager.py`

### 4. Legacy Simulation / Backtesting
Replaced by the `src/backtest/` BackTrader framework.
- `src/backtester.py`
- `src/trade_simulator.py`
- `src/trade_simulator_fast.py`
- `src/strategy.py`
- `src/trading_config.py`
- `src/ticker_filter.py`
- `src/temporal_validator.py`

### 5. Legacy ML / Evaluation
Replaced by `src/evaluation/classification_evaluator.py`, `train_mfe_classifier.py`, and `model_registry.py`.
- `src/evaluate_model.py`
- `src/ml_scorer.py`
- `src/model_preparation.py`
- `src/train_model.py`
- `src/reporting.py`
- `src/dashboard_reports.py`
- `src/evaluation/base_evaluator.py`
- `src/evaluation/classification_report.py`
- `src/evaluation/errors.py`
- `src/evaluation/feature_analyzer.py`
- `src/evaluation/feature_screener.py`
- `src/evaluation/m01_evaluator.py`
- `src/evaluation/m03_grid_search.py`
- `src/evaluation/metrics.py`
- `src/evaluation/plotting.py`
- `src/evaluation/ranking.py`
- `src/evaluation/reports.py`
- `src/evaluation/targets.py`

*(Note: `classification_evaluator.py`, `leakage_guard.py`, `m03_evaluator.py`, `m03_ground_truth.py` will be kept as they are still active)*

---

## Recommended Repository Management Method

Given the highly experimental and evolving nature of a quant framework, I recommend the following best practices for this repository going forward:

1. **Delete, Don't Hoard**: Trust Git. If code is deprecated, delete it rather than commenting it out or leaving it "just in case". If you ever need to reference how you built the old `trade_simulator.py`, you can easily retrieve it from Git history.
   *Alternative*: Create an `archive/` folder at the root and move old code there. This keeps it out of the main `src/` execution path but allows for easy text-searching in PyCharm without navigating Git history.
2. **Namespace Segregation**: Continue your current practice of moving logical units into their own folders (e.g., `src/backtest/`, `src/evaluation/`, `src/managers/`). As your framework grows, consider moving API/data ingestors into `src/ingestion/` to further declutter the root `src/` folder.
3. **Use the `docs/manual_for_me.md` as the Source of Truth**: When you add a new script or pipeline phase, document it here immediately. If a file isn't in the manual, it should be considered a candidate for deletion. 
4. **Regular Dependency Audits**: Periodically run a dependency graph script to highlight isolated files and keep the `src/` directory clean.
