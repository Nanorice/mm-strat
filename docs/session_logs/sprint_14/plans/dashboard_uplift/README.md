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
| **1 · Decision surface** (theta "Console") | Macro · Screening · Portfolio · ~~Track Record~~ (dropped) · Supply-chain | daily decision-making | **new** cream/serif (`style.md`) |
| **2 · Workshop** (ours only) | Model Lab · Backtest Studio · Pipeline Health | operator/researcher | dense/mono — **do NOT theta-style** |

Shared nav + header shell; divergent body density. theta exposes only Tier 1;
Tier 2 is the mechanic's view.

## The "Today" page dissolves

The old monolith splits — every orphaned section gets a home:

> ✅ **RESOLVED 2026-07-18** — the table below was the *plan*; the triage that follows
> (checklist section) is what actually happened, and it corrected two wrong premises here:
> "Screener Watchlist → Portfolio" (different populations) and the missing VIP row.

| Old "Today" cluster | Lands on | Actual outcome |
|---|---|---|
| 6-Pillar Macro · Weather Gauge | **Macro** | ✅ migrated |
| Sector Heat | ~~Macro~~ | ⬜ **dropped** — Macro S2 `sector_breadth` is a strict superset |
| Daily Shortlist · Pre-Breakout · VIP (one population, sliced) | **Screening** | ✅ migrated; VIP renamed **Watchlist** |
| Screener Watchlist · Watchlist Activity | ~~Portfolio~~ → **Session activity** | ✅ **new page** — NOT Portfolio (sessions ≠ trades) |
| Decision Log · Past-Decision Perf | ~~Portfolio~~ | ⬜ **dropped** — 1 `decision_taken` in 302,220 rows; the `trades` CLI replaced it |
| Daily Rank Bump | **Model Lab** | ✅ `render_live_monitoring()` |
| Cohort-Return | ~~Model Lab~~ | ⬜ **dropped** — median band contradicts the sprint's tail-first conclusion |
| Analytics (diagnostics) | ~~Model Lab~~ | ⬜ **dropped** — quadrants over *session* data; Portfolio Risk covers the real book |
| decision headline + 6-decision widget | slim **Today** landing | ⬜ open — decide at the switch |

---

## Progress tracker

Status: ⬜ not started · 🟡 planned (design doc done) · 🔵 mock built · 🟢 partial (some sections shipped) · ✅ shipped

