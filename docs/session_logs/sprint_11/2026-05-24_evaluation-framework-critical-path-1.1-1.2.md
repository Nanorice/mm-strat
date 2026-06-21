# Session Handover: 2026-05-24 — Critical Path §1.1 + §1.2 Complete

## 🎯 Goal
Execute the critical path in
[docs/plans/evaluation_remaining_implementation_plan_2026_05_24.md](../plans/evaluation_remaining_implementation_plan_2026_05_24.md)
§1.1 (fan-out fix) and §1.2 (daily pipeline run). Stop short of §1.3 retrain
+ §1.4 framework re-eval — both are operational tasks the user will run
next session.

## ✅ Accomplished

### §1.1 — `v_d2_features` fan-out fix

**Diagnosis refinement.** Probe queries against the live DB revealed the
[view_fanout_fix_2026_05_24.md](../proposals/view_fanout_fix_2026_05_24.md)
proposal was **partially right**:

| Question | Probe answer |
|---|---|
| `fundamental_features` dups on `(ticker, filing_date)` | 1,072 dups / 211,287 unique keys (~0.5%) |
| Adding `fiscal_period` deduplicates? | Yes — `(ticker, filing_date, fiscal_period)` is unique |
| `shares_history` dups on `(ticker, date)` | **Zero.** Proposal's `sh_dedup` CTE was unnecessary. |
| `v_d2_features` fan-out in practice | Rare but real: 2/50 random tickers had any fan-out, max 3-way |
| Smoking gun | UNH 2007-03-21 — `fundamental_features` has Q2/Q3/Q4 all stamped `filing_date='2007-03-06'`. The `MAX(filing_date)` subquery returns one date but matches all 3 rows. |

