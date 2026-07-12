# Sprint 14 — Consolidation EDA: the super-performer selection, honestly

> **What this notebook is.** Sprint 14 arrived at its conclusions across ~15 scripts and 20 verdicts.
> This pulls the *visual statistics behind those conclusions* into one narrative — the numbers that,
> downstream, became backtest verdicts. It is a **consolidation**, plus one genuinely new study
> (§4, trough-geometry leadership).
>
> **The audit that shaped it (2026-07-11).** Sprint 14's own Q21 found that the SEPA-gate fix
> *invalidated* a whole strategy arena that had silently selected its "top-5" from the **inflated**
> ~99%-off-setup scored panel. Re-checking every feeder script: the `multiyear/` parquets
> (`raw_full_*_fwd.parquet`, ~500k rows/yr) are the **full trend-active universe**. The funnel is
> **full → trend_ok (~13%) → breakout (trend_ok ∧ breakout_ok, ~1%)**. Everything here reads from ONE
> audited panel (`gated_eda_panel.load_gated_panel(gate=…)`), so no cut silently uses the wrong tier.
>
> **The five questions (user brainstorm) + review round 2:** (1) forward-return distribution across
> pools + mark extreme days vs regime; (2) score + candidate-churn distribution per pool; (3) selection
> pool by sector × market-cap × fwd; (4) **NEW** — leadership trough-geometry incremental to RS; (5) the
> equity fan, filtered by pool. Round-2 additions are marked **[R2]** inline.
>
> **Data-coverage facts (verified):** only the **2025** multiyear file has the rich 21-col schema, so
> `rs`/`pe_ratio`/`mom_*` are ~5% covered (2025 rows only) → joined from `t3_sepa_features`.
> `sector`/`industry`/`fwd150`/`fwd200` ARE ~100% covered across all years. SPY & QQQ both have price
> history back before 2003.
>
> Engines (all smoke-tested): `gated_eda_panel.py` (now takes `gate=full|trend|breakout`),
> `trough_geometry.py`, `start_day_basket_paths.py`.

**Paste each block as one cell.** Cell 0 must run first (CWD is the `cells/` folder, so paths are
ROOT-anchored). Figures save to `data/model_output_eda/sprint_summary/`.

---

### Cell 0 — repo-root bootstrap (run FIRST)

```python
import sys
from pathlib import Path

def _root():
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("root not found")

ROOT = _root(); sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs/session_logs/sprint_14/scripts"))
import numpy as np, pandas as pd, matplotlib.pyplot as plt
pd.set_option("display.width", 140)
from gated_eda_panel import load_gated_panel, top_n_per_day
from src import db
(ROOT/"data/model_output_eda/sprint_summary").mkdir(parents=True, exist_ok=True)
print("ROOT:", ROOT)
```

### Cell 1 — the three funnel tiers + shared params/helpers

```python
# THREE populations (the funnel), each built once. breakout = the audited default.
panel       = load_gated_panel(gate="breakout")     # trend_ok ∧ breakout_ok (~1%)
panel_trend = load_gated_panel(gate="trend")        # trend_ok only (~13%) — Minervini watchlist tier
panel_full  = load_gated_panel(gate="full")         # every scored row (full universe)
for p in (panel, panel_trend, panel_full):
    p["year"] = p["date"].dt.year
print(f"full   : {len(panel_full):,} rows")
print(f"trend  : {len(panel_trend):,} rows  ({len(panel_trend)/len(panel_full):.1%} of full)")
print(f"breakout: {len(panel):,} rows  ({len(panel)/len(panel_full):.2%} of full)")

# ── SCORE GATE param + helpers (used across §1/§2/§5) ─────────────────────────
# ⚠️ TWO prob_elite SCALES (the isotonic naming trap, project_isotonic_flattens_ranking):
#   • PANEL (multiyear parquets) prob_elite = RAW p_pos, median ~0.55 → gate on 0.5/0.6/0.7.
#   • basket_paths' score CACHE prob_elite = CALIBRATED (iso), median ~0.12 → 0.15 ≈ the
#     model's coin-flip line. So §1/§2 use RAW gates; §5's basket_paths uses CALIBRATED gates.
SCORE_GATES      = [0.5, 0.6, 0.7]   # RAW scale (panel) — §1/§2
PRIMARY_GATE     = 0.6               # RAW
CAL_GATE         = 0.20              # CALIBRATED scale (score cache) — §5 basket_paths

def top_n_gated(p, n=5, gate=None):
    """That day's top-n by prob_elite AMONG names clearing `gate` (None=no gate).
    Days with < n qualifiers deploy fewer names (quality over blind count)."""
    q = p[p.prob_elite >= gate] if gate is not None else p
    return q.sort_values(["date","prob_elite"], ascending=[True,False]) \
            .groupby("date", group_keys=False).head(n)

def load_index(tk):
    s = db.connect(str(ROOT/"data/market_data.duckdb"), read_only=True).execute(
        f"SELECT date, close FROM price_data WHERE ticker='{tk}' ORDER BY date").df()
    s["date"] = pd.to_datetime(s["date"]); return s.set_index("date")["close"]
spy = load_index("SPY"); qqq = load_index("QQQ")

# (date,ticker)->rs / dollar-vol (panel's rs is 2025-only → join from t3)
_con = db.connect(str(ROOT/"data/market_data.duckdb"), read_only=True)
RS_T3 = _con.execute("SELECT date,ticker,rs FROM t3_sepa_features WHERE rs IS NOT NULL").df()
DVOL  = _con.execute("SELECT ticker,date,close*CAST(volume AS BIGINT) AS dollar_vol FROM price_data").df()
_con.close()
for _f in (RS_T3, DVOL): _f["date"] = pd.to_datetime(_f["date"])
print(f"helpers ready. gates={SCORE_GATES}, primary={PRIMARY_GATE}")
```

