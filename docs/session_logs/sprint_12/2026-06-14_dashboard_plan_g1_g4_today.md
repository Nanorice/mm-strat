# Dashboard Plan — G1, G4, + Today-page enhancements (2026-06-14)

Continuation of `2026-06-14_dashboard_followups.md`. G2/G3/G5 investigations
closed (see that doc); **G3 fixed locally** (price_data added to slim build).
Remaining + newly-scoped items below, each with a do/defer recommendation.

---

## Investigation results carried over (closed)

| Item | Verdict |
|------|---------|
| G2 cik_map / earnings_calendar "not run" | Expected — weekly cadence-gated (7d) on last successful `pipeline_runs` entry. Last success 2026-06-09, fires again ~06-16. No code change. |
| G2 T1 amber | success-with-per-entity-errors (`n_errors>0` from `pipeline_error_log`). Expected; G4 makes it actionable. |
| G3 price_data "no data" | Slim DB never carried `price_data` (not in `build_dashboard_db.MANIFEST`). FIXED locally by adding a windowed entry. |
| G5 NULL filing_date | Single path: statements land but yfinance earnings fetch returns nothing → no PIT anchor; EDGAR backfill repairs. The "+90d" is the *mapping* window, NOT a staleness fallback. Staleness anchors on `last_period_end + EXPECTED_NEXT_FILING_LAG_DAYS (135)`; fallback when period_end unknown is flat `FUNDAMENTAL_STALENESS_DAYS (100)`. No code change. (Optional: tighten UI caption to say 135d.) |

---

## G1 — Data-flow .mmd rewrite  ·  DEFER (last)

`docs/architecture/data_flow.mmd`. Pure Mermaid layout: reconcile against the
orchestrator's current phase list (incl. Phase 7.4 scoring, v_d3_prebreakout, R2
sync), group by layer to de-cross, drop dead nodes/edges. No data dependency,
no risk. Leave for last / a dedicated layout pass.

---

## G4 — T1 failures → deactivation window  ·  DO (the one real feature)

Add a window at the bottom of Page 5's T1 Ingestion Failures section.

**Data is already there**: `load_t1_ingestion_failures()` in `dashboard_utils.py`
already aggregates `pipeline_error_log` per (ticker, phase, error_type) with
`days_failing`, `first/last_failure_date`. The feature is mostly a render +
one threshold filter + a CLI-command hint.

Build:
1. New loader (or reuse the existing one) filtered to `days_failing >= N`
   (default 14) over the window.
2. Render a table: ticker (Finviz LinkColumn, mirror watchlist pattern
   `https://finviz.com/quote.ashx?t=<t>`), days_failing, last_failure_date,
   error_type, sample_detail.
