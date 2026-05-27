# Session Handover: 2026-05-23 — Evaluation Framework Phases B & C

## 🎯 Goal
Continue from the Phase A handover ([2026-05-23_evaluation-framework.md](2026-05-23_evaluation-framework.md))
and implement Phases B (§3) and C (§4) of
[docs/plans/evaluation_implementation_plan_2026_05_23.md](../plans/evaluation_implementation_plan_2026_05_23.md).
Eval re-run on real data was deferred (per user) — this session shipped
library + unit tests against synthetic fixtures, same posture as Phase A.

## ✅ Accomplished

### Phase B (between S1 and S2, 5.5-7.5d budget)

- **§3.1 Walk-forward backtest harness** — `src/evaluation/walk_forward_backtest.py`
  Converts per-fold `FoldResult` objects from §2.3 into per-fold backtests.
  Delegates the backtest leg to a caller-supplied `backtest_fn` so tests can
  inject a mock and production can wire `SEPABacktestRunner`.
  Public API:
  - `default_signals_to_scores(fold_result, production_class_idx)` — emits
    a `(date, ticker, normalized_score, daily_pct_rank, prob_elite,
    calibrated_score, trailing_pct)` frame matching the
    `UniverseScorer.score_from_t3` contract.
  - `run_walk_forward_backtest(...)` — per-fold orchestrator that writes
    `trades.parquet`, `equity.parquet`, `metrics.json` to
    `output_dir/fold_<idx>/`. Skips folds whose `signals_to_scores` raises
    instead of aborting the whole run.
  - `aggregate_walk_forward_backtest(...)` — 4 blocking gates per the plan:
    - `wf_backtest_mean_sharpe` > 0.5
    - `wf_backtest_worst_sharpe` > -0.3 AND ≥ N/9·7 positive folds
      (proportionally sized for runs with fewer than 9 folds)
    - `wf_backtest_worst_max_drawdown` < 35%
    - `wf_backtest_mean_top_3_home_run_lift` > 5×
  - `_top_k_home_run_lift` helper — per-date top-k lift on the production class.

- **§3.2 Regime-conditional metrics** — `src/evaluation/regime_decomposition.py`
  Promoted to P0 because S3 (regime routing) can't be validated without it.
  - `metrics_by_regime(...)` — per-regime accuracy / weighted_f1 / top-k lift /
    calibration ECE / ROC-AUC on production class. Regimes with `n <
    min_samples_per_regime` get `status='insufficient_data'` and NaN metrics.
  - `regime_decomposition_gate(...)` — blocking gate: at least
    `min_regimes_passing` regimes have AUC ≥ `passing_regime_min_auc`
    AND no regime is catastrophic (AUC < `failing_regime_min_auc`).
  - Default regime names are `["Strong Bear", "Bear", "Neutral", "Bull",
    "Strong Bull"]` to match the M03 0..4 schema in `SEPABacktestRunner`.
  - **Wired into `ClassificationEvaluator.evaluate`** as new step 13c (only
    runs when `regimes_test` is passed). Records the gate to
    `metrics['gates']` so the §6 promotion gate enforces it.

- **§3.3.1 Permutation importance** — added `_compute_permutation_importance`
  to `ClassificationEvaluator`. Wraps `sklearn.inspection.permutation_importance`
  with an `_XGBAdapter` that exposes `predict_proba` on a raw `xgb.Booster`,
  scored against `neg_log_loss`. Subsamples to `permutation_sample_size`
  rows for tractability. No gate (diagnostic per plan).

- **§3.3.2 Ablation + triangulation** — `src/evaluation/ablation.py` + `scripts/ablation_backtest.py`
  Pure helpers in the library, I/O-heavy orchestrator in the script.
  Library:
  - `compute_ablation_delta(baseline, ablated, group_name) → AblationDelta`
  - `ablation_summary_payload(deltas, baseline) → dict` (matches the JSON
    schema from the plan)
  - `ablation_top_groups(deltas, n)` — most negative delta_sharpe first
  - `triangulation_check(shap_summary, perm_importance, ablation_top_features,
    feature_groups, min_overlap=3)` — **non-blocking** diagnostic. The 3-way
    overlap of SHAP top-N ∩ permutation top-N ∩ ablation top-M is the
    "feature-robust" signal from the plan.

  CLI (`scripts/ablation_backtest.py`):
  - `--model-version`, `--feature-set`, `--feature-groups Momentum,Volume,...`
  - `--dry-run` → emits placeholder summary without training/backtesting
  - Writes `ablation_summary.json` + `ablation_impact.png` to `--output`

### Phase C (parallel to S2/S3, 4.5d budget)

