# Data Sources & API Endpoints

Comprehensive documentation of all APIs and data sources used across the Quantamental system.

---

## Price Data

**Primary Source**: yfinance (Yahoo Finance API)

- **Endpoint**: `yf.download(ticker, start, end)`
- **Rate Limit**: None (casual usage tolerated)
- **Data**: OHLCV daily bars (Open, High, Low, Close, Volume)
- **Fallback**: Cache-only mode (`force_cache_only=True`)
- **Storage**: DuckDB `price_data` table
- **Usage**: Technical analysis, candlestick patterns, moving averages, volatility metrics

---

## Fundamental Data

**Status**: Cache-only mode (FMP API disabled, no new ingestion)

- **Historical Source**: FMP API (Financial Modeling Prep)
  - Endpoints:
    - `/income-statement` (quarterly income statements)
    - `/balance-sheet-statement` (quarterly balance sheets)
    - `/cash-flow-statement` (quarterly cash flow)
- **Why Cache-Only?**:
  - Fundamentals are **NOT used** by ML models (M01/M02 use only technical features)
  - Zero business value to active API ingestion = zero ROI on maintenance
  - 5-year historical cache sufficient for any future model work
  - Eliminates FMP API dependency (rate limits, quota management, error handling)
- **Storage**: Parquet cache (`config.FUNDAMENTALS_DIR`)
- **Cache Age**: 5 years of historical data maintained for reference

**Future Options** (if fundamentals become model inputs):
- Option 1: Implement yfinance fundamentals (4-year limit, ~30% field coverage)
- Option 2: Reactivate FMP API (API key exists, requires proper error handling)
- Option 3: Migrate to SEC EDGAR (official source, unlimited history, complex parsing)

---

## Macro Data

**Primary Source**: FRED API (Federal Reserve Economic Data)

- **Rate Limit**: 120 calls/hour (free tier)
- **Storage**: DuckDB `macro_data` table
- **Endpoints**:
  - **Fed Assets** (`WALCL`): Fed Balance Sheet (total assets)
  - **TGA** (`WTREGEN`): Treasury General Account (cash reserves)
  - **RRP** (`RRPONTSYD`): Reverse Repo Operations (overnight RRP)
  - **VIX** (`VIXCLS`): CBOE Volatility Index (market volatility)
- **Frequency**: Daily updates
- **Usage**: M03 regime scoring (liquidity pillars, volatility detection)

---

## Shares Outstanding

**Primary Source**: yfinance

- **Endpoint**: `yf.Ticker(ticker).info['sharesOutstanding']`
- **Fallback**: Cache
- **Storage**: DuckDB `shares_outstanding` table
- **Usage**: Computing per-share metrics (EPS, dividend adjustments)

---

## Company Profiles

**Primary Source**: yfinance

- **Endpoint**: `yf.Ticker(ticker).info`
- **Data**:
  - Industry (e.g., "Software—Infrastructure")
  - Sector (e.g., "Technology")
  - IPO date
  - Market cap
- **Fallback**: Cache
- **Storage**: DuckDB `company_profiles` table
- **Usage**: Sector/industry-based filtering, cross-sectional analysis

---

## Screener Universe

**Current Method**: `screener_members` table (DuckDB)

- **Source**: Real-time computation based on price and volume criteria
- **Criteria**:
  - Price >= $15 (USD)
  - 20-day average volume >= 500,000 shares
  - Active trading (recent data)
- **Membership Tracking**:
  - Table: `screener_members` (ticker, added_date, removed_date, is_active)
  - Daily updates via Phase 2 of pipeline
- **Historical Source**: FMP `/company-screener` (deprecated, rate-limited)

---

## Feature & Model Data

**T1 (Ingestion Layer)**: Raw price, fundamental, shares, macro data

**T2 (Screener Layer)**: Lightweight technical features for universe screening
- Stored in: `t2_screener_features` table
- Computed daily via Phase 3 of pipeline
- Used for: SEPA breakout detection (trend_ok, breakout_ok flags)

**T3 (Feature Store)**: Comprehensive technical features for SEPA candidates
- Stored in: `t3_sepa_features` table (materialized view)
- Computed via Phase 6 of pipeline
- Features: 149 columns (SMA, RSI, ATR, volatility, momentum, ranks, regime)
- Filtered to: SEPA candidates only (reduces storage from 2.6M to 500K rows)
- Version: `v3.1` (includes pct_chg deltas)

