# Summary: yfinance Download Issue Investigation

## Problem
Dataset B still starts from 2010-01-04 despite removing date filters

## Root Causes Found

### 1. yfinance API Behavior ✅ FIXED
**Issue**: yfinance ignores `start` parameter and returns only ~5 years by default
**Fix**: Changed from `start='2000-01-01'` to `period='max'` in both methods:
- `_get_ticker_data_yfinance()` (line 422)
- `_update_cache_yfinance()` (line 606)

### 2. Cache Validation Gap ✅ FIXED
**Issue**: `_is_cache_stale()` only checked file age, not date range coverage
**Fix**: Enhanced validation to check if cache date range covers required `min_date`
- Updated `_is_cache_stale()` to accept and validate `min_date` parameter
- Updated `get_ticker_data()` and `update_cache()` to pass `min_date`

### 3. Trade Simulator Missing Parameter ✅ FIXED
**Issue**: `FastTradeSimulator.run_simulation()` calls `update_cache()` but doesn't pass `min_date`
**Fix**: Updated line 54-57 to pass `min_date=self.start_date`

## Next Steps

1. **Clear cache completely**:
   ```powershell
   Remove-Item data\price\*.parquet -Force -ErrorAction SilentlyContinue
   ```

2. **Rebuild Dataset B** (will now download full history):
   ```bash
   python build_dataset_b.py --start 2003-01-01 --end 2025-11-28
   ```

3. **Verify date range**:
   ```bash
   python verify_dataset_b.py
   ```
   Should show: "Date range: 2003-01-XX to 2025-11-28"

## Comparison: initialise_price_data.py vs build_dataset_b.py

| Script | Method Path | Issue |
|--------|------------|-------|
| initialise_price_data.py | → update_cache() → _update_cache_yfinance() | ✅ Uses batch download with period='max' |
| build_dataset_b.py | → FastTradeSimulator → update_cache() | ❌ Was not passing min_date |
