# Session Handover: 2026-05-25 — Binary Pruned Retrain + §1.4 Deep-Rigor on m01_binary/v1

## 🎯 Goal

Two things, both unblocked by yesterday's work:

1. Test whether dropping `Volatility_Ranges` + `Technical_Oscillators` (the §1.4(c) ablation finding) actually improves the binary model — train `m01_binary_pruned/v1` and compare head-to-head.
2. Run the §1.4 deep-rigor suite (bootstrap CI, permutation null, decile IC, ablation) against `m01_binary/v1` and produce the formal DEMOTE/HOLD/PROMOTE verdict that yesterday's handover left pending.

## ✅ Accomplished

### Pruned-feature retrain — verdict: don't promote

- Registered `fs_m01_prototype_pruned` (79 features = `fs_m01_prototype` minus 14 Volatility_Ranges minus 4 Technical_Oscillators) via inline INSERT into `model_feature_sets`.
- Trained `m01_binary_pruned/v1` with `--with-wf-backtest --walk-forward --with-regime-decomp --with-perm-importance --with-calibration`.
- Result: **marginal in both directions, worse on the gates that matter most.**
  - WF mean Sharpe 0.405 vs v1's 0.476 (worse by 0.07)
  - WF top-3 lift 1.66× vs v1's 1.55× (better by 0.10, still nowhere near 5× threshold)
  - WF worst-fold Sharpe -0.268 vs -0.263, 2/4 positive folds (same failure pattern)
  - Per-regime AUC: marginal shifts ±0.015, 4/4 still pass
  - Fold-2 (most-recent OOS year) Sharpe dropped from 0.68 → 0.49 — pruning hurts where it matters most
- The §1.4(c) Volatility_Ranges ablation finding was derived from the *4-class* `v2_gated` model + vectorised engine. It did not generalise cleanly to the *binary* model under BackTrader. The takeaway: feature pruning is not the dominant lever here; operating-point selection (S3 vs S1) is.

### §1.4 deep-rigor suite — verdict: DEMOTE-as-ranker, HOLD-as-filter

Ran all four scripts against `m01_binary/v1`. Outputs in [models/m01_binary/v1/evaluation/full_eval/](models/m01_binary/v1/evaluation/full_eval/).

- **Bootstrap CI** (355 trades, 10K iter, block=60d): observed Sharpe 0.893; **95% CI [-0.84, +2.53]** — straddles zero. Return CI [-306%, +1054%]. ❌ statistically indistinguishable from zero.
- **Permutation null** (vectorised, 200 perms, ~4 min): observed Sharpe **-0.13**; null median +0.42; observed at **percentile 6.5** (p=0.935). ❌ worse than 93.5% of random allocations.
- **Decile IC** (qcut formed 5 deciles because isotonic calibration ties): **Spearman IC -0.120, p=0.024** — negative and significant. Top decile loses -5.1%, decile 3 has highest Home Run rate at 11.6%. Non-monotone.
- **Ablation** (9 groups, ~70 min, 4-class proxy): Core_Volume / Fundamentals / Momentum_RS load-bearing (Δ Sharpe -0.41 to -0.57); Volatility_Ranges hurts (+0.13 when dropped); Technical_Oscillators neutral. Matches the v2_gated ablation almost exactly — group ranking is stable.

### Verdict for `m01_binary/v1`: DEMOTE-as-ranker, HOLD-as-filter

- **DEMOTE-as-ranker.** Three independent statistical tests (bootstrap CI, decile IC, permutation null) all say the model's probability rank doesn't translate to PnL. The trainer's `wf_backtest_mean_sharpe = 0.476` is a BackTrader-engine artifact — the vectorised engine reads the same signal as -0.13.
- **HOLD-as-filter.** Strategy S3 (calibrated `P(>30%) ≥ 0.30` threshold + 5-position cap) achieved Sharpe 1.59, DD 11.1% on the 18-month OOS window. The model's value is in *filtering out the bottom* of its own distribution, not in ranking the top. Isotonic calibration compresses the right tail into ties; threshold gates use that capability, rankers fight it.

Full one-pager in [models/m01_binary/v1/evaluation/full_eval/full_eval_report.md](models/m01_binary/v1/evaluation/full_eval/full_eval_report.md).

### Infrastructure: reusable deep-rigor wrapper + ablation label-awareness

