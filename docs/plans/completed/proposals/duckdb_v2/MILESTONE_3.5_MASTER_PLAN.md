# Milestone 3.5: Feature Optimization - Master Plan
**Version**: 1.0
**Last Updated**: 2026-03-14
**Status**: In Progress

---

## 🎯 Overview

Milestone 3.5 focuses on optimizing the feature computation pipeline for **performance**, **storage efficiency**, and **maintainability** without sacrificing flexibility or model accuracy.

**Key Principles**:
- ✅ **Correctness over speed**: Use proper percentage change formulas
- ✅ **Flexibility over size**: Keep intermediate features for future use
- ✅ **Incremental over full**: Only recompute what changed
- ✅ **Materialized over computed**: Cache expensive views

---

## 📋 Sub-Milestones

### **3.5.1: Feature Pruning & Delta Calculation** ⏳ IN PROGRESS
**Goal**: Add proper percentage change delta features, remove redundant lag1 views

**Deliverables**:
- ✅ Feature dictionary documentation ([FEATURE_DICTIONARY.md](c:/Users/Hang/PycharmProjects/quantamental/docs/modules/FEATURE_DICTIONARY.md))
- ✅ Implementation plan ([FEATURE_PRUNING_PLAN.md](c:/Users/Hang/PycharmProjects/quantamental/docs/proposals/duckdb_v2/FEATURE_PRUNING_PLAN.md))
- [ ] Add 19 `*_pct_chg` features to Phase A (percentage change formula)
- [ ] Remove lag1 CTE from `v_d1_candidates`
- [ ] Drop alpha051 from Phase B
- [ ] Bump feature_version to 'v4.0'

**Expected Impact**:
- Feature count: 110 → ~128 (+18, includes proper deltas)
- Storage: ~286M → ~334M cells (+17%, acceptable)
- Computation time: Similar (~180s)

---

### **3.5.2: Performance Optimization** 🔜 PLANNED
**Goal**: Reduce Phase B runtime from ~166s to <60s

**Approach**:
1. **Multiprocessing for WQ101 Alphas** (PRIMARY)
   - Parallelize 15 alpha computations using `multiprocessing.Pool`
   - Each alpha is independent (no shared state)
   - Expected speedup: **3-4x on multi-core systems**

2. **Vectorization Review** (SECONDARY)
   - Replace `groupby().apply()` with vectorized ops where possible
   - Candidates: alphas without `rolling().corr()` dependencies
   - Use numpy/pandas native operations

**Implementation Tasks**:
- [ ] Create `src/alpha_multiprocessing.py` wrapper module
- [ ] Refactor `compute_alpha_features()` to use process pool
- [ ] Add `n_workers` parameter (default: `os.cpu_count() - 1`)
- [ ] Test on full dataset (verify results match serial version)
- [ ] Benchmark: measure Phase B runtime improvement

**Expected Results**:
- Phase B runtime: **166s → 40-60s** (60-75% reduction)
- Total pipeline: **~180s → ~70-90s**
- No accuracy loss (deterministic results)

**Risk Mitigation**:
- Serialize DataFrame to shared memory or pickle for workers
- Handle edge cases (single-core fallback, worker failures)
- Ensure reproducibility (same results as serial version)

---

### **3.5.3: Incremental Feature Computation** 🔜 PLANNED
**Goal**: Only compute features for new/changed data (daily updates)

**Approach**:
1. **Delta Detection**
   - Identify which tickers have new data since last `daily_features` run
   - Query: `SELECT DISTINCT ticker FROM price_data WHERE date > (SELECT MAX(date) FROM daily_features)`

2. **Merge Strategy**
   - Compute features only for delta tickers (+ warmup days)
   - Merge with existing `daily_features` using `INSERT OR REPLACE`
   - Preserve feature_version consistency

3. **Fallback to Full Recompute**
   - If schema changed (feature_version mismatch)
   - If validation fails (missing warmup data)
   - If user forces full rebuild (`--force-full` flag)

**Implementation Tasks**:
- [ ] Add `detect_data_delta()` method to FeaturePipeline
- [ ] Add `compute_incremental()` method (delta + merge logic)
- [ ] Update `compute_all()` to support `incremental=True` parameter
- [ ] Add validation: check warmup sufficiency, schema compatibility
- [ ] Update `data_curator_duckdb.py` to use incremental mode by default

**Expected Results**:
- Daily updates: **~180s → 10-20s** (90% reduction)
- Weekly full recompute: **~180s** (unchanged, for data integrity)
- Reduced database write pressure

