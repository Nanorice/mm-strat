# Session Handover: 2026-07-17 (session 06)

> Sixth session on the dashboard-uplift thread, and the first dated 07-17 (sessions 01–05
> are all 07-16; session 05 ran past midnight but stayed dated 07-16 for thread
> continuity). This one: **NAV wired into the nightly**, **Track Record dropped**, and a
> **DQ section + serving-table audit** on Pipeline Health. Live `dashboard.py` still
> untouched. **Session 05 + 06 both COMMITTED** (`32b0812`, `f9ec382`).

## 🎯 Goal
Clear the three open items the last handover left: decide the `nav_history` nightly
wiring, resolve what Track Record should actually contain, and check Tier 1 for friction
with the live pipeline — specifically whether the DQ audit is comprehensive.

## ✅ Accomplished

### 1 · `nav_history` nightly → Phase 7.47 `portfolio_nav` (the top open item, closed)
- New phase (WARN, order 7.47) between `sector_breadth` (7.46) and `dashboard_db` (7.5)
  so the fresh row **ships in the slim DB**. Modelled exactly on 7.46.
- **Why it earns a slot despite writing one row/day**: a NAV series **cannot be honestly
  backfilled** — TWR needs the day's `net_flow` recorded *on the day*, so a missed run is
  a permanent hole. Cheap now, unrecoverable later.
- 🐛 `target_date` is a **`str`** in the orchestrator but `snapshot_nav` takes a **`date`**
  → explicit `strptime`, not a silent pass-through.
- Driven for real on a temp DB: **NAV 105,000 = cash 85k + positions 20k**, `net_flow`
  100k captured for TWR, **idempotent** (1 row after two runs).
- The existing `test_phase_registry.py` already covers it (it greps the orchestrator's
  real call sites). **Mutation-verified**: removing `portfolio_nav` from config fails it.

### 2 · Track Record DROPPED from Tier 1 (user's call, and the user found the flaw)
- The user's own read killed it: reports are **study material**, entries/exits are
  **discretionary**, so the only thing actually "projected" is the entry/exit decision —
  which **IS the `trades` log on Portfolio**. Scoring the *report* would measure a thing
  that never bound the decision. The tradingagent structured-block contract it was
  "blocked on" wouldn't have fixed the overlap; it was blocked on the wrong thing.
- ⚠️ **The plan doc contained a false claim** that this exposed: *"Brier/**cone** scoring
  already exists"* conflated the **start-date cone** (strategy evaluation across 90 start
  dates — a regime-ride tool) with **forecast scoring**. Two unrelated things both called
  "scoring"; the cone has **no role** on that page. Corrected in the tracker.

### 3 · DQ: the audit was NOT comprehensive — two real findings
- **The user's question ("is there a table already?") had a better answer than a new
  table.** Phase 8 already runs `tools/run_all_audits.py` nightly → writes
  `data/audit_reports/audit_report_YYYYMMDD.json` (**23 on disk, R2-synced**). The data
  was always there; nothing read it.
- 🐛 **The Pipeline Health "Audit History" chart has NEVER once shown real data.** It read
  `summary.pass_count` / `passed` / `warn_count` / `fail_count`; the real keys are
  `summary.total.{OK,WARNING,FAIL,INFO}`. **Three fallback spellings, each `.get(...,0)`**
  → a total miss rendered **three flat zero lines** instead of erroring, **hiding 6 real
  FAILs across 23 reports**. Present in committed `HEAD` (`641c2d1`), not from the uplift.
- **DQ section shipped** (`render_data_quality`): per-audit FAIL/WARN/OK breakdown +
  today's failing checks by name/detail + **`new_fails`** (regressions vs the previous
  run). All three keys were **already written nightly and simply never read** — no new
  table, no new phase. This is the user's "beyond pass or fail".
- **`tools/audit_serving_tables.py` (NEW)** — the real scope gap. The T1 script audits
  **T1**; `sector_breadth` / `weather_gauge` / `daily_predictions` / `nav_history` sit
  **below that line with no freshness check at all**, so a dead Phase 7.4/7.45/7.46 greys
  a panel out and **says nothing**. Registered in `run_all_audits.py` → the real nightly
  run now reports **Serving Tables: 0 FAIL / 0 WARN / 6 OK**.
  - Scope correction to the last handover's framing: the nightly runs **four** audits
    (T1, T2 membership, T2 screener, T3), not just T1 — coverage was wider than the T1
    script alone suggested, but the serving layer was genuinely uncovered.

