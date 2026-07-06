# Verdict: Top-5 selection bias — is the pick better than a random tie-pool draw?

**Date:** 2026-07-07 · **Status:** 🔄 smoke test (1 window) — needs full run before acting
**Feeds:** Sprint 14 Goal 1 (selection consistency / turnover)
**Artifact:** [cells/cohort-bootstrap_cells.md](../cells/cohort-bootstrap_cells.md)

## Question
The champion gates by `prob_elite ≥ 0.15`, then takes `top_n=5` ranked by `prob_elite`. Is that
top-5 a *skilled* pick, or a **random draw** from a pool of interchangeable (tie-scored) names?
If random → the model is a **pure gate, not a ranker** → selection bias is real and the fix is to
stop picking 5 (widen the basket), not to build a ranker.

## Mechanism (why the bias exists)
`prob_elite` is coarse. On **55 of 57 entry days in `r_202101_h12`, every picked name shares one
identical `prob_elite` value.** The top-5 "rank" is a tie → the 5 held are an arbitrary draw from
the tied set. Any single 5-name portfolio is therefore a high-variance sample of the gated set.

## Method
Reuses existing sweep artifacts — **no backtest re-run**:
- `trades.parquet` → the 5 actually picked per day.
- `rejections.parquet` (reason `no_slots`) → names the gate admitted but the slot cutoff excluded.
- Forward 20d return per candidate from `price_data.close` (adj_close is 100% NULL).
- Bootstrap: 5000× random 5-draws from the tie-pool; where does the actual pick sit in that null?
- Two tie-pool definitions, side by side:
  - **`exact`** — draw only from names at the *exact* picked tie score (true interchangeables).
    The honest selection-skill test.
  - **`min`** — draw from all `no_slots` names scored ≥ the lowest picked score. Mixes in the
    score gradient (gating) → inflates apparent "edge".

## Result (smoke test — `r_202101_h12`, 20d fwd)
| mode | days | edge mean / median | pick percentile | beats null |
|------|-----:|-------------------:|----------------:|-----------:|
| exact | 34 | +1.7% / **−0.2%** | **0.375** | 32% |
| min   | 36 | +1.3% / **−0.5%** | **0.369** | 31% |

Both modes agree. The **median** edge is ~0 (slightly negative); the pick sits at the ~37th
percentile of the random-draw null and beats it only ~31% of days. The positive *mean* edge is a
few right-tail days, not consistent skill.

**Read:** on this window the top-5 is statistically **a random draw from the tie-pool** — the
model gates, it does not rank. Naive picked-vs-rejected (+1.9% vs −0.8%) *looks* like skill but
that gap is the **score gradient (gating)**, which the bootstrap correctly removes.

## ⚠️ Caveats
- **One window, 34 days → underpowered.** Not a verdict. Loop all 53 cells (or seed best/worst
  months) before acting.
- Median is the honest stat here; mean is inflated by tail days.

## Implication
- **If confirmed across cells:** don't build a ranker — **hold the whole gated survivor set
  (15–20), not 5.** No selection → no selection bias, no new model. (Sprint 14 Goal 1 fix "(a)
  limit/rethink the selection set".)
- **Only if `exact` percentile > 0.6 somewhere:** there's latent ranking skill → build a
  within-cohort ranker (finer prob_elite / RS-momentum), then test rotation (#5b). Ties to
  [[project_cohort_vs_model_scores]]: pre-breakout has rank persistence, breakout doesn't.
