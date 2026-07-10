# Sprint 14 — Strategy Consistency & Deployment

**Dates:** 2026-07-06 → TBD · **Status:** 🔄 Active · **Prev:** [sprint_13](../sprint_13/README.md)

> Sprint 13 proved M01 is real alpha and that the edge lives in the exits (E1 top-5 immediate).
> Sprint 14 turns that into a **deployable, capital-efficient** strategy: fix the rotation/turnover
> problem, ship it to ITX + the remote dashboard, and settle the macro-sizing question against M03.

### Progress so far (banked / falsified)
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

- [ ] **Enhance macro stress expression via Market Breadth / Internal Indicators.**
  The current 6-pillar macro mostly relies on external pricing and yields (credit spreads, rates, VIX, CAPE). We should evaluate internal equity market breadth to see if it improves or confirms the stress signal. Candidate metrics to test:
  - Advance/Decline (A/D) line
  - Equal-Weight S&P 500 (RSP) relative to market-cap weight (SPY)
  - Percentage of stocks above their 50-day moving average
  - New Highs vs. New Lows
  *Goal:* Determine if internal market deterioration provides a better or complementary "stress" sizing input than the existing composite.

- [ ] **Incorporate recent Sector Strength / Clustering into stock selection.**
  Mimic discretionary intuition (e.g., noticing a semiconductor boom) by quantifying sector clustering within the SEPA watchlist. If an increasing density of SEPA breakout candidates belongs to the same sector, it strongly suggests a thematic, sustained capital rotation (a "major hike").
  *Goal:* Test whether overlaying a recent sector momentum or SEPA-density score improves stock selection. For example, do we see a higher hit rate if we favor names in sectors that are actively expanding their representation in the SEPA pool?

- [ ] **Stock Selection EDA: Impact of Market Cap and P/E on Top-N Returns.**
  We need to deeply understand the fundamental and size characteristics of our daily top picks.
  - Plot the daily range/distribution of Market Cap for the top 1/5/10 selected stocks (similar to how we plotted forward returns).
  - Investigate the correlation between Market Cap within the SEPA candidate pool and forward returns. Does the model's alpha live exclusively in micro/small caps, or does it scale to larger names?
  - Perform the same correlation analysis for P/E ratios to see if the "value-rebound" effect (cheap names working better) holds robustly across the entire 25-year backtest.

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

**Population-inflation fix (2026-07-09):**
- [x] **FIXED — candidate selection now gates on genuine SEPA breakouts (trend_ok AND breakout_ok).**
  `score_from_t3` scores the WHOLE trend-active panel; consumers were selecting top-N by prob_elite from
  that inflated pool (a stock scored mid-downtrend is out-of-distribution for a breakout model). Gate
  added at every selection layer: `ScoreLookup.get_candidates` (→ sepa_strategy + forward_engine),
  `VectorizedSEPABacktest._select_entries`, `start_day_basket_paths.py` (both variants), and
  `run_strategy_wfo.py` (after the parquet/daily_predictions read). The **per-(ticker,date) scores are
  unchanged and the existing cache stays valid** — the flags aren't cached; they're joined from
  `t3_sepa_features` at read time via `src/backtest/sepa_gate.py::attach_sepa_flags` (an exact
  (date,ticker) join, rows preserved). NO re-score needed. Measured: only **~1% of scored rows are
  genuine breakouts** (~20/day median), so the old top-5 was drawn from ~99% off-setup rows. Guards:
  `tests/test_sepa_gate.py` + `sepa_gate.py::__main__`. Gate ON by default; `require_sepa=False` for the
  research unfiltered view.
- [ ] **RE-RUN the 25y cone + start-day lottery on the gated population** and check whether the sprint-14
  conclusions still hold (governor = DD-dial-not-alpha; the lottery shape; champion=flat). No cache
  regen — the WFO/lottery now attach the flags at read time, so just re-run the cone
  (`run_strategy_wfo.py --scores-parquet …`) and the lottery notebook. This is the substantive question:
  do the conclusions survive once the population is real breakouts?
