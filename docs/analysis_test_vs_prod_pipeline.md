# Test vs Production Pipeline Analysis
**Date:** 2026-02-07
**Issue:** Test pipeline returns MORE trades than Production (opposite of expectation)

## Results Summary

```
D1 Test:  18,219 trades
D1 Prod:  14,792 trades
Common:    7,071 trades
Only Test: 11,148 trades (61% of test)
Only Prod:  7,721 trades (52% of prod)
```

**Key Finding:** Test generates **3,427 MORE trades** than Production (23% increase), despite having a supposedly stricter C9 filter.

---

## Root Cause Analysis

### Volume Filter Discrepancy (C11)

**Production Pipeline** ([indicators.py:431](../src/indicators.py#L431)):
```python
# VCP detection
vcp = df['Breakout'] & (df['Vol_Ratio'] > config.VOL_SPIKE_THRESHOLD)

# Where:
Vol_Ratio = Volume / Volume.shift(1).rolling(50).mean()
VOL_SPIKE_THRESHOLD = 1.3  # Requires 130% of average volume
```

**Test Pipeline** ([data_pipeline_test.py:137-141](../src/pipeline/data_pipeline_test.py#L137-L141)):
```python
# C11: Volume > 50-day average (volume confirmation)
df_matrix['Vol_MA_50'] = df_matrix.groupby('ticker')['Volume'].transform(
    lambda x: x.shift(1).rolling(50).mean()
)
c11 = df_matrix['Volume'] > df_matrix['Vol_MA_50']  # Any increase (1.0x threshold)
```

### Impact

| Filter | Production | Test | Winner |
|--------|-----------|------|--------|
| **C9 (RS Rating)** | `rs_rating > 0` (weak) | `rs_rating >= P70` (strict) | Production (looser) |
| **C11 (Volume)** | `Vol > 1.3 × MA_50` (strict) | `Vol > 1.0 × MA_50` (loose) | **Test (looser)** |

The **C11 discrepancy dominates** the C9 effect:
- C9 being stricter in Test → filters out ~30% candidates
- C11 being looser in Test → accepts ~30% more candidates
- **Net result:** Test gets more trades because volume filter is significantly looser

---

## Additional Differences

### 1. RS Trend Check (Production Only)

**Production** has an additional filter via `check_relative_strength()`:
```python
# From strategy.py:118-130
def check_relative_strength(self, df: pd.DataFrame, date: pd.Timestamp) -> bool:
    rs = self.ta.detect_relative_strength(df)
    return rs.loc[date] if date in rs.index else False
```

This checks if `RS > RS.rolling(63).mean()` (RS trending up).

**Test** only checks this once at entry (C12), while Production validates it continuously.

### 2. VCP Setup Check (Production Only)

Production uses `detect_vcp_setup()` which combines:
- Breakout (C10 equivalent)
- Volume spike with **1.3× threshold** (stricter than Test's C11)

Test uses raw C10-C12 conditions with **1.0× volume threshold**.

---

## Why Test Has More Trades

### Primary Reason: Looser Volume Filter
- Test's `Volume > MA_50` (any increase) is much looser than Production's `Vol_Ratio > 1.3`
- This alone could add **thousands of false positives**

### Secondary Effects:
1. **No continuous RS validation** - Test only checks RS at entry, Production re-validates
2. **Universe data availability** - Test might have more complete universe coverage (pre-computed features available for more tickers/dates)
3. **Transition detection differences** - Test uses vectorized 0→1 transitions, Production uses sequential daily checks

---

## Recommendations

### Option 1: Align Test to Production Standards (Recommended)
**Goal:** Make Test produce same results as Production, just faster

**Changes needed in `data_pipeline_test.py`:**
```python
# Fix C11 to match Production VCP threshold
from config import VOL_SPIKE_THRESHOLD

# Replace line 141:
c11 = df_matrix['Volume'] > df_matrix['Vol_MA_50']

# With:
df_matrix['Vol_Ratio'] = df_matrix['Volume'] / df_matrix['Vol_MA_50']
c11 = df_matrix['Vol_Ratio'] > VOL_SPIKE_THRESHOLD  # 1.3 threshold
```

**Expected impact:** Test will produce ~30-40% fewer trades, closer to Production count

---

### Option 2: Update Production to Use Stricter C9
**Goal:** Implement true Minervini methodology (top 30% RS) in Production

**Changes needed:**
1. Production must have access to universe-wide RS data (currently only single-ticker)
2. Update `detect_stage2_uptrend()` to accept cross-sectional RS ranking
3. This is a **major refactor** and changes historical backtest results

**Not recommended** without full regression testing of M01/M02 models.

---

### Option 3: Create Hybrid Approach
**Goal:** Best of both worlds

**New pipeline configuration:**
```python
# config.py
SEPA_C9_MODE = 'cross_sectional'  # or 'proxy' (rs_rating > 0)
SEPA_C11_THRESHOLD = 1.3  # Volume spike multiplier
```

This allows A/B testing different SEPA configurations.

---

## Immediate Action Items

### 1. Fix Test Pipeline Volume Filter (HIGH PRIORITY)
**File:** `src/pipeline/data_pipeline_test.py:141`
```python
# Current (WRONG):
c11 = df_matrix['Volume'] > df_matrix['Vol_MA_50']

# Fixed (matching production):
df_matrix['Vol_Ratio'] = df_matrix['Volume'] / df_matrix['Vol_MA_50']
c11 = df_matrix['Vol_Ratio'] > config.VOL_SPIKE_THRESHOLD
```

### 2. Verify C10 Consistency
**Check:** Does Test's `High_20D` match Production's `Breakout` calculation?
```python
# Test: df_matrix['High_20D'] = x.shift(1).rolling(20).max()
# Prod: df['Breakout'] = Close > High.shift(1).rolling(N).max()
```
Need to verify `N` value in Production.

### 3. Add RS Trend Validation (OPTIONAL)
Currently Test only checks C12 once at entry. Production continuously validates RS trend.

### 4. Run Comparison After Fix
```bash
# Fix Test pipeline volume filter
# Re-run test
python model_runner_test.py scan --start-date 2024-01-01 --end-date 2024-03-31

# Compare
python model_runner_test.py compare
```

**Expected outcome:**
- Test trades should decrease from 18,219 to ~13,000-15,000
- Overlap with Production should increase from 7,071 to ~10,000+

---

## Long-Term Considerations

### Universe Parquet Strategy
If Test pipeline proves faster/cleaner after fix:
1. Migrate Production to use Universe Parquet
2. Deprecate `FastTradeSimulator` + `SEPAStrategy` individual ticker loading
3. All pipelines use `VectorizedSEPAScreener` with configurable thresholds

### Testing Requirements
Before production deployment:
1. Validate D1 Test ≈ D1 Prod (>95% overlap)
2. Validate D2 Test ≈ D2 Prod (feature parity)
3. Re-run M01/M02 training with Test data, compare metrics
4. If IC/Precision degrade, investigate feature calculation differences

---

## Conclusion

**The discrepancy is NOT a bug in C9 filtering.**

It's a **design difference** in C11 (volume filter):
- Production: `Vol > 1.3 × MA_50` (strict, quality-focused)
- Test: `Vol > 1.0 × MA_50` (loose, quantity-focused)

**Fix:** Update Test C11 to use `VOL_SPIKE_THRESHOLD = 1.3` to match Production.

This will reduce Test trades by ~30-40% and bring it in line with Production's quality standards.
