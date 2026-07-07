# DuckDB v2 Optimization Proposals

This folder contains proposals and implementation plans for optimizing the DuckDB-based feature pipeline.

---

## 📂 Documents

### **Planning & Analysis**
- [FEATURE_OPTIMIZATION_ANALYSIS.md](./FEATURE_OPTIMIZATION_ANALYSIS.md) - Feature usage analysis and optimization opportunities
- [FEATURE_PRUNING_PLAN.md](./FEATURE_PRUNING_PLAN.md) - Implementation plan for feature optimization (Milestone 3.5.1)

### **Migration Guides**
- [MIGRATION_V3_1_SUMMARY.md](./MIGRATION_V3_1_SUMMARY.md) - **CURRENT**: v3.0 → v3.1 migration guide (add pct_chg features)

---

## 🎯 Current Milestone: 3.5.1 - Feature Optimization

### **Objective**
Add 19 percentage change delta features to `daily_features` table to improve query performance and model training.

### **Status**: Ready for Execution (Step 1 Complete)

### **Quick Start**

#### **Step 1: Run Migration**
```bash
python scripts/migrate_to_v3_1.py
```

Expected runtime: ~60 seconds

#### **Step 2: Validate Migration**
```bash
python scripts/validate_v3_1_migration.py
```

Expected result: All checks pass (exit code 0)

#### **Step 3: Review Results**
Check validation output for:
- ✅ All 19 pct_chg columns exist
- ✅ NULL counts match ticker count (~1,826)
- ✅ Formula calculations are correct
- ✅ No extreme outliers (or very few)

---

## 📊 Migration Details

### **What Changes?**
- **Add**: 19 new `*_pct_chg` columns to `daily_features`
- **Update**: `feature_version` from 'v3.0' to 'v3.1'
- **Storage**: +19 columns (+17% increase, ~49M additional cells)

### **Formula**
```sql
(current_value - previous_value) / ABS(previous_value) * 100
```

**Special handling**:
- Use `ABS()` for distance metrics that can be negative
- First row per ticker will be NULL (no previous value)
- Handle division by zero with `NULLIF(..., 0)`

### **New Features**
See [MIGRATION_V3_1_SUMMARY.md](./MIGRATION_V3_1_SUMMARY.md) for complete list.

**Categories**:
- 3 Moving Average deltas
- 2 Momentum deltas
- 1 Volume delta
- 5 Volatility deltas
- 4 52-week range deltas
- 4 20-day range deltas

---

## 🔧 Scripts

### **Migration Scripts**
- [scripts/migrate_to_v3_1.py](../../scripts/migrate_to_v3_1.py) - Add columns and populate pct_chg features
- [scripts/validate_v3_1_migration.py](../../scripts/validate_v3_1_migration.py) - Comprehensive validation checks

### **Related Scripts**
- [scripts/verify_d2_columns.py](../../scripts/verify_d2_columns.py) - General schema validation
- [scripts/create_duckdb_views.py](../../scripts/create_duckdb_views.py) - Recreate all views

---

## 🚨 Troubleshooting

### **Migration Fails**
1. Check database exists: `ls data/market_data.duckdb`
2. Verify no other processes using database
3. Check error message and traceback

### **Validation Fails**
1. Review which specific check failed
2. Check sample data output for anomalies
3. Verify formula calculations manually

### **Rollback**
See [MIGRATION_V3_1_SUMMARY.md](./MIGRATION_V3_1_SUMMARY.md#-rollback-plan) for rollback options.

---

## 📈 Next Steps (Future Milestones)

### **3.5.2 - Update Feature Pipeline**
- Modify `src/feature_pipeline.py` to compute pct_chg features in Phase A
- Remove post-hoc migration script (no longer needed for new data)

### **3.5.3 - Remove Deprecated Features**
- Remove `df_lags` CTE from `v_d1_candidates`
- Drop `alpha051` from Phase B
- Update model feature lists

### **3.5.4 - Performance Optimization**
- Benchmark query performance (v3.0 vs v3.1)
- Optimize view queries with new pct_chg features
- Profile model training time

---

## 🔗 Related Documentation

### **Architecture**
- [src/feature_pipeline.py](../../src/feature_pipeline.py) - 3-phase feature computation
- [src/view_manager.py](../../src/view_manager.py) - View definitions and COLUMN_CASE_MAP
- [data_curator_duckdb.py](../../data_curator_duckdb.py) - Pipeline orchestration

### **Project Memory**
- [MEMORY.md](../../../.claude/projects/c--Users-Hang-PycharmProjects-quantamental/memory/MEMORY.md) - Project-wide knowledge base

### **Feature Documentation**
- [FEATURE_DICTIONARY.md](../modules/FEATURE_DICTIONARY.md) - Comprehensive feature reference

---

**Last Updated**: 2026-03-14
**Version**: v3.1 (in progress)
