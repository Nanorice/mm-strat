# Generalised Model Development Methodology

> Last updated: 2026-07-15 (Sprint 14 rewrite). Source-of-truth for how every M-series model
> variant is built, validated, and promoted in this repo. The 8-gate skeleton is unchanged; G6
> was rewritten and the **three currencies of proof** were added as the organizing spine after
> Sprint 14 proved that passing G0–G5 says nothing about whether the strategy makes money.

---

## Why this document exists

The notebook-driven workflow that produced `m01_prototype` leaks small structural mistakes —
overlapping horizons, uncalibrated thresholds, single train/test splits, missing held-out gates —
that look fine in the notebook and break in the backtest. This document codifies an **8-gate
pipeline** every new model variant must pass in order, with hard pass/fail criteria fixed
**before** training.

### The three currencies of proof (read this first)

Sprint 14 spent weeks discovering that a result can be a *win* in one currency and a *null* in
another — and that these are **not interchangeable**. Every claim must name which currency it is in:

- **C1 — label-ranking.** Does the score rank the forward-outcome tail (`tail_mag`, `home_run`,
  `mfe`) beyond the incumbent bar? Lives at **G2–G3**. Cheap, in-sample-ish, a *hypothesis*.
- **C2 — OOS-ranking.** Does the model beat the incumbent bar **walk-forward, out-of-sample**?
  Lives at **G3**. A model that ties the incumbent rule here is not worth registering.
- **C3 — exit-aware P&L.** Does the selection make money on the **BackTrader start-date cone**,
  after real stops, slot contention, and capital sharing? Lives at **G6–G7**. The only currency
  that pays.

**The master lesson (label-lift ≠ trade-edge, confirmed ~5× in Sprint 14):** a C1/C2 win does NOT
imply C3. The stop + trailing exit truncate the exact tail the score concentrates; slot contention
correlates entries the label treats as independent. RS-tail, minervini+prog-fills, and
hi-score-wide-stop all won C1 and died at C3. **Treat every pre-G6 result as a hypothesis. A model
is only "good" when it clears the C3 cone.** The full trap ledger the gates defend against lives in
memory `project_standing_epistemics` — check it before reading any result as a win.

### Two structural invariants the gates enforce

1. **The held-out cutoff is sacred.** A single date (`2024-01-01`, in `config.py`) separates
   training/CV/calibration from final promotion evidence. The G7 eval lives strictly after it and
   is touched **once**.

2. **Calibration vs. ranking is a fork, decided at G0.** Absolute-probability gating (`prob > 0.60`)
   makes G4 a hard blocker; cross-sectional rank gating (top-K daily) makes G4 optional but demands
   rank-stability at G4/G6. Mixing them — `scale_pos_weight`'d probabilities used as if calibrated —
   is the most common silent failure. (The shipped `m01_binary` gates on rank/percentile, not an
   absolute floor — its `prob_elite` is discrete ~447 levels, so an absolute threshold is a cliff.)

---

## The 8 Gates

| Gate | Currency | Question | Hard pass criterion |
|---|---|---|---|
| **G0 Hypothesis** | — | What edge, target, horizon, *why* | Positive-rate 5–15%; references a known SEPA mechanism; calibration-vs-ranking fork chosen |
| **G1 Data lineage** | — | Right source, right grain, no leakage | Zero P0 quality findings; `LeakageGuard` clean; warmup-clipped |
| **G2 Signal** | **C1** | Do features rank the target beyond the incumbent bar | ≥5 features stable \|IC\| > 0.05; **beats the one-column RS bar at matched depth** |
| **G3 Fit** | **C1→C2** | Does a disciplined model beat the bar *out-of-sample* | ROC-AUC/lift > bar in **every** fold incl. drawdown regimes; **holds 2019+**, not just pre-2019 |
| **G4 Calibration** | — | Do scores mean what the strategy assumes | ECE < 0.05 if probability-gated; OR rank-stability proven if rank-gated |
| **G5 Attribution** | — | Are the drivers economically sane | Top-5 gain∩SHAP ≥3; all match G2 IC; no outcome proxy in top-15 |
| **G6 Strategy** | **C3** | Does it make money on the **BackTrader start-date cone** | Cone *distribution* beats incumbent (median/floor/%neg), not a single Sharpe; **confirmed on BackTrader, not vec** |
| **G7 Promotion** | **C3** | Strictly better than prod on untouched data | Wins the pre-registered held-out **cone**; `set_prod()` gate enforced |

