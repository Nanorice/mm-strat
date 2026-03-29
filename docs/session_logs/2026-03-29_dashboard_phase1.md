# Session Handover: 2026-03-29

## Goal
Design and scaffold the Streamlit dashboard (Phase 1) — screener watchlist with M01 4-class classification and M03 regime header.

## Accomplished
- Designed full dashboard architecture across two planning sessions, documented in `docs/dashboard_design.md`
- Investigated M01 model identity: confirmed M01_baseline is a **4-class XGBoost MFE classifier** (`multi:softprob`), NOT the regressor from `src/pipeline/m01_trainer.py`
- Audited `src/pipeline/` directory — confirmed entire directory is active (parallel model tracks), nothing to delete
- Verified M03 wiring: `DailyPipelineOrchestrator` Phase 4 calls `RegimePipeline.update_incremental()` → `t2_regime_scores` stays fresh
- Identified model registry schema gap: `models` table only has regression columns; classifier metrics stored in `metadata.json` on filesystem
- Implemented `scripts/dashboard.py` — full Phase 1 Streamlit dashboard with all 4 sections
- Updated `docs/dashboard_design.md` with implementation status, known limitations, Phase 2 TODOs
- Updated `docs/manual_for_me.md` with new Dashboard section, resolved item, updated TODOs

## Files Changed
- `scripts/dashboard.py`: **NEW** — Streamlit dashboard (Phase 1). M03 regime header, M01 signal summary, screener watchlist table with filters, analytics section.
- `docs/dashboard_design.md`: **NEW** — Full design doc: data sources, M01/M03 specs, layout, implementation notes, Phase 2 roadmap.
- `docs/manual_for_me.md`: Added Dashboard section (Phase 1 + Phase 2 roadmap), updated TOC, updated Open TODOs, added resolved item.

## Work in Progress (CRITICAL)
- **Dashboard is scaffolded but untested against live data.** Needs `streamlit run scripts/dashboard.py` to verify:
  - M01 scoring works end-to-end (feature column mapping between `v_d3_deployment` lowercase and `metadata.json` mixed-case)
  - `screener_watchlist` table is populated (requires daily pipeline to have run)
  - `t2_regime_scores` has data (requires Phase 4 to have run)
- **No M01 Score vs Actual Return scatter yet** — exited trades need historical features from `t3_sepa_features` at `entry_date`, deferred to Phase 2.

## Next Steps
1. **Test-launch** `streamlit run scripts/dashboard.py` and fix any data/column mapping issues
2. **Dashboard Phase 2** — add data audit, model eval, backtest, feature time-series pages (see `docs/dashboard_design.md`)
3. **Model work** — retrain M01 on updated T3 data (rebuilt 2026-03-27), address class imbalance (macro_F1=0.25)
4. **Promote M01 to prod** — `reg.set_prod(version_id)` after validation backtest

## Context/Memory
- **M01 model confusion**: `src/pipeline/m01_trainer.py` is NOT stale — it's a parallel regressor track used by `run_m01_*.py` scripts. The classifier (`M01_baseline`) lives in `scripts/train_mfe_classifier.py` and saves to `models/m01_baseline/v1/`. These are two different model tracks sharing the M01 name.
- **`ProductionScorer`** (`src/pipeline/production_scorer.py`) is wired for the old regressor, not the classifier. Dashboard bypasses it entirely and loads the XGBClassifier directly.
- **DuckDB column casing**: All column names stored lowercase, but model `valid_features` has mixed case (e.g., `RS_Sector_Rank`). Dashboard handles this with a `col_map = {c.lower(): c for c in columns}` mapping.
- **`screener_watchlist`**: `close_price` serves double duty — current price for ACTIVE trades, exit price for EXITED. No separate `exit_price` column. `exit_date` IS present.
- **Model registry schema gap**: Classifier metrics (`accuracy`, `f1`) are NOT in the `models` table (only regression columns exist). For Phase 2, plan to embed in `specs_json` column — no schema migration needed.
