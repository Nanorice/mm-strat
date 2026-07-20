# Plan — widening the T3 universe to cover first-time setups

**Status:** investigation, not approved work. Drafted 2026-07-20.
**Trigger:** 13 names on the Screening page pass `trend_ok` but carry no score.

## The gap

T3 (`t3_sepa_features`) is the lazy/expensive tier. Its universe is **tickers that have
opened a SEPA session at least once** — `feature_pipeline.compute_t3_features` UNIONs the
`sepa_watchlist` ticker set with `vip_watchlist`, then carries full history for those
names.

Consequence: a ticker in the trend template for the **first time** has never had a
`trend_ok ∧ breakout_ok` day, so it is not in `sepa_watchlist`, so it has no t3 row, so it
is absent from `v_d3_lifecycle`, so nothing scores it. On 2026-07-17 that was 13 of 630
screening rows:

```
ABEO ASIC CZWI IMMX LINE NP OGN PTRN SUNC TRNS XLE XOP   (never any t3 row)
AGL                                                      (session since 2026-06-26, t3 lag)
```

AGL is a **separate bug** — it has a session, so the Phase 5 t3 self-heal (`_t3_holed_dates`)
should have materialised it. Check that first; it is probably cheap and unrelated to the
universe question. ABSI showed the same shape under the wider population.

This is a chicken-and-egg gap, not corruption: the name is invisible to the model until it
triggers once, which is exactly when it stops being a pre-breakout candidate.

## Why it matters

The whole point of `pre_breakout` scoring is ranking names *before* they trigger. A name
whose first-ever breakout is imminent is the highest-value case, and it is precisely the
one we cannot score. The current coverage is biased toward names that have already proven
they can trigger.

## Questions to answer before touching anything

1. **How many names are we talking about, over time?** 13/630 is ~2% today. Measure the
   daily count of `trend_ok ∧ no-t3-row` across the last 12 months. If it is a stable 2%,
   the gap is a rounding error. If it spikes at regime turns — when fresh leadership first
   enters Stage 2 — it is structural and worth paying for.
2. **What does admitting them cost?** T3 currently runs ~2,400 rows/day. Get the true
   marginal cost: how many *distinct new tickers* would `trend_ok`-ever admit, and T3
   carries **full history** per ticker, so the cost is (new tickers x history depth), not
   (new tickers x 1 day). This is the number that decides the whole plan. Budget against
   the existing Phase 5 runtime in `pipeline_runs`.
3. **Is the model even valid on them?** M01 trained on the SEPA population. A first-time
   setup is in-distribution for `pre_breakout` features but has no session history — check
   whether any training feature is implicitly conditioned on prior-session existence. If
   yes, scoring these names is out-of-distribution and the honest answer is to leave the
   blank and say why, not to widen T3.
4. **Does `screener_membership` already gate this?** T2 is membership-filtered; confirm
   whether a widened T3 would inherit that filter or need its own.

## Candidate approaches, cheapest first

- **A. Do nothing, document the blank.** Already partly done — the Screening page's "How
  to read the dates" expander now explains it. Correct outcome if Q1 says ~2% flat or Q3
  says OOD. Zero cost.
- **B. Admit on first `trend_ok`, not first session.** Change the T3 universe from
  "ever in `sepa_watchlist`" to "ever `trend_ok`". Conceptually a one-line change to the
  candidate UNION; the cost is entirely in Q2's history-depth multiplier. Needs a
  backfill for the newly-admitted tickers before scores appear.
- **C. Admit with a shallow window.** Same as B but carry only the trailing N days of
  history for trend-only names instead of full history — enough for the `pre_breakout`
  feature set, a fraction of the cost. Adds a second code path in T3 (two classes of
  ticker with different history depth), which is the reason to prefer B if B is
  affordable.
- **D. Score them from T2 alone.** Only if the model's feature set turns out to be a T2
  subset for the `pre_breakout` cohort. Check `model_feature_sets` before considering —
  almost certainly false, listed for completeness.

## Suggested order of work

1. Fix / explain AGL's self-heal miss (independent, small).
2. Answer Q1 and Q2 — both are read-only queries against the existing DB. **Stop here and
   report the numbers**; they decide between A and B/C.
3. Only if the numbers justify it: Q3, then prototype B behind a smoke-test on a single
   backfill date before any full run.

## Constraints

- T3 is the expensive tier — per CLAUDE.md, smoke-test a small batch before any long run,
  with `flush=True` progress logging and checkpoint/resume.
- `market_data.duckdb` is single-writer and the nightly Prefect job runs on `sh019`;
  confirm idle before writing.
- Do not widen T3 and `v_d3_lifecycle` in the same change — widen T3, verify rows land,
  then widen the lifecycle filter. Two reviewable steps.

## Related

- `v_d3_lifecycle` cohort filter: `src/managers/view_manager.py` (`(f.trend_ok = TRUE AND
  f.breakout_ok = FALSE) OR wl.cohort IS NOT NULL`).
- The 42 non-trend breakouts dropped from `v_d3_screening` on 2026-07-20 are a *different*
  gap, already closed — see the `pop` CTE comment in `_create_v_d3_screening`.
