# Session Handover: 2026-07-19 (docs overhaul: meta doc + module docs + accuracy sweep)

## 🎯 Goal
Make `comprehensive_methodology.md` accurate and restructure it as the meta doc, create
a per-module reference layer under `docs/modules/`, and purge/repair every stale doc in
`docs/architecture/` + `docs/modules/` so the only truth is how the code works.

## ✅ Accomplished
1. **Verified the doc corpus against code + live DB** (read-only). Confirmed drift:
   4-class → binary prod model, cooldown gate removed, `screener_watchlist` = VIEW,
   16-phase registry, `daily_features` dead, `champion_trail_spygate` champion,
   `load_training_data_from_db` doesn't exist.
2. **Rewrote `comprehensive_methodology.md`** (1,041 → ~370 lines) as the meta doc:
   doc-map table, phase/table inventory, epistemic spine, replication guide, verified
   tech-debt list. Everything module-level delegated.
3. **Created the module reference layer** `docs/modules/`: new `engines.md`,
   `feature_pipeline.md`, `regime_m03.md`, `managers.md`, `orchestrator.md`,
   `model_registry.md`, `evaluation.md`; surgical refresh of `backtest.md`
   (champion + engine-fidelity caveats); kept `dashboard.md`.
4. **Cleanup**: deleted 6 obsolete architecture docs + 12 stale module docs + the whole
   `docs/modules/manual/` Obsidian vault; moved 3 plan/review docs to their sprint
   folders (sprint_10/plans ×2, sprint_13/plans ×1). All dangling refs fixed.
5. **Accuracy sweep of the survivors** (user prompted — several were stale):
   - `manual_for_me.md` (was renamed `stale_` by user, renamed back): Phase 4b cooldown
     logic, Phase 6 view chain, prod-model claims, backtesting section, retired
     Today-monolith pages, 3 broken `docs/plans/` links — all fixed; added Phases
     7.4–7.6/10 sections.
   - `db_schema.md` regenerated (was generated pre-merge; had `cooldown_end` +
     `v_screener_dashboard`). Now 34 tables + 15 views.
   - All 4 `data_flow*.mmd` + legend: watchlist-as-view, dropped `v_screener_dashboard`,
     added 1.6 gate / shadow pass / 7.45–7.47, "red gate withholds R2" edge.
   - `local_vs_remote_db.md` rewritten: slim = 31 objects / 750 MB; noted
     `shadow_book`/`shadow_action`/`m02_*`/`t3_training_cache` absent post-recovery.
6. **CLAUDE.md Codebase Map fixed**: training loader is
   `src/evaluation/training_data_loader.py::load_training_data`; `daily_features`
   references removed; deep-docs section now points at the module layer.
7. **Memory**: new `project_doc_architecture.md` + index line.

## 📝 Files Changed
- `docs/architecture/comprehensive_methodology.md`: full rewrite (meta doc)
- `docs/modules/*.md`: 7 new module docs + `backtest.md` refresh
- `docs/architecture/{manual_for_me,db_schema,local_vs_remote_db,data_flow*,backtester_manual}.md/.mmd`: accuracy fixes
- `.claude/CLAUDE.md`: Codebase Map + deep-docs corrections
- Deletions/moves: see the two commits' file lists (git history preserves everything)

## 🚧 Work in Progress (CRITICAL)
- **None half-finished in docs.** But: `local_vs_remote_db.md` full-DB per-table row
  counts couldn't be re-queried (main DB locked by another process, PID 53964) — the
  doc's regenerate snippet fills them in when the DB is free.
- Pre-existing uncommitted changes NOT touched/committed by this session:
  `scripts/pages/{3_Model_Lab,4_Backtest_Studio,6_Supply_Chain}.py`,
  `src/evaluation/model_card/report.py` (leftovers from session 11 — triage next session).

## ⏭️ Next Steps
1. Triage/commit or discard the leftover `scripts/pages/*` + `model_card/report.py` diffs.
2. `src/data_loader_duckdb.py` still queries the dead `daily_features` table — its batch
   paths are likely broken at runtime; fix or delete the module.
3. sh019: pull code, rerun watchlist backfill + `create_duckdb_views` (post-merge parity)
   — still open from session 11, plus the backup story.
4. Habit going forward: when changing a module, update its `docs/modules/*.md` in the
   same session (recorded in memory `project_doc_architecture`).

## 💡 Context/Memory
- **Doc architecture decided**: meta doc (`comprehensive_methodology.md`, narrative +
  doc map) → module docs (`docs/modules/`, per-module truth) → ops manual
  (`manual_for_me.md`) → generated (`db_schema.md`) → diagrams (`data_flow*.mmd`).
  Model lifecycle docs stay in `docs/model_doc/`.
- Commit-date ≠ accuracy: `db_schema.md` was committed the same day it went stale (the
  merge landed hours later). The only reliable check is content-vs-code.
- `db_schema.md` is regenerate-only (`scripts/gen_db_schema_doc.py`); never hand-edit.
