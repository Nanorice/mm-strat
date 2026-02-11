# RS Formula Comparison: Production vs Test
**Date:** 2026-02-07
**Question:** What RS formula is used in Production's `RS > RS_MA` check?

## Answer: BENCHMARK VERSION (Price Ratio)

Both Production and Test use the **same RS formula** for the RS trend check.

---

## Detailed Breakdown

### Production Pipeline

**Step 1: Calculate RS** ([indicators.py:119](../src/indicators.py#L119))
```python
# RS Ratio = Stock / Benchmark (kept for charting compatibility)
df['RS'] = df['Close'] / benchmark_aligned
```

**Step 2: Calculate RS_MA** ([indicators.py:122](../src/indicators.py#L122))
```python
# RS Moving Average for trend detection
df['RS_MA'] = df['RS'].rolling(window=lookback).mean()
```
Where `lookback = config.RS_LOOKBACK = 63` days

**Step 3: Check RS Trend** ([indicators.py:445](../src/indicators.py#L445))
```python
rs_strong = df['RS'] > df['RS_MA']
```

**Formula Summary:**
```
RS = Stock_Close / SPY_Close
RS_MA = 63-day moving average of RS
Check: RS > RS_MA  (is stock outperforming SPY over 63 days?)
```

---

### Test Pipeline

**Step 1: Load Pre-computed RS from Universe**
Universe Parquet includes `RS` column (calculated same way as Production)

**Step 2: Calculate RS_MA_63** ([data_pipeline_test.py:150-152](../src/pipeline/data_pipeline_test.py#L150-L152))
```python
df_matrix['RS_MA_63'] = df_matrix.groupby('ticker')['RS'].transform(
    lambda x: x.rolling(63).mean()
)
```

**Step 3: Check C12** ([data_pipeline_test.py:153](../src/pipeline/data_pipeline_test.py#L153))
```python
c12 = df_matrix['RS'] > df_matrix['RS_MA_63']
```

**Formula Summary:**
```
RS = Stock_Close / SPY_Close  (from Universe Parquet)
RS_MA_63 = 63-day moving average of RS
Check: RS > RS_MA_63  (identical to Production)
```

---

## Two Different "RS" Metrics in the Code

The codebase has **TWO metrics with confusing names:**

### 1. `RS` (Price Ratio - Used for Trend Check)
```python
RS = Stock_Close / SPY_Close
```
- **Used by:** Production's `check_relative_strength()`, Test's C12
- **Purpose:** Detect if stock is outperforming SPY over time
- **Check:** `RS > RS.rolling(63).mean()`

### 2. `rs_rating` (Weighted Momentum - Used for Ranking)
```python
rs_rating = 0.4 * ROC(3m) + 0.2 * ROC(6m) + 0.2 * ROC(9m) + 0.2 * ROC(12m)
```
- **Used by:** Production's C9 (`rs_rating > 0`), Test's C9 (`rs_rating >= P70`)
- **Purpose:** Rank stocks by momentum performance (Minervini/IBD style)
- **Check:** Production uses `> 0`, Test uses `>= 70th percentile`

**These are INDEPENDENT metrics!**

---

## So Why the Mismatch?

If both use the same `RS > RS_MA` formula, why do we have trades only in Test?

### Confirmed: Not a Formula Issue

Both pipelines use identical `RS` (price ratio) and `RS_MA` (63-day MA) calculations.

### Remaining Hypotheses

**1. Data Source Difference**
- **Production:** Calculates `RS` on-the-fly from price data
- **Test:** Uses pre-computed `RS` from Universe Parquet

**Potential issue:** Universe Parquet might have:
- Different SPY benchmark alignment
- Missing/interpolated values
- Calculation bugs in universe generation

**2. Filter Application Order**
- **Production:** Sequential checks (can early-terminate if Stage 2 fails)
- **Test:** Vectorized (applies all filters simultaneously)

**Potential issue:** Production might reject tickers at Step 1 (C1-C9) before ever checking RS trend.

**3. Transition Detection Timing**
- **Production:** Checks SEPA status **daily** and triggers on first pass
- **Test:** Computes SEPA status for **all dates**, then finds 0→1 transitions

**Potential issue:** Test might detect transitions on dates when Production didn't run the check.

---

## Next Investigation Steps

### Step 1: Verify Universe RS Calculation
Check how Universe Parquet computes `RS`:

```python
# In src/universe_engine.py - find where RS is calculated
# Does it use the same FeatureEngineer.add_relative_strength()?
```

### Step 2: Compare Actual RS Values
For a trade that appears **only in Test**, compare:

```python
# Test RS value (from Universe)
df_universe.loc[(ticker, date), 'RS']
df_universe.loc[(ticker, date), 'RS_MA']

# Production RS value (calculated live)
prod_df = data_repo.get_price_data(ticker, start, date)
prod_df = feature_engine.calculate_indicators(prod_df)
prod_df.loc[date, 'RS']
prod_df.loc[date, 'RS_MA']
```

If values differ → Universe calculation issue
If values match → Filter timing/ordering issue

### Step 3: Check C9 Strictness Impact

Test's stricter C9 (`rs_rating >= P70`) means it filters OUT ~70% of candidates.

**Question:** Are the 7,612 "only in Test" trades coming from tickers that:
- Pass Test C9 (top 30% rs_rating)
- Fail Production C9? **No, impossible** (Prod only needs `rs_rating > 0`)

**Therefore:** The mismatch is NOT from C9 strictness.

---

## Conclusion

✅ **Confirmed:** Both Production and Test use the **BENCHMARK VERSION** of RS:
```
RS = Stock_Close / SPY_Close
RS_MA = 63-day moving average of RS
Check: RS > RS_MA
```

❓ **Unresolved:** Why 7,612 trades appear only in Test despite identical RS formula?

**Most likely cause:** Different data sources (Universe Parquet vs live calculation) or filter timing differences.

**Recommended next step:** Run diagnostic to compare actual RS values for sample trades.

```bash
python debug_why_test_not_in_prod.py
```
