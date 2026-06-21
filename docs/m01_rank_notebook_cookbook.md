# `m01_rank` Notebook Cookbook — G0 through G6

> Companion to [model_development_methodology.md](model_development_methodology.md).
> Concrete, copy-paste cells to walk `m01_rank` through gates G0 → G6 using the
> existing `src/evaluation/` infrastructure. **Do not paste all cells at once** —
> each cell is an independent gate; stop and inspect the output before advancing.
> G7 is deliberately omitted (touch the held-out window once, manually, after the
> notebook is reviewed).
>
> **State assumption**: the cells below are designed to run **top-to-bottom in one
> kernel** — later cells reuse variables from earlier ones (`df`, `model`,
> `feature_cols`, etc.). If you restart, re-run from Cell 1.

---

## Cell 0 — Notebook header (G0 hypothesis)

Paste this as a **markdown cell** at the top. Filling it in honestly is the gate.

```markdown
# m01_rank — Conviction Engine

**Edge**: Post-breakout 20-day continuation in tight-ATR consolidations. The
binary collapse (Home Run vs Rest) focuses XGBoost's loss on separating
elite setups from everything else, instead of spending capacity on the
arbitrary boundary between Solid and Strong.

**Target**: `y_homerun = (close.shift(-20) / close - 1) > 0.20`, computed
per ticker on dense `t3_sepa_features`.

**Horizon**: 20 trading days. Chosen because (a) it matches the SEPA
holding-period median, (b) shorter horizons amplify microstructure noise,
(c) longer horizons widen the survivorship aperture too much.

**Strategy gating**: cross-sectional rank (daily top-K), NOT absolute
probability threshold. → G4 Branch B applies; ECE is informational, not
blocking.

**Expected positive rate**: 5–8% (verified by sensitivity table below).
```

---

## Cell 1 — Imports + path setup

```python
import os, sys, time
import numpy as np
import pandas as pd
import xgboost as xgb
import matplotlib.pyplot as plt

if os.path.abspath("..") not in sys.path:
    sys.path.append(os.path.abspath(".."))

from src.evaluation.training_data_loader import load_pretrain_data
from src.evaluation.data_quality import warmup_clip, run_quality_gate
from src.evaluation.leakage_guard import LeakageGuard
from src.evaluation.feature_signal import (
    compute_ic, compute_mutual_information, compute_redundancy,
)
from src.evaluation.pretrain_report import _select_feature_cols

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)
```

---

## Cell 2 — G0 target construction + sensitivity sweep

The point: choose horizon × threshold **with evidence**, not by eye.

```python
df_full = load_pretrain_data(mode="dense")
df = df_full[(df_full["date"] >= "2018-01-01") & (df_full["date"] <= "2024-12-31")].copy()
del df_full

df = df.sort_values(["ticker", "date"])
df = warmup_clip(df)
print(f"Rows after warmup clip: {len(df):,}")

def add_forward_returns(d, horizons=(5, 10, 20, 60)):
    g = d.groupby("ticker", group_keys=False)
    for h in horizons:
        d[f"return_{h}d_fwd"] = g["close"].shift(-h) / d["close"] - 1.0
    return d

df = add_forward_returns(df)

# Sensitivity table — pick the (horizon, threshold) where positive rate is 5–15%
# AND IC of the top-5 features stays comparable across adjacent cells.
def sensitivity(d, horizons=(5, 10, 20, 60), thresholds=(0.10, 0.15, 0.20, 0.30)):
    rows = []
    for h in horizons:
        col = f"return_{h}d_fwd"
        valid = d[col].notna().sum()
        for t in thresholds:
            y = (d[col] > t)
            rows.append({"horizon_d": h, "threshold": t,
                         "pos_rate": float(y.mean()),
                         "n_pos": int(y.sum()),
                         "n_valid": int(valid)})
    return pd.DataFrame(rows)

sens = sensitivity(df)
print(sens.pivot(index="horizon_d", columns="threshold", values="pos_rate").round(3))

# Lock the chosen target (matches the notebook header)
HORIZON, THRESHOLD = 20, 0.20
df["y_homerun"] = (df[f"return_{HORIZON}d_fwd"] > THRESHOLD).astype(int)
df = df.dropna(subset=[f"return_{HORIZON}d_fwd"])
print(f"\nPositive rate at h={HORIZON}, t={THRESHOLD}: {df['y_homerun'].mean():.1%}")
```

