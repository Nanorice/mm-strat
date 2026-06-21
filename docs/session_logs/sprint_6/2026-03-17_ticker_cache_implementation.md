# Feature: Ticker Discovery Caching

## Problem
Running `python scripts/run_universe_backfill.py --discover` would:
1. Hit yfinance.screen() rate limiting (fails after first page or two)
2. Silently fail and exit mid-discovery
3. Force user to retry repeatedly, waiting 1-2 hours each time

## Solution: Smart Caching Layer

Implemented a JSON-based cache for discovered tickers:

### How It Works

1. **First run** (cache miss):
   ```bash
   python scripts/run_universe_backfill.py --discover
   # Discovers 4,550+ tickers from yfinance.screen(), caches them
   ```
   - Output: `Step 1: Paginate yfinance.screen() for US tickers...`
   - Saves tickers to `data/ticker_discovery_cache.json`
   - Takes ~1-2 hours (limited by yfinance rate limiting)

2. **Subsequent runs** (cache hit):
   ```bash
   python scripts/run_universe_backfill.py --discover
   # Loads cached tickers instantly
   ```
   - Output: `Step 1: Loaded 4,550 tickers from cache`
   - Takes ~100ms
   - Cache auto-refreshes if >7 days old

3. **Force re-discovery**:
   ```bash
   python scripts/run_universe_backfill.py --discover --force-refresh
   # Bypass cache, re-query yfinance
   ```
   - Use when yfinance adds new tickers
   - Takes ~1-2 hours

### Cache Details

**File**: `data/ticker_discovery_cache.json`

**Format**:
```json
{
  "cached_at": "2026-03-17T16:29:29.910252",
  "ttl_days": 7,
  "count": 4550,
  "tickers": ["AAPL", "MSFT", "GOOGL", ...]
}
```

**TTL**: 7 days (weekly refresh)
- If cache is <7 days old → use cached tickers
- If cache is ≥7 days old → re-discover from yfinance
- Threshold configurable in `src/universe_backfill.py`: `TICKER_CACHE_TTL_DAYS = 7`

### Implementation Details

**New methods in `UniverseBackfillEngine`**:
- `_load_ticker_cache()`: Load from JSON, check TTL
- `_save_ticker_cache(tickers)`: Save discovered tickers to JSON

**Modified methods**:
- `discover_tickers(use_cache=True, force_refresh=False)`: Added cache parameters

**New CLI flags**:
- `--force-refresh`: Force re-discovery from yfinance (bypass cache)

### Benefits

✅ **~100ms discovery** after first run (vs 1-2 hours)
✅ **Resilient to rate limiting** — cache survives yfinance failures
✅ **Automatic refresh** — weekly TTL prevents stale ticker list
✅ **Zero config** — cache is automatic, no API keys needed
✅ **Opt-in bypass** — `--force-refresh` flag for manual updates

### Example Workflows

**Initial discovery + price backfill** (~1-2 hours):
```bash
python scripts/run_universe_backfill.py --discover --backfill-prices
```

**Daily/weekly metadata updates** (~100ms):
```bash
python scripts/run_universe_backfill.py --discover
```

**Quarterly full refresh** (when yfinance adds new tickers):
```bash
python scripts/run_universe_backfill.py --discover --force-refresh
```

## Files Changed

- `src/universe_backfill.py`:
  - Added imports: `json`, `datetime`
  - Added constants: `TICKER_CACHE_PATH`, `TICKER_CACHE_TTL_DAYS`
  - Added methods: `_load_ticker_cache()`, `_save_ticker_cache()`
  - Modified `discover_tickers()` to use cache

- `scripts/run_universe_backfill.py`:
  - Updated docstring with cache usage examples
  - Added `--force-refresh` CLI flag
  - Updated main logic to pass `force_refresh` to `discover_tickers()`

## Future Improvements

1. **FMP Screener integration**: Use FMP instead of yfinance (no rate limiting)
   - Would reduce first discovery from 1-2 hours → 2-3 seconds
   - Requires FMP_API_KEY in `.env`

2. **Cache expiration notifications**:
   - Alert user when cache is nearing TTL expiration
   - Suggest running `--force-refresh` to update

3. **Cache versioning**:
   - Track ticker list schema changes
   - Invalidate cache if yfinance API changes
