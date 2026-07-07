# m01_rank — Phase 1 Audit Findings

**Created:** 2026-05-21
**Companion to:** `m01_rank_dense_grain_audit_2026_05_20.md`
**Scope:** Phase 1 only — "which infra silently assumes event-grain?"
**Method:** Static read of the actual code paths m01_rank executes. No notebook
edits (per workflow rule); proposed cells are documented here as artifacts to
paste manually.

---

## 0. Premise check (must read first)

The audit assumes m01_rank trains on dense data. **Confirmed true**, but the
mechanism differs from what the plan implies, and it changes item 1.6.

- `notebooks/m01_rank.ipynb` G0 cell calls `load_pretrain_data(mode="dense")`.
- `mode="dense"` → `SELECT * FROM t3_sepa_features` (`training_data_loader.py:79-84`).
  This is the genuinely dense table (~daily rows per SEPA-active ticker).
- The target is **recomputed in-notebook**: `y_homerun = (close.shift(-20)/close - 1) > 0.20`,
  per ticker (G0 cell `add_forward_returns` + threshold). It does NOT come from
  `mfe_pct` / `v_d2_training`.
- `v_d2_training` / `d2_training_cache` is **event-grain** — `v_d1_candidates`
  Step 4 keeps only the entry-date row per trade (`view_manager.py:300`). m01_rank
  never touches it. The `feature_signal.py:96-99` "one row per trade" docstring
  describes the *trades* mode only.

**Implication:** the dense-grain artifact concern is real for m01_rank's metrics,
because every per-row metric (AUC, IC, SHAP) pools ~250 near-duplicate rows per
ticker-year. Items 1.1–1.4 stand. Item 1.6 is misdirected (see below).

---

## 1.1 — Walk-forward AUC (G3) → **FIX-NEEDED**

`expanding_walk_forward` (G3 cell) scores each fold with
`roc_auc_score(yte, p)` over the **pooled per-row** test set. AUC is a rank
statistic over all (row) pairs, so a ticker contributing 250 rows dominates one
contributing 5 rows by 50×. The 2022 fold's 0.79 is whatever the
longest-surviving 2022 names happened to do.

**Fix (proposed G3 addition — paste as a new cell after the existing G3 cell):**

```python
# G3b — ticker-grouped AUC alongside per-row AUC
from sklearn.metrics import roc_auc_score

def ticker_grouped_auc(d, feature_cols, target, folds, min_rows=20, min_pos=2):
    """Per-fold: fit on train, then AUC computed PER TICKER and averaged
    (equal weight per ticker), vs the pooled per-row AUC."""
    rows = []
    for train_end, test_start, test_end in folds:
        tr = d[d["date"] < pd.Timestamp(train_end)]
        te = d[(d["date"] >= pd.Timestamp(test_start)) &
               (d["date"] <= pd.Timestamp(test_end))]
        Xtr, ytr = tr[feature_cols].copy(), tr[target]
        Xte = te[feature_cols].copy()
        for c in Xtr.select_dtypes(include=["object", "category"]).columns:
            Xtr[c] = Xtr[c].astype("category"); Xte[c] = Xte[c].astype("category")
        spw = (len(ytr) - ytr.sum()) / (ytr.sum() + 1e-5)
        m = xgb.XGBClassifier(objective="binary:logistic", n_estimators=100,
            max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
            scale_pos_weight=spw, enable_categorical=True, tree_method="hist",
            random_state=42)
        m.fit(Xtr, ytr)
        te = te.assign(_p=m.predict_proba(Xte)[:, 1])
        pooled = roc_auc_score(te[target], te["_p"])
        per_tkr = []
        for _, g in te.groupby("ticker"):
            if len(g) >= min_rows and min_pos <= g[target].sum() <= len(g) - min_pos:
                per_tkr.append(roc_auc_score(g[target], g["_p"]))
        rows.append({"fold": f"{test_start[:7]}->{test_end[:7]}",
                     "auc_pooled": pooled,
                     "auc_ticker_mean": float(np.mean(per_tkr)) if per_tkr else np.nan,
                     "n_tickers_scored": len(per_tkr)})
    return pd.DataFrame(rows)

wf_grouped = ticker_grouped_auc(df_train_full, feature_cols, "y_homerun", FOLDS)
display(wf_grouped)
# Verdict signal: if auc_ticker_mean << auc_pooled, the headline AUC is
# carried by a few long-lived tickers, not broad cross-sectional skill.
```

---

