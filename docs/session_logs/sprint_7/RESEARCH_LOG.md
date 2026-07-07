# Sprint 7 — Research Log

This is the linear train-of-thought for the sprint, tracking questions and their resolution.

## Thread A: Pipeline Debugging
1. **Why did the daily pipeline cross-sectional ranks return 0 rows?** → The `warmup_days=365` parameter fell exactly on the edge of the 252 trading days needed. Increased to 400. [2026-04-01_02_pipeline_investigation.md](logs/2026-04-01_02_pipeline_investigation.md)
2. **How to fix earnings calendar fetch timeouts?** → Implemented smart filtering to skip tickers with known future dates, dropping API calls from ~3981 to ~3790.

## Thread B: Model Reproducibility
1. **How do we ensure models can be reconstructed in the future?** → Built a `feature_catalog` inside `ModelRegistry`. Removed hardcoded feature lists from Python and migrated them to DuckDB-backed configuration. [2026-04-10.md](logs/2026-04-10.md)

---

## Open meta-questions
- **Feature Casing**: `FEATURE_GROUPS` uses lowercase (e.g. `rs_sector_rank`) but `metadata.json` uses TitleCase (`RS_Sector_Rank`). We need to unify these upstream.
