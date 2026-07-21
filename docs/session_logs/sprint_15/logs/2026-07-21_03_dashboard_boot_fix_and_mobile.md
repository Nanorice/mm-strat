# Session Handover: 2026-07-21 (03) — remote boot fix + mobile pass

## 🎯 Goal
Get the remote dashboard loading again (it rendered nothing but the sidebar), and
make the pages readable on a phone.

## ✅ Accomplished

**Diagnosis — two independent defects, not one.**
- **Import-scope asset pull.** `dashboard_utils` called `_ensure_asset_dirs()` at
  module scope, which downloaded **3,744 R2 objects / 381 MB** one blocking request
  at a time before the first pixel — ~10 minutes of round-trip latency on a cold
  container, plus ~1.9 GB peak disk (DB + its `.tmp` + assets). The `.r2_synced`
  marker is only touched *after* a prefix completes, so a health-check restart
  mid-pull started from zero. The landing page reads none of those 381 MB.
- **Ungoverned DuckDB connection.** `_connect()` was the one connection in the repo
  using raw `duckdb.connect()` instead of `src/db.py`'s governor. DuckDB sizes its
  default budget from the **host's** RAM, not the container's cgroup limit, so it
  allocated past the ceiling and the container was SIGKILLed mid-query — blank body,
  no traceback, boot log restarting at "dependencies installed". **Dataset EDA was
  the only page still rendering, and it is the only page that never opens the DB.**
  That symptom was the tell.

**Fixes**
- `_connect()` + `update_decision_taken()` route through `db.connect()`. Verified
  live: `memory_limit=5.5 GiB, threads=4, temp_directory=data/.duckdb_tmp` (was unset).
- `DUCKDB_MEMORY_LIMIT` / `DUCKDB_THREADS` added to `_SECRET_KEYS` — `config.py`
  reads them from `os.environ`, and Streamlit Cloud only ever puts them in
  `st.secrets`. Unlisted, the secret is a silent no-op (same trap as
  `DASHBOARD_PULL_FROM_R2` in the 2026-07-18 incident).
- `_ensure_asset_dirs()` → `ensure_assets(*prefixes)`, called by the page that reads
  the dir. Module-scope call deleted; `_ensure_local_db()` stays (5 of 6 pages need
  the DB). Boot: 1.1 GB + 3,744 requests → 768 MB + 1.

**Mobile pass** (every change measured in-browser at 375×812 *and* 1280×800)
- **Equity Research**: 13-option horizontal radio → collapsible expanders (Business
  Analyst open). Media query for title tracking, `overflow-wrap:anywhere` (accession
  numbers are unbreakable tokens), tables scroll inside their own box.
- **Macro**: S1 regime grid 7→2 cols (gauge spans full width), S2 heatmap 4→2 cols,
  S3 board scrolls. Then per user feedback: S3 drops the history sparkline column on
  mobile and gives the width to the indicator name (24%→38%), padding 13→10px —
  median row height **64px → 56px**.
- **Screening**: selectbox labels inline with their controls, capped at 220px
  (block height **68px → 40px**); stacked again below 640px.

**Screening / tables**
- Finviz links restored (they existed on the main page and Pipeline Health, never on
  Screening). Consolidated 4 copies of the URL + 4 of the display regex into
  `finviz_url()` / `finviz_ticker_col()` — on the current `/stock?t=` form, since the
  old `/quote.ashx` copies are exactly what went stale.
- Ticker column **pinned** on every wide table (Streamlit 1.58 native).
- Screening default order: **fresh → triggered → score**.

## 📝 Files Changed
- `scripts/dashboard_utils.py`: governor import (ordered *after* the secrets bridge),
  `ensure_assets`, `_asset_fresh`, finviz helpers, `_SECRET_KEYS`.
- `scripts/dashboard.py`: finviz helpers replace two local copies.
- `scripts/pages/1_Dataset_EDA.py`: `ensure_assets("docs_reports")`.
- `scripts/pages/2_Macro.py`: three media queries; S3 header `<th>`s carry the column
  classes (`table-layout:fixed` reads widths off the first row).
- `scripts/pages/3_Screening.py`: `_default_order`, finviz + pinned ticker, inline
  filter labels.
