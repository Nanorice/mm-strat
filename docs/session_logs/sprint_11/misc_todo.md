# Miscellaneous To-Do List

This document outlines various tasks grouped by category, expanded with specific plans for investigation and implementation for each item.

## Execution Priorities
1. **High Priority (Data Quality & Model Impact):** 
   - ✅ Fundamentals update audit table (missing 'filed' date) — DONE 2026-05-29 (SEC EDGAR backfill, 97.73% coverage)
   - T1 ingestion failures
   - ✅ Pipeline Health Page data freshness (stale tables) — DONE 2026-05-29 (macro_data wired into daily orchestrator)
   - Calibrate prototype model
2. **Medium Priority (Observability):** 
   - Pipeline Health Page: Audit history
   - Pipeline Runs (last 30d) plot formatting and color criteria
3. **Low Priority (Dashboard Visualizations & UI Polish):** 
   - Multicollinearity plot cleanup
   - Feature signal bar chart colors
   - Universe activity formatting
   - Active density by class plot
   - Forward-Return profile explanation
4. **Long Term / Strategic:** 
   - Fundamental engine investigation
   - Eval framework phase 4
   - Risk: 5-Factor model improvements
   - Model card with longer period

## 1. Dashboard Visualizations & UI

### Active Density by Class Plot
* **Issue:** There is a large bar at the end of the plot for the 'elite' class. Is this due to a bad ticker?
* **Investigation Plan:** Query the underlying data feeding the 'elite' class density plot to identify the specific tickers or data points contributing to the large bar at the tail end. Check for outliers, bad data, or a genuine accumulation of extreme values.
* **Implementation Plan:** Filter or handle outliers if they are caused by erroneous data. If the data is legitimate, adjust the x-axis limits, apply a log scale, or bin the tail end into a "+X" bucket to improve readability.

### Multicollinearity Plot
* **Issue:** The plot is very messy and hard to read.
* **Investigation Plan:** Review the current correlation matrix/heatmap. Check if there are too many features being displayed simultaneously or if the color scale fails to highlight important relationships.
* **Implementation Plan:** Apply hierarchical clustering to group correlated features. Set a correlation threshold (e.g., > 0.7 or < -0.7) to only display or highlight strong correlations. Simplify labels and consider a cleaner visualization library.

### Feature Signal Bar Chart
* **Issue:** The chart is too colorful, and the colors do not convey any meaning that isn't already obvious from the chart axes.
* **Investigation Plan:** Inspect the chart configuration to determine how colors are assigned (e.g., categorical coloring by feature name).
* **Implementation Plan:** Switch to a uniform color or use a meaningful color gradient (e.g., positive signals in green, negative in red, or color intensity based on signal magnitude). Remove redundant legends.

### Universe Activity
* **Issue:** Formatting makes new SEPA additions per week almost invisible.
* **Investigation Plan:** Check the data scaling and formatting. New additions are likely dwarfed by the total universe size when plotted on the same axis.
* **Implementation Plan:** Use a secondary y-axis for new additions, change the plot type (e.g., switch from a stacked bar to a grouped bar or line chart), or adjust the scale to highlight weekly marginal changes.

### Forward-Return Profile
* **Issue:** Unclear what the plot population is, and every bin strangely shows a positive forward return.
* **Investigation Plan:** Audit the data filtering, joining logic, and binning strategy for the forward-return plot. Check if survivorship bias, a specific bullish time period, or calculation errors are skewing the population.
* **Implementation Plan:** Correct the underlying query if biases or errors are found. Add a baseline (e.g., market average return for the period) to the plot for context. Explicitly document the population criteria in the chart subtitle or tooltip.

### Pipeline Runs (last 30d) Plot
* **Issue:** The plot has uneven bar widths for each day. Additionally, what is the criteria for a run to be colored green, given there are active warnings on T1 price and fundamentals?
* **Investigation Plan:** Inspect the plotting code (e.g., bar width settings, time-axis alignment) to determine why the widths are uneven. Review the status logic deciding the bar's color (green vs. yellow/red) and verify why T1 price/fundamental warnings are not triggering a non-green state.
* **Implementation Plan:** Standardize the bar widths (e.g., by ensuring evenly spaced date indices). Adjust the color-coding logic to properly reflect partial failures/warnings (e.g., using yellow for warnings) instead of just checking for catastrophic pipeline failures.

---

## 2. Data Pipeline & Data Quality

