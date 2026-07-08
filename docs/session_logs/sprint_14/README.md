# Sprint 14 — Strategy Consistency & Deployment

**Dates:** 2026-07-06 → 2026-07-08 · **Status:** ✅ Closed · **Prev:** [sprint_13](../sprint_13/README.md) · **Next:** [sprint_15](../sprint_15/README.md)

> Sprint 13 proved M01 is real alpha and that the edge lives in the exits (E1 top-5 immediate).
> Sprint 14 turns that into a **deployable, capital-efficient** strategy: fix the rotation/turnover
> problem, ship it to ITX + the remote dashboard, and settle the macro-sizing question against M03.

### Headline outcomes (what the sprint banked / falsified)
- **M01 is a strong GATE, and a strong RANKER on the full universe** — but "weak ranker (4×)" was only
  true *within* the homogeneous gated pool / on the *flattened calibrated* score (the ties were a
  calibrator artifact, not the model). On the raw full-universe score the tail concentrates at the top.
- **Objective re-cut to tail-MAGNITUDE** (`Σmax(fwd−30%,0)` + tail-lift@k) — the gate misses 14% of
  magnitude, not 23% of events; reusable metric adopted, regime-robust.
- **M4 (magnitude regressor) SMOKE-BUILT then PARKED** — a plain winsorized regressor ranks the tail
  within the elite pool better than the classifier (median), but noisy; no artifact shipped.
- **M4's pro-cyclicality OVERTURNED** — with an independent regime label the tail-ranking edge is
  **counter-cyclical** (strongest under stress/bear), cross-validated on two stress axes. The
  "dies in the GFC" story was a circular hand-picked-fold artifact.
- **M6 regime STATE label shipped** — bull/bear trunk (SPY-200MA) solid & regime-matching; the
  stress sub-split (dd / macro axes) NOT yet settled (leaky/sparse/flickery) — a known refinement.
- **m01 ranking is REGIME-ROBUST** (full universe, all tickers): the score ranks fwd return in every
  state; stress/bear precede HIGHER returns than calm (gap statistically real by block-bootstrap), and
  **both gap and gradient GROW with the hold** (judge on fwd100). NO pillar trunk beats SPX-200MA.
- **VIX ≈ the bear/drawdown axis** (≈ realized vol) — VIX-sizing and the regime overlay are the same
  bet, not independent inputs.
- **Deployment facts:** SPY>200d is a real ex-ante deploy gate (+3.0% vs +0.6%); VIX is NOT a gate
  (high-VIX = rebound); widening top-5→10 dilutes (sharp cliff at 5); champion is start-time dependent
  → judge on a start-date cone, not one Sharpe. Stage-gate & τ=0.90-quantile theses FALSIFIED.

**→ full question ledger (how the thinking evolved):** [RESEARCH_LOG.md](RESEARCH_LOG.md)

### Folder map
- **`RESEARCH_LOG.md`** — linear question ledger (M1–M6 + threads A–F, by sequence).
- **`logs/`** — dated session handovers (`YYYY-MM-DD_NN_<slug>.md` + `_index.md` on multi-session days).
- **`verdicts/`** — findings / reports (one per question).
- **`cells/`** — notebook-cell artifacts (`*_cells.md`).
- **`scripts/`** — reusable research harnesses built this sprint.

## 🧭 Research questions we're answering (the big picture)

The whole sprint is one thesis: *M01 gates well but doesn't rank, and the edge is start-time
dependent — so how do we deploy it as a robust, capital-efficient strategy instead of a lucky
top-5?* The open questions, each mapped to a goal below:

1. **Selection bias — is the top-5 a skilled pick or a random draw?** `prob_elite` is coarse
   (most days every picked name ties on one value), so top-5 is a draw from a tie-pool. If it's
   random → the model is a **gate, not a ranker** → don't build a ranker, **widen the basket**.
   → *smoke test done 2026-07-07: on 1 window the pick ≈ random (pctile 0.37, median edge ≈ 0).*
   Full multi-cell run pending. See [verdict](verdicts/2026-07-07_selection_bias_cohort_bootstrap.md).
