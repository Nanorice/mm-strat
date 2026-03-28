# Conceptual Architecture

> Last updated: 2026-03-27 — Backtest wired to DuckDB (`setup_from_duckdb`, `score_from_duckdb`). M01 classifier auto-detected (4-class softprob → expected MFE). `--duckdb` is now the default CLI mode. Legacy parquet path preserved via `--full`/`--run`.

# Daily Pipeline

```
Phase 1 (price/fund/shares/macro) ──CRITICAL──▶ Phase 2 (screener members)
│ -> price_data                                  │ -> screener_membership
│   fundamentals                                 │   [criteria from screener_criteria_versions]
│   shares_outstanding                           │
│   macro_data                    ┌──────────────┴──────────────┐
│                                 ▼                              ▼
│                         Phase 3 (T2 features)         Phase 4 (regime) [non-crit]
│                         -> t2_screener_features       -> t2_regime_scores
│                         [OHLCV, SMAs, EMAs,            [M03 pillars, deltas]
│                          XS alphas, ranks]
│                                 │
│                         Phase 5 (T3 SEPA features) ──CRITICAL
│                         -> t3_sepa_features
│                         [carry-forward T2 + TS alphas + M03 join]
│                                 │
│                         Phase 6 (views) [non-crit]
│                         -> SQL views
│                         [v_d1 = sessions/trades, v_d2 = hydrate + outcomes]
│                                 │
│                         Phase 7 (training cache) [non-crit]
│                         -> d2_training_cache
│                                 │
│                         Phase 8 (monitoring) [always]
│                         -> logs / alerts only
```

**CLI (daily runner):**
```bash
python scripts/run_daily_pipeline.py                    # Full pipeline (yesterday)
python scripts/run_daily_pipeline.py --date 2024-01-15  # Specific date
python scripts/run_daily_pipeline.py --phase-1-only     # T1 ingestion only
python scripts/run_daily_pipeline.py --phase-2-only     # Screener membership only
python scripts/run_daily_pipeline.py --phase-3-only     # T2 features incremental
python scripts/run_daily_pipeline.py --phase-4-only     # Regime scores incremental
python scripts/run_daily_pipeline.py --phase-5-only     # T3 SEPA features incremental
python scripts/run_daily_pipeline.py --force            # Ignore idempotency
python scripts/run_daily_pipeline.py --dry-run          # Validate only
```

---

## Phase Map

### Phase 1 — T1 Ingestion & Maintenance *(CRITICAL)*

**Purpose**: Fetch raw data from external sources into DuckDB.

**Input**: Active tickers from `company_profiles`, external APIs (yfinance, FMP, FRED).

**Process**:
| Step | Updates | Source |
|------|---------|--------|
| 1.1 Price | `price_data` | yfinance (stale tickers only) |
| 1.2 Fundamentals | `fundamentals`, `earnings_calendar` | yfinance (due tickers only) |
| 1.3 Shares | `shares_outstanding` | yfinance (7-day staleness check) |
| 1.4 Macro | `macro_data`, `t1_macro` | FRED + VIX + SPY/QQQ OHLCV |

