# Milestone 6.2: Pipeline Monitoring Dashboard (Streamlit)

## Context

Milestone 6.1 (Daily Pipeline Orchestration) is complete. The orchestrator writes execution state to `pipeline_runs`, SEPA candidates flow into `t3_sepa_features`, and model versions are tracked in the `models` table via `ModelRegistry`. However, there is **no observability layer** — no way to see pipeline health, monitor trade candidates, or review model evaluations without writing ad-hoc SQL. This dashboard closes that gap.

**Existing `dashboard.py`** is a 1600-line Streamlit app tightly coupled to the old SQLite `buy_list` workflow. It uses `DatabaseManager` (SQLite) and `DataRepository` (parquet/yfinance cache). The new dashboard operates entirely on **DuckDB** (`data/market_data.duckdb`) and the new 4-layer architecture. Starting from scratch is cleaner than refactoring, but we reuse chart helpers and layout patterns.

## Deliverable

**New file**: `scripts/pipeline_monitoring_dashboard.py` (~400-500 lines)

**Run command**: `streamlit run scripts/pipeline_monitoring_dashboard.py`

## Architecture

```
scripts/pipeline_monitoring_dashboard.py
├── get_duckdb_connection()          # @st.cache_resource, read-only
├── render_health_overview()         # Page 1
├── render_trade_candidates()        # Page 2
├── render_model_evaluation()        # Page 3
└── main()                           # Router (sidebar radio)
```

All queries hit DuckDB directly via `duckdb.connect(read_only=True)`. No dependency on `DatabaseManager`, `DataRepository`, or any `src/` module. Pure SQL + Streamlit + Plotly.

---

## Page 1: Pipeline Health Overview

### Data Sources
- `pipeline_runs` (run_id, target_date, phase_name, status, runtime_seconds, error_message)
- `t3_sepa_features` (ticker, date — for breakout counts)
- Data freshness: MAX(date) from `price_data`, `t2_screener_features`, `t3_sepa_features`

### Layout
```
┌─────────────────────────────────────────┐
│  4 Metric Cards (st.metric)             │
│  - Total Runs (30d)                     │
│  - Success Rate (%)                     │
│  - Avg Runtime (seconds)                │
│  - Breakouts Today                      │
├─────────────────────────────────────────┤
│  Data Freshness Table                   │
│  - Table | Max Date | Gap Days          │
│  - Flags if gap > 2 trading days        │
├─────────────────────────────────────────┤
│  Pipeline Run History (st.dataframe)    │
│  - target_date | phase | status |       │
│    runtime_s | error_message            │
│  - Failures highlighted (red background)│
├─────────────────────────────────────────┤
│  Runtime Trend (Plotly line chart)      │
│  - X: target_date, Y: total runtime    │
│  - Horizontal line at 2× avg (warning) │
├─────────────────────────────────────────┤
│  Daily Breakout Count (Plotly bar chart)│
│  - X: date, Y: COUNT(DISTINCT ticker)  │
│  - Last 30 days from t3_sepa_features  │
└─────────────────────────────────────────┘
```

### Key SQL Queries
```sql
-- 1. Run summary (last 30 days)
SELECT COUNT(*) as total_runs,
       SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) as successes,
       AVG(runtime_seconds) as avg_runtime
FROM pipeline_runs
WHERE target_date >= CURRENT_DATE - 30

-- 2. Run history detail
SELECT target_date, phase_name, status, runtime_seconds, error_message
FROM pipeline_runs
WHERE target_date >= CURRENT_DATE - 30
ORDER BY target_date DESC, phase_name

-- 3. Data freshness
SELECT 'price_data' as table_name, MAX(date) as latest_date FROM price_data
UNION ALL
SELECT 't2_screener_features', MAX(date) FROM t2_screener_features
UNION ALL
SELECT 't3_sepa_features', MAX(date) FROM t3_sepa_features

-- 4. Daily breakout counts
SELECT date, COUNT(DISTINCT ticker) as breakouts
FROM t3_sepa_features
WHERE date >= CURRENT_DATE - 30
GROUP BY date ORDER BY date

-- 5. Runtime per day (aggregated across phases)
SELECT target_date, SUM(runtime_seconds) as total_runtime
FROM pipeline_runs
WHERE target_date >= CURRENT_DATE - 30 AND status = 'SUCCESS'
GROUP BY target_date ORDER BY target_date
```

