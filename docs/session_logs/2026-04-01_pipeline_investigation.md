# Pipeline Investigation — 2026-04-01

## 1. SXI Timeout Error
**`curl: (28) Operation timed out after 10013 milliseconds`**

- Network-level timeout (10s curl limit), not a rate limit (429).
- `data_engine.py` has 5 retries with exponential backoff — all 5 failed for SXI.
- SXI is a valid active ticker. One-off transient failure, will be re-fetched on next run.

---

## 2. Error Handling / Rate Limit / Retry Summary

**What we have:**
| Layer | Mechanism |
|---|---|
| Per-request throttle | 0.2s fixed delay between FMP calls (300/min cap) |
| 429 rate limit | Exponential backoff: `3*(attempt+1) + jitter`, plus 5s global cooldown |
| 5xx / timeout / conn error | 5 retries with exponential backoff |
| Post-batch retry | `update_cache()` waits 10s then retries all failed tickers with reduced parallelism (3 workers) |
| Phase-level tracking | Logs `"X/Y OK, Z failed (N%)"` per sub-phase |

**What we DON'T have (acceptable for now):**
- No aggregated failure report across sub-phases — each tracks independently.
- No delayed bulk retry within same run — failed tickers retry on next daily run.
- No persistent failure table — failures logged to daily log file only.

**Decision**: Not building `pipeline_failures` table or `--retry-failures` now. Daily log files (per-date) provide sufficient audit trail. Can revisit if recurring failures emerge.

**FIXED**: Log files now rotate daily: `logs/daily_pipeline_YYYY-MM-DD.log`. Multiple runs per day append to same day's file with timestamp separators.

---

## 3. Earnings Calendar — Only 153 Tickers with Data ✅ FIXED

**Root cause**: `refresh_earnings_calendar()` was fetching ALL ~3981 active tickers, even though most already had a known future earnings date or returned empty.

**Fixes applied** ([fundamental_engine.py](src/fundamental_engine.py)):
1. **Smart filtering**: New `_get_tickers_needing_earnings_refresh()` skips tickers that already have a future unconfirmed earnings date. Reduces API calls from ~3981 → ~3790 (and shrinking as calendar fills).
2. **Only store confirmed earnings**: `_fetch_one` now filters out unconfirmed/future rows (`is_confirmed=False`). We don't need to store earnings that haven't been reported yet — those are estimates, not actuals.
3. **Error counting**: Progress logs now include error count: `"500/3790 fetched, 152 with data, 23 errors"`. Errors were previously silent (DEBUG level only).
4. **Completion summary**: Final log line shows total processed, with data, and errors.

---

## 4. FutureWarning — DataFrame Concatenation ✅ FIXED

**Root cause**: `pd.concat(fetched)` where some DataFrames had all-NA columns (e.g., `eps_surprise_pct` for unconfirmed earnings). Pandas 2.x warns about type inference for these columns.

**Fix**: By filtering to confirmed-only rows in `_fetch_one`, DataFrames now always have populated `reported_eps` values, eliminating the all-NA column scenario.

---

## 5. DQ Warning — Filing Date <= 7d After Period End

**What it means**: yfinance mapped earnings announcement date instead of SEC filing date for some rows. Gap of 1-7 days vs expected 20-40 days.

**Scope**: 245 rows out of 291,437 (0.08%). Distribution:
- gap=1d: 44 rows | gap=2d: 55 | gap=3d: 64 | gap=4d: 19 | gap=5d: 14 | gap=6d: 26 | gap=7d: 23
- Mostly historical (pre-2020). Only 23 rows in 2025.
- Top offenders: TILE (9), SBET (9), RMCF (5), ARCT (4)

**Impact**: Conservative (earnings date is earlier than filing date, so no lookahead bias). Not worth a one-off fix at 0.08%. The DQ warning is working as intended.

---

## 6. "2742 Tickers" — Screener Membership Filter

**Yes, this is the screener filter.** Phase 2 runs `screener_manager.evaluate_and_log()`:
- Price >= $5, 20d avg volume >= 100K, Market cap >= $150M
- ~3981 active → ~2742 pass criteria on this date
- **Working as designed.** Count varies daily.

---

## 7. Cross-Sectional Ranks: 0 Rows ✅ ROOT CAUSE FOUND & FIXED

**Root cause**: `warmup_days=365` was exactly on the edge.

**The math**:
- `LAG(close, 252)` needs 253 trading days in the window
- 365 calendar days ≈ 252 trading days (exact match, not enough)
- Incremental run for 2026-04-01: `fetch_start = 2025-04-01` → **0 tickers** had 253+ rows
- Previous batch for 2026-03-31: `fetch_start = 2025-03-30` (2 extra days) → **2320 tickers** had enough

**DB evidence**:
```
fetch_start=2025-03-30: 2319 tickers with >= 253 rows ← matches 2320 rs values on 03-31
fetch_start=2025-04-01:    0 tickers with >= 253 rows ← matches 0 rs values on 04-01
```

**Fix**: Increased `warmup_days` from 365 → 400 in `compute_t2_screener_features()`. 400 calendar days ≈ 280 trading days, providing ~28 days of margin above the 252 needed.

---

## 8. Breakout Drought: 0 Days

**Healthy state.** `_count_breakout_drought()` counts consecutive days with 0 T3 breakouts from most recent date backwards. **0 = breakouts found today.** A value >0 would trigger the drought alert.

---

## Changes Made

| File | Change |
|---|---|
| [feature_pipeline.py](src/feature_pipeline.py) | `warmup_days` default: 365 → 400 |
| [fundamental_engine.py](src/fundamental_engine.py) | New `_get_tickers_needing_earnings_refresh()` — skip tickers with known future dates |
| [fundamental_engine.py](src/fundamental_engine.py) | `refresh_earnings_calendar()` — only store confirmed earnings, error counting in logs |
| [run_daily_pipeline.py](scripts/run_daily_pipeline.py) | Daily log rotation: `daily_pipeline_YYYY-MM-DD.log` |

## Remaining TODOs

| Priority | Item |
|---|---|
| **P2** | Recompute 2026-04-01 t2_screener_features with new warmup (will happen on next pipeline run) |
| **P3** | Consider adding Phase C input row count logging for future debugging |
