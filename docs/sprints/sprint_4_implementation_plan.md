# Sprint 4 Final Stretch: Implementation Plan

This plan formalizes the goals discussed for the remainder of Sprint 4. It focuses on finalizing the DuckDB migration, automating MLOps, and ensuring pristine data integrity for backtesting.

## Goal Description
The objective is to complete the migration to DuckDB across all remaining pipelines (EDA, feature selection, model evaluation, and backtesting) while ensuring zero interference with the legacy Python codebase. We will also finalize the Dynamic Universe backfill and completely revamp the model lifecycle (training/evaluation) to eliminate manual bottlenecks.

## User Review Required
> [!IMPORTANT]
> **T+1 vs T Close Execution Logic**: Before we can proceed with model evaluation and backtesting on DuckDB, we must decide whether `trade_simulator.py` (legacy) adapts to DuckDB's realistic `T+1 Open` slippage assumption, or if DuckDB simplifies to `T Close`. 

## Proposed Architecture & Roadmap

### Phase 1: Data Foundation & Universe Preparation
To prepare the final dataset for robust backtesting without lookahead or survivorship bias:
1. **Execution Logic Finalized**: We will strictly use DuckDB's realistic `T+1 Open` assumption for both entry and exit prices. The legacy Python simulator will be updated to match this conservative approach. [No need to modify the old python pipeline, we can leave as reference]
2. **Execute Dynamic Universe Backfill**: 
   - Run the full discovery of active and delisted tickers (`src/universe_backfill.py`).
   - Backfill 20 years of OHLCV and compute point-in-time shares outstanding.
3. **Data Parity & Confidence**: 
   - Execute the feature pipeline with `use_backfill=True`. 
   - Validate that 100% of M01/M03 features and valuation ratios are successfully calculated across the fully backfilled universe.
   - Run complete EDA notebooks to guarantee there are no remaining anomalies or missing mappings.

### Phase 2: MLOps & Model Lifecycle Refinement (Prerequisite)
Establish a robust model registry in DuckDB to eliminate manual workflows.

**2.1 Model Registry Table**
- Create `models` table in DuckDB with:
  - `version_id` (PK): e.g., 'M01_v3'
  - `status_flag`: 'prod' | 'test' | 'archived'
  - `specs_json`: Hyperparameters, feature list, training config (JSON type)
  - `feature_version`: e.g., 'v3.0'
  - `training_date`, `dataset_rows`, `rmse`, `mae`, `r2`
  - `artifacts_path`: Filesystem path to plots/reports
  
**2.2 Dynamic Feature Loading**
- Refactor training/evaluation scripts to load features from `models.specs_json`
- Remove hardcoded feature lists from `src/feature_config.py`
- Add validation: fail fast if requested features missing from `daily_features`

**2.3 Enhanced Evaluation Pipeline**
- Minimum viable metrics: RMSE, MAE, R², Spearman correlation, top 10 feature importance
- Store lightweight artifacts (metrics JSON, feature importance) in `models` table
- Store plots/reports in `models/artifacts/{version_id}/`
- Defer regime-specific analysis to Sprint 5

**2.4 Automated Model Registration**
- Create `scripts/register_model.py` to programmatically insert new versions
- Auto-populate `specs_json` from training hyperparameters

### Phase 3: DuckDB Migration (Clean Architecture)
To ensure we do not interfere with the legacy Python code, we will implement the Dependency Inversion Principle.
- **Data Access Layer**: Create a `DuckDBDataLoader` that implements the exact same interface expected by the models, but pulls exclusively from `v_d2_training` and `v_d1_candidates`. 
- **Backtesting & EDA**: Point the backtester and feature EDA pipelines to use these DuckDB interfaces. The old Python file-based loaders will remain entirely unmodified for legacy comparison.

### Phase 4: Dashboard Resilience
- Update the UI (Streamlit/Dash) to query the SQL views directly instead of the legacy parquet files.

## Verification Plan

### Automated Tests
- Run existing integration tests to ensure the new MLOps runner does not break existing model contracts.
- Run `pytest` on the completed Dynamic Universe engine to ensure SQL backfills execute without dropping tickers.

### Manual Verification
- **Data Parity**: Manually compare the top 50 trades driven by the new DuckDB `v_d1_candidates` against the legacy Python results to ensure the T+1/T Close fix is perfectly aligned.
- **MLOps Workflow**: Perform a manual end-to-end test of `model_runner.py`, explicitly verifying that a new model version is logged automatically with its exact feature list without human intervention.
- **Dashboard Load**: Manually open the dashboard locally and verify that equity curves and heatmaps load correctly from the `.duckdb` backend.
