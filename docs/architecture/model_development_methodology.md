# Generalised Model Development Methodology

> Last updated: 2026-05-19. Source-of-truth for how every M-series model variant is built, validated, and promoted in this repo. Referenced by [docs/plans/m01_modeling_strategy_plan_2026_05_18.md](plans/m01_modeling_strategy_plan_2026_05_18.md).

---

## Why this document exists

The notebook-driven workflow that produced `m01_prototype` and the `m01_rank` EDA leaks
small structural mistakes — overlapping forecast horizons, uncalibrated probability
thresholds, single train/test splits, missing held-out gates — that look fine in the
notebook and break in the backtest. This document codifies an **8-gate pipeline** that
every new model variant (`m01_rank`, `m01_breakout`, M01-Hold, future regime variants)
must pass through in order, with hard pass/fail criteria fixed **before** training.

The two non-negotiable invariants the gates enforce:

1. **The held-out cutoff is sacred.** A single date (proposed: `2024-01-01`, lives in
   `config.py`) separates training/CV/calibration from final promotion evidence.
   Training, CV folds, calibration fits, threshold tuning — all live strictly before
   the cutoff. The G7 promotion eval lives strictly after it and is touched **once**.

2. **Calibration vs. ranking is a fork, decided at G0.** If the strategy gates on
   absolute probability (`prob > 0.60`), G4 calibration is a hard blocker. If it
   gates on cross-sectional rank (top-K daily), G4 is optional but G6 must prove
   rank-stability. Mixing the two — `scale_pos_weight`'d probabilities used as if
   calibrated — is the most common silent failure.

---

## The 8 Gates

| Gate | Question | Artifact | Hard pass criterion |
|---|---|---|---|
| **G0 Hypothesis** | What edge, what target, what horizon, *why* | 1-paragraph spec + target sensitivity table | Target positive-rate 5–15%; rationale references a known SEPA mechanism; calibration-vs-ranking fork chosen |
| **G1 Data lineage** | Right source, right grain, no leakage | Lineage note + `run_quality_gate(...)` PASS | Zero P0 quality findings; leakage scan clean; warmup-clipped |
| **G2 Signal** | Do features predict the target *before* modelling | IC / MI / redundancy tables | ≥5 features with stable \|IC\| > 0.05; collinear clusters pruned |
| **G3 Fit** | Does a disciplined model learn it | Walk-forward, ≥4 expanding folds | ROC-AUC stable & > 0.70 in **every** fold including drawdown regimes |
| **G4 Calibration** | Do scores mean what the strategy assumes | Reliability curve, ECE pre/post | ECE < 0.05 if probability-gated; OR strategy switched to rank-based gating |
| **G5 Attribution** | Are the drivers economically sane | Gain vs SHAP agreement | Top drivers agree across methods AND match G2 IC; no leakage proxy in top-10 |
| **G6 Strategy** | Does it make money net of frictions | Non-overlapping vectorised backtest with costs | Beats prod on the same window; positive net of costs; robust to ±params |
| **G7 Promotion** | Strictly better than prod on untouched data | Held-out eval vs prod | Wins on the pre-registered held-out window; `ModelRegistry.set_prod()` gate enforced |

You do not advance on a failed gate. You do not rewrite the gate to make a failing model
pass. If a gate fails, the model goes back to the gate that produced the broken
assumption — usually G0 (wrong target) or G4 (uncalibrated scores).

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

**Why this gate exists**: the m01_proto 4-class problem fails here in retrospect —
forcing XGBoost to separate 12% from 28% MFE has no economic rationale, and the
binary `m01_rank` collapse outperforms it. The hypothesis would have surfaced this.

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

**Why this gate exists**: a model that learns nothing at G3 usually had nothing to
learn at G2. Cheap to run, decisive to interpret.

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

**Hard pass**: ROC-AUC > 0.70 in **every fold**, including any fold that covers a
known drawdown regime (2022 is the obvious one). A model with mean AUC 0.80 across
folds but one fold at 0.55 has not passed this gate — that 0.55 fold is the
operational truth.

**Why this gate exists**: SEPA is regime-sensitive. A model that only works in bull
quarters is not deployable.

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

## G6 — Strategy (portfolio backtest with capital-sharing)

**Deliverable**: a backtest that models the strategy as a fixed-slot portfolio
(K equal-weighted positions held in parallel for `hold_days` each), with
transaction costs, and reports a Sharpe computed from the daily portfolio NAV —
not from the trade-return series.

### Two traps to avoid

Both are easy to write, both inflate the number to nonsense:

1. **Compounding overlapping trades.** `(1 + trade_ret).prod() - 1` across N
   concurrent trades treats them as if they were sequential single-position
   trades of one portfolio. With ~500 trades at avg 15% you get ~10¹⁴, which is
   a math artefact, not a return. Concurrent trades **share capital**; they do
   not multiply each other.
2. **Sharpe of the trade-return series.** Each trade is a 20-day outcome, not a
   one-day P&L event. Computing `mean(trade_rets) / std(trade_rets) * sqrt(252)`
   inflates Sharpe by `sqrt(20)` against the natural denominator.

### The right model

K slots. Each slot fills with the highest-ranked eligible candidate when free.
A trade locks its slot for `hold_days`. Daily portfolio return is the
**average** of currently-open slot returns (slots holding cash contribute 0).
Sharpe is computed from this daily NAV series.

