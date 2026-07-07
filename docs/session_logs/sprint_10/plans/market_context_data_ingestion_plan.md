# Market Context Data Ingestion Plan

> Created: 2026-05-12  
> Status: PLANNING — not yet implemented  
> Related: `development_roadmap.md` item 2 (5-Factor Risk Model), item 9 (M03 Enhancement)

---

## Background

This plan covers adding two categories of new data to the pipeline:

1. **Benchmark & sector ETFs** — tradeable instruments (indices, sectors, commodities) that will flow through the full T2/T3 pipeline and be SEPA-eligible.
2. **Non-tradeable rate series** — FRED series needed by the 5-factor risk model (`DGS10`, `DGS2`, `WBAA`) stored in `macro_data`.

---

## Storage Architecture Decision

### Key facts confirmed

- **`price_data`** — long format: `(ticker, date)` PK, one row per ticker per day. Currently 15.8M rows across 4,135 tickers. This is the correct format for DuckDB columnar storage — queries filter by date range or ticker efficiently via predicate pushdown on sorted columns.
- **`macro_data`** — also long format: `(date, symbol)` PK, one row per series per day. Uses a `PIVOT` (conditional aggregation) at read time in `get_macro_data()`. Currently holds WALCL, WTREGEN, RRPONTSYD, BAMLH0A0HYM2, VIX, and derived net liquidity series.
- **`t1_macro`** — **wide format** (legacy design): one row per date, columns `spy_close`, `spy_high`, `spy_low`, `spy_volume`, `qqq_*`, `vix_close`. This is the exception — it was built for just 3 instruments and is used directly by `feature_pipeline.py` for the SPY benchmark in T2 feature computation.

### Decision

| Data type | Table | Format | Rationale |
|---|---|---|---|
| Benchmark & sector ETFs (SPY, QQQ, IWM, XLE, GLD, etc.) | **`price_data`** | Long `(ticker, date)` | They are OHLCV time series identical to equities. Flows into T2/T3 naturally. |
| Commodity ETFs (GLD, SLV, CPER, USO, etc.) | **`price_data`** | Long `(ticker, date)` | Same as above. SEPA-eligible. |
| FRED rate series (DGS10, DGS2, WBAA) | **`macro_data`** | Long `(date, symbol)` | Non-tradeable, no volume, weekly frequency. Consistent with existing FRED series. |
| `t1_macro` (SPY/QQQ/VIX wide) | **keep as-is** | Wide columns | `feature_pipeline.py` reads `spy_close` directly from this table by column name. Refactoring to long format would require changes to T2 SQL CTE — too much disruption for no benefit. The 3-instrument wide table is fine at this scale. |

### Why long format is correct for DuckDB

DuckDB is a columnar store. A long table with `(ticker, date)` means:
- The `ticker` column stores values like `['SPY','SPY','SPY',...]` — highly compressible (run-length encoding).
- The `date` column is sorted and compressible.
- A query like `WHERE ticker = 'SPY' AND date BETWEEN ...` uses predicate pushdown — reads only the relevant row groups.

A wide table with one column per ticker (e.g., `spy_close`, `qqq_close`, `iwm_close`, ...30 more) would:
- Require schema changes every time a ticker is added.
- Read all columns even when only one ticker is needed.
- Be unmaintainable at 30+ instruments.

**The existing `t1_macro` wide format is a legacy exception — do not replicate it.**

---

## Ticker Universe

### Category 1: Broad Market Benchmarks (add to `price_data` + `company_profiles`)

| Ticker | Name | Notes |
|---|---|---|
| `SPY` | S&P 500 ETF | Already in `t1_macro`; add to `price_data` + `company_profiles` |
| `QQQ` | Nasdaq-100 ETF | Already in `t1_macro`; add to `price_data` + `company_profiles` |
| `^GSPC` | S&P 500 Index | Used by 5F model for trend/slope factors; store as `GSPC` |
| `^DJI` | Dow Jones | Store as `DJI` |
| `^IXIC` | Nasdaq Composite | Store as `IXIC` |
| `IWM` | Russell 2000 ETF | Small cap |
| `EFA` | iShares MSCI EAFE | Developed ex-US |
| `EEM` | iShares MSCI EM | Emerging markets |

### Category 2: Sector ETFs (add to `price_data` + `company_profiles`)

| Ticker | Sector |
|---|---|
| `XLE` | Energy |
| `XLF` | Financials |
| `XLK` | Technology |
| `XLV` | Healthcare |
| `XLI` | Industrials |
| `XLY` | Consumer Discretionary |
| `XLP` | Consumer Staples |
| `XLU` | Utilities |
| `XLB` | Materials |
| `XLRE` | Real Estate |
| `SOXX` | Semiconductors (iShares) |
| `IBB` | Biotech (iShares) |
| `KRE` | Regional Banks |
| `XOP` | Oil & Gas E&P |

### Category 3: Commodity ETFs (add to `price_data` + `company_profiles`)

