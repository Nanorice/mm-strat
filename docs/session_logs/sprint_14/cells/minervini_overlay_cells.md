# From lottery → governor → Minervini overlay: the full chain to "the engine is next"

> **What this replicates (the reasoning chain, for review):** across this session we established, step
> by step, why the current strategy is a lottery and what actually fixes it. This file runs the chain
> end-to-end with inline charts:
> 1. **The strategy is a start-day LOTTERY** — top-5 on day-0, held to horizon; outcome dominated by
>    *when* you start (`start_day_lottery_cells.md`).
> 2. **The governor trims the WRONG tail** — at the single-basket level it does NOT protect the
>    downside (−15% floor untouched, losing% ~unchanged); it clips the UPSIDE (max +823%→+202%). Its
>    real DD value is a *compounding* effect across consecutive bear baskets, invisible to one basket.
> 3. **VCP is already in the model** — `prob_elite` trains on `vcp_ratio`/`breakout_momentum`/etc., so
>    re-weighting by VCP double-counts. Only the pivot TRIGGER EVENT is non-redundant.
> 4. **The Minervini overlay (pivot-trigger + progressive add-on + tight stop) is a NULL in this lens**
>    — worse median/losing% than the naive basket — BUT the win/loss payoff ratio DOUBLES (2.85→6.18).
>    The asymmetry is real; the forward-return lens just can't harvest it (no trailing-stop-to-breakeven,
>    no intraday adds).
>
> **Conclusion → next session:** the honest, capital-artifact-free lens has done its job. The remaining
> Minervini edge (trailing stop to breakeven + progressive fills) lives in mechanics this lens lacks →
> it must go in the **backtest engine** (`vectorized_backtest.py`). That's task (a) for next session.
>
> Engine: `docs/session_logs/sprint_14/scripts/start_day_basket_paths.py`
> (`basket_paths`, `basket_paths_minervini`). Directional basket study, NOT the shared-pool backtest.
> cf `project_entry_timing_macro_axis` (governor reassessed), `project_champion_starttime_dependent`.

Paste each block as one cell.

---

### Cell 0 — repo-root bootstrap (run FIRST)

```python
%load_ext autoreload
%autoreload 2

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
from start_day_basket_paths import basket_paths, basket_paths_minervini
print("ROOT:", ROOT)
```

### Cell 1 — build the three arms (baseline, governor, Minervini)

```python
# sample_every=7 (~weekly start-days): good density/speed. ~3-5 min total.
base = basket_paths(sample_every=7, horizon=150, sl_pct=0.15, use_governor=False)[0]
gov  = basket_paths(sample_every=7, horizon=150, sl_pct=0.15, use_governor=True)[0]
minv = basket_paths_minervini(sample_every=7, horizon=150, sl_pct=0.07,
                              vol_mult=1.4, add_pct=0.10, add_day=10, use_governor=False)[0]
b, g, m = base[base.deployed], gov[gov.deployed], minv[minv.deployed]

def _stats(x):
    r = x.fwd_return; win = r[r > 0].mean(); loss = r[r < 0].mean()
    return dict(n=len(x), mean=r.mean(), median=r.median(), std=r.std(),
                losing=(r < 0).mean(), payoff=abs(win / loss), max=r.max())

tbl = pd.DataFrame({"baseline (all-top5, 15%)": _stats(b),
                    "+ governor gate": _stats(g),
                    "Minervini (trig+prog, 7%)": _stats(m)}).T
for c in ["mean", "median", "std", "losing", "max"]:
    tbl[c] = (tbl[c] * 100).round(1).astype(str) + "%"
tbl["payoff"] = tbl["payoff"].round(2)
tbl
```

### Cell 2 — Step 1&2: the lottery, and the governor trims the WRONG tail (INLINE)

```python
fig, ax = plt.subplots(figsize=(11, 5))
bins = np.linspace(-20, 120, 60)
ax.hist(b.fwd_return * 100, bins=bins, color="#888", alpha=0.55,
        label=f"baseline (median {b.fwd_return.median():+.0%}, max {b.fwd_return.max():+.0%})")
ax.hist(g.fwd_return * 100, bins=bins, color="#3d85c6", alpha=0.6,
        label=f"+ governor (median {g.fwd_return.median():+.0%}, max {g.fwd_return.max():+.0%})")
ax.axvline(0, color="k", lw=0.7); ax.axvline(-15, color="#cc0000", ls=":", lw=1, label="-15% floor")
ax.set_xlabel("basket 150d fwd return (%)"); ax.set_ylabel("# start-days")
ax.set_title("Step 1&2 — a LOTTERY, and the governor clips the UPSIDE not the downside\n"
             f"floor(-15%) days: {(b.fwd_return<=-0.149).mean():.0%} -> {(g.fwd_return<=-0.149).mean():.0%} "
             f"(unchanged) · but max {b.fwd_return.max():+.0%} -> {g.fwd_return.max():+.0%} (tail kneecapped)")
ax.legend()
plt.tight_layout(); plt.show()

# By-percentile: prove the trim is upper-tail, not downside.
qs = [0.05, 0.10, 0.25, 0.50, 0.90, 0.95]
print("percentile   baseline   governor    delta")
for q in qs:
    bq, gq = b.fwd_return.quantile(q), g.fwd_return.quantile(q)
    print(f"  p{int(q*100):02d}      {bq:+7.1%}   {gq:+7.1%}   {gq-bq:+.1%}")
assert abs(b.fwd_return.quantile(0.10) - g.fwd_return.quantile(0.10)) < 0.005, "downside should be ~identical"
```

