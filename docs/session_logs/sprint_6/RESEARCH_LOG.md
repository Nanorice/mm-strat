# Sprint 6 — Research Log

This is the linear train-of-thought for the sprint, tracking questions and their resolution.

## Thread A: Infrastructure Refactor
1. **How do we finalize the DuckDB transition?** → Migrated EDGAR fundamentals and company profiles, resolving schema mapping issues and ticker caching. [2026-03-17_03_fundamentals_schema_migration.md](logs/2026-03-17_03_fundamentals_schema_migration.md)
2. **Is the 9-phase daily pipeline robust?** → Conducted mid-sprint check, finding 5 minor issues (transaction wrappers, missing logs/ folder) but deemed it production-ready. [mid_sprint6_check.md](verdicts/mid_sprint6_check.md)

## Thread B: Dashboard & Model Identity
1. **How to visualize M01 & M03 scores live?** → Designed and scaffolded `scripts/dashboard.py` (Phase 1) using Streamlit for screener watchlist and classifications. [2026-03-29.md](logs/2026-03-29.md)
2. **Wait, which M01 model are we scoring with?** → Discovered that `M01_baseline` is a 4-class XGBoost classifier (`multi:softprob`), distinct from the old parallel regressor track.

---

## Open meta-questions
- **M01 Class Imbalance**: The classifier currently has a poor macro_F1 (0.25). How can we address this imbalance before promoting it?
- **Incremental Mode**: Phase 5 incremental mode is a no-op (rebuilds all 2.6M rows). Should we fix this or accept the 90s runtime?
