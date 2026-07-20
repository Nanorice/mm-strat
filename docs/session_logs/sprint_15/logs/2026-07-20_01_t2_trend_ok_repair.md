# Session Handover: 2026-07-20

## 🎯 Goal
Execute the outstanding **data repair** for the six days where `trend_ok` was written all-FALSE
universe-wide in `t2_screener_features` (2026-06-01/03/04/05/09, 06-24), caused by the WARN-mode
`phase_1_t1_macro` leaving `t1_macro.spy_close` NULL. Code fix had already landed in a prior
session; only the data was outstanding.

## ✅ Accomplished

**Pre-flight (all verified, not assumed)**
- Prefect confirmed idle: cron is `0 22 * * 1-5`, session ran Sunday→Monday early AM, so nothing
  was due. Server not listening on 4200; scheduled tasks all `Ready`, not `Running`.
- Guard precondition verified: **0 missing `spy_close`** across 06-01..06-25 (18 SPY trading days),
  so `_assert_benchmark_coverage` would pass.
- Write lock probed directly (read-write connect) rather than inferred from process list.

**Backups taken** (see 🚧 — the claimed pre-existing backup did not exist)
- `data/backups/sepa_watchlist_20260720_0030.parquet` — 39,056 rows
- `data/backups/t2_screener_features_2026-06-01_2026-06-24_20260720_0030.parquet` — 46,666 rows
- `data/backups/t2_screener_features_2026-06-25_2026-07-17_20260720_0210.parquet` — 44,051 rows
- All three verified by reading back row counts.

**T2 recompute — DONE and verified**
- Smoke test on 2026-06-01 first (project long-run rule): 2,754 rows, 66s, `trend_ok` 0 → 326.
- Full range 06-01..06-24: 46,895 rows written, 63s.
- Extended tail 06-25..07-17: 44,168 rows written, 66s (see Context for why the extension).
- Six originally-corrupt days now match the expected counts:

  | Date | Expected | Actual | Δ |
  |---|---|---|---|
  | 06-01 | ~324 | 326 | +2 |
  | 06-03 | ~344 | 347 | +3 |
  | 06-04 | ~390 | 389 | −1 |
  | 06-05 | ~378 | 380 | +2 |
  | 06-09 | ~453 | 455 | +2 |
  | 06-24 | ~609 | 616 | +7 |

- Final health check, `t2_screener_features` 2026-06-01..2026-07-17:
  **91,063 rows / 33 trading days, `NULL price_vs_spy` = 0, `NULL price_vs_spy_ma63` = 0,
  no all-FALSE `trend_ok` days remaining.**

## 📝 Files Changed
**No source files were edited this session.** The code fix (`_assert_benchmark_coverage`,
LEFT→INNER JOIN, config comment, `tests/test_t2_benchmark_guard.py`) was pre-existing
uncommitted work from a prior session — it was *used*, not authored, here.

- `data/backups/*.parquet` (3 new files) — pre-write safety copies, ~35 MB total.
- `data/market_data.duckdb` → `t2_screener_features`: rows for 2026-06-01..2026-07-17
  DELETEd and re-INSERTed (91,063 rows across 33 days).
- `docs/session_logs/sprint_15/logs/2026-07-20.md` — this handover.

## 🚧 Work in Progress (CRITICAL)

**Steps 5–7 of the repair were NOT started.** They are the destructive phase and were never
authorized. Nothing is half-applied — `sepa_watchlist` is untouched at its original 39,056 rows:

1. `CREATE TABLE sepa_watchlist_bak` → `DROP TABLE sepa_watchlist` → `SepaWatchlistManager.backfill()`
   over full t2 history (`src/managers/sepa_watchlist_manager.py:90`).
2. Diff rebuilt vs `sepa_watchlist_bak`.
3. `ViewManager.create_all()`.
4. `scripts/build_dashboard_db.py`.
5. Remove the censoring notice in `scripts/pages/3_Screening.py` ("Trend since" capped at 2026-06-25).

**Three hazards for whoever runs them:**

- ⚠️ **`screener_watchlist` is a VIEW over `sepa_watchlist`**, not a table — it is destroyed by the
  DROP and only comes back via `ViewManager.create_all()`. Do not skip step 3.
