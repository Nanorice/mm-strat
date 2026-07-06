# Sprint 14 — Strategy Consistency & Deployment

**Dates:** 2026-07-06 → TBD · **Status:** 🔄 Active · **Prev:** [sprint_13](../sprint_13/README.md)

> Sprint 13 proved M01 is real alpha and that the edge lives in the exits (E1 top-5 immediate).
> Sprint 14 turns that into a **deployable, capital-efficient** strategy: fix the rotation/turnover
> problem, ship it to ITX + the remote dashboard, and settle the macro-sizing question against M03.

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
    ~31%) — model gates, doesn't rank. Mechanism: `prob_elite` ties (55/57 days, one value). Points
    at fix **(a): widen the basket (hold 15–20, not 5)** over building a ranker. ⚠️ 1 window only —
    loop all 53 cells before acting. Artifact: [cells/cohort-bootstrap_cells.md](cells/cohort-bootstrap_cells.md),
    verdict: [verdicts/2026-07-07_selection_bias_cohort_bootstrap.md](verdicts/2026-07-07_selection_bias_cohort_bootstrap.md).
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