**Output**: Raw OHLCV, fundamentals, shares, macro data in DuckDB.

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/data_engine.py` | Price ingestion (`DataRepository`) |
| `src/fundamental_engine.py` | Fundamentals + earnings calendar |
| `src/shares_engine.py` | Shares outstanding |
| `src/macro_engine.py` | Macro indicators + SPY/QQQ |
| `src/universe_backfill.py` | Historical backfill + FMP discovery |
| `scripts/run_universe_backfill.py` | CLI for backfill + universe management |
| `scripts/backfill_fundamentals.py` | FMP fundamentals backfill |
| `tools/audit_t1_data_quality.py` | T1 data quality audit |
| `tools/purge_t1_price_negatives.py` | Remove bad price rows |
| `tools/deactivate_tickers.py` | Retire delisted tickers |
| `tools/purge_junk_tickers.py` | Remove warrants/SPACs/units |
| `tools/rename_tickers.py` | Cross-table ticker rename |

**Backfill:**
```bash
python scripts/run_universe_backfill.py --discover-fmp
python scripts/run_universe_backfill.py --backfill-prices --start-date 2000-01-01
python scripts/run_universe_backfill.py --backfill-shares
python scripts/backfill_fundamentals.py --source fmp --overwrite
```

**Audit:** `python tools/audit_t1_data_quality.py`

---

### Phase 2 — Screener Membership *(CRITICAL)*

**Purpose**: Determine which tickers qualify for the investable universe (point-in-time correct).

**Input**: `price_data`, `shares_outstanding`, `screener_criteria_versions`.

**Process**: Evaluate criteria (v2: close >= $5, avg_volume_20d >= 100K, market_cap >= $150M) for each ticker on target date. Log entry/exit events with 126-day grace period before exit.

**Output**: `screener_membership` — append-only event log (one row per status change per ticker).

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/managers/screener_manager.py` | `ScreenerManager.evaluate_and_log()` |
| `scripts/backfill_screener_membership.py` | Full history backfill (~10s) |
| `tools/audit_t2_membership.py` | Membership audit |

**Backfill:** `python scripts/backfill_screener_membership.py [--reset]`

**Audit:** `python tools/audit_t2_membership.py`

---

### Phase 3 — T2 Screener Features *(CRITICAL)*

**Purpose**: Compute features for the full investable universe. This is the broadest feature table — every active screener ticker gets a row per trading day.

**Input**: `price_data`, `screener_membership` (point-in-time join), `t1_macro` (SPY benchmark).

**Process** (4 sub-phases):
| Sub-phase | Method | What |
|-----------|--------|------|
| A — SQL | CTE chain in `compute_t2_screener_features()` | OHLCV carry-through, SMAs (20/50/150/200), RS line + rating, 52w/20d ranges, volume ratios, ATR, NATR, VCP, volatility, SEPA flags (`trend_ok`, `breakout_ok`) |
| B — Python (alphas) | `compute_alpha_features()` | 9 XS alphas (alpha001–alpha060) via multiprocessing. Must run on full ~2400-ticker population for valid cross-sectional ranks. |
| B-EMA — Python | `compute_ema_features()` | 5 EMAs (8, 21, 50, 100, 200) via `pandas.ewm()`. Recursive — cannot be computed in SQL. |
| C — SQL | `compute_cross_sectional_ranks()` | 7 rank columns: RS_Universe_Rank, RS_Sector_Rank, RS_vs_Sector, Sector_Momentum, RS_Industry_Rank, RS_vs_Industry, Industry_Momentum |

**Output**: `t2_screener_features` (~2400 tickers/day, ~70 columns including OHLCV + EMAs + alphas + ranks).

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/feature_pipeline.py` | `FeaturePipeline.compute_t2_screener_features()` |
| `tools/audit_t2_screener_features.py` | T2 feature audit |

**Incremental:** `python scripts/run_daily_pipeline.py --phase-3-only` (detects gap from `MAX(date)` to last trading day)

**Audit:** `python tools/audit_t2_screener_features.py`

---

### Phase 4 — T2 Regime Scores *(non-critical)*

**Purpose**: Compute M03 market regime scores (macro/breadth context, one row per date).

**Input**: `macro_data`, `price_data`.

**Process**: `M03RegimeCalculator.calculate_history_vectorized()` — computes trend/liquidity/risk pillars, 5d/20d deltas, regime volatility.

**Output**: `t2_regime_scores` — columns: `date, m03_score, m03_pillar_trend, m03_pillar_liq, m03_pillar_risk, m03_delta_5d, m03_delta_20d, m03_regime_vol`.

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/regime_pipeline.py` | `RegimePipeline` (CLI + programmatic) |
| `src/pipeline/m03_regime.py` | `M03RegimeCalculator` |

