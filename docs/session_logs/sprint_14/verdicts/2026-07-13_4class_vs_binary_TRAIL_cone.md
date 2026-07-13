# 4-class vs binary ON THE CHAMPION TRAIL-EXIT — binary WINS, decisively

**Date**: 2026-07-13 · **Thread**: L (binary-over-4class) · **Status**: ✅ CLOSED — the
last-mile BackTrader confirm. Binary is the deploy candidate; 4-class does not catch up
under the real exit even at a tight high-conviction gate.

## Question (user)
The earlier 4-class-vs-binary cone used a SIMPLE exit (SL10%/SMA50). Binary won there,
but on the champion's TRAIL exit (15% stop + SMA50, no tranche TP) — the real deployed
config — does 4-class close the gap? Run 4-class through the champion trail-exit and
compare to the binary champion cone. **User steer on the gate:** the 4-class arm is
*gated and ranked*, gate = **0.60** (a deliberate ~96th-pctile HIGH-CONVICTION cut —
prob_class_3 median is 0.24, so 0.60 is tight by design; "tight gate, tight capacity").
On a day with no qualifying name the rolling book keeps scanning subsequent days (live
behaviour), not a fixed day-1 basket.

## Method
- **Arm**: `champion_trail_spygate_4cls` (registry) = the binary champion config
  (`_trail_only(_champion_kwargs())` + SPY-200d gate) with **signal + gate swapped only**
  (`proto_cali_gated`, `min_prob_elite=0.60`). Self-check asserts diff-from-champion is
  exactly {signal, min_prob_elite}.
- **Reference**: the existing binary champion cone `champion_trail_spygate` (median 0.76).
- **Population**: SEPA-gated (trend_ok ∧ breakout_ok), 4-class prod prototype scored over
  full span — cache `m01_prototype_2003-01-01_2026-05-22_sepa_gated.parquet` (built this
  session; **no re-scoring**).
- **Cone**: 90 quarterly starts × 12m, BackTrader, 2003–2026. Both arms identical exit
  (15% stop + decoupled SMA50, tranches OFF) + SPY-200d deploy gate.

## Result — Sharpe cone (88-cell paired intersection)

| metric | BINARY @0.15 | 4-CLASS @0.60 | Δ (4c − bin) |
|---|--:|--:|--:|
| n cells | 89 | 88 | — |
| min (floor) | −1.93 | **−2.38** | −0.45 |
| p25 | −0.05 | −0.37 | −0.32 |
| **median** | **0.76** | 0.33 | **−0.42** |
| p75 | 1.40 | 0.76 | −0.64 |
| max | 3.35 | 2.74 | −0.61 |
| IQR (spread) | 1.45 | 1.13 | −0.32 |
| **%neg cells** | **28%** | 38% | +9pp |
| median ann_return | 18% | 5% | −13pp |
| median maxDD | −18% | −18% | ~0 |

**Paired**: 4-class wins only **28/88 cells (32%)**, median paired Δ **−0.44**, mean −0.47.
**Era-stable loss** — 4-class loses every third:

| era | binary med | 4-class med |
|---|--:|--:|
| 2003–08 | 1.22 | 0.18 |
| 2009–17 | 0.77 | 0.55 |
| 2018–26 | 0.47 | 0.18 |

## Findings
1. **Binary beats 4-class on the champion trail-exit, decisively and everywhere** — lower
   median (0.33 vs 0.76), lower floor (−2.38 vs −1.93), MORE negative cells (38% vs 28%),
   a third the median return (5% vs 18%). Not a marginal/lens artifact: paired 32% win
   rate, negative in all three eras.
2. **The tight 0.60 gate did NOT rescue 4-class.** The user's hypothesis (high-conviction
   gate compensates for capacity) is falsified for THIS model+exit: the gate only narrows
   the spread slightly (IQR 1.45→1.13) — the same variance-knob signature as Q47 — while
   the floor and median both get WORSE. A tight gate on a weaker ranker just starves the
   book (median ann_return collapses to 5%) without buying the consistency it bought binary.
3. **Consistent with the simple-exit cone, and stronger.** The SL10%/SMA50 cone had binary
   0.81 vs 4-class 0.52 (each at own best gate). The trail exit widens the gap (0.76 vs
   0.33). Binary's advantage is NOT exit-specific — it holds on the deployed trail exit too.
4. **The floor is worse, not just the median** — 4-class's −2.38 vs binary's −1.93 means
   the tight gate didn't even protect the downside it was meant to. High-conviction 4-class
   entries in bad windows still blow through the 15% stop repeatedly (sparse book, each cell
   rests on few trades → fat left tail).

## Caveats / what this is NOT
- **Each model at its OWN gate, not a shared cut** (binary 0.15 calibrated / loose vs
  4-class 0.60 / tight — the scales aren't comparable, `project_scoring_vs_selection_unclipped`).
  This is "each at a sensible operating point", by user design — NOT a clean model-only
  isolation. But the direction is so large (−0.42 median) that gate choice can't flip it:
  the 4-class gate would have to *raise* its median by 0.42 to tie, and raising the gate
  LOWERS median on the trail exit (Q47) — so a looser 4-class gate wouldn't help either.
- Tight-gate 4-class is a sparse-entry strategy (~30% of days have any candidate) → some
  cells thin; 2/90 cells produced no computable Sharpe (dropped). The 88-cell cone is
  robust to this (era-stable).

## Decision
**Binary is CONFIRMED as the deploy candidate over the 4-class prod prototype.** It wins
the model cone on BOTH the simple exit AND the champion trail-exit; 4-class does not catch
up even with a tight high-conviction gate. The last-mile BackTrader gate every promotion
must pass is **passed for binary**.

**This closes the kill/keep question. It does NOT auto-promote** — promotion is a separate
go/no-go (set_prod + backfill_daily_predictions + rebuild dashboard DB; operating threshold
by per-day RANK not absolute floor). Held for user decision.

## Replication
Registry arm `champion_trail_spygate_4cls`. Run:
```
.venv/Scripts/python.exe scripts/run_starttime_sweep.py --strategy champion_trail_spygate_4cls \
  --grid rolling --cache-start 2003-01-01 --cache-end 2026-05-22 --step-months 3 --workers 3
```
Output: `data/selection_sweep/starttime/champion_trail_spygate_4cls/rolling/`. Compare vs
`champion_trail_spygate/rolling/` on the shared `r_*_h12` cells.

cf `2026-07-13_4class_vs_binary_cone.md` (the simple-exit cone this confirms on the trail
exit), `2026-07-11_prob_elite_gate_sensitivity.md` (Q47 — why a tight gate is a variance
knob on the trail exit), [[project_4class_vs_binary]], [[project_vec_engine_optimistic]].
