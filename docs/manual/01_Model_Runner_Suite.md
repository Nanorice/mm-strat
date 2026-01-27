---
title: Model Runner Suite
type: overview
layer: model_runner
status: stable
created: 2026-01-27
tags:
  - ml
  - pipeline
  - training
  - overview
dependencies:
  - "[[07_Data_Layer]]"
  - "[[08_Strategy_Layer]]"
---

# Model Runner Suite

**Location:** `src/pipeline/`

← [[00_Project_Overview|Back to Project Overview]]

---

## Purpose

The Model Runner Suite orchestrates **end-to-end ML training** for SEPA trade prediction models. It manages:
- Data generation (D1 → D2 → D2R → D3 workflow)
- Model training with walk-forward validation
- Hyperparameter tuning (Optuna)
- Model evaluation and reporting

---

## Components

### 1. Data Pipeline → [[02_Data_Pipeline|View Details]]

**File:** `src/pipeline/data_pipeline.py`
**Class:** `DataPipeline`

**Purpose:** Orchestrates all data preparation steps

**Key Methods:**
- `scan()` - Generate SEPA trade candidates (D1)
- `features()` - Add ML features (D2)
- `hydrate()` - Create multi-day trajectories (D2R)
- `label()` - Apply triple barrier labels (D3)

**Output Datasets:**
- **D1:** Trade candidates with labels (date, ticker, return_pct)
- **D2:** D1 + ~150 ML features
- **D2R:** Multi-day price trajectories (long format)
- **D3:** D1 with triple barrier labels (y_meta: 1=TP, 0=SL/Time)

---

### 2. M01 Trainer → [[03_M01_Trainer|View Details]]

**File:** `src/pipeline/m01_trainer.py`
**Class:** `M01Trainer`

**Purpose:** **Return Predictor** - Ranks candidates by expected return %

**Model Type:** XGBoost Regressor

**Target Variable:**
- `return_pct` (default) - Actual SEPA return
- `y_max` (survivor model) - Maximum Favorable Excursion (MFE)

**Training Data:** D2 (trades + features)

**Output Files:**
- `models/m01.json` - Trained model
- `models/m01_config.json` - Configuration + metrics
- `models/feature_importance_m01.csv` - Feature rankings

**Use Case:**
```python
# Predict expected returns for new candidates
predictions = model.predict(features)
top_picks = df.nlargest(10, 'prediction')
```

---

### 3. M02 Trainer → [[04_M02_Trainer|View Details]]

**File:** `src/pipeline/m02_trainer.py`
**Class:** `M02Trainer`

**Purpose:** **Ignition Classifier** - Predicts probability of hitting profit target before stop-loss

**Model Type:** XGBoost Classifier

**Target Variable:**
- `y_meta` - Binary label (1 = TP hit first, 0 = SL/Time hit first)

**Triple Barrier Parameters:**
```python
{
    'k_sl': 1.0,      # Stop = 1.0 × ATR
    'k_tp': 4.0,      # Target = MAX(20%, 4.0 × ATR)
    'min_tp': 0.20,   # Minimum 20% profit target
    'max_time': 30    # Time barrier (days)
}
```

**Training Data:** D3 (trades + features + barrier labels)

**Output Files:**
- `models/m02.json` - Trained model
- `models/m02_config.json` - Configuration + metrics
- `models/feature_importance_m02.csv` - Feature rankings

**Use Case:**
```python
# Filter low-probability setups
probabilities = model.predict_proba(features)[:, 1]
high_confidence = df[probabilities > 0.7]
```

---

### 4. Base Trainer

**File:** `src/pipeline/base_trainer.py`
**Class:** `BaseTrainer` (Abstract)

**Purpose:** Shared training infrastructure for M01 and M02

**Provides:**
- Walk-forward validation framework
- Data cleaning (outliers, missing values)
- Hyperparameter tuning (Optuna TPE sampler)
- Decile analysis (selection edge calculation)
- Model serialization (JSON format)

---

### 5. Entry Point → [[05_Model_Entry_Point|View Details]]

**File:** `model_runner.py` (root directory)

**Purpose:** Command-line interface for training workflows

**Usage:**
```bash
# M01 training
python model_runner.py m01 --start 2018-01-01 --end 2023-12-31 --report

# M02 training
python model_runner.py m02 --start 2018-01-01 --end 2023-12-31 --report
```

---

## Data Flow

### M01 Workflow (Return Prediction)

```
┌─────────────────────────────────────────────────────────────────┐
│ STEP 1: scan()                                                   │
│ Run SEPA screener over historical dates                          │
│ Output: D1 (trade candidates with actual returns)                │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 2: features()                                               │
│ Extract features at entry date for each trade                    │
│ Output: D2 (D1 + ~150 ML features)                               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 3: train()                                                  │
│ M01Trainer.train(D2) → XGBoost Regression                        │
│ Output: models/m01.json + metrics                                │
└─────────────────────────────────────────────────────────────────┘
```

### M02 Workflow (Ignition Classification)

