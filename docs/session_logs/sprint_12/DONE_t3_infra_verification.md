# T3 — Training/Eval Infrastructure Verification ✅ DONE 2026-06-11

**Goal:** confirm the full training → eval → model-card flow works on the current
clean dataset (post-EDGAR, post-deactivation, post-macro-fix). Verification only —
model promotion is a human decision and was **not** done.

---

## Outcome: flow works end-to-end. One real bug fixed at the root.

### Step 1 — Data load ✅
`load_pretrain_data(mode="trades")` (the real loader; `load_training_data_from_db`
in CLAUDE.md/memory is a legacy name):
- **37,952 rows × 218 cols**, dates **2001-01-03 → 2026-06-10** (current),
  **2,673 tickers**, **0 NULL mfe_pct**. Cache fresh.
- All **97** prod-model features present, none missing. Null fractions are the
  normal sparse-fundamentals pattern (`peg_adjusted` 49%, `pb_ratio` 11%, m03
  ~4%) — XGBoost handles natively. Universe shrink (4020→3980) and EDGAR changes
  caused no shape/completeness problem.

### Step 2 — `get_model_features('M01')` ✅ (after root-cause fix)
First raised `RuntimeError: No prod model found for 'M01'` despite a fully
populated catalog. **Root cause:** `src/utils.py:218` used case-sensitive
`version_id LIKE 'M01%'`, but prod `version_id`s are lowercase
(`m01_prototype_2003_2026_…`); DuckDB `LIKE` is case-sensitive → no match.
**Fix:** `LOWER(version_id) LIKE LOWER(?)`.

This was **not** verification-only: `src/backtest/universe_scorer.py:146` calls
`get_model_features('M01')` on the live scoring path — the bug silently broke
production universe scoring against any lowercase-prefixed prod model. The
RuntimeError message ("run populate_feature_catalog.py") was misleading; the
catalog was fine.

> Note: `tests/test_feature_catalog.py::test_get_model_features_from_db` is
> pre-existing stale — imports archived `src.feature_config`, asserts ≥105
> features vs the current 97 in `fs_m01_prototype`. Not introduced here.

### Step 3 — Trained `m01_prototype/v2` ✅
Standard 60/20/20 (real test holdout → honest card metrics), `fs_m01_prototype`,
label `mfe_4class_v1`, min-date 2003. Test window 2023-04-11 → 2026-06-10, no
temporal leakage.
- **Test acc 0.293 / wF1 0.280 / macroF1 0.288** — in line with prod v2.
- Registered `m01_prototype_20260611_133021`, status=**test** (not prod).
- A mangled first command (PowerShell backticks via the Bash tool) accidentally
  trained a stray `v1`; its dir + registry row were deleted.

### Step 4 — Model card ✅
`model_cards/m01_prototype_v2.{html,json}`. `card_void=False`, band=**WEAK**
(9/21). Built in ~69 min (Section G permutation/bootstrap dominates).

### Step 5 — What the card says

| Use case | Verdict |
|---|---|
| `hit_rate_ranker_equal_size` | **PASS** |
| `selection_ranker_size_by_p` | REJECT |
| `threshold_gate` | REJECT |
| `probability_sizing` | REJECT |
| `composite_gate_plus_rank` | REJECT |

| Section | Result | Detail |
|---|---|---|
| A Integrity | PASS | no outcome leakage, label horizon clean |
| B Discrimination | PASS | ROC-AUC **0.773**, PR-AUC lift 2.57× |
| C Calibration | **REJECT** | ECE **0.132** vs 0.05; 5/5 bins exceed ±0.05 |
| D Ranking | binary PASS / magnitude REJECT | binary IC 0.41 (t=41.5), top/bot decile 33.6×; top-5 magnitude lift only 1.12× |
| E Threshold gate | REJECT | precision lift 3.76× at T=0.6, but 1.72 trades/day < 3.0 gate |
| F Robustness | PASS | AUC > 0.55 in every M03 regime and every year |
| G Edge vs null | **PASS (3/3)** | AUC/IC/top-5 at 100th pct of permutation null, p=0.0; bootstrap CIs exclude baseline |

**vs SEPA-composite baseline:** real edge — AUC 0.773 vs 0.594, binary IC 0.365
vs 0.167, Brier 0.135 vs 0.284.

**Interpretation:** the model has statistically-significant ranking edge and is
robust, but is REJECTED for every probability-consuming use case purely on
**calibration** — expected for a raw 4-class booster (isotonic calibration is a
binary-only step in the trainer). The one PASS is exactly the rank-order-only use
case. For a promotable probability model, the indicated next step is the **binary
home-run variant trained with `--with-calibration`**, not promoting this card.

---

## Not done (intentional)
- Did **not** promote v2 (human decision).
- Did **not** use `--register-version`, so `models.model_card_path` write-back on
  a real card remains unexercised (v2 is a `test` candidate, not the prod row).

## Artifacts
- Model: `models/m01_prototype/v2/`
- Card: `model_cards/m01_prototype_v2.{html,json}`
- Logs: `logs/m01_prototype_v2_train.log`, `logs/m01_prototype_v2_card.log`
- Code change: `src/utils.py` (case-insensitive feature lookup)
- Memory: `project_get_model_features_case_bug.md`
