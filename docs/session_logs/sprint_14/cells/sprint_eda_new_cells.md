# Sprint 14 EDA — New Cells (§1b, Q3, Q5)

## §1b — REVERSE-ENGINEERING REGIME FROM BREAKOUT COUNTS

### Cell: breakout_daily_counts
```python
# daily breakout counts + regime flags
daily_counts = panel.groupby("date").size().reset_index(name="breakout_count")
daily_counts["date"] = pd.to_datetime(daily_counts["date"])
daily_counts["spy_close"] = daily_counts["date"].map(lambda d: spy.asof(d))
daily_counts["qqq_close"] = daily_counts["date"].map(lambda d: qqq.asof(d))
daily_counts["spy_above200"] = daily_counts["date"].map(
    lambda d: bool(spy.asof(d) > spy.rolling(200).mean().asof(d)) if pd.notna(spy.rolling(200).mean().asof(d)) else np.nan)
daily_counts["qqq_above200"] = daily_counts["date"].map(
    lambda d: bool(qqq.asof(d) > qqq.rolling(200).mean().asof(d)) if pd.notna(qqq.rolling(200).mean().asof(d)) else np.nan)
daily_counts["spy_ret_20"] = daily_counts["spy_close"].pct_change(20)
daily_counts["qqq_ret_20"] = daily_counts["qqq_close"].pct_change(20)
daily_counts["year"] = daily_counts["date"].dt.year

print(f"breakout counts: min {daily_counts.breakout_count.min():.0f}, "
      f"median {daily_counts.breakout_count.median():.0f}, max {daily_counts.breakout_count.max():.0f}")
print(f"\nby regime (SPY>MA200):")
for regime in [True, False]:
    sub = daily_counts[daily_counts.spy_above200 == regime]
    print(f"  {'bull' if regime else 'bear':4s}: {sub.breakout_count.median():.0f} median, "
          f"{sub.breakout_count.mean():.1f} mean, std {sub.breakout_count.std():.1f}")
```

