# DuckDB Transition Gap Analysis

This document identifies the gaps between the current file-based architecture and the target DuckDB-based system.

## 1. Data Ingestion & Curation


| Feature | Current (`data_curator.py`) | Target (`data_curator_duckdb.py`) | Gap Status |
| :--- | :--- | :--- | :--- |
| **Price Updates** | Fetch -> Parquet (Legacy) | Fetch -> Parquet (via Legacy Engine) + Buffer -> DuckDB | **Complete** (Phase 1) - `--dual-mode` flag creates explicitly identical parity. |
| **Fundamentals** | Fetch -> Parquet (Legacy) | Fetch -> Parquet (via Legacy Engine) + Buffer -> DuckDB | **Complete** |
| **Universe Mgmt** | `update_universe` | Handled via `DataAcquisitionQueue` | **Review**: Ensure universe synchronization logic is equivalent. |
| **Macro Data** | Fetch -> Parquet | Fetch -> DuckDB | **Complete** |
| **Validation** | Basic Checks | SQL types & Constraints | **In Progress**: `migrate_to_duckdb.py` shows constraints, but runtime validation in curator needs verification. |


**Action Items:**
- [ ] Fully retire `data_curator.py` once `data_curator_duckdb.py` is validated.
- [ ] Verify `DataAcquisitionQueue` logic correctly prioritizes updates compared to the current sequential/batch approach.

## 2. Feature Engineering (The Major Gap)

Currently, features are calculated in Python (Pandas) during the pipeline build or daily scan. The goal is to move this to SQL.

| Component | Current (Python) | Target (SQL in `daily_features`) | Gap Analysis |
| :--- | :--- | :--- | :--- |
| **Trend Templates** | `SEPAStrategy` (Pandas) | `v_sepa_candidates` (View) | **Partial**: View exists in migration script but needs to match Python logic exactly (e.g., moving average logic, 52w high logic). |
| **Relative Strength** | `rs_rating` (Percentile) | SQL Window Functions | **Critical Gap**: `rs_rating` is a cross-sectional rank (1-99). SQL `PERCENT_RANK()` can do this, but needs efficient daily computation. Current SQL feature only has `price_vs_spy`. |
| **M01 Features** | `FeatureEngineer` (Complex) | `daily_features` Table | **Critical Gap**: M01 uses specific transforms (log-returns, interactions). These need to be ported to SQL or calculated cheaply on-the-fly after SQL load. |
| **M02 Features** | `FeatureEngineer` | `daily_features` Table | **Critical Gap**: Evaluation needed to see if M02 specific features are in SQL. |
| **Volatility** | VCP/ATR (Pandas) | `atr_14`, `volatility_20d` | **Partial**: Basic volatility is in SQL. Advanced VCP pattern detection might need to stay in Python or be complex SQL. |

**Action Items:**
- [ ] **Feature Parity Audit**: List every input feature for M01/M02 and verify its SQL equivalent.
- [ ] **RS Rating Implementation**: Implement efficient cross-sectional ranking in DuckDB (likely a `dbt` model or scheduled SQL job).
- [ ] **Migration of Logic**: Port `FeatureEngineer.py` logic to SQL `CREATE MACRO` or persisted tables.

## 3. Data Pipeline (`model_runner.py`)

| Step | Current Flow | Target Flow | Gap |
| :--- | :--- | :--- | :--- |
| **Scan (D1)** | Read Parquet -> Filter (Python) | `SELECT * FROM v_sepa_candidates` | **High**: Need to replace `D1_Scan` class with a DB connector. |
| **Features (D2)** | Read Parquet -> Calc Features | `SELECT * FROM daily_features` | **High**: `DataPipeline` class needs a "DB Mode" to pull features directly. |
| **Hydrate (D2R)** | Read Price -> Attach Next/Prev Returns | SQL Window Functions (Lead/Lag) | **Medium**: Can be done in SQL easily, but pipelines need to be updated to query it. |

**Action Items:**
- [ ] Refactor `DataPipeline` to support a `source="duckdb"` argument.
- [ ] Create SQL queries that replicate the `D2` and `D2R` construction (joining features with future returns).

## 4. Daily Operations (`daily_scanner.py`)

| Function | Current | Target | Gap |
| :--- | :--- | :--- | :--- |
| **Data Loading** | Loads ALL price history for universe | Query last N rows from DB | **Solved** by DuckDB (huge perf boost). |
| **Processing** | Multi-threaded Python calc | SQL View/Table | **Gap**: Script needs rewriting to remove `FeatureEngineer` dependency. |
| **Scoring** | `ProductionScorer` (Python) | `ProductionScorer` (Python) | **Low**: Scorer takes a DataFrame. Just need to feed it result from DuckDB query instead of constructed CSV. |

**Action Items:**
- [ ] Rewrite `daily_scanner.py` to:
    1.  Connect to DuckDB.
    2.  Execute `SELECT * FROM v_daily_inference_set`.
    3.  Pass result to `ProductionScorer`.
    4.  Write results to SQLite (or back to DuckDB `buy_list` table).

## Summary of Critical Path
1.  **Feature Parity**: Ensure SQL `daily_features` contains ALL columns required by the M01/M02 models.
2.  **Pipeline Refactor**: Update `src/pipeline` to read from DuckDB instead of Filesystem.
3.  **Scanner Rewrite**: Strip down `daily_scanner.py` to be a lightweight SQL-querying wrapper.
