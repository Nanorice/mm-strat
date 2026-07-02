# Step 6 — Per-Mechanism Lead Signals: intended notebook cells (2026-06-26)

> Implements `docs/research/regime_model/2026-06-26_step6_per_mechanism_design.md`. **Pre-registered:**
> the declustered onset list + mechanism taxonomy are FROZEN in S6-0 BEFORE any forward-return look.
> Two stages: **6a = controlled distributional SCREEN** (lead generator, not verdict), **6b =
> signal-conditional WALK-FORWARD gate** (the verdict).
>
> **The discipline (why Steps 1–4 were right to fear this):** ~6–8 onsets × 7 signals = overfitting
> minefield. Only OOS with a frozen taxonomy counts. 6a never proves a lead; 6b does.
>
> Data: `scratch/raw_factor_panel.parquet` (FRED) + DuckDB (VIX/HY/rates/SPY), read-only. Candidate
> transforms fold in the momentum challenge: level + diff1m(21d) + diff3m(63d).

---

## S6-0 — FROZEN artifacts: panel, declustered tail ONSETS, candidate signals

```python
# %% S6-0 — assemble panel + FREEZE the onset list and candidate set. NO forward returns touched yet.
import numpy as np, pandas as pd, duckdb
from pathlib import Path
import matplotlib.pyplot as plt
def _repo_root() -> Path:
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError(f"repo root not found above {p}")

ROOT = _repo_root()

# --- factors: FRED parquet (wide) + DB-resident (VIX, HY, rates) ---
fred = pd.read_parquet(ROOT / "scratch" / "raw_factor_panel.parquet")
wide = fred.pivot(index="date", columns="symbol", values="value")
wide.index = pd.to_datetime(wide.index)

con = duckdb.connect(str(ROOT / "data" / "market_data.duckdb"), read_only=True)
def macro(sym): 
    d = con.execute("SELECT date, COALESCE(value,close) v FROM macro_data WHERE symbol=? ORDER BY date",
                    [sym]).fetchdf()
    d["date"] = pd.to_datetime(d["date"]); return d.set_index("date")["v"].rename(sym)
vix = macro("VIX"); hy = macro("BAMLH0A0HYM2"); dgs10 = macro("DGS10"); dgs2 = macro("DGS2")
spy = con.execute("SELECT date, close FROM price_data WHERE ticker='SPY' ORDER BY date").fetchdf()
con.close()
spy["date"] = pd.to_datetime(spy["date"]); spy = spy.set_index("date")["close"].rename("spy")

P = pd.concat([wide, vix, hy, dgs10, dgs2, spy], axis=1).sort_index()
P["term_spread"] = P["DGS10"] - P["DGS2"]
P = P.loc["2003-01-01":]                       # bind to real_yield/HY coverage (cliffs: design §0.2)

# --- FACTORS under test (the candidate set, FROZEN) ---
FACTORS = ["VIX", "BAMLH0A0HYM2", "real_yield_10y", "term_spread", "dxy_broad"]
# --- candidate TRANSFORMS (folds momentum challenge in) ---
def transforms(s):
    return {"level": s, "diff1m": s.diff(21), "diff3m": s.diff(63)}
SIGNALS = {f"{f}__{t}": tr for f in FACTORS for t, tr in transforms(P[f]).items()}

# --- DECLUSTERED TAIL ONSETS (frozen). tail = SPY 21d fwd-looking? NO -> use realized 1d worst days,
#     then keep only FIRST of each cluster (gap >= 63d) so a pre-window can't overlap a prior tail. ---
ret1 = P["spy"].pct_change(fill_method=None)
TAIL_Q = 0.01                                  # worst 1% daily returns define a 'tail day'
thr = ret1.quantile(TAIL_Q)
tail_days = ret1[ret1 <= thr].index
onsets = []
for d in tail_days:
    if not onsets or (d - onsets[-1]).days >= 63:   # decluster: 63d gap => new episode
        onsets.append(d)
ONSETS = pd.DatetimeIndex(onsets)
print(f"tail threshold (1d) = {thr:.3%}  |  raw tail days = {len(tail_days)}  |  "
      f"DECLUSTERED onsets = {len(ONSETS)}")
print("onset dates:", [d.date().isoformat() for d in ONSETS])

# --- FROZEN crisis windows for the OOS split / labelling (pre-specified, NOT fit) ---
CRISES = [("2007-07","2009-06"), ("2020-02","2020-04"), ("2022-01","2022-10")]
```

> **FREEZE CHECK before proceeding:** `ONSETS`, `SIGNALS` keys, `CRISES`, and `TAIL_Q`/63d-decluster
> rule are now fixed. If any of these change after S6a/b runs, the pre-registration is VOID — re-date
> the doc and note why. This cell must NOT reference forward returns.

---

## S6a — Controlled distributional SCREEN (lead generator)