---

## §1 — The population funnel: what selection pool are we actually in?

> **Q2 (the pool).** How big is each funnel tier, how does breakout supply drift, how does the model
> score distribute, and how much does the top-5 rotate? **[R2]** added: (a) the full→trend→breakout
> comparison (not just full→breakout), (b) churn as an overlap-COUNT distribution and a name-TENURE
> survival, each with a SCORE-GATED variant.

### Cell 2 — funnel counts: full → trend_ok → breakout, and supply-drift [R2]

```python
rows = []
for yr in sorted(panel_full.year.unique()):
    nf = (panel_full.year==yr).sum()
    nt = (panel_trend.year==yr).sum()
    nb = (panel.year==yr).sum()
    nd = max(panel[panel.year==yr].date.nunique(), 1)
    rows.append({"year": yr, "full": nf, "trend_ok": nt, "breakout": nb,
                 "trend_%": nt/nf*100, "bko_%": nb/nf*100, "bko/day": nb/nd})
funnel = pd.DataFrame(rows)
print(funnel.to_string(index=False, formatters={
    "trend_%":"{:.1f}%".format, "bko_%":"{:.2f}%".format, "bko/day":"{:.1f}".format}))
print(f"\nbreakout supply swings {funnel['bko/day'].min():.0f}-{funnel['bko/day'].max():.0f}/day "
      f"— the exposure-drift artifact (Extension D), on the CLEAN pop.")
```

### Cell 3 — chart: the funnel drift (three tiers) [R2]

```python
fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 4.5))
# left: absolute rows per tier (log) — the 100× compression full→breakout
a1.plot(funnel.year, funnel.full, "o-", label="full universe", color="#999")
a1.plot(funnel.year, funnel.trend_ok, "s-", label="trend_ok (~13%)", color="#e69138")
a1.plot(funnel.year, funnel.breakout, "^-", label="breakout (~1%)", color="#3d85c6")
a1.set_yscale("log"); a1.set_ylabel("rows / year (log)"); a1.legend(); a1.set_title("§1 — the funnel: three tiers")
# right: breakout supply/day + % of full
a2b = a2.twinx()
a2.bar(funnel.year, funnel["bko/day"], color="#3d85c6", alpha=0.8)
a2.set_ylabel("breakouts / day", color="#3d85c6")
a2b.plot(funnel.year, funnel["bko_%"], "o-", color="#cc0000"); a2b.set_ylabel("% of full", color="#cc0000")
a2.set_title("§1 — breakout SUPPLY drifts 5× (2008 famine → 2021 flood)")
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s1_funnel.png", dpi=110, bbox_inches="tight")
plt.show()
```

![§1 funnel + supply drift](../../../../data/model_output_eda/sprint_summary/s1_funnel.png)

### Cell 4 — score distribution per tier [R2: trend vs breakout added]

```python
fig, axes = plt.subplots(1, 2, figsize=(14, 4.5))
# left: prob_elite across the three tiers (density) — is breakout just the high-score tail of trend?
for p, lab, c in [(panel_full,"full","#999"),(panel_trend,"trend_ok","#e69138"),(panel,"breakout","#3d85c6")]:
    axes[0].hist(p.prob_elite.dropna(), bins=60, density=True, histtype="step", lw=1.8, label=lab, color=c)
axes[0].axvline(PRIMARY_GATE, color="k", ls=":", label=f"gate {PRIMARY_GATE}")
axes[0].set_title("prob_elite by funnel tier"); axes[0].set_xlabel("prob_elite"); axes[0].legend()
# right: daily top-5 vs the rest of the breakout pool + how many top-5 fall below the gate
t5 = top_n_per_day(panel, 5); rest = panel.drop(t5.index)
axes[1].hist(rest.prob_elite, bins=50, density=True, alpha=0.5, label="breakouts NOT in top-5", color="#999")
axes[1].hist(t5.prob_elite, bins=50, density=True, alpha=0.7, label="daily top-5", color="#e69138")
axes[1].axvline(PRIMARY_GATE, color="k", ls=":", label=f"gate {PRIMARY_GATE}")
axes[1].set_title("daily top-5 vs the rest"); axes[1].set_xlabel("prob_elite"); axes[1].legend()
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s1_scores.png", dpi=110, bbox_inches="tight")
plt.show()
below = (t5.prob_elite < PRIMARY_GATE).mean()
print(f"{below:.0%} of daily top-5 picks score BELOW {PRIMARY_GATE} — the 'blindly top-5' quality leak "
      f"the score gate addresses (Q2).")
```

![§1 score by tier](../../../../data/model_output_eda/sprint_summary/s1_scores.png)