**Inspect**: the printed pivot. Positive rate at your chosen cell should be 5–15%.
If it's outside that range, change the cell — do not advance.

---

## Cell 3 — G1 data lineage + leakage scan

```python
# Strip every column that could leak the future, then verify with LeakageGuard
FORWARD_RETURN_COLS = [c for c in df.columns if c.endswith("_fwd")]
LEAKAGE_EXTRAS = {"y_homerun", "mfe_pct", "mae_pct", "days_observed",
                  "return_1d", "return_5d", "return_20d", "return_60d"}

candidate_feats = _select_feature_cols(df)
feature_cols = [f for f in candidate_feats
                if f not in LEAKAGE_EXTRAS and f not in FORWARD_RETURN_COLS]
print(f"Feature columns after exclusion: {len(feature_cols)}")

# Quality gate — must PASS
qa = run_quality_gate(df, feature_cols, mode="dense")
print(f"\nQuality gate: {'PASS' if qa.passed else 'FAIL'}")
if not qa.passed:
    print("Action required:")
    for a in qa.action_required:
        print(" ", a)
    raise RuntimeError("G1 failed — fix upstream before continuing")

# Independent leakage backstop
flagged = LeakageGuard().check_feature_leakage(feature_cols)
print(f"\nLeakageGuard flagged: {flagged}")
assert not any(flagged.values()), "G1 failed — leakage detected"
```

**Inspect**: `PASS` and `flagged` empty. If anything trips, fix upstream — never
silence the assertion.

---

## Cell 4 — G2 signal (IC + MI + redundancy)

**This is the cell that was hanging before.** `compute_redundancy` now subsamples
to 200k rows by default (rank-then-Pearson, same answer as Spearman). Expect total
runtime ~1–2 minutes on a 3M-row slice.

```python
# Run on the TRAINING WINDOW only — keep the held-out slice untouched.
HELDOUT_CUTOFF = pd.Timestamp("2024-01-01")
df_train_full = df[df["date"] < HELDOUT_CUTOFF].copy()
print(f"Training-window rows: {len(df_train_full):,}")

# IC — full df is fine; the slow O(N log N) is inside spearmanr, manageable.
t = time.time()
ic_df = compute_ic(df_train_full, feature_cols, target="y_homerun")
print(f"IC: {time.time()-t:.1f}s")
display(ic_df.head(15))

# MI — internally samples to 20k rows; runs in seconds.
t = time.time()
mi_df = compute_mutual_information(df_train_full, feature_cols, target="y_homerun")
print(f"MI: {time.time()-t:.1f}s")
display(mi_df.head(15))

# Redundancy — fast path (rank + Pearson + 200k sample) lives in compute_redundancy
t = time.time()
corr, redundant = compute_redundancy(df_train_full, feature_cols, threshold=0.80)
print(f"Redundancy: {time.time()-t:.1f}s  pairs>|0.80|={len(redundant)}")
display(pd.DataFrame(redundant[:15], columns=["a", "b", "abs_corr"]))

# G2 gate
strong = ic_df[ic_df["abs_ic"] > 0.05]
print(f"\nG2 gate: {len(strong)} features with |IC|>0.05")
assert len(strong) >= 5, "G2 failed — not enough signal in features"
```

**Inspect**: the IC table — the top entries should be `adr_20d`, `natr`,
`consolidation_width`, `dist_from_52w_high`, `m03_*` (these are the known SEPA
drivers). If a forward-return column shows up here, G1 missed something.

---

## Cell 5 — Prune redundant features

