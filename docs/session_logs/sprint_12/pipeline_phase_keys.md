# Pipeline phase keys — convention problem + proposed redesign

Status: **proposal only** (2026-06-16). No code changed. Documents why the
current phase-key scheme is fragile and proposes a single-source-of-truth
registry. Came out of the Phase-9-gap discussion (orchestrator jumps 8 → 10).

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