**D2 (Training Cache)**: Materialized training data for fast model loading
- Stored in: `d2_training_cache` table
- Computed via Phase 8 of pipeline
- Performance: 70x faster than views (0.126s vs 8.8s)
- Features: 72 columns + log-transforms for M01, 38 columns for M02

---

## ML Model Data

**M01 (Breakout Exit Model)**: 72 features
- Technical features (SMA, RSI, ATR, momentum, volatility, ranks)
- Fundamental features (P/E, P/B, debt-to-equity)
- M03 regime features (liquidity, volatility)
- Log-transforms computed in view layer

**M02 (Ignition Classifier)**: 38 features
- Velocity-only (no fundamentals, no regime)
- Fast classifier for entry timing

---

## Data Pipeline Phases

| Phase | Name | Universe | Input | Output | Frequency |
|-------|------|----------|-------|--------|-----------|
| 1 | T1 Ingestion | price_data (cached tickers) + screener_members | yfinance, FRED, FMP (cache) | price_data, macro_data, fundamentals | Daily |
| 2 | Screener Membership | All price_data tickers | price_data | screener_members (filtered by $15 price, 500K vol) | Daily |
| 3 | T2 Screener | screener_members | price_data, company_profiles | t2_screener_features (lightweight) | Daily |
| 4 | T2 Regime | All price_data | macro_data | t2_screener_features (M03 cols) | Daily |
| 5 | daily_features | All price_data | price_data, company_profiles, macro_data | daily_features (comprehensive) | Daily |
| 6 | T3 Lazy | SEPA candidates | daily_features, t2_screener | t3_sepa_features (materialized) | Daily |
| 7 | Views | SEPA candidates | daily_features, t3_sepa_features | v_sepa_candidates, v_d1_candidates, etc. | Daily |
| 8 | Cache Refresh | SEPA candidates | Views | d2_training_cache (materialized) | Daily |
| 9 | Monitoring | All phases | pipeline_runs | Logs, alerts | Daily |

### Universe Logic
- **Bootstrap** (first run): Phase 1 detects no cached tickers, runs ingestion to initialize
- **Steady state**: Phase 1 checks staleness of currently cached tickers (per-ticker, not global)
  - If ANY cached ticker is stale, run Phase 1 to update ALL tickers
  - If ALL cached tickers are fresh, skip Phase 1
- **Phase 2 Filtering**: Screener applies criteria to ALL price_data tickers

---

## API Key Configuration

All API keys are stored in environment variables (`.env` file, not in version control):

```bash
FMP_API_KEY=your_fmp_key_here
FRED_API_KEY=your_fred_key_here
```

**Note**: FMP API is currently disabled (cache-only mode). FRED API is active and required for macro data.

---

## Rate Limits & Performance

| API | Rate Limit | Typical Usage | Bottleneck |
|-----|-----------|--------------|-----------|
| yfinance | None | 1 call/ticker | Low (~0.1s per ticker) |
| FRED | 120/hour | 4 calls/day | Low (async batch) |
| FMP | 300/min (Starter) | Disabled | N/A (cache-only) |

---

## Fallback & Error Handling

- **Price Data**: yfinance → Local cache (7+ years history)
- **Fundamental Data**: Cache-only (FMP API disabled, no fallback needed)
- **Macro Data**: FRED API → Linear interpolation (if data unavailable)
- **Company Profiles**: yfinance → Cache (updated quarterly)
- **Shares Outstanding**: yfinance → Cache (updated quarterly)

---

## Data Freshness Guarantees

- **Price Data**: Updated daily (T+1 from market close)
- **Fundamental Data**: Updated after earnings releases (quarterly)
- **Macro Data**: Updated daily (FRED publishes on various schedules)
- **Company Profiles**: Updated quarterly (IPO dates, sector changes)
- **Screener Universe**: Updated daily (Phase 2)

---

## Known Issues & Limitations

1. **FMP API Disabled**: Due to 401 errors from incorrect API key handling. Migration to yfinance not prioritized (fundamentals not used by models).
2. **Global Staleness Check Bug**: Fixed in Phase 1 (now per-ticker staleness check).
3. **Fundamental Data Quality**: yfinance has 30% field coverage vs FMP's superior data. Cache-only approach maintains 5 years of history for reference.
4. **VWAP Scaling**: Uses standard (H+L+C)/3 formula (not Chinese-market scaling used in WQ101).

---

## References

- yfinance: https://github.com/ranaroussi/yfinance
- FRED API: https://fred.stlouisfed.org/
- Financial Modeling Prep: https://financialmodelingprep.com/
