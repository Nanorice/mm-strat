---
name: document-model
description: >
  Build or enrich a model lifecycle doc in docs/model_doc/ (one per model: m01, m02,
  regime_model/m03, and any future model). Use whenever the user wants to document a
  model's research journey, problem, theory, variants, performance, version history, or
  roadmap; wants a single source-of-truth doc for a model; asks to "write up", "consolidate
  docs for", or "enrich the doc for" M01/M02/M03/macro/regime or any model; or has just had
  a modelling breakthrough and wants it recorded. Also use when scattered model docs
  (research notes, sprint logs, module passports, model cards) need gathering into one
  clean, non-contaminated doc. Trigger even if the user doesn't say "lifecycle doc" — if the
  subject is documenting *what a model is, why it exists, and how it evolved*, this is it.
---

# document-model

Produce/maintain **one lifecycle doc per model** in `docs/model_doc/` — the source of truth
for *why the model is the shape it is*: problem, theory, live variants, journey, performance,
roadmap. Code structure/infra stays in `docs/modules/`; lifecycle docs link out, never duplicate.

Two modes:
- **Build** — gather scattered truth into a new/rewritten doc.
- **Enrich** — a breakthrough happened; update the affected sections without disturbing the rest.

## The one rule that matters most: no contamination

Model names in this project get **reused** (M02 was a loser-detector, then a quantile-cone, now
an ignition classifier) and each model accretes **dozens of dead experiment folders** (`models/`
has ~30 `m01_*` dirs). A doc that lets retired work sit next to live work as if they were peers
is the exact confusion the reader came to escape.

**A lifecycle doc describes ONE live purpose.** Enforce it:

1. **Title the doc by the current purpose**, not the bare model name. "M02 — Ignition Classifier",
   not "M02 (a name with history)".
2. **Retired ≠ variant.** A *variant* is a live alternative you'd choose between under the same
   purpose (m01_binary vs m01_4class). A *retired* model or a dead experiment folder is not — it
   never appears in Variants, Theory, Spec, or the main Journey.
3. **Quarantine dead things in one fenced block at the bottom** (§9 "Sources & Name history / Dead
   variants"), explicitly labeled *"do not treat as variants/alternatives."* One paragraph naming
   what they were and why they died — not a full write-up that competes for attention.
4. **Tag every gathered fact by era before you place it.** Source docs mix eras (e.g.
   `m02_final_verdict.md` retires one M02 while a later doc revives the name). Split them:
   current-purpose facts flow into the body; dead-purpose facts flow into the quarantine block.
   Never let a retired model's metrics/target/theory sit beside the live one's.
5. **On a purpose pivot (enrich mode): retire, don't blend.** Move the old purpose into the
   quarantine block and re-title the doc around the new one. Appending the new purpose alongside
   the old is how contamination starts.

## The other three rules

- **Cite real numbers.** Prose docs round and drift. Pull metrics from the actual artifacts —
  `models/**/summary.json`, `*_config.json`, `ablation_summary.json`, calibration reports — and
  quote the run/version id. If a research doc says "~50%" and `summary.json` says 0.5011, use 0.5011.
- **Verify before you link.** A cross-link is a claim the target is current and consistent. Before
  emitting one, open the target. If it's **contaminated** (describes a retired thing under the live
  name — as `docs/modules/model_m02.md` was), *fix it too* — a stale linked doc spreads the same
  confusion. If making it correct would mean heavy duplication of the lifecycle doc, **don't link;
  give it a distinct job** (code-structure passport) and dedupe by role instead.
- **Status must be loud and first.** SHIPPED / PROTOTYPE / RETIRED + champion variant + its path +
  headline metric go in the §0 TL;DR. That operational truth (esp. "not in prod yet") must not be
  buried.

## Workflow

1. **Identify the model and mode.** New doc, or enrich existing `docs/model_doc/<model>.md`?
2. **Hunt sources** (see `references/source_map.md`). Grep `docs/research/`, `docs/session_logs/
   sprint_N/`, `models/<model>*/`, `scripts/train_*`, `src/evaluation/*_cv.py`, `docs/modules/`.
   Tag each finding: *current purpose* or *dead era*.
3. **Separate live from dead.** Which `models/<model>_*` folders are the live champion/variants,
   which are graveyard? Cross-check memory (MEMORY.md) and the latest sprint summary — the
   directory listing alone will mislead you (typo'd dupes, abandoned sweeps).
4. **Pull real metrics** from artifacts for §0 and §5. Note run/version ids.
5. **Write to the template** (`references/template.md`) — build mode fills all 9 sections; enrich
   mode touches only §0, §5, §6 (Journey gets a new dated line), §8.
6. **Verify links.** Open each target; fix or drop per the rule above.
7. **Update the index** `docs/model_doc/README.md` (status + one-liner row).

## Template & source map

- `references/template.md` — the 9-section lifecycle template with per-section guidance. Read it
  before writing; it is the required structure.
- `references/source_map.md` — where each kind of truth lives in this repo, and how to tell a live
  variant from a dead experiment folder.

## Style

Terse and honest (matches this repo's doc conventions). Tables over prose for specs/variants/
metrics. State uncertainty plainly ("regime-flattered", "not yet in prod"). A journey doc should
also say *when to kill the model* (a retirement condition in §8) — documenting only how to grow it
is half the picture.
