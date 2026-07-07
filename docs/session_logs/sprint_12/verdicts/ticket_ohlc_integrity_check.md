# Ticket: price_data OHLC integrity check missing (next session)

**Status:** OPEN — NOT blocking m02 infra build (m02 targets already bound excursions
with close, so they are correct despite the dirt).

## Problem
`price_data` contains OHLC-inconsistent rows that violate `low <= {open,close} <= high`:
- **21,526 rows** with `high < close`
- **19,996 rows** with `low > close`
- **2,716 rows** with `high < open`
- `high < low`: 0 (so not fully corrupt — high/low just don't always bound open/close)

Source: penny-stock rounding / bad vendor ticks (e.g. ZCAR at $0.07–0.078). Discovered
2026-06-20 while building m02_prototype dense forward targets — naive `MAX(high)`/`MIN(low)`
forward excursions produced 4,468 rows violating MFE >= ret >= MAE (worst 1.43pp).

## Root cause
`src/evaluation/data_quality.py` has **NO OHLC integrity check**. The existing checks
cover warm-up sentinels and return-dominance, not basic bar consistency. So this class
of dirt has never been surfaced.

## Why it matters beyond m02
Any code that trusts high/low as true intraday extremes (excursion math, ATR, breakout
detection, stop-loss backtests) can be silently wrong on these ~41k rows.

## Proposed work (next session)
1. **Add an OHLC integrity check** to `data_quality.py`:
   `low <= LEAST(open, close)` AND `high >= GREATEST(open, close)` AND `high >= low`.
   Report counts per ticker; surface in the pipeline health / quality log.
2. **Decide remediation policy** — flag vs. repair vs. drop:
   - Repair option: clamp `high = GREATEST(high, open, close)`, `low = LEAST(low, open, close)`
     (same logic m02 applies defensively at read time).
   - Or quarantine offending tickers (mostly illiquid penny names — overlaps
     `project_bad_tickers_not_filtered` / `detect_bad_tickers`).
3. Backfill the check into the daily pipeline so new dirt is caught at ingestion.

## References
- Memory: `project_price_data_ohlc_dirt`
- m02 defensive handling: `scripts/build_m02_targets.py` (GREATEST/LEAST(close) bound)
- Related: `project_bad_tickers_not_filtered`, `project_price_data_adj_close_null`
