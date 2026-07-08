# Session Handover: 2026-07-08 (session 04 — regime governor / point-8)

## 🎯 Goal
Run the queued point-8 experiment — regime-weight the existing per-day top-5 fwd-return panel (an EDA
reweight, NOT a backtest) — to decide whether the external regime governor is worth promoting to a
backtest; then follow the user's chart/quantification asks to a strategy conclusion.

## ✅ Accomplished
- **Point-8 (the governor's cheapest test):** reweighted the top-5 fwd100 panel by ENTRY-DATE regime.
  (a) SPY-200MA bear=0 → worst-decile +5.0pp but mean −1.0pp (a variance BRAKE). (b) stress_ew_vix
  bull-gated → improves BOTH (mean +0.8pp, worst-dec +6.0pp) but deploys only ~18% capital. **Verdict:
  promote to backtest, carry both weights.**
- **Start-date drift (user Q1):** cumulative top-1/5/10 fwd20 per representative period — steady up-slope
  in every bull/rebound, **−1.9/100d in the 2007-09 GFC** (regime-blindness as an equity curve);
  top-5≈top-10, top-1 noisier.
- **6-pillar backdrop (user Q2) + data-fact answers:** CAPE genuinely starts 2012-12 (CAPE_OURS);
  Liquidity "never <50%" was a TRANSFORM bug — expanding-pct saturates on a trending series (Liq
  corr+0.96 w/ time, CAPE +0.91). Fixed with a rolling 2yr percentile.
- **Non-cumulative + whole-period (user):** stripped the cumulative panel (no realistic meaning); raw
  daily top-5 return by horizon, regime-shaded — bear bands sit on the flat/declining stretches.
- **Can macro QUANTIFY high/low-return periods? (user):** YES, all one stress/VIX axis. fwd100
  top−bottom-tercile spread: VIX +11.5%, stress +10.5%, credit +9.6% (buy-the-stress); rates −8.9% &
  CAPE −8.3% (flipped); SPY>200d −5.1% (rebound lives sub-200d → tail gate, not return-level ranker).
- **INSIDE high-stress + 150d/200d (user) — THE conclusion:** enriched fwd150/200, built a 5-horizon
  top-5 panel. Within the top stress tercile, SPY>200d splits bull-stress vs bear-stress: ~EQUAL MEAN
  at every horizon but bear-stress worst-decile ~2.5× deeper (−56 vs −24% fwd100). **Governor = a GATE
  (SPY>200d, removes the knife at ~0 mean cost) × a TILT (stress/VIX, ranks the mean) — two jobs.**

## 📝 Files Changed
- `docs/session_logs/sprint_14/scripts/regime_weight_panel.py` (+`_chart.py`): point-8 reweight + fig.
- `docs/session_logs/sprint_14/scripts/start_date_drift.py` (+`_chart.py`, `_extra.py`): Q1/Q2 drift &
  pillar charts + the 3 follow-ups (non-cumulative, whole-period, rolling-pct fix).
- `docs/session_logs/sprint_14/scripts/return_vs_macro.py`: C6 return-by-horizon + C7 quantification.
- `docs/session_logs/sprint_14/scripts/build_top5_horizons.py`: enrich fwd150/200 + 5-horizon top-5 panel.
- `docs/session_logs/sprint_14/scripts/high_stress_conditional.py`: the inside-high-stress split + fig.
- `docs/session_logs/sprint_14/cells/regime_weight_panel_cells.md`: 25 cells, 5 parts (notebook-grade).
- `docs/session_logs/sprint_14/RESEARCH_LOG.md`: point-8 resolved + all follow-ups appended.
- `data/model_output_eda/regime_weight/`: panels, CSVs, 7 figures. `multiyear/raw_full_*_fwd.parquet`
  enriched IN PLACE with fwd150/200 (idempotent, verified).
- Memory: `project_entry_timing_macro_axis.md` — added the GATE×TILT separation + quantification.

## 🚧 Work in Progress (CRITICAL)
- Nothing half-finished. All scripts run clean end-to-end; all cells are notebook-grade with asserts.
- `data/model_output_eda/regime_weight/_topN_scratch.parquet` (3.5MB) is a cache the drift cells
  regenerate if absent — left in place, not committed to git-tracked docs (it's under data/).
- The user's IDE has `regime-weight.ipynb` open — they apply the cells; we do NOT edit .ipynb directly.

## ⏭️ Next Steps
1. **Promote the governor to a REAL backtest** — the falsifiable spec: size up on stress (stress_ew_vix
   quintile), GATE on SPY>200d, hold ~100-150d. Run through the M2 start-date cone (`run_strategy_wfo.py`),
   judge the Sharpe DISTRIBUTION across start-months, not one aggregate. This is the M2→M3 entry.
2. **Make the cuts live-safe first** — stress tercile + SPY gate are currently full-sample; needs an
   expanding-window version before it can size live capital.
3. Deferred (user): dashboard current-state badge + regime strip beneath the 6-pillar table.

## 💡 Context/Memory
- **The governor is TWO signals, TWO jobs — don't collapse them.** stress/VIX ranks the MEAN; SPY>200d
  is the TAIL GATE. Bear-stress's high fwd200 mean is a mirage of 2008/09 crash clusters (catch-the-
  bottom bets you can't rely on). Don't stack a 2nd vol-sizing factor — VIX ≈ the bear axis, double-counts.
- **Transform lesson:** expanding percentile is only valid for MEAN-REVERTING series; use a rolling
  window for TRENDING pillars (Liq, CAPE) or you just re-encode "later = higher".
- The `entry_timing_daily.parquet` panel IS the top-5 basket (corr 1.0) and carries fwd20/50/100 +
  all pillars + VIX + SPY — one table answered most of the asks with no new plumbing.
