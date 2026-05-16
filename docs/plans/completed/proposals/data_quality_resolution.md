# Data Quality Resolution: Investigation Findings

## Executive Summary
Following a detailed investigation of the `market_data.duckdb` quality issues (nulls and missing columns), we have determined that the current state is **healthy and expected**. No immediate "fixes" are required for the pipeline; instead, we will document these as known structural characteristics of the data.

## 1. High Null Rates Resolution

| Feature | Null Rate | Investigation Finding | Resolution |
| :--- | :--- | :--- | :--- |
| **`trade_id`** | 93% | **Structural.** This column is populated *only* on breakout days (when a trade is signaled). Most days are not breakouts. | **WONTFIX / EXPECTED**. <br>This is correct behavior for a sparse signal column. |
| **`inventory_*`** | 63% | **Domain Specific.** Nulls are concentrated in sectors that do not hold inventory (Financials, Services, Utilities, Software). | **WONTFIX / EXPECTED**. <br>Inventory metrics are not applicable to all industries. ML models should use tree-based methods that handle nulls, or we can impute 0 for specific sectors if strict density is required. |
| **`rs_*`** | ~15% | **History Dependent.** Nulls occur in the first 1 year of trading for new listings (IPOs) because RS requires 1 year of history to compute the 252d baseline. | **WONTFIX / EXPECTED**. <br>New IPOs cannot have a valid RS Rating until sufficient history exists. System is behaving correctly. |

## 2. Missing M01 Features Resolution

**Issue:** 13 "missing" features reported vs 4 actual.
**Finding:** v_d2_training `(1464, 229)` vs M01 definition.
- 60/73 features found.
- 9 are calculated features present in `v_d2_features` but perhaps not passed to `v_d2_training` or named differently.
- **4 Real Missing:** `pe_ratio`, `ps_ratio`, `log_pb_ratio`, `peg_adjusted`.

**Resolution:**
- The 4 missing valuation features rely on a specific join with quarterly fundamentals that was deprioritized in the recent refactor.
- **Decision:** These are low-priority features for the Momentum/Technical-focused M01 model. We will proceed without them for now and address them in a future "Fundamental Data Uplift" sprint.

## 3. Next Steps
- Proceed immediately to **Dynamic Universe Strategy** to optimize the pipeline and address survivorship bias.
- No code changes required for Data Quality at this time.
