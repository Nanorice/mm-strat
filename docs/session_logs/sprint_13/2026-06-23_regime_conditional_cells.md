# Regime models reframed — conditional & lead-lag cells (verified, paste into `signs_of_tail.ipynb`)

> All code run end-to-end against `data/market_data.duckdb`. Reframes the question away from
> event-anchoring (which assumes the signal sits near the drop) toward two cleaner tests:
> (1) lead-lag sweep — does the indicator predict returns at ANY horizon? (2) conditional
> outcomes — when the model says danger, what actually happens?

## Setup (shared)
```python
rsk = con.execute("select * from t2_risk_scores").df();   rsk["date"]=pd.to_datetime(rsk["date"])
reg = con.execute("select * from t2_regime_scores").df(); reg["date"]=pd.to_datetime(reg["date"])
px  = con.execute("select date,close from price_data where ticker=? and date>=? order by date",
                  [BENCH, START]).df(); px["date"]=pd.to_datetime(px["date"])
df  = px.merge(reg,on="date",how="left").merge(rsk,on="date",how="left").sort_values("date").reset_index(drop=True)
df["ret"] = df["close"].pct_change()
```

### Cell X1 — lead-lag sweep (does it lead at ANY horizon?)
```python
inds=["z_vix","z_hy","z_trend","z_slope","z_term","weighted_z","m03_score","target_exposure"]
H_set=[5,10,21,42,63,126,189,252]
print("corr(indicator_t, fwd return over next H)  — leading bear signal => NEGATIVE & growing with H")
hdr="indicator".ljust(16)+"".join(f"H{h:>4d}" for h in H_set); print(hdr)
for c in inds:
    fwd=lambda H: df["close"].shift(-H)/df["close"]-1
    print(c.ljust(16)+"".join(f"{df[c].corr(fwd(H)):+5.2f}" for H in H_set))
# RESULT: z_vix +0.09->+0.30 (rises with H) — OPPOSITE of a lead. No danger z leads. Falsifies "fired too early".
```

### Cell X2 — conditional forward outcomes (when it says danger, what happens?)
```python
for H in [21,63]:
    df[f"fwd{H}"]=df["close"].shift(-H)/df["close"]-1
    rollmin=df["close"][::-1].rolling(H,min_periods=1).min()[::-1].shift(-1)
    df[f"mdd{H}"]=rollmin/df["close"]-1

def cond(name,mask,H):
    s=df.loc[mask,f"fwd{H}"].dropna(); b=df[f"fwd{H}"].dropna()
    sm=df.loc[mask,f"mdd{H}"].dropna(); bm=df[f"mdd{H}"].dropna()
    print(f"  {name:26s} n={int(mask.sum()):5d} | mean {s.mean():+.2%} (base {b.mean():+.2%}) "
          f"| P5 {s.quantile(.05):+.2%} (base {b.quantile(.05):+.2%}) "
          f"| MDD {sm.mean():+.2%} (base {bm.mean():+.2%}) | P(neg) {(s<0).mean():.0%}")

for H in [21,63]:
    print(f"\n--- H={H}d : DANGER signals vs unconditional ---")
    cond("z_vix top decile",        df.z_vix>=df.z_vix.quantile(.90),H)
    cond("weighted_z top decile",   df.weighted_z>=df.weighted_z.quantile(.90),H)
    cond("M03 bottom 25%",          df.m03_score<=df.m03_score.quantile(.25),H)
    cond("veto_flag True",          df.veto_flag==True,H)
# RESULT: danger => HIGHER mean fwd return (vol risk premium / mean-reversion) but FATTER left tail
# + bigger MDD. Signals dispersion, not direction. veto_flag is the exception: worse P(neg), no mean lift.
```

### Cell X3 — position-sizing proof: indicator predicts forward REALIZED VOL
```python
print("corr(z_vix_t, realized stdev of next-H returns) — the SIZING claim")
for H in [2,3,5,10,21,42,63,126]:
    fv=df["ret"].shift(-1).rolling(H).std().shift(-(H-1))
    sub=df[["z_vix"]].join(fv.rename("fv")).dropna()
    print(f"  H={H:>3d}  corr={sub['z_vix'].corr(sub['fv']):.3f}")
# RESULT: peaks 0.67 at H=5-10, decays past 21d => sizing horizon is 1-2 WEEKS.

# monotonic decile check at H=5 (annualized fwd realized vol by z_vix decile)
H=5; fv=df["ret"].shift(-1).rolling(H).std().shift(-(H-1))
d=df[["z_vix"]].join(fv.rename("fv")).dropna(); d["dec"]=pd.qcut(d.z_vix,10,labels=False)
print("\nannualized 5d-fwd realized vol by z_vix decile (monotone => clean sizing signal):")
print((d.groupby("dec")["fv"].mean()*np.sqrt(252)).round(3).to_string())
# RESULT: 0.094 (dec0) -> 0.337 (dec9), strictly increasing. Clean.
```
