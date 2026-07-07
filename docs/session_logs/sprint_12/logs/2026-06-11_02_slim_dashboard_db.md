# Session 2026-06-11 — T1 Slim Dashboard DB (DONE) + Sync/Deploy Plan

**Sprint:** 12 (infra_uplift)
**Scope:** T1 (slim dashboard DB + cross-device sync) — build + verify done; sync planned, not built.

---

## What shipped

### 1. Slim dashboard DB — `data/dashboard.duckdb` (783 MB, from 67 GB)

- **[scripts/build_dashboard_db.py](../../../scripts/build_dashboard_db.py)** — declarative manifest;
  `ATTACH` source read-only → `CREATE TABLE AS SELECT` into a fresh DB. Idempotent (rebuilds from
  scratch). `--window-days` param (default 252). Modes: `full` / `window` / `window_plus_active` /
  `materialize_view`. The fresh CTAS also re-compacts away the dead-row bloat (see Findings).
- **Result:** 1.83M rows, 783 MB — a **98.8% reduction** from the 67 GB source. Build ~140s.
- **Slice policy (user-chosen):** big feature tables (`t2_screener_features`, `t3_sepa_features`)
  sliced to a plain **252d window**; all small tables full; `v_d3_deployment` **materialized** as a
  table (1,941 rows) so active-trade M01 scores survive; `price_data` **excluded** (no loader reads it).
  - `window_plus_active` mode exists (keeps full history for ACTIVE tickers) but is NOT used — the
    dashboard only reads feature tables at the latest date, so a flat window suffices. First build used
    it and ballooned to 2.34 GB (352 active tickers × full multi-year history); switched to plain window.

### 2. App DB path parameterised

- **[scripts/dashboard_utils.py:19-27](../../../scripts/dashboard_utils.py#L19-L27)** — `DB_PATH` now reads
  `DASHBOARD_DB_PATH` env var (absolute, or relative to repo root). Default = full local DB. This is the
  seam that lets the same app run local-full or remote-slim.

### 3. Nightly rebuild hook — orchestrator Phase 7.5

- **[src/orchestrators/daily_pipeline_orchestrator.py](../../../src/orchestrators/daily_pipeline_orchestrator.py)**
  — new `_run_phase_7_5_dashboard_db()` runs after Phase 7 cache refresh. Subprocess call to
  `build_dashboard_db.py` (600s timeout, own process → no ATTACH contention). **Best-effort:** failure
  logs a warning, never halts the daily pipeline. **Tested live → produced a valid 784 MB DB.**

### 4. Deleted 66 GB stale backup

- `data/market_data.duckdb.bak_0531_t1macro` removed. Reclaimed 66 GB.
- Justified by a **rigorous real-COUNT comparison** (not the broken `estimated_size`): live DB exceeds
  the backup in every *source* table; the only 2 tables where the backup had more rows
  (`d2_training_cache`, `screener_watchlist`) are materialized caches rebuilt from source each run →
  zero unique/unreconstructable data.

---

## Verification (all green)

- **Page audit:** only `dashboard.py` (page 1 "Today") + page 5 (Pipeline Health) touch the DB. Pages
  1-EDA / 3-Model Lab / 4-Backtest Studio read filesystem artifacts only.
- **18/18 dashboard loaders** return valid current (2026-06-10) rows against the slim DB.
  (`scratch/verify_slim_db.py` kept as a reusable smoke test.)
- **Streamlit boots clean** against the slim DB (HTTP 200, no exceptions) with
  `DASHBOARD_DB_PATH=data/dashboard.duckdb`.
- **Prod model** (`m01_prototype_2003_2026/v2`) resolves from the slim DB; `model.json` +
  `metadata.json` artifacts present → live M01 scoring works.

---

## Findings (recorded to memory)

1. **DuckDB dead-row bloat** (`project_duckdb_dead_row_bloat`) — the 67 GB main DB is ~95% dead,
   unvacuumed rows. `t2_screener_features` = 9.8M live but **182.9M `estimated_size`** (173M dead);
   `price_data` = 16.1M live vs 28.8M estimated. Root cause: the t2 incremental `DELETE+INSERT per date
   window` accumulates dead space (DuckDB has no auto-vacuum). **`duckdb_tables.estimated_size` is
   UNRELIABLE here — always use real `COUNT(*)`.** Noted, not actioned this session (user decision).
2. **Backup math reconciled** — the 66 GB backup was a full byte-copy carrying the same bloat, not
   66 GB of unique data. Total disk was ~133 GB (two bloated copies).

---

## Sync / remote-deploy — PLANNED (not built)

Full plan: **[dashboard_sync_deploy_plan.md](dashboard_sync_deploy_plan.md)**. Decisions locked:

| Decision | Choice |
|---|---|
| Pipeline host | Dev box builds, cloud serves (only the 783 MB slim DB travels) |
| GitHub repo | **existing** `github.com/Nanorice/mm-strat` — verified no DB ever committed, safe to push |
| Object storage | **Cloudflare R2** (zero egress, 10 GB free) |
| Cloud host | **Streamlit Community Cloud** (cold starts OK), auth via Google-email viewer allowlist |
| Nightly job | **spare PC** woken (WoL / wake-to-run) → Task Scheduler runs pipeline → 7.5 build → 7.6 upload |

Execution phases (none done): **S1** GitHub push · **S2** R2 bucket + `sync_dashboard_db.py` (Phase 7.6)
· **S3** Streamlit Cloud deploy + auth + R2-pull-on-boot shim · **S4** spare-PC Task Scheduler runbook.

---

## Files touched this session

- NEW: `scripts/build_dashboard_db.py`
- NEW: `docs/session_logs/sprint_12/dashboard_sync_deploy_plan.md`
- NEW: `docs/session_logs/sprint_12/2026-06-11_t1_slim_dashboard_db.md` (this file)
- NEW: `data/dashboard.duckdb` (gitignored, 783 MB)
- EDIT: `scripts/dashboard_utils.py` (DASHBOARD_DB_PATH)
- EDIT: `src/orchestrators/daily_pipeline_orchestrator.py` (Phase 7.5)
- EDIT: `docs/session_logs/sprint_12/todo.md` (T1 progress)
- DELETED: `data/market_data.duckdb.bak_0531_t1macro` (66 GB)
- KEPT: `scratch/verify_slim_db.py` (reusable slim-DB loader smoke test)

---

## Next session

Start **T2 — Model Card Phase 4 (promotion gate)**: wire the card verdict into
`ModelRegistry.set_prod()`. Full spec in
[../sprint_11/DONE_phase_4_promotion_gate.md](../sprint_11/DONE_phase_4_promotion_gate.md).
Resolve the open `threshold_gate` Section-C question first.
