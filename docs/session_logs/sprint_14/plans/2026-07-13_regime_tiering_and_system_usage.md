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

## 0.5 Coincident regime GAUGE — Step 1: what we've done + the uncovered angle (2026-07-13)

**The opening question, restated (user):** before splitting strategy by regime (§1.2), settle *how we
classify a regime*. Today the only regime lever that survived is **SPY-200d, a single binary**. We
also have the 6-pillar (weather gauge). Can a richer coincident measure tell trade-days from
don't-trade-days *better than SPY-200d alone*? **Deliverable target: an actual go / no-go trade gauge,
beyond the single SPY-200d metric.**

### 0.5.1 What we already did (three prior attacks — all rule-based or univariate)
| # | Work (verdict) | Construction | Result |
|---|---|---|---|
| 1 | **M6 regime STATE label** (`verdicts/2026-07-08_m6_regime_state_label.md`) | RULE: `bear=SPY<200d`; `bull-stress=drawdown≥10%` (dd axis) or stress-tercile (macro axis); else `bull-calm` | Bear/bull **trunk (SPY-200d) is solid** — its runs match every known regime 2000-26. Stress sub-split **leaks-by-time / flickers / sparse → NOT settled.** |
| 2 | **m01 × regime, consumer #2** (`verdicts/2026-07-08_m01_by_regime.md`) | Stratify full-universe fwd-return by the rule label; trunk bakeoff (spx200 vs each pillar/composite) | Ranking is regime-robust; **NO pillar trunk beats spx200** — every trunk has *negative* bull−bear fwd separation (rebound lives on bear days). |
| 3 | **Q15 capital_deployment + C7 return_vs_macro** (`verdicts/2026-07-07_capital_deployment.md`, `scripts/return_vs_macro.py`) | UNIVARIATE: Spearman-ρ + tercile-spread of each macro signal (6 pillars, stress, VIX, SPY-mom) vs the **top-5 basket** fwd-return | **SPY-200d wins** (+3.0% vs +0.6% fwd20, 5× gap, holds 25y). **VIX is NOT a gate** (high-VIX = best fwd, crash-rebound). Stress = high mean BUT **worst tail**. |

**The exercise the user remembers as "falsified and not dug further" = #3 (C7 trunk bakeoff).** It asked
"can any macro signal separate high/low return periods?" and judged by **ρ + tercile spread, one signal
at a time**. Every pillar lost to SPX200; several had the *wrong sign*. It was dropped there.

### 0.5.2 The three things #3 did NOT cover (why the user's new angle is a genuine cut, not a repeat)
1. **A cleaner, model-agnostic label.** #3's target was the *top-5 basket* fwd-return — already a
   selection+ranking product, confounded by the picker. The new label is the **full trend_ok cohort's
   fwd-return, loss-weighted** — "how hostile was the tape to *breakouts as a class* that day,"
   independent of any model. This is the during-period lens [[project_regime_during_period_goal]] the
   user has steered toward; **never built as a supervised target.**
