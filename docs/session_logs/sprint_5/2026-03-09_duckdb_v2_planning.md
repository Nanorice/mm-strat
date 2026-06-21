# Session Handover: 2026-03-09 - DuckDB V2 Architecture Planning

## 🎯 Goal
Create comprehensive documentation and implementation plan for DuckDB V2 infrastructure uplift, transitioning from full table rebuilds to a 3-tier lazy materialization architecture with append-only T3 features for SEPA breakout candidates.

## ✅ Accomplished

### Phase 1: Documentation & Architecture Alignment (COMPLETE)
- **Milestone 1.1**: Updated `technical_blueprint.md` with:
  - 6 new T1 table schemas (price, fundamentals, shares, macro, company profiles)
  - 2 T2 tables (screener features full-universe, regime scores)
  - 1 T3 table (SEPA features append-only with `feature_version` column)
  - 8 supporting tables documented (models, buy_list, registry, etc.)
  - Section 6: Historical Backfill Strategy (2020-01-01, 8hr runtime, checkpointing)
  - Section 7: Error Handling & Monitoring (fail-safe mode, 3 alert levels)
  - 12 acceptance criteria for validation

- **Milestone 1.2**: Created `reconciliation_plan.md` (580 lines):
  - Current → v2 table mapping for 14 tables
  - Daily features split strategy (T2 lightweight vs T3 heavy)
  - Component-by-component refactor plan (3 keep, 3 refactor, 9 create)
  - Risk assessment with mitigation strategies
  - Phase-by-phase validation queries
  - 6-step rollback procedure
  - Timeline: ~45-55 dev hours + 2-week parallel validation

- **Milestone 1.3**: Created `pipeline_dag.md` (650 lines):
  - Full dependency graph (Mermaid diagram, 20+ nodes)
  - 9-phase daily execution order with Python/SQL code snippets
  - Failure decision tree (HALT vs WARN vs CONTINUE)
  - Performance benchmarks (90-180s total expected runtime)
  - Monitoring queries (data freshness, pipeline history, breakout trends)
  - Idempotency guarantees and checkpoint recovery

### Phase 2: Schema Design & Migration Preparation (IN PROGRESS)
- **Milestone 2.1**: Created `schema_design.sql` (650 lines):
  - Complete DDL for all 11 T1/T2/T3 tables
  - Migration notes (rename vs extend vs create)
  - 102-column T3 schema with composite PK (ticker, date, feature_version)
  - Indexes for fast queries
  - Validation queries to verify correctness
  - Migration summary with step-by-step ALTER TABLE commands

- **Milestone 2.2**: Completed fundamental data audit:
  - Created `scripts/audit_fundamental_schema.py` (220 lines)
  - **CRITICAL FINDING**: All 5 ratio columns missing from fundamentals table
    - Missing: `pe_ratio`, `ps_ratio`, `pb_ratio`, `peg_ratio`, `market_cap`
  - Data quality: 387K rows, 2,557 tickers, date range 1970-2027
  - Staleness: 737 tickers (28.8%) haven't updated in 90+ days
  - NULL rates: revenue 2.3%, net_income 45.3%, total_assets/equity 48.2%

## 📝 Files Changed

### Created (Documentation)
- `docs/proposals/duckdb_v2/technical_blueprint.md`: 312 lines - Full architecture spec with T1/T2/T3 schemas, backfill strategy, error handling, monitoring
- `docs/proposals/duckdb_v2/reconciliation_plan.md`: 580 lines - Migration roadmap, current→v2 mapping, component refactor plan, validation strategy
- `docs/proposals/duckdb_v2/pipeline_dag.md`: 650 lines - Daily pipeline dependencies, failure modes, execution order, performance benchmarks
- `docs/proposals/duckdb_v2/schema_design.sql`: 650 lines - Complete DDL for all tables, migration scripts, validation queries

### Created (Scripts)
- `scripts/audit_fundamental_schema.py`: 220 lines - Schema audit tool, detects missing columns, checks data quality and staleness

### Modified
- `docs/proposals/duckdb_v2/architecture.md`: Updated table names to match reconciliation plan
- `docs/proposals/duckdb_v2/duckdb_v2_infra.md`: Aligned status indicators with reconciliation plan

## 🚧 Work in Progress (CRITICAL)

### Milestone 2.3: Validate v_d2r_hydrated Stop-Loss Logic (NOT STARTED)
**Status**: Pending
**Task**: Read current `src/view_manager.py` to review `v_d2r_hydrated` SQL logic, create test cases for:
- Gap-down below stop on entry day
- ATR-based stop triggers before % stop
- Stop hit on partial fill scenarios

