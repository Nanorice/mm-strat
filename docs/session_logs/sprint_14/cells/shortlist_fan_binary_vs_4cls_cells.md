# §6 — Shortlist equity fan: binary vs 4-class prod (Q3)

Add to `sprint_summary_eda.ipynb` after the §5 fan cells (35–36). These reuse the
validated §5 lottery engine (`basket_paths`) but run it against **two** score caches —
the deployed 4-class prototype and the candidate binary — so the population being
plotted is the **daily shortlisted candidates** (top-N breakouts per day by each
model's `prob_elite`), the exact thing the screener serves.

Prereq: build the 4-class gated cache once (same format as the binary cache the engine
already reads). Run this from a terminal (not the notebook — it's a ~5 min score pass):

```
.venv/Scripts/python.exe scripts/build_prototype_score_cache.py   # writes data/score_cache/m01_prototype_..._sepa_gated.parquet
```

(A throwaway build script was used this session; if you want it kept, promote it to
`scripts/`. Cache path expected below: `data/score_cache/m01_prototype_2003-01-01_2026-05-22_sepa_gated.parquet`.)

---

### CELL A (markdown)

```markdown
### §6 — Shortlist fan: does the binary shortlist beat the 4-class prod shortlist?

§5 fanned the deployed strategy. Here the population is the **daily shortlist itself** —
top-5 genuine breakouts/day ranked by each model's `prob_elite` (4-class = P(class 3, homerun);
binary = P(pos)). Same lottery engine, same SL/horizon, only the *ranker* changes. If the
binary shortlist is better, its fan should sit higher / narrower.
```

### CELL B (code)

```python
# §6 — build the shortlist fan for BOTH models, same engine, only the score cache swapped.
# basket_paths reads a module-level SCORE_CACHE_GATED; we point it at each model's cache
# in turn (monkeypatch the module constant — cheaper than parametrizing the engine).
import importlib
import start_day_basket_paths as bp

CACHES = {
    "binary (candidate)": ROOT / "data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22_sepa_gated.parquet",
    "4-class (prod)":      ROOT / "data/score_cache/m01_prototype_2003-01-01_2026-05-22_sepa_gated.parquet",
}
for label, pth in CACHES.items():
    assert pth.exists(), f"missing cache for {label}: {pth} — build it first (see cells md header)"

FAN_KW = dict(sample_every=5, horizon=150, sl_pct=0.15, use_governor=False, min_score=None)

fans = {}
for label, pth in CACHES.items():
    bp.SCORE_CACHE_GATED = pth          # re-point the engine's cache
    s, p, st = bp.basket_paths(**FAN_KW)
    fans[label] = (s, p, pd.to_datetime(pd.Series(st)))
    print(f"{label:20s}: {s.deployed.sum()} deployed start-days / {len(s)}")
```

### CELL C (code)

```python
# §6 plot — overlay the two shortlist fans (median + 10–90 band), side by side.
# Reuse §5's draw_fan look; add a paired final-return summary so the ranker gap is a number.
def draw_fan(ax, paths, dep, title, color):
    P = (paths[dep] - 1) * 100
    if len(P) == 0: return None
    x = np.arange(P.shape[1])
    for row in P: ax.plot(x, row, color=color, alpha=0.03, lw=0.5)
    ax.plot(x, np.median(P, 0), color="k", lw=2, label="median")
    ax.fill_between(x, np.percentile(P,10,0), np.percentile(P,90,0), color=color, alpha=0.2, label="10–90")
    lo, hi = np.percentile(P, 2), np.percentile(P, 98)
    ax.set_ylim(lo*1.15, hi*1.15)
    fin = P[:, -1]
    ax.set_title(f"{title} (n={dep.sum()})\nfinal median {np.median(fin):+.0f}%  "
                 f"10–90 {np.percentile(fin,10):.0f}..{np.percentile(fin,90):.0f}%  std {fin.std():.0f}%")
    ax.axhline(0, color="k", lw=0.5); ax.set_xlabel("days after start"); ax.legend(fontsize=8)
    return fin

fig, axes = plt.subplots(1, 2, figsize=(15, 5.5), sharey=True)
colors = {"binary (candidate)": "#6aa84f", "4-class (prod)": "#3d85c6"}
finals = {}
for ax, (label, (s, p, st)) in zip(axes, fans.items()):
    finals[label] = draw_fan(ax, p, s.deployed.values, label, colors[label])
axes[0].set_ylabel("shortlist basket return (%)")
fig.suptitle("§6 — Daily-shortlist equity fan: binary (green) vs 4-class prod (blue).\n"
             "Top-5 breakouts/day ranked by each model's prob_elite; same SL/horizon. "
             "Higher/narrower fan = better shortlist ranker.", y=1.04)
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s6_shortlist_fan.png", dpi=110, bbox_inches="tight")
plt.show()
```

### CELL D (code)

```python
# §6 verdict — paired, same start-days: is the binary shortlist's edge real or start-date luck?
# Align on common start-days, then median of the per-start difference (binary − 4cls final return).
b_s, _, b_st = fans["binary (candidate)"]
p_s, _, p_st = fans["4-class (prod)"]
b = b_s.assign(start=b_st.values).set_index("start")["fwd_return"]
p = p_s.assign(start=p_st.values).set_index("start")["fwd_return"]
j = pd.concat({"binary": b, "fourcls": p}, axis=1).dropna()
diff = (j["binary"] - j["fourcls"]) * 100
print(f"common start-days: {len(j)}")
print(f"median final return  — binary {j['binary'].median():+.1%}  4-class {j['fourcls'].median():+.1%}")
print(f"binary − 4cls per-start diff: median {diff.median():+.1f}pp  "
      f"win-rate {(diff>0).mean():.0%}  (binary beats 4cls on this many start-days)")
print(f"loss-rate — binary {(j['binary']<0).mean():.0%}  4-class {(j['fourcls']<0).mean():.0%}")
```

### Rendered output (2026-07-13, sample_every=5, horizon=150, sl=15%, no gov, no score gate)

![shortlist fan binary vs 4-class](../../../../data/model_output_eda/sprint_summary/s6_shortlist_fan.png)

```
binary (candidate)  : 1136 deployed / 1136   final median +3%  10-90 -15..31%  std 24%
4-class (prod)      : 1136 deployed / 1136   final median +3%  10-90 -15..32%  std 26%

=== §6 VERDICT (common start-days: 1136) ===
median final return  — binary +3.2%  4-class +2.9%
binary − 4cls per-start diff: median +0.0pp  win-rate 24%
loss-rate — binary 43%  4-class 44%
```

---

**Reading it — the honest result: on the raw shortlist basket the two are a WASH.**
Median +3.2% vs +2.9%, per-start diff median **+0.0pp**, fans visually near-identical
(binary std 24% vs 4-class 26% — a hair tighter, nothing more). This does NOT contradict
the model-cone verdict (`2026-07-13_4class_vs_binary_cone.md`: binary 0.81 vs 4-class 0.52
median **Sharpe**). It measures a different thing:

- The cone ranks by **Sharpe** after a **per-model threshold sweep** (binary best at thr=0.25).
  Binary's edge is *threshold-dependent and risk-adjusted* — it shows up as a tighter
  return-per-unit-risk once you cut to the high-conviction tail.
- This §6 fan is **threshold-free top-5, raw return**. The two rankers are 96%
  Spearman-correlated on breakouts (Q2), so a threshold-free top-5 basket barely differs.

So the shortlist *population* is nearly the same either way; binary's advantage lives in
**where you cut and how you size**, not in the un-thresholded basket. If you want §6 to
show the cone's edge, add a `min_score` sweep (per-model quantile) — that's the axis the
wash hides. The §5 fan already in the notebook was ALREADY built on the binary cache.

**Caveat (keep in the notebook).** Same vec-engine lottery as §5 — a ranker comparison on
a simple SL/horizon basket, NOT the champion trail-exit. Promote on BackTrader
(`project_vec_engine_optimistic`).

---

## §7 — Score distribution + gate-sweep fan (why the binary gate is a cliff)

### CELL E (markdown)

```markdown
### §7 — What the prob_elite distribution looks like, and what a gate actually does

The binary score is COMPRESSED and PLATEAUED — only ~447 distinct values across 122k rows
(p90≈p95≈0.29, p99≈p99.5≈0.50, then a thin tail to 0.94), whereas the 4-class prob_class_3
is effectively continuous (122k distinct). This is NOT calibration (the scorer ran with no
isotonic calibrator) — it's the BINARY BOOSTER's structure: 100 trees + sigmoid collapses
many breakout rows onto shared leaf-sums → few discrete P(pos) levels. The 4-class model
has 400 trees and a softmax normalization, so its class-3 prob stays smooth. Consequence:
an absolute binary gate is a CLIFF, not a dial — and raising it doesn't lift median return,
it's a RISK knob that costs return.
```

### CELL F (code)

```python
# §7a — prob_elite distribution on the breakout pool, both models (full history caches).
B = pd.read_parquet(ROOT/"data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22_sepa_gated.parquet")
Pc = pd.read_parquet(ROOT/"data/score_cache/m01_prototype_2003-01-01_2026-05-22_sepa_gated.parquet")
qs = [.50,.75,.90,.95,.975,.99,.995,.999,1.0]
dist = pd.DataFrame({"binary": B.prob_elite.quantile(qs).values,
                     "4class": Pc.prob_elite.quantile(qs).values},
                    index=[f"p{q*100:g}" for q in qs]).round(3)
print(dist.to_string())
# survival: what fraction of breakouts clears each absolute gate
gates = [0.0,0.10,0.15,0.20,0.25,0.30]
surv = pd.DataFrame({"binary %kept": [(B.prob_elite>=g).mean()*100 for g in gates],
                     "4class %kept": [(Pc.prob_elite>=g).mean()*100 for g in gates]},
                    index=[f">={g:.2f}" for g in gates]).round(1)
print("\n", surv.to_string())
assert B.prob_elite.quantile(.90) == B.prob_elite.quantile(.95), "expected a binary plateau at p90-p95"
```

### CELL G (code)

```python
# §7b — gate-sweep equity fan. Re-run basket_paths at several min_score floors PER MODEL,
# overlay the median paths + show the final-return distribution shift. min_score is the
# built-in quality gate (Q11) — names below the floor are dropped BEFORE the top-5 pick.
import start_day_basket_paths as bp
GATES = [None, 0.10, 0.15, 0.20, 0.25]
KW = dict(sample_every=5, horizon=150, sl_pct=0.15, use_governor=False)
CMAP = plt.cm.viridis(np.linspace(0.15, 0.9, len(GATES)))
lab = lambda g: "no gate" if g is None else f">={g:.2f}"
CACHES = {"binary": ROOT/"data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22_sepa_gated.parquet",
          "4-class": ROOT/"data/score_cache/m01_prototype_2003-01-01_2026-05-22_sepa_gated.parquet"}

res = {}
for model, pth in CACHES.items():
    bp.SCORE_CACHE_GATED = pth
    for g in GATES:
        s, p, _ = bp.basket_paths(min_score=g, **KW)
        P = (p[s.deployed.values] - 1) * 100
        res[(model, g)] = (P[:, -1], np.median(P, 0), int(s.deployed.sum()))
        print(f"{model:8s} {lab(g):8s}: n={s.deployed.sum():4d}  median {np.median(P[:,-1]):+.1f}%  "
              f"loss {(P[:,-1]<0).mean()*100:.0f}%")

fig, axes = plt.subplots(2, 2, figsize=(15, 9))
for r, model in enumerate(CACHES):
    axm, axv = axes[r,0], axes[r,1]; x = np.arange(KW["horizon"]+1)
    for c, g in enumerate(GATES):
        fin, med, n = res[(model, g)]
        axm.plot(x, med, color=CMAP[c], lw=2, label=f"{lab(g)} (n={n})")
    axm.axhline(0, color="k", lw=0.5); axm.legend(fontsize=8)
    axm.set_title(f"{model} — median path by gate"); axm.set_xlabel("days"); axm.set_ylabel("return (%)")
    parts = axv.violinplot([res[(model,g)][0] for g in GATES], showmedians=True, widths=0.8)
    for c, bdy in enumerate(parts["bodies"]): bdy.set_facecolor(CMAP[c]); bdy.set_alpha(0.6)
    axv.axhline(0, color="k", lw=0.5); axv.set_xticks(range(1,len(GATES)+1))
    axv.set_xticklabels([lab(g) for g in GATES], fontsize=8)
    axv.set_title(f"{model} — final-return dist by gate"); axv.set_ylabel("return (%)")
fig.suptitle("§7 — Gate-sweep fan: raising prob_elite is a RISK knob, not a return knob.\n"
             "Binary median cracks negative by >=0.20 (plateau cliff); 4-class drifts down smoothly. "
             "Neither gains median return.", y=1.02)
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s7_gate_sweep_fan.png", dpi=110, bbox_inches="tight")
plt.show()
```

### Rendered output (2026-07-13)

```
        binary  4class
p50      0.115   0.239
p90      0.289   0.510
p95      0.289   0.577     <- binary p90==p95: a PLATEAU
p99      0.500   0.665
p99.5    0.500   0.691     <- another plateau at 0.500
p100     0.936   0.810

          binary %kept  4class %kept
>=0.10          55.3         87.2
>=0.20          22.0         59.3     <- binary loses 60% of rows here
>=0.30           3.8         37.2     <- binary near-empty; one notch past 0.25

binary   no gate : n=1136  median +3.2%  loss 43%
binary   >=0.20  : n= 976  median -0.3%  loss 50%    <- median goes NEGATIVE
binary   >=0.25  : n= 936  median -1.5%  loss 51%
4-class  no gate : n=1136  median +2.9%  loss 44%
4-class  >=0.25  : n=1101  median +2.3%  loss 45%     <- drifts down, never cracks
```

![gate sweep fan](../../../../data/model_output_eda/sprint_summary/s7_gate_sweep_fan.png)

---

**Reading it.**
1. **The binary distribution is plateaued** — ~447 distinct P(pos) levels (100-tree
   binary booster + sigmoid; NOT calibration): p90==p95==0.29, p99==p99.5==0.50. So an
   *absolute* binary gate is a cliff — `>=0.25` keeps 18.7% of rows, `>=0.30` only 3.8%,
   `>=0.35` and `>=0.45` select the IDENTICAL rows (no level between 0.29 and 0.50), and
   `>=0.20` already empties ~15% of days. You cannot dial a binary gate the way you dial
   the smooth 4-class one. **Gate binary by per-day rank (top-N) or per-day percentile,
   never an absolute floor.** Note (memory correction): the plateaus mean there is NO
   smooth score hiding under the band to re-rank on — the model genuinely assigns those
   rows one probability. For finer separation use a secondary key (RS, mcap), not a
   de-calibrated score.
2. **Raising the gate does NOT lift median return — it lowers it.** Binary median goes
   *negative* at `>=0.20` (−0.3%) and loss-rate climbs to 50%; 4-class drifts down
   monotonically. The violins barely shift — you don't concentrate winners, you lose count.
3. **No contradiction with the model cone** (binary best at thr=0.25, Sharpe 0.81): the
   cone ranks by **Sharpe**, this fan by **raw return**. The gate is a **risk/variance
   knob** — it tightens the floor and lifts Sharpe by dropping wide low-conviction names,
   at the cost of median return and coverage. Exactly memory
   `project_prob_elite_gate_variance_knob`, now visible on the return distribution.

**Takeaway for deployment:** don't gate the shortlist to "improve returns" — you'd bleed
median and starve days. If you want binary's Sharpe edge, express it as top-N per day (the
shortlist already does) and let sizing/exit do the risk control, not a hard score floor.

**What `n` means (asked):** `n` (= `n_baskets`) is the number of **start-days that
deployed a basket**, NOT the number of trades. The engine samples one basket every 5
trading days (`sample_every=5`); each basket = the top-5 breakouts that day. So `n=1136` =
1,136 sampled entry-points over 2003–2026. A gate lowers `n` only when a start-day has zero
names clearing the floor (empty day → no basket). It is coverage, not trade count.

**How to read the right-hand violins (asked):** each violin is the **full distribution of
final (150-day) basket returns** across all `n` baskets at that gate — width = density
(fat where many baskets landed), the horizontal tick = the median. Reading them: as the
gate rises the body squeezes toward −15% (the stop) while a thin upper tail stretches — the
distribution goes bimodal ("stop-out or moonshot"). That's the variance knob made visible:
you're not shifting the body up, you're trading a broad slightly-positive spread for a
narrow high-variance lottery.

---

## §7b — Higher gates + a toggle cell (pick one gate, see its FULL fan)

### CELL H (code) — higher-gate sweep, both models

```python
# §7b — push gates HIGHER (0.15/0.25/0.35/0.45). Relabeled: n_baskets, "median = fan center".
import start_day_basket_paths as bp
GATES = [None, 0.15, 0.25, 0.35, 0.45]
KW = dict(sample_every=5, horizon=150, sl_pct=0.15, use_governor=False)
CMAP = plt.cm.viridis(np.linspace(0.15, 0.9, len(GATES)))
lab = lambda g: "no gate" if g is None else f">={g:.2f}"
CACHES = {"binary": ROOT/"data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22_sepa_gated.parquet",
          "4-class": ROOT/"data/score_cache/m01_prototype_2003-01-01_2026-05-22_sepa_gated.parquet"}
res = {}
for model, pth in CACHES.items():
    bp.SCORE_CACHE_GATED = pth
    for g in GATES:
        s, p, _ = bp.basket_paths(min_score=g, **KW)
        P = (p[s.deployed.values] - 1) * 100
        res[(model, g)] = (P[:, -1], np.median(P, 0), int(s.deployed.sum()))

fig, axes = plt.subplots(2, 2, figsize=(15, 9))
for r, model in enumerate(CACHES):
    axm, axv = axes[r, 0], axes[r, 1]; x = np.arange(KW["horizon"]+1)
    for c, g in enumerate(GATES):
        fin, med, n = res[(model, g)]
        axm.plot(x, med, color=CMAP[c], lw=2, label=f"{lab(g)} (n_baskets={n})")
    axm.axhline(0, color="k", lw=0.5); axm.legend(fontsize=8, title="score gate")
    axm.set_title(f"{model} — MEDIAN of the equity fan, per gate")
    axm.set_xlabel("days after entry"); axm.set_ylabel("basket return (%)")
    parts = axv.violinplot([res[(model,g)][0] for g in GATES], showmedians=True, widths=0.85)
    for c, b in enumerate(parts["bodies"]): b.set_facecolor(CMAP[c]); b.set_alpha(0.6)
    axv.axhline(0, color="k", lw=0.5); axv.set_xticks(range(1, len(GATES)+1))
    axv.set_xticklabels([lab(g) for g in GATES], fontsize=8); axv.set_ylim(-40, 120)
    axv.set_title(f"{model} — FINAL (150d) return: full distribution"); axv.set_ylabel("return (%)")
fig.suptitle("§7b — Higher-gate sweep. Left: median line = fan CENTER. Right: violin = FULL spread.\n"
             "Both models: raising the gate erodes median; binary cracks hard past its plateaus "
             "(>=0.35 and >=0.45 = identical rows).", y=1.03)
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s7b_gate_sweep_hi.png", dpi=110, bbox_inches="tight")
plt.show()
```

### CELL I (code) — TOGGLE: pick one model + gate, draw its full equity fan

```python
# §7b toggle — set these two, re-run to see the WHOLE fan (all paths + median + 10–90 band)
# for that single (model, gate) — not just the median line.
MODEL = "binary"      # "binary" | "4-class"
GATE  = 0.15          # None for no gate, else e.g. 0.15 / 0.25 / 0.35

bp.SCORE_CACHE_GATED = CACHES[MODEL]
s, p, st = bp.basket_paths(min_score=GATE, sample_every=5, horizon=150, sl_pct=0.15, use_governor=False)
P = (p[s.deployed.values] - 1) * 100
x = np.arange(P.shape[1]); fin = P[:, -1]

fig, ax = plt.subplots(figsize=(11, 6))
for row in P: ax.plot(x, row, color="#3d85c6", alpha=0.03, lw=0.5)   # every basket path
ax.plot(x, np.median(P, 0), color="k", lw=2.5, label="median")
ax.fill_between(x, np.percentile(P,10,0), np.percentile(P,90,0), color="#3d85c6", alpha=0.2, label="10–90 band")
ax.fill_between(x, np.percentile(P,25,0), np.percentile(P,75,0), color="#3d85c6", alpha=0.3, label="25–75 band")
ax.axhline(0, color="k", lw=0.5)
lo, hi = np.percentile(P, 1), np.percentile(P, 99); ax.set_ylim(lo*1.1, hi*1.1)
gate_lbl = "no gate" if GATE is None else f"prob_elite>={GATE}"
ax.set_title(f"§7b — FULL equity fan · {MODEL} · {gate_lbl}\n"
             f"n_baskets={len(P)}  final median {np.median(fin):+.1f}%  "
             f"10–90 {np.percentile(fin,10):.0f}..{np.percentile(fin,90):.0f}%  loss {(fin<0).mean()*100:.0f}%")
ax.set_xlabel("days after entry"); ax.set_ylabel("basket return (%)"); ax.legend()
plt.tight_layout(); plt.show()
```

### Rendered output (§7b sweep)

```
binary   no gate : n_baskets=1136  median +3.2%  p10..p90 -15..31%  loss 43%
binary   >=0.15  : n_baskets=1094  median +2.6%  p10..p90 -15..34%  loss 44%
binary   >=0.25  : n_baskets= 936  median -1.5%  p10..p90 -15..43%  loss 51%
binary   >=0.35  : n_baskets= 137  median -15.0%  p10..p90 -15..107%  loss 59%   <- plateau: same rows as >=0.45
binary   >=0.45  : n_baskets= 136  median -15.0%  p10..p90 -15..107%  loss 59%
4-class  no gate : n_baskets=1136  median +2.9%  p10..p90 -15..32%  loss 44%
4-class  >=0.25  : n_baskets=1101  median +2.3%  p10..p90 -15..35%  loss 45%
4-class  >=0.35  : n_baskets=1039  median +0.1%  p10..p90 -15..38%  loss 49%
4-class  >=0.45  : n_baskets= 868  median -4.0%  p10..p90 -15..44%  loss 55%     <- smooth decay, no cliff
```

![gate sweep higher](../../../../data/model_output_eda/sprint_summary/s7b_gate_sweep_hi.png)

**Reading it.** Higher gates confirm §7 and expose the cliff: binary `>=0.35`/`>=0.45`
return the *identical* 136–137 baskets (there's no score level between 0.29 and 0.50), and
that tiny survivor pool is a −15%-floor / +107%-tail lottery — you've filtered the shortlist
down to almost nothing but a fat tail. 4-class decays smoothly (2.9 → 0.1 → −4.0). Same
verdict: the gate destroys median return and coverage; it only ever buys variance/Sharpe.

---

## §8 — Attribute breakdown (which slice of the shortlist carries the edge)

Uses `docs/session_logs/sprint_14/scripts/breakdown_basket_fan.py` — a thin wrapper that
reuses the §5 per-name path, joins each entry-day's sector/industry/market_cap
(company_profiles) + RS rank (t3), buckets them, and fans each slice.

### CELL J (code)

```python
import sys; sys.path.insert(0, str(ROOT / "docs/session_logs/sprint_14/scripts"))
from breakdown_basket_fan import enrich, load_prices, basket_fan, fan_stats

sc = enrich(pd.read_parquet(ROOT/"data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22_sepa_gated.parquet"))
by = load_prices(sc["ticker"].unique().tolist())
FKW = dict(top_n=5, horizon=150, sl_pct=0.15, sample_every=5)

ATTRS = {"sector": None,
         "mcap_bucket": ["micro","small","mid","large","mega"],
         "rs_band": ["rs20-40","rs40-60","rs60-80","rs80-100"]}
fig, axes = plt.subplots(1, 3, figsize=(19, 5.5))
for ax, (attr, order) in zip(axes, ATTRS.items()):
    levels = order or sc[attr].value_counts().head(8).index.tolist()
    cmap = plt.cm.turbo(np.linspace(0.1, 0.9, len(levels)))
    for c, lv in enumerate(levels):
        sub = sc[sc[attr] == lv]
        if len(sub) < 200: continue
        P, fin = basket_fan(sub, by, **FKW); st = fan_stats(fin)
        if st["n"] < 20: continue
        ax.plot(np.arange(FKW["horizon"]+1), np.median((P-1)*100, 0), color=cmap[c], lw=2,
                label=f"{lv} (n={st['n']}, med {st['median']:+.0f}%)")
    ax.axhline(0, color="k", lw=0.5); ax.legend(fontsize=7, title=attr)
    ax.set_title(f"binary shortlist — median fan by {attr}")
    ax.set_xlabel("days after entry"); ax.set_ylabel("basket return (%)")
fig.suptitle("§8 — Which slice of the daily top-5 carries the edge?", y=1.03)
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s8_breakdown_fan.png", dpi=110, bbox_inches="tight")
plt.show()
assert sc["mcap_bucket"].nunique() >= 4, "mcap buckets collapsed — check qcut"
```

### Rendered output

```
sector       Industrials +3.0% · Real Estate +3.1% (best) | Healthcare -0.5% · Energy -1.8% (worst) · Tech +0.7%
mcap_bucket  MONOTONE: micro -3.8% (loss 57%) → small +1.5 → mid +3.5 → large +4.9 → mega +6.8% (loss 34%)
rs_band      rs20-40 +6.3% (n=104) · rs40-60 +2.9 · rs60-80 +3.7 · rs80-100 +2.4% (NOT monotone on median)
```

![breakdown fan](../../../../data/model_output_eda/sprint_summary/s8_breakdown_fan.png)

**Reading it — and a real tension worth flagging.**
- **Market cap is the cleanest axis and it's MONOTONE THE "WRONG" WAY on median:** bigger =
  higher median, lower loss (mega +6.8%/34% loss vs micro −3.8%/57% loss). This looks like
  it contradicts the sprint's small-cap thesis (`project_r1b_step2_subsumed`:
  smallcap-T1 = 2.4–3.2×). It does NOT, but the distinction matters: that thesis was about
  **home-run RATE (the tail)** — small-caps have fatter right tails. This is **median basket
  return** — small-caps have a worse *center* and stop out more. The current shortlist
  composite up-weights small-cap; on a median/Sharpe basis that TILT is a drag. **Decide
  which objective the shortlist serves** (tail-odds vs median) — they point opposite ways on
  size.
- **Sector:** Industrials / Real Estate lead; Healthcare / Energy lag; Tech is middling
  despite the most names. A coarse sector triage (bury Energy/Healthcare) is a cheap add.
- **RS band:** not monotone on median (rs20-40 best, but n=104 — thin). rs80-100 (the
  deployed high-RS thesis) is only +2.4% on median — again a tail-vs-median split.

**Caveat.** Same vec-lottery / simple-exit engine as §5–§7 (`project_vec_engine_optimistic`);
median-return breakdown, not the champion trail-exit. Directional, not a promotion.

---

## §9 — UNCLIPPED gate sweep (drop top-N; the gate alone defines the population)

The §7/§7b sweeps entangle TWO filters: the score gate AND the top-5 selection. To isolate
the **scoring** question, drop the clip: `top_n=None` → the basket holds EVERY name clearing
the gate that day (100 names if 100 clear it), equal-weighted. Now raising the gate tests
whether higher-score *populations* have better forward returns — not whether the score
*ranks within* a pool. (`basket_paths`/`basket_fan` now default-support `top_n=None`.)
Also adds a higher/denser gate ladder for 4-class (its score is near-continuous).

### CELL K (code) — unclipped sweep, per-model gate ladders

```python
import start_day_basket_paths as bp
CACHES = {"binary": ROOT/"data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22_sepa_gated.parquet",
          "4-class": ROOT/"data/score_cache/m01_prototype_2003-01-01_2026-05-22_sepa_gated.parquet"}
GATES = {"binary":  [None, 0.15, 0.25, 0.35],
         "4-class": [None, 0.25, 0.40, 0.50, 0.60, 0.70]}   # denser + higher (dense score)
KW = dict(sample_every=5, horizon=150, sl_pct=0.15, use_governor=False, top_n=None)  # NO CLIP
lab = lambda g: "no gate" if g is None else f">={g:.2f}"
res = {}
for model, pth in CACHES.items():
    bp.SCORE_CACHE_GATED = pth
    for g in GATES[model]:
        s, p, _ = bp.basket_paths(min_score=g, **KW)
        P = (p[s.deployed.values]-1)*100
        res[(model, g)] = (P[:,-1], np.median(P,0), int(s.deployed.sum()))
        print(f"{model:8s} {lab(g):8s}: n={s.deployed.sum():4d} median {np.median(P[:,-1]):+.1f}% "
              f"skew {pd.Series(P[:,-1]).skew():+.2f} loss {(P[:,-1]<0).mean()*100:.0f}%")

fig, axes = plt.subplots(2, 2, figsize=(15, 9))
for r, model in enumerate(CACHES):
    gts = GATES[model]; cmap = plt.cm.viridis(np.linspace(0.12, 0.9, len(gts)))
    axm, axv = axes[r,0], axes[r,1]; x = np.arange(151)
    for c, g in enumerate(gts):
        fin, med, n = res[(model, g)]
        axm.plot(x, med, color=cmap[c], lw=2, label=f"{lab(g)} (n={n})")
    axm.axhline(0, color="k", lw=0.5); axm.legend(fontsize=8, title="score gate")
    axm.set_title(f"{model} — UNCLIPPED (all survivors) median fan, per gate")
    axm.set_xlabel("days after entry"); axm.set_ylabel("basket return (%)")
    parts = axv.violinplot([res[(model,g)][0] for g in gts], showmedians=True, widths=0.85)
    for c, b in enumerate(parts["bodies"]): b.set_facecolor(cmap[c]); b.set_alpha(0.6)
    axv.axhline(0, color="k", lw=0.5); axv.set_xticks(range(1,len(gts)+1))
    axv.set_xticklabels([lab(g) for g in gts], fontsize=8); axv.set_ylim(-40, 120)
    axv.set_title(f"{model} — final-return distribution (UNCLIPPED)"); axv.set_ylabel("return (%)")
fig.suptitle("§9 — UNCLIPPED gate sweep (top_n=None). Gate alone defines the population.", y=1.02)
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s9_gate_sweep_unclipped.png", dpi=110, bbox_inches="tight")
plt.show()
```

### CELL L (code) — #3: does dropping the clip symmetrize the downside?

```python
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
GATE_CMP = {"binary": 0.15, "4-class": 0.40}
for ax, model in zip(axes, CACHES):
    bp.SCORE_CACHE_GATED = CACHES[model]; g = GATE_CMP[model]; fins = {}
    for tag, tn in [("unclipped (all)", None), ("top-5", 5)]:
        s, p, _ = bp.basket_paths(min_score=g, sample_every=5, horizon=150, sl_pct=0.15,
                                  use_governor=False, top_n=tn)
        fins[tag] = (p[s.deployed.values][:,-1]-1)*100
    for tag, col in [("unclipped (all)","#6aa84f"), ("top-5","#cc0000")]:
        f = fins[tag]
        ax.hist(f, bins=60, alpha=0.5, density=True, color=col,
                label=f"{tag}: med {np.median(f):+.0f}% skew {pd.Series(f).skew():+.2f}")
        ax.axvline(np.median(f), color=col, ls="--", lw=1.5)
    ax.axvline(0, color="k", lw=0.7); ax.set_xlim(-40, 120)
    ax.set_title(f"{model} @ gate>={g}: clipped vs unclipped"); ax.legend(fontsize=8)
    ax.set_xlabel("final basket return (%)"); ax.set_ylabel("density")
fig.suptitle("§9 (#3) — removing the top-5 clip: does the downside symmetrize?", y=1.02)
plt.tight_layout()
plt.savefig(ROOT/"data/model_output_eda/sprint_summary/s9b_clip_vs_unclip.png", dpi=110, bbox_inches="tight")
plt.show()
```

### Rendered output

```
binary   no gate : n=1136 median +4.3%  p10..p90 -12..22%  skew +2.52  loss 36%
binary   >=0.15  : n=1094 median +4.2%  p10..p90 -15..31%  skew +2.26  loss 39%
binary   >=0.25  : n= 936 median +0.0%  p10..p90 -15..43%  skew +2.95  loss 50%
binary   >=0.35  : n= 137 median -15.0% p10..p90 -15..107% skew +4.34  loss 57%
4-class  no gate : n=1136 median +4.3%  p10..p90 -12..22%  skew +2.52  loss 36%
4-class  >=0.25  : n=1101 median +4.1%  p10..p90 -15..31%  skew +1.99  loss 39%
4-class  >=0.40  : n= 977 median +0.1%  p10..p90 -15..41%  skew +3.69  loss 50%
4-class  >=0.50  : n= 721 median -7.5%  p10..p90 -15..44%  skew +4.24  loss 58%
4-class  >=0.60  : n= 332 median -15.0% p10..p90 -15..57%  skew +5.48  loss 64%
4-class  >=0.70  : n=  51 median -15.0% p10..p90 -15..105% skew +4.14  loss 65%
```

![unclipped gate sweep](../../../../data/model_output_eda/sprint_summary/s9_gate_sweep_unclipped.png)

![clip vs unclip](../../../../data/model_output_eda/sprint_summary/s9b_clip_vs_unclip.png)

**Reading it — three findings, all sharper once selection is removed.**

1. **The top-5 clip HURTS the median. Holding all survivors beats holding the 5
   highest-score names** (no-gate: unclipped median **+4.3%**, band −12..22% vs the clipped
   top-5's +3.2%, −15..31% from §6). So within the gated breakout pool the score's ranking
   is *anti-informative on median* — top-5-by-score is worse than a coin-toss over the pool.
   Direct confirmation of `project_breakout_pool_refinement` (model IC ≈ −0.03 within the
   gated pool). **The gate is where the model earns its keep; the within-pool rank isn't.**

2. **Raising the gate lowers median for BOTH models — now that selection is out, it's a
   clean monotone decay** (4-class: +4.3 → +4.1 → +0.1 → −7.5 → −15). The gate does NOT
   select better-forward-return populations; it shrinks count and pushes mass to the −15%
   stop. Binary hits its plateau cliff (>=0.35 = 137 names); 4-class decays smoothly through
   the denser ladder. Same verdict as §7, now un-entangled from the clip.

3. **#3 answered — higher gate = lower median AND fatter/more-skewed right tail** (skew
   climbs +2.5 → +4.3 binary, +2.0 → +5.5 4-class). The violin's upper taper thickens
   exactly as you saw. And the clip question: **the downside is NOT symmetric either way** —
   both clipped and unclipped pile up hard at the −15% stop (that's the SL flooring the left
   tail by construction, not the score). Removing the clip only *mildly* helps — shifts a
   little mass out of the −15% spike into the small-positive body (median +4% vs +3% binary,
   +0% vs −1% 4-class) and lowers skew a touch. The stop makes a symmetric left tail
   impossible; the asymmetry is a design feature of the exit, not the ranker.

**Deployment implication (matters).** If the shortlist's job is median/Sharpe, the model's
value is the GATE (which names are breakouts worth scoring), not the within-pool RANK — so a
top-N-by-score shortlist is the wrong shape; a broad gated basket (or a rank on a *different*
axis like mcap/sector from §8) does better. If the job is tail-odds, the high-score tail is
where the skew concentrates — but you pay median and coverage for it. Same objective fork as
§8. Still the vec/simple-exit engine — promote on BackTrader.
