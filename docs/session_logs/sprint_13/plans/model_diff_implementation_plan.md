# Model Diff Tool Implementation Plan

A CLI tool to compare two XGBoost model versions side-by-side: features, hyperparameters, training config, metrics, feature importance rank shifts, and confidence calibration.

---

## Goal

`model_diff` bridges a major gap in the ML pipeline — when iterating models, it is currently impossible to quickly see what actually changed between two versions. This makes debugging backtests slow and model validation error-prone.

---

## Prerequisites (Must Complete Before Building the Tool)

These are structural fixes to the data layer. The diff tool is only as good as the data it reads.

### P1 — Fix artifacts path in `ModelRegistry.register_version()`

**Problem:** `train_mfe_classifier.py` saves model files to `models/{model_name}/{model_version}/` (line 316). `ModelRegistry.register_version()` ignores this and sets `artifacts_path = models/artifacts/{version_id}/` automatically — a directory nothing ever writes to. The registry lies about where the artifacts are.

**Fix (one line in `train_mfe_classifier.py`):** Pass `artifacts_path=model_dir` explicitly into `register_version()` instead of letting the registry compute it. Also add `artifacts_path` as an optional parameter to `register_version()` in `model_registry.py` — when provided, use it directly; when absent, fall back to the current auto-computed path.

```python
# Before (registry invents a path nothing writes to):
registry.register_version(version_id=version_id, ...)

# After (registry records where files actually are):
registry.register_version(version_id=version_id, artifacts_path=model_dir, ...)
```

**Why this approach over moving files:** The `models/{model_name}/{model_version}/` layout is intentional — human-browsable, and the evaluator writes plots + `results.json` into subfolders there. Moving everything to `models/artifacts/` would be a larger disruption. The root problem is the registry not knowing the real path, not the path itself.

**Why this matters:** `model_diff.py` and any future tool resolves artifact paths via `registry.get_artifacts_path(version_id)`. If that returns a wrong path, every caller breaks. The filesystem-path fallback for unregistered models is unaffected.

### P2 — Add missing fields to `specs_json` in `train_mfe_classifier.py`

**Problem:** `specs_json` currently stores XGBoost params + training config, but omits:
- `num_boost_round` (hardcoded 100) and `early_stopping_rounds` (hardcoded 20) — actual best iteration is only in the model binary
- `label_thresholds`: the MFE bin boundaries (0, 2, 10, 30, inf) that define classes — never recorded, so historical class definitions are not auditable
- `class_weights`: whether `balanced` weighting was used and the computed per-class weight values

**Fix:** Extend the `specs_json` block in `register_version()` call to include:
```python
'training_config': {
    ...existing fields...,
    'num_boost_round': 100,
    'early_stopping_rounds': 20,
    'label_thresholds': [0, 2, 10, 30],   # upper bounds per class
    'class_weighting': 'balanced',
    'class_weights': dict(zip(classes.tolist(), weights.tolist())),
}
```

### P3 — Add confidence calibration to `ClassificationEvaluator`

**Problem:** No existing metric answers: "When the model predicts Home Run with ≥80% confidence, what does the actual `mfe_pct` distribution look like?" ROC/PR AUC don't answer this. This is needed to determine if current class boundaries are appropriate or if a new class is warranted.

**Fix:** In `ClassificationEvaluator.evaluate()`, after computing `y_proba`, add a calibration bucket analysis:
- For each class, group test samples by predicted probability bucket: `[0.5, 0.6)`, `[0.6, 0.7)`, `[0.7, 0.8)`, `[0.8, 0.9)`, `[0.9, 1.0]`
- For each bucket: count samples, mean/median/p25/p75 actual `mfe_pct`, and the proportion that fell into each true class
- Store result in `results.json` under `"confidence_calibration"` key

This answers the question: if 60% confident → actual return is 100% on average, that's a strong signal the class boundary is too coarse. Also reveals if high-confidence predictions are actually well-calibrated.

**Note:** `mfe_pct` (the raw return) must be passed into `evaluate()` alongside `y_test` to enable this. Currently it is not passed.

### P4 — Add `model_name` and `model_version` as explicit columns in `models` table

**Problem:** These are embedded inside `version_id` (e.g. `m01_prototype_20260506_160054`) but not queryable independently. The unregistered fallback path resolution needs them explicitly.