All are ETF proxies — futures not viable due to yfinance 3-6 month history limit on front-month contracts. Continuous backadjusted futures would require a paid data source (Refinitiv, IBKR, Barchart) — deferred.

| Ticker | Commodity | Proxy type | Inception |
|---|---|---|---|
| `GLD` | Gold | SPDR Gold ETF | 2004 |
| `SLV` | Silver | iShares Silver ETF | 2006 |
| `CPER` | Copper | US Copper Index Fund | 2011 |
| `USO` | WTI Crude Oil | United States Oil Fund | 2006 |
| `BNO` | Brent Crude Oil | United States Brent Oil | 2010 |
| `UNG` | Natural Gas | United States Nat Gas Fund | 2007 |
| `SOYB` | Soybeans | Teucrium Soybean Fund | 2011 |
| `WEAT` | Wheat | Teucrium Wheat Fund | 2011 |
| `CORN` | Corn | Teucrium Corn Fund | 2010 |
| `VEGI` | Bean Oil / Agri | iShares MSCI Agriculture (includes soybean oil exposure) | 2012 |
| `DBA` | Agriculture broad | Invesco DB Agriculture | 2007 |
| `PDBC` | Commodities broad | Invesco Optimum Yield (includes metals, energy, ag) | 2014 |
| `URA` | Uranium | Global X Uranium ETF | 2010 |

> **Note on soybean oil**: No pure soybean oil ETF exists. `VEGI` (iShares MSCI Agriculture) holds agricultural commodity producers with broad exposure including soybean oil. `DBA` holds futures on soybean oil directly. Both are reasonable proxies.

> **Note on aluminum**: No US-listed pure aluminum ETF. `PDBC` has ~5% aluminum allocation. `PDAL` (Aberdeen) was delisted. LME aluminum is not available via yfinance. Best proxy is `PDBC` for commodity basket exposure.

> **Note on futures**: Industry approach for continuous contracts is Panama backadjustment (ratio splice at roll date). Requires IBKR API, Quandl Premium, or Refinitiv. Not in scope for this task — revisit if dedicated commodity signal research is needed.

### Category 4: Fixed Income & Dollar (add to `price_data` + `company_profiles`)

| Ticker | Name |
|---|---|
| `TLT` | iShares 20Y+ Treasury |
| `HYG` | iShares High Yield Corporate Bond |
| `LQD` | iShares Investment Grade Corporate Bond |
| `UUP` | Invesco DB US Dollar Index Bullish |

### Category 5: FRED Rate Series (add to `macro_data` — long format)

| Symbol | Name | Used by |
|---|---|---|
| `DGS10` | 10Y Treasury yield (daily) | 5-factor model `f_term`, `f_slope` |
| `DGS2` | 2Y Treasury yield (daily) | 5-factor model `f_term` |
| `WBAA` | Moody's Baa corporate yield (weekly) | 5-factor model `f_hy` proxy (replaces restricted `BAMLH0A0HYM2`) |

**Already present — no action needed**: `WALCL`, `WTREGEN`, `RRPONTSYD`, `BAMLH0A0HYM2`, `VIX`.

---

## Treatment in Downstream Pipeline

### T1 — Ingestion

ETFs/indices added to `price_data` via the existing `DataRepository` (yfinance path). No special handling needed — same OHLCV fetch as equities.

FRED rate series added via `MacroEngine.fetch_fred_series()` → `macro_data` table. Already has the right infrastructure.

### T2 — Screener Membership & Features

ETFs need entries in `company_profiles` with a distinct `ticker_type = 'ETF'` (or `'INDEX'` for `^GSPC` etc.) and `sector = 'Benchmark'` / actual sector for sector ETFs.

`ScreenerManager` criteria (close ≥ $5, avg_volume_20d ≥ 100K, market_cap ≥ $150M) — ETFs will easily pass price and volume criteria. Market cap is computed from shares × price; ETFs have AUM-based implied market cap. **Simplest approach**: hard-code these tickers as always-eligible in `screener_membership`, bypassing the market cap check. Alternatively add a `skip_market_cap_check` flag to screener criteria.

T2 feature computation runs identically — OHLCV, SMAs, RS rating, SEPA flags all compute from price data regardless of ticker type.

Cross-sectional ranks (`RS_Universe_Rank`, `RS_Sector_Rank`) will include ETFs in the population. This is intentional — an XLE SEPA breakout ranks against the universe.

### T3 — SEPA Features

ETFs flow through `sepa_watchlist` and `t3_sepa_features` identically to equities. SEPA breakout signals on sector ETFs are actionable.

### Model Scoring — No Score for ETFs

ETFs have no fundamentals (`pe_ratio`, `ps_ratio`, `pb_ratio`, `net_income`, `revenue` etc.). Rather than letting XGBoost handle missing values (which it can but inconsistently), **ETFs receive no M01 score**. 

Implementation: `UniverseScorer.score_from_duckdb()` should skip rows where `ticker_type IN ('ETF', 'INDEX')` in `company_profiles`. The dashboard shows them in the SEPA watchlist table with `score = N/A`.

