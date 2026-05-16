# Implementation Plan - DuckDB Data Curator Optimization

## Goal
Optimize [data_curator_duckdb.py](file:///c:/Users/Hang/PycharmProjects/quantamental/data_curator_duckdb.py) to remove I/O bottlenecks by:
1.  Checking fundamental update status using DuckDB SQL (vs reading 5000+ parquet files).
2.  Vectorizing fundamental feature computation using DuckDB SQL (vs iterating 5000+ tickers in Python).

## User Review Required
> [!IMPORTANT]
> This change requires the [earnings](file:///c:/Users/Hang/PycharmProjects/quantamental/src/earnings_engine.py#353-390) data to be available in DuckDB. Currently, it appears only [fundamentals](file:///c:/Users/Hang/PycharmProjects/quantamental/data_curator_duckdb.py#457-519) and [prices](file:///c:/Users/Hang/PycharmProjects/quantamental/data_curator_duckdb.py#368-434) are being written. I will add [earnings](file:///c:/Users/Hang/PycharmProjects/quantamental/src/earnings_engine.py#353-390) ingestion to the pipeline.

## Proposed Changes

### 1. Schema & Data Ingestion ([data_curator_duckdb.py](file:///c:/Users/Hang/PycharmProjects/quantamental/data_curator_duckdb.py))
- **[NEW]** Add `_fetch_earnings` and `_write_earnings_to_duckdb` methods.
- **[MODIFY]** Update [run_update](file:///c:/Users/Hang/PycharmProjects/quantamental/data_curator_duckdb.py#199-326) to include earnings in the fetch/write cycle.
- **[MODIFY]** Ensure [earnings](file:///c:/Users/Hang/PycharmProjects/quantamental/src/earnings_engine.py#353-390) table exists in [database_duckdb.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/database_duckdb.py) or create it on the fly (DuckDB is flexible, but explicit schema is better).

### 2. Optimized Staleness Check ([EarningsEngine](file:///c:/Users/Hang/PycharmProjects/quantamental/src/earnings_engine.py#28-751))
- **[MODIFY]** [src/earnings_engine.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/earnings_engine.py): Add `get_tickers_needing_update_sql(con)` method.
    - Logic: `SELECT ticker FROM earnings e JOIN (SELECT ticker, MAX(report_date) as max_fund FROM fundamentals GROUP BY ticker) f ON e.ticker = f.ticker WHERE e.date > f.max_fund`
- **[MODIFY]** [data_curator_duckdb.py](file:///c:/Users/Hang/PycharmProjects/quantamental/data_curator_duckdb.py): Switch to this SQL method when `dual_mode=False` (or always, if we trust DuckDB).

### 3. Vectorized Feature Computation ([FundamentalProcessor](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_processor.py#22-632))
- **[NEW]** create `src/sql/fundamental_features.sql` (or embedded string) with the vectorized logic.
    - Replicates `FundamentalProcessor.py` logic using `LAG()`, `Avg() OVER()`, etc.
    - Handles:
        - YoY Growth (Revenue, Net Income, EPS) - `LAG(x, 4)`
        - Acceleration (Growth - Lagged Growth) - `growth - LAG(growth, 1)`
        - Margins (Gross, Operating, Net)
        - Ratios (PE, PS, PB using latest price) - *Note: P/E usually requires join with price, but FundamentalProcessor calculates "intrinsic" ratios involving price? No, [FundamentalProcessor](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_processor.py#22-632) calculates `debt_to_equity`, `current_ratio`. The `view_manager` calculates PE/PS/PB. I will stick to the processor's scope.*
- **[MODIFY]** [data_curator_duckdb.py](file:///c:/Users/Hang/PycharmProjects/quantamental/data_curator_duckdb.py): Replace [_compute_fundamental_features](file:///c:/Users/Hang/PycharmProjects/quantamental/data_curator_duckdb.py#786-949) python loop with `con.execute(INSERT INTO fundamental_features SELECT ... FROM vectorized_query)`.

## Verification Plan

### Automated Tests
- **Parity Check**:
    1.  Run the old Python [FundamentalProcessor](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_processor.py#22-632) on a sample ticker (e.g., NVDA).
    2.  Run the new SQL logic on the same ticker.
    3.  Compare the resulting DataFrame for exact matches (floating point tolerance).

### Manual Verification
- **Performance Benchmark**:
    - Measure time to check updates (expected: <1s vs ~20s).
    - Measure time to compute features (expected: <2s vs ~60s).
- **Data Integrity**:
    - Inspect [earnings](file:///c:/Users/Hang/PycharmProjects/quantamental/src/earnings_engine.py#353-390) table in DuckDB to ensure it's populated.
    - Inspect [fundamental_features](file:///c:/Users/Hang/PycharmProjects/quantamental/data_curator_duckdb.py#786-949) table to ensure no nulls/gaps introduced.
