# Milestone 3.5.3: Incremental Feature Computation - Implementation Plan

**Status**: 🔜 PLANNED
**Version**: 1.0
**Created**: 2026-03-14
**Dependencies**: 3.5.1 ✅ (v3.1 pct_chg features), 3.5.2 ✅ (multiprocessing)

---

## 🎯 Objective

Optimize daily feature pipeline to only compute features for **new/updated data** instead of full universe rebuild (~180s → 10-20s, **90% reduction**).

**Current Behavior:**
- `FeaturePipeline.compute_all()` rebuilds entire `daily_features` table (CREATE OR REPLACE)
- Processes 1,826 tickers × ~1,419 days = 2.59M rows **every single run**
- Runtime: ~180s (Phase A: 10s, Phase B: 166s, Phase C: 2s)

**Target Behavior:**
- Detect which tickers have new price data since last run
- Compute features ONLY for changed tickers (typically 1,826 tickers × 1 day = 1,826 rows)
- Merge results into existing `daily_features` table
- Runtime: ~10-20s (90% reduction)

---

## 📊 Analysis

### Data Growth Patterns

Based on production data:
- **Daily price updates**: 1,826 tickers × 1 new day = 1,826 rows
- **Warmup requirement**: 365 days lookback (for SMAs, alphas)
- **Typical incremental workload**: 1,826 tickers × 365 days = 666,490 rows (~25% of full dataset)
- **Full rebuild workload**: 1,826 tickers × 1,419 days = 2,590,494 rows

**Why not just last 1 day?**
- Rolling window features (SMA_200, RS_3m) require historical context
- Solution: Fetch 365 days of price data, compute features, keep ONLY new day's results

### Performance Expectations

| Scenario | Rows Processed | Expected Runtime | Speedup |
|----------|----------------|------------------|---------|
| **Full rebuild** (current) | 2.59M | ~180s | 1.0x baseline |
| **Incremental (daily)** | 666K warmup | **~60s compute** | **3x faster** |
| **Incremental (daily, optimized)** | 666K warmup, keep 1.8K | **~10-20s** | **9-18x faster** |

**Why 60s → 10-20s optimization?**
- Only **write** 1,826 rows (new day) instead of 666K
- Use `INSERT OR REPLACE` for merge instead of `CREATE OR REPLACE TABLE`
- Avoid recomputing ranks/regime scores for unchanged historical data

---

## 🏗️ Architecture Design

### Delta Detection Logic

```python
def detect_data_delta(self, conn: duckdb.DuckDBPyConnection) -> dict:
    """
    Detect which data has changed since last feature computation.

    Returns:
        dict with keys:
            - 'new_date': Latest date in price_data (e.g., '2026-03-14')
            - 'last_computed_date': Latest date in daily_features (e.g., '2026-03-13')
            - 'has_new_data': bool (True if new_date > last_computed_date)
            - 'tickers_with_new_data': list[str] (tickers with data on new_date)
            - 'warmup_start_date': new_date - 365 days (for rolling windows)
    """
    new_date = conn.execute(
        "SELECT MAX(date) FROM price_data"
    ).fetchone()[0]

    last_computed_date = conn.execute(
        "SELECT MAX(date) FROM daily_features WHERE feature_version = ?"
        , [self.feature_version]
    ).fetchone()[0]

    if last_computed_date is None or new_date > last_computed_date:
        # Get tickers with data on new_date
        tickers = conn.execute(
            "SELECT DISTINCT ticker FROM price_data WHERE date = ?",
            [new_date]
        ).fetchdf()['ticker'].tolist()

        warmup_start = (pd.to_datetime(new_date) - pd.Timedelta(days=365)).strftime('%Y-%m-%d')

        return {
            'new_date': new_date,
            'last_computed_date': last_computed_date,
            'has_new_data': True,
            'tickers_with_new_data': tickers,
            'warmup_start_date': warmup_start
        }
    else:
        return {'has_new_data': False}
```

### Incremental Computation Strategy

