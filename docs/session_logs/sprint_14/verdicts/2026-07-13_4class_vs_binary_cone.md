# Verdict — is the deployed 4-class m01_prototype actually the best model? NO.

**Date**: 2026-07-13 · **Sprint**: 14 · **Status**: ✅ CLOSED — binary dominates the 4-class prod model.

## Question (user)
The prod model is `m01_prototype` (4-class softmax; strategy uses `prob_elite = prob_class_3`).
The champion was chosen in the *old* selection method — **without adjusting the score threshold**.
Is the 4-class model actually better, or would a binary / no-macro variant win once the threshold
is swept? Also: is `industry` the top feature (as the EDA claimed)?

## Method
Honest bar-by-bar **start-date cone** (13 folds, starts 2004→2022 every 18mo, each held to
2026-06-30), shared strategy infra (top-3/day, SL10%, SMA50 exit, 252d hold), **SEPA entry gate
ON** (trend_ok∧breakout_ok — the population-inflation trap that invalidated the sprint-13 arena).
Each model scored via `UniverseScorer.score_from_t3` (unlock: **prototype v2 IS now t3-loadable** —
old memory said it wasn't). Swept `min_prob_elite ∈ {0, .10, .15, .20, .25, .30}` per model.
Ranked by **cone median Sharpe + floor + %neg**, NOT label lift (memory:
[[project_population_reframe_tail_ranker]] — label lift ≠ trade edge). `cells/model_cone.py`,
`verdicts/2026-07-13_4class_vs_binary_cone.csv`.

Cross-model threshold-comparison caveat: 4-class `prob_class_3` and binary `P(pos)` live on
different scales, so an absolute shared threshold isn't apples-to-apples. Two honest reads:
the **threshold-free top-3 rank** (thr=0) for cross-model, and **each model's own best threshold**.

## Result — MEDIAN SHARPE (13-fold cone)

| model | thr=0 | 0.10 | 0.15 | 0.20 | 0.25 | 0.30 | best | floor@best | %neg@best |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **binary** | 0.43 | 0.53 | 0.58 | 0.75 | **0.81** | 0.68 | **0.81** @.25 | **+0.41** | **0%** |
| prototype_4cls (PROD) | 0.39 | 0.40 | 0.43 | 0.45 | 0.45 | 0.52 | 0.52 @.30 | +0.05 | 0% |
| binary_no_macro | 0.14 | 0.20 | 0.21 | 0.22 | 0.39 | 0.40 | 0.40 @.30 | +0.01 | 0% |
| no_macro_4cls | 0.15 | 0.17 | 0.18 | 0.18 | 0.22 | 0.30 | 0.30 @.30 | −0.53 | 31% |

## Findings
1. **Binary beats the 4-class prod model at EVERY threshold**, threshold-free included (0.43 vs
   0.39 rank-only). At each model's own best cut: **binary 0.81 (floor +0.41, 0% neg) vs 4-class
   0.52 (floor +0.05, 0% neg)** — a +0.29 median-Sharpe gap AND a far higher floor (+0.41 vs +0.05).
   The win is robust across the cone, not a two-fold fluke (binary is 0%-neg at *every* threshold).
2. **The champion selection had a real blind spot.** Binary's edge is threshold-DEPENDENT: nearly
   invisible at rank-only (0.43 vs 0.39) but large by thr=0.25 (0.81 vs 0.45). A bake-off at one
   fixed operating point (the old method) could easily have missed it. Sweeping the threshold —
   the exact thing that wasn't done — is what surfaces the binary advantage.
3. **Macro (M03 features) matters, a lot.** Both no-macro variants are far worse (binary_no_macro
   0.40, no_macro_4cls 0.30 at best) — dropping macro roughly halves the edge and wrecks the floor.
   The macro-inclusive binary is the clear winner. (Note: model-level macro FEATURES ≠ the weather
   gauge's macro GATE — different mechanism.)
4. **Raising the threshold helps every model's median here** — but this is the SL10%/SMA50 exit,
   NOT the champion strategy's trail-exit. Q47 ([[project_prob_elite_gate_variance_knob]]) found the
   gate is a variance knob that COSTS median/tail on the *champion's* exit. No contradiction: this
   cone measures a different exit regime. **Do NOT read "raise the gate" as a champion-strategy
   change** — that was already settled the other way for the trail exit.
5. **Feature importance (industry Q):** in the 4-class prod model, `industry` IS effectively #1 —
   by **total_gain (#1/97)** and **split-count (#1/97, 1748 splits)**, though only #12 by per-split
   gain. Classic high-cardinality-categorical signature; consistent with the EDA's industry-tail
   claim. `sector` is near-dead (#59–76) — signal is at industry granularity, not sector.

## Caveats / what this is NOT
- This is a **model-ranking** cone on a SIMPLE exit (SL10%/SMA50), not the champion trail-exit
  strategy. Binary winning the model cone ≠ binary winning the deployed strategy — that needs a
  BackTrader confirm on the champion exit (memory: [[project_vec_engine_optimistic]] — vec cones
  are within-engine ranking only; promote on BackTrader). The vec engine is optimistic in bear
  folds; the START-DATE CONE partly controls for this but doesn't replace the BT confirm.
- Absolute thresholds aren't cross-model comparable; trust the threshold-free rank + each model's
  own sweep, not a shared-threshold column read across rows.

## Recommendation (for user decision — not auto-promoted)
The binary model is a **strong deploy-candidate to replace the 4-class prototype**, pending a
BackTrader confirm on the CHAMPION trail-exit (the last-mile gate every promotion has passed). If it
holds there, swap is cheap: `set_prod(<binary_version>)` + `backfill_daily_predictions` (the
shortlist/serving layer is model-agnostic, [[project_weather_gauge_shortlist]]). Also decide the
binary's operating threshold as part of the swap — its edge is threshold-sensitive.

## Follow-ups
- ⏭️ **BackTrader confirm binary on the champion trail-exit** (the real kill/keep gate).
- ⏭️ The binary's own threshold is a live knob (0.25 best here) — tune it on the champion exit, not this one.
- Note: `m01a_tail` (tail-magnitude) NOT re-run — already CLOSED at M4 (lost the BT cone to incumbent).
