# Session Handover: 2026-05-24 — Binary Reformulation + Calibration + Strategy Array

## 🎯 Goal
Pivot the 4-class MFE model to a binary Home-Run formulation, then add the missing rigor pieces (isotonic calibration, configurable backtest strategies) so we can move from "the model has AUC 0.72 but no usable backtest" to a fair head-to-head between trade-selection rules.

## ✅ Accomplished

### Binary model reformulation
- Created `mfe_binary_homerun_v1` label (boundary: MFE > 30%) and renamed the 4-class label to `mfe_4class_v1`, dropping the misleading `_30d` suffix (the underlying `mfe_pct` is over the SEPA holding period, capped at 120 days for trades still open at end-of-data — *not* a fixed 30-day horizon).
- Refactored `scripts/train_mfe_classifier.py` to derive `num_class`, `class_names`, XGBoost objective, and label thresholds from `label_def.bins` instead of hardcoded constants. New `_BinaryProbaShim` adapter exposes 2-D probabilities to the evaluator while saving the raw booster.
- Trained `m01_binary/v1` (val acc 0.634, wF1 0.688, Home Run AUC 0.716, top-50 lift 3.44× — vs 4-class top-50 lift 2.62×).
- Verified leakage clean: temporal split honored, WF folds anchored, feature-name check passed, top features confirmed backward-looking (`ROWS BETWEEN N PRECEDING`).

