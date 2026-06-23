# DuckDB Migration - Implementation Ready

**Date:** 2026-02-11
**Status:** 🟢 Approved for Development
**Phase:** 1 (Parallel Operation)

---

## Executive Summary

Migration plan reviewed and refined. All architectural concerns addressed:

✅ **Schema Evolution** - Hybrid JSON + typed columns for fundamentals
✅ **Concurrency** - Single-writer gatekeeper pattern
✅ **Data Integrity** - Validator harness built
✅ **Performance** - Sort-by-date strategy + materialized features
✅ **Rollback** - Files remain source of truth during Phase 1

---

## What's Been Delivered

### 1. Schema Design Document
**File:** `docs/database_schema.md`

Defines 6 core tables:
- `price_data` - Raw OHLCV (sorted by date, ticker)
- `daily_features` - Pre-computed SMA, RS, ATR (SQL window functions)
- `fundamentals` - Hybrid schema (revenue, EPS + JSON blob)
- `company_profiles` - Universe management with sector/industry
- `buy_list_history` - Scanner output log (never overwrite)
- `macro_data` - SPY, VIX, economic indicators

Plus 2 analytical views:
- `v_sepa_candidates` - Live SEPA filter (replaces Python logic)
- `v_master_dataset` - Equivalent to D2R (price + features + fundamentals)

### 2. Migration Script
**File:** `scripts/migrate_to_duckdb.py`

Features:
- **Single-writer gatekeeper** (all writes go through this script)
- **Staging pattern** (temp table → insert) to avoid locks
- **Idempotent schema** (CREATE IF NOT EXISTS)
- **Upsert support** (ON CONFLICT DO UPDATE)
- **Two modes:**
  - `--mode initial` - Full data migration
  - `--mode daily` - Incremental updates (only recent dates)

Usage:
```bash
# One-time migration
python scripts/migrate_to_duckdb.py --mode initial

# Daily updates (last 7 days)
python scripts/migrate_to_duckdb.py --mode daily

# Daily updates (custom date)
python scripts/migrate_to_duckdb.py --mode daily --start-date 2026-02-01
```

### 3. Validation Harness
**File:** `scripts/validate_migration.py`

Tests:
1. **Price Data** - Random sample, compare file vs. DB (assert_frame_equal)
2. **Company Profiles** - Verify sector/industry consistency
3. **Daily Features** - Spot-check SMA/52w-high calculations
4. **SEPA View** - Verify filter logic (close > SMA-200, etc.)

Usage:
```bash
# Run all validations
python scripts/validate_migration.py --test all --sample-size 20

# Test specific component
python scripts/validate_migration.py --test price --sample-size 50
```

---

## Phase 1 Workflow

**Principle:** Files = Truth, DB = Shadow

```
┌─────────────────┐
│  data_curator   │ (existing)
│  downloads data │
└────────┬────────┘
         │
         ▼
    ┌────────┐
    │ Files  │ ◄── SOURCE OF TRUTH
    └────┬───┘
         │
         ▼
┌─────────────────┐
│migrate_to_duckdb│ (new)
│   reads files   │
└────────┬────────┘
         │
         ▼
    ┌────────┐
    │ DuckDB │ ◄── SHADOW (validation only)
    └────┬───┘
         │
         ▼
┌─────────────────┐
│  validate.py    │ (new)
│  file == DB?    │
└─────────────────┘
```

**Daily Routine:**
1. `data_curator.py` updates files (existing workflow)
2. `migrate_to_duckdb.py --mode daily` syncs to DB
3. `validate_migration.py` checks consistency
4. If validator passes → proceed
5. If validator fails → investigate before using DB

---

## Key Design Patterns

### 1. Sort-Before-Insert (Critical for Performance)

```python
# ALWAYS do this before inserting price data
df = df.sort_values(['date', 'ticker'])
conn.execute("INSERT INTO price_data SELECT * FROM df")
```

**Why:** DuckDB's columnar format uses min/max zone maps. Sorted data enables:
- Fast date range queries (skip entire row groups)
- Efficient ticker lookups (secondary benefit)

### 2. Staging Pattern (Avoid Locks)

```python
# Bad: Direct insert (can lock table)
conn.execute("INSERT INTO price_data VALUES (...)")

# Good: Staging table (atomic swap)
conn.execute("CREATE TEMP TABLE staging AS SELECT * FROM df")
conn.execute("INSERT INTO price_data SELECT * FROM staging ON CONFLICT ...")
conn.execute("DROP TABLE staging")
```

### 3. Materialized Features (Compute Once)

Instead of:
```python
# Slow: Compute SMA every time
df['sma_50'] = df.groupby('ticker')['close'].rolling(50).mean()
```

Do:
```sql
-- Fast: Pre-computed in daily_features table
SELECT sma_50 FROM daily_features WHERE ticker = 'AAPL' AND date = '2026-02-11'
```

### 4. Views for Complex Logic

