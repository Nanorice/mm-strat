# Sprint 8 — Research Log

This is the linear train-of-thought for the sprint, tracking questions and their resolution.

## Thread A: Backtest Data Flow
1. **How do we remove the brittle parquet dependencies?** → Archived all parquet-based feeds, replacing them entirely with `score_from_t3()` queries from DuckDB. This enforced a single source of truth. [2026-04-21_02_session2.md](logs/2026-04-21_02_session2.md)

## Thread B: Backtest Performance Optimization
1. **Can we speed up BackTrader sweeps?** → The event loop in BackTrader is too slow for 1800+ tickers. Built a pure pandas/numpy vectorized engine (`VectorizedSEPABacktest`) that simulates exits via merged logic. [2026-04-22.md](logs/2026-04-22.md)

---

## Open meta-questions
- **T3 vs Training Set Gap**: The M01 model has ~45 NaN-filled features because it was trained on `d2_training_cache` but scored against T3 (which lacks some features like `atr_delta`). We must retrain M01 natively on T3 features.
