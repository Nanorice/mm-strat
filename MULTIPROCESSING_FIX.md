# Multiprocessing Pickle Error Fix

## Problem
When running `build_dataset_b.py` with the `--n-jobs` flag (parallel processing), the following error occurred:
```
ERROR:__main__:Simulation failed: cannot pickle '_thread.lock' object
```

## Root Cause
The `_simulate_trades_parallel()` method was trying to pickle the entire `FastTradeSimulator` instance (via `self._simulate_ticker_trades`) to send to worker processes. The instance contained objects with thread locks that cannot be pickled:
- `DataRepository` (likely has threading locks in cache)
- `SEPAStrategy` (contains benchmark_data with locks)
- `FeatureEngineer` (may have locks)

## Solution
Refactored the parallel processing to use standalone module-level functions instead of instance methods:

1. **Created `_simulate_ticker_trades_standalone()`**: A module-level function that takes only the necessary picklable arguments (ticker, signals, ticker_df, config, outcome_end)

2. **Created `_find_exit_vectorized_standalone()`**: A module-level function for exit detection that relies on the precomputed `SEPA_Status` column instead of the strategy object

3. **Removed strategy dependency**: The standalone functions no longer need the strategy object (which is unpicklable). Instead, they rely on the `SEPA_Status` column that was already computed during signal detection

## Changes Made

### File: `src/trade_simulator_fast.py`

**Added standalone functions at module level:**
- `_simulate_ticker_trades_standalone()`: Picklable version of trade simulation
- `_find_exit_vectorized_standalone()`: Picklable version of exit detection

**Modified `_simulate_trades_parallel()`:**
- Changed to pass only picklable arguments to worker processes
- Removed strategy object from arguments
- Now calls `_simulate_ticker_trades_standalone` instead of `self._simulate_ticker_trades`

## Testing
Run the build script with parallel processing:
```bash
python build_dataset_b.py --start 2020-01-01 --end 2023-12-31 --n-jobs -1
```

## Notes
- The fix maintains identical behavior to the sequential version
- The `SEPA_Status` column must be precomputed during signal detection (already implemented)
- If `SEPA_Status` column is missing, the parallel mode will raise an error (cannot fall back to strategy)
- Sequential mode (`--n-jobs 1`) still works with the original instance methods
