# Ticker Discovery Strategy: Caching + Rate Limiting Workaround

## Problem Statement

Running `python scripts/run_universe_backfill.py --discover` experiences:
- **Rate limiting**: yfinance.screen() hits aggressive rate limits after 1-2 pages
- **Silent failures**: Exceptions are caught, script exits without completing
- **No resilience**: No cache, so every discovery must hit the API
- **High latency**: 1-2 hours per run due to throttling + retries

## Solution Architecture

### Level 1: Caching (IMPLEMENTED) ✅

**File**: `data/ticker_discovery_cache.json`

**Behavior**:
1. On first run → discover tickers from yfinance.screen(), save to JSON
2. On subsequent runs → load from JSON instantly (<100ms)
3. Auto-refresh if cache >7 days old
4. Manual override with `--force-refresh` flag

**Benefits**:
- ✅ Instant discovery after first run
- ✅ Survives yfinance outages
- ✅ Prevents repeated rate-limit hammering
- ✅ No dependencies (JSON, not a database)

**Downside**:
- ❌ First run still takes 1-2 hours
- ❌ Can't distinguish new vs delisted tickers

### Level 2: Alternative Data Source (FMP) [OPTIONAL]

**For future enhancement**: Use FMP Screener instead of yfinance.screen()
- Returns all 10K tickers in **1 request** (~2-3 seconds)
- Provides market_cap, exchange metadata directly
- Requires `FMP_API_KEY` in `.env` (you have this configured)
- Would reduce first discovery: 1-2 hours → 2-3 seconds

**Implementation**:
```python
def discover_tickers_via_fmp(self) -> List[str]:
    """Get all US tickers from FMP screener (no rate limits)."""
    # Uses config.FMP_SCREENER_PARAMS
    # Returns 10K+ tickers in 1 request
```

Then modify discovery to:
```python
if FMP_API_KEY and use_fmp:
    tickers = self._discover_tickers_via_fmp()  # 2-3 seconds
else:
    tickers = self._load_ticker_cache()  # ~100ms (cached)
    if not tickers:  # Cache miss/stale
        tickers = self._discover_via_yfinance()  # 1-2 hours + rate limiting
```

## Current Implementation (v1)

### Files Changed

1. **src/universe_backfill.py**:
   - Added cache I/O methods: `_load_ticker_cache()`, `_save_ticker_cache()`
   - Modified `discover_tickers()` to accept `use_cache=True, force_refresh=False`
   - Added retry logic to `_fetch_company_profiles()` (exponential backoff)
   - Added all-ticker coverage (no more silent skip of failed metadata fetches)

2. **scripts/run_universe_backfill.py**:
   - Added `--force-refresh` CLI flag
   - Updated docstring with cache usage examples
   - Enhanced help text

### Usage

**First run** (builds cache):
```bash
python scripts/run_universe_backfill.py --discover
# Discovers 4,550 tickers from yfinance (1-2 hours)
# Saves to data/ticker_discovery_cache.json
# Then fetches metadata for each ticker
```

**Typical run** (uses cache):
```bash
python scripts/run_universe_backfill.py --discover
# Loads cached tickers (~100ms)
# Fetches metadata for new tickers (if any)
# Cache auto-refreshes after 7 days
```

**Force refresh** (bypass cache):
```bash
python scripts/run_universe_backfill.py --discover --force-refresh
# Ignores cache, re-discovers from yfinance (1-2 hours)
# Updates cache for next run
```

### Cache Format

**File**: `data/ticker_discovery_cache.json`

```json
{
  "cached_at": "2026-03-17T16:29:29.910252",
  "ttl_days": 7,
  "count": 4550,
  "tickers": ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", ...]
}
```

### Workflow Examples

**Scenario A: Initial setup**
```bash
# Day 1: Discover tickers (1-2 hours)
python scripts/run_universe_backfill.py --discover

# Day 1: Backfill prices (8-15 hours)
python scripts/run_universe_backfill.py --backfill-prices

# Day 3: Backfill shares (1-2 hours)
python scripts/run_universe_backfill.py --backfill-shares

# Total: ~10-20 hours over 3 days
```

**Scenario B: Daily metadata check**
```bash
# Daily: Quick check (cache hit, ~100ms)
python scripts/run_universe_backfill.py --discover

# Weekly: Full refresh if needed
python scripts/run_universe_backfill.py --discover --force-refresh
```

**Scenario C: Handle failed discovery**
```bash
# If previous discovery failed (hit rate limit)
python scripts/run_universe_backfill.py --discover --force-refresh

# Cache will have latest successful result on next run
```

## Rate Limiting Workarounds

### Issue: yfinance.screen() rate limiting

**Root cause**: yfinance server limits concurrent requests from single IP

**Current mitigation** (implemented):
1. Cache reduces API calls from ~52 per week to 1-2 per month
2. Retry logic with exponential backoff (2^attempt seconds)
3. Saves checkpoint every page (could resume on failure)

**Future improvements**:
1. Use FMP Screener (no rate limiting)
2. Implement proxy rotation (complex, not recommended)
3. Add exponential backoff to `_discover_via_yfinance()` between pages
4. Save progress checkpoints (resume mid-discovery)

## Testing

To verify cache behavior:

```bash
# Test 1: Cache loads correctly
python -c "
from src.universe_backfill import UniverseBackfillEngine
engine = UniverseBackfillEngine('data/market_data.duckdb')
tickers = engine._load_ticker_cache()
print(f'Loaded {len(tickers)} cached tickers')
"

# Test 2: Discover with cache
python scripts/run_universe_backfill.py --discover --status

# Test 3: Check cache file
cat data/ticker_discovery_cache.json | python -m json.tool
```

## Next Steps

1. **Run discovery on fresh yfinance** (after rate limit resets)
   - Build initial cache with all 4,550 US tickers
   - Should see: `[OK] Fetched 4,550 profiles (4,281 with missing metadata)`

2. **Test cache workflow**:
   - Re-run `--discover` → should load from cache instantly
   - Verify `data/ticker_discovery_cache.json` exists

3. **Optional: Implement FMP Screener**
   - Would solve rate limiting entirely
   - Estimated effort: 2-3 hours
   - Would reduce first discovery: 1-2 hours → 2-3 seconds

## Configuration

**Cache TTL**: 7 days
- Edit `src/universe_backfill.py`: `TICKER_CACHE_TTL_DAYS = 7`
- Cache auto-refreshes if older than 7 days

**Cache location**: `data/ticker_discovery_cache.json`
- Configurable via `TICKER_CACHE_PATH` constant
- Stored as human-readable JSON

**Retry logic**: 2 attempts with exponential backoff
- First failure: wait 1 second, retry
- Second failure: skip ticker, log debug message
- Edit in `_fetch_company_profiles()`: `max_retries = 2`

## Known Limitations

1. **First discovery is slow** (~1-2 hours due to rate limiting)
   - Mitigation: Only need to run once per week
   - Better solution: Switch to FMP Screener (2-3 seconds)

2. **Can't detect new vs delisted tickers**
   - Cache contains static list from last discovery
   - Mitigation: Manual `--force-refresh` after new listings
   - Could enhance with differential updates in future

3. **yfinance metadata fetches still slow**
   - ~4,550 tickers × 1 request each = ~4,550 API calls
   - Takes ~45-60 minutes per full run (even with cache)
   - Mitigation: Only fetch metadata for new tickers
