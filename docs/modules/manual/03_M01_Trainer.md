---
title: M01 Trainer - Return Predictor
type: component
layer: model_runner
status: stable
created: 2026-01-27
updated: 2026-01-29
tags:
  - ml
  - regression
  - m01
  - xgboost
  - return-prediction
  - evaluation
  - feature-selection
dependencies:
  - "[[02_Data_Pipeline]]"
  - "[[06_Feature_Config]]"
---

# M01 Trainer: Return Predictor

**File:** [src/pipeline/m01_trainer.py](../../src/pipeline/m01_trainer.py)
**Class:** `M01Trainer`

← [[01_Model_Runner_Suite|Back to Suite Overview]]

---

## Purpose

M01 predicts **expected return %** for SEPA trade candidates. It uses XGBoost regression to **rank stocks by upside potential**.

**Use Case:**
- Rank candidates: Higher score = higher expected return
- Position sizing: Larger positions for higher scores
- Portfolio construction: Top N predictions become watchlist
- **Dual-model scoring:** Combined with [[04_M02_Trainer|M02 Loser Detector]] for risk-adjusted ranking

---

## Model Type

**Algorithm:** XGBoost Regressor

**Target Variables:**
- `return_pct` (default) - Actual SEPA return %
- `log_space` (recommended) - Log-compressed MFE target
- `y_max` (survivor model) - Maximum Favorable Excursion (MFE)

**Output:** Continuous return % prediction