This is the cleaner approach — avoids systematic bias from missing fundamental features across a whole class of securities.

---

## Implementation Plan

### Phase A — `company_profiles` Schema Extension

Add `ticker_type VARCHAR` column to `company_profiles`:
- Values: `'EQUITY'` (default for existing rows), `'ETF'`, `'INDEX'`
- Existing rows default to `'EQUITY'`

```sql
ALTER TABLE company_profiles ADD COLUMN ticker_type VARCHAR DEFAULT 'EQUITY';
```

Insert new rows for all ETF/index tickers with appropriate metadata.

**File**: one-time migration script `scripts/add_benchmark_tickers.py`

### Phase B — MacroEngine: Add FRED Rate Series

Extend `MacroEngine` to fetch `DGS10`, `DGS2`, `WBAA` via existing `fetch_fred_series()` infrastructure.

Add these to `config.py` `FRED_SERIES` dict. They will be fetched automatically by `update_macro_cache()` and written to `macro_data` in the existing long format.

**Verify**: `macro_data` schema already supports arbitrary symbols — no DDL change needed. The `(date, symbol)` PK handles it.

**File**: `config.py` + `src/macro_engine.py` (minor extension)

### Phase C — DataRepository: Fetch ETFs into `price_data`

ETFs/indices need to be fetched via yfinance. They should be treated as always-active tickers (no staleness skip). The existing `DataRepository.fetch_price_data()` handles this if the tickers are in `company_profiles`.

Check: does `DataRepository` skip tickers not in `screener_membership`? If so, ETFs need to be pre-enrolled.

**File**: `src/data_engine.py` (verify no ETF-specific exclusion logic)

### Phase D — Screener Membership: ETF Bypass

Modify `ScreenerManager.evaluate_and_log()` to auto-enroll tickers where `ticker_type IN ('ETF', 'INDEX')` without market cap check. These tickers are always eligible.

**File**: `src/managers/screener_manager.py`

### Phase E — Backfill Scripts

Two backfill operations needed:

**E1 — Price backfill for new tickers** (adapt `run_universe_backfill.py`):
```bash
python scripts/run_universe_backfill.py --backfill-prices --tickers SPY QQQ IWM XLE ... --start-date 1990-01-01
```
The existing backfill script should already support `--tickers` filtering if not — add it.

**E2 — FRED rate series backfill**:
```bash
python scripts/backfill_macro_rates.py --start 1990-01-01
```
New script that fetches DGS10, DGS2, WBAA from FRED back to 1990 (needed for 5F model z-score warmup with 10-year window).

### Phase F — Model Scoring: ETF Exclusion

In `UniverseScorer.score_from_duckdb()`, filter out ETF/INDEX tickers before scoring:
```python
# Skip ETFs — no fundamentals, model would be unreliable
scored_df = scored_df[scored_df['ticker_type'] == 'EQUITY']
```

**File**: `src/backtest/universe_scorer.py`

---

## Clarifications Still Needed

- [ ] `run_universe_backfill.py` — does it support `--tickers` flag for targeted backfill? Need to check and add if missing.
- [ ] `ScreenerManager` — how market cap is computed for ETFs (needs shares_outstanding or AUM-based approach). Simplest: `ticker_type='ETF'` bypasses market cap check entirely.
- [ ] `^GSPC`, `^DJI`, `^IXIC` — yfinance uses `^` prefix. Store in `price_data` as `GSPC`, `DJI`, `IXIC` (strip caret) for clean primary key. Pipeline must strip caret on ingest.

---

## Files To Create / Modify

| File | Action | Purpose |
|---|---|---|
| `config.py` | Modify | Add DGS10, DGS2, WBAA to `FRED_SERIES`; add `BENCHMARK_TICKERS` and `ETF_TICKERS` lists |
| `scripts/add_benchmark_tickers.py` | Create | One-time: add ticker_type column + insert ETF/INDEX rows into company_profiles |
| `scripts/backfill_benchmark_prices.py` | Create | Backfill price_data for new ETF/INDEX tickers from 1990 |
| `scripts/backfill_macro_rates.py` | Create | Backfill DGS10/DGS2/WBAA into macro_data from 1990 |
| `src/macro_engine.py` | Modify | Add DGS10/DGS2/WBAA fetch support |
| `src/managers/screener_manager.py` | Modify | Auto-enroll ETF/INDEX tickers; bypass market cap check |
| `src/backtest/universe_scorer.py` | Modify | Skip ETF/INDEX tickers from M01 scoring |
| `src/data_engine.py` | Verify/Modify | Ensure no exclusion of non-equity tickers |

---

## Out of Scope (this task)

- Continuous backadjusted futures contracts — requires paid data source
- 5-factor model integration into daily pipeline — separate task (roadmap item 2)
- Dashboard changes to display benchmark ETF SEPA signals — separate task (roadmap item 3)
- M03 z-score enhancement using new rate data — separate task (roadmap item 9)