### Evaluator binary-compatibility fixes
- Fixed `label_binarize` returning `(n, 1)` for binary inputs across 6 sites in `classification_evaluator.py` (ROC/PR/Brier) and `plotting.py` (ROC/PR/calibration curves) via a `_one_hot()` helper that pads to `(n, 2)`.
- Fixed `_default_actionable_classes()` to return `[1]` for binary (was `[0, 1]` — meaningless).
- Fixed SHAP path: unwraps the `_BinaryProbaShim` to the raw booster (SHAP refuses unknown wrapper types), normalises `shap_values` shape (binary returns single array, multi-class returns list).
- Fixed permutation-importance adapter: 1-D→2-D shim in `predict_proba`, plus `_estimator_type = "classifier"` and `__sklearn_tags__()` override (sklearn ≥1.6 doesn't honor `ClassifierMixin` alone).

### Calibration infrastructure
- New `src/evaluation/calibrator.py` — `IsotonicCalibrator` (fit on val, save/load via joblib + sidecar `.meta.json`, out-of-bounds clip, monotonicity).
- Trainer hook (`--with-calibration`): fits on val slice after `evaluator.evaluate()`, persists `<model_dir>/calibrator.joblib`, merges `calibration_ece_post < 0.10` gate into `results.json`.
- `default_signals_to_scores` now accepts `calibrator_path` and applies it before emitting `prob_elite`; propagated through `run_walk_forward_backtest`.
- `UniverseScorer` extended for binary objective (`binary:logistic` detection, 1-D proba handling, binary-appropriate MFE midpoints `[3, 70]`); auto-loads `calibrator.joblib` adjacent to `model.json`.
- 8 unit tests in `tests/test_calibrator.py`, all passing.

### Backtest strategy array (S1–S5)
- Extended `SEPAHybridV1` with `min_hold_days`, `persistence_window_days`, `persistence_min_count`, `persistence_threshold`. Fixed two latent bugs in `_check_rank_exits` (wrong `.get()` on tuple, swapped args to `get_score`).
- Added `ScoreLookup.check_persistence(ticker, date, window, min_count, threshold, rank_field)` for S5's "sustained-rank" entry gate. 6 unit tests in `tests/test_score_lookup_persistence.py`, all passing.
- `SEPABacktestRunner.setup()` now accepts `strategy_kwargs` for per-run param injection.
- `default_signals_to_scores` now populates `trailing_pct` from rolling daily ranks (was NaN — broke `rank_by='trailing'` for WF backtest).
- New CLI `scripts/run_strategy_array.py` runs all 5 strategies (S1 baseline_top3, S2 trailing10_top5, S3 prob_threshold_5pos, S4 trailing20_regime_aware, S5 hybrid_persistent) on a single window with `--include-uncalibrated` toggle. Emits per-strategy `trades.parquet` + `equity.parquet` + `metrics.json` + `config.json`, plus top-level `comparison.md` ranked by Sharpe and `summary.json`.

### Documentation
- `docs/plans/eval_14c_parallel_session_instructions.md` — self-contained plan for the §1.4(c) deep-rigor pass (bootstrap CI, permutation null, ablation, regime decomp, decile analysis, one-pager) to run in parallel against `m01_prototype_may/v2_gated`.

## 📝 Files Changed

### New
- `src/evaluation/calibrator.py` — IsotonicCalibrator class
- `label_registry/mfe_4class_v1.json` — renamed from `_30d_v1`, horizon_days set to null
- `label_registry/mfe_binary_homerun_v1.json` — binary label, bins=[30.0]
- `scripts/run_strategy_array.py` — CLI for S1–S5 backtest array
- `tests/test_calibrator.py` — 8 tests for calibrator
- `tests/test_score_lookup_persistence.py` — 6 tests for persistence check
- `docs/plans/eval_14c_parallel_session_instructions.md` — parallel-session deep-rigor plan
- `models/m01_binary/` — first artifacts from binary training (also reran via `--label-id` once mistake caught)

### Modified
- `scripts/train_mfe_classifier.py` — generic label binning (`label_def.bins`), `_BinaryProbaShim`, `--with-calibration` flag, calibrator fit/save block, calibrator passed to WF backtest
- `src/evaluation/classification_evaluator.py` — `_one_hot()` helper, fixed ROC/PR/Brier, binary SHAP path, permutation-importance binary adapter, `_default_actionable_classes` for binary
- `src/evaluation/plotting.py` — `_one_hot()` helper, fixed ROC/PR/calibration plot functions
- `src/evaluation/walk_forward_backtest.py` — `default_signals_to_scores` takes `calibrator_path` + `trailing_window`, populates `trailing_pct`
- `src/backtest/sepa_strategy.py` — added `min_hold_days` + persistence params, fixed two latent bugs in `_check_rank_exits`
- `src/backtest/score_lookup.py` — new `check_persistence()` method
- `src/backtest/runner.py` — `setup()` accepts `strategy_kwargs`
- `src/backtest/universe_scorer.py` — binary objective support, isotonic calibrator auto-load
- `tests/test_label_registry.py` + `tests/test_base_evaluator_metadata.py` — updated fixtures to new label IDs

### Deleted
- `label_registry/mfe_4class_30d_v1.json`
- `label_registry/mfe_binary_homerun_30d_v1.json`

## 🚧 Work in Progress (CRITICAL — RESULTS TO BE CHECKED)

The user is going to run the following two commands. Outputs are not yet verified:

1. **Retrain binary with calibration enabled**:
   ```powershell
   .\.venv\Scripts\python.exe .\scripts\train_mfe_classifier.py `
     --feature-set fs_m01_prototype `
     --model-name m01_binary `
     --model-version v1 `
     --label-id mfe_binary_homerun_v1 `
     --no-holdout `
     --walk-forward `
     --with-wf-backtest `
     --with-regime-decomp `
     --with-perm-importance `
     --with-calibration
   ```
   - **Expected**: `models/m01_binary/v1/calibrator.joblib` exists, `results.json` shows `pre_ece ≈ 0.316 → post_ece < 0.10`, new `calibration_ece_post` gate present.
   - **Risk**: untested end-to-end. Most likely failure surface is the WF backtest applying the calibrator per fold — `default_signals_to_scores` was modified, the WF aggregator wasn't.

2. **Strategy array on 6-month window**:
   ```powershell
   .\.venv\Scripts\python.exe .\scripts\run_strategy_array.py `
     --model-name m01_binary `
     --model-version v1 `
     --start 2024-11-01 --end 2026-05-22 `
     --strategies S1,S2,S3,S4,S5 `
     --include-uncalibrated
   ```
   - **Expected**: 10 runs (5 strategies × 2 calibration variants), `models/m01_binary/v1/backtests/comparison.md` ranked by Sharpe.
   - **Risk**: This is the first time `SEPAHybridV1` is invoked with `min_hold_days`/persistence params for real. Unit tests cover `check_persistence` in isolation but not the strategy-wiring. `UniverseScorer.score_from_t3` for a binary model also untested end-to-end (binary-objective branch is new).

## ⏭️ Next Steps (when user returns)

1. **Verify the two commands above ran cleanly.** If they did, read `comparison.md` and decide whether any strategy beats the WF backtest's mean Sharpe of 0.24.
2. **If calibrated ECE is still >0.10**, investigate val-slice size — n=5,548 may be too thin for isotonic in some probability regions. Fallback: try Platt scaling.
3. **If strategy array shows S5 (hybrid_persistent) outperforms**, the "prefer winners + min hold" hypothesis is validated and we should extend with sensitivity sweeps (min_hold ∈ {5, 10, 15, 20}, persistence_count ∈ {2, 3, 4}).
4. **§1.4(c) deep-rigor pass** is documented in `docs/plans/eval_14c_parallel_session_instructions.md` — runnable in a parallel session whenever; produces the DEMOTE record for the 4-class v2_gated.

## 💡 Context/Memory

- **The fan-out bug touched only 18 of ~31,000 training rows** (0.06%) — my earlier claim that v0.1 was inflated by it was wrong. v0.1 and v2_gated train on essentially identical data and produce statistically identical metrics. The fan-out fix was a correctness fix, not a model-quality fix.
- **The binary objective produces 1-D `predict()` output**, which is structurally incompatible with sklearn's `label_binarize`, the SHAP TreeExplainer's wrapper expectations, and the evaluator's `proba.shape[1]` patterns. The fix is a one-hot helper (`_one_hot()`) and a `_BinaryProbaShim` wrapper. There may be more sites that haven't been hit yet — they'll surface on the next run.
- **`mfe_pct` semantics**: measured over the SEPA holding period (entry to C1/C2/C6 loss), not a fixed 30-day horizon. The 120-day cap only applies to trades still open at end-of-data. Both labels share this — the new label files document it correctly.
- **Top XGBoost-gain features (`natr`, `consolidation_width`, `adr_20d`) have NEGATIVE permutation importance** on validation — shuffling them improves log-loss. This is *not* leakage; it's the opposite. The model is keying on noise that correlated with the label in-sample. After calibration this is worth revisiting: try removing those features and see if AUC stays put.
- **The WF backtest's `top_3_home_run_lift` of 1.55× vs top-50 lift of 3.44× says the bottleneck is now the trade-selection rule, not the model's ranking.** That's exactly what the strategy array is designed to test.
- **`SEPAHybridV1` already supported most of what was needed** (`rank_by`, `entry_mode`, `regime_max_pos`, `sizing_mode`, `cooldown_days`). The only new params required were `min_hold_days` and the persistence trio. The strategy array exploits existing knobs more than it adds new ones.
- **Two latent bugs fixed in `_check_rank_exits`**: it called `.get('trailing_10d_pct')` on a tuple (raises) and passed `(ticker, current_date)` instead of `(current_date, ticker)` to `get_score`. Neither was hit in production because `exit_use_percentile` defaults to False. S4/S5 may flip this on — keep an eye.
- **`UniverseScorer` had no binary detection** — `binary:logistic` fell through to the regressor branch, which would have crashed. Now detects via `'binary' in objective`. The binary midpoints `[3, 70]` are heuristic (avg MFE in Not-Home-Run vs Home-Run buckets) — if downstream code relies on calibrated_score being precisely 3/70-weighted, that's a knob to tune.
- **Permutation importance + sklearn 1.6 gotcha**: `ClassifierMixin` is no longer sufficient. The adapter now sets `_estimator_type = "classifier"` and overrides `__sklearn_tags__()`. Worth remembering for future custom estimators.

---

Want me to `git add` and `git commit` this handover note now?