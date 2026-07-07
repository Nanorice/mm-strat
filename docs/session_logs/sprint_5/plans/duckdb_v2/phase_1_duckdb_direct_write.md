# Phase 1 Refactor: Direct-to-DuckDB Price Ingestion

> Created: 2026-03-21
> Status: APPROVED — pending implementation

---

## Problem Statement

`DataRepository` is parquet-only and DuckDB-unaware. The daily pipeline Phase 1 calls
`update_cache()` which writes to `data/price/*.parquet` — the DuckDB `price_data` table
is never updated by the daily run.

Additionally, the orchestrator passes `self.db_path` to `DataRepository()` but the
constructor signature is `__init__(self, enable_validation: bool = True)` — the path
string is silently coerced to truthy `enable_validation=True`. No crash, but `db_path`
is ignored entirely.

### Current flow (broken)
```
Phase 1 trigger
  → parallel file-stat scan (50 workers, parquet mtime)
  → fetch yfinance/FMP
  → write to data/price/{ticker}.parquet   ← DuckDB never touched
  → price_data table stays stale           ← downstream phases read stale data
```

### Target flow
```
Phase 1 trigger
  → one DuckDB query → stale ticker list (from company_profiles)
  → parallel fetch (yfinance/FMP) → validate in-memory
  → accumulate results in memory buffer
  → cross-ticker quality gate
  → single bulk INSERT OR IGNORE INTO price_data
  → failure rate check → HALT if > 10%
```

---

## Design Decisions

### No per-ticker DuckDB writes — bulk write after all workers finish
Workers return `(ticker, df)` tuples into a shared results list. After
`ThreadPoolExecutor` joins, results are concatenated and flushed in a single
`INSERT OR IGNORE`. This matches the pattern already used in `universe_backfill.py`
(`_write_price_batch`).

Benefits over per-worker DuckDB writes:
- Zero WAL contention — single writer, no lock serialisation overhead
- Cross-ticker quality checks are possible before any data lands in DuckDB
- `ticker` column is always set at concat time — no caller contract to forget

For `force=True` full-history reloads where memory may grow large, a
`flush_threshold` (default 5000 rows) triggers intermediate flushes so the
buffer never grows unboundedly.

### No per-ticker parquet files in the write path
Per-ticker parquets (`data/price/*.parquet`) are removed from the write path.
Existing files in `data/price/` are retained as a cold backup until the
implementation is validated across several production runs.

### Staleness check: one query, not N file stats
Current code runs 50 parallel `os.stat()` calls on parquet files. Replacement:

```sql
SELECT cp.ticker
FROM company_profiles cp
LEFT JOIN (
    SELECT DISTINCT ticker FROM price_data WHERE date = '<latest_trading_day>'
) fresh ON cp.ticker = fresh.ticker
WHERE cp.is_active = TRUE
  AND fresh.ticker IS NULL
```

One query. Returns exactly the tickers missing the latest trading day.
- New tickers (in company_profiles, not in price_data): naturally included
- Delisted tickers (is_active = FALSE): naturally excluded
- Already-fresh tickers: naturally excluded
- Empty result = skip condition (no separate `_should_skip_phase_1` needed)

> **Pre-implementation check:** Verify `is_active` column exists in the live
> `market_data.duckdb` — two schema definitions exist (`migrate_to_duckdb.py` has it,
> `universe_backfill.py` does not). Run:
> ```python
> conn.execute("PRAGMA table_info('company_profiles')").df()
> ```
> If missing, fall back to `WHERE ticker IN (SELECT ticker FROM screener_members)`.

### `force=True` requires interactive confirmation
`force=True` bypasses the staleness check and re-fetches full price history
(from `DEFAULT_HISTORICAL_START_DATE`) for all active tickers. Since no parquet
cache exists post-migration, every ticker gets a full download. This consumes
significant FMP API quota. An interactive prompt guards against accidental runs:

```python
if force:
    n = len(tickers or self._get_all_active_tickers())
    print(f"⚠️  Force mode: will re-fetch full price history for {n} active tickers.")
    print(f"    This consumes significant API quota and may take 30-60 minutes.")
    confirm = input("    Type 'yes' to continue: ").strip().lower()
    if confirm != 'yes':
        logger.info("Force update cancelled by user.")
        return {}
```