```sql
-- SEPA filter as a view (no code changes needed)
CREATE VIEW v_sepa_candidates AS
SELECT ...
FROM daily_features f
JOIN price_data p ON ...
WHERE close > sma_200 AND sma_50 > sma_200 AND ...
```

**Benefit:** Scanner can query view instead of reimplementing logic.

---

## TODO Before Running Migration

### A. Data Source Review
Need to verify actual paths in your system:

```python
# In migrate_to_duckdb.py, update these paths:
PRICE_DATA_DIR = PROJECT_ROOT / "data" / "universe.parquet"  # ← Is this correct?
COMPANY_PROFILE_DIR = PROJECT_ROOT / "data" / "company_profiles"  # ← Verify
```

**Action:** Check where your current data lives:
- Universe parquet location?
- Company profiles format (JSON files? Single parquet?)
- Earnings data structure?

### B. SEPA Filter Criteria
Placeholder in `v_sepa_candidates` uses generic rules:
```sql
WHERE close > sma_200
  AND sma_50 > sma_200
  AND pct_from_high_52w > -0.25
  AND vol_avg_50 > 500000  -- ← Is this your actual liquidity filter?
```

**Action:** Review `daily_scanner.py` for exact SEPA criteria.

### C. RS Rating Calculation
Current migration computes basic features (SMA, 52w-high) but not RS rating.

**Options:**
1. Keep RS in Python (easier, flexible)
2. Implement in SQL (faster, but complex)

**Action:** Decide approach based on RS formula complexity.

---

## Open Questions (Answer Before POC)

1. **Fundamentals Data Format:**
   - Do you have earnings data already?
   - What format? (JSON per ticker? Single parquet?)
   - Which fields are most important?

2. **Current Data Volume:**
   - How many tickers in universe?
   - Date range of historical data?
   - This affects migration time estimate

3. **Daily Update Timing:**
   - When does `data_curator.py` run? (market close? overnight?)
   - Should DuckDB sync happen immediately after? Or scheduled separately?

4. **Backup Strategy:**
   - Daily snapshots? Weekly?
   - Local only or cloud backup (S3, Drive)?

---

## Success Metrics (Phase 1)

After 1 week of parallel operation, verify:

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Data Consistency | 100% | `validate_migration.py` passes all tests |
| Migration Speed | <2 min | Time `migrate_to_duckdb.py --mode daily` |
| Memory Usage | <2 GB peak | Task Manager during migration |
| Query Speed | 10x faster | Compare file-read vs. SQL query |
| No Regressions | 0 issues | Scanner output identical |

**Go/No-Go Decision After Phase 1:**
- ✅ **Go to Phase 2** if all metrics met
- 🛑 **Rollback** if validator fails or performance worse

---

## Phase 2 Preview (Future)

Once Phase 1 validated:

1. **Migrate Scanner to DuckDB**
   ```python
   # Replace file reads with:
   sepa_df = conn.execute("SELECT * FROM v_sepa_candidates WHERE date = ?", [today])
   ```

2. **Migrate Model Training**
   ```python
   # Replace D2R generation with:
   df = conn.execute("SELECT * FROM v_master_dataset WHERE date BETWEEN ? AND ?", [start, end])
   ```

3. **Deprecate File Reads**
   - DuckDB becomes source of truth
   - Universe parquets generated FROM DuckDB (backup only)

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Migration corrupts data | Files untouched (rollback = delete DB file) |
| Validator shows discrepancies | Investigate before using DB queries |
| Query slower than expected | Verify sort order, add indexes if needed |
| Out of disk space | Monitor with `du -sh data/` (only +250 MB expected) |
| DuckDB file corruption | Daily backups, keep last 7 days |

---

## Next Steps (Recommended Order)

1. **Review & Answer Open Questions** (you + Claude)
   - Verify data paths
   - Confirm SEPA criteria
   - Decide on RS calculation approach

2. **Update Migration Script Paths** (Claude)
   - Point to actual universe parquet
   - Adjust company profiles loader

3. **Run POC on Sample Data** (you)
   ```bash
   # Test with 1 year of data first
   python scripts/migrate_to_duckdb.py --mode initial
   python scripts/validate_migration.py --test all
   ```

4. **Full Migration if POC Succeeds** (you)
   - Migrate all historical data
   - Set up daily sync cron job

5. **Monitor for 1 Week** (you)
   - Run validator daily
   - Compare scanner results (file vs. DB)
   - Track performance metrics

6. **Go/No-Go Decision** (you + Claude)
   - If pass → Phase 2 (switch to DB-primary)
   - If fail → Debug or rollback

---

**Estimated Timeline:**
- Questions + Path Updates: 30 min
- POC (1 year data): 1 hour
- Full Migration: 2 hours
- Validation Period: 1 week (background)
- **Total Active Work:** ~4 hours
- **Calendar Time:** 1 week

**Ready to proceed when you answer the open questions above!**