**Incremental:** `python scripts/run_daily_pipeline.py --phase-4-only` (auto-detects gap)

**Backfill:** `python src/regime_pipeline.py --backfill [--start 2020-01-01]`

---

### Phase 5 — T3 SEPA Features *(CRITICAL)*

**Purpose**: Materialize the full feature set for SEPA breakout candidates only. This is the single source of truth for all downstream ML and views.

**Input**: `t2_screener_features` (SEPA filter + carry-forward), `price_data` (per-ticker rolling windows), `t2_regime_scores` (M03 join).

**Process** (2 sub-phases):
| Sub-phase | What |
|-----------|------|
| A — SQL INSERT OR IGNORE | Filters T2 to `trend_ok AND breakout_ok` candidates. Carries forward all T2 columns (OHLCV, SMAs, EMAs, RS, XS alphas, ranks). Computes per-ticker window features: momentum (21/63/126/189/252d), RSI-14, ATR-14, volume depth, velocity features, pattern flags, pct_chg deltas, sma_50_slope, rs_line_lag_delta. Joins M03 regime scores by date. |
| B — Python UPDATE | 9 TS alphas (alpha006–alpha101) via multiprocessing. Warmup loaded from `t2_screener_features` (broader population) for continuous rolling windows. |

**Output**: `t3_sepa_features` (~13–100 rows/day, ~133 columns). Keyed by `(ticker, date, feature_version)`.

**Key design notes**:
- T3 only stores rows where `trend_ok AND breakout_ok` — these flags are NOT stored in T3 (implicit TRUE for all rows).
- Session detection (trend_ok transitions) is done by views joining back to T2.
- `dist_from_52w_high_pct_chg` / `dist_from_20d_high_pct_chg`: uses `CASE WHEN cur = prev THEN 0` to handle zero-denominator (breakout stocks at highs).

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/feature_pipeline.py` | `FeaturePipeline.compute_t3_features()` |
| `scripts/create_t3_schema.py` | Standalone schema creation |
| `tools/audit_t3_sepa_features.py` | T3 feature audit (coverage, versions, nulls, referential integrity) |

**Incremental:** `python scripts/run_daily_pipeline.py --phase-5-only` (detects gap from `MAX(date)` to last trading day)

**Backfill:**
```bash
# Full rebuild (drops and recreates — skip T2 if already populated)
python -c "
from src.feature_pipeline import FeaturePipeline
fp = FeaturePipeline(db_path='data/market_data.duckdb')
fp.compute_all(start_date='2020-01-01', skip_t2=True, recreate_t3=True)
"
```

**Audit:** `python tools/audit_t3_sepa_features.py`

---

### Phase 6 — View Refresh *(non-critical)*

**Purpose**: Recreate SQL views that transform T3 features into trade-level training data.

**Input**: `t3_sepa_features`, `price_data`, `fundamentals`, `company_profiles`.

**Process**: The view chain progressively transforms daily SEPA observations into trade-level rows with outcomes:

| View | Row represents | Key logic |
|------|---------------|-----------|
| `v_sepa_candidates` | 1 day per ticker (while in trend) | All T3 rows (SEPA candidates by definition) |
| `v_d1_candidates` | **1 trade** (session) | Detects `trend_ok` transitions in **T2** → sessions. Entry = first `breakout_ok` day. Exit = last `trend_ok` day. Features from T3. |
| `v_d1_trades` | Alias for `v_d1_candidates` | |
| `v_d2_features` | 1 trade + fundamentals | Point-in-time PE/PS/PB/margins join |
| `v_d2_hydrated` | **N days per trade** | Expands entry→exit to daily rows. Adds adaptive stop-loss (`max(-15%, -2×ATR)`), `sl_hit` flag |
| `v_d2r_hydrated` | Alias for `v_d2_hydrated` | |
| `v_d2_training` | **1 trade + outcomes** | Aggregates hydrated days → MAE, MFE, SL date/price, holding days, return. Adds 39 log-transforms. **This is the training dataset.** |
| `v_d3_deployment` | Last 252 days of SEPA candidates | For model scoring |
| `v_screener_dashboard` | **1 trade** (session) | Entry date, entry price, current close, pct_return, company name/sector/industry/market_cap, ACTIVE/EXITED status |

**Output**: 9 production views + 2 backward-compat aliases + 1 materialised table.

**Materialised tables:**
| Table | Source | Rows | Refresh |
|-------|--------|------|---------|
| `screener_watchlist` | `v_screener_dashboard` | ~42K (all trades ever) | ~7s via `CREATE OR REPLACE TABLE` in `create_all()` |
| `d2_training_cache` | `v_d2_training` | ~15K | ~7s via `refresh_cache()` |

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/managers/view_manager.py` | `ViewManager.create_all()` (views + screener_watchlist) |
| `scripts/create_duckdb_views.py` | Standalone CLI for view recreation |
| `scripts/show_screener.py` | CLI table of active SEPA trades (reads `screener_watchlist`) |
| `notebooks/screener_dashboard_snippet.py` | Notebook snippet (3 cells: active trades, watchlist, recent exits) |

