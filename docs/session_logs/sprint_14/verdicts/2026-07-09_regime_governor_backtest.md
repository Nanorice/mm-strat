# Regime governor — promoted to a REAL backtest (M2→M3): a DD dial, NOT a strategy fix

> **⚠️ READ §6 FIRST for the current position.** §1-§5 (the mid-session cone build) conclude "bank as a
> DD-control overlay" — the later start-day-lottery analysis DOWNGRADES that: the governor trims the
> GOOD trades, not the bad ones, and is NOT usable as a strategy improver (§6c). The real fix is
> Minervini's conditional entry + trailing-stop discipline (§6d), which is task (a) for next session.

**Date:** 2026-07-09 · **Status:** ✅ BUILT + RUN through the 25y start-date cone, then REASSESSED on
the start-day lottery lens (§6). Net verdict: a usable RISK DIAL, NOT a strategy fix — flat should stay
the champion. Closes the point-8 promotion ("EDA reweight → real backtest").
**Model:** `m01_binary` (calibrated), the loadable champion (prototype can't — `daily_predictions`
holds only ~1yr, can't span the 25y cone).
**Wiring:** `src/backtest/macro_sizer.py::governor_weight` (new `--sizing governor` mode) →
`equity_curve(exposure=w)`; cone via `scripts/run_strategy_wfo.py` (added `--sizing`, `--scores-parquet`,
per-fold cone metric). Scores cached once via `scripts/cache_model_scores.py`
(`data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22.parquet`, 8.9M rows).

---

## 1. The spec that went into the backtest (LIVE-SAFE)

Two signals, two jobs (from [[project_entry_timing_macro_axis]]):
- **TILT** — size up on stress: full exposure in the **top expanding-quintile** of `stress_ew_vix`
  (expanding-z of +credit −rates −cape +vix), `GOV_BASE_W=0.5` below.
- **GATE** — the tail brake: **zero exposure when SPY ≤ 200d** MA.

Both cuts are **live-safe**: the composite is an expanding-z (day *t* uses stats through *t−1*),
the quintile threshold is an **expanding quantile** (the EDA used full-sample cuts — can't size live
capital), and the whole weight is lagged one business day. Self-check in `macro_sizer.py::__main__`.

## 2. The 25y start-date cone (20 anchored yearly folds, 40 trials/fold, calibrated)

| Arm | Agg Sharpe | Agg ann_ret | Agg maxDD | Cone median | Cone min | Cone max | %neg folds | median fold DD | worst fold DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **flat** | 0.48 | 615% | −50.7% | **0.76** | −1.47 | 2.68 | 35% | −28.9% | −46.1% |
| **vix** | 0.44 | 278% | −37.5% | 0.64 | −1.58 | 2.30 | 35% | −17.5% | −33.6% |
| **governor** | 0.51 | 212% | **−25.4%** | 0.51 | −1.54 | 2.68 | 35% | **−13.6%** | **−19.1%** |

## 3. What it says (the honest verdict)

1. **The governor is a genuine, start-date-ROBUST drawdown controller.** Worst single-fold DD
   **−46% → −19%**, median fold DD **−29% → −14%** — both roughly halved, at *every* start-year, not
   just in aggregate. Aggregate maxDD −50.7% → −25.4%. This is the real, durable win, and it survives
   the cone (the whole thread's lesson: judge the distribution, not one number).
2. **It does NOT improve the Sharpe or the fold-sign distribution.** All three arms have the **same
   35% negative folds** and the same worst folds (2008/2011, ≈ −1.5). The brake lowers drawdown
   *within* the surviving exposure; it can't rescue a bad start-year, because the losing years are
   *bear* years where the SPY gate has already flattened exposure — there's little left to protect.
3. **On the M3 stability objective it COSTS median Sharpe (0.76 → 0.51)** and most of the total return
   (615% → 212%). Base-0.5 sizing damps the winning folds while the bad folds stay bad. A pure brake
   mechanically cannot lift the mean.
4. **VIX is strictly dominated** — lower Sharpe than both, worse median than flat, worse maxDD than
   governor. Confirms [[project_entry_timing_macro_axis]]: VIX-sizing is the same bear axis, blunter.

## 4. WHY the "improves both" EDA story didn't survive: GATE × TILT cancel

Measured directly (`macro_sizer.py`, 2007-2022): of ~467 top-quintile-stress days in the window, only
**18** are also SPY>200d (**bull-stress**). The SPY gate zeroes ~96% of the "size up on stress" days
because **high stress ≈ below-200d ≈ falling knife** (rebound lives sub-200d — the exact tension from
[[project_entry_timing_macro_axis]] C7). So once the gate is applied the **stress-tilt is nearly
inert**, and the governor reduces to point-8(**a**), the pure SPY-200d variance brake. The EDA's
point-8(**b**) "improves both" was per-$-deployed on the rare bull-stress cell (~18% capital); at full
book, the brake dominates and the tilt disappears. This is a real design property, not a wiring bug —
and the self-check documents it (`full-size 0%` over calm/gated windows is EXPECTED).

## 4b. What drawdown is it controlling? (user Q) — regime bleed, NOT gap-down; complements the stop-loss

The backtest already has a ~15% stop-loss, so: what does the governor add? **They control different,
non-overlapping drawdowns and compose cleanly (no double-count, no conflict):**
- **Stop-loss** runs INSIDE `run()` (`_simulate_exits`, `stop_level = entry×0.85`, `hit_stop = low ≤
  stop_level`) — it truncates each trade's window **per-position, intraday**. It catches a *single
  name* falling ≥15% from its own entry.
- **Governor** runs in `equity_curve` (multiplies the daily BOOK return by exposure) — **per-calendar-
  day, portfolio-wide**. It catches *market-regime* drawdown (SPY≤200d) hitting *all names at once*.

**Proven empirically (2007-09):** the stop-loss fired **64-76 times** (each booking −15%) and the flat
book STILL fell **−56%**, because the regime-blind strategy kept re-entering fresh breakouts into the
decline and getting stopped again. The governor gated 58-93% of the window → **−12%**. So the governor
is *"don't repeatedly re-enter a falling market"* control — a portfolio-level regime brake the per-name
stop structurally cannot provide. It is **NOT a gap-down tool** (gaps are the stop's domain).
`cells/governor_vs_stoploss_cells.md`, `governor_vs_stoploss_2008.png`.

**⚠️ SEPARATE CAVEAT — gap-down loss is UNDERSTATED (quantified; own ticket, doesn't change the verdict):**
on a stop-out the backtest books the fill at `stop_level` exactly (`_simulate_exits` line 342-344) —
i.e. it assumes a fill at −15% even when the stock GAPS OPEN below the stop (`hit_stop` fires on
`low ≤ stop_level`, but the real fill is the open). Measured over the full 25y stop-out population
(329 stop-outs): **7.0% gap through the level**; on those gapped stops the **real loss averages −19.7%
(worst −39.8%)** vs the booked −15%. Averaged over ALL stop-outs the understatement is only **−0.33%**,
so it does NOT distort the headline cone — but the −40% tail case matters for a tail-focused strategy.
**Fix = book gap-outs at `min(stop_level, open)`** (a stop-loss realism change, orthogonal to the
governor). The governor reduces gap EXPOSURE (fewer bear days held) but does NOT fix gap MODELLING.
`cells/governor_vs_stoploss_cells.md` Cell 5 quantifies it.

## 5. Decision & scope (mid-session — SUPERSEDED by §6, kept as the record)

**BANK the governor as a drawdown-control sizing overlay** (`--sizing governor`), not as an alpha or
stability improver. It is the right tool when the objective is capital preservation / DD-halving and a
lower Sharpe/return is acceptable. It is NOT a replacement for flat when the objective is risk-adjusted
return — flat wins the median cone. **Not tuned** (user, 2026-07-09): the `GOV_BASE_W=0.5` and the hard
SPY=0 gate are un-swept; a base-weight sweep or a *soft* gate (revive the tilt by de-weighting rather
than zeroing bear-stress) are open levers, deliberately NOT pursued (the cone lesson warns against
fitted knobs; the gate×tilt cancellation is a finding to record, not engineer around).

**Artifacts:** `models/m01_binary/wfo/calibrated_{flat,vix,governor}/wfo_{results.json,report.md}`.
cf [[project_regime_during_period_goal]] (this is the during-period behaviour the governor expresses),
[[project_capital_deployment]] (SPY>200d as the during-period gate), point-8 in the sprint 14
RESEARCH_LOG.

---

## 6. POST-CONE REASSESSMENT — is it usable as a governor? (added end of 2026-07-09, after the lottery lens)

> ⚠️ **§1-§5 above were written mid-session and OVERSELL the governor.** The later start-day-lottery
> analysis (`start_day_lottery_cells.md` Cell 2b, `minervini_overlay_cells.md`) materially downgrades
> the verdict. Read this section as the current position.
>
> ⚠️⚠️ **§6 itself was computed on an INFLATED population** — see [§7](#7-re-run-on-the-corrected-sepa-gated-population-2026-07-09).
> The score cache scored EVERY trend-active t3 row (~99% off-setup), and the basket lottery selected
> top-5 from that pool, so the extreme numbers below (esp. the +823% max and its −202% "kneecap") came
> largely from off-setup crash-rebound draws. §7 re-runs the SAME lens on genuine breakouts (trend_ok
> AND breakout_ok). **Direction of every §6 conclusion holds; the magnitudes shrink sharply.**

### 6a. On the lottery, the governor trims the GOOD trades, not the bad ones (user, 2026-07-09)
Reframing the strategy as a per-start-day basket lottery (fixed 5-name equal-weight basket, removes the
exposure-drift artifact) and comparing WITH vs WITHOUT the governor **by percentile**:

| | p05 | p10 | median | p90 | p95 | max | losing% |
|---|--:|--:|--:|--:|--:|--:|--:|
| no governor | −15.0% | −15.0% | +5.6% | +54.0% | +76.4% | **+823%** | 42% |
| with governor | −15.0% | −15.0% | +6.3% | +51.8% | +69.9% | **+202%** | 41% |

**The downside is IDENTICAL (p05/p10 both −15%, losing% 42→41% trivial). The trim is ALL upper-tail
(p95 −6.5%, max +823%→+202%).** So at the single-basket level the governor is **kneecapping the
winners**, not protecting losers — exactly the user's read. The 234 SPY≤200d start-days it drops have a
*high* mean (+18.1%, crash-rebound jackpots) but a *low* median (+1.9%) and 47% losing — it removes
low-median/high-variance draws, which is why median ticks up and variance falls.

### 6b. Reconciling with §2's −46%→−19% DD "win" — both are true, different scales
A single 5-name basket can only lose 15% (all names stop out) — there is no sequencing, so at the
basket scale there is nothing to protect. **The cone's drawdown improvement is a COMPOUNDING effect:**
a bear gates off entry for up to **51 CONSECUTIVE start-days**; in a real shared-pool book those
consecutive losing baskets compound into the −46% drawdown. The governor avoids the SEQUENCE. So §2 is
not wrong — but it measures compounded sequence risk, and §6a measures single-draw shape. **Net: the
governor buys compounding-DD protection by sacrificing the exact right tail SEPA's edge lives in.**

### 6c. Straight answer: is this usable as a governor?
**No — not as a strategy improver, and not worth wiring into the arena.** It is a pure risk-reduction
dial: it lowers compounded drawdown at the cost of median Sharpe (0.76→0.51), total return
(615%→212%), and the multi-bagger tail (+823%→+202%). For a **tail-magnitude** strategy
([[project_tail_magnitude_objective]]) that is a bad trade — you are paying with the exact outcomes the
edge depends on. Keep `--sizing governor` in the codebase as an optional DD-control knob for a
risk-averse mandate, but **the default/champion should be flat.** The governor does NOT solve the real
problem (the lottery); it just narrows both ends of it.

### 6d. What the analysis says to do instead — Mark Minervini's post-watchlist discipline
The governor is a macro overlay bolted onto a structurally lottery-like core (fixed day-0 top-5, fixed
hold). No sizing overlay fixes that. Minervini's *Trade Like a Stock Market Wizard* method is the
alternative, and it is CONDITIONAL/PATH-DEPENDENT rather than static:
1. **Pivot-trigger entry** — enter only on a VCP-pivot breakout, not because a name is on the list.
   (Already in our data: `t3.breakout_momentum>0 & vol_ratio>1.4`; regime-aware — 28% fire in a bull,
   ~1% in a crash. But the model ALREADY prices VCP via `prob_elite` → the trigger is largely a
   double-count; tested = a NULL in the fwd lens.)
2. **Progressive exposure** — starter position, add only on confirmation (press winners, starve losers).
3. **Tight stop (5-8%)** — the real risk tool; it DOUBLES the win/loss payoff ratio (2.85→6.18 at 7% vs
   15%). Corrects an earlier wrong claim in this thread that tight stops "hurt" — they only hurt a
   FIXED-HOLD basket that can't concentrate into the survivors.
4. **Trailing stop to breakeven + asymmetric exits** — where the tight-stop asymmetry is actually
   harvested.

**Tested in the forward-return lens: the Minervini overlay is a NULL** (worse median/losing% than the
naive basket) BECAUSE the lens is exit-naive (no trailing-stop-to-breakeven, no intraday adds) and the
entry-trigger is a double-count. The doubled payoff ratio is the real signal: the asymmetry exists but
must be harvested in the ENGINE. **→ Next (task a): port the trailing-stop-to-breakeven exit into
`vectorized_backtest.py` and re-test on the cone + lottery lens.** `minervini_overlay_cells.md`,
`start_day_basket_paths.py::basket_paths_minervini`, `minervini_conclusion.png`.

**Bottom line:** the governor is a usable RISK DIAL but not a strategy fix; the actual fix is replacing
the static-basket core with Minervini's conditional entry + tight-stop/trailing-stop exit discipline.

---

## 7. RE-RUN ON THE CORRECTED, SEPA-GATED POPULATION (2026-07-09)

> **The population-inflation fix.** `UniverseScorer.score_from_t3` scores the WHOLE trend-active t3
> panel; the score cache + basket lottery + backtest selectors then took top-5 by `prob_elite` from that
> pool WITHOUT filtering `trend_ok`/`breakout_ok`. Only **~1% of scored rows are genuine breakouts**
> (~16–20/day), so §2/§6 selected largely from off-setup price action — a stock scored mid-downtrend is
> out-of-distribution for a breakout model. Fixed by gating every selection layer on
> `trend_ok AND breakout_ok` (the per-(ticker,date) score is unchanged — only WHICH tickers are
> selectable). Flags joined from `t3_sepa_features` at read time (`src/backtest/sepa_gate.py`); NO
> re-score needed, existing cache stays valid. Pre-gated population cached to
> `data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22_sepa_gated.parquet` (122k rows).
> Guards: `tests/test_sepa_gate.py`, `sepa_gate.py::__main__`.

**Net verdict: every §6 conclusion survives; the magnitudes shrink and the governor gets even weaker.**

### 7a. Point 3 (lottery) re-run — governor now nearly INERT (SL 15%, horizon 150, sample_every=5)

| arm | n | mean | median | std | losing% | p95 | max | payoff |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| SL-only, **no gov** | 1136 | +7.4% | +3.2% | 24% | 43% | +44% | **+307%** | 2.09 |
| SL-only, **+gov** | 935 | +8.4% | +3.9% | 25% | 41% | +46% | **+307%** | 2.22 |
| SL+TP(25%), no gov | 1136 | +4.1% | +4.1% | 11% | 32% | +25% | +25% | 1.18 |
| SL+TP(25%), +gov | 935 | +4.5% | +4.6% | 11% | 30% | +24% | +25% | 1.22 |

Governor by-percentile (SL-only): **p05/p10 IDENTICAL −15.0%** (downside untouched, as before), median/p90/p95
all **+0.8–1.2%**, **max unchanged (+307% both arms)**.

- **The §6a "kneecaps the winners" claim is now BARELY TRUE.** On the inflated pool the governor cut the
  max **+823%→+202%**; on genuine breakouts it cuts **nothing at the top** (max +307% either way) and
  nudges every percentile *up* by ~1%. The +823% jackpots were off-setup crash-rebound draws that the
  gate now excludes from BOTH arms. So the governor is close to **inert** here — neither protecting the
  downside nor clipping the upside. This makes §6c *stronger*, not weaker: it's not even a meaningful
  DD-vs-tail trade at the single-basket scale; it's a near-no-op that still costs median Sharpe at the
  compounded/cone scale (§2 unchanged — that's a sequence effect the basket can't show).
- **SL vs TP confirmed and cleaner.** SL enforces the −15% floor; TP(+25%) cuts losing% 43→32%, halves
  the fan (std 24%→11%), but caps the right tail hard (max +307%→+25%). Exactly the user's read: TP buys
  consistency by surrendering the multi-bagger tail SEPA's edge lives in.

### 7b. Point 4 (Minervini stop sweep) re-run — asymmetry SURVIVES, even stronger (horizon 150, sample_every=10)

| stop | mean | median | payoff |
|--:|--:|--:|--:|
| 5% | +5.1% | −1.3% | **3.59** |
| 8% | +6.1% | +0.3% | 2.84 |
| 10% | +6.5% | +0.9% | 2.63 |
| 15% | +7.4% | +3.9% | 2.11 |
| 20% | +7.6% | +4.1% | 1.81 |

Payoff **3.59 (5%) → 1.81 (20%)** — a tighter stop still doubles+ the win/loss ratio, and the effect is
*larger* than the pre-fix 2.85→6.18 framing implied on clean breakouts. Yet on a FIXED-HOLD basket the
mean still FALLS as the stop tightens (+7.6%→+5.1% — whipsaw). Same tension as before.

Full overlay (trigger + progressive + 7% stop, sample_every=7): baseline median **+3.6%** →
Minervini **+0.6%**, losing% 42→48% — **still a NULL in this exit-naive lens**, while payoff rises
**2.31 → 3.61**. Nothing about the clean population rescues the overlay in a lens that can't harvest the
asymmetry.

### 7c. Bottom line after the re-run
The corrected population **did not change any conclusion — it hardened them**: (1) the governor is not a
strategy improver (now near-inert at basket scale, still a pure compounded-DD dial at cone scale; champion
stays **flat**); (2) SL bounds downside, TP trades tail for consistency; (3) the Minervini tight-stop
asymmetry is real and even sharper on genuine breakouts but **only harvestable in the ENGINE** (trailing
stop-to-breakeven + progressive fills), not in a fixed-hold basket. **→ Task (a) unchanged and now
better-motivated:** port the breakeven-ratchet trailing stop into `vectorized_backtest.py` (recommended
as a new `exit_policy='minervini'`) and re-test on the cone + lottery. Re-run:
`docs/session_logs/sprint_14/cells/regime-governor.ipynb` (points 3&4 cells now read the gated cache).
