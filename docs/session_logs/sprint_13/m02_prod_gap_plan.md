# M02 prototype→production — implementation plan (G3–G7)

> Written 2026-07-04. Implements the gap table in [m02.md §8a](../../model_doc/m02.md).
> G1 (final model) + G2 (frozen metadata) are DONE (`models/m02_breakout/final_20260704_175544/`).
> This plan covers the rest, **gated**: Phase 0's arena verdict decides whether Phases 2–4 run
> at all. Do not start Phase 2+ before the Phase 0 verdict is written.
>
> **⛔ GATE CLOSED — 2026-07-04.** Phase 0.1 signal-quality gate returned NO-GO.
> Phases 2–4 do NOT run on the strategy justification. See verdict in
> [m02_signal_quality_report.md](m02_signal_quality_report.md) and [m02.md §6/§8b](../../model_doc/m02.md).
> The only open path is the ops-tool framing (§ "What survives" in the report) — a separate,
> smaller decision that is NOT covered by this plan.

## Gate philosophy

```
Phase 0 (G6 backtest+eval)  ──verdict──►  no edge → park model, update doc, STOP (plan ends)
                                          edge    → Phase 1 → 2 → 3 → 4 (PROTOTYPE→PROD flip)
```

Everything after Phase 0 is prod plumbing that only earns its keep if the model earns a slot.

---

## Phase 0 — economic evaluation (G6) — the critical path

Mostly already planned in [goal_a3_m02_strategy_plan.md](goal_a3_m02_strategy_plan.md) and
[strategy_arena_playbook.md](strategy_arena_playbook.md); this phase adds two cheap checks that
attack the *circularity caveat* (the WF result proves M02 predicts the scanner event, not P&L).

**0.1 — Signal-quality gate script** (`scripts/analyze_m02_signal_quality.py`, one script, ~150 lines):

- **(a) Job-2 lead time** (A3 §3): for names that later enter `sepa_watchlist`, days between M02's
  first top-decile-rank crossing and the M01 entry date. Emit the distribution + forward return
  from each date.
- **(b) Decile forward-return monotonicity**: bucket `score_panel.parquet` into daily score
  deciles, compute 5/10/21d forward returns from `price_data` (NOT t3 — gappy panel). Pass =
  monotone-ish gradient with a real top-vs-bottom spread. This is the direct "does the score
  predict *returns*, not just the event" test.
- **(c) Top-50 turnover / unique-name P@50**: daily overlap of consecutive top-50 lists +
  precision counted on unique names. Diagnostic only — tells us what the 50.1% P@50 actually
  means (persistent-name domination vs broad signal).

Inputs all exist: `score_panel.parquet`, `sepa_watchlist`, `price_data`. Output: one markdown
report to this sprint folder. **Go/no-go on (a)+(b):** lead time ≈ 0 **or** no forward-return
gradient → no-go.

**0.2 — Job-1 short-hold backtest** (only if 0.1 passes): E1 fixed N-day hold via
`VectorizedSEPABacktest(precomputed_scores=...)`, entry = **daily rank/decile cut** (never an
absolute `min_prob_elite` — rank-only contract, G4 still open). Sweep N∈{5,10,21} with
`run_strategy_optimizer.py`, gate with `run_strategy_wfo.py`, confirm winner on BackTrader
(`run_strategy_array.py`). All engines already built — see playbook §3.

**0.3 — Verdict** written to sprint summary + m02.md §6/§8. This is the gate.

## Phase 1 — calibration decision (G4) — decide, don't build

The lazy resolution: if the winning Phase-0 strategy selects by **rank** (it should — 0.2 mandates
it), no calibrator is needed. Then G4 closes as a *documented contract*, not code:

- Add a `RANK-ONLY` banner to `metadata.json` (`"score_contract": "rank_only"`) and assert in the
  scoring path that no consumer thresholds the raw value.
