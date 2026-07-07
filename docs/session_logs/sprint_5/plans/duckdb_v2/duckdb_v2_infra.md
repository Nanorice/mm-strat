# DuckDB v2 Infrastructure Overview

## OBJECTIVE
Build a systematic equity screening pipeline inspired by Minervini's SEPA methodology, with ML models (M01 entry scoring, M03 regime detection) to rank and filter US stock candidates for swing trading.

## TECH STACK
- Database: DuckDB (local, file-based)
- Language: Python
- Data Source: `yfinance` for OHLCV, fundamentals
- ML: XGBoost (M01 entry model, M03 regime model)
- Dashboard: [Streamlit / Grafana / TBD]

## DATA ARCHITECTURE (3 Tiers + Views)

### TIER 1: `t1_price` & `t1_fundamentals` (Eager, Full Universe)
- Scope: ALL US tickers (~8,000+), full history (10yr+)
- Columns: ticker, date, open, high, low, close, adj_close, volume
- Update: daily append
- Status: 🟡 IN PROGRESS (Migrating to `yfinance`)

### TIER 2: `t2_screener_features` & `t2_screener_members` (Eager, All History)
- Scope: computed eagerly on full history for simplicity/speed. `t2_screener_members` tracks which tickers pass the first-pass volume/price screener.
- Columns: ticker, date, ~20-30 lightweight features (SMA_50, SMA_150, SMA_200, RS_rating, ATR, distance_from_52w_high, etc.)
- Trigger: Eager calculation executing daily over updated `t1_price`
- Status: 🟡 PARTIALLY IMPLEMENTED (Refactoring for naming conventions)

### TIER 3: `t3_sepa_features` (Materialized Point-in-Time SEPA Candidates)
- Scope: tickers passing full SEPA trend template + breakout
- Columns: ticker, date, 100+ features (all Tier 2 features + fundamental features + sector-relative metrics + ML Phase B Alphas + M03 regime pillars)
- Lifecycle: Expands daily. Rows appended *only* for the specific dates a ticker satisfied the SEPA Trend Template.
- Status: 🔴 NOT YET IMPLEMENTED (Needs permanent physical table creation)

### VIEWS (derived, not stored)

#### `v_d1_trades` (Trade ID & Gap Generation)
- Generates `trade_id` dynamically using LAG-based date-gap detection on valid trading days.
- Groups consecutive days in Tier 3 into single trade events.
- Columns: ticker, trade_id, entry_date, exit_date, entry_price, exit_price
- Status: 🔴 NOT YET IMPLEMENTED (SQL designed, needs view creation)

#### `v_d2_hydrated`
- Tier 3 enriched with forward-looking trade metrics
- Columns: trade_id, mae, mfe, running_return_pct, sl_hit (boolean), sl_date, sl_pct
- Stop-loss: single configurable set (ATR-based + pct-based)
- Status: 🔴 NOT YET IMPLEMENTED

#### `v_d2_training`
- Entry-date snapshot: features at entry + target variables
- Joins `v_d1_trades` (entry context) + `v_d2_hydrated` (outcomes)
- Targets: target_return, target_class (Superperformer/Winner/Loser)
- Used for: M01 model training and refresh
- Status: 🔴 NOT YET IMPLEMENTED

#### `v_d3_deployment` (daily scoring view)
- Latest-day snapshot of all current active SEPA candidates.
- Formats `t3_sepa_features` equally to `v_d2_training`.
- Pipeline: snap latest rows -> score M01/M03 -> filter -> dashboard
- Status: 🔴 NOT YET IMPLEMENTED

### SUPPORTING TABLES

#### `buy_list`
- Lean table: ticker, date_added, date_removed, status
- Derived from `v_d3_deployment` after model scoring + manual review
- Status: 🔴 NOT YET IMPLEMENTED

## MODELS

### M01 - Entry Scoring
- Type: XGBoost classifier/regressor
- Input: features at entry date (from `v_d2_training`)
- Output: probability score for trade quality
- Refresh: periodic retrain as Tier 3 grows
- Status: 🔴 NOT YET IMPLEMENTED

### M03 - Regime Detection
- Type: XGBoost or rules-based
- Input: market-wide features (breadth, index trend, volatility)
- Output: multi-pillar regime flags (not single label)
- Used as: feature input to M01 + standalone filter
- Status: 🔴 NOT YET IMPLEMENTED

## KEY DESIGN RULES
1. Raw Data (`t1_price`) is eager & updated cleanly via `yfinance`.
2. Base Features (`t2_screener_features`) are eager, decoupling feature definitions from raw data ingestion.
3. ML Features (`t3_sepa_features`) are LAZY & permanently MATERIALIZED (stored) only for breakout dates.
4. `trade_id` splits on ANY non-weekend/holiday gap in consecutive trading days.
5. Stop-loss columns are generic, logically hydrated forward over trade lifespans.
6. The ML prediction pipeline runs inference daily off `v_d3_deployment`.

## CURRENT STATUS SUMMARY
- 🟡 Tier 1 Price ingestion pipeline (Migrating to `yfinance`)
- 🟡 Tier 2 feature computation (Refactoring Eager evaluation)
- 🔴 Tier 3 Materialized SEPA features table
- 🔴 Gap-generated View: `v_d1_trades`
- 🔴 Outcome Views: `v_d2_hydrated`, `v_d2_training`, `v_d3_deployment`
- 🔴 M01 model & M03 Model
- 🔴 Dashboard & Daily Orchestration Cron