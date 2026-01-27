---
title: Data Pipeline
type: component
layer: model_runner
status: stable
created: 2026-01-27
tags:
  - data
  - pipeline
  - orchestration
  - ml
dependencies:
  - "[[07_Data_Layer]]"
  - "[[08_Strategy_Layer]]"
  - "[[06_Feature_Config]]"
---

# Data Pipeline

**File:** [src/pipeline/data_pipeline.py](../../src/pipeline/data_pipeline.py)
**Class:** `DataPipeline`

← [[01_Model_Runner_Suite|Back to Suite Overview]]

---

## Purpose

The `DataPipeline` class orchestrates **all data preparation steps** for ML training. It manages the transformation from raw market data to ML-ready datasets:

**D1 → D2 → D2R → D3**

---

## Constructor

```python
DataPipeline(output_dir: str = 'data/ml')
```

**Parameters:**
- `output_dir` - Directory for saving dataset files (default: `data/ml`)

**Example:**
```python
from src.pipeline import DataPipeline

pipeline = DataPipeline()  # Uses default data/ml directory
```

---

## Core Methods

### 1. scan() - Generate Trade Candidates

**Purpose:** Run SEPA screener over historical dates to identify trade candidates

**Signature:**
```python
scan(
    start_date: str,
    end_date: str,
    threshold: float = 15.0,
    save: bool = True
) -> pd.DataFrame
```

**Parameters:**
- `start_date` - Simulation start date (YYYY-MM-DD)
- `end_date` - Simulation end date (YYYY-MM-DD)
- `threshold` - Success threshold in % (default: 15.0)
- `save` - Save result to d1.parquet (default: True)

**Returns:**
- DataFrame with columns: `[date, ticker, label, return_pct, days_held, exit_reason]`

**Output File:** `data/ml/d1.parquet`

