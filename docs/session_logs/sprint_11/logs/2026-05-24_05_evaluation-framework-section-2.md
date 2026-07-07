# Session Handover: 2026-05-24 — Section 2 (library work) Complete

## 🎯 Goal
Execute Section 2 of
[docs/plans/evaluation_remaining_implementation_plan_2026_05_24.md](../plans/evaluation_remaining_implementation_plan_2026_05_24.md)
— the parallel-to-critical-path library items (2.1 WF-backtest wiring,
2.2 PSI/drift library, 3.1 lazy `__init__`) — while the user runs the
operational critical path (Steps 1/2/3 from the prior handover).

## ✅ Accomplished

### 2.1 — Walk-forward backtest wired into training script

[scripts/train_mfe_classifier.py](../../scripts/train_mfe_classifier.py):

- **New CLI flags:** `--with-wf-backtest`, `--wf-backtest-output`,
  `--wf-backtest-initial-cash`
- `_run_walk_forward_block` now returns `(agg, fold_results)` and **re-attaches
  `date` + `ticker` to each fold's `X_test`** post-hoc (since `run_walk_forward`
  strips non-feature cols). Ticker stashed on the panel as `__ticker__` to
  avoid colliding with feature_cols.
- New helper `_run_walk_forward_backtest_block` builds a `SEPABacktestRunner`
  closure as the `backtest_fn` (model_path=None — scores_df from the fold's
  classifier is passed directly, so the runner doesn't re-score), calls
  `run_walk_forward_backtest` then `aggregate_walk_forward_backtest`, and
  merges the 4 gates into `results.json`:
  - `wf_backtest_mean_sharpe`
  - `wf_backtest_worst_sharpe`
  - `wf_backtest_worst_max_drawdown`
  - `wf_backtest_mean_top_3_home_run_lift`
- Wrapped in try/except — backtest failures don't kill training
- All 15 existing `tests/test_walk_forward_backtest.py` tests still pass

### 2.2 — PSI / feature drift library

**New module** [src/evaluation/drift.py](../../src/evaluation/drift.py) (3 public functions):

| Function | Purpose |
|---|---|
| `compute_psi(reference, current, bins=10, epsilon=1e-6)` | Bare PSI on two arrays |
| `reference_snapshot(train_df, feature_cols, output_path, bins=10, model_version_id=None)` | Freeze per-feature quantile bin edges + reference counts at training time |
| `quarterly_drift_report(reference_snapshot_path, current_view, db_path, quarter, ...)` | Score current-period drift vs frozen baseline; emit gate |

Key design choices:
- **Bin edges from reference quantiles only** (frozen at training, never recomputed) — rolling baselines hide the drift we want to detect
- **Open-ended tails**: first/last bin edges set to ±inf so out-of-distribution values fall in the extreme bins instead of being lost
- **Duplicate edge dedup** — handles near-constant features without zero-width bins
- **Empty-bin clamping to epsilon** — keeps PSI finite when current distribution is degenerate
- **NaN-safe**: drops NaNs before binning; `n_missing` recorded in the snapshot
- **Insufficient-data flag**: if `n_rows < bins`, feature is marked `status: insufficient_data` and skipped at report time
- **Gate is non-blocking** (`blocking=False`) — drift is a warning signal, not a promotion blocker

**Wiring:**
1. Training tail ([train_mfe_classifier.py:520-534](../../scripts/train_mfe_classifier.py)) writes
   `model_dir/reference_snapshot.json` for numeric features (categoricals
   skipped via the `cat_mapping` set).
2. Phase 8 orchestrator ([daily_pipeline_orchestrator.py:1008-1064](../../src/orchestrators/daily_pipeline_orchestrator.py))
   has a new `_maybe_run_quarterly_drift(target_date)` method. Fires **only**
   when `target_date.day == 1 AND month in (1, 4, 7, 10)`. Output goes to
   `logs/drift/<YYYY>Q<N>.json`. Silently skips if no prod model, no
   artifacts_path, or no `reference_snapshot.json` (older models pre-date this
   wiring).

**Tests** [tests/test_drift.py](../../tests/test_drift.py) — 12 new tests:
- Identical distributions → PSI ≈ 0
- 1σ shift → PSI > 0.25
- NaN handling
- Empty inputs → raise
- Zero-current-bins → finite PSI
- Snapshot round-trip + missing-column + insufficient-data
- Drift report identifies the drifted feature
- Drift report passes when no drift
- Missing-snapshot → FileNotFoundError

### 3.1 — Lazy `src/evaluation/__init__.py` (already in code)

The plan flagged this as a 0.5h task but the PEP 562 `__getattr__` was already
in place in [src/evaluation/__init__.py](../../src/evaluation/__init__.py).
Verified empirically:

- `import src.evaluation` cold start: **17 ms**
- `import tests.test_bootstrap` cold start: **0.59 s** (was ~25 min before)
- `yfinance` and `macro_engine` NOT loaded by either

So nothing to do — the plan was written before noticing the fix had landed.

## 📝 Files Changed (uncommitted)

### Modified
- [scripts/train_mfe_classifier.py](../../scripts/train_mfe_classifier.py)
  — 3 new CLI flags, WF-backtest helper, PSI reference-snapshot tail
- [src/orchestrators/daily_pipeline_orchestrator.py](../../src/orchestrators/daily_pipeline_orchestrator.py)
  — Phase 8 quarterly drift trigger

### New
- [src/evaluation/drift.py](../../src/evaluation/drift.py) — PSI library
- [tests/test_drift.py](../../tests/test_drift.py) — 12-test suite

### Pre-existing uncommitted (from earlier sessions, unchanged this session)
- `.claude/scheduled_tasks.lock`
- `docs/session_logs/2026-05-23_evaluation-framework.md`
- `scripts/dashboard.py`, `scripts/dashboard_utils.py`
- Plus this session's plan + handover artifacts

## 🚧 Work in Progress (CRITICAL)

**Nothing half-finished in code.** All four sub-items either landed cleanly or
were verified as already in place. The remaining work is operational (user
side) and documented below.

**One known caveat from the plan §6 not yet addressed:** the PSI reference
snapshot doesn't yet capture sector/industry categoricals — they're skipped at
the training-tail stage since `reference_snapshot` only handles numerics. If
categorical drift becomes interesting, would need a parallel
`categorical_drift_report` (chi-squared or KL on category-frequency vectors).
Filed as a future item below; not blocking anything.

## ⏭️ Next Steps

### Step 2 (from prior handover) — Retrain `M01_baseline_v0.2` — UPDATED CLI

The exact command to run now that `--with-wf-backtest` exists:

```powershell
C:/Users/Hang/PycharmProjects/quantamental/.venv/Scripts/python.exe scripts/train_mfe_classifier.py `
  --feature-set fs_m01_prototype `
  --model-name m01_baseline `
  --model-version v0.2 `
  --label-id mfe_4class_30d_v1 `
  --walk-forward `
  --with-regime-decomp `
  --with-perm-importance `
  --with-wf-backtest `
  --promote-prod
```

**Difference from the prior handover's Step 2 CLI:** added
`--with-wf-backtest`. This folds the 4 WF-backtest gates into v0.2's
`results.json` in one pass. Adds ~30-60 min wallclock per fold for the
`SEPABacktestRunner` step (so plan ~2-4h total instead of ~2-3h).

**Side effect of this command:** writes
`models/m01_baseline/v0.2/reference_snapshot.json` automatically at the
training tail (PSI baseline frozen for the next quarterly report). Nothing to
do manually.

### Acceptance check additions for v0.2

On top of the prior handover's Step 2 acceptance checks, also verify:

```powershell
# WF-backtest gates merged into results.json
C:/Users/Hang/PycharmProjects/quantamental/.venv/Scripts/python.exe -c "
import json
r = json.load(open('models/m01_baseline/v0.2/evaluation/results.json'))
wf_gates = [g for g in r.get('gates', []) if g['name'].startswith('wf_backtest_')]
print(f'WF-backtest gates: {len(wf_gates)}')
for g in wf_gates:
    print(f'  {g[\"name\"]}: {g[\"status\"]} (value={g.get(\"value\")})')
"
# PSI baseline frozen
ls models/m01_baseline/v0.2/reference_snapshot.json
# Per-fold backtest artifacts
ls models/m01_baseline/v0.2/wf_backtest/
```

Expected: 4 gates, baseline file ~30-200 KB, fold_NN subdirs with
trades.parquet / equity.parquet / metrics.json.

### Step 3 (from prior handover) — Framework re-evaluation

Unchanged. The Section 2 wiring doesn't change §1.4 sub-tasks 1-6. With
`--with-wf-backtest`, the §1.4 sub-task 2 (walk-forward backtest) is already
done during training — that subtask collapses to "read the gates from
results.json and document them."

## 📋 What's left in the evaluation framework uplift

Treating the original plan
([docs/plans/evaluation_remaining_implementation_plan_2026_05_24.md](../plans/evaluation_remaining_implementation_plan_2026_05_24.md))
as the canonical scope, here's the current status:

| Item | Status | Owner |
|---|---|---|
| §1.1 fan-out fix | ✅ shipped (commit cca85e9) | — |
| §1.2 daily pipeline run | ✅ shipped (commit cca85e9) | — |
| §1.2 UI smoke test | ⏸️ **pending — your Step 1** | user |
| §1.3 retrain v0.2 | ⏸️ **pending — your Step 2 (CLI above)** | user |
| §1.4 framework re-eval | ⏸️ **pending — your Step 3** | user |
| §2.1 WF-backtest wiring | ✅ this session | — |
| §2.2 PSI/drift library | ✅ this session (code + tests + wiring) | — |
| §2.2 dashboard surface | ⏸️ **deferred** — see below | future |
| §3.1 lazy `__init__` | ✅ already in code (verified) | — |
| §3.2 backfill predictions | ⏸️ optional, deferred (plan flagged this as P3) | future |

**Items NOT yet done in the framework uplift:**

1. **Pipeline Health dashboard "Feature Drift" page** (§2.2 sub-bullet).
   The library writes `logs/drift/<quarter>.json` but nothing in
   [scripts/dashboard.py](../../scripts/dashboard.py) reads it yet. ~1-2h work:
   add a section to whichever Health/Monitoring page is the natural home, glob
   `logs/drift/*.json`, render the latest with color-coded PSI cells. Defer
   until the first quarterly file actually exists (next trigger: 2026-07-01 if
   the daily pipeline runs that day).

2. **Categorical drift report** (caveat in §2.2 wiring above). PSI is
   numeric-only by design. If sector/industry distribution shifts become a
   concern, add a parallel chi-squared/KL function. Not in the original plan;
   surface this if needed.

3. **§3.2 historical-prediction backfill**. Plan P3, optional. Only worth it
   if "performance of past decisions" view becomes a recurring need. Once
   v0.2 is prod, we'd be backfilling from at most 2026-05-24 forward, so the
   ROI is small — defer indefinitely.

4. **Numpy fast-path for `permutation_null_backtest`** (plan §7, explicitly
   out-of-scope). 1000-perm backtest in §1.4 sub-task 4 is going to take ~8h
   wallclock against `SEPABacktestRunner`. If that becomes painful operationally,
   ~2.5d to build a numpy fast-path. Defer until/unless §1.4 makes you wait.

5. **`d3_deployment_cache`** (flagged in prior session handover, watch-item 1).
   Parity check is now 170s but deploy-side load is still ~130s of that —
   would drop to <30s with a materialized cache. Same pattern as
   `d2_training_cache`. ~2h to add a `RefreshDeploymentCache` step in Phase 7
   of the orchestrator. Defer until parity check becomes a bottleneck.

6. **Cross-sectional rank casing cleanup** (flagged in prior session, watch-item 2).
   `RS_Sector_Rank` etc. are TitleCase in `daily_features`/`t3_sepa_features`
   but lowercase in `feature_catalog`. Parity check now bypasses via
   case-insensitive resolution — but the underlying inconsistency lives.
   Long-term fix: pick one convention and apply at the source. Not blocking.

**Bottom line:** the evaluation framework uplift is **functionally complete**
on the library side. What's left is (a) running the operational pipeline
(Steps 1/2/3) to validate v0.2, and (b) deferred polish that isn't on any
critical path.

## 💡 Context/Memory

- **Why I refactored `_run_walk_forward_block` to return a tuple rather than
  running the backtest inside it.** Keeping the WF training and WF backtest
  as separate concerns means a user who wants WF *without* backtest (e.g. fast
  iteration during model dev) doesn't pay the SEPABacktestRunner cost. The
  caller in `main()` is the right place to branch on `--with-wf-backtest`.
- **Why `model_path=None` in the SEPABacktestRunner closure.** Looked at
  `runner.py` line 231: the strategy receives `scores_df` directly, no
  re-scoring. `model_path` and `model_version_id` are metadata-only (used in
  `_extract_metrics` reports). So I don't have to copy
  `categorical_mapping.json` into each fold dir (the plan flagged this as a
  caveat — sidestepped by not invoking the scorer at all).
- **Why I stash ticker as `__ticker__` instead of plain `ticker` on the panel.**
  `feature_cols=valid_features` is explicit, so plain `ticker` wouldn't end up
  in `X_test` — but using `__ticker__` makes it obvious to a reader that this
  is internal-only and not a feature.
- **Why the PSI gate is non-blocking.** Drift is an alert, not a rollback
  trigger. A drifted feature might be exactly what the model wants to see
  (regime change). The dashboard surface (when built) is where humans look at
  the drifted features and decide; the gate is there to make sure the report
  ran, not to block deployment.
- **Why I built `reference_snapshot` to skip categoricals silently rather than
  cast them.** The catalog has 2 categorical features (sector, industry) and
  they participate in the model as XGBoost categoricals, not numeric. Chi-squared
  is the right distance for them, not PSI. Building the wrong tool would have
  led to spurious "drift" alerts every time a single new ticker landed.
- **Why the quarterly trigger is a method on the orchestrator rather than a
  separate `scripts/run_drift_report.py`.** Plan §6 question 4 left this open.
  I picked auto-fire because (a) it's more reliable than remembering to run a
  CLI, (b) the orchestrator already runs daily, (c) the silent-skip behavior
  when there's no `reference_snapshot.json` means old models don't break it.
  If you want to invoke manually, just call
  `DailyPipelineOrchestrator(...)._maybe_run_quarterly_drift("2026-04-01")`
  — date doesn't have to be today.

---

## 📋 Final test status

```
tests/test_drift.py                 12 passed   (new — drift library)
tests/test_walk_forward_backtest.py 15 passed   (existing — no regression)
tests/test_view_fanout.py            4 passed   (from prior session)
tests/test_feature_parity.py         7 passed   (from prior session)
```

38 / 38 in 2.64s.

## 📊 Critical path status (updated)

| Item | Status |
|---|---|
| §1.1 fan-out fix | ✅ committed (cca85e9) |
| §1.2 run daily pipeline | ✅ committed (cca85e9) |
| §1.2 UI verification | ⏸️ user — Step 1 of prior handover |
| §1.3 retrain M01_baseline_v0.2 | ⏸️ user — Step 2 (CLI above, now includes --with-wf-backtest) |
| §1.4 framework re-eval | ⏸️ user — Step 3 |
| §2.1 WF-backtest wiring | ✅ this session |
| §2.2 PSI/drift library + wiring | ✅ this session |
| §3.1 lazy `__init__` | ✅ already done (verified) |

The §8 Definition of Done from the original plan now has a path that's
entirely "user runs commands" — no further library work needed before §1.4.

---

**Suggested commit message:**
**"feat(eval): wire WF-backtest + PSI/drift library (plan §2.1, §2.2)"**

Files in this commit:
- `scripts/train_mfe_classifier.py` — WF-backtest flags + helper, PSI snapshot tail
- `src/orchestrators/daily_pipeline_orchestrator.py` — Phase 8 quarterly drift
- `src/evaluation/drift.py` — new library
- `tests/test_drift.py` — new test suite

(Pre-existing uncommitted files from prior sessions — `dashboard.py`,
`dashboard_utils.py`, etc. — are NOT this session's work and should not be
folded in here.)
