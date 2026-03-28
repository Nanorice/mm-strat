# Migration Summary: v3.0 → v3.1

**Date**: 2026-03-14
**Milestone**: 3.5.1 Feature Pruning - Step 1
**Status**: Ready for execution

---

## 🎯 Objective

Add 19 percentage change delta features to `daily_features` table to support ML models without requiring expensive `LAG()` operations in views.

**Key Principle**: Store computed deltas, avoid recomputing in every query.

---

## 📊 Schema Changes

### **New Columns (19 total)**

#### Moving Average Deltas (3)
- `price_vs_sma_50_pct_chg` - % change in distance from SMA50
- `price_vs_sma_150_pct_chg` - % change in distance from SMA150
- `price_vs_sma_200_pct_chg` - % change in distance from SMA200

#### Momentum Deltas (2)
- `rs_pct_chg` - % change in RS line
- `rs_ma_pct_chg` - % change in RS moving average

#### Volume Delta (1)
- `dry_up_volume_pct_chg` - % change in dry-up volume metric

#### Volatility Deltas (5)
- `natr_pct_chg` - % change in normalized ATR
- `atr_pct_chg` - % change in ATR 20d
- `vcp_ratio_pct_chg` - % change in VCP contraction ratio
- `consolidation_width_pct_chg` - % change in consolidation width
- `rsi_14_pct_chg` - % change in RSI 14-day

#### 52-Week Range Deltas (4)
- `dist_from_52w_high_pct_chg` - % change in distance from 52w high
- `dist_from_52w_low_pct_chg` - % change in distance from 52w low
- `low_52w_pct_chg` - % change in 52-week low level
- `high_52w_pct_chg` - % change in 52-week high level

#### 20-Day Range Deltas (4)
- `dist_from_20d_high_pct_chg` - % change in distance from 20d high
- `dist_from_20d_low_pct_chg` - % change in distance from 20d low
- `lowest_low_20d_pct_chg` - % change in 20-day lowest low
- `highest_high_20d_pct_chg` - % change in 20-day highest high

---

## 🔧 Migration Scripts

### 1. **migrate_to_v3_1.py**
**Purpose**: Add columns and populate percentage change features

**Steps**:
1. ✅ Add 19 new columns to `daily_features` schema (DOUBLE type)
2. ✅ Compute percentage change using window functions:
   ```sql
   (current_value - LAG(current_value, 1) OVER ticker_date)
   / NULLIF(ABS(LAG(current_value, 1) OVER ticker_date), 0) * 100
   ```
3. ✅ Update `feature_version` to 'v3.1'

**Special Handling**:
- Use `ABS()` in denominator for distance metrics that can be negative (e.g., `dist_from_52w_high`)
- First row per ticker will be NULL (no previous value to compare)
- Handles division by zero with `NULLIF(..., 0)`

**Runtime**: ~60s for 2.6M rows (single UPDATE with 19 computations)

---

### 2. **validate_v3_1_migration.py**
**Purpose**: Verify migration correctness

**Validation Checks**:
1. ✅ **Schema Check**: All 19 pct_chg columns exist
2. ✅ **Version Check**: `feature_version = 'v3.1'` for all rows
3. ✅ **Formula Check**: Spot-check calculations match manual recomputation
4. ✅ **NULL Pattern**: Each ticker has exactly 1 NULL (first row)
5. ✅ **Extreme Values**: Flag >1000% changes (may be valid for stock splits)
6. ✅ **Sample Data**: Display 10 rows for manual inspection

**Exit Codes**:
- 0: All checks passed
- 1: At least one check failed

---

## 📝 Usage Instructions

### **Step 1: Run Migration**
```bash
python scripts/migrate_to_v3_1.py
```

**Expected Output**:
```
================================================================================
Schema Migration: daily_features v3.0 → v3.1
================================================================================
Database: c:\Users\Hang\PycharmProjects\quantamental\data\market_data.duckdb

📋 Adding new columns to daily_features schema...
  ✅ price_vs_sma_50_pct_chg         DOUBLE     -- % change in distance from SMA50
  ✅ price_vs_sma_150_pct_chg        DOUBLE     -- % change in distance from SMA150
  ...
  (19 columns total)

📊 Summary: 19 columns added, 0 columns skipped

🔄 Computing percentage change features...
  ⏳ Running UPDATE query (this may take 30-60s for 2.6M rows)...
  ✅ All percentage change features populated

🔖 Updating feature version...
  ✅ v3.1: 2,600,000 rows

🔍 Validating migration...
  📊 Total columns: 129
  📈 Total tickers: 1826
  ⚠️  NULL counts (should ~= 1826, first row per ticker):
      rs_pct_chg: 1,826
      natr_pct_chg: 1,826
      price_vs_sma_50_pct_chg: 1,826

  📋 Sample data (first 5 non-NULL rows):
  ...

  🎯 Max absolute percentage changes (sanity check):
      rs_pct_chg: 245.67%
      natr_pct_chg: 523.12%
      price_vs_sma_50_pct_chg: 187.45%

================================================================================
✅ Migration completed successfully!
================================================================================
```

---

### **Step 2: Run Validation**
```bash
python scripts/validate_v3_1_migration.py
```