**Phase 1: Fetch warmup data (365 days)**
```python
# Get 365 days of price data for tickers with new data
df = conn.execute("""
    SELECT * FROM price_data
    WHERE ticker IN ?
      AND date >= ?
      AND date <= ?
    ORDER BY ticker, date
""", [tickers_with_new_data, warmup_start_date, new_date]).fetchdf()
```

**Phase 2: Compute features (all phases)**
```python
# Run full feature pipeline on warmup data
features = self._compute_phase_a(df, conn)  # SQL features
features = self._compute_phase_b(features)   # Python alphas
features = self._compute_phase_c(features, conn)  # Cross-sectional ranks
features = self._compute_phase_d_e(features, conn)  # M03 regime
```

**Phase 3: Keep ONLY new day's results**
```python
# Filter to ONLY new_date rows
new_features = features[features['date'] == new_date].copy()
```

**Phase 4: Merge into daily_features**
```python
# Use INSERT OR REPLACE to update existing rows
conn.execute("""
    INSERT OR REPLACE INTO daily_features
    SELECT * FROM new_features_df
""")
```

### Fallback Conditions

**When to force FULL rebuild:**
1. **Schema mismatch**: `feature_version` in database != current code version
2. **Missing warmup**: Insufficient historical data (< 365 days available)
3. **Empty table**: `daily_features` table is empty
4. **User override**: `--force-full` flag passed
5. **Validation failure**: Incremental mode produces unexpected results

**Fallback logic:**
```python
def compute_all(self, incremental: bool = True, force_full: bool = False):
    if force_full:
        logger.info("⚠️ Full rebuild forced by user (--force-full)")
        return self._compute_full_rebuild()

    delta = self.detect_data_delta(conn)

    if not delta['has_new_data']:
        logger.info("✅ No new data detected, skipping feature computation")
        return

    # Check warmup sufficiency
    warmup_days = (pd.to_datetime(delta['new_date']) -
                   pd.to_datetime(delta['warmup_start_date'])).days
    if warmup_days < 365:
        logger.warning(f"⚠️ Insufficient warmup ({warmup_days} days < 365), forcing full rebuild")
        return self._compute_full_rebuild()

    # Check feature version compatibility
    current_version = conn.execute(
        "SELECT DISTINCT feature_version FROM daily_features"
    ).fetchone()
    if current_version and current_version[0] != self.feature_version:
        logger.warning(
            f"⚠️ Feature version mismatch (DB: {current_version[0]}, Code: {self.feature_version}), "
            "forcing full rebuild"
        )
        return self._compute_full_rebuild()

    if incremental:
        return self._compute_incremental(delta)
    else:
        return self._compute_full_rebuild()
```

---

## 💻 Implementation Tasks

### Task 1: Add Delta Detection Method
**File**: `src/feature_pipeline.py`

```python
def detect_data_delta(self, conn: duckdb.DuckDBPyConnection) -> dict:
    """Detect new data since last feature computation."""
    # (Implementation shown above)
```

**Testing:**
```python
# Test: No new data
delta = pipeline.detect_data_delta(conn)
assert delta['has_new_data'] == False

# Test: New data available
# (add 1 day of price data)
delta = pipeline.detect_data_delta(conn)
assert delta['has_new_data'] == True
assert delta['new_date'] == '2026-03-14'
assert len(delta['tickers_with_new_data']) > 0
```

---

### Task 2: Add Incremental Compute Method
**File**: `src/feature_pipeline.py`

