# Sprint 14 — Strategy Consistency & Deployment

**Dates:** 2026-07-06 → TBD · **Status:** 🔄 Active · **Prev:** [sprint_13](../sprint_13/README.md)

> Sprint 13 proved M01 is real alpha and that the edge lives in the exits (E1 top-5 immediate).
> Sprint 14 turns that into a **deployable, capital-efficient** strategy: fix the rotation/turnover
> problem, ship it to ITX + the remote dashboard, and settle the macro-sizing question against M03.

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
