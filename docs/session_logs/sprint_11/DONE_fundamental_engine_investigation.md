# Fundamental Engine Debugging & Investigation Findings

> **STATUS: CLOSED — 2026-05-27.** All three flaws fixed structurally and verified against the live DB. See "Resolution" section at the bottom.
>
> **2026-05-28 follow-up:** Filing-date data quality addressed. See "Filing-Date Quality Follow-Up" section at the bottom.


## Overview
This document summarizes the investigation into the `fundamental_engine.py` data pulling logic and why Q1 2026 fundamentals are largely missing from the database. It also covers a spot check of specific tickers (`MU` and `TSLA`) and identifies tech debt within the SQL views.

## 1. Spot Checks: MU and TSLA
A targeted check was performed on `MU` and `TSLA` to confirm if Q1 earnings are being pulled in a timely manner. Both are missing, and they highlight two distinct failure modes:

* **`MU` (Micron):** 
  * `fundamentals` ends at `2025-11-30`. 
  * There are **zero rows** for `MU` in the `earnings_calendar`. Because it has no unconfirmed dates, `update_fundamentals` completely ignores it and its data is frozen.
* **`TSLA` (Tesla):** 
  * `fundamentals` ends at `2025-12-31` (Q1 missing). 
  * `earnings_calendar` has Tesla's Q1 reporting date (`2026-04-21`) logged, but it is incorrectly marked as `is_confirmed = TRUE`.

## 2. Root Causes of Fundamentals Failure
The pipeline relies on `earnings_calendar` to trigger fundamental data pulls from Yahoo Finance. However, there are three distinct flaws working together to starve the database of updates:

### Flaw 1: Trigger Deadlock (The Orchestrator Flaw)
* **What happens:** The daily pipeline (`Phase 1`) contains a check `_should_refresh_earnings_calendar()` to determine if the monthly calendar refresh should run. It queries: `SELECT COUNT(*) FROM earnings_calendar WHERE updated_at >= [start_of_month]`.
* **The impact:** Because `update_fundamentals` runs daily and sets `updated_at = CURRENT_TIMESTAMP` every time it confirms an earnings report, the `earnings_calendar` is updated almost every day. Therefore, the orchestrator constantly thinks the "monthly refresh" has already occurred and skips fetching new calendar dates from `yfinance`.

### Flaw 2: "Silent Skip" Contamination (The TSLA Flaw)
* **What happens:** When `refresh_earnings_calendar` *does* manage to run (e.g., if forced manually), it pulls dates from Yahoo. If the company has already reported recently (like `TSLA` in April), Yahoo returns the `Reported EPS`. The script detects this and **immediately inserts the row as `is_confirmed = TRUE`**.
* **The impact:** Because the calendar row goes straight to `TRUE`, `update_fundamentals` skips it forever (since it only targets tickers where `is_confirmed = FALSE`). This effectively means any ticker that reports *before* our calendar is refreshed will never have its fundamentals downloaded for that quarter.

### Flaw 3: Ghost Tickers (The MU Flaw)
* **What happens:** If a ticker drops out of the `earnings_calendar` completely (or never made it in), the pipeline has no fallback mechanism to re-discover it or queue it for a refresh.
* **The impact:** Its fundamentals remain permanently frozen at the last known quarter.

## 3. View Duplications & Tech Debt
A review of the Phase 6 views revealed the following explicit duplications (some of which are noted as tech debt in the manual):

1. **`v_screener_dashboard` vs `v_d1_candidates`**: 
   * This is the heaviest duplication. Both views independently calculate the complex SEPA session boundary logic (`C1+C2+C6` transitions) using identical, computationally expensive window functions over `t2_screener_features`. They should ideally share a materialized intermediate table.
2. **`v_d1_trades`**: 
   * This is just a backward-compatible alias (`SELECT * FROM v_d1_candidates`). 
3. **`v_d2r_hydrated`**: 
   * Another backward-compatible alias (`SELECT * FROM v_d2_hydrated`).

---

## 4. Resolution (2026-05-27)

### Code fixes
| Flaw | Location | Fix |
|------|----------|-----|
| 1. Trigger deadlock | `src/orchestrators/daily_pipeline_orchestrator.py:_should_refresh_earnings_calendar` | Now gates on `MAX(completed_at) WHERE phase_name='phase_1_earnings_calendar_refresh' AND status='success'` from `pipeline_runs`, configurable via `config.EARNINGS_CALENDAR_REFRESH_DAYS` (default 7). The refresh call is wrapped in `start_phase`/`complete_phase` so the gate has an authoritative signal independent of any row-touch side effects. |
| 2. Silent skip contamination | `src/fundamental_engine.py:refresh_earnings_calendar` | Always inserts `is_confirmed = FALSE`. ON CONFLICT clause no longer writes `is_confirmed` at all — preserves whatever `_mark_earnings_confirmed` set. The only path to TRUE is a successful fundamentals upsert. |
| 3. Ghost tickers | `src/fundamental_engine.py:update_fundamentals` | `to_fetch = union(pending_earnings, stale_fundamentals)`. Staleness was previously a fallback only triggered when the pending list was empty; it's now co-equal. Staleness threshold: `config.FUNDAMENTAL_STALENESS_DAYS` (default 100). |

