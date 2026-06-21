# Review of DuckDB v2 Infra Proposal

## 1. Architectural Challenges & Feedback

*   **Lazy Evaluation of Tier 2 (daily_features):** Your proposal suggests computing Tier 2 features *only* for screener-passed tickers. In DuckDB, applying SQL window functions (Phase A) across the full 8,000 ticker universe is actually extremely fast (usually just a few seconds). The true bottleneck is typically Phase B (pulling data into Pandas for Alpha factor calculation). **Recommendation:** Compute Phase A (SQL) eagerly on all tickers, but strictly filter down to `stock_screener` membership *before* pulling data into Pandas for Phase B. This gives you the best of both worlds.
*   **Tier 3 (`sepa_candidates_w_features`) as a Persistent Table:** Currently, `v_sepa_candidates` and `v_d1_candidates` are views built dynamically on top of `daily_features`. Materializing Tier 3 into a permanent table makes absolute sense here. It freezes the point-in-time features for ML reproducibility and drastically speeds up M01 training/inference. **Recommendation:** This requires adding a daily explicit `INSERT INTO sepa_candidates_w_features` task snippet into `data_curator_duckdb.py`.
*   **Trade_ID Generation (Gap Detection):** You defined `trade_id` via "LAG-based gap detection on consecutive trading days; ANY gap = new trade". Our current `v_d1_candidates` view defines sessions based on `trend_ok` transitions. We need to refactor this logic to explicitly measure `datediff` against a valid `trading_calendar` (or previous row dates) to guarantee that any gap explicitly splits the trade ID, exactly as you specified.

---

## 2. Gap Analysis: Current vs. Proposed

### ✅ What is Already Implemented (or Mostly Done)
*   **Tier 1 (Price):** Done via `DataRepository` and DuckDB `price_data` table.
*   **Tier 2 (Features):** Mostly implemented in `src/feature_pipeline.py`. However, it currently computes eagerly for the full universe instead of lazily.
*   **Trade Hydration & Targets:** The logic for tracking entry/exit, SL hits, MAE, MFE, and `return_pct` exists in `v_d2r_hydrated` and `v_d2_training` views.

### 🔴 The Gaps (What needs changing/building)

#### Gap 1: Pipeline Orchestration & Lazy Evaluation (`feature_pipeline.py` & `data_curator_duckdb.py`)
*   **Current State:** Phase B Alpha generation and Phase C (M03) run on the entire universe.
*   **Action Required:** Modify `FeaturePipeline` to inner-join against `stock_screener` prior to executing the expensive Pandas-based alpha computations. 

#### Gap 2: Tier 3 Permanent Materialization
*   **Current State:** We only have dynamic views (`v_sepa_candidates`, `v_d2_features`). 
*   **Action Required:** Create the physical table schema for `sepa_candidates_w_features` (permanently storing the 100+ combined Tier 2/Fundamentals/M03 features). Add a step in `data_curator_duckdb.py` to append new qualifying SEPA breakouts to this table daily.

#### Gap 3: Refactoring Views & Gap-based `trade_id` (`src/view_manager.py`)
*   **Current State:** `v_d1_candidates` builds sessions via boolean transitions.
*   **Action Required:** 
    1. Update the session logic to use strict gap detection (date diffs).
    2. Adapt `d1_candidate`, `d2_hydrated`, and `d2_training` views to read directly from the new physical `sepa_candidates_w_features` table instead of re-evaluating the breakout logic on the fly.
    3. Build the missing `d3_deployment` view to load the 1yr trailing context + current M01/M03 scores.

#### Gap 4: M01/M03 Models & Deployment Tables
*   **Current State:** No ML components or physical deployment outputs exist.
*   **Action Required:** 
    1. Build the XGBoost training/inference pipeline for M01 (Entry Quality) and M03 (Regime).
    2. Create the lean `buy_list` table.
    3. Add the daily inference step to the orchestrator to populate `buy_list` from `d3_deployment`.