**Fix:** Add `model_name VARCHAR` and `model_version VARCHAR` columns to the `models` table schema in `ModelRegistry._create_feature_catalog_tables()`, and populate them in `register_version()`. These become the explicit namespace for resolving filesystem paths.

---

## Model Identifier Strategy

The tool accepts two formats for `--model-a` and `--model-b`:

1. **DuckDB `version_id`** (primary): e.g. `m01_prototype_20260506_160054` — resolves `artifacts_path` via `ModelRegistry.get_artifacts_path(version_id)`
2. **Filesystem path** (fallback for unregistered models): e.g. `models/m01_baseline_2021_2025` — reads `metadata.json` and `evaluation/results.json` directly from the path. Hyperparameters and feature sets not in DuckDB will show as `N/A`.

Resolution order: try DuckDB first; if not found, treat as a filesystem path.

---

## Save Location

- **Default**: stdout only (Rich console output)
- **`--save` flag**: writes machine-readable output to `models/artifacts/{version_b}/diffs/vs_{version_a}.json`
- **`--save-text` flag**: writes the rendered Rich table output as plain text to the same directory

---

## Dependencies

| Dependency | Source | Notes |
|---|---|---|
| `src/model_registry.py` | DuckDB reads | `get_model_specs()`, `get_artifacts_path()`, `list_versions()` |
| `data/market_data.duckdb` | `models`, `model_feature_sets` tables | Primary source for hyperparams + feature sets |
| `models/artifacts/{version_id}/metadata.json` | Filesystem | Train/val/test splits, temporal validation, leakage check, label thresholds |
| `models/artifacts/{version_id}/evaluation/results.json` | Filesystem | Per-class metrics, feature importance, SHAP, brier score, calibration (after P3) |
| `rich` | Already installed | Console table rendering |
| `duckdb` | Already installed | Registry reads |

No new package installs required.

---

## Proposed Changes

### `scripts/model_diff.py` — [NEW]

A CLI script that accepts two model identifiers and renders a structured diff.

#### Section 1 — Training Config

Compares `metadata.json` fields side-by-side:

| Field | Model A | Model B | Changed? |
|---|---|---|---|
| split_mode | standard_60_20_20 | no_holdout_85_15_0 | ✅ |
| min_date | 2003-01-01 | 2021-01-01 | ✅ |
| feature_version | v3.1 | v3.1 | — |
| train_samples | 1,052 | 2,134 | ✅ |
| val_samples | 350 | 376 | ✅ |
| test_samples | 352 | 0 | ✅ |
| label_thresholds | [0, 2, 10, 30] | [0, 2, 10, 30] | — |
| class_weighting | balanced | balanced | — |
| temporal_validation | all_valid=True | all_valid=True | — |

#### Section 2 — Hyperparameter Diff

Source: `specs_json.hyperparameters` from DuckDB. Only changed params are shown; unchanged params are listed but dimmed.

| Param | Model A | Model B | Delta |
|---|---|---|---|
| max_depth | 4 | 6 | +2 ✅ |
| learning_rate | 0.05 | 0.03 | -0.02 ✅ |
| num_boost_round | 100 | 200 | +100 ✅ |
| subsample | 0.8 | 0.8 | — |
| colsample_bytree | 0.8 | 0.7 | -0.1 ✅ |

#### Section 3 — Feature Set Diff

Source: `model_feature_sets` table (DuckDB) or `metadata.json` fallback.

```
Features in A only (removed in B):  3
  - alpha004
  - dist_from_52w_high
  - low_52w_delta

Features in B only (added in B):  5
  - breakout_gap_pct
  - vol_expansion_ratio
  - ...

Shared features:  102 / 105
```

#### Section 4 — Aggregate Metrics

Source: `models` table (DuckDB) or `results.json`. Shows absolute values and delta. Metric label adapts to split mode (Val vs Test).

| Metric | Model A | Model B | Delta |
|---|---|---|---|
| Accuracy (Test) | 0.6705 | 0.6923 | +0.022 ✅ |
| Weighted F1 | 0.5820 | 0.6012 | +0.019 ✅ |
| Macro F1 | 0.2475 | 0.2810 | +0.034 ✅ |
| Mean Brier Score | 0.1210 | 0.1150 | -0.006 ✅ |

#### Section 5 — Per-Class Metrics

Source: `classification_report` in `results.json`. Generalises to any number of classes — reads class names dynamically from the JSON.

