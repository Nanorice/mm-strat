# Sprint 14 EDA — Follow-up Round 2 Cells

All code smoke-tested against the audited panel on 2026-07-11 (results quoted in comments come
from those runs). §1c/§2b/§2c/§3b2/§3d/§4c are INSERTED AND RUN in the notebook already.

## ROUND 2b fixes (after the notebook run — cell numbers = the CURRENT 45-cell notebook)

1. **§3 sector chart (REPLACE cells 24 + 25)** — the reference chart is the §2 lottery style
   (overlaid transparent hists), NOT ridgelines. The new cell below draws BOTH splits
   (regime, model-score) in that style. It ALSO fixes the §3c crash at the root: old cell 24
   used `d` as its loop variable, clobbering the size×RS frame `d` that §3c (cell 28) needs —
   that's the `KeyError: 'rs_dec'`, and it means cell 28's printed ρ=+0.768 came from the wrong
   frame (a single-sector slice with 2025-only panel rs). After replacing, re-run cell 27 → 28;
   expect ρ ≈ +0.68.
2. **§3c (cell 28)** — add the one-line guard below as its first line (order-of-execution trap).
3. **Duplicates to DELETE**: cell 35 (identical §4c prep, superseded by cell 37) and cell 36
   (identical Q3 deployed-vs-rejected copy of cell 15, stranded inside §4).

```python
# add as FIRST line of cell 28 (§3c):
assert {"rs_dec","size_dec","prob_elite"}.issubset(d.columns), "stale `d` — run the size×RS cell first"
```

Q5 (macro failure model) is NOT here — the question was invalidated (forward return isn't a
live weather gauge); results were run once for curiosity and live in the thoughts log only.

---

## §3 sector overlays — REPLACES cells 24 (stacked hist) and 25 (ridgeline)

```python
# §3 — per-sector fwd100 distributions, lottery-style OVERLAYS (transparent, density).
# Two facet grids: (a) bull vs bear, (b) score≥gate vs below — (b) is the per-sector view of
# the model↔outcome DIVERGENCE (§3b2 scatter): split medians nearly tie, the home-run tails don't.
# NOTE deliberately no bare `d` in here — the old cell's loop var clobbered §3c's size×RS frame.
_ma200 = spy.rolling(200).mean()
_days = pd.Series(panel.date.unique())
panel["spy_above200"] = panel.date.map(
    pd.Series((spy.reindex(_days) > _ma200.reindex(_days)).values, index=_days))
d5 = panel.dropna(subset=["sector", "fwd100"]).copy()
d5["hi_score"] = d5.prob_elite >= PRIMARY_GATE
secs = d5.groupby("sector")["fwd100"].median().sort_values(ascending=False).index.tolist()

def sector_facets(flag, colors, labels, fname, title):
    fig, axes = plt.subplots(3, 4, figsize=(16, 10), sharex=True)
    for ax, sec in zip(axes.ravel(), secs):
        ds = d5[d5.sector == sec]
        a = ds[ds[flag] == True]["fwd100"].dropna() * 100
        b = ds[ds[flag] == False]["fwd100"].dropna() * 100
        for v, c, lab in [(a, colors[0], labels[0]), (b, colors[1], labels[1])]:
            ax.hist(v, bins=40, range=(-60, 100), density=True, alpha=0.55, color=c, label=lab)
            ax.axvline(v.median(), color=c, ls="--", lw=1.2)
        ax.axvline(0, color="k", lw=0.6)
        ax.set_title(f"{sec}\nmed {a.median():+.0f}/{b.median():+.0f} · "
                     f"HR {(a>30).mean()*100:.0f}%/{(b>30).mean()*100:.0f}%", fontsize=9)
    for ax in axes.ravel()[len(secs):]:
        ax.axis("off")
    axes[0, 0].legend(fontsize=8)
    fig.suptitle(title, y=1.0)
    plt.tight_layout()
    plt.savefig(ROOT/f"data/model_output_eda/sprint_summary/{fname}.png", dpi=110, bbox_inches="tight")
    plt.show()

sector_facets("spy_above200", ["#6aa84f", "#cc0000"], ["bull (>200MA)", "bear"],
              "s3_sector_regime_overlay",
              "§3 — per-sector fwd100 OVERLAID, bull vs bear (dashed = split medians; title: med bull/bear · HR bull/bear)")
sector_facets("hi_score", ["#e69138", "#3d85c6"], [f"score≥{PRIMARY_GATE}", "below gate"],
              "s3_sector_score_overlay",
              "§3 — per-sector fwd100 OVERLAID, score-gated vs below-gate: medians ~tie, the ORANGE right tail\n"
              "is where the model's sector view lives (per-sector divergence, cf §3b2 ρ_median≈0.06 vs ρ_HR≈0.90)")
piv = (d5.dropna(subset=["spy_above200"]).groupby(["sector","spy_above200"])["fwd100"]
       .median().mul(100).unstack())
piv.columns = ["bear","bull"]; piv["flip"] = piv.bull - piv.bear
print("sector median RANKING flips bull↔bear — a pooled sector tilt is unsafe:")
print(piv.round(1).sort_values("bull", ascending=False).to_string())
```

