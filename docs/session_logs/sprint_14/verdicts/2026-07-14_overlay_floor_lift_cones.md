# Floor-lift cones: DD-breaker + earnings-blackout overlays vs champion — 2026-07-14

**Thread M (§1.1 + earnings arm).** Both overlays were WIRED 2026-07-13 (no-op-by-default, halt-new-
entries pattern) with the cone as the OPEN verdict. This runs the 90-cell start-date cone for each vs
the champion `champion_trail_spygate` baseline, judged on the **distribution** (floor-lift without
killing the median — the recurring variance-vs-median test that killed the governor), not aggregate
return. Full-span spec: `--cache-start 2003-01-01 --step-months 3 --workers 3` (90 quarterly cells).

Scripts: `scripts/overlay_cone_compare.py` (paired cone), `scripts/regime_gate_recut.py` (unrelated,
§1.2b). Baseline cone = `champion_trail_spygate/rolling/summary.json` (median Sharpe 0.757, floor
−1.934, %neg 27.8%).

---

## §1.1 DD circuit breaker (`champion_trail_spygate_ddbrake6`, 6% trip / 2% release) — ❌ REJECTED

**A pure book-brake that LOWERS the floor — the governor's fate, worse.** 90-cell paired cone:

| metric (cone) | baseline | ddbrake6 | Δ |
|---|---|---|---|
| Sharpe median | **0.757** | −0.038 | **−0.795** |
| Sharpe floor (worst cell) | −1.934 | −2.823 | **−0.889 (WORSE)** |
| Sharpe %neg | 27.8% | 50.0% | **+22.2pp** |
| maxDD floor (worst) | −0.444 | −0.250 | +0.194 |
| maxDD median | −0.184 | −0.114 | +0.070 |
| total_return median | +0.134 | −0.016 | −0.150 |

Differs in 89/90 cells, beats baseline in only **19/90**. The ONE thing it buys is drawdown control
(worst maxDD −44%→−25%, median −18%→−11%) — but at a catastrophic risk-adjusted cost: it drops the
Sharpe FLOOR it was built to lift and doubles the negative-cell rate.

**WHY (the mechanism — decisive, not the double-count trap).** Trip-timing check across all 90 cells
(179 trip events): **92% of trips (164) fire on gate-OPEN bull days (SPY>200d)**; only 8% (15) on
gate-closed bear days. So the breaker is NOT redundant with the SPY gate (unlike the governor, which
collapsed into it) — it is genuinely ADDITIVE. **But additive here means HARMFUL:** trips cluster in
the STRONGEST bull years (2020: 15, 2013: 13, 2014: 11, 2003/2005: 10) — routine bull-market pullbacks.
A 6% peak-to-trough book DD is INSIDE the normal noise of a tail strategy that stops out ~55% of names;
using it as a halt trigger means standing aside during ordinary bull wobbles and **missing the recovery
that carries the winners**. The floor DROPS precisely because the recovery is what the brake cuts. This
is the tail-strategy version of "don't sell your winners to avoid a drawdown."

**THRESHOLD SWEEP (6/10/15/20/30%) — settles mechanism-vs-threshold: it's MECHANISM at every level.**
Ran the full trip-level curve (`champion_trail_spygate_ddbrake{6,10,15,20,30}`, each differs from
ddbrake6 only by `dd_breaker_pct`):

| trip % | med Sharpe | floor | %neg | worst DD |
|---|---|---|---|---|
| **champion (no brake)** | **0.757** | **−1.934** | **27.8** | −0.444 |
| 6 | −0.038 | −2.823 | 50.0 | −0.250 |
| 10 | 0.347 | −2.980 | 40.0 | −0.250 |
| 15 | 0.490 | −3.102 | 35.6 | −0.291 |
| 20 | 0.709 | −3.405 | 31.1 | −0.309 |
| 30 | 0.750 | −3.055 | 30.0 | −0.368 |