### Warnings/Alerts
- Runtime > 2× average → orange warning banner
- Any `status = 'FAILURE'` in last 7 days → red alert
- 0 breakouts for 5+ consecutive days → yellow warning
- Data freshness gap > 2 business days → red flag in table

---

## Page 2: Trade Candidate Monitoring

### Data Sources
- `t3_sepa_features` (all SEPA breakout candidates with features)
- Delta tracking: compare candidates between consecutive dates

### Layout
```
┌─────────────────────────────────────────┐
│  Date Picker (default: max date in t3)  │
├─────────────────────────────────────────┤
│  3 Metric Cards                         │
│  - Total Candidates on Selected Date    │
│  - New Today (added vs previous day)    │
│  - Removed Today (dropped vs prev day)  │
├─────────────────────────────────────────┤
│  Candidate Table (st.dataframe)         │
│  - ticker | date | rs | natr | close    │
│  - price_vs_sma_50 | price_vs_sma_200  │
│  - volume_ratio | vcp_ratio             │
│  - Sortable by any column              │
│  - New tickers marked with tag          │
├─────────────────────────────────────────┤
│  Added/Removed Summary (2-column)       │
│  - Left: New tickers (green)            │
│  - Right: Removed tickers (red)         │
├─────────────────────────────────────────┤
│  Historical Candidate Count (line chart)│
│  - Last 30 days trend                   │
└─────────────────────────────────────────┘
```

### Key SQL Queries
```sql
-- 1. Available dates (for picker)
SELECT DISTINCT date FROM t3_sepa_features
ORDER BY date DESC LIMIT 60

-- 2. Candidates on selected date
SELECT ticker, date, close, rs, natr, volume_ratio,
       price_vs_sma_50, price_vs_sma_200, vcp_ratio,
       rsi_14, dist_from_52w_high
FROM t3_sepa_features
WHERE date = ? AND feature_version = 'v3.1'
ORDER BY rs DESC

-- 3. New candidates (added today)
SELECT ticker FROM t3_sepa_features WHERE date = ?
EXCEPT
SELECT ticker FROM t3_sepa_features WHERE date = (
    SELECT MAX(date) FROM t3_sepa_features WHERE date < ?
)

-- 4. Removed candidates (dropped today)
SELECT ticker FROM t3_sepa_features WHERE date = (
    SELECT MAX(date) FROM t3_sepa_features WHERE date < ?
)
EXCEPT
SELECT ticker FROM t3_sepa_features WHERE date = ?

-- 5. Historical candidate count (30 days)
SELECT date, COUNT(DISTINCT ticker) as candidates
FROM t3_sepa_features
WHERE date >= CURRENT_DATE - 60
GROUP BY date ORDER BY date
```

### Features
- Date picker defaults to most recent date in `t3_sepa_features`
- Previous date auto-detected (handles weekends/holidays via `MAX(date) WHERE date < selected`)
- New tickers shown with green highlight in main table
- Candidate count trend shows if universe is expanding or contracting

---

## Page 3: Model Evaluation

