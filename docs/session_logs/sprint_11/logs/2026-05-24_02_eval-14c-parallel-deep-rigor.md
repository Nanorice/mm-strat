# Session Handover: 2026-05-24 — Eval §1.4(c) Deep-Rigor on m01_prototype_may/v2_gated

## 🎯 Goal
Run the §1.4(c) parallel "deep rigor pass" from
`docs/plans/eval_14c_parallel_session_instructions.md` — produce a formal
demote/hold/promote verdict on the 4-class MFE model backed by bootstrap CI,
permutation null, ablation, per-regime AUC, and decile analysis.

## ✅ Accomplished
- **§1 Bootstrap CI** (10,000 iter, circular block, block=60d): observed
  Sharpe 0.334; **95% CI [-1.29, +1.85]** — straddles zero. Return CI
  similarly diffuse. ❌ fail.
- **§2 Permutation null** (200 perms, vectorized engine): observed Sharpe
  **-0.42**; null median +0.43; observed sits at **percentile 2.0** of null
  distribution (bottom 2% — *worse than random*). ❌ fail (catastrophic).
- **§4 Per-regime AUC** (extracted from `results.json`): Bear 0.665, Neutral
  0.735, Bull 0.716, Strong Bull 0.721. Strong Bear had 0 test samples.
  **4/4 evaluable regimes pass 0.55 threshold.** ✅ pass (surprising).
- **§5 Decile IC** (348 WF trades): **Spearman IC = -0.135, p = 0.012** —
  negative & statistically significant. Top decile P(HR)=8.6% vs bottom 0%,
  middle deciles (3-4) carry the only positive mean PnL. Non-monotone. ❌ fail.
- **§3 Ablation** — COMPLETED (9 groups, ~70 min wallclock).
  Baseline (all 97 features): Sharpe 1.045, total return +197.98%, max DD 34.5%.

  | Group dropped | Features | Δ Sharpe | Δ Return | Verdict |
  |---|---:|---:|---:|---|
  | Core_Volume | 9 | **-0.569** | -153.6pp | load-bearing |
  | Fundamentals | 21 | **-0.511** | -143.9pp | load-bearing |
  | Momentum_RS | 20 | **-0.412** | -125.2pp | load-bearing |
  | Moving_Averages | 6 | -0.265 | -95.6pp | meaningful |
  | Categoricals | 2 | -0.228 | -86.0pp | meaningful |
  | M03_Regime | 7 | -0.223 | -84.3pp | meaningful |
  | Fast_Alphas | 14 | -0.121 | -66.3pp | minor |
  | Technical_Oscillators | 4 | +0.012 | +6.7pp | neutral |
  | **Volatility_Ranges** | 14 | **+0.131** | +14.0pp | **hurts** (removing helps) |

  Action items for binary reformulation:
  - **Drop Volatility_Ranges** (or put it behind importance pruning)
  - **Treat Technical_Oscillators as expendable**
  - **Protect Core_Volume, Fundamentals, Momentum_RS** in any selection step

- **§6 One-pager final** at
  `models/m01_prototype_may/v2_gated/evaluation/full_eval/full_eval_report.md`.
  Verdict: **DEMOTE.** All 6 sections filled with final numbers.

## 📝 Files Changed / Created

### New scripts
- `scripts/run_bootstrap_ci.py` — circular block bootstrap CI on WF trades.
  Output: `…/full_eval/bootstrap_ci.json`. Done.
- `scripts/run_permutation_null.py` — per-date shuffle null test, uses
  `VectorizedSEPABacktest` for tractable runtime (~3 min for 200 perms).
  Output: `…/full_eval/permutation_null.json`. Done.
- `scripts/run_decile_analysis.py` — decile bucketing on `prob_elite` vs
  `pnl_percent` from WF trades. Output: `…/full_eval/decile_analysis.json`. Done.

### Edited
- `scripts/ablation_backtest.py` — three bit-rot fixes so the existing CLI
  could run against the current trainer API:
  1. Renamed import `DEFAULT_HYPERPARAMS` → `_xgb_params_for_n_classes(4)`
  2. `create_mfe_labels(df, bins=[2.0, 10.0, 30.0], …)` (bins now required)
  3. Each tmp model now lives in its own subdir with sibling
     `metadata.json` and `categorical_mapping.json` so `UniverseScorer.load_model()`
     reads the per-ablation feature list (it ignored `_m01_features` override
     and tried to look up M01 in `model_feature_sets`).
  4. Added TitleCase rename for cross-sectional rank features
     (`rs_sector_rank` → `RS_Sector_Rank` etc.) — `model_feature_sets`
     stores lowercase but `daily_features` UPDATE writes TitleCase.

