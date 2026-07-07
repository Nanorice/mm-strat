# Handover — Consolidated TODOs (2026-06-16)

Single place to track what's left. Merges three sources:
1. **This session's** remaining work (dashboard charts done; diagram cleanup + infra view-removal pending).
2. **Plan file** `2026-06-14_dashboard_plan_g1_g4_today.md` — open items.
3. **`todo.md`** (sprint-12 active list) — still-open items.

Anything not listed here is either done (see commits / `DONE_*.md`) or explicitly deferred to Sprint 13.

---

## 0. State at handover

**Branch:** `infra_uplift`.

### Done in follow-up session (2026-06-16 cont.) — D1–D3, V1–V2, DB parity, F1
- `<uncommitted>` **F1 — t3 hole bug (v_d1_candidates trade-drop).** Handover's
  "entry-date divergence" was misdiagnosed — see §3 F1 for the full write-up. Root
  cause: lazy t3 is materialized forward-only from global MAX(date), so late
  `sepa_watchlist` admits leave permanent (ticker,date) holes behind the frontier;
  `v_d1_candidates`' entry-row INNER JOIN to t3 then silently deletes whole trades.
  Fix = self-healing Phase 5 hole-detector + INNER→LEFT guard on v_d1 +
  one-time 12-quarter backfill. Verified 0 holes 2001→2026; HPE 8→9 rows, parity
  with screener_watchlist. Touches `daily_pipeline_orchestrator.py`,
  `view_manager.py`, `tests/test_view_manager.py`. **Not yet committed.**

- `61a7d70` **D1+D2+D3** — page-5 Data Flow now renders **4 tabs** (Overview /
  Pipeline / Serving / **Full**=canonical `data_flow.mmd`) via reused
  `_render_mermaid_file`. The 3 drafts were already committed (`47b8085`), so D1
  was a no-op. **Root-caused the mermaid "Syntax error in text" bomb**: NOT a
  diagram-syntax issue (all 3 parse clean) — `st.tabs` hides inactive panels with
  `display:none`, collapsing the component iframe to 0 width, so mermaid's
  `startOnLoad` measured a 0-box and threw. Fixed by deferring `mermaid.render()`
  until the tab has width (ResizeObserver gate). Verified headlessly + in-browser.
- `b258aee` **V1+V2** — deleted `v_d1_trades` (0 consumers); retired
  `v_d2r_hydrated` alias. **Handover undercounted V2**: `v_d2_training` reads it
  *internally* (outcomes + sl_events CTEs) — repointed those to `v_d2_hydrated`,
  migrated `validate_stop_loss_logic.py` + `audit_fundamental_schema.py`.
  `create_all()` now `DROP VIEW IF EXISTS` both retired views (CREATE OR REPLACE
  never drops what it stops creating). V3 left to the daily pipeline (no manual run).
- `6d8a1fa` **Local/remote DB parity** (new ask) — `build_dashboard_db.py` is now
  **fail-fast**: removed the per-table `except duckdb.Error` that silently dropped
  a table from remote, added a post-build invariant asserting every MANIFEST
  object exists. Audit confirmed the dashboard reads only manifest tables (none of
  the 18 full-only objects) → no manifest additions needed. New comparison doc
  `docs/architecture/local_vs_remote_db.md`. Contract: **remote ≡ local slim
  byte-for-byte; no bespoke remote content; row-windowing OK, silent drops throw.**

