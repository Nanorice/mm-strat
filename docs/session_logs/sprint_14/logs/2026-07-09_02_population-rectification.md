# Session Handover: 2026-07-09 (population rectification → Minervini port → BackTrader confirm FAILS)

## 🎯 Goal
Rectify the conclusion chain after the SEPA-gate population fix: the fix invalidated not just the
governor verdict but the whole Sprint 13 Strategy Arena (top-5 was selected from the ~99% off-setup
panel). Sequence: build a Minervini exit+entry, re-run the arena on the gated population, re-derive the
honest champion — and confirm it on the fidelity engine before promoting anything.

## ✅ Accomplished
- **Assessed + reordered the user's plan** (challenged "include minervini in the arena" as actually the
  engine port; pulled the deploy-gate to parallel). Wrote it as a sub-plan of record.
- **M1 — built `exit_policy='minervini'`** (breakeven-ratchet trailing stop) + **progressive fills**
  (starter position, add on +trigger cross; press winners / starve losers) in `vectorized_backtest.py`.
  Two self-checks. Progressive fills is the load-bearing piece (single-window Sharpe 0.35→1.19).
- **M2 — vec head-to-head cone** on the gated population: minervini+prog-fills BEAT sma (median 1.44 vs
  1.00, %neg 5% vs 25%, prog-fills chosen 20/21 folds). Wrote the M2 verdict.
- **M2b — ported prog-fills into `SEPAHybridV1`** (pre-tranche scale-in; `PositionTracker.confirm_add`
  blends cost basis; tranche keys off final size; default off = byte-identical) + BackTrader-confirmed it.
- **M2b result = NEGATIVE (the honest kind):** the vec cone does NOT survive BackTrader. Fixed-config
  apples-to-apples proved the gap is the ENGINE not tuning (vec median 1.51/%neg 10% vs BT 0.35/%neg 45%,
  concentrated in bear folds). **Champion stays the existing native tranche exit. Minervini NOT promoted.**
- **Caught + fixed a gate-drop bug** that would poison ANY gated BackTrader run.
- Saved 2 memories; annotated the superseded Sprint 13 + M2 verdicts.

## 📝 Files Changed
- `src/backtest/vectorized_backtest.py`: `exit_policy='minervini'` (breakeven ratchet) +
  `progressive_fills`/`starter_frac`/`add_trigger_pct`; 2 `__main__` self-checks.
- `src/backtest/sepa_strategy.py`: progressive-fill scale-in (`_check_adds`, starter split in
  `_enter_position`, add-routing in `notify_order`); 3 new params, default off.
- `src/backtest/position_tracker.py`: add-target fields on `SEPAPosition`; `confirm_add` (grow +
  blend cost basis); starter-size `remaining_shares` in `confirm_entry`.
- `src/backtest/score_lookup.py`: **BUG FIX** — `prototype_scores_to_contract` now carries
  trend_ok/breakout_ok through (was silently dropping them → population re-inflation).
- `scripts/run_strategy_optimizer.py`: `minervini` arm + prog-fills knobs in `suggest_params`;
  `LOCK_EXIT_POLICY` env var for head-to-head cones.
- `scripts/run_strategy_confirm.py`: **BUG FIX** (`_load_scores` drops flags) + `binary_gated` cache +
  `_m2b_arms()`.
- `tests/test_progressive_fills.py`: NEW — scale-in state math (starter, blend, tranche-on-final, starve).

## 🚧 Work in Progress (CRITICAL)
- Nothing half-finished. All 19 guards pass; scratch cleaned. The minervini/prog-fills code is complete
  and default-off (byte-identical to before), kept as an available lever with NO live slot.
- **The conclusion is settled: do NOT promote minervini.** The champion is the existing `SEPAHybridV1`
  native 3-tranche/trailing exit, on the gated population.

## ⏭️ Next Steps
1. **M4 (still open)** — re-confirm the deploy gate (SPY 50/100/200 EMA/SMA trunk + 6-pillar stress
   as calm/stress) on the GATED population + on BackTrader (not vec). Independent of the champion choice.
2. **Optional M3** — the honest start-date fragility is already the M2b BT cone (%neg 45%); if a finer
   rolling-monthly start grid is wanted, run it on BackTrader, never vec absolute numbers.
3. Consider fixing the vec stop-at-level gap understatement ([[project_backtest_stop_gap_fill]]) so the
   vec cone is less optimistic — but the durable rule is just "promote on BackTrader".

## 💡 Context/Memory
- **The meta-lesson (saved to memory):** the vectorized engine is ~3× optimistic in ABSOLUTE Sharpe vs
  BackTrader — usable for within-engine ranking only. This retro-flags every vec cone in this thread
  (M2, the governor §2/§6/§7). Every promote decision runs on BackTrader.
- **Progressive fills is real mechanically but not an edge here** — it works exactly as designed (starve
  losers / press winners, confirmed by state-math tests and the vec cone), but the incumbent native
  tranche exit is ALREADY a Minervini discipline, so on the honest engine it's a wash.
- The population fix STILL stands — Sprint 13's champion was genuinely inflated; what changed is the
  replacement doesn't win once measured honestly.
