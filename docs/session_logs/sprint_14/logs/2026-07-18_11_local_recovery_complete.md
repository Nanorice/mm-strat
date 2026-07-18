# Session Handover: 2026-07-18 (session 11) — Local DB recovery COMPLETE

## 🎯 Goal
Resume sprint 14 after session 10's DB restore: audit the pipeline, then backfill the main
DB forward from the 2026-06-21 snapshot to today, so every table is current again.

## ✅ Accomplished
1. **Step-0 audit** (before any long run, as requested): identified `v_d1_candidates` as the
   remaining duplicate session derivation (re-derives from t2 independently of
   `sepa_watchlist`), flagged `manual_for_me.md` Phase Map as stale vs the session-10 merge,
   and identified two droppable research-artifact tables. User approved dropping
   `m02_prototype_targets` (16.1M rows, falsified m02 thesis) and `t3_training_cache` (9.36M
   rows, closed r1/r1b research) — both one-command rebuildable if ever needed.
2. **Phase-1 smoke test PASS** (10 tickers, exact prod code path) before the full ingest.
3. **Full raw-layer backfill 06-19→07-17**: Phase 1 (3,951 stale tickers + fundamentals/
   shares/macro), screener_membership (+165 events via idempotent backfill — Phase 2 only
   evaluates single dates), T2/T2-regime/T3 incrementals (all auto gap-detected).
4. **Found + fixed: the restored snapshot resurrected pre-06-21 data dirt.** The Phase-1.6
   plausibility gate correctly failed (78,265 dirty price bars, 125 bad share-count rows) —
   the 07-10 adjudicated cleanup had been undone by restoring the older file. Re-ran
   `clean_dirty_shares_price.py` (dry-run verified against gate counts; EXE/QXO whitelist
   honored) before computing T2/T3 on top of it.
5. **`t1_macro` gap filled without network**: the daily engine only ever writes the target
   date (leaves interior gaps), and `backfill_t1_macro.py` failed *silently* on a yfinance
   rate limit (`[OK] 0 rows` — no error). Filled the 18 missing rows directly from data
   already in the DB: SPY/QQQ from `price_data`, VIX from FRED rows in `macro_data`.
