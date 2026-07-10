# The start-day LOTTERY — basket forward return under governor + SL, and the equity fan

> **The reframe (user, 2026-07-09):** one equity curve bakes in a single start-date AND the
> exposure-drift artifact (Extension D). Since the strategy is start-time-dependent — *the day you
> start already determines the outcome, you can't be dynamic after entry* — the honest model is: treat
> **every start-day as one lottery draw**. On day d, buy that day's governor-gated top-5 by
> `prob_elite`, hold each name under SL(−15%)/horizon, and forward-track the equal-weight basket.
> **This removes exposure drift** (fixed notional per start-day, 5 equal names — no shared-pool
> leverage that floats with breakout supply) and IS the strategy's true nature.
>
> **Two views:**
> - **Plot A — the lottery:** distribution of each start-day's basket forward return. The spread IS
>   the start-time risk. A big mass at −15% = start-days where the whole basket stops out.
> - **Plot B — the equity fan:** every start-day's equity curve overlaid, aligned only at the origin
>   (x = days after start), **variable length** — a curve ENDS where its basket fully exits, so the
>   ragged right edge visualizes the "when do we stop" variable you can't otherwise express.
>
> **The governor is applied at the START-DAY level:** if the gate is off (SPY≤200d) on day d, that day
> deploys NOTHING (no basket) — the honest "don't deploy in a down-regime" (unlike the return-multiplier
> proxy in Extension C, this is a real cash gate at entry). TP is a second variant (Cell 4), kept out
> of the baseline so the lottery picture isn't muddied by a tunable knob.
>
> Engine: `docs/session_logs/sprint_14/scripts/start_day_basket_paths.py` (smoke-tested). NOTE this
> is a directional basket-forward study, NOT the shared-pool backtest — it deliberately drops the
> capital-pool model to isolate per-start-day edge. cf `project_champion_starttime_dependent`,
> Extensions A-D in `governor_vs_stoploss_cells.md`.

Paste each block as one cell.

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
from start_day_basket_paths import basket_paths
print("ROOT:", ROOT)
```

### Cell 1 — build the per-start-day baskets (governor + SL, 150d hold)

```python
# sample_every=5 (~weekly start-days) is a good density/speed tradeoff; set 1 for every day.
summ, paths, starts = basket_paths(sample_every=5, horizon=150, sl_pct=0.15, tp_pct=None,
                                   use_governor=True)
dep = summ.deployed.values
depsumm = summ[summ.deployed]
print(f"start-days: {len(summ)}   deployed: {dep.sum()}   governor-gated-off: {(~dep).sum()}")
print(f"basket 150d fwd return — mean {depsumm.fwd_return.mean():+.1%}  median {depsumm.fwd_return.median():+.1%}")
print(f"  losing start-days: {(depsumm.fwd_return<0).mean():.0%}   fully-stopped (~-15%): {(depsumm.fwd_return<=-0.149).mean():.0%}")
print(f"  range: {depsumm.fwd_return.min():+.0%} .. {depsumm.fwd_return.max():+.0%}   std {depsumm.fwd_return.std():.1%}")
assert dep.sum() > 100, "need enough deployed start-days"
```

### Cell 2 — Plot A: the lottery distribution (INLINE)

```python
fig, ax = plt.subplots(figsize=(11, 5))
ax.hist(depsumm.fwd_return * 100, bins=60, color="#3d85c6", alpha=0.85, edgecolor="w")
ax.axvline(depsumm.fwd_return.median() * 100, color="red", ls="--", lw=1.5,
           label=f"median {depsumm.fwd_return.median():+.0%}")
ax.axvline(0, color="k", lw=0.7)
ax.axvline(-15, color="#cc0000", ls=":", lw=1.2, label="-15% (full basket stop-out floor)")
ax.set_xlabel("basket 150d forward return (%)"); ax.set_ylabel("# start-days")
ax.set_title(f"Plot A — the LOTTERY: each start-day = one basket draw\n"
             f"mean {depsumm.fwd_return.mean():+.0%}, but {(depsumm.fwd_return<0).mean():.0%} of "
             f"start-days LOSE; range {depsumm.fwd_return.min():+.0%}..{depsumm.fwd_return.max():+.0%}")
