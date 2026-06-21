# Quantamental SEPA Framework

An end-to-end pipeline for ingesting, processing, and systematically scoring equity
"super performers" using Mark Minervini's SEPA (Specific Entry Point Analysis)
methodology, quantitative alpha factors, and machine learning.

> **Authoritative documentation lives in two files — start there:**
> - [`docs/comprehensive_methodology.md`](docs/comprehensive_methodology.md) — full technical specification (replication-grade).
> - [`docs/manual_for_me.md`](docs/manual_for_me.md) — operational architecture, toolkit, and runbooks.
>
> This README is a high-level orientation only; those two are the source of truth.

## What it does

A sequential **daily pipeline** (8 phases) screens the investable universe, computes a
two-tier feature set, gates SEPA trading sessions, and materialises a single ML-ready
feature table in **DuckDB**. A 4-class XGBoost classifier (**M01**) scores breakout
candidates by Maximum Favorable Excursion (MFE) probability; a market-regime model
(**M03**) provides macro context; a BackTrader simulation validates the strategy
historically.

*The data-engineering and predictive-scoring pipelines are fully operational. Execution
logic currently exists only inside the backtest simulation — there is no live order routing.*

## Pipeline at a glance

| Phase | Module | Output table | Criticality |
|-------|--------|--------------|-------------|
| 1 — T1 ingest | `src/data_engine.py`, `fundamental_engine.py`, `shares_engine.py`, `macro_engine.py` | `price_data`, `fundamentals`, `shares_history`, `macro_data`, `t1_macro` | CRITICAL |
| 2 — Screener | `src/managers/screener_manager.py` | `screener_membership` | CRITICAL |
| 3 — T2 features | `src/feature_pipeline.py` | `t2_screener_features` | CRITICAL |
| 4 — Regime (M03) | `src/pipeline/m03_regime.py` | `t2_regime_scores` | non-critical |
| 4b — SEPA gate | `src/managers/sepa_watchlist_manager.py` | `sepa_watchlist` | CRITICAL |
| 5 — T3 features | `src/feature_pipeline.py` | `t3_sepa_features` (144 cols, single ML source of truth) | CRITICAL |
| 6 — Views | `src/managers/view_manager.py` | SQL views + `screener_watchlist` | non-critical |
| 7 — Training cache | `src/managers/view_manager.py` | `d2_training_cache` | non-critical |
| 8 — Monitoring + audits | `src/orchestrators/daily_pipeline_orchestrator.py`, `tools/run_all_audits.py` | logs / alerts | always |

**Universe criteria (v2, effective 2020-01-01):** close ≥ $5, 20-day avg volume ≥ 100K,
market cap ≥ $150M, with a 126-day grace period before exit. Survivorship bias is
mitigated via a ticker-lifecycle system (deactivate / rename / purge).

## Quick start

```bash
# Environment (Windows PowerShell)
python -m venv .venv
.venv/Scripts/Activate.ps1
pip install -r requirements.txt

# Provide API keys in a .env file (see .env.example): FMP, FRED.
```

The primary database is created at `data/market_data.duckdb` on first run — no manual
schema setup is required. For a full from-scratch rebuild, follow the **Replication Guide**
in [`docs/comprehensive_methodology.md`](docs/comprehensive_methodology.md) §14.

### Daily operations

```bash
python scripts/run_daily_pipeline.py                  # full pipeline (yesterday)
python scripts/run_daily_pipeline.py --date 2024-01-15 # specific date
python scripts/run_daily_pipeline.py --phase-3-only    # single phase (incremental)
python scripts/run_daily_pipeline.py --dry-run         # validate only

python tools/run_all_audits.py                         # data-quality audits (all phases)
```

The nightly run is scheduled on the ITX ops box via a self-hosted **Prefect** server +
scheduler (deployment `daily-pipeline/daily`, 22:00 Europe/London, Mon–Fri). The flow
(`flows/daily_pipeline_flow.py`) shells out to the CLI above — one execution path. See
[`docs/session_logs/sprint_12/s4_prefect_orchestration_runbook.md`](docs/session_logs/sprint_12/s4_prefect_orchestration_runbook.md).

### Modelling, backtest, dashboard

```bash
python scripts/train_mfe_classifier.py                 # train M01 (4-class MFE classifier)
python scripts/run_backtest.py                         # BackTrader simulation (DuckDB mode)
streamlit run scripts/dashboard.py                     # full local DB
DASHBOARD_DB_PATH=data/dashboard.duckdb streamlit run scripts/dashboard.py  # slim DB
```

## Project structure

```
src/            Core library — engines, feature pipeline, managers, backtest, evaluation
scripts/        Human-run entrypoints (daily pipeline, backfills, training, dashboard)
  pages/        Streamlit multi-page dashboard
  migrations/   One-off SQL migrations
tools/          Audits + ticker-lifecycle maintenance (deactivate / rename / purge / patch)
tests/          pytest suite
flows/          Prefect flow wrapping the daily pipeline
docs/           Methodology, manual, architecture, plans, session logs
models/         Trained model artifacts (<name>/<version>/)
model_cards/    Rendered model-card HTML/JSON
data/           DuckDB databases + caches/reports (gitignored)
config.py       Central configuration
```

## Machine learning

- **M01 — MFE classifier**: XGBoost `multi:softprob`, 4 classes by MFE % (Noise ≤2%,
  Moderate 2–10%, Strong 10–30%, Home Run >30%), balanced class weights, ~105 features
  across 8 groups. Trained from `d2_training_cache`; artifacts + evaluation registered to
  the `models` table via `ModelRegistry`.
- **M03 — Regime model**: daily market-regime score (Trend / Liquidity / Risk pillars)
  used to gate backtest entries and position sizing.
- **Evaluation**: `ClassificationEvaluator` (confusion matrix, ROC/PR, calibration, SHAP),
  `LeakageGuard` (temporal-leakage validation), and a model-card promotion advisory.

See [`docs/comprehensive_methodology.md`](docs/comprehensive_methodology.md) §7–9 for the
full ML, evaluation, and backtest specification.

## License

Private project. All rights reserved.

---

**Disclaimer**: For educational and personal use only. Past performance does not guarantee
future results. Trading involves risk of loss.
