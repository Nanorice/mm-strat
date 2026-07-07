# Feature Pipeline Analysis: Architecture vs. Dynamic Scoring

## 1. Goal: Dynamic Daily Scoring
The objective is to expose all 90 model features and the XGBoost M01 model score in the backtest's `get_daily_holding_dataframe()`. This would allow the backtest to observe the dynamic evolution of the model score for every ticker on every day it is held, aiding in distribution analysis and potential dynamic exit management.

## 2. Current Architecture (As Documented)
According to `docs/manual_for_me.md`, the data engineering pipeline is strictly segregated to manage compute overhead and database size:

*   **Phase 3 (`t2_screener_features`)**: Completely dense. Computes lightweight technicals (OHLCV, SMAs, RS) for the full investable universe (~2,400 active tickers) every trading day.
*   **Phase 5 (`t3_sepa_features`)**: Completely sparse. Intentionally restricted to compute the 90 complex features (advanced TS alphas, velocity metrics, M03 regimes) **only** for tickers that have triggered a SEPA setup (`trend_ok AND breakout_ok`).

**Resulting State**: `t3_sepa_features` contains only ~13 to 100 rows per day.

## 3. The Core Conflict
The current XGBoost model (`M01`) was designed exclusively as an **Entry Quality Gate**. Because the data pipeline only materializes the 90 model features on the exact day of a breakout, it is structurally impossible to evaluate the model's score on Day 2, Day 3, or Day 10 of a holding period.

To feed the 90 features into the daily holding dataframe, the data must exist in the database. Because of the Phase 5 sparsity design, it currently does not.

## 4. Proposed Solution: Making T3 Dense
Despite the original design, we have discovered that DuckDB actually computes all the complex window functions across the entire 2,400-ticker universe in memory, but simply discards 95% of them at the very last step. 

If the goal is to shift the strategy from "Entry Quality Scoring" to "Continuous Dynamic Scoring," we can safely implement the following:

1.  **Drop the Sparsity Filter**: Remove the `AND t2.trend_ok = TRUE AND t2.breakout_ok = TRUE` filter from the final CTE in `src/feature_pipeline.py`.
2.  **Storage Impact**: `t3_sepa_features` will expand from ~100k rows to ~3.5 million rows. (Easily handled by DuckDB).
3.  **Compute Impact**: Minimal. DuckDB handles the 3.5M inserts trivially, and the subsequent Python scripts (volatility adjustments, TS alphas) are already vectorized to process the full universe.
4.  **Training Integrity**: Preserved. The downstream ML training view (`v_d1_candidates`) natively reapplies the `trend_ok AND breakout_ok` filter. This ensures the XGBoost model is still trained *only* on valid breakout setups, protecting the integrity of the training dataset.

## 5. Decision Required
We must explicitly decide whether to pivot the pipeline's architectural intent:

*   **Option A (Original Design)**: Keep T3 sparse. Accept that the XGBoost model is strictly an entry filter. The daily holding dataframe will carry the static "Entry Score" but cannot track dynamic feature evolution.
*   **Option B (Pivot to Dense)**: Implement the plan to make T3 dense, allowing the model to act as a continuous daily signal across the entire holding period.