### New non-destructive backfill path
* `FundamentalEngine.backfill_fundamentals()` + `_insert_to_duckdb_no_overwrite()`: `INSERT … ON CONFLICT (ticker, period_end) DO NOTHING`. Daily UPSERT semantics (which must overwrite to pick up restatements) are unchanged.
* `scripts/backfill_fundamentals.py --source yfinance --no-overwrite` exposes it.

### One-shot backfill results (2026-05-27)
* **Tickers attempted**: 4,176 (all equities)
* **Rows inserted**: 4,369 (across 3,628 tickers; 548 fetch failures from yfinance)
* **FMP rows touched**: **0** — the 294,731 authoritative FMP rows were preserved as-is
* **Equity freshness shift**:
  * Fresh (≤ 100d): **35 → 3,547** (~100× improvement)
  * Stale (> 100d): **3,945 → 433** (remainder are yfinance unavailability, not bugs)
  * Ghost (zero rows): **1 → 1** (genuine yfinance gap)

### Spot-check verification
* **MU**: was frozen at `2025-11-30` → now `2026-02-28` (Q1 FY2026 ingested).
* **TSLA**: was frozen at `2025-12-31` → now `2026-03-31` (Q1 ingested — the very filing the silent-skip bug was hiding).

### Known follow-ups (non-blocking)
* The 434 stale tickers will be re-fetched every daily run until either yfinance returns data or they're marked inactive. Worth adding exponential backoff or an `is_fetch_failing` flag on `company_profiles` if it becomes noisy.
* View duplication (`v_screener_dashboard` vs `v_d1_candidates`) is **NOT** addressed by this work — still tech debt, tracked separately.

---

## 5. Filing-Date Quality Follow-Up (2026-05-28)

The Phase 1 daily-pipeline warning `[Phase 1] DQ: 4 fundamentals with filing_date <= 7d after period_end. Sample: AMS (0d), AIRS (0d), ALTI (0d), AMZE (1d)` exposed a separate data-quality issue: yfinance was returning the **earnings-announcement date** (sometimes the period_end itself) as `filing_date`, not the actual 10-Q filing date.

### Investigation
* yfinance rows had filing_date NULL **94.7% of the time** (5,965 / 6,301 rows) vs FMP rows at **1.2% NULL**.
* `_fetch_from_yfinance` itself returns filing_date correctly when yfinance provides one (verified on AAPL: 5/5 populated).
* The dominant cause was historical data inserted before recent fixes — not an ongoing bug in the current fetch path.
* A small subset of rows had filing_date <= 7d after period_end — these were announcement dates, not filings (real 10-Q filings take 8+ days, typically 20-45).

### Fixes
| Component | File | Change |
|-----------|------|--------|
| Sanitiser at upsert gate | `src/fundamental_engine.py` (`_sanitize_filing_dates`) | NULL out any incoming `filing_date` with gap < 8d from `period_end`. Wired into both `_upsert_to_duckdb` and `_insert_to_duckdb_no_overwrite`. Logs sample at INFO. |
| Constant | `src/fundamental_engine.py:_MIN_REAL_FILING_GAP_DAYS = 8` | Minimum real 10-Q filing gap. |
| One-shot cleanup | (SQL, applied 2026-05-28) | 4 legacy bogus rows nulled (`UPDATE fundamentals SET filing_date = NULL WHERE … DATE_DIFF('day', period_end, filing_date) < 8`). |
| New backfill | `FundamentalEngine.backfill_filing_dates()` + `scripts/backfill_filing_dates.py` | Surgical UPDATE — only sets `filing_date` where currently NULL on yfinance rows. Never touches numeric columns. Cannot reintroduce bogus dates (same sanitiser logic). |
| DQ check upgrade | `daily_pipeline_orchestrator._check_filing_date_quality` | Now emits two warnings: (a) any remaining legacy rows with gap < 8d, (b) tickers with NULL or stale (>100d) latest filing_date. |

### Results
* **Bogus rows**: 4 → 0 (cleanup + sanitiser prevents new ones).
* **NULL filing_dates on yfinance rows**: 5,969 → 3,979 (1,990 recovered, 33%).
* The remaining 3,979 NULLs are dominated by Q1 2026 (2,960 rows) where yfinance only has the announcement date — correctly rejected by the 8-day guard. These will populate organically over the next 30-45 days as real filings hit.

### Important note: model impact
This work is **DQ infrastructure only — models are unaffected.**
* `v_d2_training` and `v_d3_deployment` do not reference `filing_date`.
* The model scores off numeric features (revenue, net income, etc.) joined on `(ticker, date)`.
* The earlier fundamentals-staleness issue (Section 4) DID affect model scoring up to 2026-05-27 — fixed by the structural fixes. Today's pipeline scores against current fundamentals.
