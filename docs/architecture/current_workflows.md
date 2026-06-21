# Current System Architecture & Workflows

This document outlines the architecture and workflows of the current Quantamental trading system as of February 2024.

## Core Components

The system is built around a file-based architecture (Parquet/CSV) with Python scripts orchestrating data flow and analysis.

### 1. Data Layer (`DataRepository`)
- **Storage**: Local filesystem (`data/price/*.parquet`, `data/fundamentals/`, etc.).
- **Access**: `src.data_engine.DataRepository` class manages caching and API fetching (FMP).
- **Format**: 
    - **Price**: Individual Parquet files per ticker.
    - **Fundamentals**: Parquet files.
    - **Universe**: Scalable `universe.parquet` file (managed by `UniverseEngine`).

### 2. Processing Layer (`ModelRunner` / `DataPipeline`)
- **Engine**: Python (Pandas/NumPy).
- **Pipeline Stages**:
    - **D1 (Scan)**: Raw trade candidates based on trend templates (SEPA).
    - **D2 (Features)**: Feature-rich dataset with technicals, fundamentals, and macros.
    - **D2R (Hydrated)**: D1 candidates hydrated with full forward/backward price action for labeling (e.g., MFE/MAE).
    - **D3 (Labeled)**: Training dataset with targets aimed at ML models.

### 3. Execution Layer (`DailyScanner`)
- **Scanner**: `daily_scanner.py` runs daily operations.
- **Database**: SQLite (`data/trading_system.db`) for tracking buy lists, signals, and portfolio state.
- **Models**: Scikit-learn/XGBoost models stored in `models/`.

---

## Workflow 1: Research & Backtesting

This workflow is used for strategy development, model training, and historical validation.

**Execution Flow:**
```
1. Data Curation       -> 2. Data Pipeline (D1/D2) -> 3. Feature Selection -> 4. Model Training -> 5. Backtesting
(data_curator.py)         (model_runner.py)           (model_runner.py)       (model_runner.py)    (run_backtest.py)
```

### Step 1: Data Curation
**Script**: `data_curator.py`
- **Input**: Universe source (e.g., S&P 500, FMP Screener).
- **Process**: 
    - Fetches/Updates price history for all tickers.
    - Updates fundamental data.
    - Updates macro data (FRED/VIX).
- **Output**: Updated Parquet files in `data/`.

### Step 2: Data Pipeline Build (D1 -> D2)
**Script**: `model_runner.py data --steps scan features hydrate`
- **Scan (D1)**: Scans historical data for trend templates.
    - Output: `data/pipeline/d1_scan.parquet` (List of Ticker/Date pairs).
- **Features (D2)**: Calculates features for all D1 points.
    - Uses `FeatureEngineer` (Python-based).
    - Output: `data/pipeline/d2_features.parquet`.
- **Hydrate (D2R)**: Attaches future/past price action for target calculation.
    - Output: `data/pipeline/d2r_hydrated.parquet`.

### Step 3: EDA & Feature Selection
**Script**: `model_runner.py --steps eda` or `workflow`
- **Process**:
    - Analyzes D2 features against targets.
    - Runs correlation analysis, mutual information, etc.
- **Output**: `eda_report.md`, `selected_features.json`.

### Step 4: Model Training (M01/M02)
**Script**: `model_runner.py m01 --steps train` (or `run_m01_ablation_study.py`)
- **Process**:
    - Loads D2/D2R.
    - Calculates targets (e.g., `log_hybrid`, `return_pct`).
    - Trains model (XGBoost/LGBM).
    - Runs cross-validation.
- **Output**: Trained model artifact (`models/m01.json`), Metrics report.

### Step 5: Backtesting
**Script**: `run_backtest.py`
- **Process**:
    - **Preparation**: Pre-calculates signals/scores for entire history (`prepare_data`).
    - **Execution**: Simulates trading day-by-day (`SEPABacktestRunner`).
    - **Logic**: Portfolio construction, position sizing, exit rules.
- **Output**: Equity curve, trade logs, performance metrics (`backtests/run_name/`).

---

## Workflow 2: Daily Operations

This workflow runs every trading day after market close to generate buy signals for the next day.

**Execution Flow:**
```
1. Data Curation -> 2. Daily Scanner -> 3. Database Update
(data_curator.py)   (daily_scanner.py)    (SQLite)
```

### Step 1: Daily Update
**Script**: `daily_scanner.py` calls `data_curator` functions internally.
- **Process**:
    - Updates universe (if needed).
    - Incremental update of prices (latest day).
    - Checks for new earnings/fundamentals.

### Step 2: Scanning & Feature Calculation
**Script**: `daily_scanner.py`
- **Process**:
    - Loads latest data window (requires lookback for features).
    - **Batch Feature Calc**: Uses `FeatureEngineer` + `AlphaEngine` (threaded) to compute features in Python.
    - **Screening**: Applies SEPA trend templates (`SEPAStrategy`).
    - **ML Scoring**: Runs `ProductionScorer` (M01 + M02) on candidates.
- **Output**: List of qualified setups with ML scores.

### Step 3: Review & Execution
- **Process**:
    - Valid candidates are written to `buy_list` table in SQLite.
    - `dashboard.py` (Streamlit) visualizes the results for human review.
