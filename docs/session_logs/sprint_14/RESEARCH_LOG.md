# Sprint 14 — Research Log (question ledger)

> **Purpose:** the linear train-of-thought — every question in the order it arose, one-line
> outcome, link to the deep verdict. This is the *middle zoom* between the per-finding `verdicts/`
> (deep, one file each) and the goal-organised `README.md` (current state). Read top-to-bottom to
> follow how the thinking evolved. Append one line per question at each key point / topic switch.
> `→` = what happened · `⟳` = a later finding revised this · `?` = open.

## Thread A — is the top-5 a skilled pick, or random? (gate vs ranker)

1. **Is the champion's top-5 a skilled pick or a random draw from a tie-pool?**
   → smoke cohort-bootstrap (1 window): pick sits at 37th pctile of random-null → looks random.
   `verdicts/2026-07-07_selection_bias_cohort_bootstrap.md`
2. **Why is it tied? — is `prob_elite` really that coarse?**
   → ⟳ the ties were on `normalized_score` (4 distinct), NOT the model's actual score. The champion
   is the **binary** model ranking on **calibrated** `prob_elite = iso_calibrator.transform(p_pos)`.
3. **So is the "gate-not-ranker" verdict real, or a calibrator artifact?**
   → the isotonic calibrator is a step function: collapses ~2000 raw scores → ~23 plateaus →
   manufactures the ties. Live `daily_predictions` raw score is continuous. **Mechanism overturned:
   ties are a calibrator artifact, not the model.** `verdicts/2026-07-07_calibrator_flattens_ranking.md`
4. **Then rank on RAW p_pos instead of calibrated?** (fix b)
   → WFO reconciliation: calibrated 0.91 vs raw 0.79 aggregate OOS. Looked like calibrated wins →
   ⟳ **corrected: 0.12 gap is inside start-time noise (folds swing >2 Sharpe). NOT settled.**
   `models/m01_binary/wfo/{calibrated,raw}/`

## Thread B — is 0.15 the right threshold? (EDA, model output)

5. **How does the model output distribute; is 0.15 the right gate?**
   → 0.15 is **calibrated**; = **raw p_pos ≈ 0.48** (the model's ~50/50 line). Not low — the model
   is overconfident, calibrator corrects raw 0.50 → 0.15. `verdicts/…calibrator_flattens_ranking.md`,
   `cells/model_output_eda_cells.md`
6. **On the full universe, does the raw score grade forward return / is the gate right?**
   → yes, 3× home-run-rate gradient at the top (0.48→12.7% at 0.71). Gate is a precision/recall
   dial; a top-5 strategy only fills 5 of ~805 admitted/day → **can tighten hard for free precision.**
   `verdicts/2026-07-07_raw_score_forward_return_eda.md`
7. **How many home-runs do we miss?**
   → 23.4% missed, but they're near-misses (median raw 0.41 vs 0.48 gate). ⟳ **flawed measure —
   home-run treated as binary >30%, ignores the fat tail we actually care about. Re-cut needed.**

## Thread C — can we refine / rotate the gated pool?

8. **Do the ~6 gated breakout names persist day-to-day (could we rotate)?**
   → 0% next-day persistence — breakout is a day-0 event by construction. Rotation dead *for breakouts*.
   `verdicts/2026-07-07_breakout_pool_refinement.md`
9. **Is there ANY within-day separator of winners in the pool?**
   → no — every technical feature's within-day IC ≈ noise; model score IC ≈ −0.03. Third confirm of
   weak ranking. **Only residual = SECTOR** (Tech +9% vs Healthcare −3% median, breakout cohort).
10. **Now scores are continuous, do the TOP names persist?**
    → ⟳ **yes** (top-5 50% overnight, ~7-place drift) — but on the *full active pool*, not day-0
    breakouts. A persistent, rotatable top-N exists here that the breakout gate throws away.
    `verdicts/2026-07-07_raw_score_forward_return_eda.md`
11. **What do the best performers share?**
    → cheap, lower-quality **value-rebound** names (PE 17.7 vs 37.4); technicals flat/inverted; 2025
    sector tilt Healthcare 1.65× (⚠️ opposite the breakout finding → regime/population-dependent).
    ⚠️ 2025 only, one regime.

## Thread D — macro sizing (parallel track)

12. **What do the 6 macro pillars mean / how to use in sizing?**
    → reference doc written; sizing-not-selection; VIX works, M03 no-op (S13). Credit pillar is the
    top candidate to test next to VIX. `docs/research/macro_pillars_reference.md`

## Open meta-questions (deferred — carry to next session)

- **M1. Are we evaluating on the wrong metric?** Home-run as binary >30% ignores the fat tail
  (a +35% and a +400% count equally). The strategy's alpha IS the tail → objective should be
  tail-magnitude (Σ max(fwd−30%,0), or rank-of-top-1%), not hit-count. Re-cut Q7 this way.
- **M2. Single-Sharpe decisions are unsafe** given start-date dependence. Every raw-vs-cal /
  gate-height decision should be a **start-date cone** (Sharpe *distribution* across start months),
  not one aggregate. cf [[project_champion_starttime_dependent]].
- **M3. Did we start the whole strategy search on the wrong foot?** (user, 2026-07-07) — we ran a
  strategy grid over ONE fixed horizon, picked a winner, THEN discovered start-date dependence and
  swept it. Every early decision was backed by one horizon's result. Proposed re-frame: pick a
  strategy → sweep start-month × horizon (done) → **in both good AND bad months, sweep strategies to
  find the most STABLE one** (not the highest-mean) → refine/iterate. Stability-first, not mean-first.
- **M4. Classifier can't express fat tails.** m01_binary outputs P(>30%); +35% and +400% are
  identical to it. A **regressor / quantile model targeting forward-return magnitude** (working
  name **m03**) could rank by expected tail contribution. Eval on rank-of-tail, not RMSE. Design
  doc next session. (Note: name m03 collides with the existing regime model M03 — pick a distinct id.)
- **M5. Persistent continuous-score top-N** (from Q10) is a different, lower-turnover product than
  the day-0 breakout champion — worth prototyping + cone-testing.
