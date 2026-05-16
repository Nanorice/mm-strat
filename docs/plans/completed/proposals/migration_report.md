# FMP to yfinance Migration Analysis

## 1. FMP API Usage Inventory & yfinance Mapping

### Data Repository ([src/data_engine.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/data_engine.py))
| Component | FMP API Endpoint | Purpose | yfinance Equivalent | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Screener** | `/company-screener` | Fetch universe based on filters (market cap, price, etc.) | **None** (Direct) | yfinance `Screen` is experimental. <br> **Recommendation:** Rely on `SSGA` (S&P 500) or static lists. |
| **IPO Date** | `/profile/{ticker}` | Get IPO date for data trimming | `yf.Ticker(ticker).info['firstTradeDateEpochUtc']` or `start` metadata | [info](file:///c:/Users/Hang/PycharmProjects/quantamental/src/company_profile_engine.py#657-701) dictionary is heavy; might be slower. |
| **Price Data** | `/historical-price-eod/full` | Fetch daily OHLCV | `yf.download(ticker)` or `yf.Ticker(ticker).history()` | `yf.download` is faster for batch processing. |

### Fundamental Engine ([src/fundamental_engine.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_engine.py))
| Component | FMP API Endpoint | Purpose | yfinance Equivalent | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Income Statement** | `/income-statement` | Revenue, Net Income, EPS, etc. | `ticker.get_income_stmt(freq='quarterly')` | Field names differ significantly (e.g., `revenue` vs `Total Revenue`). |
| **Balance Sheet** | `/balance-sheet-statement` | Assets, Liabilities, Equity | `ticker.get_balance_sheet(freq='quarterly')` | |
| **Cash Flow** | `/cash-flow-statement` | Operating, Investing, Financing CF | `ticker.get_cashflow(freq='quarterly')` | |

### Company Profile Engine ([src/company_profile_engine.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/company_profile_engine.py))
| Component | FMP API Endpoint | Purpose | yfinance Equivalent | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Profile** | `/profile` | Sector, Industry, Market Cap, Description | `yf.Ticker(ticker).info` | [info](file:///c:/Users/Hang/PycharmProjects/quantamental/src/company_profile_engine.py#657-701) dict contains [sector](file:///c:/Users/Hang/PycharmProjects/quantamental/src/company_profile_engine.py#378-416), [industry](file:///c:/Users/Hang/PycharmProjects/quantamental/src/company_profile_engine.py#339-377), `marketCap`. |
| **Industry List** | `/available-industries` | List all available industries | **None** | Must build dynamically from universe or use static list. |
| **Sector List** | `/available-sectors` | List all available sectors | **None** | Must build dynamically from universe. |

### Macro Engine ([src/macro_engine.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/macro_engine.py))
*   **Current State:** Primarily uses `FRED` API.
*   **FMP Usage:** Fetches VIX via FMP in [MacroEngine](file:///c:/Users/Hang/PycharmProjects/quantamental/src/macro_engine.py#24-367) class comments, but code actually calls [fetch_fred_series('VIXCLS')](file:///c:/Users/Hang/PycharmProjects/quantamental/src/macro_engine.py#71-135).
*   **Impact:** **None**. Code already uses FRED for VIX (`VIXCLS` series).

## 2. Key Concerns & Risks

### A. Data Quality & Reliability
*   **Missing Data:** Yahoo Finance is known to have more gaps in fundamental data than FMP, especially for smaller cap stocks.
*   **Delisted Tickers:** FMP often retains data for delisted companies. Yahoo Finance tends to remove them or provide incomplete data, potentially introducing **survivorship bias**.
*   **Data Latency:** FMP is generally faster to update after earnings releases.

### B. API Constraints
*   **Rate Limits:** yfinance fetches data by scraping Yahoo Finance or using their unofficial API. It is stricter with rate limits (IP-based) and more prone to being blocked if not throttled correctly.
*   **Batching:** FMP allows efficient batch requests (though current code doesn't fully utilize this). yfinance `download` allows batching for prices, but fundamental data extraction is strictly **one-ticker-at-a-time**, which will be **significantly slower** for the full universe.

### C. Schema Differences
*   **Field Mapping:** FMP returns normalized keys (camelCase, e.g., `netIncome`). yfinance returns human-readable keys (Title Case, e.g., `Net Income`). A robust mapping layer will be required.
*   **Data Types:** Ensure numeric handling is consistent (e.g., reported in thousands vs millions).

### D. Missing Features
*   **Screener:** The loss of the `/company-screener` endpoint means we lose the ability to dynamically discover new tickers based on fundamental criteria (e.g., "Market Cap > 200M" and "Price > 5"). Verification of universe completeness will be harder.

## 3. Migration Checklist

- [ ] **Data Engine:** Replace [_fetch_fmp_historical](file:///c:/Users/Hang/PycharmProjects/quantamental/src/data_engine.py#487-637) with `yf.download`.
    -   *Constraint:* Ensure `Adj Close` vs `Close` logic is consistent.
- [ ] **Fundamental Engine:** Rewrite [fetch_statement](file:///c:/Users/Hang/PycharmProjects/quantamental/src/fundamental_engine.py#118-235) methods to use `yf.Ticker` objects.
    -   *Constraint:* Map Yahoo's DataFrame structure to existing parquet schema to maintain compatibility with `FundamentalProcessor`.
- [ ] **Profile Engine:** Replace `/profile` call with `yf.Ticker().info`.
    -   *Constraint:* Create a static list of Sectors/Industries since `available-industries` endpoint is gone.
- [ ] **Refactor Rate Limiter:** Current "tokens per minute" logic might need to change to "requests per session" or "time between requests" to satisfy Yahoo's protections.

## 4. Conclusion
Migrating to yfinance is feasible but comes with **performance costs** (slower fundamental fetching) and **data maintenance overhead** (manual schema mapping, universe management). I recommend benchmarking `yf.Ticker(ticker).get_income_stmt()` performance on a small sample before full commitment.
