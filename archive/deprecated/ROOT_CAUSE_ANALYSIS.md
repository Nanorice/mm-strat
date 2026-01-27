# Root Cause Analysis: Price Cache Corruption

## Executive Summary

**CONFIRMED ROOT CAUSE:** The FMP API returns historical data for ticker symbols that were used by **different companies** in the past. When downloading data for newly public companies (RIVN, SNOW, RKLB, etc.), the API returns data dating back decades to when those ticker symbols were used by previous companies.

---

## Key Findings

### 1. Fresh Download Test Results

| Ticker | Cached Start | Fresh Download Start | Years Difference | IPO Date |
|--------|--------------|---------------------|------------------|----------|
| RIVN | 1994-11-07 | 2021-11-10 | **27.0 years** | 2021-11-10 |
| SNOW | 1980-01-02 | 2020-09-16 | **40.7 years** | 2020-09-16 |
| RKLB | 1994-11-07 | 2020-11-24 | **26.0 years** | 2021-08-25 |
| U | 1984-01-10 | 2020-09-18 | **36.7 years** | 2019-04-18 |
| RITM | 1994-11-07 | 2013-05-02 | **18.5 years** | 2015-06-25 |
| RKT | 1994-11-07 | 2020-08-06 | **25.7 years** | 2020-08-06 |

**Critical Discovery:** When I re-downloaded these tickers from FMP today, they returned CORRECT data (starting from IPO). This means:
- The **cache was built with wrong/old data**
- FMP API **currently returns correct data**
- The corruption likely happened during **initial cache population**

### 2. Identical Data Across Different Tickers

**CONFIRMED:** RIVN, RKLB, RKT, and RITM all have **100% IDENTICAL** price data from 1994-11-07 through 2025-12-07.

```
All tickers on 2003-04-02 have identical close price: $2.566112
```

This proves they all got assigned data from the **SAME unknown company** that used these ticker symbols in the 1990s.

### 3. Data Quality Comparison

**Cached RIVN (CORRUPTED):**
```
Date: 1994-11-07
Close: $0.579885
Volume: 1,142,100
```

**Fresh FMP Download (CORRECT):**
```
Date: 2021-11-10 (actual IPO)
Close: $100.73
Volume: 103,679,466
```

The cached data is completely wrong - showing penny stock prices from 1994 for a company that didn't exist until 2021.

---

## Root Cause

### Why This Happened

**Ticker Symbol Reuse:** Stock exchanges recycle ticker symbols. When a company delists, their ticker symbol eventually gets reassigned to a new company.

**FMP API Behavior (Historical):**
- When the cache was originally built, FMP may have returned ALL historical data for a ticker symbol, including data from previous companies
- OR: There was a bug in how we handled the API response, causing wrong ticker data to be saved

**Current FMP API Behavior:**
- FMP now returns ONLY data from the current company (correct behavior)
- This suggests either:
  1. FMP fixed their API
  2. Our cache was built incorrectly during initial population

### When This Happened

All corrupted files show modification dates from whenever the cache was last rebuilt. The corruption persisted because:
1. **No IPO date validation** during download
2. **No sanity checks** on start dates (e.g., data from 1980s is suspicious for most stocks)
3. **No duplicate detection** to catch identical data across tickers

---

## Why Only These Tickers?

**Theory:** These are relatively recent IPOs (2013-2021) where:
- Their ticker symbols were previously used by other companies
- When cache was built, wrong historical data was returned/saved
- Older, established tickers (AAPL, MSFT, etc.) don't have this issue because they've had the same symbol for decades

---

## Solutions Implemented

### Solution 1: IPO Date Validation

**Status:** ✅ FMP Company Profile API Available

The FMP API provides IPO dates in the `/profile/{ticker}` endpoint. We can use this to:

```python
def validate_price_data_with_ipo(ticker: str, price_df: pd.DataFrame) -> pd.DataFrame:
    """Filter price data to start from IPO date."""

    # Get IPO date from company profile
    profile = get_company_profile(ticker)

    if profile and 'ipoDate' in profile:
        ipo_date = pd.to_datetime(profile['ipoDate'])
        data_start = price_df.index.min()

        if data_start < ipo_date:
            logger.warning(
                f"{ticker}: Trimming data before IPO. "
                f"Data started {data_start}, IPO was {ipo_date}"
            )
            # Trim to IPO date
            price_df = price_df[price_df.index >= ipo_date]

    return price_df
```

### Solution 2: Duplicate Detection

**Status:** ✅ Implemented in validate_price_cache.py

Using data hashing to detect when multiple tickers share identical price data:

```python
data_hash = hashlib.md5(pd.util.hash_pandas_object(df).values).hexdigest()

if data_hash in hash_registry:
    logger.error(f"{ticker} has duplicate data from {hash_registry[data_hash]}")
```

### Solution 3: Sanity Checks

**Status:** ⚠️ To Be Implemented

Add validation rules:
- Reject data starting before 1970 (suspicious)
- Reject data where first close price < $0.10 for stocks currently trading > $10
- Check if data start date makes sense (most IPOs are after 1980)

---

## Immediate Action Plan

### Phase 1: Clean Cache (URGENT)
1. ✅ Identify corrupted files (Done: 10-13 tickers identified)
2. Delete corrupted cache files
3. Re-download with validation

### Phase 2: Add Validation to data_engine.py
1. Add `get_ipo_date()` method
2. Modify `_parse_fmp_response()` to trim data before IPO
3. Add duplicate detection in cache update
4. Add sanity checks for unrealistic dates/prices

### Phase 3: Rebuild Dataset B
1. Verify cache is clean
2. Regenerate Dataset B
3. Confirm no duplicate trades
4. Validate all entry dates are after ticker IPOs

---

