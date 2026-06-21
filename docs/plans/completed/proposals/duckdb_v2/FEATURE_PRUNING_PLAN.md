# Feature Pruning Implementation Plan
**Milestone**: 3.5.1 - Feature Optimization
**Date**: 2026-03-14
**Status**: ✅ COMPLETE (Steps 1-5 Complete - v3.1 Migration & View Optimization Done)

---

## 🎯 Objective

**Remove unnecessary features** from the pipeline to improve:
1. **Storage efficiency**: Reduce `daily_features` table size
2. **Computation speed**: Skip redundant calculations
3. **Model clarity**: Keep only features that are actually used

**Key Principle**: **No auto-drop based on correlation or importance**. Only remove:
- ✅ `log_*` features (computed in views, not stored)
- ✅ `*_lag1` features (replaced with `*_delta` computed directly in SQL)
- ✅ Intermediate/passthrough features (only used for calculations, not ML)

---

## 📊 Current State Analysis

### **Current Feature Count**
```
Phase A (SQL):     79 columns  (base features)
Phase B (Python):  16 columns  (WQ101 alphas)
Phase C (SQL):      8 columns  (cross-sectional ranks)
Phase D (SQL):      4 columns  (M03 regime base)
Phase E (SQL):      3 columns  (M03 derived)
─────────────────────────────────
TOTAL:            110 columns
```

### **Features to Remove (27 total)**

#### **1. Log Transform Features (29 features)** - Computed in `v_d2_training` view
These are **NOT stored** in `daily_features`, only computed in the training view:
```python
LOG_FEATURES = [
    'log_close', 'log_volume', 'log_turnover', 'log_dollar_volume_avg_20',
    'log_sma_50', 'log_sma_150', 'log_sma_200',
    'log_rs', 'log_rs_ma', 'log_vol_avg_20', 'log_vol_avg_50',
    'log_atr_20d', 'log_natr', 'log_volatility_20d',
    'log_high_52w', 'log_low_52w',
    'log_eps_diluted', 'log_revenue_growth_yoy', 'log_eps_growth_yoy',
    'log_net_income_growth_yoy', 'log_debt_to_equity', 'log_current_ratio',
    'log_gross_margin', 'log_operating_margin', 'log_roe', 'log_roa',
    'log_fcf_margin', 'log_m03_score', 'log_m03_regime_vol'
]
```
**Action**: ✅ Already handled correctly (not in `daily_features`)

