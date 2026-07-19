# sh019 Catch-Up Checklist

**Goal**: bring the ops box `sh019` to parity with the research box (DESKTOP-MTF20CI)
for everything the **nightly pipeline** needs. Research artifacts (cones, sweeps,
score caches) are deliberately NOT replicated — see §6.

**Written**: 2026-07-19. Target state measured on the research box that day:

| Object | Research box (target) |
|---|---|
| `price_data` | 9,203 distinct dates → 2026-07-17 |
| `t2_screener_features` | 9,854,872 rows → 2026-07-17 |
| `t3_sepa_features` | 9,406,883 rows → 2026-07-17 |
| `sepa_watchlist` | 39,088 sessions (ACTIVE 530 / EXITED 38,558) |
| `d2_training_cache` | 39,088 rows (incl. the +292 delisted) |
| `daily_predictions` | 303,803 rows → 2026-07-17 |
| prod model | `m01_binary_20260524_222020` |
| views | 15 |

Row counts will differ (sh019 ingests independently); **date frontiers and schema
must match**. Don't chase exact row parity.

---

## 0. Pre-flight — verify BEFORE touching anything

🛑 The tier-0 incident began by running a destructive flag without checking the target.

- [ ] `SELECT COUNT(DISTINCT date) FROM price_data;` → expect **~9,184+**, NOT 172.
      172 means you are looking at a slim DB, not the main DB. **Stop** if so.
- [ ] `DASHBOARD_DB_PATH` is **UNSET** on this box (`echo $env:DASHBOARD_DB_PATH`).
      It may only ever name a file called `dashboard.duckdb`. Leave unset for the full DB.
- [ ] `DASHBOARD_PULL_FROM_R2` is **unset** (only the Streamlit Cloud app sets it).
- [ ] No DuckDB writer holds the DB (Prefect run / open notebook kernel).
- [ ] File-copy backup of `data/market_data.duckdb` taken. There is still no backup
      job — this is the one manual safety net (see §7).

## 1. Pull code

- [ ] `git pull` (branch `research` unless told otherwise)
- [ ] `.venv\Scripts\python.exe -m pytest tests/ -q` — expect **439 passed**;
      3 failed + 26 errors are pre-existing (stale EDGAR stubs, `test_phase1_backfill`
      tmpfile fixture). Anything else is a real regression.

## 2. Clean dirty data BEFORE recomputing features

Dirty prices propagate into T2/T3, so this precedes any feature compute.

- [ ] `.venv\Scripts\python.exe scripts\clean_dirty_shares_price.py`

Stays manual **by design**: Phase 1.6 detects the dirt and withholds the R2 publish,
but corrupt *lows* were deliberately KEPT as real flash crashes. Auto-cleaning would
destroy that adjudication.

## 3. Ingest + T2 (must precede the watchlist backfill)

⚠️ **Ordering is load-bearing.** `backfill_sepa_watchlist.py` defaults `end_date` to
`MAX(date) FROM t2_screener_features`. Run it on a stale box and it rebuilds
authoritatively (`DROP TABLE`) only up to that date — every later session vanishes,
T3 then filters its universe from the truncated watchlist, and `v_d1_candidates`
INNER-JOINs entry rows, so **trades silently disappear from the training population**.
`_t3_holed_dates` repairs only the trailing 30 days; older holes are permanent.

- [ ] `.venv\Scripts\python.exe scripts\run_daily_pipeline.py --phase-1-only`
- [ ] `.venv\Scripts\python.exe scripts\run_daily_pipeline.py --phase-2-only`
- [ ] `.venv\Scripts\python.exe scripts\run_daily_pipeline.py --phase-3-only`
- [ ] Verify T2 is current: `SELECT MAX(date) FROM t2_screener_features;`

## 4. Rebuild the watchlist source table

- [ ] `.venv\Scripts\python.exe scripts\backfill_sepa_watchlist.py`
- [ ] Verify statuses are only ACTIVE/EXITED:
      `SELECT status, COUNT(*) FROM sepa_watchlist GROUP BY 1;`
      Any `COOLDOWN` means the rebuild didn't take.
- [ ] Verify no `cooldown_end` column survives.

