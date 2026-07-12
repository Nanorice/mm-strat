# Sprint 14 Consolidation EDA — the linear story (A → B → C)

**Source**: `cells/sprint_summary_eda.ipynb` (§1–§5 + §6 follow-ups) + `logs/thoughts_summary_eda.md` (Rounds 1–2b)
**Date**: 2026-07-11 (follow-up round closed same day; scripts: `resilience_metrics.py`, `industry_permutation.py`)

One paragraph version: we audited the selection population honestly (post SEPA-gate fix),
found the edge is a **tail phenomenon** concentrated at strong-RS × small-cap, found the
**downside is the regime** (not stock picking), confirmed **SPY-200d** as the one deploy gate
that earns its keep, and established that the score gate buys **tail and mean, not safety**.
Trough-geometry and sector are label-level enrichments, not live filters.

---

## The chain

### A. Why this notebook exists
The funnel program closed (champion unchanged), but earlier sprint-14 studies drew the
daily top-5 from an **inflated pool** (pre SEPA-gate fix). This notebook re-derives every
population claim from the audited funnel tiers: full (9.0M rows) → trend_ok (17.8%) →
breakout (1.3%).

### B. §1 — What pool are we actually picking from?
**Asked**: what does the funnel look like year by year?
**Tested**: per-year counts of the three tiers + daily top-5 churn (carryover count, tenure survival).
**Found**: breakout supply swings 5× with regime (2008: 5.8/day → 2021: 42.5/day) because the
breakout definition is intrinsically bullish. The top-5 is high-churn (mass at 0–1 carryover,
median tenure ~2d) and 30% of blind top-5 picks score below the 0.6 gate.
**Conclusion**: supply drift is the regime signature, not a defect. Gating trades count for
conviction (fewer names, tenure ~5d) — churn A (scarcity) and churn B (persistence) are
complementary, not contradictory.

### C. §1b/§1c — Can the supply itself be a weather gauge?
**Asked**: reverse-engineer regime from breakout counts.
**Tested**: normalize daily count by scored-universe size (universe grew 3.6×), smooth with
EMA10/EMA20, classify SPY<200MA days; compare as a deploy gate vs SPY-200d.
**Found**: EMA share classifies bear regime at **AUC ≈ 0.93** — but it is **coincident, not
leading** (ρ vs fwd60 SPY ≈ −0.14). As a gate it is dominated by SPY-200d; the interesting
pocket is **famine ∧ above-200MA** (early-recovery scarcity): mean fwd100 +10.5% vs +3.6% famine-all.
**Conclusion**: keep as a regime state EXPRESSION (during-period steer), not a brake.

### D. §2 — The start-day lottery and its downside
**Asked**: what does the top-5 basket forward return look like, and does the score gate cut the left tail?
**Tested**: basket fwd{20,100,150,200} across all start-days, raw vs gate 0.6, then the full
gate ladder 0.5/0.6/0.7 (§2b); worst-decile start-days vs index MAs (§2 table); a macro
failure model (Q5, offline); bad-day coverage decomposition (§2c).
**Found**:
- Gate ladder is **monotone on the tail** (HR-days 11→20%) but the **median gives it back at
  0.7** (+5.5→+4.1%) and loss/p10 worsen (38→44%, −20→−29%). 0.6 is the knee.
- Worst start-days cluster below **long** MAs: SPY-200d gap +12pp (MA50 +1pp — noise).
- Macro logistic model AUC 0.557; its strongest coefficient is spy_above_ma200 — it
  rediscovers the 200MA gate with extra steps. Question retired.
- Every day-blocker pays ≈1 good day per bad day caught (200MA: catches 21% of bad days,
  costs 16% of good days); adding the score day-block never improves the exchange rate.
**Conclusion**: the downside IS the regime; SPY-200d does the honest work; the score gate is a
tail/mean instrument, not a safety instrument.

