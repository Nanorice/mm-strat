# Dataset B - Early 2020 Signal Gap Explanation

## Issue

When building Dataset B starting from 2020-01-01, no trading signals are generated for the first ~300 days (approximately until November 2020).

## Root Cause

This is **NOT a data quality issue** - it's a **technical indicator warm-up period requirement**.

### Why This Happens

1. **SMA_200 Requirement**: The SEPA strategy uses SMA_200 (200-day Simple Moving Average) to confirm trends
2. **Minimum Data**: You need at least 200 trading days of historical price data to calculate SMA_200
3. **Buffer for Other Indicators**: Additional indicators (RS, volume metrics) need 50-100 days
4. **Total Warm-up**: ~250 trading days needed

### Timeline Calculation

```
Start Date: 2020-01-01
+ 250 trading days ≈ 300-310 calendar days
= First Viable Signals: ~2020-11-15
```

## Evidence from Code

### 1. Feature Calculation (src/features.py, line 81)
```python
if len(df) < 200:
    logger.warning(f"Insufficient data ({len(df)} rows). Need 200+ for accurate indicators.")
```

### 2. Trade Simulator (src/trade_simulator.py, line 209-212)
```python
valid_ticker_data = {
    t: df for t, df in ticker_data.items() 
    if df is not None and len(df) >= 200  # Filters out insufficient data
}
```

### 3. Strategy Requirements
- SMA_50, SMA_150, SMA_200: Need 200 days minimum
- RS (Relative Strength): ~50-100 days
- Volume metrics: ~50 days
- Breakout detection: ~20 days

## Solutions

### Option 1: Accept Limited Training Data (Easiest)
**What**: Start training from November 2020
**Pros**: No code changes needed
**Cons**: Less training data (Nov 2020 - Nov 2025 instead of Jan 2020 - Nov 2025)

```bash
# Build Dataset B from viable date
python build_dataset_b.py --start 2020-11-01 --end 2025-11-28
```

### Option 2: Extend Historical Data (Recommended)
**What**: Load price data starting from 2019 or earlier
**Pros**: Full training period from early 2020
**Cons**: Need to download more historical data

```bash
# Step 1: Download earlier price data
python initialise_price_data.py  # Make sure it pulls from 2019-01-01

# Step 2: Build datasets (signals will start appearing from ~Oct 2020)
python build_dataset_a.py --start 2019-01-01 --end 2025-11-28 --include-fundamentals
python build_dataset_b.py --start 2020-01-01 --end 2025-11-28
```

### Option 3: Reduce Warm-up Requirements (Not Recommended)
**What**: Modify strategy to use shorter moving averages
**Pros**: Earlier signals
**Cons**: Changes the strategy fundamentals, less reliable indicators

```python
# In config.py, change:
SMA_SLOW = 100  # Instead of 200
```

## Verification

To verify this is working as expected, you can check:

1. **Check when first trades appear**:
```bash
python -c "import pandas as pd; df = pd.read_parquet('data/ml/dataset_b.parquet'); print(f'First trade: {df.entry_date.min()}')"
```

Expected: Around 2020-10-15 to 2020-11-30

2. **Run diagnostic** (if venv activated):
```bash
python diagnose_early_signals.py
```

## Impact on Training

### Current Situation (2020-01-01 start)
- Training data: ~Nov 2020 - Nov 2025 = ~5 years
- Trading days: ~1,250 days
- Expected trades: 500-1,000 (depending on strategy selectivity)

### With Extended Data (2019-01-01 price data start)
- Training data: ~Oct 2020 - Nov 2025 = ~5 years  
- Same number of trades, but indicators are more reliable

## Recommendation

**Use Option 2** (Extend Historical Data):

1. Ensure price data starts from 2019-01-01 or earlier
2. Build Dataset A from 2019-01-01 (for warm-up)
3. Build Dataset B from 2020-01-01 (first valid signals ~Nov 2020)
4. Training dataset will have ~5 years of reliable data

## Additional Notes

- The 300-day gap is **normal and expected**
- This affects all technical analysis strategies that use long-term indicators
- The alternative (using insufficient data) would produce **unreliable signals**
- COVID crash (Feb-Mar 2020) makes this period less suitable for SEPA signals anyway

## Quick Check Command

```bash
# See when your price data starts for a sample ticker
python -c "from src.data_engine import DataRepository; r = DataRepository(); df = r.get_price_data('AAPL'); print(f'Data starts: {df.index.min()}')"
```

If this shows 2020-01-01, that's your issue - extend it back to at least 2019-01-01.
