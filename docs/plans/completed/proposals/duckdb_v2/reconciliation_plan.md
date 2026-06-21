# DuckDB V2 Reconciliation Plan

## Overview
This document maps the **current implementation** to the **v2 target state**, identifying what to keep, refactor, and create.

---

## Table Architecture Migration

### Current State → Target State Mapping

| Current Table/File | Status | Target State | Migration Strategy |
|-------------------|--------|--------------|-------------------|
| `price_data` | ✅ Keep | `t1_price` | **Rename** via `ALTER TABLE price_data RENAME TO t1_price` |
| `fundamentals` | ✅ Keep | `t1_fundamentals` | **Rename** via `ALTER TABLE fundamentals RENAME TO t1_fundamentals` |
| `shares_outstanding` | ✅ Keep | `t1_shares_outstanding` | **Rename** if exists, else create |
| `company_profiles` | ✅ Keep | `t1_company_profiles` | **Rename** (used for sector/industry) |
| `macro_data` | 🟡 Extend | `t1_macro` | **Audit schema**, add missing columns (VIX, breadth indicators) |
| `data/regime_scores.parquet` | ❌ Deprecate | `t2_regime_scores` | **Migrate** parquet → DuckDB table, delete parquet file |
| `daily_features` | ❌ Deprecate | Split into `t2_screener_features` + `t3_sepa_features` | **Refactor** (see detailed plan below) |
| `stock_screener` | ✅ Keep | `t2_screener_members` | **Rename** for clarity (tracks historical screener pass/fail) |
| `models` | ✅ Keep | `models` | **No change** (MLOps model registry, already DuckDB-native) |
| `buy_list` | ✅ Keep | `buy_list` | **No change** (daily scored candidates, output of M01/M02/M03) |
| `buy_list_activity` | ✅ Keep | `buy_list_activity` | **No change** (trade audit log) |
| `master_ticker_registry` | ✅ Keep | `master_ticker_registry` | **No change** (universe management) |
| `universe_snapshots` | ✅ Keep | `universe_snapshots` | **No change** (monthly screener snapshots) |
| `price_data_backfill` | 🟡 Conditional | `price_data_backfill` | **Keep** if backfill ongoing, else drop after migration |
| `shares_backfill` | 🟡 Conditional | `shares_backfill` | **Keep** if backfill ongoing, else drop after migration |

### Daily Features Split Strategy

**Current `daily_features` contains:**
- 79 SQL features (Phase A)
- 16 Python alphas (Phase B)
- 7 cross-sectional ranks (Phase C)
- 4 M03 regime scores (Phase D)
- 3 M03 derived features (Phase E)

**Total:** 109 columns, ~2.6M rows (full universe × history)

**Target Split:**

| Column Group | Current Location | Target Location | Compute Frequency |
|--------------|-----------------|-----------------|-------------------|
| Lightweight features (SMAs, ATR, RS_rating, distances) | `daily_features` | `t2_screener_features` | **Eager** (full universe, daily) |
| Heavy features (16 alphas, 7 ranks) | `daily_features` | `t3_sepa_features` | **Lazy** (SEPA breakouts only) |
| M03 regime scores | `daily_features` (from parquet) | `t2_regime_scores` + `t3_sepa_features` | Regime table updated daily, joined into T3 |

**Migration Steps:**
1. **Create `t2_screener_features`** with 30 lightweight columns
2. **Create `t3_sepa_features`** with 102 heavy columns + `feature_version`
3. **Backfill T3** from 2020-01-01 (using existing `daily_features` as validation)
4. **Parallel validation** (2 weeks): compare T2/T3 outputs vs `daily_features`
5. **Deprecate `daily_features`** once validation passes

---

## Component Migration Status

### ✅ Components to Keep As-Is

| Component | File Path | Reason |
|-----------|-----------|--------|
| `v_d2r_hydrated` | `src/view_manager.py` | Stop-loss logic works correctly, just rename to `v_d2_hydrated` (remove `r`) |
| `FundamentalEngine` | `src/fundamental_engine.py` | Handles yfinance API, just need schema audit for P/E, P/S |
| `SharesEngine` | `src/shares_engine.py` | Manages shares outstanding, no changes needed |
| `CompanyProfileEngine` | `src/company_profile_engine.py` | Fetches sector/industry, works as-is |
| `MacroEngine` | `src/macro_engine.py` | May need extension for VIX, breadth indicators |
| `ViewManager` | `src/view_manager.py` | Extend with new views, don't replace |
| `DataRepository` | `src/data_engine.py` | Low-level DuckDB interface, keep unchanged |

