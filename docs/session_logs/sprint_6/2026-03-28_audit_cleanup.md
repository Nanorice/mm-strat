# Session Handover: 2026-03-28 (Audit Cleanup)

## 🎯 Goal
Investigate all 19 warnings from the 2026-03-28 audit report and resolve the legitimate ones — reducing noise so remaining warnings are actionable signals.

## ✅ Accomplished

### DB Fixes
- **27 screener_membership exit events injected** for tickers where `cp.is_active=FALSE` but latest screener row was still `is_active=TRUE`. These were all 2026-03-22 delisting batch tickers that the screener never formally exited.
- **GE Aerospace restored** to `company_profiles` as active (`is_active=TRUE`, sector=Industrials, ~$298B market cap). Was erroneously missing after the 2023/2024 GE restructuring (GE→GEV+GEHC spinoffs). Successor tickers GEV and GEHC were already in CP, but GE Aerospace (which kept the GE ticker) was not.
- **167 orphan equity tickers purged** from `shares_history` and `fundamentals`; 1 orphan (`AIB`) from `price_data`. These were regular equity tickers present in T1 tables but not in `company_profiles` — residue from prior universe cleanup cycles. Warrants (`*W`, `*-WT`), preferred (`*-PA/PB`), and rights (`*-RI`) were intentionally kept (26 remaining).

### Audit Logic Fixes
- **`audit_t1_data_quality.py`** — `missing_from_cp` check now counts only `is_active=TRUE` tickers (inactive/delisted correctly excluded); `orphan_tickers` check excludes warrants/preferred/rights from WARNING count, reports them as INFO only.
- **`audit_t2_membership.py`** — `active_tickers_no_recent_price` now filters to `cp.is_active=TRUE` tickers only, eliminating 27 false-positive ghost ticker warnings for recently delisted tickers.
- **`audit_t2_screener_features.py`** — RS and rank column null checks now split nulls into warmup window (first 270 rows/ticker) vs post-warmup. If all nulls are within warmup, status downgrades to INFO (expected — RS requires 252d lookback). Post-warmup nulls still trigger WARNING. Added `_warmup_null_split()` helper. Result: 8 spurious rank warnings eliminated; 1.8% post-warmup rank nulls still correctly flagged.

### New Fix Modes in patch_fundamentals.py
- **`--fix filing_date_zero`**: For rows where `filing_date = period_end` (FMP placeholder). Looks up actual filing date from SEC EDGAR (`data.sec.gov/submissions`) using ticker→CIK map. Falls back to `period_end + 45d` if no EDGAR match. ~55K rows affected.
- **`--fix filing_date_stale_historical`**: For rows where `filing_date > period_end + 90d`. Gaps >365d are NULLed (FMP back-populated historical data using download date). Gaps 91-365d try EDGAR first, NULL on no match. ~6.4K rows affected.

## 📝 Files Changed
- `tools/audit_t1_data_quality.py`: `missing_from_cp` scoped to active tickers; `orphan_tickers` excludes warrants/preferred/rights
- `tools/audit_t2_membership.py`: `active_tickers_no_recent_price` excludes `cp.is_active=FALSE`
- `tools/audit_t2_screener_features.py`: RS/rank null warmup-aware logic; `_warmup_null_split()` helper; `_WARMUP_NULL_COLS` set
- `tools/patch_fundamentals.py`: Added `filing_date_zero` and `filing_date_stale_historical` fix modes; EDGAR lookup helpers (`_load_edgar_ticker_map`, `_fetch_edgar_filing_dates`)
- `docs/manual_for_me.md`: Updated header timestamp, added filing_date patch TODOs, added full Resolved entry for this session

## 🚧 Work in Progress (CRITICAL)

- **`filing_date` patches not yet run on full data.** The two new fix modes were tested with `--dry-run` on sample tickers and confirmed working, but the actual UPDATE has NOT been applied. Need to run:
  ```bash
  python tools/patch_fundamentals.py --fix filing_date_zero
  python tools/patch_fundamentals.py --fix filing_date_stale_historical
  ```
  This affects point-in-time correctness for `days_since_report` feature in training data — currently many historical rows have `filing_date = period_end` which means 0-day lag, causing look-ahead contamination in backtests.

- **GE has no price_data or fundamentals yet.** Will appear as 1 WARNING in T1 audit until next daily pipeline run fetches it. Not blocking anything but should confirm it ingests cleanly.

- **1.8% post-warmup rank nulls remain** in `t2_screener_features` (RS_Universe_Rank etc., ~168K rows outside warmup window). Root cause not fully investigated — likely tickers that entered the universe mid-history and still had insufficient lookback at the time of computation. Low priority but should investigate if it grows.

## ⏭️ Next Steps

1. **Run filing_date patches** (see commands above) — ~60K rows total, EDGAR API rate-limited so expect 5-15 min runtime. Run with `--dry-run` first to confirm counts.
2. **Run daily pipeline** to fetch GE price_data and fundamentals: `python scripts/run_daily_pipeline.py`
3. **Re-run full audit** after above steps to confirm warning count drops to ≤5: `python tools/run_all_audits.py --warn-only`
4. **Implement Option A monitoring table** (`audit_history`) — append audit results to DuckDB table on each run for trend tracking. Design discussed, not yet implemented.
5. **Investigate 1.8% post-warmup rank nulls** — query which specific dates/tickers have nulls outside the first 270 rows to understand if this is a systematic gap.

## 💡 Context/Memory

- **GE situation**: GE underwent two spinoffs — GEHC (Jan 2023) and GEV (April 2024). The old GE became "GE Aerospace" and retained the GE ticker. Our universe rebuild in early 2026 picked up GEV and GEHC but somehow missed GE itself. The shares_history and fundamentals for old GE were in the DB as orphans (no price_data), confirming it was never fetched as a price ticker in this system.

- **Orphan patterns**: The 194 shares_history orphans fell into 4 categories: 167 regular equities (purged), 15 warrants, 9 preferred, 2 rights. The regular equities were mostly SPACs/micro-caps that had been removed from company_profiles at some point but whose T1 data was never cascaded. None were flowing downstream (t2/t3 had 0 orphan rows — screener membership gated them).

- **Filing date root cause confirmed**: VSCO audit report showed `filing_date = 2026-01-31 = period_end`. EDGAR confirmed actual filing was 2026-03-20 (~48 days later). This is FMP setting `filing_date = period_end` as a placeholder when the actual SEC date isn't in their system. The `>90d` cases are different: FMP back-populated historical quarterly data (going back to 2001) but used the current year's download date as filing_date — giving nonsensical 7700-day gaps.

- **EDGAR API**: `https://www.sec.gov/files/company_tickers.json` gives ticker→CIK mapping (10K tickers). `https://data.sec.gov/submissions/CIK{cik:010d}.json` gives all filings for a company. Rate limit is ~10 req/s. The `_fetch_edgar_filing_dates()` function filters to 10-K/10-Q only and maps `reportDate → filingDate`. Works well for post-2000 filings; pre-2000 often missing from EDGAR.

- **Audit philosophy**: The goal is to make every WARNING actionable. INFO is for expected structural patterns (warmup windows, expected data gaps). WARNING should only fire when operator intervention is needed.
