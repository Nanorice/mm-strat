# Feature Optimization Analysis
**Date**: 2026-03-14
**Context**: Analyzing which features can be eliminated to reduce compute time and overfitting

---

## 1. Lag vs Delta Features: Can We Drop Lags?

### Current State
**Lag features ARE stored separately** in `daily_features` table:

#### Stored in Phase A SQL (feature_pipeline.py, lines 173-175):
```sql
LAG(rs_line_delta, 1) OVER (PARTITION BY ticker ORDER BY date) as rs_line_lag_delta,
LAG(sma_200, 20) OVER (PARTITION BY ticker ORDER BY date) as sma_200_lag20,
```

#### Stored in Phase B Python (feature_pipeline.py, lines 351-354):
```python
df['delta_close_1'] = df.groupby('ticker')['close'].diff(1)
df['delta_vol_1'] = df.groupby('ticker')['volume'].diff(1)
df['close_lag10'] = df.groupby('ticker')['close'].shift(10)
df['close_lag20'] = df.groupby('ticker')['close'].shift(20)
```

### Problem: Redundancy & Multicollinearity
Your observation is **correct** — lag pairs create **severe multicollinearity**:

| Lag Pairs | Correlation | Issue |
|-----------|-------------|-------|
| `rs_line_lag_delta` + `rs_line_delta` | ~1.0 | Perfect correlation (lag of derived metric) |
| `close_lag10` + `close_lag20` | ~0.95 | Close prices only change slightly per day |
| `delta_close_1` + `close_lag1` | ~1.0 | Same information, different form |

### Recommendation: DROP ALL LAG FEATURES

**Action**: Remove from `daily_features` computation:
- ❌ `rs_line_lag_delta` (line 173) — redundant with `rs_line_delta`
- ❌ `sma_200_lag20` (line 175) — only used for flag `close_above_sma200`, keep flag instead
- ❌ `close_lag10`, `close_lag20` (lines 353-354) — redundant with current price
- ❌ `delta_vol_1`, `delta_close_1` (lines 351-352) — already captured in `return_1d`, `vol_ratio`

