# Sprint 11 Summary — FINAL

**Dates:** 2026-05-22 to 2026-06-06  
**Branch:** `infra_uplift` (end of sprint)  
**Goal:** Solidify infrastructure, establish irrefutable evaluation framework, determine path forward for modelling strategy.

---

## 1. Strategy Verdict: m01_rank Retired as Timing Model

Evaluated the dual-model thesis (prototype selects, rank times). Discovered m01_rank's scores are horizon-invariant (1d and 20d correlate at 0.92), meaning it captures *setup quality* not *timing*. **Decision:** treat timing as a price-action problem (ATR stops + trend breaks). Use the ML model as a threshold filter — P(MFE > 30%) ≥ 0.30 — not a magnitude ranker. Docs: [m01_rank_dense_grain_audit](../../plans/m01_rank_dense_grain_audit_2026_05_20.md), [2026-05-23_evaluation-framework.md](2026-05-23_evaluation-framework.md).

---

## 2. Deep-Rigor Evaluation Framework

Built a full academic-grade evaluation suite:

- **Walk-Forward Cross-Validation** — anchored walk-forward training + backtesting, no overlapping lookahead bias
- **Regime-Conditional Metrics** — performance broken down by Strong Bull / Bull / Neutral / Bear / Strong Bear
- **Calibration Audits** — ECE + Isotonic calibration
- **Robustness Tools** — Block Bootstrap CI, Permutation null backtesting, Decile IC analysis, Feature Ablation
- **CLI:** `run_deep_rigor_suite.py`

Verdict on m01_binary: **DEMOTE-as-ranker, HOLD-as-filter**. Docs: [2026-05-24_eval-14c-parallel-deep-rigor.md](2026-05-24_eval-14c-parallel-deep-rigor.md), [2026-05-25_binary-pruned-and-deep-rigor.md](2026-05-25_binary-pruned-and-deep-rigor.md).

---

## 3. Model Card Framework (Phases 1–3)

Built a 7-section automated model card generator (`build_model_card.py`) producing numerical (0–3) rubric scores.

| Phase | Sections | Status |
|---|---|---|
| 1 | A (Integrity), B (Discrimination), C (Calibration) | ✅ Done |
| 2 | D (Ranker Quality), E (Threshold Gates), F (Robustness) + Mode A/B ledgers | ✅ Done |
| 3 | G (Edge vs. Baselines — permutation null + block bootstrap CI + SEPA composite benchmark) + per-use-case verdict reasons | ✅ Done |
| 4 | Promotion-gate integration into ModelRegistry | ❌ Deferred → Sprint 12 |

Key findings from the card:
- `m01_prototype_2003_2026/v1`: score 9/21 (WEAK), acc=0.6705, wF1=0.582, macroF1=0.248
- `m01_prototype_cali/v1` (calibrated): score 10/21 (WEAK). ECE barely improved (0.142 → 0.125). Model fails E2_trade_frequency gate (2.76 trades/month at T=0.6, gate requires ≥3.0). Root cause: calibration pushed probabilities toward base rate, suppressing high-confidence calls. As a human-in-the-loop screener at T=0.6 (precision 54.1%, 4.68× lift) or T=0.7 (precision 81.1%, 7.02× lift) the model performs well despite the gate failure.

Docs: [2026-05-25_model-card-phase-1-and-2.md](2026-05-25_model-card-phase-1-and-2.md), [2026-05-26_model-card-phase-3.md](2026-05-26_model-card-phase-3.md), [phase_4_promotion_gate_pending.md](phase_4_promotion_gate_pending.md).

---

## 4. Fundamental Engine — Root Cause Investigation & EDGAR Fix

### Root Causes Found (DONE_fundamental_engine_investigation.md)
Three structural flaws in the fundamentals pipeline:
1. **Trigger Deadlock** — orchestrator staleness check touched `updated_at` daily → monthly calendar refresh never fired
2. **Silent-Skip Contamination** — tickers already confirmed on calendar refresh went straight to `is_confirmed=TRUE`, skipping fundamentals pull
3. **Wrong staleness anchor** — `_get_stale_fundamental_tickers` measured against `MAX(updated_at)` (audit timestamp), not `MAX(period_end)` (data date) → 34 tickers missed for 57–183 days

All three fixed: staleness check now anchors on `period_end`; daily fetch list 1 → 345 tickers.

### EDGAR Backbone (feat commit 8b808db)
yfinance is the wrong source for authoritative filing dates. Built `EDGAREngine`:
- `src/edgar_engine.py`: `EDGARClient` (10 req/s, User-Agent) + `EDGAREngine` (CIK map + filing-date backfill via SEC submissions API)
- New DuckDB table: `cik_map` (10,365 rows)
- Filing-date coverage: **42.9% → 97.73%** (3,068 rows backfilled in 8 min)
- Daily orchestrator: weekly `phase_1_cik_map_refresh` + daily `phase_1_filing_date_backfill` (200 tickers/run, bounded)
- Residual 143 NULLs: 95 fiscal-calendar mismatches, 41 no-CIK foreign filers, 7 inactive

---

## 5. T1 Ingestion Failures — Full Triage

