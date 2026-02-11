# 🐛 BUG REPORT: Preprocessing Decision Tree Logic Error
**Date:** 2026-02-09
**Severity:** ⚠️ HIGH - Blocks M01 training
**Status:** 🔴 CONFIRMED

---

## Problem Statement

Training M01 fails with:
```
Missing 3 features: ['log_breakout_momentum', 'log_alpha009', 'log_net_income_growth_yoy']
```

---

## Root Cause

### Bug Location: [feature_preprocessor.py:194-218](../src/feature_preprocessor.py#L194-L218)

The decision tree in `FeaturePreprocessor.fit()` has **INCORRECT LOGIC ORDER**:

```python
# CURRENT (BUGGY) CODE:
for feature in features:
    # ... (skip if not in df.columns)

    # Check kurtosis
    kurt = stats.kurtosis(series, fisher=True)
    if abs(kurt) <= self.kurtosis_threshold:  # ❌ BUG: Checks kurtosis FIRST
        continue  # Normal distribution, no transform needed

    feature_config = {'original_kurtosis': float(kurt)}

    # Decision tree
    if feature in BOUNDED_FEATURES:
        # ... winsorize
    elif feature in EXPLOSIVE_FEATURES:  # ← NEVER REACHED for low-kurtosis features
        # ... log transform
    elif feature in STANDARD_FEATURES:
        # ... winsorize
```

### Why This Is Wrong

The `EXPLOSIVE_FEATURES` list is a **MANUAL CURATION** of features known to need log transforms based on:
- Domain knowledge (e.g., `breakout_momentum` measures ATR-normalized breakouts, fat tails expected)
- Visual inspection of distributions
- Theoretical understanding of feature semantics

**The kurtosis check should NOT override manual curation.**

### Correct Logic Order

```python
# CORRECT CODE (Fixed):
for feature in features:
    # ... (skip if not in df.columns)

    series = df[feature].dropna()
    if len(series) < 100:
        continue

    # Check kurtosis
    kurt = stats.kurtosis(series, fisher=True)
    feature_config = {'original_kurtosis': float(kurt)}

    # Decision tree - PRIORITY ORDER MATTERS
    if feature in BOUNDED_FEATURES:
        # Always winsorize bounded features (e.g., RSI_14: 0-100)
        # ... (lines 202-211 unchanged)

    elif feature in EXPLOSIVE_FEATURES:
        # FORCE log transform (MANUAL OVERRIDE - bypass kurtosis check)
        feature_config.update({
            'transform': 'log',
            'category': 'explosive'
        })

    elif feature in STANDARD_FEATURES:
        # Always winsorize standard features (e.g., margins, slopes)
        # ... (lines 220-229 unchanged)

    else:
        # Unknown feature - use empirical kurtosis + TAR
        if abs(kurt) <= self.kurtosis_threshold:
            continue  # ← Kurtosis check ONLY for unknown features

        tar = self.compute_tail_alpha_ratio(df, feature, target)
        feature_config['tail_alpha_ratio'] = float(tar)

        if tar > self.tail_alpha_threshold:
            feature_config.update({'transform': 'log', 'category': 'tar_based'})
        else:
            lower = float(np.percentile(series, self.lower_percentile))
            upper = float(np.percentile(series, self.upper_percentile))
            feature_config.update({
                'transform': 'winsorize',
                'category': 'tar_based',
                'lower_bound': lower,
                'upper_bound': upper
            })

    self.config['features'][feature] = feature_config
```

---

## Evidence

### 1. Features Exist in D2 ✅
```python
d2 = pd.read_parquet('data/ml/d2.parquet')
print('breakout_momentum' in d2.columns)  # True
print('alpha009' in d2.columns)           # True
```

### 2. Features Passed to fit() ✅
```python
numeric_cols = d2.select_dtypes(include=[np.number]).columns.tolist()
preprocess_cols = [c for c in numeric_cols if c not in exclude_cols]
print('breakout_momentum' in preprocess_cols)  # True
print('alpha009' in preprocess_cols)           # True
```

### 3. Features In EXPLOSIVE_FEATURES ✅
```python
# feature_preprocessor.py lines 38-55
EXPLOSIVE_FEATURES = [
    # ...
    'breakout_momentum',  # Line 52
    'alpha009',           # Line 54
]
```

### 4. Kurtosis Too Low → Skipped ❌
```python
from scipy import stats
d2 = pd.read_parquet('data/ml/d2.parquet')

print(f"breakout_momentum kurtosis: {stats.kurtosis(d2['breakout_momentum'], fisher=True):.2f}")
# Output: 8.30 (< 10.0 threshold)

print(f"alpha009 kurtosis: {stats.kurtosis(d2['alpha009'], fisher=True):.2f}")
# Output: 6.96 (< 10.0 threshold)

# Compare with price_momentum_curve (which DID get fitted):
print(f"price_momentum_curve kurtosis: {stats.kurtosis(d2['price_momentum_curve'], fisher=True):.2f}")
# Output: 12.13 (> 10.0 threshold) ✅
```

