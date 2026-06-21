# m01 Case Studies — backtest infra (2026-05-22)

## TL;DR / Verdict

1. **SHIP: m01_prototype standalone is a strong, verified signal** — +201%
   (2020-2024), Sharpe 0.79, max DD -26%, positive 4/5 years, 2022 only -9%.
   This closes the handover's open debt ("prototype dense backtest unverified").
2. **m01_rank does NOT improve it as an entry re-ranker** (+65%, max DD -42%) —
   it over-weights high-nATR names entered at the breakout top.
3. **m01_rank's core skill IS real** (per-ticker fwd-return IC 0.07-0.13,
   positive in 85% of names) — it's a sound setup-QUALITY signal.
4. **But it is NOT a timing instrument:** the H=1/5/10/20 variants are
   0.92-0.99 correlated (one horizon-invariant score), so the term-structure
   "delay-entry" cohort (high 20d / low 1d-5d) is statistically empty (6-9 rows).

**Decision (2026-05-22): ship m01_prototype standalone; shelve m01_rank as a
timing layer.** Future m01_rank revival needs path-distinguishing features or a
price-action timing rule (not the model's horizon scores) — see final section.

### Clarification — both cases score DAILY; the difference is WHICH model

A possible misread of the above: "prototype wins because it's dynamic / dense."
Not so. **Case 1 already scores m01_prototype dynamically every day** on the
dense T3 panel (`score_from_t3` runs it on every active SEPA-candidate row,
daily; the engine ranks entries by the prototype's trailing-10d percentile). It
is NOT score-once-at-breakout. Case 2 is the SAME daily-dense pipeline with the
entry-ranking key swapped to the densely-trained m01_rank score.

So the verified conclusion is: **m01_prototype's daily-updated score is a better
entry criterion than the densely-trained m01_rank's daily score** (+201% vs
+65%), even though the prototype was trained only on breakout-day rows.

**Caveat (not isolated, accepted as-is):** prototype vs rank differ in three
ways at once — (a) 4-class MFE target vs 2-class >20%/20d binary, (b) 2003-2026
training vs shorter dense window, (c) event-grain vs dense-grain training. The
gap is NOT cleanly attributable to grain alone. A controlled A/B (dense model
with the prototype's 4-class target + window) was considered and DEFERRED — the
practical entry-criterion question is already answered.

---

**Engine:** `src/backtest` BackTrader (`UniverseScorer` + `SEPAHybridV1`):
daily M01 scoring over the dense T3 panel, M03 regime gating, 3-tranche ATR
exits, realistic fills (0.1% commission + 0.1% slippage). Window 2020-2024,
2019 warmup year (not evaluated — see warmup stall note). Prototype model:
`models/m01_prototype_2003_2026/v1/model.json` (4-class softprob).

Scripts: `scripts/run_case1_prototype_standalone.py`,
`scripts/run_case2_prototype_plus_rank.py`, `scripts/m01_rank_scorer.py`
(inline reproduction of the m01_rank.ipynb binary classifier; the saved
`models/m01_rank/model.json` rank:pairwise artifact is stale).

---

## Case 1 — m01_prototype as a standalone top-K signal ✅ STRONG

m01_prototype scores; SEPA engine ranks entries by prototype trailing percentile.

| Year | Return | Sharpe | Max DD |
|------|--------|--------|--------|
| 2020 | +21.5% | 1.63 | -9.7% |
| 2021 | +49.6% | 1.32 | -21.0% |
| 2022 | -9.1% | -0.34 | -17.4% |
| 2023 | +27.9% | 0.95 | -25.9% |
| 2024 | +39.9% | 1.10 | -20.7% |
| **Eval total** | **+201%** | **0.79** | **-25.9%** |

891 trades, win rate 38.8%, avg ~9 positions. **This verifies the open debt
from the handover ("m01_prototype dense backtest unverified") — it is verified
and good.** Positive 4/5 years; M03 gating contains the 2022 drawdown to -9%.
This is a much better result than the design-note §0 standalone-rank verdict.

## Case 2 — m01_prototype selection + m01_rank entry-timing gate ❌ HURTS

Identical engine/floors/exits to Case 1; ONLY the entry-priority ranking key is
swapped to m01_rank's daily cross-sectional percentile.

| Year | Return | Sharpe | Max DD |
|------|--------|--------|--------|
| 2020 | +60.2% | 2.21 | -13.4% |
| 2021 | -2.2% | 0.09 | -28.6% |
| 2022 | -25.4% | -1.06 | -28.5% |
| 2023 | +49.8% | 1.28 | -30.7% |
| 2024 | -11.6% | -0.13 | -31.1% |
| **Eval total** | **+65%** | **0.39** | **-42.0%** |

973 trades, win rate 31.1%. **m01_rank's daily rank is a worse entry-priority
key than the prototype's own.** Halves Sharpe, blows out max DD to -42%.

**Diagnosis:** m01_rank picks higher-volatility names (entry nATR median 8.35
vs 7.22) and trades more (962 vs 882) with worse per-trade pnl (mean 1.55 vs
2.39%, win 31% vs 38%). Its >20%/20d target rewards explosive moves → ranks the
most-EXTENDED names first → great in trending years (2020 +60%, 2023 +50%),
sharply negative in choppy/rotating years (2021, 2024). Classic momentum beta,
matching design-note §0. m01_rank is not a good *selection re-ranker*.

## Skill validation — is m01_rank good at its DESIGNED job? (user directive)

Before any further wiring, validate the model's core skill directly (score vs
return, NOT a portfolio backtest). m01_rank trained on <2020, scored 2020-2024
OOS. Forward returns from price_data.close, adjacency-guarded.
Script: `scripts/validate_m01_rank_skill.py`.

### Metric A — per-ticker forward-return IC ✅ PASSES

| Horizon | IC (ticker-mean) | % tickers IC>0 | IC (pooled) |
|---------|------------------|----------------|-------------|
| 5d  | 0.069 | 86% | 0.016 |
| 10d | 0.100 | 86% | 0.031 |
| 20d | 0.133 | 84% | 0.042 |

The signal is real and BROAD: 84-86% of tickers have positive within-name IC.
IC rises with horizon (trained on 20d). Per-ticker IC >> pooled — m01_rank
genuinely tracks the right moment WITHIN each name's own history. This is the
timing skill it was designed for. Top-decile 20d fwd return +2.1% vs bottom
+0.5% (monotonic-ish). **m01_rank IS good at predicting short-horizon forward
performance on a SEPA candidate.**

### Metric B — breakout-day pullback by m01_rank quintile (the key insight)

On breakout_ok days, by m01_rank score quintile (1=low, 5=high):

| Quintile | 10d fwd_dd (pullback) | 10d fwd_ret | 20d fwd_dd | 20d fwd_ret |
|----------|-----------------------|-------------|------------|-------------|
| 1 (low)  | -2.9% | +0.21% | -4.7% | -0.07% |
| 3        | -4.6% | +0.41% | -6.9% | +0.68% |
| 5 (high) | -9.4% | +0.75% | -13.0% | +2.23% |

**The naive 'low score -> delay entry to avoid pullback' thesis is WRONG.** Low-
score names don't pull back — they go nowhere (small dip, ~0 return). It is the
HIGH-score names that both dip deeper AND return more: they pull back ~9-13%
before continuing to a +2.2% (20d) net move. This is exactly why m01_rank fails
as a top-K re-ranker (Case 2): ranking by score loads the book with high-ADR
names entered AT the breakout, eating the full pullback.

**Actionable wiring (revised):** the 'wait out the pullback' use case applies to
HIGH-score names — enter them on a DIP after the breakout, not at the breakout.
High score = high-conviction-but-volatile; m01_rank is a volatility/continuation
detector, not a smooth-return ranker.

## Multi-horizon term structure — horizons are REDUNDANT (key negative)

User directive: don't delay entry on one signal; train variants at H=1,5,10,20
and use the SHAPE (e.g. 20d positive but 1d/5d negative => delay, buy the dip).
Script: `scripts/m01_rank_multihorizon.py` (thresholds tuned to ~3-3.5% base
rate per horizon; trained <2020, OOS 2020-2024).

**Each variant predicts its own horizon** (per-ticker IC): 1d 0.021 (74% pos),
5d 0.061, 10d 0.093, 20d 0.136 (85% pos). Signal strengthens with horizon; 1d is
near-noise.

**But the four horizon scores are 0.92-0.99 Spearman-correlated** — they are
essentially the SAME signal. A name's m01_rank is horizon-invariant; it just
looks more confident at longer horizons because a 20d>20% target is easier to
hit than 1d>4%.

**Consequence — the delay-entry cohort is statistically empty.** Among high-20d-
conviction breakouts (~29,700), those with a LOW short-horizon score (the
"good name, bad entry day" signature) number **6 rows (1d) / 9 rows (5d)**.
Because scores are ~0.95 correlated, high-20d => high-short almost always. The
term-structure delay signal does not exist in this feature set.

Secondary observation: among high-conviction breakouts, the bulk (high short-
bucket) DO dip — 5d fwd_dd -5.8%, 5d fwd_ret -0.3%, recovering to +1.3% at 20d.
The pullback is real; it just isn't *separable* via a divergent short-horizon
score.

**Verdict:** m01_rank is a sound single "setup-quality" signal (IC validated) but
NOT a multi-horizon timing instrument as-is. To get a real entry-timing signal,
the model needs features that distinguish near-term from longer-term path
(e.g. explicit pullback/oversold features, intraday structure), or timing must
come from price-action rules (buy-the-dip after breakout) rather than from the
model's horizon scores.