2. **Multivariate, not univariate.** #3 ranked signals ONE AT A TIME. Nobody tested whether the pillars
   **jointly** separate bad days even if none does alone. A logistic / XGBoost on all pillars at once is
   the honest joint test. (Prior on the result: given #3 found individual pillars carry the *wrong* sign,
   this likely mostly *recovers* SPX200 — but it **closes** the question instead of leaving it at "no
   single pillar wins," and any multivariate lift over SPX200 is the whole prize.)
3. **Discrimination framing (AUC / precision-at-threshold), not correlation.** A go/no-go tool needs a
   *classification-quality* number and an operating threshold. #3 produced ρ and spreads, never an AUC.

### 0.5.3 Proposed design — the coincident trade-gauge classifier  *(design only; NOT built)*
A supervised **nowcaster**: label is future (hindsight), features are strictly past (live-safe) — the
standard nowcast setup. The DELIVERABLE is the classifier's **live-safe daily score**, not the label.

- **Population / grain:** one row per trading day. The trend_ok cohort each day = the panel already used
  upstream (v_d1_candidates / the trend_ok gate). No new universe.
- **LABEL (build BOTH, compare — user):** per day `t`, over the trend_ok cohort entering at `t`:
  - **(A) loss-weighted mean fwd-return** — downside-semivariance-weighted (convex weight on losers), so
    a day where breakouts bled is scored worse than the plain mean would show.
  - **(B) hostility rate** — fraction of the cohort whose fwd path went negative / hit −15% within the
    hold (maps directly to the §0.3 "71% stopped out" failure mode; exit-aware-ish).
  - Compare: correlation of the two daily series; keep whichever separates more cleanly under the model.
  - **HORIZON = fwd20 for the first cut** (trade-relevant), **but the label builder MUST be
    horizon-parameterized** (`--horizon fwd20|fwd50|fwd100`) — m01×regime showed the regime gap TRIPLES
    fwd20→fwd100, so the next iteration re-runs at fwd50/100 with zero code change. (user)
  - Threshold continuous label → good/bad by a percentile cut (e.g. bottom tercile of days = "bad");
    keep the cut itself live-safe (expanding, not whole-history) if the label feeds anything ex-ante.
- **FEATURES (all live-safe — day `t` uses only info through `t−1`):** reuse the Thread-F machinery
  verbatim (`entry_timing_features.py`: expanding-z of the 6 pillars +credit −rates −cape +vix; the
  `stress_ew_vix` composite; `spy_above_200d`; SPY 60d momentum; `spy_vol20`). **No new feature
  engineering** — the point is to test whether the *existing* pillars carry *joint* signal SPX200 misses.
- **Model:** logistic regression FIRST (interpretable coefficients answer "which pillars, and do they
  keep the wrong sign from #3?"), then XGBoost as the non-linear check. Small feature set → both cheap.
- **Validation:** walk-forward by year (no shuffled CV — days autocorrelate; the iid-p-value trap from
  m01×regime §2d). Report **AUC + precision-at-the-no-go-threshold**, always **against the SPX200-alone
  baseline** — the tool only earns its place if it beats one binary.
- **Falsification / kill-criterion (state up front):** if walk-forward AUC ≤ SPX200-alone AND the
  logistic keeps the pillars at #3's wrong sign → the gauge adds nothing; **SPY-200d stands as the whole
  regime tool** and we stop. That is a real, likely outcome — bank it as the settled answer, not a
  failure. The win condition is a *live-safe multivariate score that shifts the no-go day distribution
  beyond SPX200* (judge on the day-return distribution split, not a point AUC).
- **Reuse (ladder):** label join = `regime_state.py`'s date-key pattern; features = `entry_timing_
  features.py`; SPY gate = `macro_sizer.spy_above_200d`. New code ≈ one label-builder script + one
  train/eval script. Nothing here needs a new dependency or table.

### 0.5.4 Relation to §1.2 (why this is Step 1, gating the split)
The per-regime strategy split (§1.2) needs a regime *definition* to split on. If 0.5.3 dies on its kill
criterion, §1.2 splits on **SPY-200d only** (coarse, as its own caveat already demands). If it survives,
the classifier score becomes a *second, validated* axis to tier on. **So 0.5.3 runs before §1.2** — it
decides whether we have one regime axis or two.

---

## 1. Ideas raised (documented; NOT yet actioned)

### 1.1 Portfolio-level drawdown circuit breaker  *(✅ IMPLEMENTED 2026-07-13 — cone OPEN)*
**Hypothesis**: if the BOOK is down ≥ X% (e.g. 6%), stop opening new positions until it recovers —
a book-level brake distinct from the per-name stop and the per-day entry gate. Mechanism from Elder,
*Trading for a Living*.

**✅ IMPLEMENTED 2026-07-13** (no-op-by-default overlay, mirrors the `spy_deploy_gate` / earnings
brake point — halts NEW entries, open positions & exits untouched):
- **Design decisions taken** (resolving the open questions below):
  - *Threshold* = **peak-to-trough** DD from a running equity high-water mark (the clean backtest
    analog of Elder's monthly 6% rule; not since-entry). Latches once tripped.
  - *Release* = equity recovers to **within `dd_breaker_release_pct` of the peak** (a book cool-off,
    default 2%). This is Elder's own mechanism and — deliberately — does NOT default to SPY>200d, to
    avoid collapsing into the SPY gate (the governor's fate). SPY>200d is an *optional* extra release
    condition (`dd_breaker_require_spy_uptrend`, default off) for the doc's "cool-off vs 200d" cut.
  - Latch is **re-armable**: a new high-water mark resets the peak, so a fresh 6% bleed re-trips.
- **Code**:
  - `src/backtest/sepa_strategy.py` — params `dd_breaker_pct` (0/None=off), `dd_breaker_release_pct`
    (default 0.02), `dd_breaker_require_spy_uptrend` (default False); `_update_dd_breaker` (HWM +
    trip/release latch, called each bar from `_record_daily_snapshot`); entry-block via
    `available_slots = 0` in `_process_entries` (right after the SPY-gate block).
  - `src/backtest/strategy_registry.py` — arm `champion_trail_spygate_ddbrake6` (6% trip / 2%
    release, book-recovery alone) + a parity assert (differs from `champion_trail_spygate` only by
    the two breaker knobs).
- **Verify**: registry self-check (24 strategies) + 26 backtest/strategy tests pass; branch-level
  self-check of the latch (trip / hold / release / re-arm / spy-gate / off) passes.
- **⚠️ FP edge (left as-is)**: an *exactly*-`release_pct` recovery can miss by a float epsilon and
  release one bar later. Soft research knob, not a money-exact boundary — not worth a tolerance band.
- **NEXT RUN** (floor-lift test, mirrors the earnings arm): `python scripts/run_starttime_sweep.py
  --strategy champion_trail_spygate_ddbrake6 --grid rolling --workers 3` → compare cone
  (floor/IQR/%neg) vs `champion_trail_spygate`.
- **⚠️ Read the cone carefully**: breaker & SPY gate often fire together (the book bleeds *because*
  SPY rolled over). Count how many trip-days were ALREADY gate-closed before crediting the breaker
  with a floor-lift — else you double-count the 200d brake (the §0.3 / governor trap).

---

**Original hypothesis (for the record)**: if the BOOK is down ≥ X% (e.g. 6%), stop opening new
positions until SPY is back above its 200d — a book-level brake distinct from the per-name stop and
the per-day entry gate.
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

> **📋 ASSESSMENT 2026-07-14 (regime-expression now LOCKED → §1.2 unblocked).** The regime-indicator
> program is closed (SPY-200d is the whole axis; §0.5.3 + the 15-candidate manual, 5 falsifications).
> So §1.2 tiers on **SPY-200d up/down, coarse, full stop** — exactly the caveat §1.2 already bakes in.
> Assessment of the three sub-tasks below, in the order they should run:
>
> **Feasibility win — §1.2a and §1.2b are a CHEAP RE-CUT, not new backtests.** Every cone cell already
> persists `trades.parquet` with `entry_date`, `entry_score`/`prob_elite`, `pnl_percent`, `holding_days`,
> `exit_reason` per trade. The **ungated** `champion_trail` cone (90 cells, **2664 trades across BOTH
> SPY-200d states**) is the right substrate — the *gated* champion can't be split by regime (every entry
> is gate-open = bull by construction, degenerate). Tag each trade by SPY-200d-at-entry (price_data SPY
> 200d SMA) and re-aggregate. **No BackTrader re-run for the diagnostic cut.**
>
> **⚠️ The load-bearing caveat that decides whether §1.2 is real or a mirage.** A per-trade P&L re-cut is
> a *diagnostic*, NOT the promotion bar — it ignores slot contention, sizing, and rotation
> ([[project_vec_engine_optimistic]]: label/trade-log lift ≠ cone edge, proven 3×). A regime tier only
> earns promotion on a **fresh per-regime start-date CONE** (the honest engine), never on the re-cut
> mean/median. The re-cut's job is to decide **whether a cone run is even worth it** — if the trade-log
> split shows no separation, stop; if it does, run the cone to confirm it survives the exits. This is the
> same discipline that killed RS-tail and the governor.
>
> **First-look re-cut (ungated champion_trail, 2664 trades, per-trade — DIAGNOSTIC ONLY):** below-200d
> entries mean −1.11% / median −3.89%; above-200d mean +0.05% / median −5.46%. A mean/median FORK (below
> worse on mean, better on median) — do NOT over-read: it's per-trade, un-sized, un-slot-contended, and
> the below-200d count (898) is entries the *gate would have blocked anyway*. It says only "there's a
> distributional difference worth a proper cut," which we already knew (the gate is distribution-shifting).
>
> **Recommended order + gate on each:**
> 1. **§1.2b FIRST — per-regime gate sweep (cheapest, tests the user's live hunch directly).** Re-cut the
>    ungated cone's above-200d trades ONLY (bull-regime), sweep the entry-score gate (0.15 → 0.20 → 0.25
>    → 0.30), measure per-trade + basket distribution. **Kill/continue gate:** if a higher gate lifts the
>    bull-only distribution where Q47's *pooled* sweep found it hurt, that's the signal the pooled median
>    hid a regime interaction → promote to a **bull-only cone gate-sweep** to confirm. If bull-only looks
>    like pooled, the hunch is dead — bank it. (Q47 = [[project_prob_elite_gate_variance_knob]], gate is
>    a variance knob pooled; the open question is *purely* whether that's regime-conditional.)
> 2. **§1.2a SECOND — per-regime fan/cone.** IF §1.2b shows a bull/chop split matters, run the start-date
>    cone SEPARATELY on bull-start vs chop-start windows (partition the 90 rolling cells by SPY-200d state
>    at each cell's START, or better, sub-period the equity curves). Deliverable: two cones, not one
>    blended — the honest "SEPA in a clean bull vs SEPA in chop" picture. This is where a tier becomes a
>    real recommendation (e.g. "gate 0.25 + full deploy in bull; stand-aside/half-size in chop").
> 3. **§1.1 / earnings breaker cones (already wired, un-run) — orthogonal, run anytime.** Not regime
>    tiering per se, but they're the floor-lift overlays that a *chop tier* would use. Fold their cone
>    results into the chop-tier definition once §1.2a establishes the tiers.
>
> **Honest prior on the outcome.** SEPA is structurally a bull-continuation strategy ([[project_capital_deployment]]);
> the 200d gate ALREADY captures most of "trade in bull, stand aside in chop." So the realistic upside of
> §1.2 is NOT a new alpha axis — it's (a) *confirming* the gate hunch is or isn't regime-conditional
> (§1.2b), and (b) formalizing the chop tier as "reduce/stop + DD-breaker + earnings-blackout" rather than
> "keep trading blended" (§1.2a + §1.1). A likely-clean outcome is "tiering ≈ the gate we already have,
> plus a documented stand-aside rule for chop" — modest, honest, and the correct closing of the sprint's
> opening question. Don't oversell it into a second alpha engine; the regime work has repeatedly proven
> there isn't one.

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
- [x] **Earnings-proximity entry/exit rule.** ✅ IMPLEMENTED 2026-07-13. Block entry / force-exit
  N days before a scheduled earnings date (Minervini: never hold a binary gap you can't stop out
  of; the 15% stop understates gap loss, [[project_backtest_stop_gap_fill]]). **Cone verdict still
  OPEN** — wiring done + smoke-verified, the floor-lift test is the next run.
  - **Data**: FMP earnings parquets (`data/earnings/{T}.parquet`, `date` col) have deep history
    (AAPL→1985, 1839 tickers) — a real, usable calendar. `is_future` irrelevant for a backtest.
  - **Code** (no-op-by-default overlay, mirrors the `spy_deploy_gate` pattern):
    - `src/backtest/earnings_calendar.py` — `{ticker→sorted dates}` loader + `next_earnings_within`;
      fail-open on missing coverage (gaps never fabricate a signal).
    - `src/backtest/sepa_strategy.py` — params `earnings_blackout_days` (0=off), `earnings_exit_frac`
      (1.0/0.5/0.33), `earnings_exit_min_ret` (return-gate: trim only winners); `_check_earnings_exits`
      (force-trim before the print) + entry-block with a distinct `earnings_blackout` reject reason.
    - `src/backtest/strategy_registry.py` — arm `champion_trail_spygate_earn5` (N=5, full exit).
    - `scripts/run_starttime_sweep.py` — injects the calendar once (window-independent, not per-cell).
  - **Params per user steer**: N=5; exit parameterized (full / half / third), optional return-gate so
    underwater names ride to their own stop. Headline arm = full-exit (cleanest falsifiable test).
  - **Smoke** (2 bad-regime cells): 9 earnings force-exits + near-print entry-blocks fired; 22
    backtest/registry tests pass.
  - **⚠️ Caveat**: `earnings_blackout_days` is CALENDAR days (5 cal ≈ 3.5 trading) — simpler +
    slightly conservative; switch to trading-day window if the cone is sensitive to it.
  - **NEXT RUN**: `python scripts/run_starttime_sweep.py --strategy champion_trail_spygate_earn5
    --grid rolling --workers 3` → compare cone (floor/IQR/%neg) vs `champion_trail_spygate`.

- [x] **Portfolio-level DD circuit breaker (§1.1).** ✅ IMPLEMENTED 2026-07-13. Book-level brake:
  peak-to-trough equity DD ≥ X% (6%) halts NEW entries (open positions/exits untouched) until equity
  recovers within Y% (2%) of the high-water mark. All flexible: `dd_breaker_pct`,
  `dd_breaker_release_pct`, `dd_breaker_require_spy_uptrend`. Elder, *Trading for a Living*. Full
  design + code + verify in §1.1 above. **Cone verdict still OPEN** — wiring done + branch-verified.
  - **NEXT RUN**: `python scripts/run_starttime_sweep.py --strategy champion_trail_spygate_ddbrake6
    --grid rolling --workers 3` → compare cone vs `champion_trail_spygate`. **Count gate-already-closed
    trip-days** before crediting a floor-lift (don't double-count the 200d brake — §0.3 / governor).

### 🔍 NEXT (design needs a decision first)
- [x] **§0.5.3 — coincident trade-gauge classifier (GATES §1.2). ✅ DONE 2026-07-13 →
  `verdicts/2026-07-13_coincident_trade_gauge.md`.** Result: **SPY-200d stands as the whole regime
  tool.** Logistic KILLED (no lift, `stress_ew_vix` +0.85 = C7 wrong-sign reconfirmed multivariate);
  XGBoost lifts only on hostility (0.602 vs 0.568) and ONLY in crises (2016/2022) — a crash-detector,
  not a calm-market gauge. Coincident bad-days are ~coin-flip to nowcast; the Q15 5× gap is a
  mean-shift, not day-level separability. → **§1.2 splits on SPY-200d only** (no second axis).
- [x] **Regime-indicator test manual (15-candidate sweep, GATES §1.2). ✅ DONE 2026-07-14 →
  `verdicts/2026-07-14_regime_indicator_manual.md` + `cells/regime-indicator-results.ipynb`.**
  Extends §0.5.3 from the macro-pillar cut to the full price/breadth candidate field: §6 SPY/QQQ
  technicals (200d slope+dist, ADX, Donchian, SuperTrend, Aroon, BBW, RS), §4 whole-universe breadth,
  §2 RV-target, §5 batch. **All 15 FAIL.** Block A (nowcaster AUC): best = breadth 0.55 vs SPY-200d
  baseline 0.531 — nothing near the 0.65 wall; only significant deltas are candidates *worse* than
  baseline. Block C (cone, the two §7 leads §6.8 slope + §4 breadth): both FAIL — standalone gates
  score **worse** than SPY-200d (slope median Sharpe 0.59, breadth 0.46 vs 0.76), composed-OR arms
  are washes (≈0.76, candidate deploy-days overlap SPY>200d → the §0.9 overlap trap, candidate ≡
  incumbent). Breadth's one bright spot (calm-year AUC 0.71) does NOT convert to P&L (label lift ≠
  trade edge). **5th independent falsification of "a second regime axis beats SPY-200d."** →
  **REGIME-EXPRESSION QUESTION CLOSED: SPY-200d is the whole axis; §0.5.4 fork resolves to ONE axis;
  §1.2 is unblocked and splits on SPY-200d up/down only.**
- [ ] **§1.2b — per-regime gate sweep. ← NEXT ACTIONABLE (assessed 2026-07-14, §1.2 above).** Split
  the Q47 gate result by SPY-200d regime: does a higher gate pay in clean bull while hurting in chop?
  **Cheap re-cut confirmed**: `champion_trail` (UNGATED) cone's 90 `trades.parquet` = 2664 trades in
  both regimes; tag each by SPY-200d-at-entry, sweep gate 0.15→0.30 on the above-200d subset. Diagnostic
  only → promote to a bull-only cone if the split shows the pooled median hid a regime interaction. The
  concrete test of the user's live-pick hunch.
- [x] **§1.1 — portfolio-level DD circuit breaker.** ✅ IMPLEMENTED 2026-07-13 (see IMMEDIATE
  above); cone floor-lift test is the next run.
- [ ] **§1.2a — regime-tiered fan/cone.** Run the equity-fan / cone analysis PER regime (coarse:
  200d up/down) instead of one blended cone. Formalizes tiered usage.
- [ ] **§1.3 — m02 breakout-probability classifier** (reframed as watchlist ripeness, not
  selection alpha). Only if §1.2 shows tiering has legs.

### ⏸️ DEFERRED (after the above)
- [ ] **Granular day-level dispersion within good vs bad months.** How much does picking the wrong
  DAY inside a known-good month cost — quantifies residual day-luck after regime is controlled.
  Cheap on the existing `entry_timing_daily.parquet` × regime label. Deferred per user.
- [ ] **1-day entry delay on the EQUITY FAN.** Re-test `entry_delay_days=1` in the fan/basket lens
  (single-factor forward-return, no slot-book confounds — where the backtest version was
  inconclusive: short window + too many interacting factors). Engine already supports E2;
  `basket_paths` can take a delay. Isolates: does waiting one day to confirm the breakout hold
  change the distribution?
  
---

## Cross-refs
- Thread L trail cone: `verdicts/2026-07-13_4class_vs_binary_TRAIL_cone.md`
- Q47 gate sensitivity: `verdicts/2026-07-11_prob_elite_gate_sensitivity.md`
- Governor / stress-axis: `verdicts/2026-07-09_regime_governor_backtest.md`
- Regime state label: `verdicts/2026-07-08_m6_regime_state_label.md`
- Memory: [[project_entry_timing_macro_axis]], [[project_capital_deployment]],
  [[project_weather_gauge_shortlist]], [[project_scoring_vs_selection_unclipped]],
  [[project_regime_during_period_goal]], [[project_backtest_stop_gap_fill]].
