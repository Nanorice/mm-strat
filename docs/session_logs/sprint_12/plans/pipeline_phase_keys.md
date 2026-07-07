# Pipeline phase keys — convention problem + redesign

Status: **IMPLEMENTED — full** (2026-06-16). The stable-id registry exists at
`src/orchestrators/phase_registry.py` (single source of truth for id/label/order);
`config.PIPELINE_FAILURE_MODES` is keyed by stable id (drift fixed); AND
`failure_mode` is now the live control surface (part b — every call site routes
through `_is_critical(id)`). Came out of the Phase-9-gap discussion (8 → 10).

## What shipped (registry-only)

- `src/orchestrators/phase_registry.py` — `Phase(id, label, order)` + `PHASES`
  list + `PHASE_BY_ID` + `failure_mode_for/label_for/order_for`. **Stable ids**
  (`ingestion`, `t2_screener`, `scoring`, `model_card`, …) decoupled from order.
- **Source-of-truth split (to keep `config` low-level + cycle-free):** failure
  mode lives in `config.PIPELINE_FAILURE_MODES` (keyed by stable id, drift gone);
  label/order live in the registry, which imports the failure modes. config does
  NOT import the registry.
- Orchestrator: all 13 `_execute_phase(...)` calls use stable ids; `record_write`
  tags updated to match; label derived via `label_for` (was `split('_')[1]`).
- Heatmap `_phase_sort_key`: registry `order_for` first, regex fallback for old
  persisted keys during the seam.
- `tests/test_phase_registry.py` — consistency guardrails (config↔registry↔
  orchestrator) so drift can't silently return.

### Part (b) — live control surface (landed same session)
Turned out to be **behavior-preserving**, not behavior-changing: the registry
`failure_mode`s were set from the call sites' observed behavior, and
`_execute_phase` already returns `False` only for HALT phases (WARN/SKIP always
return `True`). So this was a consolidation, not a semantics change:
- New `_is_critical(phase_id)` helper = `failure_mode_for(id) == HALT`.
- Every `_execute_phase` call is followed by a uniform
  `if not phase_success and self._is_critical("<id>"): return False`. The 5
  copy-pasted critical blocks + the vestigial `phase_1_t1_price` lookup + the 8
  `# Non-critical, continue` comments all collapse into this one pattern.
- `_execute_phase` itself now resolves its mode via `failure_mode_for` (registry).
- Guardrail tests: `_is_critical` matches config for all phases; every
  orchestrated call has a guard; end-to-end WARN-continues / HALT-aborts.
- The map is now genuinely the control surface — flipping a phase's mode in
  config changes real run behavior (and a test makes that visible).

### Deliberately NOT done (scope decision 2026-06-16)
- **No `pipeline_runs` migration — heatmap seam accepted.** Old `phase_N_*` rows
  age out of the 30d window; `_phase_sort_key` interleaves both generations
  meanwhile. Sub-phase keys (`phase_1_t1_*`, gate keys) intentionally unchanged.

---

## Original proposal (kept for rationale)

## The core problem: phase identity is positional

Phase keys encode order in the name (`phase_1_…`, `phase_2_…`). Consequences:

1. **Inserting a step renumbers everything after it.** When serving steps were
   added mid-pipeline, monitoring went 9 → 8 and the model card kept "10" → the
   permanent "no Phase 9" gap. To *avoid* renumbering, people sub-number instead:
   `phase_4b_sepa_watchlist`, `phase_7_4_scoring`, `phase_7_5_dashboard_db`,
   `phase_7_6_r2_sync`. The scheme actively encourages ad-hoc suffixes.
2. **The key is persisted.** `pipeline_runs.phase_name` stores these strings for
   idempotency + the Pipeline Health heatmap. Renaming a key strands historical
   rows (heatmap shows the old + new key as two rows until the 30d window rolls).
3. **Keys are scattered across files** with no enforced agreement:
   - `daily_pipeline_orchestrator.py` — the live keys (first arg to `_execute_phase`)
   - `config.py` `PIPELINE_FAILURE_MODES` — failure-mode map, keyed by phase name
   - `pipeline_runs` table — persisted history
   - `5_Pipeline_Health.py` — parses the number out for sort order (`_phase_sort_key`)

## Finding: config/orchestrator phase keys have DRIFTED (latent)

