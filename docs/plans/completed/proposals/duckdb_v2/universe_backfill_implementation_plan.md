# Phase 1: Universe Backfill Infrastructure

Establish the foundational data layer for historical analysis. Phase 1 pulls **all raw data for all tickers** (no filtering). Phase 2 applies screening criteria to create operational tables (`screener_members`, `daily_features`). Phase 3+ further filters to SEPA candidates.

**Scope**: Populate `company_profiles`, backfill `price_data`, backfill `shares_history`, backfill `fundamentals`, then establish quarterly expansion mechanism.

## Proposed Changes

---

### Module A — Ticker Population & Company Profiles

#### [MODIFY] [universe_backfill.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/universe_backfill.py)

**Task A1: Get initial ticker population**
- Replace FMP-dependent [discover_tickers()](file:///c:/Users/Hang/PycharmProjects/quantamental/src/universe_backfill.py#95-109) with yfinance.screen() pagination
- Use EquityQuery to filter US region, major exchanges (NYSE, NASDAQ, AMEX)
- Handle 250-result pagination cap via offset parameter
- Store results in `company_profiles` table (not a separate registry)

```python
import yfinance as yf
from yfinance import EquityQuery

q = EquityQuery("and", [
    EquityQuery("eq", ["region", "us"]),
    EquityQuery("is-in", ["exchange", "NMS", "NYQ", "ASE"]),
])

all_tickers = []
offset = 0
size = 250

while True:
    r = yf.screen(q, size=size, offset=offset, sortField="ticker", sortAsc=True)
    page = [qt["symbol"] for qt in r.get("quotes", [])]
    if not page:
        break
    all_tickers.extend(page)
    if len(page) < size:
        break
    offset += size
```

**Task A2: Populate company_profiles table**
- For each ticker from yf.screen(), fetch `yf.Ticker(ticker).info`
- Extract: sector, industry, exchange, country, marketCap, beta
- Write to `company_profiles` table (no FMP dependency)
- Remove FMP_API_KEY requirement — it blocks the pipeline unnecessarily

**Quarterly Population Expansion**
- Rerun yf.screen() quarterly to catch newly-listed tickers
- Batch fetch profiles for new tickers only
- `INSERT OR IGNORE` into `company_profiles` (idempotent)


### Module B — Price Data Backfill

#### [MODIFY] [universe_backfill.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/universe_backfill.py)

**Task B1: Backfill price_data (no _backfill suffix)**
- For each ticker in `company_profiles`, download historical OHLCV from yfinance
- Write to `price_data` table (production table, not `price_data_backfill`)
- Date range: 2000-01-01 to today (or start_date from config)
- Handle missing data gracefully (gaps OK, will be NULLs in features)
- **No filtering** — pull all tickers, all dates

```python
def backfill_price_data(self, start_date: str = '2000-01-01') -> int:
    """
    Backfill price_data for all tickers in company_profiles.
    Idempotent: uses INSERT OR IGNORE (replace on duplicate key).
    """
    con = duckdb.connect(self.db_path)
    tickers = con.execute("SELECT ticker FROM company_profiles").fetchall()

    for (ticker,) in tickers:
        df = yf.download(ticker, start=start_date, progress=False)
        # Normalize column names, cast volume to UBIGINT
        # INSERT OR IGNORE into price_data
```

**Performance Note**: ~10-20s per 250 tickers with concurrent requests (ThreadPoolExecutor). Full 10K tickers ≈ 8-15 hours.

### Module C — Shares History Backfill

#### [MODIFY] [universe_backfill.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/universe_backfill.py)

**Task C1: Backfill shares_history (no _backfill suffix)**
- For each ticker in `company_profiles`, fetch historical shares outstanding
- Source: yfinance.Ticker(ticker).quarterly_financials + shares_outstanding field
- Write to `shares_history` table (production table, not `shares_backfill`)
- Date range: earliest available to today
- **No filtering** — pull all available historical shares

```python
def backfill_shares_history(self, start_date: str = '2000-01-01') -> int:
    """
    Backfill shares_history for all tickers in company_profiles.
    Uses yfinance quarterly financials (limited but free).
    Idempotent: INSERT OR IGNORE.
    """
    con = duckdb.connect(self.db_path)
    tickers = con.execute("SELECT ticker FROM company_profiles").fetchall()

    for (ticker,) in tickers:
        info = yf.Ticker(ticker).info
        shares = info.get('sharesOutstanding')
        # Fetch quarterly snapshot dates from financials
        # INSERT current + estimated historical (forward-fill backwards)
```

**Limitation**: yfinance has limited historical shares data (quarterly snapshots only). Will be supplemented in Module D with SEC Edgar data.

---

### Module D — Fundamentals Backfill (SEC Edgar Integration — TBD)

#### [NEW] [fundamental_edgar_engine.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_edgar_engine.py)

**Task D1: SEC Edgar fundamentals backfill (placeholder for next session)**
- Fetch 10-Q / 10-K filings from SEC Edgar for all tickers
- Extract IS (income statement), BS (balance sheet), CF (cash flow) metrics
- Date range: earliest available to today
- Write to `fundamentals` table (production table, not `fundamentals_backfill`)
- **Metric normalization function**: Map Edgar raw fields → standardized columns (see note below)

**Edgar Schema Inconsistencies (IMPORTANT)**:
- Different industries report different metrics (e.g., banks vs tech: `NetInterestIncome` vs `RevenueFromOperations`)
- Solution: Create mapping function `normalize_edgar_metrics(industry, metric_dict)` to map raw fields to standard names
- Store raw fields in `fundamentals` table; mapping logic lives in feature pipeline

**Example**:
```python
def normalize_edgar_metrics(ticker: str, period_end: date, metrics_raw: dict) -> dict:
    """
    Map Edgar raw fields → standardized column names.
    Different industries require different field selections.

    Returns: Standardized dict with keys: revenue, net_income, assets, liabilities, etc.
    """
    industry = get_industry(ticker)
    if industry == 'Finance':
        return {
            'revenue': metrics_raw.get('NetInterestIncome'),
            'net_income': metrics_raw.get('NetIncome'),
            ...
        }
    elif industry == 'Technology':
        return {
            'revenue': metrics_raw.get('TotalRevenue'),
            'net_income': metrics_raw.get('NetIncome'),
            ...
        }
    # Handle other industries...
```

**Performance**: SEC Edgar API is throttled (1-2 requests/sec). Full backfill 10K tickers × 20 years ≈ **weeks of runtime**. Recommend batching by date (oldest first) with checkpoint/resume capability.

**Placeholder Implementation**:
```python
def backfill_fundamentals_edgar(self, start_date: str = '2000-01-01', batch_size: int = 100) -> int:
    """
    Backfill fundamentals from SEC Edgar.
    PLACEHOLDER: Implement next session.

    Args:
        start_date: Earliest filing period
        batch_size: Tickers per batch (resume checkpoint)

    Returns: Count of fundamentals rows inserted
    """
    raise NotImplementedError("SEC Edgar integration deferred to next session")
```

---

### Module E — Screener Grace-Period Cool-Down (Phase 2+)

#### [MODIFY] [screener_manager.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/managers/screener_manager.py)

**Note**: Grace period is applied at **Phase 2 onwards** (when screening criteria are enforced), not Phase 1.

**Schema addition** (in [_ensure_table()](file:///c:/Users/Hang/PycharmProjects/quantamental/src/managers/screener_manager.py#24-42)):
```sql
ALTER TABLE screener_members ADD COLUMN IF NOT EXISTS failed_criteria_since DATE;
ALTER TABLE screener_members ADD COLUMN IF NOT EXISTS grace_period_days INTEGER DEFAULT 255;
```

**[update_membership()](file:///c:/Users/Hang/PycharmProjects/quantamental/src/managers/screener_manager.py#101-218) logic** (applied during Phase 2 daily runs):

New behavior:
1. Ticker **passes criteria** → clear `failed_criteria_since`, set `is_active = TRUE`
2. Ticker **fails criteria, first time** → set `failed_criteria_since = target_date`, keep `is_active = TRUE`
3. Ticker **keeps failing** AND `target_date - failed_criteria_since > grace_period_days (255)` → set `is_active = FALSE`
4. Ticker **re-passes during grace period** → clear `failed_criteria_since`, set `is_active = TRUE`

**Grace Period Rationale**: Prevents feature sparsity. If a ticker fails criteria for 1 day then re-passes, we keep computing features (continuous time series for training) rather than creating data gaps.

**Optional audit table**: `screener_membership_history` (if needed for analysis):
```sql
CREATE TABLE IF NOT EXISTS screener_membership_history (
    ticker VARCHAR,
    event VARCHAR,  -- 'added' | 'grace_started' | 'removed' | 'reactivated'
    event_date DATE,
    criteria_version INTEGER,
    last_price DOUBLE,
    avg_volume_20d DOUBLE
)
```

---

### Module F — Quarterly Population Expansion

#### [MODIFY] [daily_pipeline_orchestrator.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/orchestrators/daily_pipeline_orchestrator.py)

Add quarterly-gated refresh (runs if last run was > 90 days ago):

**Phase 1.1 — Quarterly Universe Refresh**:
- Calls `UniverseBackfillEngine.quarterly_refresh()`
- Reruns yf.screen() to discover newly-listed tickers
- Batch fetches company_profiles for new tickers only
- Backfills price_data + shares_history for new tickers
- Non-critical: pipeline continues on failure

---

## Data Model (Phase 1)

**Production tables** (no `_backfill` suffix):
- `company_profiles`: Ticker metadata (sector, industry, exchange, country, mktCap)
- `price_data`: OHLCV for all tickers, all dates (no filtering)
- `shares_history`: Historical shares outstanding per ticker, per date
- `fundamentals`: Income statement, balance sheet, cash flow statements (sec edgar)

**Tables to DELETE**:
- `master_ticker_registry` (redundant; ticker list derived from `company_profiles`)
- `price_data_backfill` (merge into `price_data`)
- `shares_backfill` (merge into `shares_history`)
- `universe_snapshots` (screening logic moves to Phase 2; not needed for Phase 1 backfill)

---

## Verification Plan

### Phase 1 Deliverables

1. **company_profiles populated** (10K+ tickers):
   ```sql
   SELECT COUNT(*), COUNT(DISTINCT sector) FROM company_profiles;
   -- Expected: ~10000 rows, 11 sectors
   ```

2. **price_data backfilled** (all tickers, 2000-present):
   ```sql
   SELECT COUNT(*) FROM price_data;
   SELECT MIN(date), MAX(date) FROM price_data;
   -- Expected: ~2.6M rows, date range 2000-01-01 to today
   ```

3. **shares_history backfilled** (partial, yfinance source):
   ```sql
   SELECT COUNT(DISTINCT ticker), COUNT(*) FROM shares_history;
   -- Expected: ~10K tickers, ~50K rows (quarterly snapshots)
   ```

4. **fundamentals placeholder** (raises NotImplementedError):
   ```python
   from src.fundamental_edgar_engine import FundamentalEdgarEngine
   e = FundamentalEdgarEngine()
   e.backfill_fundamentals_edgar()  # Should raise NotImplementedError
   ```

### New Unit Tests to Write

#### [NEW] `tests/test_phase1_backfill.py`

```python
def test_company_profiles_has_sector_industry():
    # Assert sector and industry are populated for major tickers

def test_price_data_no_filtering():
    # Assert price_data contains tickers below screener thresholds (e.g., penny stocks)

def test_shares_history_idempotent():
    # Run backfill twice; assert row count unchanged (INSERT OR IGNORE works)

def test_quarterly_refresh_adds_new_tickers():
    # Mock yf.screen to return new ticker
    # Run quarterly_refresh
    # Assert new ticker in company_profiles
```

#### [NEW] `tests/test_edgar_normalization.py`

```python
def test_normalize_edgar_metrics_finance():
    # Test banking metrics extraction

def test_normalize_edgar_metrics_tech():
    # Test tech metrics extraction

def test_unsupported_industry_raises():
    # Unknown industry should raise or return empty dict
```

### Manual Verification

After Phase 1 completion:

1. **Ticker population** — run:
   ```powershell
   python scripts/run_universe_backfill.py --discover
   ```
   Should discover ~10K US-listed tickers, write to `company_profiles`.

2. **Price backfill** — run:
   ```powershell
   python scripts/run_universe_backfill.py --backfill-prices
   ```
   Should backfill all tickers, 2000-present (8-15 hours depending on concurrency).

3. **Shares backfill** — run:
   ```powershell
   python scripts/run_universe_backfill.py --backfill-shares
   ```
   Should backfill ~10K tickers (yfinance source, limited historical depth).

4. **Verify no filtering** — spot-check a low-price ticker:
   ```sql
   SELECT COUNT(*) FROM price_data WHERE ticker = 'SQQQ';
   -- Expected: Non-zero (not filtered, even though price often < $5)
   ```

5. **Quarterly expansion** — run:
   ```powershell
   python scripts/run_daily_pipeline.py  # Phase 1.1 will run if > 90 days since last refresh
   ```
   Should discover any newly-listed tickers, add to `company_profiles`, backfill their data.

---

## Open TODOs (Next Session)

- [ ] Implement SEC Edgar integration (`fundamental_edgar_engine.py`)
- [ ] Implement Edgar metric normalization (mapping function for different industries)
- [ ] Add Edgar data to Phase 2 feature pipeline
- [ ] Test Edgar backfill on sample of tickers (e.g., 100 tickers × 5 years)
- [ ] Optimize Edgar batch processing with checkpoint/resume (for 10K tickers × 20 years)