### Cell: breakout_regime_viz
```python
# 4-part viz: (1) time-series, (2) scatter vs future return, (3) regime correlation, (4) year summary
fig = plt.figure(figsize=(16, 10))
gs = fig.add_gridspec(3, 2, hspace=0.35, wspace=0.3)

# (1) TIME-SERIES: daily breakout counts vs SPY price + MA200
ax1 = fig.add_subplot(gs[0, :])
ax1_twin = ax1.twinx()
ax1_twin2 = ax1.twinx()
ax1_twin2.spines["right"].set_position(("outward", 60))
l1, = ax1.plot(daily_counts.date, daily_counts.breakout_count, "o-", color="#3d85c6",
               alpha=0.5, markersize=3, lw=0.8, label="daily breakout count")
l2, = ax1_twin.plot(daily_counts.date, daily_counts.spy_close, color="#333", lw=1, label="SPY")
ma200_ts = spy.rolling(200).mean()
l3, = ax1_twin.plot(ma200_ts.index, ma200_ts.values, color="#e69138", lw=1.5, label="SPY MA200")
bull_mask = daily_counts.spy_above200 == True
ax1_twin2.scatter(daily_counts[bull_mask].date, [1]*bull_mask.sum(), color="#6aa84f",
                  s=20, alpha=0.3, label="bull (>MA200)")
ax1_twin2.scatter(daily_counts[~bull_mask].date, [1]*((~bull_mask).sum()), color="#cc0000",
                  s=20, alpha=0.3, label="bear (<MA200)")
ax1_twin2.set_ylim([0.5, 1.5]); ax1_twin2.set_yticks([]); ax1_twin2.spines["right"].set_visible(False)
ax1.set_ylabel("breakout count", color="#3d85c6")
ax1_twin.set_ylabel("SPY price & MA200", color="#333")
ax1.set_title("§1b — BREAKOUT COUNTS over time: reverse-engineering regime (2003+)")
ax1.tick_params(axis="y", labelcolor="#3d85c6")
ax1_twin.tick_params(axis="y", labelcolor="#333")
ax1.grid(alpha=0.2)
lines = [l1, l2, l3]
ax1.legend(handles=lines, loc="upper left", fontsize=8, ncol=3)

# (2) SCATTER: daily counts vs fwd20 SPY return (does high count = imminent downturn?)
ax2 = fig.add_subplot(gs[1, 0])
daily_counts["fwd_ret_20_spy"] = daily_counts["spy_close"].pct_change(-20)*100
s = daily_counts[daily_counts.fwd_ret_20_spy.notna()].copy()
colors = s.spy_above200.map({True:"#6aa84f",False:"#cc0000"})
ax2.scatter(s.breakout_count, s.fwd_ret_20_spy, alpha=0.4, s=20, c=colors)
z = np.polyfit(s.breakout_count, s.fwd_ret_20_spy, 1)
p = np.poly1d(z)
xs = np.linspace(s.breakout_count.min(), s.breakout_count.max(), 100)
ax2.plot(xs, p(xs), "k--", alpha=0.5, lw=1.5)
corr = s.breakout_count.corr(s.fwd_ret_20_spy, method="spearman")
ax2.set_xlabel("breakout count (today)"); ax2.set_ylabel("SPY fwd 20d return (%)")
ax2.set_title(f"does HIGH breakout count → BAD fwd return? (ρ={corr:+.3f})\nbull (green) vs bear (red)")
ax2.grid(alpha=0.2); ax2.axhline(0, color="k", lw=0.5)

# (3) REGIME STABILITY: rolling 5d mean of counts, bull vs bear
ax3 = fig.add_subplot(gs[1, 1])
daily_counts["breakout_count_ma5"] = daily_counts["breakout_count"].rolling(5).mean()
bull = daily_counts[daily_counts.spy_above200 == True]
bear = daily_counts[daily_counts.spy_above200 == False]
ax3.scatter(bull.date, bull.breakout_count_ma5, alpha=0.5, s=30, color="#6aa84f", label="bull regimes")
ax3.scatter(bear.date, bear.breakout_count_ma5, alpha=0.5, s=30, color="#cc0000", label="bear regimes")
ax3.axhline(bull.breakout_count_ma5.median(), color="#6aa84f", ls="--", lw=1.5, 
            label=f"bull median {bull.breakout_count_ma5.median():.0f}")
ax3.axhline(bear.breakout_count_ma5.median(), color="#cc0000", ls="--", lw=1.5,
            label=f"bear median {bear.breakout_count_ma5.median():.0f}")
ax3.set_ylabel("5d MA of daily counts"); ax3.set_xlabel("date")
ax3.set_title("§1b — Regime signature: bull/bear breakout supply")
ax3.legend(fontsize=8); ax3.grid(alpha=0.2)

# (4) YEAR-BY-YEAR summary: regime %-days vs median breakout count
ax4 = fig.add_subplot(gs[2, :])
year_regime = []
for yr in sorted(daily_counts.year.unique()):
    yr_data = daily_counts[daily_counts.year == yr]
    pct_bull = (yr_data.spy_above200 == True).sum() / len(yr_data) * 100
    med_count = yr_data.breakout_count.median()
    bull_count = yr_data[yr_data.spy_above200==True].breakout_count.median()
    bear_count = yr_data[yr_data.spy_above200==False].breakout_count.median()
    year_regime.append({"year": yr, "pct_bull": pct_bull, "med_count": med_count,
                        "bull_count": bull_count, "bear_count": bear_count})
yr_summary = pd.DataFrame(year_regime)
ax4_twin = ax4.twinx()
ax4.bar(yr_summary.year, yr_summary.pct_bull, alpha=0.4, color="#6aa84f", label="% days in bull")
ax4_twin.plot(yr_summary.year, yr_summary.med_count, "o-", color="#3d85c6", lw=2, ms=4, label="median breakout/day")
ax4.set_xlabel("year"); ax4.set_ylabel("% days above MA200 (bull)", color="#6aa84f")
ax4_twin.set_ylabel("median daily breakouts", color="#3d85c6")
ax4.set_title("§1b — YEAR SUMMARY: regime composition vs breakout supply stability")
ax4.tick_params(axis="y", labelcolor="#6aa84f")
ax4_twin.tick_params(axis="y", labelcolor="#3d85c6")
ax4.legend(loc="upper left", fontsize=8)
ax4_twin.legend(loc="upper right", fontsize=8)
ax4.grid(alpha=0.2)

plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s1b_breakout_regime_reverseeng.png", dpi=110, bbox_inches="tight")
plt.show()
print("\nCORRELATION: breakout count vs fwd SPY return (20d ahead):", f"{corr:+.3f}")
```

