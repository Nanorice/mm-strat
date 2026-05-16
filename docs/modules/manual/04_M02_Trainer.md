---
title: M02 Trainer - Loser Detector
type: component
layer: model_runner
status: stable
created: 2026-01-27
updated: 2026-01-29
tags:
  - ml
  - classification
  - m02
  - xgboost
  - triple-barrier
  - loser-detection
  - risk-filter
dependencies:
  - "[[02_Data_Pipeline]]"
  - "[[06_Feature_Config]]"
  - "[[08_Strategy_Layer#Triple Barrier Labeler]]"
---

# M02 Trainer: Loser Detector

**File:** [src/pipeline/m02_trainer.py](../../src/pipeline/m02_trainer.py)
**Class:** `M02Trainer`

← [[01_Model_Runner_Suite|Back to Suite Overview]]

---

## Purpose

M02 predicts **stop-loss hit probability** - the likelihood of hitting SL before TP or time exit. It uses triple barrier meta-labeling to **filter high-risk trades**.

> [!important] Critical Pivot (2026-01-28)
> M02 was originally designed as an "Ignition Classifier" (predict TP hits). With only 5.4% TP rate, the model learned to always predict "no TP" (91% accuracy but useless). **Inverting to predict SL hits (61.6% base rate)** produces a learnable, useful model.

**Use Case:**
- **Risk filtering:** Penalize trades likely to hit stop-loss
- **Dual-model scoring:** `Final_Score = M01_adj × (1 - P(loser))`
- Position sizing: Lower P(loser) = larger position

---

## Model Type

**Algorithm:** XGBoost Classifier

**Target Variable:**
- `y_loser` - Binary label (1 = SL hit, 0 = TP or Time exit)

**Output:** Probability [0, 1] of hitting stop-loss

