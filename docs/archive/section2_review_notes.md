# Section 2 Review Notes

## Issues Fixed

### 1. Variable Name Errors (Cell 19)
**Issue:** `n_train_samples` and `mean_r2` don't exist in model_m01_config.json
**Root Cause:** Config only stores `validation_metrics` array with per-fold stats, not aggregate training stats
**Fix:** Changed `n_features` to use `len(m01_config.get('feature_columns', M01_FEATURES))`

### 2. Survivor Model Flag (Cell 19)
**Issue:** `survivor_model` flag displayed as False
**Root Cause:** This flag is a training-time parameter, not stored in the config
**Fix:** Hardcoded display to `True # (M01 trained on survivors only)` since we know M01 was trained with `--survivor-model`

### 3. Quintiles vs Deciles (Cell 24)
**Issue:** User requested deciles instead of quintiles
**Status:** ✅ Already implemented! Cell 24 uses `pd.qcut(q=10)` for decile analysis

### 4. FOMO/Toxic Error Analysis Data Leakage (Cell 26)
**Issue:** Testing on same data used for training
**Analysis:**
- `survivors_df` = full d2_features merged with survivor labels
- Contains ALL data (2019-2025), including training years
- M01 trained with walk-forward validation (3-year train, 1-year test)
- FOMO/Toxic analysis runs on entire dataset → **Data leakage**

**Fix Applied:** Added warning message:
```python
print("⚠️  NOTE: This includes training data - use for EDA only, not final validation")
```

**Recommendation:**
- Current analysis is useful for understanding model behavior patterns
- For true out-of-sample validation, should:
  1. Only analyze predictions on held-out test years
  2. Or move to Section 4 when evaluating portfolio with 3bar filter

## Question 3: Should FOMO/Toxic Move to Section 4?

**Current Position (Section 2):**
- ✅ Good for: Understanding M01's raw prediction errors before any filtering
- ❌ Problem: No downside protection yet (3bar filter not applied)
- ❌ Problem: Data leakage (includes training data)

**Alternative Position (Section 4):**
- ✅ Would incorporate 3bar ignition filter
- ✅ Could analyze error patterns on final portfolio candidates
- ✅ More realistic assessment with downside protection
- ✅ Could properly separate train/test for validation

**Recommendation:**
Keep in Section 2 BUT:
1. ✅ Add warning about training data (DONE)
2. Add similar analysis in Section 4 for filtered portfolio
3. Compare error patterns before/after 3bar filtering

## Model Performance Review

Based on `model_m01_config.json`:

### Walk-Forward Validation Results (5 folds):

| Year | Train N | Test N | RMSE | MAE  | Selection Edge | Top Decile | Top2 Edge |
|------|---------|--------|------|------|----------------|------------|-----------|
| 2021 | 2,159   | 1,464  | 28.4 | 13.9 | **18.9%**     | 38.5%      | 15.9%     |
| 2022 | 3,011   | 488    | 17.3 | 13.2 | **17.6%**     | 30.3%      | 12.1%     |
| 2023 | 2,663   | 896    | 26.1 | 15.1 | **15.7%**     | 35.1%      | 15.1%     |
| 2024 | 2,848   | 1,133  | 30.1 | 14.8 | **30.2%**     | 51.4%      | 21.0%     |
| 2025 | 2,517   | 1,225  | 30.6 | 18.6 | **14.7%**     | 26.8%      | 11.4%     |

**Average:** Selection Edge = **19.4%** | Top Decile = **36.4%**

### Key Observations:

#### ✅ Strengths:
1. **Consistent Selection Edge**: 14.7% - 30.2% across all years
   - Never negative (always beats random selection)
   - Average 19.4% uplift for top decile vs. average survivor

2. **Strong 2024 Performance**:
   - Best year: 51.4% top decile mean, 30.2% edge
   - Suggests model captures strong momentum regimes well

3. **Reasonable MAE**: 13-19%
   - Given that survivors have mean y_max ~18-20%, this is acceptable
   - Model isn't wildly off in magnitude predictions

#### ⚠️ Concerns:

1. **High RMSE (17-31%)**:
   - Large variance in prediction errors
   - Indicates outliers or regime-dependent performance
   - RMSE much higher than MAE suggests fat-tailed errors

2. **2025 Weakness**:
   - Lowest performance: 26.8% top decile, 14.7% edge
   - Could indicate:
     - Different market regime (rotation, consolidation)
     - Feature drift
     - Survivor bias changing (more/fewer crashes)

3. **No Calibration Metrics**:
   - Config doesn't show correlation or R²
   - Can't assess if predictions are well-calibrated
   - Only know ranking quality, not magnitude accuracy

4. **Sample Size Variation**:
   - Test sets range from 488 (2022) to 1,464 (2021)
   - Larger test sets in 2024-2025 with mixed results
   - Suggests signal strength varies with market conditions

### Model Quality Assessment: **B+ / A-**

**Verdict:**
- M01 is a **strong ranker** (consistent positive selection edge)
- But **weak calibrator** (high RMSE, large prediction variance)
- Perfect for **portfolio construction** (top decile selection)
- Not ideal for **position sizing** (magnitude predictions unreliable)

### Recommended Actions:

1. **Immediate:**
   - ✅ Fixed variable errors in notebook
   - ✅ Added data leakage warning
   - Run Section 2 to visualize decile performance

2. **Section 4 Enhancements:**
   - Add FOMO/Toxic analysis AFTER 3bar filter
   - Compare error rates before/after ignition filter
   - Analyze if 3bar reduces Toxic errors (false positives)

3. **Future Model Improvements:**
   - Investigate 2025 weakness (feature drift?)
   - Add regime detection (bull/bear/rotation)
   - Consider ensemble with volatility-adjusted targets
   - Test if 3bar predictions improve calibration

## Decile Analysis (Already Implemented)

The notebook already uses **deciles** (10 bins) not quintiles:
- Cell 24: `pd.qcut(survivors_df['m01_prediction'], q=10)`
- Provides finer granularity for top/bottom analysis
- Matches the config's `top_decile_mean` metric

No changes needed here!