### 🟡 Components to Refactor

#### 1. `FeaturePipeline` (`src/feature_pipeline.py`)

**Current Behavior:**
- `compute_all()` rebuilds entire `daily_features` table via `CREATE OR REPLACE`
- Phase A (SQL) → Phase B (Python) → Phase C (SQL) → Phase D (Python+SQL) → Phase E (SQL)
- Computes for full universe (~8,000 tickers)

**Target Behavior:**
- Split into **T2 path** (lightweight, eager) and **T3 path** (heavy, lazy)
- `compute_t2()`: Update `t2_screener_features` for full universe (SQL only, fast)
- `compute_t3(candidates)`: Append to `t3_sepa_features` for SEPA breakouts only (SQL + Python, selective)

**Refactor Plan:**

```python
# NEW: src/feature_pipeline.py

class FeaturePipeline:
    def compute_t2(self, start_date: str = None) -> int:
        """Compute lightweight features for full universe."""
        # Phase A (subset): SMAs, ATR, RS_rating, distances
        # Write to t2_screener_features (UPDATE or INSERT)
        pass

    def compute_t3_for_candidates(self, candidates: pd.DataFrame, feature_version: str = 'v3.0') -> int:
        """Compute heavy features for SEPA breakout candidates only."""
        # Phase A (full): All 79 SQL features
        # Phase B: 16 Python alphas (WQ101)
        # Phase C: 7 cross-sectional ranks
        # Join M03 scores from t2_regime_scores
        # INSERT OR IGNORE into t3_sepa_features
        pass

    def compute_all(self):
        """DEPRECATED: Use compute_t2() + compute_t3_for_candidates() instead."""
        raise DeprecationWarning("Use split T2/T3 compute paths")
```

**Files to Modify:**
- `src/feature_pipeline.py` (split compute_all logic)
- `data_curator_duckdb.py` (call new compute methods)

**Migration Risk:** Medium
- **Risk:** Feature values diverge from current implementation
- **Mitigation:** 2-week parallel validation, compare 10 tickers/day

#### 2. `data_curator_duckdb.py` (Main Pipeline Orchestrator)

**Current Behavior:**
- Fetch price/fundamentals/shares
- Call `FeaturePipeline.compute_all()` to rebuild `daily_features`
- Call `ViewManager.create_all()` to refresh views

**Target Behavior:**
- Fetch T1 data (price, fundamentals, shares, macro)
- Update `t2_screener_members` (screener pass/fail)
- Call `FeaturePipeline.compute_t2()` (eager, full universe)
- Identify new SEPA breakouts (query T2)
- Call `FeaturePipeline.compute_t3_for_candidates(breakouts)` (lazy, selective)
- Call `ViewManager.create_all()` (refresh views)

**Refactor Plan:**

```python
# MODIFIED: data_curator_duckdb.py

def run_daily_pipeline(date: str = None):
    """V2 pipeline with T2/T3 split."""
    date = date or get_latest_trading_day()

    # Step 1: Ingest T1 (parallel)
    with ThreadPoolExecutor() as ex:
        ex.submit(ingest_t1_price, date)
        ex.submit(ingest_t1_fundamentals, date)
        ex.submit(ingest_t1_shares, date)
        ex.submit(ingest_t1_macro, date)  # NEW

    # Step 2: Update screener membership
    update_t2_screener_members(date)

    # Step 3: Compute T2 features (full universe)
    FeaturePipeline(db_path).compute_t2(start_date=date)

    # Step 4: Identify NEW SEPA breakouts
    new_breakouts = identify_new_sepa_breakouts(date)  # NEW function

    # Step 5: Compute T3 for new breakouts only
    if not new_breakouts.empty:
        FeaturePipeline(db_path).compute_t3_for_candidates(
            new_breakouts,
            feature_version='v3.0'
        )
    else:
        logger.warning(f"0 new SEPA breakouts on {date}")

    # Step 6: Refresh views
    ViewManager(db_path).create_all()
```

