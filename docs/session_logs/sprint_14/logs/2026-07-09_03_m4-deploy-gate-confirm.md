# Session Handover: 2026-07-09 (M4 — deploy-gate BackTrader confirm)

## 🎯 Goal
Close the last open milestone of the population-rectification plan (M4): re-confirm the SPY-200d deploy
gate on the GATED population and — critically — on **BackTrader**, not the engine-optimistic vec cone the
governor verdict used. Independent of the (settled) champion-exit choice.

## ✅ Accomplished
- **Scoped M4 with the user** to the one genuinely new thing: the governor's DD-control conclusion was
  already banked but on VEC (which we quantified last session as ~3× optimistic, understating exactly the
  bear damage a DD-controller should fix). So M4 = run the SPY-200d gate through the FIDELITY engine.
- **Wired the gate into the WFO-gate path** (it existed for vec + `run_starttime_sweep`, not for
  `run_strategy_confirm --wfo-gate`): added a `spy_gated` flag on `Arm`, two arms
  `M4_gated_{baseline,spygate}`, and per-fold `spy_above_200d()` injection in `wfo_gate`. Reused the
  existing `spy_deploy_gate` param in `SEPAHybridV1` + `macro_sizer.spy_above_200d`.
- **Ran the 25y gated cone** (rolling 2y/1y, 21 folds, matches M2b): **the gate improves EVERY metric** —
  agg Sharpe 0.52→0.79, return 299%→794%, maxDD −61%→−37%, %neg folds 45%→35%, cone median 0.53→0.68.
- **Diagnosed the mechanism:** win = 3 deep-bear rescues (2008 −1.86→+2.50 with gate open only 2% of days,
  2022 −1.69→−0.33, 2009) DWARF 4 mid-cycle whipsaws (2007 shallow-dip, 2018 sub-200d rebound-miss,
  2010/2014). Verified via the gate open-fraction per fold.
- **Explained why BackTrader disagrees with the vec governor verdict** ("DD-only, costs the mean"): a
  drawdown-avoidance overlay can only be valued on an engine that models the drawdown; vec understated the
  bear damage, so the gate looked like pure cost there.
- **Consistency check PASSED** — `M4_gated_baseline` reproduces the M2b BackTrader baseline to the decimal
  (0.52 / median 0.53 / 45% neg) → gate wiring didn't perturb the baseline.
- Wrote the verdict; updated plan (M4 done), RESEARCH_LOG (Q26 + M4 closed), 2 memories.

## 📝 Files Changed
- `scripts/run_strategy_confirm.py`: `spy_gated` flag on `Arm`; `_m4_arms()` (`M4_gated_baseline` /
  `M4_gated_spygate`); per-fold `spy_above_200d()` injection in `wfo_gate`; cone-summary print
  (median/min/%neg/DD). All additive — 10 backtest guards pass.
- `docs/session_logs/sprint_14/verdicts/2026-07-09_m4_deploy_gate_backtrader_confirm.md`: NEW — full write-up.
- `plans/population_rectification_plan.md`: M4 marked ✅ DONE.
- `RESEARCH_LOG.md`: Thread G Q26 + M4 open-question closed.
- Memories `project_entry_timing_macro_axis` + `project_capital_deployment`: revised the "governor =
  DD-controller only" claim (was vec-specific); added the M4 BackTrader confirm.
- Artifacts: `data/selection_sweep/wfo_gate/M4_gated_{baseline,spygate}.json` (per-fold cones).

## 🚧 Work in Progress (CRITICAL)
- Nothing half-finished. All guards pass. The gate confirm is complete and the verdict is written.
- **NOT auto-promoted:** `champion_spygate` (registry, `status="candidate"`) is now the evidence-backed
  promotion candidate for the live champion's **deployment layer** — but that's a user decision, flagged
  and left for confirmation, not applied.

## ⏭️ Next Steps
1. **User decision:** promote `champion_spygate` to the live deployment layer? It's a portfolio-exposure
   choice, orthogonal to the (settled) native-tranche exit. The M4 verdict is the evidence.
2. **The population-rectification plan is now fully closed** (M1/M2 done, M2b failed-honestly, M3 absorbed,
   M4 done). Natural next move = `sprint-wrap-up` for sprint 14, OR pick up a carried meta-question (M5
   persistent continuous-score top-N; the "release near the bottom" recovery-trigger v2 that would recover
   the 2018 rebound-miss).
3. **Optional realism ticket (still open):** the vec stop-at-level gap-fill understatement
   ([[project_backtest_stop_gap_fill]]) — `min(stop_level, open)` fix, not yet applied.

## 💡 Context/Memory
- **The meta-lesson lands twice now:** last session the vec engine's optimism KILLED a candidate
  (minervini washed on BackTrader); this session the same optimism had HIDDEN a real win (the gate looked
  like cost on vec). Same fidelity gap, opposite direction — the durable rule "promote/judge on BackTrader"
  cuts both ways.
- **The gate is a GATE, not a re-entry model** — it re-deploys at the 200d *reclaim*, not the trough. 2018
  quantifies the missed sub-200d rebound cost. A recovery-momentum re-deploy ("release near the bottom" v2,
  governor verdict Ext-B) is the clean extension.
- The stress-TILT stays inert once gated (gate × tilt cancel, unchanged from the governor verdict) — the
  confirmed win is the binary SPY-200d gate alone.
