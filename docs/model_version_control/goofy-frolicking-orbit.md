# Plan: Feature Catalog & Model Reproducibility System

## Context

The project has no way to reproduce past models. Feature formulas are hardcoded in SQL strings, the training script defines its own feature list locally (disconnected from `feature_config.py`), and the model registry tracks regression metrics for what is actually a 4-class classifier. The `v_d2_training` view computes ~23 log-transform columns that no model uses.

**Goal**: Given any model `version_id`, we can reconstruct exactly which features were used and know those feature names map to immutable, documented formulas. The current M01_baseline becomes v0.1.

**Principle**: Feature name = frozen formula. If a calculation changes, it becomes a new feature name.

**Non-negotiable constraint**: This plan must not alter any behavior of the current M01_baseline model. v0.1 is a snapshot of what exists today — register it as-is, including `atr_delta` in FEATURE_GROUPS even though it is currently missing from the trained artifact. Do not "fix" the model while registering it.

---

## Phase 1: New DuckDB Tables (model_registry.py)

### 1a. `feature_catalog` table

Add `_create_feature_catalog_tables()` in `src/model_registry.py`, called from `__init__` (alongside existing `_create_models_table()`):

```sql
CREATE TABLE IF NOT EXISTS feature_catalog (
    feature_name      VARCHAR NOT NULL,
    display_name      VARCHAR,
    description       VARCHAR,
    formula_summary   VARCHAR,           -- Human-readable, NOT executable SQL
    source_layer      VARCHAR NOT NULL,  -- t1_sql | t1b_ema | t1c_alpha_xs | t1d_rank |
                                         -- t2_sql | t2b_alpha_ts | d1_view | d2_view | m03_regime
    source_table      VARCHAR,           -- table/view that materializes this column
    data_type         VARCHAR DEFAULT 'DOUBLE',
    is_categorical    BOOLEAN DEFAULT FALSE,
    version_introduced VARCHAR NOT NULL DEFAULT 'v3.1',
    version_retired    VARCHAR,          -- NULL = active
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (feature_name, version_introduced)
);
```

### 1b. `model_feature_sets` table

```sql
CREATE TABLE IF NOT EXISTS model_feature_sets (
    feature_set_id  VARCHAR NOT NULL,    -- e.g., 'fs_m01_baseline_v0.1'
    feature_name    VARCHAR NOT NULL,    -- lowercase, matches feature_catalog
    feature_group   VARCHAR,             -- e.g., 'Moving_Averages'
    ordinal         INTEGER,             -- position in feature vector
    PRIMARY KEY (feature_set_id, feature_name)
);
```

### 1c. Update `models` table schema

Migrate from regression to classification metrics. Add reproducibility columns. **Keep existing regression columns** (`rmse`, `mae`, `r2`, `spearman_corr`) — do not drop.

In `_create_models_table()`:
- Add: `accuracy DOUBLE`, `weighted_f1 DOUBLE`, `macro_f1 DOUBLE`
- Add: `feature_set_id VARCHAR`, `git_sha VARCHAR`, `model_type VARCHAR DEFAULT 'classifier'`

Create `scripts/migrate_model_registry.py` for existing DBs (ALTER TABLE ADD only — no drops).

### 1d. Update `src/model_registry.py`

- `register_version()`: Add `feature_set_id`, `git_sha` params. Add `accuracy`, `weighted_f1`, `macro_f1` params (regression params remain for backward compat, just unused going forward).
- `update_metrics()`: Add classification metric params alongside existing ones.
- New: `register_feature_set(feature_set_id, features, feature_groups)` — INSERT rows into `model_feature_sets`.
- New: `get_reproducibility_info(version_id)` — JOIN models → model_feature_sets → feature_catalog, return full feature definitions + hyperparams + git SHA.
- `list_versions()`: Update SELECT to include new metric columns.

**Files**: `src/model_registry.py`, new `scripts/migrate_model_registry.py`

---

## Phase 2: Remove Log Transforms from v_d2_training

