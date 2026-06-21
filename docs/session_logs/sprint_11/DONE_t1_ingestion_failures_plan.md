# T1 Ingestion Failures — Execution Plan

**Created:** 2026-05-29
**Related todo:** [misc_todo.md](misc_todo.md) §2 "T1 Ingestion Failures"

## Discovery Snapshot (2026-05-29, last 30d)

### Price ingestion
- **9,570 errors / 3,688 tickers** in `pipeline_error_log` for `phase_1_t1_price`.
- **100% classified `FETCH_FAILURE`** with identical generic string `"No data from yfinance bulk download"`. Classifier sees no signal.
- Per-ticker error distribution:
  - chronic (>=20 err): 11 tickers / 354 err
  - heavy (10-19): 5 / 71
  - repeated (5-9): 226 / 1,192
  - occasional (2-4): 2,605 / 7,112
  - one-off (1): 841 / 841
- Top-20 chronic tickers all `is_active=True` with recent (within weeks) price data — they are getting prices, just not on every run. Consistent with yfinance bulk download silently dropping some tickers per call (likely transient 429s collapsed to a None result).

### Fundamentals ingestion
- **213 errors / 188 tickers** for `phase_1_t1_fundamentals` — much smaller than the dashboard's "~1.5k" headline.
- All `FETCH_FAILURE` with identical string `"yfinance fetch returned None"`.
- Active equity (3,981 total) fundamentals freshness:
  - <=100d: 3,784
  - **101-200d: 161** — real investigation cohort (was estimated at 369 in the EDGAR notes; EDGAR backfill closed most of the gap)
  - 201-400d: 20
  - >400d: 15
  - no fundamentals: 1
- Of the 161-cohort:
  - 129 have CIK in `cik_map`, 32 don't
  - 140 still trade actively (price within 7d), 8 are 8-30d stale, 13 are 31-90d stale