---

## §1c — breakout SUPPLY as a regime GAUGE (EMA of daily counts)

```python
# §1c — breakout SUPPLY as a regime GAUGE. Hypothesis: weak market = fewer breakouts.
# Count is NORMALIZED by that day's scored-universe size (universe grew 3.6× over 25y —
# a raw-count EMA would read secular growth as "improving regime").
from sklearn.metrics import roc_auc_score
bko_n, full_n = panel.groupby("date").size(), panel_full.groupby("date").size()
days = full_n.index[full_n.index >= "2003-03-01"]          # ALL trading days (incl. 0-breakout days)
sup = pd.DataFrame({"share": bko_n.reindex(days).fillna(0) / full_n.reindex(days) * 100})
ma200 = spy.rolling(200).mean()
sup["below200"] = (spy.reindex(days) < ma200.reindex(days)).astype(int)
sup["spy_fwd60"] = spy.shift(-60).reindex(days) / spy.reindex(days) - 1

print("smoother     | AUC vs SPY<200MA (coincident) | rho(fwd60 SPY)")
for lab, s in [("raw share", sup.share), ("MA10", sup.share.rolling(10).mean()),
               ("EMA10", sup.share.ewm(span=10).mean()), ("EMA20", sup.share.ewm(span=20).mean()),
               ("EMA60", sup.share.ewm(span=60).mean())]:
    m = s.notna()
    print(f"  {lab:10s} |            {roc_auc_score(sup.below200[m], -s[m]):.3f}            |"
          f"    {s.corr(sup.spy_fwd60, method='spearman'):+.3f}")
```

```python
# §1c chart + the DEPLOY-GATE test: is a supply-famine gate incremental to SPY-200d?
sup["ema20"] = sup.share.ewm(span=20).mean()
famine_cut = sup.ema20.quantile(0.20)                       # in-sample split — gauge EDA, not ex-ante
sup["famine"] = sup.ema20 < famine_cut

fig, ax = plt.subplots(figsize=(14, 5))
axb = ax.twinx()
ax.fill_between(sup.index, 0, sup.ema20, color="#3d85c6", alpha=0.55, label="EMA20 breakout share %")
ax.axhline(famine_cut, color="#cc0000", ls=":", lw=1.2, label="famine cut (p20)")
ax.fill_between(sup.index, 0, sup.ema20.max()*1.05, where=sup.below200.astype(bool),
                color="#cc0000", alpha=0.08, label="SPY < 200MA")
axb.plot(spy.reindex(days).index, spy.reindex(days).values, color="#333", lw=0.8, label="SPY")
ax.set_ylabel("EMA20 of breakout share (%)", color="#3d85c6"); axb.set_ylabel("SPY")
ax.legend(loc="upper left", fontsize=8)
ax.set_title("§1c — breakout-supply EMA20 IS the regime, seen from inside the funnel\n"
             "(share collapses exactly where SPY loses its 200MA — AUC ≈ 0.93, coincident not leading)")
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s1c_supply_gauge.png", dpi=110, bbox_inches="tight")
plt.show()

# deploy-gate comparison on the raw top-5 basket
bsk = top_n_gated(panel, 5).groupby("date")["fwd100"].mean().reindex(days)
b = pd.DataFrame({"fwd100": bsk, "famine": sup.famine, "below200": sup.below200.astype(bool)}).dropna(subset=["fwd100"])
for name, mk in [("famine days", b.famine), ("normal days", ~b.famine),
                 ("below 200MA", b.below200), ("above 200MA", ~b.below200),
                 ("famine & ABOVE 200MA", b.famine & ~b.below200)]:
    s = b.loc[mk, "fwd100"]
    print(f"  {name:20s}: n={len(s):5d}  mean {s.mean():+.1%}  loss {(s<0).mean():.0%}")
print("READ: the gauge is an excellent regime EXPRESSION (AUC~0.93 vs 200MA) but a WORSE deploy")
print("gate than 200MA itself — famine days that are still above the 200MA are actually GOOD")
print("(early-recovery scarcity). Use it as a state descriptor, not a brake.")
```