**Training Data:** [[02_Data_Pipeline#D3 Labeled Dataset|D3 Dataset]] (trades + features + barrier labels)

**Features Used:** [[06_Feature_Config#M02 Features|M02_FEATURES]] (48 velocity-focused features)

---

## Constructor

```python
M02Trainer(
    output_dir: str = 'models',
    barrier_params: Optional[Dict] = None
)
```

**Parameters:**
- `output_dir` - Directory for saving model files (default: `models`)
- `barrier_params` - Triple barrier configuration (default: Phase 1 optimized)

**Default Barriers:**
```python
{
    'k_sl': 1.0,      # Stop = 1.0 × ATR
    'k_tp': 4.0,      # Target = MAX(20%, 4.0 × ATR)
    'min_tp': 0.20,   # Minimum 20% profit target
    'max_time': 30    # Time barrier (days)
}
```

**Example:**
```python
from src.pipeline import M02Trainer

trainer = M02Trainer()  # Uses default barriers
```

---

## Training Method

```python
train(
    data: pd.DataFrame,
    tune: bool = False,
    tune_trials: int = 50,
    train_years: int = 3,
    test_years: int = 1
) -> Tuple[model, metrics_df]
```

**Parameters:**
- `data` - D3 DataFrame (from [[02_Data_Pipeline#label|pipeline.label()]])
- `tune` - Enable Optuna hyperparameter tuning (default: False)
- `tune_trials` - Number of Optuna trials (default: 50)
- `train_years` - Training window size (default: 3)
- `test_years` - Test window size (default: 1)

**Returns:**
- `model` - Trained XGBoost classifier
- `metrics_df` - DataFrame with validation fold metrics

---

## Walk-Forward Validation

Same as [[03_M01_Trainer#Walk-Forward Validation|M01]]:

**Configuration:**
- Train on 3 years → Test on 1 year
- Rolling windows, no gaps

**Metrics per Fold:**
- Accuracy
- Precision (TP class)
- Recall (TP class)
- ROC-AUC
- Selection Edge (optional)

---

## Hyperparameters

**Default Parameters:**
```python
{
    'objective': 'binary:logistic',
    'n_estimators': 500,
    'learning_rate': 0.03,
    'max_depth': 5,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'min_child_weight': 3,
    'eval_metric': 'logloss'
}
```

**Class Imbalance Handling:**
- Automatically calculates `scale_pos_weight` based on class distribution
- Example: If TP rate = 5.6%, then `scale_pos_weight = 16.9`

---

## Triple Barrier Method

M02 uses path-dependent labeling via triple barriers:

### Barrier Configuration

**1. Stop Loss (SL):**
```
SL = Entry Price - (k_sl × nATR)
Default: -1.0 × nATR (volatility-adaptive)
```

**2. Profit Target (TP):**
```
TP = Entry Price + MAX(min_tp, k_tp × nATR)
Default: MAX(20%, 4.0 × nATR)
```

**3. Time Barrier:**
```
Max holding period: 30 days
```

### Labeling Logic (Inverted for Loser Detection)

For each trade trajectory in [[02_Data_Pipeline#D2R Rehydrated Trajectories|D2R]]:
1. Check each day: Did price hit SL, TP, or Time barrier?
2. **y_loser = 1** → SL hit first (loser)
3. **y_loser = 0** → TP or Time exit (survivor)

**Example:**
```
Trade Entry: $100, nATR = 5%
- SL = $95 (-5%)
- TP = MAX($120, $120) = $120 (+20%)
- Time = 30 days

Day 3: Price = $92 → SL hit → y_loser = 1
Day 12: Price = $122 → TP hit → y_loser = 0
Day 31: Time limit → y_loser = 0
```

> [!note] Why Invert?
> With 5.4% TP rate vs 61.6% SL rate, the model learns better patterns when predicting the majority class (SL). We then **invert the scoring formula** to penalize high P(loser).

---

## Feature Engineering (Velocity Focus)

M02 uses **velocity-focused features** from [[06_Feature_Config#M02 Features|M02_FEATURES]]:

**Key Features:**
- `rs_velocity` - RS acceleration (5-day slope of RS rating)
- `volume_acceleration` - Volume surge detector
- `breakout_momentum` - Breakout strength in ATR units
- `consolidation_duration` - Coil length (days in tight range)
- `price_momentum_curve` - Parabolic detector (2nd derivative)

**Rationale:**
- Ignition requires **acceleration**, not just setup quality
- Static features (RSI, MACD) don't predict **when** ignition happens
- Velocity features capture rate of change

---

## Output Files

### 1. Trained Model

**File:** `models/m02.json`
**Format:** XGBoost JSON
**Size:** ~3 MB

Load model:
```python
import xgboost as xgb
model = xgb.XGBClassifier()
model.load_model('models/m02.json')
```

---

### 2. Configuration

**File:** `models/m02_config.json`
**Format:** JSON
**Contents:**
- Model metadata (created date, barrier params)
- Walk-forward validation metrics
- Class distribution stats
- Barrier outcome rates (TP/SL/Time %)

---

### 3. Feature Importance

**File:** `models/feature_importance_m02.csv`
**Format:** CSV
**Columns:** `rank, feature, gain, gain_pct, cumulative_pct`

---

### 4. Training Report

**File:** `models/model_report_M02_{timestamp}.md`
**Format:** Markdown

**Sections:**
- Executive summary (viability assessment)
- Walk-forward validation results
- Feature importance (top 20)
- Barrier configuration
- Usage recommendations (thresholds)

---

## Evaluation Metrics

### Accuracy

**Baseline:** Use class distribution (e.g., 94.4% if predicting SL always)

**Target:** Must beat naive baseline

**Example:**
```
Baseline accuracy: 94.4% (always predict SL)
Model accuracy: 94.8%
Improvement: +0.4% (marginal but significant with 12K samples)
```

---

### Precision (TP Class)

**Definition:** Of predictions marked TP, how many were correct?

**Critical for:** Avoiding false positives (toxic predictions)

**Target:** > 10% (given 5.6% base rate)

**Example:**
```
Precision = 11.2%
→ Of 100 predictions marked TP, 11 actually hit TP
→ Better than random (5.6%)
```

---

### Recall (TP Class)

**Definition:** Of actual TPs, how many did we catch?

**Trade-off:** Higher recall = lower precision

**Target:** > 30%

**Example:**
```
Recall = 34.1%
→ Caught 34% of all TP trades
→ Missed 66% (acceptable for high-precision filter)
```

---

### ROC-AUC

**Range:** 0.5 (random) to 1.0 (perfect)

**Target:**
- **> 0.70:** Excellent
- **0.60-0.70:** Good
- **< 0.60:** Weak

**Example:**
```
ROC-AUC = 0.683
→ Model has good discriminative power
```

---

## Usage Examples

### Basic Training

```python
from src.pipeline import DataPipeline, M02Trainer

# Generate data
pipeline = DataPipeline()
d1 = pipeline.scan('2018-01-01', '2023-12-31')
d2r = pipeline.hydrate(d1, horizon_days=120, n_jobs=-1)
d3 = pipeline.label(d2r, k_sl=1.0, k_tp=4.0, min_tp=0.20, max_time=30)

# Train model
trainer = M02Trainer()
model, metrics = trainer.train(d3)

# Save
trainer.save(model, metrics)
```

---

### Custom Barriers

```python
custom_barriers = {
    'k_sl': 0.8,     # Tighter stop
    'k_tp': 5.0,     # Larger target
    'min_tp': 0.25,  # 25% minimum
    'max_time': 20   # Shorter horizon
}

trainer = M02Trainer(barrier_params=custom_barriers)
```

---

### Generate Report

```python
report_path = trainer.generate_report(
    model, metrics,
    start_date='2018-01-01',
    end_date='2023-12-31'
)
```

---

## Prediction Example

```python
import pandas as pd
import xgboost as xgb

# Load model
model = xgb.XGBClassifier()
model.load_model('models/m02.json')

# Load feature config
from src.feature_config import get_model_features
M02_FEATURES = get_model_features('M02')

# Predict on new data
new_data = pd.read_parquet('data/ml/d3_new.parquet')
probabilities = model.predict_proba(new_data[M02_FEATURES])[:, 1]

# Filter high-confidence trades
new_data['ignition_prob'] = probabilities
high_confidence = new_data[new_data['ignition_prob'] > 0.7]

print(high_confidence[['ticker', 'date', 'ignition_prob']])
```

---

## Dual-Model Scoring (Production)

The recommended production approach combines M01 ranking with M02 loser filtering.

**File:** [src/pipeline/production_scorer.py](../../src/pipeline/production_scorer.py)
**Class:** `ProductionScorer`

### Scoring Formula

```
Final_Score = M01_Vol_Adj × (1 - P(loser))
            = M01_Vol_Adj × m02_survival
```

Where:
- `M01_Vol_Adj` = M01 prediction / nATR (volatility-adjusted)
- `P(loser)` = M02 probability of hitting stop-loss
- `m02_survival` = 1 - P(loser)

### ProductionScorer Usage

```python
from src.pipeline import ProductionScorer

scorer = ProductionScorer()
scorer.load_models()

# Score with M02 Loser Detector (RECOMMENDED)
scores = scorer.score(candidates, use_m02=True)

# Output columns:
# - m01_score: Raw M01 prediction
# - adjusted_score: Vol-adjusted M01
# - m02_loser_proba: P(hitting stop-loss)
# - m02_survival: 1 - P(loser)
# - final_score: adjusted_score × m02_survival

positions = scorer.get_position_sizes(scores, portfolio_value=100000)
```

### Performance Improvement (2022 Crisis Simulation)

| Configuration | IC | p-value | Selection Edge | Top Decile |
|--------------|-----|---------|----------------|------------|
| Vol-Adjusted M01 Only | +0.094 | 0.0036 | +6.46% | 3.77% |
| **M01 + M02 Loser Detector** | **+0.304** | **<0.0001** | **+10.02%** | **7.33%** |

> [!success] IC improved 3.2x with the inverted M02
> The loser detector successfully filters out trades likely to hit stop-loss.

### Daily Scanner Integration

```bash
# Run with M02 Loser Detector
python daily_scanner.py --use-ml
```

**Output Columns:**
- `final_score`: Combined M01 × M02 score
- `m02_loser_proba`: Stop-loss hit probability (Loser%)
- `m02_survival`: 1 - P(loser) (Surv%)

---

## Dependencies

**Data:**
- [[02_Data_Pipeline#D3 Labeled Dataset|D3 Dataset]] (from pipeline.label())

**Features:**
- [[06_Feature_Config#M02 Features|M02_FEATURES]] (48 velocity features)

**Labeling:**
- [[08_Strategy_Layer#Triple Barrier Labeler|TripleBarrierLabeler]]

**Base Class:**
- `BaseTrainer` - Walk-forward validation, data cleaning

---

## Related Documentation

- For data generation: [[02_Data_Pipeline#label|Data Pipeline]]
- For CLI usage: [[05_Model_Entry_Point#M02 Training|CLI Reference]]
- For M01 model: [[03_M01_Trainer|M01 Trainer]]
- For triple barriers: [[08_Strategy_Layer#Triple Barrier Labeler|Strategy Layer]]

---

## Key Insights

> [!tip] Invert the Target for Imbalanced Data
> When one class is rare (5.4% TP rate), invert the target to predict the majority class (61.6% SL rate). This produces a learnable model.

> [!tip] Accuracy Drop is Intentional
> Old TP model: 91% accuracy (useless - always predicted "no TP")
> New SL model: 57% accuracy (useful - actually learns patterns)
> **Don't optimize for accuracy with imbalanced data.**

> [!info] The Loser Detector Insight
> ```
> Problem: 5.4% TP rate → Model learns "always predict no TP" → 94.6% accuracy but useless
> Solution: 61.6% SL rate → Model learns actual patterns → 57% accuracy but useful
>           Formula: Final = M01_adj × (1 - P(loser))
>           ↳ High P(loser) → penalize the trade
> ```

> [!info] Velocity Features Matter
> Static features (RSI, MACD) don't predict ignition timing. Use velocity features: rs_velocity, volume_acceleration, breakout_momentum.

> [!success] M02 Training Comparison
> | Metric | Old (TP Target) | New (SL Target) |
> |--------|-----------------|-----------------|
> | Accuracy | 91.4% | 57.3% |
> | Precision | 21% | **66%** |
> | Recall | 21% | **68%** |
> | Crisis IC | -0.075 | **+0.304** |

---

*Last updated: 2026-01-29*
