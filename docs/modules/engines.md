# Module: Data Engines (T1 ingestion + nightly materializers)

> Verified against code 2026-07-18. Each engine fetches from one external source (or
> aggregates internal tables) and writes one raw/materialized table. Engines contain
> I/O logic only — no feature computation (that is `feature_pipeline.py`) and no
> workflow logic (that is the orchestrator).

## T1 ingestion engines (orchestrator Phase 1)

| Module | Class | Source | Writes | Notes |
|---|---|---|---|---|
| `src/data_engine.py` | `DataRepository` | yfinance | `price_data` | Daily OHLCV for the active universe. `update_cache()` fetches stale tickers only; also used by the Phase 1.5 quality-gate retry. |
| `src/fundamental_engine.py` | `FundamentalEngine` | yfinance (default) or FMP | `fundamentals` | Quarterly IS/BS/CF keyed `(ticker, period_end)`. Only `ticker_type='EQUITY'` tickers are fetched. |
| `src/fundamental_fmp_engine.py` | `FundamentalFmpEngine` | FMP (via `FundamentalEngine(source='fmp')`) | `fundamentals` | Historical backfill path: pivots three stacked statements into one wide row per period. |
| `src/fundamental_edgar_engine.py` | `FundamentalEdgarEngine` | SEC EDGAR XBRL | `fundamentals`, `shares_history` | Deep-history backfill from 10-K/10-Q. `INSERT OR IGNORE` — yfinance rows (2024+) take precedence. ⚠️ Full backfill not yet run (see memory `edgar_fundamentals`). |
| `src/edgar_engine.py` | `EDGARClient`, `EDGAREngine` | SEC submissions API | `cik_map`, `fundamentals.filing_date` | Authoritative 10-Q/10-K filing dates at 10 req/s. Daily bounded backfill (200 tickers/run); weekly CIK-map refresh. `classify_ticker_types()` maps EDGAR form types → `company_profiles.ticker_type` (`EQUITY`/`FOREIGN`/`FUND`/`ETF`/`INDEX`). |
| `src/shares_engine.py` | `SharesEngine` | yfinance | `shares_history` | Historical shares outstanding; must run after prices. |
| `src/macro_engine.py` | `MacroEngine` | FRED, yfinance, CNN, AAII | `t1_macro`, `macro_data` | Two tables on purpose: `t1_macro` = SPY/QQQ OHLCV + VIX close (the T2 benchmark source); `macro_data` = long-format FRED/VIX/AAII/Fear&Greed series (regime + Macro page). Fear&Greed needs `curl_cffi` impersonation (CNN 418-blocks plain clients). New `macro_data` series need no extra wiring downstream. |
| `src/earnings_engine.py` | `EarningsEngine` | yfinance/FMP | `earnings_calendar` | Earnings release dates; drives fundamentals staleness checks and the backtest earnings overlay. |
| `src/company_profile_engine.py` | `CompanyProfileEngine` | FMP | `company_profiles` | Sector/industry/metadata; the universe seed. `is_active`, `delisting_date`, `ticker_type` govern the ticker lifecycle. |
| `src/universe_backfill.py` | `UniverseBackfillEngine` | FMP discovery | `company_profiles` + price/shares backfill | Initial universe seed and `quarterly_refresh()` (new-listing discovery). Only runs when the pipeline is invoked with `universe_refresh=True` — never automatic. |

## Derived/materializer engines (orchestrator Phases 7.45–7.46 + macro add-ons)

| Module | Class | Reads | Writes | Notes |
|---|---|---|---|---|
| `src/cape_engine.py` | `CapeEngine` | `price_data`, `shares_history`, `fundamentals`, FRED CPI | `macro_data` (`CAPE_OURS`) | Self-computed aggregate market CAPE (Shiller workbook is dormant). Display-only valuation pillar; winsorization of the EPS aggregate is load-bearing. |
| `src/weather_engine.py` | `WeatherEngine` | MacroSizer signals + breadth | `weather_gauge` | One row/day deploy-posture state (Phase 7.45). Assembly of validated signals (SPY>200d brake, expanding-z stress composite), not new research. Full recompute each night (expanding stats need all history). |
| `src/sector_breadth_engine.py` | `SectorBreadthEngine` | `t2_screener_features` ⋈ `company_profiles` | `sector_breadth` | Latest-day snapshot per (grain, sector/subsector) for the Macro page heatmap (Phase 7.46). Rendering job — the dashboard never re-scans feature tables per pageload. |

## Design rules

- **One engine, one table.** An engine never writes another engine's table
  (exception: the EDGAR fundamentals backfill also inserts `shares_history`, guarded
  by `INSERT OR IGNORE`).
- **Idempotent upserts.** Engines use `INSERT OR REPLACE`/`OR IGNORE` patterns so
  re-running an ingestion date is safe.
- **Plausibility clamps live in the engine, ceilings in the gate.** Engines clamp/warn
  on absurd values at write time; orchestrator Phase 1.6 enforces FAIL-level ceilings
  (`config.T1_PLAUSIBILITY_BOUNDS`) and withholds the R2 publish when they fire.

## Data gotchas (verified, still live)

- `price_data.adj_close` / `adj_factor` / `vwap` are 100% NULL — compute returns from `close`.
- `price_data.volume` is `UBIGINT` — `CAST(volume AS BIGINT)` before subtraction.
- `company_profiles.listing_date` is 100% NULL — use `MIN(date)` from `price_data` as the age proxy.
- Corrupt OHLC: extreme bad highs were source-nulled 2026-07-10; extreme lows were
  deliberately KEPT (real flash crashes). Bound excursions with `GREATEST/LEAST(close, ...)`.
- `detect_bad_tickers` only warns — junk tickers (e.g. LIF, CUE) can reach backtests.

## Related

- Orchestration and sub-phase order: [orchestrator.md](orchestrator.md)
- Ticker lifecycle CLIs (deactivate/rename/purge): `tools/`, documented in
  [manual_for_me.md](../architecture/manual_for_me.md)