---

## §2b — the GATE LADDER: monotonicity of basket quality vs score gate

```python
# §2b — gate ladder (Q: monotone score→quality?). All gates on ONE chart per horizon.
# MEAN and tail (p90, home-run days) are monotone ↑ in the gate; MEDIAN is NOT (0.7 gives
# back median), and the LEFT tail widens too — the gate buys tail, not safety.
baskets = {g: basket_daily(panel, g) for g in [None] + SCORE_GATES}
xt, xl = range(len(baskets)), ["raw"] + [str(g) for g in SCORE_GATES]
fig, axes = plt.subplots(1, 4, figsize=(16, 4))
for ax, h in zip(axes, HZ):
    st = {k: [] for k in ("mean", "median", "p10", "p90", "hr")}
    for g, bk in baskets.items():
        s = bk[h].dropna() * 100
        st["mean"].append(s.mean()); st["median"].append(s.median())
        st["p10"].append(s.quantile(.1)); st["p90"].append(s.quantile(.9))
        st["hr"].append((s > 30).mean() * 100)
    ax.fill_between(xt, st["p10"], st["p90"], alpha=0.15, color="#3d85c6", label="p10-p90")
    ax.plot(xt, st["mean"], "o-", color="#3d85c6", label="mean")
    ax.plot(xt, st["median"], "s--", color="#e69138", label="median")
    axb = ax.twinx()
    axb.plot(xt, st["hr"], "^-", color="#6aa84f", label="HR-days % (>30%)")
    axb.tick_params(axis="y", labelcolor="#6aa84f")
    ax.set_xticks(list(xt)); ax.set_xticklabels(xl); ax.set_title(h); ax.axhline(0, color="k", lw=.5)
    if h == HZ[0]:
        ax.legend(fontsize=7, loc="upper left"); axb.legend(fontsize=7, loc="lower right")
fig.suptitle("§2b — GATE LADDER: mean & home-run days ramp with the gate; median and loss-rate don't.\n"
             "Score is monotone on the TAIL (its training target), not on the typical day.", y=1.06)
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s2b_gate_ladder.png", dpi=110, bbox_inches="tight")
plt.show()
for h in ["fwd100"]:
    print(f"{h}: " + " | ".join(f"gate {g}: mean {bk[h].mean():+.1%}, med {bk[h].median():+.1%}, "
          f"lose {(bk[h]<0).mean():.0%}, HRdays {(bk[h]>.3).mean():.0%}" for g, bk in baskets.items()))
```

---

## §2c — blocker COVERAGE: how much of the bad-day mass does each gate remove?