The orchestrator's actual `_execute_phase` keys vs `config.py PIPELINE_FAILURE_MODES`:

**In orchestrator, NOT in config** (9): `phase_1_t1_ingestion`, `phase_4b_sepa_watchlist`,
`phase_5_t3_features`, `phase_6_views`, `phase_7_cache`, `phase_7_4_scoring`,
`phase_7_5_dashboard_db`, `phase_7_6_r2_sync`, `phase_8_monitoring`.

**In config, never used by orchestrator** (dead): `phase_1_cik_map_refresh`,
`phase_1_filing_date_backfill`, `phase_1_t1_fundamentals/macro/shares`,
`phase_5_daily_features`, `phase_6_t3_lazy`, `phase_7_views`, `phase_8_cache`.

`config.py` says `phase_6_t3_lazy`/`phase_7_views`/`phase_8_cache`; the
orchestrator says `phase_6_views`/`phase_7_cache`/`phase_8_monitoring`. The map is
keyed on stale names.

### Why it hasn't blown up (the real mechanism)

`_execute_phase` line 391 does `PIPELINE_FAILURE_MODES.get(phase_name, HALT)` —
**default HALT**. So a drifted phase that fails *and whose caller acts on the
return* would halt. BUT the actual halt/continue decision is **hardcoded at each
call site**, not driven by the config:
- Critical phases: `if not phase_success: return False` (e.g. `phase_5`, line 249).
- Non-critical phases: the caller ignores `phase_success` with a
  `# Non-critical, continue even if failed` comment (e.g. `phase_6`, line 264).

So the `PIPELINE_FAILURE_MODES` map is **largely dead config** — it looks like the
control surface but the call sites override it. The drift is latent today because
the call-site comments happen to encode the right intent. It is a trap: anyone
editing `config.py` to change a phase's failure mode will see no effect (key
mismatch + call-site override), and anyone relying on the default trusts HALT.

## Proposed redesign

### Principle: stable id, decoupled from order

A phase has a **stable identifier** that never changes when order changes:
`ingestion`, `screener_membership`, `t2_regime`, `sepa_watchlist`, `t3_features`,
`views`, `cache`, `scoring`, `dashboard_db`, `r2_sync`, `monitoring`, `model_card`.
Execution **order** and the human **label** ("Phase 7.4") are separate attributes,
not baked into the key. Inserting a step changes only `order`, never any id.

### Single source of truth

One file (e.g. `src/orchestrators/phase_registry.py`) holds the list:

```python
@dataclass(frozen=True)
class Phase:
    id: str                 # stable, persisted key — never renumber
    label: str              # display only: "Phase 7.4 · Scoring"
    order: float            # sort key for execution + heatmap (7.4, 7.5, …)
    failure_mode: PipelineFailureMode

PHASES: list[Phase] = [
    Phase("ingestion",          "Phase 1 · Ingestion",      1.0,  HALT),
    Phase("screener_membership","Phase 2 · Screener",       2.0,  HALT),
    ...
    Phase("monitoring",         "Phase 8 · Monitoring",     8.0,  WARN),
    Phase("model_card",         "Phase 10 · Model Card",    10.0, WARN),
]
```

- Orchestrator iterates `PHASES` (or looks up by id) instead of hardcoding keys +
  per-site halt/continue. `failure_mode` becomes the *actual* control surface again.
- `config.py` stops duplicating the map — imports from the registry (or the
  registry lives in config; either way, one definition).
- Heatmap sorts by `order`, labels by `label` — no more parsing numbers out of keys.
- `pipeline_runs.phase_name` stores the stable `id`. A future reorder never strands
  history.

### Migration note (when this is actioned)

Persisted `pipeline_runs.phase_name` currently holds `phase_N_*` strings. Moving to
stable ids needs a one-time `UPDATE` mapping old → new id (or accept a heatmap seam
for one 30d window). Decide at implementation time.

## Decision log

- **2026-06-16:** keep `phase_10` as-is for now (the gap is cosmetic; idempotency
  is already skipped for it). Do NOT renumber piecemeal — that's the very thing the
  positional scheme makes painful. Redesign to stable ids when there's appetite.
- The config-drift / dead-`PIPELINE_FAILURE_MODES` finding is **flagged, not
  fixed**, this session (would change prod HALT/WARN behavior — needs review).
