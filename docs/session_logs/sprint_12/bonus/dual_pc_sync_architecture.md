# Dual-PC Architecture & Weekly Parquet Delta Sync Pipeline

This document outlines the architecture for splitting workloads between the ITX (Spare PC) and Taro (Main PC), and details the mechanism for safely synchronizing DuckDB data incrementally using the existing pipeline metadata logs.

## 1. The Dual-PC Dynamics

To maximize hardware efficiency and minimize interruptions on the main compute rig, the workload is split as follows:

### The Operations Hub: ITX (Spare PC / 4060)
* **Role:** "Always-On" Operations & Data Engineering Server.
* **Workloads:** 
    * Executes the daily `daily_pipeline_orchestrator.py` to ingest new market and fundamental data into the local `market_data.duckdb`.
    * Hosts the Hermes agent for background repository maintenance, docstring generation, and log analysis.
* **Benefit:** Frees up the main machine from daily cron jobs, API fetching limits, and lightweight background tasks.

### The Compute Hub: Taro (Main PC / 4090)
* **Role:** Heavy Lifting & Active Development.
* **Workloads:** 
    * Training deep learning/regression models, heavy hyperparameter tuning, backtesting over large time horizons.
* **Benefit:** Maximum VRAM and compute are dedicated entirely to analytical performance rather than daily I/O.

---

## 2. The DuckDB Syncing Problem

**The Challenge:** DuckDB is an in-process database. Attempting to synchronize the raw `market_data.duckdb` and its Write-Ahead Log (`.wal`) between two actively used machines using standard file-sync tools (Syncthing, Dropbox) carries a high risk of database corruption if a sync occurs during an active read/write transaction.

**The Solution:** We will sync *the data* instead of the database file. By exporting the incremental daily updates (deltas) into immutable Parquet files on a weekly basis, we ensure safe, high-speed, and corruption-free data transfer.

---

## 3. Implementation Plan: Weekly Parquet Delta Sync

Instead of building a redundant logging mechanism, we will leverage the existing pipeline state tracker inside `src/managers/pipeline_run_manager.py` (which already logs execution times, phase success/failure, and target dates into the `pipeline_runs` table).

### Component A: `sync_state` Tracking
We will create a lightweight state tracker (e.g., a simple `data/sync/sync_state.json` file or a 1-row table) to track the `last_synced_target_date`. This decouples the weekly sync extraction logic from the core daily orchestrator logic.

### Component B: The Weekly Extractor (ITX side)
A new script: `scripts/sync_export_weekly.py`
- **Execution:** Run manually or via cron (e.g., every Sunday evening) on the ITX.
- **Logic:**
  1. Reads the `last_synced_target_date` from the `sync_state`.
  2. Queries the local ITX `pipeline_runs` table to find the maximum successfully completed `target_date`.
  3. Extracts all data from relevant tables (e.g., `price_data`, `t2_screener_features`, `t3_sepa_features`) where the date falls between `last_synced_target_date` and the new max date.
  4. Writes this data into partitioned Parquet files: `data/sync/updates/wk_{date}_price_data.parquet`.
  5. Updates the `sync_state` with the new maximum date.
  6. **Metadata Sync:** Exports the corresponding rows from `pipeline_runs`, `table_write_log`, and `pipeline_error_log` into Parquet files so the Taro machine inherits the health history.

### Component C: The Delta Ingestor (Taro side)
A new script: `scripts/sync_ingest_deltas.py`
- **Execution:** Run manually on Taro before a heavy training session or backtest.
- **Logic:**
  1. Scans the shared `data/sync/updates/` directory (which is synced over the LAN via Syncthing/SMB) for new Parquet files.
  2. Ingests the data safely into Taro's local `market_data.duckdb` using `INSERT INTO ... SELECT * FROM read_parquet(...)`.
  3. Appends the metadata logs so Taro's health dashboard remains identical to the ITX.
  4. Moves the processed Parquet files into `data/sync/archive/` to prevent duplicate ingestion.

---

## 4. Why This Architecture Works
- **Zero Corruption Risk:** Parquet files are written once and never modified, making them completely safe for network syncing.
- **Network Efficiency:** We only transfer highly compressed deltas (a few megabytes) instead of syncing a multi-gigabyte `.duckdb` file.
- **Seamless Health Tracking:** By exporting the `pipeline_runs` table alongside the data, the Taro machine maintains full visibility into any pipeline failures or data quality warnings that occurred on the ITX over the week.
