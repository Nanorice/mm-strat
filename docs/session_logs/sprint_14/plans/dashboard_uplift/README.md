# Dashboard Uplift — Meta Plan

> Sprint 14. Rebuild the dashboard toward the theta.md workflow/style.
> **Implementation started** (2026-07-16): Macro S2 shipped on a **shadow app**
> (`scripts/dashboard_uplift.py`) — the live `dashboard.py` is untouched until the
> full uplift switches over. This is the index + progress tracker; each page has
> its own design doc in this folder.

---

## Goal

Move from today's single monolithic Streamlit "Today" page to a **two-tier**
dashboard in the theta.md visual language, wired to the daily research workflow
(orchestrator → model → tradingagent reports → comprehension → reading list →
decisions → portfolio).

## Architecture — two tiers

| Tier | Pages | Audience | Style |
|---|---|---|---|
| **1 · Decision surface** (theta "Console") | Macro · Screening · Portfolio · Track Record · Supply-chain | daily decision-making | **new** cream/serif (`style.md`) |
| **2 · Workshop** (ours only) | Model Lab · Backtest Studio · Pipeline Health | operator/researcher | dense/mono — **do NOT theta-style** |

Shared nav + header shell; divergent body density. theta exposes only Tier 1;
Tier 2 is the mechanic's view.

## The "Today" page dissolves

The old monolith splits — every orphaned section gets a home:

| Old "Today" cluster | Lands on |
|---|---|
| 6-Pillar Macro · Weather Gauge · Sector Heat | **Macro** |
| Daily Shortlist · Pre-Breakout · VIP (one population, sliced) | **Screening** (stage filter) |
| Screener Watchlist (held trades) · Watchlist Activity · Decision Log · Past-Decision Perf | **Portfolio** |
| Daily Rank Bump · Cohort-Return · Analytics (diagnostics) | **Model Lab** (new "Live Monitoring" tab) |
| decision headline + 6-decision widget | stays as slim **Today** landing |

---

## Progress tracker

Status: ⬜ not started · 🟡 planned (design doc done) · 🔵 mock built · 🟢 partial (some sections shipped) · ✅ shipped

### Tier 1 — Decision pages
| Page | Status | Doc | Data gap | Notes |
|---|---|---|---|---|
| **Macro** | 🟢 | `macro_page.md` + `macro_page_mock.html` | **S3 only** (~54/66 indicators; C1 FRED / C2 scrape / C3 defer). S1+S2 done. | **S1+S2 SHIPPED** (`scripts/pages/2_Macro.py` on shadow app). S1 = F&G dial (`curl_cffi` clears the CF 418 ✓) + 6 macro-pillar percentile tiles + deploy headline. S2 = `sector_breadth_engine.py` + Phase 7.46. **S3 remains.** |
| **Screening** | ✅ | `screening_page.md` | **near-zero** (P/E derived) | **SHIPPED** (`scripts/pages/3_Screening.py` on shadow app; `v_d3_screening` view + MANIFEST + `load_screening`). Population = trend_ok∨breakout_ok (619); stage/fundamental filters in `st.form`; P(HR) rank + aggressive small-cap strip. No point-return column (honest cone). |
| **Portfolio** | ⬜ | — | **high** (no live `positions`/`nav_history` tables) | not drafted |
| **Track Record** | ⬜ | — | **medium** (needs `forecasts` ledger; Brier/cone scoring already exists) | not drafted; highest-leverage new table |
| **Supply-chain** | 🟡 | `supply_chain_page.md` | **highest** (nodes yes, **zero edges**) | long-term; Tier-0 correlation mock → Tier-1 EDGAR 10-K extraction (new engine) vs Tier-2 buy |

### Tier 2 — Workshop pages (exist; grow, don't rebuild)
| Page | Status | Doc | Change |
|---|---|---|---|
| **Model Lab** | ✅ exists | — | absorb diagnostics cluster as "Live Monitoring" tab; link out to `docs/model_doc/`, don't duplicate. **Card ✅ adheres to methodology** (C1 banner shipped; only Section-G hang outstanding) |
| **Backtest Studio** | 🟡 **revision planned** | `backtest_studio_page.md` | **⚠️ contradicts new methodology** — headlines the single Sharpe G6 retired, no cone, no C3 currency label, no engine tag. Revise: C3 banner + promote cone (=Gate tab) + engine column + demote single-Sharpe |
| **Pipeline Health** | ✅ exists | — | grow one freshness/failure row per new phase (esp. `comprehend_reports`); surface `deactivate_tickers.py` (memory TODO) |

### Cross-cutting infra
| Item | Status | Doc | Notes |
|---|---|---|---|
| **Style system** | 🟡 | `style.md` | tokens/type/components settled |
| **Research layer contract** | 🟡 | `research_layer_contract.md` | `research_reports` table = tradingagent boundary; `comprehend_reports` phase + `research_signals` deferred |
| **Platform decision** | ⬜ open | — | Streamlit vs static-HTML-over-slim-DB. Decide *per page* by interaction density; validate with the mocks. Migrate page-by-page, no big-bang. Dense pages (Macro, Supply-chain) are the pressure cases. |
| **Slim-DB `MANIFEST`** | — | — | **every** new table/view a loader reads MUST be added (remote-parity, `project_dashboard_remote_parity`) |

