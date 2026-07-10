# R3b verdict — rising-trail-from-entry FAILS: the trail clips the very winners that made champion_trail work

**Date:** 2026-07-10 · **Status:** ✅ CLOSED — 2 variants × 90-cell cone ran. Hypothesis FALSIFIED.
**Parent:** [`2026-07-10_r3_exit_selection_coupling.md`](2026-07-10_r3_exit_selection_coupling.md) (§Un-pursued: "rising trail from entry — the
single most-likely lever to turn champion_trail's +0.21 into something real"). Currency **C3**.
**Repro:** `run_starttime_sweep.py --strategy {champion_trail_e25,champion_trail_e15} --grid rolling
--cache-start 2003-01-01 --cache-end 2026-05-22 --step-months 3 --workers 3`.
**Artifacts:** `data/selection_sweep/starttime/champion_trail_e{25,15}/rolling/`.

## The hypothesis (from R3)

R3 diagnosed `champion_trail`'s ceiling: with tranches disabled, the SEPA trailing stop never engages
(it gates on `tranche1_sold`), so the runner sits on its **fixed initial stop** and bleeds the median
path on the way to the SMA trend break. The fix on the table: a stop that **ratchets up from entry**
at an ATR multiple, protecting the median without a tranche take-profit. Ex-ante tight/wide pair,
1.5× and 2.5× ATR. **Prediction: median-path protection lifts champion_trail's +0.21 further.**

## Result — the opposite: tighter trail = monotonically worse

| arm | exit | min | p25 | **median** | p75 | max | %neg |
|---|---|--:|--:|--:|--:|--:|--:|
| champion_gated | tranche (incumbent) | −2.81 | −0.38 | +0.47 | +1.17 | +3.85 | 33% |
| **champion_trail** | trend-exit-only (R3 winner) | −2.62 | −0.14 | **+0.46** | +1.29 | +3.36 | 33% |
| champion_trail_e25 | + 2.5×ATR trail-from-entry | −3.40 | −0.73 | **+0.32** | +1.16 | +3.05 | 44% |
| champion_trail_e15 | + 1.5×ATR trail-from-entry | −3.42 | −1.17 | **−0.29** | +0.83 | +3.94 | 54% |

Paired vs `champion_trail` (the R3 winner it was meant to improve):
- e25 (wide): wins **33%** of cells, median Δ Sharpe **−0.49**.
- e15 (tight): wins **21%** of cells, median Δ Sharpe **−0.82**.

**The from-entry trail does not improve champion_trail — it degrades it, worse the tighter it is.**
e25 falls below even the incumbent; e15 goes outright negative-median. Kill criterion (a trail variant
that doesn't beat champion_trail) FIRED for both.

## Why — the trail destroys the mechanism that generated the edge (the honest read)

Exit decomposition (full panel):

| arm | n_trades | med PnL | med hold | win-rate | exit mix |
|---|--:|--:|--:|--:|---|
| champion_trail | 2,664 | −4.9% | 21d | 31% | **46% stop / 38% trend** / 16% liq |
| champion_trail_e25 | 5,191 | −2.7% | 15d | 38% | 90% stop / **2% trend** / 7% liq |
| champion_trail_e15 | 12,164 | −1.2% | 7d | 43% | 97% stop / **1% trend** / 2% liq |

The from-entry trail **eliminates the trend exit** (38% → 2% → 1%): the ratcheting stop *always* fires
before price can break the SMA, so the runner is never held to the trend. Trade count explodes
(2.7k → 12k), hold collapses (21d → 7d), win-rate rises (31% → 43%) — a stream of small scratches.

The cruel irony: **`champion_trail`'s +0.21 edge over the incumbent came precisely from holding to the
trend break** (its 38% trend exits are the tail-rides). The from-entry trail was meant to protect the
median but instead **clips the winners before they reach the trend** — it cures the median bleed by
amputating the tail that paid for it. The tail is still *reachable* (e15 max Sharpe 3.94, the biggest
of any arm) but only in rare cells; across the cone the whipsaw variance dominates and Sharpe punishes
it (%neg 33% → 54%). R3's median bleed was real, but the fix costs far more than the disease.

## Decision

- **Rising-trail-from-entry is KILLED as a champion_trail improvement**, both multiples. No further
  sweeping of the ATR level — the direction is monotone wrong (tighter = worse) and the mechanism
  (kills the trend exit) means no multiple in this family can help; a trail tight enough to protect
  the median is tight enough to clip the tail. Widening past 2.5× just asymptotes back toward
  champion_trail (the trail stops binding).
- **`champion_trail` remains the R3 candidate exit** — trend-exit-only, +0.21 over the incumbent,
  deploy-gate re-confirm still pending. R3b confirms it is a *local optimum* in the trail family:
  the median bleed is the price of the tail-ride, not a fixable defect.
- **The R3 "un-pursued lever" is now pursued and closed.** The only remaining R3 idea — a *hybrid*
  (one tranche to bank the median + let the runner trail) — is a different structure (re-introduces a
  take-profit), not a trail-tuning; it needs its own ex-ante thesis if ever taken up. Not recommended:
  R3b shows the median bleed and the tail are the same coin; banking the median via a tranche is what
  the incumbent already does (and champion_trail beat it by *not* doing).

## Code / tests shipped

- `trail_from_entry_atr` param: [position_tracker.py](../../../../src/backtest/position_tracker.py) `update_stops` (ratchets from
  first bar; high-water logic keeps it ≥ initial stop), wired via [sepa_strategy.py](../../../../src/backtest/sepa_strategy.py)
  `_update_all_stops`. Off by default (0.0) — zero change to existing arms.
- Arms `champion_trail_e25` / `_e15` + `Xtr.e{N}` fingerprint token (emit-only).
- Unit test [test_trail_from_entry.py](../../../../tests/test_trail_from_entry.py) — off-default / ratchet-up / never-below-initial (3 pass).
- Smoke caught the profile shift pre-cone (100% stop exits, hold 69d→7d) — flagged as needing the
  cone to adjudicate whipsaw-vs-tail; the cone adjudicated: whipsaw wins, hypothesis dead.

## Guardrail compliance

BackTrader cone (never vec, [[project_vec_engine_optimistic]]); post-gate-fix population; identical
harness to R3 (A/champion_trail reused); ex-ante multiples, no post-hoc level sweep after seeing the
cone (the M3/M4 failure mode); trail verified live pre-cone (100% of shared exits differ from
champion_trail). Label→trade currency is C3 throughout.

## Program consequence

The SEPA funnel program's last live thread is closed. `champion_trail` (+0.21, trend-exit-only) is the
**final** candidate exit refinement — deploy-gate re-confirm is the only remaining action before it can
be promoted or parked. No further exit-family research is indicated: the tranche→trend-exit step was
the real lever, and it is a local optimum. See [[project_sepa_three_currencies]].