**Manual recreation:** `python scripts/create_duckdb_views.py`

**Screener dashboard:**
```bash
python scripts/show_screener.py                    # Active trades (default: sort by entry_date)
python scripts/show_screener.py --sort pct_return  # Sort by return
python scripts/show_screener.py --sort ticker      # Alphabetical
```

**Notebook (DataWrangler):** Open `notebooks/screener_dashboard_snippet.py` and run cells:
- Cell 1: Active trades — breakout triggered, session still open
- Cell 2: Watchlist — tickers in SEPA trend template, no breakout yet (candidates to watch)
- Cell 3: Recent exits — trades that exited in last 30 days, with return since entry

---

### Phase 7 — Training Cache Refresh *(non-critical)*

**Purpose**: Materialize `v_d2_training` into `d2_training_cache` for fast ML training loads (70x speedup).

**Input**: `v_d2_training`.

**Output**: `d2_training_cache` table.

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/managers/view_manager.py` | `ViewManager.refresh_cache()` |
| `scripts/refresh_training_cache.py` | CLI (`--stats` for age/rows) |

---

### Phase 8 — Monitoring *(always runs)*

**Purpose**: Log health metrics and fire alerts on anomalies.

**Input**: `run_stats` from phases 1–7, `pipeline_runs` table.

**Output**: Log entries + alert messages only (no DB writes).

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/managers/pipeline_run_manager.py` | `PipelineRunManager` (tracking + health reports) |
| `config.py` | `PIPELINE_FAILURE_MODES`, `PIPELINE_ALERT_THRESHOLDS` |

---

## Key Tables

| Table | Phase | Rows | Purpose |
|-------|-------|------|---------|
| `price_data` | 1.1 | ~12M | OHLCV history (equity only; SPY/QQQ in `t1_macro`) |
| `fundamentals` | 1.2 | ~300K | IS/BS/CF quarterly, keyed `(ticker, period_end)` |
| `earnings_calendar` | 1.2 | ~20K | Upcoming/past earnings dates |
| `shares_outstanding` | 1.3 | ~2M | Historical shares |
| `macro_data` | 1.4 | ~40K | FRED + VIX indicators |
| `t1_macro` | 1.4 | ~7K | SPY/QQQ OHLCV + VIX (benchmark source) |
| `screener_membership` | 2 | ~20K | Event log — one row per entry/exit per ticker |
| `t2_screener_features` | 3 | ~9.6M | Full universe: OHLCV, SMAs, EMAs, RS, alphas, ranks, SEPA flags |
| `t2_regime_scores` | 4 | ~1.5K | One row per date: M03 score + pillars + deltas |
| `t3_sepa_features` | 5 | ~41K | SEPA candidates only: 133 cols, single ML source of truth |
| `screener_watchlist` | 6 | ~42K | Materialized `v_screener_dashboard` (all trades, ACTIVE/EXITED, with returns) |
| `d2_training_cache` | 7 | varies | Materialized `v_d2_training` (trade-level with outcomes) |
| `pipeline_runs` | 8 | varies | Phase execution tracking + idempotency |

