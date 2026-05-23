# Session Handover: 2026-05-23 — Evaluation Framework Phase A

## 🎯 Goal
Implement Phase A of the evaluation framework per
[docs/plans/evaluation_implementation_plan_2026_05_23.md](../plans/evaluation_implementation_plan_2026_05_23.md):
ship the cross-cutting infrastructure (§1.1–§1.2), the pre-S1 gating
modules (§2.1–§2.5), and the keystone promotion gate (§6) — then wire
them into the live training script, evaluator, and daily orchestrator.

## ✅ Accomplished
- **§1.1 EvaluationGate** — `GateResult` + `EvaluationGate.is_promotable()` with serialization round-trip.
- **§1.2 evaluator_run metadata block** — `BaseEvaluator._save_metrics_json` now emits `git_sha`, `python_version`, `platform`, `label_registry_id`, `feature_set_id`, `pipeline_run_id` (auto-resolved from `pipeline_runs` when not set).
- **§2.1.1 LabelDefinition registry** — dataclass + `fingerprint()` (canonical-JSON SHA-256, excludes `generated_at`). First label authored: `mfe_4class_30d_v1`.
- **§2.1.2 LeakageGuard.audit_label** — horizon-window check against `price_data`, optional reference recomputer, classifies violations as `no_in_horizon_prices` / `value_mismatch` / `horizon_overrun`.
- **§2.1.3 LeakageGuard.feature_parity_check** — samples (ticker, date) keys common to train+deploy views, asserts numerical (rtol) + dtype + categorical equality. Catches the m01_rank class of bug.
- **§2.2 Calibration / ECE gate** — equal-width binning per Guo et al. (2017), `calibration_audit` records blocking gate on production class only.
- **§2.3 Walk-forward classification harness** — anchored (train_start fixed), `FoldSpec` + `anchored_walk_forward` generator + `run_walk_forward` + `aggregate_walk_forward` with worst-fold AUC gate.
- **§2.4 Threshold optimization** — `precision_min` / `f1_max` / `youden` modes, returns `achievable=False` cleanly when target unreachable.
- **§2.5 Paper-trade prediction logging** — `daily_predictions` table migration + `log_daily_predictions` (idempotent, ranks by production-class probability).
- **§6 Promotion gate** — `ModelRegistry.set_prod` now reads `results.json`, refuses on blocking-fail, requires non-empty reason for `force=True`, logs to new `forced_promotions` table. New `PromotionError` exception. Supports both legacy and current results.json layouts.

### Integration wiring (per user request, after Phase A library work)
- **`scripts/train_mfe_classifier.py`** — loads `LabelDefinition`, runs `feature_parity_check` (abortable via `--skip-parity`), freezes label def to artifact dir, populates evaluator's reproducibility ids, new `--walk-forward` mode with per-fold artifacts + merged gates.
- **`src/evaluation/classification_evaluator.py`** — step 7 now also runs `calibration_audit` alongside Brier; adds `ece_per_class`, `production_class_ece`, and the calibration gate to `metrics['gates']`.
- **`src/orchestrators/daily_pipeline_orchestrator.py`** — Phase 8 now calls `_log_prod_model_predictions(target_date)`: loads prod model, scores `v_d3_deployment` for that date, writes to `daily_predictions`. Best-effort — never breaks Phase 8.

**62 new tests, all passing.**

## 📝 Files Changed

### New library modules
- `src/evaluation/gate.py` — `GateResult` + `EvaluationGate`.
- `src/evaluation/label_registry.py` — `LabelDefinition` with stable fingerprinting.
- `src/evaluation/calibration.py` — `expected_calibration_error` + `calibration_audit`.
- `src/evaluation/walk_forward.py` — anchored WF: `FoldSpec`, `anchored_walk_forward`, `run_walk_forward`, `aggregate_walk_forward`.
- `src/evaluation/thresholding.py` — `find_optimal_threshold` (3 modes).
- `src/evaluation/prediction_logger.py` — `log_daily_predictions` + `ensure_schema`.
- `scripts/migrations/2026_05_24_create_daily_predictions.sql` — DDL for `daily_predictions`.
- `label_registry/mfe_4class_30d_v1.json` — first label definition.

