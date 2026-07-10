# M3 verdict — ML ranker ties the RS-only bar: kill criterion #2 fires, ship the one-column RS rule

**Date:** 2026-07-10 · **Status:** ❌ M3 gate FAILS (a *valid* outcome per the plan) —
`../plans/m01a_tail_ranker_plan.md` kill criterion #2. Parent: `2026-07-10_m1_label_m2_rs_baseline.md`.

## Setup (scoped with the user before training)

- **Trainer:** `scripts/train_m01a_tail.py` (m02-trainer pattern: registry feature set, anchored WF,
  per-fold checkpoints, `--smoke` first). Label recomputed from the canonical
  `label_registry/m01a_tail_v1.json` `source_query` — never re-derived.
- **Variants:** `reg:tweedie` (power 1.5) on `tail_mag_63` + `binary:logistic` on `home_run_63`
  (the bins=[30] diagnostic). **No class reweighting** — the imbalance is the signal.
- **Features:** `fs_m01_prototype` ∩ `t3_training_cache` = **86 of 97** (11 `*_delta` cols not in the
  cache, dropped — same availability-intersection as the m02 trainer).
- **Split:** anchored walk-forward, train 2003→, test 2012→2026-04 in 1Y steps = **15 OOS folds**,
  embargo 100 calendar days (~63 trading bars, the LeakageGuard bridge).
- **Metric:** pooled per-fold top-decile / top-5% `tail_mag_63` lift (per-date PERCENT_RANK), computed
  IDENTICALLY for the model score and for `rs_universe_rank` on the same fold → apples-to-apples margin.
- Matrix: 1,611,203 rows (exactly the label panel — 1:1 cache↔label join). Run dir:
  `models/m01a_tail/20260710_124110/`.

## Result — a wash, with a temporal break

| variant | D10 lift mean | RS D10 mean | folds beating RS | worst margin |
|---|--:|--:|--:|--:|
| tweedie | 3.88× | 3.87× | 7/15 | −1.16 |
| binary | 3.93× | 3.87× | 8/15 | −1.19 |

- **Mean margin ≈ 0** (+0.01 / +0.06 D10; top-5% RS slightly ahead for tweedie, tied for binary).
  Half the folds negative, worst fold −1.2×. This does not "beat RS by a margin that survives
  start-date variation" — the gate fails cleanly.
- **The break is temporal, not noise:** both variants beat RS in **6/7 folds 2012–2018** (margins up
  to +1.50) and lose in **13/16 variant-folds 2019–2026** (worst 2021: −1.16/−1.19). Anchored WF means
  the later folds train on MORE data — the decay is not data scarcity; whatever the extra 85 features
  added over RS pre-2019 has since decayed or inverted (2020–21 regime is the worst stretch for both).
- **Objective-agnostic:** tweedie and binary produce near-identical fold-by-fold margin patterns
  (agree on sign in 13/15 folds) — the binding constraint is the feature set / population, not the
  loss. No tuning was attempted, deliberately: RS ties an *un-tuned* model; tuning to scrape out a
  +0.1 margin is exactly the "force the ML" failure mode the plan forbids.

## Decision

**Ship the one-column RS rule as the m01a selection signal** (plan kill criterion #2). The M2 bar
stands as the production spec: rank the `trend_ok` panel by `RS_Universe_Rank`, top decile ≈ 3.5×
tail_mag lift, top-5% ≈ 4.2×, stable across date-thirds. No model registration — `m01a_v1_h63`
fold models remain in the run dir for archaeology only.

**M4 consequence:** selection = top-X% *RS* on the trend panel (not an ML score); entry trigger =
breakout/VCP; exit = SEPA trail. Judge on the start-date cone + BackTrader as planned.

Not pursued (out of scope, noted): whether a model ranks WITHIN the RS top decile — prior evidence
says within-pool rankers are weak ([[project_breakout_pool_refinement]] IC≈−0.03), and the plan's
question was full-panel selection, which is now answered.

## Reproduce

- Smoke: `.venv/Scripts/python.exe scripts/train_m01a_tail.py --smoke` (~10s, path check only).
- Full: `.venv/Scripts/python.exe scripts/train_m01a_tail.py` (~30 min, 2 variants × 15 folds,
  checkpointed/resumable). Summary: `models/m01a_tail/20260710_124110/summary.json`.