When the data is trade-level (only the *total* hold-period return is known,
not the daily path), spread each trade's total return uniformly across its
hold window as a constant daily compounded equivalent: `(1+r)^(1/hold_days)-1`.
This path-smoothing approximation loses intra-trade drawdown shape but
correctly handles capital-sharing across overlapping trades.

```python
def portfolio_backtest(scored, hold_days=20, prob_enter=0.60,
                       consec=3, top_k=3, cost_bps=10):
    """K-slot portfolio backtest with proper capital sharing.
    scored: date, ticker, prob, fwd_return (realised hold-period total return).
    Returns (trade_ledger, summary_dict, daily_nav_series)."""
    scored = scored.sort_values(["ticker", "date"]).copy()
    enter = (scored["prob"] >= prob_enter)
    scored["streak"] = enter.groupby(scored["ticker"]).transform(
        lambda s: s.groupby((~s).cumsum()).cumsum())
    eligible = scored[scored["streak"] >= consec]

    trades, open_until = [], {}
    for d, day in eligible.groupby("date"):
        for _, r in day.sort_values("prob", ascending=False).iterrows():
            if sum(v >= r.date for v in open_until.values()) >= top_k: break
            if open_until.get(r.ticker, pd.Timestamp.min) >= r.date: continue
            ret = r.fwd_return - 2 * cost_bps / 1e4
            trades.append({"date": r.date, "ticker": r.ticker, "ret": ret})
            open_until[r.ticker] = r.date + pd.Timedelta(days=hold_days)
    led = pd.DataFrame(trades)
    if led.empty: return led, {"n_trades": 0}, None

    per_day = (1 + led["ret"]).pow(1.0 / hold_days) - 1.0
    legs = pd.concat([
        pd.Series(per_day.iloc[i],
                  index=pd.bdate_range(led["date"].iloc[i], periods=hold_days))
        for i in range(len(led))
    ], axis=1).sort_index()
    daily_port_ret = legs.sum(axis=1).fillna(0) / top_k        # cash on empty slots
    nav = (1 + daily_port_ret).cumprod()
    return led, {
        "n_trades": int(len(led)),
        "avg_trade_ret": float(led["ret"].mean()),
        "win_rate": float((led["ret"] > 0).mean()),
        "ann_per_slot": float((1 + led["ret"].mean()) ** (252 / hold_days) - 1),
        "total_ret_nav": float(nav.iloc[-1] - 1),
        "nav_sharpe": float(daily_port_ret.mean() / daily_port_ret.std() * np.sqrt(252))
            if daily_port_ret.std() > 0 else 0.0,
    }, nav
```

### Hard pass

- `avg_trade_ret` > 0 net of `cost_bps = 10` (round-trip)
- `nav_sharpe` (from the daily portfolio NAV, NOT the trade series) > 1.0
- Beats prod on the same window — run prod through
  `UniverseScorer.score_from_duckdb` on identical rows, apply the same
  entry/exit logic, compare `total_ret_nav` and `nav_sharpe`
- Robust to ±20% on `prob_enter`, `consec`, and `top_k` — a single isolated
  winning cell is overfit, a cluster of passing cells is signal

### Sanity flags

- **`total_ret_nav` > 100x over a 1-year window**: methodology bug. A 6-Sharpe
  daily strategy compounds aggressively but does not return 10⁴ in 250 days.
- **`nav_sharpe` > 5**: investigate. Real edges in equity strategies cluster
  around 1.0–2.5 Sharpe. Anything higher is usually insufficient sample,
  remaining overlap leakage, or a cost model that's too generous.
- **`avg_trade_ret` arithmetic-vs-geometric gap > 2×**: heavy positive tail
  driving the mean — re-run with median-trade-return as the headline.

**Why this gate exists**: the original notebook's `(1 + led.ret).prod() - 1`
reported `5.98e+14` total return on 496 trades averaging 15% — a number that
"looks impressive" but is structurally meaningless. G6 exists specifically to
make this class of error impossible to ship.

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
- Held-out backtest avg trade return ≥ G6 in-sample avg − 30% (allow some decay,
  not collapse)
- Strictly beats prod on the held-out window across **all** of: AUC, top-K
  precision, backtest avg return, Sharpe

**Why this gate exists**: every previous model in this repo was evaluated on data
it had seen during early stopping or threshold tuning. G7 enforces the discipline
that the promotion number is the *first time* the model meets the held-out window.

---

## Reusing this across models

The same gates apply to every variant. Only **G0** changes per model — target, horizon,
threshold, and the calibration-vs-ranking fork. Everything from G1 onward is
mechanical.

For `m01_breakout`, the G0 target is `breakout_within_next_3d` derived from
`sepa_watchlist` entry events against dense `t3` history. The base rate is rarer
than home runs (~1–2%), which pushes G4 toward Branch B (rank-based) by default.

For M01-Hold (position-degradation classifier), the G0 target is
`sl_hit_within_K_days` on active positions. Same 8 gates.

---

## See also

- [docs/plans/m01_modeling_strategy_plan_2026_05_18.md](plans/m01_modeling_strategy_plan_2026_05_18.md) — what models the 8 gates apply to
- [docs/plans/eda_analytics_pipeline_plan_2026_05_17.md](plans/eda_analytics_pipeline_plan_2026_05_17.md) — Phase 1 primitives this methodology depends on
- [docs/comprehensive_methodology.md §7–§8](comprehensive_methodology.md) — system context: model registry, evaluation suite, leakage guard
- [src/evaluation/](../src/evaluation/) — the importable building blocks (every snippet above)
