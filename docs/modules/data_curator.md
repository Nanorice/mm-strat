# Module Passport: Data Curator

## 1. Overview
* **Responsibility:** The `data_curator` module handles the entire data lifecycle for the Quantamental SEPA System. It consolidates ticker universe updates, price/fundamental data refreshing, data health checks, and macroeconomic data fetching into a single maintenance interface. It acts as the central orchestrator for "Data Curation".
* **Key Dependencies:** 
    * **External:** `pandas`, `numpy`, `yfinance`, `requests`
    * **Internal:** `src.data_engine`, `src.fundamental_engine`, `src.company_profile_engine`, `src.macro_engine`, `src.earnings_engine`, `data_health_analyzer`

## 2. File Structure

| File | Purpose |
|------|---------|
| `data_curator.py` | **Entry Point**. CLI orchestrator that coordinates all data update tasks (prices, fundamentals, profiles, macro, health checks). |
| `src/data_engine.py` | **Price Data Core**. `DataRepository` class. Handles fetching OHLCV data from FMP/yfinance, managing Parquet cache, and enforcing rate limits. |
| `src/fundamental_engine.py` | **Fundamental Core**. `FundamentalEngine` class. Fetches Income, Balance Sheet, Cash Flow statements. Implements "Smart Update" logic using earnings dates. |
| `src/company_profile_engine.py` | **Metadata Core**. `CompanyProfileEngine` class. Manages static company data (Sector, Industry, Market Cap) and industry/sector mappings. |
| `src/macro_engine.py` | **Macro Core**. `MacroEngine` class. Fetches FRED series (Fed Assets, TGA, RRP) and VIX. Calculates Net Liquidity. |
| `src/earnings_engine.py` | **Event Core**. `EarningsEngine` class. Tracks historical and future earnings dates to drive "Smart Updates" of fundamental data. |
| `data_health_analyzer.py` | **QA Core**. `DataHealthAnalyzer` class. Audits data quality, checking for 200-bar sufficient history, fundamental completeness, and staleness. |

## 3. Data Schemas

### Price Data Cache (`data/price/{ticker}.parquet`)
| Column | Type | Description |
|--------|------|-------------|
| `Date` | Index | Trading date |
| `Open` | float | Opening price |
| `High` | float | High price |
| `Low` | float | Low price |
| `Close` | float | Closing price (adjusted/raw depending on source) |
| `Volume` | int | Trading volume |

### Fundamental Cache (`data/fundamentals/{ticker}.parquet`)
*Composite of Income Statement, Balance Sheet, and Cash Flow Statement.*
| Key Columns | Description |
|-------------|-------------|
| `fiscal_date` | Date of the fiscal period end |
| `filing_date` | Date the report was filed (used for point-in-time logic) |
| `revenue` | Total revenue |
| `eps` | Earnings Per Share |
| `netIncome` | Net Income |
| `totalAssets` | Total Assets |
| `totalLiabilities`  | Total Liabilities |
| `operatingCashFlow` | Operating Cash Flow |
| `statement_type` | Source statement (`income`, `balance`, `cash_flow`) |

### Company Profile Cache (`data/company_info/company_profiles.parquet`)
| Column | Type | Description |
|--------|------|-------------|
| `sector` | str | GICS Sector (e.g., "Technology") |
| `industry` | str | GICS Industry (e.g., "Semiconductors") |
| `mktCap` | float | Market Capitalization |
| `exchange` | str | Exchange Short Name (e.g., "NASDAQ") |
| `ipoDate` | str | IPO Date |
| `industry_id` | int | Internal ID mapped via `industry_mapping.parquet` |
| `sector_id` | int | Internal ID mapped via `sector_mapping.parquet` |

### Macro Data (`data/macro/{series_id}.parquet`)
| Column | Description |
|--------|-------------|
| `value` | The raw observation value (frequency varies by series) |
| `observation_date` | Index. Date of the observation. |

### Earnings Cache (`data/earnings/{ticker}.parquet`)
| Column | Description |
|--------|-------------|
| `date` | Earnings release date |
| `time` | Release time (`bmo` = Before Market Open, `amc` = After Market Close) |
| `epsEstimated` | Consensus EPS estimate |
| `epsActual` | Actual EPS reported |
| `revenueEstimated`| Revenue estimate |
| `revenueActual` | Revenue reported |
| `is_future` | Boolean flag, True if date > today |

## 4. Implementation Rules

### Rate Limiting
*   **FMP API:** Hard limit of **300 calls/minute** (Starter tier). Implemented via sliding window in `_rate_limit_check`. Engines sleep automatically if limit is reached.
*   **FRED API:** Limit of **120 calls/minute**.

### Smart Update Logic (Fundamentals)
*   **Trigger:** Instead of re-fetching fundamentals blindly, the system checks the **Earnings Calendar**.
*   **Rule:** If `latest_earnings_date > last_fundamental_update_timestamp`, the cache is considered stale.
*   **Actuals Check:** If the latest 3 earnings reports have `null` actuals in the cache, but `epsActual` is now available in the earnings calendar, a refresh is triggered.

### Data Validation
*   **Price History:** `DataHealthAnalyzer` flags tickers with **< 200 bars** of history.
*   **IPO Trimming:** `DataRepository` trims price data that predates the `ipoDate` from company profiles to prevent bad backfills.
*   **Market Hours Safety:** `update_prices` prevents updates if **Market is OPEN (09:00 - 16:00 ET, Mon-Fri)** to avoid caching incomplete daily bars. Override with `--skip-market-check` or `--force`.

### Macro Calculations
*   **Net Liquidity Formula:** `WALCL` (Fed Assets) - `WTREGEN` (TGA) - `RRPONTSYD` (Reverse Repo).
*   **Units:** All converted to **Billions** before calculation. (WALCL/WTREGEN are originally in Millions).

## 5. Public Interface

### `DataRepository` (src/data_engine.py)
```python
def get_ticker_data(ticker: str, mode: CacheMode = None, date_range: Tuple[str, str] = None) -> DataFrame
# Fetches OHLCV data.
# mode=CacheMode.LIVE: Checks for latest trading day.
# mode=CacheMode.HISTORICAL: Validates coverage of date_range.
# mode=CacheMode.CACHE_ONLY: Returns whatever is on disk.
```

### `FundamentalEngine` (src/fundamental_engine.py)
```python
def update_fundamentals_cache(tickers: List[str], use_earnings_calendar: bool = True) -> Dict[str, bool]
# Main entry point for batch updating fundamentals.
# use_earnings_calendar=True enables the Smart Update logic.
```

### `MacroEngine` (src/macro_engine.py)
```python
def get_net_liquidity(as_of_date: str = None) -> DataFrame
# Returns DataFrame with 'net_liquidity', 'fed_assets', 'tga', 'rrp' (all in Billions).
```

### `DataHealthAnalyzer` (data_health_analyzer.py)
```python
def run_full_analysis()
# Runs the full diagnostic suite and prints a report to stdout.
```