### E. §3 — Where in the pool does the edge live?
**Asked**: sector and size structure of fwd100.
**Tested**: per-sector distributions split by regime and by score (§3b overlay facets);
sector median-score vs median-fwd and vs home-run-rate scatter (§3b2); size×RS home-run
heatmap; score monotonicity within (RS,size) cells (§3c); m01 feature-importance (§3d).
**Found**:
- Sector median ranking **flips bull↔bear** → pooled sector tilt unsafe.
- The model is nearly blind to sector medians (ρ ≈ +0.06) but prices the **sector home-run
  rate at ρ ≈ +0.90** — it does what its target asks. Gate lifts HR in EVERY sector (+6 to +19pp).
- Home-run rate rises with RS and rises MORE for small-caps; the **median inverts** — the
  edge is tail-only, which is why median studies miss it. Liquidity-constrained (~$7.5M/day).
- Score is monotone in RS (ρ ≈ +0.68) and already tilts small-cap; **within every (RS,size)
  cell** hi-score beats lo-score on HR by **+9.7pp** — a real residual beyond RS+size.
- Importance (total_gain): explicit RS family 4.0%, broad momentum block 22.6%,
  **`industry` alone 29%**.
**Conclusion**: durable second axis = SIZE; sector is a regime-conditional tail axis; the
model has a genuine residual but its weight structure warrants an audit (see follow-ups).

### F. §4 — Leadership trough-geometry (the RS residual the book describes)
**Asked**: leaders bottom higher/earlier and recover faster — is that real, incremental to RS, and live-predictable?
**Tested**: 6 SPY drawdown episodes 2003+, per-name geometry (trough_lead_days,
relative_depth, recover_lead_days) → leader_score 0–3; graded vs fwd100 within RS quintiles;
pre-episode proxies (beta, relative vol, corr, RS126) vs realized geometry (§4c).
**Found**: all three traits grade fwd100 in the predicted direction (ρ +0.13 / −0.14 / +0.09);
mean fwd100 ramps within EVERY RS quintile (top quintile −3.4%→+4.4% across scores 0→3);
geometry substitutes for RS on weak names, adds on strong ones. Live proxies: only **depth**
is predictable (low pre-episode relative vol → shallower trough, ρ +0.44); the **timing** legs
are unpredictable (ρ ≈ 0).
**Conclusion**: label-level axis to stack on RS. The live-usable slice collapses to a
defensive low-relative-vol tilt; park live timing prediction. Caveat: 6 episodes, 2008/2020 dominate.

