# Sprint 12 Plan

**Start:** 2026-06-09  
**Goal:** Infra that supports training/evaluation workflow, slim dashboard DB synced across devices, model card promotion gate.

---

## Objectives

1. **Slim Dashboard DB + Cross-Device Sync** — build `dashboard.duckdb` containing only the data the dashboard actually queries (<1 GB target). Parameterise the app's DB path so it works local or remote. Sync across devices via object storage or shared drive. This is the primary infra goal.
2. **Model Card Phase 4** — wire the card verdict into `ModelRegistry.set_prod()`. ✅ DONE 2026-06-11, implemented as **ADVISORY** (warns, does not block): the card's thresholds are hand-set/unvalidated, so the only hard gate stays the `results.json` blocking gates. See [decision_log/2026-06-11_model_card_gate.md](../../decision_log/2026-06-11_model_card_gate.md).
3. **Training/Evaluation Infrastructure** — verify the full training → evaluation → card flow works end-to-end on the current clean dataset. Deploying the model itself is a human judgement call, not a to-do.
4. **Documentation update** — add the model development lifecycle decision framework to `comprehensive_methodology.md`. Do this *after* infra/card work, not before. `lifecycle_manual.md` created in sprint setup is superseded — merge its unique content (model dev lifecycle section + runbooks) into the existing master docs, then delete it.

---

## Rolled-Over Backlog (from Sprint 11)

See [todo.md](todo.md) for the active task list.

| Priority | Item | Source |
|---|---|---|
| P1 ✅ | Infra uplift — slim DB (sync DEFERRED to S1-S4) | [misc_todo_0529.md §4](../sprint_11/misc_todo_0529.md) |
| P1 ✅ | Model Card Phase 4 — advisory (not a gate) | [DONE_phase_4_promotion_gate.md](../sprint_11/DONE_phase_4_promotion_gate.md) |
| P1 ✅ | Training/eval infra verification — **DONE 2026-06-11 (T3)** | Sprint 11 §Deferred |
| P2 | Universe lifecycle automation (outflow side) | Sprint 11 misc_todo §5 |
| P2 | Mode B analytics (score trajectory) | Sprint 11 §Deferred |
| P2 | Feature drift / PSI quarterly trigger | Sprint 11 §Deferred |
| P3 | Eval framework Phase 4 (scope TBD) | Sprint 11 §Deferred |
| P3 | Risk: 5-factor model improvements | Sprint 11 §Deferred |
| P3 | `earnings_calendar` at-scale rate-limit | Sprint 11 misc_todo §6 |
| P3 | Audit script timeout 120s → 600s | Sprint 11 misc_todo §8 |

---

## File Structure for This Sprint

```
docs/session_logs/sprint_12/
  sprint_12_plan.md          ← this file
  todo.md                    ← active task list (updated each session)
  sprint_12_summary.md       ← filled in at sprint end
  DONE_*.md                  ← completed items (one per major task)
  YYYY-MM-DD_*.md            ← session handover notes
```

Note: `lifecycle_manual.md` (created 2026-06-09) is superseded — its unique content will be merged into `comprehensive_methodology.md` and `manual_for_me.md`, then deleted.

---

## Definition of Done

- [x] `dashboard.duckdb` builds from a manifest, is <2 GB, and the app runs from it off the dev box — **783 MB**, verified (sync S1-S4 deferred)
- [x] Model Card Phase 4: card wired into `set_prod()` as an **advisory WARNING** (the hard gate stays `results.json`; decision reversed from "refuses on REJECT" — see decision log)
- [x] Training → eval → card flow verified on current clean dataset (model promotion = human decision) — **T3 DONE 2026-06-11**: flow works end-to-end; fixed a real case-sensitivity bug in `get_model_features`; candidate `m01_prototype/v2` card band=WEAK (ranks well, calibration fails). Not promoted (human call).
- [ ] Model dev lifecycle section added to `comprehensive_methodology.md` — T4
- [ ] `todo.md` reflects current state at end of each session

---

## T3 — DONE 2026-06-11 (Training/Eval Infra Verification)

The full **load → features → train → eval → card** flow runs end-to-end on the
current clean dataset (post-EDGAR / deactivation / macro fixes). Promotion is a
human call and was **not** done. Findings:

- **Data ✅** `load_pretrain_data(mode="trades")` → 37,952 rows × 218 cols,
  2001-01-03 → 2026-06-10, 2,673 tickers, 0 NULL mfe_pct. All 97 prod features
  present; null fractions are normal sparse-fundamentals (XGBoost-native).
  (The `load_training_data_from_db` name in CLAUDE.md is legacy; real loader is
  `load_pretrain_data`.)
- **Root-cause fix:** `src/utils.get_model_features('M01')` used case-sensitive
  `version_id LIKE 'M01%'` but prod `version_id`s are lowercase `m01_…` → raised
  RuntimeError despite a fully-populated catalog. Fixed to
  `LOWER(version_id) LIKE LOWER(?)`. **Also silently broke the live
  `universe_scorer.py:146` scoring path** — not just verification.
- **Candidate `m01_prototype/v2`** (60/20/20, fs_m01_prototype, mfe_4class_v1):
  test acc 0.293 / wF1 0.280 / macroF1 0.288 — in line with prod v2. Registered
  status=`test` (`m01_prototype_20260611_133021`), NOT promoted.
- **Model card** (`model_cards/m01_prototype_v2.{html,json}`): void=False,
  band=**WEAK** (9/21). Only `hit_rate_ranker_equal_size` PASS; other 4 use cases
  REJECT — all on **calibration** (raw 4-class booster, ECE 0.132 vs 0.05 gate).
  Real edge confirmed: AUC 0.773 vs SEPA-composite 0.594; Section G null/bootstrap
  3/3 PASS; robust across all regimes/years. For a promotable *probability* model,
  next step is the binary home-run variant with `--with-calibration`.
- **Not done (intentional):** `--register-version` write-back to
  `models.model_card_path` was skipped — v2 is a `test` candidate, not the prod
  row. The advisory write-back is still unexercised on a real card.

---

## Next session — start here (T4: Documentation)

T1–T3 are done. T4 is the remaining P1: merge model-dev-lifecycle content +
runbooks into the master docs and update `comprehensive_methodology.md` for the
post-2026-05-16 landings (EDGAR engine, ticker reclassification, macro fix, model
card framework). See [todo.md](todo.md) T4. `lifecycle_manual.md` is superseded —
merge its unique content, then delete it.

Clean state: prod model unchanged = `m01_prototype_2003_2026_20260514_233125`
(its `model_card_path` still NULL — advisory write-back not yet exercised on a
real card). Working-tree change from this session: `src/utils.py` case fix.