**Dependencies:**
- [[07_Data_Layer#DataRepository|DataRepository]] - Loads price data
- [[08_Strategy_Layer#SEPAStrategy|SEPAStrategy]] - Screening logic
- [[08_Strategy_Layer#Trade Simulator|FastTradeSimulator]] - Historical simulation

**Example:**
```python
d1 = pipeline.scan('2018-01-01', '2023-12-31', threshold=15.0)
# Output: 14,523 trades
# Win rate: 38.2% (5,548 wins)
```

**What It Does:**
1. Loads benchmark data (SPY) for market regime
2. Runs SEPA screener on each trading day
3. Simulates trades with SEPA exit rules
4. Labels trades as win (>15%) or loss (<15%)
5. Saves to parquet for next step

---

### 2. features() - Add ML Features

**Purpose:** Enrich D1 trades with ML features at entry date

**Signature:**
```python
features(
    d1: pd.DataFrame,
    n_jobs: int = -1,
    save: bool = True
) -> pd.DataFrame
```

**Parameters:**
- `d1` - DataFrame from `scan()` step
- `n_jobs` - Parallel workers (-1 = all CPUs)
- `save` - Save result to d2.parquet (default: True)

**Returns:**
- DataFrame with trade info + ~150 ML features

**Output File:** `data/ml/d2.parquet`

**Dependencies:**
- [[06_Feature_Config|Feature Config]] - Feature definitions (M01_FEATURES)
- `FeatureEngineer` - Computes technical indicators
- `FundamentalMerger` - Adds fundamental metrics

**Example:**
```python
d2 = pipeline.features(d1, n_jobs=-1)
# Output: 14,240 trades with 152 features
# Processing time: ~180s (parallel)
```

**Processing Steps:**
1. Load price data for all tickers (from cache)
2. Compute lightweight features (RSI, MACD, ATR) in parallel
3. Compute heavyweight features (RS Rating, sector metrics)
4. Merge fundamental data (EPS growth, margins)
5. Extract feature snapshot at each trade's entry date
6. Merge with D1 labels

**Feature Categories:**
- **Technical:** RSI, MACD, Bollinger Bands, nATR
- **Price Structure:** Support/resistance levels, consolidation
- **Alpha Factors:** Momentum, mean reversion, volume patterns
- **Fundamental:** EPS growth, profit margins, debt ratios

---

### 3. hydrate() - Multi-Day Trajectories

**Purpose:** Expand each trade from single entry snapshot to multi-day trajectory

**Signature:**
```python
hydrate(
    d1: pd.DataFrame,
    horizon_days: Optional[int] = None,
    n_jobs: int = -1,
    save: bool = True
) -> pd.DataFrame
```

**Parameters:**
- `d1` - DataFrame from `scan()` step
- `horizon_days` - Fixed horizon in days (None = use SEPA exit)
- `n_jobs` - Parallel workers (-1 = all CPUs)
- `save` - Save result to d2r_*.parquet (default: True)

**Returns:**
- Long-format DataFrame (one row per trade-day)

**Output Files:**
- `data/ml/d2r_sepa.parquet` (if horizon_days = None)
- `data/ml/d2r_120d.parquet` (if horizon_days = 120)

**Dependencies:**
- `DatasetRehydrator` - Trajectory generation engine
- `FeatureEngineer` - Features per day
- `FundamentalMerger` - Fundamental data

**Example:**
```python
d2r = pipeline.hydrate(d1, horizon_days=120, n_jobs=-1)
# Output: 1,187,520 rows (avg 83 days/trade)
# File size: 245 MB
```

**What It Does:**
1. For each trade in D1:
   - Load price data from entry date to exit date (or horizon)
   - Compute features for each day in trajectory
   - Add day_in_trade column (0, 1, 2, ...)
2. Concatenate all trajectories into long-format DataFrame
3. Used by M02 for triple barrier labeling

---

### 4. label() - Triple Barrier Labels

**Purpose:** Apply triple barrier method to assign binary labels

**Signature:**
```python
label(
    d2r: pd.DataFrame,
    k_sl: float = 1.0,
    k_tp: float = 4.0,
    min_tp: float = 0.20,
    max_time: int = 30,
    n_jobs: int = -1,
    save: bool = True,
    horizon_days: int = 120
) -> pd.DataFrame
```

**Parameters:**
- `d2r` - Rehydrated trajectories from `hydrate()`
- `k_sl` - Stop loss ATR multiplier (default: 1.0)
- `k_tp` - Target ATR multiplier (default: 4.0)
- `min_tp` - Minimum profit target (default: 0.20 = 20%)
- `max_time` - Maximum time barrier in days (default: 30)
- `n_jobs` - Parallel workers
- `save` - Save result to d3_*.parquet
- `horizon_days` - Horizon used for file naming

**Returns:**
- DataFrame with `y_meta` labels (1 = TP, 0 = SL/Time)

**Output Files:**
- `data/ml/d3_120d.parquet` - Labeled dataset
- `data/ml/d3_summary.json` - Quick stats (TP rate, expectancy)

**Dependencies:**
- [[08_Strategy_Layer#Triple Barrier Labeler|TripleBarrierLabeler]]

**Example:**
```python
d3 = pipeline.label(d2r, k_sl=1.0, k_tp=4.0, min_tp=0.20, max_time=30)
# Output: 12,456 trades
# TP rate: 5.6% (699 TP hits)
# Expectancy: +2.8%
```

**Triple Barrier Logic:**
1. **Stop Loss:** -1.0 × nATR (volatility-adaptive)
2. **Profit Target:** MAX(20%, 4.0 × nATR)
3. **Time Barrier:** 30 days maximum hold

**Labeling:**
- **y_meta = 1** → TP hit first (winner)
- **y_meta = 0** → SL or Time hit first (loser)

---

## Utility Methods

### load_d1()
Loads existing D1 dataset from `data/ml/d1.parquet`.

### load_d2()
Loads existing D2 dataset from `data/ml/d2.parquet`.

### load_d2r(horizon_days)
Loads existing D2R dataset. Automatically selects file based on horizon_days parameter.

### load_d3(horizon_days)
Loads existing D3 dataset from `data/ml/d3_{horizon_days}d.parquet`.

**Example:**
```python
d1 = pipeline.load_d1()
d2 = pipeline.load_d2()
d3 = pipeline.load_d3(horizon_days=120)
```

---

## Dataset Specifications

### D1 (Trade Candidates)

**Format:** Parquet
**Location:** `data/ml/d1.parquet`
**Shape:** ~14,000 trades × 6 columns

**Columns:**
- `date` (datetime) - Trade entry date
- `ticker` (str) - Stock symbol
- `label` (int) - Binary label (1 = win, 0 = loss)
- `return_pct` (float) - Actual return %
- `days_held` (int) - Holding period
- `exit_reason` (str) - Why trade exited (target_hit, stop_hit, time_limit)

---

### D2 (Features Dataset)

**Format:** Parquet
**Location:** `data/ml/d2.parquet`
**Shape:** ~14,000 trades × ~158 columns

**Columns:**
- D1 columns (date, ticker, label, return_pct, etc.)
- ~150 feature columns (see [[06_Feature_Config#M01 Features|M01_FEATURES]])

**Used by:** [[03_M01_Trainer|M01 Trainer]] for return prediction

---

### D2R (Rehydrated Trajectories)

**Format:** Parquet
**Location:** `data/ml/d2r_120d.parquet`
**Shape:** ~1.2M rows × ~160 columns

**Columns:**
- `trade_id` (int) - Unique trade identifier
- `day_in_trade` (int) - Day number (0, 1, 2, ...)
- OHLCV columns (Open, High, Low, Close, Volume)
- ~150 feature columns (computed per day)

**Used by:** label() method to generate D3

---

### D3 (Labeled Dataset)

**Format:** Parquet
**Location:** `data/ml/d3_120d.parquet`
**Shape:** ~12,000 trades × ~160 columns

**Columns:**
- D2 columns (trade info + features)
- `y_meta` (int) - Triple barrier label (1 = TP, 0 = SL/Time)
- `barrier_outcome` (str) - Which barrier hit (TP, SL, Time)
- `days_to_outcome` (int) - How many days to exit
- `return_at_outcome` (float) - Return % when barrier hit

**Used by:** [[04_M02_Trainer|M02 Trainer]] for ignition classification

---

## Complete Example

```python
from src.pipeline import DataPipeline

pipeline = DataPipeline()

# M01 workflow (return prediction)
d1 = pipeline.scan('2018-01-01', '2023-12-31')
d2 = pipeline.features(d1, n_jobs=-1)
# Ready for M01 training

# M02 workflow (ignition classification)
d1 = pipeline.scan('2018-01-01', '2023-12-31')
d2r = pipeline.hydrate(d1, horizon_days=120, n_jobs=-1)
d3 = pipeline.label(d2r, k_sl=1.0, k_tp=4.0, min_tp=0.20, max_time=30)
# Ready for M02 training
```

---

## Related Documentation

- For M01 training: [[03_M01_Trainer|M01 Trainer]]
- For M02 training: [[04_M02_Trainer|M02 Trainer]]
- For CLI usage: [[05_Model_Entry_Point#Data Generation|CLI Reference]]
- For feature definitions: [[06_Feature_Config|Feature Config]]

---

*Last updated: 2026-01-27*
