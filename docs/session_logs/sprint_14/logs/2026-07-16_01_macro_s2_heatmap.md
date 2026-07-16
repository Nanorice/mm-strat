# Session Handover: 2026-07-16

## 🎯 Goal
Bridge the design→implementation gaps for the **Macro page Section 2** (sector/subsector
heatmap) from the dashboard-uplift plan, on a **shadow app** that leaves the live dashboard
untouched until the whole uplift is ready to switch over.

## ✅ Accomplished
- **S2 data engine** — `src/sector_breadth_engine.py`: nightly-materialized `sector_breadth`
  snapshot. One latest-day pass over `t2_screener_features ⋈ company_profiles` → per sector
  **and** subsector: today's return distribution, up/down breadth, trend_ok/breakout_ok
  participation, names added-today / added-5d. Native Yahoo/FMP taxonomy, `ETF:*` excluded.
  Self-check (11 sectors, quantile order, participation ≤ names, histogram integrity).
- **Return distribution fixed** — first cut stored only 5 quantiles → the KDE drew a 5-vertex
  polyline (looked "rough / too few points"). Root cause was rendering, **not** missing data
  or un-backfilled returns: it's a same-day cross-section of `(close−open)/open` over all
  constituents (Healthcare = 470 real names). Replaced with a **32-bin fixed histogram**
  (`[-8%,+8%]`, shared axis so cards are comparable), stored as JSON `ret_hist`; page draws a
  real filled density.
- **Macro page (S2 only)** — `scripts/pages/2_Macro.py`: theta.md-styled heatmap, KDE from the
  histogram, click-to-expand subsectors, sub-`MIN_NAMES(5)` collapse into an "Other" card
  (histograms merged bin-wise).
- **Shadow app** — `scripts/dashboard_uplift.py`: separate `streamlit run` entrypoint that
  mounts only uplift pages. Live `dashboard.py` is **untouched** (its explicit `st.navigation`
  list never mounted `2_Macro.py`, and `st.navigation` suppresses `pages/` auto-discovery).
- **Nightly + remote parity wiring** — new orchestrator Phase **7.46** (`sector_breadth`,
  WARN/best-effort, runs after weather, before slim-DB build); registry + config entries;
  `sector_breadth` added to `build_dashboard_db.py` MANIFEST (remote-parity invariant).
- **Verified**: engine self-check ✓, slim-DB build ships 169 rows + manifest invariant ✓,
  shadow app boots HTTP 200 no errors ✓, phase_registry tests 8/8 ✓, phase-order invariant ✓.

## 📝 Files Changed
- `src/sector_breadth_engine.py` (NEW): S2 materializer + histogram + self-check.
- `scripts/pages/2_Macro.py` (NEW): Macro page, S2 rendering only.
- `scripts/dashboard_uplift.py` (NEW): shadow entrypoint (owns `set_page_config`).
- `scripts/dashboard_utils.py`: `load_sector_breadth()` loader (ttl=300).
- `scripts/build_dashboard_db.py`: `sector_breadth` → MANIFEST (full copy).
- `src/orchestrators/phase_registry.py`: Phase 7.46 `sector_breadth`.
- `src/orchestrators/daily_pipeline_orchestrator.py`: `_run_phase_7_46_sector_breadth` + wiring.
- `config.py`: `sector_breadth` → `PIPELINE_FAILURE_MODES` (WARN).

## 🚧 Work in Progress (CRITICAL)
- **Only Section 2 is built.** The Macro page is deliberately S2-only. S1 (regime headline) and
  S3 (indicator board) are stubbed as a one-line caption, not implemented.
- **`ret_hist` stored as a JSON string**, not a DuckDB `INTEGER[]` — deliberate (survives
  register→CTAS→slim-copy cleanly). If a future consumer wants a native array, that's a change.
- **KDE is a smoothed histogram area**, not a true kernel density (`ponytail:` grade). Fine for
  glance; upgrade only if the shape reads wrong.
- Everything runs against `data/dashboard.duckdb` via the shadow app; `market_data.duckdb` has
  the fresh `sector_breadth` table written this session (last pipeline run predates it, so the
  nightly Phase 7.46 hasn't fired on its own yet — it will on next scheduler run on `sh019`).

## ⏭️ Next Steps
1. **Finish the Macro page** — the remaining two sections, per
   `plans/dashboard_uplift/macro_page.md`:
   - **S1 (regime headline)**: buildable now from data already in DB — 6 M03 pillars
     (`t2_regime_scores`), deploy posture + SPY>200d + supply (`weather_gauge`), VIX/HY OAS
     percentiles (`macro_data`). **Fear&Greed is the only gap** (CNN scrape, `curl_cffi`
     `impersonate="chrome"` to clear the Cloudflare 418 — confirm before committing the tile;
     render pillars alone until it lands).
   - **S3 (indicator board)**: ingestion backlog, not a rendering task. Land the ~30 **C1** FRED
     series first (extend `macro_engine` symbol list — IDs are enumerated in the plan doc), grey
     out the rest; never gate the page on completeness. C2 scrapes (AAII/NAAIM/COT/F&G) next; C3
     deferred.
2. **Then implement the Screening page** — design doc **already exists**:
   `plans/dashboard_uplift/screening_page.md` (121 lines). Population = the
   `trend_ok ∨ breakout_ok` universe (NOT `sepa_watchlist`, which is a session tracker — keep it
   as-is for Portfolio); one filterable/ranked surface that retires the 3–4 scattered candidate
   tables on today's page. Data gap is near-zero (only P/E derivation). Reuse the `style.md` system
   + the shadow-app pattern; mount it in `dashboard_uplift.py` alongside Macro. Per the README build
   order, Screening is actually recommended **first** (most data-complete) — confirm sequencing with
   the user, since they asked for Macro-remainder then Screening.

## 💡 Context/Memory
- **Shadow-app pattern**: `dashboard_uplift.py` is the sandbox; `dashboard.py` stays live. Switch
  day = add finished pages to `dashboard.py`'s `st.navigation` list and delete
  `dashboard_uplift.py`. Shared **infra** (the `sector_breadth` table + MANIFEST entry + Phase
  7.46) is NOT gated — it materializes nightly regardless, but renders nothing in the live app.
- `st.set_page_config` must live in the **entrypoint**, not the `st.Page` module (throws
  otherwise) — that's why it moved out of `2_Macro.py`.
- The "rough distribution" was a **rendering** bug (5 stored quantiles), not a data gap — a good
  reminder to check what's *stored vs computed* before blaming ingestion/backfill.
- Any new dashboard loader's table MUST be in `build_dashboard_db.py` MANIFEST or the R2 remote
  app breaks (`project_dashboard_remote_parity`).
