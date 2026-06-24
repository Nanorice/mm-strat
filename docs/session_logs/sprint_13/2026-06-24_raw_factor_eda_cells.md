# Raw-Factor EDA — intended notebook cells (2026-06-24)

> Step 1 of the R-c roadmap (§10 of `2026-06-24_regime_model_design.md`).
> **Raw, non-transformed factors, full horizon, distributional.** Deliberately NOT a re-run of
> §A1–A3 (those were transformed `z_*`/`m03` columns, QQQ-2010+, lead-lag — closed findings).
> Target a NEW notebook `notebooks/raw_factor_eda.ipynb` (do not append to `signs_of_tail`).
>
> **Deliverables this EDA must hand to step 2/3:** (a) per-factor normalization choice (from S1),
> (b) per-factor mean-reverting-vs-drifting label + lookback (from S2), (c) per-factor stress level
> on its own ruler (from S3), (d) splice decision for DXY/MOVE (from S4), (e) redundancy map (S5),
> and (f) a PROPOSED step-3 success metric (the explicit deliverable noted in §10).

---

## S0 — Load & assemble the raw panel

```python
# %% S0 — setup + assemble raw factor panel (FRED parquet + DuckDB), no transforms
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd, duckdb
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

ROOT = Path.cwd()
while not (ROOT / "data" / "market_data.duckdb").exists() and ROOT != ROOT.parent:
    ROOT = ROOT.parent
DB = str(ROOT / "data" / "market_data.duckdb")
PANEL = ROOT / "scratch" / "raw_factor_panel.parquet"   # from scratch_source_factors.py
con = duckdb.connect(DB, read_only=True)                # read_only: never lock the DB

# --- FRED-sourced factors (scratch parquet, long format date/symbol/value) ---
fred = pd.read_parquet(PANEL)
fred["date"] = pd.to_datetime(fred["date"])
fred = fred.pivot(index="date", columns="symbol", values="value")
# columns: real_yield_10y, dxy_broad, dxy_major_legacy, bondvol_vxtyn_legacy

# --- DB-resident factors (macro_data long; price_data for ETFs) ---
macro = con.execute("""
    SELECT date, symbol, close FROM macro_data
    WHERE symbol IN ('VIX','BAMLH0A0HYM2','DGS10','DGS2')
""").df()
macro["date"] = pd.to_datetime(macro["date"])
macro = macro.pivot(index="date", columns="symbol", values="close").rename(
    columns={"BAMLH0A0HYM2": "hy_spread"})

etf = con.execute("""
    SELECT date, ticker, close FROM price_data WHERE ticker IN ('HYG','LQD','MOVE')
""").df()
etf["date"] = pd.to_datetime(etf["date"])
etf = etf.pivot(index="date", columns="ticker", values="close")

# --- market benchmark for S3 (raw close -> daily return) ---
mkt = con.execute("""
    SELECT date, close FROM price_data WHERE ticker = 'QQQ' ORDER BY date
""").df()
mkt["date"] = pd.to_datetime(mkt["date"])
mkt = mkt.set_index("date")["close"]
mkt_ret = mkt.pct_change().rename("qqq_ret")

# --- merge everything on a daily index (NO ffill yet -- S0 shows true coverage) ---
panel = fred.join(macro, how="outer").join(etf, how="outer").sort_index()

# derived factors (per the 'both legs + derived' decision)
panel["term_spread"]  = panel["DGS10"] - panel["DGS2"]      # 2s10s
panel["credit_ratio"] = panel["HYG"] / panel["LQD"]          # risk-appetite proxy

FACTORS = [
    "VIX", "hy_spread", "real_yield_10y",
    "dxy_broad", "dxy_major_legacy",
    "MOVE", "bondvol_vxtyn_legacy",
    "DGS10", "DGS2", "term_spread",
    "HYG", "LQD", "credit_ratio",
]

# coverage table -- the cliffs matter (1990 core -> 2003 credit/RY -> 2006 DXY -> 2021 MOVE)
cov = pd.DataFrame({
    "n":     panel[FACTORS].notna().sum(),
    "start": panel[FACTORS].apply(lambda s: s.first_valid_index()),
    "end":   panel[FACTORS].apply(lambda s: s.last_valid_index()),
})
print(cov.to_string())
print(f"\npanel: {panel.index.min().date()} -> {panel.index.max().date()}  rows={len(panel)}")
```

