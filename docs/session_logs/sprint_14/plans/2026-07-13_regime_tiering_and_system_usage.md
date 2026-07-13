# Regime tiering, gate calibration & how to actually use the system — research tracker

**Date opened**: 2026-07-13 · **Thread**: M (regime → system-usage synthesis) · **Status**: 📋
EXPLORATION + DOCUMENTATION ONLY this session. Implementation deferred to separate sessions.

**Frame**: closes the loop back to the sprint's opening question — *how do we quantify a regime,
and what does it mean for using the model*. This doc records what we verified today, the ideas
raised, and a prioritized to-do list. **Nothing here is implemented yet.**

---

## 0. Ground truth verified this session (facts, not opinions)

### 0.1 What regime signal is actually in the backtest gate — **SPY 200d SMA ALONE**
- `champion_trail_spygate` injects `spy_above_200d()` → `{date: SPY_close > SPY_200d_SMA}`. A
  binary on/off. **The 6-pillar / stress axis is NOT in the champion backtest.** (verified:
  `scripts/run_starttime_sweep.py:102`, `src/backtest/macro_sizer.py:56`).
- **Rule**: SPY < 200d that day → `available_slots = 0` → no NEW entries that bar; open positions
  are untouched (exits still run). (`src/backtest/sepa_strategy.py:651`).
- **Where the 6-pillar DOES live** (neither is in the champion strategy):
  - `weather_gauge` TABLE (display product): 200d + stress_z + supply → STAND ASIDE / DEPLOY /
    DEPLOY,TRIM NEW posture. Human-facing, not wired into the backtest.
  - `MacroSizer.governor_weight` (stress SIZING mode): backtested separately, **banked as
    DD-control only, NOT alpha**. The gate×tilt cancel (stress days are mostly sub-200d) collapsed
    it to ≡ the SPY-200d brake. So "200d alone" is not a shortcut — it is *what survived*; the
    stress axis added nothing the 200d didn't already do, in-engine.
    (`verdicts/2026-07-09_regime_governor_backtest.md`, [[project_entry_timing_macro_axis]]).

### 0.2 Does the gauge flag 2015 as a bad regime to trade? — **YES (coincident is enough)**
The disaster cell (2015-07 → 2016-03, binary champion Sharpe −1.93, −26% realized, −34% maxDD):
- **STAND ASIDE 101/189 days (53%)** of the window. SPY above 200d only **47%**, flipping the
  gate **11 times** (2015-08 breakdown → Oct blip → whipsaw into 2016). Textbook no-trend chop.
- `stress_high` fired **0 days** — 2015-16 was a TREND breakdown, not a STRESS event (no
  credit/VIX spike). So it's the **SPY-200d axis** that caught it, not stress. Consistent with the
  whole sprint: stress axis = crash-rebound timing; 200d = the trend brake.
- **Answer to the opening question**: the 200d brake WOULD have told you, day-by-day and without
  lookahead, that 2015-16 was a bad regime to deploy into. This is the one lever the sprint
  confirmed as *distribution-shifting* (BackTrader: floor −2.62 ungated → −1.93 gated).

### 0.3 Did we still lose on the 47% deploy-eligible days? — **YES, through the open gate**
Every trade in that cell entered on a gate-OPEN day (the gate blocks entry otherwise), yet **71%
stopped out** and the cell still ran −26%. **The 200d brake reduces EXPOSURE but cannot fix that
breakouts fail in a whipsaw even on green days.** This is the residual the gate can't reach — and
the motivation for a book-level breaker (§1.1 below).

### 0.4 Is there a portfolio-level drawdown breaker? — **NO (none exists today)**
Grep confirms no `portfolio_dd` / `halt` / `kill_switch` / book-level DD logic in
`sepa_strategy.py`. The only risk controls are (a) per-name 15% stop, (b) the SPY-200d entry gate,
(c) M03 regime_max_pos (regime 0 liquidates). **A book-level "down X% → stand down until SPY
uptrend" circuit breaker is genuinely un-tested territory.**

---

## 1. Ideas raised (documented; NOT yet actioned)