**Risk Mitigation**:
- Always validate delta has sufficient warmup (365 days)
- Log which mode is used (incremental vs full)
- Add integrity check: compare incremental vs full results on test set

---

### **3.5.4: View Materialization** 🔜 PLANNED
**Goal**: Pre-compute expensive views for faster query performance

**Target Views**:
1. **`v_d2_training`** (PRIMARY)
   - Computes 29 log transforms on every query
   - Used for M01/M02 training data loading
   - Current load time: 5-10s → Target: <1s

2. **`v_d2_features`** (SECONDARY)
   - Joins daily_features + fundamentals (point-in-time)
   - Used for feature exploration and analysis

**Approach**:
1. **Create Materialized Tables**
   ```sql
   CREATE TABLE m_d2_training AS SELECT * FROM v_d2_training;
   CREATE INDEX idx_m_d2_training_date ON m_d2_training(date, ticker);
   ```

2. **Refresh Strategy**
   - Refresh after `daily_features` updates (in `compute_all()`)
   - Use `CREATE OR REPLACE TABLE` for atomic updates
   - Add `materialized_at` timestamp column

3. **View Manager Updates**
   - Add `materialize_view(view_name)` method
   - Add `refresh_materialized_views()` method
   - Track materialization status in metadata table

**Implementation Tasks**:
- [ ] Add `materialized_views` metadata table (view_name, last_refresh, row_count)
- [ ] Add `materialize_view()` to ViewManager
- [ ] Add `refresh_materialized_views()` to FeaturePipeline
- [ ] Update `data_curator_duckdb.py` to refresh after feature computation
- [ ] Update `src/data_loader_duckdb.py` to query materialized tables

**Expected Results**:
- Training data load time: **5-10s → <1s** (80-90% reduction)
- Model training pipeline: **10-15s faster** overall
- Trade-off: +334M cells storage for materialized views

**Risk Mitigation**:
- Add staleness check: warn if materialized view older than daily_features
- Provide fallback to original view if materialized version missing
- Document refresh schedule (daily, after feature updates)

---

## 📊 Cumulative Impact (All Sub-Milestones)

| Metric | Before (v3.0) | After (v4.0) | Improvement |
|--------|---------------|--------------|-------------|
| **Phase A (SQL)** | 79 cols, ~10s | 98 cols, ~10s | +19 pct_chg features |
| **Phase B (Python)** | 16 alphas, ~166s | 15 alphas, ~40-60s | **60-75% faster** |
| **Phase C (SQL)** | 8 ranks, ~2s | 8 ranks, ~2s | Unchanged |
| **Total Pipeline** | ~180s | **~70-90s** | **50-60% faster** |
| **Daily Updates** | 180s (full) | **10-20s** (incremental) | **90% faster** |
| **Training Load** | 5-10s | **<1s** (materialized) | **80-90% faster** |
| **Storage** | 286M cells | ~668M cells | +134% (acceptable) |

---

## 🗓️ Implementation Timeline

### **Week 1** (Current)
- ✅ Complete 3.5.1 documentation (FEATURE_DICTIONARY.md, FEATURE_PRUNING_PLAN.md)
- [ ] Implement 3.5.1: Add pct_chg features, remove lag1, drop alpha051
- [ ] Test & validate 3.5.1 (schema, data integrity, model compatibility)

### **Week 2**
- [ ] Implement 3.5.2: Multiprocessing for Phase B
- [ ] Benchmark Phase B performance (serial vs parallel)
- [ ] Optimize: tune n_workers, test edge cases

### **Week 3**
- [ ] Implement 3.5.3: Incremental feature computation
- [ ] Test incremental mode (delta detection, merge logic)
- [ ] Validate: compare incremental vs full results

### **Week 4**
- [ ] Implement 3.5.4: View materialization
- [ ] Test materialized views (refresh, staleness checks)
- [ ] Integration test: full pipeline (incremental + materialized)
- [ ] Update MEMORY.md, documentation, and handover

---

## ✅ Success Criteria

### **Functional Requirements**
- [x] Feature dictionary documents all 128 features (purpose, calculation, unit)
- [ ] All 19 `*_pct_chg` features use correct percentage change formula
- [ ] Lag1 features removed from views (no duplication)
- [ ] Phase B runtime <60s (multiprocessing)
- [ ] Daily incremental updates <20s (90% faster)
- [ ] Training data load <1s (materialized views)

