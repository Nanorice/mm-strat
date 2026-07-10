# Session Handover: 2026-07-10 (04 — R-series funnel program close)

## 🎯 Goal
Review the Minervini/SEPA funnel research to date (R1/R1b), consolidate the ground truth, then run the
remaining open threads (R3 exit-coupling, R2 leadership passport, R3b trail variant) to a verdict —
deciding whether a new selection model (or de-gating m01) is worth building.

## ✅ Accomplished
- **Reviewed** R1/R1b/R1b-axis2 verdicts; surfaced the load-bearing distinction the program was
  conflating: **"null" is three currencies** — C1 label-ranking / C2 OOS-ranking / C3 exit-aware P&L.
  m01a-null (C2+C3) ≠ m01-null (m01 won C3). Wrote the steering doc + memory for it.
- **R3 (exit × selection coupling)** — 2×2 cone (4 arms × 90 quarterly cells): the tail-harvesting
  (trend-exit-only) exit helps the **champion's** selection (+0.21 median Sharpe, era-robust) but
  **nothing for RS-tail** (C≈B). RS-tail un-monetizable under BOTH exits. `champion_trail` = candidate
  exit refinement. **m01 de-gate NOT triggered** (would inherit RS-tail's null).
- **R2 (leadership passport)** — NO trait clears the ≥1.3× RS-D10 stacking gate → step 3 collapses
  into RS. Group-leadership = RS-clones (ρ 0.57–0.80); base-character flat-to-inverted; only residual
  = an upside-only vol tilt (adr_20d/natr 1.28×, below gate). Passport ships as a manual-review aid.
- **R3b (rising-trail-from-entry)** — R3's last un-pursued lever. FALSIFIED: the from-entry stop
  ratchet **eliminates the trend exit** (38%→2%→1%), clipping the winners that made champion_trail
  work. Monotone worse tighter (e25 0.32, e15 −0.29 vs champion_trail 0.46). champion_trail is a local
  optimum in the trail family.
- **SEPA funnel program CLOSED** — R1/R1b/R2/R3/R3b/R4 all resolved. Only open action = deploy-gate
  re-confirm for champion_trail.
- Shipped `trail_from_entry_atr` (position_tracker) + arms + unit test; deleted 4 scratch scripts.

## 📝 Files Changed
- `src/backtest/position_tracker.py`: `trail_from_entry_atr` param in `update_stops` — rising trail
  from first bar (off by default 0.0; high-water logic keeps it ≥ initial stop).
- `src/backtest/sepa_strategy.py`: `disable_tranches` (R3 tail-exit) + `trail_from_entry_atr` (R3b)
  params, wired through `_check_targets` / `_update_all_stops`.
- `src/backtest/strategy_registry.py`: arms `rs_tail_trail`, `champion_trail` (R3), `champion_trail_e25`,
  `champion_trail_e15` (R3b); `_trail_only` helper; `Xtr`/no-`Xt` fingerprint fixes; extended self-check.
- `tests/test_trail_from_entry.py`: 3 asserts on the trail branch (off-default / ratchet-up / never-below-initial).
- `scripts/r2_leadership_profile.py`: R2 M0 (univariate) + M1 (RS-stacking gate) analysis.
- Verdicts: `2026-07-10_r3_exit_selection_coupling.md`, `_r2_leadership_profile.md`, `_r3b_rising_trail_from_entry.md`.
- Plans: `sepa_ground_truth_roadmap.md` (new steering doc), `sepa_funnel_meta_plan.md` (R2/R3 boxes checked).

## 🚧 Work in Progress (CRITICAL)
- **Nothing half-finished.** All threads have a verdict. Registry self-check + 7 tests green.
- **`champion_trail` is NOT promoted** — it's a `candidate` in the registry (+0.21 sits inside
  start-date noise). It needs its SPY-200d deploy-gate re-confirm before any status change. Do NOT
  promote off the R3 cone alone (the M3/M4 post-hoc-fitting failure mode).
- `champion_trail_e15`'s `summary.json` may not have been written by the sweep (I rebuilt its cone
  from cell equity.parquet dirs); its per-cell artifacts are all present and correct.

## ⏭️ Next Steps
1. **Deploy-gate re-confirm for `champion_trail`** (SPY-200d trunk, per project_capital_deployment) —
   the ONLY open action. Then promote to champion or park as confirmed-but-marginal.
2. **Sprint wrap-up** — every thread has a verdict; this is a clean point to run `sprint-wrap-up`.
3. (Optional, needs its own ex-ante plan) A one-tranche hybrid exit — NOT recommended; R3b showed the
   median bleed and the tail are the same coin.

## 💡 Context/Memory
- **The three-currencies frame is the durable lesson.** Three times now the program caught "the
  label/median lever destroys the tradeable edge" — m01a tail ranker, R3 exit truncation, R3b whipsaw.
  In this trade structure the 63d MFE tail is fragile: every attempt to systematize its capture either
  clips it or drowns it in variance. The tail is watchlist-ordering value, not systematic alpha.
- **champion_trail's edge IS the trend-hold.** Its 38% trend-exits are the tail-rides; R3b proved you
  can't protect the median bleed without amputating them — they're one coin.
- **Smoke-as-no-op-guard earned its keep twice**: caught the R3 tranche-zeroing no-op (target1 fires
  at entry price, not disabled) and flagged R3b's whipsaw profile before the cone.