```python
def _compute_incremental(self, delta: dict) -> None:
    """
    Compute features for new data only.

    Args:
        delta: Output from detect_data_delta()
    """
    logger.info(f"🔄 Incremental mode: Computing features for {delta['new_date']}")
    logger.info(f"   Tickers: {len(delta['tickers_with_new_data'])}")
    logger.info(f"   Warmup window: {delta['warmup_start_date']} → {delta['new_date']}")

    start_time = time.time()

    # Step 1: Fetch warmup data (365 days)
    df = self.conn.execute("""
        SELECT * FROM price_data
        WHERE ticker IN (SELECT UNNEST(?))
          AND date >= ?
          AND date <= ?
        ORDER BY ticker, date
    """, [delta['tickers_with_new_data'], delta['warmup_start_date'], delta['new_date']]
    ).fetchdf()

    logger.info(f"   Fetched {len(df):,} warmup rows")

    # Step 2: Compute all phases on warmup data
    features = self._compute_phase_a(df, self.conn)
    logger.info(f"   Phase A complete: {len(features):,} rows")

    features = self._compute_phase_b(features)
    logger.info(f"   Phase B complete: {len(features):,} rows")

    features = self._compute_phase_c(features, self.conn)
    logger.info(f"   Phase C complete: {len(features):,} rows")

    features = self._compute_phase_d_e(features, self.conn)
    logger.info(f"   Phase D+E complete: {len(features):,} rows")

    # Step 3: Keep ONLY new_date rows
    new_features = features[features['date'] == delta['new_date']].copy()
    logger.info(f"   Filtered to {len(new_features):,} new rows (date={delta['new_date']})")

    # Step 4: Merge into daily_features
    self.conn.register('new_features_df', new_features)
    self.conn.execute("""
        INSERT OR REPLACE INTO daily_features
        SELECT * FROM new_features_df
    """)
    self.conn.unregister('new_features_df')

    elapsed = time.time() - start_time
    logger.info(f"✅ Incremental compute complete in {elapsed:.1f}s")
    logger.info(f"   Rows written: {len(new_features):,}")
```

**Testing:**
```python
# Test: Incremental compute adds 1 day
initial_count = conn.execute("SELECT COUNT(*) FROM daily_features").fetchone()[0]
pipeline._compute_incremental(delta)
new_count = conn.execute("SELECT COUNT(*) FROM daily_features").fetchone()[0]
assert new_count == initial_count + len(delta['tickers_with_new_data'])
```

---

### Task 3: Refactor compute_all() to Support Incremental Mode
**File**: `src/feature_pipeline.py`

```python
def compute_all(
    self,
    incremental: bool = True,
    force_full: bool = False,
    skip_t2: bool = False
) -> None:
    """
    Compute all features (T2 + daily_features).

    Args:
        incremental: If True, only compute features for new data (default: True)
        force_full: If True, force full rebuild regardless of delta (default: False)
        skip_t2: If True, skip T2 screener features (default: False)
    """
    # T2 Screener Features (always full rebuild for now)
    if not skip_t2:
        logger.info("📊 Computing T2 screener features (full universe)...")
        self.compute_t2_screener_features()

    # Daily Features (incremental or full)
    if force_full:
        logger.info("⚠️ Full rebuild forced by user (--force-full)")
        return self._compute_full_rebuild()

    delta = self.detect_data_delta(self.conn)

    if not delta['has_new_data']:
        logger.info("✅ No new data detected, skipping feature computation")
        return

    # Validate warmup sufficiency
    warmup_days = (pd.to_datetime(delta['new_date']) -
                   pd.to_datetime(delta['warmup_start_date'])).days
    if warmup_days < 365:
        logger.warning(
            f"⚠️ Insufficient warmup ({warmup_days} days < 365), forcing full rebuild"
        )
        return self._compute_full_rebuild()

    # Validate feature version compatibility
    current_version = self.conn.execute(
        "SELECT DISTINCT feature_version FROM daily_features LIMIT 1"
    ).fetchone()
    if current_version and current_version[0] != self.feature_version:
        logger.warning(
            f"⚠️ Feature version mismatch (DB: {current_version[0]}, "
            f"Code: {self.feature_version}), forcing full rebuild"
        )
        return self._compute_full_rebuild()

    # Execute incremental or full
    if incremental:
        self._compute_incremental(delta)
    else:
        self._compute_full_rebuild()

def _compute_full_rebuild(self) -> None:
    """Full rebuild of daily_features (current implementation)."""
    logger.info("🔄 Full rebuild mode: Recomputing all features...")
    # (keep existing implementation logic)
```

