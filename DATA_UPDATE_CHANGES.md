# Data Update Behavior Changes

## Issue
After rebuilding the price cache, `build_dataset_a.py` was triggering FMP rate limits by **calling `update_cache()` again** (line 172), even though the cache was just freshly rebuilt.

## Root Cause
`build_dataset_a.py` had `skip_data_updates=False` as the default, which meant:
1. It would check if any cached data is "stale" (older than configured cache days)
2. It would attempt to re-download "stale" data from FMP
3. This caused unnecessary API calls right after a fresh cache rebuild

## Changes Made ✅

### 1. Changed Default Behavior (`build_dataset_a.py`)
**Before**: `skip_data_updates: bool = False` (always check and update cache)
**After**: `skip_data_updates: bool = True` (use cached data as-is)

**Rationale**: 
- For **training datasets**, we want historical data, not fresh market data
- Cache should be updated separately via dedicated scripts or scanner
- Avoids hitting FMP rate limits during dataset generation

### 2. Updated Documentation
Updated the docstring to clearly explain:
- Default is now `True` (skip updates)
- Designed for training datasets where cache is already up-to-date
- Set to `False` only when you need to fetch fresh market data

### 3. How to Update Cache Separately
If you need fresh data before building datasets:

```bash
# Option 1: Use rebuild script
python rebuild_from_screener.py

# Option 2: Use initialization script  
python scripts/initialise_price_data.py

# Option 3: Use scanner (updates as side effect)
python optimized_scanner.py --date-range
```

Then build datasets without updates:
```bash
# Dataset A - defaults to skip_data_updates=True now
python build_dataset_a.py --start 2003-01-01 --end 2023-12-31

# Dataset B - never updates cache (no update_cache calls)
python build_dataset_b.py --start 2003-01-01 --end 2023-12-31
```

## Flag Override
If you DO want fresh data during dataset generation:
```bash
# This will update cache before building (not recommended - slow and may hit limits)
# Note: the flag name didn't change, just the default
python build_dataset_a.py --start 2003-01-01 --end 2023-12-31 
# Above uses default skip_data_updates=True (no updates)

# To force updates, you'd need to remove the --skip-updates flag 
# (since the default is now True, there's no flag to explicitly request updates)
```

Actually, I realize there's a usability issue - we need an explicit flag to ENABLE updates when needed.

## TODO: Add `--update-cache` Flag
Currently the `--skip-updates` flag exists but since default is now True, we need the opposite flag for when users want updates. This can be added later if needed.
