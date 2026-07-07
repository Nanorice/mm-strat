# Sprint 10 — Research Log

This is the linear train-of-thought for the sprint, tracking questions and their resolution.

## Thread A: Two-Model Trading System
1. **Is the 28x backtest return from `m01_rank` real?** → No. Root-caused to backtest construction bugs: gappy-panel `shift(-1)`, `price_data.adj_close` being 100% NULL, and unadjusted split outliers (like LIF +2.7M%). [2026-05-22_01_main.md](logs/2026-05-22_01_main.md)
2. **Which model configuration should we ship?** → Ran 3 case studies. Case 1 (`m01_prototype` standalone) is strong and verified (+201%, Sharpe 0.79). Case 2 (`m01_rank` as an entry-reranker) hurts performance. Shipped prototype, shelved rank. [2026-05-22_02_backtest-cases.md](logs/2026-05-22_02_backtest-cases.md)

---

## Open meta-questions
- **Adjusted Close Data Gap**: The `price_data.adj_close` column is 100% NULL, which severely impacts backtest precision and forces the use of blunt return-clips. When will we fix the upstream ingestion?
