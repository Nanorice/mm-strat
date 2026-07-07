# Verdict: the "gate-not-ranker" finding is largely a calibrator artifact

> **⚠️ UPDATE 2026-07-07 (later same day) — WFO OVERTURNS THE FIX.** The body below argues for
> "rank on raw p_pos" (fix b). A walk-forward reconciliation refuted it: **calibrated BEATS raw
> OOS, aggregate Sharpe 0.91 vs 0.79** over 3 rolling folds / 744 stitched days
> (`run_strategy_wfo.py … --train-years 2 --test-years 1 --n-trials 60`, with/without `--raw-prob`;
> artifacts `models/m01_binary/wfo/{calibrated,raw}/`). The `_raw`-wins evidence cited in step 5
> was a single IS/OOS split (overfit-prone). **Decision: KEEP calibrated `rank_by='prob_elite'`;
> fix (b) rejected.** The calibrator's flattening is real but doesn't cost OOS performance because
> the edge is the GATE (both arms share it) and the within-pool pick is near-interchangeable
> (within-day IC≈0). Real lever = sector triage, see the breakout-pool-refinement verdict. The rest
> of this doc is preserved as the reasoning trail; read it with this correction in mind.

**Date:** 2026-07-07 · **Status:** ✅ strong (live decile test + existing backtest pairs agree)
**Feeds:** Sprint 14 Q1 (selection bias) — overturns the mechanism, changes the fix.
**Artifacts:** [cells/model_output_eda_cells.md](../cells/model_output_eda_cells.md),
`data/model_output_eda/`, `models/m01_binary/v1/backtests/` (pre-existing raw-vs-cal pairs).
**Memory:** [[project_isotonic_flattens_ranking]].

## What triggered this
While pulling data to characterise the top-5 selection bias, the champion's `prob_elite` was
found to be **coarse in the sweep artifacts (4 distinct values)** but **continuous in live
`daily_predictions` (2038 distinct)**. That contradiction unwound the whole S13 story.

## Chain of findings
1. **The champion is the BINARY model** (`m01_binary/v1`), gate+rank on `prob_elite`
   (`rank_by='prob_elite'`, `min_prob_elite=0.15`). Its `prob_elite` = `iso_calibrator.transform(p_pos)`
   at [universe_scorer.py:595]. `p_pos` = P(positive), **not** the 4-class P(>30%).
2. **The isotonic calibrator is a step function that destroys ranking.** Live: it collapses 2038
   distinct raw scores → **23**. It maps a fine grid (1000) → 66 plateaus. Around the gate it
   erases spread: raw 0.20 and 0.30 both → cal 0.054.
3. **0.15 is not low — it's raw `p_pos ≥ 0.48`** (`cal.transform(0.50)=0.15`). The model is
   overconfident (raw 50% ≈ 15% realised elite-rate); the calibrator corrects it. The apparent
   "too low" was a scale confusion with the *4-class* P(HomeRun) (median 0.31, different model).
4. **Calibrated ranking is harmful at the sharp end.** Live 20d-fwd decile test on the breakout
   cohort:
   | rank key | top-decile fwd | bottom-decile | spread | monotonic ρ |
   |----------|---------------:|--------------:|-------:|------------:|
   | raw `p_pos` | +1.6% | +1.4% | **+0.2%** | **+0.60** |
   | calibrated `p_cal` | **−1.6%** | +1.2% | **−2.9%** | +0.20 |
   The calibrated **top** decile has the **worst** return — the champion ranks top-5 on a
   mis-ordered top.
5. **Pre-existing backtests already showed it** (never propagated): `m01_binary/v1/backtests/`
   raw-vs-`_raw` pairs — **4 of 5 families rank better raw** (Sharpe 0.783→1.438); calibrated
   S1/S2/S4 collapse to identical picks (283 trades) because flattening makes different ranking
   rules choose the same names.

## So the S13 "gate-not-ranker → widen the basket" verdict is...
**Premature.** The tie-pool the S13 cohort-bootstrap found ("55/57 days one prob_elite value")
was the *calibrator's plateaus*, not evidence the model can't rank. The model's raw score ranks
(weakly) forward returns; the calibrator throws that ordering away — and inverts it at the top.

## Fix menu (in laziness order)
- **(b) Rank on raw `p_pos`, not calibrated `prob_elite`.** One kwarg in the scoring path; keep
  the calibrator for *display* probabilities only. Likely the right fix. → Phase 0 confirm, then
  WFO re-run.
- **(a) Widen the basket** (S13 plan) — stays live as fallback: raw's edge is weak (+0.2%/20d
  spread), so if raw ranking doesn't hold OOS, holding the whole gated ~6-name set is fine.
- **(c) Build a within-cohort ranker** — only if both raw and calibrated are flat OOS.

## Pool-size answer (sprint 14 Q2)
Breakout cohort human-review population: **~10 names/day pre-gate, ~6 after 0.15**. Small — the
shortlist is already human-sized. (Pre-breakout's 338/day is the separate 4-class funnel.)

## ⚠️ Caveats
- Raw `p_pos` is a **weak** ranker (+0.2%/20d top-vs-bottom). Better than calibrated ≠ strong.
- One deployed window of live preds (169 days, breakout only). Phase 0 corrected-bootstrap +
  WFO needed before flipping the champion's `rank_by`.