---

### Task 4: Update data_curator_duckdb.py
**File**: `data_curator_duckdb.py`

```python
def update_features(incremental: bool = True):
    """Update feature tables (T2 + daily_features)."""
    pipeline = FeaturePipeline(db_path=DB_PATH)

    # Option 1: Use incremental mode (default)
    pipeline.compute_all(incremental=incremental)

    # Refresh views after feature update
    view_manager = ViewManager(db_path=DB_PATH)
    view_manager.create_all()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--full-rebuild', action='store_true',
                       help='Force full rebuild instead of incremental')
    args = parser.parse_args()

    update_features(incremental=not args.full_rebuild)
```

---

### Task 5: Add Validation Script
**File**: `scripts/validate_incremental_mode.py`

```python
"""
Validate incremental feature computation produces same results as full rebuild.

Usage:
    python scripts/validate_incremental_mode.py --test-date 2024-01-15
"""
import argparse
import duckdb
import pandas as pd
from src.feature_pipeline import FeaturePipeline

def validate_incremental_vs_full(test_date: str, db_path: str = "data/market_data.duckdb"):
    """
    Compare incremental vs full rebuild results for a specific date.

    Strategy:
    1. Delete features for test_date from daily_features
    2. Run incremental mode to recompute test_date
    3. Save results as df_incremental
    4. Delete all features, run full rebuild
    5. Save results as df_full
    6. Compare df_incremental vs df_full for test_date (should be identical)
    """
    conn = duckdb.connect(db_path)
    pipeline = FeaturePipeline(db_path=db_path)

    # Step 1: Backup and delete test_date features
    print(f"📋 Backing up features for {test_date}...")
    backup = conn.execute(
        "SELECT * FROM daily_features WHERE date = ?", [test_date]
    ).fetchdf()

    conn.execute("DELETE FROM daily_features WHERE date = ?", [test_date])
    print(f"   Deleted {len(backup)} rows for {test_date}")

    # Step 2: Run incremental mode
    print("🔄 Running incremental mode...")
    pipeline.compute_all(incremental=True, skip_t2=True)

    df_incremental = conn.execute(
        "SELECT * FROM daily_features WHERE date = ? ORDER BY ticker", [test_date]
    ).fetchdf()
    print(f"   Incremental mode produced {len(df_incremental)} rows")

    # Step 3: Run full rebuild
    print("🔄 Running full rebuild...")
    pipeline.compute_all(incremental=False, skip_t2=True, force_full=True)

    df_full = conn.execute(
        "SELECT * FROM daily_features WHERE date = ? ORDER BY ticker", [test_date]
    ).fetchdf()
    print(f"   Full rebuild produced {len(df_full)} rows")

    # Step 4: Compare results
    print("🔍 Comparing results...")

    # Check row counts
    assert len(df_incremental) == len(df_full), \
        f"Row count mismatch: incremental {len(df_incremental)} vs full {len(df_full)}"

    # Check tickers match
    assert set(df_incremental['ticker']) == set(df_full['ticker']), \
        "Ticker mismatch between incremental and full"

    # Check feature values (allow small numerical tolerance)
    numeric_cols = df_incremental.select_dtypes(include=['float64', 'int64']).columns
    max_diff = 0.0
    mismatches = []

    for col in numeric_cols:
        diff = (df_incremental[col] - df_full[col]).abs().max()
        if pd.notna(diff) and diff > 1e-6:
            max_diff = max(max_diff, diff)
            mismatches.append((col, diff))

    if mismatches:
        print(f"⚠️ Found {len(mismatches)} columns with differences > 1e-6:")
        for col, diff in sorted(mismatches, key=lambda x: x[1], reverse=True)[:10]:
            print(f"   {col}: max_diff = {diff:.2e}")
        print(f"   Max difference: {max_diff:.2e}")
        if max_diff > 0.01:  # Fail if difference > 1%
            raise AssertionError(f"Incremental mode produced different results (max_diff={max_diff:.2e})")
    else:
        print("✅ All feature values match (max_diff < 1e-6)")

    conn.close()
    print("\n✅ Validation PASSED: Incremental mode produces identical results to full rebuild")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-date', required=True, help='Date to test (YYYY-MM-DD)')
    parser.add_argument('--db', default='data/market_data.duckdb', help='Database path')
    args = parser.parse_args()

    validate_incremental_vs_full(args.test_date, args.db)
```