Delete the `-- Log transforms` block (~lines 605-665) from `src/managers/view_manager.py` (approximately 23 SIGN/LN expressions).

The SELECT ends after the stop-loss columns:
```sql
    ...
    CASE WHEN sl.sl_exit_price IS NOT NULL AND sl.entry_price > 0
        THEN (sl.sl_exit_price / sl.entry_price - 1.0) * 100.0
    END AS sl_pct
FROM v_d2_features f
LEFT JOIN outcomes o ON f.trade_id = o.trade_id
LEFT JOIN sl_exits sl ON f.trade_id = sl.trade_id
```

Update the print statement (line ~672) to remove "log transforms" wording.

After view recreation, `d2_training_cache` must be refreshed to drop the stale log columns.

**Consumers verified safe**: Training script does `SELECT *` then filters to `FEATURE_GROUPS` — no `log_*` features appear in any `FEATURE_GROUPS` definition. `universe_scorer.py` calls `get_model_features('M01')` which returns non-log features. No other active code path uses `log_*` columns from this view.

**File**: `src/managers/view_manager.py`

---

## Phase 3: Populate Feature Catalog (v0.1 Baseline)

Create `scripts/populate_feature_catalog.py`:

1. Read `models/m01_baseline/v1/metadata.json` to get `valid_features` (105 features) and performance metrics. **Do not hardcode metrics** — read `accuracy`, `weighted_f1`, `macro_f1` directly from the JSON.

2. Define all 105 features as dicts with:
   - `feature_name` (lowercase)
   - `description` (what it measures)
   - `formula_summary` (human-readable formula string, e.g., `"ATR(14) / close * 100"`)
   - `source_layer` mapping per group:
     - Moving_Averages → `t2_sql`
     - Momentum_RS → `t2_sql` / `t1d_rank`
     - Core_Volume → `t2_sql`
     - Volatility_Ranges → `t2_sql`
     - Technical_Oscillators → `t2_sql`
     - Fundamentals → `d2_view`
     - Fast_Alphas → `t1c_alpha_xs` / `t2b_alpha_ts`
     - M03_Regime → `m03_regime`
   - `source_table`: `t3_sepa_features` for stored features, `v_d2_features` for fundamentals
   - `is_categorical`: True for `sector`, `industry`

3. INSERT all 105 features into `feature_catalog` with `version_introduced = 'v3.1'`.

4. Also insert the ~23 retired log features with `version_retired = 'v3.2'` for historical documentation.

5. Create feature set `fs_m01_baseline_v0.1` in `model_feature_sets` with the exact 105 features from metadata.json, preserving group assignments and ordinal positions. Register all features from `FEATURE_GROUPS` as declared in the training script — including `atr_delta` — even if it was absent from the trained artifact. The feature set records intent, not post-hoc filtering.

6. Register `M01_baseline_v0.1` in the `models` table using metrics read from metadata.json:
   - `feature_set_id = 'fs_m01_baseline_v0.1'`
   - `feature_version = 'v3.1'`
   - `status_flag = 'prod'`
   - `git_sha` = HEAD at registration time
   - `specs` from existing metadata.json

**File**: new `scripts/populate_feature_catalog.py`

---

## Phase 4: Training Script Integration

Modify `scripts/train_mfe_classifier.py`:

1. After training + evaluation, register feature set:
   ```python
   feature_set_id = f'fs_{version_id}'
   registry.register_feature_set(feature_set_id, valid_features, FEATURE_GROUPS)
   ```

2. Capture git SHA:
   ```python
   import subprocess
   git_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip()
   ```

3. Update `register_version()` call to pass `feature_set_id`, `git_sha`, and classification metrics.

**No changes to `FEATURE_GROUPS`** — register the current state as-is.

**File**: `scripts/train_mfe_classifier.py`

---

## Phase 5: Clean Up feature_config.py