---

## Q3 — Score Gate Efficacy: Deployed vs Rejected Equity Fans

Insert after `§2` (after the regime charts cell), before `§3`.

### Cell: q3_rejected_fan_prep
```python
# Q3: Do rejected trades (score <PRIMARY_GATE) underperform? Compare equity fans
# Build DEPLOYED (gated) and REJECTED (filtered-out) trade sets from the score gate
from start_day_basket_paths import basket_paths

# Re-run with the actual score details logged (we need to capture rejected trades)
# Get the raw breakout pool before gating
panel_raw = panel.copy()
panel_raw["gated_flag"] = panel_raw.prob_elite >= PRIMARY_GATE

# Score gate efficacy: deployed vs rejected
deployed = panel_raw[panel_raw.gated_flag == True].copy()
rejected = panel_raw[panel_raw.gated_flag == False].copy()

print(f"Deployed (gate≥{PRIMARY_GATE}): {len(deployed):,} rows ({len(deployed)/len(panel_raw):.1%})")
print(f"Rejected (gate<{PRIMARY_GATE}): {len(rejected):,} rows ({len(rejected)/len(panel_raw):.1%})")
print(f"\nDeployed daily top-5:")
t5_dep = top_n_gated(deployed, 5, gate=None)
print(f"  {len(t5_dep):,} rows, {len(t5_dep)/len(deployed)*100:.1f}% of deployed")
print(f"\nRejected daily top-5:")
t5_rej = top_n_gated(rejected, 5, gate=None)
print(f"  {len(t5_rej):,} rows, {len(t5_rej)/len(rejected)*100:.1f}% of rejected")
```

### Cell: q3_rejected_fan_compare
```python
# Q3: Compare forward returns: deployed vs rejected
def basket_daily_by_pool(p, gate=None):
    t = top_n_gated(p, 5, gate)
    return t.groupby("date")[[h for h in HZ if h in t]].mean().dropna(how="all")

basket_dep = basket_daily_by_pool(deployed, gate=None)
basket_rej = basket_daily_by_pool(rejected, gate=None)

print("DEPLOYED (gate≥0.6) vs REJECTED (gate<0.6) — forward returns:")
print("\nDeployed:")
for h in HZ:
    if h not in basket_dep: continue
    s = basket_dep[h].dropna()
    print(f"  {h:6s}: mean {s.mean():+.1%}, std {s.std():.0%}, loss rate {(s<0).mean():.0%}, n={len(s)}")

print("\nRejected:")
for h in HZ:
    if h not in basket_rej: continue
    s = basket_rej[h].dropna()
    print(f"  {h:6s}: mean {s.mean():+.1%}, std {s.std():.0%}, loss rate {(s<0).mean():.0%}, n={len(s)}")

# Chart: overlay deployed vs rejected fans (fwd100 as key metric)
fig, ax = plt.subplots(figsize=(12, 5))
ax.hist(basket_dep["fwd100"].dropna()*100, bins=50, alpha=0.6, color="#6aa84f", label="deployed (gate≥0.6)", density=True)
ax.hist(basket_rej["fwd100"].dropna()*100, bins=50, alpha=0.6, color="#cc0000", label="rejected (gate<0.6)", density=True)
ax.axvline(0, color="k", lw=0.7)
ax.axvline(basket_dep["fwd100"].mean()*100, color="#6aa84f", ls="--", lw=2, label=f"deployed mean {basket_dep['fwd100'].mean()*100:+.1f}%")
ax.axvline(basket_rej["fwd100"].mean()*100, color="#cc0000", ls="--", lw=2, label=f"rejected mean {basket_rej['fwd100'].mean()*100:+.1f}%")
ax.set_xlabel("fwd100 return (%)"); ax.set_ylabel("density")
ax.set_title("Q3 — Score gate efficacy: deployed (green) vs rejected (red) trade returns\nDoes gating filter bad trades or just noise?")
ax.legend()
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/q3_gated_vs_rejected.png", dpi=110, bbox_inches="tight")
plt.show()
```