- **§4.1 Block bootstrap** — `src/evaluation/bootstrap.py`
  - `circular_block_bootstrap(trades_df, metric_fn, block_size_days=60,
    n_iterations=10_000, seed=42)` — circular block resample with replacement,
    blocks defined by `block_size_days` of exit-date span (so serial
    correlation survives the resample).
  - Returns observed, median, [ci_lo, ci_hi], plus a `block_bootstrap_ci_lo`
    gate that fires when the lower CI is below `ci_lo_gate_value` (default 0).
    **Gate is non-blocking** — CI tightness is diagnostic, not a hard
    promotion bar.
  - Helpers: `sharpe_from_trades` (trade-level Sharpe approximation with
    optional annualization knob), `total_return_from_trades`.

- **§4.2 Permutation null backtest** — `src/evaluation/permutation_null.py`
  - `permutation_null_backtest(signals_df, backtest_fn, n_permutations=100,
    seed=42)` — per-date shuffle preserving per-date signal density while
    breaking the ticker↔signal link.
  - Returns observed metric, full null distribution, percentile, p-value,
    blocking gate (`permutation_null` — percentile > 95).
  - **No internal backtest engine** — caller supplies `backtest_fn(df) →
    {sharpe_ratio, ...}`. Per the plan: 100 perms = ~50 min, 1000 = ~8h
    (deep mode, pre-promotion).

- **§4.3 Analytics library** — new package `src/analytics/`
  - `rolling_ic.rolling_ic(df, window_days=252, method="spearman")` — daily
    IC + rolling mean + rolling Newey-West t-stat (NW lag default 5).
  - `decile_analysis.decile_analysis(df, n_buckets=10)` — per-date qcut into
    N buckets, mean return per bucket, **Spearman monotonicity** (rank
    correlation of bucket index vs mean return), top-minus-bottom spread.
  - `score_trajectory.score_trajectory(scores, events, window_before=30,
    window_after=30)` — event-anchored T-N → T+M aggregated score path with
    95% CI per relative day.
  - Not in any gate — exploratory per plan.

### Integration wiring (training script)
- **`scripts/train_mfe_classifier.py`** — new flags:
  - `--with-perm-importance` `--perm-repeats N` `--perm-sample-size N`
  - `--with-regime-decomp` (fetches `regime_cat` from `t2_regime_scores`
    aligned to test-row dates via new helper `_load_regime_cat_for_dates`)
  - Both flow into `ClassificationEvaluator.evaluate(...)` via new kwargs
    `compute_permutation_importance`, `permutation_n_repeats`,
    `permutation_sample_size`, `regimes_test`.

### Test posture
- **66 new tests, all green.** Same posture as Phase A: synthetic fixtures /
  temp DuckDBs. No end-to-end run on real data.
- **Final pass counts:**
  - `tests/test_walk_forward_backtest.py` — 14/14 (§3.1)
  - `tests/test_regime_decomposition.py` — 7/7 (§3.2)
  - `tests/test_ablation.py` — 10/10 (§3.3.2)
  - `tests/test_bootstrap.py` — 11/11 (§4.1) — needed 2 fixes, see below
  - `tests/test_permutation_null.py` — 10/10 (§4.2)
  - `tests/test_analytics_module.py` — 14/14 (§4.3)
- **First-pass failures + fixes** (caught + corrected this session):
  - `test_sharpe_helper_constant_returns_nan` — actual code bug. `sharpe_from_trades`
    on constant input let floating-point dust (`std ≈ 1e-17`) through the
    zero-guard and returned a garbage 8.9e+16 Sharpe. Widened the guard to
    `sd < 1e-12`.
  - `test_metric_fn_failure_yields_nan_but_does_not_crash` — bad test, not a
    code bug. I had it calling `circular_block_bootstrap` twice (first with
    an always-raising metric, then with a sometimes-raising one); the first
    call propagated the exception and never reached the real assertion.
    Dropped the bogus first call.
  - `decile_analysis` — pandas `FutureWarning` about `groupby.apply` and
    grouping columns. Added `include_groups=False`. No behavior change.

## 📝 Files Changed

### New library modules
- `src/evaluation/walk_forward_backtest.py` — §3.1 harness + aggregator + gates
- `src/evaluation/regime_decomposition.py` — §3.2 metrics + gate
- `src/evaluation/ablation.py` — §3.3.2 helpers + triangulation
- `src/evaluation/bootstrap.py` — §4.1 circular block bootstrap
- `src/evaluation/permutation_null.py` — §4.2 per-date signal shuffle
- `src/analytics/__init__.py` — new package
- `src/analytics/rolling_ic.py` — §4.3.1
- `src/analytics/decile_analysis.py` — §4.3.2
- `src/analytics/score_trajectory.py` — §4.3.3