### 1.1 Portfolio-level drawdown circuit breaker  *(new, orthogonal, promising)*
**Hypothesis**: if the BOOK is down ≥ X% (e.g. 6%), stop opening new positions until SPY is back
above its 200d — a book-level brake distinct from the per-name stop and the per-day entry gate.
- **Why it's different from what exists**: the per-name stop caps individual losses; the SPY-gate
  caps exposure by market trend. Neither reacts to the PORTFOLIO's own bleed. §0.3 shows the gap:
  gate-open chop still compounds into −26% because each fresh name fails independently. A book
  breaker would halt the *sequence* of failing entries the gate lets through.
- **Design questions to resolve before building**: threshold (6%? peak-to-trough vs since-entry?),
  release condition (SPY>200d alone, or + a cool-off?), does it double-count the SPY gate (they'd
  often fire together)? Falsifiable on the existing 90-cell cone: add the breaker, re-run, check
  it lifts the FLOOR without killing the median (the recurring variance-vs-median test).
- **Caveat**: risks the same fate as the governor — a pure brake can't lift the mean, only the
  floor. But floor-lift IS the goal in chop. Judge on the cone distribution, not aggregate return.

### 1.2 Regime-TIERED strategy usage  *(the honest reframe)*
**The realization (user, 2026-07-13)**: we've been determining ONE all-weather system usage with
regimes blended together — but SEPA is a bull-regime tail strategy, not a silver bullet. It takes
two forms:
- **(a) Different strategy tiers by regime / risk appetite**, then run the equity-fan / cone
  analysis *per regime* rather than one blended cone. E.g. clean-bull tier vs chop tier vs
  stand-aside (no-SEPA) tier.
- **(b) Gate calibration may be REGIME-DEPENDENT**: user's hunch (backed by a few live high-score
  picks in 2025-26) is that a HIGHER score gate might pay off in a clean bull — the opposite of
  Q47's pooled finding. **Q47 never split the gate result by regime.** Plausible the gate helps in
  bull and hurts in chop; the pooled median hides it. → a per-regime gate cut is the test.
- **This is the M3 meta-question finally scoped**: "in both good AND bad months, sweep strategies
  for the most STABLE one" — stability-first, not mean-first, and per-regime not pooled.
- **Honest caveat baked in**: we do NOT have a validated "effective regime for SEPA" definition
  beyond SPY-200d. Tiering on an unproven regime label risks curve-fitting. Keep tiers COARSE
  (200d up/down at minimum) and validate each tier on the start-date cone, not a point estimate.

### 1.3 m02 breakout-PROBABILITY classifier — reframed  *(re-openable with corrected question)*
**Original rejection** (2026-07-04, [[project_strategy_arena_goal]]): m02_breakout FALSIFIED as a
FORWARD-RETURN predictor (top-50 fwd ≈ universe).
**The uplift (user, 2026-07-13)**: that rejected the wrong question. The question of interest is
NOT fwd return — it's **P(a trend_ok ticker actually breaks out in the next X days)**, a pure
event-probability (≈10% base rate, clean binary label). Never tested as a breakout-TIMING
probability; m02 was only ever a return regressor.
- **Product fit**: a "ripeness" score on the watchlist — which trend_ok names are ABOUT to trigger
  — feeding the human-in-the-loop shortlist, independent of whether the breakout then pays.
- **Kept-honest guardrail**: even a perfect breakout-predictor is upstream of a ranking stage
  (m01a Thread H) we proved doesn't convert to trade edge. So this is a WATCHLIST-ENRICHMENT idea
  (help the human see ripening setups earlier), NOT a selection-alpha claim. Scope it as such.

---

## 2. How to use the system in real trading (current best synthesis)

Distilled from Thread L + this thread. This is the operating manual as evidence stands today:

1. **The output is a FILTER / watchlist, never an auto-buy list.** The funnel: ~100k trend_ok/yr →
   ~10k breakouts (10%) → ~40/day → ~30 after the 0.15 gate. The system hands you ~30 genuine
   breakouts/day; **the last-mile ranking to a handful is the human's job** — that's where the
   realized alpha in past hand-picks lived (blind top-N over the 30 is coin-flip-median).
