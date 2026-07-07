# Fundamentals Schema Migration — 2026-03-17

## Decision
Migrate `fundamentals` table from legacy FMP/parquet schema to yfinance schema.
yfinance is canonical going forward. Edgar backfills gaps using the same schema.

## Column Renames (old → new)

| Old (FMP/live)            | New (yfinance)              | Notes                          |
|---------------------------|-----------------------------|--------------------------------|
| `report_date`             | `period_end`                | PK component                   |
| `period_type`             | —                           | Dropped; `form_type` replaces  |
| `revenue`                 | `total_revenue`             |                                |
| `total_equity`            | `stockholders_equity`       |                                |
| `total_current_assets`    | `current_assets`            |                                |
| `total_current_liabilities` | `current_liabilities`     |                                |
| `eps_diluted`             | `diluted_eps`               |                                |
| —                         | `basic_eps`                 | New, not in old schema         |
| —                         | `basic_avg_shares`          | New                            |
| —                         | `diluted_avg_shares`        | New                            |
| —                         | `ebit`                      | New                            |
| —                         | `ebitda`                    | New                            |
| —                         | `r_and_d`                   | New                            |
| —                         | `sga`                       | New                            |
| —                         | `net_debt`                  | New                            |
| —                         | `retained_earnings`         | New                            |
| —                         | `working_capital`           | New                            |
| —                         | `invested_capital`          | New                            |
| —                         | `tangible_book_value`       | New                            |
| —                         | `stock_based_comp`          | New                            |
| —                         | `change_in_working_capital` | New                            |
| —                         | `depreciation_amortization` | New                            |
| —                         | `shares_outstanding`        | Dropped; owned by `SharesEngine` → `shares_history`. Edgar will backfill that table separately. |
| `pe_ratio`                | —                           | Dropped; computed in view      |
| `ps_ratio`                | —                           | Dropped; computed in view      |
| `pb_ratio`                | —                           | Dropped; computed in view      |
| `peg_ratio`               | —                           | Dropped; computed in view      |
| `market_cap`              | —                           | Dropped; lives in company_profiles |
| `raw_data`                | —                           | Dropped; JSON blob not needed  |

## PK Change
- Old: `(ticker, report_date, period_type)` — 3-part key
- New: `(ticker, period_end)` — 2-part key

## Downstream Touch Points
Files that reference old column names and need updating after backfill completes:

1. `src/data_loader_duckdb.py` — ASOF JOIN on `fundamentals.report_date`
2. `src/managers/view_manager.py` — `v_d2_features` references `ff.revenue`, `ff.total_equity`, `ff.eps_diluted`, `ff.eps_growth_yoy`, `ff.filing_date`, `ff.fiscal_period`
3. `src/fundamental_edgar_engine.py` — placeholder schema uses old column names
4. `scripts/audit_fundamental_schema.py` — references `report_date`, `revenue`
5. `scripts/backfill_fundamentals_columns.py` — old schema hardcoded
6. `scripts/backfill_fundamental_ratios.py` — references `total_equity`, `revenue`

## Source of Truth
- `FundamentalEngine` (`src/fundamental_engine.py`) — yfinance schema, `_INCOME_MAP` / `_BALANCE_MAP` / `_CASHFLOW_MAP`
- `FundamentalEdgarEngine` (`src/fundamental_edgar_engine.py`) — will adopt same schema

## Data
- Old rows: 387,231 (backed up in parquet under `data/fundamentals/`)
- New population: ~4,909 tickers from `company_profiles`
- Strategy: yfinance first → Edgar gap-fill second