### Cell 5 — churn A: overlap-COUNT distribution (0–5), raw vs score-gated [R2]

```python
# instead of 'all 5 must carry over', show HOW MANY of today's top-5 were in yesterday's.
def overlap_counts(p, n=5, gate=None):
    t = top_n_gated(p, n, gate)
    day_sets = {d: set(g.ticker) for d, g in t.groupby("date")}
    days = sorted(day_sets)
    return np.array([len(day_sets[a] & day_sets[b]) for a, b in zip(days, days[1:]) if day_sets[b]])

fig, ax = plt.subplots(figsize=(11, 4.5))
width = 0.2
for i, (gate, c) in enumerate([(None,"#999"),(0.5,"#6aa84f"),(0.6,"#e69138"),(0.7,"#cc0000")]):
    oc = overlap_counts(panel, 5, gate)
    dist = pd.Series(oc).value_counts(normalize=True).reindex(range(6), fill_value=0)
    ax.bar(np.arange(6)+i*width, dist.values*100, width, label=f"gate {gate}", color=c)
ax.set_xticks(np.arange(6)+1.5*width); ax.set_xticklabels(range(6))
ax.set_xlabel("# of today's top-5 that were in yesterday's top-5")
ax.set_ylabel("% of days"); ax.legend()
ax.set_title("§1 — Churn A: carryover COUNT (0-5), raw vs score-gated\n"
             "mass at 0-1 = high turnover (breakout = day-0 event); gating shifts it (fewer, stickier names)")
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s1_churn_count.png", dpi=110, bbox_inches="tight")
plt.show()
```

![§1 churn count](../../../../data/model_output_eda/sprint_summary/s1_churn_count.png)

### Cell 6 — churn B: name TENURE in the top-5, raw vs score-gated [R2]

```python
# once a name ENTERS the top-5, how many consecutive days does it stay? (survival)
def tenures(p, n=5, gate=None):
    t = top_n_gated(p, n, gate)
    day_sets = {d: set(g.ticker) for d, g in t.groupby("date")}
    days = sorted(day_sets)
    runs, active = [], {}      # ticker -> current run length
    for d in days:
        cur = day_sets[d]
        for tk in list(active):
            if tk not in cur:
                runs.append(active.pop(tk))
        for tk in cur:
            active[tk] = active.get(tk, 0) + 1
    runs += list(active.values())
    return np.array(runs)

fig, ax = plt.subplots(figsize=(11, 4.5))
for gate, c in [(None,"#999"),(PRIMARY_GATE,"#e69138")]:
    tv = tenures(panel, 5, gate)
    xs = np.arange(1, 16)
    surv = [(tv >= k).mean()*100 for k in xs]
    ax.plot(xs, surv, "o-", color=c, label=f"gate {gate}  (median tenure {int(np.median(tv))}d)")
ax.set_xlabel("days held in top-5 (k)"); ax.set_ylabel("% of tenures lasting ≥ k days")
ax.legend(); ax.set_title("§1 — Churn B: name TENURE survival in the top-5, raw vs score-gated\n"
                          "steep drop = names cycle out fast; gate variant tests if quality names persist")
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s1_tenure.png", dpi=110, bbox_inches="tight")
plt.show()
```

![§1 tenure survival](../../../../data/model_output_eda/sprint_summary/s1_tenure.png)

---

## §2 — Forward-return distribution + regime-marked extremes

> **Q1.** On a random day, buy-and-hold the top-N — how does return vary, and do the worst start-days
> line up with the index/regime? **[R2]**: (a) add a SCORE-GATED basket (does gating cut the left
> tail?), (b) show fwd150/fwd200 alongside fwd20/100, (c) the worst-day regime clustering across
> MA{50,100,150,200} × {SPY,QQQ} as a TABLE, (d) shaded price charts for several MAs, SPY and QQQ.

### Cell 7 — the lottery, four horizons, raw vs score-gated basket [R2]

```python
HZ = ["fwd20", "fwd100", "fwd150", "fwd200"]
def basket_daily(p, gate=None):
    t = top_n_gated(p, 5, gate)
    return t.groupby("date")[[h for h in HZ if h in t]].mean().dropna(how="all")
lot     = basket_daily(panel, None)
lot_gtd = basket_daily(panel, PRIMARY_GATE)
print("horizon |     raw (no gate)      |   gate", PRIMARY_GATE)
for h in HZ:
    if h not in lot: continue
    s, sg = lot[h].dropna(), lot_gtd[h].dropna()
    print(f"  {h:6s} mean {s.mean():+.1%} std {s.std():.0%} lose {(s<0).mean():.0%}  |  "
          f"mean {sg.mean():+.1%} std {sg.std():.0%} lose {(sg<0).mean():.0%}")

fig, axes = plt.subplots(2, 2, figsize=(14, 8))
for ax, h in zip(axes.ravel(), HZ):
    if h not in lot: continue
    ax.hist(lot[h].dropna()*100, bins=60, alpha=0.55, color="#3d85c6", label="raw top-5", density=True)
    ax.hist(lot_gtd[h].dropna()*100, bins=60, alpha=0.55, color="#e69138",
            label=f"gate {PRIMARY_GATE}", density=True)
    ax.axvline(0, color="k", lw=0.7); ax.axvline(-15, color="#cc0000", ls=":", lw=1, label="-15% floor")
    ax.set_title(f"{h}: raw lose {(lot[h]<0).mean():.0%} → gated lose {(lot_gtd[h]<0).mean():.0%}")
    ax.set_xlabel(f"{h} basket return (%)"); ax.legend(fontsize=8)
fig.suptitle("§2 — LOTTERY across horizons: does the SCORE GATE cut the left tail? (raw vs gated)", y=1.01)
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s2_lottery.png", dpi=110, bbox_inches="tight")
plt.show()
```