### Tier 1 — Decision pages
| Page | Status | Doc | Data gap | Notes |
|---|---|---|---|---|
| **Macro** | ✅ | `macro_page.md` + `macro_page_mock.html` | **COT + C3 feeds** (61/61 live; C1 FRED + AAII/NAAIM ingested) | **S1+S2+S3 SHIPPED** (`scripts/pages/2_Macro.py` on shadow app). S1 = F&G dial (`curl_cffi` clears the CF 418 ✓) + 6 macro-pillar percentile tiles + deploy headline. S2 = `sector_breadth_engine.py` + Phase 7.46. S3 = indicator board, **9 of 10 groups** (group 7 filled by the C2 sentiment scrapes; only 10/calendar awaits C3). |
| **Screening** | ✅ | `screening_page.md` | **near-zero** (P/E derived) | **SHIPPED** (`scripts/pages/3_Screening.py` on shadow app; `v_d3_screening` view + MANIFEST + `load_screening`). Population = trend_ok∨breakout_ok (619); stage/fundamental filters in `st.form`; P(HR) rank + aggressive small-cap strip. No point-return column (honest cone). |
| **Portfolio** | ✅ | `portfolio_risk_section.md` | **closed** (`trades` + `cash_flows` + `nav_history`) | **SHIPPED incl. Risk section** (`scripts/pages/4_Portfolio.py` on shadow app). Append-only `trades` + `cash_flows` cash leg via `scripts/portfolio.py` CLI → derived positions/cash. **NAV = cash + positions; return TIME-WEIGHTED** (flows stripped per day → a deposit is not a gain) so YTD/drawdown are truthful. Score (raw) + cohort + %NLV + concentration + sector tilt. **Risk** = ATR/vol/S-R/52w/beta + 1-ATR-per-NAV, all from `price_data` so off-screen holdings are covered (entries are discretionary). Empty until fills are logged. ✅ `nav_history` **wired into the nightly** 2026-07-17 — **Phase 7.47** (`portfolio_nav`, WARN, between sector_breadth 7.46 and dashboard_db 7.5 so the row ships in the slim DB). |
| **Track Record** | ❌ **DROPPED** | — | n/a | **Retired 2026-07-17 (user).** Overlaps Portfolio: reports are *study material*, entries/exits are **discretionary**, so the only thing actually "projected" is the entry/exit decision — which IS the `trades` log on Portfolio. Scoring the *report* would measure a thing that never bound the decision. The tradingagent structured-block contract it was blocked on wouldn't fix the overlap. ⚠️ The old "Brier/**cone** scoring already exists" claim was **wrong** — the cone is the *start-date* cone (strategy evaluation across 90 start dates); it has no role in scoring a forecast ledger. Two different things called "scoring". |
| **Supply-chain** | ✅ **page shipped (shadow)** | `supply_chain_page.md` + `supply_chain_mock.html` | **highest** (nodes yes, **still ZERO edges**) | **Page shipped 2026-07-18** (`scripts/pages/6_Supply_Chain.py`): 3 tabs — **Sector map** (co-movement heatmap + hub/loner table), **Sub-sectors** (LIVE drill-down, 149 industries from `company_profiles`), **Company network** (honest empty state naming build-vs-buy). Loaders `load_sector_comovement` / `load_sector_industries`. ⚠️ **Heatmap, NOT the mock's d3 chord**: the mock loads d3 from a **CDN** (a Streamlit component can't rely on that remotely), and at 11 sectors a chord reads ordinally while the real question is a pairwise magnitude lookup — a matrix answers it exactly. The mock keeps its chord for the format decision. ⚠️ `price_data` is MANIFEST-`window`ed → **252d local vs 171d remote**; the loader returns ACTUAL `n_days` (not the request) so the caption tells the truth on both. Still **zero real edges** — build (Tier-1 EDGAR) vs buy (Tier-2 vendor) remains an open user decision, but the page is **no longer blocked on it**. |
| **Equity Research** | ✅ **placeholder shipped (shadow)** | `equity_research_page.md` | **total** (`research_reports` doesn't exist) | **Shipped 2026-07-18** (`scripts/pages/7_Equity_Research.py`). Verified against the live DB: **zero** tables matching `%research%`/`%report%` → renders the empty state. `_load_reports()` probes `information_schema` and distinguishes **table-absent (None)** from **table-empty (0 rows)** — two different truths, two different messages; collapsing them would hide whether the research layer is unbuilt or merely unpopulated. Fills in with **no page rewrite** once the table lands. |
| **Session activity** | ✅ **shipped (shadow)** | — (triage below) | closed | **NEW page 2026-07-18** (`scripts/pages/5_Session_Activity.py`) — the read surface for `screener_watchlist`, absorbing the old Today page's **Screener Watchlist + Watchlist Activity** pair (two views of ONE table under names implying two populations). 4 tabs: open sessions (362) · recently closed (73) · activity feed · ticker history. 🛑 **Sessions are NOT trades** — the page never shows currency P&L, only per-session % moves; the real book is Portfolio. |

### Tier 2 — Workshop pages (exist; grow, don't rebuild)

> **Spine (user, 2026-07-17): `data → model/label → strategy`.** Pages split by **STAGE**;
> the currency (C1 label / C2 OOS / C3 exit-P&L) is the claim-strength banner *within* a
> page, not the split itself. Dataset EDA = data · Model Lab = model/label · Backtest
> Studio = strategy. See `cone_and_studio_design.md`.
> ⚠️ **All three are LIVE `dashboard.py` pages** — unlike Macro/Screening/Portfolio, a
> revision here touches the working version. Uplift versions land as **new files** in the
> shadow nav; the live ones stay untouched until switch-over.

| Page | Status | Doc | Change |
|---|---|---|---|
| **Dataset EDA** | ✅ exists | `cone_and_studio_design.md` | **= the `data` stage.** Pretrain-audit report browser (120 lines). **No change planned** — it's input inspection, upstream of any currency claim. (The sprint EDA belongs on Model Lab, not here.) |
| **Model Lab** | ✅ **v2 shipped (shadow)** + **live monitoring** | `cone_and_studio_design.md` | **+ 2026-07-18: `render_live_monitoring()`** — the Daily Rank Bump carried over from the Today monolith, placed **ABOVE the registry selector** (it is scoped to the **prod** model, not to whichever model you click below; a per-model tab would imply archived models have rank history, and `daily_predictions` carries only the prod one). Cohort default `pre_breakout` — names persist day-over-day as they set up, while `breakout` renders as isolated points (**measured: 124 distinct names across 127 name-days** = near-total daily turnover), which is the finding, not a rendering fault. **= the `model/label` stage.** `scripts/pages/3_Model_Lab_v2.py`: **C1 banner** + **Funnel** tab + **Label-outcome** tab (both surface the sprint-summary EDA PNGs) + the **LABEL cone** rendered live from `cone_cells` (`engine='basket_paths'`), tail-first (home-run rate leads; median explicitly flagged misleading). Registry/card/plots/specs/diff carried over. ⚠️ Live `3_Model_Lab.py` untouched — awaits switch-over. Section-G hang still outstanding. |
| **Backtest Studio** | ✅ **v2 shipped (shadow)** | `backtest_studio_page.md` + `cone_and_studio_design.md` | **= the `strategy` stage.** `scripts/pages/4_Backtest_Studio_v2.py`: **C3 banner** → **engine column** + vec-optimism caption → **strategy cone** promoted above the run browser (full start-date distribution from `cone_cells`) → single-Sharpe demoted to "Sharpe (draw)". **+ per-cell zoom**: select a cone cell → exposure (bear-regime shaded) · per-trade P&L · breakdowns · trade table · rejection summary, from the local per-cell parquets. ⚠️ Live `4_Backtest_Studio.py` untouched — awaits switch-over. |
| **Pipeline Health** | ✅ exists | — | **DQ section shipped 2026-07-17** (`render_data_quality` — per-audit breakdown + failing checks + `new_fails` regressions) + the **audit-history zero-chart bug fixed**. Serving-layer audit now covers Phases 7.4/7.45/7.46/7.47. Still open: surface `deactivate_tickers.py` (memory TODO); a `comprehend_reports` row if that phase lands |

### Cross-cutting infra
| Item | Status | Doc | Notes |
|---|---|---|---|
| **Style system** | 🟡 | `style.md` | tokens/type/components settled |
| **Research layer contract** | 🟡 | `research_layer_contract.md` | `research_reports` table = tradingagent boundary; `comprehend_reports` phase + `research_signals` deferred |
| **Platform decision** | ⬜ open | — | Streamlit vs static-HTML-over-slim-DB. Decide *per page* by interaction density; validate with the mocks. Migrate page-by-page, no big-bang. Dense pages (Macro, Supply-chain) are the pressure cases. |
| **Slim-DB `MANIFEST`** | — | — | **every** new table/view a loader reads MUST be added (remote-parity, `project_dashboard_remote_parity`) |
| **`cone_cells` (both cones)** | ✅ | `cone_and_studio_design.md` | ONE table, TWO cones split by `engine` — never render them as one. `BackTrader` = strategy cone (C3, metric `sharpe`, `build_cone_cache.py`); `basket_paths` = label cone (C1, metric `total_return`, sharpe **NULL by design**, `build_label_cone_cache.py`). Both builders do an **engine-scoped upsert** so neither clobbers the other; `load_cone_cells(engine=…)` defaults to BackTrader. MANIFEST `full` → both engines reach the remote. Staleness checked per engine in `tools/audit_serving_tables.py` (strategy vs sweep-summary mtime, label vs score-cache mtime). |

---

## Recommended build order

1. **Screening** — most data-complete; retires 3 redundant Today tables immediately.
2. **Macro** — S2 heatmap (data-complete) → S1 (F&G ingest) → S3 incremental (C1 FRED first).
3. **Portfolio** — needs `positions`/`nav_history` tables first; unlocks the held-trades migration.
4. ~~**Track Record**~~ — **DROPPED 2026-07-17** (overlaps Portfolio; see the tracker row).
5. **Supply-chain** — long-term; Tier-0 mock now, edges as a separate research thread.

Workshop-tier changes (Model Lab monitoring tab, Pipeline Health phase rows) slot
in alongside whichever data thread lands them.

---

## Build log

- **2026-07-18 (session 09) — switch-over triage RESOLVED + the last 3 pages shipped.**
  Shadow app reaches **feature parity**; the switch is unblocked. Nav regrouped into
  **Decide** (Macro · Screening · Session activity · Portfolio · Supply chain · Equity
  research) and **Workshop** (Model Lab · Backtest Studio), matching the two-tier
  architecture this doc has described since day one.
  - **Triage: 4 carried over, 5 OK to miss** (full table + evidence in the checklist
    below). The user's "most are duplicates" premise held for 4 of 8 — but **two of the
    README's own premises were wrong**:
    - 🛑 **"Screener Watchlist → Portfolio" was never a migration.** `screener_watchlist`
      (38,648 rows / 362 ACTIVE) is the **algorithmic session store**; `trades` (**0
      rows**) is the real discretionary book. Folding one into the other would have mixed
      simulated sessions into a real NAV. It's also not a third population — it's the
      display twin of `sepa_watchlist`, i.e. the session history of the Screening page's
      own names.
    - 🛑 **The 13-section count MISSED `render_vip_watchlist`** — a 9th orphan on the live
      page and on no checklist.
  - **Section #9 needed NO BUILD.** The watchlist table already existed on Screening
    (`3_Screening.py`, the `load_vip_watchlist` block) — the user's ask ("show these 2
    tables on the same page") was already satisfied. Only the **naming** was wrong.
    Renamed VIP → **Watchlist**, `sepa_active` stated for the table above it. *Reading the
    target file first turned a "build a page" task into a 3-line rename.*
  - 🔁 **A wrong claim from earlier THIS session, corrected.** The scoring gap was
    reported as "watchlist names may have no features at all → infra project". **False** —
    `feature_pipeline.py:637` UNIONs `vip_watchlist` into the T3 candidate set precisely
    so curated names get daily features *"even if they never pass the screen"*. The real
    gap is **one join deep**: `v_d3_lifecycle`'s `wl` CTE INNER JOINs `screener_watchlist`,
    so a name with features but no SEPA *session* lands in no cohort. **Fix = INNER→LEFT
    JOIN on one view**, not a new engine. Deferred by the user; the page ships with an
    honest blank + a caption naming the cause. **Lesson: a view's SELECT tells you what it
    READS, never what FEEDS it — trace upstream before calling something structurally
    absent.**
  - **Cohort-Return Tracker DROPPED on methodology, not on the reason proposed.** The user
    asked whether it dies with `screener_watchlist`; it doesn't — `cohort` lives on
    `daily_predictions` and comes from `v_d3_lifecycle` (**two unrelated things called
    "cohort"**, cf. the Track Record "two things called scoring" trap). It was dropped
    because its **median-return band contradicts the sprint's own conclusion**
    (`project_tail_magnitude_objective`: tail-lift not medians; IC ≈ −0.03 within the
    pool). Rank Bump survives because it shows **structural rank persistence**, not P&L.
  - **Supply-chain: heatmap, not the mock's chord** — the mock's d3 comes from a **CDN**,
    unusable in a remote Streamlit component, and at 11 sectors a chord reads ordinally
    while the question ("who co-moves with whom, how much") is a pairwise magnitude
    lookup. Sub-sector drill-down is **LIVE** (149 industries) but captioned as
    **taxonomy, not edges** — `industry` says what a company *is*, never what it *buys
    from*. Company network renders the build-vs-buy gap honestly.
  - **Equity Research** distinguishes **table-absent** from **table-empty**. Verified
    `research_reports` does not exist (0 tables matching `%research%`/`%report%`).
  - ✅ **Verified by DRIVING, not by pytest** (the house lesson, 4th time this thread):
    all 5 pages via `AppTest` → **0 exceptions** against **both** the full DB **and the
    slim `dashboard.duckdb`**; every interactive path exercised — **4/4 cohorts**,
    **11/11 sectors** (152 industries / 4,109 companies), 6 window radios, real *and*
    bogus ticker lookups. MANIFEST parity checked by opening `dashboard.duckdb`
    **directly** (8/8 tables) — never through a loader.
    - 🐛 **Caught in review, not by a test**: `px` (plotly.express) was used in the new
      rank-bump renderer but the file only imported `go`. A grep for the import caught it
      before the first run.
    - 📏 **Suite: 385 passed / 15 failed.** The 15 were verified **pre-existing** by
      stashing the whole change and re-running on a clean tree — identical failures.
      ⚠️ The documented baseline said **7**; it has drifted to 15 over prior sessions
      (`test_backtest_smoke`, `test_forward_parity` are new arrivals). **None are
      dashboard tests**, but the drift deserves its own look.
- **2026-07-17/18 (sessions 07–08) — Tier 2 SHIPPED: both cones, both v2 pages.**
  Commits `7d2eb51` (feature), `60fbd7b` (schema doc + dead-test cleanup), `8862557`
  (rename closure).
  - **`cone_cells` = ONE table, TWO cones, split by `engine`.** The whole point of
    `cone_and_studio_design.md` §0: a buy-and-hold-to-exit fan is **not** a backtest
    result. They now co-exist without ever rendering as one object:
    - **strategy cone** (`engine='BackTrader'`, `build_cone_cache.py`) — 2,460 cells /
      22 arms, one per start-date draw. **Source = each arm/grid `summary.json`, NOT the
      2,892 per-cell `metrics.json`**: the summary is the curated set (degenerate 1-day
      cells filtered) and carries the **window-fair** `ann_return`/`sharpe`, while
      per-cell metrics.json has `annualized_return=0` (a known BackTrader gap). Walking
      summaries is both lazier and more correct. ✔️ `champion_gated` median Sharpe
      **0.47 / 33% neg** reproduces the pinned reference cone exactly — a strong
      correctness signal the walk is right.
    - **label cone** (`engine='basket_paths'`, `build_label_cone_cache.py`) — 3,885
      cells / 4 gate variants (regime-gate × score-gate), one per start-DAY basket.
      `total_return` = fwd_return, `n_days` = exit_day, and **`sharpe`/`ann_*`/
      `max_drawdown` are NULL BY DESIGN** — a buy-and-hold basket produces no Sharpe;
      inventing one would be the exact category error the two-cone split exists to
      prevent. Runs in ~30s (4 variants), so no checkpointing needed.
  - 🛑 **The coupling that had to be fixed first**: the strategy builder did
    `CREATE OR REPLACE TABLE cone_cells`, which would **silently wipe every label row**
    the moment someone re-ran a sweep. Both builders now do an **engine-scoped upsert**
    (delete-own-engine + insert). Verified in both directions — rebuilding the strategy
    cone left all 3,885 label rows intact, and vice versa.
  - ⚠️ **`load_cone_cells` gained an `engine` param defaulting to `BackTrader`** — the
    Studio calls it with no args, so without a default the C3 page would have silently
    started listing `label_*` arms in its picker. Verified the Studio arm picker
    excludes them.
  - **Backtest Studio v2** (`4_Backtest_Studio_v2.py`): C3 banner → engine column +
    vec-optimism caption (vec median Sharpe ~1.51 vs BackTrader ~0.35 **on the same
    config** — they sat in one table looking comparable) → **strategy cone promoted
    above the run browser** → single-Sharpe demoted to "Sharpe (draw)". **+ per-cell
    zoom**: exposure (open positions + cash/deployed, **bear-regime shaded** — a flat
    NAV stretch is *no positions*, not a losing hold), per-trade P&L, breakdowns, trade
    table, rejection summary (125k rows → grouped by reason, never dumped). All from
    per-cell parquets that **already existed**; nothing computed, only surfaced.
    Trades/rejections stay **local-only** (~37 MB) — the remote is a viewing surface,
    not the research bench, so the zoom degrades gracefully off-host.
  - **Model Lab v2** (`3_Model_Lab_v2.py`): C1 banner + **Funnel** + **Label-outcome**
    tabs (surface the existing `data/model_output_eda/sprint_summary/*.png` — the EDA
    was already rendered; porting matplotlib to live Plotly would have needed an
    aggregate cache for an 8.9M-row input, for static conclusions) + the **live label
    cone**. Framing is **tail-first**: home-run rate leads, median is rendered but
    labelled *"misleading"* — a median-first chart here would contradict the sprint's
    own conclusion.
  - **Serving audit `check_cone_cache` is now engine-scoped.** The old shared
    `MAX(built_at)` would let one fresh cone **mask the other's staleness**. Now:
    strategy vs newest sweep-summary mtime, label vs score-cache mtime. Both
    **mutation-verified** (simulated-newer source → WARNING; real state → OK).
  - 📌 `cone_cells` was already MANIFEST `full`, so the label rows reached the slim DB
    with **zero new wiring** — the shared-table choice paid for itself.
  - ✅ Verified: both pages driven via `AppTest` → **0 exceptions**, including driving
    the cell picker into a real 67-trade rolling cell and switching label-cone variants.
    6/6 cone-builder tests pass (fingerprint identity, the 4-variant gate cross, and the
    NULL-metric C1 contract). Full suite run: **391 passed**; the 7 failures / 26 errors
    are **pre-existing and unrelated** (`test_feature_catalog`, `test_phase1_backfill`,
    `test_feature_pipeline` — stale tests whose source modules drifted), confirmed by
    checking that no changed file lives in those modules.
  - 🐛 **Widget-key collision caught before it shipped**: `render_trade_table` renders
    from **both** the run browser and the cell zoom on one page, and its filter
    selectboxes used fixed keys → `DuplicateWidgetID`. Fixed with a `key_prefix` param.
  - 🐛 **Cell labels carry the grid tag** (`[rolling]`/`[horizon]`/`[matrix]`): an arm
    mixes fixed-12m start-date draws with varying-horizon cells, so a bare start date
    conflated two different things in one picker.
  - **`sepa_watchlist` display-rename → CLOSED, no action.** The plan assumed the
    dashboard renders a "SEPA watchlist" label; a case-insensitive grep across
    `dashboard.py`, `dashboard_uplift.py` and every page found **no such label**. The 9
    user-visible "SEPA" strings are prose where SEPA correctly names the *methodology*;
    the rest are class/table names §1 already decided to KEEP. The misnaming was always
    the **table name**, a surface §1 deliberately doesn't touch — so the item had no
    target. Evidence recorded in `rename_sepa_watchlist_plan.md` so it isn't re-derived.
- **2026-07-17 (session 06) — NAV nightly (Phase 7.47) · Track Record dropped · DQ section
  + serving audit.** Three user decisions.
  - **Phase 7.47 `portfolio_nav`** (WARN, order 7.47) — `snapshot_nav()` between
    sector_breadth (7.46) and dashboard_db (7.5) so the row ships in the slim DB.
    Modelled exactly on 7.46. `target_date` is a **str** in the orchestrator but
    `snapshot_nav` takes a `date` → explicit `strptime`, no silent pass-through.
    **Why it earns a slot despite writing 1 row/day**: a NAV series **cannot be honestly
    backfilled** — TWR needs the day's `net_flow` recorded *on the day*, so a missed run
    is a permanent hole. Driven for real on a temp DB: NAV 105,000 = cash 85k + positions
    20k, net_flow 100k captured, idempotent on re-run (1 row after 2 runs).
  - **Track Record DROPPED** (user). Overlaps Portfolio — reports are study material,
    decisions are discretionary, so what gets "projected" is the entry/exit = `trades`.
    ⚠️ Also killed a **false claim in this very doc**: "Brier/**cone** scoring already
    exists" conflated the **start-date cone** (strategy evaluation) with forecast
    scoring. Two unrelated things called "scoring"; the cone has no role on that page.
  - 🐛 **The Pipeline Health "Audit History" chart has NEVER shown real data** — it read
    `summary.pass_count`/`passed` etc.; the real keys are `summary.total.{OK,WARNING,
    FAIL,INFO}`. Three fallback spellings + `.get(...,0)` on each → a total miss rendered
    **three flat zero lines** instead of an error, hiding **6 real FAILs** across 23
    reports. In committed HEAD, not from the uplift. **A green-looking panel is not
    evidence the panel works.**
  - **DQ section shipped** (`render_data_quality`): per-audit FAIL/WARN/OK breakdown,
    today's failing checks by name+detail, and **`new_fails`** (regressions vs the
    previous run). All three were **already written nightly by `run_all_audits.py` and
    simply never read** — no new table, no new phase. Answering the user's "how do we
    maintain the DQ data?": Phase 8 already writes `data/audit_reports/*.json` (23 on
    disk, R2-synced).
  - **`tools/audit_serving_tables.py` (NEW)** — the derived tables had **no audit at all**
    (the T1 script audits T1; `sector_breadth`/`weather_gauge`/`daily_predictions`/
    `nav_history` sat below that line, so a dead Phase 7.4/7.45/7.46 greys a panel and
    says nothing). Registered in `run_all_audits.py` → **Serving Tables: 0 FAIL 0 WARN
    6 OK** in the real nightly run.
    - 📏 **Tolerances MEASURED not guessed** (the macro_data lesson): observed 2y
      worst-case gap = weather_gauge **6d**, daily_predictions **13d** (a one-off
      07-02→07-15), sector_breadth is a **1-date snapshot**. Shipped 10/20/5 = observed
      + headroom → 0 false warnings on the live DB.
    - Sanity checks beyond freshness: `sector_breadth` must hold **exactly 1 as_of_date**
      (refresh replaces; >1 = the append bug), `weather_gauge` non-NULL posture (it drives
      SPY>200d, the only surviving lever), `nav_history` **nav == cash + positions**
      (cash is derived, so drift = broken invariant).
    - 🐛 Caught by **driving the CLI, not by pytest**: `sector_breadth.as_of_date` is a
      **TIMESTAMP** while the rest are DATE → `TypeError: date - datetime`. Fixed with a
      `CAST(... AS DATE)` in the query. 3rd time this thread that running the real command
      caught what tests didn't.
    - 🧪 **All 4 checks mutation-verified**: on a deliberately broken DB all 4 fire; on the
      healthy DB none do. The tolerance test varies staleness across the 20d boundary —
      mutating the tolerance 20→60 **fails it** (an all-OK audit proves nothing until you
      prove it can fail).
  - ✅ Verified: page driven via `AppTest` → **0 exceptions**, "Data Quality" renders the
    **real 6 FAIL / 25 WARN / 224 OK / 35 INFO**; audit history now 23 rows of real data
    (0 all-zero rows, was 23). Suite **381 passed** + 7 new serving tests (baseline's 7
    failures / 26 errors unchanged). Real book untouched: **0 rows** (all drives on temp
    DBs, deleted).