Note: `force=True` does NOT overwrite existing rows — `INSERT OR IGNORE` skips
them. The cost is purely API quota and runtime.

### Data quality log — monthly rotation
Failed tickers are logged to `logs/data_quality/YYYY-MM.log` after all retries
are exhausted (not on transient errors). Each entry is one line, grouped by
issue type:

```
2026-03-21 | FETCH_FAILURE     | AAPL, MSFT (2 tickers)       | HTTP 429 after 5 retries
2026-03-21 | ZERO_VOLUME       | ABCD (1 ticker)               | volume=0 on 2026-03-21
2026-03-21 | NEGATIVE_CLOSE    | WXYZ (1 ticker)               | close=-0.01 on 2026-03-21
2026-03-21 | HIGH_FAILURE_RATE | 187/1826 tickers failed       | >10% threshold — write aborted
```

- Monthly files (`YYYY-MM.log`) keep size bounded: ~30 entries/month worst case
- Append-only within the month
- Only written by `update_cache` daily runs — backfill (`universe_backfill.py`) is out of scope
- Log is written regardless of whether the quality gate aborts the write

---

## Implementation Steps

### Step 1 — Fix `DataRepository.__init__`

**File:** `src/data_engine.py`

Change signature:
```python
# Before
def __init__(self, enable_validation: bool = True):
    self.price_dir = config.PRICE_DATA_DIR
    self._file_locks: Dict[str, threading.Lock] = {}
    self._file_locks_lock = threading.Lock()
    ...

# After
def __init__(self, db_path: str, enable_validation: bool = True):
    self.db_path = db_path
    # Remove: self.price_dir, self._file_locks, self._file_locks_lock
    ...
```

Remove class-level parquet state: `price_dir`, `_file_locks`, `_file_locks_lock`.

---

### Step 2 — Add `_get_stale_tickers` and `_get_all_active_tickers`

**File:** `src/data_engine.py` — replaces `_is_cache_stale`

```python
def _get_stale_tickers(self, latest_trading_day: str) -> List[str]:
    """
    One query: active tickers in company_profiles with no price row
    for latest_trading_day. Replaces per-ticker file-stat staleness checks.
    """
    conn = duckdb.connect(self.db_path, read_only=True)
    try:
        rows = conn.execute("""
            SELECT cp.ticker
            FROM company_profiles cp
            LEFT JOIN (
                SELECT DISTINCT ticker
                FROM price_data
                WHERE date = ?
            ) fresh ON cp.ticker = fresh.ticker
            WHERE cp.is_active = TRUE
              AND fresh.ticker IS NULL
            ORDER BY cp.ticker
        """, [latest_trading_day]).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()

def _get_all_active_tickers(self) -> List[str]:
    """All active tickers from company_profiles. Used by force=True path."""
    conn = duckdb.connect(self.db_path, read_only=True)
    try:
        return [r[0] for r in conn.execute(
            "SELECT ticker FROM company_profiles WHERE is_active = TRUE ORDER BY ticker"
        ).fetchall()]
    finally:
        conn.close()
```

**Delete:** `_is_cache_stale()` entirely.

---

### Step 3 — Fix incremental `from_date` in `_fetch_fmp_historical`

**File:** `src/data_engine.py` lines 516–524

Current code reads parquet index to get last date. Replace with DuckDB query:

```python
# Before
if not force_from_date and cache_file.exists():
    df = pd.read_parquet(cache_file, columns=[])
    last_date = df.index.max()
    from_date = (last_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

# After
if not force_from_date:
    conn = duckdb.connect(self.db_path, read_only=True)
    try:
        result = conn.execute(
            "SELECT MAX(date) FROM price_data WHERE ticker = ?", [ticker]
        ).fetchone()
        last_date = result[0] if result and result[0] else None
    finally:
        conn.close()
    if last_date:
        from_date = (pd.Timestamp(last_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        from_date = DEFAULT_HISTORICAL_START_DATE
```

