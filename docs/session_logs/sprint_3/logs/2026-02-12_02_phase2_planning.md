# Session Handover: 2026-02-12 - Phase 2 Planning

## 🎯 Goal
Design Phase 2 architecture for DuckDB-integrated data curator and scanner to enable direct database writes/reads, bypassing parquet files, with preparation for Prefect orchestration.

## ✅ Accomplished
- **Fixed Validation Script Issues** - Resolved KeyError: 'ticker' in validation script by adding schema normalization (handle Date in index, capitalized columns, dtype mismatches)
- **Validated Phase 1 Migration** - All validation tests pass (20/20 price data, 10/10 company profiles, 20/20 daily features, SEPA view filters validated)
- **Created Follow-up Documentation** - Comprehensive analysis addressing validation fixes, data curator DuckDB integration status, and daily sync walkthrough
- **Analyzed Current Architecture** - Deep dive into data_curator.py (759 lines) and daily_scanner.py (817 lines) to understand data flow, bottlenecks, and integration points
- **Designed Phase 2 Architecture** - Non-contaminating design with isolated new modules, no flags in existing code, clean cutover strategy
- **Clarified Design Principles** - Established validation strategy: parallel file structure (data_curator_duckdb.py, daily_scanner_duckdb.py) instead of mode flags

## 📝 Files Changed
- `scripts/validate_migration.py`: Fixed KeyError by adding schema normalization (Date in index → column, lowercase columns, handle newer rows in files)
- `docs/session_logs/2026-02-11_handover_session2.md`: NEW - Previous session handover note
- `docs/session_logs/2026-02-11_handover_followup.md`: NEW - Comprehensive follow-up analysis (validation fixes, curator status, daily sync explanation)
- `C:\Users\Hang\.claude\plans\serene-doodling-planet.md`: NEW - Complete Phase 2 implementation plan (16 pages, detailed architecture)

## 🚧 Work in Progress (CRITICAL)
**None** - This session was planning/analysis only. No implementation started.

**Key Decisions Made**:
1. **No Contamination**: Do NOT add dual-mode flags or if/else branches to existing code
2. **Parallel Files**: Create `data_curator_duckdb.py` and `daily_scanner_duckdb.py` alongside existing files
3. **Validation Strategy**: Run both systems in parallel, compare outputs, then cutover via file swap
4. **Preserve Existing Logic**: Keep earnings calendar intelligence, API retry logic, rate limiting in existing engines
5. **Dual-Mode Flag Location**: ONLY inside new `DuckDBDataCurator` class (controls whether it writes to parquet for compatibility)

## ⏭️ Next Steps

### Immediate Actions (Session Start):
1. **Create `data_curator_duckdb.py`** (Est: 600-800 lines)
   - Class: `DuckDBDataCurator`
   - Methods:
     - `update_prices_to_db()` - Sync price data to DuckDB after DataRepository writes parquet
     - `compute_daily_features_incremental()` - Recompute features using window functions
     - `update_fundamentals_to_db()` - Sync quarterly data (preserves earnings calendar logic)
     - `update_company_profiles_to_db()` - Full upsert of profiles
     - `update_macro_data_to_db()` - Sync FRED + VIX data
     - `run_daily_sync()` - Main orchestrator
   - Reuses existing engines: `DataRepository`, `FundamentalEngine`, `CompanyProfileEngine`, `MacroEngine`
   - Internal `dual_mode` flag: True = write parquet + DuckDB, False = DuckDB only

2. **Create `src/database_duckdb.py`** (Est: 300-400 lines)
   - Class: `DuckDBManager` (mirrors `DatabaseManager` API)
   - Methods: `get_buy_list()`, `add_to_buy_list()`, `update_buy_list_metrics()`, `remove_from_buy_list()`
   - Drop-in replacement for SQLite buy_list operations

3. **Create `src/data_loader_duckdb.py`** (Est: 200-300 lines)
   - Class: `DuckDBDataLoader`
   - Methods:
     - `get_universe_tickers()` - Query tickers with recent data
     - `get_sepa_candidates()` - Load from v_sepa_candidates view
     - `get_price_data_batch()` - Batch load (replaces ThreadPool)
     - `get_fundamentals_batch()` - Vectorized as-of join
     - `get_macro_data()` - Load for M03 regime