### Delete stale model-specific feature lists (~300 lines):
- `M01_Bench_FEATURES` (line 262)
- `M01_V3_FEATURES` (line 289)
- `M01_FEATURES` (line 365) — has log features, never used by training
- `M01_NO_INDUSTRY` (line 444)
- `M01_V2_FEATURES` (line 446)
- `M01_3BAR_FEATURES`, `M01_3BAR_VELOCITY_ONLY` (line 508+)
- `M02_FEATURES` (line 571)
- `M01_CANDIDATE_FEATURES` (line 629)
- All `M01_3BAR_FEATURES_V2` aliases

### Keep useful shared constants (actively imported):
- `FEATURES_TO_LAG`, `DELTA_FEATURES` — used by `features.py`, `features_stub.py`
- `LEAKAGE_FEATURES` — used by `feature_screener.py`
- `CATEGORICAL_FEATURES` — used by `feature_preprocessor.py`, `feature_screener.py`
- `FEATURE_EXCLUSION_LIST` and constituent lists — used by `feature_screener.py`
- `TECHNICAL_FEATURES`, `ALPHA_FEATURES`, `FUNDAMENTAL_FEATURES`, etc. — useful for EDA, add comment that these describe the feature universe, not any model's selection

### Replace `get_model_features()`:
Query `model_feature_sets` table via DuckDB instead of returning stale Python constants.
If the table doesn't exist or is empty, raise `RuntimeError("Run scripts/populate_feature_catalog.py first — model_feature_sets table is not populated.")`.

### Fix `universe_scorer.py`:
`src/backtest/universe_scorer.py` line 122 calls `get_model_features('M01')` — currently gets stale 77-feature list with log features. After `get_model_features()` queries DuckDB, this will return the correct 105 features from the prod model's feature set.

**Files**: `src/feature_config.py`, `src/backtest/universe_scorer.py`

---

## Phase 6: Verification

### Manual verification:
1. Run `scripts/migrate_model_registry.py` — confirm models table has new columns
2. Run `scripts/populate_feature_catalog.py` — confirm 105 features in catalog + feature set
3. Recreate views (`ViewManager.create_all()`) — confirm v_d2_training has no log columns
4. Refresh `d2_training_cache` — confirm cache matches view
5. Query `get_reproducibility_info('M01_baseline_v0.1')` — confirm returns full feature definitions
6. Run training script — confirm it registers feature_set_id + git_sha

### Automated test:
Create `tests/test_feature_catalog.py`:
- `test_v01_features_match_metadata` — catalog features == metadata.json valid_features
- `test_feature_immutability` — PK violation on duplicate feature_name + version_introduced
- `test_catalog_completeness` — every feature in model_feature_sets has a catalog entry
- `test_no_log_features_in_training_view` — v_d2_training columns contain no log_ prefixed names
- `test_get_model_features_from_db` — `get_model_features('M01')` returns 105 features from DuckDB

---

## Execution Order

```
Phase 1 (tables + registry)  ──┐
Phase 2 (remove log transforms) ├── can run in parallel
                                │
Phase 3 (populate catalog)  ────┘ depends on Phase 1
Phase 4 (training script)   ──── depends on Phase 1
Phase 5 (cleanup config)    ──── depends on Phase 3 (catalog must exist before get_model_features queries it)
Phase 6 (verification)      ──── depends on all above
```

## Files Changed Summary

| File | Action |
|------|--------|
| `src/model_registry.py` | Add catalog tables, new methods, classification metrics, feature_set_id + git_sha |
| `src/managers/view_manager.py` | Remove log transforms from v_d2_training |
| `src/feature_config.py` | Delete ~300 lines stale lists, update get_model_features() |
| `src/backtest/universe_scorer.py` | Fix stale get_model_features call |
| `scripts/train_mfe_classifier.py` | Register feature set + git_sha |
| `scripts/populate_feature_catalog.py` | **NEW** — seed catalog + register v0.1 |
| `scripts/migrate_model_registry.py` | **NEW** — ALTER TABLE ADD migration (no drops) |
| `tests/test_feature_catalog.py` | **NEW** — reproducibility tests |
