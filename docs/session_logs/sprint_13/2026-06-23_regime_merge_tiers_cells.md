# M03 vs risk-model overlap + tier calibration — cells (verified)

> Run end-to-end on `data/market_data.duckdb`. Answers: (Q1) should we merge the two macro
> models? (Q2) do the score tiers need calibrating against history?

## Shared setup
```python
reg=con.execute("select * from t2_regime_scores").df(); reg["date"]=pd.to_datetime(reg["date"])
rsk=con.execute("select * from t2_risk_scores").df(); rsk["date"]=pd.to_datetime(rsk["date"])
px =con.execute("select date,close from price_data where ticker=? and date>=? order by date",[BENCH,START]).df()
px["date"]=pd.to_datetime(px["date"])
df=px.merge(reg,on="date").merge(rsk,on="date").sort_values("date").reset_index(drop=True)
df["ret"]=df["close"].pct_change()
df["fvol"]=df["ret"].shift(-1).rolling(5).std().shift(-4)*np.sqrt(252)   # 5d ann. fwd vol
df["f21"] =df["close"].shift(-21)/df["close"]-1
```

## Q1 — overlap / merge test
```python
print("corr(m03_score, weighted_z) =", round(df.m03_score.corr(df.weighted_z),3))   # -0.57: moderate, not same
# pillar vs risk-factor map -> which M03 piece is redundant vs unique
zf=["z_vix","z_hy","z_term","z_trend","z_slope"]
for p in ["m03_pillar_trend","m03_pillar_liq","m03_pillar_risk"]:
    print(p, {z:round(df[p].corr(df[z]),2) for z in zf})
# pillar_trend ~ -0.88 z_trend (REDUNDANT); pillar_liq ~ 0.0 everywhere (UNIQUE: net-liq, risk model lacks it)

# danger agreement (each flags worst 25%)
m,r=df.m03_score<=df.m03_score.quantile(.25), df.weighted_z>=df.weighted_z.quantile(.75)
both=(m&r).sum(); print("jaccard danger-agreement =", round(both/((m|r).sum()),2))  # 0.45 -> disagree on ~55%

# incremental predictive power for fwd vol (partial corr)
from numpy.linalg import lstsq
sub=df[["m03_score","weighted_z","fvol"]].dropna()
def partial(t,b):
    X=np.column_stack([np.ones(len(sub)),sub[b].values])
    rt=sub[t].values-X@lstsq(X,sub[t].values,rcond=None)[0]
    rf=sub.fvol.values-X@lstsq(X,sub.fvol.values,rcond=None)[0]
    return round(np.corrcoef(rt,rf)[0,1],3)
print("weighted_z | m03 removed:", partial("weighted_z","m03_score"))  # +0.42 -> risk model has big independent signal
print("m03 | weighted_z removed:", partial("m03_score","weighted_z"))  # -0.19 -> smaller independent signal
# CONCLUSION: do NOT merge. ~30% overlap; pillar_liq orthogonal; both have independent fwd-vol info;
# and M01 consumes all 7 m03_* cols (-0.22 Sharpe if dropped). Present as 2-axis panel instead.
```

## Q2 — tier calibration
```python
# fixed 0/25/50/75/100 tiers: monotone but UNBALANCED + cut points mis-placed
df["m03_tier"]=pd.cut(df.m03_score,[0,25,50,75,100])
print(df.groupby("m03_tier",observed=True).agg(n=("ret","size"),fwd_vol=("fvol","mean")).round(3))
# 221/916/2125/878 days -> "danger" tier is only 5% of sample; bins assume uniform 0-100 spread (false)

# WHERE is the real breakpoint? deciles of m03 vs fwd vol
df["m03_dec"]=pd.qcut(df.m03_score,10,labels=False)
print(df.groupby("m03_dec").agg(m03=("m03_score","mean"),fwd_vol=("fvol","mean")).round(3))
# vol cliffs in bottom ~20% (dec0 m03~23->31% ; dec2 m03~48->17%), FLAT dec2-9 (17%->12%).
# => score only discriminates below ~40-50; round-number 50/75 splits separate identical days.

# distribution is clumped, not uniform -> use EMPIRICAL percentile tiers, not fixed width
print(df.m03_score.quantile([.1,.25,.5,.75,.9]).round(1))   # p50=61, p10=33

# RECOMMENDED 3-tier (signal is one-sided): Danger m03<40 / Neutral 40-70 / Benign >70
df["m03_cal"]=pd.cut(df.m03_score,[0,40,70,100],labels=["Danger","Neutral","Benign"])
print(df.groupby("m03_cal",observed=True).agg(n=("ret","size"),fwd_vol=("fvol","mean"),fwd21=("f21","mean")).round(3))
# target_exposure tiers (0.15/0.35/0.75-0.85/1.0) are ALREADY monotone+well-spaced -> risk model fine as-is.
```