### **Quality Requirements**
- [ ] Feature version bumped to 'v4.0'
- [ ] All tests pass (schema validation, data integrity, model compatibility)
- [ ] No accuracy loss (models retrained with v4.0 features)
- [ ] Performance benchmarks documented (before/after)

### **Documentation Requirements**
- [x] Feature dictionary complete (FEATURE_DICTIONARY.md)
- [x] Implementation plans for all sub-milestones
- [ ] MEMORY.md updated with v4.0 schema and performance notes
- [ ] Code comments explain multiprocessing, incremental, materialization logic

---

## 🚨 Risks & Mitigations

### **Risk 1**: Multiprocessing overhead exceeds gains (small datasets)
- **Mitigation**: Add `n_workers=1` fallback for small datasets (<500k rows)
- **Mitigation**: Benchmark on production dataset (2.6M rows) before deploying

### **Risk 2**: Incremental computation misses edge cases
- **Mitigation**: Weekly full recompute for data integrity
- **Mitigation**: Validation step compares incremental vs full on sample

### **Risk 3**: Materialized views become stale
- **Mitigation**: Add staleness warning (if view older than daily_features)
- **Mitigation**: Automatic refresh after feature updates

### **Risk 4**: Models break with v4.0 features
- **Mitigation**: Retrain M01/M02 with v4.0 features
- **Mitigation**: Keep v3.0 models as 'archived' in registry
- **Mitigation**: Feature compatibility tests before deployment

---

## 📁 Deliverables

### **Documentation**
- [x] FEATURE_DICTIONARY.md (comprehensive feature reference)
- [x] FEATURE_PRUNING_PLAN.md (3.5.1 implementation plan)
- [ ] PERFORMANCE_OPTIMIZATION_PLAN.md (3.5.2 implementation plan)
- [ ] INCREMENTAL_COMPUTATION_PLAN.md (3.5.3 implementation plan)
- [ ] VIEW_MATERIALIZATION_PLAN.md (3.5.4 implementation plan)
- [ ] MEMORY.md updates (v4.0 schema, performance notes)

### **Code**
- [ ] src/feature_pipeline.py (add pct_chg features, incremental mode)
- [ ] src/alpha_multiprocessing.py (multiprocessing wrapper)
- [ ] src/view_manager.py (materialization support)
- [ ] data_curator_duckdb.py (incremental + materialized refresh)
- [ ] scripts/verify_d2_columns.py (v4.0 schema validation)

### **Tests**
- [ ] Test percentage change formula correctness
- [ ] Test multiprocessing (serial vs parallel parity)
- [ ] Test incremental mode (delta detection, merge)
- [ ] Test materialized views (refresh, staleness)
- [ ] Integration test: full pipeline (all optimizations enabled)

---

## 🔗 Related Documentation

- [FEATURE_DICTIONARY.md](c:/Users/Hang/PycharmProjects/quantamental/docs/modules/FEATURE_DICTIONARY.md) - Feature reference
- [FEATURE_PRUNING_PLAN.md](c:/Users/Hang/PycharmProjects/quantamental/docs/proposals/duckdb_v2/FEATURE_PRUNING_PLAN.md) - 3.5.1 plan
- [MEMORY.md](C:/Users/Hang/.claude/projects/c--Users-Hang-PycharmProjects-quantamental/memory/MEMORY.md) - Architecture notes
- [implementation_plan.md](c:/Users/Hang/PycharmProjects/quantamental/implementation_plan.md) - Overall project plan

---

## 📝 Session Notes

### **2026-03-14: Planning Session**
- ✅ Created FEATURE_DICTIONARY.md (comprehensive, 128 features documented)
- ✅ Created FEATURE_PRUNING_PLAN.md (3.5.1 ready for implementation)
- ✅ Created MILESTONE_3.5_MASTER_PLAN.md (this document)
- 🔄 Ready to implement 3.5.1 (add pct_chg features)

**Key Decisions**:
1. Keep ALL intermediate features (no deletion for flexibility)
2. Use percentage change formula for all `*_pct_chg` deltas (not spread)
3. Add 19 new features (net +18 after removing alpha051)
4. Prioritize correctness and flexibility over storage optimization
5. Incremental computation and materialization for daily performance gains

**Next Steps**:
1. Implement Phase 1 of 3.5.1 (add 19 pct_chg features to Phase A)
2. Implement Phase 3 of 3.5.1 (remove lag1 from views)
3. Implement Phase 4 of 3.5.1 (drop alpha051)
4. Test & validate (schema, data integrity, model compatibility)
5. Move to 3.5.2 (multiprocessing optimization)
