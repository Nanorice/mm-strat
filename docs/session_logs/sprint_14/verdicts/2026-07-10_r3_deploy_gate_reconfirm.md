# R3 deploy-gate re-confirm — the SPY-200d gate STACKS on the trail exit; `champion_trail` PROMOTES

**Date:** 2026-07-10 · **Status:** ✅ CONFIRMED — closes the last open action of the SEPA funnel program.
**Parent:** [`../plans/sepa_ground_truth_roadmap.md`](../plans/sepa_ground_truth_roadmap.md) §5 · Currency **C3** (exit-aware P&L).
**Precondition it satisfies:** R3 verdict decision #2 — "`champion_trail` is a CANDIDATE deploy-gate
improvement… worth a deploy-gate re-confirm (SPY-200d trunk) before any registry promotion." This is that re-confirm.
**Repro:** `run_starttime_sweep.py --strategy champion_trail_spygate --grid rolling --cache-start 2003-01-01
--cache-end 2026-05-22 --step-months 3 --workers 3`. OFF arm = `champion_trail` (R3 arm D). SPY-200d gate
dict built per-cell via `macro_sizer.spy_above_200d` (close-through-t, no lookahead).
**Artifacts:** `data/selection_sweep/starttime/champion_trail_spygate/rolling/`.

## The gap this filled

M4 (`2026-07-09_m4_deploy_gate_backtrader_confirm.md`) confirmed the SPY-200d gate on the **tranche** exit
(Sharpe 0.52→0.79). R3 shipped the **trail** exit (`champion_trail`, +0.21 over tranche) but left it
**ungated**. The exact deployment config — champion selection × trail exit × SPY-gate — had **never been
run**. Added `champion_trail_spygate` to the registry (`champion_trail` + a `spy_deploy_gate` sentinel;
gate injection generalized from a hardcoded name check to the sentinel) and ran it on R3's own cone.

## The cone (per-cell Sharpe, rolling quarterly, 2003–26)

| metric | `champion_trail` (gate OFF) | `champion_trail_spygate` (gate ON) | Δ |
|---|--:|--:|--:|
| n cells | 90 | 89 | — |
| min (floor) | −2.618 | **−1.934** | **+0.684** |
| p25 | −0.138 | −0.046 | +0.092 |
| **median** | 0.463 | **0.757** | **+0.294** |
| p75 | 1.290 | 1.400 | +0.110 |
| max | 3.360 | 3.352 | −0.007 |
| **%neg cells** | 33% | **28%** | **−5pp** |
| ann_return median | 11% | 18% | +7pp |
| maxDD median | −23% | −18% | +4pp |

**Every headline metric improves at once** — floor, median, %neg, return, drawdown — costing only a sliver
of the max (−0.007). This is the *same* "improves everything" signature M4 found on the tranche exit
(0.52→0.79 there; 0.46→0.76 here). **The gate stacks additively on the trail — they work harmoniously,
not at cross-purposes.**

## The one honest caveat — paired vs distributional

Paired by start-date, gate-ON "wins" only **32/89 cells (36%)**, median paired Δ **+0.000**. This is NOT a
contradiction — it is the gate's mechanism, identical to M4:

- On the ~70% of start-windows sitting in bull regimes (SPY fully above 200d), the gate blocks **zero**
  entries → Δ=0 → a tie, which the paired count scores as a non-win.
- Its entire value lands on the minority of **bear-spanning windows**, where it converts catastrophic cells
  into survivable ones (floor −2.62 → −1.93). So the *distribution* shifts hard even though most *pairs* tie.

A drawdown-avoidance overlay can only be valued on the windows that contain the drawdown (M4 §3,
[[project_vec_engine_optimistic]]). The **distributional cone is the correct lens**, and it is decisively
positive.

## Era stability (median Sharpe by start-date third)

| arm | 2003–08 | 2009–17 | 2018–26 |
|---|--:|--:|--:|
| `champion_trail` | +0.546 | +0.755 | +0.419 |
| **`champion_trail_spygate`** | **+1.247** | **+0.771** | **+0.466** |

Improves in **all three eras**; the big lift is 2003–08 (where the 2008 bear rescue lives — gate 2% open
that window, matching M4). Not a one-window artifact.

## Decisions

1. **The SPY-200d gate CONFIRMS on the trail exit.** `champion_trail` + gate is the validated deployment
   config: it compounds the R3 trail refinement (+0.21) with the M4-confirmed gate rather than interfering.
   **The last open action of the SEPA funnel program is closed.**
2. **`champion_trail_spygate` promoted to `status="champion"`; `champion` (tranche) demoted to
   `candidate`.** This is a C3-validated exit + deployment change on the *existing* selection — orthogonal
   to selection, which stays the m01 champion picker (de-gate remains parked, R3 decision #3).
3. **Guardrail:** ex-ante promote criterion (floor↑, %neg↓, median not costed) was set *before* reading the
   cone — met on all counts. No post-hoc sweeping; single gate threshold (200d), unswept, as in M4.

## Guardrail compliance

BackTrader (never vec); post-SEPA-gate-fix population; OFF arm = R3 arm D reused (identical harness);
gate dict verified regime-real before the run (2008: 2% open, 2013: 100% open — matches M4);
registry `__main__` self-check guards the new arm (trail preserved, differs from `champion_trail` only by
the gate); all cells checkpointed/resumable.

cf `2026-07-09_m4_deploy_gate_backtrader_confirm.md` (the tranche-exit confirm this parallels),
`2026-07-10_r3_exit_selection_coupling.md` (the trail exit this gates),
`../plans/sepa_ground_truth_roadmap.md` §5 (the open action this closes),
[[project_capital_deployment]] (SPY-200d as ex-ante gate), [[project_sepa_three_currencies]].