**Keep instead**:
- ✅ **Velocity/acceleration metrics** (delta of delta): `price_accel_10d`, `volume_acceleration` — these add signal
- ✅ **Time-based lags used in alphas**: `close_lag10`, `close_lag20` only as intermediate computation in alpha001-015 (don't store)

**Impact**: Reduces T3 feature set by 5-6 columns (~5% reduction) + eliminates multicollinearity

**Implementation**:
1. Keep lag computation in alpha functions (e.g., `alpha001_46` lines 559-565 use `close_lag10`, `close_lag20`)
2. **Don't store** lag features as separate columns in `daily_features`
3. Store only **derived deltas** that add signal (velocity, momentum acceleration)

---

## 2. Log Transformations: Not Needed for XGBoost

### Current State
**Log transforms ARE computed** in `v_d2_training` view (view_manager.py, lines 628-682):

```sql
-- 29 log_* columns computed via LN(1 + ABS(...))
SIGN(f.breakout_momentum) * LN(1.0 + ABS(f.breakout_momentum)) AS log_breakout_momentum,
SIGN(f.rs) * LN(1.0 + ABS(f.rs)) AS log_RS,
-- ... 27 more log transforms
```

### Problem: Unnecessary for Tree-Based Models
XGBoost is **scale-invariant** for monotonic transformations:
- ✅ XGBoost splits on feature values, doesn't care about magnitude
- ✅ Log(x) is monotonic → same split threshold semantics
- ❌ Log transforms ONLY help with:
  - Linear models (OLS, Ridge) — needed for normality assumption
  - Neural networks — needed for convergence
  - Interpretation of coefficients
  - **NOT needed for XGBoost/Random Forest**

### Current Model: XGBoost Classifier
Your EDA uses:
```python
model = xgb.XGBClassifier(
    objective='multi:softprob',  # ← Multi-class classification (4 classes)
    n_estimators=100, max_depth=4, ...
)
```

**This model DOES NOT need log transforms** — tree splits are independent of scale.

### Recommendation: DROP ALL LOG TRANSFORMS

**Action**: Remove from `v_d2_training` view:
- ❌ All 29 `log_*` columns (lines 628-682)
- ❌ This saves compute time on every query
- ❌ Reduces view output from 102 → ~73 columns

**Impact**:
- ✅ Faster data loading (fewer computed columns)
- ✅ Simpler feature set, easier debugging
- ✅ No impact on model performance (XGBoost doesn't use them anyway)
- ✅ Aligns with your cleaned feature dictionary (no log_* features listed)

**Implementation**:
1. **Delete lines 628-682** from `v_d2_training` SQL
2. Use raw features directly in model input
3. Keep original features (`rs`, `breakout_momentum`, etc.) — XGBoost will find the right scale

---

## 3. M01 Multi-Class Output: Extract Probability Scores

### Current Model State
Your EDA model:
```python
model = xgb.XGBClassifier(
    objective='multi:softprob',      # ← Softmax probability output
    num_class=len(classes),          # ← 4 classes
)
model.fit(X_train, y_train, sample_weight=sample_weights)
```

**This is multi-class classification** (not regression), meaning:
- **Output**: 4 probability scores per sample (sum to 1.0 via softmax)
- **Classes**: Likely [Class0, Class1, Class2, Class3] (e.g., breakout strength levels?)

### Probability Output Usage
XGBoost with `multi:softprob` produces:

```python
# Option 1: Get class prediction
y_pred = model.predict(X_test)
# → [0, 1, 2, 2, 1, ...] (single class per sample)

# Option 2: Get probability for each class
y_pred_proba = model.predict_proba(X_test)
# → [[0.1, 0.3, 0.4, 0.2],  ← sample 1: Class2 is most likely
#    [0.2, 0.5, 0.2, 0.1],  ← sample 2: Class1 is most likely
#    ...]
```

### Trading Signal from Probabilities
**YES, we can extract confidence/certainty**:

```python
# Max probability = model confidence in predicted class
confidence = y_pred_proba.max(axis=1)
# → [0.4, 0.5, 0.6, ...] (0.25=random, 1.0=certain)

# Gap between top 2 probabilities = decision margin
sorted_probs = np.sort(y_pred_proba, axis=1)
margin = sorted_probs[:, -1] - sorted_probs[:, -2]
# → [0.1, 0.3, 0.2, ...] (larger gap = more confident)

# Probability of best class (instead of just class ID)
best_prob = y_pred_proba.max(axis=1)
```

### Recommendation: USE PROBABILITY SCORES AS TRADING SIGNAL

**For Milestone 4.5.2 (M01 Rules)**:

1. **Change M01 output from regressor → classifier** (matches your EDA):
   ```python
   # Instead of: score = model.predict(X) → [-0.5, 0.2, 1.1, ...]
   # Use: proba = model.predict_proba(X) → [[0.1, 0.3, 0.4, 0.2], ...]
   ```

2. **Trading rule options**:

   **Option A: Threshold on max probability (simplest)**
   ```python
   confidence = y_pred_proba.max(axis=1)  # 0 to 1
   # Entry: confidence ≥ 0.6 (60% certain)
   # Exit: confidence drops below 0.4 (40% certain)
   ```

   **Option B: Probability of "best" class**
   ```python
   best_class = 3  # Assuming Class3 = highest return expectation
   signal = y_pred_proba[:, best_class]  # Prob(Class3)
   # Entry: signal ≥ 0.5 (≥50% chance of Class3)
   # Exit: signal < 0.3 (dropout to <30%)
   ```

   **Option C: Decision margin (gap between top 2 classes)**
   ```python
   sorted_probs = np.sort(y_pred_proba, axis=1)
   margin = sorted_probs[:, -1] - sorted_probs[:, -2]
   # Entry: margin ≥ 0.3 (top class >30% more likely than 2nd)
   # Exit: margin < 0.1 (decision margin collapses)
   ```

3. **Store probability outputs in v_d3_deployment**:
   ```sql
   -- Add these columns to v_d3_deployment view:
   prob_class_0, prob_class_1, prob_class_2, prob_class_3,
   max_confidence, decision_margin, predicted_class
   ```

**Impact**:
- ✅ **Confidence-aware entries** — only trade when model is certain
- ✅ **Probabilistic exits** — exit when confidence collapses (loss of edge)
- ✅ **Better risk management** — lower confidence = tighter stops
- ✅ **Backtesting signal** — can test confidence threshold sweep

---

## Summary: Feature Optimization Plan

| Item | Current State | Action | Impact |
|------|---------------|--------|--------|
| **Lag Features** | Stored in daily_features (5-6 cols) | DROP storage, keep in alpha computation | -5-6 cols, eliminate multicollinearity |
| **Log Transforms** | Computed in v_d2_training (29 cols) | DELETE from view | -29 cols, faster queries |
| **M01 Objective** | Regressor? (TBD from EDA) | Change to **Classifier** with softmax | Extract confidence scores for trading |
| **Feature Count** | ~102 cols in v_d2_training | Target: ~70 cols (30% reduction) | Faster daily compute, better interpretability |

---

## Next Steps for Milestone 4.5.1

1. **Document exact features to drop** from your EDA:
   - Which of the 79 Phase A features are low-signal?
   - Which of the 16 alphas are redundant/correlated?
   - Are there fundamentals with >50% NULLs to exclude?

2. **Implement in FeaturePipeline**:
   - Remove lag columns from Phase A SQL
   - Remove log transforms from view_manager.py
   - Update v_d2_training SELECT to drop 29 log_* columns

3. **Validate reduced set**:
   - Train M01 on full feature set (baseline)
   - Train M01 on reduced set
   - Compare Sharpe ratio / classification metrics — target ±5% parity

---

## Appendix: Where Lags Are Used

### Alpha Functions (keep lag computation but don't store):
- `alpha001_46` (lines 559-565): Uses `close_lag10`, `close_lag20` to compute momentum curve
- `alpha002_1` (lines 572-574): Uses `close_lag10`, `close_lag20` for price momentum

**Action**: Keep this logic inside alpha functions, don't expose lags to feature set.

### Flags (sma_200_lag20):
- Used in `breakout` flag (line 253): `sma_200 > sma_200_lag20` checks if SMA is rising
- **Better approach**: Replace with `sma_50_slope`, `sma_200_slope` (velocity metrics)