3. The deactivation CLI command. **Open question — find the real writer**:
   memory says `detect_bad_tickers` only *warns*; need to locate the actual
   `ticker_blacklist` / `screener_membership` removal path (there is a
   `ticker_blacklist` table referenced in `load_data_freshness`'s omit-list).
   Surface the exact command, e.g. `python scripts/<deactivate>.py --tickers ...`.
4. Policy caption: "Tickers failing ingestion ≥14d in the window are pruning
   candidates — verify on Finviz (delisted / renamed / acquired) before removing."

Effort: Medium. No schema change.

---

## Today-page #1 — Macro regime history charts  ·  DO (high value, low risk)

Both source tables carry deep history; the Today page only shows the latest row.

- `t2_regime_scores`: 2003-07-20 → 2026-06-11, 8363 rows. Columns: `m03_score`,
  `m03_pillar_trend`, `m03_pillar_liq`, `m03_pillar_risk`, `m03_delta_5d/20d`,
  `m03_regime_vol`.
- `t2_risk_scores`: 2005-12-27 → 2026-06-12, 5147 rows. Carries the 5 z-cols
  + `target_exposure`, `weighted_z`, `rolling_percentile`, `veto_flag`.

### (a) M03 — line plot, 3 pillars + total score
New loader `load_regime_history(days=N)` → date, score, 3 pillars. Plotly line
chart with a lookback selector (90d / 1y / 3y / All). Total score as a bold line,
3 pillars thinner; shade regime bands (the REGIME_THRESHOLDS colors already
exist in dashboard_utils). Goes under `render_regime_header`.

### (b) 5F — visualizing the z-scores
**User's mental model is correct.** Each factor is z-transformed against its own
rolling history, so a z of +1.5 means "1.5σ into the stressed tail of this
factor's own distribution." Two complementary views:

1. **History line chart** (mirrors M03): `load_risk_history(days=N)` → the 5 z-cols
   + `weighted_z` over time, with a ±2σ veto band shaded. Tracks how stress built.
2. **Current-position view** (the "where on the normal curve" intuition): a
   horizontal diverging bar / dot plot — one row per factor, x-axis in σ from
   −3 to +3, a marker at today's z, veto lines at ±2σ. Reads at a glance as
   "how stretched is each factor right now." Cleaner than overlaying 5 bell
   curves; the bell-curve-with-marker version is possible but busy — recommend
   the diverging dot plot, keep the existing expander table beneath it.

Effort: Medium (two loaders + 2-3 charts). No schema change. Recommend doing
(a) + 5F history line first, then the diverging position plot.

---

## Today-page #2 — Watchlist score backfill  ·  DO (real gap, needs a backfill run)

### The gap (confirmed)
`daily_predictions` only exists from **2026-05-22** (when Phase 7.4 materialized
scoring went live). Breakout cohort: 10 distinct dates, 120 rows. The dashboard's
`load_scored_watchlist` joins each watchlist row only to the **single global
latest** `prediction_date` → on the last day only the ~11 tickers that broke out
*that day* get a score; the other ~348 active trades show blank.

**Root cause is two-fold, both structural — not a render bug:**
1. **History gap**: scores were never materialized before 2026-05-22.
2. **Join semantics**: even with full history, the loader attaches the latest
   day's batch, not *each ticker's own* score. A breakout name is only in
   `v_d3_deployment` on the day(s) it actually breaks out, so "latest date for
   all tickers" can never cover the whole watchlist.

### Coverage facts
- `screener_watchlist` ACTIVE: 359 rows, entry_date 2025-08-08 → 2026-06-12.
  **358 of 359 have entry_date ≥ 2025-10-03** (inside the d3 window). Exactly 1
  predates it.
- `v_d3_deployment`: 2025-10-03 → 2026-06-12, 168 distinct dates, 1226 tickers,
  1963 rows. This is the natural backfill domain — and matches the user's
  "start consistent with d3" requirement.

### Fix (two parts)
**Part A — backfill `daily_predictions` across the full d3 window.**
New script `scripts/backfill_daily_predictions.py`:
- Loop distinct dates in `v_d3_deployment` (and `v_d3_prebreakout` for the
  pre-breakout cohort if we want that filled too).
- Reuse the orchestrator's existing path verbatim: `_fetch_breakout_candidates`
  + `_score_and_log_cohort` already take an arbitrary `target_date` + candidate
  frame and call `log_daily_predictions`. No new scoring logic — load booster
  once, loop dates, `INSERT OR IGNORE`-style idempotent log. Estimate: 168
  dates × (small score batch) ≈ minutes.
- Backfill against the **full DB**, then rebuild slim DB so it propagates.

**Part B — fix the join so each watchlist row shows its OWN score.**
Change `load_scored_watchlist` to join on the score *at or nearest before each
ticker's entry_date* (per-ticker ASOF / correlated MAX(prediction_date) ≤
entry_date), not the single global MAX. This is the semantically correct
"score when it entered" and survives going forward without re-backfilling.
The 1 pre-d3 active trade legitimately stays blank (no features in window).

Effort: Medium. Part A is a script + a rebuild; Part B is one query rewrite.
Order: A then B (B is verifiable once A populates history).

---

---

## SYSTEM DESIGN — scores storage + scoring code path (AWAITING SIGN-OFF)

### Q: do we have a separate materialized table for scores? → YES
`daily_predictions` is the dedicated scores table. **t3 is never written for scores**
— the scorer only *reads* features (via v_d3 views). Confirmed schema
(`scripts/migrations/2026_06_12_add_cohort_to_daily_predictions.sql`):

```
PRIMARY KEY (prediction_date, ticker, model_version_id, cohort)
cols: prob_class_0..3, predicted_class, rank_within_day,
      decision_taken, taken_at, notes, ingested_at
```

Why this design already serves "switch model → rescore everything":
- `model_version_id` is IN the PK → a new model's scores are NEW rows beside the
  old model's. History per model is preserved; nothing overwritten on switch.
- writes are `INSERT OR REPLACE` → idempotent; re-running a (date, model, cohort)
  overwrites just those rows.
- dashboard selects `WHERE model_version_id = <prod>` → promoting a new prod model
  switches the dashboard automatically ONCE that model's rows exist (= why the
  backfill must run on every model switch).