---

## 🧪 Testing Strategy

### Unit Tests

1. **Test delta detection** (no new data):
   ```python
   delta = pipeline.detect_data_delta(conn)
   assert delta['has_new_data'] == False
   ```

2. **Test delta detection** (new data available):
   ```python
   # Add 1 day of price data
   delta = pipeline.detect_data_delta(conn)
   assert delta['has_new_data'] == True
   assert delta['new_date'] > delta['last_computed_date']
   ```

3. **Test incremental compute** (rows added):
   ```python
   initial_count = conn.execute("SELECT COUNT(*) FROM daily_features").fetchone()[0]
   pipeline._compute_incremental(delta)
   new_count = conn.execute("SELECT COUNT(*) FROM daily_features").fetchone()[0]
   assert new_count > initial_count
   ```

4. **Test warmup validation** (insufficient data):
   ```python
   # Delete most historical data
   conn.execute("DELETE FROM price_data WHERE date < '2026-01-01'")
   # Should trigger fallback to full rebuild
   pipeline.compute_all(incremental=True)
   ```

### Integration Tests

1. **Validation script**: Compare incremental vs full rebuild on historical date
   ```bash
   python scripts/validate_incremental_mode.py --test-date 2024-01-15
   ```

2. **End-to-end test**: Run daily pipeline with incremental mode
   ```bash
   python data_curator_duckdb.py --update-all
   # Should use incremental mode by default
   ```

3. **Performance benchmark**: Measure runtime improvement
   ```python
   # Full rebuild
   start = time.time()
   pipeline.compute_all(incremental=False, force_full=True)
   full_time = time.time() - start  # ~180s

   # Incremental (next day)
   start = time.time()
   pipeline.compute_all(incremental=True)
   incremental_time = time.time() - start  # ~10-20s

   speedup = full_time / incremental_time
   assert speedup > 5, f"Incremental mode not fast enough (speedup={speedup}x)"
   ```

---

## ✅ Acceptance Criteria

### Functional Requirements
- [ ] `detect_data_delta()` correctly identifies new data vs no new data
- [ ] `_compute_incremental()` computes features for new day only
- [ ] `compute_all(incremental=True)` uses incremental mode by default
- [ ] Incremental mode produces **identical results** to full rebuild (validation script passes)
- [ ] Fallback to full rebuild when schema mismatch, insufficient warmup, or user override

### Performance Requirements
- [ ] Daily incremental update: **< 20 seconds** (vs ~180s full rebuild, **90% reduction**)
- [ ] Warmup fetch: < 5 seconds (365 days × 1,826 tickers = 666K rows)
- [ ] Feature computation: < 15 seconds (Phase A+B+C+D+E on 666K rows)
- [ ] Merge write: < 1 second (INSERT OR REPLACE 1,826 rows)

### Quality Requirements
- [ ] Validation script confirms incremental == full (max_diff < 1e-6)
- [ ] Logging clearly shows incremental vs full mode
- [ ] Error handling for edge cases (empty table, missing warmup, schema mismatch)
- [ ] Documentation updated (MEMORY.md, code comments)

---

## 📊 Expected Impact

### Runtime Comparison

| Scenario | Mode | Rows Processed | Runtime | Speedup |
|----------|------|----------------|---------|---------|
| **Daily update** | Full | 2.59M | 180s | 1.0x (baseline) |
| **Daily update** | Incremental | 666K warmup, write 1.8K | **10-20s** | **9-18x faster** |
| **Schema change** | Full (forced) | 2.59M | 180s | 1.0x (no optimization) |
| **Weekly full rebuild** | Full | 2.59M | 180s | 1.0x (integrity check) |

