# Module: Model Registry (`src/model_registry.py`)

> Verified against code 2026-07-18. `ModelRegistry` is the CRUD + promotion layer
> over the `models`, `model_feature_sets`, `feature_catalog`, and
> `forced_promotions` tables. It is NOT part of ViewManager (deliberate split).

## The `models` table

One row per trained version. Key columns: `version_id`
(e.g. `m01_binary_20260524_222020`), `model_name`, `status_flag`
(`prod`/`test`/`archived` — plus a shadow pointer, below), `specs_json`
(features, hyperparams, training config), `feature_version` (e.g. `v3.1`),
`artifacts_path`, metrics columns, `model_card_path`/`model_card_built_at`
(promotion-gate card) and `model_card_drift_path`/`..._built_at` (weekly drift
card — separate artifacts, never overwrite each other).

**Current prod**: `m01_binary` (binary home-run classifier, promoted 2026-07-15;
the 4-class prototype is archived). Model research history:
[docs/model_doc/m01.md](../model_doc/m01.md).

## Public API

```python
reg = ModelRegistry()
reg.register_version(...)            # called by trainers
reg.get_model_specs(version_id)
reg.update_metrics(...)
reg.list_versions(status=None)
reg.get_prod_version() / reg.set_prod(version_id, force=False, force_reason="")
reg.get_shadow_version() / reg.set_shadow(version_id)
reg.register_model_card(...) / reg.register_drift_card(...)
reg.get_artifacts_path(version_id) / reg.get_model_slug(version_id)
reg.register_feature_set(...)        # rows into model_feature_sets
reg.get_reproducibility_info(version_id)   # models ⋈ model_feature_sets ⋈ feature_catalog
ModelRegistry.get_git_sha()
```

## Promotion gates (`set_prod`) — four layers

1. **Blocking**: `evaluation/results.json` gate battery — any gate with
   `blocking=True` and `status='fail'` refuses promotion. Override only with
   `force=True, force_reason="..."`; forced promotions are permanently logged to
   `forced_promotions`.
2. **Advisory**: `_warn_on_adverse_card()` — warns on REJECT/PENDING/stale/void
   model card but never blocks (card thresholds are hand-set and unvalidated).
3. **Blocking — score coverage** (`_assert_scores_backfilled`, added 2026-07-20):
   refuses promotion if the incoming version has **fewer scored dates** in
   `daily_predictions` than the outgoing prod. `force=True` skips it.

   `daily_predictions` is keyed `(date, ticker, model_version_id, cohort)` and the d3
   views join `status_flag='prod'`, so promotion **orphans all history under the
   outgoing id** — the old rows remain but are no longer joined, and the new id has
   none. The dashboard goes blank with no error anywhere; the only signal is the
   Phase 8 prod-model-identity alert ~10 min into the *next* nightly run.

   Hit for real on 2026-07-20: `m01_binary_20260524_222020` was promoted having only
   ever run as **shadow**, which scores the `breakout` cohort alone — 2,249 rows
   total vs the outgoing model's ~837/day. Screening showed 666 of 672 rows unscored.
   The gate compares *date coverage*, not mere existence, precisely because that
   shadow model had rows and would have passed a non-zero check.

   Correct order: `backfill_daily_predictions.py --model-version-id <new>` → verify →
   `set_prod(<new>)` → rebuild the slim DB.
4. **Practice (not in code)**: the real strategy-level promotion decision is the
   **start-date cone** (`scripts/run_cone_gate.py` / `run_oos_gate.py`) — a single
   backtest P&L is one draw, not a verdict. See
   [model_development_methodology.md](../architecture/model_development_methodology.md).

**Shadow slot**: `set_shadow()` marks one version for the nightly shadow scoring
pass (orchestrator Phase 7.4 → `shadow_divergence`). The live `models` CHECK
constraint is `('prod','test','archived','shadow')` — verified 2026-07-20 against
`duckdb_tables()`. `ViewManager._create_models_table` carried a stale 3-value list
(no `'shadow'`) until 2026-07-20; being `CREATE TABLE IF NOT EXISTS` it never touched
the live table, so the shadow path always worked. **Read the DB's own DDL, not the
code's, before calling a constraint contradiction.**

## Feature metadata tables

- `feature_catalog` — one row per feature (name, dtype, group, description).
  Populated by `scripts/populate_feature_catalog.py`.
- `model_feature_sets` — named feature lists per model (e.g. `fs_m01_prototype`);
  trainers load features from here, never hardcode.
- `src/utils.py::get_model_features(model_name)` is the loader; its model-name
  match is `LOWER()`-normalised (a case-sensitivity bug here once silently
  dropped features in the live scorer).

## Artifact layout (written by trainers)

```
models/<model_name>/<version>/
    model.json                # XGBoost booster
    metadata.json             # training config, feature list, leakage audit
    categorical_mapping.json  # REQUIRED for backtest loadability
    label_definition.json     # copy of the label registry entry
    evaluation/
        results.json          # metrics + the blocking-gate battery
        *.png, report_*.md, diffs/
```

## Gotchas (verified, still live)

- Load the prototype via the full path `models/m01_prototype_2003_2026/v1/` —
  bare `m01_prototype/` errors.
- Only models with `categorical_mapping.json` are loadable by the backtest scorer.
- `artifacts_path` is stored with Windows backslashes — cloud/POSIX consumers must
  `.replace("\\", "/")` before `Path.parts`.
- `build_model_card.py --model` takes the `name/version` slug, NOT the
  `version_id`.

## Related

- Trainers and evaluation artifacts: [evaluation.md](evaluation.md)
- Scoring consumers: [backtest.md](backtest.md), orchestrator Phase 7.4
