# Model Card Implementation Plan

**Companion to:** `docs/proposals/model_card_framework_2026_05_25.md`
**Author:** Hang + Claude
**Date:** 2026-05-25
**Status:** READY TO START — all §5.1 data prerequisites verified
**Estimated total effort:** ~4 days across 4 phases

---

## 0. Pre-flight (already done — see verification log)

Verification script: `scripts/verify_model_card_prereqs.py`. Outputs captured in `logs/verify_prereqs.log`. Findings drove framework doc updates committed in the same session.

| Check | Status |
|---|---|
| `mfe_pct` populated on `v_d2_training` (38,122 rows, 100%) | ✅ |
| `v_d3_deployment` reconciles with `d2_training_cache` (1976 rows match) | ✅ |
| `trend_ok` single boolean replaces C1+C2+C6 triple | ✅ |
| `t2_regime_scores.m03_score` available (also joined on d2/d3/t3 views) | ✅ |
| `t2_risk_scores.target_exposure` naturally discrete {0.0, 0.25, 0.5, 0.75, 0.85, 1.0} | ✅ |
| Trained models present: `m01_binary/v1`, `m01_prototype_2003_2026/v2` | ✅ |
| BAD_TICKERS (LIF/CUE) absent from `v_d3_deployment` | ✅ |

One residual item to confirm during Phase 1:
- **Leakage guard outcome-column exclusion** — `v_d2_training` has `mfe_pct`, `mae_pct`, `return_pct`, `exit_date`, `holding_days`, `sl_*` on the same row as features. Confirm `LeakageGuard.validate_feature_columns` (or equivalent) excludes them.

---

## 1. Module layout

New code lives under `src/evaluation/model_card/` (a package, since this needs ~8 files). Existing `src/evaluation/*` libraries are reused.

```
src/evaluation/model_card/
├── __init__.py
├── builder.py            # ModelCardBuilder orchestrator
├── data_loader.py        # Loads eval data, builds stateful pool (Mode A + B)
├── sections/
│   ├── __init__.py
│   ├── section_a_integrity.py
│   ├── section_b_discrimination.py
│   ├── section_c_calibration.py
│   ├── section_d_ranker.py
│   ├── section_e_gates.py
│   ├── section_f_robustness.py
│   └── section_g_edge.py
├── rubric.py             # Score 0-3 mapping, gate evaluation
├── verdict.py            # Use-case verdict matrix + aggregate banding
├── benchmarks.py         # DummyClassifier + SEPA-composite-score baselines
└── report.py             # HTML rendering

scripts/
└── build_model_card.py   # CLI entrypoint

tests/
└── model_card/
    ├── test_data_loader.py
    ├── test_section_b_metrics.py
    ├── test_section_d_modes.py
    ├── test_section_g_edge.py
    ├── test_rubric_scoring.py
    └── test_synthetic_models.py    # random / perfect / weak — sanity end-to-end
```

Single new CLI: `scripts/build_model_card.py --model <model_id> --output <path>`.

---

## 2. Phase 1 — Mechanical card (Sections A, B, C, F)

**Goal:** an end-to-end pipeline that loads eval data, runs the four sections backed by existing libraries, renders an HTML report. No D/E/G yet — these get placeholder "NOT YET IMPLEMENTED" cards.

**Duration:** 1 day. Each step ~1–2 hours.

### 2.1 `data_loader.py`

```python
@dataclass(frozen=True)
class EvalSplit:
    df: pd.DataFrame         # rows from v_d2_training (entry-level ledger)
    feature_cols: list[str]
    label_binary: pd.Series  # mfe_pct > 30
    label_mfe: pd.Series     # mfe_pct
    label_4class: pd.Series  # bins [2, 10, 30]
    pred_proba: pd.Series    # P(class=home_run) from the loaded model
    meta: dict               # date range, n_positives, sector counts, etc.

def load_eval_data(
    model_id: str,
    model_path: Path,
    db_path: Path,
    start_date: str | None = None,
    end_date: str | None = None,
    apply_trend_ok_filter: bool = True,
) -> EvalSplit: ...
```