- **2026-07-17 — Portfolio Risk section shipped** (`_render_risk` +
  `dashboard_utils.load_portfolio_risk`). Doc: `portfolio_risk_section.md`.
  - **Two user decisions reshaped it.** (1) Entries/exits are **DISCRETIONARY** — the
    champion is only there to set expectation (*"it is a lottery"*) → **no
    divergence-from-champion panel**, and holdings routinely sit **outside the SEPA
    screen**, so every metric resolves from `price_data` (all tickers) rather than
    t2/t3 (~2,724 of 3,980 active). (2) The section is to **measure/monitor**, not act.
  - **Shipped**: ATR(14)/ATR%, realized vol 20d/60d, 20d-50d support/resistance,
    **distances in ATR UNITS** (dollars aren't comparable across names), **1-ATR move
    as % of NAV** (`qty×ATR/NAV`), true 52w high/low, mv-weighted book beta,
    top-3/sector share.
  - 💡 **`1-ATR / NAV` is the payoff metric** — it converts per-name noise into book
    impact. Live: **PSNL (7.9% ATR) contributes MORE book risk than a much larger
    NVDA position**. Invisible on a positions table.
  - 🛑 **NO VaR / expected shortfall — and NOT for infra reasons** (it's ~10 lines off
    `price_data`). It would **mislead**: it needs a covariance matrix to mean anything
    at book level, and with ~4 concentrated same-sector names the correlation term
    dominates; a window-fitted VaR prints calm right up to the regime that breaks it.
    Don't re-propose.
  - ⚠️ **A true 52w level CANNOT be recomputed on the remote** — the slim DB windows
    `price_data` to ~172 bars (~8mo). t3's `high_52w` is a **stored** value so it
    survives the window: **READ it, never recompute**; "—" off-screen. Conversely ATR
    is **computed in the loader, NOT read from t3's `atr_20d`**, so the window is
    identical for every holding. ATR bounds the known OHLC dirt with GREATEST/LEAST.
  - 🧪 **The ATR test was mutation-checked and the first version was WORTHLESS**: a
    constant true range makes EVERY window average the same, so it passed with the
    window mutated 14 → 5. Fixed by varying TR per bar (ATR(14)=7.5 vs 5-bar=3.0);
    the mutation now fails it. **A metric test must vary the input along the axis it
    claims to pin.** 2nd time this class hit this thread (cf the session-04 bot-block
    test). ATR SQL also cross-checked against an independent pandas computation
    (NVDA 7.1407 / KO 1.7146, exact).
  - 🐛 **Bug fixes from the prior session's list**: (a) the CLI docstring still claimed
    *"NAV carries NO cash leg"* — stale and false after the cash leg landed; (b) the
    `nav_history` shape fix confirmed. ⚠️ **The first verification of (a) was a FALSE
    PASS**: `grep -P` isn't supported in this locale, so it printed "none" without
    running. Re-checked properly, then proved the real failure mode by running the CLI
    under an actual **cp1252** console (prints clean).
  - ✅ Verified: 31 portfolio tests (3 mutations checked), suite **381 passed** (7
    pre-existing failures unchanged); page driven end-to-end with real market data
    (PSNL/NVDA/KO incl. an off-screen holding). Real book untouched: 0 rows.
- **2026-07-16 — Portfolio page shipped; cash leg added after a mock review.**
  Built from a competitor screenshot the user shared. **The screenshot is a marketing
  page** — it self-labels "CONCEPT PREVIEW — SAMPLE DATA" / "money sample" behind a
  £15/30d paywall. Analysed panel-by-panel against our DB rather than copied (same
  discipline as `macro_page_mock.html`, whose "10/10 indicators" were invented):
  roughly ⅓ real for us, ⅓ needed a cash leg, ⅓ needs data that doesn't exist.
  - **Built**: append-only `trades` fill log + `cash_flows` + derived positions/cash;
    `scripts/portfolio.py` CLI (buy/sell/deposit/withdraw/positions/trades/nav);
    Score (raw) + cohort + %NLV + Top-3 concentration + sector tilt + TWR curve.
  - ✅ **Cash leg (user reversed the earlier positions-only call).** NAV = cash +
    positions; **return is TIME-WEIGHTED** — `nav_history.net_flow` stores the day's
    external flow so `returns()` strips it. Verified live: **a 500k deposit → ret
    +0.0000%**, while the naive `pct_change` it replaces booked **+500%**; a real
    mark-up on the next day still measured +1.82%. Both directions test-pinned and
    mutation-verified.
  - ⚠️ **The model scores only ~751 of ~3,980 active tickers** (SEPA lifecycle
    universe) → a held name outside it renders **"—", never a stale score or a zero**
    (a zero reads as "model hates it"). Score is **RAW** (a rank, not a probability),
    same rule as Screening.
  - **Rejected from the mock, deliberately**: cash/margin/theta/options (no data),
    supply-chain concentration (**zero edges**), and the "Style review 5.8/10
    Balanced" composite (**an invented number**).
  - **Risk section = PLAN ONLY** (`portfolio_risk_section.md`), per the user —
    *(superseded: **shipped 2026-07-17**, see the entry above)*. The plan's core
    finding, which still binds it: **our research already falsified the obvious
    levers** — DD circuit breaker (sweep 6–30% = mechanism not threshold), earnings
    blackout, VIX de-risking all LOSE on the cone; only **SPY>200d** survived
    BackTrader. So the section **describes, never acts**.
  - 🐛 **pytest green ≠ the command works**: unit tests never touch stdout, so they
    missed a CLI that **crashed on every successful trade** (✅ glyph vs Windows
    cp1252 under a bare `python.exe`). The writes succeeded; only the print raised.
    Driving the real CLI caught it → ASCII `[OK]`/`[ERR]`.
  - 🐛 **`CREATE TABLE IF NOT EXISTS` silently skips an existing OLD-shape table** —
    the cash columns were a no-op until the (verified empty) `nav_history` was dropped.
  - ✅ Verified: 29 portfolio tests (2 mutations checked), suite **379 passed** (7
    pre-existing failures unchanged); slim rebuilt + parity checked **directly**;
    page driven end-to-end with **real scored tickers** (PSNL 0.855 / NVCT 0.818) and
    a real unscored holding (KO → "—"). Real book untouched: 0 rows.
- **2026-07-16 — AAII ingest LANDED; group 7 complete (4/4 rows live).** The Imperva
  block aged out; fetch clean on the dev box. `macro_data` **214,699 rows / 69 symbols**;
  slim rebuilt, parity verified **against `dashboard.duckdb` directly** (69/69, no loader).
  DQ audit macro_data section: **71 OK / 0 FAIL** (was 68 OK / 3 FAIL — the 3 AAII rows).
  Board renders all 4 flows rows, all |z|<1.5 (quiet, correct).
  - 🐛 **`update_series()` does NOT write the DB — it only writes the pickle cache.**
    The DB write lives in `update_macro_cache`, which calls `write_to_macro_data`
    separately. The previous handover's "re-run `MacroEngine().update_series('AAII_BULL')`
    to ingest" is **wrong**: it returns a populated 1,228-row frame and prints success
    while inserting **zero rows**. Correct one-off ingest:
    `df = e.update_series(sym); e.write_to_macro_data(sym, df)`.
  - Verified the col-0 trap did NOT bite: the 3 symbols hold **distinct** means
    (bull 37.51 / bear 33.57 / spread 3.95), spread ≡ bull−bear on **all 1,228 dates**
    (max err 0.0), zero bull+bear>100 violations.
  - Note: `macro_data.value` is **NULL for all 69 symbols** — the populated column is
    `close`. Pre-existing and audit-guarded; don't "fix" it by reading `value`.
- **2026-07-16 — S3 group 7 (Flows & Positioning): AAII + NAAIM ingest.** The last
  group with no source; board now **9 of 10 groups**. Scope confirmed with the user:
  AAII+NAAIM only, **COT deferred** (87-col file, one zip PER YEAR ≈ 20 fetches to
  backfill, plus a market-selection + net-position derivation — triples the work for a
  third sentiment read).
  - `config.SENTIMENT_SERIES` (NEW dict, 4 symbols) + `macro_engine.fetch_aaii_sentiment`
    / `fetch_naaim_exposure` + dispatch + an **isolated** nightly loop (per-symbol try,
    like the Yahoo loop — these parse third-party spreadsheets whose layout can change).
    Ingest free as predicted: `macro_data` is MANIFEST-`full` → **zero orchestrator/
    MANIFEST edits**.
  - **NAAIM: 1,045 weekly rows, 2006→2026-07-15, live in main + slim.** ✓
  - ⚠️ **AAII: fetcher verified against live data (1,228 rows, 2003+, bull+bear ≤100,
    spread ≡ bull−bear) but NOT yet ingested** — the IP tripped **Imperva bot defense**
    mid-session. Configured-but-empty → the 3 rows grey out; the nightly picks them up
    when the block ages out. No retry loop added (hammering hardens the block).
  - 🐛 **The exact trap this thread keeps hitting: AAII's block returns HTTP 200 with
    6KB of HTML** ("Pardon Our Interruption"). Status *and* a plausible length both look
    fine; `read_excel` then raises a **misleading** "format cannot be determined" that
    hides the cause. Guard = **magic bytes** (`D0CF11E0` .xls / `PK` .xlsx) *before*
    parsing, applied to NAAIM too (same exposure — its 404 serves 175KB of HTML).
    Reinforces **smoke-test the payload, not the status code**.
  - **NAAIM's export URL is date-stamped** (`USE_Data-since-Inception_2026-07-15.xlsx`)
    and rolls weekly → scraped off the page, never hardcoded (a pinned URL 404s within
    a week *into HTML that looks alive*).
  - **AAII sheet parsed by date-detection, not `header=3`** — a pinned header row
    silently shifts if AAII adds a banner. 3 junk rows above, commentary below.
  - `write_to_macro_data` takes **one symbol per call** (`value_col = df.columns[0]`),
    so the 3-column AAII frame is sliced per symbol at dispatch — passing it whole would
    have silently written `AAII_BULL`'s values under all three names.
  - Unit: `percent` → **absolute-change z** (AAII_SPREAD crosses zero; a pct z would
    explode like T10Y2Y's 22.6% σ). Not `revised` — a survey print is a point-in-time
    count, so INSERT-OR-IGNORE costs nothing. Display-only like the rest of S3.
  - ✅ Verified: parity checked by opening `dashboard.duckdb` **directly** (66/66
    symbols, no loader) after rebuilding **post-ingest**; NAAIM z=0.98 (quiet, correctly
    under the 1.5σ amber); `/` + `/Macro` 200 clean. **335 passed** (was 332; +3 new).
  - 🧪 The bot-block test was **mutation-checked**: the first version passed even with
    the guard deleted (read_excel raises → broad `except` → empty either way), so
    `.empty` proved nothing. Now asserts `read_excel` is **never called**; verified it
    fails with the guard removed and passes with it.
- **2026-07-16 — Data-quality audit: macro_data freshness 12 → 66 symbols.**
  Prompted by "update the DQ check with the new feeds"; the real finding was bigger than
  the two new feeds. `tools/audit_t1_data_quality.py` held a hardcoded
  `MACRO_DATA_EXPECTED` of **12 symbols while macro_data had grown to 66** — every one of
  the **54 series added by the S3 board over sessions 01–03 had NO freshness check**. A
  dead FRED/Yahoo feed would have gone unnoticed indefinitely (the board greys the row
  out and says nothing).
  - Fix = the same one the board already uses: **derive tolerance from each series'
    `freq`** (`MACRO_FRESHNESS_BY_FREQ`), so a newly-configured series is audited the
    moment it's added. `MACRO_DATA_EXPECTED` shrinks to genuine exceptions (VIX/CAPE/
    CAPE_OURS/FEAR_GREED + the dead `EXHOSLUSM495S`). New check: **unconfigured_symbols**
    (ingesting but in no config dict → never renders, nothing owns its freshness).
  - 📏 **Tolerances MEASURED, not guessed.** First cut (D5/W12/M70/Q190) fired **11
    false warnings** on healthy feeds. Cause: the inter-OBSERVATION gap is small (M=31d)
    but these series are **dated at PERIOD START and published weeks later**, so
    staleness must cover period + publication lag. Measured worst-case on a healthy feed
    over 2y: **D=6** (DEXJPUS/DTWEXBGS skip US holidays), **W=12** (CCSA), **M=106**
    (SPCS20RSA — Case-Shiller is a 2mo-lagged 3mo average), **Q=196** (DRCCLACBS).
    Shipped D10/W18/M125/Q230 = observed worst + headroom → **68 OK, 0 false warnings**.
    Same wallpaper lesson as the S3 banner: an alert that fires on a healthy day is noise.
    Test-guarded against re-tightening.
  - ✅ Result: macro_data section 12 → **72 checks**; the only FAILs are the **3 AAII
    rows** — i.e. the audit immediately caught the one thing genuinely broken. Other
    sections' 3 FAIL / 7 WARNING are pre-existing (price_data/t1_macro), untouched.
    Suite **337 passed** (+5 new).
- **2026-07-16 — Macro S3 round 3**: commodities + anomaly banner + typography.
  - **Commodities via YAHOO (`config.YAHOO_SERIES`, 16 syms)** — Geopolitics 1 → 16
    rows. Yahoo beat FRED on **every** one (smoke-tested first): all daily + deep to
    2003, including **cocoa**, which FRED has no clean series for and which has no US
    ETF. Yahoo's `CL=F` is fresher than FRED's `DCOILWTICO` (T+0 vs T+2) so it owns
    the WTI row; the FRED one stays as an ungrouped cross-check. New
    `macro_engine.fetch_yahoo_series` + dispatch (per-symbol try → one dead ticker
    can't fail the nightly macro phase). Uranium = URA ETF (2010+), no futures exist.
    `macro_data` 119,593 → **209,970 rows / 65 symbols**; slim rebuilt, parity
    verified **against the slim file directly** (57/57 board series present).
  - **Anomaly banner + Z column** — |z| of the latest CHANGE vs each series' own
    full-history change distribution.
  - 🛑 **The proposed 0.5σ/1.0σ thresholds were REJECTED on measurement.** Over the
    last 120 days: **0.5σ fires on a median 14 of 56 rows EVERY day, 1.0σ on 6**. A
    banner lit daily is wallpaper. This is arithmetic, not tuning — |z|≥1 covers ~32%
    of a normal distribution, so ~18 of 56 rows fire on an ordinary day. Shipped
    **1.5σ amber / 2.5σ red**: median day = 2 amber / 0 red, a real event still
    spikes to 14/5. Guarded by a test so it can't be quietly lowered.
  - 🐛 **Two statistical flaws found and fixed before shipping:**
    1. **Absolute change isn't stationary for a trending price.** Gold's full-history
       σ is $22.69, but it traded ~$350 in 2003 and ~$4,000 now — a routine 1% day
       scored ~1.8σ. Pct-change is scale-free and measurably stationary (gold σ
       1.146% full vs 1.154% since 2021). First cut fired **21 red / 31 amber of 56**.
    2. **But pct-change EXPLODES for a series crossing zero** — T10Y2Y scored a
       **22.6% σ**. So the unit is chosen per series: pct for prices/levels,
       absolute for spreads/rates (`config.S3_PCT_UNITS`, keyed off the existing
       `unit` field — no new flag). Post-fix: **1 red / 6 amber**.
    3. `latest_v` comes from the same SQL that builds mu/sd, so the change can never
       be measured in a different unit than the moments it's compared against.
  - ⚠️ Full-history moments = all-time = **look-ahead**. Board is display-only; the z
    must never reach a model. Stated in the loader docstring + the page footer.
  - **Typography** (user: "too pale... range col too small"): body/value text →
    `#1c1a17`, secondary → `#6f6858` (was `#c3bba6`, which was near-invisible); Range
    10px → 12px, matching Prior. Indicator name now left-aligned with the symbol +
    `rev` chip on a **second line** beneath it.
  - **History mark: bars → LINE + area** (user: prefers a spline for the level). The
    original failure was never the mark type but the resolution — 180 points in 64px
    = 0.4px/point. Now 90px wide, capped at ~1pt/1.5px. **Per-row histograms of daily
    %Δ were NOT built**: a histogram needs ~50+ points for a shape, but 22 of the 42
    FRED series are monthly/quarterly (6 points in a 180d window) — half the board
    would render noise. The z column answers the same "is today unusual?" question in
    one number. Suite **332 passed**.
- **2026-07-16 — Macro S3 board redesign** (user review: "too squeezed, the line chart
  is not very informative"). Compared against `macro_page_mock.html`:
  - **Layout**: `.ggrid` was `auto-fit minmax(380px)` → packed 2–3 groups per row; now
    **one group per row, full width** (`flex column`). Row padding 4px → **14px**.
    Group headers get a filled bar + `live/total indicators` count, like the mock.
  - **History: polyline → BARS** (`_sparkbars`, 24 buckets, downsampled by mean). At
    64×22px a 180-point line gives each point ~0.4px — sub-pixel noise, which is why
    it read as uninformative. Bars are quantized to what the eye can resolve; last
    bar = today at full opacity, the rest recede.
  - **Context columns added**: `Prior` + `Range` (window min–max) + `Np` point count,
    matching the mock's Prior/Now/Δ/History/Range shape. `_fmt` scales precision to
    magnitude (the board spans SOFR 4.3 → payrolls 158,984).
  - ⚠️ **The screenshot under review was the MOCK, not the built board** — its Risk
    Regime shows "10/10 indicators" but **8 of those 10 rows are `null` in the mock's
    own data** (VVIX/SKEW/DXY/Gold/USD-JPY/BTC/futures are C3 = paid/real-time,
    deferred). The real board shows the 2 that exist. Density in the mock is partly
    fabricated; **not** reproduced.
  - 🐛 **Correction to the entry below**: the earlier "remote parity holds ✓" check was
    **WRONG** — it read the MAIN db through the loader (`_connect()` fell back), so it
    reported 49 symbols/119,593 rows that were main's, not the slim DB's. The slim DB
    at that moment had only **12 symbols, no PAYEMS**. The tell was an identical row
    count between a full DB and a windowed slim one. Re-verified by opening
    `dashboard.duckdb` **directly**: now genuinely 49 symbols/119,593 rows, all 42 S3
    series present, loader confirmed reading `dashboard`. **Lesson: verify parity
    against the slim file itself, never through a loader that can silently fall back.**
  - `tests/test_macro_s3_board.py`: +downsampling test (180 pts → 24 bars), +`_fmt`
    magnitude test. Suite **326 passed**.
- **2026-07-16 — Macro S3 (indicator board) shipped** — the C1 FRED backlog landed.
  - `config.py` — `FRED_SERIES` extended 9 → **45** entries (36 new C1 IDs, all
    smoke-tested against the live FRED API before commit: **36/36 fetch clean**).
    Each S3 entry carries a `group` tag (drives the board) + `revised` flag.
    **Ingest was free exactly as predicted**: `update_macro_cache` iterates the
    dict and `macro_data` is MANIFEST-`full` → **zero** orchestrator/MANIFEST edits;
    nightly + remote parity followed with no wiring.
  - `macro_data`: 13 → **49 symbols / 119,593 rows**. Slim-DB rebuild verified all
    42 grouped series reach `dashboard.duckdb` (remote parity holds).
  - `scripts/dashboard_utils.py` — `load_macro_indicators()`: one SQL pass →
    latest/prior/Δ%/sparkline/n_obs per series, driven off the config metadata (no
    hardcoded ID list in the page). Δ is vs previous **observation** (w/w weekly,
    m/m monthly), not a fixed calendar lag.
  - `scripts/pages/2_Macro.py` — `_render_s3` + `_sparkline` (inline SVG) +
    `S3_GROUPS`; 8 of 10 groups render (42 rows). Groups 7 (flows) + 10 (calendar)
    have no C1 source → land with C2/C3. Configured-but-empty greys out; page never
    gates on completeness.
  - `tests/test_macro_s3_board.py` (NEW) — sparkline degenerate inputs (flat series
    div-by-zero, <2 points), config↔board group parity (a series can't ingest but
    silently never render), revised-flag coverage.
  - ⚠️ **Revision caveat (accepted, documented)**: 22 series are FRED-revised but
    `write_to_macro_data` is `INSERT OR IGNORE` → **first print wins, revisions
    dropped**. Fine for a display board; these are **display-only** and must not
    feed a model wanting point-in-time accuracy. Upgrade path = `INSERT OR REPLACE`
    (cf `cape_engine`) if a consumer ever needs it.
  - **Two series are shallower than the plan assumed** (caught by the smoke test):
    `BAMLC0A0CM` (IG OAS) returns only **785 rows from 2023-07** — not the deep
    2003+ series its HY sibling `BAMLH0A0HYM2` is (6,148 rows); it would fail M03's
    10yr-z bar like the sprint-13 `MOVE` rejection. `EXHOSLUSM495S` (existing home
    sales) is re-based/discontinued → **13 rows**. Both render as stubby
    sparklines; display-only, fine for the board.
  - 🐛 **Pre-existing bug fixed** (`dashboard_utils._ensure_local_db`): `Path.rename`
    raises `FileExistsError` on Windows when the target exists (POSIX rename
    overwrites) → **`os.replace`**. Was blocking pytest collection of
    `test_cohort_return_panel.py`. Present in committed `HEAD` (93497c9), not from
    this session. Suite: **315 passed** (7 known-broken modules still excluded).
  - ⚠️ **Deeper flaw left OPEN (needs the user's call)**: `_on_cloud()` infers "am I
    the cloud app?" from **R2 creds**, but the dev box's `.env` and the ops box both
    carry them → any dotenv-loading `import dashboard_utils` starts a ~751 MB R2
    download. A correct fix needs a positive cloud marker verifiable **on** Streamlit
    Cloud; guessing it here would silently stop the remote pull (stale DB — worse
    than the bug). Documented in the docstring, not patched blind.
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

## Switch-over checklist (2026-07-18 — the gap, measured)

Live `dashboard.py` = Today · Dataset EDA · Model Lab · Backtest Studio · Pipeline Health.
Shadow `dashboard_uplift.py` = Macro · Screening · Portfolio · Model Lab v2 · Backtest Studio v2.

**Blocking — the Today monolith has 13 sections; 5 migrated, 8 not:**

| Today section | → | Status |
|---|---|---|
| 6-Pillar Macro · Weather Gauge | Macro | ✅ |
| Daily Shortlist · Pre-Breakout · VIP | Screening | ✅ (one filterable population) |
| Screener Watchlist (held trades) | Portfolio | ❌ |
| Watchlist Activity | Portfolio | ❌ |
| Decision Log | Portfolio | ❌ |
| Performance of Past Decisions | Portfolio | ❌ |
| Daily Rank Bump | Model Lab | ❌ |
| Cohort-Return Tracker | Model Lab | ❌ |
| Analytics (diagnostics) | Model Lab | ❌ |
| Sector Heat | Macro | ❌ (S2 `sector_breadth` exists; "Sector Heat" as such doesn't) |

⚠️ **User (2026-07-18): most of these 8 are DUPLICATES of what the new pages already do** —
triage each as *duplicate → delete* vs *genuinely orphaned → rehouse*. **Don't rebuild by
default**; verify against the new home first.

### ✅ TRIAGE RESOLVED (2026-07-18 session 09) — decision only, nothing deleted

Verified each section against its claimed new home **and against the DB**, not against the
README's assumption. Two premises in the table above turned out to be **wrong**:

🛑 **"Screener Watchlist → Portfolio" was never a migration.** `screener_watchlist` (38,648
rows / 362 ACTIVE) is the **session store** of the algorithmic SEPA screener; `trades`
(**0 rows**) is the real discretionary book. Different populations, not two views of one.
Folding it into Portfolio would have mixed simulated sessions into a real NAV. It is also
not a third population — it is the display-enriched twin of `sepa_watchlist` (35,884), i.e.
the **session history of the Screening page's own population**. So it collapses into the
activity log rather than needing a home of its own.

🛑 **The 13-section count MISSED `render_vip_watchlist`.** A 9th orphan (`v_d3_vip` /
`vip_watchlist`) was on the live page and on no checklist.

**Naming (user, this session) — three distinct objects, use these names:**

| Name to use | Table / view | Rows | What it is |
|---|---|---|---|
| **sepa_active** | `v_d3_screening` (← `sepa_watchlist`) | 653 (584 setup / 69 triggered) | screener population — **already the Screening page** |
| **watchlist** | `vip_watchlist` / `v_d3_vip` | **0** | manual CLI adds ("VIP" is retired as a name) |
| **session activity log** | `screener_watchlist` | 38,648 (362 ACTIVE) | opened/closed sessions + exits ("Watchlist Activity" retired) |

**Verdicts — 4 INCLUDE, 4 OK to miss:**

| # | Live section | Verdict | Evidence |
|---|---|---|---|
| 1 | Screener Watchlist | **fold into #2** | same population, session view of it |
| 2 | Watchlist Activity | ✅ **INCLUDE** as **session activity log** | exits/adds have no equivalent on any new page |
| 3 | Decision Log | ⬜ OK to miss | **1** `decision_taken` in 302,220 `daily_predictions` rows; the `trades` CLI replaced it |
| 4 | Past-Decision Perf | ⬜ OK to miss | reads that same n=1 field — no population to measure |
| 5 | Daily Rank Bump | ✅ **INCLUDE** → Model Lab | shows rank **persistence** (pre_breakout names persist day-over-day, breakout names don't — `project_cohort_vs_model_scores`); a structural fact about the population, not a P&L claim |
| 6 | Cohort-Return Tracker | ⬜ **OK to miss** (2026-07-18) | its median-return band **contradicts the sprint's own conclusion**: `project_tail_magnitude_objective` says use tail-lift not medians, and `project_breakout_pool_refinement` measured IC ≈ **−0.03** within the pool. Model Lab v2 had to label its median "misleading" for the same reason. Dropped on methodology, NOT on the `screener_watchlist` argument (see note) |
| 7 | Analytics | ⬜ OK to miss | quadrants/sector bars over **session** data; Portfolio Risk covers the real book |
| 8 | Sector Heat | ⬜ OK to miss | Macro S2 `sector_breadth` is a strict **superset** (`n_trend_ok`/`n_breakout_ok` + breadth + `ret_hist`) |
| 9 | **watchlist** (was VIP) | ✅ **INCLUDE** | user: show **on the same page as sepa_active**, with the same key columns |

⚠️ **Nothing was deleted this session.** "OK to miss" = *agreed not to carry into the new
dashboard*; the live code is untouched and stays until the mechanical switch.

### ⏸️ DEFERRED (infra) — watchlist names are NOT guaranteed a score

> **User 2026-07-18: this is an infra job, deferred; the dashboard switch takes priority.**
> The watchlist table ships anyway, with an **honest empty state** on the score column
> (`—` + a caption naming the gate as the cause) rather than a hidden or zero-filled
> score. Revisit when the scoring population is widened.


User requirement (2026-07-18): *"we need to make sure this population make to scoring any
time, regardless if they pass sepa gate."* **This does not currently hold** — verified
against `v_d3_vip`'s definition, not assumed:

🔁 **CORRECTION (same session).** The first version of this note claimed watchlist names
might have **no features at all**. That was **WRONG** — derived from reading `v_d3_vip`'s
SELECT without checking what feeds T3 upstream. The real gap is one step later and much
smaller:

✅ **Features: already solved.** `src/feature_pipeline.py:637` UNIONs
`vip_watchlist WHERE active` into the T3 candidate set — *"manually-curated names forced
into T3 so the pipeline reports their daily status even if they never pass the screen"*.
So a watchlist name **does** get daily t3 features regardless of the gate. (Forward-only:
they appear in chunks run after the add, with the normal 200d warmup.)

❌ **Scoring: the actual gap, one join deep.** The nightly scorer reads `v_d3_lifecycle`
(`daily_pipeline_orchestrator.py:1952`). That view's `wl` CTE **INNER JOINs
`screener_watchlist`** — so a name with t3 features but no SEPA *session* matches no row,
lands in no cohort (`active`/`pre_breakout`/`removed`/`breakout`), and gets no
`daily_predictions` row. `v_d3_vip` then LEFT JOINs that absence → `prob_elite` NULL.

**Fix is one view, not an infra project**: `v_d3_lifecycle`'s INNER JOIN → LEFT JOIN with a
`watchlist`/`watching` cohort for the unmatched names. Everything downstream
(`backfill_daily_predictions.py --cohort lifecycle`, the scorer, `v_d3_vip`) already reads
that view, so no other wiring changes.

⚠️ Still **unmeasured** — `vip_watchlist` is empty, so no name exists to test against. Add
one, run a nightly, confirm it scores.
📌 Ships as-is meanwhile: `v_d3_vip` already renders `not_in_universe` / `'watching'` states
and the page captions the blank score honestly.

**Remaining build work (triage done — 3 sections to carry over):**
1. **Session activity log** (#2, absorbing #1) — exits / universe adds+removes.
2. **watchlist next to sepa_active** (#9) — same page, same key columns.
3. **Daily Rank Bump** (#5) → Model Lab v2 "Live Monitoring" tab.

📌 **`daily_predictions.cohort` is NOT a `screener_watchlist` reference.** Raised
2026-07-18: *"if we drop screener_watchlist from the pipeline, don't we lose the cohort
column?"* — **no.** `cohort` lives on `daily_predictions`; its values
(`active`/`pre_breakout`/`removed`/`breakout`) come from **`v_d3_lifecycle`**, i.e. which
funnel stage the name was in when scored. Neither rank-bump loader touches
`screener_watchlist`. Retiring that table later does **not** strand the cohort column or
the Rank Bump chart. (Two unrelated things called "cohort" — cf. the Track Record
"two things called scoring" trap.)

⚠️ **Rank Bump and Cohort-Return shared the `cohort` dependency** (both call
`load_rank_cohorts`), so dropping one did not decouple the other — Cohort-Return was
dropped on its own methodology grounds, above.

### ✅ SWITCH-OVER DONE (2026-07-18)

All mechanical steps executed:
- ✅ Shadow pages folded into `dashboard.py`'s `st.navigation`, now a **two-tier dict**
  (**Decide**: Macro · Screening · Session activity · Portfolio · Supply chain · Equity
  research — **Workshop**: Dataset EDA · Model Lab · Backtest Studio · Pipeline Health).
- ✅ v1 `3_Model_Lab.py` / `4_Backtest_Studio.py` **deleted**; the `_v2` files promoted to
  those names via `git mv` (history preserved). Their docstrings no longer claim to be
  shadow files.
- ✅ `dashboard_uplift.py` **deleted**.
- ✅ **No slim "Today" landing** — once Decision Log + Past-Decision Perf were dropped,
  the planned landing had nothing left to render but a title. **Macro is the default
  landing**: the deploy posture is what you want first in the morning.
- ⬜ **`page_today` + its ~950 lines of `render_*` helpers are RETAINED but UNROUTED** in
  `dashboard.py` — dead code kept one cycle so anything the triage missed is recoverable
  from HEAD rather than git history. **Follow-up: deletion pass.**
- ✅ Slim-DB MANIFEST parity re-verified by opening `data/dashboard.duckdb` **directly**
  (8/8 tables the new loaders read).
- ✅ **All 10 pages driven via `AppTest` against BOTH the full DB and the slim DB → 0
  exceptions each** (20 page-runs). The live entrypoint boots clean.
  ⚠️ Booting the app only renders the *default* page — every route was driven
  individually, because a broken non-default page is invisible to a boot check.

**Docs synced to the new structure**: `manual_for_me.md` (page map + file table),
`comprehensive_methodology.md` §Ops, `docs/modules/dashboard.md`, `data_flow_legend.md`.
📌 **MANIFEST parity for the carry-overs is already satisfied** (checked this session):
`screener_watchlist` `full` · `sepa_watchlist` `full` · `v_d3_vip` `materialize_view`
(flattened so the remote needs no runtime join to `vip_watchlist`). So #1 and #2 need
**zero new slim-DB wiring** — same free ride `cone_cells` got. Re-verify against the slim
file directly if a loader reaches for a *new* column (`project_dashboard_remote_parity`).

**New pages requested 2026-07-18:** Supply-chain (wire the mock in; hover→sub-sectors,
click→company network — placeholders) · **Equity Research** (`equity_research_page.md`,
reads `research_reports.raw_md` — placeholder).

### ⬜ Deployment — UNSCOPED, needed to actually close the migration
Nobody has scoped how the switched-over app **deploys**:
- **`sh019` (ops box)** — runs the Prefect server + nightly scheduler. How does the
  dashboard get served/restarted there? Is it a service, a scheduled task, manual?
- **Remote dashboard** — Streamlit Cloud reads the slim `dashboard.duckdb` from R2.
  Confirm every merged loader's table is in the MANIFEST, and re-check the
  `_on_cloud()` creds false-positive (`project_on_cloud_creds_false_positive`, still OPEN
  — R2 creds ≠ "am the cloud app", so a dotenv-loading import can start a 751 MB download).
- Decide whether the shadow app keeps existing during a transition or is deleted at cut-over.

## Open questions (user)

1. **tradingagent output** — what does it emit, can it write DuckDB or drop a file? (sizes the ingest side of the research layer)
2. **Supply-chain edges** — build (Tier-1 EDGAR extraction, multi-week) vs buy (Tier-2 vendor feed, paid)?
3. **Platform** — settle after the mocks give evidence.

## Files in this folder
- `README.md` — this meta plan.
- `style.md` — visual system.
- `macro_page.md` / `macro_page_mock.html` — Macro design + standalone mock.
- `screening_page.md` — Screening design.
- `portfolio_risk_section.md` — Portfolio Risk section: shipped metrics, why no VaR, and the falsified-lever list that binds it.
- `backtest_studio_page.md` — Backtest Studio revision (methodology adherence: cone + C3 currency).
- `cone_and_studio_design.md` — **the TWO cones** (label §5 fan vs strategy `cone_gate`), the
  `data → model/label → strategy` page spine, cell-level zoom, and the cache design
  (Track A = bounded dashboard summary; Track B = re-runnability, infra-only).
  **Built 2026-07-17/18** — §5b Q1 resolved: the label cone **reuses the `cone_cells`
  shape** with an `engine` tag, rather than rendering an unpersisted fan.
- `rename_sepa_watchlist_plan.md` — display-rename plan; **CLOSED no-action 2026-07-18**
  (the assumed user-facing label does not exist — see its "Scope" section).
- `supply_chain_page.md` — Supply-chain design + edge-sourcing tiers. **Step 1 done.**
  Now framed (user) as the **knowledge-base map**: `screening → shortlist → agentic
  markdown report → agentic digestion → knowledge base`; edges accrue as that pipeline
  runs, so the page ships framework-first and is **not** gated on edges.
- `equity_research_page.md` — read surface for single-name markdown reports
  (`research_reports.raw_md`). ✅ **Placeholder SHIPPED 2026-07-18**
  (`scripts/pages/7_Equity_Research.py`) — `research_reports` verified absent, page
  renders the empty state and needs no rewrite when the table lands.
- `supply_chain_mock.html` — Tier-0 chord mock (**generated** by
  `scripts/build_supply_chain_mock.py`; re-run to refresh, don't hand-edit). Real
  co-movement data, **zero supply-chain edges** — read the caveat on the page.
- `research_layer_contract.md` — tradingagent → repo boundary.