6. **T3 hole self-heal exercised for real**: `sepa_watchlist` backfill (39,088 sessions,
   2,728 tickers) admitted 15 tickers late; re-running Phase 5 triggered
   `_t3_holed_dates`/`_recompute_t3_dates` and closed 14 of 15 (1 legitimate remainder:
   EHAB, delisted 2026-05-14, outside the 30-day lookback — views' LEFT JOIN guard covers it).
7. **Views + training cache rebuilt**: 15 views recreated; `d2_training_cache` refreshed to
   39,088 rows (38,467 + 292 delisted + July sessions) in **76s** — confirms the old 592s
   correlated-subquery bottleneck (fixed 2026-05-14) stays fixed.
8. **Model registry repaired**: `populate_feature_catalog.py` re-run, `m01_binary_20260524_222020`
   promoted to PROD through the real evaluation gate (no force). **Session 10's hypothesis
   about the 4 feature-catalog test failures was wrong** — they weren't caused by the missing
   binary registration. Root cause: stale tests (hardcoded `M01_baseline_v0.1` as *the* prod
   model, imports of `FEATURE_GROUPS`/`src.feature_config` that no longer exist since training
   moved to reading `model_feature_sets` from the DB). Fixed the tests to current contracts,
   added an explicit "exactly one prod model" assertion. 11/11 pass.
9. **`daily_predictions` backfilled**: full lifecycle cohort, 124,715 rows across 172 dates,
   binary model, RAW softprob (same `ScoreEngine` path as orchestrator Phase 7.4).
10. **One-shot rebuilds**: `cone_cells` (2,460 rows via `build_cone_cache.py`), `weather_gauge`
    (5,917 rows), `sector_breadth` (169 rows), empty `trades`/`cash_flows`/`nav_history`
    schemas (`PortfolioManager.ensure_schema()` — noted it's explicit, not called from
    `__init__`, so instantiating the manager alone doesn't create the tables).
11. **Full suite**: 406 passed (up from 401), remaining 3 failures + 26 errors confirmed
    pre-existing and unrelated (stale EDGAR-placeholder tests, `test_feature_pipeline`).
12. Deleted stale `data/market_data.r2etag` (session-10 carryover, was permission-blocked then).

## 📝 Files Changed
- `tests/test_feature_catalog.py`: rewrote 4 stale assertions (prod-model hardcode, removed
  `FEATURE_GROUPS`/`src.feature_config` imports) to match the current DB-driven feature-set
  contract; added `test_exactly_one_prod_model`. **Uncommitted** — user has not yet said commit.
- `data/market_data.duckdb`: all tables healed to 2026-07-17 (see below); two tables dropped
  (`m02_prototype_targets`, `t3_training_cache`); `models.status_flag` for `m01_binary_...` →
  `prod`; `feature_catalog`/`model_feature_sets` repopulated.
- Memory: `project_r2_pull_destroyed_main_db` (recovery-complete section + restore gotchas),
  `project_watchlist_merge` (d2 refresh done, 39,088 rows).
- `data/market_data.r2etag`: deleted.

## 🚧 Work in Progress (CRITICAL)
None — this session closes out the recovery. DB is in a consistent, fully-forward-healed
state. The `test_feature_catalog.py` edit is the only uncommitted change; nothing else is
half-finished.

## ⏭️ Next Steps
1. **Commit** `tests/test_feature_catalog.py` (ask user first — not yet confirmed this session).
2. **sh019** (must run there, not here): verify its DB (`count(distinct date)` on `price_data`
   should be ≈9,184+, now that the research box is ahead at 9,203), pull code, run
   `backfill_sepa_watchlist.py` + `create_duckdb_views.py` (else stale COOLDOWN rows linger —
   nothing promotes them since the merge), confirm the cloud Streamlit app sets
   `DASHBOARD_PULL_FROM_R2=1`.
3. **Backup story** — the whole incident was only survivable because a month-old snapshot
   existed by luck. Even a weekly file-copy of the main DB to a second drive turns a future
   tier-0 into an inconvenience. User's call on mechanism.
4. **Phase-8 gap-detection audits** — user steer (repeated from session 10): the daily
   pipeline should detect/heal gaps automatically rather than requiring a manual recovery
   session like this one.
5. Small robustness fix worth queuing: `backfill_t1_macro.py` should exit non-zero (or at
   least warn loudly) when the underlying fetch returns 0 rows on a non-trivial date range —
   currently prints `[OK]` on a silent rate-limit failure.
6. Session-09 leftovers still open: dashboard feedback (rank-bump palette, supply-chain
   render, backtest-run caching design), `bootstrap_remote()` refactor, `page_today` deletion.
7. Rebuild the slim `dashboard.duckdb` + R2 sync now that the full DB is current (Phase 7.5/7.6
   equivalent) — not yet run this session; the full DB is ahead of what's published.

## 💡 Context/Memory
- **A restored snapshot doesn't just lose new data — it un-does old fixes.** The 78,265-row
  plausibility-gate failure was the tell: always run T1 quality gates before trusting a
  restored DB enough to compute features on it, even when the restore itself "succeeded".
- **`ensure_schema()` on `PortfolioManager` is not automatic.** `PortfolioManager(db_path=...)`
  alone does not create `trades`/`cash_flows`/`nav_history` — call `.ensure_schema()`
  explicitly. Worth a comment in the class if it bites someone else.
- **Test failures should be root-caused, not pattern-matched to the nearest open incident.**
  Session 10 correctly flagged 4 failing tests but attributed them to the missing binary
  registration without reading the assertions; this session found the real cause (stale
  hardcoded expectations from a superseded training-config design) by actually reading the
  failure messages before writing the fix.
- `populate_feature_catalog.py` is safe to re-run — it's idempotent (`[SKIP] already in models
  table` for anything already registered) and cheap (~1s).
