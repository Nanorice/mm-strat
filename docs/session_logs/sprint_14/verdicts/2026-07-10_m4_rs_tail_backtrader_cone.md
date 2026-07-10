# M4 verdict — RS-selection loses the BackTrader cone to the incumbent: kill criterion #3, champion stays

**Date:** 2026-07-10 · **Status:** ❌ M4 gate FAILS (a *valid* outcome) — `../plans/m01a_tail_ranker_plan.md`
kill criterion #3: incumbent stays champion. Parent: `2026-07-10_m3_ml_vs_rs_bar.md` (RS rule = the
m01a selection signal). **This closes the m01a plan.**

## Setup — a clean A/B on SELECTION only, first full-span gated cone

Two arms, identical exits/slots (champion native tranche: sl15 × t1_10 × decoupled SMA50, top-5/day,
equal-weight), identical engine (BackTrader via `population_runner`), identical windows (rolling
**quarterly starts × 12-month horizon, 2003-01 → 2026-05 = 90 cells/arm**, the post-gate-fix SEPA
population):

- **`champion_gated`** (incumbent): rank breakouts by `prob_elite` (m01_binary calibrated, full-span
  SEPA-gated cache).
- **`rs_tail`** (challenger): no model — selection = top-decile per-date RS percentile over the FULL
  `trend_ok` panel (panel-wide `PERCENT_RANK`, not within-breakout), breakout as entry trigger
  (~6.5 candidates/day vs the champion's ~17). `_load_rs_scores` in `run_strategy_confirm.py`;
  registry arm `rs_tail`.

NB: the Jul-5 champion start-month cone (ann −39%..+197%, [[project_champion_starttime_dependent]])
predates the SEPA-gate fix — it ran on the ~99%-off-setup inflated population. **This run is the
incumbent's first honest full-span cone** and replaces those reference numbers.

## Result — the champion wins the whole distribution, in every era

| cone (per-cell Sharpe, n=90) | rs_tail | champion_gated |
|---|--:|--:|
| min (floor) | −3.31 | −2.81 |
| p25 | −0.69 | −0.38 |
| **median** | **0.10** | **0.47** |
| p75 | 0.65 | 1.17 |
| max | 2.75 | 3.85 |
| % cells Sharpe < 0 | 47% | 33% |
| median ann_return | −1.2% | +9.7% |
| median / worst maxDD | −23% / −53% | −20% / −51% |

Paired by start date: rs_tail wins only **33/90 cells**, median Sharpe margin **−0.37**. By era
(median Sharpe rs vs champion): 2003–08 **0.15 vs 0.49**, 2009–17 **0.26 vs 0.63**, 2018–26
**−0.17 vs 0.31** — the champion wins every third (rs's best era is 2018–26 at 47% cell wins, still
under half). Not under-deployment: rs_tail trades as much or more (spot-check 55–78 trades/cell vs
50–67) — the selection itself converts worse.

## Why a 3.5× label lift didn't convert (the honest mechanics)

The M2 finding contained its own warning: RS top-decile concentrates the **tail** (MFE_63 ≥ +30%)
while its **median inverts** (weak-RS beats strong-RS on median — reframe verdict probe 1). A slot
book with a 15% stop and a +10% T1 tranche realizes mostly **median-path** outcomes and truncates the
exact excursion the label measures — the champion's exits harvest the middle, and `prob_elite` was
trained on a tradeable-return objective that ranks that middle. So: **label-level tail lift ≠ trade
edge under these exits** — the selection-side rhyme of the m02 lesson ("signal works ≠ trade works"),
which is precisely what M4 existed to catch.

## Decision

- **Incumbent stays champion** (kill criterion #3). No promotion, no registry status change for
  `rs_tail` (stays `candidate` as a costless baseline arm).
- **The RS rule stays banked as a LABEL-level selection finding** (M2/M3: 3.5×/4.2× tail_mag lift,
  ML can't beat it) — it is the honest watchlist-ranking axis, but it does not replace the champion
  as a trading strategy under the current exit machinery.
- **M5 (deploy-gate re-confirm) is moot** — the champion is unchanged, and its SPY-200d deploy gate
  was already confirmed on BackTrader on the gated population (2026-07-09, Thread E/Q26).
- **Un-pursued levers (recorded, deliberately not swept post-hoc):** top-X threshold (0.95/0.98),
  tail-harvesting exits (drop the T1 cap so the ≥30% runs breathe — the SL/TP tension from the
  governor verdict §7a), RS × prob_elite combo rank. Sweeping any of these after seeing the cone is
  fitting the cone; each needs a fresh ex-ante hypothesis.
- Side deliverable: **the incumbent's post-gate-fix reference cone** — median Sharpe 0.47, floor
  −2.81, 33% negative cells, median ann +9.7% (2003–26, quarterly, BackTrader).

## Artifacts / reproduce

- `data/selection_sweep/starttime/{rs_tail,champion_gated}/rolling/` (per-cell trades/rejections/
  equity/metrics + `summary.json` + `report.md`).
- Reproduce: `.venv/Scripts/python.exe scripts/run_starttime_sweep.py --strategy rs_tail
  --grid rolling --cache-start 2003-01-01 --cache-end 2026-05-22 --step-months 3 --workers 3`
  (same for `champion_gated`; `--smoke` first; cells resume — delete a cell dir to force).