- [ ] **DEFERRED — Minervini trailing-stop-to-breakeven exit in `vectorized_backtest.py`** (was sprint-14
  task (a)). **Recommendation:** add as a NEW `exit_policy='minervini'` (do NOT mutate sma/nday/atr_trail)
  so it A/Bs cleanly on the cone: tight initial stop (~7%), ratchet the stop UP to breakeven once the
  trade is up ~X% (e.g. +10%), then trail (ATR or a fixed give-back) from the running high. The lottery
  lens proved the tight-stop *payoff ratio* doubles (2.85→6.18) but a fixed-hold basket whipsaws that
  away — the asymmetry only harvests with this breakeven ratchet in the engine. Re-test on cone + lottery
  to see if it tightens the start-day distribution WITHOUT kneecapping the tail.
  cf `verdicts/2026-07-09_regime_governor_backtest.md` §6d, `cells/minervini_overlay_cells.md`.
- [ ] **DEFERRED — "MA50 governor" side-quest** — revisit only AFTER the gated re-run above, to see if the
  cleaner population changes the conclusion. (Note: a per-name price<MA50 exit already exists as
  `exit_policy='sma'`, `sma_exit_period=50`; if the intent is a portfolio SPY-MA50 deploy gate, it's a
  faster sibling of the existing SPY-200d gate in `MacroSizer` — a small new method.)

**Meta-questions status (full detail in [RESEARCH_LOG.md](RESEARCH_LOG.md)):**
- [x] **M1 — fat-tail-weighted objective** — DONE, `Σmax(fwd−30%,0)` + tail-lift@k adopted.
- [x] **M4 — magnitude/quantile regressor** — SMOKE-BUILT then PARKED (A-target ranks tail better but noisy).
- [x] **M6 — regime state expression + during-period behaviour** — label shipped; M4 counter-cyclical; m01 regime-robust.
- [ ] **M2 — decisions on a start-date CONE, not a single Sharpe.** Re-open raw-vs-calibrated and
  gate-height using the Sharpe *distribution* across start months. 0.12 gap inside start-time noise.
- [ ] **M3 — stability-first strategy search** — sweep strategies in BOTH good and bad months, pick the
  most STABLE (not highest-mean). Decide the methodology before more strategy work.
- [ ] **M5 — persistent continuous-score top-N** (top-5 raw = +5.7%/19% HR, 50% overnight persistence)
  — a lower-turnover product distinct from day-0 breakouts.

**Regime follow-ups (opened 2026-07-08 by M6, still open):**
- [ ] **⭐ NEXT: regime-weight the DAY-SWEEP fwd-return panel (not a backtest yet).** Apply an
  SPY-200MA (≡ VIX) 2-state weight to the existing per-day top-5 fwd panel + full-universe fwd-by-state
  table; check if it lowers the AVERAGE + WORST-DECILE loss. Cheapest test of the "regime governor" the
  regime-blind finding calls for. Judge on fwd100. If it helps → promote to backtest; if not → saved it.
  Trunk = SPY-200MA only; the calm/stress sub-split is NOT needed for this first cut.
- [ ] **Settle the regime STRESS sub-split** (only if the 2-state weight above isn't enough) —
  persistence filter (de-flicker) + a vol/VIX-percentile stress cut (`spy_vol20` already computed; ≈ a
  VIX cut → grounds it in the S13 sizing signal, fixes dd-sparsity / macro-leak). cf
  `verdicts/2026-07-08_m6_regime_state_label.md` §3b/§5.
- [ ] **dd regime axis on the SEPA-CANDIDATE population pre-2013** — the "reaches 2008" test + the
  model-agnostic during-period lens on the actual watchlist (consumer #2 used the full universe).
- [ ] **Dashboard: current-state regime badge + regime strip** beneath the 6-pillar table — DEFERRED as
  a separate deliverable (user). Payload = state→level+CI (`verdicts/2026-07-08_m01_by_regime.md`).
- [ ] **Feed regime as a training FEATURE into m01/m04** (once the stress axis is settled) — label is
  date-keyed/joinable; finding suggests regime helps LEVEL calibration more than ranking.
- [ ] **M4 regime-reweighting** — runnable, but the counter-cyclical finding argues AGAINST it. Parked.

- [ ] **Docs infra — fold RESEARCH_LOG maintenance into `handover` + `sprint-wrap-up` skills** (append
  the session's question→outcome lines at session/sprint close), plus a light manual "log this" trigger.