2. **Keep the score gate LOW (0.15), not high** — for the CURRENT blended usage. A tighter gate
   gives fewer names AND a worse distribution (median + floor both worse; the "wider tail" hope is
   a label-level illusion the exits truncate — §Thread L). *Exception under investigation: §1.2b,
   whether bull-regime warrants a higher gate.*
3. **SPY-200d is the one real ex-ante lever — it's your WHEN, not your WHICH.** Deploy fresh
   capital when SPY>200d; stand aside below. Confirmed distribution-shifting on BackTrader.
4. **Don't expect rotation or the stop to rescue a bad regime.** They cap per-trade loss and turn
   the book over — they cannot manufacture a winner to rotate into when breakouts fail
   market-wide (§0.3: 71% stop-out even on gate-open days). Infra is working as designed; the
   limitation is structural, not a bug.
5. **Size and hold for the TAIL.** Edge is long-hold, tail-shaped (fwd100 ≫ fwd20; a few names
   run). Enter above the 200d gate, cut losers fast (15% stop), let winners run (why the trail
   exit / no-TP is champion). Taking profit early clips the tail that pays for the strategy.
6. **It is not all-weather by design.** Continuation model; structurally excludes crash-bottom
   reversals ([[project_capital_deployment]]). In sustained chop/downtrend (2015-16 type), the
   correct usage is *reduce or stop* — which §1.2's tiering would formalize.

---

## 3. To-do (prioritized) — IMPLEMENTATION IS SEPARATE

### 🔨 IMMEDIATE (design known, just execute — separate implementation session)
- [ ] **Earnings-proximity entry/exit rule.** Block entry / force exit N days before a scheduled
  earnings date (Minervini: never hold a binary gap you can't stop out of; the 15% stop already
  understates gap loss, [[project_backtest_stop_gap_fill]]). Needs an earnings-date table joined
  at entry/exit (`earnings_engine` exists per the codebase map). Falsifiable overlay on the cone.
- [ ] **1-day entry delay on the EQUITY FAN.** Re-test `entry_delay_days=1` in the fan/basket lens
  (single-factor forward-return, no slot-book confounds — where the backtest version was
  inconclusive: short window + too many interacting factors). Engine already supports E2;
  `basket_paths` can take a delay. Isolates: does waiting one day to confirm the breakout hold
  change the distribution?

### 🔍 NEXT (design needs a decision first)
- [ ] **§1.2b — per-regime gate sweep.** Split the Q47 gate result by SPY-200d regime: does a
  higher gate pay in clean bull while hurting in chop? (Cheap: re-cut existing cone cells by
  entry-regime.) This is the concrete test of the user's live-pick hunch.
- [ ] **§1.1 — portfolio-level DD circuit breaker.** Design the threshold/release rule, then add
  as a strategy option and re-run the 90-cell cone; test floor-lift without median-kill.
- [ ] **§1.2a — regime-tiered fan/cone.** Run the equity-fan / cone analysis PER regime (coarse:
  200d up/down) instead of one blended cone. Formalizes tiered usage.
- [ ] **§1.3 — m02 breakout-probability classifier** (reframed as watchlist ripeness, not
  selection alpha). Only if §1.2 shows tiering has legs.

### ⏸️ DEFERRED (after the above)
- [ ] **Granular day-level dispersion within good vs bad months.** How much does picking the wrong
  DAY inside a known-good month cost — quantifies residual day-luck after regime is controlled.
  Cheap on the existing `entry_timing_daily.parquet` × regime label. Deferred per user.

---

## Cross-refs
- Thread L trail cone: `verdicts/2026-07-13_4class_vs_binary_TRAIL_cone.md`
- Q47 gate sensitivity: `verdicts/2026-07-11_prob_elite_gate_sensitivity.md`
- Governor / stress-axis: `verdicts/2026-07-09_regime_governor_backtest.md`
- Regime state label: `verdicts/2026-07-08_m6_regime_state_label.md`
- Memory: [[project_entry_timing_macro_axis]], [[project_capital_deployment]],
  [[project_weather_gauge_shortlist]], [[project_scoring_vs_selection_unclipped]],
  [[project_regime_during_period_goal]], [[project_backtest_stop_gap_fill]].