The **only** genuinely required manual data step. Phase 4b appends today's events
only, so pre-2026-07-18 `COOLDOWN` rows never self-clear.

✅ **`create_duckdb_views.py` is NOT required** (supersedes the older note). Phase 6
runs `ViewManager.create_all()` nightly and `_create_screener_watchlist_view`
self-migrates a leftover `BASE TABLE` into the VIEW — verified idempotent. Run it
only to heal views immediately instead of waiting for the nightly run.

## 5. Full pipeline run (computes T3 against the correct universe)

- [ ] `.venv\Scripts\python.exe scripts\run_daily_pipeline.py`
- [ ] Confirm prod model: `SELECT version_id, status_flag FROM models WHERE status_flag='prod';`
      → expect `m01_binary_20260524_222020`. If it's the archived 4-class or absent,
      **promote it** — the registry is per-box. Phase 8 now alerts on absent /
      duplicate / changed prod model, so this no longer fails silently.
- [ ] `SELECT COUNT(*) FROM information_schema.tables WHERE table_type='VIEW';` → 15
- [ ] `.venv\Scripts\python.exe tools\audit_date_coverage.py` → expect 0 interior gaps.
      The 5 June-2026 `t1_macro` holes self-heal in Phase 1 (offline, from local
      `price_data`/`macro_data`).

⚠️ Do **not** use `scripts\backfill_t1_macro.py` for those holes — it refetches from
yfinance and prints `[OK] Done … Rows written: 0` on a rate-limit, i.e. failure shaped
exactly like success.

## 6. Backtest cones — DO NOT re-run on sh019

**Answer: no.** The cones are not part of the nightly pipeline and sh019 does not need them.

- **No orchestrator phase builds them.** `build_cone_cache.py` /
  `build_label_cone_cache.py` are CLI-only research tools.
- **The inputs don't exist there.** They read `data/selection_sweep/starttime/**/summary.json`
  (24 files) and a **3.3 GB** score-cache parquet — research outputs of the dev box,
  not committed to git. Regenerating means re-running the sweeps: hours of backtest on
  the ops box for zero live benefit.
- **It would break promotion discipline.** The cone is the honest-Sharpe lens that gates
  champions ([[project_champion_starttime_dependent]]). Two boxes rebuilding it from
  different sweep state is how you get two disagreeing answers to "did this pass?"
- `audit_serving_tables._cone_staleness` already reports `"not on this host
  (dev-box local)"` as **INFO, not a failure** — a box without sweep sources is
  expected, not broken.

🛑 **Implication for R2**: `cone_cells` is MANIFEST-`full`, so it is *copied into the
slim DB by whichever box builds it*. The slim DB must therefore keep being built on
**this (research) box**, or the remote dashboard loses its cones. If sh019 ever becomes
the publisher, that is a deliberate decision — not a side effect of this catch-up.

## 7. Still open (not closed by this checklist)

- [ ] **Backup story** — weekly file-copy of `data/market_data.duckdb`. Should be
      OS-scheduled and **independent of Prefect**: a backup driven by the process it
      protects dies with it.
- [ ] Confirm the Streamlit Cloud app sets `DASHBOARD_PULL_FROM_R2=1`, or the remote
      silently stops refreshing (Barrier 1 is opt-in).
- [ ] Standing audit FAILs (t1_macro NULL vix row, 4 gap tickers) — pre-existing, see
      sprint_14 README.

---

## Verification summary

| Check | Command | Expect |
|---|---|---|
| Suite | `pytest tests/ -q` | 439 passed (3F/26E pre-existing) |
| Date coverage | `tools\audit_date_coverage.py` | 0 gaps |
| Watchlist vocab | `SELECT status, COUNT(*) FROM sepa_watchlist GROUP BY 1` | ACTIVE/EXITED only |
| Prod model | `SELECT version_id FROM models WHERE status_flag='prod'` | `m01_binary_20260524_222020` |
| Views | `information_schema.tables WHERE table_type='VIEW'` | 15 |
| Frontier | `MAX(date)` on price/t2/t3 | all same trading day |
| Full battery | `tools\run_all_audits.py --warn-only` | no NEW FAILs vs research box |