**Files to Modify:**
- `data_curator_duckdb.py` (refactor main pipeline)
- Add new function: `identify_new_sepa_breakouts(date)` (query T2, filter SEPA criteria, exclude already in T3)

**Migration Risk:** Low
- Current `data_curator_duckdb.py` already has modular structure
- New functions slot in cleanly

#### 3. `ViewManager` (`src/view_manager.py`)

**Current Views:**
- `v_sepa_candidates` (Trend template C1-C9)
- `v_d1_candidates` (Full SEPA signal C1-C11)
- `v_d2_features` (D1 + fundamentals)
- `v_d2r_hydrated` (D1 trades hydrated to exit)
- `v_d2_training` (D2 features + outcomes)

**Target Views:**
- `v_sepa_candidates` ✅ Keep (used to identify T3 candidates)
- `v_d1_candidates` ✅ Keep
- `v_d1_trades` 🆕 Add (gap-based trade ID generation from T3)
- `v_d2_hydrated` 🟡 Rename from `v_d2r_hydrated` (remove `r` suffix)
- `v_d2_training` ✅ Keep, update to read from `t3_sepa_features`
- `v_d3_deployment` 🆕 Add (last 252 days from T3 for daily scoring)

**Refactor Plan:**

```python
# MODIFIED: src/view_manager.py

class ViewManager:
    def create_all(self):
        self._create_v_sepa_candidates(con)  # Keep
        self._create_v_d1_candidates(con)    # Keep
        self._create_v_d1_trades(con)        # NEW
        self._create_v_d2_hydrated(con)      # Renamed from v_d2r_hydrated
        self._create_v_d2_training(con)      # Update to read from t3_sepa_features
        self._create_v_d3_deployment(con)    # NEW

    def _create_v_d1_trades(self, con):
        """Generate trade_id using LAG-based gap detection."""
        con.execute("""
            CREATE OR REPLACE VIEW v_d1_trades AS
            WITH t3_with_gaps AS (
                SELECT
                    ticker, date,
                    LAG(date, 1) OVER (PARTITION BY ticker ORDER BY date) as prev_date,
                    DATEDIFF('day', prev_date, date) as days_since_last
                FROM t3_sepa_features
                WHERE feature_version = 'v3.0'
            ),
            trade_boundaries AS (
                SELECT
                    ticker, date,
                    SUM(CASE WHEN days_since_last > 1 OR prev_date IS NULL THEN 1 ELSE 0 END)
                        OVER (PARTITION BY ticker ORDER BY date) as trade_id
                FROM t3_with_gaps
            )
            SELECT
                ticker,
                trade_id,
                MIN(date) as entry_date,
                MAX(date) as exit_date
            FROM trade_boundaries
            GROUP BY ticker, trade_id
        """)

    def _create_v_d3_deployment(self, con):
        """Last 252 days of T3 for daily inference."""
        con.execute("""
            CREATE OR REPLACE VIEW v_d3_deployment AS
            SELECT *
            FROM t3_sepa_features
            WHERE date >= CURRENT_DATE - INTERVAL '252 days'
              AND feature_version = 'v3.0'
            ORDER BY date DESC, ticker
        """)
```

**Files to Modify:**
- `src/view_manager.py` (add 2 new views, rename 1)

