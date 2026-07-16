# Session Handover: 2026-07-16 (session 02)

> Session 01 that day = Macro S2 heatmap (`2026-07-16_01_macro_s2_heatmap.md`). This session
> continues the same dashboard-uplift thread: **Screening page** + **Macro S1**.

## 🎯 Goal
Build the **Screening page** (the most data-complete uplift page) and then finish **Macro
Section 1** (regime headline), both on the shadow app — live `dashboard.py` still untouched.

## ✅ Accomplished

### Screening page — SHIPPED
- **`v_d3_screening` view** (`view_manager._create_v_d3_screening`, registered in `create_all`):
  latest-day `trend_ok ∨ breakout_ok` universe (619) ⋈ prod `daily_predictions`
  (P(HR) via `COALESCE(prob_class_3, prob_class_1)`) ⋈ `fundamental_features` (deduped as-of
  filing) ⋈ `company_profiles`; derived **P/E** = `close/eps_diluted` (NULL when unprofitable).
  Pure JOIN of materialized parts, no new compute. Model-swap free (resolves `status_flag='prod'`).
- **`scripts/pages/3_Screening.py`** — theta-styled header strip + `st.form` filters (stage /
  sector / cap tier / gross+net margin / P/E / rev-growth / FCF-positive) + `st.column_config`
  P(HR)-ranked table + aggressive small-cap strip. **No expected-return column** (honest cone).
- Wiring: MANIFEST (`materialize_view`) + `load_screening()` + mounted in `dashboard_uplift.py`.

### Macro S1 (regime headline) — SHIPPED, incl. the F&G gap
- **Fear&Greed ingest LANDED.** `curl_cffi` `impersonate="chrome"` **clears the Cloudflare 418**
  — confirmed both directions (plain urllib → 418; curl_cffi → 200, score 46.9 neutral, 253 pts).
  Already installed → **no new dependency**. `macro_engine.fetch_fear_greed()` mirrors the
  `fetch_cape` non-FRED template; dispatched in `update_series`; added to the
  `update_macro_cache` non-FRED loop.
- **Nightly + remote parity came FREE** — the orchestrator's Phase 1.4 already calls
  `update_macro_cache()`, and `macro_data` is already MANIFEST-`full`. **Zero orchestrator /
  MANIFEST edits.** (The extension point already existed; that was the lazy path.)
- **`_render_s1`** in `2_Macro.py`: F&G dial (SVG arc, CNN banding) + **6 macro-pillar** percentile
  tiles w/ LONG/SHORT/NEUTRAL bias chips + deploy headline (posture · SPY>200d · supply regime ·
  stress_z · M03 score). `load_fear_greed()` + `fear_greed_label()` in `dashboard_utils`.

### Verified
Screening: view 619 rows / 558 scored / 408 P/E; slim-DB MANIFEST invariant ✓; `/Screening` 200.
Macro S1: gauge geometry correct at 0/25/50/75/100 (180°→0°); all 6 tiles resolve w/ percentiles;
F&G in slim DB (253 rows, through today); `/Macro` 200; no errors in either boot log.
Today's live read: **DEPLOY · SPY above 200d · supply famine · Credit 2.5th (LONG) · Rates 94th +
CAPE 76.7th (SHORT) · M03 82.9 · F&G 46.9 Neutral**.

## 📝 Files Changed
- `src/managers/view_manager.py`: `_create_v_d3_screening` + registration.
- `src/macro_engine.py`: `fetch_fear_greed()` + `update_series` dispatch + `update_macro_cache` loop.
- `scripts/pages/3_Screening.py` (NEW): Screening page.
- `scripts/pages/2_Macro.py`: S1 render (`_fg_gauge`, `_render_s1`, `S1_PILLARS`) + `pd` import.
- `scripts/dashboard_utils.py`: `load_screening()`, `load_fear_greed()`, `fear_greed_label()`.
- `scripts/build_dashboard_db.py`: `v_d3_screening` → MANIFEST.
- `scripts/dashboard_uplift.py`: mount Screening in nav.
- `docs/.../dashboard_uplift/README.md` + `macro_page.md`: status + build log + doc correction.

## 🚧 Work in Progress (CRITICAL)
- **Macro S3 (indicator board) NOT started** — the only remaining Macro section. It's an
  **ingestion backlog** (~30 C1 FRED series), not a rendering job. IDs enumerated in
  `plans/dashboard_uplift/macro_page.md` §"C1 — FRED".
- **Nothing is wired into the live `dashboard.py`.** Screening + Macro live only on
  `scripts/dashboard_uplift.py`. The 3 redundant Today tables (Shortlist / Pre-Breakout / VIP)
  are **not** retired — that's the switch-over step, deliberately deferred to the user's call.
- **Phase 7.46 (`sector_breadth`) still hasn't fired on its own** (carried from session 01) — the
  ops box `sh019` scheduler will run it; not yet observed.
- **No visual screenshot check** — verification was HTTP 200 + boot-log + exercising the real
  loaders/geometry. Playwright isn't installed; I judged a browser stack not worth it for one
  section. **S1's layout has never been seen by a human eye** — worth a glance next session.

## ⏭️ Next Steps
1. **Macro S3** — land the ~30 **C1 FRED** series (extend the `config.FRED_SERIES` list; the
   `update_macro_cache` loop already iterates it, so ingest should again be near-free). Grey out
   what's missing; **never gate the page on completeness**. Then C2 scrapes (AAII/NAAIM/COT),
   defer C3.
2. **Eyeball the shadow app** — `streamlit run scripts/dashboard_uplift.py` (set
   `DASHBOARD_DB_PATH=data/dashboard.duckdb`), confirm S1 + Screening look right.
3. Then: Portfolio (needs `positions`/`nav_history` tables) or Track Record (`forecasts` ledger)
   per the README build order.

## 💡 Context/Memory
- **The plan doc had a factual error, now fixed.** It credited `t2_regime_scores` for the "6
  pillars". Wrong table: `t2_regime_scores` holds M03's **three** pillars (trend/liq/risk). The
  6-pillar board is `load_macro_pillars` (VIX/Credit/Term/Rates/Liquidity/CAPE) — what the live
  Today page has always read. Built against the correct tables; both now in use (6 pillars = tiles,
  M03 = deploy headline). **Lesson: verify a plan's table citations against the DB before building.**
- **F&G has ~1yr of history ONLY** (253 rows) — CNN serves no deep archive, so unlike the FRED
  series this can **never** backfill to 2003. Display gauge only; **must not become a backtest input**.
- **F&G `INSERT OR IGNORE`** on the `(date,symbol)` PK → first write of the day wins, no intraday
  update. Correct for a nightly EOD snapshot; note it if a consumer ever needs intraday freshness.
- **The reuse win**: both features needed near-zero new plumbing because the extension points
  existed — `update_macro_cache`'s non-FRED loop (→ free nightly ingest) and `macro_data` being
  MANIFEST-`full` (→ free remote parity). `v_d3_prebreakout` already had the exact
  fundamentals-dedup + P/E derivation the Screening doc asked for; lifted the idiom rather than
  re-deriving.
- **Screening filter semantics (deliberate)**: a NULL fundamental = "unknown, keep", not "fails" —
  a pre-report biotech isn't dropped by a margin floor. Flip it if that reads wrong in use.
- Console glyphs: `∨`/`⋈` crash cp1252 on this box — ASCII in `print()`, unicode fine in docs/HTML.