### Earlier this session
- `e8c0999` watchlist M01 score backfill across d3 window (Today #2)
- `bd16ae1` macro/5F history charts + G4 Finviz links (Today #1 + G4)
- `83dea91` data_flow.mmd reconciled with real orchestrator phases (G1)

The 3 drill-down `.mmd` drafts (`data_flow_overview/pipeline/serving.mmd`) are
committed and wired. Decision standing: keep layout **auto-rendered** — do NOT
re-introduce invisible-edge / anchor-node ordering hacks (see memory
`feedback_mermaid_dont_fight_layout`).

**`tests/test_view_manager.py` — FIXED (`d2aae99`).** Was red since before Phase
5.1 (never validated the current view). Rewrote the fixture to seed the real
sources (`t2_screener_features` + `t3_sepa_features`), recomputed every
expectation from the live SQL, and fixed the static-call connection leaks. 13/13.

**Still-red test modules (pre-existing, NOT mine, out of scope):**
`test_feature_pipeline`, `test_phase1_backfill` (7 failed + 26 errors), and 4
import-error collections (`test_metrics`, `test_rehydration`,
`test_feature_preprocessor`, `test_m01_evaluator`) referencing deleted modules
(`src.features`, `src.evaluation.metrics`). Candidate for a separate test-rot sweep.

---

## 1. This session — immediate follow-ups (diagrams) ✅ DONE (`61a7d70`)

- [x] **D1 — Commit the three draft `.mmd` files** — already committed in `47b8085`.
- [x] **D2 — Wire page 5 to render the new diagrams.** Shipped as **tabs**
  (Overview / Pipeline / Serving / Full) per updated UX, not inline+expander.
  Reused `_render_mermaid_file` helper.
- [x] **D3 — Visually verify** — confirmed in-browser. Fixed the hidden-tab mermaid
  bomb (see §0). render() errors now surface as real mermaid text, not the generic bomb.

---

## 2. INFRA — View-layer cleanup ✅ V1+V2 DONE (`b258aee`)

Came out of the data-flow review. **Premise correction kept on record:** cross-phase
reads of a base table (e.g. `price_data` → phases 2/3/5/6/app) are *normalization,
not waste* — do NOT denormalize to reduce diagram edges. The only real cruft is
**redundant views**. Usage heatmap (prod consumer files, tests/defs excluded):

| View | Consumers | Action |
|------|-----------|--------|
| `v_d2_training` | 16 | keep (training SoT) |
| `v_d3_deployment` | 7 | keep (scoring) |
| `v_d1_candidates` | 5 | keep |
| `v_d2_features` | 5 | keep |
| `v_d3_prebreakout` | 4 | keep (new cohort) |
| `v_sepa_candidates` | 2 | keep |
| `v_d2_hydrated` | 1 | keep (feeds v_d2_training) |
| `v_screener_dashboard` | 1 | keep (materializes screener_watchlist) |
| `v_price_combined` | internal | keep (Phase 6 abstraction) |
| `v_shares_combined` | internal | keep (Phase 6 abstraction) |
| **`v_d1_trades`** | **0** | 🔴 **DELETE** — pure alias of `v_d1_candidates`, zero consumers (`view_manager.py:645`) |
| **`v_d2r_hydrated`** | 2 (alias) | 🟡 **RETIRE** — back-compat alias of `v_d2_hydrated` (`view_manager.py:556`) |

- [x] **V1 — Delete `v_d1_trades`.** Done — method + registration removed.
- [x] **V2 — Retire `v_d2r_hydrated` alias.** Done. **Correction:** it was NOT just
  2 straggler scripts — `v_d2_training` consumed it internally; repointed those to
  `v_d2_hydrated` too. Migrated both scripts. `create_all()` now drops both retired
  views explicitly.
- [x] **V3 — Re-run `ViewManager.create_all()`** — deferred to the daily pipeline
  (user: no manual run). Until it next runs, the old views still physically exist
  in the live DB but are dead (no longer recreated).
- ⚠️ The `view_manager.py:645` / `:556` line refs in the table above are now stale
  (lines shifted after deletion).

### Phase numbering gap — Phase 9 is missing (orchestrator jumps 8 → 10)

`daily_pipeline_orchestrator.py` runs Phase 8 (monitoring) then **Phase 10**
(advisory model card) — **there is no Phase 9.** Monitoring was "Phase 9" in the
old 9-phase layout and was renumbered to 8 when serving phases 7.4–7.6 were
inserted; the model card kept its "10" label. Documented in diagrams + memory
`project_orchestrator_phase_list`. This is a naming smell, not a missing step.

- [x] **PN1 — Decided: keep Phase 10 as-is.** The gap is cosmetic (idempotency is
  already skipped for it). Renumbering piecemeal is the exact pain the positional
  scheme causes, so we don't. Documented the gap with a code comment at the call site.
- [x] **PN2 — IMPLEMENTED (registry-only).** The stable-id phase registry from
  `pipeline_phase_keys.md` now exists: `src/orchestrators/phase_registry.py`
  (`Phase(id, label, order)` + `PHASES` + `failure_mode_for/label_for/order_for`).
  Stable ids (`ingestion`, `t2_screener`, `scoring`, `model_card`, …) decoupled
  from order — a mid-pipeline insert never renumbers / strands `pipeline_runs`.
  Orchestrator's 13 `_execute_phase` calls + `record_write` tags repointed to
  stable ids; label now from `label_for()`. Heatmap `_phase_sort_key` uses
  registry order with a regex fallback for old keys. New `tests/test_phase_registry.py`
  (6 guardrails). Doc marked IMPLEMENTED.
- [x] **Config drift FIXED (as a side effect).** `config.PIPELINE_FAILURE_MODES`
  is now keyed by stable id; the stale `phase_6_t3_lazy`/`phase_7_views`/
  `phase_8_cache` entries are gone. **Source-of-truth split (deliberate, to keep
  config low-level + avoid a cycle):** failure mode lives in config, label/order
  in the registry (which imports config; config does NOT import the registry).
- [x] **Part (b) DONE (same session) — failure_mode is now the live control
  surface.** Was behavior-PRESERVING: registry modes were set from observed
  call-site behavior + `_execute_phase` already returns False only for HALT, so
  this was consolidation not a semantics change. New `_is_critical(id)` helper;
  every `_execute_phase` call followed by a uniform
  `if not phase_success and self._is_critical("<id>"): return False`; the 5 critical
  blocks + vestigial `phase_1_t1_price` lookup + 8 "non-critical" comments all
  collapsed into it. Guardrails added (incl. end-to-end HALT-aborts/WARN-continues).
- ⚠️ **Heatmap seam accepted (your scope choice):** no `pipeline_runs` migration.
  Old `phase_N_*` rows age out of the 30d window; `_phase_sort_key` interleaves
  both generations meanwhile. Sub-phase keys (`phase_1_t1_*`, gate keys) unchanged.
- Commits: `<this session>` (registry + config + orchestrator + heatmap + test).

---

## 2b. Local ↔ Remote DB parity ✅ DONE (`6d8a1fa`)

New ask this session: eliminate any layout/content divergence between local and
remote so there's no bespoke remote content (→ simpler sync + future dev).

**Finding:** remote is not a separate build — `sync_dashboard_db.py` uploads the
slim `dashboard.duckdb` **verbatim**, so remote ≡ local slim byte-for-byte. Zero
bespoke remote content already; all 22 shared tables have identical schema. The 3
big tables are windowed to 252d (~4.5% of rows) — kept (that's the slim DB's point;
layout parity, not full-content parity). 18 full-only objects exist but the
dashboard reads none of them → nothing to add.

**Done:** `build_dashboard_db.py` is fail-fast (removed the silent per-table
`except duckdb.Error`; added a post-build invariant that every MANIFEST object
exists). New `docs/architecture/local_vs_remote_db.md` (topology + row-count table
+ regen query). Memory `project_dashboard_remote_parity` updated.

**Contract going forward:** a new dashboard page that reads a full-only object will
work locally and **throw** on remote by design — add it to the MANIFEST + rebuild,
never special-case the remote.

---

## 3. From the dashboard plan file (`2026-06-14_dashboard_plan_g1_g4_today.md`)

Status of that plan's items after this session:

- [x] Design sign-off (RAW-softprob scores contract) — signed 2026-06-14
- [x] Shared scorer extraction (`src/evaluation/score_engine.py`) — `e8c0999`
- [x] Today #2 watchlist score backfill (`scripts/backfill_daily_predictions.py`) — `e8c0999`
- [x] Today #1 macro/5F history charts — `bd16ae1`
- [x] G3 price_data in slim DB MANIFEST
- [x] G4 T1-failures Finviz links — `bd16ae1`
- [x] G1 data_flow.mmd reconcile — `83dea91` (+ overview/pipeline/serving drafts, see §1)

**Still open from that plan (deferred follow-ups, were out of dashboard-sprint scope):**
- [x] **F1 — Watchlist ↔ deployment entry-date divergence. ✅ DONE (root cause was
  MISDIAGNOSED).** The two views do NOT disagree on entry-date *logic* — their
  session-detection CTEs are byte-identical, HPE sessions 1-8 match exactly. The
  "2026-05-13 vs 2024-09-25" was comparing the watchlist's newest (ACTIVE) entry
  against v_d1's most recent *surviving* (EXITED) entry. **Real bug:** `v_d1_candidates`
  INNER-JOINs the entry-date row to `t3_sepa_features` (lazily materialized). T3's
  true universe is `sepa_watchlist ∩ t2_screener_features`, evaluated forward-only
  from global `MAX(date)`; tickers admitted to sepa_watchlist over time never get
  their earlier in-window history backfilled → permanent (ticker,date) holes →
  INNER JOIN silently DELETES whole trades (and their M01 score). Quantified: 6,691
  holes / 661 dates, 2023-09→2026-05. **Fix (3 parts):** (1) Phase 5's single-day,
  breakout-only coverage check replaced with `_t3_holed_dates` (trailing 30d scan,
  `sepa_watchlist ∩ t2` expected set — mirrors t3's real source) + `_recompute_t3_dates`
  (DELETE+recompute span) → self-heals nightly. (2) `v_d1_candidates` entry-row join
  INNER→LEFT (`f.* EXCLUDE (ticker,date)`, identity from `cand`): a missing t3 row
  now yields a visible trade with NULL features instead of vanishing — defense in
  depth. (3) One-time backfill of 2023-Q3→2026-Q2 (12 quarters, 8 min via
  `backfill_t3_sepa_features.py`). **Verified:** 0 holes across 2001→2026; HPE now 9
  rows in BOTH views (was 8 in v_d1), 2026-05-13 present with real `rsi_14=28.21`.
  New regression test `test_missing_t3_row_keeps_trade_with_null_features`.
- [x] **F2 — Watchlist activity / exit tracking (feature). ✅ DONE.** New
  **Watchlist Activity** section on the Today page (3 tabs: Recent exits /
  Activity feed / Ticker history) + a 7/14/30-day window. 3 cached loaders in
  `dashboard_utils.py` (`load_recent_exits`, `load_ticker_history`,
  `load_activity_feed`); `load_activity_feed` UNIONs `screener_watchlist` EXITED
  rows (`TRADE_EXIT`) with `screener_membership` is_active flips
  (`UNIVERSE_ADD`/`UNIVERSE_REMOVE`) into one timeline. All 3 tables already in the
  slim-DB MANIFEST → no build/parity change; verified identical vs live + slim DB.
  **The "data-integrity nit" was NOT a bug:** an ACTIVE row's `exit_date` =
  latest `price_date` (prospective trend-break boundary, view_manager.py:876), not
  a realized exit — it advances daily while the trend holds. Fixed in the *display*
  layer (blank exit_date for ACTIVE rows) in the ticker-history drill-down +
  `render_past_decisions`; no backfill. **Deferred:** watchlist *entry* events in
  the feed (only exits + universe flips for now).

**Minor caption nit (optional):** G4 chronic-offender warning fires at ≥10d but
caption text says ≥14d. Align one to the other (`5_Pipeline_Health.py`).

---

## 4. From `todo.md` (sprint-12 active list) — still open

### P1 — T1 Dashboard Sync — RECONCILED against git (2026-06-16)
- [x] **S1** GitHub push — landed (`0da7f13`). **Reconcile found a real gap:** a stray
  274 KB `market_data.duckdb` stub was tracked at repo root (the plan's "no DB ever
  committed" decision was WRONG — `.gitignore` only had `data/`). Fixed in `9d762f3`:
  untracked + added `*.duckdb`. Model-artifact policy resolved (model.json filtered from sync).
- [x] **S2** R2 sync script + orchestrator Phase 7.6 — landed (`c783641`).
- [x] **S3** Streamlit Cloud shim + secrets bridge + duckdb req + localhost-header
  revisit — landed (`a4b2a0e`/`d5f3d12`/`02ae9cd`/`d84d467`). **Reconcile fix (`9d762f3`):**
  dashboard.py header named the wrong R2 secret var names → corrected.
- [ ] **S4** Task Scheduler runbook — **OPEN, no runbook exists.** **DECIDED 2026-06-16:
  builder = current dev box** (67 GB DB + .env already local; no migration, no spare-PC
  wake-on-LAN needed). Remaining: write the Task Scheduler entry (schtasks/XML) for
  nightly `run_daily_pipeline.py` (ends with Phase 7.5 build + 7.6 upload) + an
  end-to-end verify (pipeline → slim rebuild → R2 upload → remote shows fresh data) +
  failure alerting. Deferred to next session.
- [ ] Daily: "try dashboard remote" + "figure out data sync" — folds into S4 verify.

### Fixes
- [ ] the activity section in dashboard, when selecting between windowed history and ticker history, the page flickers, and sometimes have to select the ticker history twice
- [ ] would be good to have also the score for the ticker in ticker history table, using prod model, for the day signal is generated
- [ ] watchlist table: (a) still some tickers with no score, we dealt with these before can you remind me why we left as is? (b) I noticed the LPTH score is constant at 0.7 recently, do we not update the scores every day?


### P1 — T4 Documentation (do after infra settles)
- [ ] Model-dev lifecycle section in `docs/comprehensive_methodology.md`
- [ ] Refresh `comprehensive_methodology.md` stale sections + timestamp
- [ ] Runbooks into `docs/manual_for_me.md` (ticker deactivation, macro gap repair, view recreation, filing-date backfill)
- [ ] Delete `lifecycle_manual.md` once merged

### P2 — High value, not blocking
- [ ] **T5** Universe lifecycle automation (outflow): auto-detect ≥14d NO_DATA +
  `last_px>30d` → yfinance-confirm → auto-deactivate, ≤50/day cap, dry-run default,
  wire into orchestrator. (Overlaps the G4 deactivation workflow surfaced this sprint.)
- [ ] **T6** Mode B score-trajectory analysis (daily_predictions vs fwd returns 5/20/60d)
- [ ] **T7** Feature drift / PSI quarterly report + wire path into Pipeline Health

### P3 — Deferred
- [ ] Eval framework Phase 4 (scope TBD)
- [ ] 5-factor risk model improvements
- [ ] `earnings_calendar` at-scale rate-limit
- [ ] Audit script timeout `tools/run_all_audits.py:51` 120s→600s (trivial)
- [ ] `trend_c8` CTE rename → `trend_exit`
- [ ] Cross-sectional casing in `COLUMN_CASE_MAP` (`rs_sector_rank` etc.)

---

## 5. Suggested next-session order

**Closed this session:** D1–D3 (diagrams), V1–V2 (view cleanup), 2b (DB parity),
PN1/PN2 (decided keep-10 + wrote phase-registry proposal), test_view_manager fix,
**phase-key registry (registry-only) + config-drift fix**, **F1 (t3 hole bug —
self-heal + LEFT-JOIN guard + 12-quarter backfill; uncommitted).**

**Loose end on F1:** the new Phase 5 self-heal was exercised via the methods
directly, not through a full orchestrator run. Next nightly run will exercise it;
optionally dry-run Phase 5 against today to confirm it reports "0 holes" before
relying on it. F1 changes are **unstaged** — commit when ready.

Remaining, in priority:
1. ✅ **DONE — Phase-key convention change (FULL: registry + part b).** Stable-id
   registry; config drift fixed; `failure_mode` is the live control surface;
   heatmap + guardrail tests wired. See §2 PN2. **Only optional follow-up left:**
   the `pipeline_runs.phase_name` old→new id migration if the 30d heatmap seam is
   undesirable (otherwise it self-heals). Spec'd in `pipeline_phase_keys.md`.
2. **S4 - defer to late sprint or next sprint** spare-PC Task Scheduler runbook — the only open sync item (S1–S3 verified
   done this session; S1/S3 reconcile gaps fixed in `9d762f3`). Blocked on your
   hardware choices (builder PC, wake mechanism); ask me to scaffold the runbook.
3. ✅ **DONE — F2** (watchlist activity / exit feed + per-ticker history +
   ACTIVE-row exit_date display fix). See §3.
4. **T4 docs** once infra settles.
5. (Optional) test-rot sweep — fix the pre-existing red modules listed in §0.