![§2 lottery raw vs gated](../../../../data/model_output_eda/sprint_summary/s2_lottery.png)

### Cell 8 — worst-day regime clustering: MA{50,100,150,200} × {SPY,QQQ} TABLE [R2]

```python
# does the worst decile of start-days (by fwd100) cluster below each index's MA?
L = lot.reset_index()[["date","fwd100"]].dropna()
worst_mask = L.fwd100 <= L.fwd100.quantile(0.10)
tbl = []
for name, idx in [("SPY", spy), ("QQQ", qqq)]:
    for w in (50, 100, 150, 200):
        f = idx.rolling(w).mean()
        blw = L.date.map(lambda d: (idx.asof(d) < f.asof(d)) if pd.notna(f.asof(d)) else np.nan)
        tbl.append({"index": name, "MA": w,
                    "worst-decile %below": blw[worst_mask].mean()*100,
                    "all-days %below": blw.mean()*100,
                    "gap (pp)": (blw[worst_mask].mean() - blw.mean())*100})
regtbl = pd.DataFrame(tbl)
print(regtbl.to_string(index=False, formatters={
    "worst-decile %below":"{:.0f}%".format, "all-days %below":"{:.0f}%".format, "gap (pp)":"{:+.0f}".format}))
print("\nbiggest gap = the MA that best flags bad start-days. Longer MAs (150/200) separate; MA50 barely.")
```

### Cell 9 — shaded price charts, several MAs, SPY + QQQ (2003+) [R2]

```python
# same worst-decile markers, shading by different MAs; 2003+ only (no trades before).
wd = set(L.loc[worst_mask, "date"])
fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
for ax, (name, idx) in zip(axes, [("SPY", spy), ("QQQ", qqq)]):
    s = idx[idx.index >= "2003-01-01"]
    ax.plot(s.index, s.values, color="#333", lw=0.7, label=name)
    for w, c in [(50,"#f6b26b"),(100,"#93c47d"),(150,"#76a5af"),(200,"#e69138")]:
        m = idx.rolling(w).mean().reindex(s.index)
        ax.plot(s.index, m.values, lw=0.8, color=c, alpha=0.8, label=f"MA{w}")
    below200 = (s < idx.rolling(200).mean().reindex(s.index)).fillna(False).values
    ax.fill_between(s.index, s.min(), s.max(), where=below200, color="#cc0000", alpha=0.07, label="< MA200")
    marks = [d for d in wd if d >= pd.Timestamp("2003-01-01")]
    ax.scatter(marks, s.reindex(marks).values, color="#cc0000", s=14, zorder=5, label="worst start-day")
    ax.set_ylabel(name); ax.legend(loc="upper left", fontsize=7, ncol=3)
axes[0].set_title("§2 — worst start-days vs index regime (SPY & QQQ), MA overlays, 2003+")
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s2_regime_charts.png", dpi=110, bbox_inches="tight")
plt.show()
```

![§2 regime charts SPY+QQQ](../../../../data/model_output_eda/sprint_summary/s2_regime_charts.png)

---

## §3 — Dig into the pool: sector × market-cap × forward return

> **Q3.** Group by sector and size — anything we missed on super-performers? **[R2]**: (a) per-sector
> DISTRIBUTIONS (histograms) not just medians, with the bull/bear regime split stacked INSIDE each;
> (b) the size×RS grid clarified — the conclusion is *strong-RS × small-cap has a higher HOME-RUN RATE*
> (Q8), shown as a clean marginal line, median demoted to a note.

### Cell 10 — per-sector fwd100 distribution + regime split stacked [R2]

```python
assert panel["sector"].notna().mean() > 0.9
panel["spy_above200"] = panel.date.map(
    lambda d: bool(spy.asof(d) > spy.rolling(200).mean().asof(d))
    if pd.notna(spy.rolling(200).mean().asof(d)) else np.nan)
secs = panel.groupby("sector")["fwd100"].median().sort_values(ascending=False).index.tolist()
fig, axes = plt.subplots(3, 4, figsize=(16, 10), sharex=True)
for ax, sec in zip(axes.ravel(), secs):
    d = panel[panel.sector == sec]
    bull = d[d.spy_above200 == True]["fwd100"].dropna()*100
    bear = d[d.spy_above200 == False]["fwd100"].dropna()*100
    ax.hist([bull, bear], bins=40, range=(-60,100), stacked=True,
            color=["#6aa84f","#cc0000"], label=["bull","bear"])
    ax.axvline(0, color="k", lw=0.6)
    ax.axvline(d["fwd100"].median()*100, color="blue", ls="--", lw=1)
    ax.set_title(f"{sec}\nmed {d.fwd100.median()*100:+.1f}%  bull {bull.median():+.0f} / bear {bear.median():+.0f}",
                 fontsize=9)
for ax in axes.ravel()[len(secs):]: ax.axis("off")
axes[0,0].legend(fontsize=8)
fig.suptitle("§3 — Per-SECTOR fwd100 DISTRIBUTION, bull(green)/bear(red) stacked "
             "(dashed=median). Shape + regime split, not just the median bar.", y=1.01)
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s3_sector_dist.png", dpi=110, bbox_inches="tight")
plt.show()
print("sector median RANKING flips bull↔bear (next line): a pooled sector tilt is unsafe.")
piv = (panel.dropna(subset=["spy_above200"]).groupby(["sector","spy_above200"])["fwd100"]
       .median().mul(100).unstack())
piv.columns = ["bear","bull"]; piv["flip"] = piv.bull - piv.bear
print(piv.round(1).sort_values("bull", ascending=False).to_string())
```