- `scripts/pages/4_Backtest_Studio.py`: `ensure_assets("sweep_starttime")` inside
  `render_fan`, where the fan is drawn.
- `scripts/pages/5_Pipeline_Health.py`, `5_Session_Activity.py`: `ensure_assets`,
  finviz, pinned ticker.
- `scripts/pages/7_Equity_Research.py`: expanders + mobile CSS.
- `tests/test_r2_pull_guard.py`: +3 tests — no raw `duckdb.connect(` in the module,
  governor import follows secret hydration, no module-scope asset pull.
- `tests/test_screening_order.py`: **new**, 7 tests pinning the sort-key *order*.
- `docs/session_logs/sprint_15/plans/dashboard_mobile_and_model_lab.md`: **new**, the
  backlog.

## 🚧 Work in Progress (CRITICAL)
- **NOTHING IS DEPLOYED.** `origin/main` is still at `ccbaadc` and still has
  `_ensure_asset_dirs()` at module scope. This repo is on a **detached HEAD**, 23
  commits ahead of `origin/main` (0 behind — clean fast-forward available).
- The user set `DUCKDB_MEMORY_LIMIT=700MB` in Cloud secrets and reported the remote
  "works now" — **that is a fresh container from saving the secret, not the fix.**
  On the deployed code `_SECRET_KEYS` doesn't list the key, so the secret is inert.
  Expect the same failure on the next cold boot until this is pushed.
- The slim DB is 770 MB and still pulled at import: `t3_sepa_features` 355 MB +
  `t2_screener_features` 187 MB = 70% of it, both on a 252-day window. Trimming those
  two to ~90d lands it near 300 MB. Not started.
- `dashboard.duckdb` was last built 2026-07-20 22:50, so remote has no AMD/SHC/TBI
  research reports. Needs a `build_dashboard_db.py` + `sync_dashboard_db.py` run.
- Pre-existing, untouched: Backtest Studio logs an `ArrowTypeError` on the
  `case2_prototype_plus_rank` column (mixed float/bytes); Streamlit auto-coerces it.

## ⏭️ Next Steps
1. **Branch off the detached HEAD and push** — nothing above reaches the remote
   otherwise. Fast-forward `main` to HEAD, or merge the branch.
2. Rebuild + sync the slim DB (gets today's three reports onto remote).
3. Backlog in dependency order — see
   [`plans/dashboard_mobile_and_model_lab.md`](../plans/dashboard_mobile_and_model_lab.md):
   sector filter (10c) and Model Lab blank metrics (7) are the cheap bugs; Dataset EDA
   and the Model Lab tab consolidation are decisions first, code second.

## 💡 Context/Memory
- **The canary was the clue.** "Only Dataset EDA loads" is not a Dataset EDA fact —
  it is the only page that never opens DuckDB. When one page survives, ask what it
  *doesn't* do.
- **A secret that isn't in `_SECRET_KEYS` does nothing on Streamlit Cloud.** Second
  time this exact shape has bitten (`DASHBOARD_PULL_FROM_R2`, then `DUCKDB_*`). The
  import order matters too: `config.py` snapshots the env at import, so the governor
  must be imported *below* the secrets bridge. Pinned by a test.
- **Measure row height, don't reason about it.** Inlining the S3 indicator name and
  symbol looked like it would save a line; measured, it made rows *taller*
  (64px → 72px) because the run then wraps mid-name. Shipped the stacked version.
- **`st.dataframe` renders to a canvas**, not the DOM — cell contents and pinned
  columns can't be asserted from the page. Verify column config through the API and
  the page's rendered state instead.
- Sweep grid semantics, for the record: `rolling` = varying start month at a fixed
  12-month hold (the cone the Studio scores); `horizon` = one start, holds h3…h60;
  `matrix` = the cross-product — and `publish_sweep_to_studio.py:119` warns matrix
  contains 1-day cells that annualize to +138853%.

## RESEARCH_LOG
Not updated — this session was ops/infra + UI and opened no research questions. The
product decisions it did open (Dataset EDA content, Model Lab consolidation) live in
the plan doc, not the question ledger.
