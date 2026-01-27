# How Did the Wrong Data Get Queried?

## Your Question
> How is the wrong data queried? For example, will it happen if I query start date as 1994 for RIVN then FMP will try to return the demised ticker from exchange?

## Answer: NO - FMP API Currently Works Correctly! ✅

### Test Results

I tested the FMP API with different `from` dates:

**Test 1: RIVN with from=1990-01-01 (31 years before IPO)**
```python
GET https://financialmodelingprep.com/api/v3/historical-price-eod/full?symbol=RIVN&from=1990-01-01

Result:
- Records: 1045
- Date range: 2021-11-10 to 2026-01-09  ✅
- Oldest record: 2021-11-10 (actual IPO date)
```

**Conclusion:** FMP **IGNORES** the `from` parameter if it's before the ticker's IPO. It only returns data from when the current company started trading.

### yfinance Test Results

**Test 2: yfinance with period="max"**
```python
yf.download('RIVN', period='max')

Result:
- Date range: 2021-11-10 to 2026-01-09  ✅
- No pre-IPO data returned
```

**Conclusion:** yfinance also works correctly and doesn't return data from previous companies that used the ticker symbol.

---

## So How Did Our Cache Get Corrupted?

### Key Evidence

1. **Cache files modified: 2026-01-10 19:27** (YESTERDAY!)
   - This is when the corruption happened
   - Not a historical issue - it's RECENT

2. **Four tickers (RIVN, RKLB, RKT, RITM) have IDENTICAL data:**
   - All start: 1994-11-07
   - All have: Close=$0.579885, Volume=1,142,100
   - Same 7,843 rows
   - This is NOT a coincidence - they got assigned the same file's data

3. **Different corruption for SNOW and U:**
   - SNOW starts 1980-01-02 (different wrong data)
   - U starts 1984-01-10 (different wrong data)

### Hypothesis: Cache Rebuild Gone Wrong

Since the FMP/yfinance APIs are working correctly TODAY, but the cache was corrupted YESTERDAY during a rebuild, here are the possible causes:

---

## Theory 1: Parallel Download Race Condition (MOST LIKELY)

**What Happened:**

```python
# In _fetch_price_worker (line 676-728)
# Multiple workers downloading in parallel:

Worker 1: Downloads RIVN data → Saves to RIVN.parquet
Worker 2: Downloads RKLB data → Saves to RKLB.parquet
Worker 3: Downloads RKT data → RACE CONDITION!
Worker 4: Downloads RITM data → RACE CONDITION!

# If there's a race condition in file naming or ticker assignment:
# Worker 3 might save RIVN's data to RKT.parquet
# Worker 4 might save RIVN's data to RITM.parquet
```

**Evidence Supporting This:**
- RIVN, RKLB, RKT, RITM have **IDENTICAL** data (all 7,843 rows match)
- All were modified at the **same time** (19:27:06-19:27:07 - 1 second apart!)
- This suggests parallel workers all got/saved the same data

**Code Location:**
```python
# src/data_engine.py line 713
cache_file = self.price_dir / f"{ticker}.parquet"
df.to_parquet(cache_file)  # ← NO FILE LOCKING!
```

**Problem:** If multiple workers try to write at the same time, or if ticker variable gets reassigned in shared scope, wrong data could be saved to wrong file.

---

## Theory 2: Ticker Symbol Mix-up in Batch Processing

**What Happened:**

If yfinance was used with batch downloads:

```python
# _update_cache_yfinance line 842-856
data = yf.download(['RIVN', 'RKLB', 'RKT', 'RITM'], ...)

# If ticker extraction fails:
for ticker in ['RIVN', 'RKLB', 'RKT', 'RITM']:
    ticker_data = self._extract_ticker_from_batch(data, ticker)
    # BUG: If 'ticker' not in batch response, might extract WRONG ticker
    # Or might extract first ticker's data for all
```

**Evidence:**
- Batch downloads can return MultiIndex DataFrames
- If ticker doesn't exist in batch response, extraction might fail
- Could default to first ticker's data

**Code Location:**
```python
# src/data_engine.py line 878-916
def _extract_ticker_from_batch(self, data: pd.DataFrame, ticker: str):
    if isinstance(data.columns, pd.MultiIndex):
        if ticker in data.columns.levels[0]:  # ← What if NOT in levels?
            df = data[ticker].copy()
        else:
            return None  # ← Returns None, but caller might not check
```