---

## Q5 — Macro Regression: Predicting Failure Days

Insert after `§2` regime charts, as an optional research cell before `§3`.

### Cell: q5_macro_regression_prep
```python
# Q5: Can we PREDICT failure days (fwd100 < 0) using macro metrics on trade entry date?
# Build a binary classification: "will this trade fail in 100d?" vs macro state

# Prepare macro features from daily_counts (already has spy_above200, fwd_ret_20_spy)
# Add more macro signals: VIX regime, yield curve, SPY momentum
_con = db.connect(str(ROOT/"data/market_data.duckdb"), read_only=True)
try:
    VIX = _con.execute("SELECT date, close FROM price_data WHERE ticker='VIX' ORDER BY date").df()
    VIX["date"] = pd.to_datetime(VIX["date"])
    vix = VIX.set_index("date")["close"]
except:
    vix = None
_con.close()

# Macro features: on each trade date, what's the market state?
macro_feat = daily_counts[["date","spy_close","spy_above200"]].copy()
macro_feat["spy_ma200"] = spy.rolling(200).mean().reindex(macro_feat["date"]).values
macro_feat["spy_above_ma200"] = macro_feat.spy_close > macro_feat.spy_ma200
macro_feat["spy_ret_5d"] = spy.pct_change(5).reindex(macro_feat["date"]).values
macro_feat["spy_ret_20d"] = spy.pct_change(20).reindex(macro_feat["date"]).values
macro_feat["qqq_ret_5d"] = qqq.pct_change(5).reindex(macro_feat["date"]).values
if vix is not None:
    macro_feat["vix"] = vix.reindex(macro_feat["date"]).values
    macro_feat["vix_ma20"] = vix.rolling(20).mean().reindex(macro_feat["date"]).values
    macro_feat["vix_above_ma20"] = macro_feat.vix > macro_feat.vix_ma20

# Link to forward outcomes: for each date in breakout panel, what was the forward return?
breakout_outcomes = panel.groupby("date")["fwd100"].mean().reset_index()
breakout_outcomes["date"] = pd.to_datetime(breakout_outcomes["date"])
macro_feat = macro_feat.merge(breakout_outcomes, on="date", how="inner")
macro_feat["failure"] = (macro_feat.fwd100 < 0).astype(int)

macro_feat_clean = macro_feat.dropna(subset=["spy_ret_5d","spy_ret_20d","qqq_ret_5d","failure"])
if "vix" in macro_feat_clean.columns:
    macro_feat_clean = macro_feat_clean.dropna(subset=["vix"])

print(f"{len(macro_feat_clean)} days with complete macro features")
print(f"Failure rate (fwd100<0): {macro_feat_clean['failure'].mean():.0%}")
```

