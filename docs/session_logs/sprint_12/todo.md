# Sprint 12 — Active To-Do

> Update this file at the start/end of each session. Move completed items to a `DONE_*.md` file.
>
> **📌 Consolidated handover (2026-06-16):** see
> [2026-06-16_handover_consolidated_todos.md](2026-06-16_handover_consolidated_todos.md)
> — merges this file + the dashboard plan file + this session's diagram/view-cleanup
> work into one tracker. Start there.

---

## NEW (2026-06-16 session) — see consolidated handover for detail

### Data-flow diagrams (drafts uncommitted)
- [ ] Commit `data_flow_{overview,pipeline,serving}.mmd`
- [ ] Wire page 5 render: overview+pipeline+serving inline, full canonical in expander
- [ ] Visually verify rendered layout on page 5

### INFRA — view-layer cleanup (held pending go)
- [ ] Delete dead view `v_d1_trades` (0 consumers, alias of v_d1_candidates)
- [ ] Retire `v_d2r_hydrated` alias — migrate 2 scripts to `v_d2_hydrated`, drop alias
- [ ] Re-run `ViewManager.create_all()` after the above
- [ ] (optional) Phase numbering smell: orchestrator jumps 8→10, no Phase 9

---

## In Progress

### T1 — Slim Dashboard DB (mostly done, 2026-06-11)
- ✅ Manifest finalised via full audit of all 5 pages (only page 1 + page 5 touch the DB; pages EDA/Model Lab/Backtest Studio read filesystem only)
- ✅ `scripts/build_dashboard_db.py` written — ATTACH+CTAS, idempotent, `--window-days` param. Modes: full/window/window_plus_active/materialize_view
- ✅ Slim DB built: **783 MB** from 67 GB (98.8% reduction), 1.83M rows. t2/t3 sliced 252d window; v_d3_deployment materialized
- ✅ `DASHBOARD_DB_PATH` env var added to dashboard_utils.py (default = full local DB)
- ✅ Verified: all 18 loaders return valid current rows off slim DB; Streamlit boots clean (HTTP 200)
- ✅ Phase 7.5 nightly rebuild hook added to orchestrator (best-effort subprocess, never halts daily run)
- ✅ Deleted 66 GB stale backup (`bak_0531_t1macro`) after rigorous real-COUNT subset proof
- ⬜ Sync mechanism (Google Drive / Dropbox / object storage) — DEFERRED, "ship local first"
- 📌 **Discovered:** 67 GB main DB is ~95% dead/unvacuumed rows (t2 has 173M dead). Noted, not actioned this sprint. See memory `project_duckdb_dead_row_bloat`.

---

## P1 — Core This Sprint

### T1: Slim Dashboard DB + Cross-Device Sync

Goal: carve out a `dashboard.duckdb` from the 72 GB main DB containing only what the dashboard needs (<2 GB target), parameterise the app's DB path, and sync it across devices.

- [x] Finalise table manifest — done. Audited all pages: t2/t3 only read at MAX-date (+60d trend/20d sector). No page needs full 183M (real count is 9.8M anyway). price_data not read at all.
- [x] Write `scripts/build_dashboard_db.py` — ATTACH+CTAS, idempotent, `--window-days` param.
- [x] Parameterise app DB path via `DASHBOARD_DB_PATH` env var (default: full local DB).
- [x] Verify all 5 dashboard pages load from slim DB — 18/18 loaders OK; Streamlit boots clean.
- [~] Set up sync mechanism — **PLANNED** (not built). See [dashboard_sync_deploy_plan.md](dashboard_sync_deploy_plan.md). Decisions locked: existing repo (Nanorice/mm-strat, verified no DB ever committed), Cloudflare R2, Streamlit Community Cloud, spare-PC nightly job. Phases S1-S4 below.
- [x] Wire nightly rebuild — orchestrator Phase 7.5 (`_run_phase_7_5_dashboard_db`), best-effort, tested live.

#### T1 Sync sub-phases (next, from dashboard_sync_deploy_plan.md)
- [ ] **S1** GitHub push (code only; add `.env.example`; decide model-artifact policy)
- [ ] **S2** R2 bucket + `scripts/sync_dashboard_db.py` upload → wire as orchestrator Phase 7.6
- [ ] **S3** Streamlit Cloud deploy + Google-email auth + R2-pull-on-boot shim; revisit localhost-only header comment
- [ ] **S4** spare-PC Task Scheduler runbook (wake-on-LAN, builder-PC clarification, end-to-end verify)

### T2: Model Card Phase 4 — Promotion Gate

Full spec + ✅ implementation record: [DONE_phase_4_promotion_gate.md](../sprint_11/DONE_phase_4_promotion_gate.md)

