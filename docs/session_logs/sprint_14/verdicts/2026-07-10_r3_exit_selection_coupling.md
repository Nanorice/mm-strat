# R3 verdict — exit×selection coupling: the TAIL-EXIT helps, but only on the CHAMPION'S selection; RS-tail stays un-monetizable

**Date:** 2026-07-10 · **Status:** ✅ CLOSED — 2×2 cone ran (4 arms × 90 quarterly cells 2003–26).
**Plan:** [`../plans/r3_exit_selection_coupling_plan.md`](../plans/r3_exit_selection_coupling_plan.md) ·
**Parent:** [`../plans/sepa_ground_truth_roadmap.md`](../plans/sepa_ground_truth_roadmap.md) · Currency **C3** (exit-aware P&L).
**Repro:** `run_starttime_sweep.py --strategy {rs_tail_trail,champion_trail} --grid rolling
--cache-start 2003-01-01 --cache-end 2026-05-22 --step-months 3 --workers 3`. Arms A/B reused from M4.
**Artifacts:** `data/selection_sweep/starttime/{champion_gated,rs_tail,rs_tail_trail,champion_trail}/rolling/`.

## The 2×2 cone (per-cell Sharpe, n=90 each)

| Arm | Selection × Exit | min | p25 | **median** | p75 | max | %neg |
|---|---|--:|--:|--:|--:|--:|--:|
| A `champion_gated` | champion × tranche | −2.81 | −0.38 | **+0.47** | +1.17 | +3.85 | 33% |
| B `rs_tail` | RS-D10 × tranche | −3.31 | −0.69 | **+0.10** | +0.65 | +2.75 | 47% |
| C `rs_tail_trail` | RS-D10 × **trail** | −2.72 | −0.65 | **+0.10** | +0.82 | +2.27 | 44% |
| D `champion_trail` | champion × **trail** | −2.62 | −0.14 | **+0.46** | +1.29 | +3.36 | 33% |

Paired by start-date (first arm wins X% of cells, median Δ):

| Contrast | wins | median Δ Sharpe | reads as |
|---|--:|--:|---|
| **C vs B** — does the trail rescue RS selection? | 53% | **+0.06** | **NO** — trail ≈ tranche on RS. Kill criterion for R3's headline test. |
| **D vs A** — does the trail help the champion? | 56% | **+0.21** | **YES, mild** — trail lifts p75 (1.17→1.29) and p25 (−0.38→−0.14), median flat. |
| **D vs C** — same exit, which selection? | 76% | **+0.42** | Selection dominates. The exit can't save a weaker picker. |
| **C vs A** — RS-trail vs the incumbent | 39% | **−0.34** | RS-trail still loses the incumbent outright. |

## The finding, in one line

**The tail-harvesting exit is real but it is NOT a substitute for good selection.** It adds a mild,
one-directional improvement *on the champion's own picks* (D > A, +0.21 median, p25/p75 both up) and
does **nothing** for RS-tail selection (C ≈ B). Selection is the binding constraint, not the exit —
the D-vs-C gap (+0.42, 76% of cells) is 2× the exit main-effect (D-vs-A +0.21).

This resolves the meta-plan's R3 branch cleanly: **branch 2** ("D > A but C ≁ B-lift → the trail helps
*any* selection… selection question stays closed") — with the sharpening that the trail helps the
*champion's* selection specifically, not any selection (it did nothing for RS).

## Why — the mechanism (from the trade logs, the honest read)

The trail does exactly what it was built to do; it just isn't enough.

| arm | n_trades | median PnL | median hold | exit mix |
|---|--:|--:|--:|---|
| A champion×tranche | 4,616 | −3.9% | 17d | 81% stop / 11% trend / 9% liq |
| D champion×trail | 2,664 | −4.9% | 21d | 46% stop / 38% trend / 16% liq |
| B RS×tranche | 5,127 | −4.1% | 15d | 83% stop / 11% trend / 6% liq |
| C RS×trail | 3,116 | −5.6% | 20d | 50% stop / 40% trend / 10% liq |

The trail arms hold longer (20–21d vs 15–17d), churn ~40% fewer trades, and flip the exit mix from
~82% stops to ~50/50 stop/trend — the runner **is** being held to the trend break, and the fat right
tail shows up (arm D max ann +424%, arm C +146%). **But the median trade bleeds ~1pp more** (D −4.9%
vs A −3.9%; C −5.6% vs B −4.1%): with no tranche sale, `update_stops` never engages the rising trail
(it gates on `tranche1_sold`), so the runner sits on its **fixed initial stop** and gives back more of
the median path on the way to the SMA break. The extra tail and the extra median-bleed roughly cancel
on RS (net +0.06); on the champion's better picks the tail slightly outweighs the bleed (+0.21).

