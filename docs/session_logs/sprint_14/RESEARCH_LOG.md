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
   → ✅ **M1 re-cut (magnitude): only 14.2% of tail MAGNITUDE missed, not 23.4% of events — the
   gate keeps big winners, drops small ones (missed mean-excess +12% vs captured +23%). AND the
   raw score DOES rank the tail (top-1% fwd at score-pctile 0.89; top-1% scores hold 6.1× their
   share of tail) — "weak ranker" was only true within the gated pool, not on the full universe.**
   `verdicts/2026-07-07_tail_magnitude_recut.md`

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

## Thread E — capital deployment: bad-day risk, basket width, scope (user Qs, 2026-07-07)

13. **Is the crash pro-cyclicality a model defect?** → **No — a scope boundary.** SEPA screening
    (Stage-2 uptrend, rising MAs, high RS) structurally EXCLUDES beaten-down reversal names at their
    bottom; they only enter the full-universe test set later, after re-building a trend. The model is
    a CONTINUATION model, not a reversal model. → accept it; the 25-yr full-universe bad-regime floor
    is a slightly pessimistic read of the SEPA-gated live system (which wasn't down there ranking
    reversals). `verdicts/2026-07-07_capital_deployment.md`
14. **Does top-10 catch more winners than top-5?** → **No.** Both from the same ~284 gated/day.
    Pooled 25y: top-5 +2.36% / HR 8.75% ≈ top-10 +2.30% / 8.34%; names 6–10 average +2.23%. The
    score's power is a SHARP CLIFF at the top-5 then flat. **Widening the basket dilutes, doesn't
    help** — argues AGAINST the S13 "widen it" instinct. Inside the 5, no order (IC≈0). Same verdict.
15. **Can we tell good days from bad EX-ANTE (the limited-capital start-date problem)?** → Partly.
    **SPY-above-200d is a real deploy gate:** top-5 fwd +3.0% (above) vs +0.6% (below), 25y — a 5×
    gap from one binary known at the open. **VIX is NOT a gate** (corr +0.03; high VIX>30 days are
    the BEST +4.5% — crash-rebound, don't cut them). Residual: even in the best state 42% of days
    still go negative → the un-removable part is STAGGERED entry (dose-average the start), not
    day-timing. Confirms M2's cone-not-point; SPY-200d tightens the cone's downside. Same verdict.

## Open meta-questions (deferred — carry to next session)

- ✅ **M1. DONE — objective re-cut to tail-magnitude, validated across 25 regimes.** New reusable
  metrics: captured/missed `Σ max(fwd−30%,0)` (2025 leak 14.2% not binary 23.4%) and **tail-lift@k**.
  Scope clarified: the "good ranker" claim is point-in-time full-universe RAW score, 20d fwd; the
  "weak ranker (4×)" was the OPPOSITE conditioning (inside the gated pool / calibrated score).
  Selection edge honestly bounded: 2025 top-1% lift 6.1× is ~half gate; **above-gate residual 3.2×**.
  **Multi-year (2001–2025, `data/model_output_eda/multiyear/`): the ranker is PRO-CYCLICAL** — median
  6.8× but 0.68× (below no-skill) in 2001/2008 crashes; above-gate edge negative in 5/25 yrs;
  corr(lift,HR-rate)=−0.44. Only regime-robust result: `miss_mag<miss_count` 25/25. → adopt the
  metric; treat ranking as a distribution; M3 judges the bad-regime floor, M4 must be
  regime-conditioned. `verdicts/2026-07-07_tail_magnitude_recut.md`
- 🔀 **M2. ABSORBED, not skipped — it's the evaluation LENS, not a standalone deliverable.**
  Single-Sharpe is unsafe → decisions go through a start-date cone (distribution not aggregate).
  Validated 3× this session (the 25-yr sweep is a coarse cone; Q15 "42% neg days → stagger not time";
  and the next step (b) IS a cone test). No separate harness to "do" — (b) applies M2. Don't
  re-litigate. cf [[project_champion_starttime_dependent]].
  → **(b) NEXT SESSION:** does the SPY>200d deploy gate (Q15) SHRINK the start-date cone — narrow the
  Sharpe *distribution* across start-months, not just lift the mean? Needs `run_strategy_wfo.py`, not
  a cache re-slice. This is the entry into M3. `verdicts/2026-07-07_capital_deployment.md`
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
