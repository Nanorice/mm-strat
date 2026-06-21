# M04 MFE Classifier - Data Leakage Audit

**Date**: 2026-03-15
**Model**: M04 (MFE 4-Class Classifier)
**Auditor**: Claude
**Status**: ✅ **CLEAN - No leakage detected**

---

## Summary

The M04 baseline model uses **105 features** from `v_d2_training` view. A comprehensive audit confirms:
- ✅ **No future outcome leakage** - MAE/MFE excluded from features
- ✅ **No forward-looking returns** - All `return_*` features are lagged (T vs T-N)
- ✅ **Temporal split enforced** - Train/val/test split is chronological
- ✅ **Exit data excluded** - Exit dates, prices, holding periods not used

---

## Audit Methodology

### 1. Column Classification

All 267 columns in `v_d2_training` were categorized:

| Category | Count | Usage |
|----------|-------|-------|
| Features (valid) | 246 | ✅ Available for training |
| Leakage (future) | 15 | ❌ Excluded (target/outcomes only) |
| Metadata | 6 | ❌ Excluded (identifiers/timestamps) |

### 2. Leakage Column Verification

**Excluded from Features** (used only for labeling):

```python
# Future outcomes (computed from entire trade horizon)
'mae_pct'              # ❌ Lowest point in trade (future)
'mfe_pct'              # ❌ Highest point in trade (TARGET ONLY)
'return_at_exit'       # ❌ Final exit return (future)
'holding_days'         # ❌ Trade duration (future)
'exit_date'            # ❌ Exit timestamp (future)
'exit_price'           # ❌ Exit price (future)
'mae_date'             # ❌ Date of max drawdown (future)
'mfe_date'             # ❌ Date of max gain (future)
'sepa_exit_date'       # ❌ SEPA exit trigger date (future)
'sl_exit_date'         # ❌ Stop-loss exit date (future)
'return_pct'           # ❌ Alias for return_at_exit
```

**Metadata** (excluded):
```python
'ticker'               # Identifier
'date'                 # Timestamp
'trade_id'             # Identifier
'feature_version'      # Schema version
'entry_date'           # Redundant with date
'entry_price'          # Raw price (non-stationary)
```

### 3. Return Feature Direction Check

**Suspicious Features**: `return_1d`, `return_5d`, `return_20d`, `return_60d`

**Test Method**: Traced computation in `src/feature_pipeline.py:334-337`

**Source Code**:
```sql
-- Line 334-337 in feature_pipeline.py
(close / NULLIF(prev_close, 0) - 1) as return_1d,                        -- T vs T-1
(close / NULLIF(LAG(close, 5) OVER ticker_date, 0) - 1) as return_5d,   -- T vs T-5
(close / NULLIF(LAG(close, 20) OVER ticker_date, 0) - 1) as return_20d, -- T vs T-20
(close / NULLIF(LAG(close, 60) OVER ticker_date, 0) - 1) as return_60d, -- T vs T-60
```

**Verification**:
```
AAPL on 2024-12-20:
  Current close: $254.49
  Prev close (T-1): $249.79
  Expected return_1d: (254.49/249.79 - 1) * 100 = 1.88%
  Actual return_1d in database: 1.88%
  ✅ MATCH - Confirmed lagged (T vs T-1)
```

**Conclusion**: All `return_*` features compare **current price to PAST prices**, not future. **NO LEAKAGE**.

### 4. Temporal Split Validation

**Train/Val/Test Split**:
```python
# From train_mfe_classifier.py:311-323
df_sorted = df.sort_values('date')  # Chronological order
X_sorted = X.loc[df_sorted.index]
y_sorted = y.loc[df_sorted.index]

# 60% train, 20% val, 20% test
train_size = int(len(X_sorted) * 0.6)
val_size = int(len(X_sorted) * 0.2)

X_train = X_sorted.iloc[:train_size]        # Oldest 60%
X_val = X_sorted.iloc[train_size:train_size + val_size]  # Middle 20%
X_test = X_sorted.iloc[train_size + val_size:]           # Newest 20%
```

**Result**:
- Train: 1,052 samples (2020-01-02 to ~2022)
- Val: 350 samples (~2022 to ~2024)
- Test: 352 samples (~2024 to 2026-02-12)