- Build an isotonic calibrator (mirror m01's `calibrator.joblib`, fit on WF OOS fold predictions —
  they're banked in `fold_NN.json`) **only if** a threshold-based strategy wins the arena or the
  dashboard needs a probability display. Do not build it speculatively.

## Phase 2 — nightly scoring + materialization (G3)

Goal: M02's daily top-of-universe shortlist persisted nightly so the dashboard never scores live
(same invariant as m01).

**2.1 — Incremental scorer.** Extend `scripts/score_m02_breakout.py` with `--date YYYY-MM-DD`
(default: latest t3 date) → score one cross-section instead of the full panel. Reuses the
existing loader; ~20 lines (a WHERE clause on `load_matrix`).

**2.2 — Write path.** Reuse `prediction_logger.log_daily_predictions` (idempotent
INSERT OR REPLACE, PK includes model_version_id):
- `prob_class_1` = clipped proximity, `production_class_idx=1`.
- New cohort `'ignition'` added to `_VALID_COHORTS` (the existing cohorts are SEPA lifecycle
  tags; M02's universe scan is a genuinely different cohort — don't overload `pre_breakout`).
- `model_version_id = 'm02_breakout/final_20260704_175544'` (path slug; register in
  `model_registry` model_versions so joins/model cards resolve — check the insert helper there).
- **Materialize top-200 per day only**, not 2,700 rows — the product is a shortlist; the full
  panel lives in parquet for research. `# ponytail: top-200 cap; raise if dashboard needs depth`.

**2.3 — Orchestrator phase.** New stable-ID phase in `phase_registry.py` +
`daily_pipeline_orchestrator.py`, after t3/lifecycle scoring: call 2.1+2.2. Failure = warn, not
pipeline-fatal (M02 is additive).

**2.4 — Dashboard tile.** "Ignition watchlist" — today's top-50 by proximity rank with rank-delta
vs yesterday. **Must** add the table/query to `build_dashboard_db.py` MANIFEST (remote-parity
landmine) or the R2 remote app breaks.

## Phase 3 — governance (G5 + G7) — gates the PROTOTYPE→PROD flip

**3.1 — Pre-train audit (G5a).** `run_pretrain_audit.py --mode dense` already exists — run it
against the m02 training population, bank the HTML. Fix what it flags before the flip.

**3.2 — Reference snapshot (G5b).** Reuse `src/evaluation/drift.py` snapshot machinery: freeze
the training feature distribution → `models/m02_breakout/final_*/reference_snapshot.json`.
Check what `test_drift.py` expects the snapshot shape to be and match it.

**3.3 — Model card (G7).** Do NOT force m02 through the m01 `build_model_card` sections (they're
classifier/evaluation-framework shaped — verify before assuming). Lazy version that satisfies
"shipped, reviewable evaluation surface": one static HTML/markdown from `summary.json` (WF table)
+ Phase 0 report (lead time, decile gradient, backtest verdict) + metadata.json. If
`build_model_card` turns out to accept a custom section list cheaply, use it; otherwise a
~100-line render script is the honest scope.

## Phase 4 — forward monitoring + retirement trigger

The final model has **no holdout** (metadata says so) — forward monitoring is the safety net,
not a nice-to-have.

- **4.1 — Live P@50 job**: weekly script (or orchestrator phase) computing rolling forward P@50
  on the materialized `'ignition'` cohort rows once the 60d horizon matures, vs the 13.66% base
  rate. Persist to a small table; surface on the dashboard tile (2.4).
- **4.2 — Retirement condition (mechanical, from m02.md §8b.4)**: rolling-quarter P@50 collapses
  toward base rate → hypothesis falsified for the live regime → retire. Encode the threshold in
  the monitoring job so it alerts, not a human remembering to look.
- **4.3 — Doc flip**: m02.md §0 status `PROTOTYPE → PROD`, §8a table statuses, variant row
  updated to the final run. Only after 3.x are banked.

---

## Task list (order = dependency order)

| # | Task | Files touched | Reuses | Gate | Status |
|---|---|---|---|---|---|
| 0.1 | signal-quality gate script | `scripts/analyze_m02_signal_quality.py` | score_panel, price_data, sepa_watchlist | — | ✅ DONE |
| 0.2 | E1 backtest + WFO + BT confirm | arena scripts (built) | injected-scores slot | 0.1 go | ⛔ NO-GO |
| 0.3 | verdict → sprint summary + m02.md | docs | — | **STOP here if no edge** | ✅ DONE |
| 1 | rank-only contract in metadata | metadata.json, score_m02_breakout.py | — | 0.3 go | ~~cancelled~~ |
| 2.1 | `--date` incremental scoring | score_m02_breakout.py | load_matrix | 0.3 go | ~~cancelled~~ |
| 2.2 | daily_predictions write, cohort `'ignition'`, registry row | prediction_logger.py, model_registry | log_daily_predictions | 2.1 | ~~cancelled~~ |
| 2.3 | orchestrator phase | phase_registry.py, daily_pipeline_orchestrator.py | — | 2.2 | ~~cancelled~~ |
| 2.4 | dashboard tile + MANIFEST | dashboard.py, build_dashboard_db.py | slim-DB pattern | 2.2 | ~~cancelled~~ |
| 3.1 | dense pre-train audit run | none (run + bank HTML) | run_pretrain_audit --mode dense | 0.3 go | ~~cancelled~~ |
| 3.2 | reference snapshot | small script or --final hook | drift.py | 0.3 go | ~~cancelled~~ |
| 3.3 | minimal model card | new small render script | summary.json + 0.x reports | 0.3 go | ~~cancelled~~ |
| 4.1 | live P@50 monitor | new script/phase | daily_predictions | 2.x | ~~cancelled~~ |
| 4.2 | retirement alert threshold | same job | — | 4.1 | ~~cancelled~~ |
| 4.3 | PROTOTYPE→PROD doc flip | m02.md | — | 3.x + 4.1 | ~~cancelled~~ |

**Not in scope** (deliberately): target stratification and k/horizon sweeps (m02.md §8b.1–2) —
modelling improvements, not prod gaps; revisit only after the model is live and monitored.
Calibrator build — see Phase 1 condition.
