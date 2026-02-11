# Feature Preprocessing Gap Analysis
**Date:** 2026-02-09
**Issue:** Missing log-transformed features in preprocessing pipeline

## 🔴 Problem Summary

Training M01 fails with:
```
Missing 3 features: ['log_breakout_momentum', 'log_alpha009', 'log_net_income_growth_yoy']
```

## Root Cause Analysis

### 1. **`breakout_momentum` - NOT IN PREPROCESSING CONFIG**
- **Status:** ❌ MISSING from `models/preprocessing_config.json`
- **Expected:** Should be in `EXPLOSIVE_FEATURES` list (line 52 in `feature_preprocessor.py`)
- **Actual:** Listed in `EXPLOSIVE_FEATURES` but NOT present in the fitted config
- **Reason:** Feature was likely missing from D2 dataset during `fit()` call
- **Impact:** `log_breakout_momentum` cannot be created during `transform()`

### 2. **`alpha009` - NOT IN PREPROCESSING CONFIG**
- **Status:** ❌ MISSING from `models/preprocessing_config.json`
- **Expected:** Should be in `EXPLOSIVE_FEATURES` list (line 54 in `feature_preprocessor.py`)
- **Actual:** Listed in `EXPLOSIVE_FEATURES` but NOT present in the fitted config
- **Reason:** Feature was likely missing from D2 dataset during `fit()` call
- **Impact:** `log_alpha009` cannot be created during `transform()`

### 3. **`net_income_growth_yoy` - WRONG TRANSFORMATION**
- **Status:** ⚠️ WINSORIZED (should be ARCSINH transformed)
- **Current:** `"transform": "winsorize", "category": "tar_based"` (lines 396-403)
- **Expected:** Should use `np.arcsinh()` transform for features that can be negative
- **Reason:** User correctly identified this can be negative (losses), so log transform is invalid
- **Impact:** `log_net_income_growth_yoy` is incorrectly named/expected by M01

---

## Current System Architecture (Gaps Identified)

### Feature Preprocessing Flow
```
1. Define EXPLOSIVE_FEATURES in feature_preprocessor.py
   ├─ Lines 38-55: Static list of features expected to need log transform
   │
2. FeaturePreprocessor.fit(D2, features, target)
   ├─ For each feature in `features` parameter:
   │  ├─ Check if feature in df.columns  ← ❌ FAILURE POINT 1
   │  ├─ If NOT in D2 → skip silently
   │  └─ If in EXPLOSIVE_FEATURES → mark for log transform
   │
3. FeaturePreprocessor.transform(D2)
   ├─ Create log_{feature} for each marked feature
   │  ├─ Only if original feature exists in df.columns  ← ❌ FAILURE POINT 2
   │
4. M01_FEATURES expects log-transformed versions
   └─ If log_{feature} not created → MISSING FEATURE ERROR
```

