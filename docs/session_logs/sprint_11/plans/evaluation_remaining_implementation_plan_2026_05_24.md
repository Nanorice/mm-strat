# Evaluation Framework — Remaining Items Implementation Plan

> **Created:** 2026-05-24
> **Owner:** Hang
> **Status:** Draft for review.
> **Companion docs:**
>   • [`evaluation_implementation_plan_2026_05_23.md`](evaluation_implementation_plan_2026_05_23.md)
>     — original plan (Phases A/B/C/D scope).
>   • [`../proposals/view_fanout_fix_2026_05_24.md`](../proposals/view_fanout_fix_2026_05_24.md)
>     — diagnosis + fix for the #1 blocker.
>   • [`../session_logs/2026-05-24_evaluation-framework-phase-d.md`](../session_logs/2026-05-24_evaluation-framework-phase-d.md)
>     — Phase D session handover with gap analysis.

---

## 0. How to use this document

This plan covers ONLY the items still outstanding after the 2026-05-24
session. Each item uses the same shape as the original plan:

| Field | Meaning |
|---|---|
| **Module** | Concrete file path + new vs. modified |
| **API** | Function/class signatures with types |
| **Inputs** | Where the data comes from |
| **Outputs** | What gets written (file, table, JSON, plot) |
| **Integration** | Where it gets wired into the existing pipeline |
| **Acceptance test** | The concrete check that says "this is done" |
| **Effort** | Days |
| **Depends on** | Other items that must land first |

**Convention:** every new evaluator/library module returns a JSON-serializable
`dict` matching the `ClassificationEvaluator.evaluate` pattern, and writes
artifacts under `models/<name>/<version>/evaluation/` (or `logs/` for
operational outputs).

---

## 1. The critical path (~2 days total)

These four items unblock the original plan's §8 Definition of Done. Run them
in order — each depends on the previous.

### 1.1 Fan-out fix on `v_d2_features`  *(P0, 0.5d)*

**Module.** Modify [`src/managers/view_manager.py`](../../src/managers/view_manager.py)
(`_create_v_d2_features`, lines 405-485).

**Change.** Replace the two correlated as-of subqueries (`fundamental_features`
and `shares_history`) with `QUALIFY ROW_NUMBER() OVER (...)` CTEs that dedup
at the source with a deterministic tiebreaker.

**Proposed SQL shape.**
```sql
CREATE OR REPLACE VIEW v_d2_features AS
WITH ff_dedup AS (
    SELECT ticker, filing_date, fiscal_period, revenue, net_income, ...
    FROM fundamental_features
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY ticker, filing_date
        ORDER BY fiscal_period DESC NULLS LAST  -- TBD, verify with probe
    ) = 1
),
ff_asof AS (
    SELECT d1.ticker, d1.date AS d1_date, ff.*
    FROM v_d1_candidates d1
    INNER JOIN ff_dedup ff
        ON ff.ticker = d1.ticker AND ff.filing_date <= d1.date
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY d1.ticker, d1.date
        ORDER BY ff.filing_date DESC
    ) = 1
),
sh_dedup AS (
    SELECT ticker, date, shares_outstanding
    FROM shares_history
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY ticker, date
        ORDER BY <tiebreaker — TBD via probe>
    ) = 1
),
sh_asof AS (
    SELECT d1.ticker, d1.date AS d1_date, sh.shares_outstanding
    FROM v_d1_candidates d1
    INNER JOIN sh_dedup sh
        ON sh.ticker = d1.ticker AND sh.date <= d1.date
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY d1.ticker, d1.date
        ORDER BY sh.date DESC
    ) = 1
)
SELECT
    d1.*,
    ff.revenue, ff.net_income, ff.eps_diluted, ...,
    cp.market_cap,
    COALESCE(sh.shares_outstanding, cp.shares_outstanding) AS shares_outstanding,
    -- Valuation ratios stay the same
    ...
FROM v_d1_candidates d1
LEFT JOIN company_profiles cp ON d1.ticker = cp.ticker
LEFT JOIN ff_asof ff ON d1.ticker = ff.ticker AND d1.date = ff.d1_date
LEFT JOIN sh_asof sh ON d1.ticker = sh.ticker AND d1.date = sh.d1_date
```

