# Quantamental System — Project Lifecycle Manual

**Audience:** Developer / operator running this system solo or in a small team.  
**Purpose:** Single authoritative reference for every stage of the project lifecycle. Start here before touching any code.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Stage 1 — Data Ingestion (T1)](#2-stage-1--data-ingestion-t1)
3. [Stage 2 — Feature Processing (T2/T3)](#3-stage-2--feature-processing-t2t3)
4. [Stage 3 — Monitoring & Pipeline Health](#4-stage-3--monitoring--pipeline-health)
5. [Stage 4 — Model Training](#5-stage-4--model-training)
6. [Stage 5 — Model Evaluation & Model Card](#6-stage-5--model-evaluation--model-card)
7. [Stage 6 — Strategy Backtesting & Deployment](#7-stage-6--strategy-backtesting--deployment)
8. [Model Development Lifecycle](#8-model-development-lifecycle)
9. [Running the Daily Pipeline](#9-running-the-daily-pipeline)
10. [Runbooks](#10-runbooks)

---

## 1. System Overview

### Architecture (4+1 Layers)

```
Layer 1: Engines      — raw data I/O (price, fundamentals, shares, macro, EDGAR)
Layer 2: Pipelines    — computation (features, regime scores)
Layer 3: Managers     — state & lifecycle (views, screener, pipeline runs)
Layer 4: Orchestrator — 9-phase daily workflow coordinator
Layer 5: CLI Scripts  — human-facing entry points
```

### Database

Single DuckDB file: `data/market_data.duckdb` (71.8 GB, not committed to git).

Key tables:

| Table | Owner | Size | Purpose |
|---|---|---|---|
| `price_data` | DataRepository | 29M rows | OHLCV, one row per (ticker, date) |
| `fundamentals` | FundamentalEngine | ~6K rows | Quarterly financials per ticker |
| `daily_features` | FeaturePipeline | ~2.6M rows | 149 features per (ticker, date) |
| `t2_screener_features` | FeaturePipeline | 183M rows | Lightweight screener features, all tickers |
| `t3_sepa_features` | FeaturePipeline | 9.3M rows | Full feature set for SEPA breakout candidates only |
| `d2_training_cache` | ViewManager | ~500K rows | Materialized training set (70x faster than view) |
| `screener_members` | ScreenerManager | ~4K rows | Universe membership (active + criteria version) |
| `pipeline_runs` | PipelineRunManager | rolling | Per-run state, phase metadata, error counts |
| `pipeline_error_log` | PipelineRunManager | rolling | Per-ticker errors by phase |
| `models` | ModelRegistry | small | Registered model versions + promotion state |
| `cik_map` | EDGAREngine | 10.4K rows | Ticker → SEC CIK mapping |
| `macro_data` | MacroEngine | long-format | 8 macro series (FRED + VIX), daily/weekly |

### Universe

~3,980 active tickers (equities only; ETF=36, FOREIGN=23, FUND=19, INDEX=3 handled separately).  
Criteria for screener membership: price ≥ $15, 20d avg volume ≥ 500K.

---

## 2. Stage 1 — Data Ingestion (T1)

### What runs

The daily orchestrator Phase 1 runs four parallel sub-phases:

| Sub-phase | Engine | What it does |
|---|---|---|
| `phase_1_t1_price` | DataRepository | yfinance incremental price fetch; writes to `price_data` |
| `phase_1_t1_fundamentals` | FundamentalEngine | yfinance quarterly financials; writes to `fundamentals` |
| `phase_1_t1_shares` | SharesEngine | shares outstanding; writes to `shares_outstanding` |
| `phase_1_t1_macro` | MacroEngine | FRED + VIX; writes to both `t1_macro` (wide) AND `macro_data` (long) |

Weekly (gated): `phase_1_cik_map_refresh` refreshes `cik_map` from SEC directory.  
Daily (bounded): `phase_1_filing_date_backfill` uses EDGAR to fill `filing_date` NULLs (200 tickers/run).

### Key design decisions

- **Price staleness:** `DataRepository._get_stale_tickers` uses a 45-day liveness floor — tickers with no bar in 45d are assumed dead and skipped (avoids infinite retry on dead names).
- **Fundamentals trigger:** daily fetch targets tickers where `today > last_filed_period_end + 135d` (new) or `filing_date IS NULL` (legacy NULL cleanup). Not earnings-calendar-driven (calendar is broken at scale — yfinance silently rate-limits at ~3,400 tickers).
- **Filing dates:** SEC EDGAR is the authoritative source, not yfinance. `EDGAREngine` matches `reportDate ≈ period_end ±35d`. Coverage: 97.73%.
- **macro_data:** must call BOTH `ingest_daily_macro()` (→ `t1_macro`) AND `update_macro_cache(write_db=True)` (→ `macro_data`). Calling only the first leaves `macro_data` stale.

### Common failure modes

| Symptom | Root Cause | Fix |
|---|---|---|
| `NO_DATA` for a ticker | yfinance: ticker delisted or OTC-only | Check yfinance manually; if consistently failing → `deactivate_tickers.py` |
| `filing_date = NULL` for fundamentals | yfinance `get_earnings_dates()` rate-limited or failed | EDGAR backfill drains NULLs daily; check `null_filing_date_written` metric on Pipeline Health |
| `macro_data` shows stale on dashboard | orchestrator called `ingest_daily_macro` but not `update_macro_cache` | Run `update_macro_cache(write_db=True)` manually; verify orchestrator Phase 1 calls both |
| Stale fundamentals cohort growing | staleness check wrong anchor or instrument misclassified | Run `scripts/enrich_ticker_types_edgar.py` to reclassify; check `_check_filing_date_quality` |

### Universe management (manual today)

- **Deactivate dead tickers:** `python tools/deactivate_tickers.py --tickers XYZ --reason "no yfinance data 30d" --execute`  
  Writes to `logs/data_quality/deactivations.jsonl`.
- **Discover new tickers:** `python scripts/run_universe_backfill.py --discover-fmp` (manual; no cron yet)

---

## 3. Stage 2 — Feature Processing (T2/T3)

### Computation flow

```
price_data + fundamentals + macro_data + shares_outstanding
    ↓ Phase A (SQL, ~10s)       → daily_features: 79 base columns
    ↓ Phase B (Python, ~50-60s) → +16 WQ101 alpha factors
    ↓ Phase C (SQL, ~2s)        → +7 cross-sectional ranks
    ↓ Phase D (SQL)             → +7 M03 regime features
    ↓ Phase E                   → d2_training_cache refresh (7s)
    → t2_screener_features      (lightweight, all tickers, ~3.25M rows)
    → t3_sepa_features          (SEPA candidates only, lazy materialization)
```

Feature version: `v3.1` (149 columns total in `daily_features`).

### Views (managed by ViewManager)

| View | Source | Purpose |
|---|---|---|
| `v_d1_candidates` | `t3_sepa_features` | Current SEPA candidates with delta features |
| `v_d2_training` | `t3_sepa_features` | Training set with outcomes |
| `v_d2_hydrated` | `t3_sepa_features` | Training set + sma_50, atr_20d for stop-loss logic |
| `v_d3_deployment` | `t3_sepa_features` | Last 252 days for model scoring |
| `d2_training_cache` | materializes `v_d2_training` | 70x faster training data load (0.126s vs 8.8s) |

Views query `t3_sepa_features WHERE feature_version = 'v3.1'`.

### Key gotchas

- `price_data.volume` is `UBIGINT` — subtract with `CAST(volume AS BIGINT)`.
- DuckDB named windows cannot reference other named windows — use multiple CTEs.
- `daily_features` is rebuilt via `CREATE OR REPLACE TABLE` (not incremental INSERT).
- Phase B (Python groupby+rolling) is the bottleneck — uses multiprocessing (4 workers). ~50-60s for 2.6M rows.
- Log transforms were **removed** from `v_d2_training` (2026-04-10). No model uses `log_*` columns.
- `sector` / `industry` are VARCHAR categoricals for XGBoost `enable_categorical` — no integer encoding.

### Recreating views after schema changes

```bash
python scripts/create_duckdb_views.py
python scripts/refresh_training_cache.py
```

---

## 4. Stage 3 — Monitoring & Pipeline Health

### Dashboard

```bash
streamlit run scripts/app.py
```

Pages:
- **Page 1: Dataset EDA** — universe overview, feature distributions, multicollinearity, SEPA trade stats
- **Page 5: Pipeline Health** — data freshness per table, pipeline runs heatmap (30d), audit history, fundamentals DQ metrics

### Pipeline Runs Heatmap

Color coding: 🔴 failed / 🟡 warning (success + n_errors > 0) / 🟢 success / ⬜ no-run.  
Yellow = T1 ticker errors that didn't halt the phase but represent partial data quality failures.

### Audit System

Phase 8 of the orchestrator runs `tools/run_all_audits.py` daily (600s timeout, best-effort).  
Audit reports: `data/audit_reports/audit_report_YYYYMMDD.json`.

To run manually:
```bash
python tools/run_all_audits.py --date 2026-06-09 --warn-only
```

### Key freshness tolerances

| Table | Tolerance | Notes |
|---|---|---|
| `price_data` | 2d | Weekends/holidays expected |
| `fundamentals` | 135d | Quarterly filing lag |
| `macro_data` | 8d | Weekly series (WALCL etc.) |
| `earnings_calendar` | -200d | Future-looking; negative tolerance normal |

### Deactivating dead tickers

```bash
# Dry run first
python tools/deactivate_tickers.py --tickers TICKER1 TICKER2 --reason "no price data 30d"
# Execute
python tools/deactivate_tickers.py --tickers TICKER1 TICKER2 --reason "no price data 30d" --execute
```

---

## 5. Stage 4 — Model Training

### Training data

```python
from src.evaluation.training_data_loader import load_training_data_from_db
df = load_training_data_from_db(use_cache=True)  # uses d2_training_cache (~0.1s)
```

Column casing: DuckDB returns lowercase; `load_training_data_from_db` applies `COLUMN_CASE_MAP` to rename to TitleCase for M01_FEATURES compatibility.

### Feature set

```python
from src.evaluation.training_data_loader import get_model_features
features = get_model_features('M01')  # queries model_feature_sets in DuckDB
```

If this raises `RuntimeError`: run `python scripts/populate_feature_catalog.py` first.

### Models

| Model | Role | Notes |
|---|---|---|
| `m01_prototype` | SELECTION — picks breakout setups | Primary prod model. Use as threshold filter: P(MFE>30%) ≥ 0.30 |
| `m01_rank` | TIMING | **Retired** — horizon-invariant. Not a standalone picker. |
| `m02` | Ignition classifier | 38 velocity-only features, no fundamentals, no M03 |

### Training a new model version

1. Load training data: `load_training_data_from_db(use_cache=True)`
2. Select features via `get_model_features('M01')` or define a new feature set
3. Train with `XGBClassifier(enable_categorical=True)` — `sector`/`industry` are categorical
4. Evaluate (see Stage 5)
5. Register: `ModelRegistry.register(model_name, version, path, feature_set, ...)`
6. Promote only after model card passes (see Stage 5 + Model Card Phase 4)

---

## 6. Stage 5 — Model Evaluation & Model Card

### Evaluation suite

```bash
python scripts/run_deep_rigor_suite.py --model m01_prototype/v2
```

Produces:
- Walk-forward cross-validation results
- Regime-conditional metrics (Strong Bull → Strong Bear)
- Calibration audit (ECE, reliability diagram)
- Block Bootstrap CI, Permutation null backtesting
- Decile IC analysis
- Feature ablation

### Model Card

```bash
python scripts/build_model_card.py --model m01_prototype/v2 --output model_cards/m01_prototype_v2.html
```

7 sections (A–G):
- **A** Integrity — data quality, lookahead checks
- **B** Discrimination — AUC, PR-AUC, lift
- **C** Calibration — ECE, reliability diagram
- **D** Ranker Quality — IC, decile spread
- **E** Threshold Gates — trade frequency, precision at T*
- **F** Robustness — block bootstrap, permutation null
- **G** Edge vs. Baselines — permutation null + bootstrap CI vs SEPA composite

Each section scores 0–3. Use-case verdicts: `PASS / MARGINAL / REJECT`.

Use cases:
- `composite_gate_plus_rank` — requires A+B+C+D+E+F+G
- `threshold_gate` — requires A+E+G (Section C dropped 2026-05-26; document rationale before next promotion)
- `human_screener` — more relaxed; precision lift at T=0.6/0.7 is the key metric

### Calibration context

Current `m01_prototype_cali/v1` findings:
- ECE: 0.125 (gate requires <0.05 — not met)
- At T=0.6: precision 54.1% (4.68× lift), ~3 candidates/month
- At T=0.7: precision 81.1% (7.02× lift), ~1 candidate/3 months
- Calibration failed E2_trade_frequency gate (2.76 trades/month vs ≥3.0 required)
- **Operational use:** treat as human-in-the-loop screener, not automated executor

### Promotion gate (Phase 4 — not yet implemented)

Target: `ModelRegistry.set_prod()` reads `model_card_built_at` + `model_card_path`; refuses promotion if card REJECTS the requested use case or if card is stale (>7 days old). See [phase_4_promotion_gate_pending.md](../sprint_11/phase_4_promotion_gate_pending.md).

---

## 7. Stage 6 — Strategy Backtesting & Deployment

### SEPA Trade Logic

- **Entry:** SEPA breakout signal (C1–C10 criteria from `t2_screener_features`)
- **Exit:** C1+C2+C6 only (close > SMA150 AND SMA200 AND SMA50). C3/C4/C5/C7/C8 removed (lag price by weeks; not Minervini exit criteria). C8 alone caused 13.9% premature exits.
- **Exit date:** `LEAD(date) OVER (PARTITION BY ticker ORDER BY date)` — first trading day after last C1+C2+C6=True day.
- **C11 fix:** `breakout_ok` uses `vol_avg_50_prev` (ROWS 50 PRECEDING AND 1 PRECEDING) — excludes current bar from denominator.
- **Trade counts:** 36,913 total, ~13K since 2020. Median hold 40d, max 715d.

### Deployment pattern (current)

Model scores SEPA candidates daily via `v_d3_deployment`. Logged to `daily_predictions` table (point-in-time paper-trade record). Human reviews top candidates at P ≥ 0.30 (or P ≥ 0.60 for high-conviction).

No automated execution. Current Mode: **human-in-the-loop screener.**

### Deployment strategies (evaluated)

| Strategy | Description | Status |
|---|---|---|
| S1 | Raw model rank (top-N by score) | Retired — rank not predictive |
| S2 | Hard threshold (P ≥ 0.50) | Tested; too few trades |
| S3 | Calibrated P ≥ 0.30 + 5-position cap | Candidate for prod |
| S4 | Human screener at P ≥ 0.60 / 0.70 | Current operational use |

### Backtest infrastructure

- `run_deep_rigor_suite.py` — Mode A (entry-only ledger) and Mode B (stateful daily SEPA pool)
- Walk-forward engine in `src/evaluation/`
- `daily_predictions` table for live paper-trade tracking

---

## 8. Model Development Lifecycle

The full lifecycle for a new model idea, from hypothesis to deployment:

```
IDEA
 ↓
STEP 1: EDA & Target Selection
 ↓
STEP 2: Feature Selection
 ↓
STEP 3: Model Training
 ↓
STEP 4: Evaluation & Model Card
 ↓
STEP 5: Easy Fixes (if card is MARGINAL)
 ↓
STEP 6: Backtest (if card passes for its designed use case)
 ↓
STEP 7: Deployment
```

### Step 1: EDA & Target Selection

Before choosing a target variable, answer:
- **What is the model trying to do?** Selection (which setup?) vs. Timing (when to act?) vs. Sizing (how much?).
- **What is the base rate?** If the positive class is <5%, binary classification is hard — consider label design.
- **What horizon?** 1d / 5d / 20d / 60d forward return. Avoid overlapping horizons (they correlate and create lookahead bias in walk-forward splits).
- **Is 2-class or 4-class right?** 2-class (hit/miss on MFE threshold) is simpler and backtests cleanly. 4-class (loss/small/medium/large) gives richer signal but fails easily on class imbalance.

Use the EDA dashboard (Page 1) and `d2_training_cache` to profile candidate targets:
```python
df = load_training_data_from_db(use_cache=True)
df['mfe_30pct'] = df['mfe_20d'] > 0.30  # example target
df['mfe_30pct'].value_counts(normalize=True)  # check base rate
```

### Step 2: Feature Selection

Sources:
- `daily_features` (149 columns) — full feature set
- `model_feature_sets` in DuckDB — registered feature groups for M01

Decision criteria:
- **Mutual Information** (non-linear relevance) — run via EDA report
- **Decile IC** — does the feature rank correctly across quantiles?
- **Multicollinearity** — don't include >0.85 correlated pairs (use hierarchical cluster view in dashboard)
- **Phase leakage check** — ensure no feature uses future information. All features in `daily_features` are point-in-time safe.

Model-specific rules:
- `sector` / `industry` — include as XGBoost categoricals
- M03 regime features — include if regime-conditional performance matters
- Fundamental ratios (`pe_ratio` etc.) — currently NOT in `fundamental_features` table; not available

### Step 3: Model Training

Standard path:
```python
from xgboost import XGBClassifier
model = XGBClassifier(
    enable_categorical=True,
    n_estimators=500,
    early_stopping_rounds=50,
    eval_metric='logloss'
)
model.fit(X_train, y_train, eval_set=[(X_val, y_val)])
```

Walk-forward split: use anchored walk-forward (not rolling) to avoid training on future folds.

Register after training:
```python
from src.registry import ModelRegistry
registry = ModelRegistry()
registry.register(model_name='m01_prototype', version='v2', ...)
```

### Step 4: Evaluation & Model Card

Run the full eval suite:
```bash
python scripts/run_deep_rigor_suite.py --model m01_prototype/v2
python scripts/build_model_card.py --model m01_prototype/v2
```

Read the card verdict:
- **PASS** on the target use case → proceed to Step 6 (Backtest)
- **MARGINAL** → Step 5 (Easy Fixes), then re-evaluate
- **REJECT** → go back to Step 1 or Step 2 — the problem is structural

**Do not backtest a REJECT model.** The backtest will look for a strategy that works on bad probabilities and will find one (overfitting).

Key gates (for `threshold_gate` use case):
- A: data integrity ✓
- E2: ≥3.0 trades/month at T* (currently failing for calibrated model at T=0.6)
- G: model beats SEPA composite baseline

### Step 5: Easy Fixes

Only attempt if the card is MARGINAL, not REJECT. Common fixes:
- **Calibration** — try Isotonic regression (`src/evaluation/calibrator.py`). Note: Platt/Isotonic may not fix ECE if the model's score distribution is bimodal.
- **Threshold tuning** — if E2 fails, try a lower T* (but document why and check precision doesn't collapse)
- **Feature pruning** — drop features with negative IC or >0.95 multicollinearity
- **Class weight tuning** — `scale_pos_weight` in XGBoost for imbalanced targets

Re-run full card after each fix. Do not iterate more than 2-3 times on "easy fixes" — if the model still fails, the issue is in Step 1 or Step 2.

### Step 6: Backtest

Only run after the card PASSES for the intended use case.

Mode A (entry-only ledger): each SEPA trade is scored at entry; outcomes tracked by MFE/MAE.
Mode B (stateful daily pool): model re-scores the entire active SEPA pool daily; simulate portfolio-level decisions.

Walk-forward backtest:
```bash
python scripts/run_deep_rigor_suite.py --model m01_prototype/v2 --mode A
```

Interpretation:
- The backtest is a **sanity check**, not an optimization target. A model that passes the card should perform reasonably in the backtest.
- If the backtest fails but the card passed, investigate: regime dependency, position sizing, or look at a Mode B simulation.
- A backtest that outperforms the card's calibration is a red flag — you may be overfitting to the train/test split.

### Step 7: Deployment

Prerequisites:
- Model card built within last 7 days
- Card PASSES (or MARGINAL with documented human sign-off) for the deployed use case
- `models.model_card_path` populated (Phase 4)

```bash
python scripts/build_model_card.py --model m01_prototype/v2 --require-promotion-pass threshold_gate
# If exit 0:
python scripts/set_prod_model.py --model m01_prototype/v2
```

Post-deployment:
- `daily_predictions` table logs every candidate scored each day
- Review top candidates daily: `P ≥ 0.30` for consideration, `P ≥ 0.60` for high conviction
- Monitor calibration drift via PSI report (quarterly)

---

## 9. Running the Daily Pipeline

```bash
# Activate venv first
C:/Users/Hang/PycharmProjects/quantamental/.venv/Scripts/Activate.ps1

# Standard daily run
python scripts/run_daily_pipeline.py --date 2026-06-09

# Dry run (no writes)
python scripts/run_daily_pipeline.py --date 2026-06-09 --dry-run

# Force re-run (ignore idempotency checks)
python scripts/run_daily_pipeline.py --date 2026-06-09 --force
```

### 9-phase orchestrator

| Phase | What | Error mode |
|---|---|---|
| 1 | T1 Ingestion (PARALLEL): price, fundamentals, shares, macro | WARN (per-ticker errors allowed) |
| 2 | Screener membership update | HALT |
| 3 | T2 Screener Features | HALT |
| 4 | T2 Regime Scores | WARN |
| 5 | daily_features Rebuild (TRANSACTIONAL) | HALT |
| 6 | T3 Lazy Materialization | WARN |
| 7 | View Refresh | HALT |
| 8 | Training Cache Refresh + Audits | WARN |
| 9 | Monitoring (log metrics, alerts) | WARN |

Logs: `logs/daily_pipeline.log`

### What to check after a run

1. `logs/daily_pipeline.log` — look for HALT, ERROR
2. Pipeline Health dashboard — heatmap color, freshness panel
3. `data/audit_reports/audit_report_YYYYMMDD.json` — FAIL count
4. `pipeline_error_log` — per-ticker failures in Phase 1

---

## 10. Runbooks

### Runbook: Ticker Deactivation

**When:** consecutive NO_DATA for ≥10 trading days + yfinance confirms no data.

```bash
# 1. Verify with yfinance
python -c "import yfinance as yf; print(yf.Ticker('XYZ').history(period='1mo'))"

# 2. Deactivate (dry run first)
python tools/deactivate_tickers.py --tickers XYZ --reason "no yfinance data 30d"

# 3. Execute
python tools/deactivate_tickers.py --tickers XYZ --reason "no yfinance data 30d" --execute
```

Audit trail: `logs/data_quality/deactivations.jsonl`

### Runbook: macro_data Gap

**When:** Pipeline Health shows `macro_data` stale.

```bash
python -c "
from src.macro_engine import MacroEngine
import duckdb
conn = duckdb.connect('data/market_data.duckdb')
engine = MacroEngine(conn)
engine.update_macro_cache(write_db=True)
"
```

### Runbook: Filing Date Backfill

**When:** large number of `filing_date = NULL` in fundamentals.

```bash
python scripts/backfill_filing_dates_edgar.py --dry-run
python scripts/backfill_filing_dates_edgar.py --execute
```

### Runbook: View Recreation

**When:** schema changes to `daily_features` or `t3_sepa_features`.

```bash
python scripts/create_duckdb_views.py
python scripts/refresh_training_cache.py
python scripts/refresh_training_cache.py --stats  # verify
```

### Runbook: t1_macro Gap Repair

**When:** audit shows `date_gaps_vs_price_data > 0` for `t1_macro`.

1. Identify missing dates: compare `t1_macro` dates vs `price_data` dates.
2. Run `ingest_daily_macro()` for missing dates or insert manually.
3. Recompute T2 for the affected date range: `DELETE WHERE date = d` + re-run Phase 3.
4. Verify: `SELECT COUNT(*) FROM t2_screener_features WHERE date = '...' AND trend_ok = TRUE`.
