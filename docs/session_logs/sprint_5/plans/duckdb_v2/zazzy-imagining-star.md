# Implementation Plan: API Migration & Dashboard Fixes

## Context

**Problem 1: FMP API is broken** (401 Unauthorized errors) due to incorrect API key being passed (DB path instead of actual key). The FMP API is no longer functional and needs replacement.

**Problem 2: Phase 1 staleness check is buggy** - uses `MAX(date)` across ALL tickers, causing the pipeline to skip ingestion when even ONE ticker has fresh data, leaving other stale tickers unupdated.

**Problem 3: Trade Candidates dashboard page is date-grouped** - shows only one date's candidates at a time with date picker, but should show ALL candidates ungrouped (like the Signal Review page in `dashboard.py`).

**Problem 4: No centralized documentation** of API endpoints and data sources used across the system.

**Critical discovery**: Fundamental data is **fetched but NOT used** by ML models (M01/M02 use only technical features). This simplifies the migration strategy significantly.

---

## Strategy

### Task 1: Fix Phase 1 Staleness Check (CRITICAL - blocks data ingestion)
**Priority**: P0 (fixes broken pipeline)

**Current bug**:
```sql
-- WRONG: Global max date check
SELECT MAX(date) FROM price_data
-- If ANY ticker has latest date, skips ALL tickers
```

**Fix**: Per-ticker staleness check
```sql
-- CORRECT: Count stale tickers in active universe
SELECT COUNT(*) as stale_count
FROM (
    SELECT ticker, MAX(date) as latest_date
    FROM price_data
    WHERE ticker IN (active_universe)  -- 1,252 tickers from screener_members
    GROUP BY ticker
) per_ticker
WHERE latest_date < latest_market_date
-- If stale_count > 0, run Phase 1
```

**Files**:
- `src/orchestrators/daily_pipeline_orchestrator.py` - Replace `_should_skip_phase_1()` method (lines 290-329)

**Verification**: Run pipeline twice—first run should ingest, second run should skip (all tickers fresh).

---

### Task 2: Disable FundamentalEngine FMP Calls (WORKAROUND - not full migration)
**Priority**: P1 (removes 401 errors, data already not used)

**Rationale**: Since fundamentals are **not used** by models, don't waste effort migrating to yfinance (which has inferior data quality). Instead, disable FMP calls and rely on cache-only mode.

**Approach**:
1. Set `force_cache_only=True` when initializing `FundamentalEngine` in orchestrator
2. Remove FMP API calls from Phase 1 (or let them fail silently with cache fallback)
3. Add warning log: "Fundamentals cache-only mode - no API refresh"

**Files**:
- `src/orchestrators/daily_pipeline_orchestrator.py` - Pass `force_cache_only=True` to `FundamentalEngine.__init__`
- `src/fundamental_engine.py` - Ensure `force_cache_only` mode skips all API calls gracefully

**Long-term**: If fundamentals become needed, implement proper yfinance migration (separate initiative).

---

### Task 3: Fix Trade Candidates Dashboard (Ungrouped Display)
**Priority**: P2 (UX improvement)

**Changes**:
1. Remove date picker (selectbox)
2. Remove `prev_date` logic and "Daily Changes" section
3. Query ALL candidates across all dates: `SELECT * FROM t3_sepa_features WHERE feature_version = 'v3.1' ORDER BY date DESC, rs DESC`
4. Add `signal_date` column to table (show when ticker entered universe)
5. Add sort selector (like Signal Review): "RS", "nATR", "Volume Ratio", "Signal Date"
6. Keep candidate count trend chart (optional—user can decide)

**Files**:
- `scripts/pipeline_monitoring_dashboard.py` - Rewrite `render_trade_candidates()` (lines 211-323)

**Verification**: Dashboard shows all SEPA candidates ungrouped, sortable by technical metrics.

---

### Task 4: Create DATA_SOURCES.md Documentation
**Priority**: P3 (documentation)

**Content**:
```markdown
# Data Sources & API Endpoints

## Price Data
- **Primary**: yfinance (Yahoo Finance API)
- **Endpoint**: `yf.download(ticker, start, end)`
- **Rate Limit**: None (casual usage tolerated)
- **Data**: OHLCV daily bars
- **Fallback**: Cache-only mode (`force_cache_only=True`)

## Fundamental Data
- **Status**: Cache-only (FMP API disabled)
- **Historical Source**: FMP `/income-statement`, `/balance-sheet`, `/cash-flow`
- **Note**: Fundamentals NOT used in models; cache maintained for reference

## Macro Data
- **Primary**: FRED API (Federal Reserve Economic Data)
- **Endpoints**:
  - Fed Assets: `WALCL` (Fed Balance Sheet)
  - TGA: `WTREGEN` (Treasury General Account)
  - RRP: `RRPONTSYD` (Reverse Repo)
  - VIX: `VIXCLS` (CBOE Volatility Index)
- **Rate Limit**: 120 calls/hour (free tier)

## Shares Outstanding
- **Primary**: yfinance `.info['sharesOutstanding']`
- **Fallback**: Cache

## Company Profiles
- **Primary**: yfinance `.info` (industry, sector, IPO date)
- **Fallback**: Cache

## Screener Universe
- **Current**: `screener_members` table (DuckDB)
- **Historical**: FMP `/company-screener` (deprecated, rate-limited)
```

**Files**:
- Create `docs/DATA_SOURCES.md`

---

## Implementation Order

1. **Task 1** (staleness fix) - CRITICAL blocker
2. **Task 2** (disable FMP) - Quick workaround
3. **Task 4** (docs) - Reference before Task 3
4. **Task 3** (dashboard) - UX polish

---

## Verification

### Task 1: Staleness Check
```bash
# Test 1: Fresh data (should skip)
python scripts/run_daily_pipeline.py --date 2026-03-15
# Expected: "Phase 1 Check: All 1252 tickers fresh - SKIP"

# Test 2: Stale data (should run)
# Manually delete 1 ticker's latest date in price_data
python scripts/run_daily_pipeline.py --date 2026-03-15
# Expected: "Phase 1 Check: 1/1252 tickers stale - RUN"
```

### Task 2: FMP Disable
```bash
# Run pipeline, check logs
python scripts/run_daily_pipeline.py
# Expected: No 401 errors, log shows "Fundamentals cache-only mode"
```

### Task 3: Dashboard
```bash
streamlit run scripts/pipeline_monitoring_dashboard.py
# Navigate to "Trade Candidates"
# Expected: All candidates ungrouped, sortable, no date picker
```

### Task 4: Docs
```bash
# Read docs/DATA_SOURCES.md
# Verify all endpoints documented
```

---

## Critical Files

| File | Change | Lines |
|------|--------|-------|
| `src/orchestrators/daily_pipeline_orchestrator.py` | Fix `_should_skip_phase_1()`, disable FMP | 290-329, 401 |
| `scripts/pipeline_monitoring_dashboard.py` | Rewrite `render_trade_candidates()` | 211-323 |
| `docs/DATA_SOURCES.md` | CREATE new file | N/A |

---

## Trade-offs

**Why not migrate FMP → yfinance for fundamentals?**
- Models don't use fundamentals → zero business value
- yfinance has inferior data quality (30% field coverage vs FMP)
- Migration effort: 40-60 hours for unused feature
- Better ROI: Use that time for feature engineering that models actually use

**If fundamentals needed later**:
- Reactivate FMP API (fix API key issue)
- OR implement proper yfinance migration (separate initiative)
- Current cache has 5 years of historical data (sufficient for now)
