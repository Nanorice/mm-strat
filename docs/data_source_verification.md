# Data Source Verification: Universe vs Production RS Calculation
**Date:** 2026-02-07

## Hypothesis 1: Different Data Sources

### Question
Does Universe Parquet calculate RS differently than Production?

---

## Answer: ✅ SAME CALCULATION METHOD

Both use the **identical function** from `TechnicalAnalysis.add_relative_strength()`.

---

## Evidence

### Universe Parquet Generation

**File:** [src/universe_engine.py:230-258](../src/universe_engine.py#L230-L258)

```python
# Initialize feature engine with benchmark
feature_engine = FeatureEngineer(benchmark_data=benchmark_data)

# Process each ticker
for ticker, df in batch_data.items():
    # Calculate features
    df = feature_engine.calculate_lightweight_features(df)
```

**Trace:** `calculate_lightweight_features()` → `add_relative_strength()`

From [src/features.py:108-110](../src/features.py#L108-L110):
```python
# Relative Strength vs. Benchmark
if self.benchmark_data is not None:
    df = self.ta.add_relative_strength(df, self.benchmark_data, lookback=config.RS_LOOKBACK)
```

---

### Production Pipeline

**File:** [src/strategy.py:64-74](../src/strategy.py#L64-L74)

```python
def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
    return self.ta.calculate_all_indicators(df, self.benchmark_data)
```

**Trace:** `calculate_all_indicators()` → `add_relative_strength()`

From [src/indicators.py:353-355](../src/indicators.py#L353-L355):
```python
# Add RS if benchmark provided
if benchmark is not None:
    df = TechnicalAnalysis.add_relative_strength(df, benchmark)
```

---

## Shared Implementation

**Both paths converge to:** [src/indicators.py:97-134](../src/indicators.py#L97-L134)

```python
def add_relative_strength(df: pd.DataFrame, benchmark: pd.Series, lookback: int = None) -> pd.DataFrame:
    if lookback is None:
        lookback = config.RS_LOOKBACK  # 63 days

    # Align benchmark to stock dates
    benchmark_aligned = benchmark.reindex(df.index).ffill()

    # RS Ratio = Stock / Benchmark
    df['RS'] = df['Close'] / benchmark_aligned

    # RS Moving Average
    df['RS_MA'] = df['RS'].rolling(window=lookback).mean()

    # rs_rating (weighted momentum)
    df['rs_rating'] = (
        0.4 * df['Close'].pct_change(63) +
        0.2 * df['Close'].pct_change(126) +
        0.2 * df['Close'].pct_change(189) +
        0.2 * df['Close'].pct_change(252)
    )

    return df
```

**Conclusion:** Universe and Production use **identical code** to calculate RS, RS_MA, and rs_rating.

---

## Hypothesis 2: Filter Ordering

### Question
You asked: "Why would order of filter matter if we need all criteria to be met?"

### Answer: You're RIGHT! Order SHOULDN'T matter.

If we need ALL criteria to pass:
```python
# These should be logically equivalent:
result1 = C1 & C2 & C3 & ... & C12  # Vectorized (Test)
result2 = (C1 and C2 and C3 and ... and C12)  # Sequential (Production)
```

**But there's a subtle issue:** Early termination doesn't change the logic, it just changes **when errors occur**.

---

## Production Sequential Flow

From [src/strategy.py:266-270](../src/strategy.py#L266-L270):

```python
trend_ok = self.screen_candidates(df, date)      # C1-C9
trigger_ok = self.check_trigger(df, date)        # VCP
rs_ok = self.check_relative_strength(df, date)   # RS > RS_MA

buy_signal = trend_ok and trigger_ok and rs_ok
```

**Key point:** If `trend_ok = False`, Production **doesn't even evaluate** `trigger_ok` or `rs_ok` (short-circuit AND).

**BUT:** This is just an optimization. The final result is the same as `trend_ok & trigger_ok & rs_ok`.

---

## So Why the Mismatch?

If both use identical RS calculation and filters, why 7,612 trades only in Test?

### Remaining Possibilities

#### 1. **Data Availability Mismatch**

**Potential issue:**
- Universe Parquet might have **missing tickers** that Production has
- Or vice versa: Test might have **extra tickers** that Production skips

**Example:**
```python
# Production might skip tickers with insufficient data
if len(df) < 260:  # Not enough history
    return False  # Skip this ticker

# Universe might include newer stocks with limited history
if len(df) < 50:  # Minimal threshold
    continue  # But still processes if >=50 days
```

From [src/universe_engine.py:254](../src/universe_engine.py#L254):
```python
if len(df) < 50:
    continue
```

From [src/indicators.py:390-393](../src/indicators.py#L390-L393):
```python
if len(df) < 260:
    # Simplified trend for IPOs/newer stocks
    c_trend = (df['Close'] > df['SMA_50']) & ...
```

**This could explain it!** Production uses a **simplified Stage 2 check** for stocks with <260 days of history, while Universe might compute full features.

#### 2. **Error Handling Differences**

**Production:**
```python
try:
    rs_strong = self.ta.detect_relative_strength(df)
    return rs_strong.loc[date]
except Exception:
    return False  # Fail silently
```

**Test:**
```python
if 'RS' in df_matrix.columns:
    c12 = df_matrix['RS'] > df_matrix['RS_MA_63']
else:
    c12 = pd.Series(True, index=df_matrix.index)  # Skip check!
```

**Critical difference:** If `RS` column is missing, Test **passes the check** (True), Production **fails the check** (False via exception).

#### 3. **Date Alignment in Benchmark**

Both use:
```python
benchmark_aligned = benchmark.reindex(df.index).ffill()
```

**Potential issue:** If SPY data has gaps, `ffill()` could cause slight differences in RS values depending on when the calculation runs.

---

## Next Investigation Steps

### Step 1: Check Ticker Coverage
```python
# Which tickers are in Test but not Prod?
test_tickers = set(d1_test['ticker'])
prod_tickers = set(d1_prod['ticker'])

only_test = test_tickers - prod_tickers
print(f"Tickers only in Test: {len(only_test)}")
```

Run:
```bash
python debug_why_test_not_in_prod.py
```

### Step 2: Check IPO/Recent Stocks
```python
# Are the "only Test" trades from newer stocks?
only_test_df = d1_test[d1_test['ticker'].isin(only_test)]
# Check if these tickers have <260 days of history
```

### Step 3: Check RS Column Existence
```python
# Load a sample ticker from Universe
df_universe_sample = universe[universe['ticker'] == sample_ticker]

# Does it have RS, RS_MA columns?
print(df_universe_sample[['RS', 'RS_MA']].head())
```

---

## Hypothesis: IPO Filter Difference

**Most likely explanation:**

Production's `detect_stage2_uptrend()` has special handling for stocks with <260 days:

```python
if len(df) < 260:
    # Simplified trend for IPOs/newer stocks
    c_trend = (df['Close'] > df['SMA_50']) & \
             (df['Close'] > df['Close'].rolling(20).mean())
else:
    # Full Stage 2 template (C1-C8)
    c1 = df['Close'] > df['SMA_150']
    # ... full checks ...
```

**Test pipeline** might compute full C1-C9 for ALL tickers (even IPOs with <260 days), while **Production** uses a simplified check.

**This would cause:**
- Test accepts IPO stocks that pass full C1-C9
- Production rejects or uses different criteria for IPOs

---

## Conclusion

✅ **Confirmed:** Universe and Production use **identical RS calculation** (`TechnicalAnalysis.add_relative_strength()`)

❓ **Unresolved:** Why the mismatch exists

**Most likely causes:**
1. **IPO handling:** Production uses simplified checks for stocks with <260 days of history
2. **Error handling:** Missing RS columns handled differently (Test skips check, Production fails)
3. **Ticker coverage:** Different universe scope

**Recommended:** Run diagnostic to check ticker coverage and history length for "only Test" trades.