---

## Model Registry

**Table**: `models` in DuckDB. Tracks model versions, specs, metrics, and artifact paths.

| Column | Type | Purpose |
|--------|------|---------|
| `version_id` | VARCHAR PK | Unique ID (e.g., `M01_baseline_20260315_133129`) |
| `status_flag` | VARCHAR | `test` / `prod` / `archived` |
| `specs_json` | JSON | Features list, hyperparameters, training config |
| `feature_version` | VARCHAR | Feature schema (e.g., `v3.1`) |
| `training_date` | DATE | When the model was trained |
| `dataset_rows` | INTEGER | Training set size |
| `artifacts_path` | VARCHAR | Path to model files on disk |
| `rmse`, `mae`, `r2`, `spearman_corr` | FLOAT | Evaluation metrics |

**Current production model**: `M01_baseline_20260315_133129` (status=`test`, not yet promoted)

**Artifact layout**:
```
models/artifacts/M01_baseline_20260315_133129/
    model.json              # XGBoost booster (509 KB)
    metadata.json           # Training config, feature list, metrics, leakage audit
    evaluation/
        results.json        # Accuracy, F1, confusion matrix
        confusion_matrix.png
        feature_importance.png
        roc_curves.png
        pr_curves.png
        calibration_curves.png
        class_distribution.png
        report_*.md
```

**Working copy**: `models/m01_baseline/v1/` (same content, used during development)

**Toolkit:**
| File | Purpose |
|------|---------|
| `src/model_registry.py` | `ModelRegistry` class — CRUD for `models` table |
| `src/evaluation/base_evaluator.py` | Base evaluator (auto-registers via `ModelRegistry`) |
| `src/evaluation/classification_evaluator.py` | `ClassificationEvaluator` — confusion matrix, ROC, SHAP |

**CLI:**
```python
from src.model_registry import ModelRegistry
reg = ModelRegistry()
reg.list_versions()                    # Show all registered models
reg.set_prod('M01_baseline_...')       # Promote to production
reg.get_model_specs('M01_baseline_...')  # Load feature list + hyperparams
```

---

## Model Training

**Purpose**: Train M01 MFE classifier on `v_d2_training` data. Not part of the daily pipeline — run periodically or after significant feature changes.

**Current model**: M01 — 4-class XGBoost MFE (Maximum Favorable Excursion) classifier.
- Classes: 0=Noise (0-2%), 1=Moderate (2-10%), 2=Strong (10-30%), 3=Home Run (>30%)
- Features: 105 (8 groups: Moving Averages, Momentum/RS, Volume, Volatility, Oscillators, Fundamentals, Alphas, M03 Regime)
- Baseline metrics: accuracy=67%, weighted_F1=0.58, macro_F1=0.25 (class imbalance)

**Data flow**:
```
v_d2_training (or d2_training_cache)
    → temporal split (train / val / test, chronological)
    → XGBoost multi:softprob, balanced class weights
    → ClassificationEvaluator (artifacts + plots)
    → ModelRegistry.register_version()
    → models/artifacts/<version_id>/
```

**Toolkit:**
| File | Purpose |
|------|---------|
| `scripts/train_mfe_classifier.py` | Training script (~500 lines). Reads `v_d2_training`, trains, evaluates, registers. |
| `src/evaluation/classification_evaluator.py` | Reusable evaluator (confusion matrix, ROC/PR, SHAP, feature importance) |
| `src/evaluation/leakage_guard.py` | Temporal leakage validation |