**Phase A** — per-ticker failure causes captured; classifier widened for yfinance NO_DATA strings.  
**Phase B** — deactivated 14 chronic-NO_DATA tickers; universe 4020 → 4006.  
**Phase C** — staleness check fixed (wrong anchor); daily fetch list corrected.  
**Phase D** — SKIPPED (dashboard reads `pipeline_error_log` live; no hardcoded headline).

Follow-up items completed:
- **Follow-up #2** ✅ — deactivated 26 confirmed-dead tickers (stale price ≥10d); universe 4006 → 3980. `deactivate_tickers.py` now requires `--reason` + writes JSONL audit to `logs/data_quality/deactivations.jsonl`.
- **Follow-up #3** ✅ — EDGAR_NO_DATA cohort: bumped `REPORT_DATE_TOLERANCE_DAYS` 15→35d (4 rows filled); deleted 66 phantom yfinance rows across 40 tickers (SPAC/blank-check fabrications).
- **Follow-up #4** ✅ — no-CIK cohort 36→3; patched 33/36 via EDGAR full-text search; `cik_map` 10,365 → 10,398; active-equity CIK coverage 98.2% → 99.0%.
- **Follow-up #9** ✅ — stale-fundamentals check rewritten: anchors on last *filed* period_end + 135d expected lag (not flat 100d). Instrument reclassification via `EDGAREngine.classify_ticker_types`: 42 tickers reclassified (23 FOREIGN, 19 FUND); equity staleness cohort 204 → 162. Zero deactivations from this batch (all 162 confirmed price-live).
- **Follow-up #10** ✅ — NULL filing_date on write surfaced in pipeline health: new `null_filing_date_written` counter in Phase-1 stats, visible on Pipeline Health page.

---

## 6. macro_data Fix

`macro_data` was orphaned from the daily pipeline — orchestrator called `ingest_daily_macro()` (writes `t1_macro`) but never called `update_macro_cache(write_db=True)` (writes `macro_data`). Downstream: `t2_risk_scores` and M03 regime used 17-day-old macro data for ~3 weeks.

Fix: orchestrator Phase 1 now calls both; `macro_data` freshness tolerance bumped 2d → 8d for weekly series (WALCL/WTREGEN/WBAA). Catch-up run brought all 8 series current.

---

## 7. Pipeline Health Dashboard Upgrades

- **Audit History** — orchestrator Phase 8 now calls `tools/run_all_audits.py` daily (600s timeout, best-effort); audit reports date-keyed in `data/audit_reports/`
- **Pipeline Runs heatmap** — continuous date axis (no collapsed weekends); yellow `warning` state when `success + n_errors > 0` (T1 ticker errors previously invisible)
- **Data freshness** — `macro_data` correctly wired; `earnings_calendar` tolerance clarified (not stale, future-looking)
- **t1_macro gap repair** — 6 missing dates (2026-03-30 to 2026-05-08) backfilled; 4 downstream T2 audit FAILs cleared

---

## 8. Dashboard UI Fixes (all ✅)

| Fix | File |
|---|---|
| Active Density by Class — truncate at p99 (not clip) | `src/evaluation/html_report.py` |
| Multicollinearity plot — scipy hierarchical reorder | `src/evaluation/html_report.py` |
| Feature Signal bar chart — uniform ACCENT color | `src/evaluation/html_report.py` |
| MFE histogram — overflow bar for >p99 | `src/evaluation/html_report.py` |
| Universe Activity — 2-row layout, smoothed line + yearly bars | dashboard |
| Pipeline Runs — continuous date axis + warning state | `scripts/pages/5_Pipeline_Health.py` |
| Forward-Return Profile — renamed "Trailing Return at Entry" | `src/evaluation/html_report.py` |
| Sector ETF flow — verified T1→T2→T3 end-to-end, no bypass | investigation only |

---

## 9. Infra Uplift (Sunday Sprint — in progress at sprint end)

Branch: `infra_uplift`. Goal: slim dashboard DB + remote hosting so the dashboard runs off the dev box.

- **4.1** Table audit done (first pass): 22 tables/views the dashboard queries identified
- **4.2** GitHub push — not yet executed (`.gitignore` review, secrets scan, model-artifact policy TBD)
- **4.3** Remote hosting — not started; recommended path: slim `dashboard.duckdb` (<1 GB) → object storage → Streamlit Cloud/Fly.io

See [misc_todo_0529.md §4](misc_todo_0529.md#4-sunday-sprint-plan-infra_uplift) for full plan.

---

## Deferred to Sprint 12

| Item | Notes |
|---|---|
| Deploy prod model | Retrain m01_prototype on clean fan-out-free dataset; promote to prod |
| Model Card Phase 4 | Wire card verdict into `ModelRegistry.set_prod()` promotion gate |
| Infra uplift (4.2 + 4.3) | GitHub push + remote hosting |
| Mode B analytics | Score trajectory analysis — super performers vs ordinary trades |
| Universe lifecycle automation | Auto inflow discovery + outflow dead-ticker detection |
| Feature drift / PSI quarterly trigger | Finalize cron |
| Evaluation framework Phase 4 | Wording TBD |
| Risk: 5-factor model improvements | Factor weights, Z-score memory, UI |
| `earnings_calendar` at-scale rate-limit | Separate ticket |
| Audit script 120s → 600s timeout | Minor; run_all_audits manual timeout |
