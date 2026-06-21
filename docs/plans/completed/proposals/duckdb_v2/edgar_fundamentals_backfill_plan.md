# Edgar Fundamentals Backfill — Implementation Plan

**Status**: Ready to implement
**Context**: yfinance backfill complete (4,128 tickers, 2024-present only). Edgar fills 2009–2024 history.

---

## Objective

Populate `fundamentals` table with historical quarterly data (2009–2024) sourced from SEC EDGAR XBRL API, using INSERT OR IGNORE to not overwrite newer yfinance rows.

---

## What We Already Know (from test session)

### API
- **CIK map**: `GET https://www.sec.gov/files/company_tickers.json` → `{ticker: zero-padded-10-digit-CIK}`
- **Company facts**: `GET https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`
- **Rate limit**: 10 req/s official; use 0.15s sleep → ~6 req/s to be safe
- **Headers required**: `{'User-Agent': 'AppName contact@email.com'}`

### Taxonomy (validated on AAPL/JPM/NOW — see `tools/test_edgar_fundamentals.py`)

Priority-ordered tag lists per `fundamentals` column (first tag found wins):

| Column | Tags (priority order) |
|---|---|
| `total_revenue` | `RevenueFromContractWithCustomerExcludingAssessedTax`, `RevenueFromContractWithCustomerIncludingAssessedTax`, `Revenues`, `SalesRevenueNet`, `InterestAndDividendIncomeOperating` |
| `gross_profit` | `GrossProfit` |
| `operating_income` | `OperatingIncomeLoss` |
| `net_income` | `NetIncomeLoss`, `NetIncomeLossAvailableToCommonStockholdersBasic`, `ProfitLoss` |
| `r_and_d` | `ResearchAndDevelopmentExpense`, `ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost` |
| `sga` | `SellingGeneralAndAdministrativeExpense`, `GeneralAndAdministrativeExpense` |
| `total_assets` | `Assets` |
| `current_assets` | `AssetsCurrent` |
| `cash_and_equivalents` | `CashAndCashEquivalentsAtCarryingValue`, `CashCashEquivalentsAndShortTermInvestments`, `Cash` |
| `total_debt` | `DebtLongtermAndShorttermCombinedAmount`, `LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities`, `LongTermDebt` |
| `long_term_debt` | `LongTermDebt`, `LongTermDebtNoncurrent`, `LongTermDebtAndCapitalLeaseObligations` |
| `current_liabilities` | `LiabilitiesCurrent` |
| `stockholders_equity` | `StockholdersEquity`, `StockholdersEquityAttributableToParent` |
| `operating_cash_flow` | `NetCashProvidedByUsedInOperatingActivities`, `NetCashProvidedByUsedInOperatingActivitiesContinuingOperations` |
| `capex` | `PaymentsToAcquirePropertyPlantAndEquipment`, `PaymentsForCapitalImprovements` |

### Known Coverage Gaps (acceptable)
- Banks (JPM): `gross_profit`, `current_assets`, `capex`, `long_term_debt` genuinely absent — not a bug
- SaaS with no debt (NOW): `total_debt`, `long_term_debt` absent — expected

### Shares History (separate concern)
- Edgar `CommonStockSharesOutstanding` (unit=`shares`) → INSERT into `shares_history` table
- NOT into `fundamentals`
- This is a bonus: Edgar gives exact point-in-time shares per filing, better than yfinance's quarterly average

---

## Implementation

### File: `src/fundamental_edgar_engine.py`

Replace the current placeholder entirely. The class has two public methods:

```
FundamentalEdgarEngine
├── __init__(db_path)              — no _ensure_schema (table already exists)
├── backfill(tickers, start_date)  — main entry point
├── _fetch_cik_map()               — one-time SEC fetch
├── _fetch_company_facts(cik)      — per-ticker SEC fetch + sleep
├── _resolve_taxonomy(us_gaap)     — tag priority resolution → {period_end: {col: val}}
├── _upsert_fundamentals(con, df)  — INSERT OR IGNORE (don't overwrite yfinance)
└── _upsert_shares_history(con, df) — bonus: shares_outstanding → shares_history
```

Key design decisions:
1. **INSERT OR IGNORE** — yfinance rows (2024-present) take precedence
2. **10-K and 10-Q only** — filter out 8-K, 10-K/A etc.
3. **`aggfunc='last'` per (ticker, period_end, form)** — handles amendments
4. **Fetch-then-write pattern** — same as FundamentalEngine: parallel fetch (network), sequential write (DuckDB single-writer)
5. **No `_ensure_schema`** — table already created by yfinance backfill

### File: `scripts/backfill_fundamentals_edgar.py`

```
Usage: python scripts/backfill_fundamentals_edgar.py [--start 2009-01-01] [--resume] [--workers N]

Steps:
  1. Load tickers from company_profiles WHERE ticker NOT IN (SELECT DISTINCT ticker FROM fundamentals WHERE period_end < '2024-01-01')
     → Only fetch Edgar for tickers missing historical data
  2. Fetch CIK map (one call)
  3. For each ticker: fetch company facts, resolve taxonomy, collect rows
  4. Batch upsert to fundamentals (INSERT OR IGNORE)
  5. Bonus: upsert shares_outstanding to shares_history
  6. Checkpoint file: save progress every 100 tickers → resume support
```

### Rate Limiting
- `time.sleep(0.15)` after each `_fetch_company_facts` call
- 2-4 workers max (SEC is more lenient than Yahoo but still throttles)
- Expected runtime: ~4,900 tickers × 0.15s / 2 workers ≈ 6 minutes for fetching

---

## Scope of Rows Expected

- AAPL: ~68 quarters (2009–2024) × 4,000 tickers ≈ **~200,000–300,000 rows**
- Many tickers have less history (IPOs post-2015, delistings, etc.)
- Realistic estimate: **~150,000–250,000 rows** added

---

## Downstream (after Edgar backfill complete)

Update column names in these files to use yfinance schema:

| File | Old column | New column |
|---|---|---|
| `src/data_loader_duckdb.py:306` | `f.report_date` | `f.period_end` |
| `src/managers/view_manager.py:437` | `ff.revenue` | `ff.total_revenue` |
| `src/managers/view_manager.py:439` | `ff.total_equity` | `ff.stockholders_equity` |
| `src/managers/view_manager.py:441` | `ff.eps_diluted` | `ff.diluted_eps` |
| `src/managers/view_manager.py:447` | `fundamental_features` table | needs rebuild with new col names |

Full mapping in `docs/session_logs/2026-03-17_fundamentals_schema_migration.md`.

---

## Session Start Checklist

1. Read `tools/test_edgar_fundamentals.py` — the taxonomy and fetch logic is proven, promote it into `FundamentalEdgarEngine`
2. Read `docs/session_logs/2026-03-17_fundamentals_schema_migration.md` — column rename record
3. Confirm `fundamentals` table has yfinance schema: `PRAGMA table_info('fundamentals')`
4. Current state: 25,059 rows, 4,128 tickers, 2024-present only