```python
# Default rule: for each redundant pair, keep the one with the higher MI score.
mi_lookup = mi_df.set_index("feature")["mi_score"].to_dict()
to_drop = set()
for a, b, _ in redundant:
    if a in to_drop or b in to_drop:
        continue
    if mi_lookup.get(a, 0) < mi_lookup.get(b, 0):
        to_drop.add(a)
    else:
        to_drop.add(b)

feature_cols = [f for f in feature_cols if f not in to_drop]
print(f"Dropped {len(to_drop)} redundant features; {len(feature_cols)} remain")
```

---

## Cell 6 — G3 walk-forward fit (≥4 expanding folds)

```python
def expanding_walk_forward(d, feature_cols, target, folds):
    """folds = [(train_end, test_start, test_end), ...] — date strings."""
    from sklearn.metrics import roc_auc_score, average_precision_score
    out = []
    for train_end, test_start, test_end in folds:
        tr = d[d["date"] <  pd.Timestamp(train_end)]
        te = d[(d["date"] >= pd.Timestamp(test_start)) &
               (d["date"] <= pd.Timestamp(test_end))]
        Xtr, ytr = tr[feature_cols].copy(), tr[target]
        Xte, yte = te[feature_cols].copy(), te[target]
        for c in Xtr.select_dtypes(include=["object", "category"]).columns:
            Xtr[c] = Xtr[c].astype("category")
            Xte[c] = Xte[c].astype("category")
        spw = (len(ytr) - ytr.sum()) / (ytr.sum() + 1e-5)
        m = xgb.XGBClassifier(
            objective="binary:logistic", n_estimators=100, max_depth=4,
            learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
            scale_pos_weight=spw, enable_categorical=True,
            tree_method="hist", random_state=42,
        )
        m.fit(Xtr, ytr)
        p = m.predict_proba(Xte)[:, 1]
        out.append({
            "fold": f"{test_start[:7]}->{test_end[:7]}",
            "n_train": len(ytr), "n_test": len(yte),
            "base_rate": float(yte.mean()),
            "roc_auc": roc_auc_score(yte, p),
            "pr_auc": average_precision_score(yte, p),
        })
    return pd.DataFrame(out)

# Four expanding folds. 2022 fold MUST be present — it's the drawdown stress test.
FOLDS = [
    ("2020-01-01", "2020-01-01", "2020-12-31"),
    ("2021-01-01", "2021-01-01", "2021-12-31"),
    ("2022-01-01", "2022-01-01", "2022-12-31"),  # drawdown regime — critical
    ("2023-01-01", "2023-01-01", "2023-12-31"),
]
wf = expanding_walk_forward(df_train_full, feature_cols, "y_homerun", FOLDS)
display(wf)

print(f"\nMean ROC-AUC: {wf['roc_auc'].mean():.3f}  |  "
      f"Min: {wf['roc_auc'].min():.3f}  |  Std: {wf['roc_auc'].std():.3f}")
assert wf["roc_auc"].min() > 0.65, \
    "G3 failed — model collapses in at least one fold (check the 2022 row)"
```

**Inspect**: the 2022 row. If it's > 0.70 you're in good shape; if it's between
0.65 and 0.70, document the regime sensitivity; if it's below 0.65, the model is
not robust enough to advance.

---

## Cell 7 — Refit on full training window (for G4–G6)

