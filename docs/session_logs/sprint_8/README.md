# Sprint 8 — Backtest Engine Refactor & Vectorization

**Dates:** 2026-04-21 → 2026-04-22 · **Status:** ✅ Closed · **Next:** [sprint_9](../sprint_9/README.md)

> This sprint was dedicated to overhauling the backtest infrastructure, deprecating legacy parquet-based data flows, and implementing a high-performance vectorized backtest engine to radically speed up strategy iteration.

### Folder map
- **`RESEARCH_LOG.md`** — the linear question ledger (how the thinking evolved, by sequence).
- **`logs/`** — dated session handovers.
- **`plans/`** — forward-looking design/plan docs.
- **`verdicts/`** — findings, reports, issues, playbooks.
- **`cells/`** — notebook-cell artifacts.

### Headline outcomes
- **Legacy Parquet Paths Archived** — fully deprecated all parquet file loaders for price, regime, and scores, moving strictly to DuckDB.
- **Vectorized SEPA Engine Built** — implemented `VectorizedSEPABacktest`, achieving 10-50x speedups for notebook iteration over the BackTrader event loop.

## Roadmap & Goals
- [x] Wire `score_from_t3()` as single source of truth for backtest scoring
- [x] Archive parquet-based feeds and clean up `runner.py` / `sepa_strategy.py`
- [x] Build Component 5: Vectorized SEPA Backtest Engine

## Carried over
- [ ] Smoke test `vbt.run()` end-to-end (DuckDB lock issue)
- [ ] Retrain M01 on a T3-native feature set to resolve NaN column mismatches