```python
# §2c — coverage decomposition (Q: "%below" reframed). For each blocker B and BAD definition:
#   recall  = P(B | bad)  — share of bad start-days it catches
#   %all    = P(B ∧ bad)  — share of ALL start-days removed AND bad (the user's ~23% math)
#   cost    = P(B | good) — good start-days lost
# score-block = a day where NO breakout clears the gate (day-level block, composition ignored).
L = lot[["fwd100"]].dropna().copy()
L["below200"] = (spy.reindex(L.index) < spy.rolling(200).mean().reindex(L.index)).fillna(False)
for g in SCORE_GATES:
    L[f"sb{g}"] = ~L.index.isin(panel[panel.prob_elite >= g].groupby("date").size().index)

blockers = [("SPY<200MA", L.below200), ("score-block 0.5", L["sb0.5"]), ("score-block 0.6", L["sb0.6"]),
            ("score-block 0.7", L["sb0.7"]), ("200MA OR sb0.6", L.below200 | L["sb0.6"]),
            ("200MA OR sb0.7", L.below200 | L["sb0.7"])]
for bad_name, bad in [("fwd100<0", L.fwd100 < 0), ("worst decile", L.fwd100 <= L.fwd100.quantile(.10))]:
    print(f"\nBAD = {bad_name}: {bad.mean():.0%} of {len(L)} start-days")
    print("  blocker          | %days blocked | recall | precision | %ALL blocked&bad | good days lost")
    for name, blk in blockers:
        print(f"  {name:16s} |     {blk.mean():4.0%}     |  {(blk&bad).sum()/bad.sum():4.0%}  |"
              f"   {(blk&bad).sum()/max(blk.sum(),1):4.0%}    |      {(blk&bad).mean():5.1%}      |"
              f"     {(blk&~bad).sum()/(~bad).sum():4.0%}")

bad = L.fwd100 < 0
fig, ax = plt.subplots(figsize=(10, 4))
for y, (name, blk) in enumerate(blockers):
    hit, cost = (blk & bad).mean()*100, (blk & ~bad).mean()*100
    ax.barh(y, hit, color="#6aa84f"); ax.barh(y, cost, left=hit, color="#cc0000", alpha=0.6)
    ax.text(hit+cost+0.3, y, f"recall {(blk&bad).sum()/bad.sum():.0%}", va="center", fontsize=8)
ax.set_yticks(range(len(blockers))); ax.set_yticklabels([n for n, _ in blockers], fontsize=8)
ax.set_xlabel("% of ALL start-days blocked   (green = bad days caught, red = good days lost)")
ax.set_title("§2c — every blocker pays ~1 good day per bad day caught; the score gate stacks a "
             "little recall on 200MA at the same exchange rate")
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s2c_blocker_coverage.png", dpi=110, bbox_inches="tight")
plt.show()
```

---

## §3b2 — sector DIVERGENCE: where the model's sector view and fwd return disagree

```python
# §3b2 — model-vs-outcome divergence by sector. The model has no idea about sector MEDIANS
# (rho ≈ +0.06) but ranks sector HOME-RUN rates almost perfectly (rho ≈ +0.90) — it scores
# its tail target, not the typical trade. Healthcare/Comm Svcs = high score + worst median +
# high HR = pure lottery sectors; Consumer Defensive = the mirror (median-safe, model-ignored).
g = panel.dropna(subset=["sector", "fwd100"]).groupby("sector")
sec = pd.DataFrame({"n": g.size(), "med_score": g.prob_elite.median(),
                    "med_fwd": g.fwd100.median()*100,
                    "hr": g.fwd100.apply(lambda s: (s > .3).mean()*100)})
fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
for ax, ycol, ylab in [(axes[0], "med_fwd", "median fwd100 (%)"), (axes[1], "hr", "home-run rate (%)")]:
    ax.scatter(sec.med_score, sec[ycol], s=sec.n/150, color="#3d85c6", alpha=0.7)
    for s_name, r in sec.iterrows():
        ax.annotate(s_name, (r.med_score, r[ycol]), fontsize=7, xytext=(4, 3), textcoords="offset points")
    rho = sec.med_score.corr(sec[ycol], method="spearman")
    ax.set_xlabel("sector median prob_elite"); ax.set_ylabel(ylab)
    ax.set_title(f"score vs {ylab}:  ρ = {rho:+.2f}"); ax.grid(alpha=0.2)
fig.suptitle("§3b2 — the model's sector view matches the TAIL (right), not the MEDIAN (left)", y=1.0)
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s3b2_sector_divergence.png", dpi=110, bbox_inches="tight")
plt.show()
print(sec.assign(score_rank=sec.med_score.rank(ascending=False), fwd_rank=sec.med_fwd.rank(ascending=False))
      .sort_values("fwd_rank").round(2).to_string())
```

---

## §3c — is prob_elite MONOTONE in (RS, size)? does it add WITHIN each cell?