**Probe queries (run before applying the fix).**
```sql
-- 1. Confirm fundamental_features has dups
SELECT ticker, filing_date, fiscal_period, COUNT(*) AS n
FROM fundamental_features
WHERE ticker IN ('AAPL', 'NVDA', 'TSLA')
GROUP BY 1, 2, 3
HAVING COUNT(*) > 1
LIMIT 20;

-- 2. Confirm shares_history has dups (if table exists)
SELECT ticker, date, COUNT(*) AS n
FROM shares_history
WHERE ticker IN ('AAPL', 'NVDA', 'TSLA')
GROUP BY 1, 2
HAVING COUNT(*) > 1
LIMIT 20;

-- 3. Confirm v_d2_features currently fans out (post-build, against the OLD view)
SELECT ticker, date, COUNT(*) AS n
FROM v_d2_features
WHERE ticker IN ('AAPL', 'NVDA', 'TSLA') AND date >= '2025-01-01'
GROUP BY 1, 2
HAVING COUNT(*) > 1
LIMIT 20;
```

**Strategy.**
1. Build the new view in parallel as `v_d2_features_v2` (preserve old view during testing).
2. Compare row counts: old vs new.
3. Spot-check 10 (ticker, date) pairs that fan out in old — confirm new returns exactly 1 row.
4. Re-run `feature_parity_check` against `v_d2_features_v2` + `v_d3_deployment_v2`. Expect: gate passes.
5. Cut over: `CREATE OR REPLACE VIEW v_d2_features` with the new SQL.
6. Refresh `d2_training_cache` (the materialized version of `v_d2_training`).

**Integration.**
- `view_manager.py::_create_v_d2_features` — replace SQL body.
- `view_manager.py::create_all()` — no change (downstream views recreate automatically).
- `scripts/refresh_training_cache.py` — re-run after fix to materialize cleaned data.

**Acceptance test.**
- New test file `test/test_view_fanout.py`:
  - Insert synthetic `fundamental_features` rows with deliberate dups
  - Build `v_d2_features` via view_manager
  - Assert `SELECT COUNT(*) FROM v_d2_features GROUP BY ticker, date HAVING COUNT(*) > 1` returns zero rows
- Manual: `feature_parity_check` against live DB passes without `--skip-parity`.

**Effort.** 0.5d (incl. probe + parallel-build + verification).

**Depends on.** Nothing.

---

### 1.2 Run daily pipeline → populate `daily_predictions`  *(P0, 5 min)*

**Module.** None — operational task.

**Command.**
```powershell
python scripts/run_daily_pipeline.py
```

**Why this is here.** The `daily_predictions` table was created this session
but the orchestrator hasn't run since the migration. Without this step:
- The dashboard `render_decision_log` section will show "No predictions
  logged yet" until tomorrow's scheduled run
- The dashboard toggle has nothing to flip
- Phase D §5.1 can't be UAT'd

**Acceptance test.**
```sql
SELECT COUNT(*) FROM daily_predictions
WHERE prediction_date = CURRENT_DATE;
-- Expect > 0
```

Then: open `streamlit run scripts/dashboard.py`, navigate to Today page,
verify the "Today's Predictions — Decision Log" section renders rows.
Toggle one ticker to Taken, refresh, confirm persistence.

**Effort.** 5 min (pipeline run is ~3 min; dashboard verify is ~2 min).

