# R2 verdict — leadership profile (Minervini step 3): collapses into RS; the one residual is an upside-only volatility tilt, below gate

**Date:** 2026-07-10 · **Status:** ✅ CLOSED — M0+M1 ran on the full 1.61M-row panel.
**Plan:** [`../plans/r2_leadership_profile_eda_plan.md`](../plans/r2_leadership_profile_eda_plan.md) ·
**Parent:** [`../plans/sepa_ground_truth_roadmap.md`](../plans/sepa_ground_truth_roadmap.md) · Currency **C1** (label-ranking).
**Repro:** `.venv/Scripts/python.exe scripts/r2_leadership_profile.py` (~90s). Reuses the R1b label
panel + joins R2 traits from `t3_training_cache`. **Cache:** `data/research_cache/r2/{m0_univariate,m1_rs_stack}.csv`.

## TL;DR

**No trait clears the M1 gate** (stack ≥1.3× on RS-D10, monotone, not RS-clone). Minervini's step-3
"leadership profile" collapses into RS on this panel — the kill criterion fired. The only residual
signal is a **volatility tilt** (`adr_20d`/`natr`, 1.28×/1.26× within RS-D10), which is (a) below the
1.3× gate, (b) **upside-only-biased** (MFE mechanically rewards volatility — tail-lift 1.6× > HR-lift
1.28×), and (c) not a *new* axis — it is the same phenotype as R1b's small-cap/coverage axis
([[project_r1b_step2_subsumed]]). The passport ships as a **descriptive / manual-review aid**, not a
selection layer. This closes the last open box of the SEPA funnel program.

## M1 — the decisive test: within-RS-D10 tercile lift (n=164,626 D10 rows, base HR 0.284)

| trait | T3 HR-lift vs D10 | T3 tail-lift | monotone | ρ vs RS | PASSES |
|---|--:|--:|:--:|--:|:--:|
| adr_20d | **1.28** | 1.61 | ✓ | 0.34 | ❌ (below 1.3) |
| natr | **1.26** | 1.56 | ✓ | 0.32 | ❌ (below 1.3) |
| rs_vs_industry | 1.14 | 1.32 | ✓ | **0.80** | ❌ (RS-clone) |
| market_cap (small) | 1.09 | 1.15 | ✓ | 0.08 | ❌ |
| rs_sector_rank | 1.06 | 1.20 | ✗ | **0.57** | ❌ (RS-clone) |
| vcp_ratio | 1.04 | 1.16 | ✓ | 0.08 | ❌ |
| industry_momentum | 1.02 | 1.03 | ✗ | −0.02 | ❌ |
| rs_industry_rank | 1.02 | 1.10 | ✗ | 0.25 | ❌ |
| consolidation_duration | 1.00 | 0.95 | ✗ | 0.03 | ❌ |
| dollar_volume_avg_20 (thin) | 1.00 | 0.89 | ✗ | 0.02 | ❌ |
| volatility_20d | 0.96 | 0.97 | ✗ | 0.14 | ❌ |
| dist_from_52w_high | 0.92 | 0.91 | ✗ | −0.03 | ❌ |
| consolidation_width (tight) | 0.80 | 0.59 | ✗ | −0.28 | ❌ |

**Reading the table against the book's step-3 claims:**
- **Group-leadership traits are RS in disguise.** `rs_vs_industry` (ρ 0.80) and `rs_sector_rank`
  (ρ 0.57) correlate too tightly with RS to be independent — dropped by design even though they show
  raw lift. "Leaders lead their group" is *already inside* the RS composite.
- **Base-character traits are flat-to-negative.** `vcp_ratio` (1.04×), `consolidation_duration`
  (1.00×), `dist_from_52w_high` (0.92×), `consolidation_width` (0.80×) — the VCP/tight-base emphasis
  adds **no** tail lift on top of RS. Notable null for the book's central technical pattern *as a
  cross-sectional ranker* (it may still matter as an entry *trigger*, which R2 did not test — traits
  here are scored at panel rows, not at breakout).
- **The only residual is volatility** (`adr_20d`/`natr`) — and it's the upside-only artifact, below.

## The volatility residual — era-stable but below gate, and upside-only