Per-ticker read-only query runs inside the parallel worker — safe, no WAL pressure.

---

### Step 3b — Fix incremental `from_date` in `_update_cache_yfinance`

**File:** `src/data_engine.py`

Current code uses `period='max'` which re-downloads full history on every run.
Replace with a per-batch `start=` derived from the earliest gap in the batch.
Verified working in yfinance v0.2.66.

```python
# Before
data = yf.download(
    batch,
    period='max',   # always full history — no incremental logic
    group_by='ticker',
    auto_adjust=True,
    progress=False,
    threads=True
)

# After
conn = duckdb.connect(self.db_path, read_only=True)
try:
    result = conn.execute("""
        SELECT MIN(max_date) FROM (
            SELECT ticker, MAX(date) AS max_date
            FROM price_data
            WHERE ticker IN (SELECT unnest(?))
            GROUP BY ticker
        )
    """, [batch]).fetchone()
    last_date = result[0] if result and result[0] else None
finally:
    conn.close()

from_date = (
    (pd.Timestamp(last_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    if last_date else DEFAULT_HISTORICAL_START_DATE
)

data = yf.download(
    batch,
    start=from_date,   # fetch only the gap
    group_by='ticker',
    auto_adjust=True,
    progress=False,
    threads=True
)
```

**Why `MIN(MAX(date))`:** yfinance downloads all tickers in a batch with a single
`start=` date. Using the earliest gap in the batch ensures no ticker is missed.
`INSERT OR IGNORE` absorbs any overlap for tickers that are already more recent.

**New ticker in batch:** if a ticker has no rows in `price_data`, it is excluded
from the `GROUP BY` result, so `MIN` pulls from the tickers that do have data.
If *all* tickers in the batch are new, `MIN` returns NULL → falls back to
`DEFAULT_HISTORICAL_START_DATE` for a full history download.

---

### Step 4 — Workers return tuples; bulk writer owns DuckDB

**File:** `src/data_engine.py`

Workers no longer write to DuckDB. They return `(ticker, df | None, error | None)`.

**Add `_flush_buffer`:**

```python
def _flush_buffer(
    self,
    buffer: List[Tuple[str, pd.DataFrame]],
    run_date: str,
    flush_threshold: int = 5000,
) -> int:
    """
    Concatenate buffer, run quality checks, bulk-insert into price_data.
    Returns number of rows written.
    Called either when buffer exceeds flush_threshold or after all workers finish.
    """
    if not buffer:
        return 0

    df = pd.concat(
        [d.assign(ticker=t) for t, d in buffer],
        ignore_index=True,
    )

    issues = self._quality_check(df, run_date)   # see Step 5
    if issues:
        self._log_quality_issues(issues, run_date)

    conn = duckdb.connect(self.db_path)
    try:
        conn.execute("""
            INSERT OR IGNORE INTO price_data (ticker, date, open, high, low, close, volume)
            SELECT ticker, date, open, high, low, close, CAST(volume AS UBIGINT)
            FROM df
        """)
        return len(df)
    except Exception as e:
        logger.error(f"Bulk DuckDB write failed: {e}")
        return 0
    finally:
        conn.close()
```

**Delete:** `_safe_write_parquet()` and `_write_to_duckdb()` (single-writer pattern
makes per-ticker writes obsolete).

---

### Step 5 — Add `_quality_check` and `_log_quality_issues`

**File:** `src/data_engine.py`