- ⚠️ **Other Claude Code sessions were cycling DB writers on this box** every 30–60s
  (`build_label_cone_cache.py`, `build_dashboard_db.py`, `sync_dashboard_db.py`, pytest — identified
  via `.claude/shell-snapshots/` parents). `market_data.duckdb` is single-writer. They must stay down
  through the rebuild or they will republish stale anchors on top of corrected ones. One of them
  already built the dashboard from **uncorrected** data — the current `data/dashboard.duckdb` is stale.
- ⚠️ **Run from the main repo path, not the worktree.** The worktree
  `.claude/worktrees/epic-ellis-3f3f4d` still has the **old `LEFT JOIN`** and no guard. All repair
  work this session ran from `C:\Users\sh019\Documents\projects\mm-strat`.
  (The fix itself was uncommitted for most of the session but was committed by a *parallel* session
  as `4b6b9b8 fix(pipeline): hard-fail T2 when t1_macro lacks benchmark coverage`. Two worktree
  merges — `ccbaadc`, `2323199` — also landed mid-session; the guard and `INNER JOIN` were
  re-verified intact afterwards at `src/feature_pipeline.py:127/310/349`.)

## ⏭️ Next Steps
1. Quiesce the other agent sessions; confirm no python holds the write lock.
2. Run steps 5–7 above, in that exact order.
3. Diff check: expect the rebuild to **add** sessions and pull entry dates **earlier**
   (total > 39,056). If exits move instead, **stop** — that contradicts how `run_bounds` works.
4. Rebuild `data/dashboard.duckdb` (currently stale/uncorrected) after the views.
5. Only after step 4 lands: remove the censoring notice at `scripts/pages/3_Screening.py:228`
   ("Trend since is currently censored at 2026-06-25"). It is still present and still accurate
   until the watchlist + dashboard are rebuilt.

## 💡 Context/Memory

**The stated causal story was wrong, and the correction matters for the diff.**
The plan assumed the bad days forced *spurious session exits*. They did not. Session boundaries come
from `trend_active` (`close > sma_50/150/200`), which the SPY gap never touched; only `entry_signal`
(`trend_ok AND breakout_ok`) was corrupted. `run_bounds` filters `HAVING entry_date IS NOT NULL`, so
a trend run whose *only* entry signal landed on a corrupt day was **dropped entirely**. Data confirms:
all six corrupt days have **zero** entries in `sepa_watchlist`, with a pileup after (06-26 has **95**
entries, not the 82 stated — worth knowing which filter produced 82).

**A NULL benchmark degrades a forward window, not just its own day.**
`price_vs_spy_ma63` is `AVG(price_vs_spy) OVER w63`. SQL `AVG` *skips* NULLs, so on the corrupt days
it averaged ~57 values instead of 63 — a small, much harder-to-spot error that propagates forward.
This is why the supposedly-healthy in-window days also shifted (+4 to +16) once recomputed.

**But the propagation extent was NOT the theoretical 63 days.** I predicted contamination through
07-17; the tail diff showed **41 flips confined to 06-25..07-02, and exactly zero from 07-06 onward**.
Reason: the nightly pipeline rewrites a trailing window each run, so once `t1_macro` was backfilled
(evidently ~07-03..07-06) later nightly runs had already self-healed those rows. **Lesson for any
future macro backfill: the contaminated range is bounded by *when the backfill happened relative to
each row's last write*, not by the window length.** `_assert_benchmark_coverage` prevents *new*
occurrences but nothing flags that a *past* gap contaminates forward rows — worth a comment on the guard.

**A full file snapshot of `market_data.duckdb` is impossible on this box.**
DB is 82.6 GiB; C: had 43.4 GiB free — short by ~39 GiB. Table-level Parquet export is the only
viable backup path here. Plan accordingly in future runbooks.

**Verify backup claims before destructive writes.** The session was told a backup already existed.
It did not: `data/backups/` was empty, no `*_bak` table existed, and no large file had been written
in two hours. The only 39,056-row match was `screener_watchlist` — a VIEW, which would have been
destroyed by the DROP rather than preserving anything.