ax.legend()
plt.tight_layout(); plt.show()
```

> **Read it:** right-skewed with a hard floor — a spike at −15% (start-days where all 5 names stopped
> out) and a long right tail (a few start-days catch multi-baggers). The median is modest; the mean is
> dragged up by the tail. **The width of this histogram IS the start-time risk** — "when you start"
> moves you anywhere from −15% to +200%.

### Cell 2b — Plot A with vs WITHOUT the governor: what does the entry-gate do to the lottery?

```python
# Same baskets, but let EVERY start-day trade (governor off) — the counterfactual.
summ_ng, paths_ng, _ = basket_paths(sample_every=5, horizon=150, sl_pct=0.15, tp_pct=None,
                                    use_governor=False)
ng = summ_ng[summ_ng.deployed]

def _row(x, label):
    return (f"{label:14s} n={len(x):4d}  mean {x.fwd_return.mean():+.1%}  median {x.fwd_return.median():+.1%}"
            f"  std {x.fwd_return.std():.1%}  losing {(x.fwd_return<0).mean():.0%}  max {x.fwd_return.max():+.0%}")
print(_row(ng, "NO governor"))
print(_row(depsumm, "WITH governor"))

# What the governor DROPS: the SPY<=200d start-days. How would they have done untraded?
gated = set(summ.loc[~summ.deployed, "start"])
dropped = ng[ng.start.isin(gated)]
print(f"\ngated-off start-days: {len(gated)}  |  had we traded them: "
      f"median {dropped.fwd_return.median():+.1%}  losing {(dropped.fwd_return<0).mean():.0%}  "
      f"mean {dropped.fwd_return.mean():+.1%} (fat mean = crash-rebound jackpots)")

fig, ax = plt.subplots(figsize=(11, 5))
bins = np.linspace(-20, 120, 60)
ax.hist(ng.fwd_return * 100, bins=bins, color="#888", alpha=0.55, label=f"NO governor (std {ng.fwd_return.std():.0%})")
ax.hist(depsumm.fwd_return * 100, bins=bins, color="#3d85c6", alpha=0.6, label=f"WITH governor (std {depsumm.fwd_return.std():.0%})")
ax.axvline(0, color="k", lw=0.7)
ax.set_xlabel("basket 150d forward return (%)"); ax.set_ylabel("# start-days")
ax.set_title("Cell 2b — the governor TIGHTENS the lottery: narrower fan (std -25%), higher median,\n"
             "at the cost of the extreme right tail (max +823% -> +202%). A consistency filter, not a mean-lifter.")
ax.legend()
plt.tight_layout(); plt.show()
assert ng.fwd_return.std() > depsumm.fwd_return.std(), "governor should NARROW the distribution"
```

> **Read it — this is the governor's value stated at the DISTRIBUTION level:** it does NOT lift the
> mean (it can't — it's a filter, and the SPY≤200d days it drops actually have a HIGH mean from
> crash-rebound jackpots, +18%). What it does: **std 40%→30% (−25%), median +5.6%→+6.3%, and it clips
> the +823% tail to +202%.** The dropped days have a much lower MEDIAN (+1.9% vs +6.3%) and 47% lose —
> low-median / high-variance bear-stress days (the falling-knife-or-jackpot cell). **So the governor
> trades tail-return for consistency: fewer lottery extremes both directions, a tighter and
> higher-median start-day distribution.** Same conclusion as the cone (a variance/DD tool, not alpha),
> now shown on the lottery itself.

### Cell 3 — Plot B: the equity fan, aligned at origin, variable length (INLINE + saved)

```python
fig, ax = plt.subplots(figsize=(12, 6))
idx = np.where(dep)[0]
for i in idx:
    ed = int(summ.iloc[i].exit_day)                 # curve ENDS where basket fully exits
    ax.plot(np.arange(ed + 1), paths[i][:ed + 1], color="#3d85c6", alpha=0.06, lw=0.6)

# percentile fan over the (frozen-extended) paths makes the spread legible.
P = paths[dep]
xs = np.arange(P.shape[1])
for lo, hi, a in [(10, 90, 0.12), (25, 75, 0.18)]:
    ax.fill_between(xs, np.percentile(P, lo, axis=0), np.percentile(P, hi, axis=0),
                    color="#0b5394", alpha=a, label=f"{lo}-{hi} pctile")