Single SQL query against `v_d2_training` (NOT `d2_training_cache`, because we need outcomes). Filters:
- `feature_version = 'v3.1'`
- `mfe_pct IS NOT NULL`
- optional date range
- optional `trend_ok = TRUE`

The model is loaded via `xgboost.Booster.load_model`; predict produces `pred_proba`. For 4-class models, project to binary by taking the last (Home-Run) class probability per §6 R6.

**Important:** `feature_cols` must come from the model's `model_feature_sets` row in DuckDB (per memory `m01_two_model_system`), NOT from the dataframe column list. The dataframe will contain outcome columns we must NOT pass to predict.

### 2.2 `sections/section_a_integrity.py`

Six checks (A1–A6 per framework doc). Five are gate-only PASS/FAIL:

```python
def run_section_a(split: EvalSplit, db_path: Path) -> SectionResult:
    results = {}
    results['A1_leakage'] = check_no_outcome_features(split)
    results['A2_label_horizon'] = spot_check_label_horizon(split, n=100)
    results['A3_sepa_match'] = reconcile_with_v_d3_deployment(split, db_path)
    results['A4_class_balance'] = compute_class_balance(split)
    results['A5_bad_tickers'] = check_bad_tickers_excluded(split)
    results['A6_trend_ok_consistency'] = cross_check_trend_ok(split, db_path)
    return SectionResult(name='A', results=results, scored=False, ...)
```

A4 returns a number (prevalence), the others return PASS/FAIL with detail. Any FAIL voids the card.

### 2.3 `sections/section_b_discrimination.py`

Reuses `classification_evaluator.py` machinery — ROC-AUC, PR-AUC, Brier, log-loss already implemented. New code: rubric scoring + DummyClassifier benchmarks.

```python
def run_section_b(split: EvalSplit) -> SectionResult:
    metrics = {
        'roc_auc': roc_auc_score(split.label_binary, split.pred_proba),
        'pr_auc': average_precision_score(split.label_binary, split.pred_proba),
        'brier': brier_score_loss(split.label_binary, split.pred_proba),
        'log_loss': log_loss(split.label_binary, split.pred_proba),
    }
    metrics['baseline_prior'] = dummy_prior_metrics(split)
    metrics['baseline_stratified'] = dummy_stratified_metrics(split)
    scores = {
        'roc_auc': rubric_score(metrics['roc_auc'], thresholds=[0.55, 0.60, 0.68]),
        'pr_auc': rubric_score(metrics['pr_auc'] / split.meta['prevalence'],
                                thresholds=[1.5, 2.0, 3.0]),
    }
    gates = {
        'B1_auc': metrics['roc_auc'] > 0.55,
        'B2_pr_auc': metrics['pr_auc'] > 1.5 * split.meta['prevalence'],
        'B3_brier': metrics['brier'] < metrics['baseline_prior']['brier'],
    }
    return SectionResult(...)
```

### 2.4 `sections/section_c_calibration.py`

Reuses `calibrator.py` + `calibration_audit`. New: **per-threshold-bin calibration check** — the single most important addition because the user's deployment uses thresholds.

```python
def per_threshold_bin_calibration(
    y_true: np.ndarray, y_prob: np.ndarray,
    thresholds: list[float] = [0.3, 0.4, 0.5, 0.6, 0.7],
    tolerance: float = 0.05,
) -> dict[float, dict]:
    """For each T, check |observed_freq(P in [T, T+0.1]) - predicted_mean| <= tolerance."""
```

### 2.5 `sections/section_f_robustness.py`

Reuses `regime_decomposition.py` (`metrics_by_regime`). New: parameterise the bucketing column, run twice with M03 quintiles AND `target_exposure` discrete levels.

```python
def run_section_f(split: EvalSplit, db_path: Path) -> SectionResult:
    m03_quintiles = pd.qcut(split.df['m03_score'], 5, labels=['Q1','Q2','Q3','Q4','Q5'])
    target_exp = join_target_exposure(split, db_path)   # from t2_risk_scores

    return {
        'taxonomy_m03': metrics_by_regime(split, regime_col=m03_quintiles),
        'taxonomy_5factor': metrics_by_regime(split, regime_col=target_exp),
        'per_year': metrics_by_year(split),
        'per_sector': metrics_by_sector(split),
        'psi': compute_psi_train_vs_eval(split, db_path),
    }
```

