# Dashboard Module Passport

## 1. Overview
* **Responsibility:** The TradeOps Dashboard is the primary user interface for the quantitative trading system. It visualizes scanner results, manages the "buy list," displays historical analytics, and renders detailed performance reports for ML models (M01, M02, M03). It serves as the "Control Center" for daily trading operations.
* **Key Dependencies:** 
    * **Internal:** `src.database`, `src.data_engine`, `src.pipeline` (regime calc), `src.features`, `src.ml_scorer`.
    * **External:** `streamlit` (UI framework), `plotly` (charts), `pandas`.

## 2. File Structure

| File | Purpose |
|------|---------|
| `dashboard.py` | **Entry Point**. Orchestrates the application, defines the sidebar navigation, and implements core trading pages (Signal Review, Manual Override, History). |
| `src/dashboard_reports.py` | **Report Renderer**. Contains logic to render static ML performance reports (D1, M01, M02, Backtest) by loading pre-generated JSON/CSV files. |

## 3. Data Schemas

### Database Tables (Implied Usage)
The dashboard interacts heavily with the SQLite `buy_list` and `buy_list_activity` tables.

| Table | Key Columns Used | Purpose |
|-------|------------------|---------|
| `buy_list` | `ticker`, `signal_date`, `final_score`, `final_score_rank`, `m01_expected_return`, `m02_survival`, `m02_loser_proba` | Active signals displayed in "Signal Review". |
| `buy_list_activity` | `action_date`, `ticker`, `action` (ADDED/REMOVED/TRADED), `reason`, `entry_price` | Source for "History & Analytics" timeline. |

### Configuration Files (JSON)
Reports in `dashboard_reports.py` expect specific JSON structures in the `models/` directory.

| File Pattern | Key Fields | Used By |
|--------------|------------|---------|
| `*_config.json` | `validation_metrics` (array), `feature_columns` (list), `model_type` | M01/M02 Reports |
| `d1_analysis.json` | `total_trades`, `median_mfe`, `median_mae`, `crash_rate`, `mae_mfe_scatter` | D1 Analysis Page |
| `d3_summary.json` | `tp_rate`, `sl_rate`, `time_rate` | M02 Report (Triple Barrier) |

## 4. Implementation Rules

### Position Sizing Logic
* **Formula:** `shares = int((config.INITIAL_CAPITAL * config.POSITION_SIZE_PCT) / entry_price)`
* **Constraint:** Uses fixed fractional capital sizing based on `config.POSITION_SIZE_PCT`. The comment mentions "8% max loss per position," implying that if the stop loss is hit, the loss should not exceed ~8% of the *position value* (depending on `STOP_LOSS_PCT`), or possibly 8% of *account equity* if configured aggressively. (Code reference: `dashboard.py` L818)

### Manual Override Math
* **Target Price:** automatically calculated as `entry_price * (1 + config.PROFIT_TARGET_R * config.STOP_LOSS_PCT)`.
* **Stop Price default:** `entry_price * (1 - config.STOP_LOSS_PCT)`.
* **ML Probability:** Manual entries are assigned `ml_probability = 1.0`.

### M03 Regime Gating
* **Logic:** The dashboard checks `M03RegimeCalculator.should_gate_signal()`.
* **Visuals:**
    * **RED (Block)**: `allow_longs=False` → "⛔ Long Signals BLOCKED"
    * **ORANGE (Caution)**: `reduced_sizing=True` → "⚠️ Reduced Position Size"
    * **GREEN (Go)**: Otherwise → "✅ Full Risk On"

### Performance caching
*   **Data Loading:** `load_model_config`, `load_latest_report`, etc. use `@st.cache_data(ttl=60)` to prevent disk I/O on every interaction, refreshing every 60 seconds.
*   **Resource Objects:** Database and DataRepository are cached with `@st.cache_resource` to maintain persistent connections.

## 5. Public Interface

### Entry Point
*   **`dashboard.py`**: Run via `streamlit run dashboard.py`. The `main()` function is the application router.

### Report Renderers (`src/dashboard_reports.py`)
These functions are called by the main router to display specific analysis pages.

| Function | Page Name | Description |
|----------|-----------|-------------|
| `render_d1_analysis()` | D1 Analysis | Displays "Trade Physics" (MAE/MFE, E-Ratio) from `d1_analysis.json`. |
| `render_m01_report()` | M01 Report | Visualizes regression performance (Edge, RMSE, Deciles) for M01. |
| `render_m02_report()` | M02 Report | Visualizes classification performance (AUC, Triple Barrier) for M02. |
| `render_dual_model()` | Dual-Model | Comparative view of M01 and M02 metrics side-by-side. |
| `render_backtest()` | Backtest | *Placeholder* for future backtest results. |
