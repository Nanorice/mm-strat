# Verdict: can we refine the ~6-name/day breakout pool into a high-quality subset?

**Date:** 2026-07-07 · **Status:** ✅ strong (three independent tests agree) · 1 deployed window
**Feeds:** Sprint 14 Q1/Q2 (selection, human-review pool) · **Memory:** [[project_breakout_pool_refinement]]
**Data:** live `daily_predictions` (m01_binary, breakout cohort, 169 days), 20d fwd from close.

## Question
The 0.15 gate leaves ~6 names/day. Do these persist across days (so we could track/rotate the
best), and can a metric surface a genuinely higher-quality subset to reduce what a human reviews?

## Findings
**1. Persistence = 0%.** Names gated today are essentially never gated tomorrow (next-day
persistence mean 0%; every consecutive-gated streak is exactly 1 day; 63% of tickers appear once
in 169 days). Breakout is a **day-0 event by construction** — a ticker breaks out once, gets
flagged, then is no longer a fresh breakout. → **Rotation / persistence-based refinement
(sprint-14 Q#2) is dead for this cohort.** There is nothing to persist.

**2. No within-day technical separator.** Within-day rank-IC (spearman of feature vs 20d fwd,
per day, averaged over 130+ days) for every candidate is noise-level:

| feature | within-day rank-IC |
|---|---:|
| volatility_20d | +0.078 |
| natr / adr_20d | −0.077 |
| mom_21d | +0.052 |
| rs / RS_Universe_Rank | −0.05 |
| **p_pos (model) / p_cal** | **−0.03 / −0.03** |
| breakout_momentum, vcp_ratio, dist_from_20d_high | ~0 |

The **model's own score has slightly NEGATIVE within-day IC** — a third independent confirmation
of gate-not-ranker (cf decile test + top-K test). RS/momentum are weakly negative (the most
extended breakouts mean-revert). → **No within-day ranker is buildable; "take all ~6" ≈ best.**

**3. SECTOR is the one real residual (~10pt spread).** Mean 20d fwd by sector:

| sector | mean | median | n |
|---|---:|---:|---:|
| Technology | +9.2% | +4.6% | 238 |
| Energy | +4.0% | +4.5% | 89 |
| Basic Materials | +2.1% | +4.5% | 52 |
| Industrials | +0.8% | +1.8% | 168 |
| Financial Services | +0.3% | −3.0% | 65 |
| **Healthcare** | **−0.1%** | **−3.4%** | **285** |
| Consumer Cyclical | −0.6% | −0.9% | 87 |

Healthcare is the largest bucket (285) and the worst by median (−3.4%) — biotech binary-event
pops the technical model flags as real breakouts but which fail forward. Tech is the mirror image.

## Answer
- **You cannot distill a "high-quality subset" by score or technicals** — three tests say the ~6
  names are near-interchangeable. The gate is the alpha.
- **The residual alpha the system is blind to is SECTOR/industry** — exactly the human-judgment
  layer the user described (Minervini: system shortlists, human applies sector/fundamental
  context). Healthcare/biotech breakouts are the concrete failure mode.

## Recommended (test OOS before hard-wiring)
1. **Sector-aware triage of the daily gated list** — surface sector alongside each name;
   flag/deprioritise Healthcare (biotech) breakouts. This is the monitorable "reduce the pool"
   metric — not a ranker.
2. **Test a Healthcare veto or sector-tilt sizing** in the backtest (n=285 → not a fluke, but
   confirm across the start-time cone, [[project_champion_starttime_dependent]]).
3. Fundamentals (the off-system info) likely explain the within-sector residual — a candidate for
   the human review step, not automation.

## ⚠️ Caveats
- One deployed window (169 days, breakout only). Sector split is large (n=285 Healthcare) but
  confirm it holds across start dates before wiring a veto.
- Sector returns here are unconditional (no market-regime split); Tech's +9% may be regime-era.
