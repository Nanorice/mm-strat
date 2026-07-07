# Session Handover: 2026-03-17 (EDGAR Fundamentals)

## 🎯 Goal
Implement SEC EDGAR XBRL fundamentals backfill engine to populate historical data (2009–2024) for 4,128 tickers, complementing the existing yfinance data (2024-present).

## ✅ Accomplished

- **`src/fundamental_edgar_engine.py`** — Full implementation replacing placeholder:
  - `_resolve_tag()`: priority-ordered tag resolution with shortest-period-wins dedup (standalone quarterly beats YTD cumulative)
  - `_resolve_fundamentals()`: anchors rows on duration-fact keys only (income/cashflow), preventing balance-sheet-only null rows
  - `_resolve_shares()`: extracts `CommonStockSharesOutstanding` → `shares_history`
  - `backfill(overwrite_edgar=True)`: parallel fetch, sequential DuckDB write, INSERT OR IGNORE
  - Expanded TAXONOMY covering 11 sectors: added `SalesRevenueGoodsNet`, `RevenueMineralSales`, `RevenuesNetOfInterestExpense`, `PaymentsToAcquireProductiveAssets`, `SeniorNotes`, `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`, `MarketingAndAdvertisingExpense`, etc.

- **`scripts/backfill_fundamentals_edgar.py`** — Full CLI:
  - `--tickers AAPL JPM NOW` — test run on specific tickers
  - `--dry-run` — fetch + resolve without DB write
  - `--report` — print quality report after writing
  - `--overwrite` — DELETE edgar rows before re-inserting (yfinance untouched)
  - `--resume` — checkpoint-based resume for full backfill
  - `print_quality_report()` — per-ticker coverage: populated/partial/missing cols + spot-check values

- **`fundamentals` table** — Added `period_type VARCHAR` column (`'annual'` / `'quarterly'`), backfilled `'quarterly'` for all yfinance rows

- **Taxonomy audit** — Validated across 27 tickers spanning all 10 GICS sectors; documented structural gaps vs fixable gaps

## 📝 Files Changed

- `src/fundamental_edgar_engine.py`: Full rewrite from placeholder — EDGAR fetch, taxonomy resolution, DuckDB upsert
- `src/fundamental_engine.py`: Added `period_type='quarterly'` to yfinance row construction and upsert col list
- `scripts/backfill_fundamentals_edgar.py`: New script — CLI entrypoint with test/dry-run/report/overwrite/resume modes

## 🚧 Work in Progress (CRITICAL)

- **8,925 old edgar rows have `period_type = NULL`** — these were inserted in a prior session before `period_type` was added. They will remain NULL until `--overwrite` is run on those tickers. Full backfill with `--overwrite` will fix all of them.
- **Full backfill not yet run** — only 27 sample tickers have been processed. 4,128 tickers still need `python scripts/backfill_fundamentals_edgar.py --start 2009-01-01 --workers 2` (estimated ~6 min fetch time).
- **BHP and foreign filers** — BHP files as a foreign private issuer (20-F), not 10-K/10-Q. Will log `WARNING: no duration data resolved` and produce no rows. This is expected for ~50-100 foreign filers in the universe.

## ⏭️ Next Steps

1. **Run full backfill**: `python scripts/backfill_fundamentals_edgar.py --start 2009-01-01 --workers 2 --overwrite` — this replaces old NULL `period_type` rows and fills all 4,128 tickers
2. **Schema migration in downstream code** (from `docs/proposals/duckdb_v2/edgar_fundamentals_backfill_plan.md`):
   - `src/data_loader_duckdb.py:308`: `f.report_date` → `f.period_end`
   - `src/managers/view_manager.py:437`: `ff.revenue` → `ff.total_revenue`
   - `src/managers/view_manager.py:439`: `ff.total_equity` → `ff.stockholders_equity`
   - `src/managers/view_manager.py:441`: `ff.eps_diluted` → `ff.diluted_eps`
   - Rebuild `fundamental_features` table with new column names
3. **TTM / YoY computation** — now that `period_type` exists, implement TTM revenue as `SUM(total_revenue) WHERE period_type='quarterly' ORDER BY period_end DESC LIMIT 4`

## 💡 Context/Memory

- **Taxonomy priority = gap-fill, not first-wins**: The final `_resolve_tag` iterates ALL tags and merges results — higher-priority tags win for overlapping periods, lower-priority tags backfill older history. This handles companies that switched XBRL tags mid-history (e.g. AAPL used `SalesRevenueNet` pre-2017, then `RevenueFromContractWithCustomerExcludingAssessedTax` post-2017). The original first-tag-wins logic caused 47% null on `total_revenue`.

- **Duration vs instant fact anchoring**: EDGAR balance sheet items are "instant" facts (no `start` date) and appear at every quarter-end. Income statement items are "duration" facts and only exist when a P&L was filed. Using `all_keys = union(all columns)` caused 25-60% null income statement columns because balance-sheet-only keys had no P&L data. Fix: anchor rows only on `duration_keys` (income/cashflow columns).

- **Shortest-span wins for quarterly dedup**: EDGAR stores both standalone Q3 ($94B) and YTD-cumulative Q3 ($313B) with the same `(end_date, form=10-Q)` key but different `start` dates. Must pick shortest span (≈90 days = standalone quarterly). The original last-filed logic picked YTD for some periods.

- **Structural gaps that are NOT bugs** (document to avoid re-investigation):
  - `gross_profit`: absent for banks, telecoms, REITs, utilities — they don't compute this subtotal
  - `operating_income`: absent for energy (CVX), pharma (JNJ), mining (NEM) — they go revenue → pre-tax income
  - `current_assets`/`current_liabilities`: absent for banks (JPM) — regulatory capital structure doesn't separate current/non-current
  - `capex`: absent for REITs (DLR) — they invest via property acquisition, not PP&E
  - `total_debt`/`long_term_debt`: absent for no-debt companies (NOW pre-2020) and REITs with fragmented debt structures

- **`period_type` semantics**: `'annual'` = 10-K filing (full fiscal year, e.g. AAPL Sep: $416B), `'quarterly'` = 10-Q filing (standalone quarter, e.g. AAPL Dec: $144B). The PK stays `(ticker, period_end)` — we deduplicate to one row per date, keeping the standalone quarterly when both forms exist for the same date. The 10-K annual row only survives when it's the only filing for that fiscal year-end date (AAPL's case — they don't file a separate Q4).
