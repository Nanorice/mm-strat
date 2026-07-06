# Rotation second-pass — notebook cells (verified, paste into `notebooks/signs_of_tail.ipynb`)

> Per workflow rule: cells are provided here, NOT edited into the .ipynb directly.
> All code below was run end-to-end against `data/market_data.duckdb` and produced the
> results in the "Findings" section of the session log. Append these as new cells after
> the existing rotation cells.

## Why these cells exist
The first-pass rotation test (breakout-share Δ vs fwd-21d relative return → corr 0.008)
was abandoned. The open item said: swap breakout **count → `RS_Universe_Rank`**, lengthen
horizons to **63/63**, test sustained **level** not Δ, and **anchor on merged onsets**
(the repo notebook still used the event-anchored windows that the doc proved were artifacts).
These cells do all four.

---

### Cell R1 — onset-anchored merged bearish events + sector rotation series
```python
# %%  Rotation v2 — knobs
PRE, POST  = 63, 63          # lengthened horizons
MERGE_GAP  = 10              # merge clustered bearish days -> ONSET anchoring (de-overlap)

# bench returns + bearish ONSET events (merged, not event-anchored)
bench = con.execute("select date, close from price_data where ticker=? and date>=? order by date",
                    [BENCH, START]).df()
bench["ret"] = bench["close"].pct_change()
bench = bench.dropna().reset_index(drop=True)
bench["i"]   = np.arange(len(bench))
bench["date"]= pd.to_datetime(bench["date"])
cut = bench["ret"].quantile(BEAR_Q)

bear = bench[bench["ret"] <= cut].copy()
bear["new"] = bear["i"].diff().gt(MERGE_GAP).fillna(True)
bear["eid"] = bear["new"].cumsum()
onset = bear.groupby("eid", as_index=False).first()[["eid","i"]].rename(columns={"i":"i0"})
print(f"cutoff={cut:.3%}  bearish days={len(bear)}  merged onset events={len(onset)}")  # 80 events

# sector-level rotation: daily mean RS_Universe_Rank per real sector (drop ETF: pseudo-sectors)
sec = con.execute(f"""
  with x as (
    select t.date, cp.sector, t.RS_Universe_Rank r
    from t3_sepa_features t join company_profiles cp using (ticker)
    where t.date >= '{START}' and t.RS_Universe_Rank is not null
      and cp.sector not like 'ETF:%'
  )
  select date, sector, avg(r) mean_rank from x group by 1,2
""").df()
sec["date"] = pd.to_datetime(sec["date"])
sec = sec.merge(bench[["date","i"]], on="date")
```

### Cell R2 — rotation INTENSITY (dispersion) event study — sustained level test
```python
# how much sector rotation is happening = cross-sectional std of sector mean-ranks per day
disp = sec.groupby("i")["mean_rank"].std().rename("dispersion")
disp_idx = disp.to_dict()

rows = [(off, disp_idx[e.i0+off])
        for e in onset.itertuples() for off in range(-PRE, POST+1)
        if (e.i0+off) in disp_idx]
ev = pd.DataFrame(rows, columns=["offset","dispersion"])
prof = ev.groupby("offset")["dispersion"].agg(m="mean", se=lambda s: s.std()/np.sqrt(s.count())).reset_index()

pre  = ev[ev.offset.between(-PRE,-6)].dispersion
evt  = ev[ev.offset.between(-5, 5)].dispersion
post = ev[ev.offset.between(6, POST)].dispersion
print(f"dispersion  PRE={pre.mean():.4f}  EVENT={evt.mean():.4f}  POST={post.mean():.4f}")
# -> 0.0985 / 0.0972 / 0.1000  : FLAT into onset, drifts up only AFTER. No lead.

fig, ax = plt.subplots(figsize=(9,4))
ax.plot(prof.offset, prof.m); ax.fill_between(prof.offset, prof.m-prof.se, prof.m+prof.se, alpha=.2)
ax.axvline(0, color="r", ls="--"); ax.set(title="sector rotation intensity around bearish onset",
                                          xlabel="trading days from onset", ylabel="sector-rank dispersion")
plt.show()
```

### Cell R3 — DIRECTIONAL test: do defensives lead into the drawdown?
```python
DEF = {"Utilities","Consumer Defensive","Healthcare"}
CYC = {"Technology","Consumer Cyclical","Industrials","Basic Materials"}
g = sec.assign(grp=np.where(sec.sector.isin(DEF),"DEF",
                   np.where(sec.sector.isin(CYC),"CYC",None))).dropna(subset=["grp"])
gm  = g.groupby(["i","grp"])["mean_rank"].mean().unstack()
dmc = (gm["DEF"] - gm["CYC"])          # >0 = defensives already leading = risk-off rotation underway

rows = [(off, dmc.loc[e.i0+off]) for e in onset.itertuples()
        for off in range(-PRE,POST+1) if (e.i0+off) in dmc.index]
evd = pd.DataFrame(rows, columns=["offset","dmc"])
print("def_minus_cyc  PRE={:+.4f}  EVENT={:+.4f}  POST={:+.4f}".format(
    evd[evd.offset.between(-PRE,-6)].dmc.mean(),
    evd[evd.offset.between(-5,5)].dmc.mean(),
    evd[evd.offset.between(6,POST)].dmc.mean()))
# -> -0.0229 / -0.0089 / -0.0097 : defensives UNDER-perform pre-onset, snap up AT day 0. No lead.

# predictive: does pre-window rotation forecast drawdown depth?
close = bench.set_index("i")["close"]
depth = {e.i0: (min(close.reindex(range(e.i0, e.i0+21)).dropna()) /
                close.get(e.i0) - 1) for e in onset.itertuples() if pd.notna(close.get(e.i0))}
pre_lvl = {e.i0: dmc.reindex(range(e.i0-PRE, e.i0-5)).mean() for e in onset.itertuples()}
dfp = pd.DataFrame({"pre_dmc": pre_lvl, "depth": depth}).dropna()
print(f"corr(pre def_minus_cyc, fwd drawdown depth) = {dfp.pre_dmc.corr(dfp.depth):+.3f}  (n={len(dfp)})")
# -> +0.019  (n=80) : zero predictive power, mirrors first-pass corr 0.008
```

---

## ⚠️ Unrelated bug spotted while reading the notebook
Existing **Cell 5 (`fwd return of breakout names`)** divides by `px.adj_close`, but
`adj_close` is **NULL table-wide** in `price_data` (the same Goal-D data gap noted in the log).
That cell's `med_fwd_ret` / `avg_fwd_ret` are therefore all NULL/garbage. Fix: use `close`
(splits → prefer the `median` already in place), or wait for Goal D to populate `adj_close`.