### Data Sources
- `models` table (version_id, status_flag, specs_json, artifacts_path, metrics)
- Filesystem: `models/artifacts/{version_id}/` (report.md, plots/*.png)
- `ModelRegistry` class methods reused for queries (or direct SQL)

### Layout
```
┌─────────────────────────────────────────┐
│  Dropdown: Select Model Version         │
│  - Format: "M01_v4 [PROD] 2026-03-15"  │
│  - Sorted by created_at DESC            │
├─────────────────────────────────────────┤
│  4 Metadata Cards (st.metric)           │
│  - Status (PROD/TEST/ARCHIVED)          │
│  - Training Date                        │
│  - Feature Version (v3.1)              │
│  - Dataset Rows                         │
├─────────────────────────────────────────┤
│  Metrics Cards (if populated)           │
│  - RMSE | MAE | R² | Spearman          │
├─────────────────────────────────────────┤
│  Specs Expander (JSON viewer)           │
│  - Features list                        │
│  - Hyperparameters                      │
│  - Training config                      │
├─────────────────────────────────────────┤
│  Evaluation Report (st.markdown)        │
│  - Load *.md from artifacts_path        │
│  - Full markdown rendering              │
├─────────────────────────────────────────┤
│  Plots Gallery (2-column grid)          │
│  - Load all *.png from artifacts_path   │
│  - st.image() with captions            │
│  - confusion_matrix, roc_curve, etc.    │
└─────────────────────────────────────────┘
```

### Key SQL Queries
```sql
-- 1. List all model versions (dropdown)
SELECT version_id, status_flag, feature_version,
       training_date, dataset_rows, artifacts_path,
       created_at
FROM models
ORDER BY created_at DESC

-- 2. Get full model details
SELECT version_id, status_flag, specs_json, feature_version,
       training_date, dataset_rows, artifacts_path,
       rmse, mae, r2, spearman_corr
FROM models
WHERE version_id = ?
```

### Artifact Discovery Logic
```python
artifacts_path = Path(model_row['artifacts_path'])

# Find evaluation reports (*.md files)
reports = sorted(artifacts_path.glob("*.md"))

# Find plots (*.png files) - also check plots/ subdirectory
plots = sorted(artifacts_path.glob("*.png")) + sorted(artifacts_path.glob("plots/*.png"))

# Find JSON results
results_files = sorted(artifacts_path.glob("*results*.json"))
```

### Features
- Dropdown shows `{version_id} [{status}] {training_date}` for easy identification
- Production model highlighted with green badge
- Specs JSON displayed in collapsible expander (avoids clutter)
- Report markdown rendered inline
- Plots displayed in 2-column grid with filename as caption
- Graceful handling if artifacts_path doesn't exist or is empty

---

## Files to Create/Modify

| File | Action | Lines |
|------|--------|-------|
| `scripts/pipeline_monitoring_dashboard.py` | CREATE | ~400-500 |

No modifications to existing files needed.

## Dependencies

Already installed (used by `dashboard.py`):
- `streamlit`
- `plotly`
- `duckdb`
- `pandas`

No new dependencies required.

## Key Design Decisions

1. **Separate from `dashboard.py`**: New file, not extending the old dashboard. Different data model (DuckDB vs SQLite), different purpose (monitoring vs trading).
2. **Read-only DuckDB connection**: Dashboard never writes. Safe to run concurrently with pipeline.
3. **No `src/` imports**: Pure SQL queries. Avoids import chain issues and keeps the dashboard lightweight.
4. **Exception**: `ModelRegistry.get_artifacts_path()` pattern reused as inline SQL (no class import needed).

## Reusable Patterns from `dashboard.py`

| Pattern | Source Location | Usage in New Dashboard |
|---------|----------------|----------------------|
| `@st.cache_resource` for DB | `dashboard.py:33-39` | DB connection caching |
| Sidebar radio navigation | `dashboard.py:1541-1555` | Page routing |
| `st.metric` cards layout | `dashboard.py:990-1026` | All 3 pages |
| Plotly bar chart pattern | `dashboard.py:1049-1075` | Breakout/runtime charts |
| Dataframe with formatting | `dashboard.py:445-451` | All tables |

## Verification

```bash
# 1. Start the dashboard
streamlit run scripts/pipeline_monitoring_dashboard.py

# 2. Verify Page 1 (Pipeline Health)
# - Metric cards show non-zero values (if pipeline has been run)
# - Data freshness table shows dates for all 3 tables
# - Run history table loads with pipeline_runs data
# - Charts render without errors

# 3. Verify Page 2 (Trade Candidates)
# - Date picker shows available dates
# - Candidate table shows SEPA tickers with features
# - New/removed delta metrics work
# - Historical trend chart loads

# 4. Verify Page 3 (Model Evaluation)
# - Dropdown populated from models table
# - Selecting a model shows metadata cards
# - Evaluation report renders (if artifacts exist)
# - Plots display in grid (if *.png files exist)
# - Graceful handling if no artifacts found

# 5. Performance check
# - Each page loads in < 2 seconds
# - No errors in Streamlit console
```

## Estimated Time: 3 hours
- 1 hour: Page 1 (Pipeline Health)
- 1 hour: Page 2 (Trade Candidates)
- 1 hour: Page 3 (Model Evaluation)