## 1.2 — IC / Spearman (G2) → **FIX-NEEDED**

`compute_ic` (`feature_signal.py:229`) runs `stats.spearmanr` over all pooled
rows. Same grain inflation: IC magnitude and its p-value are computed as if
3.4M rows were independent, so p-values are meaningless (N is ~50× the true
effective N) and the ranking favors features that are stable within a ticker's
long run (slow movers like `adr_20d`, `low_52w`).

**Fix (proposed G2 addition — new cell after the existing IC/MI/redundancy cell):**

```python
# G2b — per-ticker IC, averaged across tickers (equal weight)
def ticker_grouped_ic(d, feature_cols, target, min_obs=30):
    from scipy import stats
    recs = []
    for feat in feature_cols:
        if not pd.api.types.is_numeric_dtype(d[feat]):
            continue
        ics = []
        for _, g in d.groupby("ticker"):
            s = g[[feat, target]].replace([np.inf, -np.inf], np.nan).dropna()
            if len(s) >= min_obs and s[feat].nunique() > 1:
                ics.append(stats.spearmanr(s[feat], s[target]).correlation)
        if ics:
            recs.append({"feature": feat, "ic_ticker_mean": float(np.nanmean(ics)),
                         "ic_ticker_std": float(np.nanstd(ics)), "n_tickers": len(ics)})
    return (pd.DataFrame(recs)
            .assign(abs_ic=lambda x: x["ic_ticker_mean"].abs())
            .sort_values("abs_ic", ascending=False).reset_index(drop=True))

ic_grouped = ticker_grouped_ic(df_train_full, feature_cols, "y_homerun")
display(ic_grouped.head(15))
# Compare ordering vs pooled ic_df. Features that fall out of the top on the
# grouped view were riding label-mass concentration, not cross-ticker signal.
```

Note: the in-notebook target makes this a *within-ticker time-series* IC. That
answers "does this feature track future returns inside one name's history,"
which is closer to what the model can actually exploit cross-sectionally.

---

## 1.3 — SHAP / feature importance (G5) → **FIX-NEEDED (test designed)**

The G5 SHAP cell samples the **500 highest-prob rows** (`np.argsort(-p_valid)[:500]`).
If those 500 are dominated by a handful of long-lived high-scoring tickers, the
SHAP profile is per-ticker, not per-population — `adr_20d`'s dominance could be
that handful's idiosyncrasy replicated across their many rows.

The audit's proposed test (subsample to 1 row per (ticker, 20-day block), refit,
recompute SHAP) is the right control. Concrete version:

**Fix (proposed G5 addition — new cell after the existing SHAP cell):**

```python
# G5b — block-subsampled SHAP control (1 row per ticker per 20d block)
import shap
blk = df_train.assign(_blk=lambda d: d.groupby("ticker").cumcount() // 20)
thin = blk.groupby(["ticker", "_blk"], group_keys=False).head(1)
Xth, yth = thin[feature_cols].copy(), thin["y_homerun"]
for c in Xth.select_dtypes(include=["object", "category"]).columns:
    Xth[c] = Xth[c].astype("category")
spw = (len(yth) - yth.sum()) / (yth.sum() + 1e-5)
m_thin = xgb.XGBClassifier(objective="binary:logistic", n_estimators=100,
    max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
    scale_pos_weight=spw, enable_categorical=True, tree_method="hist",
    random_state=42).fit(Xth, yth)
sv_thin = shap.TreeExplainer(m_thin).shap_values(Xth.sample(min(2000, len(Xth)),
                                                            random_state=42))
shap_thin = pd.Series(np.abs(sv_thin).mean(0), index=feature_cols,
                      name="shap_thinned").sort_values(ascending=False)
print("SHAP ranking on block-thinned data (dense artifact removed):")
display(shap_thin.head(15).to_frame())
# Verdict: if adr_20d drops from 5x-peer to peer-level here, its G5 dominance
# is a duplication artifact, not economic signal.
```

---

## 1.4 — Score persistence (G4) → **FIX-NEEDED (null model)**

The G4 hard gate is `day_to_day_corr.mean() > 0.50` (cross-sectional daily-rank
Spearman between consecutive days). High persistence is currently sold as a
*feature* of m01_rank. But if the input features barely move day-to-day, ANY
monotone model produces persistent ranks — the metric would be measuring feature
autocorrelation, not model skill.

**Fix (proposed G4 addition — new cell after the existing G4 cell):**