**Expected Output**:
```
================================================================================
Validation: daily_features v3.1 Migration
================================================================================

📋 Checking schema...
  ✅ All 19 expected pct_chg columns found

🔖 Checking feature version...
  feature_version       cnt
            v3.1 2,600,000
  ✅ All 2,600,000 rows updated to v3.1

🔍 Validating percentage change formulas...
  ✅ All rs_pct_chg calculations match manual recomputation

🔍 Checking NULL patterns...
  ✅ All tickers have exactly 1 NULL (first row)

🎯 Checking for extreme values...
  📊 Total non-NULL rows: 2,598,174
  📈 Max absolute values:
      rs_pct_chg: 245.67%
      natr_pct_chg: 523.12%
      price_vs_sma_50_pct_chg: 187.45%
  ✅ No extreme outliers detected

📋 Sample data (random ticker, 10 consecutive days):
  ...

================================================================================
✅ All validation checks PASSED
================================================================================
```

---

## 🎯 Post-Migration Tasks

### **Immediate (Required)**
- [ ] Run migration script
- [ ] Run validation script (must pass)
- [ ] Update `MEMORY.md` with new schema info
- [ ] Update `FEATURE_PRUNING_PLAN.md` checklist (mark Phase 1 complete)

### **Next Steps (Phase 2-4)**
- [ ] Remove `df_lags` CTE from `v_d1_candidates` (Phase 3)
- [ ] Drop `alpha051` from Phase B (Phase 4)
- [ ] Update `feature_pipeline.py` to compute pct_chg in Phase A (future runs)
- [ ] Test model training with new features
- [ ] Update model feature lists if needed

### **Optional (Future)**
- [ ] Add pct_chg columns to `COLUMN_CASE_MAP` if models require TitleCase
- [ ] Backfill missing fundamental ratios (pe_ratio, ps_ratio, pb_ratio)
- [ ] Performance benchmarks (compare v3.0 vs v3.1 query times)

---

## 🚨 Rollback Plan

If migration fails or data is corrupted:

### **Option 1: Manual Rollback (Recommended)**
```sql
-- Remove pct_chg columns
ALTER TABLE daily_features DROP COLUMN price_vs_sma_50_pct_chg;
ALTER TABLE daily_features DROP COLUMN price_vs_sma_150_pct_chg;
-- (repeat for all 19 columns)

-- Revert feature version
UPDATE daily_features SET feature_version = 'v3.0';
```

### **Option 2: Restore from Backup**
```bash
# If you have a backup of market_data.duckdb
cp data/market_data.duckdb.backup data/market_data.duckdb
```

### **Option 3: Re-run Feature Pipeline**
```bash
# Nuclear option: rebuild daily_features from scratch
python data_curator_duckdb.py --rebuild-features
```

---

## 📊 Expected Impact

### **Storage**
- **Before**: 110 columns × 2.6M rows = 286M cells
- **After**: 129 columns × 2.6M rows = 335M cells
- **Increase**: +19 columns (+17% column count, minimal disk impact)

### **Performance**
- **View Queries**: Should be **faster** (no LAG() recomputation)
- **Feature Pipeline**: Will be **slower** next run (+19 computations in Phase A)
- **Model Training**: Should be **same** (features already computed)

### **Data Quality**
- **NULL Values**: +1,826 NULLs per pct_chg column (first row per ticker, expected)
- **Extreme Values**: May see >100% changes for volatile stocks (normal)

---

## ✅ Success Criteria

- [ ] All 19 columns added successfully
- [ ] All validation checks pass (exit code 0)
- [ ] NULL count matches ticker count (~1,826)
- [ ] Sample data looks reasonable (no obvious errors)
- [ ] Feature version updated to 'v3.1'
- [ ] No extreme outliers (>1000% changes) or very few (<0.1%)

---

## 🔗 Related Files

- **Migration**: [scripts/migrate_to_v3_1.py](../../scripts/migrate_to_v3_1.py)
- **Validation**: [scripts/validate_v3_1_migration.py](../../scripts/validate_v3_1_migration.py)
- **Plan**: [FEATURE_PRUNING_PLAN.md](./FEATURE_PRUNING_PLAN.md)
- **Feature Pipeline**: [src/feature_pipeline.py](../../src/feature_pipeline.py)
- **View Manager**: [src/view_manager.py](../../src/view_manager.py)

---

## 📝 Notes

1. **Why Percentage Change?**
   - More meaningful than absolute spread (e.g., +0.5 means different things for $10 vs $1000 stocks)
   - Handles negative values correctly (distance metrics like `dist_from_52w_high`)
   - Standard formula: `(current - previous) / ABS(previous) * 100`

2. **Why ABS() in Denominator?**
   - Distance metrics can be negative (e.g., `dist_from_52w_high = -2.5` means 2.5% below high)
   - Without ABS(), percentage change would flip sign incorrectly
   - Example: `-2.5 → -3.0` should be **increase** in magnitude (+20%), not decrease

3. **Why Store in daily_features?**
   - Avoid expensive LAG() recomputation in every view query
   - Pre-computed features are faster to load for model training
   - Enables easier debugging (can query deltas directly)

4. **Future Optimization**
   - Consider migrating Phase A computations to DuckDB SQL (currently FeaturePipeline)
   - This would compute pct_chg features during pipeline run (not post-hoc migration)
   - Milestone 3.5.2 will update `feature_pipeline.py` to include these in Phase A

---

**End of Migration Summary**
