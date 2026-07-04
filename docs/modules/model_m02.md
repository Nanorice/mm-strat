# Module Passport: M02 (Ignition Classifier) — Code Structure

> **Scope:** this passport documents the **code/infra** of the *live* M02 — the
> ignition classifier (breakout-proximity regressor). For the model's purpose, theory,
> metrics, and journey see the lifecycle doc [docs/model_doc/m02.md](../model_doc/m02.md).
>
> ⚠️ The previous version of this passport described the **retired loser-detector**
> (`M02Trainer`, triple-barrier, `y_loser` inversion). That code is dead and is **not**
> the current M02. See §4 (Retired code) for what it was.

## 1. Overview

**Responsibility:** train and evaluate the ignition classifier — an XGBoost regressor that
ranks the dense ticker universe by proximity to the next SEPA-watchlist breakout.

**Key dependencies:**
- `src.evaluation.walk_forward.anchored_walk_forward` — fold geometry (60d embargo)
- `src.evaluation.breakout_cv` — `cross_sectional_rank_ic`, `precision_recall_at_k`
- `model_feature_sets` table — resolves `fs_m01_prototype` feature columns
- `t3_training_cache` + `m02_breakout_targets` (DuckDB) — feature matrix and target join

## 2. File Structure

| File | Purpose |
| :--- | :--- |
| `scripts/build_breakout_targets.py` | **Target builder.** Joins `price_data` × `sepa_watchlist`, computes days-to-next-ignition, applies `exp(-0.1·days)` decay → `m02_breakout_targets` table. |
| `scripts/train_breakout_model.py` | **Trainer + eval.** Loads matrix, runs anchored WF folds, trains one XGBoost booster per fold, scores Rank IC / Precision@K. Checkpointed per fold; `--smoke` for a 5-ticker path test. |
| `src/evaluation/breakout_cv.py` | **Metrics.** `cross_sectional_rank_ic`, `precision_recall_at_k`. |
| `src/evaluation/walk_forward.py` | **Fold geometry.** `anchored_walk_forward` — anchored train window, stepping test window, embargo. |

## 3. Data & Artifacts

- **Input matrix:** `SELECT fs_m01_prototype features FROM t3_training_cache JOIN m02_breakout_targets ON (ticker, date)`.
- **Target column:** `breakout_proximity` (float, 0..1).
- **Run output:** `models/m02_breakout/<run_tag>/` — `fold_NN_model.json` (per-fold boosters),
  `fold_NN.json` (metric checkpoints), `summary.json` (aggregated IC / P@50).
- **XGBoost params:** `reg:squarederror`, `hist`, `max_depth=6`, `eta=0.05`, `subsample=0.8`,
  `colsample_bytree=0.8`, `min_child_weight=20`, `num_boost_round=300`.

## 4. Retired code (NOT the current M02)

The following are dead and retained only to explain the name collision. Do not treat as the
live model or as fallbacks.

- `src/pipeline/m02_trainer.py` (`M02Trainer`) — the retired **loser-detector**: binary
  classifier predicting `y_loser` (P(stop-loss hit)) via label inversion, trained on triple-barrier
  outcomes (`k_sl=1.0`, `k_tp=4.0`, `min_tp=0.20`, `max_time=30`).
- `src/triple_barrier_labeler.py` — the path-dependent labeler feeding that model.
- `M02_FEATURES` in `src/feature_config.py` — the old "Velocity Squad" 53-feature set for the
  loser-detector (the live model uses `fs_m01_prototype`, resolved from `model_feature_sets`).

Retirement rationale (and the earlier quantile-cone M02): [docs/model_doc/m02.md](../model_doc/m02.md) §9.