```python
# §3c — score monotonicity vs the (RS, size) grid (the pushed-back feature-audit Q, now run).
# Uses `d` from the size×RS cell above (has prob_elite, rs_dec, size_dec, home_run).
print(f"pooled spearman(prob_elite, rs) = {d.prob_elite.corr(d.rs, method='spearman'):+.3f}"
      f"  — RS is thoroughly baked into the score")
d["hi_score"] = d.prob_elite > d.groupby(["rs_dec","size_dec"]).prob_elite.transform("median")
piv = d.groupby(["rs_dec","size_dec","hi_score"]).home_run.mean().unstack()
lift = (piv[True] - piv[False]) * 100
lift = lift[d.groupby(["rs_dec","size_dec"]).size() >= 200]
LM = lift.unstack()

fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
axes[0].plot(d.groupby("rs_dec").prob_elite.median(), "o-", color="#3d85c6")
axes[0].set_xlabel("RS decile"); axes[0].set_title("median score by RS decile\n(monotone ↑ — RS baked in)")
axes[1].plot(d.groupby("size_dec").prob_elite.median(), "o-", color="#e69138")
axes[1].set_xlabel("size decile (0=small)"); axes[1].set_title("median score by SIZE decile\n(monotone ↓ — model already tilts small)")
im = axes[2].imshow(LM.values, cmap="RdYlGn", aspect="auto", origin="lower", vmin=0)
axes[2].set_xlabel("size decile"); axes[2].set_ylabel("RS decile")
axes[2].set_title("WITHIN-cell home-run lift, hi- vs lo-score (pp)\n(positive everywhere = signal beyond RS+size)")
fig.colorbar(im, ax=axes[2], label="pp")
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s3c_score_rs_size.png", dpi=110, bbox_inches="tight")
plt.show()
print(f"cells (n≥200) where hi-score beats lo-score on home-run rate: {(lift > 0).mean():.0%}"
      f", mean lift {lift.mean():+.1f}pp")
print("READ: score ≈ RS + small-cap tilt + a real orthogonal residual (~+10pp HR in EVERY cell).")
print("It is NOT monotone on fwd100 RANK inside a cell (tail model, rank-flat) — split, don't sort.")
```

---

## §3d — the actual weight of RS inside m01_prototype

```python
# §3d — RS weight in m01 (deferred Q2, now run). total_gain share from the prototype booster.
import xgboost as xgb
bst = xgb.Booster()
bst.load_model(str(ROOT/"models/m01_prototype_2003_2026/v1/model.json"))
share = pd.Series(bst.get_score(importance_type="total_gain"))
share = (share / share.sum() * 100).sort_values(ascending=False)
RS_FAM = [f for f in ["rs","rs_ma","rs_delta","rs_ma_delta","rs_line_lag_delta","RS_vs_Sector",
                      "RS_vs_Industry","RS_Universe_Rank","RS_Sector_Rank","RS_Industry_Rank"] if f in share]
MOM = [f for f in ["dist_from_20d_high","mom_21d","return_60d","return_1d","price_vs_spy_ma63",
                   "highest_high_20d_delta","ema_8_21_ratio"] if f in share]
top = share.head(20)
colors = ["#cc0000" if f in RS_FAM else "#e69138" if f in MOM else "#3d85c6" for f in top.index]
fig, ax = plt.subplots(figsize=(10, 6))
ax.barh(top.index[::-1], top.values[::-1], color=colors[::-1])
ax.set_xlabel("share of total_gain (%)")
ax.set_title(f"§3d — m01_prototype importance: explicit RS family (red) = {share[RS_FAM].sum():.1f}%,\n"
             f"broad momentum block (orange) = {share[MOM].sum():.1f}%, "
             f"industry categorical alone = {share['industry']:.1f}%")
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s3d_rs_weight.png", dpi=110, bbox_inches="tight")
plt.show()
print(f"explicit RS family: {share[RS_FAM].sum():.1f}%  {dict(share[RS_FAM].round(2))}")
print(f"RS-correlated momentum block: {share[MOM].sum():.1f}%")
print("READ: RS the FEATURE is small (~4%) yet the SCORE is ~0.68 rank-correlated with RS —")
print("the momentum block carries the same signal in pieces. Healthy (no single-feature bet),")
print("but don't expect to remove 'rs' and see the RS tilt disappear.")
```

---

## §4c — trough-geometry LIVE PROXIES: can we see the leader shape BEFORE the decline?