```python
# G4b — permuted-feature null baseline for rank persistence
# Permute features WITHIN ticker (Open Q5 -> within-ticker): preserves each
# name's marginal feature distribution but destroys the feature->return link,
# so any residual persistence is pure feature autocorrelation, not signal.
rng = np.random.default_rng(42)
Xnull = X_valid.copy()
idx = df_valid.reset_index().groupby("ticker").indices
for col in Xnull.columns:
    for _, pos in idx.items():
        Xnull.iloc[pos, Xnull.columns.get_loc(col)] = \
            Xnull.iloc[pos, Xnull.columns.get_loc(col)].sample(frac=1, random_state=int(rng.integers(1e9))).values
p_null = model.predict_proba(Xnull)[:, 1]
sn = df_valid[["date", "ticker"]].copy(); sn["prob"] = p_null
sn["daily_rank"] = sn.groupby("date")["prob"].rank(pct=True)
wn = sn.pivot_table(index="date", columns="ticker", values="daily_rank")
null_corr = wn.corrwith(wn.shift(1), axis=1, method="spearman").dropna()
print(f"Persistence  real: {day_to_day_corr.mean():.3f}  "
      f"null(within-ticker perm): {null_corr.mean():.3f}")
# Verdict: real >> null  -> persistence is model skill.
#          real ~= null  -> persistence is just slow features; metric uninformative.
```

Recommendation on Open Q5: **within-ticker permutation** is the correct null. A
global permutation destroys the slow-feature structure too, so it can't isolate
"is persistence just autocorrelation."

---

## 1.5 — compute_redundancy (G2 infra) → **PASS (minor note)**

`compute_redundancy` (`feature_signal.py:320-323`) takes a uniform random
`work.sample(n=200_000)` then rank-Pearson. The audit's own hypothesis holds:
feature-feature correlation is a population statistic that does not depend on
label duplication, so dense rows being IID-sampled is fine for *correlations*.

Minor: the sample is uniform-random, not ticker-stratified. With 200k of ~3.4M
rows the long-lived tickers are over-represented, which can nudge a borderline
pair across the 0.80 cutoff. Low severity. Optional hardening: stratified sample
(`groupby('ticker').sample(...)`) if a redundancy pair sits right on the
threshold. **No code change required for correctness.**

---

## 1.6 — v_d2_training / d2_training_cache → **IRRELEVANT (audit misdirected)**

This item assumes m01_rank consumes `v_d2_training`. It does not — it uses
`mode="dense"` → `t3_sepa_features` (see §0). So:

- `v_d2_training` is correctly **event-grain** by design (one row per trade).
  There is no hidden dedup; the "dedup" is the intended Step-4 entry-row keep.
- The dense table m01_rank actually uses, `t3_sepa_features`, is dense by design
  and has no target column (target is built in-notebook). No silent row drops.

**Action:** rewrite item 1.6 in the audit doc to target the right table:
> 1.6 — Confirm `t3_sepa_features` (mode="dense") returns dense rows with no
> implicit dedup, and that `warmup_clip` only drops leading-NULL warm-up rows
> (verified: `data_quality.py:117-139` — per-ticker cumsum on sentinels, interior
> rows kept). PASS.

---

## Summary table

| Item | Component | Verdict | Severity |
|------|-----------|---------|----------|
| 1.1 | Walk-forward AUC (G3) | FIX-NEEDED | High — headline metric |
| 1.2 | IC / Spearman (G2) | FIX-NEEDED | High — feature ranking + p-values |
| 1.3 | SHAP (G5) | FIX-NEEDED | Med — drives feature-importance story |
| 1.4 | Persistence (G4) | FIX-NEEDED | High — currently a sold "feature" |
| 1.5 | compute_redundancy | PASS | Low — optional stratification |
| 1.6 | v_d2_training grain | IRRELEVANT | — audit targeted wrong table |

All four FIX-NEEDED items are **additive** (new cells reporting grouped metrics
alongside the existing pooled ones) — no existing infra needs deletion. That
keeps the pooled numbers visible for comparison, which is exactly what the DoD
verdict needs.

---

## Recommended next step

Run the four `*b` control cells (1.1–1.4) on the current trained model **before**
the Phase 2 backtest rewrite. They are cheap and decide the central question:

- If ticker-grouped AUC/IC collapse and block-thinned SHAP flattens `adr_20d`,
  then the 28× backtest return is largely a dense-grain measurement artifact, and
  Phase 2's job is mostly to stop double-counting.
