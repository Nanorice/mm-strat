# Model Card Phase 4 — Promotion-Gate Integration

**Status:** ✅ DONE (2026-06-11, sprint 12) — implemented as **ADVISORY**, not a hard gate.
**Source plan:** [docs/plans/model_card_implementation_plan_2026_05_25.md §5](../../plans/model_card_implementation_plan_2026_05_25.md)
**Decision log:** [docs/decision_log/2026-06-11_model_card_gate.md](../../decision_log/2026-06-11_model_card_gate.md)
**Carried over from session:** 2026-05-26 (Phase 3 completion)

---

## ✅ Implementation record (2026-06-11)

**Key reversal vs. the spec below:** the user directed that the model card is
**informational only and must NOT block promotion**. The card's verdict
thresholds (`USE_CASE_REQUIREMENTS`, band cutoffs `6/21`, `12/21`, `17/21`) are
hand-set and empirically unvalidated; blocking promotion on them would let an
arbitrary number veto a human decision and manufacture false confidence. The
**only hard promotion gate remains the `results.json` blocking gates** already
in `set_prod()` (overridable via `force=True` + logged `force_reason`).

### Prod model resolution (confirmed)
"Prod" = the dashboard's model = the single `models` row with
`status_flag='prod' AND model_type='classifier'`:
**`m01_prototype_2003_2026_20260514_233125`** (`model_name=m01_prototype_2003_2026`, `v2`).
- Dashboard resolves it via `dashboard_utils.load_prod_model()` /
  `load_prod_model_version_id()` ([scripts/dashboard_utils.py:462,575](../../../scripts/dashboard_utils.py#L462)).
- Phase 10 + `set_prod()` resolve the same row via
  `ModelRegistry.get_prod_version()`. No mismatch.
- ⚠️ **Minor open note:** `get_prod_version()` filters only `status_flag='prod'`
  (no `model_type` filter). With a single prod row the two agree; if a non-
  classifier prod row is ever added, Phase 10 should add the
  `model_type='classifier'` filter to stay identical to the dashboard. Not
  changed now (single prod row, no ambiguity).

### What shipped (4 touch points + advisory wiring)

| # | Change | Location |
|---|--------|----------|
| 1 | `models.model_card_path VARCHAR`, `models.model_card_built_at TIMESTAMP` — added idempotently | `ModelRegistry._migrate_models_table` ([src/model_registry.py](../../../src/model_registry.py)) |
| 2 | `register_model_card(version_id, card_path, built_at)` + `get_model_card_info(version_id)` | src/model_registry.py |
| 3 | `ModelCardBuilder.render(register_version_id=..., registry_db_path=...)` writes the card path back (lazy registry import → eval package stays decoupled) | [src/evaluation/model_card/builder.py](../../../src/evaluation/model_card/builder.py) |
| 4 | CLI `--require-promotion-pass <use_case>` (exit≠0 on REJECT/PENDING, 0+stderr on MARGINAL — CI/manual only, does NOT touch set_prod) + `--register-version` | [scripts/build_model_card.py](../../../scripts/build_model_card.py) |
| — | `set_prod()` calls `_warn_on_adverse_card()` — logs a WARNING on REJECT/PENDING/void for `composite_gate_plus_rank`, then **promotes regardless**. Silent (info) when no card registered. | src/model_registry.py |
| — | Orchestrator **Phase 10** `_run_phase_10_model_card()` — rebuilds prod card when stale (>7d), registers path back. **Best-effort.** | [src/orchestrators/daily_pipeline_orchestrator.py](../../../src/orchestrators/daily_pipeline_orchestrator.py) |
| — | `phase_10_model_card: PipelineFailureMode.WARN` in config — **required** because `_execute_phase` defaults unregistered phases to HALT; without this a slow card build would halt the daily pipeline. | [config.py](../../../config.py) |

### Threshold-gate Section-C question — RESOLVED
`USE_CASE_REQUIREMENTS["threshold_gate"]` stays `["A", "E", "G"]` (C dropped).
A fixed-cutoff threshold gate does not consume calibrated probabilities, so
Section C (calibration) is not required. `probability_sizing` and
`composite_gate_plus_rank` still require C. Moot in practice since the card is
advisory. Documented in the decision log.

### Verified (no full card build kicked off, per user)
- Migration adds both columns against the live DB; `register_model_card` /
  `get_model_card_info` round-trip `built_at`.
- Advisory path: synthetic REJECT card → WARNING + **no exception**; PASS → info.
  (Test card path reset to NULL on the prod row afterward.)
- All touched files parse; new CLI flags register in `--help`.
- **Not run:** an end-to-end Phase 10 / full card build (multi-minute Section G).
  Subprocess wiring mirrors the already-tested Phase 7.5 pattern.

### Remaining (process, not code)
- §8.7 acceptance: populate `models.model_card_path` for the prod card by running
  `build_model_card.py --model <prod_version> --register-version <prod_version>`
  once (or let Phase 10 do it on the next daily run). Currently NULL on the prod
  row (test value was cleared).
- Human sign-off for `is_production=true` flips is still a decision-log process
  rule, not enforced in code.

---

## Original spec (below) — superseded where it conflicts with the advisory decision

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
