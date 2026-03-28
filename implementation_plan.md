# Refactor Feature Engineering: Python-Based Alphas

We will transition the alpha factor computation from a complex SQL CTE in `data_curator_duckdb.py` to a robust Python-based `AlphaCalculator` integrated into the existing `FeatureEngineer`. This resolves parity issues, fixes logic errors (slope inversion), and improves maintainability.

## User Review Required
> [!IMPORTANT]
> This refactor will **replace** the current SQL logic for alpha generation. Users should expect `daily_features` table to be fully updated. The `WorldQuant_101.py` file will be deprecated.

## Proposed Changes

### 1. Alpha Logic Encapsulation
#### [NEW] [src/alpha_definitions.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/alpha_definitions.py)
- Create `AlphaCalculator` class.
- Implement corrected alpha logic (fixing VWAP scale and Slope calculation direction).
- Input: Standard DataFrame (Open, High, Low, Close, Volume).
- Output: DataFrame with alpha columns.

### 2. Feature Engine Integration
#### [MODIFY] [src/alpha_factors.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/alpha_factors.py)
- Update `AlphaEngine` to use `AlphaCalculator` instead of `WorldQuant_101.py`.
- Remove legacy `S_DQ_` column mapping wrapping.

### 3. Data Curator Refactor
#### [MODIFY] [data_curator_duckdb.py](file:///c:/Users/Hang/PycharmProjects/quantamental/data_curator_duckdb.py)
- Remove the large `alpha_final` CTE from `_compute_features_incremental`.
- Implement new `_compute_features_python` method:
    1.  **Fetch**: Load `price_data` + `SPY` benchmark from DuckDB into Pandas.
    2.  **Compute**: Call `FeatureEngineer.calculate_lightweight_features`.
    3.  **Write**: Bulk insert/update `daily_features` table in DuckDB.
- Update CLI args (`--update-features`) to trigger this Python path.

## Verification Plan

### Automated Tests
- **Unit Tests**: Create `tests/test_alpha_calculator.py` to verify individual alpha values against known good inputs.
- **Integration Test**: Run `data_curator_duckdb.py --update-features` on a small sample (e.g., 5 tickers).
- **Parity Check**: Run `scripts/validate_alpha_parity_v2.py` (updated to check new implementation vs historical/expected) to ensure correlations are now > 0.99.

### Manual Verification
- Inspect `daily_features` table for `alpha046/049/051` to confirm they properly identify deceleration (positive values when slope decreases).