### 5. Features Missing From Config ❌
```python
import json
config = json.load(open('models/preprocessing_config.json'))

print('breakout_momentum' in config['features'])  # False
print('alpha009' in config['features'])           # False
print('price_momentum_curve' in config['features'])  # True ✅
```

---

## Impact Analysis

### Affected Features
Based on kurtosis analysis, the following `EXPLOSIVE_FEATURES` may be silently skipped:

| Feature | Kurtosis | Skipped? | In M01_FEATURES? | Impact |
|---------|----------|----------|------------------|--------|
| `breakout_momentum` | 8.30 | ✅ YES | ✅ YES | 🔴 **BLOCKS TRAINING** |
| `alpha009` | 6.96 | ✅ YES | ✅ YES | 🔴 **BLOCKS TRAINING** |
| `price_momentum_curve` | 12.13 | ❌ NO | ✅ YES | ✅ OK |
| `revenue_growth_yoy` | ? | ? | ✅ YES | ⚠️ **NEED TO CHECK** |
| `eps_growth_yoy` | ? | ? | ✅ YES | ⚠️ **NEED TO CHECK** |
| `pe_ratio` | ? | ? | ✅ YES | ⚠️ **NEED TO CHECK** |

### Secondary Issue: `net_income_growth_yoy`

This feature has a DIFFERENT problem:
- **Current:** Winsorized (TAR=1.17 < 1.2 threshold)
- **Expected:** Should use `arcsinh()` transform (can be deeply negative)
- **Impact:** `log_net_income_growth_yoy` created but mathematically incorrect
- **Fix:** See "Recommended Fixes" section below

---

## Why Kurtosis Can Be Misleading

### Case Study: `breakout_momentum`

**Definition:** `(Close - High_20D) / ATR` (Breakout strength in ATR units)

**Expected Distribution:**
- **Most days:** Stock not breaking out → values near 0 (kurtosis contribution: low)
- **Breakout days:** Stock breaks out → values of 2-5 ATR (fat right tail)
- **Rare igniters:** Explosive breakout → values of 8-15 ATR (extreme right tail)

**Problem with Kurtosis:**
- In a **sparse signal** (only 5% of days are breakouts), the **bulk of the distribution is near zero**
- This creates a **LOW KURTOSIS** despite having **critical fat-tail information** in the right tail
- The kurtosis is **diluted by the 95% of zero-signal days**

**Why We MUST Log Transform Anyway:**
- The 5% of breakout days contain the **alpha signal** (predictive power)
- Raw values of 10+ ATR will **dominate linear models** (numerical scale mismatch)
- Log transform **compresses the right tail** so XGBoost can learn thresholds effectively

**Analogy:**
- Kurtosis says: "This data looks normal" (because 95% is noise)
- Domain expert says: "The 5% tail is what matters, and it's explosive"
- **We must trust the domain expert, not the summary statistic.**

---

## Recommended Fixes

### Fix 1: Move Kurtosis Check Inside "Unknown Feature" Branch ✅

**Priority:** 🔴 CRITICAL (blocks training)

**Changes:**
1. Remove lines 195-197 (early kurtosis check)
2. Move kurtosis check INSIDE the `else` block (line 231+)
3. Ensure `EXPLOSIVE_FEATURES`, `BOUNDED_FEATURES`, `STANDARD_FEATURES` are **ALWAYS RESPECTED** regardless of kurtosis

**File:** `src/feature_preprocessor.py`

**Implementation:** See "Correct Logic Order" above

---

### Fix 2: Add ARCSINH Transform Category ⚠️

**Priority:** 🟡 MEDIUM (technical debt)

**Problem:** `net_income_growth_yoy` can be deeply negative (losses), so:
- `signed_log(x) = sign(x) * log(1 + |x|)` works but is suboptimal near zero
- `arcsinh(x) = log(x + sqrt(x^2 + 1))` is smoother for bipolar distributions

**Changes:**
1. Add `ARCSINH_FEATURES` list
2. Add `arcsinh_transform()` static method
3. Update `fit()` to check `ARCSINH_FEATURES`
4. Update `transform()` to apply `arcsinh` and create `arcsinh_{feature}` columns
5. Update `M01_FEATURES` to use `arcsinh_net_income_growth_yoy` instead of `log_`

**File:** `src/feature_preprocessor.py`

---

### Fix 3: Add Validation Function ⚠️

**Priority:** 🟡 MEDIUM (prevents future bugs)

**Implementation:**
```python
def validate_explosive_features_coverage(
    preprocessor: FeaturePreprocessor,
    df: pd.DataFrame
) -> None:
    """
    Validate that all EXPLOSIVE_FEATURES in df were fitted.

    Raises:
        AssertionError: If any explosive feature was skipped
    """
    from src.feature_preprocessor import EXPLOSIVE_FEATURES

    missing = []
    for f in EXPLOSIVE_FEATURES:
        if f in df.columns and f not in preprocessor.config['features']:
            missing.append(f)

    if missing:
        raise AssertionError(
            f"EXPLOSIVE_FEATURES skipped during fit(): {missing}\n"
            f"This indicates a bug in the decision tree logic.\n"
            f"All EXPLOSIVE_FEATURES should be force-transformed regardless of kurtosis."
        )
```

