# Sprint 3 — Research Log

This is the linear train-of-thought for the sprint, tracking questions and their resolution.

## Thread A: Infrastructure & Performance
1. **How do we speed up feature engineering?** → Replaced file-based parquet generation with a centralized `market_data.duckdb` instance using SQL views (`v_sepa_candidates`, `v_d1_candidates`, `v_d2_features`). [sprint_3_summary.md](verdicts/sprint_3_summary.md)
2. **How do we avoid look-ahead bias in fundamentals?** → Created `fundamental_features` in DuckDB with point-in-time logic, ensuring joins only use the most recent filing date ≤ trading date.

## Thread B: Strategy Refinement
1. **Why don't the Test and Prod pipelines match?** → Found discrepancies in volume filters, trend exits, and C9 logic. Shifted C9 to use `price_vs_spy > price_vs_spy_ma63`. Test trades are now a verified 73% overlap subset of Prod.

---

## Open meta-questions
- **Cutover Readiness**: While DuckDB works locally, when can we fully deprecate the legacy parquet-based tools? (Pending a 2-week parallel validation period).
