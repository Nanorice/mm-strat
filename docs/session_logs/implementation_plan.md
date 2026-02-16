# Implementation Plan - Optimize Alpha Calculation Performance

The user requested utilizing DuckDB for alpha calculations ("can we utilise duckDB?"). Native DuckDB execution avoids Python round-trips entirely, offering massive speedups and simplifying the architecture.

## Problem Analysis
- **Current Approach**: Iterative Python read-calc-write loop (slow, memory-inefficient).
- **Proposed Approach**: **Native SQL Alphas**.
  - Most WorldQuant 101 alphas rely on rolling windows (`SUM`, `AVG`, `STDDEV`, `CORR`, `MIN`, `MAX`), which are native DuckDB window functions.
  - Complex functions like [ts_rank](file:///c:/Users/Hang/PycharmProjects/quantamental/WorldQuant_101.py#63-71) (rolling rank) and [ts_argmax](file:///c:/Users/Hang/PycharmProjects/quantamental/WorldQuant_101.py#143-151) can be implemented using DuckDB's advanced list functions (`list`, `list_sort`, `list_grade`, `list_extract`).
  - Cross-sectional ranks are trivial with `PERCENT_RANK() OVER (PARTITION BY date)`.

## Feasibility of Key Functions
- **Rolling Correlation**: `CORR(x, y) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN N PRECEDING AND CURRENT ROW)`. Native.
- **Rolling Rank ([ts_rank](file:///c:/Users/Hang/PycharmProjects/quantamental/WorldQuant_101.py#63-71))**: 
  - Challenge: Standard SQL lacks `ROLLING_RANK`.
  - Solution: Use `list()` window function + list lambda.
  - `list_grade(list_sort(window_list), current_val) / len(window_list)`
- **Rolling ArgMax ([ts_argmax](file:///c:/Users/Hang/PycharmProjects/quantamental/WorldQuant_101.py#143-151))**:
  - Challenge: Index of max value in window.
  - Solution: `arg_max(struct_pack(val, index))` over window? Or list sort.
  - Simpler: `position(max_val in window_list)`.

## Proposed Changes

### [data_curator_duckdb.py](file:///c:/Users/Hang/PycharmProjects/quantamental/data_curator_duckdb.py)

1.  **Remove [_compute_python_features](file:///c:/Users/Hang/PycharmProjects/quantamental/data_curator_duckdb.py#1495-1662) Loop**:
    - Delete the batch iteration and Python-side [AlphaEngine](file:///c:/Users/Hang/PycharmProjects/quantamental/src/alpha_factors.py#25-265) usage.

2.  **Implement `_compute_alphas_sql`**:
    - Build a massive SQL query (or series of CTEs/UPDATEs) to compute alphas directly in DuckDB.
    - **Step 1: Rank Base Features**: Compute cross-sectional ranks of raw inputs (Open, High, Low, Close, Vol) first, as many alphas rank these.
    - **Step 2: Core Alphas**: Implement standard window function alphas (A6, A9, A12, A41, A101...).
    - **Step 3: Complex Alphas**: Implement [ts_rank](file:///c:/Users/Hang/PycharmProjects/quantamental/WorldQuant_101.py#63-71)-dependent alphas using list functions or approximations.

3.  **Refactor [AlphaEngine](file:///c:/Users/Hang/PycharmProjects/quantamental/src/alpha_factors.py#25-265) (Optional)**:
    - If we move to SQL, [src/alpha_factors.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/alpha_factors.py) becomes legacy/validation only.
    - We might want to keep it for parity checks but the production path should be SQL.

## Detailed SQL Implementation Strategy

### Alpha 1 (Legacy): [rank(ts_argmax(signed_power(..., 2), 5))](file:///c:/Users/Hang/PycharmProjects/quantamental/WorldQuant_101.py#125-133)
- [ts_argmax(x, 5)](file:///c:/Users/Hang/PycharmProjects/quantamental/WorldQuant_101.py#143-151): Index of max value in last 5 days.
- SQL: `list_position(window_list, MAX(x) OVER w)`? No, position in *unsorted* list.
- DuckDB: `list_indexof(list(x) OVER w, MAX(x) OVER w)`.

### Alpha 4 (Priority): [ts_rank(rank(low), 9)](file:///c:/Users/Hang/PycharmProjects/quantamental/WorldQuant_101.py#63-71)
- [rank(low)](file:///c:/Users/Hang/PycharmProjects/quantamental/WorldQuant_101.py#125-133): Cross-sectional rank (already easy).
- [ts_rank(x, 9)](file:///c:/Users/Hang/PycharmProjects/quantamental/WorldQuant_101.py#63-71): Rank of current `x` in last 9 values.
- SQL: 
  ```sql
  (list_count(list_filter(list(x) OVER w, y -> y < x)) + 1) / 9.0
  ```
  (Count values smaller than x in window). This is exactly [ts_rank](file:///c:/Users/Hang/PycharmProjects/quantamental/WorldQuant_101.py#63-71).

## Verification Plan

1.  **Verify DuckDB Functions**: Create a test script `test_duckdb_alphas.py` to prove [ts_rank](file:///c:/Users/Hang/PycharmProjects/quantamental/WorldQuant_101.py#63-71) implementation matches Python.
2.  **Implement SQL**: Port the 13-16 selected alphas to SQL.
3.  **Compare**: 
    - Compute alphas via Python (old way) -> `alpha001_py`.
    - Compute via SQL -> `alpha001_sql`.
    - Compare correlation or exact match.

## User Action
- Confirm if we should **replace** the Python implementation with this SQL-native approach.
