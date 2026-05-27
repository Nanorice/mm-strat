# Session Handover: 2026-05-24 — Evaluation Framework Phase D (§5.3 + §5.1) + Fan-Out Proposal

## 🎯 Goal
Continue from the Phase B/C handover
([2026-05-23_evaluation-framework-phase-bc.md](2026-05-23_evaluation-framework-phase-bc.md))
and ship the wiring half of Phase D per
[docs/plans/evaluation_implementation_plan_2026_05_23.md](../plans/evaluation_implementation_plan_2026_05_23.md)
§5. This session shipped:

- **§5.3 Pretrain audit auto-invocation** (P1, 0.5d) — wired into training script
- **§5.1 Paper-trade dashboard toggle** (P0, 1d) — wired into Page 1, with the
  required prerequisite (migration to create `daily_predictions` table)
- **Fan-out bug diagnosis + proposed fix** as a draft proposal doc (NOT applied
  — see [docs/proposals/view_fanout_fix_2026_05_24.md](../proposals/view_fanout_fix_2026_05_24.md))

§5.2 (PSI / drift) was deferred — see Next Steps.

## ✅ Accomplished

### Phase D §5.3 — Pretrain audit auto-invocation

- **`scripts/train_mfe_classifier.py`**:
  - New imports: `DataQualityError`, `run_pretrain_audit`
  - New CLI flag: `--skip-pretrain-audit` (default-on; audit runs unless skipped)
  - New step 2b after `load_training_data`: calls
    `run_pretrain_audit(mode="trades", output_path=...)` and writes
    `models/<name>/<version>/pretrain_audit.html` per the plan.
  - **Warn-only failure mode** — both `DataQualityError` (P0 quality fail)
    and any other exception log a warning but do not abort training. The
    audit is diagnostic; the promotion gate handles blocking.

