# Sprint 10 — M01 Two-Model System Evaluation

**Dates:** 2026-05-13 → 2026-05-22 · **Status:** ✅ Closed · **Next:** [sprint_11](../sprint_11/README.md)

> This sprint focused on evaluating a two-model trading system: `m01_prototype` as the event-grain SELECTION model, and `m01_rank` as the dense-grain TIMING model. We conducted rigorous case studies to audit previous backtest anomalies and determine the true trading edge.

### Folder map
- **`RESEARCH_LOG.md`** — the linear question ledger (how the thinking evolved, by sequence).
- **`logs/`** — dated session handovers.
- **`plans/`** — forward-looking design/plan docs.
- **`verdicts/`** — findings, reports, issues, playbooks.
- **`cells/`** — notebook-cell artifacts.

### Headline outcomes
- **m01_prototype Verified & Shipped** — The standalone M01 prototype (daily-dense score + SEPAHybridV1) delivered a strong, verified backtest (+201% return, 0.79 Sharpe, positive in 4/5 years). 
- **m01_rank Shelved** — The previous 28x return for `m01_rank` was root-caused to measurement artifacts (unadjusted split outliers, all-NULL adj_close). We concluded its signal is not durable for entry timing, and it was shelved.

## Roadmap & Goals
- [x] Audit `m01_rank` dense-grain Phase 1 findings
- [x] Build clean Phase 2 backtest engine to fix 28x measurement artifact
- [x] Run Case 1: `m01_prototype` standalone
- [x] Run Case 2: `m01_prototype` + `m01_rank` timing

## Carried over
- [ ] Wire `BAD_TICKERS` upstream into the data loader
- [ ] Fix `price_data.adj_close` being 100% NULL

## Migrated Documents
**Plans:**
- [market_context_data_ingestion_plan.md](plans/market_context_data_ingestion_plan.md)
- [system_design_review_action_plan_2026_05_16.md](plans/system_design_review_action_plan_2026_05_16.md)
- [t1_quality_gate_patch_plan_2026_05_17.md](plans/t1_quality_gate_patch_plan_2026_05_17.md)
- [eda_analytics_pipeline_plan_2026_05_17.md](plans/eda_analytics_pipeline_plan_2026_05_17.md)
- [m01_modeling_strategy_plan_2026_05_18.md](plans/m01_modeling_strategy_plan_2026_05_18.md)
- [m01_rank_phase2_backtest_engine_2026_05_21.md](plans/m01_rank_phase2_backtest_engine_2026_05_21.md)

**Verdicts:**
- [m01_rank_dense_grain_audit_2026_05_20.md](verdicts/m01_rank_dense_grain_audit_2026_05_20.md)
- [m01_rank_phase1_findings_2026_05_21.md](verdicts/m01_rank_phase1_findings_2026_05_21.md)
- [m01_case_studies_2026_05_22.md](verdicts/m01_case_studies_2026_05_22.md)
- [m01_rank_design_note_2026_05_22.md](verdicts/m01_rank_design_note_2026_05_22.md)
