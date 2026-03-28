# T1 Data Quality Findings & Cleanup Plan

Audit date: 2026-03-18
Tool: `tools/audit_t1_data_quality.py`

---

## F1 — Fundamentals: orphan tickers (1,258 tickers) ✅ RESOLVED

**What**: `fundamentals` has 1,258 tickers not in `company_profiles` — 1,137 yfinance + 665 edgar (overlap exists).
**Cause**: Historical data ingested before the current universe was defined. These tickers were later excluded/purged from `company_profiles` but their fundamentals rows were never cleaned up.
**Risk**: Low — joins to `company_profiles` filter them out of model training. But they bloat the table and confuse audits.
**Resolution**: Covered by F6+F7 purge below — all orphans removed in the same DELETE. `tools/purge_t1_fundamentals.py`

---

## F2 — Price/Shares coverage gaps ✅ RESOLVED

**What**: After blacklist cleanup, 6 tickers had no price data and 490 had no shares history.
**Cause**: Mix of (a) legitimate tickers missed in backfill, (b) SPAC/preferred/debt instruments that slipped through the blacklist filter (hyphenated tickers, `-UN`/`-WT`/`-P` suffixes).
**Resolution** (2026-03-20):
- Blacklisted 19 SPAC/unit/debt instruments manually (`reason='spac_unit_or_debt_instrument'`).
- Blacklisted 1,697 tickers with no FMP fundamentals via `--blacklist-no-fundamentals` (SPACs, warrants, shells).
- Blacklisted 7 tickers with no shares history (`reason='no_shares_history'`): AKTS, BIPI, CBIO, CHSCL, TTRX, VATE, VHI.
- Purged all blacklisted tickers from all T1 tables.
- Added FMP fallback to `backfill_prices` in `src/universe_backfill.py` — yfinance failures now retry via `DataRepository._fetch_fmp_historical`.
- Fixed `_write_company_profiles` to set `is_active=TRUE` on upsert and `is_active=FALSE` for tickers no longer returned by FMP screener.
- Re-ran `--discover-fmp` to sync `is_active` flags across all 4,316 tickers.
- Re-ran `--backfill-prices` + `--backfill-shares` for newly discovered tickers.

**Final state** (2026-03-20): Universe **4,316 tickers**. Price **100%**, Shares **99.9%**, Fundamentals **100%**. Zero orphans across all tables.

**Stale price warning** (`price_data_stale_tickers`): 1,818 active tickers show last price ~2026-02-18. Root cause is the **daily pipeline not having run since Feb 18** — not a data issue. Will resolve once pipeline resumes. Audit check now correctly filters to `is_active=TRUE` only.

---

## F3 — Price data: negative close prices (5,344 rows) ✅ RESOLVED

**What**: 5,344 rows across 3 tickers (VATE: 2,729, CBIO: 2,189, VHI: 426) with `close <= 0`.
**Cause**: Systematic sign inversion in historical ingestion (pre-validation-guard era) — all OHLC values are negative, not just close. This is a sign-flip artifact, not zero-volume or halted trading. Both FMP and yfinance return positive adjusted prices for these tickers; the bug was in old ingestion code since fixed.
**Risk**: Medium — corrupts any ratio or return calculation touching these date ranges.
**Decision**: Full delete and re-ingest from FMP — cleaner than row-level purge. `tools/purge_t1_price_negatives.py` remains available for future occurrences.
**Resolution** (2026-03-20): Deleted all rows for VATE, CBIO, VHI from `price_data`, `shares_history`, `fundamentals`, `company_profiles`. Re-inserted profiles manually (FMP `/profile` returns 404 for these tickers but `/historical-price-eod/full` works). Re-ingested 12,265 rows of clean FMP price data: VATE (4,199 rows, 2009–2026), CBIO (3,066 rows, 2014–2026), VHI (5,000 rows, 2006–2026). Zero non-positive close rows confirmed post-ingest.

---

## F4 — Price data: extreme moves >200% in a single day (monitored)

**What**: 697+ rows with single-day close-to-close price change exceeding 200%, across 135 tickers.
**Cause**: Two distinct categories:
  1. **Reverse splits / corporate actions** (legitimate but unadjusted): e.g. BMNR ($640 → $64,640), RCAT, GAME.
  2. **Data corruption** (sub-penny stocks, extreme ratios): ABVC (max +416,567%), AYTU, NXPL, MRDN.
**Risk**: Medium — extreme feature values for affected tickers/dates; universe screener ($15 min price) already filters out most sub-penny cases.
**Decision**: Leave as-is for now. Screener filter provides natural protection. Monitor via audit tool.
**Audit enhancement**: `tools/audit_t1_data_quality.py` now logs `extreme_movers_top20` — top 20 tickers by event count with max move % (e.g. `PRG:431x(max 1659%) | SRXH:9x(max 99900%)`).

---

## F5 — Fundamentals: 1 row with future `period_end`

**What**: One row with `period_end > today`.
**Cause**: Likely a forward estimate accidentally stored as a filed period.
**Risk**: Low in isolation, but signals ingestion logic is not validating dates.
**Action**: Identify and delete the row; add a validation guard in the ingestion engine.

---

## F6 — Fundamentals: edgar annual rows coexisting with FMP quarterly (11,232 rows) ✅ RESOLVED

**What**: 11,232 annual (10-K) rows from edgar, of which ~3,200 sit alongside FMP quarterly for the same fiscal year. Annual rows never collide on PK because `period_end` dates differ from quarterly rows.
**Cause**: Edgar engine fetched annual filings; FMP only stores quarterly.
**Risk**: Medium — any pipeline joining `fundamentals` to price data without filtering `period_type` may pick up annual rows and double-count or use stale figures.
**Decision**: Remove all edgar rows. Edgar field mapping is not comprehensive enough to distinguish industry nuances; FMP/yfinance provide better-normalised coverage for all active universe members. All 1,887 edgar tickers either have FMP/yfinance coverage or are orphans.
**Resolution**: `tools/purge_t1_fundamentals.py` — deletes all `source='edgar'` rows + all orphan rows in a single DELETE. Net: 44,665 rows removed (13%), 299,121 remaining.

---

## F7 — Fundamentals: 2,682 NULL `period_type` rows (all edgar) ✅ RESOLVED

**What**: Old edgar rows predating the `period_type` column. Examples: LOW, ETN, AVGO.
**Cause**: Schema column added after initial edgar ingest; rows were never backfilled.
**Risk**: Low-medium — if pipeline treats NULL as "include", these can slip through alongside F6 annual rows.
**Resolution**: Removed as part of F6 purge (all edgar rows deleted). `tools/purge_t1_fundamentals.py`

---

## Priority Order

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | F3 — negative close prices | High | ✅ Resolved (deleted + re-ingested from FMP) |
| 2 | F2 — price/shares coverage gaps | High | ✅ Resolved (100% price, 99.9% shares, 100% fundamentals) |
| 3 | F6+F7 — annual rows + NULL period_type | Medium | ✅ Resolved |
| 4 | F4 — extreme price moves | Medium | Monitored via audit tool |
| 5 | F5 — future period_end | Low | Pending — identify row + add ingestion guard |
| 6 | F1 — orphan fundamentals | Low | ✅ Resolved |
