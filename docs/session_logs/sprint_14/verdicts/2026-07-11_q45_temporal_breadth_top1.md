# Q45 — temporal breadth via entry cadence: WASH (the knob doesn't bind)

**Date**: 2026-07-11 · **Thread**: J · **Arm**: `champion_trail_spygate_top1` (registry)
**Design**: identical book to the champion (5 slots, 20% sizing, trail exit, SPY-200d gate),
ONLY the entry cadence changed: max 1 new position/day (top-1 by prob_elite) vs same-day top-5
fill. 90-cell rolling cone (quarterly starts × 12m, 2003–2026), paired vs the champion's cone.

**Prerequisite fix**: `entry_top_n` was declared but NEVER ENFORCED in
`SEPAHybridV1._process_entries` (entries sliced by `available_slots` only). Fixed with a per-bar
cadence cap + `daily_cap` rejection reason. Champion regression-verified byte-identical
(slots=5 ≡ top5); smoke tests pass.

## Result (Sharpe cone, 89 paired cells)

| metric | champion (top5 fill) | top1 drip | Δ |
|---|--:|--:|--:|
| min (floor) | −1.93 | −2.06 | −0.13 |
| median | **0.76** | 0.65 | **−0.10** |
| p75 | 1.40 | 1.12 | −0.28 |
| IQR | 1.45 | 1.13 | −0.32 |
| % cells Sharpe<0 | 28% | 26% | −2pp |

Paired: top1 wins 40% of cells; era medians −0.55 (2003-04), −0.26 (2005-09), ≈0 from 2010 on.

## Why: the cadence cap barely changes the book

Drip anatomy (median/cell): 23 trades (= champion), mean open 3.7/5 (champion 3.8), 52% of days
full (champion 55%), **days-to-full from cell start = 5**, and only ~14 `daily_cap` rejections
per year. With ~29-day holds, slots free at ≤1/day anyway — one entry/day refills as fast as the
champion does. The only behavioral difference is the first week of a window (and post-gate-shut
reopenings), where the champion fills 5 same-day and the drip takes a week. In the early-2000s
momentum eras that delay costs (−0.26..−0.55); afterwards it's noise.

## Verdict

**Temporal breadth through entry cadence is already implicit in the slow rotation** — the
stagger the fan analysis motivated exists naturally because the book turns over ~23×/yr across
5 slots. The drip variant narrows the cone slightly (IQR −0.32) but pays median (−0.10) and
doesn't lift the floor. **Not promoted; champion unchanged.**

Wave 2 (pool variants: new-candidates-only / trailing-average / age-decayed score) — **PARKED**:
the cadence knob doesn't bind, so pool-freshness variants would only re-order which name takes a
freed slot, and within-pool re-ranking is a closed kill (m01a M3, §3c weak-ranker).

**The live lever left is slot COUNT / capital, not cadence or pool**: rotation anatomy (Q44)
showed the no_slots queue is near-book quality (fwd100 +5.7% vs +6.4%). The honest next test is
one ex-ante arm (e.g. 10 slots @ 10% sizing, same everything) — a capacity question, not a
selection question. NB this is NOT the closed Q14 "top-10 per day dilutes" result: Q14 widened
the same-day pick; a slot-count arm deepens the book across days, drawing from the queue Q44
priced. One arm, no sweep (cone-fitting guard).

## Caveats
- 12m windows understate the drip's slower first-week deployment less than shorter windows would.
- daily_cap ≈14/yr means the arm tested a weaker treatment than "1/day" suggests — the
  conclusion is "cadence doesn't bind", not "stagger is harmful".
