# Handover — Consolidated TODOs (2026-06-16)

Single place to track what's left. Merges three sources:
1. **This session's** remaining work (dashboard charts done; diagram cleanup + infra view-removal pending).
2. **Plan file** `2026-06-14_dashboard_plan_g1_g4_today.md` — open items.
3. **`todo.md`** (sprint-12 active list) — still-open items.

Anything not listed here is either done (see commits / `DONE_*.md`) or explicitly deferred to Sprint 13.

---

## 0. State at handover

**Branch:** `infra_uplift`. **Committed this session:**
- `e8c0999` watchlist M01 score backfill across d3 window (Today #2)
- `bd16ae1` macro/5F history charts + G4 Finviz links (Today #1 + G4)
- `83dea91` data_flow.mmd reconciled with real orchestrator phases (G1)

**Uncommitted working-tree drafts (this session, NOT wired in):**
- `docs/architecture/data_flow_overview.mmd` — schematic, all key stages
- `docs/architecture/data_flow_pipeline.mmd` — data side (sources → ingestion → features → views → cache)
- `docs/architecture/data_flow_serving.mmd` — scoring → serving → models → apps

All three parse/render clean under mermaid@10. Decision standing: keep layout
**auto-rendered** — do NOT re-introduce invisible-edge / anchor-node ordering
hacks (see memory `feedback_mermaid_dont_fight_layout`).

---

## 1. This session — immediate follow-ups (diagrams)

- [ ] **D1 — Commit the three draft `.mmd` files** as docs (currently untracked).
- [ ] **D2 — Wire page 5 to render the new diagrams.** `render_data_flow_diagram()`
  in `scripts/pages/5_Pipeline_Health.py`. Agreed UX: **overview + pipeline +
  serving inline; canonical `data_flow.mmd` in a collapsed expander.** ~15 LOC,
  one render helper reused 4×. (Only code touch in the diagram workstream.)
- [ ] **D3 — Visually verify rendered layout on page 5** before considering done.
  Parse-valid ≠ de-crossed; eyeball it (`streamlit run scripts/dashboard.py` →
  Pipeline Health). Sources sub-phase L-R order is whatever auto-layout picks (accepted).

---

## 2. INFRA — View-layer cleanup (the "remove some views" work)

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

- [ ] **V1 — Delete `v_d1_trades`.** Remove `_create_v_d1_trades` + its registration
  in `create_all()`. Zero consumers → safe.
- [ ] **V2 — Retire `v_d2r_hydrated` alias.** First migrate 2 stragglers
  (`scripts/audit_fundamental_schema.py`, `scripts/validate_stop_loss_logic.py`)
  to `v_d2_hydrated`, then drop the alias line.
- [ ] **V3 — Re-run `ViewManager.create_all()`** after V1/V2 so the DB reflects the change.
- Effort: ~30 min, isolated to `view_manager.py` + 2 scripts. **Held pending explicit go** (user paused infra changes this session).

**Related naming smell (found, not a view):** orchestrator phases jump **8 → 10,
no Phase 9** (monitoring was Phase 9 in the old layout, renumbered to 8 when
serving phases 7.4–7.6 were inserted; model card kept "10"). Documented in
diagrams + memory `project_orchestrator_phase_list`. Optional renumber later.

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
1. **D1–D3** — commit + wire + visually verify the diagrams (closes the workstream we were mid-flight on).
2. **V1–V3** — view-layer cleanup (quick, isolated; needs your go).
3. Reconcile **todo.md S1–S4** against git (some already landed) and finish remote-dashboard verify.
4. **F2** (watchlist exit panel) — high user value, data already exists.
5. **T4 docs** once infra above settles.
