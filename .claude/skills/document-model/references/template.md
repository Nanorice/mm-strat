# Lifecycle doc template (9 sections)

Copy this structure into `docs/model_doc/<model>.md`. Every section earns its place; if a section
is genuinely empty (e.g. single-variant model), keep the heading and say so in one line rather than
deleting it — a reader scanning for "Variants" should find an answer, not a gap.

The three worked examples in `docs/model_doc/` (m01.md, m02.md, regime_model.md) are the reference
implementations — read whichever is closest to the model you're documenting.

---

```markdown
# <MODEL> — <current live purpose, e.g. "Ignition Classifier">

> Model-lifecycle doc: problem, theory, variants, journey, roadmap — source of truth for
> *why the model is the shape it is* and *how to run it* (§3, §7). Code structure/infra lives
> in docs/modules/; link out, don't duplicate.
>
> **Scope:** <one line: what this model IS>. What it is NOT: <the framing that was tested and
> rejected, or the reused name / dead folders that must not be treated as live>.

## 0. TL;DR / Status
- **Status:** SHIPPED | PROTOTYPE | RETIRED — loud and first.
- **What it does:** one sentence.
- **Champion:** variant name + exact path + version/run id.
- **Headline:** the one metric, with its honest caveat (regime-flattered? short window?).

## 1. Problem & Purpose
The decision this model serves. What breaks without it. The job-to-be-done — not the algorithm.

## 2. Theory / Hypothesis
The market/statistical thesis. What edge it captures and why it should exist. If a competing
framing was tested and rejected, name it here (that's what keeps the doc from re-litigating it).

## 3. Specification
Table: algorithm · target (formula) · feature set (name + where defined, not a 100-row dump) ·
universe (sparse/dense, rows, dates) · key hyperparams · CV/eval geometry (embargo, folds).
Call out scale/units gotchas (e.g. 0–100 vs 0–1).

## 4. Variants (LIVE only)
Table: variant | role | target | key diff | path | status. LIVE members only. If one variant,
say so. Dead experiments and retired-purpose models go in §9, never here.

## 5. Performance
Real numbers from artifacts, per variant. Baseline comparison. The honest steady-state number vs
any flattered one. Where the eval lives (artifact path).

## 6. Version History / Journey
Dated, terse. "Sprint N: conceived as X → pivoted to Y because Z." Current-purpose history only;
the reused name's prior lives go in §9. This is the narrative that explains the current shape.

## 7. Usage
How to train / score / where it plugs into prod (scanner, dashboard, backtest). CLI commands +
canonical path. Note prod-scoring quirks (e.g. materialized nightly, injection paths).

## 8. Roadmap / Open Questions
Known gaps, next experiments, AND a retirement condition (when does this model's hypothesis count
as falsified for the live regime?). Documenting only growth is half the picture.

## 9. Sources & <Name history / Dead variants>
- **Sources:** links to research docs, session logs, module passport, code, artifacts.
- **Fenced quarantine block:** retired-purpose models and dead experiment folders. Explicitly
  labeled "DO NOT treat as variants/alternatives." One paragraph each — what it was, why it died.
```

---

## Enrich mode (a breakthrough happened)

Do **not** rewrite the whole doc. Touch only:
- **§0** — if champion/status/headline changed.
- **§5** — add the new run's real numbers.
- **§6** — add ONE new dated Journey line.
- **§8** — resolve/replace the open question this breakthrough closed.
- **§9** — if the model's purpose *pivoted*, move the old purpose into the quarantine block and
  re-title the doc. (Retire, don't blend.)