```python
TRAIN_END  = pd.Timestamp("2023-01-01")
VALID_END  = pd.Timestamp("2024-01-01")    # the sacred cutoff
df_train = df_train_full[df_train_full["date"] <  TRAIN_END].copy()
df_valid = df_train_full[df_train_full["date"] >= TRAIN_END].copy()
print(f"Train: {len(df_train):,}  |  Validation: {len(df_valid):,}")

X_train, y_train = df_train[feature_cols].copy(), df_train["y_homerun"]
X_valid, y_valid = df_valid[feature_cols].copy(), df_valid["y_homerun"]
for c in X_train.select_dtypes(include=["object", "category"]).columns:
    X_train[c] = X_train[c].astype("category")
    X_valid[c] = X_valid[c].astype("category")

spw = (len(y_train) - y_train.sum()) / (y_train.sum() + 1e-5)
model = xgb.XGBClassifier(
    objective="binary:logistic", n_estimators=100, max_depth=4,
    learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
    scale_pos_weight=spw, enable_categorical=True,
    tree_method="hist", random_state=42,
)
model.fit(X_train, y_train, eval_set=[(X_valid, y_valid)], verbose=20)

p_valid = model.predict_proba(X_valid)[:, 1]
```

---

## Cell 8 — G4 calibration / rank-stability (Branch B per Cell 0)

Strategy gates on **rank**, not absolute probability. So calibration is informational;
the hard pass is **rank stability**.

```python
from sklearn.metrics import roc_auc_score
from sklearn.calibration import calibration_curve

# Informational: how bad is the raw probability?
frac_pos, mean_pred = calibration_curve(y_valid, p_valid, n_bins=10, strategy="quantile")
ece = float(np.mean(np.abs(frac_pos - mean_pred)))
print(f"ECE (informational, since we use rank gating): {ece:.3f}")

plt.figure(figsize=(6, 5))
plt.plot([0, 1], [0, 1], "k--", alpha=0.4)
plt.plot(mean_pred, frac_pos, marker="o")
plt.xlabel("Mean predicted prob"); plt.ylabel("Observed positive rate")
plt.title(f"Reliability curve  (ECE = {ece:.3f})")
plt.grid(alpha=0.3); plt.show()

# THE HARD GATE — rank stability across consecutive days.
scored = df_valid[["date", "ticker"]].copy()
scored["prob"] = p_valid
scored["daily_rank"] = scored.groupby("date")["prob"].rank(pct=True)

# Day-to-day rank correlation per ticker (Spearman of (daily_rank_t, daily_rank_{t-1}))
wide = scored.pivot_table(index="date", columns="ticker", values="daily_rank")
day_to_day_corr = wide.corrwith(wide.shift(1), axis=1, method="spearman").dropna()
print(f"\nRank-stability  median: {day_to_day_corr.median():.3f}  "
      f"mean: {day_to_day_corr.mean():.3f}")
assert day_to_day_corr.mean() > 0.50, \
    "G4 (Branch B) failed — daily rank order is too unstable to gate on"
```

**Inspect**: median day-to-day rank correlation. > 0.70 is excellent; 0.50–0.70 is
acceptable but means the strategy needs the `consec` filter at G6 to suppress churn.

---

## Cell 9 — G5 attribution (Gain vs SHAP)

```python
import shap

gain = pd.Series(model.get_booster().get_score(importance_type="gain"),
                 name="gain").sort_values(ascending=False)
print("Top 15 by Gain:"); display(gain.head(15).to_frame())

# SHAP on a 500-row sample of high-confidence predictions
hi = X_valid.iloc[np.argsort(-p_valid)[:500]]
sv = shap.TreeExplainer(model).shap_values(hi)
shap_imp = pd.Series(np.abs(sv).mean(0), index=hi.columns,
                     name="mean_abs_shap").sort_values(ascending=False)
print("\nTop 15 by SHAP (high-confidence sample):"); display(shap_imp.head(15).to_frame())

# G5 gate
top5_gain = set(gain.head(5).index)
top5_shap = set(shap_imp.head(5).index)
overlap = len(top5_gain & top5_shap)
print(f"\nTop-5 Gain ∩ SHAP overlap: {overlap} / 5")
assert overlap >= 3, "G5 failed — drivers disagree across methods (investigate)"

top5_ic = set(ic_df.head(20)["feature"])
in_ic = sum(f in top5_ic for f in top5_shap)
print(f"Top-5 SHAP in IC top-20: {in_ic} / 5")
assert in_ic >= 3, "G5 failed — SHAP drivers don't match the IC story"
```

