# Replace M03/5F Risk with the 6-Pillar Macro Dashboard

This plan outlines the steps to replace the legacy aggregated regime models on the Streamlit dashboard with a clear, orthogonal 6-Pillar Macro view. 

## Open Questions

> [!WARNING]
> **CAPE & Real Yield Data Sources**
> Currently, the production database (`macro_data`) contains the 10-Year Treasury (`DGS10`), but not the 10-Year Real Yield (`DFII10`) or the Shiller CAPE valuation ratio (which was sourced directly from Yale's website in the research phase). 
> **Question:** Should I dynamically fetch these missing series on-the-fly in the dashboard (using the `pandas_datareader` FRED API / Yale XLS), or should I approximate them using existing database fields (e.g., using Nominal 10-Year `DGS10` for Rates, and leaving CAPE out until the data pipeline is updated)? I recommend dynamic fetching with caching so the dashboard is immediately complete.

## Proposed Changes

### 1. `scripts/dashboard_utils.py`
We will add new data loaders to pull and calculate the 6 pillars:
- **Fast Risk (All-Time Percentiles):**
  - **Equity Fear (VIX):** Pull directly from `macro_data`.
  - **Credit Stress (HY Spread):** Pull `BAMLH0A0HYM2` from `macro_data`.
  - **Growth Fear (Term Spread):** Calculate `DGS10 - DGS2` from `macro_data`.
- **Slow Fundamentals (5-Year Rolling Percentiles):**
  - **Financial Conditions (Rates):** Dynamically fetch `DFII10` (or use `DGS10`).
  - **Capital Flow (Net Liquidity):** Calculate `WALCL - (WTREGEN + RRPONTSYD)` from `macro_data`.
  - **Valuation (CAPE):** Dynamically fetch the Shiller CAPE ratio.
- Implement the rolling/expanding percentile logic directly in the utility so the dashboard receives normalized `[0, 100]` values.

### 2. `scripts/dashboard.py`
We will rip out the legacy visualizations and build the new two-panel layout:
#### [DELETE] Legacy Components
- Remove `render_regime_header`
- Remove `render_risk_5f_header`
- Remove `render_regime_history`
- Remove `render_risk_history`
- Remove `render_risk_position`

#### [NEW] `render_macro_dashboard()`
Create a new layout with two side-by-side columns:
- **Left Panel (Snapshot Bar Chart):**
  - A Plotly horizontal bar chart displaying the latest percentile (`0-100`) for all 6 pillars.
  - Bars will be color-coded (e.g., Green for benign / <40, Yellow for elevated / 40-75, Red for extreme / >75).
- **Right Panel (Historical Line Chart):**
  - A time-series Plotly line chart.
  - A multiselect dropdown allowing the user to overlay any combination of the 6 pillars.
  - A lookback selector (e.g., 6mo, 1y, 3y).

## Verification Plan

### Automated/Manual Verification
- Run the Streamlit app locally (`streamlit run scripts/dashboard.py`).
- Verify the left panel bar chart renders cleanly and the colors accurately reflect the percentiles.
- Verify the right panel allows toggling the historical lines.
- Ensure the dynamic fetching of CAPE/FRED data (if chosen) does not significantly lag the page load (by verifying `@st.cache_data` is working).