**CLI:**
```bash
python scripts/train_mfe_classifier.py    # Train baseline, auto-registers in models table
```

**Status**: ⚠️ Functional but needs work
- [ ] **Class imbalance** — macro_F1=0.25 indicates poor minority class prediction. Needs SMOTE / threshold tuning / cost-sensitive learning.
- [ ] **Retrain on updated T3 data** — current model trained on 2026-03-15 data. T3 was rebuilt on 2026-03-27.
- [ ] **Promote to prod** — currently `status=test`. Run `reg.set_prod(version_id)` after validation.

---

## Backtesting

**Purpose**: Simulate the SEPA strategy historically using BackTrader. Not part of the daily pipeline — run on-demand to validate model/strategy changes.

**Strategy**: `SEPAHybridV1` — M01 score-based selection + M03 regime gating + 3-tranche exit with trailing stops.

**Data flow (DuckDB — default)**:
```
d2_training_cache                   → UniverseScorer.score_from_duckdb() → M01 scoring (vectorized)
t2_regime_scores                    → regime feed (regime_cat 0-4 from m03_score thresholds)
price_data                          → OHLCV feeds + inline ATR-14
    → SEPABacktestRunner.setup_from_duckdb() + run()
    → report + equity curve + trade log
```

**Data flow (legacy parquet — `--full` / `--run`)**:
```
prepare_regime_feed()     → data/backtest/m03_feed.parquet
UniverseScorer.score()    → data/backtest/universe_scores.parquet    ← reads data/ml/d2.parquet
prepare_price_feeds()     → data/backtest/prices/*.parquet
    → SEPABacktestRunner.setup() + run()
    → report + equity curve + trade log
```

**Toolkit:**
| File | Purpose |
|------|---------|
| `scripts/run_backtest.py` | CLI entrypoint (`--duckdb` default, `--full`/`--run` legacy) |
| `src/backtest/runner.py` | `SEPABacktestRunner` — `setup_from_duckdb()` (DuckDB) or `setup()` (parquet) |
| `src/backtest/sepa_strategy.py` | `SEPAHybridV1` — BackTrader strategy (entry/exit/position sizing) |
| `src/backtest/universe_scorer.py` | `UniverseScorer` — `score_from_duckdb()` (DuckDB) or `score_universe()` (parquet) |
| `src/backtest/score_lookup.py` | `ScoreLookup` — in-memory O(1) daily candidate filtering |
| `src/backtest/position_tracker.py` | `PositionTracker` — read-model position tracking (3-tranche exits) |
| `src/backtest/report.py` | Post-backtest markdown report generation |
| `src/backtest/analyzers.py` | Custom BackTrader analyzers (CalmarRatio) |
| `src/backtest/feeds.py` | `SEPAStockFeed`, `M03RegimeFeed` — BackTrader feed classes |
| `src/backtest/price_feed.py` | Legacy parquet-based price feed (used by `--full`/`--run`) |
| `src/backtest/duckdb_feed.py` | `DuckDBCandidateFeed` — standalone feed class (not used by runner) |

**CLI:**
```bash
python scripts/run_backtest.py                                 # DuckDB mode (default)
python scripts/run_backtest.py --duckdb --model m01_baseline/v1 # Explicit model
python scripts/run_backtest.py --duckdb --max-tickers 50       # Quick test
python scripts/run_backtest.py --duckdb --start 2021-01-01 --end 2023-12-31
python scripts/run_backtest.py --full                          # Legacy: prepare parquet + run
python scripts/run_backtest.py --prepare-data                  # Legacy: prepare parquet only
python scripts/run_backtest.py --run                           # Legacy: run from prepared parquets
```