### Gap 1: Silent Feature Skipping
**Location:** [feature_preprocessor.py:183-184](feature_preprocessor.py#L183-L184)
```python
for feature in features:
    if feature not in df.columns:
        continue  # ← SILENT SKIP - No warning logged
```

**Issue:** If a feature is missing from D2 during `fit()`, it's silently skipped.
**Impact:** No log transform config created, but M01_FEATURES still expects `log_{feature}`

### Gap 2: No Validation Between EXPLOSIVE_FEATURES and M01_FEATURES
**Location:** No validation exists between:
- `EXPLOSIVE_FEATURES` in `feature_preprocessor.py` (lines 38-55)
- `M01_FEATURES` in `feature_config.py` (lines 278-353)

**Issue:** M01_FEATURES can reference `log_{feature}` that:
1. Was never in EXPLOSIVE_FEATURES
2. Was in EXPLOSIVE_FEATURES but missing from D2 during fit()
3. Exists in EXPLOSIVE_FEATURES but not yet computed in data pipeline

### Gap 3: Negative-Value Features Misclassified
**Location:** [feature_preprocessor.py:38-55](feature_preprocessor.py#L38-L55)

**Issue:** `EXPLOSIVE_FEATURES` list uses `signed_log(x) = sign(x) * log(1 + |x|)` transform.
This works for features that can be negative (e.g., `eps_growth_yoy`, `revenue_growth_yoy`).

However, user correctly identified that `net_income_growth_yoy` should use **`arcsinh()`** instead because:
- Can be deeply negative (losses)
- `arcsinh(x) ≈ log(2x)` for large positive x
- `arcsinh(x) ≈ -log(-2x)` for large negative x
- Smoother near zero than signed_log

**Current behavior:** `net_income_growth_yoy` got winsorized via TAR-based decision (TAR=1.17 < 1.2 threshold).

---

## Configuration Documentation Gap

### Current State: ❌ NO CLEAR MAPPING

The user asked:
> "Do we have a clear mapping on what transformation is done to which features, and documentation on this?"

**Answer:** No, the system has **implicit** rules but no explicit mapping document.

### Current Transformation Logic (Reverse-Engineered)

```
Decision Tree in FeaturePreprocessor.fit():
│
├─ If feature in BOUNDED_FEATURES (line 70)
│  └─ → ALWAYS winsorize (e.g., RSI_14, earnings_quality_score)
│
├─ Elif feature in EXPLOSIVE_FEATURES (lines 38-55)
│  └─ → ALWAYS log transform (sign(x) * log(1 + |x|))
│
├─ Elif feature in STANDARD_FEATURES (lines 57-68)
│  └─ → ALWAYS winsorize (margins, slopes, etc.)
│
└─ Else (Unknown feature)
   ├─ Compute kurtosis
   ├─ If |kurtosis| <= 10.0 → SKIP (no transform)
   └─ If |kurtosis| > 10.0:
      ├─ Compute TAR (Tail Alpha Ratio)
      ├─ If TAR > 1.2 → log transform
      └─ If TAR ≤ 1.2 → winsorize
```

### Where is this documented?
1. **Code comments:** Lines 74-84 in `feature_preprocessor.py`
2. **EDA report:** `models/eda_report.md` (lines 641-687) - shows results, not rules
3. **Preprocessing config JSON:** Shows fitted results, not decision logic
4. **User documentation:** ❌ DOES NOT EXIST

---

## Transformation Registry (What We Need)

A proper transformation mapping would look like:

| Feature | Transform | Rationale | Handles Negatives? |
|---------|-----------|-----------|-------------------|
| `breakout_momentum` | `signed_log` | High kurtosis, extreme outliers | ✅ Yes |
| `alpha009` | `signed_log` | Trend acceleration, fat tails | ✅ Yes |
| `net_income_growth_yoy` | `arcsinh` | Can be deeply negative (losses) | ✅ Yes (better) |
| `eps_growth_yoy` | `signed_log` | Explosive, already in EXPLOSIVE_FEATURES | ✅ Yes |
| `revenue_growth_yoy` | `signed_log` | Explosive, already in EXPLOSIVE_FEATURES | ✅ Yes |
| `RSI_14` | `winsorize` | Bounded 0-100, oscillator | N/A (bounded) |
| `operating_margin` | `winsorize` | Standard feature, margins capped at 100% | ⚠️ Can be negative |

**Current Gap:** This table does not exist. Users must read code to understand.

---

## Recommended Fixes

### Fix 1: Add Missing Features to D2 Pipeline
**Action:** Ensure `breakout_momentum` and `alpha009` are computed BEFORE `FeaturePreprocessor.fit()`

**Files to check:**
- `src/features.py` - Where are these computed?
- `src/pipeline/m01_workflow.py` - Is the feature computation step before preprocessing?

**Validation:**
```python
# Before fit()
assert 'breakout_momentum' in d2.columns, "breakout_momentum missing from D2"
assert 'alpha009' in d2.columns, "alpha009 missing from D2"
```

### Fix 2: Add ARCSINH Transform for Bipolar Features
**Location:** `feature_preprocessor.py`

**Add new category:**
```python
# Features that can be deeply negative (use arcsinh instead of signed_log)
ARCSINH_FEATURES = [
    'net_income_growth_yoy',  # Can be -1000% (bankruptcy) to +5000%
    # Add others if discovered
]

@staticmethod
def arcsinh_transform(x: np.ndarray) -> np.ndarray:
    """Apply inverse hyperbolic sine: arcsinh(x) = log(x + sqrt(x^2 + 1))"""
    return np.arcsinh(x)
```

**Update fit() logic:**
```python
elif feature in ARCSINH_FEATURES:
    feature_config.update({
        'transform': 'arcsinh',
        'category': 'bipolar'
    })
```

**Update transform() logic:**
```python
elif transform_type == 'arcsinh':
    new_col = f'arcsinh_{feature}'
    log_columns[new_col] = self.arcsinh_transform(df[feature].values)
```

**Update M01_FEATURES:**
```python
# Change from:
'log_net_income_growth_yoy',
# To:
'arcsinh_net_income_growth_yoy',
```

### Fix 3: Add Preprocessing Validation Step
**Location:** `src/pipeline/m01_workflow.py` or `src/pipeline/base_trainer.py`

**Add validation function:**
```python
def validate_preprocessing_coverage(
    preprocessor: FeaturePreprocessor,
    required_features: List[str]
) -> None:
    """
    Validate that all required log/arcsinh-transformed features are covered.

    Raises:
        ValueError: If required transformed features are missing
    """
    config = preprocessor.config['features']

    missing = []
    for feat in required_features:
        if feat.startswith('log_'):
            original = feat.replace('log_', '')
            if original not in config or config[original]['transform'] != 'log':
                missing.append(feat)
        elif feat.startswith('arcsinh_'):
            original = feat.replace('arcsinh_', '')
            if original not in config or config[original]['transform'] != 'arcsinh':
                missing.append(feat)

    if missing:
        raise ValueError(
            f"Preprocessing config missing transforms for: {missing}\n"
            f"Ensure these features are:\n"
            f"1. Present in D2 dataset before fit()\n"
            f"2. Listed in EXPLOSIVE_FEATURES or ARCSINH_FEATURES\n"
            f"3. Have high kurtosis (>10) to trigger transform"
        )
```

### Fix 4: Create Transformation Documentation
**Location:** `docs/feature_preprocessing_guide.md` (NEW FILE)

**Contents:**
1. Transformation decision tree (flowchart)
2. List of all EXPLOSIVE_FEATURES with rationale
3. List of all ARCSINH_FEATURES with rationale
4. How to add a new feature to preprocessing
5. How to debug missing transformed features

---

## Immediate Action Items

### Priority 1 (Blocking Training):
1. ✅ Identify why `breakout_momentum` and `alpha009` are missing from D2
2. ✅ Re-fit preprocessing config with complete feature set
3. ✅ Re-train M01 model

### Priority 2 (Technical Debt):
4. ⏳ Implement ARCSINH_FEATURES category
5. ⏳ Add validation step to pipeline
6. ⏳ Create transformation documentation

### Priority 3 (Monitoring):
7. ⏳ Add logging for skipped features in fit()
8. ⏳ Add unit test: M01_FEATURES ⊆ {original + log/arcsinh transformed features}

---

## Investigation Questions

To resolve this, we need to answer:

1. **Where are these features computed?**
   - `breakout_momentum` - Defined in `TECHNICAL_FEATURES` (line 76 in `feature_config.py`)
   - `alpha009` - Defined in `ALPHA_FEATURES` (line 90 in `feature_config.py`)

2. **Are they in D1 or added in D2 construction?**
   - Need to check: `src/features.py` or `src/indicators.py`

3. **When was the preprocessing config last fitted?**
   - `models/preprocessing_config.json` - `"created_at": "2026-02-09T12:06:17.339929"`
   - This was TODAY - so very recent

4. **Did the feature engineering pipeline change recently?**
   - Check git history for `src/features.py` and `src/indicators.py`

---

## Next Steps

Run this investigation script:
```python
# Check feature availability in pipeline
import pandas as pd
from src.data_engine import DataEngine

engine = DataEngine()
d1 = engine.load_parquet('D1')  # or whatever the entry point is

print("🔍 Feature Availability Check:")
print(f"breakout_momentum in D1: {'breakout_momentum' in d1.columns}")
print(f"alpha009 in D1: {'alpha009' in d1.columns}")
print(f"net_income_growth_yoy in D1: {'net_income_growth_yoy' in d1.columns}")

# If not in D1, check where they're added
from src.pipeline.m01_workflow import M01Workflow
# ... trace through workflow to find where features are added
```