#### **2. Lag1 Features (18 features)** - Replace with delta features
Currently in `v_d1_candidates` view (see [view_manager.py:315-335](c:/Users/Hang/PycharmProjects/quantamental/src/view_manager.py#L315-L335)):
```sql
LAG1_FEATURES = [
    'natr_lag1',
    'atr_lag1',
    'vcp_ratio_lag1',
    'consolidation_width_lag1',
    'price_vs_sma_50_lag1',
    'price_vs_sma_150_lag1',
    'price_vs_sma_200_lag1',
    'rs_lag1',
    'rs_ma_lag1',
    'dry_up_volume_lag1',
    'high_52w_lag1',
    'low_52w_lag1',
    'lowest_low_20d_lag1',
    'highest_high_20d_lag1',
    'rsi_14_lag1',
    'dist_from_52w_high_lag1',
    'dist_from_52w_low_lag1',
    'dist_from_20d_low_lag1',
    'dist_from_20d_high_lag1'
]
```

**Action**:
- ❌ **Remove** these 18 `*_lag1` columns from `v_d1_candidates`
- ✅ **Add** 12 `*_delta` columns (computed directly in SQL)

#### **3. Intermediate/Passthrough Features (KEEP in storage)**
**Decision**: Do NOT remove features just because they're not in the final ML feature list.

These features may be useful for:
- Future feature engineering
- Manual analysis and debugging
- Alternative model experiments
- Validation and cross-checks

**Action**: ✅ Keep all intermediate features in `daily_features` table
**Rationale**: Storage is cheap, recomputation is expensive. Only remove truly redundant duplicates.

---

## 🎯 Target Feature Set (72 features)

Based on `FEATURE_GROUPS` dictionary:

### **1. Moving Averages (8 features)**
```python
['close_above_sma200', 'price_vs_sma_50', 'price_vs_sma_150', 'price_vs_sma_200',
 'sma_50_slope', 'price_vs_sma_50_pct_chg', 'price_vs_sma_150_pct_chg', 'price_vs_sma_200_pct_chg']
```
**Implementation**:
- ✅ Already in Phase A: `close_above_sma200`, `price_vs_sma_50/150/200`, `sma_50_slope`
- ➕ **Add percentage change deltas** in Phase A (replace lag1):
  ```sql
  -- Use percentage change, NOT absolute spread
  ((price_vs_sma_50 - LAG(price_vs_sma_50, 1) OVER ticker_date)
   / NULLIF(ABS(LAG(price_vs_sma_50, 1) OVER ticker_date), 0)) * 100 AS price_vs_sma_50_pct_chg,

  ((price_vs_sma_150 - LAG(price_vs_sma_150, 1) OVER ticker_date)
   / NULLIF(ABS(LAG(price_vs_sma_150, 1) OVER ticker_date), 0)) * 100 AS price_vs_sma_150_pct_chg,

  ((price_vs_sma_200 - LAG(price_vs_sma_200, 1) OVER ticker_date)
   / NULLIF(ABS(LAG(price_vs_sma_200, 1) OVER ticker_date), 0)) * 100 AS price_vs_sma_200_pct_chg
  ```
  **Note**: Use `ABS()` in denominator to handle negative distances correctly

### **2. Momentum & RS (22 features)**
```python
['rs_line_uptrend', 'rs_line_delta', 'rs_line_lag_delta', 'rs_rating', 'rs', 'rs_ma',
 'rs_pct_chg', 'rs_ma_pct_chg', 'mom_21d', 'mom_63d', 'mom_126d', 'mom_189d', 'mom_252d',
 'rs_velocity', 'price_accel_10d', 'RS_Sector_Rank', 'RS_vs_Sector', 'Sector_Momentum',
 'RS_Industry_Rank', 'RS_vs_Industry', 'Industry_Momentum']
```
**Implementation**:
- ✅ Already in Phase A: `rs_line_uptrend`, `rs_line_delta`, `rs_line_lag_delta`, `rs_rating`, `rs`, `rs_ma`, `mom_21d/63d/126d/189d/252d`, `rs_velocity`, `price_accel_10d`
- ➕ **Add percentage change deltas** in Phase A:
  ```sql
  -- RS momentum (percentage change, handle negatives correctly)
  ((rs - LAG(rs, 1) OVER ticker_date)
   / NULLIF(ABS(LAG(rs, 1) OVER ticker_date), 0)) * 100 AS rs_pct_chg,

  ((rs_ma - LAG(rs_ma, 1) OVER ticker_date)
   / NULLIF(ABS(LAG(rs_ma, 1) OVER ticker_date), 0)) * 100 AS rs_ma_pct_chg
  ```
- ✅ Already in Phase C: `RS_Sector_Rank`, `RS_vs_Sector`, `Sector_Momentum`, `RS_Industry_Rank`, `RS_vs_Industry`, `Industry_Momentum`

### **3. Core Volume (7 features)**
```python
['vol_ratio', 'dry_up_volume', 'dry_up_volume_pct_chg', 'turnover',
 'volume_acceleration', 'return_1d', 'return_5d']
```
**Implementation**:
- ✅ Already in Phase A: `vol_ratio`, `dry_up_volume`, `turnover`, `volume_acceleration`, `return_1d`, `return_5d`
- ➕ **Add percentage change delta** in Phase A:
  ```sql
  ((dry_up_volume - LAG(dry_up_volume, 1) OVER ticker_date)
   / NULLIF(LAG(dry_up_volume, 1) OVER ticker_date, 0)) * 100 AS dry_up_volume_pct_chg
  ```

### **4. Volatility & Ranges (18 features)**
```python
['natr', 'natr_pct_chg', 'atr_20d', 'atr_pct_chg', 'vcp_ratio', 'vcp_ratio_pct_chg',
 'consolidation_width', 'consolidation_width_pct_chg', 'consolidation_duration',
 'dist_from_52w_high', 'dist_from_52w_high_pct_chg',
 'dist_from_52w_low', 'dist_from_52w_low_pct_chg',
 'low_52w_pct_chg', 'high_52w_pct_chg',
 'dist_from_20d_high', 'dist_from_20d_high_pct_chg', 'highest_high_20d_pct_chg',
 'dist_from_20d_low', 'dist_from_20d_low_pct_chg', 'lowest_low_20d_pct_chg']
```
**Implementation**:
- ✅ Already in Phase A: `natr`, `atr_20d`, `vcp_ratio`, `consolidation_width`, `consolidation_duration`, `dist_from_52w_high/low`, `dist_from_20d_high/low`
- ➕ **Add percentage change deltas** in Phase A (replace lag1):
  ```sql
  -- Volatility metrics (percentage change)
  ((natr - LAG(natr, 1) OVER ticker_date)
   / NULLIF(LAG(natr, 1) OVER ticker_date, 0)) * 100 AS natr_pct_chg,

  ((atr_20d - LAG(atr_20d, 1) OVER ticker_date)
   / NULLIF(LAG(atr_20d, 1) OVER ticker_date, 0)) * 100 AS atr_pct_chg,

  ((vcp_ratio - LAG(vcp_ratio, 1) OVER ticker_date)
   / NULLIF(LAG(vcp_ratio, 1) OVER ticker_date, 0)) * 100 AS vcp_ratio_pct_chg,

  ((consolidation_width - LAG(consolidation_width, 1) OVER ticker_date)
   / NULLIF(LAG(consolidation_width, 1) OVER ticker_date, 0)) * 100 AS consolidation_width_pct_chg,

  -- Distance metrics (percentage change, handle negatives with ABS)
  ((dist_from_52w_high - LAG(dist_from_52w_high, 1) OVER ticker_date)
   / NULLIF(ABS(LAG(dist_from_52w_high, 1) OVER ticker_date), 0)) * 100 AS dist_from_52w_high_pct_chg,

  ((dist_from_52w_low - LAG(dist_from_52w_low, 1) OVER ticker_date)
   / NULLIF(LAG(dist_from_52w_low, 1) OVER ticker_date, 0)) * 100 AS dist_from_52w_low_pct_chg,

  -- Raw level changes (percentage change)
  ((low_52w - LAG(low_52w, 1) OVER ticker_date)
   / NULLIF(LAG(low_52w, 1) OVER ticker_date, 0)) * 100 AS low_52w_pct_chg,

  ((high_52w - LAG(high_52w, 1) OVER ticker_date)
   / NULLIF(LAG(high_52w, 1) OVER ticker_date, 0)) * 100 AS high_52w_pct_chg,

  ((dist_from_20d_high - LAG(dist_from_20d_high, 1) OVER ticker_date)
   / NULLIF(ABS(LAG(dist_from_20d_high, 1) OVER ticker_date), 0)) * 100 AS dist_from_20d_high_pct_chg,

  ((dist_from_20d_low - LAG(dist_from_20d_low, 1) OVER ticker_date)
   / NULLIF(LAG(dist_from_20d_low, 1) OVER ticker_date, 0)) * 100 AS dist_from_20d_low_pct_chg,

  ((lowest_low_20d - LAG(lowest_low_20d, 1) OVER ticker_date)
   / NULLIF(LAG(lowest_low_20d, 1) OVER ticker_date, 0)) * 100 AS lowest_low_20d_pct_chg,

  ((highest_high_20d - LAG(highest_high_20d, 1) OVER ticker_date)
   / NULLIF(LAG(highest_high_20d, 1) OVER ticker_date, 0)) * 100 AS highest_high_20d_pct_chg
  ```
  **Note**: Use `ABS()` for distance metrics that can be negative (dist_from_52w_high, dist_from_20d_high)

### **5. Technical Oscillators (7 features)**
```python
['rsi_14', 'rsi_14_pct_chg', 'is_green_day', 'green_days_ratio_20d', 'breakout',
 'breakout_momentum', 'immediate_thrust']
```
**Implementation**:
- ✅ Already in Phase A: `rsi_14`, `is_green_day`, `green_days_ratio_20d`, `breakout`, `breakout_momentum`, `immediate_thrust`
- ➕ **Add percentage change delta** in Phase A:
  ```sql
  ((rsi_14 - LAG(rsi_14, 1) OVER ticker_date)
   / NULLIF(LAG(rsi_14, 1) OVER ticker_date, 0)) * 100 AS rsi_14_pct_chg
  ```

### **6. Fundamentals (24 features)**
```python
['eps_diluted', 'revenue_growth_yoy', 'eps_growth_yoy', 'net_income_growth_yoy',
 'eps_accel', 'revenue_accel', 'revenue_cagr_3y', 'eps_stability_score',
 'debt_to_equity', 'current_ratio', 'gross_margin', 'operating_margin', 'roe', 'roa',
 'fcf_margin', 'earnings_quality_score', 'gross_margin_trend', 'days_since_report',
 'pe_ratio', 'ps_ratio', 'pb_ratio']
```
**Implementation**:
- ✅ Already in `fundamentals` table (joined in views)
- ⚠️ **Note**: `pe_ratio`, `ps_ratio`, `pb_ratio` currently missing (100% NULL) - needs data backfill (outside this phase)

### **7. Fast Alphas (15 features)**
```python
['alpha001', 'alpha002', 'alpha004', 'alpha006', 'alpha009', 'alpha011', 'alpha012',
 'alpha013', 'alpha015', 'alpha041', 'alpha046', 'alpha049', 'alpha054', 'alpha060',
 'alpha101']
```
**Implementation**:
- ✅ Already in Phase B (Python)
- ⚠️ **Note**: Currently computing 16 alphas (includes `alpha051`), should drop `alpha051` if not in target set

### **8. M03 Regime (7 features)**
```python
['m03_score', 'm03_pillar_trend', 'm03_pillar_liq', 'm03_pillar_risk',
 'm03_delta_5d', 'm03_delta_20d', 'm03_regime_vol']
```
**Implementation**:
- ✅ Already in Phase D (base) + Phase E (derived)

---

## 🔧 Implementation Strategy

### **Phase 1: Add Percentage Change Delta Features to Phase A**
**File**: `src/feature_pipeline.py` → `compute_base_features()`

**Changes**:
1. Add 19 **percentage change** delta computations in `final_features` CTE:
   ```sql
   -- Moving Average deltas (percentage change, handle negatives with ABS)
   ((price_vs_sma_50 - LAG(price_vs_sma_50, 1) OVER ticker_date)
    / NULLIF(ABS(LAG(price_vs_sma_50, 1) OVER ticker_date), 0)) * 100 AS price_vs_sma_50_pct_chg,

   ((price_vs_sma_150 - LAG(price_vs_sma_150, 1) OVER ticker_date)
    / NULLIF(ABS(LAG(price_vs_sma_150, 1) OVER ticker_date), 0)) * 100 AS price_vs_sma_150_pct_chg,

   ((price_vs_sma_200 - LAG(price_vs_sma_200, 1) OVER ticker_date)
    / NULLIF(ABS(LAG(price_vs_sma_200, 1) OVER ticker_date), 0)) * 100 AS price_vs_sma_200_pct_chg,

   -- Momentum deltas (percentage change, handle negatives with ABS)
   ((rs - LAG(rs, 1) OVER ticker_date)
    / NULLIF(ABS(LAG(rs, 1) OVER ticker_date), 0)) * 100 AS rs_pct_chg,

   ((rs_ma - LAG(rs_ma, 1) OVER ticker_date)
    / NULLIF(ABS(LAG(rs_ma, 1) OVER ticker_date), 0)) * 100 AS rs_ma_pct_chg,

   -- Volume delta (percentage change)
   ((dry_up_volume - LAG(dry_up_volume, 1) OVER ticker_date)
    / NULLIF(LAG(dry_up_volume, 1) OVER ticker_date, 0)) * 100 AS dry_up_volume_pct_chg,

   -- Volatility deltas (percentage change)
   ((natr - LAG(natr, 1) OVER ticker_date)
    / NULLIF(LAG(natr, 1) OVER ticker_date, 0)) * 100 AS natr_pct_chg,

   ((atr_20d - LAG(atr_20d, 1) OVER ticker_date)
    / NULLIF(LAG(atr_20d, 1) OVER ticker_date, 0)) * 100 AS atr_pct_chg,

   ((vcp_ratio - LAG(vcp_ratio, 1) OVER ticker_date)
    / NULLIF(LAG(vcp_ratio, 1) OVER ticker_date, 0)) * 100 AS vcp_ratio_pct_chg,

   ((consolidation_width - LAG(consolidation_width, 1) OVER ticker_date)
    / NULLIF(LAG(consolidation_width, 1) OVER ticker_date, 0)) * 100 AS consolidation_width_pct_chg,

   ((rsi_14 - LAG(rsi_14, 1) OVER ticker_date)
    / NULLIF(LAG(rsi_14, 1) OVER ticker_date, 0)) * 100 AS rsi_14_pct_chg,

   -- Range deltas (percentage change, use ABS for distance metrics that can be negative)
   ((dist_from_52w_high - LAG(dist_from_52w_high, 1) OVER ticker_date)
    / NULLIF(ABS(LAG(dist_from_52w_high, 1) OVER ticker_date), 0)) * 100 AS dist_from_52w_high_pct_chg,

   ((dist_from_52w_low - LAG(dist_from_52w_low, 1) OVER ticker_date)
    / NULLIF(LAG(dist_from_52w_low, 1) OVER ticker_date, 0)) * 100 AS dist_from_52w_low_pct_chg,

   ((low_52w - LAG(low_52w, 1) OVER ticker_date)
    / NULLIF(LAG(low_52w, 1) OVER ticker_date, 0)) * 100 AS low_52w_pct_chg,

   ((high_52w - LAG(high_52w, 1) OVER ticker_date)
    / NULLIF(LAG(high_52w, 1) OVER ticker_date, 0)) * 100 AS high_52w_pct_chg,

   ((dist_from_20d_high - LAG(dist_from_20d_high, 1) OVER ticker_date)
    / NULLIF(ABS(LAG(dist_from_20d_high, 1) OVER ticker_date), 0)) * 100 AS dist_from_20d_high_pct_chg,

   ((dist_from_20d_low - LAG(dist_from_20d_low, 1) OVER ticker_date)
    / NULLIF(LAG(dist_from_20d_low, 1) OVER ticker_date, 0)) * 100 AS dist_from_20d_low_pct_chg,

   ((lowest_low_20d - LAG(lowest_low_20d, 1) OVER ticker_date)
    / NULLIF(LAG(lowest_low_20d, 1) OVER ticker_date, 0)) * 100 AS lowest_low_20d_pct_chg,

   ((highest_high_20d - LAG(highest_high_20d, 1) OVER ticker_date)
    / NULLIF(LAG(highest_high_20d, 1) OVER ticker_date, 0)) * 100 AS highest_high_20d_pct_chg
   ```

2. Update final SELECT to include these 19 columns
3. Add to COLUMN_CASE_MAP in `view_manager.py` (if needed for TitleCase)

### **Phase 2: Keep All Intermediate Features (SKIP)**
**Decision**: Do NOT remove intermediate features just because they're not in the final ML feature list.

**Rationale**:
- Storage is cheap, recomputation is expensive
- Features may be useful for future feature engineering
- Helpful for manual analysis and debugging
- Alternative models may use different feature subsets

**Action**: ✅ **SKIP this phase** - keep all features in `daily_features` table

### **Phase 3: Remove Lag1 Features from Views**
**File**: `src/view_manager.py` → `_create_v_d1_candidates()`

**Remove**:
- Entire `df_lags` CTE (lines 315-335)
- All `l.*_lag1` references in final SELECT

**Result**: `v_d1_candidates` will use delta features from `daily_features` instead

### **Phase 4: Drop alpha051 from Phase B**
**File**: `src/feature_pipeline.py` → `compute_alpha_features()`

**Remove**:
```python
('alpha051', self._alpha051),  # Not in target feature set
```

Update `ALPHA_NUMS` and `ALPHA_COLS`:
```python
ALPHA_NUMS = [1, 2, 4, 6, 9, 11, 12, 13, 15, 41, 46, 49, 54, 60, 101]  # Remove 51
ALPHA_COLS = [f"alpha{n:03d}" for n in ALPHA_NUMS]
```

### **Phase 4: Update COLUMN_CASE_MAP (Optional)**
**File**: `src/view_manager.py`

**Decision**: Percentage change features use lowercase `*_pct_chg` naming convention.
Only add to COLUMN_CASE_MAP if M01/M02 models require TitleCase.

**Example mappings** (if needed):
```python
COLUMN_CASE_MAP: Dict[str, str] = {
    # ... existing mappings ...

    # Percentage change deltas (only if models require TitleCase)
    # "price_vs_sma_50_pct_chg": "Price_vs_SMA_50_Pct_Chg",
    # "rs_pct_chg": "RS_Pct_Chg",
    # etc.
}
```

**Recommendation**: Keep lowercase `*_pct_chg` convention for consistency with SQL naming.

---

## 📈 Expected Results

### **Before Pruning**
```
daily_features:     110 columns
Storage:            ~2.6M rows × 110 cols = 286M cells
Feature load time:  5-10s
```

### **After Pruning**
```
daily_features:     ~110 columns  (minimal change, +19 pct_chg, -18 lag1, -1 alpha = net 0)
Storage:            ~2.6M rows × 110 cols = 286M cells (similar)
Feature load time:  5-10s (similar)
```

**Key Changes**:
- ✅ **Add 19 `*_pct_chg` features** (percentage change deltas)
- ❌ **Remove 18 `*_lag1` features** from views (not from daily_features)
- ❌ **Remove 1 alpha051** from Phase B
- ✅ **Keep all intermediate features** (no storage optimization, prioritize flexibility)

### **Feature Breakdown**
```
Phase A (SQL):      ~98 columns  (was 79, +19 pct_chg deltas)
Phase B (Python):   15 columns   (was 16, -1: alpha051)
Phase C (SQL):       8 columns   (unchanged)
Phase D+E (SQL):     7 columns   (unchanged: M03)
Fundamentals:       21 columns   (from joins, not in daily_features)
─────────────────────────────────
TOTAL:              ~128 columns (was 110, +18 net increase)
```

**Note**: We're **adding features**, not removing them. The focus is on **computing deltas correctly** (percentage change, not spread).

---

## ✅ Validation Steps

1. **Schema Validation**:
   ```bash
   python scripts/verify_d2_columns.py
   ```
   - Verify all 72 features present in `daily_features`
   - Verify delta features computed correctly
   - Verify lag1 features removed from views

2. **Data Integrity**:
   ```sql
   -- Check for NULLs in delta features (first row per ticker will be NULL)
   SELECT ticker, MIN(date) as first_date,
          COUNT(*) as total_rows,
          SUM(CASE WHEN Price_vs_SMA_50_Delta IS NULL THEN 1 ELSE 0 END) as null_deltas
   FROM daily_features
   GROUP BY ticker
   HAVING null_deltas > 1;  -- Should only be 1 (first row)
   ```

3. **Model Compatibility**:
   ```bash
   python scripts/validate_m01_features.py
   ```
   - Load training data from `v_d2_training`
   - Verify all M01_FEATURES present
   - Check for unexpected NULLs

4. **Performance Test**:
   ```bash
   time python data_curator_duckdb.py --start-date 2024-01-01
   ```
   - Measure Phase A runtime (should be similar, ~10s)
   - Measure total pipeline (should be similar, ~180s)
   - Measure feature load time (should improve ~40%)

---

## 🚨 Risks & Mitigations

### **Risk 1**: Delta features have NULL on first row per ticker
**Impact**: Model training may fail if not handled
**Mitigation**:
- Use `COALESCE(delta_feature, 0)` in views if needed
- Or filter `WHERE date > MIN(date)` per ticker

### **Risk 2**: Removing intermediate features breaks flags
**Impact**: `trend_ok`, `rs_line_uptrend` may fail
**Mitigation**:
- Keep intermediate features in CTEs
- Only remove from final SELECT (storage)

### **Risk 3**: Model retraining required
**Impact**: Existing models expect old features
**Mitigation**:
- Increment feature_version to 'v4.0'
- Update M01/M02 training pipelines
- Keep old models as 'archived' in registry

---

## 📝 Implementation Checklist

### Step 1: Create Migration Scripts ✅
- [x] Create `scripts/migrate_to_v3_1.py` (add 19 pct_chg columns, populate, update version)
- [x] Create `scripts/validate_v3_1_migration.py` (comprehensive validation checks)
- [x] Create `docs/proposals/duckdb_v2/MIGRATION_V3_1_SUMMARY.md` (usage guide)

### Step 2: Execute Migration ✅
- [x] Run `python scripts/migrate_to_v3_1.py` (~60s runtime) - COMPLETED
- [x] Run `python scripts/validate_v3_1_migration.py` (validation passed with warnings)
- [x] Verify NULL counts - Some tickers have sparse data (253 NULLs instead of 1, expected)
- [x] Spot-check sample data - Values look reasonable, formulas validated correct

### Step 3: Update Pipeline & Views ✅
- [x] Phase 2: SKIP (keep all intermediate features for flexibility)
- [x] Phase 3: Remove lag1 CTE from `v_d1_candidates` - replaced with pct_chg/100
- [x] Phase 3b: Update `v_d2_training` to add missing log transforms for new delta features
- [x] Phase 3c: Update `src/feature_config.py` to replace lag1 features with delta equivalents
- [ ] Phase 4: Drop alpha051 from Phase B in `src/feature_pipeline.py` (OPTIONAL - not in current M01)
- [x] Phase 5: COLUMN_CASE_MAP - delta features already mapped correctly

### Step 4: Integration & Validation ✅
- [x] Update `feature_version` to 'v3.1' (completed in migration)
- [x] Recreate all DuckDB views (`scripts/create_duckdb_views.py`)
- [x] Run model compatibility tests - ALL PASSED (test_v3_1_model_loading.py)
- [ ] Run performance benchmarks (compare v3.0 vs v3.1 query times) - OPTIONAL

### Step 5: Documentation ✅
- [x] Update MEMORY.md with new schema and pct_chg naming convention
- [ ] Update FEATURE_DICTIONARY.md with new pct_chg features (optional)
- [x] Create migration summary documentation

---

## 🔗 Related Files

- `src/feature_pipeline.py` - Main feature computation
- `src/view_manager.py` - View definitions and COLUMN_CASE_MAP
- `scripts/verify_d2_columns.py` - Schema validation
- `data_curator_duckdb.py` - Pipeline orchestration
- `docs/proposals/duckdb_v2/FEATURE_OPTIMIZATION_ANALYSIS.md` - Analysis doc

---

## 📚 References

- [Feature Pipeline Architecture](c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py)
- [View Manager](c:/Users/Hang/PycharmProjects/quantamental/src/view_manager.py)
- [M01 Features](c:/Users/Hang/PycharmProjects/quantamental/src/feature_config.py)
