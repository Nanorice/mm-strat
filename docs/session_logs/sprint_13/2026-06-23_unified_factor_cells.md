# 2-axis regime view, PCA & clustering, weight audit — cells (verified)

> Run end-to-end on `data/market_data.duckdb`. Tests whether (a) the 2-axis M03×risk view carries
> information beyond either axis, (b) the unified factor space has interpretable PCA/cluster
> structure, (c) the risk model's hand-weights are sane, (d) the input set is complete.

## Shared setup
```python
reg=con.execute("select * from t2_regime_scores").df(); reg["date"]=pd.to_datetime(reg["date"])
rsk=con.execute("select * from t2_risk_scores").df(); rsk["date"]=pd.to_datetime(rsk["date"])
px =con.execute("select date,close from price_data where ticker=? and date>=? order by date",[BENCH,START]).df()
px["date"]=pd.to_datetime(px["date"])
df=px.merge(reg,on="date").merge(rsk,on="date").sort_values("date").reset_index(drop=True)
df["ret"]=df["close"].pct_change()
df["fvol"]=df["ret"].shift(-1).rolling(5).std().shift(-4)*np.sqrt(252)   # 5d ann fwd realized vol
df["f21"]=df["close"].shift(-21)/df["close"]-1
FACS=["z_vix","z_hy","z_term","z_trend","z_slope","m03_pillar_liq","m03_pillar_trend"]
```

## Cell U1 — the 2-axis plot, colored by forward vol
```python
fig,ax=plt.subplots(1,2,figsize=(15,6))
sc=ax[0].scatter(df.m03_score,df.weighted_z,c=df.fvol,cmap="RdYlGn_r",s=8,alpha=.6,vmax=0.5)
ax[0].set(xlabel="M03 score (regime quality, higher=benign)",ylabel="weighted_z (stress, higher=worse)",
          title="2-axis: position colored by 5d fwd realized vol")
plt.colorbar(sc,ax=ax[0],label="fwd vol (ann.)")
# off-diagonal = disagreement. annotate the two interesting corners
ax[0].axhline(df.weighted_z.median(),color="grey",ls=":"); ax[0].axvline(df.m03_score.median(),color="grey",ls=":")
sc2=ax[1].scatter(df.m03_score,df.weighted_z,c=df.f21,cmap="RdYlGn",s=8,alpha=.6,vmin=-.1,vmax=.1)
ax[1].set(xlabel="M03 score",ylabel="weighted_z",title="same, colored by fwd 21d return")
plt.colorbar(sc2,ax=ax[1],label="fwd 21d ret")
plt.tight_layout(); plt.show()
```

## Cell U2 — does POSITION add info beyond either axis? (R² ladder)
```python
from numpy.linalg import lstsq
def r2(cols,tgt):
    s=df[cols+[tgt]].dropna(); X=np.column_stack([np.ones(len(s))]+[s[c].values for c in cols])
    b=lstsq(X,s[tgt].values,rcond=None)[0]; p=X@b
    return 1-((s[tgt].values-p)**2).sum()/((s[tgt].values-s[tgt].mean())**2).sum()
df["interact"]=df.m03_score*df.weighted_z
for t in ["fvol","f21"]:
    print(t, "m03",round(r2(['m03_score'],t),4),"| wz",round(r2(['weighted_z'],t),4),
          "| both",round(r2(['m03_score','weighted_z'],t),4),
          "| +interact",round(r2(['m03_score','weighted_z','interact'],t),4))
# fvol: m03 0.20 | wz 0.32 | both 0.34 | +interact 0.35  -> 2nd axis adds ~0.02-0.04 R2. Small but real.
```

## Cell U3 — PCA on unified 7-factor set
```python
F=df[FACS].dropna(); Fz=(F-F.mean())/F.std()
U,S,Vt=np.linalg.svd(Fz.values,full_matrices=False); evr=S**2/(S**2).sum()
print("explained var:",np.round(evr,3))   # [0.46 0.18 0.13 0.11 0.07 0.04 0.01]
load=pd.DataFrame(Vt[:3].T,index=FACS,columns=["PC1","PC2","PC3"]).round(2); print(load)
# PC1 = broad risk-on/off (vix+trend+slope). PC2 = credit-vs-curve. PC3 = ALMOST PURE net-liquidity (0.88).
# project & color by fwd vol
sc=df.dropna(subset=FACS).copy()
P=(sc[FACS]-F.mean())/F.std()
sc["pc1"]=P.values@Vt[0]; sc["pc2"]=P.values@Vt[1]
plt.figure(figsize=(8,6))
plt.scatter(sc.pc1,sc.pc2,c=sc.fvol,cmap="RdYlGn_r",s=8,alpha=.6,vmax=.5)
plt.colorbar(label="fwd vol"); plt.xlabel("PC1 (risk-on/off)"); plt.ylabel("PC2 (credit vs curve)")
plt.title("factor space in PC1-PC2, colored by fwd vol"); plt.show()
```

## Cell U4 — KMeans clusters → market conditions
```python
from sklearn.cluster import KMeans
sc=df.dropna(subset=FACS+["fvol","f21"]).copy()
Fz=(sc[FACS]-sc[FACS].mean())/sc[FACS].std()
sc["clu"]=KMeans(4,n_init=10,random_state=0).fit_predict(Fz.values)
print(sc.groupby("clu").agg(n=("ret","size"),z_vix=("z_vix","mean"),z_trend=("z_trend","mean"),
    liq=("m03_pillar_liq","mean"),fwd_vol=("fvol","mean"),fwd21=("f21","mean")).round(3))
# clu interpretation (typical run):
#  0 calm/weak-trend low-liq | 1 risk-OFF high-vol | 2 calm high-liq (best fwd) | 3 CRISIS (n~29, Mar2020, fwd_vol .72)
```

## Cell U5 — CONTRIBUTION AUDIT (done right: weight the Z-SCORES, not raw f_*)
```python
# WRONG WAY (do not use): mean(|f_*|) — f_vix is raw VIX spot (~9-82) vs f_trend (~0.04),
# so |f_vix| dominates purely on UNITS. That is NOT a weight. The model z-scores first.
W={"z_vix":0.25,"z_hy":0.25,"z_term":0.15,"z_trend":0.15,"z_slope":0.20}   # src/pipeline/risk_5_factor.py:40
d=rsk.dropna(subset=list(W))
recon=sum(d[c]*w for c,w in W.items())
print("weighted_z reconstruct corr:",round(recon.corr(d.weighted_z),4))   # 1.0 exact -> code is correct
# proper variance-share of each weighted term in weighted_z:
vw=d.weighted_z.var()
for c,w in W.items():
    share=np.cov(d[c]*w,d.weighted_z)[0,1]/vw
    print(f"  {c:8s} var-share {share*100:5.1f}%")
# RESULT: z_vix 29.5 | z_hy 24.8 | z_slope 21.7 | z_trend 19.1 | z_term 4.9  -> BALANCED, not VIX-only.
# 'looks like just VIX' = factor co-movement in stress (z_trend corr w/ wz 0.87 > z_vix 0.78), not weighting.
# Only genuine takeaway: z_term contributes 4.9% -> near-inert, candidate to drop/re-spec.
```