> **Read it:** p05/p10 identical (the −15% floor is untouched — the governor does NOT stop losing
> baskets), while p90/p95 drop and the max is clipped. The governor's real drawdown value is a
> *compounding* effect across consecutive bear baskets (up to 51 in a row) — invisible to a single
> independent basket, which can only lose 15%.

### Cell 3 — Step 4: the Minervini overlay is a NULL here — but the payoff ratio DOUBLES (INLINE)

```python
fig, ax = plt.subplots(figsize=(11, 5))
bins = np.linspace(-25, 120, 60)
ax.hist(b.fwd_return * 100, bins=bins, color="#3d85c6", alpha=0.55,
        label=f"baseline all-top5,15%  (median {b.fwd_return.median():+.0%}, win/loss {_stats(b)['payoff']:.2f})")
ax.hist(m.fwd_return * 100, bins=bins, color="#e69138", alpha=0.55,
        label=f"Minervini trig+prog+7%  (median {m.fwd_return.median():+.0%}, win/loss {_stats(m)['payoff']:.2f})")
ax.axvline(0, color="k", lw=0.7)
ax.set_xlabel("basket 150d fwd return (%)"); ax.set_ylabel("# start-days")
ax.set_title("Step 4 — pivot-trigger + tight stop: WORSE median/losing%, LOWER max,\n"
             "but the win/loss payoff ratio DOUBLES (2.85 -> 6.18) = the asymmetry is real")
ax.legend(fontsize=9)
plt.tight_layout(); plt.show()
assert _stats(m)["payoff"] > _stats(b)["payoff"], "Minervini should raise the payoff ratio"
assert m.fwd_return.median() < b.fwd_return.median(), "but its median is worse in this lens (the null)"
```

> **Read it — the honest null:** buying exactly at the pivot with a tight 7% stop whipsaws most names
> out (63% losing), so the median is worse than the naive basket. The trigger is ~a double-count (the
> model already scores breakout names high → it just subsets to the most-EXTENDED = most whipsaw-prone
> names). The one real signal is the **payoff ratio doubling** — the tight-stop asymmetry exists, but a
> FIXED-HOLD basket can't harvest it (no trailing stop to breakeven, no intraday adds).

### Cell 4 — WHY the payoff signal can't be harvested here: the stop-sweep (INLINE + saved)

```python
sls = [0.05, 0.06, 0.08, 0.10, 0.15, 0.20]
rows = []
for sl in sls:
    x = basket_paths(sample_every=10, horizon=150, sl_pct=sl, use_governor=False)[0]
    x = x[x.deployed]; r = x.fwd_return
    rows.append(dict(sl=sl, mean=r.mean(), median=r.median(),
                     payoff=abs(r[r > 0].mean() / r[r < 0].mean())))
sweep = pd.DataFrame(rows)

fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5))
a1.plot(sweep.sl * 100, sweep.payoff, marker="o", color="#0b5394", lw=2)
a1.set_xlabel("stop-loss %"); a1.set_ylabel("win/loss payoff ratio")
a1.set_title("Tighter stop DOUBLES the payoff ratio (Minervini's core edge)")
a1.axhline(1, color="k", lw=0.6, ls=":"); a1.grid(alpha=0.3)
a2.plot(sweep.sl * 100, sweep["mean"] * 100, marker="o", label="mean", color="#3d85c6")
a2.plot(sweep.sl * 100, sweep["median"] * 100, marker="s", label="median", color="#e69138")
a2.set_xlabel("stop-loss %"); a2.set_ylabel("return (%)")
a2.set_title("...but on a FIXED-HOLD basket, mean/median FALL with a tighter stop\n(whipsaw) -> the asymmetry needs the ENGINE to harvest")
a2.axhline(0, color="k", lw=0.6); a2.legend(); a2.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(ROOT / "data/model_output_eda/regime_weight/minervini_conclusion.png", dpi=110, bbox_inches="tight")
plt.show()
assert sweep.payoff.iloc[0] > sweep.payoff.iloc[-1], "tighter stop should raise payoff ratio"
```

![minervini conclusion — payoff vs stop, and the whipsaw cost](../../../../data/model_output_eda/regime_weight/minervini_conclusion.png)

> **Read it:** LEFT — a 5% stop gives a 5.26:1 payoff vs 2.85:1 at 15% (Minervini's "cut losses tiny").
> RIGHT — yet on a fixed-hold basket the mean AND median FALL as the stop tightens (you get whipsawed
> out before the move develops). **These two panels together are the whole conclusion:** the asymmetry
> Minervini exploits is real and measurable, but harvesting it needs a **trailing stop to breakeven +
> progressive intraday adds** — mechanics the forward-return basket lacks and the backtest engine has.

## Conclusion

The forward-return lottery lens has done its job — it cleanly separated what helps from what doesn't:
- The strategy **is** a start-day lottery (huge fan, ~40% of start-days lose at the −15% floor).
- The **governor** is a weak fix here: it trims the upside, not the downside (its DD value is a
  compounding effect only a real book shows).
- **VCP** is already in the model — don't re-weight it; only the pivot **trigger event** is new
  information, and even that is largely redundant (the model scores breakout names high already).
- The **Minervini overlay is a null in this lens** — worse median, but a doubled win/loss payoff ratio
  that proves the asymmetry is there to harvest.

**→ Next session, task (a):** port the highest-leverage Minervini mechanic — a **trailing stop that
moves to breakeven once the trade works** (plus, later, progressive intraday adds) — into
`vectorized_backtest.py`, then re-test whether it converts the doubled payoff ratio into a real
edge that tightens the start-day distribution *without* kneecapping the tail. That is the piece the
forward-return lens structurally cannot show.
