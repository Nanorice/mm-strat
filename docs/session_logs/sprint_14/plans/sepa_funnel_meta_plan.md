# Meta plan — the SEPA funnel research program (steps 2–4)

**Date:** 2026-07-10 · **Status:** 📋 TRACKING (meta — child plans carry the milestones).
Born from the 2026-07-10 brainstorm after m01a closed (kill #2 + #3 fired,
`m01a_tail_ranker_plan.md`).

> **Steering doc:** [`sepa_ground_truth_roadmap.md`](sepa_ground_truth_roadmap.md) consolidates the
> settled ground truth, the "three currencies of null" (C1 label-ranking / C2 OOS-ranking / C3
> exit-aware P&L — do not conflate), the standing epistemics, and the **m01 de-gate decision gated
> behind R3**. Read it before drawing any conclusion or citing a verdict.

## The frame — Minervini's 4-step funnel, mapped to this repo

| Step | Book | Repo state 2026-07-10 |
|---|---|---|
| 1. Trend template | Stage-2 uptrend filter, **incl. criterion #8: RS rating ≥ 70** | ✅ RESOLVED (R1b-M0 2026-07-10) — floor = `rs_universe_rank` ≥ 0.70: keeps 91% of home-runs, trims 21% of names; but `trend_ok` already implies median RS at the 84th pct, so the missing criterion was largely implicit |
| 2. Fundamentals (+ volatility) | earnings/sales/margin *acceleration* screen, tightness | ✅ RESOLVED (R1b 2026-07-10) — rev-growth/margin-trend SUBSUMED by RS (real ramps, RS-correlated); EPS growth/accel NULL (U-shaped); verbatim screen dominated 3× by RS depth-matched, era-fragile. RS stays the one-column gate |
| 3. Leadership profile | similarity to past super-performers | 🔲 UNTOUCHED — but the dataset already exists (`m01a_tail_v1` label = realized home-runs) → **R2** |
| 4. Manual review / prioritising | human scorecard | 🔲 UNTOUCHED — deliberately NOT a fourth ranker; R2's passport feeds it |

**The reframe from the brainstorm:** the funnel is not stuck at step 2 — steps 1–2 already produce a
working watchlist ranking (RS top decile). The pipeline is stuck at **monetization**: M4 showed a real
3.5× label-level lift dies under the champion's tranche exits (exits truncate the tail). Selection and
exit are COUPLED and were never tested as a pair → **R3 is the highest-value open question**, not more
selection research.

## Standing evidence (don't re-litigate — see verdicts/)

- Breakout = entry trigger, not a universe; population reframe done (`2026-07-09_population_reframe_tail_ranker.md`).
- ML on the full panel ties one-column RS; selection signal = `rs_universe_rank` top decile
  (`2026-07-10_m3_ml_vs_rs_bar.md`). Features beat RS pre-2019 only — any revived edge must survive 2019+.
- Label-level tail lift does NOT convert under stop+tranche exits (`2026-07-10_m4_rs_tail_backtrader_cone.md`);
  incumbent reference cone: median Sharpe 0.47, 33% neg cells.
- Minervini prog-fills exit washed on BackTrader — but with the OLD (population-inflated) selection
  ([[project_minervini_progfills_fails_bt]]). The RS-tail × trail-exit PAIR is untested.
- Judge everything on the BackTrader start-date cone, never vec, never a single window
  ([[project_vec_engine_optimistic]], [[project_champion_starttime_dependent]]).

## The priorities (cheap-first, each independently falsifiable)

- [x] **R1 — Fundamental coverage audit + within-RS splits** → `r1_fundamental_coverage_audit_plan.md`
  **Completed 2026-07-10, verdict SCOPE-NARROWED same day:** M0 coverage adequate (eps/rev accel
  ~90%); M1/M2 splits within RS-D10 all null. What that kills: fundamentals as an *incremental ranker
  beyond extreme RS at 63d*. What it does NOT kill: Mark's step 2 — the test conditioned on a mediator
  (RS is downstream of fundamentals) and mis-placed RS (a step-1 criterion) as the second gate → R1b.