**Read:** confirm the coverage cliffs before any cross-factor work — only VIX/rates reach 1990;
real-yield/HY/credit join ~2003; DXY-broad ~2006; MOVE 2021. Anything multivariate is bounded by
the latest-starting factor in that subset.

---

## S1 — Per-factor univariate distribution

```python
# %% S1 — moments + fat-tail diagnostics on RAW levels
from scipy import stats

rows = []
for f in FACTORS:
    s = panel[f].dropna()
    rows.append({
        "factor": f, "n": len(s),
        "mean": s.mean(), "median": s.median(), "std": s.std(),
        "skew": stats.skew(s), "kurtosis": stats.kurtosis(s),  # excess (0 = normal)
        "p01": s.quantile(.01), "p99": s.quantile(.99),
        "jb_p": stats.jarque_bera(s).pvalue,                   # <0.05 => non-normal
    })
moments = pd.DataFrame(rows).set_index("factor")
print(moments.round(3).to_string())

# histograms + QQ vs normal, one row per factor
n = len(FACTORS)
fig, ax = plt.subplots(n, 2, figsize=(11, 2.4 * n))
for i, f in enumerate(FACTORS):
    s = panel[f].dropna()
    ax[i, 0].hist(s, bins=80); ax[i, 0].set_title(f"{f}  hist")
    stats.probplot(s, dist="norm", plot=ax[i, 1]); ax[i, 1].set_title(f"{f}  QQ-norm")
fig.tight_layout()
```

**Deliverable:** which factors are fat-tailed (high excess kurtosis: expect VIX, MOVE, hy_spread)
vs. roughly Gaussian → drives normalization choice (raw-z OK for Gaussian; percentile/rank for
fat-tailed, per §7-F). Note skew direction — vol/spread factors are right-skewed (tail = stress).

---

## S2 — Stationarity & cyclicality (the mean-reverting vs. drifting label)

```python
# %% S2 — ADF/KPSS + ACF + rolling mean.  This sets the per-factor LOOKBACK decision.
from statsmodels.tsa.stattools import adfuller, kpss, acf

rows = []
for f in FACTORS:
    s = panel[f].dropna()
    adf_p  = adfuller(s, autolag="AIC")[1]
    try:
        kpss_p = kpss(s, regression="c", nlags="auto")[1]
    except Exception:
        kpss_p = np.nan
    ac = acf(s, nlags=252, fft=True)
    # half-life of mean reversion via AR(1): dx = a + b*x_{t-1}; HL = -ln2 / ln(1+b)
    x = s.shift(1).dropna(); y = s.loc[x.index]
    b = np.polyfit(x, y, 1)[0] - 1.0
    hl = (-np.log(2) / np.log(1 + b)) if -1 < b < 0 else np.nan
    rows.append({
        "factor": f,
        "adf_p": adf_p,            # <0.05 => stationary (reject unit root)
        "kpss_p": kpss_p,          # <0.05 => NON-stationary (reject level-stationarity)
        "acf_21": ac[21], "acf_252": ac[252],
        "ar1_halflife_d": hl,
        "label": ("mean-reverting" if adf_p < 0.05 else "drifting"),
    })
stat = pd.DataFrame(rows).set_index("factor")
print(stat.round(3).to_string())

# rolling 1y mean -- visual of secular drift (P3) vs mean-reversion
# BUGFIX: panel has an OUTER-joined index with NaN holes (S0 intentionally skips ffill).
# rolling(252) counts INDEX ROWS, so any 252-row window touching a NaN returns NaN -> the line
# shatters into fragments. Fix at source: dropna() PER FACTOR so each rolls over its own valid obs.
fig, ax = plt.subplots(figsize=(13, 5))
for f in ["VIX", "hy_spread", "real_yield_10y", "term_spread", "dxy_broad", "credit_ratio"]:
    s = panel[f].dropna()                                 # <-- per-factor, contiguous valid series
    z = (s - s.mean()) / s.std()                          # z only for shared-axis VISUAL
    z.rolling(252).mean().plot(ax=ax, label=f, alpha=.8)
ax.legend(ncol=3); ax.set_title("rolling 1y mean (z-scaled for display) — drift vs reversion")
ax.set_ylabel("rolling 1y mean, z-scaled")
```