```python
# %% S6a — P(signal | controlled pre-tail) vs P(signal | MATCHED calm windows). Tail-mass, not mean.
#   controls (design §3): (1) declustered onsets, (2) calm-start (signal < its median at t-k),
#   (3) MATCHED baseline (random k-windows, same era), (4) test the 90th-pctl shift + KS, not the mean.
from scipy.stats import ks_2samp
rng = np.random.default_rng(0)
K = 42                                          # pre-tail window length (swept in S6a-robust)

def pre_tail_sample(sig, onsets, k):
    """values of sig over [onset-k, onset-1], calm-start filtered (below median at t-k)."""
    med = sig.median()
    vals = []
    for o in onsets:
        loc = sig.index.searchsorted(o)
        if loc - k < 0: 
            continue
        win = sig.iloc[loc - k: loc].dropna()
        if win.empty or win.iloc[0] >= med:     # calm-start: must START below its median
            continue
        vals.append(win)
    return pd.concat(vals) if vals else pd.Series(dtype=float)

def matched_sample(sig, onsets, k, n_draw=200):
    """random k-windows NOT within 126d of any onset (matched era via same index)."""
    s = sig.dropna()                              # drop leading-diff NaNs BEFORE sampling
    idx = s.index
    bad = pd.DatetimeIndex([d for o in onsets for d in pd.date_range(o-pd.Timedelta(days=126),
                                                                     o+pd.Timedelta(days=126))])
    cand = idx[(idx > idx[k]) & ~idx.isin(bad)]
    picks = rng.choice(len(cand), size=min(n_draw, len(cand)), replace=False)
    # window over the NaN-free series; concat then drop any residual NaN (ks_2samp returns NaN on NaN)
    return pd.concat([s.loc[:cand[p]].iloc[-k:] for p in picks]).dropna()

rows = []
for name, sig in SIGNALS.items():
    pre = pre_tail_sample(sig, ONSETS, K).dropna()
    base = matched_sample(sig, ONSETS, K)         # already NaN-free
    if len(pre) < 30 or len(base) < 30:
        continue
    # tail-mass shift: how much higher is the pre-tail 90th pctl vs matched? (z-normalized by base)
    b_mu, b_sd = base.mean(), base.std()
    p90_shift = (pre.quantile(.90) - base.quantile(.90)) / (b_sd + 1e-9)
    ks_stat, ks_p = ks_2samp(pre, base)           # NaN-free inputs => real p-value
    rows.append({"signal": name, "p90_shift_z": round(p90_shift, 3),
                 "ks": round(ks_stat, 3), "ks_p": round(ks_p, 4), "n_pre": len(pre)})
screen = pd.DataFrame(rows).sort_values("p90_shift_z", ascending=False)
print("=== S6a screen (positive p90_shift_z + low ks_p = distributional fingerprint) ===")
print(screen.to_string(index=False))

# carry forward: signals with a real right-tail shift AND distinguishable distribution
SCREENED = screen.loc[(screen["p90_shift_z"] > 0.5) & (screen["ks_p"] < 0.10), "signal"].tolist()
print("\nSCREENED -> 6b:", SCREENED)
```

```python
# %% S6a-robust — a fingerprint must not be a single-k artifact. Sweep k; sign must be stable.
for k in (21, 42, 63):
    sub = []
    for name in SCREENED or list(SIGNALS):
        pre = pre_tail_sample(SIGNALS[name], ONSETS, k)
        base = matched_sample(SIGNALS[name], ONSETS, k)
        if len(pre) < 30: 
            continue
        sub.append((name, round((pre.quantile(.9)-base.quantile(.9))/(base.std()+1e-9), 2)))
    print(f"k={k:2d}: " + "  ".join(f"{n}={v}" for n, v in sub))
```

```python
# %% S6a-plot — overlay the conditional vs matched distribution for screened signals (the eyeball).
show = SCREENED[:4] if SCREENED else list(SIGNALS)[:4]
fig, ax = plt.subplots(1, len(show), figsize=(4.2*len(show), 4), squeeze=False)
for j, name in enumerate(show):
    pre = pre_tail_sample(SIGNALS[name], ONSETS, K)
    base = matched_sample(SIGNALS[name], ONSETS, K)
    a = ax[0][j]
    a.hist(base, bins=30, density=True, alpha=.5, label="matched calm", color="grey")
    a.hist(pre, bins=20, density=True, alpha=.6, label="pre-tail (calm-start)", color="firebrick")
    a.axvline(base.quantile(.9), color="grey", ls="--"); a.axvline(pre.quantile(.9), color="firebrick", ls="--")
    a.set_title(name, fontsize=9); a.legend(fontsize=7)
fig.suptitle("S6a — pre-tail vs matched distributions (dashed = 90th pctl). RIGHT-tail shift = signal.")
fig.tight_layout()
```

**Read (S6a is a SCREEN, never a verdict):** a screened signal has a fatter controlled right tail than
matched calm windows — i.e. it tends to be *elevated before its tails, from a calm start*. With only
~6–8 onsets this is low-power and curve-fit-prone; treat the shortlist as **candidates for 6b, not a
finding.** If NOTHING screens (all p90_shift_z ≈ 0 or signs unstable across k), that is itself the
S3b/c result reproduced at the distribution level → likely a 6b FAIL ahead.

---

## S6b — Signal-conditional WALK-FORWARD gate (the verdict)