### Cell: q5_macro_regression_model
```python
# Q5: Fit a logistic regression to predict failure days
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, confusion_matrix

feat_cols = ["spy_above_ma200", "spy_ret_5d", "spy_ret_20d", "qqq_ret_5d"]
if "vix_above_ma20" in macro_feat_clean.columns:
    feat_cols.append("vix_above_ma20")

X = macro_feat_clean[feat_cols].values.astype(float)
y = macro_feat_clean["failure"].values
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# Fit logistic regression
lr = LogisticRegression(max_iter=1000)
lr.fit(X_scaled, y)
y_pred = lr.predict(X_scaled)
y_proba = lr.predict_proba(X_scaled)[:, 1]
auc = roc_auc_score(y, y_proba)

print("Q5 — Macro Regression to Predict Failure Days (fwd100 < 0)")
print(f"AUC: {auc:.3f}")
print(f"Coefficients (feature importance):")
for i, fc in enumerate(feat_cols):
    print(f"  {fc:20s}: {lr.coef_[0, i]:+.3f}")

# Confusion matrix & performance
cm = confusion_matrix(y, y_pred)
tn, fp, fn, tp = cm.ravel()
specificity = tn / (tn + fp)
sensitivity = tp / (tp + fn)
print(f"\nConfusion Matrix:")
print(f"  TP={tp:,}, FP={fp:,}, TN={tn:,}, FN={fn:,}")
print(f"  Sensitivity (recall): {sensitivity:.1%}, Specificity: {specificity:.1%}")

# Plot: predicted prob vs actual outcome
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
# (1) Distribution of predicted probability, stratified by actual outcome
axes[0].hist(y_proba[y==0], bins=30, alpha=0.6, color="#6aa84f", label="success (fwd100≥0)")
axes[0].hist(y_proba[y==1], bins=30, alpha=0.6, color="#cc0000", label="failure (fwd100<0)")
axes[0].set_xlabel("predicted probability of failure"); axes[0].set_ylabel("count")
axes[0].set_title(f"Q5 — Predicted failure probability (AUC={auc:.3f})")
axes[0].legend()

# (2) Feature importance: coefficients
feat_importance = pd.DataFrame({
    "feature": feat_cols,
    "coef": lr.coef_[0]
}).sort_values("coef", key=abs, ascending=True)
axes[1].barh(feat_importance["feature"], feat_importance["coef"], color="#3d85c6")
axes[1].set_xlabel("logistic coefficient")
axes[1].set_title("Feature importance for predicting failure")
axes[1].grid(alpha=0.2)

plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/q5_macro_failure_model.png", dpi=110, bbox_inches="tight")
plt.show()
```

---

### Cell: q3_rejected_fan_assertions
```python
# Self-check: gate filtering is real
assert (deployed.prob_elite >= PRIMARY_GATE).all(), "deployed set failed gate check"
assert (rejected.prob_elite < PRIMARY_GATE).all(), "rejected set failed gate check"
assert len(deployed) + len(rejected) == len(panel_raw), "deployed + rejected != raw"

# Check: deployed should have BETTER forward returns
dep_mean = basket_dep["fwd100"].mean()
rej_mean = basket_rej["fwd100"].mean()
print(f"\n✓ Deployed mean fwd100: {dep_mean:+.1%} vs Rejected: {rej_mean:+.1%}")
print(f"  Gate filters {'UP' if dep_mean > rej_mean else 'DOWN'} (diff={dep_mean-rej_mean:+.1%})")

# Check: lower loss rate in deployed
dep_loss = (basket_dep["fwd100"] < 0).mean()
rej_loss = (basket_rej["fwd100"] < 0).mean()
print(f"✓ Deployed loss rate: {dep_loss:.0%} vs Rejected: {rej_loss:.0%}")
if dep_loss < rej_loss:
    print(f"  Gate cuts bad trades (saves {(rej_loss-dep_loss)*100:.1f}pp of downside)")
else:
    print(f"  ⚠️ Gate does NOT filter downside (might be noise)")
```

---

## Q5b — Macro Regression: Robustness Check

### Cell: q5_macro_regression_robustness
```python
# Self-check: model makes sense
assert auc > 0.5, f"model worse than random (AUC={auc:.3f})"
assert (y_proba >= 0).all() and (y_proba <= 1).all(), "probabilities out of range"

# Check: most important signal
coef_abs = pd.Series(lr.coef_[0], index=feat_cols).abs().sort_values(ascending=False)
top_feat = coef_abs.index[0]
print(f"\n✓ Macro failure model AUC: {auc:.3f}")
print(f"  Strongest signal: {top_feat} (|coef|={abs(lr.coef_[0][list(feat_cols).index(top_feat)]):.3f})")

# Check: if AUC is strong, what's the deployment implication?
if auc > 0.65:
    print(f"  → Strong signal: deploy only on low-failure-prob days? (test: filter when pred_prob > 0.5)")
elif auc > 0.55:
    print(f"  → Weak signal: macro slightly predictive, but single-feature MA200 may suffice")
else:
    print(f"  → No signal: macro state doesn't predict failure. Regime gate is orthogonal to forward return.")
```