**Decision (2026-06-11):** card is ADVISORY only — does NOT block promotion. The
real hard gate stays the `results.json` blocking gates in `set_prod()`. Card
verdict thresholds are hand-set/unvalidated; blocking on them manufactures false
confidence. See [decision_log/2026-06-11_model_card_gate.md](../../decision_log/2026-06-11_model_card_gate.md).

- [x] `ALTER TABLE models ADD COLUMN model_card_path VARCHAR, model_card_built_at TIMESTAMP` (idempotent in `_migrate_models_table`)
- [x] `ModelCardBuilder.render(register_version_id=...)` → `ModelRegistry.register_model_card()` writes path + timestamp back
- [x] CLI: `build_model_card.py --require-promotion-pass <use_case>` exits non-zero on REJECT/PENDING, 0 on PASS/MARGINAL (CI/manual only) + `--register-version`
- [x] `ModelRegistry.set_prod()` `_warn_on_adverse_card()` — ADVISORY WARNING on REJECT/PENDING/void, **never blocks** (force/results.json gate unchanged)
- [x] Resolved: `threshold_gate` stays `["A","E","G"]` (Section C not required — fixed-cutoff gate doesn't consume calibrated probs). Documented in decision log.
- [x] Daily orchestrator Phase 10 (`_run_phase_10_model_card`): rebuild prod card when stale (>7d); `phase_10_model_card: WARN` in config — never halts pipeline

### T3: Training/Eval Infrastructure Verification — ✅ DONE 2026-06-11

Full record: [DONE_t3_infra_verification.md](DONE_t3_infra_verification.md). Flow works end-to-end; candidate `m01_prototype/v2` card band=WEAK (ranks well, calibration fails). NOT promoted (human call).

- [x] `load_pretrain_data(mode="trades")` — 37,952 rows × 218 cols, current through 2026-06-10, all 97 features present
- [x] `get_model_features('M01')` — **fixed case-sensitivity bug** (`LIKE 'M01%'` → `LOWER()`); also broke live `universe_scorer.py:146`
- [x] Trained candidate `m01_prototype/v2` (test acc 0.293, status=test, not prod)
- [x] `build_model_card.py` ran end-to-end → `model_cards/m01_prototype_v2.{html,json}`, band=WEAK
- [x] Findings documented in DONE file + plan

### T4: Documentation — Model Dev Lifecycle + Master Doc Update

Do this last (after T1–T3), so the doc reflects any discoveries made during infra work.

- [ ] Add model development lifecycle section to `docs/comprehensive_methodology.md` (decision framework: target selection, 2-class vs 4-class, when to backtest vs go back to EDA, easy fixes, promotion rules)
- [ ] Update `comprehensive_methodology.md` timestamp and any stale sections (EDGAR engine, ticker reclassification, macro fix, model card framework — all landed post 2026-05-16)
- [ ] Add runbooks to `docs/manual_for_me.md` (ticker deactivation, macro gap repair, view recreation, filing date backfill) — these were the only genuinely new content in `lifecycle_manual.md`
- [ ] Delete `docs/session_logs/sprint_12/lifecycle_manual.md` once merged

---

## P2 — High Value, Not Blocking

### T5: Universe Lifecycle Automation (outflow side first)

- [ ] Daily auto-detect: tickers with ≥14 consecutive NO_DATA AND `last_px > 30d` → yfinance-confirm → auto-deactivate with JSONL audit entry
- [ ] Safety: ≤50 deactivations/day cap + dry-run default
- [ ] Wire into orchestrator Phase 1 post-ingestion (or Phase 9 monitoring)
- [ ] Inflow side (weekly FMP discovery) — defer to Sprint 13

### T6: Mode B Score Trajectory Analysis

- [ ] Correlation of daily `daily_predictions` scores with forward returns at 5d/20d/60d
- [ ] Score trajectory for "super performers" (top quartile MFE) vs ordinary trades
- [ ] Surface as a section in the eval report or a dashboard tab

### T7: Feature Drift / PSI Trigger

- [ ] Finalize quarterly PSI report cron (or orchestrator hook)
- [ ] Wire report path into Pipeline Health page

---

## P3 — Deferred

- [ ] Eval framework Phase 4 (scope TBD)
- [ ] Risk: 5-factor model improvements
- [ ] `earnings_calendar` at-scale rate-limit
- [ ] Audit script timeout: `tools/run_all_audits.py:51` 120s → 600s (trivial, do whenever touching that file)
- [ ] `trend_c8` CTE rename to `trend_exit`
- [ ] Cross-sectional casing in `COLUMN_CASE_MAP` (`rs_sector_rank` etc.)


## Daily To Do
- [ ] Try dashboard remote
- [ ] Figure out data sync
- 