**Fix applied.** [src/managers/view_manager.py:404-510](../../src/managers/view_manager.py#L404)
`_create_v_d2_features` now wraps `fundamental_features` in an `ff_dedup` CTE
with `QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker, filing_date ORDER BY
fiscal_period DESC NULLS LAST) = 1`. The as-of correlated subquery now reads
from `ff_dedup` instead of the raw table. `shares_history` join left
untouched — no dups, no fix needed.

**Why `fiscal_period DESC NULLS LAST`.** When Q2/Q3/Q4 are tied on the same
`filing_date`, the largest (most-recent quarter) wins. Verified on UNH: now
returns Q4 with revenue=$18.128B and EPS=$0.84.

### Parity check rewrite

The `feature_parity_check` runtime that triggered this session
(~25min, never finished) had three problems beyond fan-out — all fixed:

1. **`d2_training_cache` fast-path** ([leakage_guard.py:550-565](../../src/evaluation/leakage_guard.py#L550))
   When caller passes `train_view='v_d2_training'` and `d2_training_cache`
   exists, swap to the materialized table. Train-side load drops from
   826s → **0.4s** (~2000× speedup).
2. **JOIN over `IN-tuples`** ([leakage_guard.py:594](../../src/evaluation/leakage_guard.py#L594))
   Replaced `WHERE (ticker, date) IN (200-tuple list)` with INNER JOIN
   against a registered DataFrame. Better predicate pushdown on the deploy
   side (~3× speedup, not 100× — DuckDB still materializes much of the view
   chain).
3. **Case-insensitive feature resolution** ([leakage_guard.py:586-617](../../src/evaluation/leakage_guard.py#L586))
   `_resolve_columns` matches catalog names to actual view columns
   case-insensitively, then aliases the SELECT to catalog names. Fixes the
   long-standing cross-sectional rank casing gotcha (`rs_sector_rank` in
   catalog vs `RS_Sector_Rank` in view) **without** touching `COLUMN_CASE_MAP`
   or the catalog itself. Mirrors what `train_mfe_classifier.validate_features`
   already does at [scripts/train_mfe_classifier.py:105](../../scripts/train_mfe_classifier.py#L105).

**End-to-end parity result:**

| Metric | Before | After |
|---|---|---|
| `passed` | ❌ (would fail on fan-out + missing-columns) | ✅ **pass** |
| Wall time | ~25 min (and rising) | **170s (~2:50)** |
| `mismatches` | N/A (gated) | **0** |
| `dtype_mismatches` | 7 (all `missing_column` due to casing) | **0** |
| `multi_row_keys` (train/deploy) | unknown | 0 / 0 |

### Regression test

[tests/test_view_fanout.py](../../tests/test_view_fanout.py) — new file, 4 tests:

- `test_no_fanout_when_source_has_tied_filings` — UNH-style 3-way collision
  on `(ticker, filing_date)`, asserts exactly 1 output row per key
- `test_tiebreaker_picks_largest_fiscal_period` — asserts Q4 > Q3 > Q2 wins
- `test_no_fanout_with_clean_source` — sanity (no dups in → no dups out)
- `test_d1_rows_without_filings_still_appear` — LEFT JOIN semantics survive

Fixture is minimal: stubs `v_d1_candidates`, `company_profiles`,
`fundamental_features`, and `t3_sepa_features` (the last only because the
post-build sanity print queries it). All 4 pass in 0.7s.

**Negative control verified:** ran the OLD buggy SQL against the same fixture
— produces 3-way fan-out on UNH 2007-03-21. Confirms the test bites if
someone reverts the fix.

All 7 existing tests in [tests/test_feature_parity.py](../../tests/test_feature_parity.py)
still pass — the parity-check rewrite is backward-compatible.

### §1.2 — Daily pipeline run

Ran `python -u scripts/run_daily_pipeline.py`. **Exit 0**, ~37min wallclock.

- Phase 1.1 Price: 35/51 stale OK, 16 yfinance 404s on delisted tickers (expected)
- Phase 1.3 Shares: 3981/3981 (was bottleneck — ~6min, last run was April 1)
- Phase 5/6 used the rebuilt `v_d2_features` cleanly
- Phase 7 cache refresh: 38,122 rows in 561s
- **Phase 8 wrote 7 predictions** for date `2026-05-22`, model
  `m01_prototype_2003_2026_20260514_233125`:

  | Rank | Ticker | Class | P(Home Run) |
  |---|---|---|---|
  | 1 | LPTH | 3 | 0.714 |
  | 2 | FEIM | 3 | 0.601 |
  | 3 | AA | 3 | 0.518 |
  | 4 | ATKR | 3 | 0.465 |
  | 5 | DELL | 3 | 0.462 |
  | 6 | MITK | 3 | 0.459 |
  | 7 | ROST | 2 | 0.165 |

All `decision_taken=NULL` — dashboard toggle ready to flip them.

## 📝 Files Changed (uncommitted)

### Modified
- [src/managers/view_manager.py](../../src/managers/view_manager.py) —
  `_create_v_d2_features` ff_dedup CTE
- [src/evaluation/leakage_guard.py](../../src/evaluation/leakage_guard.py) —
  parity check perf + case-insensitive resolution

### New
- [tests/test_view_fanout.py](../../tests/test_view_fanout.py) —
  4-test regression suite

### Pre-existing uncommitted (from prior session, unchanged)
- `scripts/dashboard.py`, `scripts/dashboard_utils.py`,
  `scripts/train_mfe_classifier.py`, plus this session-log directory

### Database state
- `v_d2_features` rebuilt with new SQL (via ViewManager)
- `d2_training_cache` refreshed (38,122 rows)
- `daily_predictions` has 7 rows for `2026-05-22`

## 🚧 Operational tasks remaining — what YOU need to run next session

The critical path's remaining work is operational. Listed in order with
exact commands and acceptance checks.

### Step 1 — UI smoke test (§1.2 acceptance, 2min)

Spin up streamlit and confirm the Today page renders the 7 predictions
with a working Decision toggle:

```powershell
streamlit run scripts/dashboard.py
```

In the browser:
1. Navigate to the **Today** page (default landing)
2. Scroll to "Today's Predictions — Decision Log" — confirm 7 rows render
   (LPTH at top, ROST at bottom)
3. Pick one ticker (e.g. LPTH) — change Decision from `—` to `Taken`
4. Wait for re-run, then refresh the browser
5. Re-open Today page — LPTH should still show `Taken`

Verify persistence via SQL:
```powershell
C:/Users/Hang/PycharmProjects/quantamental/.venv/Scripts/python.exe -c "
import duckdb
con = duckdb.connect('data/market_data.duckdb', read_only=True)
print(con.execute('''
    SELECT prediction_date, ticker, decision_taken, taken_at
    FROM daily_predictions
    WHERE decision_taken IS NOT NULL
''').df())
"
```

Expected: one row with `decision_taken='taken'` and a non-NULL `taken_at`.

### Step 2 — Retrain `M01_baseline_v0.2` (§1.3, ~half-day wallclock)

```powershell
C:/Users/Hang/PycharmProjects/quantamental/.venv/Scripts/python.exe scripts/train_mfe_classifier.py `
  --feature-set fs_m01_prototype `
  --model-name m01_baseline `
  --model-version v0.2 `
  --label-id mfe_4class_30d_v1 `
  --walk-forward `
  --with-regime-decomp `
  --with-perm-importance `
  --promote-prod
```

**NO `--skip-parity`** — the parity gate should now pass naturally
(~3min into the run, before any training starts).

Acceptance checks (per plan §1.3):
- `feature_parity` gate in the log shows `status=pass`
  (look for `🔁 feature_parity: pass`)
- `models/m01_baseline/v0.2/results.json` contains all gates with real
  values (no `"skipped"` entries)
- `models/m01_baseline/v0.2/pretrain_audit.html` exists (Phase D §5.3)
- `models/m01_baseline/v0.2/folds/` has per-fold artifacts
- `models/m01_baseline/v0.2/evaluation/walk_forward_summary.json` exists
- `models` table shows v0.2 with `status_flag='prod'`:
  ```sql
  SELECT version_id, model_name, status_flag, registered_at
  FROM models
  WHERE model_name = 'm01_baseline'
  ORDER BY registered_at DESC LIMIT 5;
  ```

**Risks to watch:**
1. The `--promote-prod` flag will try to demote the current prod model
   (`m01_prototype_2003_2026_20260514_233125`). If any blocking gate fails,
   `ModelRegistry.set_prod` will refuse — read the failure reason carefully
   before deciding `--force` is appropriate.
2. The new model is trained on the **clean** `v_d2_features` (no fan-out
   averaging). Metrics may move materially vs v0.1 — could be better
   (less noise) or worse (less data leakage masking poor signal). The
   plan §1.4 is the place to interrogate this.
3. Wallclock: walk-forward + regime decomposition + perm importance is
   the heaviest combo. Expect 2-4 hours; perm-importance alone is ~30min
   per fold × N folds.

### Step 3 — Full framework re-evaluation (§1.4, ~1 day)

This is the **definition-of-done** for the entire evaluation framework.
Six sub-tasks per the plan; the heavyweight one is the 1000-perm null
backtest (~8 hours with `SEPABacktestRunner`, no fast-path yet).

Read [docs/plans/evaluation_remaining_implementation_plan_2026_05_24.md](../plans/evaluation_remaining_implementation_plan_2026_05_24.md)
§1.4 subtasks 1-6 in order. Output: one-pager at
`models/m01_baseline/v0.2/evaluation/full_eval_report.md` deciding
promote/hold/demote.

## 🛑 Things to Keep an Eye On

1. **Parity check is faster but the deploy-side load is still ~130s.** That's
   because `v_d3_deployment` is a view chain that has no materialized
   counterpart. If a future session wants sub-30s parity, the right move is
   a `d3_deployment_cache` table refreshed in pipeline Phase 7
   (mirroring `d2_training_cache`).
2. **Cross-sectional rank casing is now bypassed in the parity check** but
   the underlying inconsistency still exists in `daily_features` /
   `t3_sepa_features` / the views. Any other consumer that hits these
   columns without `lower()`-matching will trip the same bug. Long-term fix:
   add the 7 names to `COLUMN_CASE_MAP` OR rename the columns at the source
   — pick one convention. Tracked in MEMORY.md.
3. **Pipeline took 37min today because Shares cache was 7 weeks stale.**
   The Shares fetch loop hits one yfinance HTTP per delisted ticker (~30-60s
   timeout per 404). If you run again within ~7 days, Shares phase will be
   near-instant. If you skipped a long stretch again, the same slowdown
   recurs — not a code bug, an upstream API limitation.
4. **`v_d2_features` post-build sanity print queries `t3_sepa_features`.**
   The fan-out fixture has to stub that table (one row). If you add more
   view tests, keep this in mind. Long-term: that print should probably
   be lifted into the orchestrator and removed from the view-builder.
5. **`v_d2_features_v2` temp view was created during diagnosis and dropped
   at end** of the verification step. Don't be surprised if it isn't there
   — it shouldn't be.
6. **§1.2 acceptance is partial.** The SQL side is verified (7 rows written
   correctly). The UI side (toggle + persistence) is NOT — that needs Step 1
   above.

## ⏭️ Next Steps (in order)

1. **Step 1 UI smoke test** (2min) — closes out §1.2
2. **Step 2 retrain `M01_baseline_v0.2`** (half-day) — produces a model
   trained on clean data
3. **Step 3 framework re-evaluation** (1 day) — promote/hold/demote
   decision
4. **Section 2 work** (parallel-able, ~3d) — per the plan:
   - 2.1 Wire walk-forward backtest into training (`--with-wf-backtest`)
   - 2.2 PSI / feature drift library + wiring
   - 3.1 Make `src/evaluation/__init__.py` lazy (0.5h, biggest dev-experience win)
   - 3.2 Backfill historical `daily_predictions` (optional)

## 💡 Context / Memory

- **Why the proposal's tiebreaker guess was right.** `ORDER BY fiscal_period
  DESC NULLS LAST` works because the fiscal periods come from yfinance as
  literal strings `'Q1'/'Q2'/'Q3'/'Q4'/'FY'` — DESC string sort gives
  Q4 → Q3 → Q2 → Q1 → FY. Q4 is the most-recent quarter when they all
  carry the same `filing_date`, so this picks the freshest data.
  If FY were also tied, Q4 would still win (FY < Q* lexically), which is
  what we want — the quarterly is more granular than the annual.
- **Why the parity perf rewrite didn't help deploy-side as much as
  train-side.** `d2_training_cache` is a base table — DuckDB can index-scan
  it. `v_d3_deployment` is a view chain (4 levels deep) — DuckDB
  re-evaluates the whole chain regardless of the predicate shape. The JOIN
  fix saves some, but the real fix would be materializing v_d3 too.
- **Why I picked option (1c) earlier** ("read from cache directly") rather
  than (1a) ("materialize v_d3_deployment"). (1c) is a 15-line patch in
  one library. (1a) needs an orchestrator phase + a refresh script + cache
  invalidation logic + a fallback path. Same outcome on the train side,
  half the surface area. The deploy-side perf was acceptable as-is.
- **Why I scoped the regression test to `_create_v_d2_features` alone**
  rather than running through `ViewManager.create_all()`. `create_all`
  needs a fully-populated `daily_features` table and the whole view chain
  — fixture would be ~500 lines. The bug is contained to one view's SQL;
  one view's test is enough.
- **The `v_d2_features_v2` parallel-build step** described in the proposal
  was actually done in-session (live verification before cutover). Worked
  fine — UNH/CAL/VMI confirmed clean, row counts match on a 5-year x
  10-ticker window (84 = 84). Then dropped the temp view.

---

## 📋 Final test status

```
tests/test_view_fanout.py    4 passed   (new — fan-out regression)
tests/test_feature_parity.py 7 passed   (existing — no regression from rewrite)
```

## 📊 Critical path status

| Item | Status |
|---|---|
| §1.1 fan-out fix | ✅ done (code + DB state + tests) |
| §1.2 run daily pipeline | ✅ done (Phase 8 wrote 7 predictions) |
| §1.2 UI verification | ⏸️ deferred (operational — see Step 1) |
| §1.3 retrain M01_baseline_v0.2 | ⏸️ next session (Step 2) |
| §1.4 framework re-eval | ⏸️ next session (Step 3) |

The §8 Definition of Done from the original plan is unblocked. Everything
needed to run §1.3 is in place.

---

**No commit made.** Uncommitted files at session end:

- `src/managers/view_manager.py` — fan-out fix
- `src/evaluation/leakage_guard.py` — parity check rewrites
- `tests/test_view_fanout.py` — new regression test
- (plus the pre-existing uncommitted files from prior session — `dashboard.py`,
  `dashboard_utils.py`, `train_mfe_classifier.py`, doc artifacts)

Suggest committing this session's changes as one logical unit:
**"fix(views): v_d2_features fan-out + parity check perf"**.
