# Sprint 13 — Research Agenda

> Infra (Prefect nightly, dashboard, DuckDB memory governance) is operational — see
> [2026-06-22_prefect.md](2026-06-22_prefect.md). Sprint 13's research half asks one
> core question: **is the M01 score real alpha, or a structural artifact (industry mix,
> regime, survivorship)?**

## Goals

### A — Score attribution & validity
1. **Industry/sector score bias** — Healthcare tends to score high. Real edge, or a
   class-prior artifact now that `industry`/`sector` are model *inputs*? Compare score
   distribution vs realized forward return *within* each industry.
2. **Period analysis on recent breakouts** — avg score, industry mix, realized return by
   industry. Empirical ground-truth check for (1).
3. **m01_prototype vs m01_binary vs m02_prototype** — m01 looks like it solves a harder
   problem yet scores better. Illusion? Run a single bake-off: same OOS window, metric,
   universe. (Suspicion warranted — `notebooks/memo.md` already flags m01_baseline as a
   dead-end: longer window + leakage didn't lift backtest.)

### B — SEPA staging / entry timing
- Classify Minervini Stage 1–4 so we enter Stage 1/2, not late Stage 3. Build a
  rule-based Stage Classifier first (`price_vs_sma_200`, `sma_ratio_150_200`,
  `dist_from_52w_low`). Defer Elliott-wave counting unless rules prove insufficient.

### C — Regime / bearish-event notebook  ← **ACTIVE**
- QQQ/SPX daily-return distribution → define a bearish-event cutoff → mark those dates →
  inspect neighbouring segments → breakout pattern by industry + watchlist forward
  returns around those events. Connects to M03 regime. (Overlaps A2.)

### D — Feature correctness & housekeeping
- `_pct_change` vs `_delta` features are likely duplicates — confirm and drop
  `_pct_change`. (Fix before trusting any model comparison in A.)
- Guard against the feature-shift SQL bug (an edit landed in the wrong place in SQL and
  shifted all features).
- Document cleanup — batch at sprint end.
