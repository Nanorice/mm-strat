# DuckDB V2 Sequencing Update

**Date**: 2026-03-14
**Change**: Moved Feature Optimization (Milestone 4.5.1) → Phase 3.5.1 (before T3 backfill)

---

## Problem Identified

The original plan had this sequencing:

```
Phase 3 (T1/T2 tables)
  → Phase 4.1 (T3 backfill with 102-column schema)
  → Phase 4.5.1 (Feature optimization: reduce to 70 columns)
  → Need to re-backfill T3 with new schema (8+ hours wasted)
```

**Issue**: If we backfill 500K rows of T3 data with the full 102-column schema, then optimize features down to 70 columns, we'd need to either:
1. Re-run the 8-hour T3 backfill with the new schema (wasted time)
2. Migrate the T3 table schema (complex ALTER TABLE operations, data loss risk)
3. Keep unused columns in T3 (storage bloat, slower queries)

---

## Solution: Reorder Milestones

**New sequencing**:

```
Phase 3.0 ✅ Fundamental ratios backfill (COMPLETE)
Phase 3.1-3.3: T1/T2 implementation (9 hours)
Phase 3.5.1: Feature Optimization (3 hours) ← MOVED HERE
  ↓
Phase 4.1: T3 backfill with OPTIMIZED 70-column schema (8 hours)
Phase 4.2: FeaturePipeline refactor for T3
  ↓
Phase 4.5.1: M01 model training (renumbered from 4.5.2)
Phase 5-8: Views, orchestration, validation, cutover
```

**Benefits**:
- ✅ T3 backfill runs ONCE with final 70-column schema
- ✅ Saves 8+ hours of re-backfill time
- ✅ No schema migration complexity
- ✅ Cleaner, more efficient T3 table from day 1

---

## Feature Optimization Details

### What Gets Dropped (Phase 3.5.1)

Based on [FEATURE_OPTIMIZATION_ANALYSIS.md](FEATURE_OPTIMIZATION_ANALYSIS.md):

**1. Lag Features (5-6 columns)**:
- `rs_line_lag_delta` - redundant with `rs_line_delta`
- `sma_200_lag20` - replaced by `sma_200_slope` velocity metric
- `close_lag10`, `close_lag20` - keep as intermediate computation only (not stored)
- `delta_vol_1`, `delta_close_1` - already captured in `return_1d`, `vol_ratio`

**2. Log Transforms (29 columns from v_d2_training view)**:
- All `log_*` columns (e.g., `log_breakout_momentum`, `log_RS`, etc.)
- **Rationale**: XGBoost is scale-invariant, log transforms unnecessary for tree-based models
- **Action**: Delete from view SQL, use raw features directly

**Total reduction**: 34-35 columns dropped (102 → ~67-70 columns)

### What Gets Kept

- ✅ All base features (SMAs, ATR, RS, volume, returns, momentum)
- ✅ All 16 WQ101 alphas (alpha001-alpha101)
- ✅ All 7 cross-sectional ranks (RS_Universe_Rank, etc.)
- ✅ All fundamental ratios (market_cap, pe_ratio, ps_ratio, pb_ratio, peg_ratio)
- ✅ Velocity/acceleration metrics (actual signal, not redundant lags)

---

## Impact on Milestone 3.0 (Fundamental Ratios)

**No rework needed**! The 5 fundamental ratio columns we backfilled are:
- ✅ Base data columns (not derived lags or log transforms)
- ✅ Part of the OPTIMIZED 70-column feature set
- ✅ Used directly in M01 model (no transformations needed)

**Verification**:
```python
# Fundamental ratios are PRIMARY features
fundamental_cols = ['market_cap', 'pe_ratio', 'ps_ratio', 'pb_ratio', 'peg_ratio']

# Feature optimization drops DERIVED features
dropped_cols = [
    'rs_line_lag_delta',  # Lag of delta (derived)
    'sma_200_lag20',      # Lag of SMA (derived)
    'log_*',              # Log transform (derived)
]

# No overlap!
assert not any(f in dropped_cols for f in fundamental_cols)
```

**Conclusion**: Milestone 3.0 work is fully compatible with Phase 3.5.1 optimization.

---

## Updated Timeline

| Phase | Milestone | Time | Status |
|-------|-----------|------|--------|
| 3.0 | ✅ Fundamental ratios | 1.5h | COMPLETE |
| 3.1 | T1 Macro table | 4h | TODO |
| 3.2 | M03 migration | 3h | TODO |
| 3.3 | T2 refactor | 2h | TODO |
| **3.5.1** | **Feature optimization** | **3h** | **TODO (MOVED)** |
| 4.1 | T3 backfill (70 cols) | 12h | TODO |
| 4.2 | FeaturePipeline T3 path | 4h | TODO |
| 4.5.1 | M01 training (renumbered) | 4h | TODO |
| 5-8 | Views, orchestration, validation | 21h | TODO |

