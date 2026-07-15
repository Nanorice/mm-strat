# Model Docs

Lifecycle docs — one per model. Each is the source of truth for *why the model is the shape it
is*: problem, theory, live variants, journey, performance, roadmap. Code structure/infra lives
in `docs/modules/`; these docs link out to it, they don't duplicate it.

| Doc | Model | Status | One-liner |
| :--- | :--- | :--- | :--- |
| [m01.md](m01.md) | M01 — SEPA Candidate Ranker | SHIPPED | GATES already-surfaced SEPA candidates by P(MFE>30%) (selection). Champion `m01_binary` (binary, promoted 2026-07-15; 4-class archived). |
| [m02.md](m02.md) | M02 — Ignition Classifier | PROTOTYPE | Ranks the universe by proximity to next breakout (early warning). |
| [regime_model.md](regime_model.md) | M03 — Macro Regime Gauge | SHIPPED | 0–100 weather gauge; coincident state descriptor, not a predictor. |

## The one rule these docs obey: **no contamination**

A model doc describes **one live purpose**. Retired models, reused names, and dead experiments
are quarantined in a fenced "Name history / Dead variants" block at the bottom and never appear
in the Variants, Theory, Spec, or Journey as if they were live alternatives. See the
`document-model` skill for how to write/enrich these without cross-contaminating eras.