**The S2 plot, explained (and how to READ it):** the *table* is the deliverable (per-factor label);
the plot just makes "drifting" visible vs. asserted. Each line is a factor's **1-year trailing mean**,
z-scaled so all six share one axis. **Read it by SHAPE, not level:**
- A line that stays roughly **FLAT near 0** = mean-reverting: its 1y average keeps returning to the
  same center (expect VIX, hy_spread). The yardstick is stable → full-history reference is valid.
- A line that **WANDERS far from 0 and stays there** (long swings up/down) = drifting: its "normal"
  level relocated (expect real_yield, dxy_broad, the rate factors). The yardstick slides → needs a
  rolling lookback, NOT differencing (per §10 reason #1).

The first render was a BUG (shattered fragments from the NaN-hole issue above), not the real signal —
re-run with the dropna() fix and the lines become continuous. Drop the plot if the S2/S2b tables
already settle each factor; the table is what step 2 actually consumes.

```python
# %% S2b — full-history ADF is UNRELIABLE on regime-switching factors (real_yield is bimodal!).
#          Test stationarity WITHIN a rolling window: is the factor mean-reverting locally even if
#          it drifts globally? That distinction IS the §10 reason-#1 decision (rolling window vs.
#          differencing). A factor MR-within-5yr but drifting-across-20yr => use a rolling lookback.
def rolling_adf_pass_rate(s, win=1260, step=63):   # 5yr window, quarterly step
    s = s.dropna(); ps = []
    for i in range(0, len(s) - win, step):
        seg = s.iloc[i:i + win]
        try: ps.append(adfuller(seg, autolag="AIC")[1])
        except Exception: pass
    ps = np.array(ps)
    return (ps < 0.05).mean() if len(ps) else np.nan, len(ps)

for f in ["real_yield_10y", "DGS10", "term_spread", "dxy_broad", "VIX", "hy_spread"]:
    rate, k = rolling_adf_pass_rate(panel[f])
    full = adfuller(panel[f].dropna(), autolag="AIC")[1]
    print(f"{f:16s} full-ADF p={full:.3f} ({'MR' if full<.05 else 'drift'})  "
          f"| rolling-5yr MR-rate={rate:.2f} over {k} windows")
```

**Deliverable:** the per-factor **mean-reverting vs. drifting** label + half-life, AND the
local-vs-global split (S2b). This is §10 reason #1 made concrete: VIX/HY/MOVE should be
mean-reverting (→ full-history reference OK); rates/real-yield/DXY likely drift *globally* but may
revert *locally* (→ rolling window that captures the cycle, NOT differencing — which would destroy
the cycle signal). **real_yield specifically:** its S1 histogram is bimodal (ZIRP cluster ~0 +
post-Covid cluster ~+2), so a single full-history ADF cannot tell "unit root" from "two stationary
regimes" — S2b's rolling MR-rate is the honest read. ADF+KPSS together: both-agree = confident;
disagree = trend-stationary / fractional.

---

## S3 — Raw factor level conditioned on market tail days (full history)

```python
# %% S3 — what level does each raw factor sit at when the MARKET is in its tail?
#         NOT lead-lag (that's §A2, closed). Pure same-day conditional LEVELS, full history.
df3 = panel.join(mkt_ret, how="inner")
tail = df3["qqq_ret"] <= df3["qqq_ret"].quantile(0.05)    # worst 5% market days, full horizon

rows = []
for f in FACTORS:
    s_all  = df3[f].dropna()
    s_tail = df3.loc[tail, f].dropna()
    if len(s_tail) < 30:
        continue
    rows.append({
        "factor": f,
        "all_median":  s_all.median(),
        "tail_median": s_tail.median(),
        "all_p95":     s_all.quantile(.95),
        "tail_pctl_of_all": (s_all < s_tail.median()).mean(),  # where tail-median sits in full dist
        "tail_vs_all_z": (s_tail.mean() - s_all.mean()) / s_all.std(),
    })
stress = pd.DataFrame(rows).set_index("factor")
print(stress.round(3).to_string())

# distribution overlap: full vs tail-day, per factor
keyf = ["VIX", "hy_spread", "MOVE", "real_yield_10y", "term_spread", "credit_ratio"]
fig, ax = plt.subplots(2, 3, figsize=(15, 8))
for a, f in zip(ax.ravel(), keyf):
    a.hist(df3[f].dropna(), bins=60, density=True, alpha=.5, label="all")
    a.hist(df3.loc[tail, f].dropna(), bins=60, density=True, alpha=.5, label="mkt tail")
    a.set_title(f); a.legend()
fig.tight_layout()
```

**Deliverable:** each factor's **stress level on its own native ruler** (`tail_pctl_of_all` = the
percentile a factor reaches on market-tail days). Directly feeds the per-factor veto/percentile in
step 2 (§7-G): a factor whose tail-day median is only its 60th pctl has a *shallow* stress
signature and must not share a fixed z≥2 veto with a fat-tailed one. **Note:** S3 is COINCIDENT by
construction — it is not a prediction claim; it characterizes co-stress, consistent with §2.

