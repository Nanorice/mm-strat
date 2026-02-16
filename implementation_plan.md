# Implementation Plan - Add Feature Recompute Flags

To enable the backfilling of new RS Line features into DuckDB, we need to add explicit control over feature computation modes in `data_curator_duckdb.py`.

## Problem
The `daily_features` table now has new columns (`price_vs_spy`, etc.) that are NULL for existing rows.
The current `data_curator_duckdb.py` defaults to "incremental" update (last 252 days) whenever it sees existing data.
There is no CLI flags to force a full recomputation of the entire history, meaning older rows will remain NULL for the new features.

## Proposed Changes

### `data_curator_duckdb.py`

1.  **Update `argparse`**:
    *   Add `--recompute`: Force full feature calculation from 2020-01-01.
    *   Add `--incremental`: Force incremental update.
    *   Add `--update-features`: Allow running feature computation *without* requiring `--update-prices` (decoupling).

2.  **Update `DuckDBDataCurator.run_update`**:
    *   Accept new arguments.
    *   Allow skipping "fetch" phases if only `--update-features` is requested.

3.  **Update `_compute_features_incremental`**:
    *   Accept `force_full: bool = False`.
    *   If `force_full` is True, ignore `last_update` and use default start date (2020-01-01).

## Verification Plan

### Manual Verification
1.  Run `python data_curator_duckdb.py --update-features --recompute`
    *   Expect: Script runs "Full feature build (from 2020-01-01)..."
    *   Verify: SQL query shows non-null `price_vs_spy` in early 2020.

2.  Run `python data_curator_duckdb.py --update-features --incremental`
    *   Expect: Script runs "Incremental feature update..."
