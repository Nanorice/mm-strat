# Session Handover: 2026-07-09 (regime governor → backtest → start-day lottery → Minervini overlay)

## 🎯 Goal
Promote the regime governor from EDA to a REAL backtest through the start-date cone (M2→M3), then —
under user challenge — stress-test what it actually does, culminating in reframing the strategy as a
start-day lottery and testing a Minervini-style entry overlay against it.

## ✅ Accomplished
- **Governor → 25y cone (M2→M3).** Built `MacroSizer.governor_weight` (live-safe: expanding-quintile
  stress tilt × SPY>200d gate, expanding-quantile thresholds, 1-day lag), wired `--sizing governor` +
  a per-fold cone metric into `run_strategy_wfo.py`, cached m01_binary scores to parquet
  (`cache_model_scores.py`, chunked to fix a 12.6 GiB OOM). **Verdict: a start-date-robust DRAWDOWN
  CONTROLLER** (worst fold DD −46%→−19%, median −29%→−14%) but NOT alpha — flat wins median Sharpe
  (0.76 vs 0.51); the GATE cancels the TILT (only ~4% of stress days are SPY>200d). VIX dominated.
- **Governor vs the 15% stop-loss (user Q).** Traced both layers: stop = per-position/intraday;
  governor = per-day/book-wide. Proven in 2008 (stop fired 64-76× at −15%, book still −56%; governor
  gated 58-93% → −12%). Governor controls **regime bleed, NOT gap-down**.
- **Gap-down loss UNDERSTATED (quantified).** `_simulate_exits` books stop-outs at `stop_level` even
  on gap-downs; 7% of stops gap through, real loss −19.7% (worst −39.8%) vs booked −15%; aggregate
  drag only −0.33%. Fix = `min(stop_level, open)`. Logged, not applied.
- **Equity mechanics (user Qs) — 4 extensions.** No capital ledger (return-compounding); governor
  re-entry mismodelled (inherits stale frozen-window positions, not fresh); gate misses the +38%
  sub-200d rebound (re-deploys at 200d reclaim not the trough); **gross exposure is an artifact of
  breakout supply (28%→66% drift), not a sizing decision** — "unlimited capital → always up" is FALSE
  (mostly under-deployed, 43% mean).
- **Start-day LOTTERY reframe (user idea).** `start_day_basket_paths.py`: each start-day = one
  governor-gated top-5 basket, SL/horizon, equal-weight fwd return. Plot A (lottery: 41% of start-days
  lose, hard −15% floor cluster, max +202%) + Plot B (equity fan aligned at origin, variable length =
  the "when do we stop" variable). **Governor on the lottery: trims the UPSIDE not the downside**
  (p05/p10 identical, max +823%→+202%).
- **Minervini overlay BUILT + tested (user's next-step + challenge).** Confirmed VCP is already in the
  model (don't re-weight); pivot-trigger is already in t3 (`breakout_momentum`, `vol_ratio`).
  `basket_paths_minervini` (trigger + progressive add-on + tight stop). **Honest NULL in this lens** —
  worse median/losing% than naive, but win/loss payoff ratio DOUBLES (2.85→6.18). The asymmetry is
  real; the fwd-return lens can't harvest it (no trailing-stop-to-breakeven, no intraday adds).
- **Corrected my own earlier claim** that tight stops "hurt" — they double the payoff ratio (Minervini
  edge); they only look bad on a fixed-hold basket that can't concentrate into winners.

## 📝 Files Changed
- `src/backtest/macro_sizer.py`: +`governor_weight` mode + `_stress_ew_vix` + `__main__` self-check.
- `scripts/run_strategy_wfo.py`: `--sizing`, `--scores-parquet`, per-fold cone metric.
- `scripts/cache_model_scores.py`: NEW — chunked score cache (fixes OOM).
- `docs/session_logs/sprint_14/scripts/start_day_basket_paths.py`: NEW — lottery + Minervini engines.
- `cells/`: `regime_governor_backtest_cells.md`, `governor_vs_stoploss_cells.md` (Ext A-D),
  `start_day_lottery_cells.md`, `minervini_overlay_cells.md` — all ROOT-anchored, asserts pass, hook green.
- `verdicts/2026-07-09_regime_governor_backtest.md`: NEW.
- `RESEARCH_LOG.md`: point-8 promotion + all follow-ups appended.
- Memory: `project_entry_timing_macro_axis` (governor reassessed), `project_backtest_stop_gap_fill`
  (NEW), `feedback_no_direct_notebook_edits` (ROOT-anchor HARD RULE), MEMORY.md.
- `data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22.parquet` + several figures under
  `data/model_output_eda/regime_weight/`.

## 🚧 Work in Progress (CRITICAL)
- Nothing half-finished. All scripts run clean; all cells notebook-grade with passing asserts + hook.
- Two fixes LOGGED but deliberately NOT applied (await user go-ahead): (1) gap-fill `min(stop_level,
  open)`; (2) the Minervini trailing-stop + progressive-fills port to the engine = **task (a)**.

## ⏭️ Next Steps
1. **Task (a) — port the Minervini trailing-stop-to-breakeven into `vectorized_backtest.py`** (the
   single highest-leverage piece; a contained exit-logic change). Then re-test whether it converts the
   doubled payoff ratio (6.18) into a real edge that tightens the start-day distribution WITHOUT
   kneecapping the tail. Progressive intraday adds = a bigger engine change, defer.
2. Optionally the gap-fill fix alongside (both touch `_simulate_exits`).
3. The governor is banked as a DD-control overlay (`--sizing governor`), un-tuned — not the arena
   champion.

## 💡 Context/Memory
- **The whole session's arc: the strategy is a start-day LOTTERY, and neither the governor nor TP
  fixes it** — the governor trims the wrong tail, TP shrinks everything. The lottery is STRUCTURAL
  (fixed day-0 basket + fixed hold). The fix is Minervini's conditional/progressive process.
- **VCP is in the model; the pivot-trigger is largely a double-count** — filtering top-5 again by the
  trigger just subsets to the most-extended, most-whipsaw-prone names. The non-redundant Minervini
  edge is the EXIT mechanic (trailing stop to breakeven), not the entry filter.
- **The forward-return basket lens is capital-artifact-free but exit-naive** — it can't model trailing
  stops or intraday adds, so it's the right tool to DIAGNOSE the lottery but the wrong tool to HARVEST
  the Minervini asymmetry. That's why task (a) is in the engine.
- **Cone vs single-basket reconciliation:** the governor's −46%→−19% DD win is a COMPOUNDING effect
  (up to 51 consecutive gated bear start-days), invisible to a single independent basket (max loss 15%).