```
┌─────────────────────────────────────────────────────────────────┐
│ STEP 1: scan()                                                   │
│ Run SEPA screener over historical dates                          │
│ Output: D1 (trade candidates)                                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 2: hydrate()                                                │
│ Expand each trade to multi-day trajectory (fixed horizon)        │
│ Output: D2R (long-format with features per day)                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 3: label()                                                  │
│ Apply triple barrier method to each trajectory                   │
│ Output: D3 (D1 + barrier labels: y_meta)                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 4: train()                                                  │
│ M02Trainer.train(D3) → XGBoost Classification                    │
│ Output: models/m02.json + metrics                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Walk-Forward Validation

Both M01 and M02 use **walk-forward validation** to avoid look-ahead bias:

**Configuration:**
- Training window: 3 years
- Test window: 1 year
- Rolling basis (no gaps)

**Example Timeline:**
```
Fold 1: Train [2018-2020] → Test [2021]
Fold 2: Train [2019-2021] → Test [2022]
Fold 3: Train [2020-2022] → Test [2023]
```

**Why This Matters:**
- Models are trained on past data only
- Tested on truly unseen future data
- Mimics real-world deployment conditions
- Prevents overfitting to historical quirks

**Evaluation Metrics:**
- **M01:** RMSE, Spearman IC, Decile analysis (selection edge)
- **M02:** Accuracy, Precision, Recall, ROC-AUC

---

## Key Concepts

### Selection Edge (M01)

**Definition:** Top Decile Mean Return - Overall Mean Return

**Example:**
- Top 10% predicted returns average: +18.5%
- All trades average: +12.0%
- **Selection Edge = +6.5%**

**Interpretation:**
- Positive edge = model successfully ranks winners
- Edge > 5% = strong signal
- Edge < 2% = weak/marginal signal

### Survivor Model (M01)

**Purpose:** Train only on trades that didn't hit structural stop-loss

**Concept:**
- Filter out "crashed" trades (MAE < -2×nATR)
- Use `y_max` (MFE) as target instead of `return_pct`
- Predicts maximum achievable upside for survivors

**Use Case:**
- Better for position sizing (estimate best-case upside)
- Avoids bias from early stop-outs

### Triple Barrier Method (M02)

**Purpose:** Path-dependent labeling for classification

**Barriers:**
1. **Profit Target (TP):** +20% or +4×ATR (whichever is higher)
2. **Stop Loss (SL):** -1×ATR
3. **Time Barrier:** 30 days

**Labeling Logic:**
- **y_meta = 1** → TP hit first (winner)
- **y_meta = 0** → SL or Time hit first (loser)

**Why This Matters:**
- Accounts for when exit happens (path-dependent)
- More realistic than binary win/loss labels
- Captures risk/reward asymmetry

---

## Example Usage

### Full M01 Training

```python
from src.pipeline import DataPipeline, M01Trainer

# Generate data
pipeline = DataPipeline()
d1 = pipeline.scan('2018-01-01', '2023-12-31', threshold=15.0)
d2 = pipeline.features(d1, n_jobs=-1)

# Train model
trainer = M01Trainer()
model, metrics = trainer.train(d2, tune=False)

# Save and report
trainer.save(model, metrics)
trainer.generate_report(model, metrics)
```

### Full M02 Training

```python
from src.pipeline import DataPipeline, M02Trainer

# Generate data
pipeline = DataPipeline()
d1 = pipeline.scan('2018-01-01', '2023-12-31')
d2r = pipeline.hydrate(d1, horizon_days=120, n_jobs=-1)
d3 = pipeline.label(d2r, k_sl=1.0, k_tp=4.0, min_tp=0.20)

# Train model
trainer = M02Trainer()
model, metrics = trainer.train(d3, tune=False)

# Save and report
trainer.save(model, metrics)
trainer.generate_report(model, metrics)
```

---

## Dependencies

**Data Layer:**
- [[07_Data_Layer#DataRepository|DataRepository]] - Price data cache
- [[07_Data_Layer#FundamentalEngine|FundamentalEngine]] - Fundamental data
- [[07_Data_Layer#EarningsEngine|EarningsEngine]] - Earnings tracking

**Strategy Layer:**
- [[08_Strategy_Layer#SEPAStrategy|SEPAStrategy]] - SEPA screening logic
- [[08_Strategy_Layer#Trade Simulator|FastTradeSimulator]] - Historical simulation
- [[08_Strategy_Layer#Triple Barrier Labeler|TripleBarrierLabeler]] - Meta-labeling

**Feature Engineering:**
- [[06_Feature_Config|Feature Config]] - Feature definitions
- `FeatureEngineer` - Technical indicators
- `FundamentalMerger` - Fundamental enrichment

---

## Related Documentation

- [[02_Data_Pipeline|Data Pipeline Details]]
- [[03_M01_Trainer|M01 Trainer Details]]
- [[04_M02_Trainer|M02 Trainer Details]]
- [[05_Model_Entry_Point|CLI Usage Guide]]

---

*Last updated: 2026-01-27*