**Status**: ✅ DuckDB-native (2026-03-27)
- [x] Runner reads regime from `t2_regime_scores`, prices from `price_data`, scores from `d2_training_cache`
- [x] `UniverseScorer.score_from_duckdb()` scores directly from `d2_training_cache`
- [x] M01 classifier auto-detected (4-class softprob → expected MFE scoring)
- [x] `--model` flag selects model variant (reads metadata.json for feature list)
- [x] Legacy parquet path preserved via `--full` / `--run`

---

## Open TODOs

### Model Development (blocking backtests from being meaningful)
- [ ] **Retrain M01 on updated T3 data** — current model trained on 2026-03-15. T3 was rebuilt 2026-03-27 with 0% NULL alphas/EMAs. Retrain + compare metrics.
- [ ] **Class imbalance** — macro_F1=0.25. Try SMOTE, cost-sensitive learning, or threshold tuning.
- [ ] **Promote to prod** — currently `status=test`. Run `reg.set_prod(version_id)` after validation backtest.
- [ ] **Full backtest** — run `--duckdb` on full date range (2020-2026) with all tickers to establish baseline.

### Data Quality (non-blocking but should fix)
- [ ] **`filing_date` NULL gap** — historical fundamentals rows pre-yfinance migration have no `filing_date`
- [ ] **`log_alpha008`, `log_alpha019` in `v_d2_training`** — not yet log-transformed or added to M01_FEATURES
- [ ] **`rename_tickers.py`** — still references dropped `daily_features`. Update to `t3_sepa_features` + `t2_screener_features`.

### Cleanup (low priority)
- [ ] **`screener_members` view** — drop once all joins migrated to `screener_membership`
- [ ] **Monthly earnings calendar refresh trigger** — where to persist last-refresh timestamp
- [ ] **Delete `duckdb_feed.py`** — `DuckDBCandidateFeed` class is unused now that runner uses `SEPAStockFeed` directly. Keep or delete.

## Resolved

- ~~Backtest parquet dependency~~ → DuckDB-native (2026-03-27). `setup_from_duckdb()` reads `t2_regime_scores` + `price_data` + `d2_training_cache`. No parquet prep step needed.
- ~~Universe discovery~~ → `--discover-fmp` via `UniverseBackfillEngine`
- ~~Historical fundamentals backfill~~ → FMP backfill complete (297K rows)
- ~~Blacklist / SPAC contamination~~ → `ticker_blacklist` table
- ~~`daily_features` table~~ → **DROPPED** (2026-03-24). T2 + T3 replace it.
- ~~T2 missing OHLCV~~ → Added 2026-03-26. OHLCV now stored directly + backfilled.
- ~~T2 missing EMAs~~ → Added 2026-03-26. EMA 8/21/50/100/200 via pandas ewm.
- ~~No T3 audit~~ → `tools/audit_t3_sepa_features.py` created 2026-03-26.
- ~~No Phase 3/4 incremental CLI~~ → `--phase-3-only`, `--phase-4-only` added 2026-03-26.
- ~~T3 full rebuild needed~~ → Rebuilt from T2 (2026-03-27). 41K rows, 0% NULL on XS alphas/EMAs. `rs_line_lag_delta` added.
- ~~T3 views referencing `trend_ok`~~ → Views now use T2 for session detection, T3 for features (2026-03-27).
- ~~No Phase 5 incremental CLI~~ → `--phase-5-only` added 2026-03-27.
- ~~`dist_from_52w_high_pct_chg` 41% NULL~~ → Zero-denominator fix (2026-03-27). Breakout stocks at 52w high: `0→0 = 0%` not NULL.
- ~~Model registry stale entries~~ → Cleaned up (2026-03-27). Removed `M04_baseline`, `M01_test_v1`. Canonical: `M01_baseline_20260315_133129`. Artifacts path fixed.
- ~~`screener_watchlist` materialisation~~ → Added (2026-03-27). `CREATE OR REPLACE TABLE` from `v_screener_dashboard`, ~42K rows, refreshed in Phase 6.