### Missing Fundamental Columns (BLOCKING T3 BACKFILL)
**Issue**: `fundamentals` table lacks 5 required ratio columns for T3 features
**Impact**:
- T3 cannot populate `fundamental_pe`, `fundamental_ps`, `fundamental_pb` columns
- M01 model may need retraining if fundamentals were part of feature set

**Required Action Before Phase 3**:
```sql
-- Step 1: Add market_cap column (requires JOIN with price & shares)
ALTER TABLE fundamentals ADD COLUMN market_cap DOUBLE;
UPDATE fundamentals f
SET market_cap = (
    SELECT p.close * s.shares_outstanding
    FROM t1_price p
    JOIN t1_shares_outstanding s ON p.ticker = f.ticker AND p.date = f.report_date
    WHERE p.ticker = f.ticker AND p.date = f.report_date
);

-- Step 2: Add ratio columns
ALTER TABLE fundamentals ADD COLUMN pe_ratio DOUBLE;
ALTER TABLE fundamentals ADD COLUMN ps_ratio DOUBLE;
ALTER TABLE fundamentals ADD COLUMN pb_ratio DOUBLE;

-- Step 3: Compute ratios
UPDATE fundamentals
SET pe_ratio = market_cap / NULLIF(net_income, 0),
    ps_ratio = market_cap / NULLIF(revenue, 0),
    pb_ratio = market_cap / NULLIF(total_equity, 0);
```

### Unresolved Design Questions
1. **T2 Performance**: Will 60M+ row T2 table (8K tickers × full history) cause query slowdowns?
   - Mitigation: Add indexes, use `PRAGMA threads=8`, profile before cutover
2. **M03 Breadth Indicators**: Where to source `advance_decline_ratio`, `new_high_low_ratio`?
   - Current `macro_data` only has SPY/QQQ/VIX
   - May need additional API or computed metric from S&P 500 constituents

## ⏭️ Next Steps

### Immediate (Milestone 2.3)
1. **Validate Stop-Loss Logic**:
   - Read `src/view_manager.py` → `_create_v_d2r_hydrated()` method
   - Create 5 test cases (gap-down, ATR vs %, weekend handling, exit on stop day)
   - Document any edge cases or bugs in reconciliation plan

### Short-Term (Phase 3 - T1/T2 Refactor)
2. **Add Missing Fundamental Columns** (BLOCKING):
   - Run `ALTER TABLE` commands above
   - Validate market_cap computation for 10 random tickers vs yfinance
   - Update `schema_design.sql` to mark as DONE

3. **Milestone 3.1 - Create T1 Macro Table**:
   - Migrate existing `macro_data` (long format) to `t1_macro` (wide format)
   - Add VIX ingestion (currently missing)
   - Implement `scripts/ingest_t1_macro.py` for daily updates

4. **Milestone 3.2 - Migrate M03 Parquet → DuckDB**:
   - Create `src/regime_pipeline.py`
   - One-time migration: `data/regime_scores.parquet` → `t2_regime_scores`
   - Validate 10 random dates match exactly

5. **Milestone 3.3 - Refactor T2 Features**:
   - Split lightweight features from `daily_features` → `t2_screener_features`
   - Ensure full-universe scope (~8K tickers)
   - Benchmark: <30s compute time for 60M+ rows

### Medium-Term (Phase 4 - T3 Implementation)
6. **Milestone 4.1 - Backfill T3**:
   - Create `scripts/backfill_t3_sepa_features.py`
   - Run historical backfill: 2020-01-01 → present (~8 hours)
   - Target: ~500K rows, ~1500 unique tickers

7. **Milestone 4.2 - Refactor FeaturePipeline**:
   - Split `compute_all()` into `compute_t2()` + `compute_t3_for_candidates()`
   - Remove `CREATE OR REPLACE` pattern, use `INSERT OR IGNORE`

### Long-Term (Phase 8 - Cutover)
8. **2-Week Parallel Validation**:
   - Run v1 (current) and v2 (new) pipelines side-by-side
   - Compare SEPA candidate lists (<1% discrepancy target)
   - Compare feature values (sample 10 tickers/day, <5% variance)
   - Compare M01 scores (±0.01 tolerance)

9. **Rollback Preparation**:
   - Backup `daily_features` table
   - Test `scripts/rollback_to_v1.py` on staging DB
   - Document rollback triggers (when to abort migration)

## 💡 Context/Memory

### Key Architectural Decisions Made
1. **T2 Scope = Full Universe**: Chose to compute T2 features for all ~8K tickers (not just screener members) to capture emerging stocks and maintain historical consistency. DuckDB columnar compression can handle 60M+ rows efficiently.

2. **Feature Versioning is CRITICAL**: Added `feature_version` column to T3 as composite PK. Enables:
   - Reproducibility when feature logic changes (e.g., bug fix in alpha006)
   - Parallel datasets for old/new M01 models
   - Audit trail for debugging (which feature definition was used?)