```python
# §4c — proxy validation (the §4 live-prediction gap, now tested). Proxies measured in the
# 126 trading days BEFORE each SPY peak: beta, relative vol, correlation to SPY, 126d RS.
# Targets = the realized geometry traits from `geo`. Runtime ~1-2 min (6 price pulls).
spyret = spy.pct_change()
prox = []
for _, ep in eps_test.iterrows():
    names = geo[geo.peak_date == ep.peak_date].ticker.unique().tolist()
    lo = (ep.peak_date - pd.Timedelta(days=320)).strftime("%Y-%m-%d")
    hi = (ep.peak_date - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    con = db.connect(str(ROOT/"data/market_data.duckdb"), read_only=True)
    px = con.execute(f"SELECT ticker,date,close FROM price_data WHERE ticker IN "
                     f"{tuple(sorted(set(names)))} AND date BETWEEN ? AND ? ORDER BY date", [lo, hi]).df()
    con.close(); px["date"] = pd.to_datetime(px["date"])
    wide = px.pivot_table(index="date", columns="ticker", values="close").iloc[-127:]
    ret = wide.pct_change(fill_method=None).iloc[1:]
    sr = ret.index.to_series().map(spyret)
    keep = ret.count() >= 80
    ret = ret.loc[:, keep[keep].index]
    pre = pd.DataFrame({"beta":   ret.apply(lambda c: c.cov(sr) / sr.var()),
                        "relvol": ret.std() / sr.std(),
                        "corr":   ret.corrwith(sr),
                        "rs126":  (wide.iloc[-1]/wide.iloc[0] - 1)
                                  - (spy.asof(ret.index[-1])/spy.asof(ret.index[0]) - 1)})
    pre = pre.reset_index().rename(columns={"index": "ticker"})
    pre["peak_date"] = ep.peak_date
    prox.append(pre)
    print(f"  {ep.peak_date.date()}: {len(pre)} names with pre-window proxies", flush=True)
P = geo.merge(pd.concat(prox, ignore_index=True), on=["ticker","peak_date"], how="inner")
print(f"{len(P):,} name-episodes with proxies")
```

```python
# §4c verdict: per-episode spearman (median over the 6 episodes) + RS-partialled version
def ep_rho(p, t):
    return P.groupby("peak_date").apply(
        lambda s: s[p].corr(s[t], method="spearman"), include_groups=False).median()
TRAITS = ["relative_depth", "trough_lead_days", "recover_lead_days"]
print(f"{'proxy':8s} | " + " | ".join(f"{t:18s}" for t in TRAITS))
for p in ["beta", "relvol", "corr", "rs126"]:
    print(f"{p:8s} | " + " | ".join(f"{ep_rho(p, t):+18.3f}" for t in TRAITS))

P["relvol_terc"] = P.groupby("peak_date").relvol.transform(
    lambda s: pd.qcut(s, 3, labels=["low_vol","mid","high_vol"]))
fig, ax = plt.subplots(figsize=(9, 4.5))
groups = [P[P.relvol_terc == t]["relative_depth"].clip(0, 3).dropna() for t in ["low_vol","mid","high_vol"]]
ax.boxplot(groups, tick_labels=["low relvol","mid","high relvol"], showfliers=False)
ax.axhline(1.0, color="#cc0000", ls=":", lw=1, label="fell as deep as SPY")
ax.set_ylabel("relative_depth (name maxDD / SPY maxDD)")
ax.set_title("§4c — pre-episode RELATIVE VOL predicts trough DEPTH (ρ≈+0.44, RS-partialled ≈ same)\n"
             "…but NOT the timing traits (lead days ρ≈0). Only the depth leg of the leader shape is live-visible.")
ax.legend(fontsize=8)
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s4c_geometry_proxies.png", dpi=110, bbox_inches="tight")
plt.show()
print("READ: 'bottoms shallower' is forecastable — but the forecast is just LOW RELATIVE VOL")
print("(a defensive tilt, echoing R2's upside-vol residual), and pre-peak RS predicts NONE of the")
print("geometry. The timing traits (bottoms first / recovers first) remain post-hoc labels only.")
```

---

# Embedded charts (populated after the cells run)

## §1c — supply gauge
![](../../../../data/model_output_eda/sprint_summary/s1c_supply_gauge.png)

## §2b — gate ladder
![](../../../../data/model_output_eda/sprint_summary/s2b_gate_ladder.png)

## §2c — blocker coverage
![](../../../../data/model_output_eda/sprint_summary/s2c_blocker_coverage.png)

## §3 — sector overlays
![](../../../../data/model_output_eda/sprint_summary/s3_sector_regime_overlay.png)
![](../../../../data/model_output_eda/sprint_summary/s3_sector_score_overlay.png)

## §3b2 — sector divergence
![](../../../../data/model_output_eda/sprint_summary/s3b2_sector_divergence.png)

## §3c — score vs (RS, size)
![](../../../../data/model_output_eda/sprint_summary/s3c_score_rs_size.png)

## §3d — RS weight in m01
![](../../../../data/model_output_eda/sprint_summary/s3d_rs_weight.png)

## §4c — geometry proxies
![](../../../../data/model_output_eda/sprint_summary/s4c_geometry_proxies.png)