---

## Recommended build order

1. **Screening** — most data-complete; retires 3 redundant Today tables immediately.
2. **Macro** — S2 heatmap (data-complete) → S1 (F&G ingest) → S3 incremental (C1 FRED first).
3. **Portfolio** — needs `positions`/`nav_history` tables first; unlocks the held-trades migration.
4. **Track Record** — `forecasts` ledger + existing scoring; high leverage, low effort once agent emits convictions.
5. **Supply-chain** — long-term; Tier-0 mock now, edges as a separate research thread.

Workshop-tier changes (Model Lab monitoring tab, Pipeline Health phase rows) slot
in alongside whichever data thread lands them.

---

## Build log

- **2026-07-16 — Macro S1 (regime headline) shipped** + **Fear&Greed ingest landed**.
  - `src/macro_engine.py` — `fetch_fear_greed()`: CNN dataviz endpoint via
    `curl_cffi` `impersonate="chrome"` (clears the Cloudflare TLS 418; plain
    urllib reproduces the 418). Dispatched in `update_series` + added to the
    `update_macro_cache` non-FRED loop → **nightly Phase 1.4 picks it up with no
    orchestrator change**; `macro_data` is already MANIFEST-`full` → remote parity free.
    ⚠️ ~1yr history only (253 rows) — CNN serves no deep archive; display gauge, not a
    backtest input.
  - `scripts/pages/2_Macro.py` — `_render_s1`: F&G dial (SVG arc, CNN banding) +
    6 macro-pillar percentile tiles w/ LONG/SHORT/NEUTRAL bias chips + deploy
    headline (posture · SPY>200d · supply regime · stress_z · M03 score).
  - `scripts/dashboard_utils.py` — `load_fear_greed()` + `fear_greed_label()`.
  - **Doc correction**: the plan credited `t2_regime_scores` for the "6 pillars" —
    wrong table. Pillars = `load_macro_pillars` (VIX/Credit/Term/Rates/Liquidity/
    CAPE); `t2_regime_scores` = M03's *three* pillars, now feeding the deploy
    headline. Fixed in `macro_page.md`.
  - Verified: F&G scrape 200 (score 46.9 neutral, 253 pts); gauge geometry across
    0/25/50/75/100; all 6 tiles resolve w/ percentiles; slim DB ships F&G (253
    rows); shadow app `/Macro` + `/Screening` boot 200 no errors.
- **2026-07-16 — Screening page shipped** on the shadow app.
  - `src/managers/view_manager.py` — `_create_v_d3_screening`: latest-day
    `trend_ok∨breakout_ok` universe ⋈ prod `daily_predictions` (P(HR), COALESCE
    class_3→class_1) ⋈ `fundamental_features` (margins/growth, deduped as-of
    filing) ⋈ `company_profiles`; derived P/E (`close/eps_diluted`, NULL when
    unprofitable). Display view, lowercase (not model-fed).
  - `scripts/pages/3_Screening.py` — theta-styled header strip + `st.form`
    stage/fundamental/sector/cap filters + `st.column_config` P(HR)-ranked table
    + aggressive small-cap strip. No point-return column (honest cone).
  - Wiring: `v_d3_screening` → `build_dashboard_db` MANIFEST (`materialize_view`);
    loader `load_screening()`; mounted in `dashboard_uplift.py` nav.
  - Verified: view 619 rows / 558 scored / 408 P/E; slim-DB build + MANIFEST
    invariant ✓; shadow app + `/Screening` route boot 200 no errors.
- **2026-07-16 — Macro S2 (sector/subsector heatmap) shipped** on the shadow app.
  - `src/sector_breadth_engine.py` — nightly `sector_breadth` snapshot (return
    histogram + breadth + participation + added today/5d, per sector & subsector).
  - `scripts/pages/2_Macro.py` — theta-styled S2 render (histogram KDE, expand-on-click).
  - `scripts/dashboard_uplift.py` — shadow `st.navigation` entrypoint (live nav untouched).
  - Wiring: Phase 7.46 (`phase_registry` + `config` + orchestrator) + `build_dashboard_db`
    MANIFEST entry. Loader `load_sector_breadth()` in `dashboard_utils.py`.
  - Session handover: `../../logs/2026-07-16.md`.
  - **Switch-over reminder**: fold shadow pages into `dashboard.py`'s `st.navigation`
    and delete `dashboard_uplift.py` once the full uplift is ready.

## Open questions (user)

1. **tradingagent output** — what does it emit, can it write DuckDB or drop a file? (sizes the ingest side of the research layer)
2. **Supply-chain edges** — build (Tier-1 EDGAR extraction, multi-week) vs buy (Tier-2 vendor feed, paid)?
3. **Platform** — settle after the mocks give evidence.

## Files in this folder
- `README.md` — this meta plan.
- `style.md` — visual system.
- `macro_page.md` / `macro_page_mock.html` — Macro design + standalone mock.
- `screening_page.md` — Screening design.
- `backtest_studio_page.md` — Backtest Studio revision (methodology adherence: cone + C3 currency).
- `supply_chain_page.md` — Supply-chain design + edge-sourcing tiers.
- `research_layer_contract.md` — tradingagent → repo boundary.
