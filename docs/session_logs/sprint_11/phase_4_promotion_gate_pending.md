# Pending: Model Card Phase 4 — Promotion-Gate Integration

**Status:** DEFERRED (Phases 1–3 done; framework operational standalone)
**Source plan:** [docs/plans/model_card_implementation_plan_2026_05_25.md §5](../../plans/model_card_implementation_plan_2026_05_25.md)
**Estimated effort:** 0.5 day
**Carried over from session:** 2026-05-26 (Phase 3 completion)

---

## Why this is pending, not killed

Phase 4 wires the model card into model promotion so it can actually block bad promotions. Without it the card is a report that anyone can argue away — the same fate the deep-rigor analysis hit. The framework doc (`docs/proposals/model_card_framework_2026_05_25.md` §6 risk register) calls this out explicitly.

The user chose to defer rather than ship Phase 4 in the same session that wrapped Phases 1–3. Re-pick this up before the next model is promoted to `is_production=true`.

---

## What's in scope

### 1. Model registry schema (`models` table)

```sql
ALTER TABLE models ADD COLUMN model_card_path VARCHAR;
ALTER TABLE models ADD COLUMN model_card_built_at TIMESTAMP;
```

Update `ModelRegistry` write path so `ModelCardBuilder.render()` (or a thin wrapper) writes the card path + build timestamp back to the registry on completion.

Touch points:
- [src/registry.py](../../../src/registry.py) (or wherever the `models` table is maintained — verify before editing)
- [src/evaluation/model_card/builder.py](../../../src/evaluation/model_card/builder.py) — `ModelCardBuilder.render()` returns `(html_path, json_path)`; add a `register_to_models_table=True` option that writes back.

### 2. Promotion gate (CLI flag)

```
python scripts/build_model_card.py --model m01_binary/v1 \
    --require-promotion-pass composite_gate_plus_rank
```

Behavior:
- Build the card as normal.
- If `card.use_case_verdicts[<use_case>] == "REJECT"`, exit non-zero.
- `"MARGINAL"` exits zero with a warning printed to stderr.
- `"PENDING"` exits non-zero (don't promote when a section was skipped).

Touch points:
- [scripts/build_model_card.py](../../../scripts/build_model_card.py) — add `--require-promotion-pass <use_case>` flag.
- Optional: also enforce the band — e.g., `--require-band ACCEPTABLE` blocks promotion of WEAK or BROKEN cards.

### 3. Decision log entry

Add `docs/decision_log/2026-MM-DD_model_card_gate.md` recording the new promotion rule. The rule per plan §5.2:

> No flip to `is_production=true` without:
> 1. Card built within the last 7 days
> 2. Card's `composite_gate_plus_rank` use-case verdict = PASS or MARGINAL
> 3. Human sign-off recorded in the decision log

Implementation choice: enforce (1) and (2) in code (a pre-promotion script reads `models.model_card_built_at` and `model_card_path`, refuses promotion if either is stale or REJECT). (3) is a process rule, not a code rule.

### 4. Refresh cadence — orchestrator hook

Hook into `DailyPipelineOrchestrator` as **Phase 10 (advisory only, non-blocking)**:

- Trigger: model version unchanged AND eval window unchanged → skip (use `model_card_built_at` to detect freshness).
- Trigger: either changed → rebuild the card for the current production model.
- Failure mode: log + alert, but do NOT halt the daily pipeline (the daily price/feature pipeline can't be blocked by a slow model-card build).

Touch points:
- [src/orchestrators/daily_pipeline_orchestrator.py](../../../src/orchestrators/daily_pipeline_orchestrator.py) — add Phase 10.
- HALT/WARN/SKIP config: card-build failure should be WARN, never HALT.

---

## Risks if Phase 4 is never landed

| Risk | Severity | Notes |
|---|---|---|
| Manual review loop drifts — humans approve REJECT cards because "we need to ship" | HIGH | The whole point of the card is to make the verdict mechanical |
| Stale cards — production model running while card is months old, eval window has moved | MEDIUM | Mitigated by the daily orchestrator hook |
| Card never integrated → reverts to "another evaluation artifact nobody looks at" | HIGH | Already happened to deep-rigor analysis once — see [2026-05-25_binary-pruned-and-deep-rigor.md](2026-05-25_binary-pruned-and-deep-rigor.md) |

---

## Acceptance criteria (from plan §8 — remaining items)

- §8.7: `models.model_card_path` populated for both v1 cards (`m01_binary/v1`, `m01_prototype_2003_2026/v2`); promotion gate refuses to flip `is_production` when the card REJECTS the requested use case.
- Promotion script demonstrably blocks a forced REJECT promotion in dry-run.
- Daily orchestrator runs Phase 10 once in production without halting the pipeline.

---

## Open question — `USE_CASE_REQUIREMENTS` for `threshold_gate`

As of 2026-05-26 (this session) [verdict.py](../../../src/evaluation/model_card/verdict.py) was edited to drop Section C from `threshold_gate`:

```python
"threshold_gate": ["A", "E", "G"],   # was: ["A", "C", "E", "G"]
```

Rationale not in the commit (intentional edit by the user). When picking up Phase 4, confirm whether:
- The plan's `--require-promotion-pass composite_gate_plus_rank` default still makes sense (composite still requires C).
- The framework doc (`docs/proposals/model_card_framework_2026_05_25.md` §4 use-case verdict matrix) needs updating to reflect the dropped C dependency on `threshold_gate`, OR the verdict.py edit needs reverting.

This decision matters because it determines whether a model with poor calibration (C=fail) can be deployed as a pure threshold gate. The framework's original position was no — calibration matters because thresholds are *probability* thresholds. If C is no longer required, document why.