**Migration Risk:** Low
- New views are additive (don't break existing code)
- Renaming `v_d2r_hydrated` → `v_d2_hydrated` requires grep for usages

---

### 🆕 Components to Create

| Component | File Path | Purpose |
|-----------|-----------|---------|
| `RegimePipeline` | `src/regime_pipeline.py` | Compute M03 scores from `t1_macro` → `t2_regime_scores` |
| `backfill_t3_sepa_features.py` | `scripts/backfill_t3_sepa_features.py` | One-time historical T3 population (2020-01-01 onward) |
| `ingest_t1_macro.py` | `scripts/ingest_t1_macro.py` | Daily fetch of SPY/QQQ/VIX → `t1_macro` |
| `migrate_m03_parquet_to_duckdb.py` | `scripts/migrate_m03_parquet_to_duckdb.py` | One-time: load `data/regime_scores.parquet` → `t2_regime_scores` |
| `run_daily_pipeline.py` | `scripts/run_daily_pipeline.py` | V2 orchestration script (replaces manual calls to `data_curator_duckdb.py`) |
| `check_pipeline_health.py` | `scripts/check_pipeline_health.py` | Monitoring dashboard (last 30 days, data freshness, alerts) |
| `validate_fundamentals_weekly.py` | `scripts/validate_fundamentals_weekly.py` | Compare our data vs FMP API (10 random tickers) |
| `check_t3_integrity.py` | `scripts/check_t3_integrity.py` | Detect duplicates, NULLs, feature drift in T3 |
| `rollback_to_v1.py` | `scripts/rollback_to_v1.py` | Emergency rollback to current architecture |

---

## Data Migration Risks

### High-Risk Areas

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Feature value divergence** | M01 predictions change post-migration | 2-week parallel validation: compare v1 `daily_features` vs v2 `t3_sepa_features` for same tickers/dates. Alert if >5% variance. |
| **Missing fundamental columns** | T3 lacks P/E, P/S if not in `t1_fundamentals` | Audit schema in Phase 2.2, add missing columns to `FundamentalEngine` before T3 backfill. |
| **M03 parquet → DuckDB mismatch** | Regime scores differ after migration | Validate 10 random dates: `t2_regime_scores` vs `regime_scores.parquet`. Must match exactly. |
| **T3 backfill failure halfway** | Partial data, wasted compute time | Checkpoint every 100 dates, allow resume via `--resume-from` flag. |
| **yfinance API rate limits** | Daily pipeline fails to fetch T1 data | Fail-safe mode: skip T2/T3 updates, alert admin, use yesterday's data for scoring. |

### Medium-Risk Areas

| Risk | Impact | Mitigation |
|------|--------|------------|
| **View renaming breaks existing code** | `v_d2r_hydrated` → `v_d2_hydrated` | Grep entire codebase for `v_d2r_hydrated`, update all references. |
| **T2 full-universe compute too slow** | >5 minutes to update `t2_screener_features` | Profile SQL, add indexes on (ticker, date), use DuckDB `PRAGMA threads=8`. |
| **Duplicate rows in T3** | `INSERT OR IGNORE` fails silently | Add `check_t3_integrity.py` to daily pipeline, alert on duplicates. |

---

## Validation Strategy

### Phase-by-Phase Validation

#### Phase 3 (T1/T2 Refactor)
**After Milestone 3.1 (T1 Macro):**
```sql
-- Check t1_macro populated
SELECT COUNT(*), MIN(date), MAX(date) FROM t1_macro;
-- Expected: ~1260 rows, 2020-01-01 to yesterday
```

**After Milestone 3.2 (M03 Migration):**
```sql
-- Compare parquet vs DuckDB
SELECT date, m03_score FROM t2_regime_scores WHERE date = '2024-01-15';
-- vs parquet: df[df['date'] == '2024-01-15']['m03_score']
-- Expected: exact match (±0.0001 tolerance)
```

**After Milestone 3.3 (T2 Features):**
```sql
-- Compare T2 vs daily_features (legacy)
SELECT ticker, date, sma_50, rs_rating
FROM t2_screener_features
WHERE date = '2024-01-15' AND ticker IN ('AAPL', 'MSFT', 'GOOGL')
-- vs
SELECT ticker, date, sma_50, rs_rating
FROM daily_features
WHERE date = '2024-01-15' AND ticker IN ('AAPL', 'MSFT', 'GOOGL')
-- Expected: exact match
```

#### Phase 4 (T3 Implementation)
**After Milestone 4.1 (T3 Backfill):**
```sql
-- Spot-check 10 random tickers
SELECT ticker, date, alpha001, alpha006, rs_rating
FROM t3_sepa_features
WHERE date = '2024-01-15'
ORDER BY RANDOM()
LIMIT 10;

-- Compare to daily_features (should match for SEPA candidates)
```

**After Milestone 4.2 (T3 Daily Append):**
```bash
# Run daily pipeline on historical date
python scripts/run_daily_pipeline.py --date 2024-01-15

# Check T3 rows created
SELECT COUNT(*) FROM t3_sepa_features WHERE date = '2024-01-15';
# Expected: ~50 rows (typical daily breakout count)
```

#### Phase 8 (Parallel Validation)
**2-week comparison:**
```python
# scripts/compare_v1_v2_outputs.py
for date in last_14_days:
    # Compare SEPA candidate lists
    v1_candidates = query_v_sepa_candidates(date)
    v2_candidates = query_t3_sepa_features(date)

    diff = set(v1_candidates) - set(v2_candidates)
    if diff:
        alert(f"Candidate mismatch on {date}: {diff}")

    # Compare feature values (sample 10 tickers)
    for ticker in random.sample(v1_candidates, 10):
        v1_features = query_daily_features(ticker, date)
        v2_features = query_t3_sepa_features(ticker, date)

        variance = compare_features(v1_features, v2_features)
        if variance > 0.05:  # >5% difference
            alert(f"Feature variance for {ticker} on {date}: {variance:.2%}")
```

---

## Rollback Procedure

### When to Rollback
- **Validation fails:** >1% SEPA candidate discrepancy during parallel period
- **Performance degradation:** Daily pipeline takes >10 minutes (vs current ~3 minutes)
- **Data corruption:** Duplicate rows in T3, NULL values in critical columns
- **Production incident:** M01 model crashes due to schema mismatch

### Rollback Steps

1. **Stop daily pipeline:**
   ```bash
   # Disable cron job or kill running process
   crontab -e  # Comment out run_daily_pipeline.py
   ```

2. **Restore `daily_features` table:**
   ```sql
   -- From backup (created before migration)
   CREATE TABLE daily_features AS
   SELECT * FROM daily_features_backup_20240215;
   ```

3. **Revert code:**
   ```bash
   git checkout main  # Or previous stable commit
   ```

4. **Run old pipeline:**
   ```bash
   python data_curator_duckdb.py --update-all
   ```

5. **Verify restoration:**
   ```sql
   SELECT MAX(date) FROM daily_features;
   -- Should be yesterday
   ```

6. **Post-mortem:**
   - Document what failed
   - Fix issues in dev branch
   - Re-validate before re-attempting migration

---

## Migration Timeline

| Phase | Estimated Duration | Deliverables |
|-------|-------------------|--------------|
| **Phase 1** (Documentation) | 3-5 hours | This doc + updated blueprint + DAG |
| **Phase 2** (Schema Design) | 4-6 hours | SQL schemas, fundamental audit, view validation |
| **Phase 3** (T1/T2 Refactor) | 8-10 hours | `t1_macro`, `t2_regime_scores`, `t2_screener_features` |
| **Phase 4** (T3 Implementation) | 12-16 hours (dev) + 8 hours (backfill) | `t3_sepa_features` backfilled, daily append working |
| **Phase 5** (View Layer) | 3-4 hours | Renamed views, new `v_d1_trades`, `v_d3_deployment` |
| **Phase 6** (Orchestration) | 6-8 hours | `run_daily_pipeline.py`, monitoring dashboard |
| **Phase 7** (Data Quality) | 4-5 hours | Validation scripts, integrity checks |
| **Phase 8** (Migration) | 2 weeks (parallel) + 2 hours (rollback prep) | Cutover to v2, deprecate v1 |

**Total Development Time:** ~45-55 hours
**Total Calendar Time:** ~4 weeks (including 2-week validation period)

---

## Success Criteria

### Must-Have (Blocking)
- [ ] T3 backfill completes successfully (~500K rows)
- [ ] 2-week parallel validation shows <1% SEPA candidate discrepancy
- [ ] Feature values match within ±5% tolerance
- [ ] M01 predictions within ±0.01 of current model
- [ ] Daily pipeline runs in <5 minutes
- [ ] Tested rollback script restores v1 in <5 minutes

### Nice-to-Have (Non-Blocking)
- [ ] T2 full-universe compute <30 seconds
- [ ] T3 daily append <10 seconds
- [ ] Weekly fundamental validation via FMP
- [ ] Monitoring dashboard shows 30-day health report
- [ ] Alert system integrated with Slack

---

## Next Steps

1. ✅ Complete Phase 1 documentation (this doc + blueprint + DAG)
2. **Phase 2.2:** Audit `t1_fundamentals` schema (check for P/E, P/S, P/B)
3. **Phase 3.1:** Implement `t1_macro` ingestion
4. **Phase 3.2:** Migrate M03 parquet → `t2_regime_scores`
5. **Phase 4.1:** Backfill `t3_sepa_features` from 2020-01-01

_Ready to proceed with Phase 2 after blueprint review._
