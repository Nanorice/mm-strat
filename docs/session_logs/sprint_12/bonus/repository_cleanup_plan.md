# Repository Cleanup Plan

This plan addresses the clutter in the `scripts/`, `tools/`, and root directories of the project. The goal is to organize files by their functional purpose and make the repository easier to navigate, without breaking existing logic.

## Proposed Changes

### 1. Dashboard Consolidation
The dashboard and its associated utilities are currently sitting inside `scripts/`, polluting the main pipeline entrypoints.
* Create a new top-level directory: `dashboard/`
* [NEW] `dashboard/`
  * [MODIFY] Move `scripts/dashboard.py` -> `dashboard/app.py`
  * [MODIFY] Move `scripts/dashboard_utils.py` -> `dashboard/utils.py`
  * [MODIFY] Move `scripts/pages/` -> `dashboard/pages/`
  * [MODIFY] Move `scripts/build_dashboard_db.py` -> `dashboard/build_db.py`
  * [MODIFY] Move `scripts/sync_dashboard_db.py` -> `dashboard/sync_db.py`
* **Action:** Update all imports within these files to reflect their new locations.

### 2. Group Backfill Scripts
There are 14+ `backfill_*.py` scripts currently sitting in the root of `scripts/` and `tools/`. 
* Create a new directory: `scripts/backfills/`
* [MODIFY] Move all `scripts/backfill_*.py` -> `scripts/backfills/`
* [MODIFY] Move `tools/backfill_earnings_calendar.py` -> `scripts/backfills/`
* **Action:** Update `sys.path.append` references inside these scripts to point to the correct project root, and update the CLI commands mentioned in the `docs/` markdown files.

### 3. Organize Validations & Tests
There are many ad-hoc `test_*.py`, `validate_*.py`, and `verify_*.py` scripts inside `scripts/` and `tools/` that belong in the dedicated `tests/` directory.
* Create a new directory: `tests/validation/`
* [MODIFY] Move `scripts/test_*.py` -> `tests/validation/`
* [MODIFY] Move `scripts/validate_*.py` -> `tests/validation/`
* [MODIFY] Move `scripts/verify_*.py` -> `tests/validation/`
* [MODIFY] Move `tools/test_edgar_fundamentals.py` -> `tests/validation/`

### 4. Group Experiments & Research
There are several prototyping and ablation scripts taking up space in `scripts/`.
* Create a new directory: `scripts/experiments/`
* [MODIFY] Move `scripts/run_case1_...`, `scripts/run_case2_...`, `scripts/run_decile_analysis.py`, `scripts/run_deep_rigor_suite.py`, `scripts/run_permutation_null.py`, `scripts/run_strategy_array.py`, `scripts/run_pretrain_audit.py`, `scripts/ablation_backtest.py` -> `scripts/experiments/`
* [MODIFY] Move `scripts/WorldQuant_101.py` -> `scripts/experiments/`

### 5. Root Directory Cleanup
* [MODIFY] Move `move_files.py` and `check_deps.py` -> `scripts/maintenance/` (or delete if obsolete).
* [MODIFY] Move `unused_report.json` -> `logs/` (or delete).
* [DELETE] `codebase_tree.txt` (This can be dynamically generated when needed instead of sitting in the root).

## Verification Plan
1. Move the files using Python or shell commands.
2. Update all internal imports (e.g. fixing `sys.path.append(...)`).
3. Update `docs/manual_for_me.md` and `docs/comprehensive_methodology.md` with the new script paths.
4. Run `python scripts/run_daily_pipeline.py --dry-run` and `python tools/run_all_audits.py --warn-only` to ensure core systems are unbroken.