2. **Rescue-by-rotation — if we drew losers on day 1, can we rotate into day-5's winners?** Only
   viable if within-cohort momentum *persists* without lookahead. Gated on Q1 showing no selection
   skill AND a positive persistence test. (S13: pre-breakout persists, breakout doesn't.)
3. **Does the day-within-month matter?** If we know the good *month* to start (from the S13
   start-time sweep, ann_return −39%..+197%), is start *day* a coin-flip or a real dial? Seed:
   shift start by **days** across the best and worst months. Frames "start today vs tomorrow".
4. **Turnover vs. immediate-entry alpha.** Top-5/day churns capital. Can trailing-average
   *membership/hold* (keep names, don't chase) cut turnover **without** delaying entry — given S13
   falsified trailing-average *entry* (the alpha is the day-0 fresh breakout)?
5. **New macro (6-pillar dashboard) in sizing — does it beat M03?** M03-banded sizing is a no-op;
   VIX-banded adds value. The 6-pillar macro is a **sizing** input (shared across tickers), not a
   selector — so it can't fix selection bias, only exposure. Does it earn a place next to VIX?

### Folder map
- **[`RESEARCH_LOG.md`](RESEARCH_LOG.md)** — the linear question ledger (train-of-thought by
  sequence; read this to follow *how* the thinking evolved). Middle zoom between verdicts & this README.
- **`logs/`** — dated session handovers.
- **`plans/`** — forward-looking design/plan docs.
- **`verdicts/`** — findings, reports, issues, playbooks.
- **`cells/`** — notebook-cell artifacts (no-direct-`.ipynb`-edit rule).

## New goals (sprint 14)

- [ ] **Selection consistency sweep — turnover vs. immediate-entry alpha.**
  Top-5/day is effectively random rotation: it churns capital with little chance of rotation payoff.
  Sweep the strategy **in days** and **split by losing vs. winning months** to see where the churn
  hurts. Two candidate fixes — (a) **limit the stock-selection set** (narrower daily choice), or
  (b) **consistency via a trailing-average score** so membership persists.
  ⚠️ **Tension to resolve, not assume away:** S13 falsified persistence (trailing-avg score, Sharpe
  −0.86) and delayed entry (+405%→−32% monotone) — the alpha is the **day-0 fresh breakout**. So a
  trailing-average *entry* likely kills the edge. The open question is whether trailing-average
  *membership/hold* (keep names, don't chase) can cut turnover **without** delaying entry. Frame it as
  a turnover/capital-efficiency study on the E1 champion, not a re-litigation of delayed entry.
  - **[2026-07-07] Selection-bias measured (smoke test).** Cohort bootstrap on `r_202101_h12`:
    top-5 ≈ **random draw from the tie-pool** (pick percentile 0.37, median edge ≈ 0, beats null
    ~31%). Mechanism *as documented then*: `prob_elite` ties (55/57 days, one value). ⚠️ 1 window.
    Artifact: [cells/cohort-bootstrap_cells.md](cells/cohort-bootstrap_cells.md),
    verdict: [verdicts/2026-07-07_selection_bias_cohort_bootstrap.md](verdicts/2026-07-07_selection_bias_cohort_bootstrap.md).
  - **[2026-07-07] ⚠️ MECHANISM OVERTURNED — the ties are a calibrator artifact, not the model.**
    The champion (binary `m01_binary/v1`) ranks top-5 on **calibrated** `prob_elite` =
    `iso_calibrator.transform(p_pos)`. The isotonic calibrator is a step function: it collapses
    2038 distinct live raw scores → **23 plateaus** — *that's* the "one value" tie-pool. Worse, its
    **top decile has the worst 20d fwd return** (−1.6% vs raw +1.6%); raw `p_pos` ranks
    weakly-positive (ρ 0.60). Pre-existing `m01_binary/v1/backtests/` raw-vs-cal pairs agree
    (raw Sharpe 1.44 vs cal 0.78, 4/5 families). Also: **the 0.15 gate = raw `p_pos ≥ 0.48`**, not
    a low threshold. → **New lead fix (b): rank on raw `p_pos`, not calibrated `prob_elite`;**
    widen-basket (a) demoted to fallback. Verdict:
    [verdicts/2026-07-07_calibrator_flattens_ranking.md](verdicts/2026-07-07_calibrator_flattens_ranking.md),
    EDA cells: [cells/model_output_eda_cells.md](cells/model_output_eda_cells.md), memory:
    `project_isotonic_flattens_ranking`.
  - **[2026-07-07] ✅ WFO RECONCILES — keep calibrated, fix (b) rejected.** Walk-forward (3 folds,
    744 OOS days, 60 trials/fold) on `run_strategy_wfo.py --raw-prob` vs not: **calibrated aggregate
    OOS Sharpe 0.91 (ann +77.5%) beats raw 0.79 (+56.9%)**. The `_raw`-wins backtests were a single
    IS/OOS split (overfit). Flattening doesn't cost OOS because the edge is the GATE (shared) and the
    within-pool pick is near-interchangeable. **Don't flip `rank_by`.** Separately, refinement study
    found the real lever is **sector triage** (Tech +9% vs Healthcare −3% median fwd20; 0% next-day
    persistence; within-day model IC ≈ −0.03) → verdict
    [verdicts/2026-07-07_breakout_pool_refinement.md](verdicts/2026-07-07_breakout_pool_refinement.md),
    memory `project_breakout_pool_refinement`.
  → reuse the vectorized sweep + BackTrader confirm ladder; `data/score_cache/` has both signals.

- [ ] **Deploy to ITX + remote dashboard.**
  ITX was deferred in S13 (other branch). Stand up the live strategy path and push the dashboard to
  the R2 remote. ⚠️ Any new dashboard loader's table MUST be in the `build_dashboard_db` MANIFEST or
  the remote breaks (see memory: dashboard-remote-parity).

- [ ] **New macro in sizing — pro/cons vs M03.**
  S13 verdict: VIX-banded sizing adds risk-timing value; **M03-banded is a no-op**. Try a new macro
  input in the sizing lever (`src/backtest/macro_sizer.py`) and lay out pros/cons against M03
  explicitly. Decide: does M03 keep any role, or is the sizing axis fully VIX + new-macro?
  → fold the winner into `run_strategy_wfo.py` so the uplift is confirmed OOS (this also closes the
  S13 carryover below).

## Carried over from sprint 13

- [ ] **WFO fold the VIX-sizing lever** into `run_strategy_wfo.py` — confirm the S13 in-sample sizing
  uplift OOS (merges with the macro-sizing goal above).
- [ ] **m02 pre-breakout tracker — rank-percentile knob** (or calibrate m02/G4). m02_breakout is a
  regressor; `prob_elite` is uncalibrated rank-only [0,0.31] → absolute-threshold knob is meaningless.
  Add pre-breakout-windowed m02 as a *table* in the manifest. See
  [sprint_13 log](../sprint_13/logs/2026-07-05_prebreakout_tracker_m02_finding.md).
- [ ] **Ops:** run `clean_dirty_shares_price.py` on **sh019** (its DB copy is still dirty); investigate
  standing FAILs (t1_macro missing June-2026 dates + NULL vix row, 4 gap tickers).
- [ ] **Deferred study (LOW):** stage primitives (`market_stage`/`slope_63d`/…) as soft M02 features —
  only if M02 needs help. Cache: `data/backtest_cache/stage_gate_panel.parquet`.

## TODOs
_(sprint-local isolated TODOs; cross-session facts go to memory, not here.)_

**Deferred to a fresh session (2026-07-07 — carry the meta-questions from [RESEARCH_LOG.md](RESEARCH_LOG.md)):**
- [ ] **M1 — fat-tail-weighted objective.** Re-cut the "home-runs captured/missed" analysis with
  magnitude, not the binary >30% count (a +35% and a +400% must not count equally). Metric:
  Σ max(fwd−30%, 0) or rank-of-top-1%. This is the objective everything else should optimise.
- [ ] **M2 — decisions on a start-date CONE, not a single Sharpe.** Re-open raw-vs-calibrated and
  gate-height using the Sharpe *distribution* across start months (reuse the S13 start-time sweep),
  not one WFO aggregate. The 0.12 cal-vs-raw gap is inside start-time noise → not settled.
- [ ] **M3 — did the whole strategy search start on the wrong foot?** We grid-searched strategies
  over ONE horizon, picked a winner, THEN found start-date dependence. Re-frame: sweep strategies
  in BOTH good and bad months and pick the most **stable** (not highest-mean); refine/iterate.
  Stability-first methodology — decide before more strategy work.
- [ ] **M4 — magnitude/quantile regressor (candidate new model).** m01_binary can't express fat
  tails (outputs P(>30%)). Design a regressor / quantile model targeting forward-return magnitude
  to rank by expected tail contribution. Eval = rank-of-tail, not RMSE. ⚠️ pick a model id that
  does NOT collide with the existing regime model M03. Design doc first.
- [ ] **M5 — prototype the persistent continuous-score top-N** (top-5 by raw = +5.7%/19% HR, 50%
  overnight persistence, ~7-place drift) — a lower-turnover product distinct from day-0 breakouts.
- [ ] **Docs infra — fold RESEARCH_LOG maintenance into `handover` + `sprint-wrap-up` skills** (append
  the session's question→outcome lines at session/sprint close), plus a light manual "log this"
  trigger for mid-session key points. Do NOT auto-detect "key points" on every turn (spam/noise risk).
