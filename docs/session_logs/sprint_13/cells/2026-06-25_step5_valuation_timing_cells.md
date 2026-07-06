# Step 5 — Strategic Valuation Timing: the one untested avenue — intended cells (2026-06-25)

> Steps 1–4 closed the **TACTICAL** question: nothing leads equity *tails* on this universe (levels
> coincident, GZ credit weak/crisis-only, Absorption Ratio falsified). Shipped: **VIX (sizing) +
> est_prob gate (crisis)**. The findings doc explicitly parks ONE different avenue (lines 486–509):
> **STRATEGIC valuation timing** at a **long horizon** — does an *expensive* market predict *lower
> long-run returns*? Different signal (valuation, not stress), different horizon (years, not days),
> different target (long-run return, not imminent tail).
> Findings doc: `docs/research/regime_model/2026-06-24_regime_eda_findings.md`.
>
> **The literature anchor — Asness, Ilmanen & Maloney (2017), "Market Timing: Sin a Little":**
> valuation DOES carry timing info, but the edge is **small and slow**; naive all-in contrarian timing
> historically underperformed because it *fights trend*. The resolution: a *small* valuation tilt,
> combined with momentum, adds modest value. "Sin a little," not a lot.
>
> **The pre-committed bar (so this can't be talked into a yes):** valuation earns a place ONLY if it
> shows a **monotone, economically meaningful** relationship between starting valuation and *long-run*
> (≥3y, ideally 10y) forward real return — AND that relationship must survive the obvious objection
> that it's just "buy after crashes." If the signal only works by being long after −50% drawdowns
> (i.e. it's momentum in disguise), it adds nothing over what we have. It must add value at a SLOW
> horizon where the tactical model is silent. A weak-but-real, trend-combined tilt is a PASS; a fast
> alarm or a crash-timer is not the claim and not the test.
>
> **Data — `scratch/valuation_panel.parquet` (sourced 2026-06-25, `scratch_source_valuation.py`):**
> monthly **1881-01 → 2026-06**, spliced Shiller (Yale ≤2023-08) + multpl (≥2023-09), validated
> identical on overlap. Symbols: `cape`, `earnings_yield`(=1/CAPE), `erp_cape`(=E/P−GS10),
> `dividend_yield`, `long_rate_gs10`, `sp_price`. Self-contained — **no DB needed.** Today: CAPE 40.9,
> erp_cape −2.05% (deeply expensive; near-record).

---

## V0 — Load the valuation panel, build forward real returns

```python
# %% V0 — load panel (wide), construct nominal & total-return forward returns.
import numpy as np, pandas as pd
from pathlib import Path
import matplotlib.pyplot as plt
def _repo_root() -> Path:
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError(f"repo root not found above {p}")

ROOT = _repo_root()
long = pd.read_parquet(ROOT / "scratch" / "valuation_panel.parquet")
df = long.pivot(index="date", columns="symbol", values="value").sort_index()
df.index = pd.to_datetime(df.index)
print("panel:", df.shape, df.index.min().date(), "->", df.index.max().date())
print(df.tail(3).round(4))

# Total-return proxy: price return + accrued dividend yield (monthly div_yield/12, ffilled).
# Real: deflate by long-run? We keep NOMINAL price-return for the core test and add a TR variant.
ret_m = df["sp_price"].pct_change()
dy_m  = (df["dividend_yield"].ffill() / 12.0)
tr_m  = ret_m + dy_m                                  # monthly total return (approx)

def fwd_annualized(tr_monthly: pd.Series, years: int) -> pd.Series:
    h = years * 12
    growth = (1.0 + tr_monthly).rolling(h).apply(np.prod, raw=True).shift(-h)
    return growth ** (1.0 / years) - 1.0              # annualized forward TR over `years`

for y in (1, 3, 5, 10):
    df[f"fwd_tr_{y}y"] = fwd_annualized(tr_m, y)
print("\nfwd return coverage (non-null):",
      {f"{y}y": int(df[f'fwd_tr_{y}y'].notna().sum()) for y in (1,3,5,10)})
```

**Expected:** ~1746 monthly rows 1881→2026; CAPE today ~41. Forward-TR columns drop the last `h`
months (no future) — that's correct, not a bug.

---

## V1 — The core test: does starting valuation predict long-run forward return?

```python
# %% V1 — Spearman corr of each valuation signal vs forward annualized TR, by horizon.
# negative corr (expensive -> low fwd return) = the valuation-timing claim.
from scipy.stats import spearmanr
signals = ["cape", "earnings_yield", "erp_cape"]   # EY & ERP are inverse of CAPE in sign
rows = []
for sig in signals:
    for y in (1, 3, 5, 10):
        sub = df[[sig, f"fwd_tr_{y}y"]].dropna()
        rho, p = spearmanr(sub[sig], sub[f"fwd_tr_{y}y"])
        rows.append({"signal": sig, "horizon": f"{y}y", "spearman": round(rho, 3),
                     "n": len(sub), "p": f"{p:.1e}"})
res = pd.DataFrame(rows)
print(res.pivot(index="signal", columns="horizon", values="spearman").to_string())
print("\n(cape: expect NEGATIVE & strengthening with horizon; EY/erp_cape: POSITIVE mirror)")
```

**Pre-committed read:** the literature says CAPE↔fwd-return should be **negative and STRENGTHEN with
horizon** (weak at 1y, strong by 10y — the opposite shape of the tactical stress signals, which were
strong at days and zero at months). `earnings_yield` / `erp_cape` are the inverse, so positive. If 10y
|rho| is small (<~0.3) OR doesn't strengthen with horizon, the strategic claim is as weak as the
tactical one and we say so.

---

## V2 — Is it real predictability, or just "buy after crashes"? (the decisive control)

```python
# %% V2 — the momentum-confound test. Asness's whole point: naive valuation timing
# fights trend. Split by whether the market is ABOVE/BELOW trend (12m price MA),
# and re-measure valuation's edge WITHIN each trend regime. If valuation only "works"
# when also below trend, it's crash-rebound (momentum), not a standalone valuation edge.
ma12 = df["sp_price"].rolling(12).mean()
above_trend = df["sp_price"] > ma12
for y in (10,):
    for label, mask in [("ABOVE trend", above_trend), ("BELOW trend", ~above_trend)]:
        sub = df.loc[mask, ["cape", f"fwd_tr_{y}y"]].dropna()
        rho, p = spearmanr(sub["cape"], sub[f"fwd_tr_{y}y"])
        print(f"{y}y | {label:12s}: cape rho={rho:+.3f}  n={len(sub)}  p={p:.1e}")
# Bonus: decile table of CAPE vs mean fwd 10y TR — is it MONOTONE or a cliff (like §A11)?
d = df[["cape", "fwd_tr_10y"]].dropna().copy()
d["cape_decile"] = pd.qcut(d["cape"], 10, labels=False)
print("\nCAPE decile -> mean fwd 10y annualized TR:")
print(d.groupby("cape_decile")["fwd_tr_10y"].agg(["mean", "count"]).round(4).to_string())
```

**Pre-committed read:** a *genuine* valuation edge survives in BOTH trend regimes (expensive predicts
low fwd return whether or not we're above trend). If the negative corr only appears BELOW trend, it's
the crash-rebound confound — which is momentum, which we already have, so valuation adds nothing new.
The decile table separately tells us SHAPE: a clean monotone gradient (each richer decile → lower fwd
return) is the strategic-timing dream; a flat-then-cliff (only the top CAPE decile is bad) is the same
"tail switch" shape every prior factor showed — usable only as a gate, not a continuous tilt.

---

## V3 — "Sin a little": does a SMALL valuation tilt + trend beat buy-and-hold?

```python
# %% V3 — the Asness construction, faithfully. Small valuation tilt, momentum-aware,
# vs buy-and-hold. NOT all-in timing. Allocation in [0,1] to equities (rest = long rate).
# tilt = mild contrarian on CAPE z-score, SCALED DOWN ("sin a little"), gated by trend.
cape_z = (df["cape"] - df["cape"].rolling(120, min_periods=60).mean()) \
         / df["cape"].rolling(120, min_periods=60).std()
val_tilt = (-cape_z).clip(-1, 1)                      # cheap -> +, expensive -> -
SIN = 0.20                                            # "a little": +/-20% around 100% equity
w_sinlittle = (1.0 + SIN * val_tilt).clip(0, 1)
w_sinlittle = w_sinlittle.where(above_trend, w_sinlittle * 0.5)   # de-risk below trend (trend-aware)
w_buyhold = pd.Series(1.0, index=df.index)
w_sinlot  = (1.0 + 1.0 * val_tilt).clip(0, 1)         # all-in contrarian, for contrast

def backtest(w):
    w = w.shift(1)                                     # trade on prior month's signal (no lookahead)
    cash = (1 - w) * (df["long_rate_gs10"].ffill() / 12.0)
    port = w * tr_m + cash
    eq = (1 + port.dropna()).cumprod()
    ann = eq.iloc[-1] ** (12 / len(eq)) - 1
    vol = port.std() * np.sqrt(12)
    sharpe = (port.mean() * 12) / vol
    return ann, vol, sharpe, eq

for name, w in [("buy&hold", w_buyhold), ("sin-a-little", w_sinlittle), ("sin-a-lot", w_sinlot)]:
    ann, vol, sh, _ = backtest(w)
    print(f"{name:14s}  ann={ann:6.2%}  vol={vol:6.2%}  Sharpe={sh:5.2f}")
```

**Pre-committed read — this is the actual decision:**
- **PASS (valuation earns a slow overlay):** `sin-a-little` Sharpe > `buy&hold`, AND `sin-a-lot`
  Sharpe < `buy&hold` (confirming the "fights trend / sin a lot fails" mechanism). That's the exact
  Asness result reproduced on our data → a *small, trend-aware* valuation tilt is worth wiring as a
  strategic allocation overlay (separate from the tactical VIX/est_prob model).
- **FAIL (drop it):** `sin-a-little` ≤ `buy&hold` after the V2 momentum control → valuation timing
  doesn't survive on our construction either; record it as the SECOND timing avenue tested and
  rejected, and the "no usable timing signal" conclusion becomes total (tactical AND strategic).

---

## V4 — Robustness (only if V1–V3 lean PASS)

```python
# %% V4 — don't ship a PASS that's one lookback / one SIN-size / one era.
# (a) SIN sweep, (b) tilt lookback sweep, (c) drop the post-2009 bull (the era that
# most punishes contrarian valuation) and re-check sign of the edge.
results = []
for SIN in (0.10, 0.20, 0.33, 0.50):
    w = (1.0 + SIN * val_tilt).clip(0, 1).where(above_trend, (1.0 + SIN*val_tilt).clip(0,1)*0.5)
    ann, vol, sh, _ = backtest(w)
    results.append({"SIN": SIN, "Sharpe": round(sh, 3), "ann": f"{ann:.2%}"})
print(pd.DataFrame(results).to_string(index=False))
# era robustness: pre-2009 vs full, V1 corr again
for lo in ("1881-01-01", "1950-01-01", "1990-01-01"):
    sub = df.loc[lo:, ["cape", "fwd_tr_10y"]].dropna()
    rho, _ = spearmanr(sub["cape"], sub["fwd_tr_10y"])
    print(f"cape vs fwd10y, from {lo[:4]}: rho={rho:+.3f}  n={len(sub)}")
```

**Read:** a PASS must hold across SIN ∈ [0.1, 0.33] and across eras (sign stable, even if magnitude
fades post-1990 as CAPE drifted structurally higher). If the edge only exists pre-1950 or only at one
SIN, it's fragile → downgrade to "directionally real, not robust enough to ship," same verdict as ebp.

---

## What this step decides (to be filled after the run)

| Question | Answer | Evidence |
|---|---|---|
| Does expensive valuation predict low LONG-run return? | TBD | V1 (10y Spearman) |
| Real edge, or just buy-after-crash (momentum)? | TBD | V2 (within-trend corr) |
| Monotone tilt or top-decile cliff? | TBD | V2 (decile table) |
| Does "sin a little" beat buy&hold; does "sin a lot" fail? | TBD | V3 |
| Robust across SIN size and era? | TBD | V4 |
| **VERDICT: ship a slow valuation overlay, or reject?** | TBD | — |

> Whatever the verdict, it closes the LAST open avenue the regime investigation named. PASS → one
> small, slow, trend-aware strategic overlay, explicitly separate from the tactical VIX+est_prob
> model. FAIL → "no usable timing signal on this universe, tactical OR strategic," fully tested.