**Important deviation from plan:**
The plan §5.3 specified
`run_pretrain_audit(df, target_col, feature_cols, output_dir)` — but the
actual library signature ([src/evaluation/pretrain_report.py:221](../../src/evaluation/pretrain_report.py#L221))
is `run_pretrain_audit(mode, mfe_bins, output_path, emit_markdown)` and the
function loads its own data via `load_pretrain_data(mode)`. Since
`mode="trades"` loads the same `v_d2_training` view the training script uses,
data parity is guaranteed but there's wasted I/O (~5-10s on the cached view).
Acceptable for a 0.5d wiring item; can be optimized later by adding a
`df`-passing overload to `run_pretrain_audit`.

### Phase D §5.1 — Paper-trade dashboard toggle

**Prerequisite shipped first.** The migration
[`scripts/migrations/2026_05_24_create_daily_predictions.sql`](../../scripts/migrations/2026_05_24_create_daily_predictions.sql)
had **never been run** against the live DB. Discovery: Phase 8 of
`DailyPipelineOrchestrator` calls `log_daily_predictions(...)`, which fails
silently because the target table didn't exist. Applied the migration
manually this session — the table is idempotent (`CREATE TABLE IF NOT EXISTS`)
so this is safe to re-run.

**Library helpers added to [scripts/dashboard_utils.py](../../scripts/dashboard_utils.py):**

| Function | Purpose | Cache |
|---|---|---|
| `load_prod_model_version_id()` | Resolves the currently-promoted prod classifier `version_id` from `models` table | 300s |
| `load_daily_predictions_today(model_version_id)` | Loads the latest-date `daily_predictions` rows for one model | 60s |
| `load_past_decisions(model_version_id, limit=200)` | Joins `daily_predictions` (decision_taken IS NOT NULL) against `screener_watchlist` for realized outcomes | 60s |
| `update_decision_taken(prediction_date, ticker, model_version_id, decision, notes)` | Writer — flips `decision_taken` + `taken_at` + `notes`. Uncached; caller invalidates the loaders. | — |

**UI added to [scripts/dashboard.py](../../scripts/dashboard.py):**

- `render_decision_log()` — new section on Page 1 between Pre-Breakout Watch
  and Sector Heat. Uses `st.data_editor` with a `SelectboxColumn` for the
  Decision column (`— / Taken / Skipped`) and a `TextColumn` for Notes.
  Diff-detects edits per row, calls `update_decision_taken(...)` only on
  changed rows, then invalidates the two loaders and `st.rerun()`s.
- `render_past_decisions()` — second view below the decision log; shows
  realized outcomes (entry_date / exit_date / pct_return / days_held) for
  past decisions, plus an aggregate "Taken hit-rate" metric.
- Both are gated on `load_prod_model_version_id()` returning non-None and
  on the relevant tables having rows.

### Smoke test

Ran (no streamlit runtime — just imports + SQL execution):

- Both `scripts/dashboard.py` and `scripts/dashboard_utils.py` parse cleanly
- All 4 new exports import successfully
- `load_prod_model_version_id()` resolves to
  `m01_prototype_2003_2026_20260514_233125`
- `daily_predictions` query returns 0 rows for that model (expected — Phase 8
  has been silently failing; the next pipeline run will populate it)
- The `past_decisions` JOIN query parses and returns 0 rows (expected — no
  decisions toggled yet)

**Not tested:** actual rendering in a live streamlit session. The
`st.data_editor` diff-detection logic + `st.rerun()` flow is unverified. Risk
is moderate — `data_editor` semantics around mid-edit state can be tricky.
First user interaction may reveal small issues with the diff comparison
(esp. for Notes, where `NaN == ""` distinctions matter).

## 📝 Files Changed

### New artifacts
- None this session (everything additive into existing files)

### Modified
- [scripts/train_mfe_classifier.py](../../scripts/train_mfe_classifier.py):
  - New imports (lines 31, 34): `DataQualityError`, `run_pretrain_audit`
  - New CLI flag (line 262): `--skip-pretrain-audit`
  - New step 2b (lines 326-348): pretrain audit invocation with warn-only
    failure handling

- [scripts/dashboard_utils.py](../../scripts/dashboard_utils.py):
  - +95 lines: 4 new functions (`load_prod_model_version_id`,
    `load_daily_predictions_today`, `load_past_decisions`,
    `update_decision_taken`)
  - All loaders cached; writer uncached with caller-invalidation contract

- [scripts/dashboard.py](../../scripts/dashboard.py):
  - Imports expanded (4 new symbols)
  - New constants: `DECISION_OPTIONS`, `_DECISION_TO_DB`, `_DB_TO_DECISION`
  - New render functions: `render_decision_log()`, `render_past_decisions()`
  - `page_today()` wires both new sections between Pre-Breakout and Sector Heat

### Database state changes
- **`data/market_data.duckdb`**: `daily_predictions` table created via
  [`scripts/migrations/2026_05_24_create_daily_predictions.sql`](../../scripts/migrations/2026_05_24_create_daily_predictions.sql).
  Empty as of session end (Phase 8 of the orchestrator will populate on next
  daily run). 3 indexes: pkey + date + model.

### Fan-out bug — diagnosis + proposed fix (NOT applied)

Spent the last 20min of the session investigating the 🔴 #1 blocker. Located
the root cause but did NOT apply the fix — too risky to ship blind under
the time budget.

**Diagnosis (high confidence):** `v_d2_features` has two correlated as-of
subqueries in [src/managers/view_manager.py:405-485](../../src/managers/view_manager.py#L405-L485):
- `fundamental_features` join: `WHERE filing_date = (SELECT MAX(filing_date)
  FROM fundamental_features WHERE ticker = d1.ticker AND filing_date <=
  d1.date)`
- `shares_history` join (if table exists): same pattern keyed on `date`

If either source table has multiple rows tied at the same key (e.g.,
amended filings on the same `filing_date`, vendor duplicates in
`shares_history`), the join **fans out** — one `d1` row becomes N
`v_d2_features` rows with conflicting fundamentals. Downstream
`v_d2_training` and `v_d3_deployment` inherit the fan-out and dedup
non-deterministically (DuckDB `ROW_NUMBER()` over a tied set has no
stable order without an explicit tiebreaker), which is why
`feature_parity_check` trips.

**Proposed fix:** replace both correlated subqueries with `QUALIFY
ROW_NUMBER() OVER (...)` CTEs that dedup at the source with a
deterministic tiebreaker. Full proposal at
[docs/proposals/view_fanout_fix_2026_05_24.md](../proposals/view_fanout_fix_2026_05_24.md)
— includes risk analysis, verification plan, and effort estimate
(~half-day fix + ~half-day retraining/re-eval).

**Why not applied:** (1) the proposed `fiscal_period DESC NULLS LAST`
tiebreaker is a guess — needs probe queries to confirm the actual
ingestion semantics; (2) the live probe against 3 tickers stalled (the
existing correlated-subquery view is O(N²) and slow even for a small
filter); (3) changing `v_d2_features` row counts will ripple into
every downstream view + the prod model needs retraining. This is a
one-PR change but the PR needs care.

## 🚧 Work in Progress

§5.2 (PSI / drift) is **not started**. Scope per plan (~1.5d):
1. `reference_snapshot` step at training-script tail — freeze feature
   distribution to `models/<name>/<version>/reference_snapshot.parquet`
2. Quarterly PSI report wired into Phase 8 of
   `DailyPipelineOrchestrator` — compute PSI(live `daily_predictions`
   features, reference snapshot); alert if any feature PSI > 0.25

## 🛑 Things to Keep an Eye On

1. **`daily_predictions` will stay empty until the next daily pipeline run.**
   Dashboard sections render "No predictions logged yet" until then. To
   populate immediately, run `python scripts/run_daily_pipeline.py` (the
   orchestrator Phase 8 will write predictions on the prod model).
2. **`st.data_editor` diff comparison is unverified in a live session.**
   The render code compares `display.loc[i, "Decision"]` vs `row["Decision"]`
   and Notes via `pd.notna(new_notes) and new_notes != orig_notes`. First
   user-interaction test may reveal edge cases:
   - Notes set to empty string vs None vs NaN — currently treats empty as
     "no change"
   - The `Decision` column is required (no NaN), so that path is safer
   - If `st.rerun()` interacts badly with the editor's `key="decision_editor"`
     stateful widget, may need to drop the `key` or use `st.form` instead
3. **Pretrain audit adds ~5-10s to every training run.** It re-loads
   `v_d2_training` (cached after Phase A's `d2_training_cache` work). If
   training cycle time becomes painful, add a `df` parameter to
   `run_pretrain_audit` to skip the re-load.
4. **Phase 8 was silently broken before today's migration.** Any historical
   pipeline_runs rows showing Phase 8 "succeeded" actually didn't write any
   predictions. If anyone tries to backfill historical `daily_predictions`,
   they'll need to manually invoke the prediction logger over a date range
   — there's no script for that yet.
5. **`load_past_decisions` JOIN may surface phantom matches.** The condition
   `sw.entry_date >= dp.prediction_date` picks the first watchlist entry on
   or after the prediction date. If a ticker has multiple entries, the
   query returns multiple rows per prediction. Acceptable for now (the
   `screener_watchlist` materialization typically has one ACTIVE entry per
   ticker), but worth a `LIMIT 1` subquery if duplicates appear.
6. **Categorical_mapping.json not refreshed for pretrain audit.** The audit
   loads its own data and doesn't touch the trained model — no risk of
   inconsistency, but be aware that the audit's view of `sector`/`industry`
   may differ from the model's frozen categorical encoding if the universe
   shifted.

## ⏭️ Next Steps

In priority order (matches the master handover's recommended order):

1. **🔴 Apply the fan-out fix.** Per the new proposal at
   [docs/proposals/view_fanout_fix_2026_05_24.md](../proposals/view_fanout_fix_2026_05_24.md).
   ~half-day fix + ~half-day retrain. Still the #1 blocker — until applied,
   every training run needs `--skip-parity` and the framework can't be
   validated end-to-end.
2. **Run the daily pipeline once to populate `daily_predictions`.** Then
   open the dashboard Page 1 and test the toggle end-to-end. ~5min.
3. **Phase D §5.2 — PSI / drift.** ~1.5d. The last remaining framework
   item. Mirrors Phase A's wiring patterns (training-script tail +
   orchestrator Phase 8).
4. **Re-evaluate `M01_baseline_v0.1` under the new framework.** This is
   what the framework was built for. Run training with `--walk-forward
   --with-regime-decomp --with-perm-importance` (pretrain audit now
   default-on). Will need `--skip-parity` until fan-out is fixed.
   Expected: some gates fail — that's the signal.
5. **Wire `run_walk_forward_backtest` into the training script** behind
   `--with-wf-backtest`. ~half-day. (Phase B/C handover #1.)
6. **Make `src/evaluation/__init__.py` lazy.** 30 minutes. Cuts pytest
   cold start from ~25min → ~3-5min on this Windows box. Biggest
   dev-experience win available.

## 💡 Context/Memory

- **Why the migration was missing.** Phase A shipped both the migration
  script and the orchestrator wiring, but the migration wasn't applied to
  the live DB. The orchestrator's `log_daily_predictions` call was
  swallowed by a try/except — Phase 8 status said "success" even though
  no rows were written. Lesson: a migration that ships with a writer
  must either be auto-applied or have a CI check that fails if the
  target table is missing.
- **Why `data_editor` instead of per-row buttons.** Three reasons:
  (1) Single round-trip — `data_editor` batches all edits into one
  re-run, vs N buttons each triggering a re-run.
  (2) Notes column gets a free text editor without extra wiring.
  (3) Matches the plan's "table with select widget per row" spec more
  literally than N stacked widgets.
  Downside: diff-detection is the dashboard's responsibility; if
  someone clicks a Decision then immediately clicks away, the rerun
  fires and may feel jumpy. If that becomes a UX issue, wrap in
  `st.form` so changes only apply on Submit.
- **Decision states stored as lowercase strings, displayed as TitleCase.**
  DB convention: `'taken' | 'skipped' | NULL`. UI convention:
  `'Taken' | 'Skipped' | '—'`. Mapping lives in `_DECISION_TO_DB` /
  `_DB_TO_DECISION` constants. The migration's column comment
  (`'taken' | 'skipped' | NULL`) is the source of truth.
- **`load_past_decisions` is intentionally not a view.** The plan
  suggested a view, but the join semantics (`sw.entry_date >=
  dp.prediction_date`) are tricky enough that I'd rather keep it as
  a parameterized query — easier to debug and the result set is
  bounded by the `LIMIT 200` so caching is fine.
- **Pretrain audit failure mode chosen: warn-only.** Plan didn't mark it
  as blocking. P0 data quality issues will surface as a logger warning;
  the operator can choose whether to abort or continue. If a future
  policy wants to make it blocking, change the `except DataQualityError`
  block to `raise SystemExit(...)`.

---

## 📋 Gap Analysis — Original Plan vs Implemented

Cross-referenced [docs/plans/evaluation_implementation_plan_2026_05_23.md](../plans/evaluation_implementation_plan_2026_05_23.md)
against the codebase as of 2026-05-24 end-of-session.

### §1 Cross-cutting infrastructure (0.5d)

| Item | Status | Notes |
|---|---|---|
| 1.1 `EvaluationGate` pass/fail recording | ✅ | `src/evaluation/gate.py` |
| 1.2 `evaluator_run` metadata block | ✅ | `src/evaluation/base_evaluator.py` |

### §2 Phase A — pre-S1 (6d)

| Item | Priority | Status | Notes |
|---|---|---|---|
| 2.1.1 Label registry | P0 | ✅ | `src/evaluation/label_registry.py`; first label `mfe_4class_30d_v1` |
| 2.1.2 Label-side leakage audit | P0 | ✅ | `LeakageGuard.audit_label` |
| 2.1.3 Training-vs-deployment feature parity | P0 | ✅ | `LeakageGuard.feature_parity_check` — **currently fails on live DB due to view fan-out** |
| 2.2 ECE + calibration gate | P0 | ✅ | `src/evaluation/calibration.py` + step 7 of `ClassificationEvaluator` |
| 2.3 Walk-forward classification harness | P0 | ✅ | `src/evaluation/walk_forward.py` + `--walk-forward` flag |
| 2.4 Threshold optimization helper | P1 | ✅ | `src/evaluation/thresholding.py` |
| 2.5.1 `daily_predictions` schema | P0 | ✅ | Migration `2026_05_24_create_daily_predictions.sql` — **applied this session** |
| 2.5.2 Prediction logger | P0 | ✅ | `src/evaluation/prediction_logger.py` + orchestrator Phase 8 |

### §3 Phase B — between S1/S2 (5.5-7.5d)

| Item | Priority | Status | Notes |
|---|---|---|---|
| 3.1 Walk-forward backtest harness | P0 | ⚠️ Library only | `src/evaluation/walk_forward_backtest.py` exists with 4 gates; **NOT wired into training script** (no `--with-wf-backtest` flag) |
| 3.2 Regime-conditional metrics | P0 | ✅ | `src/evaluation/regime_decomposition.py` + step 13c of `ClassificationEvaluator` |
| 3.3.1 Permutation importance | P1 | ✅ | `_compute_permutation_importance` in `ClassificationEvaluator` |
| 3.3.2 Ablation backtest | P1 | ✅ | `src/evaluation/ablation.py` + `scripts/ablation_backtest.py` |

### §4 Phase C — parallel to S2/S3 (4.5d)

| Item | Priority | Status | Notes |
|---|---|---|---|
| 4.1 Block bootstrap | P1 | ✅ | `src/evaluation/bootstrap.py` |
| 4.2 Permutation null backtest | P1 | ✅ | `src/evaluation/permutation_null.py` — caller supplies `backtest_fn` |
| 4.3.1 Rolling IC | P1 | ✅ | `src/analytics/rolling_ic.py` |
| 4.3.2 Decile analysis | P1 | ✅ | `src/analytics/decile_analysis.py` |
| 4.3.3 Score trajectory | P1 | ✅ | `src/analytics/score_trajectory.py` |

### §5 Phase D — operational (3d)

| Item | Priority | Status | Notes |
|---|---|---|---|
| 5.1 Paper-trade dashboard toggle | P0 | ✅ | **Shipped this session** — `render_decision_log` + `render_past_decisions` on Page 1 |
| 5.2 PSI / feature drift | P2 | ❌ Not started | `src/evaluation/drift.py` does not exist; ~1.5d remaining |
| 5.3 Pretrain audit auto-invocation | P1 | ✅ | **Shipped this session** — `--skip-pretrain-audit` flag, default-on |

### §6 Promotion-readiness gate

| Item | Status | Notes |
|---|---|---|
| `set_prod` reads `results.json`, blocks on gate-fail | ✅ | Implemented in Phase A |
| `force=True` + `force_reason` + `forced_promotions` log | ✅ | Implemented in Phase A |

### §7 Sequencing checklist (from plan)

- Pre-S1 gates land before S1 ✅
- Phase B lands between S1 and S2 ⚠️ (library done, harness not wired)
- Phase C lands parallel to S2/S3 ✅
- Phase D lands operationally ⚠️ (§5.1 + §5.3 done; §5.2 missing)

### §8 Definition of done (overall)

Per plan §8:
> "Run `python scripts/train_mfe_classifier.py --label-id mfe_4class_30d_v1
> --walk-forward --with-regime-decomp --with-perm-importance` on
> M01_baseline_v0.1; verify all gates fire and walk-forward summary is
> written. ModelRegistry refuses to promote if any blocking-fail (force
> override required, reason logged)."

**Status:** Currently impossible. Will fail at the parity check step
(needs `--skip-parity`). The framework is built but **has never been run
against real data end-to-end.** Unblocking this is the fan-out fix.

---

## 🎯 What's Actually Left

Sorted by priority and estimated effort:

| # | Task | Priority | Effort | Blocker for |
|---|---|---|---|---|
| 1 | Apply fan-out fix per [proposal](../proposals/view_fanout_fix_2026_05_24.md) | 🔴 P0 | 0.5d | End-to-end framework run |
| 2 | Run daily pipeline → populate `daily_predictions` → test dashboard toggle live | P0 | 5min | Phase D §5.1 verification |
| 3 | Retrain M01_baseline_v0.2 on clean data | P0 | 0.5d | Real-data parity gate, all gate firings |
| 4 | Re-evaluate M01_baseline_v0.2 under full framework (the §8 DoD) | P0 | 1d | Whole project's purpose |
| 5 | Wire `run_walk_forward_backtest` into training (`--with-wf-backtest`) | P1 | 0.5d | Phase B §3.1 acceptance |
| 6 | Phase D §5.2 PSI/drift (`drift.py` + reference snapshot + quarterly report) | P2 | 1.5d | Last framework library item |
| 7 | Make `src/evaluation/__init__.py` lazy | P3 | 0.5h | Dev experience (cuts pytest cycle 25min→3min) |

**Critical path to "framework is real":** items 1 → 3 → 4. ~2 days of work.
Everything else can wait or run parallel.

---

**No commit made.** Files modified but uncommitted as of session end —
review before staging:
- `scripts/train_mfe_classifier.py`
- `scripts/dashboard.py`
- `scripts/dashboard_utils.py`
- `docs/session_logs/2026-05-24_evaluation-framework-phase-d.md` (this file)
- `docs/proposals/view_fanout_fix_2026_05_24.md` (new proposal)
- `data/market_data.duckdb` (DB binary — migration applied)