You do not advance on a failed gate. You do not rewrite a gate to make a failing model pass —
**unless the gate itself is stale or biased** (Sprint 14 Q71: a failing 4-fold gate was a 3-sample
draw that *agreed* with the winning cone where they overlapped; the honest move was to rebuild it to
the cone methodology, anchored to the incumbent, not force past it). Before crediting a failing gate,
check whether it agrees with your better evidence where they overlap. If a gate fails legitimately,
the model goes back to the gate that produced the broken assumption — usually G0 (wrong target) or
G6 (the label tail didn't survive the exits).

---

## G0 — Hypothesis

**Deliverable**: one paragraph in the notebook header that states:

- Edge being captured (e.g. "post-breakout 20-day continuation in stocks with tight ATR consolidation")
- Target column and how it's derived
- Forecast horizon (and why this horizon, not adjacent ones)
- Whether the strategy will use **absolute probability thresholds** or **cross-sectional ranking** — this choice determines whether G4 is blocking
- Expected positive base rate

**Target sensitivity table** is mandatory. Sweep over horizons and thresholds, report
positive rate and the top-5 IC. Pick the cell where positive rate is in 5–15% AND
top-5 IC is stable across adjacent cells. Targets with positive rates < 3% or > 25%
are rejected at G0.

**Why this gate exists**: the m01_proto 4-class problem failed here in retrospect — forcing XGBoost
to separate 12% from 28% MFE has no economic rationale, and the **binary collapse outperformed it**
(confirmed on the Sprint 14 cone: binary median Sharpe 0.59 / α_SPY +15.6% vs 4-class 0.21 / +7.3%;
`m01_binary` is now prod). The hypothesis gate would have surfaced this. **Corollary Sprint 14
learned the hard way — a classifier QUANTIZES the tail:** a 4-class or binary head bins +35% and
+400% into the same "elite" bucket, so the score ranks *P(elite)*, never *expected magnitude*. If
the edge you care about is tail-magnitude, state at G0 that the target must be continuous
(`max(MFE−30%, 0)` or a quantile head) — a classifier structurally cannot express it.

---

## G1 — Data lineage

**Deliverable**: which DuckDB table is the source, at what grain, lowercased columns,
warmup-clipped, leakage-scanned.

Use the existing primitives — do **not** re-implement:

```python
from src.evaluation.training_data_loader import load_pretrain_data
from src.evaluation.data_quality import warmup_clip, run_quality_gate
from src.evaluation.leakage_guard import LeakageGuard

df = load_pretrain_data(mode="dense")           # or "trades"
df = warmup_clip(df)                            # drop leading-NULL warmup rows
qa = run_quality_gate(df, feature_cols, mode="dense")
assert qa.passed, qa.action_required
LeakageGuard().check_feature_leakage(feature_cols)   # forbidden-pattern scan
```

**Hard pass**: zero P0 from `run_quality_gate`; `LeakageGuard` returns no flagged
columns; warmup clip applied; all outcome columns (`mfe_*`, `return_*`, `exit_*`,
custom forward-return columns) excluded from `feature_cols`.

**Why this gate exists**: every notebook in this repo at some point added a
forward-return column and forgot to exclude it from the feature set. `LeakageGuard`
exists to catch this; G1 makes its use mandatory, not optional.

---

## G2 — Signal

**Deliverable**: IC, MI, and redundancy tables on the **training window only** (never
the held-out window — that breaks G7).

```python
from src.evaluation.feature_signal import (
    compute_ic, compute_mutual_information, compute_redundancy,
)

ic_df = compute_ic(df_train, feature_cols, target="y")
mi_df = compute_mutual_information(df_train, feature_cols, target="y")
corr, redundant = compute_redundancy(df_train, feature_cols, threshold=0.80)
```

**Hard pass**:

- At least **5 features** with \|IC\| > 0.05 that are not proxies for the same
  underlying quantity (check via the redundant-pair list)
- No feature in the top-20 IC list is a target proxy (sanity check)
- For each \|r\| > 0.95 pair, decide which to drop *now* — keep the higher-MI member
- **For a SELECTION model: the candidate features must beat the one-column RS bar** (top-decile
  `tail_mag` lift, ~3.5×) at matched depth. Sprint 14 (Thread H/I) collapsed every proposed
  selection axis — Minervini step-2 fundamentals, group-leadership, VCP/tightness — into RS: they
  were RS-clones (ρ 0.57–0.80) or subsumed. If a feature only ranks *because it correlates with RS*,
  it is not a second axis. The one residual axis that survived was **size (cap rank)**, RS-incremental.

**Two conditioning traps that make G2 lie** (Sprint 14 `project_standing_epistemics`):

- **Don't condition a cause inside its mediator.** Testing a fundamental "beyond RS" while RS already
  encodes it makes a real ramp read null (R1) or subsumed (R1b) depending on the conditioning. Decide
  what mediates what *before* the matched-depth test.
- **Median lens is wrong for a tail target.** On an upside-only MFE label the median is flat/inverted
  while the tail ranks monotonically — read `home_run_rate` / `tail_mag`, not the decile median.

**Why this gate exists**: a model that learns nothing at G3 usually had nothing to learn at G2.
Cheap to run, decisive to interpret.

---

## G3 — Fit (walk-forward, not single split)

**Deliverable**: expanding-window walk-forward over ≥4 folds. One single
train-pre-2023 / test-2023+ split does not satisfy this gate.

```python
def expanding_walk_forward(df, feature_cols, target, folds):
    """folds = [(train_end, test_start, test_end), ...] all date strings."""
    import xgboost as xgb
    from sklearn.metrics import roc_auc_score, average_precision_score
    out = []
    for train_end, test_start, test_end in folds:
        tr = df[df.date <  train_end]
        te = df[(df.date >= test_start) & (df.date <= test_end)]
        Xtr, ytr = tr[feature_cols], tr[target]
        Xte, yte = te[feature_cols], te[target]
        for c in Xtr.select_dtypes(include=["object","category"]).columns:
            Xtr[c] = Xtr[c].astype("category"); Xte[c] = Xte[c].astype("category")
        spw = (len(ytr) - ytr.sum()) / (ytr.sum() + 1e-5)
        m = xgb.XGBClassifier(
            objective="binary:logistic", n_estimators=100, max_depth=4,
            learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
            scale_pos_weight=spw, enable_categorical=True,
            tree_method="hist", random_state=42,
        )
        m.fit(Xtr, ytr)
        p = m.predict_proba(Xte)[:, 1]
        out.append({"fold": f"{test_start}->{test_end}",
                    "roc_auc": roc_auc_score(yte, p),
                    "pr_auc": average_precision_score(yte, p),
                    "base_rate": yte.mean()})
    return pd.DataFrame(out)
```

**Hard pass**: ROC-AUC (or tail-lift, for a magnitude target) > the incumbent bar in **every fold**,
including drawdown-regime folds. A model with mean AUC 0.80 but one fold at 0.55 has not passed —
that 0.55 fold is the operational truth. **The bar for a selection model is the one-column RS rule,
not 0.5 no-skill** — Sprint 14's ML tail-ranker beat RS 6/7 folds pre-2019 but LOST 13/16 folds
2019+, and the anchored folds GROW, so that is era-fragility, not data scarcity: **it must hold 2019+
or it doesn't ship**. A wash against the incumbent bar means the selection signal = the rule; don't
tune to scrape +0.1 (that's forcing the ML past a gate it failed).

**Why this gate exists**: SEPA is regime-sensitive, and "beats no-skill" is the wrong bar when a
one-column rule already ranks the tail 3.5×. A model that only beats the rule in the calm early era
is not deployable.

---

## G4 — Calibration

**Decision tree at G0 sets which branch applies here:**

**Branch A — Strategy uses absolute probability thresholds** (e.g. plan §3 "enter
when `prob_elite > 0.60`"):

```python
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator   # sklearn >= 1.6

calib = CalibratedClassifierCV(FrozenEstimator(model), method="isotonic")
calib.fit(X_calib, y_calib)                   # CALIBRATION SLICE — disjoint from train/test
p_cal = calib.predict_proba(X_test)[:, 1]
```

Hard pass: ECE_post < 0.05 *and* the reliability curve crosses y=x monotonically.

**Branch B — Strategy uses cross-sectional ranking** (top-K daily):

Calibration is not required. Instead, prove **rank stability**: the per-day Spearman
correlation between today's prob ranking and yesterday's prob ranking must be > 0.7
on average across the validation window. A model that re-shuffles the rank order
every day produces churn in the backtest regardless of how well it discriminates.

**Why this gate exists**: a 4-class XGBoost with `compute_class_weight("balanced")`
or a binary XGBoost with `scale_pos_weight` produces inflated probabilities. Using
them as absolute thresholds without recalibration is the structural mistake that
caused the `m01_rank` notebook to report ECE 0.239 while the plan blithely assumed
`>0.60` meant "60% chance".

---

## G5 — Attribution

**Deliverable**: top-15 features by XGBoost `gain` and top-15 by SHAP \|mean\|,
compared side-by-side.

```python
gain = pd.Series(model.get_booster().get_score(importance_type="gain")).sort_values(ascending=False)

import shap
explainer = shap.TreeExplainer(model)
sv = explainer.shap_values(X_test.sample(min(500, len(X_test)), random_state=42))
shap_imp = pd.Series(np.abs(sv).mean(0), index=X_test.columns).sort_values(ascending=False)
```

**Hard pass**:

- Top-5 by gain and top-5 by SHAP overlap by ≥ 3 features
- Top-5 SHAP drivers all appeared in the top-20 of G2's IC table (drivers should be
  things you already knew were predictive)
- No outcome-proxy column appears anywhere in the top-15

**Why this gate exists**: when gain and SHAP disagree wildly (as the original
4-class m01_proto did), it usually means the model is splitting on noise in a
specific region of feature space. Forces you to investigate before promoting.

---

## G6 — Strategy (the C3 gate: does it survive real exits?)

This is where Sprint 14 killed almost everything. **G0–G5 tell you the score ranks the label
(C1/C2). G6 tells you whether that survives real stops, slot contention, and capital sharing (C3) —
and the answer was repeatedly NO.** RS-tail selection, minervini+prog-fills, and a hi-score wide
stop each passed the earlier gates and died here, because the 15% stop and trailing exit truncate
the exact tail the score concentrates, and slot contention correlates entries the label treats as
independent. **A pre-G6 win is a hypothesis; G6 is the verdict.**

**Deliverable**: a BackTrader **start-date cone** — the strategy run as a fixed-slot portfolio
across many rolling start dates, reported as a *distribution* of per-cell Sharpe, not one number.
Use the existing infra: `scripts/run_starttime_sweep.py --grid rolling` produces the 90-cell cone;
`scripts/run_cone_gate.py` aggregates it (median/floor/%neg Sharpe + Calmar + α/β vs SPY & QQQ).

### The three non-negotiables Sprint 14 established

1. **A single Sharpe is a lottery, not a result — use the cone.** Folds swing >2 Sharpe on
   start-date alone. The old G6 "nav_sharpe > 1.0" was exactly the single-point error the whole
   sprint spent weeks replacing. Judge the **distribution**: does the median beat the incumbent, is
   the floor lifted, is %neg-cells lower? (`project_champion_starttime_dependent`.)

2. **Confirm on BackTrader, NOT the vectorized engine.** The vec engine is ~3× optimistic in bear
   folds (same config: vec median Sharpe 1.51/%neg 10% vs BackTrader 0.35/%neg 45%) — it has no
   cash-blocking and books stop-outs at the stop level even on a gap-down open below it. **Vec cones
   are within-engine RANKING only; the promotion number is BackTrader.** (`project_vec_engine_optimistic`.)

3. **Judge the distribution, not the paired win-rate.** A distribution-shifting lever (the SPY-200d
   gate) can win only 36% of *paired* cells yet dominate the cone — because it's inert in bull windows
   (ties) and all its value lands on the few bear windows. A paired-count read buries it.

### Two arithmetic traps that inflate any backtest to nonsense (still valid)

1. **Compounding overlapping trades.** `(1 + trade_ret).prod() - 1` across N concurrent trades
   treats capital-sharing positions as sequential — ~500 trades at 15% gives ~10¹⁴, a math artefact.
   Concurrent trades share capital; they do not multiply each other. (The original notebook shipped
   `5.98e+14` total return this way — G6 exists to make that impossible.)
2. **Sharpe of the trade-return series.** Each trade is a ~20-day outcome, not a one-day P&L event;
   `mean(trade_rets)/std(trade_rets)*sqrt(252)` inflates Sharpe by ~`sqrt(20)`. Compute Sharpe from
   the daily portfolio NAV.

### Hard pass

- The BackTrader cone **distribution** beats the incumbent: median Sharpe higher, floor no worse,
  %neg-cells no higher — across the full rolling grid, not a hand-picked window.
- Robust to ±params (score gate, top_k, hold) — a cluster of passing cells is signal, one isolated
  winning cell is overfit. Do NOT sweep a knob and report its best cell (cone-fitting).
- Beats prod scored on identical rows via `UniverseScorer` / `score_from_t3` — the canonical path.

### Sanity flags

- **Cone median Sharpe > 2.5, or any per-cell > 5**: investigate — real equity edges cluster ~0.5–1.5
  on BackTrader. Usually vec-optimism leaking in, insufficient sample, or a too-generous cost model.
- **A knob "lifts the mean" but not the floor/%neg**: it's a variance knob, not alpha (every book-level
  brake tested — governor, DD-breaker, earnings-blackout — was this). Bank as risk-control, not edge.
- **The lift is all upper-tail while p05/p10 are unchanged**: the overlay is trimming UPSIDE (the
  governor did this at basket level) — bad trade for a tail strategy.

**Why this gate exists**: the earlier gates measure label ranking; only G6 measures money. Sprint 14's
entire kill list (RS-tail, minervini, hi-score, and every overlay) passed G2–G5 and failed here. The
gap between "the score ranks the tail" and "the strategy captures it" is the whole game.

---

## G7 — Promotion (held-out, touched once)

**Deliverable**: re-fit the model on `train + calibration + validation`
(everything before the sacred cutoff), score the held-out window, and produce a
side-by-side report vs prod via `scripts/model_diff.py`.

```python
from src.model_registry import ModelRegistry
reg = ModelRegistry()
# G7 happens here, not before:
reg.register_version(model_name="m01_rank", version="v1", ...)
# Promotion is a separate step, only after the report is reviewed:
reg.set_prod("m01_rank_v1_<timestamp>")
```

**Hard pass**:

- Held-out ROC-AUC ≥ G3 mean fold AUC − 0.05 (no catastrophic out-of-sample drop)
- Held-out **cone distribution** beats prod: median Sharpe higher, floor no worse, %neg no higher —
  the same cone standard as G6, run once on the untouched window.
- The promotion gate is the incumbent-anchored cone gate in `walk_forward_backtest.py`
  (`aggregate_backtest_cone`: median/%neg/floor Sharpe + Calmar + α/β vs SPY & QQQ), enforced by
  `set_prod()`. If that gate itself is stale (computed on an invalidated config), **rebuild it to the
  cone methodology anchored to the incumbent — do not force past it** (Sprint 14 Q71).

**Why this gate exists**: every early model in this repo was evaluated on data it had seen during
early stopping or threshold tuning. G7 enforces that the promotion number is the *first time* the
model meets the held-out window — as a cone, not a point.

---

## Reusing this across models

The same gates apply to every variant. Only **G0** changes per model — target, horizon, threshold,
and the calibration-vs-ranking fork. Everything from G1 onward is mechanical. The currency map is
constant: **G2–G3 = C1/C2 (does it rank the label OOS beyond the incumbent bar); G6–G7 = C3 (does it
survive the exits on the cone).** A model that wins C1/C2 but not C3 is a *watchlist axis*, not a
strategy — that is exactly where the 63-day RS-tail ranker landed in Sprint 14 (banked as label-level
ordering, not registered as a model).

For a `breakout_within_next_3d` "ripeness" classifier, the G0 target is a ~1–2% base rate → G4 goes
Branch B (rank-based). Note its explicit guardrail: even a perfect breakout-predictor is *upstream* of
a selection stage proven not to convert to trade edge, so it is a **watchlist-enrichment** idea, not a
selection-alpha claim — scope it C1, do not expect it to clear C3.

---

## See also

- **memory `project_standing_epistemics`** — the ~12 recurring traps these gates defend against;
  check before reading any result as a win.
- **memory `project_sepa_three_currencies`** — the C1/C2/C3 vocabulary and why m01a-null ≠ m01-null.
- **memory `project_vec_engine_optimistic`** — why G6 confirms on BackTrader, not vec.
- [docs/architecture/comprehensive_methodology.md §7–§9](comprehensive_methodology.md) — system context: model registry, evaluation suite, backtester.
- [src/evaluation/](../src/evaluation/) — the importable building blocks (LeakageGuard, quality gate, signal); `scripts/run_starttime_sweep.py` + `run_cone_gate.py` for the G6/G7 cone.