4. **Create `daily_scanner_duckdb.py`** (Est: copy + modify 100 lines)
   - Copy `daily_scanner.py` → `daily_scanner_duckdb.py`
   - Replace: `DataRepository.get_batch_data()` → `DuckDBDataLoader.get_price_data_batch()`
   - Replace: `FundamentalMerger` loop → `DuckDBDataLoader.get_fundamentals_batch()`
   - Replace: `DatabaseManager` → `DuckDBManager`
   - Keep all other logic identical (features, ML, SEPA, M03 regime)

5. **Create `tools/compare_outputs.py`** (Est: 150-200 lines)
   - Run both scanners (old + new)
   - Compare buy_list outputs (tickers, ML scores)
   - Report differences
   - Performance benchmarks

### Validation Period (Week 3-4):
6. **Run Dual Systems in Parallel**:
   ```bash
   python data_curator.py --update-all          # Old (parquet)
   python data_curator_duckdb.py --sync-all     # New (parquet + DuckDB)
   python tools/compare_outputs.py              # Validation
   ```

7. **Validation Checks**:
   - Row counts match (price_data, fundamentals)
   - Buy list signals match (ticker lists identical)
   - ML scores match (within 1% tolerance)
   - Performance: New system 2-3x faster

### Cutover (Week 5):
8. **File Swap**:
   ```bash
   mv data_curator.py data_curator_legacy.py
   mv data_curator_duckdb.py data_curator.py
   mv daily_scanner.py daily_scanner_legacy.py
   mv daily_scanner_duckdb.py daily_scanner.py
   ```

### Future (Week 6+):
9. **Prefect Integration** - Create `flows/daily_data_pipeline.py`
10. **Migrate buy_list** - Run `scripts/migrate_sqlite_to_duckdb.py` (consolidate to single DB)
11. **Disable Dual-Mode** - Set `dual_mode=False` (DuckDB only, no parquet writes)

## 💡 Context/Memory

### Key Architectural Insights:

**Current Bottlenecks** (from exploration):
1. **Price Data Load**: 5-30s to read 500+ parquet files via ThreadPool
2. **Fundamental Merge**: Loop through candidates (10-100ms each) for as-of join
3. **Universe Build**: Nightly reload of 859 MB → rebuild segment files
4. **Data Duplication**: Files + DuckDB (Phase 1) → 2x storage

**Expected Performance Improvements**:
| Operation | Current (File) | Target (DuckDB) | Speedup |
|-----------|----------------|-----------------|---------|
| Load 500 tickers | 5-30s (ThreadPool) | <1s (single query) | 5-30x |
| Fundamental merge | 5-50s (loop) | <1s (vectorized) | 5-50x |
| Total scan time | 30-60s | 10-20s | 2-3x |

**Critical Design Decisions**:

1. **No Contamination Strategy**:
   - ✅ Create parallel files (`_duckdb.py` suffix)
   - ✅ Use wrapper classes (DuckDBManager, DuckDBDataLoader)
   - ❌ Do NOT add if/else branches to existing code
   - ❌ Do NOT add flags to existing function signatures

2. **Why Preserve Existing Engines**:
   - FMP API rate limiting (300 calls/min) - proven logic
   - Earnings calendar intelligence - reduces API calls by 90-95%
   - Retry logic with exponential backoff
   - Market hours safety checks
   - **Conclusion**: Keep engines, just add DB sync layer

3. **Dual-Mode Flag Scope**:
   - ONLY in `DuckDBDataCurator.__init__(dual_mode=True)`
   - NOT in any existing code
   - Purpose: Controls whether new curator writes to parquet (for compatibility) or skips it
   - Validation period: `dual_mode=True` (write both)
   - Production: `dual_mode=False` (DuckDB only)

4. **Validation Strategy**:
   - Run both systems in parallel for 2 weeks minimum
   - Compare outputs daily (buy_list tickers, ML scores)
   - Keep parquet files as backup during transition
   - Rollback plan: Just restore old files (no code changes needed)

5. **Buy List Migration**:
   - Currently: `database/trades.db` (SQLite)
   - Target: `market_data.duckdb::buy_list` table
   - One-time migration: `scripts/migrate_sqlite_to_duckdb.py`
   - Benefit: Single database source (simplifies operations)

**Questions Answered This Session**:

1. **Earnings Calendar Handling**: Preserved in `FundamentalEngine` - no duplication needed. New curator just syncs after engine updates.

2. **Writing to Parquet First**: Yes, only during validation period. Controlled by `dual_mode` flag in NEW curator only.

3. **Mode Flags in Scanner**: Decided AGAINST flags. Creating separate `daily_scanner_duckdb.py` file instead (cleaner, safer).

4. **Validation Strategy**: Focus on non-contamination. Parallel files, side-by-side testing, clean cutover via file swap.

**Implementation Plan Location**:
- Full plan: `C:\Users\Hang\.claude\plans\serene-doodling-planet.md`
- Includes: Architecture diagrams, SQL examples, code snippets, migration milestones, risk mitigation

**Phase 1 Status**:
- ✅ DuckDB schema created (6 tables + 2 views)
- ✅ Migration script working (`scripts/migrate_to_duckdb.py`)
- ✅ Validation harness fixed (`scripts/validate_migration.py`)
- ✅ Database populated: 9.78M price rows, 175K fundamentals, 2.5K profiles
- ✅ Daily features computed via window functions (2M rows/sec)
- ✅ SEPA candidates view working (436 current candidates)

**Data Flow Today**:
```
API (FMP, FRED)
    ↓
DataRepository.update_cache()
    ↓
data/price/{ticker}.parquet (859 MB, 500+ files)
    ↓
Daily Scanner
    ├─ Load: get_batch_data() (5-30s ThreadPool)
    ├─ Features: FeatureEngineer (lightweight + heavyweight)
    ├─ Merge: FundamentalMerger (loop per candidate)
    ├─ Score: ProductionScorer (M01+M02)
    └─ Store: DatabaseManager → trades.db (SQLite)
```

**Data Flow Target (Phase 2)**:
```
API (FMP, FRED)
    ↓
DataRepository.update_cache() [validation only]
    ↓
DuckDBDataCurator.sync_to_db()
    ↓
market_data.duckdb (single source)
    ↓
Daily Scanner DuckDB
    ├─ Load: DuckDBDataLoader (<1s single query)
    ├─ Features: Use pre-computed daily_features table
    ├─ Merge: Vectorized as-of join
    ├─ Score: ProductionScorer (M01+M02)
    └─ Store: DuckDBManager → buy_list table
```

**File Structure After Implementation**:
```
quantamental/
├── data_curator.py               # UNTOUCHED - current prod
├── data_curator_duckdb.py        # NEW - DuckDB version
├── daily_scanner.py              # UNTOUCHED - current prod
├── daily_scanner_duckdb.py       # NEW - DuckDB version
├── scripts/
│   ├── migrate_to_duckdb.py      # EXISTING - Phase 1 migration
│   ├── validate_migration.py     # MODIFIED - Fixed KeyError
│   └── migrate_sqlite_to_duckdb.py  # NEW - Buy list migration
├── src/
│   ├── database.py               # UNTOUCHED - SQLite
│   ├── database_duckdb.py        # NEW - DuckDB adapter
│   └── data_loader_duckdb.py     # NEW - Batch loader
├── tools/
│   └── compare_outputs.py        # NEW - Validation
└── flows/
    └── daily_data_pipeline.py    # NEW - Prefect (future)
```

**Success Criteria**:
1. ✅ Correctness: Dual-mode validation passes for 5+ consecutive days
2. ✅ Performance: Scanner runtime reduced by 50%+
3. ✅ Reliability: Zero data loss during validation period
4. ✅ Maintainability: Code complexity reduced (fewer I/O operations)
5. ✅ Prefect-Ready: Daily pipeline runs successfully for 1 week

**Estimated Timeline**:
- Week 1-2: Create new modules (data_curator_duckdb, scanner_duckdb, adapters)
- Week 3-4: Validation period (run both systems, compare outputs)
- Week 5: Cutover (file swap, monitor stability)
- Week 6+: Prefect integration, buy_list migration, disable dual-mode

**Risk Mitigation**:
- Data Loss: Dual-mode writes + daily validation checks + parquet backup
- Performance Regression: Benchmark before/after + rollback to `--mode file`
- Schema Mismatches: Reuse migration script logic + validation harness
- Concurrent Writes: Single writer pattern + read-only scanner connections
