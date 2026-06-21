# Streamlit Dashboard Design
*Single source of truth for dashboard architecture and development roadmap.*

> Last updated: 2026-03-29 — Phase 1 scaffold complete.

---

## Overview

A Streamlit dashboard to visualise the live trading pipeline output. Entry point: `scripts/dashboard.py`.

**Run:** `streamlit run scripts/dashboard.py`

**Phase 1** (implemented 2026-03-29): Screener Watchlist page — M01 4-class classification + M03 regime header + analytics.
**Phase 2** (planned): Data audit, model eval, backtest, and feature time-series pages.

---

## Data Sources

| Source | Table / File | Notes |
|--------|-------------|-------|
| Live trades | `screener_watchlist` | Materialised from `v_screener_dashboard`; columns: `ticker`, `company_name`, `sector`, `industry`, `market_cap`, `entry_date`, `entry_price`, `exit_date`, `status` ('ACTIVE'/'EXITED'), `close_price`, `price_date`, `pct_return`, `days_held`, `refreshed_at` |
| M01 model | `models/m01_baseline/v1/model.json` | Load via `xgb.XGBClassifier().load_model()` |
| M01 features (105) | `models/m01_baseline/v1/metadata.json` → `valid_features` | Feature list used at training time |
| M01 inference data | `v_d3_deployment` | Last 252 days, SEPA candidates — features joined to active trades by ticker |
| M03 regime | `t2_regime_scores` | Written daily by `RegimePipeline` (Phase 4 of orchestrator); columns: `date`, `m03_score`, `m03_pillar_trend`, `m03_pillar_liq`, `m03_pillar_risk`, `m03_delta_5d`, `m03_delta_20d`, `m03_regime_vol` |
| Pipeline health | `pipeline_runs` | Last run timestamp, phase status, runtime |

---

## M01 Model — M01_baseline

**Type:** 4-class XGBoost classifier (`multi:softprob`)
**Output:** Softmax probabilities for 4 MFE buckets:

| Class | Label | MFE Range |
|-------|-------|-----------|
| 0 | Noise | 0–2% |
| 1 | Moderate | 2–10% |
| 2 | Strong | 10–30% |
| 3 | Home Run | >30% |

`predict_proba()` returns all 4 probabilities — show all 4 as a small bar or badge row per trade.
Predicted class = `argmax(proba)`.

**Note on `src/pipeline/m01_trainer.py`:** This is a separate XGBoost Regressor model (different from M01_baseline) still actively used by `run_m01_*.py` scripts. It is a parallel model track, not stale. Do not remove.

---

## M03 Regime — Pillar Formulas

Three pillars feed a weighted composite score (0–100):

| Pillar | Weight | Column | Formula |
|--------|--------|--------|---------|
| Trend | 40% | `m03_pillar_trend` | `50 + 50 × tanh(pct_above_sma200 × 10)` — SPY vs 200d SMA |
| Liquidity | 30% | `m03_pillar_liq` | `50 + 50 × tanh(slope_pct × 50)` — 20d linear slope of Fed Net Liquidity (WALCL − WTREGEN − RRPONTSYD) |
| Risk Appetite | 30% | `m03_pillar_risk` | VIX component (0–50) + HY Credit Spread component (0–50) |

**Composite category thresholds:** Strong Bull ≥80 · Bull ≥60 · Neutral ≥40 · Bear ≥20 · Strong Bear <20

---

## Phase 1: Screener Watchlist Page

