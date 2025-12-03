# Tools Directory

**Debugging, testing, and diagnostic utilities**

This folder contains one-off scripts for checking data quality, debugging issues, and validating system behavior. These are not part of regular workflows.

---

## Data Inspection Tools

### `inspect_dataset_b.py`
**Purpose**: Analyze Dataset B (trade labels) quality and statistics

```bash
# Inspect Dataset B
python tools/inspect_dataset_b.py data/ml/dataset_b_2023_2024.parquet
```

**Output**:
- Label distribution (win rate)
- Return statistics
- Trade duration analysis
- Missing value report

**When to use**: After generating Dataset B, before training

---

### `inspect_merged.py`
**Purpose**: Validate merged dataset quality

```bash
# Inspect merged training dataset
python tools/inspect_merged.py data/ml/training_dataset_final.parquet
```

**Output**:
- Feature completeness
- Label balance
- Merge quality (match rate)
- Temporal consistency check

**When to use**: After merging datasets, before training

---

## Data Validation Tools

### `validate_features.py`
**Purpose**: Check feature engineering correctness

```bash
# Validate features for specific ticker
python tools/validate_features.py AAPL

# Validate all features
python tools/validate_features.py --all
```

**Output**: Feature value ranges, NaN counts, inf detection

**When to use**: Debugging feature calculation issues

---

### `verify_dataset_a.py`
**Purpose**: Quick check if Dataset A exists and is valid

```bash
python tools/verify_dataset_a.py
```

**Output**: File size, row count, date range

**When to use**: After building Dataset A

---

### `verify_dataset_b.py`
**Purpose**: Quick check if Dataset B exists and is valid

```bash
python tools/verify_dataset_b.py
```

**Output**: File size, trade count, label distribution

**When to use**: After building Dataset B

---

### `verify_features.py`
**Purpose**: Verify specific features are calculated correctly

```bash
# Verify features for ticker and date
python tools/verify_features.py AAPL 2024-11-15
```

**Output**: Feature values with expected ranges

**When to use**: Debugging specific feature issues

---

## Cache Inspection Tools

### `check_all_dates.py`
**Purpose**: Check date coverage across all cached price data

```bash
python tools/check_all_dates.py
```

**Output**: Min/max dates for each ticker, gaps detection

**When to use**: Debugging data staleness issues

---

### `check_cache_dates.py`
**Purpose**: Check cache freshness

```bash
python tools/check_cache_dates.py
```

**Output**: Last modified date for each cached file

**When to use**: Determining if cache needs refresh

---

### `check_dates.py`
**Purpose**: Check date alignment between price and fundamental data

```bash
python tools/check_dates.py AAPL
```

**Output**: Date overlap report

**When to use**: Debugging merge issues

---

### `check_recent_cache.py`
**Purpose**: List recently updated cache files

```bash
python tools/check_recent_cache.py
```

**Output**: Files updated in last 24 hours

**When to use**: Verifying cache updates

---

## Debugging Tools

### `debug_missing_columns.py`
**Purpose**: Diagnose missing feature columns in datasets

```bash
# Debug missing columns in Dataset A
python tools/debug_missing_columns.py data/ml/dataset_a.parquet
```

**Output**:
- Expected vs actual columns
- Missing column names
- Schema comparison

**When to use**: Model training fails due to missing features

---

## Testing Tools

### `test_fast_simulator.py`
**Purpose**: Test fast trade simulator performance

```bash
python tools/test_fast_simulator.py
```

**Output**: Speed benchmark, correctness validation

**When to use**: Validating simulator changes

---

### `test_yfinance_fix.py`
**Purpose**: Test yfinance API connectivity and data quality

```bash
python tools/test_yfinance_fix.py
```

**Output**: API response, data sample

**When to use**: Debugging yfinance download issues

---

## Usage Guidelines

### When to Use These Tools

**Use these tools when**:
- Something doesn't work as expected
- You need to understand data quality issues
- Debugging feature calculation problems
- Validating changes to core modules

**Don't use these for**:
- Regular daily operations (use `scripts/` instead)
- Production workflows
- Automated processes

---

### Tool Categories

| Category | Tools |
|----------|-------|
| **Dataset Inspection** | `inspect_dataset_b.py`, `inspect_merged.py` |
| **Data Validation** | `validate_features.py`, `verify_*.py` |
| **Cache Debugging** | `check_*_dates.py`, `check_recent_cache.py` |
| **Column Debugging** | `debug_missing_columns.py` |
| **Testing** | `test_*.py` |

---

### Tool Development

If you create new debugging/testing scripts:

1. **Place in `tools/`** - Keep root directory clean
2. **Use descriptive names** - `check_`, `verify_`, `debug_`, `test_`, `inspect_`
3. **Add to this README** - Document purpose and usage
4. **Make them standalone** - Should run without complex setup
5. **Print helpful output** - Clear diagnostic messages

---

## Common Debugging Workflows

### Dataset Build Issues

```bash
# 1. Check if price cache is stale
python tools/check_cache_dates.py

# 2. Verify Dataset B quality
python tools/verify_dataset_b.py

# 3. Inspect Dataset B in detail
python tools/inspect_dataset_b.py data/ml/dataset_b.parquet

# 4. Verify Dataset A
python tools/verify_dataset_a.py

# 5. Check merged dataset
python tools/inspect_merged.py data/ml/training_dataset_final.parquet
```

---

### Feature Calculation Issues

```bash
# 1. Validate features for specific ticker
python tools/validate_features.py AAPL

# 2. Verify specific feature values
python tools/verify_features.py AAPL 2024-11-15

# 3. Debug missing columns
python tools/debug_missing_columns.py data/ml/dataset_a.parquet
```

---

### Cache Issues

```bash
# 1. Check all cache dates
python tools/check_all_dates.py

# 2. Check recent updates
python tools/check_recent_cache.py

# 3. Check specific ticker cache freshness
python tools/check_cache_dates.py
```

---

## Dependencies

These tools depend on:
- `src/` modules (data_engine, features, etc.)
- `config.py`
- Various dataset files in `data/`

Most tools can run independently with minimal setup.