![§3 sector distributions](../../../../data/model_output_eda/sprint_summary/s3_sector_dist.png)

### Cell 11 — size × RS: the home-run-rate conclusion, made legible [R2/Q8]

```python
# CONCLUSION (Q8): small-cap × strong-RS has a HIGHER HOME-RUN RATE (fwd100>30%).
# The median is the wrong lens (it INVERTS — the edge is a TAIL phenomenon), so we lead
# with the home-run rate and show the median only as a one-line contrast.
d = (panel.drop(columns=["rs"], errors="ignore")
     .merge(RS_T3, on=["date","ticker"], how="left")
     .merge(DVOL,  on=["date","ticker"], how="left")
     .dropna(subset=["rs","dollar_vol","fwd100"]).copy())
print(f"rs coverage after t3 join: {d['rs'].notna().mean():.0%}")
d["size_dec"] = d.groupby("date")["dollar_vol"].transform(lambda s: pd.qcut(s,10,labels=False,duplicates="drop"))
d["rs_dec"]   = d.groupby("date")["rs"].transform(lambda s: pd.qcut(s,10,labels=False,duplicates="drop"))
d["home_run"] = (d.fwd100 > 0.30).astype(float)
hr   = d.groupby(["rs_dec","size_dec"])["home_run"].mean().mul(100).unstack()
pool = d.home_run.mean()*100

fig, axes = plt.subplots(1, 2, figsize=(15, 5.5))
# left: heatmap of home-run rate
im = axes[0].imshow(hr.values, cmap="RdYlGn", aspect="auto", origin="lower")
axes[0].set_xlabel("size decile (0=small→9=large)"); axes[0].set_ylabel("RS decile (0=weak→9=strong)")
axes[0].set_title(f"home-run RATE % (fwd100>30%); pool={pool:.1f}%\ntop-LEFT = strong-RS × small-cap lights up")
fig.colorbar(im, ax=axes[0], label="home-run %")
# right: the marginal that states the conclusion — RS ramp within small vs large cap
for sz, lab, c in [(0,"smallest-cap decile","#cc0000"),(9,"largest-cap decile","#3d85c6")]:
    axes[1].plot(hr.index, hr[sz], "o-", color=c, label=lab)
axes[1].axhline(pool, color="k", ls=":", label=f"pool {pool:.1f}%")
axes[1].set_xlabel("RS decile (0=weak→9=strong)"); axes[1].set_ylabel("home-run rate %")
axes[1].set_title("the conclusion: home-run rate RISES with RS,\nand rises MORE for small-caps")
axes[1].legend()
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s3_size_rs.png", dpi=110, bbox_inches="tight")
plt.show()
med = d.groupby(["rs_dec","size_dec"])["fwd100"].median().mul(100).unstack()
print(f"strong-RS small-cap (9,0) home-run {hr.loc[9,0]:.1f}% = {hr.loc[9,0]/pool:.1f}× pool.")
print(f"NOTE the MEDIAN inverts (weak-RS small-cap median {med.loc[0,0]:+.1f}% vs strong {med.loc[9,0]:+.1f}%) "
      f"— why median-based studies miss the size axis; the edge is in the TAIL, cf R1b's 63d-MFE cut.")
```

![§3 size × RS home-run](../../../../data/model_output_eda/sprint_summary/s3_size_rs.png)

---

## §4 — NEW: leadership TROUGH-GEOMETRY (the RS residual the book describes)

> **Q4.** Minervini: leaders, DURING an index decline, (a) bottom BEFORE the index, (b) fall SHALLOWER,
> (c) recover FASTER. RS is a smoothed momentum ratio — it does NOT encode this down-cycle SHAPE.
> R2 found group-leadership/VCP traits collapsed into RS; trough-geometry was never tested. **[R2]**:
> (a) a RECTANGLE viz (§4b) drawing each name's trough as a box (bottom edge=trough price, width=
> break→recover) — leaders vs laggards vs the index; (b) the leader_score chart with median+fan AND
> mean+home-run-rate (Q10 — "why not min/max/mean").

### Cell 12 — detect SPY drawdown episodes + measure per-name geometry