Within-RS-D10 HR-lift by era (the plan's stability discipline; not a one-window artifact):

| trait | 2003–08 | 2009–17 | 2018–26 | pooled |
|---|--:|--:|--:|--:|
| adr_20d | 1.28 | 1.39 | 1.21 | **1.28** |
| natr | 1.25 | 1.36 | 1.21 | **1.26** |
| industry_momentum | 0.98 | 1.10 | 1.00 | 1.02 |
| market_cap (small) | 0.85 | 0.88 | 0.98 | 0.92 |

The volatility lift is **real and era-stable** (1.21–1.39×, never below 1.2×) — but it never clears
1.3× in 2 of 3 eras, and its **tail-lift (1.6×) exceeds its HR-lift (1.28×)** — the fingerprint of
MFE magnitude-inflation, not hit-rate skill. High-ADR names produce bigger favorable *and* adverse
excursions; MFE only measures the favorable side (epistemic #3, [[project_sepa_three_currencies]]).
This is the **same phenotype R1b already banked** (small/thin/volatile names inflate MFE) wearing a
volatility label instead of a size/coverage label — not a new independent axis.

## M0 — raw univariate contrast (context, not decision)

D10/D1 home-run lift, full panel: `adr_20d` 22.8× and `natr` 20.7× top the raw table — but this is
almost entirely the volatility-inflation + the fact that low-vol names never home-run at all
(D1 HR ≈ 0.014). Once conditioned on RS-D10 (M1) the lift collapses to 1.28×. The M0→M1 collapse **is
the finding**: unconditionally these traits look enormous; on top of the shipped RS signal they nearly
vanish. Full table in `m0_univariate.csv`.

## The passport (M2 deliverable) — a descriptive/manual-review aid, NOT a selection layer

Per the kill criterion ("no trait stacks ≥1.3× → passport ships as a descriptive/manual-review aid
only"), the passport is a **contrast portrait**, not a ranker. What a realized home-run looks like at
entry vs the RS-D10 base:

**Traits that DO characterize home-runs (but don't add rank-lift over RS):**
- **Higher volatility signature** — top-tercile `adr_20d`/`natr` home-run ~1.3× the RS-D10 base.
  *Use as a manual "is this name lively enough to run?" check — NOT a buy tilt (upside-only bias).*
- **Small / thin / sparse-coverage** — confirmed at label level in R1b ([[project_r1b_step2_subsumed]]);
  liquidity-constrained ($7.5M/day), R3-gated.

**Traits the book emphasizes that are NULL here (list them — step 4 must know what does NOT matter):**
- **Tight/mature base** (`vcp_ratio`, `consolidation_width`, `consolidation_duration`) — no lift over
  RS as a cross-sectional score. (Untested as an entry *trigger* — a separate question.)
- **Proximity to 52w high** (`dist_from_52w_high`) — *inverts* (0.92×): within RS-D10 the names
  already nearest the high are slightly *less* likely to home-run (they've already moved).
- **Group leadership** (`rs_vs_industry`, `rs_sector_rank`) — real but **redundant with RS**; no
  independent information.

**Operational form (M3 handoff — scope with user):** the passport is a **dashboard column set** on the
existing RS-ranked watchlist (add `adr_20d` percentile + the R1b size/coverage flags as *display*
context), **not** a new model and **not** an auto-gate. Step 4 stays manual, per the book.

## Kill-criteria evaluation (from the plan)

- **No trait stacks ≥1.3× on RS-D10 → step 3 collapses into RS; passport = descriptive/manual aid** —
  **FIRED.** Best stacker is 1.28× (below gate) and is an upside-only volatility artifact.
- ~~A trait monotone only pre-2019~~ → did NOT fire; the volatility residual is era-stable (it just
  doesn't clear the bar). Its exclusion is on *magnitude*, not decay.

## Guardrail compliance

`read_only=True`; labels from the R1b cache (built from the registered `m01a_tail_v1` source_query,
never re-derived); per-date XS ranks throughout (raw levels not comparable across 25y); XS-rank casing
bug dodged by lowercasing on read (all trait columns resolved — verified). Label-level only (C1); no
strategy claim — any monetization routes through R3's harness, which already showed the RS tail itself
doesn't convert ([[project_sepa_three_currencies]]). MFE upside-only bias flagged on every volatility
result.

## Program consequence

R2 was the last open box. With R1/R1b/R2/R3/R4 all resolved, the SEPA funnel program is **CLOSED**:
- **Selection** = the one-column RS rule (steps 1–3 all collapse to it). Second axis = size/coverage
  (R1b), label-level only.
- **Exit** = `champion_trail` is a candidate refinement (R3, +0.21, deploy-gate pending).
- **Durable deliverables:** the RS rule, the size axis, and this passport (manual-review aid).
- **Not shippable as systematic alpha beyond the incumbent:** the 63d MFE tail does not convert under
  the available exits (R3), and no leadership trait adds rank-lift over RS (R2).
