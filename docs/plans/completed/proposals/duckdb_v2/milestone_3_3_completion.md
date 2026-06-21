# Milestone 3.3 Completion Report: T2 Screener Features for Full Universe

**Completion Date**: 2026-03-14
**Runtime**: 0.5 hours (vs 2 hours estimated - **75% faster**)
**Status**: ✅ COMPLETE

---

## Summary

Successfully created `t2_screener_features` table with 37 lightweight screening columns for the full universe (1,826 tickers). This table serves as the foundation for lazy T3 materialization by pre-computing SEPA C1-C11 criteria in SQL, enabling sub-second candidate identification.

---

## Deliverables

### 1. New Method: `FeaturePipeline.compute_t2_screener_features()`

**File**: [src/feature_pipeline.py](../../src/feature_pipeline.py) (+250 lines)

**Implementation**:
- Lightweight SQL computation (no alphas, no cross-sectional ranks)
- 37 columns: 30 features + 7 metadata
- Full universe coverage (all tickers in `price_data`)
- Includes SEPA composite flags (`trend_ok`, `breakout_ok`)
- Uses `INSERT OR REPLACE` for idempotent updates

**Features Computed**:
- **Moving Averages**: SMA_20, SMA_50, SMA_150, SMA_200, SMA_200_lag20
- **Relative Strength**: RS_rating, RS, RS_ma, RS_line_log, RS_line_delta, RS_line_uptrend
- **52-Week Metrics**: high_52w, low_52w, dist_from_52w_high, dist_from_52w_low, pct_from_high_52w
- **20-Day Metrics**: high_20d, lowest_low_20d, dist_from_20d_high, dist_from_20d_low
- **Volume**: vol_avg_20, vol_avg_50, vol_ratio, dry_up_volume
- **Volatility**: atr_20d, natr, volatility_20d
- **VCP Pattern**: vcp_ratio, consolidation_width
- **SEPA Flags**: trend_ok (C1-C9), breakout_ok (C10-C11), close_above_sma200

---

## Results

### Table Statistics
```
Total rows:              2,590,193
Total tickers:           1,826
Date range:              2020-01-02 to 2026-02-18
Avg rows per ticker:     1,419
Total columns:           38 (37 features + primary key)
```

### Performance
```
Full backfill time:      7.91s
Speed:                   4.3ms/ticker
Rows/second:             327,000
Target (<30s):           ✅ PASS (26% of target)
```

### SEPA Screening (Latest Date: 2026-02-18)
```
Total tickers:           1,822
Trend OK (C1-C9):        569 (31.2%)
Breakout OK (C10-C11):   59 (3.2%)
Full SEPA signals:       26 (1.4%)
```

### Data Quality
```
NULL rates:
  - sma_50:              0.0% (100% coverage)
  - rs_rating:           19.15% (80.85% coverage - expected due to 252d lookback)
  - atr_20d:             0.0% (100% coverage)
```

---

## Acceptance Criteria

| Criterion | Target | Actual | Status |
|-----------|--------|--------|--------|
| Full universe coverage | All tickers in `price_data` | 1,826 tickers | ✅ PASS |
| Column count | 30+ screening features | 37 columns | ✅ PASS |
| Compute time | <30 seconds | 7.91s (26% of target) | ✅ PASS |
| SEPA flag accuracy | Matches v_d1_candidates logic | Validated (26 signals match) | ✅ PASS |

---

## Indexes Created

```sql
CREATE INDEX idx_t2_screener_ticker ON t2_screener_features(ticker);
CREATE INDEX idx_t2_screener_date ON t2_screener_features(date);
CREATE INDEX idx_t2_screener_rs ON t2_screener_features(rs_rating);
CREATE INDEX idx_t2_screener_trend_ok ON t2_screener_features(trend_ok);
```

**Query Performance** (SELECT WHERE trend_ok=TRUE ORDER BY rs_rating):
- Time: 359.7ms for latest date
- Rows: 569 candidates

---

## Integration

### Updated Pipeline Flow
```python
# Before (Milestone 3.2):
compute_all():
    compute_base_features()        # daily_features (full rebuild)
    compute_alpha_features()       # Phase B
    compute_cross_sectional_ranks() # Phase C
    compute_m03_features()         # Phase D
    compute_m03_derived()          # Phase E

# After (Milestone 3.3):
compute_all():
    compute_t2_screener_features() # T2 (lightweight, full universe) ← NEW
    compute_base_features()        # daily_features (still full rebuild for now)
    compute_alpha_features()       # Phase B
    compute_cross_sectional_ranks() # Phase C
    compute_m03_features()         # Phase D
    compute_m03_derived()          # Phase E
```

**Note**: `daily_features` is still being populated for backward compatibility. It will be deprecated in Phase 4 when T3 append-only implementation is complete.

---

## Next Steps (Milestone 3.5.1)

**Feature Optimization** (3 hours, CRITICAL PATH):
- Remove lag features (5-6 cols) from `daily_features` schema
- Remove log transforms (29 cols) from `v_d2_training` view
- Reduce feature set from 102 → ~70 columns (30% reduction)
- **Rationale**: Must finalize schema BEFORE T3 backfill (8-hour runtime) to avoid re-backfilling 500K rows

**Impact**:
- ✅ T3 backfill will use optimized 70-column schema from day 1
- ✅ Daily compute time reduced (~30% fewer columns)
- ✅ Eliminates multicollinearity (better model stability)
- ✅ Aligns with XGBoost best practices (no unnecessary log transforms)

---

## Technical Notes

### DuckDB Optimizations
- Used named window definitions to avoid redundant computation
- CTEs partition work into logical stages (price_base → core_features → derived_features → final_features)
- `INSERT OR REPLACE` ensures idempotency

### SEPA Composite Flags
The `trend_ok` flag encodes SEPA C1-C9 criteria in SQL:
```sql
COALESCE(
    close > sma_150 AND close > sma_200
    AND sma_150 > sma_200 AND sma_200 > sma_200_lag20
    AND sma_50 > sma_150 AND close > sma_50
    AND close > low_52w * 1.3
    AND close > high_52w * 0.85
    AND price_vs_spy > price_vs_spy_ma63,
    FALSE
) AS trend_ok
```

This enables single SQL query to identify SEPA candidates:
```sql
SELECT ticker FROM t2_screener_features
WHERE date = '2026-02-18' AND trend_ok = TRUE
-- 569 rows in 360ms (vs ~10s Python loop in old scanner)
```

---

## Completion Checklist

- [x] `compute_t2_screener_features()` method implemented
- [x] Table schema matches proposal (37 columns)
- [x] Full backfill from 2020-01-01 (2.59M rows)
- [x] Indexes created for fast SEPA queries
- [x] Integrated into `compute_all()` pipeline
- [x] Performance validated (<30s target, actual: 7.91s)
- [x] SEPA flags validated (26 signals match expected)
- [x] Proposal document updated

---

## Time Accounting

| Metric | Value |
|--------|-------|
| Estimated time | 2 hours |
| Actual time | 0.5 hours |
| Time saved | **1.5 hours (75% faster)** |
| Cumulative savings | 6.0 hours (across Milestones 3.1, 3.2, 3.3) |

**Reason for speedup**: Reused existing Phase A SQL logic from `daily_features`, only needed to extract subset of columns and add indexes.

---

**Report Generated**: 2026-03-14
**Author**: Claude Sonnet 4.5
**Session**: DuckDB V2 Infrastructure Implementation (Phase 3)
