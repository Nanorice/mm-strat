# Verdict: entry-timing features — does any macro metric reveal a good/bad time to deploy?

**Date:** 2026-07-07 · **Status:** ✅ exploratory correlation on the 25-year cache, no re-scoring
**Answers:** the user's pivot away from the SPY-200d gate — "besides the worst time to enter, find
the *best* time; look at SPY/QQQ/VIX/macro/M03 for a feature around the best entry dates."
**Data:** `data/model_output_eda/multiyear/raw_full_{2003..2025}_fwd.parquet` (top-5/day) +
`t2_regime_scores` (M03) + `t1_macro` (SPY/QQQ/VIX) + `macro_data` (6-pillar, raw levels).
**Script:** `docs/session_logs/sprint_14/scripts/entry_timing_features.py`
**Panel:** `data/model_output_eda/entry_timing/entry_timing_daily.parquet` (5650 days, reusable).

> NOT a backtest. Outcome per day = mean forward return of that day's **top-5 by prob_elite**, over a
> **horizon grid (fwd 20/50/100d)** — because SEPA holds longer than 20d, so a weak 20d entry may get
> a "second chance" on a longer hold. Features are entry-date macro state. We correlate the two.

## Which macro model — the 6-pillar dashboard one, NOT M03

Two distinct "macro regime" models live in this repo; the user meant the **6-Pillar Macro
Environment** on the dashboard (VIX, Credit, Term Spread, Rates, Net Liquidity, CAPE), which is
`dashboard_utils.load_macro_pillars()` reading `macro_data`. This is **separate from M03**
(`t2_regime_scores`, 3 pillars trend/liq/risk). We tested both here.

⚠️ **Leakage guard:** the dashboard's pillar *percentiles* use all-time / 5-yr-rolling rank
(look-ahead) — the docstring itself says "do NOT feed these into a backtest." So we correlate on the
**raw pillar LEVELS**, not the display percentiles. CAPE_OURS only exists 2012+ → NaN before that.

## Finding 1 — M03 does NOT flag entry timing (25-year confirm)

Every M03 feature correlates between −0.09 and +0.02 with the outcome, all horizons — noise. The
best-vs-worst-date gap on `m03_score` is **−0.08** (zero separation). M03 is a trend-*state* label,
not an entry-timing signal. Consistent with the standing memory that M03 is a no-op / mildly
contrarian for this strategy ([[project_backtest_equity_and_sizing]] — M03 sizing was a no-op too).

| feature | fwd20 | fwd50 | fwd100 |
|---|--:|--:|--:|
| m03_score | −0.004 | −0.048 | −0.058 |
| m03_pillar_trend | +0.018 | +0.004 | −0.008 |
| m03_pillar_risk | −0.036 | −0.080 | −0.086 |

## Finding 2 — the 6-pillar macro DOES carry signal, and it's a VALUE/STRESS axis

The pillars show the strongest, most horizon-consistent correlations in the whole panel. The signal
is coherent: **the best entry dates are macro-stress / cheap-valuation moments** — the opposite of a
trend signal, which is exactly why M03 (trend-based) misses it.

| pillar | fwd20 | fwd50 | fwd100 | reading |
|---|--:|--:|--:|---|
| **pil_rates** (10y) | −0.061 | **−0.124** | −0.102 | high rates → worse entries (strongest single signal) |
| **pil_credit** (HY spread) | +0.027 | +0.091 | **+0.094** | **wide credit spreads → BETTER entries** (contrarian: enter into stress, paid over 50–100d) |
| **pil_cape** (valuation) | +0.006 | −0.088 | **−0.106** | expensive market → worse forward (2012+ only) |
| pil_vix | +0.036 | +0.056 | +0.078 | higher VIX → better (echoes Q15: high-VIX days rebound) |

Best-vs-worst-date table agrees on direction: best dates carry **higher net liquidity (+346B),
higher VIX, wider credit**. SPY/QQQ trailing-return and above-200d are weakly positive but far
smaller than the value/stress pillars — plain price-momentum is NOT where the entry-timing edge is.

## Finding 3 — a weak 20d entry gets a partial second chance (regime-robust)

Worst-20d-decile dates, mean outcome as the hold extends: **−20.7% (20d) → −17.5% (50d) → −8.1%
(100d)**. A bad 20d entry heals ~12pp by 100 days but doesn't turn positive. So on SEPA's longer
hold a bad entry is a *drag, not a write-off* — "not terrible, second chance" confirmed, though the
chance is partial. Stronger on the full 25y than on a bull-only slice (crash entries mean-revert
hardest).

## Caveats — read before trusting

1. **All |ρ| ≤ 0.12.** Weak-but-consistent tilts, not gates. No single pillar times entries decisively
   — same lesson as the score itself ([[project_isotonic_flattens_ranking]]).
2. **The signal is CONTRARIAN → it fights the strategy's own scope.** The model is continuation-only
   ([[project_capital_deployment]]: SEPA excludes crash-bottoms). But the pillars say the best *time*
   to deploy is into macro stress. Real tension: continuation *names*, stress-timed *deployment*. The
   two aren't contradictory (name-selection ≠ date-selection) but the combined product must be
   designed knowing this, not by accident.
3. **Univariate + full-pooled.** Not conditioned on regime, not multivariate. rates/credit/CAPE are
   correlated (all "financial-conditions" cousins) — the marginal signal after combining is untested.
   That's the next cut (see below).

## Finding 4 (option b) — the stress composite BEATS every single pillar, and works in BOTH regimes

