# Data Type Fix - Dataset A Build

## Problem

When running Dataset A build (both in Jupyter notebook and command-line), you encountered this error:

```
❌ Error building Dataset A: 'values' is not ordered, please explicitly specify the categories order by passing in a categories argument.
Traceback (most recent call last):
  File "/Users/ceolwaerc/Desktop/Projects/mm-strat/.venv/lib/python3.12/site-packages/numpy/_core/fromnumeric.py", line 57, in _wrapfunc
    return bound(*args, **kwds)
           ^^^^^^^^^^^^^^^^^^^^
TypeError: '<' not supported between instances of 'Timestamp' and 'int'
```

## Root Cause

The error occurred during the concatenation and sorting phase when:

1. The 'date' column was created from the DataFrame index without explicit type conversion
2. When concatenating multiple DataFrames, pandas couldn't sort mixed types (Timestamp vs int)
3. The categorical column handling code didn't address the 'date' column type issue

## Solution

Added explicit data type conversions in three places:

### Fix 1: Parallel Processing Worker Function (line 99, 106)

```python
# Before
df_features['date'] = df_features.index

# After
df_features['date'] = pd.to_datetime(df_features.index)

# Ensure date column is datetime type
if 'date' in df_features.columns:
    df_features['date'] = pd.to_datetime(df_features['date'])
```

### Fix 2: Sequential Processing Loop (line 248, 254)

Same fix applied to the sequential processing path for consistency.

### Fix 3: Pre-Sort Type Enforcement (line 334-335)

Added explicit type conversion right before sorting:

```python
# CRITICAL: Ensure proper data types before sorting to avoid comparison errors
dataset_a['ticker'] = dataset_a['ticker'].astype(str)
dataset_a['date'] = pd.to_datetime(dataset_a['date'])

# Then sort
dataset_a = dataset_a.sort_values(['ticker', 'date']).reset_index(drop=True)
```

## Why This Happened

1. **Index to column conversion:** When doing `df['date'] = df.index`, pandas doesn't guarantee the column gets the same dtype as the index
2. **Mixed sources:** Different tickers might have slightly different index types depending on how they were loaded
3. **Categorical handling:** The existing categorical-to-string conversion (lines 311-320) didn't catch this because 'date' wasn't categorical

## Impact

This fix applies to:
- ✅ Jupyter notebook (Cell 6 / Cell 15)
- ✅ Command-line `build_dataset_a.py` script
- ✅ Both sequential (`n_jobs=1`) and parallel (`n_jobs>1`) modes

## Testing

Try running Cell 6 again in the Jupyter notebook:

1. Should complete without the TypeError
2. Progress bar should update smoothly (thanks to the earlier fix)
3. Dataset should be built successfully

If you still see issues, check:
- Pandas version (`pd.__version__`)
- Whether any custom data sources have unusual date formats
- Log output for any warnings about data type conversions