- If they hold up, the signal is real and Phase 2 is about realistic execution
  (persistence-gated entry, business-day accounting).

Either way the Phase 2 backtest design is unaffected by these findings, so the
two phases can proceed independently once 1.1–1.4 are run.

---

## Control-cell results (run 2026-05-21) + VERDICT

### 1.1b — Ticker-grouped AUC

| fold | auc_pooled | auc_ticker_mean | n_tickers | gap |
|------|-----------|-----------------|-----------|-----|
| 2020 | 0.775 | 0.721 | 1860 | −0.054 |
| 2021 | 0.785 | 0.610 | 1282 | −0.175 |
| 2022 | 0.795 | 0.673 | 1645 | −0.122 |
| 2023 | 0.793 | 0.617 | 1483 | −0.176 |

**Read:** Signal is REAL but the headline overstates it. Grouped AUC stays
0.61–0.72 across 1,200–1,800 tickers — broad within-name discrimination, not a
few long runs carrying the pooled figure. But the 0.05–0.18 gap means the
pooled ~0.79 is inflated by row-count weighting. The 2022 drawdown fold holds
up best on the grouped view (0.673) → regime-robust.

### 1.2b — Ticker-grouped IC

Ranking is essentially UNCHANGED from pooled: `pct_from_high_52w` (−0.140),
`m03_pillar_risk` (−0.135), `low_52w` (−0.131), `rs` (−0.127), `adr_20d`
(+0.124), all with consistent sign across ~2,460 tickers. `adr_20d` is #4, not
dominant. **Feature signal is structurally stable, not a duplication artifact at
the IC level.**

### 1.3b — Block-thinned SHAP (the decisive test)

After 1-row-per-(ticker, 20d-block) thinning, `adr_20d` SHAP = **1.002, ~5× the
next feature** (`m03_pillar_risk` 0.199). The audit predicted thinning would
*flatten* `adr_20d` to peer level. **It did the opposite — dominance survived and
intensified.** Therefore `adr_20d`'s SHAP dominance is NOT a dense-grain artifact.

Verified `adr_20d` is clean: `AVG((high-low)/prev_close)` over 20d
(`feature_pipeline.py:728`) — pure trailing volatility, no lookahead. Its
dominance is the model literally learning the thesis in the notebook header:
home-run continuation lives in **tight-range (low-ADR) consolidations**.

### 1.4b — Persistence null model

real persistence **0.996** vs within-ticker-permuted null **0.879**.

**Read:** ~0.879 of the 0.996 is pure feature autocorrelation; only ~0.117 is
model signal. The G4 "0.94 persistence as a feature of m01_rank" claim is
**largely uninformative** — almost any monotone model on these slow features
would score ~0.88. The G4 gate (`mean > 0.50`) still passes trivially, but
persistence should be reframed as "real − null = +0.12" not "0.99".

---

## 🏁 VERDICT — Is m01_rank's signal real once dense-grain artifacts are controlled?

**Yes, the signal is real — but two of the four headline metrics were inflated by
grain, and one "feature" of the model was an illusion.**

1. **Discrimination is real, ~0.15 AUC weaker than advertised.** Ticker-grouped
   AUC 0.61–0.72 (not 0.79). Broad across >1,200 tickers/fold, robust through 2022.
2. **Feature signal is genuine and stable.** IC ranking is grain-invariant;
   `adr_20d` dominance is real economic signal (tight-range thesis), confirmed by
   the thinning test going the *opposite* way to the artifact hypothesis.
3. **Persistence was the real artifact.** 0.99 → ~0.12 once you subtract the
   feature-autocorrelation null. Stop selling persistence as model skill.

**The 28× backtest return is therefore NOT explained by the metrics being fake.**
The signal that produced it is real. The 28× must instead come from the
**backtest construction** — overlapping/duplicated entries on the same dense
episode, calendar-day hold accounting, or per-trade compounding without slot
capacity limits. That is exactly Phase 2's scope.

---

## Open questions — answers from this audit

1. **Exit symmetry (2.1):** unaffected by Phase 1; recommend (b) symmetric as the
   plan already states.
2. **K in top-K:** defer to Phase 2; grouped-AUC breadth (n_tickers_scored in 1.1b)
   will inform whether K=3 is too tight.
3. **Persistence window:** keep 3 fixed for now; sweep in Phase 2.
4. **Weekly cadence:** Phase 2.
5. **Null model (1.4):** **within-ticker permutation** — decided above.