**Depends on.** Item 1.1 (otherwise the prediction logger writes data based
on a fan-out-tainted feature set, and we'd need to re-do this).

---

### 1.3 Retrain `M01_baseline_v0.2` on clean data  *(P0, 0.5d)*

**Module.** None — operational. Use existing
[`scripts/train_mfe_classifier.py`](../../scripts/train_mfe_classifier.py).

**Command.**
```powershell
python scripts/train_mfe_classifier.py `
  --feature-set fs_m01_prototype `
  --model-name m01_baseline `
  --model-version v0.2 `
  --label-id mfe_4class_30d_v1 `
  --walk-forward `
  --with-regime-decomp `
  --with-perm-importance `
  --promote-prod
```

**Why.** The current prod model (`m01_prototype_2003_2026_20260514_233125`)
was trained on data with the fan-out bug. Its weights average over the
inconsistency. The post-fix retrain produces a model whose probabilities
are reproducible across runs.

**Notable absences from the command.** No `--skip-parity` (should pass
naturally) and no `--skip-pretrain-audit` (audit runs by default per §5.3).

**Acceptance test.**
- Training completes without errors
- `feature_parity_check` status = "pass" in the logs
- `results.json` contains the expected gates (calibration, regime decomp,
  walk-forward AUC) with values (not "skipped")
- `models/m01_baseline/v0.2/pretrain_audit.html` exists (per §5.3)
- `models/m01_baseline/v0.2/folds/` populated with per-fold artifacts
- `models/m01_baseline/v0.2/evaluation/walk_forward_summary.json` exists
- Model registered in `models` table with `status_flag='prod'`

**Effort.** 0.5d (mostly training wallclock; setup is minimal).

**Depends on.** Item 1.1.

---

### 1.4 Full framework re-evaluation — §8 DoD  *(P0, 1d)*

**Module.** None — analytical task. Uses Phase B/C library modules.

**What to do.** Run each framework component against `M01_baseline_v0.2` and
verify gate results match expectations. This is the original plan's §8 DoD.

**Subtasks.**
1. **Standalone evaluation review.** Read `results.json` and confirm:
   - Calibration ECE on production class < 0.15
   - Per-regime AUC ≥ 0.55 in at least 3 of 5 regimes (per §3.2 gate config)
   - Walk-forward worst-fold AUC ≥ 0.65
   - Pretrain audit `quality.passed = True` (or document the failure mode)
2. **Walk-forward backtest** (manually invoke `run_walk_forward_backtest`
   against the folds produced in 1.3). 4 gates must fire:
   - `wf_backtest_mean_sharpe` > 0.5
   - `wf_backtest_worst_sharpe` > -0.3 AND ≥ N/9·7 positive folds
   - `wf_backtest_worst_max_drawdown` < 35%
   - `wf_backtest_mean_top_3_home_run_lift` > 5×
3. **Bootstrap CI on standalone backtest trades.** Run
   `circular_block_bootstrap(trades_df, sharpe_from_trades, n_iterations=10_000)`.
   Report (observed, median, CI).
4. **Permutation null backtest** (deep mode, 1000 perms):
   `permutation_null_backtest(signals_df, backtest_fn, n_permutations=1000)`.
   Gate must pass: percentile > 95.
5. **Ablation backtest** (one per major feature group): run
   `scripts/ablation_backtest.py --feature-groups Momentum,Volume,Volatility,Fundamentals`.
   Inspect deltas; verify no single group accounts for all the alpha.
6. **Rolling IC / decile analysis** for sanity-check shape of the signal.
7. **Decide.** Compile a one-pager: "Does M01_baseline_v0.2 promote, hold, or
   demote?" with the gate results as evidence.

**Outputs.**
- `models/m01_baseline/v0.2/evaluation/full_eval_report.md` — the one-pager
- Updates to `results.json` from Phase B/C re-runs
- If gates fail and the decision is "demote": revert `set_prod` to v0.1 (or
  whichever earlier model was prod)

**Acceptance test.** This IS the acceptance test for the entire framework.

**Effort.** 1d (mostly waiting on the 1000-perm null backtest — ~8h with
`SEPABacktestRunner`, ~10s with the numpy fast-path that doesn't exist yet).

**Depends on.** Item 1.3.

---

## 2. Outstanding library work (parallel to the critical path)

These items can run in parallel to the critical path. They don't unblock §8
DoD but they're remaining items from the original plan.

### 2.1 Wire walk-forward backtest into training script  *(P1, 0.5d)*

**Module.** Modify [`scripts/train_mfe_classifier.py`](../../scripts/train_mfe_classifier.py).

**Change.** Add `--with-wf-backtest` flag. When set + `--walk-forward` is also
set, call `run_walk_forward_backtest(...)` on the fold results, then
`aggregate_walk_forward_backtest(...)`. Merge resulting gates into
`results.json` (same pattern as `_run_walk_forward_block`).

**API additions.**
```python
parser.add_argument("--with-wf-backtest", action="store_true",
                    help="Run per-fold backtest on walk-forward folds. Requires --walk-forward.")
parser.add_argument("--wf-backtest-output", default=None,
                    help="Output dir for per-fold backtest artifacts (default: model_dir/wf_backtest/)")
```

**New helper in script.**
```python
def _run_walk_forward_backtest_block(
    fold_results: list[FoldResult],
    model_dir: Path,
    class_names: list[str],
    db_path: Path,
) -> dict:
    """Invokes run_walk_forward_backtest with a SEPABacktestRunner closure.

    Wraps each fold's signals into a backtest call via default_signals_to_scores.
    Writes per-fold output to model_dir / 'wf_backtest' / 'fold_<idx>' /.
    Returns aggregated dict with `gates` list to merge into results.json.
    """
```

**Integration.** Hook into the existing `if args.walk_forward:` block in
`main()` — right after `_run_walk_forward_block` returns the fold results.

**Caveats from Phase B/C handover.**
- `default_signals_to_scores` expects `date` + `ticker` in `X_test`; the
  training script strips them. Need to re-attach.
- `categorical_mapping.json` is not regenerated per ablation/fold — workaround:
  reuse the baseline mapping.
- `UniverseScorer._m01_features = feature_cols` may not be respected on all
  code paths — verify before relying.

**Acceptance test.** Run training with both flags; verify
`models/<name>/<version>/wf_backtest/fold_<idx>/{trades,equity,metrics}.{parquet,json}`
populates for each fold and `results.json` gains 4 new gate entries.

**Effort.** 0.5d.

**Depends on.** Item 1.1 (otherwise WF-backtest also trains on tainted data).

---

### 2.2 PSI / feature drift  *(P2, 1.5d)*

**Module.** [`src/evaluation/drift.py`](../../src/evaluation/drift.py) (new).

**API.**
```python
def compute_psi(
    reference: np.ndarray,
    current: np.ndarray,
    bins: int = 10,
    epsilon: float = 1e-6,
) -> float:
    """PSI = sum_i (curr_pct_i - ref_pct_i) * ln(curr_pct_i / ref_pct_i).

    Bins from reference quantiles (so the binning is fixed at training time).
    NaN handling: drop NaNs from both arrays before binning.
    """

def reference_snapshot(
    train_df: pd.DataFrame,
    feature_cols: list[str],
    output_path: Path,
    bins: int = 10,
) -> dict:
    """Save per-feature quantile bin edges + reference bin counts.

    Called once at training time. Output JSON shape:
    {
        "n_rows": int,
        "n_features": int,
        "bins": int,
        "features": {
            "<feature_name>": {
                "bin_edges": [float, ...],   # length bins+1
                "ref_counts": [int, ...],    # length bins
                "n_missing": int,
            }
        },
        "created_at": iso8601,
        "model_version_id": str | None,
    }
    """

def quarterly_drift_report(
    reference_snapshot_path: Path,
    current_view: str,
    db_path: Path,
    quarter: str,
    psi_alert_threshold: float = 0.25,
    psi_warn_threshold: float = 0.10,
) -> dict:
    """Compute PSI per feature for the current quarter. Returns:
    {
        "quarter": "2026Q1",
        "model_version_id": str,
        "n_features_checked": int,
        "n_features_drifted": int,        # PSI > 0.25
        "n_features_warned": int,         # 0.10 < PSI <= 0.25
        "per_feature": {
            "<name>": {"psi": float, "status": "ok"|"warn"|"drifted"}
        },
        "drifted_features": [list],
        "gates": [{"name": "psi_drift", "status": "pass"|"fail", "value": int}],
    }
    """
```

**Why frozen reference.** Rolling baseline drifts in lockstep with the data
and hides the drift we want to detect. Each model's `reference_snapshot.json`
is its own immutable baseline (per gap-analysis decision #4 in the original
plan).

**Integration.**
1. **Training script tail.** After `model.save_model(...)` in step 9 of
   `train_mfe_classifier.py::main`, call
   `reference_snapshot(X_train, valid_features, model_dir / "reference_snapshot.json")`.
   Co-located with model artifacts, frozen at promotion time.
2. **Daily pipeline Phase 8.** Conditional invocation — only when
   `today.day in (1) and today.month in (1, 4, 7, 10)` (quarterly start). Call
   `quarterly_drift_report(reference_snapshot_path=<prod_model>/reference_snapshot.json,
   current_view="v_d3_deployment", quarter=<computed>, db_path=...)`. Write to
   `logs/drift/<quarter>.json`.
3. **Pipeline Health dashboard page.** Add a "Feature Drift" section that
   reads the latest `logs/drift/<quarter>.json` and surfaces drifted features
   with a color-coded table.

**Acceptance test.** New `test/test_drift.py`:
- Two synthetic distributions:
  - identical → PSI ≈ 0 (< 0.01)
  - shifted by 1σ → PSI > 0.25
- Edge cases: empty arrays (raise), all-NaN reference (raise), bins with zero
  current count (clamp via epsilon, no inf)
- `reference_snapshot` round-trip: save and reload JSON, verify bin edges match
- `quarterly_drift_report` against a fixture DB with 1 drifted feature →
  `drifted_features` list contains exactly that feature

**Effort.** 1.5d (1d library + tests, 0.5d wiring + dashboard surface).

**Depends on.** Nothing (independent of fan-out fix — PSI snapshots are
keyed to the model version that saved them, and a clean retrain (item 1.3)
naturally produces a clean baseline).

---

## 3. Operational polish (deferrable)

### 3.1 Make `src/evaluation/__init__.py` lazy  *(P3, 0.5h)*

**Module.** [`src/evaluation/__init__.py`](../../src/evaluation/__init__.py).

**Change.** Eager re-exports in this file trigger
`m03_evaluator` → `m03_regime` → `macro_engine` → `yfinance` even when only
one small library module is needed. On Windows + Defender real-time scanning,
this makes pytest cycle ~25min cold.

**Fix.** Either:
1. Switch to lazy imports via `__getattr__` (PEP 562), or
2. Remove the eager re-exports entirely — they're convenience aliases, not
   load-bearing. Callers do `from src.evaluation.X import Y` already.

**Acceptance test.** `pytest tests/test_bootstrap.py` cold-start drops from
~25min to ~3-5min wall clock.

**Effort.** 0.5h.

**Depends on.** Nothing.

---

### 3.2 Backfill historical `daily_predictions`  *(P3, 0.5d, optional)*

**Module.** New script
[`scripts/backfill_daily_predictions.py`](../../scripts/backfill_daily_predictions.py)
(new, ~80 lines).

**Why.** Phase 8 of the orchestrator was silently broken until 2026-05-24 when
the migration landed. There are no historical predictions, so the dashboard's
"Performance of past decisions" view is empty even for the M01 prod model
that's been running.

**API sketch.**
```python
def backfill_predictions(
    db_path: Path,
    model_version_id: str,
    start_date: date,
    end_date: date,
) -> int:
    """Re-run `log_daily_predictions` for each date in [start_date, end_date].

    Loads v_d3_deployment per date, scores with the named model, writes to
    daily_predictions. Idempotent via PK upsert. Returns total rows written.
    """
```

**Integration.** CLI:
```powershell
python scripts/backfill_daily_predictions.py `
  --model-version m01_baseline_v0.2_20260524 `
  --start 2026-01-01 --end 2026-05-24
```

**Acceptance test.** After backfill, `SELECT COUNT(DISTINCT prediction_date)
FROM daily_predictions` returns the number of trading days in the range.

**Effort.** 0.5d.

**Depends on.** Item 1.3 (no point backfilling against the tainted v0.1 model).

---

## 4. Sequencing and dependencies

```
Critical path (run in order, ~2d):
  1.1 fan-out fix
    └─→ 1.2 daily pipeline run (5min)
    └─→ 1.3 retrain M01_baseline_v0.2 (0.5d)
          └─→ 1.4 full framework re-eval (1d) ← §8 DoD met here

Parallel tracks (can start anytime after 1.1):
  2.1 wire WF-backtest into training (0.5d) — needs 1.1
  2.2 PSI/drift library + wiring (1.5d) — independent

Deferrable polish:
  3.1 lazy __init__ (0.5h) — anytime
  3.2 backfill historical predictions (0.5d) — after 1.3
```

**Recommended order if working alone:**
1. 1.1 → 1.2 → 1.3 (back-to-back, ~1 day)
2. 1.4 (the validation pass — 1 day)
3. 2.2 (last remaining framework item — 1.5 days)
4. 2.1 + 3.1 + 3.2 (cleanup — 1.5 days total)

**Total remaining effort:** ~5-6 days of focused work for everything; the
critical path alone is ~2 days.

---

## 5. Definition of done — overall

This plan is complete when:

1. `python scripts/train_mfe_classifier.py --label-id mfe_4class_30d_v1
   --walk-forward --with-regime-decomp --with-perm-importance --with-wf-backtest`
   on `M01_baseline_v0.2` runs **without `--skip-parity`** and all gates fire
   with real values.
2. `ModelRegistry().set_prod(version_id)` either promotes (all gates pass)
   or refuses with a clear reason (failing gates listed).
3. The Today dashboard page shows today's predictions with a working
   Decision toggle that persists across refreshes.
4. `logs/drift/<quarter>.json` is being written for the current quarter (if
   the date is past the first quarterly mark since 2.2 landed).
5. The whitepaper §5 acceptance criteria can be reproduced from a single
   command (per the original plan §8).

When all five hold, the evaluation framework is **operationally live** and
the project's evaluation rigor matches the whitepaper's academic-grade target.

---

## 6. Open questions for sign-off

1. **Fan-out tiebreaker for `fundamental_features`.** The proposal suggests
   `ORDER BY fiscal_period DESC NULLS LAST`. Confirm this matches the actual
   ingestion semantics with a probe before applying. If
   `fiscal_period` is missing or has surprising values for amended filings,
   may need `ORDER BY ingested_at DESC` or `ORDER BY <source_column> DESC`.
2. **Tiebreaker for `shares_history`.** Currently unknown. Need to inspect
   the schema and decide. If only `(ticker, date)` are unique-ish, may need
   to fall back to `MAX(shares_outstanding)` or `MIN(rowid)`.
3. **Whether to demote the current prod model after 1.4.** If the new
   model's gates fail, do we (a) revert to the pre-framework state, (b)
   keep prod as-is and flag the gap, or (c) promote anyway with
   `force=True` and document the reasoning? Decide upfront so the workflow
   is clear.
4. **PSI quarterly trigger or manual?** §2.2 proposes auto-fire on the 1st
   of Jan/Apr/Jul/Oct. Alternative: manual via a `scripts/run_drift_report.py`
   CLI, with the orchestrator just nudging via log message. Cron-on-the-1st
   is more reliable but more code; manual is simpler but easier to forget.
5. **Backfill scope (3.2).** If we backfill, from when? Earliest sensible
   date is when the current prod model was trained (2026-05-14). Earlier
   than that, the predictions would be retroactive on a model that didn't
   yet exist — analytically meaningless.

---

## 7. What this plan deliberately does NOT cover

- **M01_v2_binary modelling sprint.** Per the whitepaper, S1 is the next
  modelling work after evaluation. That's a separate plan.
- **Dashboard Page 2 (Ticker Deep Dive).** Tracked in the dashboard
  implementation plan, not the evaluation framework.
- **Numpy fast-path for `permutation_null_backtest`.** Phase B/C handover
  flagged this as an expansion (~2.5d). Defer until/unless 1000-perm runs
  become operationally painful.
- **Triangulation gate flip to blocking.** Phase B/C ships it as
  non-blocking by design. If a future policy wants it blocking, the flip is
  a 1-line change in `src/evaluation/ablation.py`.
