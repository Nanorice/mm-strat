# Pipeline Refactor: Phase 1 Decoupling + Criteria Versioning + yfinance Fundamentals

> **Status: ✅ COMPLETE** — Implemented 2026-03-16. All three modules implemented and reviewed.

Three self-contained modules to fix circular dependencies, add audit-traceability to screening, and replace the dead FMP fundamentals engine with yfinance.

---

## Module 1 — Decouple Phase 1 from [screener_members](file:///c:/Users/Hang/PycharmProjects/quantamental/src/orchestrators/daily_pipeline_orchestrator.py#498-510)

### Problem
Phase 1 sub-steps 1.2 (fundamentals) and 1.3 (shares) only ingest data for [screener_members](file:///c:/Users/Hang/PycharmProjects/quantamental/src/orchestrators/daily_pipeline_orchestrator.py#498-510) tickers, creating a circular dependency with Phase 2 and leaving non-screener tickers with stale/missing data.

### Change
In [daily_pipeline_orchestrator.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/orchestrators/daily_pipeline_orchestrator.py#395-496), replace the `screener_tickers` universe with `price_tickers` for sub-phases 1.2 and 1.3.

```diff
-            # Get screener universe: active tickers from screener_members
-            screener_tickers = self.screener_manager.get_active_tickers()
-            ...
-            # 1.2: Fundamentals (cache-only, skip if no tickers)
-            if screener_tickers:
-                futures[executor.submit(
-                    self.fund_engine.update_fundamentals_cache,
-                    tickers=screener_tickers, ...
-
-            # 1.3: Shares (update screener tickers)
-            if screener_tickers:
-                futures[executor.submit(
-                    self.shares_engine.update,
-                    tickers=screener_tickers, ...
+            # 1.2: Fundamentals (all cached tickers)
+            if price_tickers:
+                futures[executor.submit(
+                    self.fund_engine.update_fundamentals,
+                    tickers=price_tickers, ...
+
+            # 1.3: Shares (all cached tickers)
+            if price_tickers:
+                futures[executor.submit(
+                    self.shares_engine.update,
+                    tickers=price_tickers, ...
```

Also remove `self.screener_manager` from [__init__](file:///c:/Users/Hang/PycharmProjects/quantamental/src/shares_engine.py#27-29) (it's still used in Phase 2, but Phase 1 no longer needs it).

> [!NOTE]
> The diff renames `update_fundamentals_cache` → `update_fundamentals`. This rename is coupled to Module 3: Module 3 rewrites this method for yfinance. If implementing Module 1 alone (before Module 3), keep the existing method name and only change the ticker universe argument.

> [!NOTE]
> Universe discovery (discovering *new* tickers not yet in [price_data](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_merger.py#120-157)) is a separate concern. Listed as a TODO at the bottom of this plan.

---

## Module 2 — Screener Criteria Versioning

### Problem
Screening thresholds are hardcoded in `ScreenerManager.update_membership()`. No audit trail of past criteria; changing criteria mid-stream breaks historical consistency.

### Schema

#### [NEW] `screener_criteria_versions` table

```sql
CREATE TABLE IF NOT EXISTS screener_criteria_versions (
    version_id      INTEGER PRIMARY KEY,
    effective_date  DATE    NOT NULL,
    min_price       DOUBLE  NOT NULL DEFAULT 15.0,
    min_volume_20d  DOUBLE  NOT NULL DEFAULT 500000,
    min_market_cap  DOUBLE,                    -- NULL = no filter
    max_market_cap  DOUBLE,                    -- NULL = no filter
    is_backfilled   BOOLEAN DEFAULT FALSE,
    notes           VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed with current criteria
INSERT INTO screener_criteria_versions
    (version_id, effective_date, min_price, min_volume_20d, notes)
VALUES (1, '2020-01-01', 15.0, 500000, 'Initial SEPA criteria');
```

### Changes

#### [MODIFY] [screener_manager.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/managers/screener_manager.py)

1. Add `_ensure_criteria_table()` to create `screener_criteria_versions` if not exists — called from `__init__` alongside the existing `_ensure_table()`:

```python
def __init__(self, db_path: str):
    self.db_path = str(db_path)
    self._ensure_table()
    self._ensure_criteria_table()  # NEW — Module 2
```

The seed `INSERT` inside `_ensure_criteria_table()` must use `INSERT OR IGNORE` (or `INSERT INTO ... WHERE NOT EXISTS`) so it is idempotent on every startup.

2. Add `_get_active_criteria(target_date)` → queries latest `effective_date <= target_date`
3. Modify [update_membership(target_date)](file:///c:/Users/Hang/PycharmProjects/quantamental/src/managers/screener_manager.py#49-158) to read criteria from DB instead of hardcoded values:

```python
def _get_active_criteria(self, target_date: str) -> dict:
    conn = duckdb.connect(self.db_path)
    try:
        row = conn.execute("""
            SELECT * FROM screener_criteria_versions
            WHERE effective_date <= ?
            ORDER BY effective_date DESC LIMIT 1
        """, [target_date]).fetchone()
        if not row:
            raise ValueError(f"No criteria defined for {target_date}")
        return {
            'version_id': row[0],
            'min_price': row[3],
            'min_volume_20d': row[4],
            'min_market_cap': row[5],
            'max_market_cap': row[6],
        }
    finally:
        conn.close()
```

Then replace hardcoded `WHERE last_price >= 15.0 AND avg_volume_20d >= 500000` with parameterized values from `_get_active_criteria()`.

#### [NO CHANGE] `_run_phase_2_screener_membership()` in [daily_pipeline_orchestrator.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/orchestrators/daily_pipeline_orchestrator.py)

The orchestrator Phase 2 method does not need modification. The criteria version table is bootstrapped lazily in `ScreenerManager.__init__`, and `update_membership()` consumes it internally. The orchestrator call `self.screener_manager.update_membership(target_date)` remains unchanged.

---

## Module 3 — yfinance Fundamentals Engine (Detailed)

### Problem
[FundamentalEngine](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_engine.py#25-659) uses FMP API (paid, disabled). Fundamental data lives in parquet files, not queryable in DuckDB. No filing date mapping → potential look-ahead bias.

### 3.1 — DuckDB Schema

#### [NEW] [fundamentals](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_engine.py#272-320) table

```sql
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker              VARCHAR NOT NULL,
    period_end          DATE    NOT NULL,     -- fiscal quarter end (income_stmt index)
    filing_date         DATE,                 -- actual announcement date (from earnings_dates)
    -- Earnings estimates (from get_earnings_dates)
    eps_estimate        DOUBLE,
    reported_eps        DOUBLE,
    eps_surprise_pct    DOUBLE,
    -- Income Statement (from get_income_stmt)
    total_revenue       DOUBLE,
    cost_of_revenue     DOUBLE,
    gross_profit        DOUBLE,
    operating_income    DOUBLE,
    operating_expense   DOUBLE,
    ebit                DOUBLE,
    ebitda              DOUBLE,
    net_income          DOUBLE,
    basic_eps           DOUBLE,
    diluted_eps         DOUBLE,
    basic_avg_shares    DOUBLE,
    diluted_avg_shares  DOUBLE,
    r_and_d             DOUBLE,               -- ResearchAndDevelopment
    sga                 DOUBLE,               -- SellingGeneralAndAdministration
    tax_provision       DOUBLE,
    -- Balance Sheet (from get_balance_sheet)
    total_assets        DOUBLE,
    current_assets      DOUBLE,
    cash_and_equivalents DOUBLE,
    inventory           DOUBLE,
    accounts_receivable DOUBLE,
    total_debt          DOUBLE,
    net_debt            DOUBLE,
    current_liabilities DOUBLE,
    long_term_debt      DOUBLE,
    stockholders_equity DOUBLE,
    retained_earnings   DOUBLE,
    working_capital     DOUBLE,
    invested_capital    DOUBLE,
    tangible_book_value DOUBLE,
    -- Cash Flow (from get_cashflow)
    operating_cash_flow DOUBLE,
    free_cash_flow      DOUBLE,
    capex               DOUBLE,               -- CapitalExpenditure
    stock_based_comp    DOUBLE,
    change_in_working_capital DOUBLE,
    depreciation_amortization DOUBLE,
    -- Metadata
    source              VARCHAR DEFAULT 'yfinance',
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, period_end)
);
```

#### [NEW] `earnings_calendar` table (stub rows for upcoming earnings)

```sql
CREATE TABLE IF NOT EXISTS earnings_calendar (
    ticker          VARCHAR NOT NULL,
    earnings_date   DATE    NOT NULL,       -- expected announcement date
    eps_estimate    DOUBLE,
    reported_eps    DOUBLE,                 -- NULL until announced
    eps_surprise_pct DOUBLE,               -- NULL until announced
    is_confirmed    BOOLEAN DEFAULT FALSE,  -- True after earnings released
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, earnings_date)
);
```

### 3.2 — yfinance API Usage

| Data | API Call | Index Type | Returns |
|------|----------|------------|---------|
| Income stmt | `ticker.get_income_stmt(freq='quarterly').T` | `period_end` date | Last 4-5 quarters |
| Balance sheet | `ticker.get_balance_sheet(freq='quarterly').T` | `period_end` date | Last 4-5 quarters |
| Cash flow | `ticker.get_cashflow(freq='quarterly').T` | `period_end` date | Last 4-5 quarters |
| Earnings dates | `ticker.get_earnings_dates(limit=N)` | Earnings announcement datetime | Up to ~12 years back |

### 3.3 — Filing Date Mapping Logic

The `get_income_stmt()` index gives `period_end` (fiscal quarter end), but we need the *actual announcement date* (`filing_date`) for the as-of join. The `get_earnings_dates()` API provides this.

**Mapping rule:** For each `period_end`, the corresponding `filing_date` is the *first earnings date strictly after* that `period_end`, within a 90-day window.

```python
def _map_period_end_to_filing_date(
    self,
    period_ends: List[pd.Timestamp],
    earnings_dates_df: pd.DataFrame
) -> Dict[pd.Timestamp, pd.Timestamp]:
    """
    Map fiscal period end dates to actual filing/announcement dates.
    
    Rule: filing_date = first earnings date AFTER period_end, within 90 days.
    """
    mapping = {}
    ed_dates = pd.to_datetime(
        earnings_dates_df.index
    ).tz_localize(None).sort_values()

    for period_end in sorted(period_ends):
        pe = pd.Timestamp(period_end).tz_localize(None)
        candidates = ed_dates[
            (ed_dates > pe) & (ed_dates <= pe + pd.Timedelta(days=90))
        ]
        if len(candidates):
            filing = candidates[0]
            mapping[pe] = filing
    return mapping
```

### 3.4 — When to Trigger a Fundamental Data Pull

Phase 1 fundamental update logic (runs daily):

```
For each ticker in price_data:
  1. Read earnings_calendar WHERE ticker = t AND is_confirmed = FALSE
     → get next_earnings_date
  
  2. If next_earnings_date <= today:
       → Call get_income_stmt, get_balance_sheet, get_cashflow
       → Map period_end → filing_date using earnings_dates
       → UPSERT into fundamentals table
       → UPDATE earnings_calendar SET is_confirmed = TRUE,
           reported_eps = X, eps_surprise_pct = Y
  
  3. Else (no earnings today):
       → Skip this ticker (fundamentals are quarterly, no update needed)
  
  4. Also: call get_earnings_dates() monthly to refresh upcoming dates
       → UPSERT new stub rows into earnings_calendar
```

> [!IMPORTANT]
> The monthly refresh of `earnings_calendar` stubs ensures we always know upcoming earnings dates. This is independent of the daily trigger check.

### 3.5 — File Changes

#### [MODIFY] [fundamental_engine.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_engine.py)

Add `source='yfinance'` parameter and new methods:
- [__init__](file:///c:/Users/Hang/PycharmProjects/quantamental/src/shares_engine.py#27-29): accept `db_path` and `source` params. When `source='yfinance'`, store to DuckDB instead of parquet
- `_ensure_tables()`: create [fundamentals](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_engine.py#272-320) and `earnings_calendar` tables
- `_fetch_from_yfinance(ticker)`: call the 3 statement APIs + earnings_dates
- `_map_period_end_to_filing_date()`: mapping logic above
- `_upsert_to_duckdb(ticker, combined_df)`: write to [fundamentals](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_engine.py#272-320) table
- `refresh_earnings_calendar(tickers)`: monthly call to `get_earnings_dates()`
- `get_tickers_with_pending_earnings(target_date)`: query `earnings_calendar` for unconfirmed rows ≤ today

Existing FMP methods remain but are only used when `source='fmp'`.

#### [MODIFY] [daily_pipeline_orchestrator.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/orchestrators/daily_pipeline_orchestrator.py)

- Change [FundamentalEngine](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_engine.py#25-659) init to use `source='yfinance'`, remove `force_cache_only=True`
- Phase 1.2: call `fund_engine.update_fundamentals(tickers=price_tickers)` which internally checks `earnings_calendar` for due tickers
- Add monthly earnings calendar refresh (check last refresh date, only run if >30 days stale)

#### Downstream consumers (no changes needed for now)

The [FundamentalMerger](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_merger.py#25-573) currently reads from parquet via `FundamentalEngine.get_ticker_fundamentals()`. We update this single method to read from DuckDB [fundamentals](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_engine.py#272-320) table instead of parquet. The merger's as-of join logic stays unchanged since `filing_date` is now properly populated.

> [!WARNING]
> **`filing_date` NULL handling**: yfinance only returns the last 4-5 quarters, so older rows migrated from parquet will have `filing_date IS NULL`. The merger's as-of join will silently drop these rows. Decision required before implementation: either (a) accept the data gap (clean break — parquet history is abandoned), or (b) backfill `filing_date` for historical rows using `earnings_calendar` data before switching the merger over.

> [!NOTE]
> **Monthly calendar refresh persistence**: The plan states "check last refresh date, only run if >30 days stale" but does not specify where the last-refresh timestamp is stored. Options: (a) add a `last_calendar_refresh` column to a metadata table (e.g., reuse `pipeline_runs`), or (b) add a dedicated `earnings_calendar_meta` row keyed by `ticker = '__GLOBAL__'`. Must be decided before implementing the monthly refresh trigger.

> [!NOTE]
> **`update_fundamentals_cache` deprecation**: Module 3 replaces this method with `update_fundamentals()`. The old FMP cache-only method should be explicitly removed (or gated behind `source='fmp'`) to avoid dead code. Confirm removal as part of Module 3 implementation.

---

## TODOs (out of scope)

- [ ] **Universe discovery**: Phase 1.0 sub-step to discover and onboard new US tickers not yet in [price_data](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_merger.py#120-157) (reference: all US exchange tickers, monthly refresh)
- [ ] **Historical fundamentals backfill**: yfinance `get_income_stmt()` only returns last 4-5 quarters. Need SEC EDGAR / edgartools for decade-scale backfill. Schema designed here accommodates this.
- [ ] **`screener_criteria_extra`**: flexible key-value criteria table for ad-hoc filters (industry, etc.)
- [ ] **`screener_membership_history`**: point-in-time membership audit log

---

## Verification Plan

### Automated Tests

Since the existing tests in `tests/` cover feature preprocessing, M01 evaluator, M03 features, metrics, and rehydration — none directly test the orchestrator, screener_manager, or fundamental_engine. We'd need new tests:

1. **Module 1 — Orchestrator decoupling**: Verify Phase 1 no longer queries [screener_members](file:///c:/Users/Hang/PycharmProjects/quantamental/src/orchestrators/daily_pipeline_orchestrator.py#498-510)
   - Write a test that runs [_run_phase_1_t1_ingestion](file:///c:/Users/Hang/PycharmProjects/quantamental/src/orchestrators/daily_pipeline_orchestrator.py#395-497) with mocked engines and asserts fundamentals/shares are called with `price_tickers` not `screener_tickers`
   - Command: `cd c:\Users\Hang\PycharmProjects\quantamental && .venv\Scripts\activate && python -m pytest tests/test_orchestrator_decoupling.py -v`

2. **Module 2 — Criteria versioning**: Verify `_get_active_criteria()` returns correct criteria for different dates
   - In-memory DuckDB test: insert 2 criteria versions at different dates, assert correct one is returned for a query date between them
   - Command: `cd c:\Users\Hang\PycharmProjects\quantamental && .venv\Scripts\activate && python -m pytest tests/test_screener_criteria.py -v`

3. **Module 3 — yfinance fundamentals**: Verify mapping logic and DuckDB storage
   - Test `_map_period_end_to_filing_date()` with known AAPL data (verified in our research)
   - Test `_upsert_to_duckdb()` writes and reads correctly from in-memory DuckDB
   - Command: `cd c:\Users\Hang\PycharmProjects\quantamental && .venv\Scripts\activate && python -m pytest tests/test_yfinance_fundamentals.py -v`

### Manual Verification

These steps require running the actual pipeline and should be done by the user after modules are wired up:

1. **Module 1**: Run `python scripts/run_daily_pipeline.py --dry-run --verbose` and confirm Phase 1 logs show "Price universe: N tickers from price_data" as the universe for *all* sub-phases (no "screener_members" references)
2. **Module 2**: Insert a new criteria row in `screener_criteria_versions` with different thresholds, re-run Phase 2 and verify the new thresholds are applied
3. **Module 3**: Run Phase 1 for a date known to have earnings (e.g. 2025-01-30 for AAPL) and verify the [fundamentals](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_engine.py#272-320) table is populated with correct `filing_date` and `period_end`