Combined the value/stress pillars into one z-scored composite (sign-aligned so higher = more stress
= predicted-better): `stress = mean(+z(credit), −z(rates), −z(cape))`. VIX kept separate as the
incumbent stress proxy. Two results that upgrade Finding 2:

**(4a) Combining is NOT redundant — it's a real marginal lift.** At fwd100 the composite ρ = **+0.167
vs +0.10 for the best single pillar** (~60% stronger); strengthens with horizon (0.04 → 0.14 → 0.17),
a slow value-mean-reversion shape. So rates/credit/CAPE each add a piece — corrects the prior guess
that they'd be redundant financial-conditions cousins.

| feature | fwd20 | fwd50 | fwd100 |
|---|--:|--:|--:|
| **stress_score** | +0.041 | **+0.137** | **+0.167** |
| pil_credit | +0.027 | +0.091 | +0.094 |
| pil_rates | −0.061 | −0.124 | −0.102 |
| pil_vix | +0.036 | +0.056 | +0.078 |

**(4b) NOT a bear-only buy-the-dip signal — it holds in bull too.** Split on SPY>200d (exogenous,
ex-ante — the Q15 axis). The composite is **equal in both regimes** (bull +0.176, bear +0.190 @
fwd100). It's robust *because its components fire in complementary regimes*:

| pillar | bull ρ (fwd100) | bear ρ (fwd100) | reads as |
|---|--:|--:|---|
| pil_credit | **+0.142** | +0.017 | credit spreads help in BULL only |
| pil_rates | −0.077 | **−0.263** | high rates punish BEAR entries hardest |
| pil_vix | +0.080 | **+0.206** | VIX rebound is a BEAR phenomenon |
| stress_score | +0.176 | +0.190 | **regime-diversified → robust** |

→ The composite beats any single pillar precisely because the parts are **regime-diversified, not
redundant** (credit in bull; rates/VIX in bear). This is a much stronger, less fragile story than the
"contrarian buy-the-dip" framing Finding 2's pooled numbers suggested. Caveat: n(bear)=1094 vs
n(bull)=4556 — the bear column is thinner; read the sign/pattern, not the third decimal.

## Finding 5 (live-safe) — the honest composite is a BULL-ONLY tilt with a top-quintile kicker

Rebuilt the composite with **expanding-window** z (day t uses only stats through t−1 — no
look-ahead), tried 5 variants, and tested it as an actual deploy tilt on fwd100 (the horizon it peaks
at). This is the version that could size real capital; the earlier stress_full was look-ahead.

**(5a) Live-safe roughly HALVES the signal.** stress_full (look-ahead) fwd100 ρ +0.167 →
**stress_ew +0.074**; best variant **stress_ew_vix +0.084** (VIX adds a hair). rank-based +0.043
(worse — fat-tail robustness costs more than it saves); dropping CAPE +0.072 (CAPE's 2012+ gap is a
non-issue). **Pick = stress_ew_vix (+credit −rates −cape +vix, expanding-z).** The full-sample z was
inflating the edge ~2×.

**(5b) Live regime split FLIPS to bull-only.** With look-ahead z it looked regime-robust (Finding
4b); live it isn't:

| regime | fwd100 ρ | n |
|---|--:|--:|
| bull (SPY>200d) | **+0.139** | 4556 |
| bear | **−0.150** | 1094 |

In a downtrend, high stress predicts WORSE entries (stress keeps climbing — catching the falling
knife). The look-ahead z borrowed future normalization that flattered the bear column. → The signal
is a **bull-market tilt, NOT all-weather.** A naive "more stress → more capital" rule would hurt in
bear. Correct usage: stress tilt **gated by SPY>200d** (the Q15 axis returns, as a gate ON the tilt).

**(5c) The tilt works, marginally, and it's a TOP-QUINTILE effect.** Quintiles of stress_ew vs mean
fwd100: Q1..Q4 near-flat (+9.7 / +9.2 / +11.7 / +12.5%), **Q5 jumps to +18.5%**. Not a smooth linear
tilt — "deploy hard when stress is EXTREME," not "scale with stress."
- FLAT deployment fwd100: **+12.3%** · STRESS-WEIGHTED: **+14.2%** → **+1.8% uplift** (marginal, as
  expected). Q5−Q1 = **+8.8%**.

**Net:** a weak bull-regime tilt (live ρ≈0.08, +1.8% fwd100 uplift) with a top-quintile kicker.
Deploy more when stress is EXTREME **and** SPY>200d. Honest, small, and directionally usable — but
not the all-weather signal the look-ahead numbers implied.

## What this means for the regime question

The user asked whether other metrics reveal regime better than M03 for this strategy. **Yes:** the
6-pillar macro's **rates / credit / CAPE (value-stress) axis** carries the entry-timing signal that
M03's trend axis doesn't. M03 measures *trend regime*; this strategy's timing edge lives in the
*valuation/stress regime*. Different instrument — and the more useful one here.

## Next

Findings 4+5 DONE: composite built, made live-safe (expanding-z), variant-tested, and tilt-measured.
Result = a bull-gated, top-quintile deploy tilt (live ρ≈0.08, +1.8% fwd100). Remaining, if pursued:

- **Wire it as `stress_ew_vix` gated by SPY>200d** into the deploy path (macro_sizer-style exposure
  input, NOT a model feature — keep it off the score). Small effect → low priority vs core model work.
- **Judge the strategy on fwd100, not fwd20** — the timing signal (and the second-chance recovery)
  both live at the long horizon; the basket/exit grid was tuned on shorter outcomes. Re-check.
- The tilt is a top-quintile step, not linear → if wired, a threshold ("boost when stress in top
  quintile & SPY>200d") is truer to the data than a continuous weight.