---

## S3b — Offset/lead test: is any RAW factor elevated BEFORE the market tail?

```python
# %% S3b — the "alerting" test the user asked for. For each raw factor, measure its level at
#          OFFSETS before the tail day (t-21 ... t0). A LEADING factor is already elevated at t-21;
#          a COINCIDENT one only spikes at t0. This is NOT §A2 (that tested transformed z_* and asked
#          if the AGGREGATE leads). The literature predicts a SPECIFIC split here:
#            - credit (hy_spread) leads drawdowns by 2-4 weeks  [lit review §2 "the one number", §5.2]
#            - term_spread leads at long horizon                [§5.2]
#            - VIX / MOVE are CONTEMPORANEOUS, not leading       [§2: "VIX is reactive; credit leads"]
#          If our data confirms this, it directly ranks factors for a LEADING role in step 2/3.
OFFSETS = [-21, -10, -5, -3, -1, 0]
tail_idx = np.where(tail.values)[0]                      # positions of market-tail days
arr = {f: df3[f].values for f in FACTORS}
allz = {f: (df3[f] - df3[f].mean()) / df3[f].std() for f in FACTORS}   # z for cross-factor compare

rows = []
for f in FACTORS:
    z = allz[f].values
    rec = {"factor": f}
    for off in OFFSETS:
        pos = tail_idx + off
        pos = pos[(pos >= 0) & (pos < len(z))]
        vals = z[pos]
        rec[f"t{off:+d}"] = np.nanmean(vals)             # mean z-level at this offset before tail
    # "lead score": how elevated already at t-21 vs the at-event jump (t0). high => leads.
    rec["lead_t-21"] = rec["t-21"]
    rows.append(rec)
lead = pd.DataFrame(rows).set_index("factor")
print(lead.round(2).to_string())
print("\nRead: a row that is already >0 at t-21 and rises gently = LEADING (alerting).")
print("A row ~0 until t-1/t0 then jumps = COINCIDENT (confirms, does not warn).")

# visual: average z-trajectory into the tail day, per factor
fig, ax = plt.subplots(figsize=(11, 6))
for f in ["VIX", "hy_spread", "MOVE", "term_spread", "real_yield_10y", "credit_ratio"]:
    ax.plot(OFFSETS, [lead.loc[f, f"t{o:+d}"] for o in OFFSETS], marker="o", label=f)
ax.axvline(0, color="k", lw=.7); ax.axhline(0, color="grey", lw=.5)
ax.set_xlabel("trading days relative to market-tail day"); ax.set_ylabel("mean z-level")
ax.set_title("factor trajectory INTO the tail — leading vs coincident"); ax.legend()
```