```python
def _quality_check(
    self,
    df: pd.DataFrame,
    run_date: str,
) -> List[Tuple[str, List[str], str]]:
    """
    Cross-ticker checks on the full buffer before write.
    Returns list of (issue_type, affected_tickers, detail) tuples.
    Only called post-retry — transient fetch errors are not surfaced here.
    """
    issues = []

    bad_close = df[df['close'] <= 0]
    if not bad_close.empty:
        tickers = bad_close['ticker'].unique().tolist()
        issues.append(('NEGATIVE_CLOSE', tickers, f"close <= 0 on {run_date}"))

    zero_vol = df[(df['volume'] == 0) & (df['date'] == run_date)]
    if not zero_vol.empty:
        tickers = zero_vol['ticker'].unique().tolist()
        issues.append(('ZERO_VOLUME', tickers, f"volume=0 on {run_date}"))

    return issues

def _log_quality_issues(
    self,
    issues: List[Tuple[str, List[str], str]],
    run_date: str,
) -> None:
    """
    Append quality issues to logs/data_quality/YYYY-MM.log.
    One line per issue type, tickers comma-separated.
    Written after all retries exhausted — not on transient errors.
    """
    from pathlib import Path
    log_dir = Path("logs/data_quality")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{run_date[:7]}.log"  # YYYY-MM.log

    with open(log_file, 'a') as f:
        for issue_type, tickers, detail in issues:
            tickers_str = ', '.join(tickers[:20])
            if len(tickers) > 20:
                tickers_str += f' ... +{len(tickers) - 20} more'
            f.write(f"{run_date} | {issue_type:<18} | {tickers_str:<50} | {detail}\n")
```

---

### Step 6 — Update `_fetch_price_worker` (FMP path)

**File:** `src/data_engine.py` lines 1022–1028

Workers return tuple, no DuckDB call:

```python
# Before
success = self._safe_write_parquet(df, cache_file, ticker, merge_with_existing=True)

# After
df = self._parse_fmp_response(fmp_data, ticker)
if df is not None and not df.empty:
    df = self._validate_and_trim_data(df, ticker)
    if df is None:
        return (ticker, None, "Validation failed")
    return (ticker, df, None)
else:
    return (ticker, None, "No data parsed")
```

---

### Step 7 — Update `_update_cache_yfinance`

**File:** `src/data_engine.py` lines 1216–1227

```python
# Before
ticker_data.to_parquet(cache_file)
results[ticker] = True

# After
validated = self._validate_and_trim_data(ticker_data, ticker)
if validated is not None:
    buffer.append((ticker, validated))   # caller collects buffer
else:
    results[ticker] = False
```

---

### Step 8 — Rewrite `update_cache`

**File:** `src/data_engine.py`

Remove the 50-worker parallel file-stat scan. Replace with:

```python
def update_cache(
    self,
    tickers: List[str] = None,
    force: bool = False,
    source: str = 'fmp',
    max_workers: int = 10,
    from_date: str = None,
    flush_threshold: int = 5000,
) -> Dict[str, bool]:
    latest_trading_day = get_latest_trading_day()

    if force:
        candidate_tickers = tickers or self._get_all_active_tickers()
        n = len(candidate_tickers)
        print(f"⚠️  Force mode: will re-fetch full price history for {n} active tickers.")
        print(f"    This consumes significant API quota and may take 30-60 minutes.")
        confirm = input("    Type 'yes' to continue: ").strip().lower()
        if confirm != 'yes':
            logger.info("Force update cancelled by user.")
            return {}
        to_update = candidate_tickers
    else:
        to_update = self._get_stale_tickers(latest_trading_day)

    if not to_update:
        logger.info(f"✅ All active tickers fresh as of {latest_trading_day}")
        return {}

    logger.info(f"⬇️ {len(to_update)} tickers to update (latest: {latest_trading_day})")

    buffer: List[Tuple[str, pd.DataFrame]] = []
    results: Dict[str, bool] = {}
    rows_written = 0

    # ... FMP/yfinance dispatch (unchanged) ...
    # Workers return (ticker, df | None, error | None)
    # On success: buffer.append((ticker, df)); results[ticker] = True
    # On failure (post-retry): results[ticker] = False; log via _log_quality_issues

    # Intermediate flush if buffer grows large (force=True full-history scenario)
    if len(pd.concat([d for _, d in buffer])) >= flush_threshold:
        rows_written += self._flush_buffer(buffer, latest_trading_day)
        buffer.clear()

    # Final flush
    if buffer:
        rows_written += self._flush_buffer(buffer, latest_trading_day)

    # Log fetch failures (post-retry) if any
    failed = [t for t, ok in results.items() if not ok]
    if failed:
        self._log_quality_issues(
            [('FETCH_FAILURE', failed, f"no data after retries on {latest_trading_day}")],
            latest_trading_day,
        )

    failure_rate = len(failed) / len(to_update) if to_update else 0
    if failure_rate > 0.10:
        self._log_quality_issues(
            [('HIGH_FAILURE_RATE', [], f"{len(failed)}/{len(to_update)} tickers failed — >10% threshold")],
            latest_trading_day,
        )

    logger.info(f"✅ {rows_written} rows written to price_data")
    return results
```

