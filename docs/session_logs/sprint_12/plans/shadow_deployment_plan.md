# Shadow Deployment & Performance Comparison Plan (Sprint 12, Phase 3)

*Authored 2026-06-18. Status tags updated live during implementation.*

## Guiding insight

Both models score the **same** SEPA candidate universe (`v_d3_deployment` /
`v_d3_prebreakout`). The model does not gate entry — SEPA criteria do. The model
only **ranks and assigns probability**. So shadow comparison here is
**counterfactual re-scoring**, not a behavioral A/B test: there is no confounding
from different trade populations, both models see identical rows.

Because realized outcomes already exist in `screener_watchlist` / `v_d2_hydrated`,
a shadow can be judged over full history the instant it is registered. Nightly
shadow scoring is only for ongoing drift monitoring, not the initial verdict.

## Data model — one ledger, keyed by model

`daily_predictions` PK is `(prediction_date, ticker, model_version_id, cohort)`.
`model_version_id` in the key means the table already stores N models side by
side. **Shadow scores are additive rows under a different `model_version_id` —
they never overwrite prod rows.** Every dashboard loader hard-filters by the prod
`model_version_id` (`status_flag='prod'`), so shadow rows are invisible to the UI
and read only by the comparison tooling.

Shadow scores are **always materialized**, never computed on the fly:
- historical: once, via `backfill_daily_predictions.py --model-version-id <shadow>`
- nightly: Phase 7.4, right after prod scoring

The only computation done "on demand / nightly" is the cheap divergence verdict
(a self-join + correlation over already-stored scores). No model is ever loaded
at compare time.

```
                  SCORES (run the model)              VERDICT (compare scores)
                  ────────────────────                ────────────────────────
historical   backfill_daily_predictions.py ─┐
 (once)        --model-version-id <shadow>   │
                                             ├─► daily_predictions ─► shadow_compare ─► shadow_divergence
nightly      Phase 7.4: score prod          ─┘    (prod + shadow,      (self-join,        (one verdict
 (each day)           + score shadow              all tickers/dates)     spearman/jaccard)   row/day)
```

## Two modules

### Module A — historical comparison (on-demand, offline)

- **A1 — static ranking comparison** *(build now)*: For a flexible date range
  (default 1yr, decade optional), compare the two models' rankings on the
  breakout cohort. Ranking is *how stocks are selected*, so ranking difference is
  the core question. Pure function of scores — raw probs, **no outcomes, no
  calibration, no leakage concerns**. Metrics: Spearman(prod,shadow),
  top-10 Jaccard, rank-churn distribution, per-ticker disagreement table.
  Output: markdown report into `docs/session_logs/sprint_12/`.

- **A2 — strategy-backtest comparison** *(placeholder)*: Run a baseline backtest
  strategy under each model's ranking and compare realized performance. Blocked
  on backtest finalization — stub + doc note only. This is where the
  calibration / win-label / OOS concerns live; quarantined here.

### Module B — ongoing monitoring (nightly, in-pipeline)

After Phase 7.4 scores prod, score the shadow on the **same** candidates, then
run the shared compare core on today's rows and write one verdict row to
`shadow_divergence`. Best-effort: never blocks prod. Materializing the verdict
gives a cheap divergence-over-time time series for a future dashboard, without
recomputing the self-join over history.

## Shared core

`src/evaluation/shadow_compare.py` holds the ranking-diff computation. A1 runs it
over a wide range; B runs it over one day. Single code path so the two can't
drift (same discipline as the shared `ScoreEngine`).

## Decisions locked

- Shadow designation: new `status_flag='shadow'` value; at most one shadow.
- Scores: same `daily_predictions` table, second `model_version_id` (additive).
- Cohort scope: **breakout only** (the list actually acted on).
- B verdict: **materialized** to `shadow_divergence` (one row/day).
- Win label / calibration: only relevant to A2 → deferred.

## Corrections to the original Sprint-12 summary

- ❌ `scripts/daily_predictions.py` — does not exist; real path is
  `ScoreEngine` → orchestrator Phase 7.4.
- ❌ `v_d3_deployment_shadow` view — redundant; both models share the universe.

## Phase tracker

| Phase   | What                                                                                       | Status      |
|:--------|:-------------------------------------------------------------------------------------------|:------------|
| 3a      | `ModelRegistry`: `status_flag='shadow'`, `set_shadow`/`get_shadow_version`, one-shadow guard | ✅ DONE     |
| 3b      | `src/evaluation/shadow_compare.py` — shared rank-diff core                                  | ✅ DONE     |
| 3c-A1   | `scripts/compare_shadow.py` — CLI, flexible range → markdown report                         | ✅ DONE     |
| 3c-A2   | Strategy-backtest comparison                                                                | ✅ PLACEHOLDER (stub in report) |
| 3d-B    | `ScoreEngine.from_shadow` + Phase 7.4 shadow scoring + `shadow_divergence` table            | ✅ DONE     |
| 3e      | Dashboard tab (reads `shadow_divergence` + A1 reports)                                      | DEFERRED    |

## Follow-ups for 3e (dashboard, deferred)

- Add `shadow_divergence` to the slim-DB MANIFEST (`build_dashboard_db.py`) — any
  table a dashboard loader reads must be in the manifest or the R2 remote app
  breaks (see memory `project_dashboard_remote_parity`). Not needed until 3e.
- Dashboard tab: divergence sparkline from `shadow_divergence` + render the
  latest A1 report.

## How to operate (once a shadow is chosen)

```bash
# 1. designate the shadow (no gates enforced — shadow is for evaluation)
python -c "from src.model_registry import ModelRegistry; ModelRegistry().set_shadow('<shadow_version_id>')"

# 2. materialize the shadow's history into daily_predictions (one-time)
python scripts/backfill_daily_predictions.py --model-version-id <shadow_version_id> --cohort breakout

# 3. run the historical comparison report (A1)
python scripts/compare_shadow.py --start 2016-01-01   # decade; default is last 1yr

# 4. ongoing: Phase 7.4 now scores the shadow nightly and writes shadow_divergence automatically
```
