# Verdict: M1 — re-cut "home-runs captured/missed" by MAGNITUDE, not binary >30% count

**Date:** 2026-07-07 · **Status:** ✅ re-analysis, now validated across **25 regimes (2001–2025)**
**Answers:** meta-question **M1** (RESEARCH_LOG). Re-cuts Q7's flawed binary miss-rate + regime-tests it.
**Data:** 2025 baseline `data/model_output_eda/raw_full_2025_fwd.parquet`; multi-year cache
`data/model_output_eda/multiyear/raw_full_{2001..2025}_fwd.parquet` (full universe scored per year
via `score_from_t3`, RAW p_pos). Scripts: `scripts/m1_tail_magnitude_recut.py` (single-year),
`scripts/score_universe_multiyear.py` (resumable sweep toolkit), `scripts/m1_multiyear_analysis.py`
(cross-regime). **See "Multi-year (M1 across 25 regimes)" below — the 6.1× is a good-regime number.**

> **Why M1 exists:** Q7 measured "how many home-runs do we miss?" as a binary count of `fwd>30%`
> events. That treats a +35% and a +400% as identical — but the strategy's alpha IS the fat tail.
> The gate/ranker decisions M2–M5 all inherit this metric, so it had to be re-cut first.
> New objective: `tail = Σ max(fwd − 30%, 0)` (magnitude above the home-run line) and
> **rank-of-top-1%** (does the score concentrate the tail?).

## Finding 1 — the binary "23.4% missed" was pessimistic by ~40%

The `raw ≥ 0.48` gate (= calibrated 0.15), measured two ways:

| metric | captured | missed | **miss %** |
|---|---:|---:|---:|
| home-run COUNT (old binary >30%) | 14,879 | 4,552 | **23.4%** |
| tail MAGNITUDE Σmax(fwd−30%,0) | 3364.7 | 557.5 | **14.2%** |

**The gate misses small home-runs, keeps big ones.** Median magnitude of a *captured* home-run
+42.6% vs a *missed* one +37.3%; mean excess-over-30% is +0.226 captured vs **+0.122 missed**
(nearly half). So the correct headline is **"the gate misses 14% of the tail, not 23% of the
events"** — and the 14% it misses is disproportionately the near-miss end. Q7's number overstated
the leak by ~40% because it weighted a barely-+30% name the same as a +400% one.

## Finding 2 — the raw score DOES rank the fat tail (the real reversal)

The sprint narrative ("strong gate, weak ranker, confirmed 4×") was all measured *within the gated
breakout pool* (within-day IC≈0) or on the *flattened calibrated* score. On the **full-universe raw
score** the tail is strongly concentrated at the top:

- **Top-1% forward returns** (fwd ≥ +49.9%, 5,965 events) sit at raw-score percentile **0.89 median
  / 0.84 mean** (0.5 = no signal). **86%** of them clear the 0.48 gate vs **34%** base rate.
- **Tail-capture concentration** (walk the score top-down):

  | top X% of scores | share of total tail captured | lift |
  |---|---:|---:|
  | 1% | 6.1% | **6.1×** |
  | 5% | 25.1% | 5.0× |
  | 10% | 46.7% | 4.7× |
  | 25% | 77.2% | 3.1× |
  | 50% | 94.4% | 1.9× |

- **Mean-tail grades monotonically by ventile** (rho **+1.00**); the top ventile alone holds **25%**
  of all tail magnitude (mean_tail 0.033 vs ~0 in ventile 0).

**This does NOT contradict "weak ranker."** Both are true and non-overlapping: the score is a weak
ranker *within a homogeneous gated pool* (near-interchangeable ~6 names, IC≈0) but a **strong ranker
of the tail across the full universe** — the tail concentration lives at the extreme top, exactly
where M5's persistent continuous-score top-N sits (top-5 +5.7%, 50% overnight persistence). The two
findings stitch: the alpha is a *top-of-full-universe* effect, not a *within-gated-pool* one.

### Finding 2b — is the full-universe lift just the GATE re-expressed, or a real selection edge?

