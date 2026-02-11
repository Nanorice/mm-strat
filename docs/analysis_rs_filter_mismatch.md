# RS Filter Mismatch - Why Test ⊄ Production
**Date:** 2026-02-07
**Critical Finding:** Production uses **different RS metric** than Test for relative strength check

## The Paradox

```
Expected: Test ⊆ Production (Test has stricter C9: rs_rating >= P70)
Actual:   Test has 7,612 trades NOT in Production (63% of Test!)
```

This should be **mathematically impossible** if both pipelines use the same filters, since:
- Test C9: `rs_rating >= P70` (top 30%)
- Prod C9: `rs_rating > 0` (any positive)

**Every ticker passing Test's C9 MUST pass Production's C9.**

---

## Root Cause: Two Different "RS" Metrics

### 1. Production's 3-Step Filter

Production applies **THREE** independent checks:

**Step 1:** `screen_candidates()` → C1-C9 with `rs_rating > 0`
**Step 2:** `check_trigger()` → VCP breakout + volume
**Step 3:** `check_relative_strength()` → **`RS > RS_MA`** ← **THIS IS THE CULPRIT**

From [strategy.py:268](../src/strategy.py#L268):
```python
rs_ok = self.check_relative_strength(df, date)
buy_signal = trend_ok and trigger_ok and rs_ok  # All 3 must pass!
```

### 2. What is `RS` vs `rs_rating`?

**Two DIFFERENT metrics with similar names:**

#### `RS` (Price Ratio)
From [indicators.py:119-122](../src/indicators.py#L119-L122):
```python
df['RS'] = df['Close'] / benchmark_aligned  # Stock price / SPY price
df['RS_MA'] = df['RS'].rolling(window=63).mean()
```

**Production's RS check:** `RS > RS_MA` (stock outperforming SPY over 63 days)

#### `rs_rating` (Weighted Momentum)
From [indicators.py:127-132](../src/indicators.py#L127-L132):
```python
# Minervini/IBD-Style RS Rating (weighted momentum)
df['rs_rating'] = (
    0.4 * df['Close'].pct_change(63) +   # 3-month ROC
    0.2 * df['Close'].pct_change(126) +  # 6-month ROC
    0.2 * df['Close'].pct_change(189) +  # 9-month ROC
    0.2 * df['Close'].pct_change(252)    # 12-month ROC
)
```

**Test's C9 check:** `rs_rating >= P70` (top 30% weighted momentum)

---

## Why This Causes the Mismatch

### Test Pipeline
Uses `rs_rating` (weighted momentum) for **both**:
- C9 filter: `rs_rating >= P70`
- C12 filter: `RS > RS.rolling(63).mean()`

Test's C12 uses **raw `RS` price ratio**, same as Production!

### Production Pipeline
Uses **different metrics** for different checks:
- C9 filter: `rs_rating > 0` (weighted momentum)
- RS check: `RS > RS_MA` (price ratio vs SPY)

**Critical difference:** Production's `RS > RS_MA` is **INDEPENDENT** of `rs_rating`.

---

## Concrete Example

**Scenario:** Stock with strong absolute momentum but weak relative strength vs SPY

```
Stock: NVDA on 2024-02-15
  Close: $150 → $180 (+20% in 3 months)
  SPY: $450 → $470 (+4.4% in 3 months)

rs_rating = 0.4 * 0.20 + ... = 0.15  (strong, likely top 30%)
  → Passes Test C9: rs_rating >= P70 ✓

RS = 150/450 = 0.333
RS_MA (63d avg) = 0.320
RS > RS_MA? → 0.333 > 0.320 = True
  → Passes Production RS check ✓
```

**Opposite scenario:** Stock underperforming SPY recently

```
Stock: XYZ on 2024-02-15
  Close: $50 → $51 (+2% in 3 months)
  SPY: $450 → $470 (+4.4% in 3 months)

rs_rating = 0.4 * 0.02 + ... = 0.05  (could still be top 30% if others worse!)
  → Passes Test C9: rs_rating >= P70 ✓ (if ranked high vs peers)

RS = 51/470 = 0.1085
RS_MA (63d avg) = 0.1100
RS > RS_MA? → 0.1085 > 0.1100 = FALSE ✗
  → FAILS Production RS check ✗
```

**This stock appears in Test but NOT in Production!**

---

## Verification

### Test Pipeline Check
From [data_pipeline_test.py:148-153](../src/pipeline/data_pipeline_test.py#L148-L153):
```python
# C12: RS > RS 63-day MA (momentum confirmation)
if 'RS' in df_matrix.columns:
    df_matrix['RS_MA_63'] = df_matrix.groupby('ticker')['RS'].transform(
        lambda x: x.rolling(63).mean()
    )
    c12 = df_matrix['RS'] > df_matrix['RS_MA_63']
```

**Wait!** Test's C12 also uses `RS > RS_MA_63` (same as Production's RS check).

But there's a timing difference:
- **Test:** Applies C12 **once at entry** (vectorized)
- **Production:** Applies `check_relative_strength()` at **entry time** in simulator

---

## The Real Issue: Date Range or Calculation Difference

If both use `RS > RS_MA`, why the mismatch?

### Hypothesis 1: Universe Coverage
Test uses **pre-computed universe parquet** which might have:
- More complete data coverage (no missing dates)
- Different `RS` calculation methodology
- SPY benchmark alignment differences

### Hypothesis 2: Sequential vs Vectorized
Production applies filters **sequentially** on each date:
```python
# Production flow per ticker per date:
if not screen_candidates(df, date):
    return False  # Early termination
if not check_trigger(df, date):
    return False
if not check_relative_strength(df, date):
    return False
return True  # All passed
```

Test applies filters **vectorized** across entire date range:
```python
# Test flow (vectorized):
c1_to_c9 = (c1 & c2 & ... & c9)  # All dates at once
c10_to_c12 = (c10 & c11 & c12)   # All dates at once
signals = find_transitions(c1_to_c9 & c10_to_c12)  # Detect 0→1
```

**This could cause differences if:**
- RS_MA calculation differs due to data availability
- Transition detection logic differs from daily sequential checks

---

## Next Steps to Debug

### Step 1: Compare RS Values for Sample Trade
For a trade that appears **only in Test**, check:
```python
# Load universe data for that ticker/date
# Compare:
test_rs = df_universe.loc[(ticker, date), 'RS']
test_rs_ma = df_universe.loc[(ticker, date), 'RS_MA']

# vs Production calculation
prod_df = data_repo.get_price_data(ticker, start, date)
prod_df = feature_engine.calculate_indicators(prod_df)
prod_rs = prod_df.loc[date, 'RS']
prod_rs_ma = prod_df.loc[date, 'RS_MA']

# Check if values match
```

### Step 2: Check Universe RS Calculation
Verify how Universe Parquet computes `RS` and `RS_MA`:
```bash
# Find universe generation code
grep -n "def.*universe" src/*.py
grep -n "RS_MA" src/universe_engine.py
```

### Step 3: Run Diagnostic
```bash
python debug_why_test_not_in_prod.py
```

This will identify:
1. Which tickers are completely missing from Production
2. Which tickers appear in both but different dates
3. Sample RS value comparisons

---

## Recommendations

### Option A: Make Test Match Production Exactly
**Change Test to use Production's 3-step logic:**
1. C1-C9 with `rs_rating > 0` (instead of >= P70)
2. C10-C12 breakout
3. **Add separate RS check:** `RS > RS_MA`

This ensures Test is truly a "faster Production" with identical logic.

### Option B: Simplify Production to Match Test
**Remove Production's separate RS check:**
- C9 already includes `rs_rating > 0`
- C12 already checks `RS > RS_MA_63`
- The separate `check_relative_strength()` is redundant

**Risk:** This changes historical backtest results for M01/M02.

### Option C: Keep Both, Document Differences
Acknowledge they are **different strategies**:
- **Production:** 3-step with separate RS validation (conservative, fewer signals)
- **Test:** Vectorized C1-C12 (aggressive, more signals, top 30% RS ranking)

Use Test for experimentation, Production for live trading.

---

## Immediate Action

**Run the diagnostic script to confirm hypothesis:**
```bash
python debug_why_test_not_in_prod.py
```

Then decide whether to:
1. Align Test to Production (make rs_rating > 0 in Test C9)
2. Investigate RS calculation differences in Universe Parquet
3. Accept they are different strategies and use accordingly
