# Phase 1 Follow-up: Orchestrator Fixes

> Created: 2026-03-21
> Status: TODO — resume next session
> Prerequisite: `phase_1_duckdb_direct_write.md` implementation is COMPLETE

---

## Context

Phase 1 refactor (direct-to-DuckDB price ingestion) is implemented. During walkthrough
of the execution trace, three structural issues were identified in the orchestrator and
related engines. This file tracks what needs to be fixed next.

---

## Issue 1 — Wrong universe source for fundamentals/shares sub-phases

**File:** `src/orchestrators/daily_pipeline_orchestrator.py`

**Problem:** `price_tickers` is queried from `price_data`:
```python
price_tickers = SELECT DISTINCT ticker FROM price_data ORDER BY ticker
```
This is used as the population passed to `fund_engine.update_fundamentals` and
`shares_engine.update`. It's semantically wrong — on a bootstrap run (empty
`price_data`) both sub-phases get an empty list and are skipped entirely.

**Fix:** Use `company_profiles` as the single source of truth:
```python
active_tickers = conn.execute(
    "SELECT ticker FROM company_profiles WHERE is_active = TRUE ORDER BY ticker"
).fetchall()
active_tickers = [t[0] for t in active_tickers]
```
Use `active_tickers` everywhere `price_tickers` is currently used.

---

## Issue 2 — `earnings_calendar` table is empty; fundamentals gating is dormant

**Files:** `src/fundamental_engine.py`, orchestrator Phase 1

**Problem:** `update_fundamentals` already has correct earnings-gating logic:
- Calls `get_tickers_with_pending_earnings(target_date)`
- Queries `earnings_calendar WHERE earnings_date <= today AND is_confirmed = FALSE`
- Only fetches tickers in that list; marks confirmed after write

But `earnings_calendar` has **0 rows** → `get_tickers_with_pending_earnings` always
returns `[]` → `to_fetch = []` → function returns immediately with all `True` →
**fundamentals are never actually fetched on any daily run.**

**Fix options (pick one):**
- **Option A** — Populate `earnings_calendar` via a pre-Phase-1 refresh step.
  `FundamentalEngine` has a `refresh_earnings_calendar(tickers)` method — wire it
  into the orchestrator quarterly refresh (Phase 1.1) or as a new Phase 0.
- **Option B** — Fall back to staleness-based logic: if a ticker has no fundamentals
  row newer than 90 days, fetch it regardless of earnings calendar.
- **Option C** — For now, pass `force=True` to `update_fundamentals` so it fetches
  based on a time-since-last-update heuristic rather than relying on the empty calendar.

**Recommendation:** Option A is architecturally correct. Check what
`refresh_earnings_calendar` does and whether it can be called cheaply (yfinance or FMP).

---

## Issue 3 — `get_latest_trading_day` called inside worker thread; should be pre-computed

**Files:** `src/data_engine.py` (`update_cache`), `src/orchestrators/daily_pipeline_orchestrator.py`

**Problem:** `get_latest_trading_day()` makes a yfinance API call (`yf.download('SPY', ...)`).
Currently it runs inside thread 1 (`update_cache`). It should be computed once at
orchestrator level before any threads are spawned, then passed in.

Same applies to `_get_stale_tickers` — computing the stale list before threading allows:
1. Short-circuit Phase 1 entirely if nothing is stale (no threads spawned)
2. Accurate pre-fetch logging (know count before work starts)
3. `active_tickers` for fundamentals/shares derived from the same pre-thread query

**Fix:**

In `_run_phase_1_t1_ingestion`:
```python
# --- Pre-thread setup (sequential, before ThreadPoolExecutor) ---
conn = duckdb.connect(self.db_path, read_only=True)
try:
    active_tickers = [t[0] for t in conn.execute(
        "SELECT ticker FROM company_profiles WHERE is_active = TRUE ORDER BY ticker"
    ).fetchall()]
finally:
    conn.close()

latest_trading_day = self._get_last_trading_day(target_date)
stale_tickers = self.data_repo._get_stale_tickers(latest_trading_day)

if not stale_tickers:
    logger.info("[Phase 1.1] Price already fresh — skipping price sub-phase")
    # still run fundamentals/shares/macro
```

In `update_cache` — add optional params so pre-computed values can be injected:
```python
def update_cache(
    self,
    tickers: List[str] = None,          # pre-computed stale list (skips staleness query)
    latest_trading_day: str = None,     # pre-computed (skips get_latest_trading_day call)
    ...
) -> Dict[str, bool]:
    if latest_trading_day is None:
        latest_trading_day = get_latest_trading_day()
        if isinstance(latest_trading_day, pd.Timestamp):
            latest_trading_day = latest_trading_day.strftime('%Y-%m-%d')

    if tickers is not None:
        to_update = tickers   # caller already computed the stale list
    elif force:
        ...
    else:
        to_update = self._get_stale_tickers(latest_trading_day)
```

---

## Implementation Order

1. **Issue 3 first** — pre-compute in orchestrator, inject into `update_cache`.
   Touches: `daily_pipeline_orchestrator.py` (Phase 1 setup block), `data_engine.py`
   (`update_cache` signature).

2. **Issue 1** — swap `price_data` for `company_profiles` as universe source.
   One-line change in orchestrator after Issue 3 is done (already using `active_tickers`).

3. **Issue 2** — earnings calendar population.
   Investigate `refresh_earnings_calendar` first; decide Option A/B/C.
   Likely a separate mini-session.

---

## Files to Touch

| File | Change |
|---|---|
| `src/orchestrators/daily_pipeline_orchestrator.py` | Pre-compute `latest_trading_day`, `stale_tickers`, `active_tickers` before threading; use `active_tickers` for fundamentals/shares |
| `src/data_engine.py` | `update_cache` accepts optional `tickers` + `latest_trading_day` params to skip internal queries when pre-computed |
| `src/fundamental_engine.py` | Investigate + fix earnings calendar population (Issue 2) |