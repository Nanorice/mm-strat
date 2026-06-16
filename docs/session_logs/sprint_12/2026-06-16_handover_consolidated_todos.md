# Handover — Consolidated TODOs (2026-06-16)

Single place to track what's left. Merges three sources:
1. **This session's** remaining work (dashboard charts done; diagram cleanup + infra view-removal pending).
2. **Plan file** `2026-06-14_dashboard_plan_g1_g4_today.md` — open items.
3. **`todo.md`** (sprint-12 active list) — still-open items.

Anything not listed here is either done (see commits / `DONE_*.md`) or explicitly deferred to Sprint 13.

---

## 0. State at handover

**Branch:** `infra_uplift`.

### Done in follow-up session (2026-06-16 cont.) — D1–D3, V1–V2, DB parity
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

**Known pre-existing breakage (not from this session):** `tests/test_view_manager.py`
— 13 failures on plain HEAD; calls now-instance `_create_*` methods statically
(+ a temp-file lock). Out of scope here; flag for a test-harness fix.

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
- [x] **PN2 — Superseded by a redesign proposal.** Investigating the rename surfaced
  the root cause: phase keys are **positional + persisted**, scattered across
  orchestrator/config/`pipeline_runs`/heatmap. Wrote
  `docs/session_logs/sprint_12/pipeline_phase_keys.md` proposing a **stable-id phase registry**
  (single source of truth; id ≠ order ≠ label).
- 🔴 **NEW FINDING (flagged, NOT fixed): `config.py PIPELINE_FAILURE_MODES` has
  drifted from the real phase keys** — 9 orchestrator phases have no config entry,
  and the map is largely **dead** because halt/continue is hardcoded per call site.
  Editing a value there may do nothing. Fixing it changes prod HALT/WARN behavior →
  **needs your review first** (you chose doc-only this session). Spec in the doc.
- Commits: `<this session>` (doc + comments only, no behavior change).

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
- [ ] **F1 — Watchlist ↔ deployment entry-date divergence (data integrity).**
  `screener_watchlist` entry_date vs `v_d1_candidates` SEPA session-entry disagree
  (e.g. HPE 2026-05-13 vs 2024-09-25). A watchlist row's entry_date often has no
  matching scored deployment row → legitimately blank M01 score. Decide which
  "entry" is canonical and reconcile.
- [ ] **F2 — Watchlist activity / exit tracking (feature).** No UI shows when a name
  leaves the watchlist (e.g. LITE +777% EXITED, AAOI gone). Data exists in
  `screener_watchlist` (exit rows) + `screener_membership` (is_active flips). Build
  a "Recent exits / activity" panel + per-ticker history drill-down. **Data-integrity
  nit to resolve while here:** AAOI status=ACTIVE yet has exit_date=2026-06-12 — contradictory.

**Minor caption nit (optional):** G4 chronic-offender warning fires at ≥10d but
caption text says ≥14d. Align one to the other (`5_Pipeline_Health.py`).

---

## 4. From `todo.md` (sprint-12 active list) — still open

### P1 — T1 Dashboard Sync (mostly done; sync sub-phases remain)
Note: S2/S3 appear **already landed** in git history (`c783641` R2 sync + Phase 7.6,
`a4b2a0e` pull-on-boot shim, `02ae9cd` R2 download). Verify against todo.md and
tick off; the list below is what todo.md still shows open:
- [ ] **S1** GitHub push (code only; `.env.example`; model-artifact policy) — likely partly done (`0da7f13`)
- [ ] **S4** spare-PC Task Scheduler runbook (wake-on-LAN, end-to-end verify)
- [ ] Daily: "try dashboard remote" + "figure out data sync" — overlaps S3/S4

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
PN1/PN2 (decided keep-10 + wrote phase-registry proposal).

Remaining, in priority:
1. **Phase-failure-mode drift fix** (needs your go — changes prod HALT/WARN) OR the
   full phase-registry refactor. Spec: `docs/session_logs/sprint_12/pipeline_phase_keys.md`.
2. **Test-harness fix** — `tests/test_view_manager.py` is broken on HEAD (static
   calls to instance `_create_*` methods). Quick win; restores view-layer test cover.
3. Reconcile **todo.md S1–S4** against git (S2/S3 likely already landed) and finish
   remote-dashboard verify.
4. **F2** (watchlist exit panel) — high user value, data already exists.
5. **T4 docs** once infra settles.