**This is the structural cost of the trend-exit-only design we chose** (no rising stop under the
runner). It is the reason the trail is a mild tilt, not a step-change.

## Era stability (median Sharpe by date-third)

| arm | 2003–08 | 2009–17 | 2018–26 |
|---|--:|--:|--:|
| champion_gated | +0.49 | +0.63 | +0.31 |
| **champion_trail** | **+0.55** | **+0.76** | **+0.42** |
| rs_tail | +0.15 | +0.26 | −0.17 |
| rs_tail_trail | +0.00 | +0.31 | +0.00 |

`champion_trail` beats `champion_gated` in **all three eras** — the +0.21 tilt is era-robust, not a
one-window artifact. Notably it also **repairs RS-tail's 2018–26 negative** (rs_tail −0.17 → rs_tail_trail
0.00) — the trail stops RS-tail bleeding in the recent era but only up to break-even, still no edge.

## Decisions

1. **RS-tail is un-monetizable in this trade structure — CONFIRMED, both exits.** Median 0.10 under
   tranche (M4) *and* 0.10 under trail (R3). The 3.5× label-level tail lift does not convert under
   either exit. RS-tail = **watchlist-ordering value only**, as banked. The funnel's selection
   research is closed ([[project_population_reframe_tail_ranker]] extended to the trail exit).

2. **`champion_trail` is a CANDIDATE deploy-gate improvement, not a new champion.** +0.21 median,
   era-robust, floor/p25 improved, %neg unchanged (33%). It's an *exit* refinement on the *existing*
   champion selection — modest and worth a deploy-gate re-confirm (SPY-200d trunk,
   [[project_capital_deployment]]) before any registry promotion. **Do NOT promote off the cone
   alone** — the +0.21 sits inside start-date noise band width, and post-hoc exit tuning is the M3/M4
   failure mode. One ex-ante deploy-gate confirm decides it.

3. **The m01 de-gate is NOT triggered.** Per the roadmap go/no-go table, R3 landed on the "D > A but
   C ≁ B-lift" row → **de-gate NOT justified**: the improvement is the exit (orthogonal to
   selection), and RS-tail selection — which de-gating m01 would reproduce — stays null under the
   best exit we have. Training m01 on the de-gated panel would inherit C's 0.10. **De-gate stays
   parked.** ([[project_sepa_three_currencies]])

## Un-pursued (deliberately, no post-hoc sweeping)

- Rising trail *from entry* (ungate `update_stops` from `tranche1_sold`) — the "immediate ATR trail"
  option not taken in R3-M0. It would protect the median path the current trail bleeds, and is the
  single most-likely lever to turn champion_trail's +0.21 into something real. **Needs a fresh ex-ante
  plan**, not a sweep on this cone.
- Hybrid: tranche T1 to bank the median + let the *runner* trail (one tranche, not two). Untested.
- True MFE-capture ratio — trades carry `mae_pct`/`max_dd_pct` but no `mfe_pct`; the exit-mix + hold +
  median-PnL triangulate the mechanism without it. A path-level MFE join is the clean follow-up if the
  rising-trail plan proceeds.

## Kill-criteria evaluation (from the plan)

- ~~Neither trail variant changes the cone → conversion gap is structural (slots/stops/entry)~~ —
  PARTIAL: RS unchanged (C≈B) but champion improved (D>A). The gap is **selection-specific**, not
  purely structural. The trail *is* a real lever — just not on the weak selection.
- ~~C wins via 1–2 outlier cells~~ — did NOT fire; C simply ties B across the distribution.
- **C ≤ B → tail un-monetizable in this structure** — FIRED for RS-tail. Recorded; steps 3–4 re-aim
  at discretionary support per the meta-plan.

## Guardrail compliance

BackTrader (never vec, [[project_vec_engine_optimistic]]); post-SEPA-gate-fix population; A/B reused
from M4 (identical harness); trail arms verified non-no-op in R3-M0 (exit mix {stop,trend} only, exit
dates differ from tranche partner on 42% of shared trades); `disable_tranches` self-checked in the
registry `__main__`. All cells checkpointed/resumable.