## 📝 Files Changed
**Commit `32b0812`** (session 05's work — portfolio feature):
- `src/managers/portfolio_manager.py`, `scripts/portfolio.py`, `scripts/pages/4_Portfolio.py`,
  `tests/test_portfolio_manager.py` (NEW); `dashboard_utils.py` (+5 loaders),
  `build_dashboard_db.py` (MANIFEST +3), `dashboard_uplift.py` (nav mount), 2 docs.

**Commit `f9ec382`** (this session — pipeline/DQ):
- `src/orchestrators/phase_registry.py`: `Phase("portfolio_nav", ..., 7.47)`.
- `config.py`: `portfolio_nav` → `PipelineFailureMode.WARN`.
- `src/orchestrators/daily_pipeline_orchestrator.py`: call site + `_run_phase_7_47_portfolio_nav`.
- `tools/audit_serving_tables.py`: **NEW** — freshness + sanity for the 4 serving tables.
- `tools/run_all_audits.py`: registered "Serving Tables" (+ `serving` skip key).
- `tests/test_audit_serving_tables.py`: **NEW** — 7 tests, all mutation-verified.
- `scripts/pages/5_Pipeline_Health.py`: `render_data_quality` + `load_latest_audit`;
  **audit-history key bug fixed**.
- `docs/.../dashboard_uplift/README.md`: tracker (Track Record dropped, Portfolio nav
  caveat cleared, Pipeline Health row) + build-log entry.

## 🚧 Work in Progress (CRITICAL)
- **Nothing half-finished.** Both commits are clean; working tree holds only
  `model_cards/m01_binary_v1_drift.json` (untracked **on purpose**, predates this thread).
- **Nothing wired into live `dashboard.py` nav** — the shadow app still owns the uplift
  pages. The 3 redundant Today tables stay until the user calls the switch-over.
  ⚠️ Note **Pipeline Health is a Tier-2 page on LIVE `dashboard.py`**, not the shadow app
  — so this session's DQ section IS live. That's correct (Tier 2 = "grow, don't rebuild").
- `data/audit_reports/audit_report_20260717.json` was **regenerated** by the full audit
  run and now includes the Serving Tables section. Untracked data, left in place.
- Pre-existing, NOT from this session: **7 failed / 26 errors**
  (`test_phase1_backfill`, `test_feature_catalog`, + 4 collection-error modules).
- `_on_cloud()` creds false-positive still **OPEN** (carried from session 03).

## ⏭️ Next Steps
1. **Supply-chain** is the only Tier-1 page left (Track Record is dropped) — but its data
   gap is the **highest** (nodes yes, **zero edges**). It's a research thread, not a
   dashboard build. Confirm with the user whether Tier 1 is "done" and the uplift moves to
   the **switch-over** instead.
2. **Backtest Studio revision** (Tier 2, `backtest_studio_page.md`) — the tracker says it
   **contradicts the current methodology**: headlines the single Sharpe that G6 retired,
   no cone, no C3 currency label, no engine tag. Highest-value remaining doc-vs-code gap.
3. Optional Portfolio extras, all still unbuilt and scoped in `portfolio_risk_section.md`:
   **SPY-200d banner** (REUSE `weather_gauge`, don't recompute), score-decay column,
   benchmark-relative return.
4. Optional: surface `deactivate_tickers.py` in Pipeline Health (memory TODO); COT
   (deferred); `_on_cloud()` when there's cloud-container access.

## 💡 Context/Memory
- 🐛 **A panel that looks green is not evidence the panel works.** The audit-history chart
  read keys that never existed and rendered a clean zero-line chart for 23 reports —
  `.get(key, 0)` on three guessed spellings turned a total miss into "everything is fine".
  **The same class as this thread's other traps**: HTTP 200 + HTML (session 04),
  `update_series()` printing success while inserting zero rows (session 05), `grep -P`
  printing "none" without running. **A default is a silent failure mode.**
- 🐛 **Driving the CLI caught what pytest could not, for the 3rd time this thread**:
  `sector_breadth.as_of_date` is a **TIMESTAMP** while the other three are **DATE** →
  `TypeError: date - datetime`. Fixed with `CAST(MAX(col) AS DATE)`.
- 📏 **Tolerances MEASURED, not guessed** (session 04's lesson, applied): observed 2y
  worst-case gap = `weather_gauge` **6d**, `daily_predictions` **13d** (a one-off
  07-02→07-15, not a pattern), `sector_breadth` is a **single-date snapshot** (1 distinct
  `as_of_date`, replaced nightly). Shipped **10/20/5** = observed + headroom → **0 false
  warnings** on the live DB. An alert that fires on a healthy day is wallpaper.
- 🧪 **An all-OK audit proves nothing until you prove it can fail.** All 4 checks
  mutation-verified on a deliberately-broken DB (all 4 fire; none fire on the healthy one),
  and the tolerance test varies staleness **across the 20d boundary** — mutating the
  tolerance 20→60 **fails it**. Third mutation-check this thread.
- ⚠️ **"Boots 200" was NOT evidence.** The shadow app returned 200 while mounting only
  Macro/Screening/Portfolio — **Pipeline Health isn't on it**, so that check said nothing
  about the change. Re-verified with `streamlit.testing.v1.AppTest` on the real page:
  **0 exceptions**, section renders the **real 6 FAIL / 25 WARN / 224 OK / 35 INFO**.
- ⚠️ **Two different things are called "scoring"**: the **start-date cone** evaluates a
  *strategy* across 90 start dates (the edge is a regime ride); **Brier** scores a
  *forecast ledger*. The plan doc conflated them to justify Track Record's "low effort".
  Same class as the "6 pillars vs M03's 3" doc error ([[project_six_pillars_vs_m03]]) —
  **verify a plan's reuse claims against the code before building on them.**
- 💡 **The DQ answer was reuse, not construction.** `per_audit` / `results` / `new_fails`
  were all already in the nightly JSON and unread. The instinct to add a table would have
  duplicated a working pipeline.
- **A NAV snapshot's value is asymmetric in time**: worthless today (0 fills), and
  **unrecoverable** if skipped (TWR needs `net_flow` on the day). That asymmetry — not the
  row count — is what earns the nightly slot.
- Verified: **388 passed** (381 baseline + 7 new); 7 failed / 26 errors unchanged from
  baseline. Slim-DB parity checked by opening `dashboard.duckdb` **directly** (bare
  connect, no loader): all 6 tables present. **The DQ section reads JSON, not the slim DB
  → no MANIFEST entry needed.** Real book untouched: **0 rows** — every drive ran on temp
  DBs, since deleted (one was an 84GB copy of the bloated main DB; use a synthetic DB).
- **No RESEARCH_LOG entry** (4th session running): the ledger has **0** mentions of this
  thread — it's infra, not research questions. Consistent with sessions 04/05.
