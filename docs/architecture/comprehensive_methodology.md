# Comprehensive Methodological Guide to the Quantamental SEPA Framework

> Last updated: 2026-06-21 — Prefect scheduling (ITX ops box). Authoritative reference for replication. Cross-checked against `docs/manual_for_me.md`.

---

## Table of Contents

1. [Abstract & Introduction](#1-abstract--introduction)
2. [System Architecture & Pipeline Mapping](#2-system-architecture--pipeline-mapping)
3. [Data Engineering & Universe Construction](#3-data-engineering--universe-construction)
4. [Feature Engineering](#4-feature-engineering)
5. [Market Regime Context (M03)](#5-market-regime-context-m03)
6. [SEPA Session Management](#6-sepa-session-management)
7. [Machine Learning Methodology](#7-machine-learning-methodology)
8. [Model Evaluation & Validation](#8-model-evaluation--validation)
9. [Backtesting & Trade Simulation](#9-backtesting--trade-simulation)
10. [Production Pipeline & Operations](#10-production-pipeline--operations)
11. [Audit System](#11-audit-system)
12. [Ticker Lifecycle Management](#12-ticker-lifecycle-management)
13. [Helper Libraries](#13-helper-libraries)
14. [Replication Guide](#14-replication-guide)
15. [Known Tech Debt & Future Work](#15-known-tech-debt--future-work)

---

## 1. Abstract & Introduction

### Executive Summary

This document is a complete technical specification of the Quantamental SEPA Framework — an end-to-end pipeline for ingesting, processing, and systematically trading equity "super performers" according to the Specific Entry Point Analysis (SEPA) methodology. It is intended to be sufficient for a reader to fully replicate the system from scratch.

The architecture is a sequential daily pipeline divided into eight phases: raw data ingestion (T1), universe screening (screener membership), broad technical feature computation (T2), market regime scoring (M03), SEPA session gating (sepa_watchlist), dense SEPA-universe feature computation (T3), SQL view construction, and training cache materialisation. A 4-class XGBoost classifier (M01) scores breakout candidates by Maximum Favorable Excursion (MFE) probability. A BackTrader simulation engine (M03-regime-gated, 3-tranche exits) validates the strategy historically.

*Note: While the data engineering and predictive scoring pipelines are fully operational, the formal trading specification is still in development. Execution logic exists exclusively within the backtesting simulation environment (`src/backtest/sepa_strategy.py`).*

### Theoretical Framework

The SEPA methodology, systematised by Mark Minervini, identifies high-growth equities exhibiting strict fundamental acceleration and technical momentum. The core insight is that a small subset of equities (super-performers) account for a disproportionate share of total market returns, and that these equities share identifiable structural characteristics in both their fundamentals and price action immediately before and during their major advances.

This project transitions SEPA from a discretionary strategy into a fully quantitative framework. The advantages are: elimination of behavioral bias, rapid hypothesis testing across thousands of equities simultaneously, and rigorous historical backtesting with reproducible results.

---

## 2. System Architecture & Pipeline Mapping

The system is orchestrated as a sequential daily pipeline. Each phase has defined inputs, outputs, criticality, and failure modes.

```
Phase 1 (price/fund/shares/macro) ──CRITICAL──▶ Phase 2 (screener membership)
│ -> price_data                                  │ -> screener_membership
│   fundamentals                                 │   [criteria from screener_criteria_versions]
│   shares_history                               │
│   macro_data / t1_macro         ┌──────────────┴──────────────┐
│                                 ▼                              ▼
│                         Phase 3 (T2 features)         Phase 4 (regime) [non-crit]
│                         -> t2_screener_features       -> t2_regime_scores
│                         [OHLCV, SMAs, EMAs,            [M03 pillars, deltas]
│                          XS alphas, ranks,
│                          trend_ok, breakout_ok]
│                                 │
│                         Phase 4b (sepa_watchlist) ──CRITICAL
│                         -> sepa_watchlist
│                         [open/close SEPA sessions; T3 universe gate]
│                                 │
│                         Phase 5 (T3 SEPA features) ──CRITICAL
│                         -> t3_sepa_features
│                         [filtered by sepa_watchlist universe;
│                          carry-forward T2 + TS alphas + M03 join]
│                                 │
│                         Phase 6 (views) [non-crit]
│                         -> SQL views
│                         [v_d1_candidates, v_d2_features,
│                          v_d2_training, v_d3_deployment, ...]
│                                 │
│                         Phase 7 (training cache) [non-crit]
│                         -> d2_training_cache
│                                 │
│                         Phase 8 (monitoring) [always]
│                         -> logs / alerts only
```

### Phase Summary Table

| Phase | Module | Input | Output Table | Criticality |
|-------|--------|-------|--------------|-------------|
| 1.1 Price | `src/data_engine.py` | yfinance API, `company_profiles` | `price_data` | CRITICAL |
| 1.2 Fundamentals | `src/fundamental_engine.py` | yfinance API, SEC EDGAR | `fundamentals`, `earnings_calendar` | CRITICAL |
| 1.2b CIK map | `src/edgar_engine.py` | SEC directory (weekly, gated) | `cik_map` | non-critical |
| 1.2c Filing dates | `src/edgar_engine.py` | SEC submissions API (200/run) | `fundamentals.filing_date` | non-critical |
| 1.3 Shares | `src/shares_engine.py` | yfinance API | `shares_history` | CRITICAL |
| 1.4 Macro | `src/macro_engine.py` | FRED API, yfinance | `macro_data` AND `t1_macro` | CRITICAL |
| 2 Screener | `src/managers/screener_manager.py` | `price_data`, `shares_history`, `screener_criteria_versions` | `screener_membership` | CRITICAL |
| 3 T2 Features | `src/feature_pipeline.py` | `price_data`, `screener_membership`, `t1_macro` | `t2_screener_features` | CRITICAL |
| 4 Regime | `src/pipeline/m03_regime.py` | `macro_data`, `price_data` | `t2_regime_scores` | non-critical |
| 4b SEPA Gate | `src/managers/sepa_watchlist_manager.py` | `t2_screener_features` | `sepa_watchlist` | CRITICAL |
| 5 T3 Features | `src/feature_pipeline.py` | `t2_screener_features`, `sepa_watchlist`, `t2_regime_scores` | `t3_sepa_features` | CRITICAL |
| 6 Views | `src/managers/view_manager.py` | `t3_sepa_features`, `fundamentals`, `company_profiles` | SQL views + `screener_watchlist` | non-critical |
| 7 ML Cache | `src/managers/view_manager.py` | `v_d2_training` | `d2_training_cache` | non-critical |
| 7.5 Slim DB | `scripts/build_dashboard_db.py` | main DB | `data/dashboard.duckdb` | non-critical |
| 8 Monitoring + Audits | `src/orchestrators/daily_pipeline_orchestrator.py`, `tools/run_all_audits.py` | all tables | logs/alerts + `data/audit_reports/` | always |
| 10 Model Card | `scripts/build_model_card.py` | prod model + `d2_training_cache` | `model_cards/<version>.html` | WARN only |

### Key Tables Reference

| Table | Phase | Approx Rows | Purpose |
|-------|-------|-------------|---------|
| `price_data` | 1.1 | ~12M | OHLCV history (equity only; SPY/QQQ in `t1_macro`) |
| `fundamentals` | 1.2 | ~300K | IS/BS/CF quarterly, keyed `(ticker, period_end)` |
| `earnings_calendar` | 1.2 | ~20K | Upcoming/past earnings dates |
| `shares_history` | 1.3 | ~2M | Historical shares outstanding |
| `macro_data` | 1.4 | ~40K | FRED + VIX indicators |
| `t1_macro` | 1.4 | ~7K | SPY/QQQ OHLCV + VIX (benchmark source for T2) |
| `company_profiles` | seed | ~3K | Universe seed: ticker, name, sector, industry, is_active, delisting_date |
| `ticker_blacklist` | maintenance | ~200 | Permanent record of purged non-tradeable tickers |
| `screener_criteria_versions` | 2 | ~5 | Historical criteria parameter sets (v1, v2, …) |
| `screener_membership` | 2 | ~20K | Append-only event log — one row per entry/exit per ticker |
| `t2_screener_features` | 3 | ~9.6M | Full universe: OHLCV, SMAs, EMAs, RS, alphas, ranks, SEPA flags |
| `t2_regime_scores` | 4 | ~1.5K | One row per date: M03 score + pillars + deltas |
| `sepa_watchlist` | 4b | ~35K | Event log — one row per SEPA session per ticker. T3 universe gate. |
| `t3_sepa_features` | 5 | ~9.4M | sepa_watchlist universe, full history, 144 columns. Single ML source of truth. |
| `screener_watchlist` | 6 | ~38K | Materialised `v_screener_dashboard` (all trades, ACTIVE/EXITED, with returns) |
| `d2_training_cache` | 7 | ~38K | Materialised `v_d2_training` (trade-level with MFE/MAE outcomes) |
| `pipeline_runs` | 8 | varies | Phase execution tracking + idempotency |
| `models` | ML | varies | Model registry — versions, metrics, artifact paths |

---

## 3. Data Engineering & Universe Construction

### 3.1 Data Sources

| Source | Data | Module |
|--------|------|--------|
| **yfinance** | Daily OHLCV (equities), shares outstanding, SPY/QQQ/VIX | `data_engine.py`, `shares_engine.py`, `macro_engine.py` |
| **Financial Modeling Prep (FMP)** | Quarterly IS/BS/CF, universe discovery | `fundamental_engine.py`, `universe_backfill.py` |
| **SEC EDGAR** | Authoritative 10-Q/10-K filing dates via submissions API; CIK map | `src/edgar_engine.py` (`EDGARClient` + `EDGAREngine`) |
| **FRED** | Macroeconomic rates and indicators | `macro_engine.py` |

**EDGAR engine** (`src/edgar_engine.py`): primary source for `fundamentals.filing_date`. Queries `data.sec.gov/submissions/CIK*.json` at 10 req/s. Maintains `cik_map` table (10.4K ticker→CIK rows). Daily pipeline runs a bounded backfill (200 tickers/run) via `phase_1_filing_date_backfill`; weekly `phase_1_cik_map_refresh` refreshes the CIK map from the SEC directory. Filing-date coverage: **97.73%** (up from 42.9% before the EDGAR engine). Residual NULLs: fiscal-calendar mismatches >35d tolerance, foreign filers with no CIK.

**Instrument classification**: `EDGAREngine.classify_ticker_types` maps EDGAR form types to `ticker_type` (`EQUITY`/`FOREIGN`/`FUND`/`ETF`/`INDEX`). Only `EQUITY` tickers run through the fundamentals fetch and staleness checks. Run `scripts/enrich_ticker_types_edgar.py` to reclassify a cohort.

### 3.2 Universe Construction — Screener Membership (Phase 2)

The `screener_membership` table is an **append-only event log** that tracks when each ticker enters or exits the investable universe. It uses a gaps-and-islands SQL pattern in `src/managers/screener_manager.py`.

**Criteria (v2, effective 2020-01-01):**
- `Close Price >= $5`
- `20-Day Average Volume >= 100,000 shares`
- `Market Capitalisation >= $150M`

**Grace Period**: A ticker failing criteria is not immediately ejected. The pipeline grants a **126 consecutive calendar-day grace period** before emitting an exit event. This prevents flickering memberships during temporary market downturns.

**Output schema** (`screener_membership`): one row per status change per ticker. Key columns: `ticker`, `effective_date`, `is_member` (TRUE=entry, FALSE=exit), `consec_fail_days` (must be 126 on exit, 0 on entry), `market_cap`, `criteria_version`.

The criteria parameter history is stored in `screener_criteria_versions` — enabling point-in-time correct replay of past universe composition.

### 3.3 Data Integrity & Ticker Lifecycle

Survivorship bias is mitigated via a structured ticker lifecycle system (see §12 for full CLI reference):

- **Deactivations**: Delisted or acquired tickers are flagged `is_active = FALSE` in `company_profiles`. Historical rows are preserved; ingestion halts. CLI: `tools/deactivate_tickers.py --tickers XYZ --reason "..." --execute`. Requires `--reason` with `--execute`; writes one JSONL row per deactivation to `logs/data_quality/deactivations.jsonl` (`db_before`/`yf_evidence`/`db_after`/`reason`).
- **Renames/Mergers**: Ticker symbol changes are patched retroactively across all eight affected tables.
- **Purges**: Non-tradeable securities (Warrants `*-WT`, Units `*-UN`, Rights `*-RI`, Preferred `*-P_`, SPACs) are permanently blacklisted in `ticker_blacklist` and deleted from `company_profiles` and `price_data`.
- **Instrument reclassification**: `ticker_type` column on `company_profiles` distinguishes `EQUITY`/`FOREIGN`/`FUND`/`ETF`/`INDEX`. Derived from EDGAR form types via `scripts/enrich_ticker_types_edgar.py`; audit trail at `logs/data_quality/ticker_type_reclass.jsonl`. Non-EQUITY types are excluded from fundamentals fetch and staleness checks automatically.
- **Auditing**: `tools/run_all_audits.py` enforces SLAs on data freshness, null thresholds, and temporal alignment (see §11). Runs daily as orchestrator Phase 8 (600s timeout, best-effort); reports at `data/audit_reports/audit_report_YYYYMMDD.json`.

### 3.4 Macro Data (Phase 1.4)

Two macro tables serve different purposes:

- **`macro_data`**: FRED indicators and VIX — used by M03 regime model.
- **`t1_macro`**: SPY/QQQ daily OHLCV + VIX close — used as benchmark source for T2 RS computation.

The separation matters: T2 feature computation joins `t1_macro` for the SPY benchmark, while `macro_data` feeds the regime pillars.

---

## 4. Feature Engineering

The feature pipeline (`src/feature_pipeline.py`) uses a two-tier architecture — T2 and T3 — to balance computational scope with data density.

**Naming convention:**
- **T2**: Computed across the full investable universe (~2,400 tickers). Features requiring cross-sectional context (ranks, alphas) must be computed here.
- **T3**: Computed only for SEPA-eligible tickers (those that have ever entered a SEPA session). Dense, time-series-intensive features are feasible here because the population is ~10x smaller.

### 4.1 Phase 3: T2 Screener Features

Computed daily for every active screener member. Four sub-phases:

| Sub-phase | Method | Features Computed |
|-----------|--------|-------------------|
| **A — SQL** | CTE chain in `compute_t2_screener_features()` | OHLCV carry-through, SMAs (20/50/150/200d), RS line + RS rating, 52w/20d price ranges, volume ratios, ATR (10/14/20/50d), NATR, VCP ratio (`atr_10/atr_50`), consolidation width, SEPA flags (`trend_ok`, `breakout_ok`) |
| **B — Python (XS alphas)** | `compute_alpha_features()` via multiprocessing (4 workers) | 9 cross-sectional alphas: alpha001, alpha002, alpha004, alpha008, alpha011, alpha013, alpha015, alpha019, alpha060. **Must run on full ~2,400-ticker population for valid cross-sectional computation.** |
| **B-EMA — Python** | `compute_ema_features()` via `pandas.ewm()` | 5 EMAs: 8, 21, 50, 100, 200-day. Recursive — cannot be computed in SQL. |
| **C — SQL** | `compute_cross_sectional_ranks()` | 7 rank columns: `RS_Universe_Rank`, `RS_Sector_Rank`, `RS_vs_Sector`, `Sector_Momentum`, `RS_Industry_Rank`, `RS_vs_Industry`, `Industry_Momentum` |

**Relative Strength (RS) formula**: `0.4 × mom_63d + 0.2 × mom_126d + 0.2 × mom_189d + 0.2 × mom_252d`

**SEPA Entry Flags computed in T2:**
- `trend_ok` (C1–C9): Full Minervini trend template — price above all major SMAs, SMAs in correct order, RS line near highs, price within 25% of 52-week high, etc.
- `breakout_ok` (B1–B2): New 20-day high with volume > 1.3× the 50-day average volume (using `vol_avg_50_prev` — the 50-day average *excluding the current bar* to avoid inflating the denominator on breakout days).

**Output**: `t2_screener_features` — ~2,400 tickers/day, ~70 columns including OHLCV, EMAs, alphas, ranks, and SEPA flags.

**Coverage-aware recompute**: The incremental runner (`--phase-3-only`) detects if <99% of active screener tickers are present for the target date and triggers a full-date recompute rather than silently writing a partial row set. This guards against partial yfinance fetch failures propagating into the feature table.

### 4.2 Phase 5: T3 SEPA Features

Filtered to tickers present in `sepa_watchlist` (those that have ever opened a SEPA session). T3 carries forward all T2 columns and adds expensive time-series features.

Two sub-phases:

| Sub-phase | Method | Features Computed |
|-----------|--------|-------------------|
| **A — SQL INSERT** | Vectorised INSERT from `t2_screener_features` WHERE ticker IN sepa_watchlist universe | All T2 columns carried forward. Per-ticker window features: momentum (21/63/126/189/252d), RSI-14, ATR-14, volume depth (dollar volume, turnover, 50d vol ratio), velocity features, pattern flags, 19 `*_pct_chg` delta columns, `sma_50_slope`, `rs_line_lag_delta`. M03 regime scores joined by date. |
| **B — Python UPDATE** | 9 TS alphas + 2 vol-adjusted features via multiprocessing. Warmup loaded from `t2_screener_features` for continuous rolling windows. | alpha006, alpha009, alpha012, alpha041, alpha046, alpha049, alpha051, alpha054, alpha101 |

**T3 schema**: 144 columns total. Keyed by `(ticker, date, feature_version)`. `EXPECTED_T3_COLUMN_COUNT = 144` is a hard tripwire in `feature_pipeline.py` — update it alongside any DDL change.

**Critical design note (Option C, 2026-05-08)**: T3 universe = all tickers that have ever opened a SEPA session (drawn from `sepa_watchlist`), carrying their *complete price history* regardless of current SEPA state. The prior design (Option B) gated by `screener_membership.is_active` and produced ~70% non-SEPA noise rows.

**Fundamentals removed from T3 (2026-05-08)**: `net_income`, `revenue`, `shares_outstanding`, `peg_adjusted` are no longer stored in T3 rows. They are joined at query time by `v_d2_features` via LEFT JOIN to `fundamental_features` (the derived ratios table) and `shares_history`. This saves ~300MB and eliminates ASOF JOIN cost at insert time.

**Coverage-aware recompute**: The incremental runner (`--phase-5-only`) checks whether any breakout tickers (`trend_ok AND breakout_ok`) present in T2 for the target date are absent from T3. If missing tickers are found, the phase reruns for that date rather than silently leaving the gap. This is a separate gate from the T2 coverage check — T2 absence is caught at Phase 3; T3 absence (due to T3 write failure) is caught here.

### 4.3 Percentage Change Delta Features (v3.1)

19 `*_pct_chg` columns capture daily volatility on T2 metrics:

**Formula**: `(current - previous) / ABS(previous) × 100`

| Category | Columns |
|----------|---------|
| Moving Average deltas | `price_vs_sma_50/150/200_pct_chg` |
| Momentum deltas | `rs_pct_chg`, `rs_ma_pct_chg` |
| Volume delta | `dry_up_volume_pct_chg` |
| Volatility deltas | `natr_pct_chg`, `atr_pct_chg`, `vcp_ratio_pct_chg`, `consolidation_width_pct_chg`, `rsi_14_pct_chg` |
| 52-week range deltas | `dist_from_52w_high/low_pct_chg`, `high/low_52w_pct_chg` |
| 20-day range deltas | `dist_from_20d_high/low_pct_chg`, `highest_high/lowest_low_20d_pct_chg` |

**NULL handling**: First row per ticker is NULL (no previous value). `dist_from_52w_high_pct_chg` uses `CASE WHEN cur = prev THEN 0` to handle the zero-denominator case when a breakout stock is exactly at its high.

---

## 5. Market Regime Context (M03)

`src/pipeline/m03_regime.py` (`M03RegimeCalculator`) computes a daily market regime score used to gate backtest position sizing and new trade initiation.

**Three pillars:**
- **Trend**: Breadth indicators and major index moving averages.
- **Liquidity**: Volume flows and credit spreads.
- **Risk**: VIX derivatives and volatility measures.

**Output** (`t2_regime_scores`): one row per trading date. Columns: `date`, `m03_score`, `m03_pillar_trend`, `m03_pillar_liq`, `m03_pillar_risk`, `m03_delta_5d`, `m03_delta_20d`, `m03_regime_vol`.

**Regime categories** (mapped from `m03_score` thresholds, defined in `M03RegimeCalculator.DEFAULT_CONFIG['thresholds']` at `src/pipeline/m03_regime.py`):

| `m03_score` range | `m03_regime_cat` | Label | Backtest behavior |
|---|---|---|---|
| `score >= 80` | 4 | Strong Bull | Full capacity, max position size |
| `60 <= score < 80` | 3 | Bull | Normal capacity |
| `40 <= score < 60` | 2 | Neutral | Reduced capacity |
| `20 <= score < 40` | 1 | Bear | Minimal new entries |
| `score < 20` | 0 | Strong Bear | All new entries blocked; existing positions forcefully liquidated |

Gating rules (also in config): `long_allow_min = 30`, `long_reduced_min = 50`. Thresholds are loadable from `models/m03_config.json` (none currently committed; defaults apply).

M03 scores are joined into T3 by date (Phase 5A SQL) and exposed as features in the ML training set.

---

## 6. SEPA Session Management (Phase 4b)

`src/managers/sepa_watchlist_manager.py` maintains the `sepa_watchlist` event log — the universe gate for T3 and the temporal anchor for trade-level ML labelling.

### Session Model

Each row in `sepa_watchlist` represents one SEPA trading session for a ticker. Schema: `ticker`, `entry_date`, `exit_date`, `cooldown_end`, `session_id`, `trend_ok`, `breakout_ok`, `status` (`ACTIVE` / `COOLDOWN` / `EXITED`), `updated_at`.

**Entry trigger**: `trend_ok AND breakout_ok` on the target date, AND no open session exists for the ticker, AND prior session's `cooldown_end` has passed.

**Exit trigger**: C1+C2+C6 break — close drops below `sma_50` OR `sma_150` OR `sma_200`. Critically, this uses **C1+C2+C6 only**, not the full `trend_ok` flag. Using full `trend_ok` at exit causes C9 (RS line) flicker to fragment one long trade into many short ones.

**Cooldown**: 14 calendar days after `exit_date` before a new session can open. The cooldown is a *session-opening gate*, not a row-inclusion gate — T3 carries full history for every ticker regardless of cooldown state.

**Daily update logic** (one SQL pass, three operations in order):
1. **Close** open sessions where `close < sma_50 OR sma_150 OR sma_200` → set `exit_date`, `cooldown_end = exit_date + 14d`, `status = COOLDOWN`.
2. **Open** new sessions for tickers with `trend_ok AND breakout_ok` AND no open session AND past cooldown → INSERT `status = ACTIVE`.
3. **Promote** COOLDOWN rows whose `cooldown_end < today` → `status = EXITED`.

**Idempotency warning**: `update_daily(date)` is **not idempotent**. Re-running for the same date will attempt to open duplicate sessions. Use the `pipeline_runs` idempotency guard, or manually clean up before re-running:

```sql
DELETE FROM sepa_watchlist WHERE entry_date = '<DATE>';
UPDATE sepa_watchlist
SET exit_date = NULL, cooldown_end = NULL, status = 'ACTIVE'
WHERE exit_date = '<DATE>';
```

### Distinction from `screener_watchlist`

`sepa_watchlist` is the T3 universe gate (event log, one row per session). `screener_watchlist` is the materialised dashboard trade table (one row per trade with returns). Both coexist.

---

## 7. Machine Learning Methodology

### 7.1 Problem Formulation (M01)

The primary ML component is the Maximum Favorable Excursion (MFE) classifier (`scripts/train_mfe_classifier.py`).

**Question**: *Given a ticker that has passed the SEPA trend template and is experiencing a breakout today, what is the probability that it will achieve an abnormal MFE over an undefined holding period, provided the trend remains unbroken?*

**Target Classes** (based on `mfe_pct`):
| Class | Label | Range |
|-------|-------|-------|
| 0 | Noise | ≤ 2% |
| 1 | Moderate | 2% – 10% |
| 2 | Strong | 10% – 30% |
| 3 | Home Run | > 30% |

### 7.2 Algorithm & Training

- **Algorithm**: XGBoost Classifier, `multi:softprob` objective.
- **Hyperparameters**: `max_depth=4`, `learning_rate=0.05`, `subsample=0.8`, `colsample_bytree=0.8`, `tree_method=hist`, `num_boost_round=100`, `early_stopping_rounds=20`.
- **Temporal split**: Chronological 60/20/20 (standard) or 85/15/0 (no-holdout, for final production model).
- **Class imbalance**: `compute_class_weight('balanced')` — heavily penalises false negatives on high-MFE classes. Approximate weights: class 0 → 1.2×, class 1 → 0.9×, class 2 → 1.4×, class 3 → 4.1×.
- **Categorical features**: `sector`, `industry` are VARCHAR categoricals handled via XGBoost `enable_categorical=True`. No integer encoding.

### 7.3 Feature Set (M01)

105 valid features across 8 groups: Moving Averages, Momentum/RS, Volume, Volatility, Oscillators, Fundamentals, Alphas (XS + TS), M03 Regime. The complete feature list is stored in `model_feature_sets` table in DuckDB and loaded via `ModelRegistry.get_model_features('M01')`.

**Data flow:**
```
d2_training_cache (or v_d2_training fallback)
    → temporal split (chronological)
    → XGBoost multi:softprob, balanced class weights
    → ClassificationEvaluator (artifacts + plots)
    → ModelRegistry.register_version()
    → models/<model_name>/<version>/
```

### 7.4 Model Registry

All experiments are logged to the `models` table in DuckDB. Key columns:

| Column | Purpose |
|--------|---------|
| `version_id` | Unique ID, e.g. `m01_prototype_2003_2026_20260506_160054` |
| `status_flag` | `test` / `prod` / `archived` |
| `specs_json` | Features list, hyperparameters, training config |
| `feature_version` | Feature schema version (e.g. `v3.1`) |
| `artifacts_path` | Filesystem path to model files |
| `accuracy`, `weighted_f1`, `macro_f1` | Evaluation metrics |
| `model_card_path` | Path to most recent model card HTML (populated by `ModelCardBuilder.render()`) |
| `model_card_built_at` | Timestamp of most recent card build |

**Promotion gate**: `ModelRegistry.set_prod()` calls `_warn_on_adverse_card()` — emits an advisory warning if the card is REJECT, PENDING, or stale (>7d), but does **not block** promotion. Hard blocking gates remain the `results.json` gate battery (calibration ECE, WF Sharpe, regime AUC, etc.). This is intentional: card thresholds are hand-calibrated and not validated enough to be a hard stop. See `docs/decision_log/2026-06-11_model_card_gate.md`.

**Artifact layout** (written by `train_mfe_classifier.py`):
```
models/<model_name>/<model_version>/
    model.json                    # XGBoost booster
    metadata.json                 # Training config, feature list, leakage audit
    categorical_mapping.json      # category dtype mappings
    evaluation/
        results.json              # Accuracy, F1, per-class, feature importance, SHAP
        confusion_matrix.png
        feature_importance.png
        roc_curves.png
        pr_curves.png
        calibration_curves.png
        class_distribution.png
        report_*.md
        diffs/                    # model_diff.py output
```

**Current production model**: `M01_baseline_v0.1` (`status=prod`). Trained on a narrower historical window; see §8 for metrics.

**Registry CLI:**
```python
from src.model_registry import ModelRegistry
reg = ModelRegistry()
reg.list_versions()
reg.set_prod('version_id')
reg.get_model_specs('version_id')
reg.get_artifacts_path('version_id')
```

---

## 8. Model Evaluation & Validation

### 8.1 Current Production Model (M01_baseline_v0.1)

- **Accuracy**: 67.05%
- **Weighted F1**: 0.582
- **Macro F1**: 0.248

The low macro F1 reflects class imbalance — "Home Run" (class 3) trades are rare. The model's primary utility is the class 3 probability tail to gate backtest entry sizing, not perfect classification accuracy.

### 8.2 Current Prototype Model (m01_prototype_2003_2026, v2)

- **Training window**: 2003-01-02 to 2024-02-28 (31,489 breakout samples)
- **Validation window**: 2024-02-29 to 2026-05-14 (5,560 breakout samples)
- **Accuracy**: 29.91% | **Macro F1**: 0.288 | **Weighted F1**: 0.277

*(The lower accuracy compared to the baseline reflects different label thresholds and a 4-class problem on noisy market events over undetermined holding periods.)*

### 8.3 Evaluation Suite

`src/evaluation/classification_evaluator.py` (`ClassificationEvaluator`) generates a standardised artifact set per model run:

- **Global Metrics**: Accuracy, Macro/Weighted F1, Brier score.
- **Probabilistic Metrics**: ROC-AUC and Precision-Recall AUC per class.
- **Calibration Curves**: XGBoost softmax probabilities vs. observed frequencies.
- **SHAP**: Global feature impact + per-class top-5 SHAP values.
- **Feature Importance**: XGBoost gain ranking.

### 8.4 Temporal Leakage Validation

`src/evaluation/leakage_guard.py` (`LeakageGuard`) validates that no future data bleeds into the training set. This is run automatically as part of `train_mfe_classifier.py` and its output is stored in `metadata.json`.

### 8.5 Model Diff Tool

`scripts/model_diff.py` renders a 7-section side-by-side comparison of two model versions:
1. Training Config
2. Hyperparameters
3. Feature Set Diff (added/removed/shared)
4. Aggregate Metrics
5. Per-Class Metrics
6. Feature Importance Rank Shift
7. SHAP Top-5 per class

```bash
python scripts/model_diff.py \
    --model-a models/m01_prototype_2003_2026/v1 \
    --model-b models/m01_prototype_2003_2026/v2 \
    --save --save-text
```

---

## 9. Backtesting & Trade Simulation

### 9.1 Simulation Engine

Historical trading logic is simulated using the BackTrader framework. Primary strategy: `SEPAHybridV1` in `src/backtest/sepa_strategy.py`.

**Data flow (DuckDB mode — default):**
```
d2_training_cache      → UniverseScorer.score_from_duckdb() → M01 scoring (vectorised)
t2_regime_scores       → regime feed (regime_cat 0–4)
price_data             → OHLCV feeds + inline ATR-14
    → SEPABacktestRunner.setup_from_duckdb() + run()
    → report + equity curve + trade log
```

### 9.2 Entry Logic ("Top N Competition")

**M01 score mapping (entry ranking scalar):**
The backtest does **not** rank on raw `predict_proba()[:, 3]` (Home Run probability). Instead, `UniverseScorer.score_from_duckdb()` computes a **probability-weighted expected-MFE score** using class midpoints:

```python
# src/backtest/universe_scorer.py:313-314
midpoints = np.array([1.0, 6.0, 20.0, 40.0])              # per-class MFE % midpoints
calibrated_score = (predict_proba(X) * midpoints).sum(axis=1)  # expected MFE in %
```

This `calibrated_score` is normalised to 0-100 and ranked via:
- `daily_pct_rank` — single-day cross-sectional percentile, AND
- `trailing_pct` — 10-day rolling-cohort percentile (default `rank_by='trailing'`).

`prob_elite = predict_proba()[:, 3]` is also stored on the result dataframe but is a **diagnostic column only** — it is not used in candidate ranking. Confusing the two would silently change which candidates the backtest chooses.

**Entry filters:**
1. Candidates must clear `min_score = 30` (absolute floor on normalised score).
2. Sort by trailing 10-day percentile descending; take Top N (regime-capped) or `entry_percentile_min` filter.

Regime 0 (Strong Bear): all new entries blocked; existing positions forcefully liquidated.

### 9.3 Exit Logic (3-Tranche)

Positions are split into thirds and exited in tranches to secure profits while letting a runner ride the trend.

| Tranche | Trigger | Size |
|---------|---------|------|
| Initial Stop Loss | `2.0 × ATR` below entry OR `10%` below entry, whichever is tighter. Trailing (ticks up with highest close). | Full position if hit |
| Target 1 | Price reaches `3.0 × ATR` or `15%` above entry | 1/3 of position |
| Target 2 | Price reaches `Target 1 + 2.0 × ATR` | 1/3 of position |
| Trend Exit (runner) | Close drops below 50-day SMA | Final 1/3 |
| Momentum Fade (optional) | Relative percentile rank falls below 40th percentile | Remaining position |

### 9.4 Position Sizing

Depending on `sizing_mode` configuration:
- **Regime-scaled**: 2.5% – 10% per position based on M03 regime strength.
- **Equal-weighted**: uniform allocation.
- **Rank-weighted** / **Score-weighted**: proportional to M01 percentile rank or raw score.

### 9.5 Runtime Candidate Gate — `ScoreLookup`

`src/backtest/score_lookup.py` (`ScoreLookup`) is a pre-built in-memory index over the full scored universe. It is constructed once at backtest startup and queried O(1) per trading day — no per-day SQL round-trip.

```python
# Usage (inside SEPAHybridV1.next())
candidates = self.score_lookup.get_candidates(
    date,
    min_score=30.0,         # absolute floor on normalised_score (0-100)
    min_percentile=0.0,     # optional percentile gate (0 = no gate)
    rank_by='trailing'      # 'trailing' = 10-day cohort rank; 'daily' = single-day
)
# Returns: [(ticker, normalised_score, trailing_pct, daily_pct_rank, prob_elite), ...]
# Sorted by trailing_pct descending — highest persistent-strength first
```

The index is keyed `date → {ticker: (normalised_score, daily_pct_rank, trailing_pct, prob_elite)}`. Separating the scoring pass (`UniverseScorer.score_from_duckdb()`) from the day-loop lookup is what makes the backtest wall time proportional to trading days, not to (trading days × candidate count).

### 9.6 Toolkit

| File | Purpose |
|------|---------|
| `scripts/run_backtest.py` | CLI entrypoint |
| `src/backtest/runner.py` | `SEPABacktestRunner` |
| `src/backtest/sepa_strategy.py` | `SEPAHybridV1` BackTrader strategy |
| `src/backtest/universe_scorer.py` | `UniverseScorer` — `score_from_duckdb()` |
| `src/backtest/score_lookup.py` | `ScoreLookup` — in-memory O(1) daily candidate filter |
| `src/backtest/position_tracker.py` | `PositionTracker` — 3-tranche exits |
| `src/backtest/duckdb_feed.py` | `DuckDBCandidateFeed` — do NOT delete (imported by `backtest_optimization.py`) |

```bash
python scripts/run_backtest.py                                   # DuckDB mode (default)
python scripts/run_backtest.py --duckdb --model m01_baseline/v1
python scripts/run_backtest.py --duckdb --start 2021-01-01 --end 2023-12-31
```

**Output**: `data/backtest/` — reports, equity curves, trade logs.

---

## 10. Production Pipeline & Operations

### 10.1 Daily Orchestrator

`scripts/run_daily_pipeline.py` sequences Phases 1 through 8. It tracks completed phases in `pipeline_runs` (idempotency), aborts downstream phases on upstream failures (HALT mode), and supports partial re-runs.

```bash
python scripts/run_daily_pipeline.py                        # Full pipeline (yesterday's date)
python scripts/run_daily_pipeline.py --date 2024-01-15      # Specific date
python scripts/run_daily_pipeline.py --phase-1-only         # T1 ingestion only
python scripts/run_daily_pipeline.py --phase-2-only         # Screener membership only
python scripts/run_daily_pipeline.py --phase-3-only         # T2 features (incremental)
python scripts/run_daily_pipeline.py --phase-4-only         # Regime scores (incremental)
python scripts/run_daily_pipeline.py --phase-5-only         # T3 SEPA features (incremental)
python scripts/run_daily_pipeline.py --force                # Ignore idempotency
python scripts/run_daily_pipeline.py --dry-run              # Validate only
```

### 10.1.1 Scheduling & Orchestration (Prefect)

The daily run is scheduled on the ITX ops box via a **self-hosted Prefect (3.x)**
server + scheduler. Prefect owns only the outer ring — schedule, crash-level
retry (`retries=1`), run history, and the UI. The 9-phase business logic stays in
`DailyPipelineOrchestrator`; the flow (`flows/daily_pipeline_flow.py`) shells out
to the CLI above, so there is exactly **one** execution path (no per-phase Prefect
tasks — that would duplicate the phase registry and `pipeline_runs` health, with
no parallelism to gain on a single-writer DuckDB).

- **Deployment**: `daily-pipeline/daily`, cron `0 22 * * 1-5` in `Europe/London`
  (~1h after the US close). The IANA tz (not a fixed offset) makes 22:00 track the
  BST/GMT switch automatically — no DST edits. Env-overridable via `PIPELINE_CRON`
  / `PIPELINE_CRON_TZ`. The schedule's source of truth is `CRON` in the flow file
  (`serve` re-registers it on startup; UI edits are transient).
- **Process model**: two boot tasks keep it alive — `PrefectServer`
  (API + UI at http://127.0.0.1:4200) and `PrefectDailyPipelineServe` (scheduler).
  Launchers + idempotent registration in `scripts/start_prefect_server.ps1`,
  `scripts/start_prefect_serve.ps1`, `scripts/register_prefect_tasks.ps1`
  (registration needs an elevated shell). State lives in `~/.prefect` (outside the
  repo); launcher logs in `logs/prefect/`.
- **Manual run**: UI → Deployments → Quick run, or
  `prefect deployment run 'daily-pipeline/daily'`.

Full operational detail: `docs/session_logs/sprint_12/s4_prefect_orchestration_runbook.md`.
This **supersedes** the earlier Windows Task Scheduler approach.

### 10.2 View Chain

`src/managers/view_manager.py` (`ViewManager`) manages the SQL views that transform T3 features into trade-level training and deployment data.

| View | Row Represents | Downstream |
|------|---------------|------------|
| `v_sepa_candidates` | 1 day per ticker (while in trend) | Diagnostic queries |
| `v_d1_candidates` | 1 trade (session) | `v_d2_features`, `v_d2_hydrated`, `v_screener_dashboard` |
| `v_d2_features` | 1 trade + fundamentals (LEFT JOIN) | `v_d2_training`, `v_d3_deployment`, `v_d2_hydrated` |
| `v_d2_hydrated` | N days per trade (entry→exit daily rows) | `v_d2_training` only |
| `v_d2_training` | 1 trade + MFE/MAE outcomes | `train_mfe_classifier.py`, `d2_training_cache` |
| `v_d3_deployment` | Last 252 days of SEPA candidates | `dashboard.py` (live M01 scoring) |
| `v_screener_dashboard` | 1 trade (session) | Source for `screener_watchlist` materialisation |

**Manual recreation**: `python scripts/create_duckdb_views.py`

**Phase 6+7 timing (needs re-measurement)**: The previously documented `sl_exits` correlated-subquery bottleneck (~592s on ~38K trades) **has been refactored** — `v_d2_training` now uses a `price_with_next` CTE with `LEAD(date) OVER (PARTITION BY ticker ORDER BY date)` and joins on it (`src/managers/view_manager.py:580-597`). Re-time Phase 7 before deciding whether to drop or retain it; the previous wall-time argument no longer holds.

### 10.3 Phase 8 — Monitoring Alerts

Phase 8 always runs regardless of upstream failures. It reads `run_stats` from phases 1–7 and the current table state, then fires structured log warnings for any anomaly.

| Alert | Trigger condition | Recommended fix |
|-------|------------------|-----------------|
| Breakout drought | 0 breakouts for N consecutive trading days | Investigate market conditions or T2 flag logic |
| Runtime anomaly | Any phase took > 3× its rolling average duration | Check API rate limits, DuckDB buffer state |
| Recent failures | Phase failures logged in last 7 days | Check `logs/daily_pipeline.log` |
| T2 coverage gap | <99% of active screener tickers present in T2 for target date | Re-run `--phase-3-only` |
| T3 coverage gap | Breakout tickers present in T2 but absent from T3 for target date | Re-run `--phase-5-only` |

The coverage-gap alerts are the most operationally important: a partial yfinance fetch leaves tickers silently missing from the feature tables, and Phase 8 is the safety net that surfaces this before the next pipeline run.

### 10.4 Dashboard

```bash
streamlit run scripts/dashboard.py   # full local DB
DASHBOARD_DB_PATH=data/dashboard.duckdb streamlit run scripts/dashboard.py  # slim DB
```

Multi-page Streamlit app, **two-tier nav since 2026-07-18** (the "Today" monolith was retired at the sprint-14 uplift switch-over). **Decide**: Macro (`pages/2_Macro.py`, default landing), Screening (`pages/3_Screening.py`), Session activity (`pages/5_Session_Activity.py`), Portfolio (`pages/4_Portfolio.py`), Supply chain (`pages/6_Supply_Chain.py`), Equity research (`pages/7_Equity_Research.py`). **Workshop**: Dataset EDA (`pages/1_Dataset_EDA.py`), Model Lab (`pages/3_Model_Lab.py`), Backtest Studio (`pages/4_Backtest_Studio.py`), Pipeline Health (`pages/5_Pipeline_Health.py`).

**Slim dashboard DB** (`data/dashboard.duckdb`): 783 MB replica of the tables the dashboard actually reads (98.8% reduction from 67 GB). Built by `scripts/build_dashboard_db.py`; rebuilt nightly by orchestrator Phase 7.5. Set `DASHBOARD_DB_PATH=data/dashboard.duckdb` to use it. The main DB remains the source of truth for all pipeline writes.

**Decision Log** (Page 1): `daily_predictions` table logs every SEPA candidate scored by the prod model each day (point-in-time paper-trade record). Page 1 surfaces today's predictions with a toggle to mark `taken`/`skipped`. Past decisions joined to outcomes via `screener_watchlist`.

### 10.4 Cache & Report Locations

```
data/market_data.duckdb        Primary DuckDB database (all tables + views)
data/audit_reports/            Audit JSON reports — audit_report_YYYYMMDD.json
data/backtest/                 Backtest results, equity curves, trade logs
data/ml/                       ML artifacts (d2.parquet, predictions, scores)
data/evaluation/               Model evaluation results
logs/daily_pipeline.log        Daily pipeline execution log
logs/data_quality/YYYY-MM.log  Post-retry data quality failures (monthly)
models/m01_baseline/v1/        Production model artifacts
models/<name>/<version>/       Experiment model artifacts
```

---

## 11. Audit System

All audits live in `tools/`. Run individually or all-at-once via `tools/run_all_audits.py`.

```bash
python tools/run_all_audits.py                        # All phases
python tools/run_all_audits.py --warn-only             # Exit 1 if any FAIL/WARN
python tools/run_all_audits.py --date 2024-06-01       # Spot-check T2/T3 at a date
python tools/run_all_audits.py --skip t1 t3            # Skip specific audits
python tools/run_all_audits.py --json                  # Machine-readable output
```

Audit reports are written to `data/audit_reports/audit_report_YYYYMMDD.json`.

### T1 Data Quality (`tools/audit_t1_data_quality.py`)

Key checks and thresholds:

| Check | Threshold |
|-------|-----------|
| Price data coverage vs company_profiles | WARN < 80% |
| Fundamentals coverage | WARN < 60% |
| Shares history coverage | WARN < 60% |
| Price data staleness (days since latest row) | WARN > 5 days |
| Duplicate `(ticker, date)` in price_data | FAIL if > 0 |
| NULL or non-positive close | FAIL if > 0 |
| Zero volume rows | WARN > 1% |
| Extreme single-day moves (> 200%) | WARN > 100 rows |
| Active tickers with > 20% data gaps vs SPY | FAIL if > 0 |
| Fundamentals: key column null rate | WARN > 15%, FAIL > 50% |
| `filing_date` before `period_end` | FAIL if > 0 |
| `t1_macro` NULL on `spy_close`/`qqq_close`/`vix_close` | FAIL if > 0 |

### T2 Membership (`tools/audit_t2_membership.py`)

Key checks: event log state machine consistency (exits never exceed entries per ticker), grace period correctness (consec_fail_days must be exactly 126 on exit events), no duplicate consecutive entry or exit events, current active universe size (WARN < 200 or > 5,000).

### T2 Screener Features (`tools/audit_t2_screener_features.py`)

Key checks: ticker coverage vs screener membership active tickers (WARN < 80%), `trend_ok`/`breakout_ok` null rates (FAIL > 20%), SEPA candidate yield (WARN < 0.5% or > 30%), cross-sectional rank/alpha nulls (downgrade to INFO when within 270-row warmup window per ticker).

### T3 SEPA Features (`tools/audit_t3_sepa_features.py`)

Key checks: all 144 columns present, `feature_version = 'v3.1'` for all rows, 19 `*_pct_chg` columns present, 9 TS alphas from Phase B present, 7 M03 regime columns present (WARN > 5% null), referential integrity vs screener membership.

---

## 12. Ticker Lifecycle Management

### Deactivate (delisted / acquired)

Sets `is_active = FALSE`, `delisting_date = CURRENT_DATE` in `company_profiles`. Preserves all historical rows. Halts future ingestion. `--reason` is required with `--execute`; each deactivation writes a JSONL row to `logs/data_quality/deactivations.jsonl`.

```bash
python tools/deactivate_tickers.py --tickers FPAY IMAB ZYXI --reason "confirmed delisted yfinance"          # dry-run
python tools/deactivate_tickers.py --tickers FPAY IMAB ZYXI --reason "confirmed delisted yfinance" --execute # apply
```

### Rename (symbol change or merger)

Two cases: simple rename (old exists, new doesn't → UPDATE ticker across all tables) or merge (both exist → INSERT OR IGNORE old history into new, delete old). Tables updated: `price_data`, `fundamentals`, `shares_history`, `earnings_calendar`, `t2_screener_features`, `t3_sepa_features`, `screener_membership`, `company_profiles`.

```bash
python tools/rename_tickers.py POAI:AGPU LPTX:CYPH KAR:OPLN  # dry-run
python tools/rename_tickers.py POAI:AGPU --execute             # apply
```

### Purge (non-tradeable securities)

Permanently blacklists in `ticker_blacklist`. Deletes from `company_profiles` and `price_data`. Purge candidates: Warrants (`*-WT`), Units (`*-UN`), Rights (`*-RI`), Preferred (`*-P_`), SPACs/blank-check companies, tickers > 5 characters.

```bash
python tools/purge_junk_tickers.py           # dry-run
python tools/purge_junk_tickers.py --execute
```

### Patch Fundamentals (filing_date anomalies)

```bash
python tools/patch_fundamentals.py --fix filing_date_zero              # ~55K rows: EDGAR lookup + 45d fallback
python tools/patch_fundamentals.py --fix filing_date_stale_historical  # ~6.4K rows: NULL >365d / EDGAR for 91-365d
```

---

## 13. Helper Libraries

These modules are importable from notebooks, scripts, and the REPL — not just CLI tools. Use them rather than raw SQL or ad-hoc DuckDB calls.

| Module | Class / Function | Purpose |
|--------|-----------------|---------|
| `src/screener_diagnostics.py` | `ScreenerDiagnostics` | Per-ticker SEPA criteria diagnosis. `diagnose(ticker, days)` returns dict with freshness, trades, per-day C1-C9 / B1-B2 pass/fail matrix, state transitions. `print_report()` for console output. |
| `src/utils.py` | `get_latest_trading_day()` | Returns most recent completed NYSE trading day (calendar-aware). Used throughout to determine target date. |
| `src/utils.py` | `load_etf_exclusion_list()`, `filter_etfs()` | ETF/fund ticker exclusion. |
| `src/data_loader_duckdb.py` | `load_training_data_from_db(use_cache=True)` | Load `d2_training_cache` (or `v_d2_training` fallback) into DataFrame. Applies `COLUMN_CASE_MAP` rename automatically. |
| `src/model_registry.py` | `ModelRegistry` | CRUD for `models` table — list, register, promote, archive model versions. |
| `src/evaluation/classification_evaluator.py` | `ClassificationEvaluator` | Confusion matrix, ROC/PR curves, SHAP, feature importance. Auto-registers artifacts via `ModelRegistry`. |
| `src/evaluation/leakage_guard.py` | `LeakageGuard` | Temporal leakage validation — checks no future data bleeds into training set. Run automatically by `train_mfe_classifier.py`. |
| `src/managers/view_manager.py` | `ViewManager` | `create_all()` recreates all views + materialises `screener_watchlist`. `refresh_cache()` materialises `d2_training_cache`. Constructor: `ViewManager(feature_version='v3.1')`. |
| `src/managers/screener_manager.py` | `ScreenerManager` | `evaluate_and_log(date)` — evaluates screener criteria for one date and logs entry/exit events to `screener_membership`. |
| `src/managers/sepa_watchlist_manager.py` | `SepaWatchlistManager` | `backfill()` — full rebuild from T2 history. `update_daily(date)` — open/close sessions for one trading day. `get_universe()` — `SELECT DISTINCT ticker FROM sepa_watchlist`. `get_stats()` — quick monitoring summary. |
| `src/managers/pipeline_run_manager.py` | `PipelineRunManager` | Phase execution tracking, idempotency checks, health reports. |
| `src/regime_pipeline.py` | `RegimePipeline` | `compute_history()` or `compute_incremental()` — M03 regime scores. |
| `src/feature_pipeline.py` | `FeaturePipeline` | `compute_t2_screener_features()`, `compute_t3_features()`, `compute_all()`. |
| `src/backtest/score_lookup.py` | `ScoreLookup` | In-memory O(1) per-day candidate filter. Pre-built from `UniverseScorer` output; queried in `SEPAHybridV1.next()`. |

---

## 14. Replication Guide


The following sequence replicates the full system from scratch. Each step is a prerequisite for the next unless noted.

### Step 0: Environment Setup

```bash
python -m venv .venv
.venv/Scripts/Activate.ps1          # Windows PowerShell
pip install -r requirements.txt
```

Ensure a DuckDB file will be created at `data/market_data.duckdb` on first run. No manual schema creation is required — tables are created by the respective engine/pipeline on first use.

### Step 1: Universe Seed

Populate `company_profiles` with the initial ticker list. Use FMP discovery to find all tradeable US equities:

```bash
python scripts/run_universe_backfill.py --discover-fmp
```

This creates `company_profiles` rows with `sector`, `industry`, `is_active=TRUE`.

### Step 2: T1 Historical Backfill

Backfill all raw data tables. Run in this order (shares must follow prices):

```bash
python scripts/run_universe_backfill.py --backfill-prices --start-date 2000-01-01
python scripts/run_universe_backfill.py --backfill-shares
python scripts/backfill_fundamentals.py --source fmp --overwrite
python scripts/backfill_fundamental_ratios.py
python scripts/backfill_t1_macro.py --start 2000-01-01
```

### Step 3: Data Quality Baseline

```bash
python tools/run_all_audits.py
python tools/purge_junk_tickers.py --execute
python tools/patch_fundamentals.py --fix filing_date_zero
python tools/patch_fundamentals.py --fix filing_date_stale_historical
```

Resolve any FAIL-level audit findings before proceeding.

### Step 4: Screener Membership Backfill (Phase 2)

```bash
python scripts/backfill_screener_membership.py
```

Populates `screener_membership` event log for the full price_data history (~10s). Verify with `python tools/audit_t2_membership.py`.

### Step 5: T2 Feature Backfill (Phase 3)

```bash
python scripts/backfill_t2_screener_features.py
```

Computes T2 features for all screener members across the full date range. Verify with `python tools/audit_t2_screener_features.py`.

### Step 6: Regime Score Backfill (Phase 4)

```bash
python src/regime_pipeline.py --backfill --start 2000-01-01
```

Populates `t2_regime_scores`.

### Step 7: SEPA Watchlist Backfill (Phase 4b)

**Must run before T3 backfill.** This populates the T3 universe gate.

```bash
python scripts/backfill_sepa_watchlist.py
```

Expected: ~35,560 sessions across ~2,697 tickers in ~7s. Verify: `SELECT COUNT(*), COUNT(DISTINCT ticker) FROM sepa_watchlist`.

### Step 8: T3 Feature Backfill (Phase 5)

```bash
python scripts/backfill_t3_sepa_features.py --restart --from 2001-Q1
```

Expected: ~9.4M rows, 1.5–2.5h wall time. Tail progress: `tail -f -n 5 logs/t3_backfill_progress.log`.

Verify with `python tools/audit_t3_sepa_features.py`.

### Step 9: Views & Training Cache (Phases 6 & 7)

```bash
python scripts/create_duckdb_views.py
python scripts/refresh_training_cache.py
```

Phase 6 creates all SQL views (~16 min for DDL + screener_watchlist materialisation). Phase 7 materialises `d2_training_cache`. The previously documented ~592s `sl_exits` correlated-subquery bottleneck was fixed 2026-05-14 (see `docs/session_logs/2026-05-14.md`); re-time Phase 7 to confirm current wall time.

Verify: `python scripts/refresh_training_cache.py --stats`

### Step 10: Model Training

```bash
python scripts/train_mfe_classifier.py --no-holdout \
    --feature-set fs_m01_prototype \
    --model-name m01_prototype_2003_2026 \
    --min-date 2003-01-01
```

This trains the XGBoost 4-class MFE classifier, writes artifacts to `models/<model_name>/<version>/`, and registers the model in the `models` table.

Promote to production after validation:
```python
from src.model_registry import ModelRegistry
ModelRegistry().set_prod('<version_id>')
```

### Step 11: Backtest Verification

```bash
python scripts/run_backtest.py --duckdb --start 2020-01-01
```

Baseline metrics to verify against (M01_baseline_v0.1): `acc=0.6705`, `wF1=0.582`, `macroF1=0.248`. Drift > ±0.005 indicates a data or feature bug.

### Step 12: Daily Operations

After the full backfill, the system runs daily via:

```bash
python scripts/run_daily_pipeline.py
```

This increments all tables by one trading day, updates `sepa_watchlist`, appends T3 rows for new SEPA candidates, refreshes views, and logs monitoring metrics.

---

## 15. Model Development Lifecycle

This section documents the decision framework for developing a new model from idea to deployment. Follow this sequence — skipping steps (especially backtesting before passing the model card) manufactures false confidence.

```
IDEA → Step 1: Target Selection
     → Step 2: Feature Selection
     → Step 3: Training
     → Step 4: Evaluation & Model Card
     → Step 5: Easy Fixes (if MARGINAL)
     → Step 6: Backtest (only after card PASSES)
     → Step 7: Deployment
```

### Step 1: Target Selection

Answer before writing any code:
- **What is the model trying to do?** Selection (which setup?) vs. Timing (when?) vs. Sizing (how much?). `m01_prototype` is a selection filter — it never ranked trades well (horizon-invariant; 1d and 20d scores correlate at 0.92).
- **2-class or 4-class?** 2-class (binary home-run threshold) is simpler, trains faster, and the card's calibration gate is achievable. 4-class gives more signal nuance but fails calibration easily on imbalanced classes. Start binary unless you have a specific reason for 4-class.
- **What horizon?** MFE is measured over the SEPA holding period (not a fixed N days) — this is already baked into the label registry. Don't create a fixed-horizon label without a good reason; it introduces lookahead when sessions are still open at horizon cutoff.
- **What is the base rate?** Check `d2_training_cache`: `SELECT AVG(mfe_pct > 0.30)` for the home-run rate. Below ~10% base rate → class imbalance will dominate; plan for `scale_pos_weight` or `class_weight='balanced'`.

### Step 2: Feature Selection

Sources: `daily_features` (149 cols), `model_feature_sets` table (registered groups for M01).

Decision criteria:
- **Mutual Information / IC** — visible in the EDA report (Page 1 Dataset EDA → Feature Signal). Features with near-zero IC across deciles are noise.
- **Multicollinearity** — drop one of any pair with |ρ| > 0.85. The hierarchical cluster plot in the EDA report shows natural groups.
- **Phase leakage** — all features in `t3_sepa_features` are point-in-time safe. If you derive a new feature, run `LeakageGuard` before training.
- **Fundamentals** — available but sparse (~40% null rate for recent quarters). XGBoost handles NULLs natively; include them, but watch the null fraction in the pretrain audit.
- `sector`/`industry` — always include as XGBoost categoricals (`enable_categorical=True`). Do not integer-encode.

### Step 3: Training

```bash
python scripts/train_mfe_classifier.py \
    --feature-set fs_m01_prototype \
    --model-name m01_<name> \
    --label-id mfe_binary_homerun_v1 \
    --no-holdout --walk-forward \
    --with-regime-decomp --with-calibration
```

Use chronological 60/20/20 for exploration; `--no-holdout` (85/15) for the final production candidate. Always pass `--walk-forward` — the WF gates are what the card evaluates.

### Step 4: Evaluation & Model Card

```bash
python scripts/build_model_card.py --model m01_<name>/<version>
```

Read the card verdict for the *intended use case*:
- **PASS** → proceed to Step 6.
- **MARGINAL** → Step 5, then re-run card once.
- **REJECT** → go back to Step 1 or 2. The problem is structural. **Do not backtest a REJECT model** — the backtest will find a strategy that works on bad probabilities.

Current use cases in the card: `composite_gate_plus_rank`, `threshold_gate` (`["A","E","G"]` — Section C not required, see decision log), `human_screener`, `hit_rate_ranker_equal_size`.

Current prod model findings for reference: AUC 0.773 vs SEPA baseline 0.594 (Section G PASS); calibration ECE 0.132 (gate requires <0.05 — FAIL). The real edge exists; calibration is the open problem.

### Step 5: Easy Fixes (MARGINAL cards only)

Attempt at most 2–3 iterations. Common fixes:
- **Calibration failing**: try `--with-calibration` (Isotonic). If ECE stays >0.05, the score distribution is bimodal — no calibrator fixes that; revisit label design.
- **E2 trade frequency failing** (too few trades at T*): lower T* threshold, or add a `human_screener` use case that relaxes frequency. Do not just tune the threshold to pass the gate without understanding why frequency is low.
- **Regime decomp failing**: one regime (usually Strong Bear) has AUC < 0.50. Check if Strong Bear samples are too few (<50 positives) — that's a data shape problem, not a model problem.

### Step 6: Backtest

Only run after the card PASSES for the intended use case.

```bash
python scripts/run_strategy_array.py \
    --model-name m01_<name> --model-version v1 \
    --start 2020-01-01 --end 2026-01-01 \
    --strategies S1,S2,S3
```

The backtest is a **sanity check**, not an optimisation target. A model that passes the card should produce reasonable backtest metrics. If the backtest dramatically outperforms what the card predicted, you're overfitting to the train/test regime — investigate.

Mode B (stateful daily pool via `run_deep_rigor_suite.py`) is appropriate for assessing how score trajectories evolve over a live SEPA session — see Sprint 12 T6.

### Step 7: Deployment

Prerequisites: card built within last 7 days; PASS or MARGINAL (with documented sign-off) for the deployed use case; `model_card_path` populated in registry.

```python
from src.model_registry import ModelRegistry
ModelRegistry().set_prod('<version_id>')
# → triggers _warn_on_adverse_card() (advisory); hard gate is results.json blocking checks
```

Post-deployment: `daily_predictions` logs every candidate scored; review at P ≥ 0.30 (consideration) or P ≥ 0.60 (high conviction). Monitor calibration drift quarterly via PSI report.

---

## 16. Known Tech Debt & Future Work

### Active Tech Debt

| Issue | Location | Impact |
|-------|----------|--------|
| ~~`sl_exits` correlated subquery~~ | ~~`v_d2_training` CTE~~ | RESOLVED 2026-05-14 — rewritten to use `price_with_next` LEAD window. Re-measure Phase 7 timing. |
| `v_screener_dashboard` duplicates session-detection CTE | `view_manager.py` | Doubles T2 scan work. Could share a materialised intermediate with `v_d1_candidates`. |
| `trend_c8` CTE is a misnomer | `view_manager.py` | Despite the name, computes C1+C2+C6 (not C1-C8). Rename to `trend_exit` in future cleanup. |
| Cross-sectional rank column casing | `feature_pipeline.py`, `COLUMN_CASE_MAP` | `rs_sector_rank` etc. stored lowercase in `FEATURE_GROUPS` but DuckDB returns TitleCase from UPDATE. Not in `COLUMN_CASE_MAP` yet. |
| `v_d2_hydrated` exists solely to feed `v_d2_training` | `view_manager.py` | Could be eliminated if `v_d2_training` computed MAE/MFE/SL directly against `price_data`. |
| M01 macro F1 = 0.25 | model | Class imbalance. Needs SMOTE, threshold tuning, or cost-sensitive learning. |

### DuckDB Gotchas

- `price_data.volume` is `UBIGINT` — any subtraction must `CAST(volume AS BIGINT)` to avoid overflow.
- DuckDB named windows cannot reference other named windows in the same WINDOW clause — use multiple CTEs.
- DuckDB UPDATE does not support the WINDOW clause — use `CREATE OR REPLACE TABLE` with window functions instead.
- VWAP uses standard `(H+L+C)/3`.
- RS is momentum-based (weighted sum) — NOT a benchmark ratio. `price_vs_spy` (benchmark ratio) is a separate column used for SEPA C9 filter only.
- Percentage change deltas use `ABS()` in the denominator for distance metrics that can be negative.

### Operational Roadmap

Sequenced by risk-adjusted leverage. Full detail and acceptance criteria in `docs/plans/system_design_review_action_plan_2026_05_16.md`.

**P1 — Data quality & reliability:**
- Phase 1.5 quality gate: auto-run `audit_t1_data_quality` inside the DAG, HALT on FAIL, self-healing T1 retry
- Materialise `trend_exit_ok` column in T2; rename `trend_c8` CTE to `trend_exit`
- Invariant-based audits (universe contract checks across `sepa_watchlist`, `screener_membership`, `t3_sepa_features`)

**P1 — Regime model rebuild:**
- Regime v2: wide z-score table (`t2_regime_signals`), dual rolling/expanding z-scores, veto-based gating (see `docs/plans/system_design_review_action_plan_2026_05_16.md` §T2.x)

**P2 — Model operations:**
- Walk-forward CV + regime-conditional metrics + PSI drift checks
- Enforce prod-readiness checklist in `ModelRegistry.set_prod()`
- M01-Watch (pre-breakout classifier) and M01-Hold (position degradation classifier) variants

**P2-P3 — Infrastructure:**
- Structured JSON logging per phase
- `sepa_watchlist.update_daily()` idempotency via `INSERT ... ON CONFLICT DO NOTHING`
- Nightly DuckDB backup to OneDrive/S3
- ~~Prefect (local) for scheduling with retry semantics~~ — **DONE 2026-06-21**: self-hosted Prefect on ITX, deployment `daily-pipeline/daily` (cron `0 22 * * 1-5` Europe/London), coarse flow wrapping the CLI. See `docs/session_logs/sprint_12/s4_prefect_orchestration_runbook.md`.

**P3 — Dashboard expansion:**
- Pipeline Health, Ticker Deep Dive, Model Lab, Backtest Studio pages (Streamlit multipage)
