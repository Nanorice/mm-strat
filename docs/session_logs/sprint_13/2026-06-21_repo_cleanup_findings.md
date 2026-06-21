# Repository Cleanup — Findings & Deferred Decisions

**Date:** 2026-06-21
**Context:** Pre-merge cleanup of the `infra_uplift` branch before merging Sprint 12 to `main`.
The repo had grown cluttered; goal was to remove stale/unused/satellite files **safely** —
correctness of the remaining tree, not disk space, is the objective.
Starting point: [`docs/session_logs/sprint_12/bonus/repository_cleanup_plan.md`](../sprint_12/bonus/repository_cleanup_plan.md) (skeleton).

---

## Done this session (safe tier — zero code + zero living-doc ties)

| Action | Item | Verification |
|--------|------|--------------|
| `git rm` | `move_files.py` | one-off mover targeting a non-existent `archive/` dir; already run |
| `git rm` | `check_deps.py` | one-off legacy-module dependency audit |
| `git rm` | `unused_report.json` | dumped output of `check_deps.py` |
| `git rm` | `codebase_tree.txt` | corrupt UTF-16 error text, not a real tree |
| `rmdir` | `database/` | empty + untracked + gitignored (legacy SQLite location) |
| rewrite | `README.md` | was Sprint-1 / pre-DuckDB; now reflects the DuckDB 8-phase pipeline and points to the two canonical docs |

Root now contains exactly: `README.md`, `config.py`, `requirements.txt`.

---

## Key finding — `docs/reports/` is a LIVE dependency, NOT stale bloat

Originally flagged for deletion (55 MB of `pretrain_audit_*.html`). **This was wrong.**

- `scripts/pages/1_Dataset_EDA.py:68` runs `REPORTS_DIR.glob("pretrain_audit_*.html")`
  at runtime and renders the reports (newest-first) in the dashboard's **Dataset EDA** page.
- `docs/manual_for_me.md` (lines ~1274/1327) documents the dashboard iframing the newest report.

**Verdict: leave `docs/reports/` untouched.** The HTML is gitignored (global `*.html` rule),
so it is local-only anyway and was never committed bloat. Regenerate via
`python scripts/run_pretrain_audit.py --mode trades`.

---

## Key finding — deletion targets are code-DEAD but DOCUMENTED

A full-repo scan (every `.py` / `.md` / `.ps1` / `.ipynb` / `.json`) showed **none** of the
removal candidates are imported or shelled-out by live code. The only references are:
1. **Frozen history** — `docs/session_logs/sprint_*`, `docs/plans/completed/**`. Point-in-time
   records ("Created X.py"). Deleting the file leaves a dangling relative link in an archived log.
2. **Living docs** — must be reconciled if the file is removed (see table below).

**Open policy question (unresolved):** when a deleted script is linked from *frozen* history,
leave the dangling link (treat logs as an immutable record — recommended) or scrub it?
Living docs get fixed either way.

---

## Files to check / decide next session (NOT yet actioned)

### A. Code-dead, history-only scaffolding — candidate DELETE
Superseded by the real `tests/` suite or already-applied one-offs. Safe at runtime.

| File | Notes | Living-doc tie |
|------|-------|----------------|
| `scripts/test_backtest_enhancements.py` | superseded by `tests/` | none (frozen `plans/completed/duckdb_v2/`) |
| `scripts/test_evaluation_framework.py` | superseded by `tests/` | **`docs/evaluation_framework_implementation.md`** — needs 1-line edit |
| `scripts/test_fundamental_features.py` | superseded by `tests/` | none (frozen sprint_3) |
| `scripts/test_python_rs_features.py` | superseded by `tests/` | none (frozen sprint_3) |
| `scripts/test_rs_line_sql_vs_python.py` | superseded by `tests/` | none (frozen sprint_3) |
| `scripts/test_t3_integration.py` | superseded by `tests/` | none (frozen `plans/completed/`) |
| `scripts/create_t3_schema.py` | schema now owned by `feature_pipeline._create_t3_table()` | none (frozen) |
| `scripts/migrate_model_registry.py` | ALTER TABLE migration already applied | none (frozen sprint_7) |
| `scripts/check_duckdb_schema.py` | throwaway "quick schema peek" | none (frozen sprint_3) |
| `tools/backfill_earnings_calendar.py` | self-labeled one-off; outputs in `tools/_artifacts/` | none |
| `tools/_artifacts/*.csv` | stale `earnings_backfill_*` outputs (2026-05-06) | none |

### B. Coupled clusters — do NOT delete/move naively (would break imports)
| Cluster | Coupling | Recommendation |
|---------|----------|----------------|
| `m01_rank_scorer` + `m01_rank_multihorizon` + `validate_m01_rank_skill` + `run_case1_prototype_standalone` + `run_case2_prototype_plus_rank` | cross-import via `from scripts.X import …` | **KEEP in `scripts/`** — active model-comparison research, adjacent to Sprint-12 M02/shadow work. If ever moved, move the whole cluster together and rewrite imports to `scripts.oneoff.X`. |
| `add_benchmark_tickers` ↔ `backfill_benchmark_prices` | reference each other (string hints) | keep as a pair (re-seed tooling) |
| `verify_model_card_prereqs` | named by **live** `build_model_card.py:55` + `docs/proposals/model_card_framework_2026_05_25.md` | **KEEP** — companion of a load-bearing tool |

### C. Past-fix validation / ad-hoc audit one-offs — review individually
`validate_alpha_parity.py`, `validate_m03_integration.py`, `validate_stop_loss_logic.py`,
`verify_sepa_rs_fix.py`, `audit_column_refs.py`, `audit_fundamental_schema.py`,
`backfill_risk_scores.py`, `backfill_macro_rates.py`, `compare_d1_trades.py`,
`WorldQuant_101.py`. Each validates a since-landed fix or is rare tooling. Decide
delete-vs-keep per file; none are code-reachable as a blocker.

### D. New, KEEP (active Sprint-12 work, appeared mid-session)
`train_m02_prototype.py`, `build_m02_targets.py`, `compare_models.py`, `compare_shadow.py`,
`eval_m02_coverage.py`, `refresh_t3_training_cache.py`, `diag_vol_autocorrelation.py` —
M02 / shadow-comparison scripts matching the untracked `model_comparison_report.md` /
`shadow_comparison_report.md`. **Not** cleanup targets.

---

## Deferred — directory reorg (Tier 4 of the skeleton plan)

The skeleton's reorg (new `dashboard/`, `scripts/backfills/`, `scripts/experiments/`,
`tests/validation/` + rewriting all imports & `sys.path` hacks) is **deferred to a separate
post-merge PR.** Moving the dashboard package and ~14 backfills while rewriting imports is
high-breakage risk to land in the same PR that merges Sprint 12 to `main`, for low value.

---

## Verification before the final cleanup PR

```bash
python scripts/run_daily_pipeline.py --dry-run
python tools/run_all_audits.py --warn-only
```