| Class | A Prec | B Prec | Δ | A Recall | B Recall | Δ | A F1 | B F1 | Δ | A ROC AUC | B ROC AUC | Δ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Noise (0-2%) | 0.00 | 0.12 | +0.12 | 0.00 | 0.20 | +0.20 | 0.00 | 0.15 | +0.15 | 0.685 | 0.701 | +0.016 |
| ... | | | | | | | | | | | | |
| Home Run (>30%) | 0.715 | 0.698 | -0.017 | 0.966 | 0.941 | -0.025 | 0.822 | 0.804 | -0.018 | 0.719 | 0.732 | +0.013 |

#### Section 6 — Feature Importance Rank Shift

Source: `feature_importance` (gain) in `results.json`. No model loading needed. Shows top 15 features by average rank between A and B, with rank movement annotated.

```
Feature Importance Rank Shift (by XGBoost Gain, top 15 avg rank)

  Feature                  Rank A   Rank B   Move
  dist_from_52w_low           1        1      —
  rs_delta                    3        2      ▲1
  price_vs_sma_200            4        3      ▲1
  alpha049                    9       15      ▼6
  breakout_gap_pct          N/A        7    [NEW]
  alpha004                   98      N/A  [REMOVED]
```

Also shows top-5 SHAP features per class for A vs B side-by-side.

#### Section 7 — Confidence Calibration (requires P3)

Source: `confidence_calibration` in `results.json`. Answers: for high-confidence predictions, what is the actual return distribution?

```
Home Run (>30%) — Confidence Calibration

  Prob Bucket   N (A)  Mean mfe% (A)  P75 mfe% (A)  |  N (B)  Mean mfe% (B)  P75 mfe% (B)
  [0.5, 0.6)      45       38.2%          61.4%      |    52       35.1%          58.2%
  [0.6, 0.7)      31       52.1%          89.3%      |    28       49.8%          84.1%
  [0.7, 0.8)      18       71.4%         118.2%      |    22       68.9%         112.4%
  [0.8, 0.9)       9       94.2%         155.6%      |    11       91.1%         148.3%
  [0.9, 1.0]       4      142.1%         201.3%      |     6      138.4%         192.7%
```

This section is skipped with a notice if `confidence_calibration` is absent from `results.json` (i.e. before P3 is implemented).

---

## CLI Usage

```bash
# Compare two registered version_ids (primary usage)
python scripts/model_diff.py --model-a M01_baseline_20260315_133129 --model-b m01_prototype_20260506_160054

# Compare using filesystem paths (fallback for unregistered models)
python scripts/model_diff.py --model-a models/m01_baseline_2021_2025 --model-b models/m01_baseline_full

# Save machine-readable diff alongside artifact B
python scripts/model_diff.py --model-a <version_a> --model-b <version_b> --save

# Limit feature importance rank table to top N (default 15)
python scripts/model_diff.py --model-a <version_a> --model-b <version_b> --top-n 20
```

---

## Implementation Order

1. **P1** — Fix artifacts path in `train_mfe_classifier.py`
2. **P2** — Add missing fields to `specs_json` (label thresholds, class weights, boost rounds)
3. **P4** — Add `model_name`/`model_version` columns to `models` table schema + migration
4. **Build `scripts/model_diff.py`** — Sections 1–6 (all data available after P1–P4)
5. **P3** — Add confidence calibration to `ClassificationEvaluator`
6. **Wire Section 7** into `model_diff.py` once P3 is done
7. **Verify** — Run against two real model versions, validate all sections render correctly
8. **Document** — Add usage guide and output format to `docs/manual_for_me.md`

---

## Verification Plan

- Run against `M01_baseline_20260315_133129` vs any second registered version
- Confirm feature diff correctly identifies added/removed features
- Confirm rank shift table shows N/A for features absent from one model
- Confirm per-class table adapts dynamically to however many classes exist in each model's `classification_report`
- Confirm filesystem-path fallback works for unregistered models in `models/m01_baseline_2021_2025/`
- Confirm `--save` writes valid JSON to `models/artifacts/{version_b}/diffs/`
- Confirm Section 7 (calibration) shows a graceful skip notice when `confidence_calibration` key is absent

---

## Out of Scope

- Loading XGBoost model binaries into memory (all importance data comes from `results.json`)
- Automated regression alerts or CI integration (future work)
- HTML/notebook report output (future work)