```python
# %% S6b — anchor on each SCREENED signal FIRING (top-decile, trailing) -> measure forward drawdown OOS.
#   NO pooling across signals. Walk-forward: threshold fit on trailing window, evaluated strictly OOS.
H = 63                                          # forward drawdown horizon (3m)
TRAIN = 252 * 5                                 # 5yr trailing window to set the firing threshold

def fwd_drawdown(px, i, h):
    fut = px.iloc[i: i + h]
    if len(fut) < h: 
        return np.nan
    return fut.min() / fut.iloc[0] - 1.0         # worst peak-to-trough from t (<=0)

px = P["spy"]
if not SCREENED:
    print("S6a screened NOTHING (no signal cleared p90_shift_z>0.5 & ks_p<0.10).")
    print("=> nothing to gate. This IS a Step-6 result: no distributional fingerprint survived the")
    print("   controls => likely FAIL (nothing leads, now at the distribution level). Stop here.")
results = []
for name in (SCREENED or []):
    sig = SIGNALS[name].reindex(px.index).ffill()
    fire_dd, base_dd = [], []
    for i in range(TRAIN, len(px) - H):
        hist = sig.iloc[i - TRAIN: i].dropna()
        if len(hist) < TRAIN // 2 or np.isnan(sig.iloc[i]):
            continue
        thr_fire = hist.quantile(0.90)           # threshold from TRAILING data only (no lookahead)
        dd = fwd_drawdown(px, i, H)
        if np.isnan(dd): 
            continue
        (fire_dd if sig.iloc[i] >= thr_fire else base_dd).append(dd)
    if len(fire_dd) < 20:
        continue
    f_mean, b_mean = np.mean(fire_dd), np.mean(base_dd)
    results.append({"signal": name, "n_fire": len(fire_dd),
                    "fwd_dd_FIRING": round(f_mean, 4), "fwd_dd_base": round(b_mean, 4),
                    "edge": round(f_mean - b_mean, 4)})
gate = pd.DataFrame(results)
if not gate.empty:
    gate = gate.sort_values("edge")              # most negative edge = strongest lead
    print("=== S6b OOS gate: forward drawdown conditional on signal firing vs unconditional base ===")
    print(gate.to_string(index=False))
else:
    print("S6b: no signal produced >=20 firing observations OOS — no gate computed.")
```

```python
# %% S6b-robust — a PASS must hold across >=2 non-overlapping OOS sub-periods + survive the k-look count.
#   (multiple-comparison honesty: with len(SCREENED) signals tested, require consistency, not one win.)
splits = [("2010-01-01","2016-12-31"), ("2017-01-01","2026-06-30")]
for name in (SCREENED or []):
    sig = SIGNALS[name].reindex(px.index).ffill()
    line = [name]
    for a, b in splits:
        sl = px.loc[a:b]; sg = sig.loc[a:b]
        fire, base = [], []
        for i in range(TRAIN, len(sl) - H):
            hist = sg.iloc[max(0,i-TRAIN):i].dropna()
            if len(hist) < 100 or np.isnan(sg.iloc[i]): 
                continue
            dd = fwd_drawdown(sl, i, H)
            if np.isnan(dd): continue
            (fire if sg.iloc[i] >= hist.quantile(.9) else base).append(dd)
        edge = (np.mean(fire) - np.mean(base)) if len(fire) >= 10 else np.nan
        line.append(f"{a[:4]}-{b[:4]}: edge={edge:+.4f}" if not np.isnan(edge) else f"{a[:4]}: n/a")
    print("  ".join(line))
```

**Read — the PASS/FAIL gate (pre-registered, design §3):**
- **PASS:** a screened signal shows materially MORE NEGATIVE forward drawdown *conditional on its own
  firing* than the unconditional base, **OOS**, with the **same-sign edge in BOTH sub-periods**, and the
  edge survives the count of signals tested (consistency, not one lucky threshold). → it earns a
  **Layer-B gate trigger** (a "rate-shock"/"X-shock" rule alongside est_prob), NOT a Layer-A linear
  input (S3e: tail switches must not be diluted).
- **FAIL:** no screened signal's firing predicts worse OOS drawdown, or the edge flips sign across
  sub-periods. → "nothing leads" is confirmed at a HIGHER standard than event-averaged Steps 1–4
  (per-mechanism, distribution-aware, signal-conditional, OOS). The shipped `VIX + est_prob` model is
  vindicated by exhaustion, and the lead question is closed for good.

> **Honesty note:** if 6b PASSES on ONE signal in ONE configuration only, that is the Kritzman pattern
> (in-sample on ~2 events) — downgrade to "directionally real, not robust enough to ship," same verdict
> the ebp signal got. A ship-able PASS must be a *consistent* OOS edge, not a single threshold win.

---

## Artifacts
- Design: `docs/research/regime_model/2026-06-26_step6_per_mechanism_design.md`
- Frozen inputs: `scratch/raw_factor_panel.parquet` + `data/market_data.duckdb` (read-only)
- Map: `docs/research/regime_model/README_regime_research_map.md` (§2 Step 6, §3 metric glossary)