### 2.6 `builder.py` + `report.py` + `scripts/build_model_card.py`

```python
class ModelCardBuilder:
    def __init__(self, model_id, model_path, db_path, output_dir, **opts): ...
    def build(self) -> ModelCard:
        split = load_eval_data(...)
        results = {
            'A': run_section_a(split, db_path),
            'B': run_section_b(split),
            'C': run_section_c(split),
            # D, E, G: placeholder
            'F': run_section_f(split, db_path),
        }
        verdict = aggregate_verdict(results)
        return ModelCard(results=results, verdict=verdict, ...)

    def render_html(self, card: ModelCard, path: Path): ...
```

`report.py` follows `html_report.py` patterns (inline Plotly, self-contained HTML).

### 2.7 Phase 1 unit tests

- `test_data_loader.py` — synthetic 100-row dataframe, confirm feature/outcome column separation works
- `test_section_b_metrics.py` — perfect / random / inverted classifier, confirm AUC, PR-AUC, Brier produce known values
- One end-to-end smoke test calling the CLI on `m01_binary/v1`, asserting the HTML file is produced and JSON results parse

### Phase 1 exit criterion

`python scripts/build_model_card.py --model m01_binary/v1 --output model_cards/m01_binary_v1.html` runs in < 60s and produces:
- Sections A, B, C, F populated with metrics + rubric scores + gates
- Sections D, E, G marked "NOT YET IMPLEMENTED" with placeholder cards
- Verdict block partially populated (use-case rows that don't depend on D/E/G are usable)

---

## 3. Phase 2 — Stateful pool + Section D + Section E

**Goal:** the magnitude-aware ranker analysis. This is the most important phase for the user's stated goal.

**Duration:** 1.5 days.

### 3.1 `data_loader.py` — `build_stateful_pool` (Mode B)

```python
def build_mode_a_pool(split: EvalSplit) -> pd.DataFrame:
    """Entry-only pool (the headline). Already in split.df — just filter trend_ok=True."""
    return split.df[split.df['trend_ok']]

def build_mode_b_pool(
    db_path: Path,
    model_id: str,
    start_date: str, end_date: str,
    cache_path: Path | None = None,
) -> pd.DataFrame:
    """Stateful daily pool. Per date D:
       - all (ticker, D) in t3_sepa_features where trend_ok=TRUE
       - latest P for that ticker as of D (using features as of D-1)
       - realised outcome from the trade entered on D, if any
    """
    if cache_path and cache_path.exists():
        return pd.read_parquet(cache_path)
    # Per-date SQL: t3_sepa_features × predicted_log (or live scoring)
    # Heavy — cache to parquet keyed by (model_id, start_date, end_date)
    ...
```

**Important:** Mode B needs scored probabilities for every `(ticker, date)` in the active pool, not just at entry. Two options:
1. **Re-score offline**: call the loaded model on all `t3_sepa_features` rows where `trend_ok=TRUE`. Heavy but deterministic.
2. **Use `predictions_log`**: if there's a prediction log table, join it. (Memory mentions `predictions_log.parquet` — check whether it covers the eval window).

Pick **option 1** for the first cut — it's slower but doesn't depend on a log being populated. Cache aggressively.

### 3.2 `sections/section_d_ranker.py` — D-binary + D-magnitude

Each metric implemented twice: once for the binary label, once for `mfe_pct`. Common implementation pattern:

```python
def per_day_ic(pool_df: pd.DataFrame, target_col: str) -> dict:
    """Spearman rank IC of pred_proba vs target_col, computed within each date.
    Returns mean, median, std, t-stat, n_days."""
    daily_ics = (
        pool_df.groupby('date')
        .apply(lambda g: g['pred_proba'].corr(g[target_col], method='spearman'))
        .dropna()
    )
    return {
        'mean': daily_ics.mean(),
        'median': daily_ics.median(),
        'std': daily_ics.std(),
        't_stat': daily_ics.mean() / (daily_ics.std() / np.sqrt(len(daily_ics))),
        'n_days': len(daily_ics),
    }

def top_k_lift(pool_df, target_col, k: int) -> float:
    top_k_mean = (
        pool_df.sort_values(['date', 'pred_proba'], ascending=[True, False])
        .groupby('date').head(k)[target_col].mean()
    )
    pool_mean = pool_df[target_col].mean()
    return top_k_mean / pool_mean if pool_mean > 0 else np.nan

def tail_recall(pool_df, target_col, top_pct=0.01, decile=10) -> float:
    """Of realised top-1% by target_col, fraction in model's top decile by pred_proba."""
    n = len(pool_df)
    threshold = pool_df[target_col].quantile(1 - top_pct)
    tail_mask = pool_df[target_col] >= threshold
    decile_threshold = pool_df['pred_proba'].quantile(0.9)
    top_decile_mask = pool_df['pred_proba'] >= decile_threshold
    return (tail_mask & top_decile_mask).sum() / tail_mask.sum()

def decile_profile(pool_df, target_col) -> pd.DataFrame:
    """Mean, median, 90th-pct of target_col per decile of pred_proba."""
    deciles = pd.qcut(pool_df['pred_proba'], 10, labels=False, duplicates='drop')
    return pool_df.groupby(deciles)[target_col].agg(
        ['mean', 'median', lambda x: x.quantile(0.9)]
    )
```

Run all six metrics on both Mode A and Mode B, both targets (binary and continuous MFE). Rubric scoring applies only to Mode A.

### 3.3 `sections/section_e_gates.py`

Threshold sweep at `{0.3, 0.4, 0.5, 0.6, 0.7}` (per §6 R1). Headline metrics from Mode A pool:

```python
def threshold_metrics(pool_df, thresholds=[0.3, 0.4, 0.5, 0.6, 0.7]) -> pd.DataFrame:
    rows = []
    for t in thresholds:
        gate = pool_df['pred_proba'] >= t
        if gate.sum() == 0:
            continue
        rows.append({
            'threshold': t,
            'precision_binary': pool_df.loc[gate, 'label_binary'].mean(),
            'recall_binary': (gate & pool_df['label_binary']).sum() / pool_df['label_binary'].sum(),
            'coverage_pct': 100 * gate.mean(),
            'trades_per_month': estimate_monthly_frequency(pool_df, gate),
            # E6 magnitude-conditional precision at MFE thresholds
            'p_mfe_gt_30': (pool_df.loc[gate, 'mfe_pct'] > 30).mean(),
            'p_mfe_gt_50': (pool_df.loc[gate, 'mfe_pct'] > 50).mean(),
            'p_mfe_gt_100': (pool_df.loc[gate, 'mfe_pct'] > 100).mean(),
            # E7 mean realised MFE among gate-passers
            'mean_mfe_given_gate': pool_df.loc[gate, 'mfe_pct'].mean(),
            'median_mfe_given_gate': pool_df.loc[gate, 'mfe_pct'].median(),
        })
    return pd.DataFrame(rows)
```

E5 (threshold stability) needs per-fold computation — defer to walk-forward integration in Phase 4 (simpler now: report variance across calendar years).

### 3.4 Phase 2 unit tests

Three synthetic models against a synthetic pool:
- `random_model`: pred_proba ~ Uniform(0, 1). All IC ≈ 0, tail recall ≈ 10%.
- `perfect_model`: pred_proba = label_binary. AUC = 1.0, top-1 lift = 1/prevalence, tail recall ≈ 100%.
- `weak_model`: pred_proba = 0.7 * label_binary + 0.3 * noise. AUC ~0.65, IC > 0.

Assertions on closed-form expected values.

### Phase 2 exit criterion

CLI produces D and E sections populated for both modes. Synthetic-model tests pass. On `m01_binary/v1`, the doc's hypothetical "Section D fails" example becomes a real numerical readout (per the session log, IC was -0.12 — the card should show this).

---

## 4. Phase 3 — Section G (edge existence) + verdict + benchmarks

**Goal:** complete the seven-section card, add the use-case verdict matrix, run on both models.

**Duration:** 1 day.

### 4.1 `sections/section_g_edge.py`

Classification-metric-level permutation null and bootstrap. Existing `permutation_null.py` and `bootstrap.py` operate at backtest-trade level — we need analogues at classification-metric level.

```python
def permutation_null_classification(
    y_true: np.ndarray, y_prob: np.ndarray,
    metric_fns: dict[str, Callable],  # {'auc': roc_auc, 'ic': spearman_ic, ...}
    n_permutations: int = 1000,
    block_size: int | None = None,  # if set, block-shuffle preserving temporal structure
) -> dict[str, dict]:
    """Returns per-metric: observed value, null distribution percentile, p-value."""
    ...

def block_bootstrap_ci_classification(
    y_true: np.ndarray, y_prob: np.ndarray, dates: pd.Series,
    metric_fns: dict[str, Callable],
    block_size_days: int = 60,
    n_bootstrap: int = 1000,
    ci: float = 0.95,
) -> dict[str, tuple[float, float]]: ...
```

Run on: AUC, binary IC, MFE-IC, top-5 hit lift, top-5 magnitude lift, tail recall. Six metrics × two analyses = 12 numbers in the section.

### 4.2 `benchmarks.py`

```python
def dummy_baselines(split: EvalSplit) -> dict: ...
def sepa_composite_score_baseline(split: EvalSplit, db_path: Path) -> dict:
    """Replace pred_proba with universe_scorer's composite SEPA score. Re-run D and E."""
```

The SEPA-composite baseline is the key "does ML add value?" check. If the composite score gets IC=0.06 and the model gets IC=0.07, the model isn't worth the complexity.

### 4.3 `verdict.py`

```python
USE_CASE_REQUIREMENTS = {
    'selection_ranker_size_by_p': ['A', 'D_binary', 'D_magnitude', 'G'],
    'hit_rate_ranker_equal_size': ['A', 'D_binary', 'G'],
    'threshold_gate': ['A', 'C', 'E', 'G'],
    'probability_sizing': ['A', 'B', 'C', 'G'],
    'composite_gate_plus_rank': ['A', 'C', 'D_binary', 'D_magnitude', 'E', 'G'],
}

def use_case_verdict(section_results: dict) -> dict[str, str]:
    """Returns {use_case: 'PASS' | 'MARGINAL' | 'REJECT'} per requirement set."""

def aggregate_band(section_scores: dict) -> tuple[int, str]:
    """Sum sections B/C/D-binary/D-magnitude/E/F/G scores, map to band."""
```

### Phase 3 exit criterion

Both `m01_binary/v1` and `m01_prototype_2003_2026/v2` produce complete standalone cards. The card explains why the Sharpe-1.59-but-IC-negative contradiction from the session log happened (binary D-IC fails, S3 strategy mechanics work despite that — i.e., the strategy added the edge, not the model).

---

## 5. Phase 4 — Polish + integration (optional)

**Goal:** wire the card into the model-promotion gate so it's not "another report that gets argued away."

**Duration:** 0.5 day.

### 5.1 Model registry integration

Add `model_card_path` column to the `models` table:
```sql
ALTER TABLE models ADD COLUMN model_card_path VARCHAR;
ALTER TABLE models ADD COLUMN model_card_built_at TIMESTAMP;
```

`ModelCardBuilder` writes the path back to the registry on completion.

### 5.2 Promotion gate

`scripts/build_model_card.py` exits non-zero if the model is being promoted (`--require-promotion-pass` flag) AND the card's verdict for the requested use case is REJECT.

Decision log entry (`docs/decision_log/2026-MM-DD_model_card_gate.md`) recording the new promotion process. No automatic flip to `is_production=true` without:
- card built within last 7 days
- card's `composite` use-case verdict = PASS or MARGINAL
- human sign-off recorded in decision log

### 5.3 Refresh cadence

Card is rebuilt nightly only if model version OR eval window changed. Trigger from `daily_pipeline_orchestrator` as Phase 10 (advisory only — non-blocking).

---

## 6. Risk register

Material risks that could derail the plan, with mitigation:

| Risk | Likelihood | Mitigation |
|---|---|---|
| Mode B re-scoring is slow (every `(ticker, date)` row in 8mo window) | High | Cache the scored pool parquet keyed by `(model_id, window_hash)`. Expect ~500K rows × 100ms = ~50s — bearable. Use `xgboost.Booster.inplace_predict` batch mode |
| Rubric thresholds (e.g., "AUC > 0.60 = Good") don't match domain reality | Medium | Phase 3 produces real cards on both models; recalibrate thresholds against those outputs before Phase 4. Mark this as a Phase-3-exit checkpoint |
| `LeakageGuard` doesn't currently exclude outcome columns from feature lists | Medium | Phase 1 §A1 check explicitly verifies this. If it fails, fix `leakage_guard.py` before continuing — it's a 30-min fix |
| `m01_prototype` 4-class projection drops information that would change the verdict | Medium | Per §6 R6, this is a known scope cut. Document the projection method and revisit in the comparison companion doc |
| Tail recall noisy (top 1% of 38K rows = ~380 events; per-fold even fewer) | Medium | Bootstrap CI on tail recall (§G); flag as "noisy" in the report when n < 100. Don't gate on tail recall in Phase 2; warning only per current §D-gate-6 |
| Card becomes "another gate that's argued away" — same fate as deep-rigor analysis | High if Phase 4 skipped | Phase 4 wires it into the promotion flow with explicit decision-log sign-off |
| Mode B requires per-date model scoring that doesn't fit in memory | Low | Stream by month-batch; intermediate parquet caching |
| `target_exposure` levels too sparse for stable per-bucket metrics (6 levels × not many dates each) | Low | Report bucket sample sizes; collapse to {low, mid, high} if N < 30 per bucket |

---

## 7. Dependency graph

```
Phase 1
├── data_loader.load_eval_data         ──┐
├── section_a (uses data_loader)         │
├── section_b (uses classification_evaluator + new rubric)
├── section_c (uses calibrator + new threshold-bin check)
├── section_f (uses regime_decomposition + drift, parameterised on bucketing col)
├── rubric.py                            │
├── builder.py + report.py + CLI          │
└── tests/test_data_loader, test_section_b_metrics

Phase 2 (depends on Phase 1)
├── data_loader.build_mode_a_pool        │  Mode A: trivial filter on split.df
├── data_loader.build_mode_b_pool        │  Mode B: re-score t3_sepa_features
├── section_d_ranker (Mode A + B, binary + magnitude)
├── section_e_gates (threshold sweep on Mode A pool)
└── tests/test_section_d_modes, test_synthetic_models

Phase 3 (depends on Phase 2)
├── section_g_edge (classification-level perm null + bootstrap)
├── benchmarks (DummyClassifier, SEPA-composite)
├── verdict.py (use-case matrix + aggregate band)
└── tests/test_section_g_edge, test_rubric_scoring

Phase 4 (optional, depends on Phase 3)
├── models table schema additions
├── promotion gate flag in CLI
└── daily_pipeline_orchestrator integration
```

---

## 8. Acceptance checks (final, end-of-plan)

1. CLI: `python scripts/build_model_card.py --model m01_binary/v1` produces an HTML file in <90s.
2. CLI: `python scripts/build_model_card.py --model m01_prototype_2003_2026/v2` produces its own HTML file.
3. Both cards contain all seven sections with rubric scores, gate verdicts, and use-case matrix.
4. The Sharpe-vs-IC contradiction from session log `2026-05-25_binary-pruned-and-deep-rigor.md` is explained by the card (binary IC fails, magnitude IC fails, but threshold-precision at P≥0.30 is sufficient that S3 mechanics still work).
5. Synthetic-model unit tests pass: random ≈ 0/21, perfect ≈ 21/21, weak ≈ 10–12/21.
6. SEPA-composite-score baseline beats the model on at least one metric, OR the model beats it on all — either is informative, both should be visible in the card.
7. (Phase 4) `models.model_card_path` populated for both v1 cards; promotion gate refuses to flip `is_production` if card REJECTS the requested use case.

---

## 9. What to do first when picking this up

Open in order:
1. `docs/proposals/model_card_framework_2026_05_25.md` — the *what* and *why*
2. This document — the *how*
3. `logs/verify_prereqs.log` — confirm data is still as verified (re-run `scripts/verify_model_card_prereqs.py` if more than a week has passed)
4. Start Phase 1 with `data_loader.py` — it unblocks Sections A/B/C/F simultaneously