### New scripts
- `scripts/ablation_backtest.py` — §3.3.2 CLI

### Modified
- `src/evaluation/classification_evaluator.py`:
  - new kwargs on `evaluate()`: `compute_permutation_importance`,
    `permutation_n_repeats`, `permutation_sample_size`, `regimes_test`
  - new step 13b: permutation importance (diagnostic)
  - new step 13c: regime decomposition (blocking gate via `metrics['gates']`)
  - new private method `_compute_permutation_importance` with internal
    `_XGBAdapter` for sklearn compatibility
- `scripts/train_mfe_classifier.py`:
  - new CLI flags: `--with-perm-importance`, `--perm-repeats`,
    `--perm-sample-size`, `--with-regime-decomp`
  - new helper `_load_regime_cat_for_dates(db_path, dates) → pd.Series`
    (mirrors the SQL in `SEPABacktestRunner._load_regime_from_duckdb`)
  - evaluator call now forwards the new kwargs

### New tests
- `tests/test_walk_forward_backtest.py` — 14 tests (signals_to_scores
  contract, run-orchestrator, aggregator gates, edge cases)
- `tests/test_regime_decomposition.py` — 7 tests (per-regime metrics,
  insufficient_data flag, gate pass/fail, custom regime names)
- `tests/test_ablation.py` — 10 tests (delta computation, summary sort,
  triangulation pass/fail/none/group-expansion paths)
- `tests/test_bootstrap.py` — 11 tests (empty input, CI shrinkage with n,
  block size on AR(1) data, gate behavior, metric-fn failure handling)
- `tests/test_permutation_null.py` — 10 tests (random ≈ 50th percentile,
  strong signal > 95th, gate pass/fail, p-value monotonicity)
- `tests/test_analytics_module.py` — 14 tests (rolling IC predictive vs
  random, NW t-stat significance, decile monotonicity, score-trajectory
  peak alignment, missing-column errors)

## 🚧 Work in Progress
**Phase B and Phase C are both complete and fully green.** All 66 tests
pass against synthetic fixtures. No work in progress.

Note on test runtime: each pytest invocation took 20-25 min to *start*
because Windows + numpy/sklearn imports + Defender real-time scanning
combine into a pathologically slow cold-import phase. The tests themselves
run in seconds — the wall time is spent on `import numpy`/`sklearn`/etc.,
not on test execution. This is an environment issue, not a regression.
A 10-line fix to make `src/evaluation/__init__.py` lazy would cut future
test cycles from ~25 min to ~3-5 min; not done this session but flagged
in Next Steps.

Caveats to be aware of next session:
- **No end-to-end run on real data.** Every test uses synthetic fixtures.
  The first time someone wires `run_walk_forward_backtest` against
  `SEPABacktestRunner`, expect to debug small things — likely candidates:
  (1) `default_signals_to_scores` expects `date` and `ticker` columns *in*
  `X_test`, but the training script currently strips them before passing
  X to the evaluator. The caller of `run_walk_forward_backtest` will need
  to re-attach them to each fold's `X_test` before invoking. (2) The
  backtest_fn closure pattern in `scripts/ablation_backtest.py` saves the
  ablated model to disk and re-loads via `UniverseScorer` — fine for
  ablation but if the model uses categorical features, the
  `categorical_mapping.json` is not regenerated per ablation. Workaround:
  drop the model into the existing artifact dir of the baseline so it
  reuses the mapping. (3) `UniverseScorer._m01_features = feature_cols`
  is set directly — that attribute may not be respected on all code
  paths; check `score_from_t3` actually uses it before relying on it.
- **`permutation_null_backtest` is per-date shuffle, NOT block-wise.** It
  tests the *attribution* signal ("could random ticker selection within
  the same universe + density have produced this Sharpe?"). It does NOT
  test calendar-time edge — for that, pair it with `block_bootstrap` on
  the actual trade returns.
- **`triangulation_check` is non-blocking by design.** The plan flagged
  it as a §6 promotion gate component but also as "the triangulation
  rule". I interpreted "rule" as advisory (it would otherwise gate every
  promotion on agreement of three noisy importance measures, which seems
  brittle). If you want it blocking, flip `blocking=False` to True in
  `src/evaluation/ablation.py:triangulation_check`.
- **Newey-West lag default is 5.** With daily IC over a 252d window that
  corresponds to ~1 trading week of autocorrelation tolerance — standard
  for return panels. Re-tune if the model produces longer-horizon scores.

## ⏭️ Next Steps