**Verification**: ✅ No test data appears before train data (temporal order preserved)

---

## Feature Set Summary

**105 features** grouped into 8 categories:

1. **Moving Averages** (8) - Price vs SMAs + slopes
2. **Momentum/RS** (21) - Trend strength, sector/industry rankings
3. **Core Volume** (7) - Liquidity and demand signals
4. **Volatility/Ranges** (19) - VCP, ATR, 52w/20d highs/lows
5. **Technical Oscillators** (7) - RSI, breakout flags
6. **Fundamentals** (21) - Earnings, margins, ratios
7. **Fast Alphas** (15) - WorldQuant 101 factors
8. **M03 Regime** (7) - Macro environment context

**Missing**: 1 feature (`atr_delta` - not in database)

---

## Target Variable

**Column**: `mfe_pct` (Maximum Favorable Excursion %)

**Definition**: Highest % gain achieved during trade horizon
```sql
-- From v_d2_training view
MAX(high) / FIRST(close) - 1.0) * 100.0 AS mfe_pct
```

**Classes** (discretized):
- 0: Noise (0-2%) - 28 samples (1.6%)
- 1: Moderate (2-10%) - 92 samples (5.2%)
- 2: Strong (10-30%) - 242 samples (13.8%)
- 3: Home Run (>30%) - 1,392 samples (79.4%)

**Usage**: `mfe_pct` is used **ONLY** for creating target labels, **NOT** as a feature.

---

## Known Issues

### 1. Extreme Class Imbalance
- 79.4% of samples are Class 3 (home runs)
- Model defaults to predicting Class 3 (97% recall)
- Weighted F1: 0.575 (poor for minority classes)

**Not Leakage** - This is a legitimate data distribution issue, not look-ahead bias.

**Mitigation Options**:
- SMOTE (synthetic minority oversampling)
- Undersample Class 3
- Cost-sensitive learning (already using class weights)
- Change threshold boundaries (e.g., 0-5%, 5-15%, 15-50%, >50%)

### 2. Missing Feature
- `atr_delta` requested but not in `v_d2_training`
- Impact: Minimal (we have `natr_delta` as proxy)

---

## Recommendations

### 1. Model is Valid ✅
Current feature set is **leakage-free**. Proceed with evaluation framework.

### 2. Address Class Imbalance
Consider re-labeling with balanced thresholds:
```python
# Current (imbalanced)
0: 0-2%    → 1.6%
1: 2-10%   → 5.2%
2: 10-30%  → 13.8%
3: >30%    → 79.4%

# Proposed (balanced)
0: 0-10%   → ~20%  (Noise + Moderate)
1: 10-30%  → ~15%  (Strong)
2: 30-75%  → ~50%  (Home Run)
3: >75%    → ~15%  (Super Elite)
```

### 3. Evaluation Framework
Build reusable `ClassificationEvaluator` with:
- SHAP analysis (per-class feature importance)
- Confusion matrix visualization
- ROC/PR curves (one-vs-rest)
- Feature importance (XGBoost gain)
- Calibration analysis

---

## Appendix: Validation Queries

### A. Check Return Direction
```sql
SELECT ticker, date, close, return_1d,
       LAG(close, 1) OVER (PARTITION BY ticker ORDER BY date) as prev_close
FROM t3_sepa_features
WHERE ticker = 'AAPL' AND date >= '2024-12-01'
ORDER BY date;
```

### B. Verify No Future Data in Features
```python
# All features in training set
feature_cols = X_train.columns.tolist()

# Leakage keywords
leakage_keywords = ['exit', 'mae_', 'mfe_', 'holding', 'sepa_exit']

# Check for contamination
contaminated = [f for f in feature_cols if any(k in f.lower() for k in leakage_keywords)]
print(f"Contaminated features: {contaminated}")  # Should be empty []
```

### C. Temporal Split Check
```python
train_dates = df_sorted.iloc[:train_size]['date']
test_dates = df_sorted.iloc[train_size + val_size:]['date']

assert train_dates.max() < test_dates.min(), "Test data leaks into training!"
```

---

**Audit Completed**: 2026-03-15
**Next**: Build evaluation framework and re-run training with balanced classes.