### The real design issue: THREE scoring code paths exist today
1. **Orchestrator Phase 7.4** — inline in `daily_pipeline_orchestrator`
   (`_score_and_log_cohort`): load booster, resolve feature cols from registry,
   `booster.predict`, `log_daily_predictions`. RAW softprob, no calibration.
2. **`src/backtest/universe_scorer.py`** — `UniverseScorer.score_from_t3()` /
   `score_from_duckdb()`: richer — detects classifier/regressor/binary, applies an
   **isotonic calibrator** (`calibrator.joblib`) + legacy decile calibration,
   computes normalized + daily-percentile ranks. Used by backtest signal-gen.
3. **Dashboard** — no live scoring now (reads daily_predictions). Was path 3.

These can DRIFT (e.g. calibration applied in backtest but not in the materialized
dashboard scores → dashboard P(HR) ≠ backtest P(HR) for the same model+date).

### Proposed design (the part needing your sign-off)
**One scoring function, one scores table, two writers that call it.**

- **Storage**: keep `daily_predictions` as the single source of truth for
  materialized per-(date,ticker,model,cohort) scores. No new table. t3 untouched.
- **Shared scorer**: extract a single `score_candidates(model_version_id, candidates_df)
  → predictions_df` into `src/evaluation/` (or reuse/refactor `UniverseScorer` as
  that engine). It owns: model-type detection, feature-col resolution from the
  registry, calibration, prob/class output. BOTH the orchestrator's Phase 7.4 AND
  the new backfill util call it → no drift.
- **Backfill util** `scripts/backfill_daily_predictions.py`:
  `--model-version-id` (default = prod), `--start/--end` (default = d3 window),
  `--cohort both`, `--dry-run`. Loops dates in v_d3_deployment / v_d3_prebreakout,
  calls the shared scorer, writes via `log_daily_predictions`. Model loaded once.

### DESIGN DECISIONS — SIGNED OFF (2026-06-14)
1. **Store RAW softprob.** No calibration in `daily_predictions`. Reasons: (a) no
   conviction calibrated > raw yet; (b) calibration changes over time — raw keeps
   the flexibility to apply ANY calibration at read time. → Phase 7.4 ALREADY
   writes raw, so **no re-materialization** of the 2026-05-22+ rows; the backfill
   just extends the same raw contract backward.
2. **Backtest reads the table when using the prod (materialized) model.** Rule:
   if `model_version_id` + dates are already in `daily_predictions` → READ (no
   dup compute); else COMPUTE via the shared scorer (and may write back under that
   model_version_id — PK supports many models coexisting). `daily_predictions`
   becomes a raw-score cache keyed by model. (Backtest integration is its own
   sprint task; the table is ready for it now.)
3. **No new columns.** `normalized_score` / `daily_pct_rank` are NOT stored — they
   are (a) derived from *calibrated* scores (contradicts the raw contract) and
   (b) cheap `groupby('date').rank()` / min-max recomputes. Backtest derives them
   on read from the raw probs + whatever calibration it uses at the time.
   `rank_within_day` already in the table is a RAW-prob rank for the dashboard's
   display only — backtest does NOT reuse it. Net: table stays as-is, no migration.

### What daily_predictions does + current usage (for the record)
- Purpose: materialized prod-model daily scores (dashboard never scores live) +
  persistence for paper-trade decisions (`decision_taken`/`taken_at`/`notes`).
- ONLY writer: `prediction_logger.log_daily_predictions()` ← orchestrator Phase 7.4.
- Readers (dashboard only): `load_scored_watchlist`, `load_scored_pre_breakout`,
  `load_daily_predictions_today`, `load_past_decisions`; `update_decision_taken`
  writes the decision cols. Copied whole into slim DB by `build_dashboard_db.py`.
- Backtest does NOT use it today (scores live via UniverseScorer) — point 2 is a
  NEW integration, not a change to existing behavior.

### Consequences for the backfill (simpler than first thought)
- No schema migration, no re-materialization. Pure raw-score backfill.
- Shared scorer must produce RAW prob_class_* (mirror Phase 7.4), NOT call the
  isotonic calibrator. (UniverseScorer's calibration path stays backtest-only.)

---

## Recommended order this sprint
1. **DESIGN SIGN-OFF** (above) — esp. calibrated-vs-raw stored contract.
2. **Shared scorer extraction + watchlist backfill (Today #2)** — both cohorts, full d3 window.
3. **Macro history charts (Today #1)** — high value, isolated, no schema risk.
4. **G4 deactivation window** — surface `tools/deactivate_tickers.py` (exists; no new script).
5. **G1 .mmd** — defer to a dedicated layout pass.