**Usage:**
```python
# In m01_trainer.py after fit()
preprocessor.fit(data, preprocess_cols, target='return_pct')
validate_explosive_features_coverage(preprocessor, data)  # ← Add this
```

---

### Fix 4: Add Logging for Skipped Features 📝

**Priority:** 🟢 LOW (observability)

**Changes:**
```python
# In feature_preprocessor.py, line 196
if abs(kurt) <= self.kurtosis_threshold:
    logger.debug(f"Skipped {feature}: kurtosis={kurt:.2f} below threshold")  # ← Add this
    continue
```

---

## Testing Plan

### Unit Test: Decision Tree Priority
```python
def test_explosive_features_bypass_kurtosis():
    """EXPLOSIVE_FEATURES should transform even with low kurtosis."""
    # Create synthetic data with low kurtosis
    df = pd.DataFrame({
        'breakout_momentum': np.random.normal(0, 1, 1000),  # Normal dist (low kurtosis)
        'return_pct': np.random.normal(0, 0.02, 1000)
    })

    preprocessor = FeaturePreprocessor()
    preprocessor.fit(df, ['breakout_momentum'], target='return_pct')

    # Assert: Must be in config despite low kurtosis
    assert 'breakout_momentum' in preprocessor.config['features']
    assert preprocessor.config['features']['breakout_momentum']['transform'] == 'log'
    assert preprocessor.config['features']['breakout_momentum']['category'] == 'explosive'
```

### Integration Test: M01 Training
```bash
# After fix, this should succeed:
python -m src.pipeline.m01_workflow train --model_version M01_test
```

---

## Documentation Updates

### Update: [feature_preprocessing_guide.md](feature_preprocessing_guide.md)
Add decision tree flowchart with PRIORITY ORDER clearly marked:
```
1. BOUNDED_FEATURES → Always winsorize
2. EXPLOSIVE_FEATURES → Always log transform (MANUAL OVERRIDE)
3. STANDARD_FEATURES → Always winsorize
4. Unknown features → Use kurtosis + TAR
```

### Update: [CLAUDE.md](../.claude/CLAUDE.md)
Add rule:
```markdown
## Feature Preprocessing Rules
- `EXPLOSIVE_FEATURES` list is SACROSANCT - kurtosis check must NOT override it
- Adding a feature to `EXPLOSIVE_FEATURES` is a **semantic assertion** that overrides statistics
- If a feature is in `EXPLOSIVE_FEATURES`, it WILL be log-transformed, even if kurtosis=0
```

---

## Immediate Action Plan

### Step 1: Fix feature_preprocessor.py ✅
1. Edit [feature_preprocessor.py:194-250](../src/feature_preprocessor.py#L194-L250)
2. Move kurtosis check to "unknown features" branch
3. Run unit tests

### Step 2: Re-fit Preprocessing Config ✅
```bash
# Delete old config
rm models/preprocessing_config.json

# Re-run M01 workflow (will auto-refit)
python -m src.pipeline.m01_workflow train --model_version M01_fixed
```

### Step 3: Validate Results ✅
```python
import json
config = json.load(open('models/preprocessing_config.json'))

# Must be True after fix:
assert 'breakout_momentum' in config['features']
assert 'alpha009' in config['features']
assert config['features']['breakout_momentum']['transform'] == 'log'
assert config['features']['alpha009']['transform'] == 'log'
```

### Step 4: Create Transformation Documentation 📝
- Write [feature_preprocessing_guide.md](feature_preprocessing_guide.md)
- Add flowchart, examples, debugging tips

---

## Related Files

- 🐛 **Bug location:** [src/feature_preprocessor.py:194-250](../src/feature_preprocessor.py#L194-L250)
- 📋 **Feature config:** [src/feature_config.py:38-55](../src/feature_config.py#L38-L55) (EXPLOSIVE_FEATURES)
- 🧪 **Training pipeline:** [src/pipeline/m01_trainer.py:432](../src/pipeline/m01_trainer.py#L432) (fit() call)
- 📦 **Fitted config:** `models/preprocessing_config.json` (needs re-fit)
- 📊 **Gap analysis:** [docs/feature_preprocessing_gap_analysis.md](feature_preprocessing_gap_analysis.md)

---

## Conclusion

**This is a LOGIC ERROR, not a data issue.**

The kurtosis check was added as a **performance optimization** to skip transforming normal distributions.
However, it was placed **BEFORE** the manual feature classification checks, causing it to override domain knowledge.

**The fix is simple:** Move the kurtosis check to only apply to **unknown features**, where we need empirical guidance.

For **manually curated feature lists** (`EXPLOSIVE_FEATURES`, `BOUNDED_FEATURES`, `STANDARD_FEATURES`), we must **trust the domain expert** over summary statistics.