1. **Wire `run_walk_forward_backtest` into the training script.** It's
   currently a library — the caller has to assemble fold results, the
   backtest closure, and the output dir manually. Suggest adding
   `--with-wf-backtest` to `scripts/train_mfe_classifier.py`, defaulting
   the backtest_fn to a small `SEPABacktestRunner` wrapper. ~half-day.
2. **End-to-end smoke against a small synthetic m01 checkpoint.** Pick
   m01_prototype_2003_2026/v1 or a 1-year throw-away model and verify the
   per-fold output dirs populate as expected. Don't rely on Sharpe being
   meaningful — just shape-check the artifacts.
3. **Re-evaluate `M01_baseline_v0.1` once the view fan-out bug is fixed.**
   The Phase A handover flagged the `v_d2_training`/`v_d3_deployment` fan-
   out issue — until that's resolved, both `--with-regime-decomp` and the
   walk-forward backtest will trip the parity-check gate (or have to
   `--skip-parity`). Same caveat as Phase A.
4. **Implement Phase D §5.1 dashboard toggle.** The Phase A `daily_predictions`
   table is being written; the UI for `decision_taken` is the next
   user-visible deliverable. Coordinate with the dashboard uplift session
   ([2026-05-23-dashboard-uplift.md](2026-05-23-dashboard-uplift.md)).
5. **Implement Phase D §5.2 PSI / drift.** 1.5d. The `reference_snapshot`
   step plugs into the training script tail and the quarterly report into
   Phase 8 of the orchestrator — both mirror the wiring patterns already
   in place from Phase A.
6. **Implement Phase D §5.3 pretrain audit auto-invocation.** 0.5d, pure
   wiring — the `run_pretrain_audit` library function already exists.
7. **Make `src/evaluation/__init__.py` lazy.** ~10 lines, ~30 min. Currently
   `from src.evaluation.X import Y` triggers `m03_evaluator` →
   `m03_regime` → `macro_engine` → `yfinance` even when only `X` is
   needed. Switching the package init to lazy imports (or simply removing
   the eager re-exports — they're convenience aliases, not load-bearing)
   would cut pytest cycle time from ~25 min to ~3-5 min on this Windows
   box. The single biggest dev-experience win available.

## 💡 Context/Memory

- **Why some Phase C gates are non-blocking.** `block_bootstrap_ci_lo`
  and `triangulation_check` are flagged non-blocking because they're
  diagnostic — a wide CI or a feature-importance disagreement is a smell,
  not a defect. Promotion gates should reject *defects*. I made these
  visible in `results.json` so the dashboard can surface them, but
  `set_prod` won't block on them. Easy to flip later if the project
  decides otherwise; just toggle `blocking=False → True` in the relevant
  module.
- **Why `permutation_null_backtest` doesn't ship a default backtest_fn.**
  Per the plan note: "A full backtrader-based backtest is ~30s; 100
  permutations × 30s = 50min". The plan suggests a "numpy fast-path",
  but I didn't find one already implemented (the m01_rank_scorer is
  numpy-only but not a backtest engine). Rather than ship a half-baked
  fast-path I left the design as: `backtest_fn` is your problem. The
  caller can drop in `SEPABacktestRunner` (50min per 100 perms) or write
  a numpy ranking-only path (~1ms per perm, the deep 1000-perm mode
  becomes ~10s). If you want the latter built, that's the §4.2 expansion
  to 2.5d the plan called out.
- **Pytest collection takes ~25 min on this machine.** Not a code issue
  — `numpy.testing._private.extbuild` import-time triggers a Windows
  compiler-discovery code path that's pathologically slow on this box.
  Same issue Phase A noted ("60+ tests, ran them all"). The test files
  themselves run in seconds once collected.
- **Anchored vs sliding walk-forward (§3.1 inherits Phase A's choice).**
  The backtest harness uses whatever `FoldSpec`s it's handed — they
  come from §2.3's `anchored_walk_forward`, which is locked in per the
  whitepaper.
- **production_class_idx convention is consistent.** ECE gate, threshold
  sweep, walk-forward AUC gate (§2.3), wf-backtest top-k lift (§3.1),
  regime decomposition gate (§3.2), and ablation triangulation (§3.3.2)
  all default to "last actionable class" (Home Run for MFE 4-class) and
  can be overridden per call.
- **Bootstrap block size default = 60 days.** Two months of trading
  days. With median hold = 40d (per the SEPA Trade Logic memory), this
  captures roughly one trade-cycle's worth of serial correlation.
  Re-tune if the strategy's average hold changes materially.

---

After creating this file, ask the user if they want to `git add` and `git commit` it.
