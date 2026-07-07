# Session Handover: 2026-07-07 (session 04 — entry-timing macro axis / regime lens)

## 🎯 Goal
Start task (b) as the SPY-200d deploy-gate cone test, then — on user pivot ("too early to invest in
the gate") — turn it into an EXPLORATORY correlation study: across 25 years, what macro feature marks
the BEST (and worst) dates to deploy the top-5? Which macro *model* reveals regime for this strategy?

## ✅ Accomplished
- **Built the SPY-200d deploy gate (parked, not pursued).** Wired a `spy_deploy_gate` param into
  `sepa_strategy` (blocks new entries when SPY<200d, mirrors the regime-0 gate), registered
  `champion_spygate`, added `--compare-spygate` to the start-time sweep (Sharpe-DISTRIBUTION diff, not
  mean). Smoke-tested on 2022 bear: gate cut trades 78→11, loss −25.6%→−17.0%. **User pivoted before
  the full cone run** — gate left as working, unused infrastructure. Fixed a real bug along the way
  (`population_runner` config.json couldn't serialize the date-keyed gate dict → `_config_safe`).
- **Entry-timing EDA (the real deliverable).** New toolkit `entry_timing_features.py`: collapses the
  25y cache to per-day top-5, scores across a HORIZON GRID (fwd 20/50/100 — SEPA holds longer),
  attaches features, correlates. Panel cached at `data/model_output_eda/entry_timing/`.
- **Finding 1 — M03 does NOT flag entry timing** (25y, every feature ρ∈[−0.09,+0.02]). Trend-state ≠
  timing signal.
- **Finding 2/3 — the dashboard 6-PILLAR macro (≠ M03) DOES** — a value/stress axis (rates −0.12,
  wide credit +0.09, CAPE −0.11, VIX +0.08). Disambiguated the two macro models carefully
  (`load_macro_pillars` on `macro_data`, NOT `t2_regime_scores`). Weak@20d entries heal
  −20.7%→−8.1% by fwd100 (second chance, partial).
- **Finding 4/5 — composite + made it live-safe.** A stress composite BEATS every single pillar
  (full-sample fwd100 +0.167). Then rebuilt with EXPANDING-WINDOW z (no look-ahead) + 5 variants +
  a tilt test: **the look-ahead flattered it ~2×**. Honest = `stress_ew_vix` fwd100 ρ **+0.084**, a
  **BULL-ONLY** tilt (bear flips to −0.150 — falling knife), TOP-QUINTILE kicker (Q5 +18.5% vs Q1–4
  ~+10%), stress-weighted deploy **+1.8% fwd100 uplift**. Overturned Finding 4b's "regime-robust".

## 📝 Files Changed
- `docs/session_logs/sprint_14/scripts/entry_timing_features.py`: **new** — the EDA toolkit (top-5
  horizon-grid outcome × M03/macro/6-pillar features; stress composite variants; regime split; tilt).
- `src/backtest/sepa_strategy.py`: `spy_deploy_gate` param + 2-line gate in `_process_entries`.
- `src/backtest/strategy_registry.py`: registered `champion_spygate` (gate injected per-window).
- `src/backtest/macro_sizer.py`: `spy_above_200d(start,end)` loader (lifted from capital_deployment).
- `scripts/run_starttime_sweep.py`: inject gate for `champion_spygate` + `--compare-spygate` cone-diff.
- `src/backtest/population_runner.py`: `_config_safe()` — serialize the date-keyed gate dict summary.
- `docs/session_logs/sprint_14/verdicts/2026-07-07_entry_timing_features.md`: **new** — Findings 1–5.
- `docs/session_logs/sprint_14/RESEARCH_LOG.md`: **new Thread F** (Q16–20).
- Memory: new `project_entry_timing_macro_axis`; MEMORY.md index.

## 🚧 Work in Progress (CRITICAL)
- **Nothing half-finished.** The finding is landed and documented. The SPY-200d gate is working code
  but UNUSED — parked deliberately (user: too early to invest). The `--compare-spygate` full cone run
  was never executed (only smoke).
- **The composite is EDA-only until wired.** `stress_ew_vix` is live-safe (expanding-z), but it's not
  connected to any deploy/sizing path. `stress_full` in the panel is LOOK-AHEAD — never use it live.

## ⏭️ Next Steps
1. **Decide the composite's fate.** It's a low-priority exposure input (+1.8% fwd100, bull-gated). If
   pursued: wire `stress_ew_vix` gated by SPY>200d as a threshold ("boost when stress top-quintile &
   SPY>200d") into the macro-sizer-style exposure path — NOT a model feature, off the score.
2. **Judge the strategy on fwd100, not fwd20.** Both the timing signal AND the second-chance recovery
   live at the long horizon; the basket/exit grid was tuned on shorter outcomes. Re-check.
3. **Return to the deferred M-questions** (unchanged by this session): M3 (stability-first selection
   on the tail-lift objective, bad-regime floor), M4 (magnitude regressor design, regime-conditioned,
   id ≠ M03). The SPY-200d cone test (b) is still available if the gate is revived.
4. Ops carryover (from S13): clean_dirty_shares on sh019; t1_macro June gaps.

## 💡 Context/Memory
- **The two macro models are distinct and it matters.** M03 (`t2_regime_scores`, 3 pillars
  trend/liq/risk) = trend-STATE, no-op for entry timing. The dashboard 6-pillar
  (`load_macro_pillars`/`macro_data`, VIX/Credit/Term/Rates/Liq/CAPE) = value/stress, IS the useful
  lens. Always confirm which one the user means.
- **The look-ahead lesson, sharply.** Full-sample z-scores/percentiles inflated the composite ~2×
  AND faked all-weather regime-robustness (bear column went from +0.190 look-ahead to −0.150 live).
  The dashboard's pillar percentiles carry the same look-ahead ("do NOT feed to backtest") — correlate
  on RAW levels, normalize with expanding windows. Any macro-timing claim MUST be re-checked live-safe.
- **Everything here is fwd-return, no exits/sizing/liquidity** — directional, not tradable P&L.
- **The signal is a TILT, not a gate** (live |ρ|≈0.08). Deploy-more-when-extreme-and-bull, marginal.