**Total remaining**: 48.5 hours + 14 days validation

---

## Implementation Plan for Phase 3.5.1

**Estimated Time**: 3 hours

### Task 1: Update feature_pipeline.py (1 hour)

**File**: `src/feature_pipeline.py`

**Changes**:
1. **Phase A SQL** (lines ~173-175):
   ```sql
   -- REMOVE these lag columns:
   -- LAG(rs_line_delta, 1) OVER (PARTITION BY ticker ORDER BY date) as rs_line_lag_delta,
   -- LAG(sma_200, 20) OVER (PARTITION BY ticker ORDER BY date) as sma_200_lag20,
   ```

2. **Phase B Python** (lines ~351-354):
   ```python
   # REMOVE lag storage (keep computation for alphas):
   # df['delta_close_1'] = df.groupby('ticker')['close'].diff(1)  # Already in return_1d
   # df['delta_vol_1'] = df.groupby('ticker')['volume'].diff(1)   # Already in vol_ratio
   # df['close_lag10'] = df.groupby('ticker')['close'].shift(10)  # Only for alpha computation
   # df['close_lag20'] = df.groupby('ticker')['close'].shift(20)  # Only for alpha computation
   ```

3. **Keep lags as LOCAL variables in alpha functions** (don't add to `daily_features` output)

### Task 2: Update view_manager.py (1 hour)

**File**: `src/view_manager.py`

**Changes**:
1. Find `_create_v_d2_training()` method (lines ~628-682)
2. **DELETE all 29 log transform columns**:
   ```sql
   -- DELETE lines like:
   -- SIGN(f.breakout_momentum) * LN(1.0 + ABS(f.breakout_momentum)) AS log_breakout_momentum,
   -- SIGN(f.rs) * LN(1.0 + ABS(f.rs)) AS log_RS,
   -- ... (27 more)
   ```
3. **Use raw features directly** (XGBoost doesn't need log scaling)

### Task 3: Document & Validate (1 hour)

**Create**: `docs/proposals/duckdb_v2/feature_selection_report.md`

**Contents**:
- List of 34-35 dropped features with rationale
- List of 67-70 retained features
- Validation test results

**Validation script**:
```python
# scripts/validate_feature_optimization.py
import duckdb
import pandas as pd

conn = duckdb.connect('data/market_data.duckdb')

# Test 1: Verify schema reduction
df = conn.execute("SELECT * FROM v_d2_training LIMIT 1").df()
assert df.shape[1] <= 75, f"Too many columns: {df.shape[1]}"

# Test 2: Verify no lag columns
lag_cols = [c for c in df.columns if 'lag' in c.lower()]
assert len(lag_cols) == 0, f"Lag columns present: {lag_cols}"

# Test 3: Verify no log transforms
log_cols = [c for c in df.columns if c.startswith('log_')]
assert len(log_cols) == 0, f"Log columns present: {log_cols}"

# Test 4: Verify fundamental ratios still present
required = ['pe_ratio', 'ps_ratio', 'pb_ratio', 'market_cap']
for col in required:
    assert col in df.columns, f"Missing fundamental: {col}"

print(f"✅ Validation passed: {df.shape[1]} columns (target: ≤75)")
conn.close()
```

---

## Acceptance Criteria

- [ ] `feature_pipeline.py` Phase A removes 5-6 lag columns
- [ ] `feature_pipeline.py` Phase B removes delta/lag storage
- [ ] `view_manager.py` v_d2_training removes 29 log transforms
- [ ] `feature_selection_report.md` documents all changes
- [ ] Validation script confirms ≤75 columns, no lags, no log transforms
- [ ] Pipeline smoke test: Run on 10 test tickers, verify schema

---

## References

- **Technical Analysis**: [FEATURE_OPTIMIZATION_ANALYSIS.md](FEATURE_OPTIMIZATION_ANALYSIS.md)
- **Main Plan**: [logical-hatching-dewdrop.md](logical-hatching-dewdrop.md)
- **Milestone 3.0 Completion**: [milestone_3_0_completion.md](milestone_3_0_completion.md)

---

## Next Steps

**Immediate**:
1. Complete Phase 3.1-3.3 (T1/T2 tables) - 9 hours
2. Execute Phase 3.5.1 (Feature Optimization) - 3 hours
3. Proceed to Phase 4.1 (T3 backfill with optimized schema) - 12 hours

**Long-term**:
- Phase 4.5.1: Train M01 on optimized 70-column feature set
- Phase 6.5: Backtest with probability-based entry/exit rules
- Phase 8: Parallel validation and production cutover
