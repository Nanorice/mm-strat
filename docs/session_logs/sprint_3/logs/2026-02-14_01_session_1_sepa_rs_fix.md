# Session Handover: 2026-02-14 - SEPA RS Filter Fix Implementation

## 🎯 Goal
Implement the SEPA RS filter logic fix to use price/benchmark ratio (RS Line) instead of momentum-based RS for C9 filter, and drop redundant C12 check.

## ✅ Accomplished

### Core Implementation
- ✅ **Updated [src/indicators.py](../../src/indicators.py:118-145)**: Added `price_vs_spy`, `price_vs_spy_ma63`, and `rs_line_uptrend` calculations to `add_relative_strength()` method
- ✅ **Updated [src/vectorized_screening.py](../../src/vectorized_screening.py:85-135)**:
  - C9 now uses `price_vs_spy > price_vs_spy_ma63` (RS Line uptrend) instead of `rs_rating > 0`
  - Dropped C12 (redundant RS momentum check) from trigger logic
  - Trigger now uses only C10 (breakout) & C11 (volume)
- ✅ **Updated [src/features.py](../../src/features.py:52-66)**: Added new RS features to `lightweight_features` list

### Verification
- ✅ **Created [scripts/verify_sepa_rs_fix.py](../../scripts/verify_sepa_rs_fix.py)**: Comprehensive test suite with 3 test cases
  - Test 1: price_vs_spy calculation correctness
  - Test 2: SEPA screening uses new RS logic for C9
  - Test 3: C12 dropped from trigger logic
- ✅ **All tests passed** (3/3) - Implementation verified correct

## 📝 Files Changed

### Production Code
- `src/indicators.py` (lines 118-145): Added price_vs_spy metric suite (Close/SPY, MA63, uptrend flag)
- `src/vectorized_screening.py` (lines 85-135): Updated SEPA screening logic to use price_vs_spy for C9, dropped C12
- `src/features.py` (lines 52-66): Added `price_vs_spy`, `price_vs_spy_ma63`, `rs_line_uptrend` to lightweight features

### Testing
- `scripts/verify_sepa_rs_fix.py` (NEW): Verification test suite - all tests passing

## 🚧 Work in Progress (CRITICAL)

### 🔴 IMPORTANT: Changes Will Affect D1 Generation
**The SEPA RS fix is now ACTIVE in the pipeline:**
- When regenerating D1 via `python model_runner.py data --steps scan`, it will use the NEW logic
- This means different stocks may be selected compared to current D1
- **Recommendation**: Test on a narrow date range first before full regeneration

### ⚠️ Incomplete Work
1. **DuckDB `daily_features` Table NOT Updated**:
   - New RS features (`price_vs_spy`, `price_vs_spy_ma63`, `rs_line_uptrend`) are NOT yet in DuckDB schema
   - See [docs/sepa_rs_fix_implementation_plan.md](../sepa_rs_fix_implementation_plan.md) Task 2 for implementation steps

2. **FeatureEngineer Integration Incomplete**:
   - New features added to `lightweight_features` list
   - BUT `calculate_lightweight_features()` method does NOT automatically generate them
   - Features are only calculated when `add_relative_strength()` is called with benchmark data
   - This means D2 dataset may NOT include these features unless enrichment pipeline is updated

## ⏭️ Next Steps

### Priority 1: Finalize DuckDB `daily_features` Schema (Task 2)
**Reference**: [docs/sepa_rs_fix_implementation_plan.md](../sepa_rs_fix_implementation_plan.md) lines 337-786

1. **Update `daily_features` table schema** ([scripts/migrate_to_duckdb.py](../../scripts/migrate_to_duckdb.py:78-95)):
   ```sql
   ALTER TABLE daily_features ADD COLUMN price_vs_spy DOUBLE;
   ALTER TABLE daily_features ADD COLUMN price_vs_spy_ma63 DOUBLE;
   ALTER TABLE daily_features ADD COLUMN rs_line_uptrend BOOLEAN;
   ```

2. **Update SQL computation** ([data_curator_duckdb.py](../../data_curator_duckdb.py:628-677)):
   - Add SPY join in `_compute_features_incremental()`
   - Add `price_vs_spy = p.close / NULLIF(s.spy_close, 0)`
   - Add `price_vs_spy_ma63 = AVG(price_vs_spy) OVER w63`
   - Add `rs_line_uptrend = price_vs_spy > price_vs_spy_ma63`

3. **Create migration script** (`scripts/migrate_daily_features_v2.py`):
   - Backup existing table
   - Add new columns
   - Recompute features incrementally