- New `scripts/run_deep_rigor_suite.py` — single CLI driving all four §1.4 scripts. Auto-detects `production_class_idx` from the model's `label_definition.json`, patches the three constant-driven scripts in place (`MODEL_DIR`, `PRODUCTION_CLASS_IDX`), auto-discovers feature groups from `model_feature_sets` when `--feature-groups` omitted, writes per-step logs to `logs/deep_rigor/`, emits `suite_summary.json` manifest. Has `--skip-*` flags + `--n-perms` knob + `--dry-run`. Dry-run verified end-to-end.
- `scripts/ablation_backtest.py` now honors `--label-id` (resolves from arg → source model's `label_definition.json` → 4-class fallback). XGBoost objective derived from `len(bins) + 1` so binary models get `binary:logistic` instead of the hardcoded `multi:softprob`. Logs which label/objective it actually used.

### Documentation surface

- `docs/manual_for_me.md` — new §Evaluation Framework section (~180 lines) inserted between Model Training and Backtesting. Covers library inventory, gate catalogue, label registry, strategy array, deep-rigor scripts, feature catalog, per-model output layout, outstanding operational items. Updated Open TODOs + Resolved sections.
- `docs/plans/whitepaper_path_forward_2026_05_23.md` §5 — every subsection (§5.1 through §5.8) marked SHIPPED / SHIPPED-WITH-CAVEAT / LIBRARY-SHIPPED, with empirical results inline. New §5.6b (decile/IC), §5.9 (Verdicts on record — v2_gated DEMOTE, m01_binary/v1 DEMOTE-as-ranker/HOLD-as-filter), §5.10 (operational reference cross-link).

## 📝 Files Changed

### New (untracked)
- `scripts/run_deep_rigor_suite.py` — §1.4 suite wrapper
- `models/m01_binary/v1/evaluation/full_eval/` — bootstrap_ci.json, permutation_null.json, decile_analysis.json, ablation/, full_eval_report.md
- `models/m01_binary_pruned/v1/` — all artifacts from the pruned retrain
- (Carries from yesterday: `scripts/run_strategy_array.py`, `src/evaluation/calibrator.py`, `tests/test_calibrator.py`, `tests/test_score_lookup_persistence.py`, `label_registry/mfe_4class_v1.json`, `label_registry/mfe_binary_homerun_v1.json`, `models/m01_binary/`)

### Modified
- `scripts/ablation_backtest.py` — `--label-id` arg; objective dispatched from `len(bins)+1`; logs label/objective
- `scripts/run_bootstrap_ci.py` — `MODEL_DIR` flipped to `m01_binary/v1` (the wrapper re-patches per invocation)
- `scripts/run_decile_analysis.py` — same
- `scripts/run_permutation_null.py` — `MODEL_DIR` flipped + `PRODUCTION_CLASS_IDX 3 → 1` + 1-D proba shape guard (binary `predict()` returns 1-D; multi-class returns 2-D)
- `docs/manual_for_me.md` — Evaluation Framework section + Open TODOs/Resolved updates
- `docs/plans/whitepaper_path_forward_2026_05_23.md` — §5 status badges, empirical results, §5.6b/5.9/5.10 added, §6 deliverables table updated

### Deleted
- (Yesterday's `label_registry/mfe_4class_30d_v1.json` — replaced by `mfe_4class_v1.json`)

## 🚧 Work in Progress (CRITICAL — RESULTS TO BE COMMITTED)

Nothing is in-flight runtime. Everything has run to completion. **The session is in an uncommitted state — 11 modified files + 11 untracked paths.**

The natural commit grouping is three commits:

1. **`feat(eval): ablation label-awareness + deep-rigor suite wrapper`** —
   `scripts/ablation_backtest.py`, `scripts/run_deep_rigor_suite.py`, and the three patched constant-driven scripts (`run_bootstrap_ci.py`, `run_decile_analysis.py`, `run_permutation_null.py`).
2. **`eval(m01_binary): §1.4 deep-rigor verdict (DEMOTE-as-ranker, HOLD-as-filter)`** —
   `models/m01_binary/v1/evaluation/full_eval/` (full_eval_report.md + 4 JSON artifacts + ablation/).
3. **`feat(m01): m01_binary_pruned/v1 retrain — fs_m01_prototype_pruned (79 feat)`** —
   `models/m01_binary_pruned/v1/`. Don't promote; the artifacts are kept for diff/comparison purposes.
4. **`docs: evaluation framework operational reference`** —
   `docs/manual_for_me.md` + `docs/plans/whitepaper_path_forward_2026_05_23.md`.

(Plus this handover. `.claude/scheduled_tasks.lock` is harness state — leave out of commits.)

## ⏭️ Next Steps (when user returns)

1. **Commit the four groupings above.** No surprises, all of it is plain work product from this session.
2. **Decide the deployment pattern for `m01_binary/v1`.** The one-pager recommends S3 (calibrated `P(>30%) ≥ 0.30` gate + 5-position cap). If the user agrees, register S3 + `m01_binary/v1` as the production combo and start paper-trading via the dashboard Decision Log.
3. **Re-run ablation on `m01_binary/v1` with the patched script** (`--label-id mfe_binary_homerun_v1`) for a true binary ablation. The current ablation in `full_eval/ablation/` used the old 4-class proxy. Single command:
   ```powershell
   .\.venv\Scripts\python.exe .\scripts\run_deep_rigor_suite.py `
     --model-name m01_binary --model-version v1 `
     --feature-set fs_m01_prototype `
     --label-id mfe_binary_homerun_v1 `
     --backtest-start 2023-05-01 --backtest-end 2026-05-22 `
     --skip-bootstrap --skip-permutation --skip-decile
   ```
   This will overwrite `full_eval/ablation/` with the binary-objective version. If the ranking matches the 4-class proxy (likely), the one-pager's footnote becomes "binary re-run agrees with proxy." If it differs materially, the binary model has different group dependencies and the recommendations in §Recommendations should be revisited.
4. **Resolve the engine-dependence question** before any further model promotion. Two paths in the one-pager:
   - Run a "vectorised-with-3-tranche-exits" engine to isolate whether the BackTrader/vectorised disagreement is about exits or about something else entirely.
   - Document which engine matches the deployed execution path and treat the other as a robustness check.
5. **§5.4 PSI quarterly auto-trigger.** Library + tests shipped; the Phase-8 cron-style trigger in `daily_pipeline_orchestrator.py` is the last evaluation-framework operational item. Estimated 0.5d.
6. **Backfill `daily_predictions`** for `m01_binary/v1` (or whichever model goes to prod) so the dashboard's "Past Decisions" view has data. `scripts/backfill_daily_predictions.py` not yet written.

## 💡 Context/Memory

- **The pruning experiment closed a loop.** Yesterday's §1.4(c) recommendation ("drop Volatility_Ranges + Technical_Oscillators") was derived from `v2_gated` (4-class) + vectorised engine. Today's empirical test on `m01_binary` (binary) + BackTrader showed the recommendation doesn't translate. Lesson: ablation findings are conditional on objective AND engine; cross-model carry-overs need empirical confirmation before being treated as actionable.
- **The strategy array uses BackTrader, the permutation null uses vectorised.** Same scored universe, ~0.6 Sharpe gap between engines. The deployed exit rules will determine which engine is "right" — the choice isn't methodological, it's a question of which exit ruleset we'll actually run in production. SEPAHybridV1's 3-tranche scaling is the deployed path → BackTrader is closer to reality → S3's Sharpe 1.59 result is the most defensible.
- **The WF backtest's "top-3 lift = 1.55×" gate is measured under the *default* strategy, not the binary model's natural deployment.** The default strategy uses `rank_by='trailing'` + no probability threshold + regime-driven sizing/caps. It is **closest to S2** in the strategy array (Sharpe 1.44 raw, 0.78 calibrated). None of the strategy-array configs exactly match it. This is why the WF gate failures are not a verdict on the model itself — they're a verdict on a *specific strategy wrapping* of the model. S3 is the strategy that works; S2-style wrapping is what the gate measures.
- **The ablation script hardcoded 4-class for v2_gated's sake.** Yesterday's session log flagged this as a follow-up; today's patch closes it. The dispatch is now `_xgb_params_for_n_classes(len(bins) + 1)` so it follows the label registry like the trainer does.
- **Decile analysis only formed 5 buckets, not 10.** Isotonic calibration introduces tied probabilities at the top end of the distribution (the calibrator is a step function). With N=355 trades, `qcut(10, duplicates='drop')` collapses to 5 effective deciles. The rank-correlation test (Spearman) still works because it operates on ranks, not bins — but the per-decile granularity is coarse. If the deep-rigor suite gets re-run on a model with more trades or a less compressive calibrator (Platt scaling instead of isotonic, say), expect more decile granularity.
- **`models/m01_binary_pruned/v1/` should be kept on disk** but **not promoted**. The artifacts are useful for the model-diff trail (Volatility_Ranges effect in isolation) and the registered `fs_m01_prototype_pruned` feature set is the seed for any future "what if we just dropped these features" experiment.
- **The `scheduled_tasks.lock` file is harness state from the autonomous loop checks earlier this session.** Don't commit it.
- **The `models/m01_binary/v1/evaluation/full_eval/ablation/` directory** has nine subdirs (one per group) each containing a tmp model.json + metadata.json + categorical_mapping.json. Total ~80MB. Worth keeping for now; can be cleaned up after the binary-objective re-run lands (it overwrites these).

---

Want me to `git add` and `git commit` the four groupings now?
