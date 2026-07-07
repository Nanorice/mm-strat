# Sprint 2 — Models, Regimes & Visualization

**Dates:** 2026-01-20 → 2026-02-01 · **Status:** ✅ Closed · **Next:** [sprint_3](../sprint_3/README.md)

> This sprint was dedicated to sophisticated model development and visualization. We implemented the Triple Barrier Method (M02) to filter out losing trades, refined the M01 regression model ("Survivor Model") to predict upside potential, and built a comprehensive Market Regime (M03) system. Concurrently, the dashboard was transformed with industry-standard interactive visualizations.

### Folder map
- **`RESEARCH_LOG.md`** — the linear question ledger (how the thinking evolved, by sequence).
- **`logs/`** — dated session handovers.
- **`plans/`** — forward-looking design/plan docs.
- **`verdicts/`** — findings, reports, issues, playbooks.
- **`cells/`** — notebook-cell artifacts.

### Headline outcomes
- **Triple Barrier & M02 Developed** — Discovered predicting losers (M02) is highly effective, leading to the `M01_Adjusted * (1 - P(Loser))` production scoring formula.
- **M03 Market Regime System** — Built a macroeconomic "Traffic Light" gating system (Trend, Liquidity, Risk) to block longs in bear regimes.

## Roadmap & Goals
- [x] Refine M01 into a "Survivor Model" targeting Log-Space MFE
- [x] Implement M02 Triple Barrier Method
- [x] Build and calibrate the M03 Market Regime System
- [x] Overhaul analyst dashboard with interactive Plotly UI

## Carried over
- [ ] Migrate from file-based parquet to SQL-native DuckDB (Sprint 3 Focus)
- [ ] Validate M03 features in M01 out-of-sample tests

## Migrated Documents
- [m02_breakout_model.md](verdicts/m02_breakout_model.md)
- [m02_final_verdict.md](verdicts/m02_final_verdict.md)
- [macro_pillars_reference.md](verdicts/macro_pillars_reference.md)