Three monotone facts across the whole range: (1) median Sharpe RISES with the trip level (−0.04→0.75)
but **never exceeds the champion** — it asymptotes to "do nothing" (30% ≈ champion because the brake
barely fires); (2) the **floor is WORSE at EVERY trip level** (−2.82 to −3.41, all below champion's
−1.93) — there is NO threshold where the brake lifts the floor it was built to lift; each firing
commits to sitting out a deep bleed, so the worst cell always worsens; (3) drawdown control (the only
benefit) ERODES as you loosen (worst DD −0.25→−0.37 toward the champion's −0.44). **A strict
Pareto-loss to the champion across the entire 6→30% range: tight kills the median, loose ≈ do-nothing
with a worse floor. No trip level is a win.**

**Verdict: REJECTED at every threshold. `champion_trail_spygate` unchanged.** A book-level DD brake is
structurally wrong for a tail-continuation strategy — the drawdowns it halts on ARE the entry noise,
and halting always forfeits more recovery than it saves. The mechanism, not the threshold, is the
problem — now PROVEN across the full 6→30% sweep, not asserted. Consistent with the governor (DD-control
≠ alpha) and the whole sprint's finding that every "safety" lever is a variance knob.

---

## Earnings-blackout (`champion_trail_spygate_earn5`, N=5 full-exit) — ❌ REJECTED

**Worse than the DD-breaker — it costs return AND doesn't even buy drawdown.** 90-cell paired cone:

| metric (cone) | baseline | earn5 | Δ |
|---|---|---|---|
| Sharpe median | **0.757** | 0.489 | **−0.268** |
| Sharpe floor (worst cell) | −1.934 | −1.974 | −0.040 (flat-to-worse) |
| Sharpe %neg | 27.8% | 35.6% | **+7.8pp** |
| maxDD floor (worst) | −0.444 | −0.496 | **−0.052 (WORSE)** |
| maxDD median | −0.184 | −0.193 | −0.009 (WORSE) |
| total_return median | +0.134 | +0.074 | −0.060 |

Beats baseline in only 27/90 cells. It fails the floor-lift test on BOTH axes: it does not lift the
Sharpe floor (it lowers it), and unlike the DD-breaker it does not even reduce drawdown (maxDD is
uniformly worse). A pure cost.

**WHY (the mechanism — tail truncation, quantified).** Full-exiting 5 calendar days before every
scheduled print force-sells **630 trades = 23.6% of the entire book**, and **77% of those forced exits
are WINNERS**, exited at +17.4% mean. The champion's own trend-exit winners average +21.7% — so the
blackout is clipping its winners ~4pp BELOW where they'd have run. In a tail-continuation strategy the
winners are precisely the names in strong uptrends that keep reporting earnings *while they run*;
kicking a quarter of the book (mostly winners) out before each print truncates the exact tail the
strategy lives on. The gap-loss it was meant to avoid is tiny by comparison — the stop already books
gap-downs, and the aggregate gap understatement is only −0.33% ([[project_backtest_stop_gap_fill]]),
vs the multi-point tail it forfeits. Same "label lift ≠ trade edge / don't clip the tail" failure that
killed TP and tight stops.

**Verdict: REJECTED. `champion_trail_spygate` unchanged.** ⚠️ Un-tested lighter variants exist
(`earnings_exit_frac=0.5/0.33` partial-trim, or the `earnings_exit_min_ret` return-gate that only trims
winners past a threshold so underwater names ride to their own stop) — but the mechanism is
tail-truncation, and any variant that still exits winners before the print inherits it directionally.
A partial trim would only SCALE the damage, not flip its sign. Not worth a cone unless the framing
changes to "trim only extended/over-target winners" — which is a different, narrower idea.

---

## Thread M overlay conclusion

**Both floor-lift overlays REJECTED; `champion_trail_spygate` stays champion.** The §1.1 DD-breaker and
the earnings blackout join the governor, TP, tight stops, and the higher gate on the pile of levers
that trade the tail for consistency and LOSE — because in this strategy the "risk" they suppress (6%
book bleeds, pre-earnings names) IS the tail's entry/holding noise, and suppressing it forfeits the
winners that pay for everything. The champion's edge is inseparable from its variance; no book-level
brake or calendar exit tested has lifted the floor without killing more than it saved. The only lever
that ever shifted the distribution favourably remains the SPY-200d entry gate (already in the
champion). This closes the §1.1 + earnings arms of Thread M.