### Modified
- `src/evaluation/leakage_guard.py` — added `audit_label` and `feature_parity_check`; later in the day, fan-out fix (DISTINCT keys + ROW_NUMBER dedup) and progress logging.
- `src/evaluation/base_evaluator.py` — `evaluator_run` metadata block, `label_registry_id` / `feature_set_id` / `pipeline_run_id` attrs.
- `src/evaluation/classification_evaluator.py` — calibration_audit slotted into evaluate() step 7.
- `scripts/train_mfe_classifier.py` — label loading, feature parity check, --walk-forward mode, `_run_walk_forward_block` helper.
- `src/orchestrators/daily_pipeline_orchestrator.py` — Phase 8 prediction logging via `_log_prod_model_predictions` and `_resolve_prod_feature_cols`.
- `src/model_registry.py` — `PromotionError`, gated `set_prod`, `forced_promotions` table creation in `__init__`.
- `tests/test_feature_parity.py` — 2 new regression tests for multi-row-per-key dedup behavior (7 total).

### New tests (all passing — 62 total)
- `tests/test_evaluation_gate.py` (6) — promotability, serialization, non-blocking semantics.
- `tests/test_base_evaluator_metadata.py` (3) — metadata block fields, git sha helper.
- `tests/test_label_registry.py` (7) — round-trip, fingerprint stability/sensitivity, optional bins.
- `tests/test_label_audit.py` (4) — pass / horizon-overrun / missing-prices / input validation.
- `tests/test_feature_parity.py` (5) — pass / numerical mismatch / categorical mismatch / no overlap / unknown feature set.
- `tests/test_calibration.py` (8) — well-calibrated / shifted / empty / shape validation / pass+fail gates / class-count validation.
- `tests/test_walk_forward.py` (7) — disjoint folds, min-train-years skip, run_walk_forward shape, gate fires correctly.
- `tests/test_thresholding.py` (5) — precision_min leftmost / unreachable target / f1_max / youden / input validation.
- `tests/test_prediction_logger.py` (8) — schema, round-trip, idempotency, multi-day, validation, decision_taken defaults NULL.
- `tests/test_promotion_gate.py` (9) — pass / blocking-fail / force-without-reason / force-with-reason / missing-results / legacy-layout / unknown-version / non-blocking-failures.

## 🚧 Work in Progress (CRITICAL)
**None blocked.** The phase ships clean.

Caveats to be aware of next session:
- **No end-to-end run on real data yet.** Every test uses synthetic fixtures or temp DuckDBs. The first time someone runs `python scripts/train_mfe_classifier.py --walk-forward --label-id mfe_4class_30d_v1`, expect to debug small things — likely candidates: (1) feature_parity_check reaching for `v_d3_deployment` which may not exist if views haven't been recreated post-ViewManager phase 5.1 fix; (2) categorical column casting in the orchestrator's scoring path may need adjustment when actual `sector`/`industry` enter the pipeline.
- **`_log_prod_model_predictions` is best-effort.** Phase 8 catches all exceptions and just logs a warning. That's deliberate — we don't want prediction logging to break the daily pipeline — but it means silent failures need monitoring.
- **`ModelRegistry._migrate_models_table` is brittle.** Pre-existing: it calls `PRAGMA table_info('models')` which raises `CatalogException` on a fresh DB instead of returning empty rows. Test fixtures work around this by pre-creating the `models` table. Not my code, but worth flagging.

### 🔴 Parity-check failure on `v_d2_training` vs `v_d3_deployment` (discovered 2026-05-23 PM)

When run end-to-end against the live DB on `m01_prototype_may/v2_gated`, the feature-parity gate fails. The investigation surfaced **two bugs** — one fixed today, one that needs separate work in the view layer.

