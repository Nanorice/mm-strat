# Native Categorical Support Implementation

**Date**: 2026-02-09
**Feature**: Add native XGBoost categorical support for `industry_id` and `sector_id`

## Background

Previously, `industry_id` and `sector_id` were label-encoded (integers 0-158 and 0-10 respectively) but treated as numeric features by XGBoost. This is suboptimal because:

1. **Ordinal assumption**: XGBoost treated `industry_id=50` as "greater than" `industry_id=30`, which has no real meaning
2. **Split quality**: Numeric splits like `industry_id < 75.5` are artificial and don't capture categorical relationships
3. **Missing categorical interactions**: True categorical splits (e.g., "is in {20, 45, 103}") couldn't be learned

## Solution: Native Categorical Support

XGBoost 1.6+ supports native categorical features through:
- `enable_categorical=True` parameter
- Pandas `category` dtype for categorical columns

### Benefits:
1. **Proper splits**: XGBoost can split on category membership (e.g., "is in set {A, B, C}")
2. **Better interactions**: Can learn industry-specific patterns naturally
3. **Cleaner feature engineering**: No need for one-hot encoding (which would add 158+ features)

## Implementation

### 1. M01Trainer Changes

**File**: `src/pipeline/m01_trainer.py`

#### Model Parameters (Line ~117)
```python
def get_model_params(self, tuned_params: Optional[Dict] = None) -> Dict:
    default_params = {
        'objective': 'reg:squarederror',
        'n_estimators': 300,
        'learning_rate': 0.03,
        'max_depth': 4,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'reg_alpha': 5.0,
        'reg_lambda': 3.0,
        'random_state': 42,
        'n_jobs': -1,
        'enable_categorical': True  # ✅ NEW: Native categorical support
    }
    return default_params
```

#### Data Type Conversion (Line ~447)
```python
# Convert categorical features to 'category' dtype for XGBoost native support
from src.feature_config import CATEGORICAL_FEATURES
cat_features = [f for f in CATEGORICAL_FEATURES if f in available_cols]
if cat_features:
    for col in cat_features:
        data[col] = data[col].astype('category')
    logger.info(f"   Categorical features: {cat_features}")
```

### 2. Feature Preprocessor Changes

**File**: `src/feature_preprocessor.py`

#### Skip Categorical Features (Line ~167)
```python
from src.feature_config import CATEGORICAL_FEATURES

for feature in features:
    if feature not in df.columns:
        continue

    # ✅ NEW: Skip categorical features (handled natively by XGBoost)
    if feature in CATEGORICAL_FEATURES:
        continue

    series = df[feature].dropna()
    # ... rest of preprocessing logic
```

### 3. Feature Config

**File**: `src/feature_config.py`

Already defined:
```python
# Line 223
CATEGORICAL_FEATURES = [
    'sector_id',     # Encoded sector classification (0-10)
    'industry_id',   # Encoded industry classification (0-158)
]
```

Already included in `M01_V2_FEATURES` (lines 355-356):
```python
M01_V2_FEATURES = [
    # ... other features ...
    'industry_id',  # ✅ Native categorical
    'sector_id',    # ✅ Native categorical
]
```

## Usage

### Step 1: Add Company Features to D2

**Important**: The current D2 file is missing `sector_id` and `industry_id` columns because they were added to the pipeline after D2 was generated.

Run this script to fetch company profiles and add categorical features to D2:

```bash
python add_company_features_to_d2.py
```

This will:
1. Fetch company profiles from FMP API (or use cache)
2. Add `sector_id` (0-10) and `industry_id` (0-158) to D2
3. Save updated D2 with categorical features

**Note**: First run will fetch ~500-1000 ticker profiles from API (takes ~5-10 min with rate limiting). Subsequent runs use cached data.

### Step 2: Train M01_v2 with Categorical Features

```python
from src.pipeline import M01Workflow, WorkflowConfig

config = WorkflowConfig(
    start_date='2018-01-01',
    end_date='2023-12-31',
    candidate_features=M01_V2_FEATURES,  # Includes industry_id, sector_id
    auto_select=True,
    fast_eda=True
)

workflow = M01Workflow(config)
results = workflow.run()
```

The workflow will:
1. ✅ Load D2 with `industry_id` and `sector_id` as integers
2. ✅ Skip them during log/winsorize preprocessing (they stay as-is)
3. ✅ Convert them to pandas `category` dtype before training
4. ✅ XGBoost handles them natively (categorical splits)

## Expected Impact

### Model Improvements
- **Better industry/sector interactions**: Can learn "Tech stocks in Bull regime" vs "Finance in Bear"
- **Cleaner feature space**: No need for 158+ one-hot encoded columns
- **Interpretability**: Feature importance shows which industries/sectors matter most

### Validation
Compare M01 vs M01_v2:
- **IC**: Should be similar or improved (categorical interactions help)
- **Edge**: Look for sector/industry concentration in top decile
- **Feature Importance**: Check if `industry_id`/`sector_id` rank high

## Notes

1. **Encoding consistency**: The label encoding (0-158 for industry, 0-10 for sector) is stable across data loads
2. **Missing values**: If `-1` is used for missing, XGBoost treats it as a separate category
3. **Inference**: The same dtype conversion must happen in production scoring (handled by `M01Trainer.train()`)

## Testing

### Quick Test (Verify Implementation)

```bash
# Activate environment
.venv/Scripts/Activate.ps1

# Add company features to D2 (one-time setup)
python add_company_features_to_d2.py

# Test categorical support
python test_categorical_support.py
```

### Full A/B Test (M01 vs M01_v2)

```bash
# Train M01_v2 with categorical support
python model_runner.py train --model m01_v2 --feature-set M01_V2_FEATURES

# Compare with M01 baseline
python model_runner.py compare --models m01,m01_v2
```

## References

- **XGBoost Categorical Tutorial**: https://xgboost.readthedocs.io/en/stable/tutorials/categorical.html
- **Feature Config**: `src/feature_config.py` (CATEGORICAL_FEATURES)
- **M01 Trainer**: `src/pipeline/m01_trainer.py` (enable_categorical)
- **Preprocessor**: `src/feature_preprocessor.py` (skip categorical)