---

### Step 9 — Simplify orchestrator Phase 1

**File:** `src/orchestrators/daily_pipeline_orchestrator.py`

**Fix constructor call:**
```python
# Before (silent bug — db_path coerced to enable_validation=True)
self.data_repo = DataRepository(self.db_path)

# After
self.data_repo = DataRepository(db_path=self.db_path)
```

**Simplify `_run_phase_1_t1_ingestion`:** Remove pre-query that fetches `price_tickers`
from `price_data`. `update_cache` now owns its own universe:

```python
# Before
price_tickers = conn.execute("SELECT DISTINCT ticker FROM price_data").fetchall()
futures[executor.submit(self.data_repo.update_cache, tickers=price_tickers, ...)] = 'price'

# After
futures[executor.submit(self.data_repo.update_cache, source='yfinance')] = 'price'
```

**Delete `_should_skip_phase_1`:** Redundant — `_get_stale_tickers` returning empty is
the skip condition. Orchestrator calls `update_cache`; if nothing is stale it returns
immediately.

---

### Step 10 — Deprecate `PRICE_DATA_DIR` in config

**File:** `config.py`

```python
# DEPRECATED: parquet per-ticker cache — replaced by direct DuckDB writes in Phase 1
# Retained for reference; existing files in data/price/ are historical backup only
PRICE_DATA_DIR = Path("data/price")
```

---

## What Is NOT Changing

| Component | Status |
|---|---|
| `_validate_and_trim_data` | Unchanged — in-memory validation before every write |
| `_fetch_fmp_historical` fetch + retry logic | Unchanged — only `from_date` derivation changes |
| `_update_cache_fmp` two-pass retry strategy | Unchanged |
| `_update_cache_yfinance` batch download | `period='max'` → `start=from_date` (Step 3b); write path updated (Step 7) |
| `get_latest_trading_day()` | Unchanged |
| Rate limiting / 429 backoff | Unchanged |
| Failure rate check in orchestrator | Unchanged |
| `universe_backfill.py` | Unchanged — has its own DuckDB write path |
| `_parse_fmp_response` | Unchanged |

---

## Files Touched

| File | Change |
|---|---|
| `src/data_engine.py` | Constructor, remove `_is_cache_stale` + `_safe_write_parquet`, add `_get_stale_tickers` + `_get_all_active_tickers` + `_flush_buffer` + `_quality_check` + `_log_quality_issues`, fix `_fetch_fmp_historical` from_date, fix `_update_cache_yfinance` period→start, update workers to return tuples |
| `src/orchestrators/daily_pipeline_orchestrator.py` | Fix constructor call, simplify Phase 1, delete `_should_skip_phase_1` |
| `config.py` | Deprecate `PRICE_DATA_DIR` |

**Estimated scope:** ~200 lines deleted, ~120 lines added. Net reduction. No new dependencies.

---

## Data Quality Log Format

**Location:** `logs/data_quality/YYYY-MM.log` (monthly rotation, append-only)

**Example:**
```
2026-03-21 | FETCH_FAILURE      | AAPL, MSFT (2 tickers)                            | no data after retries on 2026-03-21
2026-03-21 | ZERO_VOLUME        | ABCD (1 ticker)                                   | volume=0 on 2026-03-21
2026-03-21 | NEGATIVE_CLOSE     | WXYZ (1 ticker)                                   | close=-0.01 on 2026-03-21
2026-03-21 | HIGH_FAILURE_RATE  |                                                   | 187/1826 tickers failed — >10% threshold
```

**Rules:**
- Written only by `update_cache` daily runs — not by backfill
- Entry written only after all retries are exhausted (not on transient errors)
- Tickers truncated to first 20 per line with `+N more` suffix
- Monthly file keeps log bounded: worst case ~30 lines/month per issue type