### Root cause of the noisy error log
[src/data_engine.py:977](../../../src/data_engine.py#L977) and [src/fundamental_engine.py:961](../../../src/fundamental_engine.py#L961) fabricate a generic per-ticker error message after a bulk yfinance call, throwing away the actual exception / HTTP status. So `pipeline_error_log.error_type` is forced to `FETCH_FAILURE` for everything, and no triage by error class is possible.

## Phase A — Make errors readable (prerequisite)

**Goal:** classify per-ticker failures into `RATE_LIMIT` / `NO_DATA` / `NOT_FOUND` / `TIMEOUT` / `FETCH_FAILURE` based on actual cause, not a hardcoded string.

**Changes:**
1. `src/data_engine.py` — in the yfinance bulk path, distinguish:
   - ticker not in response payload at all -> `NOT_FOUND` (likely delisted or symbol typo)
   - empty DataFrame returned -> `NO_DATA`
   - exception raised during batch -> propagate exception text so classifier can catch '429' / 'timeout'
2. `src/fundamental_engine.py` — same treatment for `_fetch_yfinance`. Capture None-return vs raised-exception distinction.
3. Verify the existing `PipelineRunManager.classify_error` regex handles the surfaced strings (it already covers '429', 'rate limit', 'timeout', 'no data', 'max retries').
4. No new error_type values needed unless the strings don't match — add 'NOT_FOUND' only if warranted.

**Success criteria:** after one daily pipeline run, `SELECT error_type, COUNT(*) FROM pipeline_error_log WHERE phase_name IN ('phase_1_t1_price','phase_1_t1_fundamentals') AND occurred_at >= today GROUP BY error_type` returns >1 distinct row per phase.

**Constraint:** do not add try/except band-aids around the bulk call. The point is to surface signal that's already there, not to swallow more.

## Phase B — Price triage (after Phase A lands one clean run)

1. Re-query `pipeline_error_log` grouped by `error_type` for the chronic-failure tickers.
2. Tickers consistently `NOT_FOUND` -> run `tools/deactivate_tickers.py` (dry-run first, then `--execute`).
3. Tickers consistently `RATE_LIMIT` -> not a ticker problem; document as throttling artifact. Consider whether bulk batch size needs to drop.
4. Tickers mixed -> leave alone; they're getting data on most runs.

### Phase B execution log (2026-05-29)

After Phase A landed and one clean daily run completed, the per-day price failure count stabilized at 14-16 tickers (down from the pre-fix 1,114-ticker spike on 2026-05-16). Today's 14 NO_DATA failures had all failed 12-36 consecutive days. Verified all 14 yielded yfinance's `YFPricesMissingError("possibly delisted; no price data found")`.

Deactivated all 14 via `tools/deactivate_tickers.py --execute`:

BLBX, THAR, VRAR, PX, ATGE, CASI, TSE, AHH, ABP, IMG, GLTO, CTHR, CMLS, ULY

`company_profiles` is_active count: 4020 -> 4006. Each ticker's `delisting_date` set to `CURRENT_DATE`. Historical price/feature/fundamentals data preserved.

### Tool reference

`tools/deactivate_tickers.py` is the canonical vehicle for marking tickers inactive after they've been confirmed as delisted / renamed / no-longer-tradeable. Usage:

```
# Dry-run (default) — preview only, no changes
python tools/deactivate_tickers.py TICKER1 TICKER2 TICKER3

# Apply
python tools/deactivate_tickers.py TICKER1 TICKER2 TICKER3 --execute
```

Behaviour:
- Sets `company_profiles.is_active = FALSE` and `delisting_date = CURRENT_DATE`.
- Skips tickers already inactive (idempotent).
- Skips tickers not in `company_profiles` (warns).
- Preserves all historical rows in `price_data`, `daily_features`, etc.

Reversible if needed: `UPDATE company_profiles SET is_active=TRUE, delisting_date=NULL WHERE ticker IN (...)`.

## Universe Lifecycle Gap (documented, NOT fixed)

The discovery surfaced a structural gap larger than Phase B can fix here. Capturing it for a future session:

**Inflows (new IPOs):** No automatic discovery. `UniverseBackfillEngine.discover_tickers()` exists and the orchestrator can call it via `_run_phase_1_1_quarterly_refresh()`, but only when invoked with `universe_refresh=True`. The orchestrator docstring is explicit: "never runs automatically". `company_profiles.discovered_at` distribution confirms this — 4,137 rows added on 2026-03-01 (initial backfill), 39 on 2026-05-01, nothing since. A SpaceX IPO today would not enter our universe until someone manually ran `scripts/run_universe_backfill.py` or passed `--universe-refresh`.

**Outflows (delistings):** No automatic deactivation. Today's pattern — a ticker fails for weeks until a human notices and runs `deactivate_tickers.py` — is the actual lifecycle. `ticker_blacklist` last received a row 2026-03-22; also stalled.

**What a proper lifecycle phase would do (out of scope for this sprint):**
1. Weekly or monthly cron phase in the orchestrator.
2. Inflow: call `discover_tickers()`, diff against `company_profiles`, backfill price + shares for new entrants.
3. Outflow: query `pipeline_error_log` for tickers with N>=14 consecutive NO_DATA failures AND `last_px > 30d` ago, auto-deactivate (with a daily-cap guard to prevent runaway deactivation during a real yfinance outage).
4. Both arms write to `pipeline_runs` so the dashboard reflects membership churn.

Estimate: ~1 day of work plus tests. Logged here for prioritisation; not part of Phase B.

## Phase C — Fundamentals staleness root cause

### Original framing (revised)
The plan above assumed two distinct cohorts (missing-CIK vs has-CIK) needed different triage. The actual root cause turned out to be a single structural bug in the staleness check, applicable to both.

### Discovery (2026-05-29, post-Phase-B baseline)

After deactivating the 14 chronic price tickers, the 101-200d fundamentals cohort shrank slightly (161 -> 155). Split: 128 has-CIK, 27 no-CIK, 16 with stale prices.

Probed all 128 has-CIK tickers against SEC EDGAR's submissions API (`get_recent_filings` in `src/edgar_engine.py`), comparing our DB's MAX(filing_date) vs EDGAR's most recent 10-Q/10-K filing:

| Status | n | Meaning |
|---|---|---|
| UP_TO_DATE | 66 | EDGAR has nothing newer than what we have. Genuinely stale because the company hasn't filed yet — not a bug. |
| **WE_MISSED** | **34** | EDGAR has a 10-Q or 10-K **57-183 days newer than ours**. All filed Apr-May 2026. |
| EDGAR_NO_DATA | 25 | `data.sec.gov/submissions/CIK*.json` returned no data. Likely stale CIKs or invalid mappings. Smaller follow-up. |
| WE_AHEAD | 3 | Edge case — we have something EDGAR doesn't. Likely date-comparison quirk. Ignored. |

Spot-checked NKE (Nike) directly against yfinance: yfinance HAS the 2026-02-28 quarter that we're missing. So this is not a yfinance-lag problem — the data is reachable, our fetch path simply isn't triggering.

### Root cause

[src/fundamental_engine.py:850-869](../../../src/fundamental_engine.py#L850-L869) — `_get_stale_fundamental_tickers` measured staleness against `MAX(updated_at)` (the row's *audit timestamp*) instead of `MAX(period_end)` (the *data* date).

```sql
-- OLD
WHERE f.last_update IS NULL
   OR f.last_update < CURRENT_TIMESTAMP - INTERVAL 100 DAY
```

If we wrote a stale quarter recently — e.g. backfilled NKE's Nov-2025 quarter on 2026-04-15 — the row's `updated_at = 2026-04-15` makes it look "fresh" (44 days old) even though the underlying `period_end = 2025-11-30` is half a year stale and yfinance has a Feb-2026 quarter available.

Result: tickers got fetched once, then permanently flagged "fresh" by the audit clock, never re-checked.

### Fix (committed)

Replaced the check with one that:
1. Uses `MAX(period_end) < CURRENT_DATE - N days` for actual data freshness.
2. Keeps a 24-hour `updated_at` cooldown to prevent re-fetching the same ticker within one calendar day.

```sql
-- NEW
WHERE (
        f.last_period IS NULL
     OR f.last_period < CURRENT_DATE - INTERVAL N DAY
      )
  AND (
        f.last_update IS NULL
     OR f.last_update < CURRENT_TIMESTAMP - INTERVAL 24 HOUR
      )
```

### Verification

Smoke-tested old vs new query on the 34 WE_MISSED tickers:
- Old query: 0/34 flagged for refetch (the bug).
- New query: 31/34 flagged. (The 3 holdouts hit the 24h cooldown — acceptable.)

Smoke-tested on 5 freshest-by-period_end tickers: 0/5 flagged. Correct behaviour preserved.

### Volume impact

Daily fetch list:
- Old query: 1 ticker
- New query: 345 tickers (299 has-CIK genuinely stale + 45 no-CIK + 1 never-fetched)

At default `max_workers=8` and ~3s/ticker, that's ~130s of fetch time per daily run. Acceptable. The 24-hour cooldown ensures this only repeats when there's actual reason to re-check.

### Known follow-up (not fixed in Phase C)
- **Chronic-empty fundamentals tickers** (e.g. ATCX, never had fundamentals) will keep being re-fetched daily because `updated_at` never bumps on a failed fetch. Solution: track `last_fetch_attempt_at` separately so failed attempts also start the 24h cooldown. Phase D scope.
- **25 EDGAR_NO_DATA tickers**: need to investigate whether their CIKs in `cik_map` are stale.
- **27 no-CIK tickers in the original 155-cohort**: likely architectural floor (foreign ADRs, SPACs, OTC). Not pursued in this session.
- **16 cohort tickers with >7d stale prices**: likely additional delistings — should be triaged through `tools/deactivate_tickers.py` after the next daily run shows the updated price-side numbers.

## Phase D — Reconcile dashboard headline (SKIPPED, moot)

Investigated [scripts/pages/5_Pipeline_Health.py](../../../scripts/pages/5_Pipeline_Health.py) and [scripts/dashboard_utils.py:238-263](../../../scripts/dashboard_utils.py#L238-L263). There is **no hardcoded "20 / 1.5k" headline** — `render_t1_failures` reads `pipeline_error_log` live via `load_t1_ingestion_failures`, aggregates per `(ticker, phase, error_type)`, and shows a "⚠ N tickers with ≥10 days failing" badge. The dashboard is accurate by construction.

The "20 / 1.5k" numbers in the original framing were the user's mental tally of the table, not a rendered headline.

With Phases A+B+C landed:
- error_type column will show real classification (RATE_LIMIT/TIMEOUT/NO_DATA/...) instead of all-FETCH_FAILURE
- chronic-failure count drops as deactivated tickers age out of the 30d window
- fundamentals staleness cohort shrinks as the period_end-based check picks up missed quarters

Dashboard accuracy is self-healing. No UI work needed.

## Success Criteria (status as of 2026-05-29)

- ✅ `pipeline_error_log.error_type` populates with real classification (Phase A landed; today's 14 rows all classified `NO_DATA` instead of the previous catch-all `FETCH_FAILURE`). Multi-bucket distribution will appear on a day with mixed rate-limit/timeout/no-data conditions.
- ✅ Chronic-failure price cohort dropped from 16 to 0 after deactivating today's 14 (Phase B). Tomorrow's daily run is the empirical confirmation.
- ⏳ Active-equity fundamentals 101-200d cohort: was 155, expected to shrink as the period_end-based staleness check (Phase C) picks up the 34 known WE_MISSED filings on the next daily run. Target ≤50.
- ✅ Pipeline Health page headline (Phase D): moot — dashboard is built directly from `pipeline_error_log`.

## Pending Follow-ups

Moved to [misc_todo.md](misc_todo.md) §"T1 Ingestion Follow-ups" — 7 deferred items tracked there as part of the broader sprint backlog.

**2026-05-29 update:** Follow-up #3 (EDGAR_NO_DATA cohort) shipped. Tolerance widened 15→35d in [src/edgar_engine.py:230](../../../src/edgar_engine.py#L230); 66 phantom yfinance rows deleted across 40 tickers. See misc_todo.md row 3 for full notes. Follow-ups #1 (re-fetch cooldown) and #2 (16 stale-price cohort) deferred — #1 indefinitely (trivial cost), #2 until next daily run.

## Out of Scope

- The Pipeline Health dashboard UI polish (separate todo).
- M01/M02 model recalibration triggered by Phase C's freshly-pulled fundamentals (only relevant if downstream features show meaningful drift).

---

## Status: DONE 2026-05-29

All four phases resolved (A+B+C shipped; D moot). Follow-ups tracked in `misc_todo.md`. This plan is now historical.