- [x] **R1b — Step 2 book-faithful retest (screen + ordering + horizon)** → `r1b_step2_book_faithful_plan.md`
  **Completed 2026-07-10, verdict `verdicts/2026-07-10_r1b_step2_screen.md`:** mediation CONFIRMED —
  rev-growth/margin-trend have real unconditional ramps (1.74× D10/D1) and are RS-correlated →
  **SUBSUMED**, not null; EPS growth/accel are U-shaped NULLs (D1 home-run rate beats D10). The
  verbatim screen is dominated 3× by pure RS at matched 3.7% depth (1.48× vs 4.54×), is 85% interior
  to RS≥80, and its residual lift decays pre-2012→2019+ (2.14→1.29). No 126d crossover. RS floor
  ≥70pct = proper step-1 semantics (91% HR capture, −21% names) but trend template already implies
  median 84th pct. R1's verdict upgrades to GENERAL. **New lead:** missing-fundamental cohort
  (young/small/sparse, 8% of panel) is the hottest era-stable bucket (2.2–2.9× tail lift) — mirror:
  RS≥70 ∧ mature ∧ full-fundamentals ≈ 1.0×. Label-level only; R3-gated. Mapping table filled
  row-by-row in the verdict (proven / subsumed / null / untested).
  **Addendum (`2026-07-10_r1b_axis2_smallcap.md`):** the lead CONFIRMS as a second watchlist axis —
  the real axis is SIZE (cap-decile ramp monotone, RS-D10 ∧ smallcap-T1 = 2.4–3.2× era-stable and
  vol-matched robust), with coverage-missingness additive within every cap tercile. Constraint =
  liquidity (hot-cell median $7.5M/day) → R3's 2×2 should add a size-tilted selection arm.
- [x] **R2 — Leadership-profile contrast EDA (step 3)** → `r2_leadership_profile_eda_plan.md`
  **Completed 2026-07-10, verdict `verdicts/2026-07-10_r2_leadership_profile.md`:** NO trait clears the
  M1 gate (stack ≥1.3× on RS-D10, monotone, non-RS-clone) → step 3 **collapses into RS**, kill
  criterion FIRED. Group-leadership traits are RS-clones (ρ 0.57–0.80); base-character (vcp/tight/
  52w-high) are flat-to-inverted; only residual = volatility (adr_20d/natr 1.28×, era-stable but BELOW
  gate and upside-only — tail-lift 1.6× > HR-lift 1.28×, same phenotype as R1b's size/coverage axis,
  not a new axis). Passport ships as a descriptive/manual-review aid (dashboard column set on the
  RS watchlist), NOT a selection layer or model. This closes the last program box.
- [x] **R3 — Exit × selection coupling A/B (the conversion problem)** → `r3_exit_selection_coupling_plan.md`
  **Completed 2026-07-10, verdict `verdicts/2026-07-10_r3_exit_selection_coupling.md`:** 2×2 cone ran.
  The tail-harvesting (trend-exit-only) exit **helps the CHAMPION's selection** (D vs A +0.21 median
  Sharpe, era-robust, p25/p75 up) but does **nothing for RS-tail** (C vs B +0.06). Selection dominates
  the exit (D vs C +0.42, 76% of cells). **RS-tail un-monetizable under BOTH exits** (median 0.10
  tranche AND trail) → watchlist-ordering only, funnel selection research CLOSED. `champion_trail` =
  CANDIDATE exit refinement pending SPY-200d deploy-gate re-confirm (not promoted off the cone — +0.21
  inside noise). **m01 de-gate NOT triggered** (roadmap "D>A but C≁B" row → de-gate inherits C's null).
  Mechanism: trail holds runner to trend break (exit mix flips 82%→50% stop) but median trade bleeds
  ~1pp more (fixed initial stop, no rising trail — the trend-exit-only cost); tail + bleed ~cancel on RS.
- [x] **R4 — EDGAR backfill + surprise/revision/streak features** — DORMANT (coverage trigger dead).
  **Status (2026-07-10):** R1-M0 found coverage adequate, so the original trigger can't fire. NOT a
  verdict that the null is genuine (that's R1b's question). New trigger: R1b finds step-2 signal that
  needs the unmapped criteria (surprise, revisions, true Code-33 streak) → write the plan then.
  **Trigger check (2026-07-10): DID NOT FIRE** — R1b's mapped growth criteria that carry signal are
  already inside RS; nothing points at the unmapped criteria. R4 stays dormant.

**Dependencies:** R1b ∥ R2 ∥ R3 — all independent, any order. R4 blocked on R1b. Recommended order
R3 first (largest payoff, informs whether selection findings can even be monetized systematically),
R1b/R2 as cheap fillers around the long runs.

## Program-level kill criteria

- R1b null (unconditional ramps flat AND screen adds no lift/capture at 63d + 126d) + R2 nothing
  stacks on RS → step 2/3 = the one-column RS rule, funnel research CLOSED; remaining value is R3's
  exit question only.
- R3 finds no exit converts the tail → RS = watchlist-ordering value only; steps 3–4 re-aim at
  discretionary support (passport as a review aid), not systematic alpha.
- Any revived edge that wins pre-2019 but loses 2019+ inherits the M3 temporal-break suspicion → not shippable.

## Done when

All four boxes resolved (done or killed with a verdict in `verdicts/`), and either (a) a new champion
is named via R3 + deploy-gate re-confirm, or (b) the program is closed with the RS rule + passport as
the durable deliverables. Roll outcomes into the sprint README at wrap-up.