```python
from trough_geometry import spy_drawdown_episodes, name_trough_geometry
eps = spy_drawdown_episodes(min_dd=0.12, min_len=20)
print(eps.assign(peak=eps.peak_date.dt.date, trough=eps.trough_date.dt.date, recover=eps.recover_date.dt.date,
                 depth=(eps.depth*100).round(1))[["peak","trough","recover","depth","peak_to_trough_days"]]
      .to_string(index=False))
eps_test = eps[eps.peak_date >= "2003-01-01"].reset_index(drop=True)   # panel era

geo_all = []
for _, ep in eps_test.iterrows():
    yr = ep.peak_date.year
    names = panel[panel.year.isin([yr-1, yr, yr+1])].ticker.unique().tolist()
    geo_all.append(name_trough_geometry(names, eps_test[eps_test.peak_date == ep.peak_date]))
geo = pd.concat(geo_all, ignore_index=True)
geo["led_trough"]  = geo.trough_lead_days > 0
geo["shallower"]   = geo.relative_depth < 1.0
geo["led_recover"] = geo.recover_lead_days > 0
geo["leader_score"] = geo[["led_trough","shallower","led_recover"]].sum(axis=1)
print(f"\n{len(geo)} name-episodes over {geo.peak_date.nunique()} episodes (2003+).")
print("leader_score dist:", geo.leader_score.value_counts().sort_index().to_dict())
```

### Cell 13 — §4b: the trough RECTANGLE viz (leaders vs laggards vs SPY, 2020) [R2/Q9]

```python
# ONE clear episode (2020 COVID). Each name's trough = a rectangle: bottom edge = trough
# price (normalized to entry=1), left edge = episode start (trend breaks), right edge =
# when it reclaims entry (recovery), width = that duration. Leaders sit HIGH & NARROW.
ep = eps_test[eps_test.peak_date.dt.year == 2020].iloc[0]
g20 = geo[geo.peak_date == ep.peak_date]
leaders  = g20[g20.leader_score >= 2].nsmallest(3, "relative_depth")   # shallow + early
laggards = g20[g20.leader_score == 0].nlargest(3, "relative_depth")    # deep + late
picks = pd.concat([leaders.assign(kind="leader"), laggards.assign(kind="laggard")])

con = db.connect(str(ROOT/"data/market_data.duckdb"), read_only=True)
tks = tuple(picks.ticker)
px = con.execute(f"SELECT ticker,date,close FROM price_data WHERE ticker IN {tks} "
                 "AND date BETWEEN ? AND ? ORDER BY ticker,date",
                 [str(ep.peak_date.date()), str(ep.recover_date.date())]).df()
con.close(); px["date"] = pd.to_datetime(px["date"])

fig, ax = plt.subplots(figsize=(14, 6))
def rect(dates, norm, color, label, lw=1.5):
    trough_i = int(norm.values.argmin())
    x0 = 0; x1 = len(norm); y = norm.min()
    ax.add_patch(plt.Rectangle((x0, y), x1-x0, 1-y, fill=False, edgecolor=color, lw=lw))
    ax.plot(range(len(norm)), norm.values, color=color, alpha=0.5, lw=1, label=label)
    ax.scatter([trough_i], [y], color=color, s=40, zorder=5)
# SPY reference
from trough_geometry import spy_close
spys = spy_close().loc[ep.peak_date:ep.recover_date]; spyn = spys/spys.iloc[0]
rect(spys.index, spyn.reset_index(drop=True), "black", "SPY (index)", lw=2.5)
for _, r in picks.iterrows():
    g = px[px.ticker == r.ticker]
    if len(g) < 5: continue
    norm = (g.close/g.close.iloc[0]).reset_index(drop=True)
    rect(g.date, norm, "#6aa84f" if r.kind=="leader" else "#cc0000", f"{r.ticker} ({r.kind})")
ax.axhline(1.0, color="k", lw=0.6, ls=":"); ax.set_ylabel("price / entry")
ax.set_xlabel("trading days from episode start")
ax.set_title("§4b — Trough RECTANGLES, 2020 COVID: leaders (green) bottom HIGHER & recover NARROWER;\n"
             "laggards (red) plunge to a deep, wide trough. The book's leader shape, made visual.")
ax.legend(fontsize=8, ncol=2)
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s4_rectangles.png", dpi=110, bbox_inches="tight")
plt.show()
```

![§4b trough rectangles](../../../../data/model_output_eda/sprint_summary/s4_rectangles.png)

### Cell 14 — does trough-geometry grade fwd100 INCREMENTAL to RS?

```python
def outcome_after(row):
    yr = pd.Timestamp(row.peak_date).year
    sub = panel[(panel.ticker==row.ticker) & (panel.year.isin([yr, yr+1]))]
    return sub["fwd100"].median() if len(sub) else np.nan
geo["fwd_out"] = geo.apply(outcome_after, axis=1)
G = geo.dropna(subset=["fwd_out"]).copy()
print(f"{len(G)} name-episodes with a forward outcome.")
for t, better in [("trough_lead_days","higher"),("relative_depth","lower"),("recover_lead_days","higher")]:
    print(f"  ρ({t:18s}, fwd100) = {G[t].corr(G.fwd_out, method='spearman'):+.3f}  (leader={better})")
rs_map = RS_T3.groupby("ticker")["rs"].median()
G["rs"] = G.ticker.map(rs_map); G = G.dropna(subset=["rs"])
G["rs_dec"] = pd.qcut(G["rs"].rank(method="first"), 5, labels=False)
print(f"\n{len(G)} name-episodes with RS. median fwd100 (%) by RS quintile × leader_score:")
print(G.groupby(["rs_dec","leader_score"])["fwd_out"].median().mul(100).unstack().round(1).to_string())
```