3. **Append-Only T3 > Full Rebuild**: Current `daily_features` rebuilds 2.6M rows nightly (~180s). New T3 appends ~50 breakouts/day (~10s), saving ~90% compute time. Trade-off: more complex backfill logic.

4. **M03 Parquet → DuckDB**: Moving regime scores from file to table enables:
   - Single source of truth (no stale parquet files)
   - SQL joins in views (no Python merge required)
   - Transactional updates (no file locking issues)

5. **Fail-Safe Mode > Silent Failures**: If yfinance API fails, HALT pipeline rather than proceeding with stale data. Prevents downstream corruption in T2/T3. Alert admin immediately.

### "Aha!" Moments
- **Current `daily_features` has 111 columns** (79 SQL + 16 Python + 7 ranks + 4 M03 + 5 M03 derived). Confirmed split strategy:
  - T2 gets 30 lightweight columns (SMAs, ATR, RS, distances)
  - T3 gets 102 heavy columns (all 111 minus overlaps, plus fundamentals)

- **Fundamentals gap is BLOCKING**: Cannot populate T3 `fundamental_pe/ps/pb` without adding ratio columns first. This must be done in Phase 3 before T3 backfill.

- **Phase B (Python alphas) is bottleneck**: 166s for 2.6M rows due to `groupby().apply()` with `rolling().corr()`. When T3 only computes ~50 tickers/day, this drops to ~3s (acceptable). No optimization needed for v2.

- **View naming inconsistency resolved**: Original proposal had `v_t3_trades` (tier-based) vs `v_d1_trades` (depth-based). Chose depth-based (`v_dN_*`) to align with existing `v_d1_candidates` pattern.

### Technical Constraints Discovered
- **DuckDB volume column is UBIGINT**: Any subtraction must `CAST(volume AS BIGINT)` to avoid overflow. Document in MEMORY.md.
- **DuckDB named windows cannot reference each other**: Use multiple CTEs instead. Affects T2 feature computation (SMA slopes, lagged values).
- **Windows console doesn't support Unicode emojis**: Use ASCII markers `[OK]`, `[WARN]`, `[ERR]` instead of ✅❌⚠️ in scripts.

### Gotchas for Next Session
- **Existing `shares_outstanding` table is named `shares_history`**: Reconciliation plan says "rename if exists" - it DOES exist, use `ALTER TABLE shares_history RENAME TO t1_shares_outstanding`.
- **`macro_data` is in long format** (date, symbol, close, volume): Need to PIVOT to wide format for `t1_macro` (date, spy_close, spy_volume, qqq_close, vix_close).
- **M01 model may need retraining**: If fundamentals were part of M01 feature set and we're changing how P/E is computed (via market_cap JOIN), predictions may shift. Add to validation checklist.

### Questions for User (Next Session)
1. **M03 Breadth Indicators**: Where to source `advance_decline_ratio` and `new_high_low_ratio`? Options:
   - Compute from S&P 500 constituents (expensive, needs constituent list)
   - Use external API (Polygon, Alpaca, etc.)
   - Skip for MVP, add in Phase 7 (nice-to-have)

2. **Backfill Start Date**: Confirm 2020-01-01 is correct. Earlier data (2015+) exists but may have survivorship bias. Trade-off:
   - 2020-01-01: 5 years, ~500K rows, 8hr backfill
   - 2015-01-01: 10 years, ~1M rows, 16hr backfill

3. **Parallel Validation Duration**: 2 weeks OK? Can reduce to 1 week if high confidence in refactor.

## 📊 Metrics
- **Total Documentation Created**: ~2,400 lines across 5 files
- **Tables Designed**: 11 (4 T1, 2 T2, 1 T3, 4 supporting)
- **Views Documented**: 4 (v_d1_trades, v_d2_hydrated, v_d2_training, v_d3_deployment)
- **Milestones Completed**: 5 of 19 (Phase 1 + Phase 2.1 + Phase 2.2)
- **Estimated Remaining Dev Time**: ~40-50 hours (Phases 3-8)
- **Estimated Calendar Time to Production**: ~4 weeks (including 2-week validation)

## 🎯 Success Criteria (Phase 1 Complete)
- [x] Technical blueprint updated with all table schemas
- [x] Reconciliation plan maps current → v2 state
- [x] Pipeline DAG documents dependencies and failure modes
- [x] SQL schemas designed for all tables
- [x] Fundamental data audit complete (found missing columns)
- [ ] Stop-loss logic validated (Milestone 2.3 - next session)

---

**Session Duration**: ~2.5 hours
**Session Focus**: Planning & Documentation (no code implementation)
**Next Session Priority**: Complete Phase 2.3 (stop-loss validation), then start Phase 3 (T1/T2 implementation)