**File:** `scripts/dashboard.py`

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER: M03 Regime                                         │
│  [Category Badge]  Score: 72.4                              │
│  Trend: 81  |  Liquidity: 65  |  Risk Appetite: 70          │
│  (hover tooltip on each pillar shows formula)               │
│  Last pipeline run: 2026-03-28 06:45  |  Data as of: today  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  SECTION 1: M01 Signal Summary (active trades only)         │
│  Score distribution histogram (4 classes)                   │
│  High-conviction count (class 2+3) vs total active          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  SECTION 2: Screener Watchlist Table                        │
│  Filters: Status | Sector | Date range                      │
│                                                             │
│  Columns:                                                   │
│  Ticker | Company | Sector | Entry Date | Entry Price       │
│  Current/Exit Price | Return % | Days Held                  │
│  M01 Class | P(Noise) | P(Moderate) | P(Strong) | P(HR)     │
│  Status                                                     │
│                                                             │
│  Styling: return % green/red · class badge colour-coded     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  SECTION 3: Analytics (below table)                         │
│                                                             │
│  Quick Stats Row:                                           │
│  # Active  |  Avg Return % (active)  |  Win Rate (exited)  │
│  Avg Holding Period                                         │
│                                                             │
│  [Col A] Trade Age Heatmap                                  │
│  Active trades by days held — flag aging (>60d, low return) │
│                                                             │
│  [Col B] Sector Concentration Bar                          │
│  # active trades per sector                                 │
│                                                             │
│  [Col C] M01 Score vs Actual Return Scatter                 │
│  Exited trades only — predicted class vs realised pct_return│
│  Key validation chart for model credibility                 │
└─────────────────────────────────────────────────────────────┘
```

### Implementation Status (2026-03-29)

All sections above are implemented in `scripts/dashboard.py`:

- `@st.cache_data(ttl=300)` on all DB reads; `@st.cache_resource` for model loading.
- M01 scoring: loads classifier from `models/m01_baseline/v1/model.json`, reads `valid_features` from `metadata.json`, joins active trades to latest `v_d3_deployment` features by ticker, calls `predict_proba()`. Handles DuckDB lowercase → mixed-case column mapping.
- M03 header: reads `MAX(date)` row from `t2_regime_scores`. Shows composite score, category badge, 3 pillar metrics with formula captions.
- M03 freshness: confirmed wired — `DailyPipelineOrchestrator` Phase 4 calls `RegimePipeline.update_incremental()`.
- Pipeline status: reads latest row from `pipeline_runs`.
- Analytics: quick stats row, trade age bar (flags >60d held with <5% return), sector concentration bar, exited returns histogram.

### Known Limitations

- **M01 Score vs Actual Return scatter** (exited trades): requires re-scoring with historical features at entry date — deferred to Phase 2 (needs `t3_sepa_features` join at `entry_date`).
- **`ProductionScorer`** (`src/pipeline/production_scorer.py`): exists but wired for the old regressor M01 (continuous scores + calibration). Dashboard bypasses it and loads the classifier directly.
- **Model registry gap**: `models` table has only regression columns (`rmse`, `r2`). Classifier metrics (`accuracy`, `f1`) stored in `metadata.json` on filesystem. Phase 2: embed in `specs_json` column.

---

## Phase 2: Future Pages

| Page | Data Source | Key Content |
|------|------------|-------------|
| Data Audit Report | `pipeline_runs`, quality logs | Phase completion status, failure rates, data freshness per ticker |
| Model Evaluation Report | `models/M01_baseline/` JSON reports | Confusion matrix, per-class precision/recall, feature importance, SHAP |
| Backtest Results | TBD (backtest engine) | Equity curve, trade stats, drawdown |
| Feature Time Series | `t3_sepa_features` JOIN `screener_watchlist` | Price + volume + selected features over time for a single ticker |

---

## File Structure

```
scripts/
  dashboard.py          ← Streamlit entrypoint (Phase 1) — implemented 2026-03-29
src/
  dashboard_reports.py  ← Existing ML report viewer (keep separate, Phase 2 integration)
  pipeline/
    production_scorer.py ← Old regressor scoring (NOT used by dashboard; parallel model track)
models/
  m01_baseline/v1/
    model.json           ← XGBoost 4-class classifier (multi:softprob)
    metadata.json        ← 105 valid_features, training metrics, leakage audit
    evaluation/          ← Confusion matrix, ROC/PR curves, SHAP, feature importance
```

---

## Completed (Phase 1)

- [x] `src/pipeline/` audit: Entire directory is active. `m01_trainer.py` is a parallel regressor track still used by `run_m01_*.py` scripts.
- [x] M03 wiring confirmed: `DailyPipelineOrchestrator` Phase 4 → `RegimePipeline.update_incremental()` → `t2_regime_scores`.
- [x] Model registry schema: classifier metrics in `metadata.json` (filesystem). Phase 2: add to `specs_json`.
- [x] `scripts/dashboard.py` scaffolded (2026-03-29).

## Phase 2 TODOs

- [ ] **Data Audit Report page** — surface `pipeline_runs` status + `data/audit_reports/` JSON
- [ ] **Model Evaluation Report page** — render `models/m01_baseline/v1/evaluation/` artifacts (confusion matrix, ROC, SHAP)
- [ ] **Backtest Results page** — equity curve, trade stats, drawdown from `data/backtest/`
- [ ] **Feature Time Series page** — `t3_sepa_features` JOIN `screener_watchlist` by ticker, plot price/volume + selected features
- [ ] **M01 Score vs Actual Return scatter** — score exited trades with historical features (join `t3_sepa_features` at `entry_date`)
- [ ] **Embed classifier metrics in `specs_json`** — update `train_mfe_classifier.py` to include accuracy/f1 in registry call