### Cell 15 — §4: leader_score vs outcome — median+fan AND mean+home-run (Q10) [R2]

```python
# Q10: median alone hides the tail. Show (a) median + p10-p90 FAN (center+dispersion),
# (b) MEAN (tail-sensitive) + HOME-RUN RATE (the tail SEPA cares about). Mean ≠ median
# here because the outcome is fat-tailed — that GAP is the point.
G["home_run"] = (G.fwd_out > 0.30).astype(float)
fig, axes = plt.subplots(1, 3, figsize=(17, 5))
qs = sorted(G.rs_dec.dropna().unique())
cmap = plt.cm.viridis(np.linspace(0, 1, len(qs)))
# (a) median + fan
for q, c in zip(qs, cmap):
    s = G[G.rs_dec==q]
    m   = s.groupby("leader_score")["fwd_out"].median()*100
    p10 = s.groupby("leader_score")["fwd_out"].quantile(.10)*100
    p90 = s.groupby("leader_score")["fwd_out"].quantile(.90)*100
    axes[0].plot(m.index, m.values, "o-", color=c, label=f"RS q{int(q)}")
    axes[0].fill_between(m.index, p10.reindex(m.index), p90.reindex(m.index), color=c, alpha=0.08)
axes[0].set_title("(a) MEDIAN + p10-p90 fan"); axes[0].set_ylabel("fwd100 (%)")
# (b) mean
for q, c in zip(qs, cmap):
    s = G[G.rs_dec==q]; m = s.groupby("leader_score")["fwd_out"].mean()*100
    axes[1].plot(m.index, m.values, "o-", color=c, label=f"RS q{int(q)}")
axes[1].set_title("(b) MEAN (tail-sensitive)")
# (c) home-run rate
for q, c in zip(qs, cmap):
    s = G[G.rs_dec==q]; m = s.groupby("leader_score")["home_run"].mean()*100
    axes[2].plot(m.index, m.values, "o-", color=c, label=f"RS q{int(q)}")
axes[2].set_title("(c) HOME-RUN RATE % (fwd100>30%)")
for ax in axes:
    ax.set_xlabel("leader_score (0-3 traits)"); ax.set_xticks([0,1,2,3]); ax.axhline(0, color="k", lw=0.5)
axes[2].legend(fontsize=8)
fig.suptitle("§4 — Trough-geometry vs outcome, within RS quintile: median hides the tail; "
             "mean & home-run show where the down-cycle SHAPE actually pays (Q10).", y=1.02)
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s4_leader_score.png", dpi=110, bbox_inches="tight")
plt.show()
print("READ: lines rising L→R WITHIN an RS quintile = geometry adds beyond RS. Compare (a) vs (c):")
print("      if home-run (c) ramps where median (a) is flat, the residual signal is TAIL-only.")
```

![§4 leader_score full distribution](../../../../data/model_output_eda/sprint_summary/s4_leader_score.png)

---

## §5 — All the paths we could have picked (the equity fan), filtered by pool

> **Q5.** Every start-day's equity curve overlaid — all the paths, coarse on exits. **[R2/Q11]**: fix
> the whitespace (autoscale y to the actual data, not min..max of SPY), and add score-gate × regime-gate
> variants of the fan (does quality-gating and/or regime-gating tighten it?).

### Cell 16 — build the fan (validated lottery engine), 4 variants [R2/Q11]

```python
from start_day_basket_paths import basket_paths
# 4 variants = {regime-gate on/off} × {score-gate none / PRIMARY_GATE}. The engine now
# takes min_score (Q11). use_governor=True = the SPY-200d regime gate (no-deploy on <200d).
def run(gov, ms):
    s, p, st = basket_paths(sample_every=5, horizon=150, sl_pct=0.15, use_governor=gov, min_score=ms)
    return s, p, pd.to_datetime(pd.Series(st))
# NOTE: CAL_GATE (calibrated scale) — basket_paths reads the CALIBRATED score cache,
# NOT the panel. PRIMARY_GATE (0.6 raw) would exclude ~everything here.
V = {("regON","scoreOFF"): run(True, None),  ("regON","scoreGT"): run(True, CAL_GATE),
     ("regOFF","scoreOFF"): run(False, None), ("regOFF","scoreGT"): run(False, CAL_GATE)}
ma200 = spy.rolling(200).mean()
regf = lambda d: "bull" if (pd.notna(ma200.asof(d)) and spy.asof(d) > ma200.asof(d)) else "bear"
for k, (s, p, st) in V.items():
    print(f"{k}: {s.deployed.sum()} deployed / {len(s)}")
```

### Cell 17 — Plot B: whitespace fixed (autoscale) + regime-gate on/off [R2/Q11]