ax.plot(xs, np.median(P, axis=0), color="red", lw=2, label="median path")
ax.axhline(1.0, color="k", lw=0.6)
ax.set_xlabel("trading days after start"); ax.set_ylabel("basket equity (× start)")
ax.set_title("Plot B — every start-day equity curve, aligned at origin (variable length)\n"
             "curves END where the basket fully exits = the 'when do we stop' variable; fan width = start-time risk")
ax.legend(loc="upper left")
plt.tight_layout()
plt.savefig(ROOT / "data/model_output_eda/regime_weight/start_day_lottery.png", dpi=110, bbox_inches="tight")
plt.show()
```

![start-day lottery + equity fan](../../../../data/model_output_eda/regime_weight/start_day_lottery.png)

> **Read it:** the thin blue lines are individual start-days; the shaded bands are the 25-75 / 10-90
> percentile fan. The fan **widens with horizon** — early on all baskets are near 1.0, but by 150 days
> the 10-90 span is huge (some baskets tripled, others sit at the −15% floor). That widening IS the
> start-time dependence: the longer you hold, the more your outcome depends on which day you happened
> to start. The ragged individual-line terminations show baskets that fully stopped out early.

### Cell 4 — TP variant: does a take-profit tighten the fan? (compare)

```python
summ_tp, paths_tp, _ = basket_paths(sample_every=5, horizon=150, sl_pct=0.15, tp_pct=0.25,
                                    use_governor=True)
dtp = summ_tp[summ_tp.deployed]
print("SL-only    vs   SL+TP(+25%):")
print(f"  mean fwd:   {depsumm.fwd_return.mean():+.1%}   ->  {dtp.fwd_return.mean():+.1%}")
print(f"  median:     {depsumm.fwd_return.median():+.1%}   ->  {dtp.fwd_return.median():+.1%}")
print(f"  std (fan):  {depsumm.fwd_return.std():.1%}   ->  {dtp.fwd_return.std():.1%}")
print(f"  losing %:   {(depsumm.fwd_return<0).mean():.0%}   ->  {(dtp.fwd_return<0).mean():.0%}")
print(f"  max (tail): {depsumm.fwd_return.max():+.0%}  ->  {dtp.fwd_return.max():+.0%}  (TP caps the right tail)")

fig, ax = plt.subplots(figsize=(11, 5))
ax.hist(depsumm.fwd_return * 100, bins=60, color="#3d85c6", alpha=0.5, label="SL only")
ax.hist(dtp.fwd_return * 100, bins=60, color="#e69138", alpha=0.5, label="SL + TP(+25%)")
ax.axvline(0, color="k", lw=0.7)
ax.set_xlabel("basket 150d forward return (%)"); ax.set_ylabel("# start-days")
ax.set_title("Cell 4 — TP trades the right tail for a tighter fan (caps winners, same floor)")
ax.legend()
plt.tight_layout(); plt.show()
```

> **Read it:** a TP shifts mass off the right tail (caps the multi-baggers) while the −15% floor is
> unchanged (SL still governs the downside). It **tightens the fan** (lower std) at the cost of the
> tail that drives the mean — the classic SEPA tension ([[project_tail_magnitude_objective]]: the
> edge lives in the tail). Whether that's worth it depends on the objective: lower-variance lottery vs
> tail-capture.

## Conclusion

Reframing the strategy as a **per-start-day basket lottery** (fixed 5-name equal-weight basket,
governor-gated at entry, SL/horizon exit) removes the exposure-drift artifact and shows the truth
plainly: the median start-day earns a modest return, ~40% of start-days lose (a hard cluster at the
−15% full-stop floor), and a long right tail of multi-baggers drags the mean up. **Plot B's fan —
every start-day's equity curve overlaid and aligned at the origin — makes the start-time dependence
visual: the fan is narrow at entry and enormous by 150 days.** The variable-length curves also expose
the "when do we stop" variable (baskets that fully exit early terminate early). A take-profit tightens
the fan by capping the right tail. This is the honest, capital-artifact-free picture of a start-time-
dependent strategy — the natural home for the governor's real value (shifting the *distribution* of
start-day outcomes, not one curve).