### Generated outputs (under `models/m01_prototype_may/v2_gated/evaluation/full_eval/`)
- `bootstrap_ci.json` ✅
- `permutation_null.json` ✅
- `regime_decomposition.json` ✅ (extracted from `results.json`)
- `decile_analysis.json` ✅
- `ablation/` (partial — populated as the run progresses; each completed group
  has a subdir with `model.json`, `metadata.json`, `categorical_mapping.json`)
- `full_eval_report.md` ✅ draft; needs final ablation table

## 🚧 Work in Progress (CRITICAL)

Nothing in-flight. All 6 sections of the one-pager are complete with final
numbers. Verdict is DEMOTE. Engine-dependence finding is documented in both
the report (§2 Engine-dependence caveat table) and §3 reconciliation.

## ⏭️ Next Steps

1. **Hand the one-pager + ablation findings to the binary-reformulation
   main session.** The most actionable carries:
   - **Drop Volatility_Ranges** from the binary feature set (or put it
     behind importance-based pruning).
   - **Treat Technical_Oscillators as expendable** — neutral on Sharpe,
     small dimensionality win.
   - **Protect Core_Volume, Fundamentals, Momentum_RS** in any
     feature-selection / regularization step — they carry 40-55% of
     the BackTrader Sharpe each.
   - **The decile-IC anti-correlation inside the operating zone is a
     strategy/operating-point issue, not (only) a label-boundary issue.**
     If the binary model also shows top-percentile being anti-skilled at
     realized PnL, look at exit/sizing rules first, not the label.

2. **Resolve the engine-dependence finding** — vectorized vs BackTrader
   give opposite verdicts on the same model. Worth a small targeted study
   on which engine's exit rules are "right" before relying on either for
   the binary model's go/no-go decision.

3. **(Optional) Re-run `populate_feature_catalog.py`** — the catalog has
   `rs_sector_rank` etc. in lowercase, but DuckDB returns TitleCase from
   `daily_features`. Worked around in `scripts/ablation_backtest.py` with
   a hardcoded rename map; cleaner fix is in the catalog populate script
   or in `model_feature_sets` migration.

4. **(Optional) Refactor `UniverseScorer.load_model()`** — currently it
   refuses to use the caller-supplied `_m01_features` override unless a
   sibling `metadata.json` exists. Worked around in the ablation CLI by
   writing tmp `metadata.json` files; cleaner to honor the override
   when set by the caller.

## 💡 Context/Memory

- **DuckDB lock surprise.** Initial run was blocked because `streamlit run
  scripts/dashboard.py` (PID 37848, running since 14:27) had the DB in write
  mode — NOT the parallel binary-training session as initially assumed.
  Found via `wmic process where "ProcessId=N" get CommandLine`. The dashboard
  is a long-running write-mode connection — worth flagging in CLAUDE.md or
  pre-eval checklist.

- **`v_d2_training` view is a JOIN bomb on bare SELECT \*** — `t3_sepa_features`
  is 9M rows. Read-only connect was hanging at 18GB memory before. Use
  `d2_training_cache` (materialized, ~38K rows, ~70x faster) for any
  per-fold rescore work. The permutation null script was rewritten to use
  the cache and went from "hangs at 25min" to "completes fold queries in
  <1s each".

- **`UniverseScorer.load_model()` ignores `_m01_features` overrides** —
  it looks up M01 features from DuckDB via `get_model_features('M01')` when
  no `metadata.json` exists next to `model.json`. The ablation CLI had been
  setting `scorer._m01_features = feature_cols` AFTER `load_model()`, but
  `load_model()` raises `RuntimeError("No prod model found for 'M01'")` before
  the override runs. Fix: write `metadata.json` next to each tmp model with
  the correct `valid_features` list, so the metadata-first code path wins.

- **`ablation_backtest.py` was bit-rotted** when I started — three API
  drift errors stacked on top of each other (`DEFAULT_HYPERPARAMS` removed,
  `create_mfe_labels` requires `bins`, catalog returns lowercase rank names).
  All three patches in place now. Worth a follow-up commit to make this
  CLI a first-class citizen for the binary reformulation work too.

- **Vectorized vs BackTrader engine disagreement is real signal, not noise.**
  Two engines, same model, same signals, opposite verdicts on whether the
  features carry value. The vectorized engine's stricter exit rules (single
  stop, single trend, single trade per ticker) may be exposing the model's
  weakness; BackTrader's multi-tranche scaling may be hiding it. Either way,
  "the model adds value" is conditional on which exit rule you trust.
