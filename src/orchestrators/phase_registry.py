"""Single source of truth for orchestrated pipeline phases' identity, order, and label.

A phase has a STABLE id that never changes when execution order changes, plus a
display label and a sort order that are free to move. Inserting a step mid-
pipeline changes only `order` — no id renumbers, so persisted
`pipeline_runs.phase_name` keys never strand. See
docs/session_logs/sprint_12/pipeline_phase_keys.md for the rationale.

Source-of-truth split (deliberate, to keep config low-level and cycle-free):
  - failure_mode  -> config.PIPELINE_FAILURE_MODES (this module imports it)
  - id/label/order -> here

Scope: ONLY the run-level phases driven by `_execute_phase`. Sub-phase keys
written via record_write/record_errors (e.g. 'phase_1_t1_price') are NOT
registered here — they are bookkeeping tags, not orchestrated steps.
"""

from dataclasses import dataclass

from config import PIPELINE_FAILURE_MODES, PipelineFailureMode


@dataclass(frozen=True)
class Phase:
    id: str                            # stable, persisted key — never renumber
    label: str                         # display only, e.g. "Phase 7.4 - Scoring"
    order: float                       # execution + heatmap sort key

    @property
    def failure_mode(self) -> PipelineFailureMode:
        return PIPELINE_FAILURE_MODES[self.id]


# (id, label, order) — failure_mode is resolved from config by stable id.
PHASES: list[Phase] = [
    Phase("ingestion",           "Phase 1 - Ingestion",       1.0),
    Phase("screener_membership", "Phase 2 - Screener",        2.0),
    Phase("t2_screener",         "Phase 3 - T2 Features",     3.0),
    Phase("t2_regime",           "Phase 4 - T2 Regime",       4.0),
    Phase("sepa_watchlist",      "Phase 4b - SEPA Watchlist", 4.5),
    Phase("t3_features",         "Phase 5 - T3 Features",     5.0),
    Phase("views",               "Phase 6 - Views",           6.0),
    Phase("cache",               "Phase 7 - Training Cache",  7.0),
    Phase("scoring",             "Phase 7.4 - Scoring",       7.4),
    Phase("weather",             "Phase 7.45 - Weather Gauge", 7.45),
    Phase("sector_breadth",      "Phase 7.46 - Sector Breadth", 7.46),
    Phase("dashboard_db",        "Phase 7.5 - Dashboard DB",  7.5),
    Phase("r2_sync",             "Phase 7.6 - R2 Sync",       7.6),
    Phase("monitoring",          "Phase 8 - Monitoring",      8.0),
    Phase("model_card",          "Phase 10 - Model Card",     10.0),
]

PHASE_BY_ID: dict[str, Phase] = {p.id: p for p in PHASES}


def failure_mode_for(phase_id: str) -> PipelineFailureMode:
    """Failure mode for a phase id; HALT for unknown ids (fail-safe default)."""
    return PIPELINE_FAILURE_MODES.get(phase_id, PipelineFailureMode.HALT)


def label_for(phase_id: str) -> str:
    """Display label for a phase id; the raw id for unknown keys."""
    phase = PHASE_BY_ID.get(phase_id)
    return phase.label if phase else phase_id


def order_for(phase_id: str) -> float | None:
    """Sort order for a phase id; None for unknown keys (caller decides fallback)."""
    phase = PHASE_BY_ID.get(phase_id)
    return phase.order if phase else None