**Training Data:** [[02_Data_Pipeline#D2 Features Dataset|D2 Dataset]] (trades + ~150 features)

**Features Used:** [[06_Feature_Config#M01 Features|M01_FEATURES]] (21 features)

---

## Constructor

```python
M01Trainer(output_dir: str = 'models')
```

**Parameters:**
- `output_dir` - Directory for saving model files (default: `models`)

**Example:**
```python
from src.pipeline import M01Trainer

trainer = M01Trainer()
```

---

## Training Method

```python
train(
    data: pd.DataFrame,
    tune: bool = False,
    tune_trials: int = 50,
    train_years: int = 3,
    test_years: int = 1,
    target: str = 'return_pct',
    survivor_model: bool = False,
    stop_multiplier: float = 2.0
) -> Tuple[model, metrics_df]
```

**Parameters:**
- `data` - D2 DataFrame (from [[02_Data_Pipeline#features|pipeline.features()]])
- `tune` - Enable Optuna hyperparameter tuning (default: False)
- `tune_trials` - Number of Optuna trials (default: 50)
- `train_years` - Training window size (default: 3)
- `test_years` - Test window size (default: 1)
- `target` - Target column: `'return_pct'` or `'y_max'` (default: 'return_pct')
- `survivor_model` - Filter crashed trades, use y_max (default: False)
- `stop_multiplier` - Survivor stop multiplier (default: 2.0)

**Returns:**
- `model` - Trained XGBoost regressor
- `metrics_df` - DataFrame with validation fold metrics

---

## Walk-Forward Validation

M01 uses rolling walk-forward validation:

**Configuration:**
- Train on 3 years → Test on 1 year
- No gaps between windows
- Temporal ordering preserved

**Example Timeline:**
```
Fold 1: Train [2018-2020] → Test [2021]
Fold 2: Train [2019-2021] → Test [2022]
Fold 3: Train [2020-2022] → Test [2023]
```

**Metrics per Fold:**
- RMSE (Root Mean Squared Error)
- MAE (Mean Absolute Error)
- Selection Edge (Top Decile Mean - Overall Mean)
- Top Decile Mean Return

---

## Hyperparameters

**Default Parameters:**
```python
{
    'objective': 'reg:squarederror',
    'n_estimators': 300,
    'learning_rate': 0.03,
    'max_depth': 4,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'reg_alpha': 5.0,   # L1 regularization (strong)
    'reg_lambda': 3.0,  # L2 regularization
    'random_state': 42
}
```

**Rationale:**
- Small `max_depth=4` prevents overfitting
- Strong L1/L2 regularization for stable predictions
- Conservative `learning_rate=0.03` for smooth convergence

**Tuning:**
Set `tune=True` to use Optuna TPE sampler for automatic hyperparameter search.

---

## Survivor Model Mode

**Purpose:** Focus on trades that didn't hit structural stop-loss

**Activation:**
```python
model, metrics = trainer.train(d2, survivor_model=True, target='y_max')
```

**Behavior:**
1. Requires [[02_Data_Pipeline#D2R Rehydrated Trajectories|D2R dataset]] with MAE/MFE calculations
2. Calculates structural stop: `-stop_multiplier × nATR` (default: -2×nATR)
3. Filters out "crashed" trades where `MAE <= structural_stop`
4. Uses `y_max` (Maximum Favorable Excursion) as target
5. Generates `models/d1_analysis.json` with trade physics stats

**Concept:**
- **Survivors:** Trades that didn't crash (MAE > structural stop)
- **y_max:** Maximum upside achieved (MFE) during trade
- **Use Case:** Predict best-case upside for non-crashed setups

**Example Output:**
```
SURVIVOR MODEL ENABLED
Total trades: 14,240
[X] Crashed: 2,156 (15.1%)
[O] Survived: 12,084 (84.9%)
Training on 12,084 survivor trades
Expected prediction bias: Mean y_max ~ 23.5%
```

---

## Output Files

### 1. Trained Model

**File:** `models/m01.json`
**Format:** XGBoost JSON
**Size:** ~2 MB

Load model:
```python
import xgboost as xgb
model = xgb.XGBRegressor()
model.load_model('models/m01.json')
```

---

### 2. Configuration

**File:** `models/m01_config.json`
**Format:** JSON
**Contents:**
- Model metadata (created date, target, features)
- Walk-forward validation metrics
- Decile performance
- Predictions sample (1000 rows for visualization)
- Error analysis (FOMO vs Toxic errors)

---

### 3. Feature Importance

**File:** `models/feature_importance_m01.csv`
**Format:** CSV
**Columns:** `rank, feature, gain, gain_pct, cumulative_pct`

**Example:**
```csv
rank,feature,gain,gain_pct,cumulative_pct
1,rs_rating,8542,18.5,18.5
2,alpha_momentum_10d,6234,13.5,32.0
3,price_vs_52w_high,4821,10.4,42.4
...
```

---

### 4. Training Report

**File:** `models/model_report_M01_{timestamp}.md`
**Format:** Markdown

**Sections:**
- Executive summary (viability assessment)
- Walk-forward validation results
- Feature importance (top 20)
- Model configuration
- Selection edge analysis

---

## Evaluation Metrics

### Selection Edge

**Definition:** Top Decile Mean Return - Overall Mean Return

**Example:**
```
Top 10% predicted returns: +18.5%
All trades average: +12.0%
Selection Edge: +6.5%
```

**Interpretation:**
- **> 5%:** Strong signal, viable for trading
- **2-5%:** Moderate signal, consider thresholds
- **< 2%:** Weak signal, needs improvement

---

### RMSE (Root Mean Squared Error)

**Typical Range:** 10-15% for return prediction

**Example:**
```
Fold 1: RMSE = 12.3%
Fold 2: RMSE = 11.8%
Mean: RMSE = 12.1%
```

---

### Spearman IC (Information Coefficient)

**Definition:** Rank correlation between predicted and actual returns

**Range:** -1 to +1

**Interpretation:**
- **> 0.10:** Excellent
- **0.05-0.10:** Good
- **< 0.05:** Weak

---

## Usage Examples

### Basic Training

```python
from src.pipeline import DataPipeline, M01Trainer

# Generate data
pipeline = DataPipeline()
d1 = pipeline.scan('2018-01-01', '2023-12-31')
d2 = pipeline.features(d1, n_jobs=-1)

# Train model
trainer = M01Trainer()
model, metrics = trainer.train(d2)

# Save
trainer.save(model, metrics)
```

---

### With Hyperparameter Tuning

```python
model, metrics = trainer.train(d2, tune=True, tune_trials=100)
```

Optuna will search for best hyperparameters using TPE sampler.

---

### Survivor Model

```python
# Requires D2R for MAE/MFE calculations
d2r = pipeline.hydrate(d1, horizon_days=None)  # Use SEPA exits

model, metrics = trainer.train(
    d2,
    survivor_model=True,
    target='y_max',
    stop_multiplier=2.0
)
```

---

### Generate Report

```python
report_path = trainer.generate_report(
    model, metrics,
    start_date='2018-01-01',
    end_date='2023-12-31'
)
print(f"Report saved to {report_path}")
```

---

## Prediction Example

```python
import pandas as pd
import xgboost as xgb

# Load model
model = xgb.XGBRegressor()
model.load_model('models/m01.json')

# Load feature config
from src.feature_config import M01_FEATURES

# Predict on new data
new_data = pd.read_parquet('data/ml/d2_new.parquet')
predictions = model.predict(new_data[M01_FEATURES])

# Rank candidates
new_data['predicted_return'] = predictions
top_10 = new_data.nlargest(10, 'predicted_return')

print(top_10[['ticker', 'date', 'predicted_return']])
```

---

## Dependencies

**Data:**
- [[02_Data_Pipeline#D2 Features Dataset|D2 Dataset]] (from pipeline.features())
- Optional: [[02_Data_Pipeline#D2R Rehydrated Trajectories|D2R Dataset]] (for survivor model)

**Features:**
- [[06_Feature_Config#M01 Features|M01_FEATURES]] (21 features)

**Base Class:**
- `BaseTrainer` - Walk-forward validation, data cleaning, Optuna tuning

---

## Related Documentation

- For data generation: [[02_Data_Pipeline#features|Data Pipeline]]
- For CLI usage: [[05_Model_Entry_Point#M01 Training|CLI Reference]]
- For M02 model: [[04_M02_Trainer|M02 Trainer]]
- For feature definitions: [[06_Feature_Config#M01 Features|Feature Config]]

---

## M01 Evaluation System

The evaluation infrastructure provides comprehensive metrics beyond basic RMSE/MAE.

**File:** [src/evaluation/](../../src/evaluation/)
**Key Classes:** `M01Evaluator`, `FeatureScreener`

### Core Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| **IC (Spearman)** | Rank correlation between predicted and actual returns | > 0.10 |
| **Precision@K** | Top K% predictions that are actual winners | > baseline |
| **Recall@K** | % of actual winners captured in top K% | > 30% |
| **Volatility Correlation** | Correlation with ATR (checks if just predicting vol) | < 0.5 |

### Ablation Study Results

The evaluation system enables testing different target definitions:

| Target | IC | Edge Sharpe | Winner? |
|--------|-----|-------------|---------|
| `return_pct` | 0.13 | 3.7 | ❌ |
| `hybrid_floor` | 0.57 | 3.4 | ❌ |
| `risk_adjusted` | 0.72 | 7.5 | ❌ |
| **`log_space`** | **0.77** | **20.6** | ✅ |

> [!tip] Log-Space Target Recommended
> The `log_space` target uses MFE with log compression. High IC (0.77) indicates excellent ranking capability.

### Running Ablation Studies

```bash
python scripts/run_m01_ablation_study.py --start 2018-01-01 --end 2023-12-31
```

---

## Feature Selection Pipeline

Automated feature screening using KS (Kolmogorov-Smirnov) test.

**File:** [src/evaluation/feature_screener.py](../../src/evaluation/feature_screener.py)
**Class:** `FeatureScreener`

### How It Works

1. Split returns into **Q1 (bottom 25%)** and **Q4 (top 25%)** quartiles
2. For each feature, run KS test between Q1 and Q4 distributions
3. Features with significant distribution shift pass the screening

### KS Threshold Guidelines

| Threshold | Strictness | Use Case |
|-----------|------------|----------|
| 0.15 | Industry standard | Conservative, only top features |
| **0.10** | Recommended | Balance of coverage and quality |
| 0.05 | Permissive | Exploratory analysis |

### Feature Screening Example

```python
from src.evaluation import FeatureScreener
from src.feature_config import M01_CANDIDATE_FEATURES

screener = FeatureScreener()
results = screener.screen(d2, M01_CANDIDATE_FEATURES, ks_threshold=0.10)

# Results include:
# - passed_features: List of features that passed KS test
# - ks_stats: KS statistic for each feature
# - p_values: Statistical significance
```

### EDA Report Generation

```python
screener.generate_eda_report(d2, M01_CANDIDATE_FEATURES, output_path='models/eda_report.md')
```

---

## M01 Workflow (Factory)

End-to-end pipeline for rapid iteration when testing new features.

**File:** [src/pipeline/m01_workflow.py](../../src/pipeline/m01_workflow.py)
**Class:** `M01Workflow`

### Workflow Steps

```mermaid
graph LR
    A[Load Data] --> B[EDA Screening]
    B --> C[Feature Selection]
    C --> D[Training]
    D --> E[Report Generation]
```

### CLI Usage

```bash
# Full workflow with auto-selection
python model_runner.py workflow --start 2018-01-01 --end 2023-12-31

# EDA only (test new features)
python model_runner.py workflow --steps load eda select --ks-threshold 0.10

# With tuning
python model_runner.py workflow --tune

# Skip auto-selection (use existing M01_FEATURES)
python model_runner.py workflow --no-auto-select
```

### Workflow Configuration

```python
from src.pipeline import M01Workflow, WorkflowConfig

config = WorkflowConfig(
    ks_threshold=0.10,
    auto_select=True,
    target='log_space',
    tune=False
)

workflow = M01Workflow(config)
workflow.run(start_date='2018-01-01', end_date='2023-12-31')
```

---

## Key Insights

> [!tip] Selection Edge is Critical
> RMSE and MAE measure prediction accuracy, but **selection edge** measures trading viability. A model with RMSE=15% but edge=+7% is better than RMSE=10% with edge=+2%.

> [!tip] IC is the Best Comparison Metric
> Information Coefficient (Spearman rank correlation) is dimensionless and allows fair comparison across different target definitions.

> [!info] Survivor Model Use Case
> Use survivor model when you want to:
> - Estimate best-case upside (y_max)
> - Filter out early stop-outs before ranking
> - Build position sizing based on maximum potential

> [!info] Feature Screening Insight
> Default KS threshold (0.15) is strict - top features like `Price_vs_SMA_200` (KS=0.145) barely miss. Using 0.10 threshold passed 6 features with IC=0.323.

> [!warning] Overfitting Risk
> If validation edge is high (+8%) but degrades over time, the model may be overfitting. Monitor edge consistency across folds.

---

*Last updated: 2026-01-29*