### G. §5 — The equity fan ("plot B")
**Asked**: show every start-day's basket path overlaid — what do the gates actually do to the fan?
**Tested**: `basket_paths` per-start-day engine (top-5, per-name 15% stop-loss applied at the
single-name level then equal-weight aggregated), 2×2 = regime gate × calibrated-score gate.
**Found**: bull-start fans are tight and drift up; bear-start fans are wide. The regime gate's
entire value is **removing the wide bear fan** (it can't tighten the bull fan); the score gate
barely moves the fan shape.
**Conclusion**: fan width is a regime property. Confirms cone-not-point and the governor arc.

### H. Synthesis
1. Selection edge = tail phenomenon at strong-RS × small-cap (median inverts; liquidity-capped).
2. Downside = regime; SPY-200d is the one gate with an honest exchange rate.
3. Score gate = conviction/tail instrument (more mean, more HR, more variance — not safety).
4. Breakout supply = coincident regime gauge (state expression, not a brake).
5. Trough-geometry & sector = label-level enrichments; live prediction parked.

### I. §6 — The follow-up round (same day)
The five questions raised in review were each run to a verdict (details below; visuals in
notebook §6a–§6e). Net effect on the synthesis: **nothing above changes** — two kills confirmed
the existing structure (gradient, sector sizing), two threads upgraded their measurement without
changing the conclusion (geometry → rel_ulcer; per-name SL → variance knob), and the industry
audit explained the model's weight structure rather than indicting it.

---

## Follow-up closures (2026-07-11 — all five closed)
- (a) ❌ CLOSED (2026-07-11): the EMA-share GRADIENT does not lead. Lead/lag scan (grad10/grad20
  of EMA20, MACD-style E20−E60, 2nd derivative): ρ vs SPY fwd{5..100} all ≈ −0.09→0.00 — LESS
  predictive than the level itself (level ρ −0.18 at h=100, mild mean-reversion). Start-day
  buckets: grad10 vs top-5 fwd100 ρ +0.01 (all days), +0.02 (above-200MA guard) — no monotone
  separation. The mid-calm-peak observation is real but weak (gradient peaks ~15d into bull
  states, ρ −0.11). The LEVEL's famine pocket remains the payload: above-200MA ∧ bottom-share-
  quintile = mean +10.8% / HR 17% vs +4.1% / 9% at the flood end. Sizing test not warranted;
  supply gauge stays a state EXPRESSION (level, not gradient).
- (b) ❌ CLOSED (2026-07-11): sector-conditional sizing killed. Within the score-gated pool the
  per-sector home-run ranking is era-UNSTABLE (2-era spearman +0.26 p=0.43; 4-era mean pairwise
  +0.14; Comm-Svcs flips rank 1→10). Control: the UNGATED breakout pool ranking is stable (+0.65)
  — the gate already absorbs the persistent sector-tail component (consistent with §3b2 ρ≈0.90);
  what's left per-sector is noise. Monetization of the fat tail = exits (R3, done) + breadth
  (widening top-N within the gated pool — still untested), NOT sector selection.
- (c) ✅ CLOSED (2026-07-11): permutation-at-scoring audit (552 sampled days, 12.6k breakout
  rows, prototype model, within-day shuffles). Permuting `industry` is the ONLY ablation that
  degrades deployed metrics (top-5 HR −1.1pp, mean −0.5pp, |Δscore| 0.058); permuting the ENTIRE
  RS family or momentum block does nothing (±0.1pp) — that information is redundant across
  collinear features. Verdict: the 29% total_gain is partly cardinality bias (true unique effect
  is modest), but `industry` is the model's only NON-redundant block — it carries unique tail
  information (the §3b2 sector-tail pricing, at industry grain). The "shaky rank" concern
  re-lands: within-day ranking on the breakout pool is ~zero ρ regardless (known weak-ranker);
  the model's value is the TAIL SPLIT and industry is its largest unique contributor.
  RS-spirit feature engineering would add redundancy, not edge — thread closed, no retrain
  warranted. Notebook cell added (§6e).
- (d) ✅ CLOSED (2026-07-11): geometry re-quantified with published metrics (8,031 name-episodes,
  6 episodes). **rel_ulcer** (name/SPY Ulcer Index — the rectangle's true integral) is the best
  label on BOTH axes: grades fwd100 at ρ=−0.19 (vs rectangle depth −0.145, trough-lead +0.131)
  AND is the most predictable (pre-episode relvol → rel_ulcer ρ=+0.50, vs +0.39 for rectangle
  depth). The physics legs die: recovery velocity and half-life decay grade nothing (ρ≈0) and
  nothing predicts them; downside-beta/beta-asymmetry add nothing over plain relvol. Incremental
  to RS: within every RS tercile rel_ulcer grades the MEDIAN monotonically (strong-RS row +1.5%
  shallow → −8.8% deep; ρ −0.13/−0.20/−0.26, strongest where RS is strongest), and the LIVE
  relvol version reproduces it (+0.4% → −6.6%). Caveat: home-run rate mildly INVERTS (deep-trough
  keeps lottery tails) — geometry is a **defensive/median axis, the mirror of RS×size's tail
  axis**. Live-usable slice = low pre-episode relative vol, now with a stronger justification.
  Notebook cell added (§6c).
- (e) ✅ CLOSED (2026-07-11): per-name SL confirmed in the engine (`_name_path` stops each name
  and freezes to cash, then aggregates — the requested design). SL-sweep run (935 deployed
  start-days, governor ON, horizon 150): sl5% median −0.2 / mean +5.6 / p10 −5.0 / loss 51% /
  std 17; sl15% +3.9 / +8.5 / −15.0 / 41% / 25; no-stop +7.8 / +11.0 / −18.1 / 35% / 29.
  **The per-name stop is a VARIANCE knob, not an alpha knob** — 5% halves fan width but whipsaws
  the majority out and costs half the mean; same shape as the governor (DD control paid in
  median). Notebook cell added (§6a). Caveats: close-only stop booked at the stop level
  (optimistic for tight stops, cf `project_backtest_stop_gap_fill`); stopped capital stays
  frozen in cash (no re-deployment).