### Cell: q5_macro_regression_deploy_test
```python
# Q5 extended: if we deployed ONLY on low-failure-prob days, how would equity fan change?
# This is a gate variant test (like §5 regime-gate test)
deploy_threshold = 0.40  # only trade when predicted failure prob < 40%

macro_feat_clean["pred_prob_fail"] = y_proba
macro_feat_clean["deploy_q5"] = macro_feat_clean["pred_prob_fail"] < deploy_threshold

# Merge back to panel for a trade-level filter
panel_with_macro = panel.merge(
    macro_feat_clean[["date","pred_prob_fail","deploy_q5"]], 
    on="date", how="left"
)

# Top-5 on macro-gated dates vs ungated
t5_macro_gated = top_n_gated(panel_with_macro[panel_with_macro.deploy_q5==True], 5, gate=None)
t5_ungated = top_n_gated(panel_with_macro, 5, gate=None)

basket_macro_gated = t5_macro_gated.groupby("date")["fwd100"].mean()
basket_ungated = t5_ungated.groupby("date")["fwd100"].mean()

print(f"\nQ5 Deployment Test: macro-filtered vs ungated")
print(f"Ungated:        mean {basket_ungated.mean():+.1%}, loss {(basket_ungated<0).mean():.0%}, n={len(basket_ungated)} days")
print(f"Macro-gated:    mean {basket_macro_gated.mean():+.1%}, loss {(basket_macro_gated<0).mean():.0%}, n={len(basket_macro_gated)} days")
print(f"Upside captured: {len(basket_macro_gated)/len(basket_ungated):.0%}, Sharpe ratio gain: {basket_macro_gated.std()}")

assert len(basket_macro_gated) < len(basket_ungated), "gated should have fewer days"
if basket_macro_gated.mean() > basket_ungated.mean():
    print(f"✓ Macro gate improves mean (+{(basket_macro_gated.mean()-basket_ungated.mean())*100:.1f}bp)")
else:
    print(f"⚠️ Macro gate reduces mean (−{(basket_ungated.mean()-basket_macro_gated.mean())*100:.1f}bp) but cuts dates by {(1-len(basket_macro_gated)/len(basket_ungated))*100:.0f}%")
```

---

# Embedded Charts (for notebook integration)

## §1b — Regime Reversal Chart
![](../../../../data/model_output_eda/sprint_summary/s1b_breakout_regime_reverseeng.png)

## Q3 — Gate Efficacy Chart
![](../../../../data/model_output_eda/sprint_summary/q3_gated_vs_rejected.png)

## Q5 — Macro Failure Model
![](../../../../data/model_output_eda/sprint_summary/q5_macro_failure_model.png)

---

# Integration Notes

1. **§1b** should be inserted after churn tenure cell (after cell `81f9f264`), before `§2` header.
   - Includes: breakout_daily_counts (print + summary), breakout_regime_viz (4-panel chart)
   
2. **Q3** should be inserted after the regime charts (after cell `c14950b3`), before `§3` header.
   - Includes: q3_rejected_fan_prep, q3_rejected_fan_compare (chart), q3_rejected_fan_assertions (self-check)
   
3. **Q5** should be inserted after Q3 or as alternative to §5.
   - Includes: q5_macro_regression_prep, q5_macro_regression_model (chart + AUC), q5_macro_regression_robustness (self-check), q5_macro_regression_deploy_test (extended gate variant)

4. All cells use the same setup (panel, spy, qqq, HZ already defined in the notebook top).

5. Self-checks verify:
   - Gate filters are correctly applied (Q3)
   - Model AUC is above random (Q5)
   - Implications are tested (Q5 deploy variant)
