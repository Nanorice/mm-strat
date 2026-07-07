# Sprint 9 — T3 Universe Refactor & Realistic Backtesting

**Dates:** 2026-04-27 → 2026-05-09 · **Status:** ✅ Closed · **Next:** [sprint_10](../sprint_10/README.md)

> This sprint fundamentally redesigned the T3 universe logic (Option C), moving from a static screener-active list to an event-driven SEPA sessions log (`sepa_watchlist`). We also evolved the backtest framework to include a sequential mode, revealing that highly optimistic vectorized results were unrealistic under portfolio constraints.

### Folder map
- **`RESEARCH_LOG.md`** — the linear question ledger (how the thinking evolved, by sequence).
- **`logs/`** — dated session handovers.
- **`plans/`** — forward-looking design/plan docs.
- **`verdicts/`** — findings, reports, issues, playbooks.
- **`cells/`** — notebook-cell artifacts.

### Headline outcomes
- **SEPA Watchlist Implemented** — Built the new event-log manager (`Phase 4b`) that tracks SEPA session lifecycles (ACTIVE, COOLDOWN, EXITED) and restricts T3 growth.
- **Sequential Backtester Built** — Created a realistic sequential backtest loop to enforce `max_positions` and cooldown constraints, proving that vectorized parameter sweeps can be dangerously optimistic.

## Roadmap & Goals
- [x] Refactor T3 Universe to use Option C (SEPA session event log)
- [x] Backfill `sepa_watchlist` and `t3_sepa_features`
- [x] Evaluate backtest findings in sequential vs vectorized modes

## Carried over
- [ ] Retrain M01 on the new T3 dataset
- [ ] Test the sequential backtest with a 5-factor risk gate