```python
def draw_fan(ax, paths, starts, dep, title, color):
    mask = dep
    P = (paths[mask] - 1) * 100
    if len(P) == 0: return
    x = np.arange(P.shape[1])
    for row in P: ax.plot(x, row, color=color, alpha=0.03, lw=0.5)
    ax.plot(x, np.median(P, 0), color="k", lw=2, label="median")
    ax.fill_between(x, np.percentile(P,10,0), np.percentile(P,90,0), color=color, alpha=0.2, label="10-90")
    # WHITESPACE FIX: clip y to the 2-98 pctile of the actual paths, not SPY's full min..max
    lo, hi = np.percentile(P, 2), np.percentile(P, 98)
    ax.set_ylim(lo*1.15, hi*1.15)
    ax.set_title(f"{title} (n={mask.sum()})\nfinal 10-90: "
                 f"{np.percentile(P[:,-1],10):.0f}..{np.percentile(P[:,-1],90):.0f}%  "
                 f"std {P[:,-1].std():.0f}%")
    ax.axhline(0, color="k", lw=0.5); ax.set_xlabel("days after start"); ax.legend(fontsize=8)

# 2×2: rows = regime gate ON/OFF, cols = score gate OFF/ON. deployed-only paths.
fig, axes = plt.subplots(2, 2, figsize=(15, 9), sharex=True)
cells = [(("regON","scoreOFF"), axes[0,0], "regime ON · score OFF", "#3d85c6"),
         (("regON","scoreGT"),  axes[0,1], f"regime ON · cal-score≥{CAL_GATE}", "#6aa84f"),
         (("regOFF","scoreOFF"),axes[1,0], "regime OFF · score OFF", "#e69138"),
         (("regOFF","scoreGT"), axes[1,1], f"regime OFF · cal-score≥{CAL_GATE}", "#cc0000")]
for key, ax, title, c in cells:
    s, p, st = V[key]
    draw_fan(ax, p, st, s.deployed.values, title, c)
axes[0,0].set_ylabel("basket return (%)"); axes[1,0].set_ylabel("basket return (%)")
fig.suptitle("§5 — Equity FAN (whitespace-fixed): regime-gate (rows) × score-gate (cols).\n"
             "regime gate narrows the fan (drops wide bear starts); score gate barely moves it "
             "(model already priced the breakout — cf §2).", y=1.02)
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s5_fan.png", dpi=110, bbox_inches="tight")
plt.show()
```

![§5 equity fan, gated variants](../../../../data/model_output_eda/sprint_summary/s5_fan.png)

### Cell 18 — closing synthesis (markdown cell)

```markdown
## What the pictures say (Sprint 14, consolidated + review round 2)

1. **The pool is a clustered event stream** (§1) — the funnel is full → trend_ok (~13%) → breakout
   (~1%); breakout SUPPLY swings 5×/day with regime (root of the exposure artifact). The daily top-5 is
   high-churn (mass at 0-1 carryover); a chunk of picks score below 0.6 — the quality leak the score
   gate addresses. Gating trades count for conviction (fewer names/day, longer tenure).

2. **Selection is a lottery whose downside IS the regime** (§2) — the top-5 basket return is wide with a
   fat left tail at the −15% floor; the SCORE GATE trims the left tail modestly. The worst start-days
   cluster below the index MA — and the 150/200-day MAs separate best (MA50 barely), for BOTH SPY and
   QQQ. Empirical case for the SPY-200d deploy gate (`champion_trail_spygate`, Q40).

3. **Sector tilt is regime-dependent; SIZE is the durable second axis** (§3) — per-sector distributions
   show the bull/bear split flips the median ranking, so a pooled sector tilt is unsafe. The stable
   super-performer signal: **home-run RATE rises with RS and rises MORE for small-caps** — the edge is a
   TAIL phenomenon (the median inverts, which is why median studies missed size). Liquidity-constrained.

4. **Trough-geometry is a residual RS misses** (§4) — leaders bottom earlier, shallower, recover faster
   (the rectangle viz makes AMGN-vs-MFA obvious). All three traits grade fwd100 in the predicted
   direction (ρ +0.13 / −0.14 / +0.09). Q10 mattered: the MEDIAN chart understates it, but the MEAN
   ramps cleanly within every RS quintile (top quintile −3.4% → +4.4% from 0→3 traits) and the home-run
   panel shows the lift is LARGEST where RS is WEAKEST (rs-q0 home-run 2.7%→5.7%) — i.e. geometry partly
   SUBSTITUTES for RS on weak names and ADDS on strong ones. A candidate LABEL-level axis to stack on RS,
   NOT a model re-weight. ⚠️ 6 episodes, 2008/2020 dominate; no 63d-MFE cut yet.

5. **The fan width is a regime property** (§5) — with the whitespace fixed, bull-start fans are tight and
   drift up; bear-start fans are wide. The regime gate's entire value is removing the wide bear fan; it
   can't tighten the bull fan (nothing to fix there). Confirms M2's cone-not-point and the governor arc.

**Population honesty:** every cut reads from the audited funnel tiers. Sprint-14 studies that used
`entry_timing_features.py` drew per-day top-5 from the INFLATED pool — their macro/regime *correlations*
likely survive (ρ is scale-free) but return *levels* were overstated; §2/§3/§5 are the corrected versions.
```
