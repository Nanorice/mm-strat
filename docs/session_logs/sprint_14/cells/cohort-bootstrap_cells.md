# Cohort bootstrap — is the top-5 pick better than a random draw from the gated tie-pool?

> **Question (sprint 13, problem #5):** the champion gates by `prob_elite ≥ 0.15` then takes
> `top_n=5` ranked by `prob_elite`. But `prob_elite` is coarse — on 55/57 entry days *every*
> picked name shares one identical value, so the top-5 is a **random draw from a tie-pool**.
> If the pick's forward return is indistinguishable from random 5-draws of that pool, the model
> is a **pure gate with no cross-sectional skill** → widening the basket (or equal-weighting all
> survivors) removes the selection bias for free. If the pick beats the pool, there's latent
> ranking skill worth extracting.
>
> Uses existing sweep artifacts (`trades.parquet` = picked, `rejections.parquet` reason
> `no_slots` = gated-but-unslotted). Forward returns from `price_data` — **no backtest re-run**.
>
> **Two tie-pool definitions, reported side by side** (they disagree on the smoke test — the
> definition is load-bearing):
> - `exact` — null draws only from names at the *exact* picked tie score. True interchangeables;
>   isolates pure selection skill.
> - `min` — null draws from all `no_slots` names scored ≥ the lowest picked score. Bigger pool,
>   more days, but mixes in the score gradient so "edge" conflates ranking-within-tie with gating.
>
> **Regenerating the sweep (if artifacts are stale):** `.venv/Scripts/python.exe
> scripts/run_starttime_sweep.py` (prod code) rewrites `data/selection_sweep/starttime/...`.
> This notebook's own outputs are saved to `data/cohort_bootstrap/` (see Cell 5).

Paste each block below as one cell.

---

### Cell 1 — setup + pool loader (parametrised by tie-pool definition)

```python
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import duckdb

def _repo_root() -> Path:
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError(f"repo root not found above {p}")

ROOT = _repo_root()
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "market_data.duckdb"
SWEEP_ROOT = ROOT / "data" / "selection_sweep" / "starttime" / "champion" / "rolling"

CELL = "r_202101_h12"        # one start window; loop later for a real verdict
HOLD_DAYS = 20               # forward window to score each candidate (≈ median hold)
TIE_TOL = 1e-6

def load_pool(cell: str, tie_mode: str) -> pd.DataFrame:
    """Per entry-day gated pool: picked + same-day no_slots rejections.
    tie_mode='exact' → only names at the exact picked tie score (interchangeables).
    tie_mode='min'   → all no_slots names scored >= the lowest picked score."""
    d = SWEEP_ROOT / cell
    picks = pd.read_parquet(d / "trades.parquet")[["ticker", "entry_date", "normalized_score"]].copy()
    picks["entry_date"] = pd.to_datetime(picks["entry_date"])
    picks["picked"] = True

    rej = pd.read_parquet(d / "rejections.parquet")
    rej = rej[rej["reason"] == "no_slots"][["date", "ticker", "score"]].copy()
    rej = rej.rename(columns={"date": "entry_date", "score": "normalized_score"})
    rej["entry_date"] = pd.to_datetime(rej["entry_date"])
    rej["picked"] = False

    pool = pd.concat([picks, rej], ignore_index=True)
    if tie_mode == "exact":
        # tie score = the max picked score that day; draw pool = names AT that score
        top = picks.groupby("entry_date")["normalized_score"].max().rename("tie_score")
        pool = pool.merge(top, on="entry_date", how="left")
        pool = pool[(pool["normalized_score"] - pool["tie_score"]).abs() <= TIE_TOL].copy()
    elif tie_mode == "min":
        floor = picks.groupby("entry_date")["normalized_score"].min().rename("tie_floor")
        pool = pool.merge(floor, on="entry_date", how="left")
        pool = pool[pool["normalized_score"] >= pool["tie_floor"] - TIE_TOL].copy()
    else:
        raise ValueError(tie_mode)
    return pool.drop_duplicates(["entry_date", "ticker"])

for mode in ("exact", "min"):
    p = load_pool(CELL, mode)
    print(f"[{mode}] {p['entry_date'].nunique()} days, {len(p)} rows, {int(p['picked'].sum())} picked")
```

---

### Cell 2 — forward-return scorer (shared by both modes)

```python
def score_fwd(pool: pd.DataFrame) -> pd.DataFrame:
    """Attach HOLD_DAYS fwd return from close (adj_close is 100% NULL — never use it)."""
    tickers = tuple(sorted(pool["ticker"].unique()))
    lo = (pool["entry_date"].min() - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    hi = (pool["entry_date"].max() + pd.Timedelta(days=HOLD_DAYS * 3 + 10)).strftime("%Y-%m-%d")
    con = duckdb.connect(str(DB), read_only=True)     # read_only — kernel must not lock the DB
    px = con.execute("""
        SELECT ticker, date, close FROM price_data
        WHERE ticker IN {tk} AND date BETWEEN ? AND ? ORDER BY ticker, date
    """.format(tk=tickers), [lo, hi]).df()
    con.close()
    px["date"] = pd.to_datetime(px["date"])
    pxg = {t: g.set_index("date")["close"] for t, g in px.groupby("ticker")}

    def fwd(row) -> float:
        p = pxg.get(row["ticker"])
        if p is None:
            return np.nan
        p = p[p.index >= row["entry_date"]]
        if len(p) <= HOLD_DAYS or p.iloc[0] == 0:
            return np.nan
        return p.iloc[HOLD_DAYS] / p.iloc[0] - 1.0

    out = pool.copy()
    out["fwd_ret"] = out.apply(fwd, axis=1)
    return out.dropna(subset=["fwd_ret"])
```

---

### Cell 3 — bootstrap, run for both tie modes

```python
def bootstrap(pool: pd.DataFrame, n_boot: int = 5000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for d, grp in pool.groupby("entry_date"):
        picked = grp[grp["picked"]]
        if len(picked) == 0 or len(grp) <= len(picked):
            continue                                  # no alternatives to draw from
        k = len(picked)
        actual = picked["fwd_ret"].mean()
        uni = grp["fwd_ret"].to_numpy()
        draws = np.array([rng.choice(uni, k, replace=False).mean() for _ in range(n_boot)])
        rows.append({"entry_date": d, "pool_n": len(grp), "k": k, "actual_mean": actual,
                     "null_mean": draws.mean(), "null_p10": np.percentile(draws, 10),
                     "null_p90": np.percentile(draws, 90),
                     "pick_percentile": (draws < actual).mean()})
    return pd.DataFrame(rows)

results = {}
for mode in ("exact", "min"):
    scored = score_fwd(load_pool(CELL, mode))
    res = bootstrap(scored)
    results[mode] = res
    edge = res["actual_mean"] - res["null_mean"]
    print(f"[{mode}] {len(res)} days | edge {edge.mean():+.4f} (med {edge.median():+.4f}) | "
          f"pick_pctile {res['pick_percentile'].mean():.3f} (0.5=random) | "
          f"beat-null {(res['pick_percentile'] > 0.5).mean():.1%}")
```

---

### Cell 4 — visual: both modes side by side

```python
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 2, figsize=(16, 9))
for j, mode in enumerate(("exact", "min")):
    res = results[mode].sort_values("entry_date")
    ax1, ax2 = axes[0, j], axes[1, j]
    ax1.fill_between(res["entry_date"], res["null_p10"], res["null_p90"], alpha=0.25,
                     color="grey", label="random-draw 10–90%")
    ax1.plot(res["entry_date"], res["null_mean"], color="grey", lw=1, label="null mean")
    ax1.scatter(res["entry_date"], res["actual_mean"],
                c=np.where(res["actual_mean"] > res["null_mean"], "#2e7d32", "#c62828"),
                s=40, zorder=3, label="actual pick")
    ax1.axhline(0, color="black", lw=0.6)
    ax1.set_title(f"[{mode}] pick vs random-draw null"); ax1.set_ylabel(f"{HOLD_DAYS}d fwd ret")
    ax1.legend(fontsize=7)
    ax2.hist(res["pick_percentile"], bins=20, color="#1f77b4", alpha=0.7, edgecolor="white")
    ax2.axvline(0.5, color="red", ls="--", label="random")
    ax2.axvline(res["pick_percentile"].mean(), color="black", lw=2,
                label=f"mean {res['pick_percentile'].mean():.2f}")
    ax2.set_title(f"[{mode}] pick percentile in null"); ax2.set_xlabel("percentile")
    ax2.legend(fontsize=7)
fig.suptitle(f"{CELL}: top-5 pick vs random tie-pool draw — exact vs min tie pool",
             fontweight="bold")
plt.tight_layout(); plt.show()
```

---

### Cell 5 — save results

```python
OUT = ROOT / "data" / "cohort_bootstrap"
OUT.mkdir(parents=True, exist_ok=True)
for mode, res in results.items():
    res.to_parquet(OUT / f"{CELL}_{mode}_hold{HOLD_DAYS}.parquet", index=False)
summary = pd.DataFrame([{
    "cell": CELL, "tie_mode": mode, "hold_days": HOLD_DAYS, "n_days": len(res),
    "edge_mean": (res["actual_mean"] - res["null_mean"]).mean(),
    "pick_pctile_mean": res["pick_percentile"].mean(),
    "beat_null_frac": (res["pick_percentile"] > 0.5).mean(),
} for mode, res in results.items()])
summary.to_csv(OUT / f"{CELL}_summary.csv", index=False)
print(f"💾 saved to {OUT}")
print(summary.round(4).to_string(index=False))
```

---

### Cell 6 (markdown) — Read

```markdown
### Read

- **`exact` mode is the honest selection-bias test** (draws only from true tie-interchangeables).
  If `exact` pick_percentile ≈ 0.50 and edge ≈ 0 → the top-5 is a **random draw**; the model
  gates but does not rank. **Fix = hold the whole gated survivor set (or 15–20), not 5** — no
  selection means no selection bias.
- **`min` will look more favourable** because it includes lower-scored names → any positive gap
  there is the *score gradient* (gating), not tie-breaking skill. If `min` shows edge but `exact`
  does not → confirms the ranker adds nothing beyond the gate.
- **If `exact` pick_percentile > 0.6** → real latent cross-sectional skill; extract a proper
  within-cohort ranker (finer prob_elite, or RS-momentum) instead of widening the basket.
- **Smoke-test caveat:** one start window ≈ 36 usable days is underpowered. Loop all 53 cells
  (or the seed best/worst months) before any verdict — see the day-shift seed study.
- **Not tested here:** rotation/rescue (#5b). Only worth it if `exact` shows no selection skill
  *and* a separate within-cohort momentum-persistence test is positive.
```