**Scope of Finding 2 (answering the horizon/scope question):** each row is one `(ticker, date)`
point-in-time cross-section (score = that day's features); `fwd20` is the same name's next-20-trading-day
close-to-close return. Tail-lift pools all daily cross-sections and asks: do the highest-scored names
hold a disproportionate share of the eventual 20d fat tail? The "weak ranker (4×)" evidence is the
OPPOSITE conditioning — *after* restricting to the ~6-name gated breakout pool (IC≈0), or on the
*calibrated* (flattened) score. Same 20d horizon; different population.

**Is the 6.1× a new selection edge, or the gate wearing a ranker costume?** Decompose by conditioning
tail-lift on already passing the 0.48 gate:

| top X% of scores | tail-lift, FULL universe | tail-lift, CONDITIONAL on passing gate |
|---|---:|---:|
| 1% | 6.1× | **3.2×** |
| 5% | 5.0× | 2.3× |
| 10% | 4.7× | 2.0× |
| 25% | 3.1× | 1.9× |

**Both effects are real, ~half each.** Roughly half the 6.1× top-1% lift is the gate itself
(admitting high-score names) — 86% of top-1% fwd winners already clear the gate. But the score keeps
ranking the tail *among gate-passers* (3.2× at the top-1%), so it is NOT purely the gate re-expressed.
That residual **above-gate 3.2×** is the actual candidate selection edge — and it reconciles the
earlier "sharp top, flat middle" finding (top-5 +5.7%, ranks 6–300 flat ~+4%): the gradient is real
but concentrated at the extreme top. **This 3.2× above-gate lift is the bar M4's magnitude regressor
must beat and what M5's tighter top-N exploits — not the headline 6.1×, which double-counts the gate.**

## The M1 objective (reusable for M3/M4)

Two metrics replace the binary home-run rate everywhere downstream:
1. **Captured/missed tail magnitude** `Σ max(fwd−30%, 0)` — the leak metric (14.2%, not 23.4%).
2. **Tail-capture lift @ top-k** — cumulative share of total tail in the top-k scores / k.
   2025: top-1% 6.1× / top-10% 4.7× (above-gate 3.2×). **But report this as a DISTRIBUTION across
   regimes, never one number** (median 6.8×, range 0.68–12.1×; above-gate median 2.7×, 5/25 below 1×
   — see multi-year section). This is the "rank-of-tail" eval M4's regressor must beat *on the bad
   years*, and the stability target M3 sweeps.

Both are computed from raw fwd returns + a score, so they drop into the WFO/start-time-cone harness
unchanged — swap `home_run_rate` for `tail_lift@k` as the objective.

## Multi-year (M1 across 25 regimes, 2001–2025) — the score is a PRO-CYCLICAL tail-ranker

The full universe was re-scored (raw p_pos) for every year 2001–2025 and the objective re-run.
**The tail-ranker survives on average but COLLAPSES in exactly the regimes where the tail matters
most.** Good/bad split (bad = 2001,02,07,08,09,11,22 — bust/bear/top/crash; 7 yrs vs 18):

| metric (median) | GOOD regimes (18y) | BAD regimes (7y) |
|---|---:|---:|
| top-1% lift, FULL universe | **8.8×** | **1.4×** |
| top-1% lift, ABOVE the gate (the selection edge) | **3.3×** (0/18 below 1×) | **0.42×** (5/7 below 1×) |
| tail-magnitude miss % | 20% | 47% |

- **Full-universe lift dives below no-skill in the two worst tapes: 2001 dot-com (0.68×) and 2008
  GFC (0.68×).** 2007 top (1.36×), 2009 (1.33×), 2011 EU (2.29×) are also weak. In bulls it runs
  7–12×.
- **The above-gate SELECTION edge is fragile:** median 2.7× overall but **negative-to-nil in 5/25
  years** (2001 0.27×, 2002 0.42×, 2007 0.11×, 2008 0.42×, 2011 0.57×). The 3.2× above-gate edge
  reported for 2025 is a *good-regime* number; **in a crash there is no above-gate ranking edge.**
- **corr(lift, home-run rate) = −0.44** — the ranker is WORSE in the tail-rich years. Crashes have
  more moonshots but the (technical, momentum-heavy) model can't find them: it's pro-cyclical.
- **The one regime-robust result is the magnitude CORRECTION itself:** `miss_mag < miss_count` in
  **25/25 years**. The re-cut's *methodological* point holds universally even though the *level* of
  the leak swings 9% (2021) → 66% (2008). So M1's metric change is safe to adopt; M1's *ranking
  claim* is regime-conditional.

**Implication for M3/M4 (this is why M1 had to come first):** a stability-first selection (M3) that
weights the bad years will see the edge go to ~zero there — so the champion must be judged on its
bad-regime floor, not its bull-market ceiling. A magnitude regressor (M4) trained on pooled years
will INHERIT this pro-cyclicality unless it is regime-conditioned or trained tail-weighted on the
down years. `data/model_output_eda/multiyear/m1_multiyear.png`, `m1_multiyear_table.csv`.

## ⚠️ Caveats
- **No exits/sizing/liquidity** — full-universe fwd return is directional, not tradable P&L. Still to
  do: bootstrap-CI the per-year lift and run it through the start-date cone (M2) at sub-year resolution.
- **Early years have a thinner universe** (2001 n=163k vs 2025 n=596k) and earlier-vintage features —
  the 2001/2008 sub-1× lift is partly regime, possibly partly coverage; don't over-read a single bad
  year, read the good/bad *split* (18-vs-7, which is robust).
- **Tail is heavy-tailed by construction** → per-year top-1% lift is dominated by a handful of names;
  the bootstrap CI (deferred) is the real robustness check.
- Uses `Σ max(fwd−30%,0)`; rank-of-top-1% AUC gives the same qualitative story. Standardised on
  **tail-lift@k**.
