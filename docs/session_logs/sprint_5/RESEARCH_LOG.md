# Sprint 5 — Research Log

This is the linear train-of-thought for the sprint, tracking questions and their resolution.

## Thread A: DuckDB V2 Architecture
1. **How should we structure the DB for performance?** → Transition to a 3-tier lazy materialization architecture (T1 raw/macro, T2 screener features for full universe, T3 SEPA features append-only). [2026-03-09_01_duckdb_v2_planning.md](logs/2026-03-09_01_duckdb_v2_planning.md)
2. **What is blocking the T3 backfill?** → The fundamental audit discovered 5 missing ratio columns (e.g. `market_cap`, `pe_ratio`). These must be backfilled first.

## Thread B: Backtest Infrastructure
1. **How do we hook BackTrader up to DuckDB?** → Created `duckdb_feed.py` which queries `t3_sepa_features` and converts it into BackTrader-compatible data feeds. Achieved ~34 tickers/sec load time. [2026-03-15.md](logs/2026-03-15.md)
2. **How to handle dynamic sizing?** → Added `sizing_mode` to `sepa_strategy.py` with regime-based, equal-weight, rank-weighted, and score-weighted options.

---

## Open meta-questions
- **T2 Performance**: Will a 60M+ row T2 table (8K tickers x full history) cause query slowdowns? (Mitigation: indexing, threads)
- **M03 Breadth Indicators**: Where to source `advance_decline_ratio` and `new_high_low_ratio`?
