# Patch: regime-governor.ipynb cells for the SEPA-GATED population (2026-07-09)

The population-inflation fix means `basket_paths`/`basket_paths_minervini` now read genuine
breakouts only (trend_ok AND breakout_ok). Three cells in `regime-governor.ipynb` still carry
**hardcoded titles + asserts from the inflated run** that the gated data falsifies — they halt
execution (cell 16's assert) or state stale numbers. Replace those three cell *sources* verbatim,
then re-execute the notebook. All other cells re-render as-is (their annotations are computed
f-strings, not hardcoded).

Verdict cross-ref: `verdicts/2026-07-09_regime_governor_backtest.md` §7.

**What changed on gated data (why the edits):**
- Governor no longer NARROWS the fan (std 23.7% no-gov vs 24.5% +gov) — it's near-inert; the old
  `assert ng.std() > gov.std()` is now FALSE. The +823%→+202% "kneecap" was off-setup crash-rebound
  draws now excluded from both arms (max +307% either way).
- Minervini payoff ratio is 2.31 → 3.61 (not "2.85 → 6.18"); the overlay is still a null in-lens.

---

### Cell 16 — replace whole source (governor is INERT here, not a "consistency filter"; drop the false assert)

```python
# Same baskets, but let EVERY start-day trade (governor off) — the counterfactual.
summ_ng, paths_ng, _ = basket_paths(sample_every=5, horizon=150, sl_pct=0.15, tp_pct=None,
                                    use_governor=False)
ng = summ_ng[summ_ng.deployed]

def _row(x, label):
    return (f"{label:14s} n={len(x):4d}  mean {x.fwd_return.mean():+.1%}  median {x.fwd_return.median():+.1%}"
            f"  std {x.fwd_return.std():.1%}  losing {(x.fwd_return<0).mean():.0%}  max {x.fwd_return.max():+.0%}")
print(_row(ng, "NO governor"))
print(_row(depsumm, "WITH governor"))

# What the governor DROPS: the SPY<=200d start-days. How would they have done untraded?
gated = set(summ.loc[~summ.deployed, "start"])
dropped = ng[ng.start.isin(gated)]
print(f"\ngated-off start-days: {len(gated)}  |  had we traded them: "
      f"median {dropped.fwd_return.median():+.1%}  losing {(dropped.fwd_return<0).mean():.0%}  "
      f"mean {dropped.fwd_return.mean():+.1%}")

# Governor delta by percentile — the honest picture on GENUINE breakouts.
print("\n  pctile     NO gov    WITH gov     delta")
for q in (0.05, 0.10, 0.50, 0.90, 0.95):
    a, bq = ng.fwd_return.quantile(q), depsumm.fwd_return.quantile(q)
    print(f"    p{int(q*100):02d}     {a:+7.1%}   {bq:+8.1%}   {bq-a:+.1%}")

fig, ax = plt.subplots(figsize=(11, 5))
bins = np.linspace(-20, 120, 60)
ax.hist(ng.fwd_return * 100, bins=bins, color="#888", alpha=0.55, label=f"NO governor (std {ng.fwd_return.std():.0%})")
ax.hist(depsumm.fwd_return * 100, bins=bins, color="#3d85c6", alpha=0.6, label=f"WITH governor (std {depsumm.fwd_return.std():.0%})")
ax.axvline(0, color="k", lw=0.7)
ax.set_xlabel("basket 150d forward return (%)"); ax.set_ylabel("# start-days")
ax.set_title("Cell 2b (GATED population) — on genuine breakouts the governor is near-INERT:\n"
             f"p05/p10 identical (downside untouched), max unchanged ({ng.fwd_return.max():+.0%} both), "
             f"every pctile ~+1%. Not a consistency filter — a near no-op at basket scale.")
ax.legend()
plt.tight_layout(); plt.show()

# The old "governor NARROWS the fan" claim was an inflated-population artifact — assert it's
# roughly a no-op instead (std moves <2pp, max unchanged).
assert abs(ng.fwd_return.std() - depsumm.fwd_return.std()) < 0.03, "governor ~inert on the fan"
assert abs(ng.fwd_return.max() - depsumm.fwd_return.max()) < 1e-6, "top tail unchanged (no kneecap)"
```

---

### Cell 22 — replace whole source (title: governor near-inert, NOT "clips the upside")

```python
fig, ax = plt.subplots(figsize=(11, 5))
bins = np.linspace(-20, 120, 60)
ax.hist(b.fwd_return * 100, bins=bins, color="#888", alpha=0.55,
        label=f"baseline (median {b.fwd_return.median():+.0%}, max {b.fwd_return.max():+.0%})")
ax.hist(g.fwd_return * 100, bins=bins, color="#3d85c6", alpha=0.6,
        label=f"+ governor (median {g.fwd_return.median():+.0%}, max {g.fwd_return.max():+.0%})")
ax.axvline(0, color="k", lw=0.7); ax.axvline(-15, color="#cc0000", ls=":", lw=1, label="-15% floor")
ax.set_xlabel("basket 150d fwd return (%)"); ax.set_ylabel("# start-days")
ax.set_title("Step 1&2 (GATED) — on genuine breakouts the governor is near-INERT:\n"
             f"floor(-15%) days: {(b.fwd_return<=-0.149).mean():.0%} -> {(g.fwd_return<=-0.149).mean():.0%} "
             f"(unchanged) · max {b.fwd_return.max():+.0%} -> {g.fwd_return.max():+.0%} (NOT kneecapped)")
ax.legend()
plt.tight_layout(); plt.show()

# By-percentile: downside identical; the upper tail is NO LONGER trimmed on clean breakouts.
qs = [0.05, 0.10, 0.25, 0.50, 0.90, 0.95]
print("percentile   baseline   governor    delta")
for q in qs:
    bq, gq = b.fwd_return.quantile(q), g.fwd_return.quantile(q)
    print(f"  p{int(q*100):02d}      {bq:+7.1%}   {gq:+7.1%}   {gq-bq:+.1%}")
assert abs(b.fwd_return.quantile(0.10) - g.fwd_return.quantile(0.10)) < 0.005, "downside ~identical"
```

---

### Cell 23 — replace whole source (payoff DOUBLES, but the ratio is now data-driven, not "2.85 -> 6.18")

```python
fig, ax = plt.subplots(figsize=(11, 5))
bins = np.linspace(-25, 120, 60)
pb, pm = _stats(b)["payoff"], _stats(m)["payoff"]
ax.hist(b.fwd_return * 100, bins=bins, color="#3d85c6", alpha=0.55,
        label=f"baseline all-top5,15%  (median {b.fwd_return.median():+.0%}, win/loss {pb:.2f})")
ax.hist(m.fwd_return * 100, bins=bins, color="#e69138", alpha=0.55,
        label=f"Minervini trig+prog+7%  (median {m.fwd_return.median():+.0%}, win/loss {pm:.2f})")
ax.axvline(0, color="k", lw=0.7)
ax.set_xlabel("basket 150d fwd return (%)"); ax.set_ylabel("# start-days")
ax.set_title(f"Step 4 (GATED) — pivot-trigger + tight stop: WORSE median/losing%, "
             f"but the win/loss payoff ratio JUMPS ({pb:.2f} -> {pm:.2f})\n= the asymmetry is real "
             f"(and sharper on genuine breakouts); a fixed-hold lens still can't harvest it")
ax.legend(fontsize=9)
plt.tight_layout(); plt.show()
assert _stats(m)["payoff"] > _stats(b)["payoff"], "Minervini should raise the payoff ratio"
assert m.fwd_return.median() < b.fwd_return.median(), "but its median is worse in this lens (the null)"
```
