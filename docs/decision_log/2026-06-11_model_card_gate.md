# Decision: Model card is ADVISORY, not a promotion gate

**Date:** 2026-06-11
**Sprint:** 12 (T2 — Model Card Phase 4)
**Supersedes:** the hard-gate intent in
[DONE_phase_4_promotion_gate.md](../session_logs/sprint_11/DONE_phase_4_promotion_gate.md)
and [model_card_framework_2026_05_25.md §6](../proposals/model_card_framework_2026_05_25.md).

---

## Decision 1 — the model card does NOT block model promotion

`ModelRegistry.set_prod()` continues to enforce exactly one **hard** gate: the
`blocking=True` gates in the model's `evaluation/results.json` (overridable with
`force=True` + a logged `force_reason`). The model card is wired in as
**advisory only**:

- `set_prod()` reads the registered card and **logs a WARNING** if the
  `composite_gate_plus_rank` verdict is `REJECT`/`PENDING` or the card is void —
  then **promotes regardless**. (`_warn_on_adverse_card`.)
- `build_model_card.py --require-promotion-pass <use_case>` exits non-zero on
  REJECT/PENDING for **CI / manual gating only**. It does not touch `set_prod()`.
- Daily orchestrator **Phase 10** rebuilds the prod model's card when stale
  (>7d). It is registered `WARN` in `PIPELINE_FAILURE_MODES` and never halts the
  daily pipeline.

### Why (overrides the original plan)

The card's verdict thresholds — `USE_CASE_REQUIREMENTS`, the band cutoffs
(`6/21`, `12/21`, `17/21`) — are **hand-set and empirically unvalidated**.
Wiring an arbitrary number into a hard promotion block lets a meaningless
threshold veto a human decision. The project's aim is not a "perfect model"
scored against an invented rubric; it is an informed human promotion call. The
*real* quality gate (`results.json` blocking gates) already exists and stays.

This trades away the "mechanical gate" risk the framework doc raised (humans
rationalising away a REJECT card). We accept that risk: the WARNING is loud and
logged, and a blocking gate built on unvalidated thresholds is worse than no
gate — it manufactures false confidence.

## Decision 2 — `threshold_gate` does NOT require Section C (calibration)

`USE_CASE_REQUIREMENTS["threshold_gate"]` stays `["A", "E", "G"]` (Section C
dropped, as edited 2026-05-26).

**Rationale:** a threshold gate fires on a **fixed score cutoff**, not on
calibrated probabilities. Calibration quality (Section C) governs whether a
predicted probability *means* what it says — relevant for `probability_sizing`
and `composite_gate_plus_rank` (both still require C), but not for a pure
cutoff. The framework's original "thresholds are probability thresholds"
position does not hold for this use case as implemented.

Because the card is advisory (Decision 1), the requirement list only affects a
**displayed verdict label**, not any promotion behaviour — so this is low-stakes
and revisitable if the gate ever becomes blocking.

---

## Touch points (4)

1. `models` table: `model_card_path VARCHAR`, `model_card_built_at TIMESTAMP`
   (added idempotently in `ModelRegistry._migrate_models_table`).
2. `ModelCardBuilder.render(register_version_id=..., registry_db_path=...)` →
   `ModelRegistry.register_model_card()`.
3. `build_model_card.py`: `--require-promotion-pass`, `--register-version`.
4. `ModelRegistry.set_prod()`: `_warn_on_adverse_card()` (advisory).
   Orchestrator: `_run_phase_10_model_card()` + `phase_10_model_card: WARN`.

## Process rule (not enforced in code)

Human sign-off for any `is_production=true` flip is still recorded here in the
decision log. Code enforces neither the 7-day freshness nor the verdict for
promotion — only the advisory surfacing.
