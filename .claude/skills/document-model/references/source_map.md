# Source map — where model truth lives in this repo

Hunt these when building/enriching a lifecycle doc. Tag every finding as **current-purpose** or
**dead-era** before placing it (see the contamination rule in SKILL.md).

## Where each kind of truth lives

| Need | Look in |
| :--- | :--- |
| Journey / verdicts / pivots | `docs/research/<model>*.md`, `docs/session_logs/sprint_N/*.md` (esp. the sprint summary) |
| Dated decisions & real findings | `docs/session_logs/sprint_N/<date>*.md` and `*_cells.md` (notebook cell artifacts) |
| Real metrics | `models/<model>*/**/summary.json`, `*_config.json`, `evaluation/**/ablation_summary.json`, `models/m03_*calibration*.md` |
| Spec ground-truth (hyperparams, target, CV) | `scripts/train_*.py`, `scripts/build_*targets.py`, `src/evaluation/*_cv.py`, `src/evaluation/walk_forward.py` |
| Feature set definition | `model_feature_sets` table (via `src/model_registry.py`), `src/feature_config.py` |
| Code structure (for the passport link) | `docs/modules/model_<model>.md`, `src/pipeline/<model>_*.py` |
| Prod scoring path | `daily_predictions` table, `src/backtest/universe_scorer.py`, dashboard build (`build_dashboard_db.py`) |
| Cross-session facts you might miss | `MEMORY.md` index in the memory dir — often names the champion path / gotchas |

Deep architecture (read a *section*, not the whole file):
`docs/architecture/comprehensive_methodology.md`, `docs/architecture/manual_for_me.md`.

## Telling a LIVE variant from a DEAD experiment folder

`models/` is a graveyard — `ls models/` will show far more `<model>_*` folders than are live.
Do not infer "variant" from a folder existing. Confirm live status by triangulating:

1. **Memory + latest sprint summary name the champion.** Start there, not the directory listing.
   (E.g. memory: `m01_prototype_2003_2026/v1/model.json` is the prototype champion.)
2. **Loadability / prod wiring is a liveness signal.** A variant scored into `daily_predictions`,
   or one the backtest scorer loads (has `categorical_mapping.json`), is live. One nothing
   references is probably dead.
3. **Typo'd / date-sweep dupes are dead.** `m01_prototyoe_*` (sic), `_2022_2024`, `_baseline_full_2024`
   style folders are abandoned sweeps — quarantine them.
4. **A distinct *role* makes a live variant; a distinct *run* does not.** m01_prototype (selection)
   vs m01_binary (home-run) vs m01_rank (timing) are real variants — different jobs. Ten dated
   retrains of the same job are one variant's run history, not ten variants.

When unsure whether a folder is live, it's safer to quarantine it in §9 with a note than to promote
a dead experiment into the Variants table — the second is contamination, the first is just caution.

## Reused-name landmine

Before writing §6 (Journey), check whether the model name covered a *different purpose* earlier.
Grep the research/session dirs for the name + words like "retired", "verdict", "pivot", "repurposed",
"name collision". If a prior purpose exists, it goes in the §9 quarantine block — never in the body.
(M02 is the canonical case: loser-detector → quantile-cone → ignition classifier.)