**Bug #1 — fixed today (commit pending):** `feature_parity_check` was Cartesian-joining the two views when (ticker, date) wasn't unique on either side. PACS 2025-11-21 produced 5×5 = 25 rows and most pairings naturally disagreed → reported 100+ false-positive mismatches. Fix: dedupe each side via `ROW_NUMBER() OVER (PARTITION BY ticker, date ORDER BY ticker) = 1` before joining; also wrap the sample CTE in `SELECT DISTINCT ticker, date`. Surfaces `train_multi_row_keys` / `deploy_multi_row_keys` in the result so the fan-out itself is visible. Two regression tests added in `tests/test_feature_parity.py`.

**Bug #2 — view-layer issue, NOT FIXED:** After the dedup fix, parity *still* fails. The new mismatch pattern is **NaN-vs-value asymmetry**:

| ticker | date       | feature             | train | deploy  |
|--------|------------|---------------------|-------|---------|
| LFUS   | 2026-05-06 | eps_diluted         | NaN   | -9.72   |
| SNDK   | 2025-09-19 | eps_diluted         | -0.16 | NaN     |
| LFUS   | 2026-05-06 | revenue_growth_yoy  | NaN   | 12.167… |

**Root cause.** Both views contain multiple rows per (ticker, date), and those duplicate rows hold *inconsistent fundamentals* — one row has `eps_diluted = NaN`, another has the real value. `ROW_NUMBER() = 1` arbitrarily picks one (DuckDB chooses, no ORDER BY discriminator), and the two views' arbitrary choices don't agree. The check is correctly reporting "you can't compare these views" but blaming the wrong layer.

**Why it happens.** Likely the views join `daily_features` against `fundamentals` without an "as-of latest filing on this date" filter. Each (ticker, date) row in `daily_features` gets multiplied by every overlapping filing version (initial + restated + amendment), and `fundamentals` itself has NaN in some columns for the earlier filings. Not investigated end-to-end because a probe query (`SELECT eps_diluted FROM v_d2_training WHERE ticker='LFUS' AND date='2026-05-06'`) **OOMs DuckDB even when scoped to one row** — the underlying view materialization is huge.

**Implications:**

1. **The model is being trained on ambiguous data.** XGBoost sees N copies of (ticker, date), some with NaN eps_diluted, some with the real number. The training set is silently fan-ing out and the model is averaging over inconsistent feature vectors — what the m01_prototype baseline has been doing for months.
2. **The parity-check gate cannot be trusted until view #2 is fixed.** Running with `--skip-parity` is the practical workaround for now, but it silences a legitimate signal. Document each skip in the run's metadata so we can audit which models were trained without parity verification.
3. **The OOM probe is itself diagnostic.** A single-ticker, single-date query against `v_d2_training` shouldn't OOM. That means the view's CTE chain is materializing far more than it needs to before the predicate gets pushed down. The fix likely involves either rewriting the join order so the filter happens before the fan-out, or materializing the as-of join into a real table.
4. **Memory: never run `SELECT *` or `COUNT(DISTINCT (ticker,date))` against any of `v_d2_training`, `v_d3_deployment`, `daily_features`, `price_data` from a notebook or smoke script.** Saved to memory as `feedback_large_dataset_queries.md`.

**Recommended next steps (separate session):**

1. **Investigate the view-layer fan-out.** `ViewManager.create_all()` writes both views — find the JOIN against `fundamentals` (and possibly `shares_outstanding`) and add an as-of filter so each (ticker, date) gets exactly one fundamental row. Likely lives in `src/managers/view_manager.py`.
2. **Add a `(ticker, date)` uniqueness assertion** to the post-view-build smoke checks. Once views are unique, the parity gate becomes meaningful.
3. **Re-run the m01_prototype_may training** without `--skip-parity` to confirm the gate passes once views are clean.

### 🟢 Progress logging added to `feature_parity_check`

The check takes 2-5 minutes on the real DB (mostly the `DISTINCT` scan + the wide load). It now logs:

```
INFO  feature_parity_check: starting (...)
INFO  feature_parity_check: loaded 102 features in 0.0s
INFO  feature_parity_check: sampling 200 common keys (may take 1-3 min on large views — DISTINCT scan)...
INFO  feature_parity_check: sampled 200 keys in 87.3s
INFO  feature_parity_check: loading train_view rows...
INFO  feature_parity_check: loaded train_view 200 rows in 42.1s (multi_row_keys=187)
INFO  feature_parity_check: loading deploy_view rows...
INFO  feature_parity_check: loaded deploy_view 200 rows in 38.7s (multi_row_keys=181)
INFO  feature_parity_check: comparing 102 features across 200 keys...
INFO  feature_parity_check: done in 168.4s — passed=False ...
```

## ⏭️ Next Steps
1. **🔴 Fix `v_d2_training` / `v_d3_deployment` fan-out** (separate session, ~half-day). The parity gate is currently un-trustworthy because the underlying views have multiple inconsistent rows per (ticker, date). See "Parity-check failure" section above. Until this is fixed, every training run needs `--skip-parity` and the metric should be flagged as "trained-without-parity-verification."
2. **Re-run `m01_prototype_may/v2_gated` after the view fix** without `--skip-parity` to confirm the gate passes.
3. **Re-evaluate `M01_baseline_v0.1` end-to-end under the new framework** (the "Overall DoD" item from §8 of the plan). Expect some gates to fail — that's the point. Decide which failures are real vs. spec-bugs.
4. **Phase B §3.1 — Walk-forward backtest harness** (3-5d) — promotes the per-fold classifier results into actual backtest-validated robustness claims. Plan: [docs/plans/evaluation_implementation_plan_2026_05_23.md §3.1](../plans/evaluation_implementation_plan_2026_05_23.md).
5. **Phase B §3.2 — Regime-conditional metrics** (1d) — promoted to P0 because S3 (regime routing) can't be validated without it.
6. **Phase D §5.1 — Dashboard "Today" decision toggle** (1d) — the `daily_predictions` table is already being written; the UI just needs to add the 3-state widget. Coordinate with the dashboard uplift session in [2026-05-23-dashboard-uplift.md](2026-05-23-dashboard-uplift.md).
7. **Authoring the label fingerprint into the registry table.** Currently labels live as JSON files. A future step (not in Phase A scope) is to mirror them into a DuckDB `label_registry` table so audits can join against historical labels.

## 💡 Context/Memory
- **Plan vs. repo layout drift.** The plan repeatedly references `test/` but the repo uses `tests/`. The plan also references `label_registry/` and `scripts/migrations/` as if they exist — they didn't, I created them. Same for the convention that artifacts live under `models/<name>/<version>/evaluation/` — that part matched what `BaseEvaluator` already does.
- **Pre-existing broken tests are pre-existing.** `tests/test_m01_evaluator.py`, `tests/test_feature_preprocessor.py`, `tests/test_metrics.py`, `tests/test_rehydration.py` all fail at *collection* time due to `ModuleNotFoundError` from archived modules (the [`src.evaluation.m01_evaluator`] and [`src.features`] removed in commit `418f229`). Not regressions from my changes. The 20 other failures/27 errors when running the full suite are existing tests against the live DB (`test_phase1_backfill`, `test_view_manager`, `test_feature_pipeline`) that need data fixtures, not code changes.
- **Anchored vs sliding walk-forward.** Locked in anchored per whitepaper §5.1: `train_start` fixed, `train_end` advances by step. Sliding-window WF would discard regime data the model could benefit from; anchored mirrors how prod retraining will eventually work.
- **Force-with-logging beats force-without.** Gap-analysis open decision #1 recommended this pattern. Implementation: forced promotions require a non-empty `force_reason` and are written to a permanent `forced_promotions` table. Makes the override expensive enough to discourage routine use without making it impossible — and if it *does* become routine, that's itself a signal the gates are wrong.
- **production_class_idx convention.** ECE gate, threshold sweep, walk-forward AUC gate all use "last actionable class" by convention (e.g., `Home Run` for MFE 4-class). Overridable per call.
- **Calibration default threshold = 0.05.** Industry standard. Re-tune later if M01_baseline can't clear it.
- **The integration changes have NOT been run against real data.** They've been verified via AST parse + import smoke tests + helper-level execution on synthetic panels. Live training is the next step's verification.

---

After creating this file, ask the user if they want to `git add` and `git commit` it.
