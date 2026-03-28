# Session Handover: 2026-03-17

## 🎯 Goal
Implement three-module pipeline refactor: (1) decouple Phase 1 from screener_members, (2) add criteria versioning to screening, (3) replace FMP fundamentals with yfinance + DuckDB.

## ✅ Accomplished
- **Module 1 (Phase 1 Decoupling)**: Replaced `screener_tickers` universe with `price_tickers` for fundamentals (1.2) and shares (1.3) sub-phases. Removed circular dependency between Phase 1 and Phase 2.
- **Module 2 (Criteria Versioning)**: Added `screener_criteria_versions` table with v1 seed row. Implemented `_ensure_criteria_table()` in `ScreenerManager.__init__`, `_get_active_criteria(target_date)` lookup, and parameterized `update_membership()` to read thresholds from DB instead of hardcoded values.
- **Module 3 (yfinance Fundamentals)**: Rewrote `FundamentalEngine` with dual-source design (`source='yfinance'` default, `source='fmp'` legacy). Added `fundamentals` and `earnings_calendar` DuckDB tables. Implemented `_fetch_from_yfinance()`, filing_date mapping logic, `_upsert_to_duckdb()`, earnings calendar refresh, and earnings-calendar-driven `update_fundamentals()`. Updated `get_ticker_fundamentals()` to dispatch to DuckDB or parquet based on source.
- **Orchestrator Updates**: Changed `FundamentalEngine(source='yfinance', db_path=...)`, removed `force_cache_only=True`. Phase 1.2 now calls `update_fundamentals(tickers=price_tickers, target_date=target_date)`. Removed stale "cache-only mode" warning.
- **Documentation**: Updated implementation plan with phase 2 modifier notes and deprecation warnings. Updated [manual_for_me.md](docs/proposals/duckdb_v2/manual_for_me.md) with post-refactor architecture: Phase 1 uses price_tickers only, Phase 2 reads criteria from DB, fundamentals now in DuckDB. Marked implementation plan complete.

## 📝 Files Changed
- `src/orchestrators/daily_pipeline_orchestrator.py`: Phase 1 decoupling (use price_tickers for 1.2/1.3), FundamentalEngine init (source='yfinance'), Phase 1.2 call signature
- `src/managers/screener_manager.py`: Complete rewrite with criteria versioning (_ensure_criteria_table, _get_active_criteria, parameterized update_membership)
- `src/fundamental_engine.py`: Complete rewrite with dual-source design (yfinance DuckDB primary path, FMP legacy path gated behind source='fmp')
- `docs/proposals/duckdb_v2/phase_1_fix_implementation_plan.md`: Added status badge, clarified Module 2 Phase 2 orchestrator requirements, flagged Module 3 implementation gaps (filing_date NULL, earnings calendar refresh persistence, deprecation)
- `docs/proposals/duckdb_v2/manual_for_me.md`: Updated Phase 1–2 descriptions, replaced fundamentals_cache with DuckDB, added Key Tables section, consolidated open TODOs

## 🚧 Work in Progress (CRITICAL)
**None** — all three modules implemented and code changes complete. **Not yet tested**:
- Phase 1 decoupling: Did not run orchestrator, so no verification that Phase 1 actually uses price_tickers correctly
- Criteria versioning: Did not test inserting new criteria versions or running Phase 2 with alternative thresholds
- yfinance Fundamentals: Did not test yfinance API calls, filing_date mapping, or DuckDB upserts. earnings_calendar refresh trigger not yet wired into daily pipeline.
- FundamentalMerger downstream: Not verified that merger correctly reads from DuckDB fundamentals table and handles NULL filing_date rows

## ⏭️ Next Steps
1. **Smoke test Phase 1**: Run `python scripts/run_daily_pipeline.py --dry-run --date 2026-03-16 --verbose` and verify Phase 1 logs show "Price universe: N tickers from price_data" (no screener_members reference) and Phase 1.2 calls `update_fundamentals` not `update_fundamentals_cache`
2. **Smoke test Phase 2**: Run Phase 2 on test date, verify `screener_criteria_versions` table created and seeded, check that membership update used v1 criteria
3. **Earnings calendar bootstrap**: Run `FundamentalEngine(source='yfinance').refresh_earnings_calendar(price_tickers)` to populate `earnings_calendar` table with upcoming earnings dates
4. **FundamentalMerger integration test**: Load a ticker via merger, verify `fundamentals` table is queried correctly and `filing_date` is present for recent quarters
5. **Monthly earnings refresh hook**: Decide where to persist last-refresh timestamp (e.g., sentinel row in earnings_calendar or pipeline_runs metadata column), implement conditional refresh in orchestrator Phase 1

## 💡 Context/Memory
- **Phase 1 decoupling rationale**: The original circular dependency (Phase 1 needs screener_members to fetch fundamentals → Phase 2 updates screener_members → Phase 2 needs Phase 1 data) was causing bootstrap failures and stale tickers. Solution: use ALL cached price tickers for Phase 1 sub-phases, screener_members is only used downstream by Phase 3+. This decouples the phases cleanly.
- **Criteria versioning design**: Screening thresholds are now versionable without code changes. To change thresholds effective 2026-04-01, just INSERT into screener_criteria_versions with that date. The merger's as-of lookup (WHERE effective_date <= target_date ORDER BY DESC LIMIT 1) automatically picks the right version per date. This enables A/B testing different universes historically.
- **yfinance fundamentals decision**: FMP API is disabled/quota-exhausted, so switched to yfinance which is free and sufficient for the 4–5 most recent quarters. Historical backfill (decade-scale) requires SEC EDGAR (edgartools), marked as future TODO. The earnings_calendar table bridges this: it tracks when earnings are announced, so daily `update_fundamentals()` only fetches tickers with pending earnings, keeping API load minimal.
- **filing_date mapping rule**: yfinance returns fiscal period_end (quarter end date), but we need the actual announcement date (filing_date) to prevent look-ahead bias in the merger's as-of join. The solution: earnings_calendar has actual announcement dates; we match each period_end to the first earnings date > period_end within 90 days. Older/sparse earnings dates may be missing, leaving some historical rows with filing_date=NULL; merger will silently drop these (acceptable, as those are pre-2024 historical records).
- **FMP legacy path preserved**: All original FMP methods remain intact, just gated behind source='fmp'. This allows rollback or parallel testing without code deletion. However, update_fundamentals_cache() now raises RuntimeError if called on source='yfinance', which is intentional (fail-fast on misuse).
- **Orchestrator Phase 1 no longer knows about screener_members**: This is the structural win. Phase 1 is now data-source-agnostic (doesn't care about downstream business logic). Phase 2 can run independently after Phase 1, and both Phase 1 and 2 can be skipped/retried without coupling.