4. **Validate**: Compare SQL vs Python calculations for consistency (<0.1% difference)

### Priority 2: Update FeatureEngineer for D2 Dataset

**Goal**: Ensure D2 dataset includes new RS features for ML model training

1. **Update `FeatureEngineer.calculate_lightweight_features()`** ([src/features.py](../../src/features.py:67-248)):
   ```python
   def calculate_lightweight_features(self, df: pd.DataFrame) -> pd.DataFrame:
       # ... existing code ...

       # NEW: Ensure RS features are calculated
       if self.benchmark_data is not None:
           df = TechnicalAnalysis.add_relative_strength(
               df,
               self.benchmark_data
           )

       return df
   ```

2. **Verify D2 generation** includes new features:
   ```bash
   # Test on small date range
   python model_runner.py data --steps scan features --start 2023-01-01 --end 2023-01-31

   # Check D2 schema
   python -c "import pandas as pd; d2 = pd.read_parquet('data/ml/d2.parquet'); print(d2.columns)"
   # Should include: price_vs_spy, price_vs_spy_ma63, rs_line_uptrend
   ```

3. **Update feature selection pipeline** to include new features in candidate pool

### Priority 3: Validation & Testing

1. **Compare old vs new D1**:
   - Generate D1 with old logic (stash changes)
   - Generate D1 with new logic (apply changes)
   - Compare: # trades, tickers selected, win rates, entry timing

2. **Backtest comparison**:
   - Run backtest with old SEPA logic
   - Run backtest with new SEPA logic
   - Compare: CAGR, Sharpe, max drawdown, # trades

3. **Feature importance analysis**:
   - After D2 includes new RS features, run feature selection
   - Check if `price_vs_spy` / `price_vs_spy_ma63` show predictive power

## 💡 Context/Memory

### Key Implementation Decisions

1. **MA Period: 63 days (not 20)**
   - User specified MA63 instead of MA20 from original plan
   - Rationale: Aligns with existing `rs_rating` calculation period
   - Config: `price_vs_spy_ma63` (not `price_vs_spy_ma20`)

2. **C12 Dropped Completely**
   - Original plan suggested making it "redundant with C9"
   - Implementation: Removed C12 entirely from trigger logic
   - Result: Trigger = C10 & C11 only (more permissive)

3. **Backward Compatibility Maintained**
   - Return signature: `(trend_ok, trigger_ok)` unchanged
   - Fallback logic: If new features missing, uses old `rs_rating > 0`
   - Legacy features kept: `RS`, `RS_MA` still calculated

4. **SEPA Structure Clarified**
   - **Trend**: C1-C9 (includes new RS filter)
   - **Trigger**: C10-C11 (C12 removed)
   - **Full SEPA**: `trend_ok & trigger_ok`

### Architectural Insights

1. **Data Flow for D1 Generation**:
   ```
   model_runner.py data --steps scan
     └─> DataPipeline.scan()
         └─> FastTradeSimulator(strategy=SEPAStrategy)
             └─> SEPAStrategy.generate_signals()
                 └─> VectorizedSEPAScreener.batch_screen_universe()
                     └─> screen_single_ticker_split() ← CHANGES APPLIED HERE
   ```
   - All changes are already integrated into production pipeline
   - No additional wiring needed for D1 generation

2. **Feature Calculation Dual Path**:
   - **Path 1 (Python)**: `TechnicalAnalysis.add_relative_strength()` → Used by D1/D2 pipeline
   - **Path 2 (SQL)**: `_compute_features_incremental()` → Used by DuckDB daily scanner
   - **Challenge**: Must keep both implementations in sync

3. **Testing Strategy for Windows Console**:
   - Emoji encoding issues on Windows (cp1252 codec)
   - Solution: Use `[PASS]`/`[FAIL]` instead of ✅/❌
   - Lesson: Always test console output on target platform

### Related Documentation

- **Implementation Plan**: [docs/sepa_rs_fix_implementation_plan.md](../sepa_rs_fix_implementation_plan.md)
- **Feature Gap Analysis**: [docs/feature_gap_analysis.md](../feature_gap_analysis.md)
- **Feature Calculation Comparison**: [docs/feature_calculation_comparison.md](../feature_calculation_comparison.md)

### Performance Considerations

- `price_vs_spy` calculation is cheap (simple division)
- MA63 calculation requires 63-day window (same as existing `rs_rating`)
- No performance degradation expected from this change
- Vectorized operations maintained throughout

---

**Session Duration**: ~1.5 hours
**Tests Passed**: 3/3 ✓
**Files Modified**: 4
**Next Session Focus**: DuckDB schema update & D2 feature enrichment
