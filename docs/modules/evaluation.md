# Module: Evaluation & Training (`src/evaluation/` + trainers)

> Verified against code 2026-07-18. Everything between "features exist" and "a
> model version is registered": data loading, labels, training, evaluation
> artifacts, gates, the model card, and the nightly scoring/drift machinery.
> The methodology (8 gates, three currencies of proof) lives in
> [model_development_methodology.md](../architecture/model_development_methodology.md);
> this doc maps it to code.

## Training data path

- `src/evaluation/training_data_loader.py::load_training_data()` — one source,
  two modes: `dense` → `t3_sepa_features` (~9.4M rows, no target; feature hygiene)
  and `trades` → `v_d2_training` (~39K trade rows + outcomes). The `trades` mode
  prefers `d2_training_cache` when fresh (~70× faster), else falls back to the
  view. Columns are lowercased on load. Named label-sets (`LABEL_SETS`) map
  `mfe_pct` → classes.
- `src/evaluation/label_registry.py` — `LabelDefinition` (description,
  `target_col`, horizon, exit rule, bins, git_sha) + `fingerprint()`; a copy is
  saved into each model's artifact dir, so "which label was this trained on?" is
  verifiable forever. Live labels: `mfe_binary_homerun_v1` (prod),
  `mfe_4class_v1`, `m01a_tail_v1` — definitions of record in
  [glossary.md](../architecture/glossary.md) §2. **Two clocks warning**: fixed
  63-bar horizons RANK; the SEPA event-terminated exit HOLDS — don't mix them.

## Trainer

`scripts/train_mfe_classifier.py` — XGBoost classifier (binary or 4-class via
`--label-id` / `--label-set`), features loaded from `model_feature_sets`
(never hardcoded), `sector`/`industry` as native categoricals
(`enable_categorical=True`, no integer encoding). Chronological splits
(60/20/20 explore; `--no-holdout` 85/15 for the production candidate);
`--walk-forward` runs the anchored WF harness whose gates the card evaluates;
`--with-calibration` fits the isotonic calibrator; `--with-regime-decomp` adds
regime-conditional metrics. Artifacts + registration per
[model_registry.md](model_registry.md).

## Evaluation building blocks (one job each)

| File | Role |
|---|---|
| `classification_evaluator.py` | Standard artifact set: accuracy/F1/Brier, per-class ROC/PR-AUC, calibration curves, SHAP, feature importance → `evaluation/` dir + registry |
| `leakage_guard.py` | Temporal-leakage validation; runs inside the trainer, result stored in `metadata.json` |
| `data_quality.py`, `pretrain_report.py` | Pre-training audit (null fractions, coverage, target sanity) — thin sequencer over small checks |
| `feature_signal.py` | IC / mutual information / redundancy (ports the notebook cells exactly) |
| `walk_forward.py`, `walk_forward_backtest.py` | Anchored (not sliding) walk-forward CV harness |
| `breakout_cv.py`, `m02_cv.py` | Purged/embargoed CV variants (breakout regressor, m02) |
| `calibration.py`, `calibrator.py` | Isotonic probability calibration. ⚠️ Isotonic plateaus flatten *ranking*; backtest `prob_elite` is post-calibration while `daily_predictions` stores RAW — same name, two scales (glossary §1) |
| `thresholding.py` | Deployment-threshold optimization for binary signals |
| `gate.py` | `GateResult` primitives — the `results.json` blocking-gate battery that `set_prod()` enforces |
| `regime_decomposition.py` | Metrics decomposed across the five M03 regimes |
| `bootstrap.py`, `permutation_null.py` | Trade-level uncertainty: circular block bootstrap; within-date label-shuffle null |
| `ablation.py` | Feature-group ablation harness |
| `drift.py` | PSI feature drift vs frozen-at-training reference bins |
| `score_engine.py` | Shared RAW-softprob scorer materializing `daily_predictions` — the single code path for orchestrator Phase 7.4 and `scripts/backfill_daily_predictions.py` |
| `prediction_logger.py` | One row per (date, ticker, model_version, cohort) into `daily_predictions` |
| `shadow_compare.py` | Prod-vs-shadow ranking diff on the same candidate universe → `shadow_divergence` |
| `m03_evaluator.py`, `m03_ground_truth.py` | Regime-model evaluation vs labeled ground truth |
| `html_report.py`, `plotting.py`, `classification_report.py` | Rendering |

## Model card (`src/evaluation/model_card/`)

`builder.py` orchestrates section builders (`sections/`) → rubric scoring
(`rubric.py`) → aggregate verdict (`verdict.py`) → HTML + JSON. Benchmarks in
`benchmarks.py`. CLI: `scripts/build_model_card.py --model <name>/<version>`
(slug, not version_id). Two card kinds: the full-history **promotion-gate card**
(`model_card_path`) and the weekly trailing-window **drift card**
(`model_card_drift_path`, orchestrator Phase 10). Verdicts are per **use case**
(e.g. `composite_gate_plus_rank`, `threshold_gate`, `human_screener`); the card
is advisory — blocking lives in the `results.json` gates.

⚠️ Section G uses multiprocessing and hangs on the dev box — stub it there
(known issue; timeout/serial fallback is an open TODO).

## Analytics siblings (`src/analytics/`)

`decile_analysis.py`, `rolling_ic.py`, `score_trajectory.py` — post-hoc score
analytics used by reports and the dashboard's Model Lab.

## Related

- Epistemics: label-lift ≠ trade-edge; C1/C2/C3 claim-strength rules —
  glossary §2 and memory `project_standing_epistemics`.
- Strategy-level validation (cones, OOS gate): [backtest.md](backtest.md)
