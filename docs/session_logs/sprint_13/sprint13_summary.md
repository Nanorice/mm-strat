# Sprint 13 — Research Agenda

> Infra (Prefect nightly, dashboard, DuckDB memory governance) is operational — see
> [2026-06-22_prefect.md](2026-06-22_prefect.md). Sprint 13's research half asks one
> core question: **is the M01 score real alpha, or a structural artifact (industry mix,
> regime, survivorship)?**

## Consolidated Sprint Roadmap & Goals

### 1. Modeling (M01 & M02)
- **Finalise M02 (the ongoing scoring model).** ✅ **DONE.**
  - Shifted M02 to predict structural breakouts directly via a continuous `breakout_proximity` score.
  - Model achieved **50% Precision@50** out-of-sample (~3.6x edge over random). See [m02_final_verdict.md](../../research/m02_final_verdict.md).
- **Strip M03 from all models.** ✅ **DONE.**
  - Created `fs_m01_no_macro` feature set. Retrained `m01_no_macro` and `m01_binary_no_macro`.
  - Conclusion: Macro context is essential for binary "Home Run" predictions, but redundant for standard 4-class multi-class predictions. See [M01 No Macro Model Card](../../models/m01_no_macro/v1/model_card.html).

### 2. Strategy Evaluation & Backtesting
- **Backtester — exploratory & finalisation.** ✅ **DONE.** 
  - Fixed bugs, converged prod/backtest scoring. Evaluated `vnpy` and decided against adopting it.
- **Goal B: SEPA Staging / Entry Timing.**
  - Classify Minervini Stage 1–4 using a rule-based Stage Classifier (`price_vs_sma_200`, `sma_ratio_150_200`, etc.) to enter Stage 1/2 and avoid late Stage 3. See [goal_b_stage_classifier_plan.md](goal_b_stage_classifier_plan.md).
- **Parameter Optimizer.** ✅ **BUILT** (2026-07-02). Optuna over the vectorized engine.
  - `scripts/run_strategy_optimizer.py` — single IS/OOS split, maximize Sharpe.
  - `scripts/run_strategy_wfo.py` — rolling/anchored walk-forward variant (the overfit gate).
  - See [2026-07-02_backtest_arena_session.md](2026-07-02_backtest_arena_session.md) for full results.
- **Evaluate the model and strategy.** ✅ **Model Arena built + first results** (2026-07-02).
  - `scripts/run_model_arena.py` — all scoreable variants on shared strategy infra, ranked by honest mark-to-market Sharpe. m01_binary ≈ m01_prototype at top; m01_no_macro (4-class) worst.

### 3. Research: Score Validity & Macro Regime
- **Goal A: Score Attribution & Validity.** 
  - Investigate Industry/sector score bias (Healthcare). Run period analysis on recent breakouts to check empirical ground-truth. Compare m01_prototype vs m01_binary vs m02_prototype in a single bake-off.
- **Goal C: Regime / Bearish-Event Notebook.** ← **ACTIVE**
  - QQQ/SPX daily-return distribution → define a bearish-event cutoff → mark dates → inspect neighbouring segments → breakout pattern by industry + watchlist forward returns.
- **High-Beta Feature of SEPA Candidates.** 
  - Top tickers currently have decent returns while SPY is up 1-2%, contrasting with past high-uncertainty performance. Check average return in 10-day lookback rolling for top tickers (score > 0.6) and correlation with index return.
- **Macro Evaluation.** Can we use this to confirm a trend? (Not leading).

### 4. Infrastructure & Housekeeping
- **Macro Dashboard.** Have a new macro dashboard for the weather/climate gauge (see [macro_dashboard_implementation_plan.md](macro_dashboard_implementation_plan.md)).
- **ITX.** Work on ITX to smooth automatic runs of the daily job.
- **Goal D: Feature Correctness & Housekeeping.** ✅ **DONE.**
  - `_pct_change` vs `_delta` features are likely duplicates — confirm and drop `_pct_change`.
  - Guard against the feature-shift SQL bug (used DuckDB's `INSERT ... BY NAME`).
  - Document cleanup — batch at sprint end.

## Sprint TODOs

- **CAPE pillar — replace Yale XLS with a FRED-derived proxy.** The macro dashboard's
  6th pillar (Valuation/CAPE) is now sourced from Yale's `ie_data.xls` into `macro_data`
  (engine path, DQ-checked). But that file's CAPE column trails badly — currently frozen
  at **2023-09** (~1000d stale), so the gauge renders on an old value and the DQ audit
  flags it WARN by design. Accepted as-is for now (5/6 pillars are fresh). Follow-up:
  build a daily FRED-derived CAPE proxy, and before swapping it in, quantify:
  (a) the gap between the proxy and true Shiller CAPE, (b) *why* the Yale file is stale
  (publication cadence vs. our fetch), and (c) how reliable the proxy is as a stand-in.
  Isolated to the dashboard valuation pillar — no downstream model/backtest impact.

- **Macro-driven position sizing in backtest — the "no double-count" experiment.**
  M03 macro was stripped from the *models* (`fs_m01_no_macro`) precisely so macro isn't
  baked into the score. The open question: reintroduce macro *only* at the **sizing /
  position-cap layer** of the backtest (bake in the new clean `macro_data` flow to scale
  exposure by regime), NOT as a model feature. Goal is to prove that — **without macro
  double-counting through the regime** — what the performance is when macro governs *how
  much* we hold rather than *what* we score. Baseline to beat: the flat-sizing bake-off
  (m01_binary Sharpe 0.60, see backtest_architecture bake-off). Compare regime-scaled
  sizing vs. flat on the same trades. Blocked on the vectorized equity-curve fix landing
  first (need trustworthy Sharpe before sizing changes are attributable).