**Deliverable:** a **leading-vs-coincident ranking** of the raw factors — the single most
decision-relevant output of the EDA, because it tells step 2/3 *which factors can warn* vs. which
only confirm. **This is the literature's central claim tested on our data:** if hy_spread/term_spread
are elevated at t−21 while VIX/MOVE are flat until t0, the lit review's "credit leads, vol reacts"
holds here and credit should be weighted for the leading role. If NOT — if even credit is flat at
t−21 on our panel — that is itself a hard finding (consistent with §A1/§A2: nothing leads on this
universe) and the model is confirmed coincident-only → sizing, not timing. **Caveat:** overlapping
tail days share offset windows; treat as descriptive, not a significance test.

### S3b RESULT (observed 2026-06-24) + the divergence it raises

Observed: **VIX and hy_spread are BOTH already at z≈+0.62 at t−21**, rising to ~+0.9 by t−1, VIX
jumps to +1.3 at t0. credit_ratio/term_spread/real_yield are flat-to-wrong-way. **On its face this
says VIX & credit LEAD** — which contradicts §A1/§A2 ("nothing leads; corr(z_vix, fwd_ret) is
POSITIVE and rising"). The contradiction is **only apparent**, and S3c below is the resolver:

- **Elevated-and-persistent ≠ leading.** Tail days CLUSTER (Mar-2020 = dozens within weeks). For a
  clustered tail day, "t−21" frequently lands inside a *prior* tail's stress window. VIX/HY are
  highly autocorrelated (S2 half-life = weeks), so "high at t−21" partly means "a crash already
  happened ~21d ago" — the exact de-overlapping artifact §A1 named.
- **The clean test is forward-predictive, and §A2 already ran it:** if VIX truly led, `corr(z_vix,
  fwd_ret)` would be NEGATIVE. It is +0.30. So the t−21 elevation does NOT convert to predictive
  power. A coincident, persistent stress meter looks EXACTLY like this S3b plot.

## S3c — Resolver: does the t−21 level SURVIVE de-overlapping + condition on a CALM start?

```python
# %% S3c — separate "leads" from "is just persistently high". Two controls:
#   (A) ONSET-only tails: drop tail days within 21d of a prior tail (de-overlap, like §A1 merge).
#   (B) CALM-start subset: keep only onset tails where the factor was BELOW median at t-21
#       (i.e. the market was calm 21d earlier). If the factor STILL rises into the tail from a calm
#       base, that is a genuine lead. If the t-21 elevation vanishes once we require a calm start,
#       the original signal was just autocorrelation/clustering -> COINCIDENT, not leading.
ti = tail_idx.copy()
onset = ti[np.concatenate([[True], np.diff(ti) > 21])]    # (A) first tail of each cluster
print(f"all tail days={len(ti)}  ->  onset-only={len(onset)}")

rows = []
for f in ["VIX", "hy_spread", "term_spread", "credit_ratio", "real_yield_10y", "MOVE"]:
    z = allz[f].values
    def mean_at(idx, off):
        p = idx + off; p = p[(p >= 0) & (p < len(z))]
        return np.nanmean(z[p])
    # (A) onset-only trajectory
    a_m21, a_t0 = mean_at(onset, -21), mean_at(onset, 0)
    # (B) calm-start: onset tails whose factor z(t-21) < 0 (below its own mean 21d before)
    pre = onset - 21; pre = pre[pre >= 0]
    calm = onset[np.isin(onset, pre + 21)]                # align back
    calm = np.array([o for o in onset if (o - 21) >= 0 and z[o - 21] < 0])
    b_m21 = np.nanmean([z[o - 21] for o in calm]) if len(calm) else np.nan
    b_t0  = np.nanmean([z[o]      for o in calm]) if len(calm) else np.nan
    rows.append({"factor": f, "onset_n": len(onset),
                 "A_t-21": a_m21, "A_t0": a_t0, "A_rise": a_t0 - a_m21,
                 "calm_n": len(calm), "B_t-21": b_m21, "B_t0": b_t0,
                 "B_rise_from_calm": (b_t0 - b_m21) if len(calm) else np.nan})
res = pd.DataFrame(rows).set_index("factor")
print(res.round(2).to_string())
print("\nVERDICT KEY:")
print(" - A_t-21 stays high after de-overlap  => persistent elevation is REAL but maybe still clustered")
print(" - B_rise_from_calm large & positive    => factor rises into tail FROM A CALM BASE = genuine LEAD")
print(" - B_rise ~0 or t0 still low            => no lead; original t-21 signal was autocorrelation")
```

**Deliverable:** the *actual* verdict on leading-vs-coincident, robust to the clustering artifact.
Decision rule for step 2/3: **a factor earns a "leading" role ONLY if `B_rise_from_calm` is
materially positive** (it climbs into the tail starting from a calm reading). Expectation given
§A2: VIX's apparent lead collapses under control (B); the open question is whether **hy_spread or
term_spread** retains any rise-from-calm — that, and only that, would justify a leading factor in the
model. Cross-check against §A2's forward-return corr: a genuine lead here must coexist with a
negative `corr(factor, fwd_ret)`, or it is not exploitable for timing.

### S3c RESULT (2026-06-24): roughly FLAT → coincident confirmed on our setup.

`B_rise_from_calm` ≈ 0 across factors → the t−21 elevation in S3b was autocorrelation/clustering,
not a lead. **But** this only falsifies "do raw daily factor levels lead QQQ daily tails." The
literature's "credit leads" rests on a DIFFERENT measurement (S3d reconciles it).

## S3d — Reconcile with the literature: the GZ Excess Bond Premium (the RIGHT credit metric)

```python
# %% S3d — Why the lit review says "credit leads" and our S3b/c said flat. FIVE differences between
#          their test and ours; this cell closes the biggest one (METRIC + frequency + target):
#   (1) METRIC: their leader is the GZ Excess Bond Premium (ebp) = credit spread with the
#       default-risk component REMOVED -> pure risk-appetite residual. Our hy_spread is the TOTAL
#       spread (closer to gz_spread); credit_ratio (HYG/LQD) is further still (an ETF price ratio).
#   (2) FREQUENCY: their lead lives at MONTHLY resolution; our t-21 was 21 daily bars (noise-buried).
#   (3) TARGET: they predict RECESSIONS (est_prob), not equity tail days.
#   (4) INDEX: they use broad market; we used QQQ (tech/vol-tilted).  [tested separately if needed]
#   (5) TEST: predictive regression w/ decades of obs, vs our ~15-25 onset events.
# Source: Fed FEDS Notes, ebp_csv.csv (Gilchrist-Zakrajsek). Monthly 1973-2026.
gz = pd.read_parquet(ROOT / "scratch" / "gz_ebp_monthly.parquet").set_index("date")
# columns: gz_spread (total), ebp (excess premium = the leading residual), est_prob (recession prob)

# monthly market return + forward drawdown to test the LEAD on the paper's own terms
mkt_m = mkt.resample("MS").last()
gz = gz.join((mkt_m.pct_change().shift(-1)).rename("fwd_1m"))           # next-month return
gz = gz.join((mkt_m.pct_change(3).shift(-3)).rename("fwd_3m"))          # next-quarter return

print("=== Does ebp LEAD where raw spread does not? corr(metric_t, forward market return) ===")
print("(a LEADING risk metric is NEGATIVE here; coincident/lagging is ~0 or positive)")
for col in ["gz_spread", "ebp"]:
    print(f"  {col:10s}  fwd_1m={gz[col].corr(gz['fwd_1m']):+.3f}   fwd_3m={gz[col].corr(gz['fwd_3m']):+.3f}")

# also: does ebp lead our DAILY hy_spread? (cross-check it's measuring something different)
hy_m = panel["hy_spread"].resample("MS").last()
aligned = gz.join(hy_m.rename("hy_total"), how="inner")
print(f"\ncorr(ebp, hy_total) monthly = {aligned['ebp'].corr(aligned['hy_total']):.3f}  "
      f"(low => ebp carries info hy_spread does NOT)")

# visual: ebp vs gz_spread around the est_prob recession signal
fig, ax = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
gz[["gz_spread", "ebp"]].plot(ax=ax[0], title="GZ total spread vs Excess Bond Premium (monthly)")
ax[0].axhline(0, color="grey", lw=.5)
gz["est_prob"].plot(ax=ax[1], title="model-implied recession probability", color="firebrick")
fig.tight_layout()
```

**Deliverable — the reconciliation verdict.** Two outcomes:
- **If `ebp` shows a negative fwd-return corr where `gz_spread`/our `hy_spread` does not** → the
  literature is RIGHT and our earlier "no lead" was a *metric* problem: we used the total spread, not
  the refined residual. Then `ebp` becomes a genuine **leading** candidate for the model (sourced,
  monthly — a real step-2 factor), and the §9/R-c call changes: timing may be back on the table.
- **If even `ebp` is flat/positive on forward returns** → the lead the papers report is specific to
  *recession* prediction (`est_prob`), not *equity* returns, and does not transfer to our use. Then
  "coincident-only" stands FIRMLY (now tested against the literature's own best metric), and we
  proceed to sizing-primary with confidence. **Either way this closes the divergence honestly** —
  we'll have tested the literature's actual claim, not a daily proxy of it.

---

## S4 — DXY & MOVE splice segments, characterized SEPARATELY (no join)

```python
# %% S4 — profile the splice partners on their OWN segments. DO NOT join here.
segments = {
    "dxy_major_legacy (1990-2019)": panel["dxy_major_legacy"].dropna(),
    "dxy_broad (2006+)":            panel["dxy_broad"].dropna(),
    "MOVE (2021+)":                 panel["MOVE"].dropna(),
    "vxtyn_legacy (2003-2020)":     panel["bondvol_vxtyn_legacy"].dropna(),
}
rows = []
for name, s in segments.items():
    rows.append({"segment": name, "n": len(s), "start": s.index.min().date(),
                 "end": s.index.max().date(), "mean": s.mean(), "std": s.std(),
                 "skew": stats.skew(s), "kurt": stats.kurtosis(s)})
print(pd.DataFrame(rows).set_index("segment").round(3).to_string())

# overlap windows: do the partners even agree where they coexist?
ov_dxy = panel[["dxy_major_legacy", "dxy_broad"]].dropna()
ov_bv  = panel[["MOVE", "bondvol_vxtyn_legacy"]].dropna()
print(f"\nDXY overlap n={len(ov_dxy)}  corr={ov_dxy.corr().iloc[0,1]:.3f}"
      f"  (level gap median={ (ov_dxy['dxy_broad']-ov_dxy['dxy_major_legacy']).median():.2f})")
print(f"MOVE/VXTYN overlap n={len(ov_bv)}"
      + (f"  corr={ov_bv.corr().iloc[0,1]:.3f}" if len(ov_bv) else "  (NO overlap — disjoint windows)"))

fig, ax = plt.subplots(1, 2, figsize=(14, 4))
panel[["dxy_major_legacy", "dxy_broad"]].plot(ax=ax[0], title="DXY legacy vs broad (different basket)")
panel[["MOVE", "bondvol_vxtyn_legacy"]].plot(ax=ax[1], title="MOVE vs VXTYN (different instrument)")
```

**Deliverable:** the splice decision. Key checks: (1) different mean/scale = a naive concat injects
a structural break; (2) overlap corr tells whether a rebase is even defensible; (3) MOVE vs VXTYN
likely have **zero overlap** (2020 vs 2021) → cannot rebase, only used as separate-era references.
Expected outcome per §10: keep separate, do NOT manufacture a continuous series (the "molding error").

---

## S5 — Raw-level cross-correlation + redundancy map

```python
# %% S5 — raw-LEVEL correlation (contrast §A6 which was on z-scores). Common-window only.
core = ["VIX", "hy_spread", "real_yield_10y", "dxy_broad", "MOVE",
        "DGS10", "DGS2", "term_spread", "credit_ratio"]
C = panel[core].dropna()                      # inner join => common window (MOVE binds to 2021+)
print(f"common-window: {C.index.min().date()} -> {C.index.max().date()}  n={len(C)}")
corr = C.corr()

fig, ax = plt.subplots(figsize=(9, 7))
im = ax.imshow(corr, vmin=-1, vmax=1, cmap="RdBu_r")
ax.set_xticks(range(len(core))); ax.set_xticklabels(core, rotation=90)
ax.set_yticks(range(len(core))); ax.set_yticklabels(core)
for i in range(len(core)):
    for j in range(len(core)):
        ax.text(j, i, f"{corr.iloc[i,j]:.2f}", ha="center", va="center", fontsize=7)
fig.colorbar(im); ax.set_title("raw-level correlation (common window)")

# ALSO compute on the longer non-MOVE window so the 2021+ clamp isn't the only view
core2 = [c for c in core if c != "MOVE"]
C2 = panel[core2].dropna()
print(f"\nno-MOVE window: {C2.index.min().date()} -> {C2.index.max().date()}  n={len(C2)}")
print(C2.corr().round(2).to_string())
```

**Deliverable:** redundancy map on raw levels + first preview of what the P2 joint space faces.
Two windows on purpose — the MOVE-inclusive matrix is clamped to 2021+ (tiny, one regime); the
no-MOVE matrix spans 2006+ and is the honest redundancy read. Expect DGS10–DGS2 collinearity (hence
term_spread), VIX–MOVE high (both vol), credit_ratio ⟂ rates. Flags which factors a learned joint
model will treat as one axis.

---

## Wrap — deliverable checklist to carry into step 2/3

After running, record a short table:

| factor | distribution (S1) | label (S2) | stress pctl (S3) | normalization pick |
|---|---|---|---|---|
| VIX | fat-tail, R-skew | mean-revert | ~? | percentile |
| real_yield_10y | ? | drifting | ~? | rolling-z |
| … | | | | |

Plus: **(a)** DXY/MOVE splice decision (S4), **(b)** redundancy clusters (S5), and **(c) a PROPOSED
step-3 success metric** — the §10-required deliverable.

### Lit-review-driven additions (from `docs/research/regime_model/market_regime_literature_review.md`)

1. **Two baseline rivals for the deferred success metric, not one.** §A4 set z_vix fwd-vol
   corr **0.67 @ H=5–10** as the incumbent. But the lit review's "one number" is **HY OAS, not VIX**
   — credit "leads equity drawdowns by 2–4 weeks" and has "the highest information ratio for regime
   classification." So step 3 must beat BOTH a VIX-only AND an hy_spread-only single-factor baseline.
   S3b directly tests whether credit's claimed lead shows up on our panel.

2. **The literature's top LEAD indicator is one we have NOT built: the Absorption Ratio** (§4.6,
   Kritzman 2012) — fraction of cross-asset variance in the top PCs; "precedes equity drawdowns by
   20–60 days." It is a *cross-asset* construct needing 20–50 asset return series, NOT computable
   from these 13 macro levels. **Flag as the #1 step-2 candidate factor to add** if S3b confirms the
   existing factors are coincident-only. (Caveat from lit: AR is a *fragility* signal w/ ~40% false
   positives and missed Mar-2020 — a fragility overlay, not a timing gate.)

3. **The lit review's "optimal stack" validates the §10 direction but reorders priority:**
   Layer 1 = vol-targeting for SIZING (the proven use, §A4) → "single highest-ROI addition";
   Layer 2 = composite threshold rules (the current model); Layer 4 = two-stage HMM→ML (= R-c).
   Note it places the learned joint model (R-c) as the *optional, last* layer — consistent with §9's
   open question. If S3b shows coincident-only, the lit review says the sizing layer is where the
   value is, and the R-c ML stage is the speculative add, not the core.

### S5 redundancy read (already observed from the run)

The raw-level corr matrix (common 2021+ window) shows **severe collinearity** that the P2/ML stage
must confront: real_yield ↔ DGS10 = **0.99**, DGS2 ↔ DGS10 = 0.94, credit_ratio ↔ DGS10 = 0.92,
MOVE ↔ {real_yield, DGS10, credit_ratio} ≈ **−0.91**. → on the 2021+ window these are nearly ONE
axis (the rate-level/QT regime), NOT independent factors. VIX ↔ hy_spread = 0.49 (the genuine
risk-off pair); term_spread is the least redundant (|corr| ≤ 0.55). **Implication:** a naive
weighted sum or even raw PCA would be dominated by the rate-collinearity cluster. Confirm against the
longer no-MOVE window (S5 second print) — the 0.99s are partly the tiny 2021+ sample (one regime).
This is the core P2 problem made visible: the joint model needs decorrelation/whitening or it just
re-measures the rate level five times.
```