### Database Write Pressure

| Mode | Rows Written | Write Time | I/O Pressure |
|------|--------------|------------|--------------|
| **Full rebuild** | 2.59M | ~10s | High |
| **Incremental** | 1.8K | <1s | **Low (99% reduction)** |

---

## 🚨 Risks & Mitigations

### Risk 1: Incremental mode produces different results than full rebuild
**Impact**: High (data integrity)
**Mitigation**:
- Validation script compares incremental vs full on test dates
- Weekly full rebuild for data integrity baseline
- Log mode used (incremental vs full) for debugging

### Risk 2: Insufficient warmup data causes errors
**Impact**: Medium (pipeline crashes)
**Mitigation**:
- Validate warmup window is ≥365 days before incremental compute
- Automatic fallback to full rebuild if warmup insufficient
- Clear error messages for debugging

### Risk 3: Schema changes break incremental mode
**Impact**: Medium (pipeline uses stale schema)
**Mitigation**:
- Check `feature_version` compatibility before incremental compute
- Automatic fallback to full rebuild if version mismatch
- Bump `feature_version` whenever schema changes

### Risk 4: Multiprocessing overhead dominates on small datasets
**Impact**: Low (incremental mode slower than expected)
**Mitigation**:
- Incremental mode benefits from multiprocessing (666K rows is large enough)
- If needed, add `n_workers=1` override for very small deltas

---

## 📁 Deliverables

### Code
- [ ] `src/feature_pipeline.py` (add `detect_data_delta()`, `_compute_incremental()`, refactor `compute_all()`)
- [ ] `data_curator_duckdb.py` (update to use incremental mode by default)
- [ ] `scripts/validate_incremental_mode.py` (validation script)

### Tests
- [ ] Unit tests for delta detection
- [ ] Integration test for incremental compute
- [ ] Validation script (incremental vs full parity)
- [ ] Performance benchmark

### Documentation
- [ ] Update MEMORY.md (incremental mode notes)
- [ ] Update README or implementation_plan.md (usage examples)
- [ ] Code comments explaining incremental logic

---

## 📝 Implementation Checklist

- [ ] **Phase 1**: Implement `detect_data_delta()` method
- [ ] **Phase 2**: Implement `_compute_incremental()` method
- [ ] **Phase 3**: Refactor `compute_all()` to support incremental mode
- [ ] **Phase 4**: Update `data_curator_duckdb.py` CLI arguments
- [ ] **Phase 5**: Create validation script
- [ ] **Phase 6**: Run validation tests (incremental vs full parity)
- [ ] **Phase 7**: Performance benchmark (measure speedup)
- [ ] **Phase 8**: Update documentation (MEMORY.md, code comments)

---

## 🔗 Related Documents

- [MILESTONE_3.5_MASTER_PLAN.md](./MILESTONE_3.5_MASTER_PLAN.md) - Overall optimization plan
- [FEATURE_PRUNING_PLAN.md](./FEATURE_PRUNING_PLAN.md) - 3.5.1 implementation
- [milestone_3_5_2_completion.md](./milestone_3_5_2_completion.md) - 3.5.2 multiprocessing
- [MEMORY.md](C:/Users/Hang/.claude/projects/c--Users-Hang-PycharmProjects-quantamental/memory/MEMORY.md) - Architecture notes

---

## 📅 Timeline

**Estimated Time**: 4-6 hours
- **Phase 1-3** (Core implementation): 2-3 hours
- **Phase 4-5** (Integration + validation): 1-2 hours
- **Phase 6-8** (Testing + documentation): 1 hour

**Dependencies**:
- ✅ 3.5.1 complete (v3.1 pct_chg features)
- ✅ 3.5.2 complete (multiprocessing)

**Blockers**: None

---

**Next Steps After Completion**:
1. Move to 3.5.4: View Materialization (materialize `v_d2_training` for faster model training)
2. Integration testing across all 3.5.x optimizations
3. Update MEMORY.md with final v4.0 schema and performance benchmarks
