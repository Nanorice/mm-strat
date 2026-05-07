# Plan: Refactor Training Script for Production & Dynamic Features

**Goal:** Modernize `scripts/train_mfe_classifier.py` so it no longer relies on hardcoded features, integrates natively with DuckDB's feature catalog, and supports a proper "production" training data split (training on all available recent data without holding out a massive chronological test set).

## Background Context
- `fs_m01_prototype` (the 99-feature set derived from EDA pruning) has already been defined in `scripts/populate_feature_catalog.py`.
- We intend to train the model on the full 2003-2026 dataset so it learns from the most recent market regime.

## Proposed Implementation Steps

### 1. Seed the Feature Catalog
- The `fs_m01_prototype` feature set must be seeded into the database before training.
- **Action:** Run `python scripts/populate_feature_catalog.py` to insert the feature set into `market_data.duckdb`.

### 2. Refactor `scripts/train_mfe_classifier.py`
- **Dynamic Feature Fetching**: 
  - Remove the hardcoded `FEATURE_GROUPS` dictionary.
  - Implement a helper function `get_feature_set(db_path, feature_set_id)` that queries `model_feature_sets` from DuckDB.
- **Argparse Integration**: Add dynamic CLI arguments:
  - `--feature-set` (default: `fs_m01_prototype`)
  - `--model-name` (default: `m01_prototype`)
  - `--min-date` (default: `2003-01-01`)
  - `--prod` (Boolean flag)
- **Production Mode Logic (`--prod`)**:
  - **Standard Testing (Default):** Chronological split of 60% Train, 20% Validation, 20% Test.
  - **Production Enabled:** Chronological split of 85% Train, 15% Validation (for XGBoost early stopping), and 0% Test. 
  - *Note:* In `--prod` mode, the script will pass the Validation set to `ClassificationEvaluator` as the "Test" set, just to ensure all the standard performance plots (Confusion Matrix, ROC, etc.) are still cleanly generated without crashing.

## Final Workflow for Deployment
Once this plan is implemented in the next session, the workflow to deploy the new model will be:

1. `python scripts/populate_feature_catalog.py`
2. `python scripts/train_mfe_classifier.py --feature-set fs_m01_prototype --model-name m01_prototype_2003_2026 --min-date 2003-01-01 --prod`
3. Enter Python REPL / Jupyter to deploy:
   ```python
   from src.model_registry import ModelRegistry
   ModelRegistry().set_prod('m01_prototype_2003_2026_...') # Use exact version_id output by script
   ```