**Inspect**: which features dominate. Compare against the m01_proto baseline —
disagreement here is informative, not necessarily a problem.

---

## Cell 10 — G6 non-overlapping vectorised backtest

**Read this before you trust any number from this cell:**

The strategy holds **K equal-weighted slots in parallel**. When a slot frees, the
highest-ranked eligible candidate fills it. We only have the *total* 20-day
return per trade (not the day-by-day OHLCV path), so each trade's total return is
**spread uniformly across its `hold_days` holding window** as a constant daily
compounded equivalent. This is a path-smoothing approximation — it loses
intra-trade drawdown shape but it is the right model for capital-sharing,
overlapping trades and gives a Sharpe computed from a real portfolio NAV.

What this cell deliberately does NOT compute, and why:

- ❌ **`(1 + trade_ret).prod()` across trades.** Wrong by construction: multiple
  concurrent trades share capital, they don't compound each other's returns. With
  ~500 trades averaging 15% each that formula returns ~10¹⁴, a math artefact, not
  a P&L.
- ❌ **Sharpe of the trade-return series.** Each trade is a 20-day outcome, not a
  daily P&L event — Sharpe of that series is inflated by `sqrt(252)` against a
  natural denominator of `sqrt(252/20)`.

What this cell *does* compute:

- ✅ `avg_trade_ret` — equal-weighted average per-trade 20d return (already net of cost).
- ✅ `ann_per_slot` — annualised return per capital slot, the right unit-economics number.
- ✅ `nav_sharpe` — Sharpe of the portfolio's daily NAV series (the honest one).
- ✅ `total_ret_nav` — total compounded return of the K-slot portfolio (the honest one).

```python
def vectorized_backtest_nonoverlap(scored, hold_days=20, prob_enter=0.60,
                                    consec=3, top_k=3, cost_bps=10):
    scored = scored.sort_values(["ticker", "date"]).copy()
    enter = (scored["prob"] >= prob_enter)
    scored["streak"] = enter.groupby(scored["ticker"]).transform(
        lambda s: s.groupby((~s).cumsum()).cumsum())
    eligible = scored[scored["streak"] >= consec]

    trades, open_until = [], {}
    for d, day in eligible.groupby("date"):
        day = day.sort_values("prob", ascending=False)
        n = 0
        for _, r in day.iterrows():
            if n >= top_k: break
            if open_until.get(r.ticker, pd.Timestamp.min) >= r.date: continue
            ret = r.fwd_return - 2 * cost_bps / 1e4
            trades.append({"date": r.date, "ticker": r.ticker, "ret": ret})
            open_until[r.ticker] = r.date + pd.Timedelta(days=hold_days)
            n += 1
    led = pd.DataFrame(trades)
    if led.empty:
        return led, {"n_trades": 0}, None

    # Portfolio NAV — K equal-weighted slots, each trade's total return spread
    # uniformly across its hold_days as a constant daily compounded equivalent.
    per_day = (1 + led["ret"]).pow(1.0 / hold_days) - 1.0
    daily_legs = [
        pd.Series(per_day.iloc[i],
                  index=pd.bdate_range(led["date"].iloc[i], periods=hold_days))
        for i in range(len(led))
    ]
    leg_df = pd.concat(daily_legs, axis=1).sort_index()
    # On each calendar day, average across the (up to top_k) open slots.
    # Days with fewer than top_k open positions hold cash on the empty slots
    # (return 0), so divide by top_k, not by the count of open legs.
    daily_port_ret = leg_df.sum(axis=1).fillna(0) / top_k
    nav = (1 + daily_port_ret).cumprod()
    nav_sharpe = (float(daily_port_ret.mean() / daily_port_ret.std() * np.sqrt(252))
                  if daily_port_ret.std() > 0 else 0.0)
    ann_per_slot = (1 + led["ret"].mean()) ** (252 / hold_days) - 1

    return led, {
        "n_trades": int(len(led)),
        "avg_trade_ret": float(led["ret"].mean()),
        "win_rate": float((led["ret"] > 0).mean()),
        "ann_per_slot": float(ann_per_slot),
        "total_ret_nav": float(nav.iloc[-1] - 1),
        "nav_sharpe": nav_sharpe,
    }, nav

# Build the scored dataframe with the realised forward return at entry
scored = df_valid[["date", "ticker", f"return_{HORIZON}d_fwd"]].copy()
scored.columns = ["date", "ticker", "fwd_return"]
scored["prob"] = p_valid
scored = scored.dropna(subset=["fwd_return"])

# Sweep ±20% around the operating point — the model must be robust to params
sweep_rows, sample_nav = [], None
for pe in [0.50, 0.60, 0.70]:
    for tk in [2, 3, 5]:
        _, stats, nav = vectorized_backtest_nonoverlap(
            scored, hold_days=HORIZON, prob_enter=pe, consec=3, top_k=tk
        )
        sweep_rows.append({"prob_enter": pe, "top_k": tk, **stats})
        if pe == 0.60 and tk == 3:
            sample_nav = nav
sweep = pd.DataFrame(sweep_rows)
display(sweep)

if sample_nav is not None:
    plt.figure(figsize=(10, 4))
    plt.plot(sample_nav.index, sample_nav.values)
    plt.title("Portfolio NAV — prob_enter=0.60, top_k=3 (validation window)")
    plt.ylabel("NAV (start=1.0)"); plt.grid(alpha=0.3); plt.show()

# G6 gates — at least one parameter region must clear all of these
ok = sweep[(sweep["avg_trade_ret"] > 0) & (sweep["nav_sharpe"] > 1.0)]
print(f"\nG6 gate: {len(ok)} / {len(sweep)} cells beat (avg_trade_ret>0, nav_sharpe>1)")
assert len(ok) >= 3, "G6 failed — no robust parameter region"
```