### Pipeline Health Page: Data Freshness ✅ DONE 2026-05-29
* **Original framing (incorrect):** Both `earnings_calendar` and `macro_data` showing stale; assume broken update jobs.
* **Actual diagnosis:**
  * `earnings_calendar` — NOT stale. Tolerance of `-200` correctly handles future-looking dates; was a UI false positive.
  * `macro_data` — Genuinely stale (17 days), but the cause was wrong table being written. Orchestrator's Phase 1 macro step called `ingest_daily_macro()` which only writes to `t1_macro` (wide: SPY/QQQ/VIX OHLCV). The long-format `macro_data` table (consumed by `risk_5_factor` and `m03_regime`) had no daily writer wired up — `write_to_macro_data` was only callable via the legacy `scripts/backfill_macro_rates.py`.
  * Downstream impact: `t2_risk_scores` and m03 regime computations were silently using 17-day-old macro data for ~3 weeks.
* **Fix (Option A — minimal):** [src/orchestrators/daily_pipeline_orchestrator.py:693-732](../../../src/orchestrators/daily_pipeline_orchestrator.py#L693-L732) now calls both `ingest_daily_macro()` and `update_macro_cache(write_db=True)` and reports correct row counts for each table.
* **Catch-up:** Manual `update_macro_cache` run brought all 8 series (WALCL/WTREGEN/RRPONTSYD/BAMLH0A0HYM2/DGS10/DGS2/WBAA/VIX) to within ~1 day of current.
* **Dashboard tweak:** `macro_data` freshness tolerance bumped 2d → 8d ([scripts/pages/5_Pipeline_Health.py:44](../../../scripts/pages/5_Pipeline_Health.py#L44)) — weekly series (WALCL/WTREGEN/WBAA) were flashing false-positive stale.
* **Known limitation (not fixed):** the freshness panel uses one tolerance per table, but `macro_data` is long-format with mixed daily/weekly frequencies. Per-symbol freezes would still be hidden. Acceptable for now; revisit if it bites.

### T1 Ingestion Failures
* **Issue:** Ingestion failures on price (~20 tickers) and fundamentals (~1.5k tickers).
* **Reality check (2026-05-29):** The dashboard's "~20 / ~1.5k" framing significantly understates price-side failures and overstates fundamentals-side. `pipeline_error_log` for last 30d:
  * `phase_1_t1_price`: **9,570 errors across 3,688 tickers** — most are transient yfinance 429s, not chronic.
  * `phase_1_t1_fundamentals`: 213 errors across 188 tickers — much smaller cohort than expected.
  * Active equity fundamentals staleness: 3,549/3,981 within 100d, 369 in 101-200d (real investigation cohort), 62 >200d (likely delisted).
* **Investigation Plan:** 
  * Reconcile the dashboard's "20 / 1.5k" headline numbers against `pipeline_error_log` — likely a window/grouping mismatch.
  * *Price:* bucket errors by `error_type` first; chronic 429s indicate yfinance throttling at scale, not bad tickers. `tools/deactivate_tickers.py` is the right vehicle once we confirm true delistings.
  * *Fundamentals:* the 369-ticker 101-200d cohort is the real action — check whether they have CIKs in `cik_map` (could be a forwarding-address ticker rename issue).
* **Implementation Plan:** triage existing errors first; only then add bulk-mark-delisted / patch logic. Avoid blind bulk action.

### Fundamentals Update Audit Table ✅ DONE 2026-05-29
* **Original framing (incorrect):** Assumed broken mapping logic — fix the transform.
* **Actual diagnosis:** Mapping logic was fine. Two real causes:
  1. **Path was the wrong source.** Existing `_fetch_filing_dates_for_ticker` round-trips yfinance live for each ticker, ignoring our local `earnings_calendar` table (which already has the data for ~570 tickers).
  2. **earnings_calendar itself is sparse** — only **570 / 3,981 active equities** have any entries. The orchestrator's `phase_1_earnings_calendar_refresh` ran exactly once (2026-05-27), took 9.6 min, and wrote **0 rows** for 3,744 attempted tickers — yfinance silently rate-limits at scale.
  3. The fundamental issue is that yfinance is the wrong primary source for authoritative filing dates. SEC EDGAR is.
* **Three-stage fix shipped:**
  1. **Stage 1 (low-hanging):** `backfill_filing_dates_from_calendar` — SQL-only path that uses the local `earnings_calendar` table without yfinance round-trips ([src/fundamental_engine.py:508-580](../../../src/fundamental_engine.py#L508-L580)). Updated 244 rows from existing local data.
  2. **Stage 2 (the real fix):** New `EDGAREngine` ([src/edgar_engine.py](../../../src/edgar_engine.py)) querying SEC's `data.sec.gov/submissions/CIK*.json` directly. Matches `reportDate ≈ period_end` within ±15 days, gap guard ≥8 days. Authoritative source. **Updated 3,068 rows across 2,516 tickers in 8 minutes.** Coverage 42.9% → **97.73%**.
  3. **Stage 3 (orchestrator wiring):** Daily pipeline now runs `phase_1_cik_map_refresh` (weekly, gated) and replaced `phase_1_filing_date_backfill` to use EDGAR. ([src/orchestrators/daily_pipeline_orchestrator.py:739-859](../../../src/orchestrators/daily_pipeline_orchestrator.py#L739-L859))
* **Residual 143 NULL rows breakdown:**
  * 95 — active tickers with CIK but EDGAR `reportDate` outside ±15d tolerance (fiscal-calendar mismatch — e.g. AZO has Aug fiscal year-end)
  * 41 — active, no CIK in EDGAR (foreign ADRs, SPACs, OTC) — architectural floor
  * 7 — inactive tickers
* **Files added/touched:**
  * NEW: [src/edgar_engine.py](../../../src/edgar_engine.py) (EDGARClient + EDGAREngine)
  * NEW: [scripts/backfill_filing_dates_edgar.py](../../../scripts/backfill_filing_dates_edgar.py) (CLI)
  * NEW DuckDB table: `cik_map` (10,365 rows)
  * Edited: [config.py](../../../config.py) (EDGAR_*, CIK_MAP_REFRESH_DAYS, failure modes)
  * Edited: [src/fundamental_engine.py](../../../src/fundamental_engine.py) (Stage 1 calendar backfill)
  * Edited: [src/orchestrators/daily_pipeline_orchestrator.py](../../../src/orchestrators/daily_pipeline_orchestrator.py) (cik_map refresh + EDGAR backfill phases)
* **Note on `EDGAR_USER_AGENT`:** defaults to a placeholder. Set a real `EDGAR_USER_AGENT="Your Name your@email"` in `.env` before next daily run.
* **Out-of-scope discovery — earnings_calendar refresh is broken at scale.** The path that *should* keep `earnings_calendar` current silently fails for ~3,400 of 3,981 active equities (yfinance rate-limit at parallelism). It's now less critical because filing_date no longer depends on it, but **the upcoming-earnings trigger for fundamentals refresh** still uses it. If a ticker doesn't get into `earnings_calendar`, the daily pipeline won't know to re-pull its fundamentals after a reporting event — falls back to the 100-day staleness check. Worth a separate investigation later.

### Pipeline Health Page: Audit History
* **Issue:** The audit history shows only 1 data point, and there are no additions from recent daily pipeline runs.
* **Investigation Plan:** Check the database append/upsert logic for the audit history table. It appears recent runs are either overwriting the same row or silently failing to insert new rows.
* **Implementation Plan:** Change the database operation from overwrite/upsert to append for the audit history table. Ensure the pipeline script correctly logs a new entry upon each successful or failed run completion.

### Fundamental Engine Investigation
* **Issue:** Needs general investigation/review.
* **Investigation Plan:** Define the specific performance, accuracy, or efficiency bottlenecks currently suspected in the fundamental engine. Review execution logs, query times, and resource usage.
* **Implementation Plan:** Refactor inefficient queries, add necessary database indices, optimize memory usage, or parallelize processing based on findings.

---

## 3. Model & Evaluation

### Calibrate Prototype Model
* **Issue:** The prototype model requires calibration.
* **Investigation Plan:** Analyze the current prototype model's output probabilities versus actual outcomes using reliability diagrams. Determine if the model is systematically overconfident or underconfident.
* **Implementation Plan:** Apply calibration techniques such as Platt scaling or Isotonic regression. Validate calibration improvements on a holdout validation set.

### Model Card with Longer Period
* **Issue:** The model card needs to be generated over a longer historical period.
* **Investigation Plan:** Review the current model card generation script. Identify hardcoded dates or limited datasets. Verify data availability and consistency for the desired longer time frame.
* **Implementation Plan:** Update the script to ingest the longer time frame. Re-generate the model card metrics (Sharpe, drawdown, etc.) over this extended period and review the outputs for consistency.

### Risk: 5-Factor Model
* **Issue:** Clarify Z-score memory, consider adding more factors, clarify what the output numbers mean, show factor weights, and try combining factors.
* **Investigation Plan:** Investigate the current Z-score memory mechanism to understand its behavior. Analyze the current 5 factors to see if they capture enough variance. Determine the mathematical representation of the current output numbers.
* **Implementation Plan:** Add documentation explaining the meaning of the output numbers. Add visualizations to show the weight/contribution of each factor in the UI. Experiment with combining existing factors or adding new macroeconomic/statistical factors. Refine the Z-score memory implementation.

### Eval Framework Phase 4
* **Issue:** Needs implementation/planning for Phase 4.
* **Investigation Plan:** Review the requirements document or previous architectural discussions for Phase 4 of the evaluation framework. Identify the specific metrics or capabilities missing (e.g., real-time tracking, advanced attribution analysis).
* **Implementation Plan:** Develop and integrate the Phase 4 features into the eval framework codebase. Write unit tests and generate sample reports to verify the new functionality.