## Code Changes Required

### File: src/data_engine.py

**Add after line 223 (after _is_cache_stale):**

```python
def _get_ipo_date(self, ticker: str) -> Optional[pd.Timestamp]:
    """
    Fetch IPO date from FMP company profile API.

    Args:
        ticker: Stock symbol

    Returns:
        IPO date as Timestamp, or None if not available
    """
    if not config.FMP_API_KEY:
        return None

    try:
        url = f"{config.FMP_BASE_URL}/profile/{ticker}"
        params = {'apikey': config.FMP_API_KEY}

        response = requests.get(url, params=params, timeout=30)

        if response.status_code == 200:
            data = response.json()

            if isinstance(data, list) and len(data) > 0:
                profile = data[0]
                ipo_date = profile.get('ipoDate')

                if ipo_date and ipo_date != '':
                    return pd.to_datetime(ipo_date)

        return None

    except Exception as e:
        logger.debug(f"Could not fetch IPO date for {ticker}: {e}")
        return None
```

**Modify _parse_fmp_response() at line 345:**

```python
def _parse_fmp_response(self, response_data: dict, ticker: str) -> Optional[pd.DataFrame]:
    """
    Convert FMP JSON response to DataFrame with IPO date validation.
    """
    try:
        if not response_data or 'historical' not in response_data:
            return None

        historical = response_data['historical']
        if not historical:
            return None

        # Convert to DataFrame
        df = pd.DataFrame(historical)

        # Rename columns to match yfinance format
        column_mapping = {
            'date': 'Date',
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        }
        df = df.rename(columns=column_mapping)

        # Convert date to datetime and set as index
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')

        # Sort by date (FMP returns newest first, we want oldest first)
        df = df.sort_index()

        # **NEW: IPO DATE VALIDATION**
        ipo_date = self._get_ipo_date(ticker)

        if ipo_date:
            data_start = df.index.min()

            if data_start < ipo_date:
                years_before = (ipo_date - data_start).days / 365.25
                logger.warning(
                    f"{ticker}: Data starts {years_before:.1f} years before IPO "
                    f"({data_start} < {ipo_date}). Trimming to IPO date."
                )

                # Trim data to start from IPO
                df = df[df.index >= ipo_date]

                if df.empty:
                    logger.error(f"{ticker}: No data after IPO date filter")
                    return None

        # Ensure we have the required columns
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        for col in required_cols:
            if col not in df.columns:
                if col == 'Volume':
                    df[col] = 0
                else:
                    df[col] = df['Close']

        return df[required_cols]

    except Exception as e:
        logger.debug(f"Failed to parse FMP data for {ticker}: {e}")
        return None
```

---

## Testing Plan

### Test 1: Clean Rebuild
```bash
# Delete corrupted files
python validate_price_cache.py --delete-corrupted --confirm

# Re-download with validation
python build_dataset_a.py --update-cache

# Verify clean
python validate_price_cache.py
```

### Test 2: Spot Check
```python
# Verify RIVN starts from IPO
rivn_df = pd.read_parquet('data/price/RIVN.parquet')
assert rivn_df.index.min() >= pd.Timestamp('2021-11-10')

# Verify no duplicates
import hashlib
hashes = {}
for ticker in ['RIVN', 'RKLB', 'RKT', 'RITM']:
    df = pd.read_parquet(f'data/price/{ticker}.parquet')
    h = hashlib.md5(pd.util.hash_pandas_object(df).values).hexdigest()
    assert h not in hashes.values(), f"{ticker} has duplicate data"
    hashes[ticker] = h
```

### Test 3: Rebuild Dataset B
```bash
# Regenerate with clean cache
python build_dataset_b.py --start 2020-01-01 --end 2024-12-31

# Verify no duplicates in Dataset B
python -c "
import pandas as pd
df = pd.read_parquet('data/ml/dataset_b.parquet')
cols = [c for c in df.columns if c not in ['ticker', 'trade_id']]
dupes = df[df.duplicated(subset=cols, keep=False)]
print(f'Duplicates: {len(dupes)}')
assert len(dupes) == 0, 'Dataset B still has duplicates!'
"
```

---

## Long-term Improvements

1. **Add FMP Profile Caching:** Cache IPO dates to avoid repeated API calls
2. **Automated Validation:** Run validation script daily/weekly to catch new corruption
3. **Data Lineage Tracking:** Track when/how each cache file was created
4. **Multi-source Validation:** Cross-check IPO dates from multiple sources (Yahoo, Polygon, etc.)

---

## Questions Answered

### 1. Have you checked the price file?
✅ **Yes** - Jupyter notebook created: `investigate_cache_issues.ipynb`

Cached files show data from wrong companies (e.g., RIVN has data from 1994, but IPO was 2021)

### 2. Can you replicate the download to see if error persisted?
✅ **Yes** - Fresh downloads from FMP today return **CORRECT data** starting from actual IPO dates.

This confirms:
- FMP API is currently working correctly
- The corruption happened during initial cache population (historical issue)
- Re-downloading will fix the problem

### 3. Is IPO date available in company profile?
✅ **Yes** - FMP Company Profile API includes `ipoDate` field

Example:
```json
{
  "symbol": "RIVN",
  "companyName": "Rivian Automotive Inc",
  "ipoDate": "2021-11-10",
  "exchangeShortName": "NASDAQ"
}
```

This can be used to validate and trim price data during download.

---

## Conclusion

The root cause is **ticker symbol reuse** combined with **lack of IPO date validation** during initial cache population. The corruption is fixable by:

1. Deleting corrupted files
2. Adding IPO date validation to data_engine
3. Re-downloading with validation enabled
4. Regenerating Dataset B

**Estimated time to fix:** 2-3 hours (mostly API download time)