**Inspect**: parameter sweep + the NAV curve.

- The NAV curve must be **monotonically-ish ascending across regimes**, not a
  vertical spike. A spike means one or two outlier trades dominate.
- `avg_trade_ret` and `ann_per_slot` should agree directionally — if `avg_trade_ret`
  is 15% but `ann_per_slot` is negative, something is wrong with the cost model.
- `nav_sharpe` after this fix should typically be 1.0–2.5 for a real edge. If
  you see Sharpe > 5, that's a sign of either insufficient sample (run on a
  longer window) or remaining methodology problem — investigate, don't celebrate.
- Look for a **region** of cells that pass, not one specific cell. A single
  isolated winner is overfit; a cluster is signal.

---

## Stop here

G7 (held-out promotion) is intentionally not in this notebook. After reviewing
the notebook end-to-end:

1. Re-fit on `df[df["date"] < HELDOUT_CUTOFF]` (train + validation combined).
2. Score `df[df["date"] >= HELDOUT_CUTOFF]` — touched **once**.
3. Run prod on the same rows for head-to-head comparison.
4. Register via `ModelRegistry.register_version(...)`.
5. Only if all G7 gates pass: `reg.set_prod(...)`.

That sequence is a separate script (`scripts/promote_m01_rank.py`), not a
notebook cell — it should not be runnable accidentally.

---

## Adapting this for `m01_breakout`

Only Cells 0 and 2 change. The rest of the cookbook is identical:

```python
# Cell 0 — different hypothesis
# Edge: predict next-3-day breakout among `trend_ok=True` candidates.
# Target: y_breakout_3d = sepa_watchlist.entry_date occurs within (t, t+3].
# Strategy gating: rank-based (base rate ~1–2% is too low for absolute thresholds).

# Cell 2 — different target construction
# Pull entry events from sepa_watchlist, asof-join to dense t3 rows,
# label any row whose ticker has an entry_date in (date, date+3 business days].
```

The 8-gate discipline, the leakage guards, the walk-forward folds, the rank
stability check, the parameter sweep — all reused as-is.