---

## Theory 3: FMP API Had a Temporary Bug Yesterday

**What Happened:**

FMP API might have had a temporary issue yesterday (2026-01-10) where:
- It returned wrong historical data for certain tickers
- OR returned data with wrong ticker symbols in response
- This was fixed by FMP today, which is why our tests show correct behavior

**Evidence:**
- Less likely because corruption is systematic (multiple tickers got same wrong data)
- Would require FMP to return identical wrong data for 4 different ticker queries

---

## How to Confirm the Root Cause

### Check 1: Review Your Cache Update Log

Do you have logs from yesterday's cache rebuild? Look for:

```bash
# Check if cache was updated yesterday
grep "2026-01-10" build_dataset_a_log.txt

# Or check git/command history
git log --since="2026-01-10" --until="2026-01-11"
```

### Check 2: Look at Code Version Used Yesterday

```python
# What was in data_engine.py when cache was rebuilt?
git log -p --since="2026-01-09" -- src/data_engine.py

# Check if parallel download was enabled
grep -n "max_workers" src/data_engine.py
```

### Check 3: Test Parallel Download with Logging

```python
# Add debug logging to _fetch_price_worker
def _fetch_price_worker(self, ticker: str, max_retries: int = 3):
    logger.info(f"[Worker {threading.current_thread().name}] Downloading {ticker}")

    # ... download logic ...

    logger.info(f"[Worker {threading.current_thread().name}] Saving {ticker} to {cache_file}")
    df.to_parquet(cache_file)
    logger.info(f"[Worker {threading.current_thread().name}] Completed {ticker}")
```

---

## The Answer to Your Question

### Direct Answer:

**NO**, querying FMP with `from=1994` for RIVN will **NOT** return data from a demised ticker. FMP correctly returns only data from the current company (starting 2021-11-10).

### What Actually Happened:

The corruption happened during **cache rebuild on 2026-01-10** due to a bug in OUR code, most likely:

1. **Race condition** in parallel downloads causing ticker mix-up
2. **Batch extraction bug** causing wrong ticker data to be saved
3. **Variable scope issue** where `ticker` variable gets overwritten

The corruption is **NOT from FMP API behavior** - it's from how we processed/saved the API responses.

---

## Recommended Fix

### Immediate (Prevent Future Corruption):

1. **Add file locking for parallel writes:**
```python
import fcntl  # Unix
# or
import msvcrt  # Windows

def _fetch_price_worker(self, ticker: str):
    # ... download data ...

    cache_file = self.price_dir / f"{ticker}.parquet"

    # Thread-safe file write
    with threading.Lock():  # Prevent concurrent writes
        df.to_parquet(cache_file)
```

2. **Add validation before saving:**
```python
def _fetch_price_worker(self, ticker: str):
    data = self._fetch_fmp_historical(ticker)
    df = self._parse_fmp_response(data, ticker)

    # VALIDATE ticker matches
    if 'symbol' in data and data['symbol'] != ticker:
        logger.error(f"Ticker mismatch: requested {ticker}, got {data['symbol']}")
        return (ticker, False, "Symbol mismatch")

    # VALIDATE reasonable date range
    ipo_date = self._get_ipo_date(ticker)
    if ipo_date and df.index.min() < ipo_date:
        logger.error(f"{ticker}: Data before IPO - trimming")
        df = df[df.index >= ipo_date]

    # Save
    cache_file = self.price_dir / f"{ticker}.parquet"
    df.to_parquet(cache_file)
```

3. **Disable parallel downloads temporarily:**
```python
# In update_cache() line 667
# Change from max_workers=10 to max_workers=1 for safety
fmp_results = self._update_cache_fmp(to_download, max_workers=1)
```

### Long-term:

1. Add comprehensive logging to track which worker downloads which ticker
2. Add post-download validation to detect corruption immediately
3. Implement atomic file writes (write to temp file, then rename)

---

## Conclusion

The corruption did **NOT** come from FMP returning wrong data when queried with old dates. FMP works correctly.

The corruption happened in OUR code during yesterday's cache rebuild, most likely due to:
- **Parallel processing race conditions**
- **Incorrect ticker assignment/extraction**
- **Lack of validation before saving**

The fix is to add proper validation and thread-safety to the cache update process.

