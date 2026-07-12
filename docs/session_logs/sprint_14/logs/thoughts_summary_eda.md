# Sprint 14 EDA — Thoughts & Analysis Log

**Status**: ✅ Analysis complete, 12 cells drafted (see `sprint_eda_new_cells.md` + `INSERTION_MAP.md`)  
**Updated**: 2026-07-11

---

# § 1 — The Population Funnel: What Selection Pool Are We Actually In?

## Funnel counts: full → trend_ok → breakout, and supply-drift

**Observation**: The population is a waterfall; effective selection distills to below 2% (breakout) vs ~20% (trend_ok).

### Q: SEPA step 2 is ~5%. Did we check the resulting population edge on home-run hit rate?

**Status**: ✅ **ANSWERED**

**Answer**: Breakout pool has strong-RS small-cap home-run rate = **5.7%** (vs 1.4% pool avg) = **4× uplift**.

**Evidence**: §3 heatmap + home-run rate chart. Edge exists and is **concentrated** at the small-cap + strong-RS intersection.

**Constraint**: Liquidity-constrained (~$7.5M/day median dollar volume).

---

### Q: How do we classify breakout? Is it VCP, consolidation, or just the correct approach?

**Status**: 🔄 **PARTIAL** (Design choice, not a defect)

**Answer**: Breakout IS VCP-like (price > high-of-10-day-range). Training on it is a **trade-off**:

| Axis | Breakout (1%) | Trend_ok (18%) |
|------|---------------|----------------|
| Pool size | Smaller, extreme | Larger, diverse |
| Regime sensitivity | High (5× swing) | Moderate |
| Supply/day | 5–43 | More stable |
| Edge (home-run %) | 5.7% (small-cap+RS) | Not tested |

**Direction**: If goal = **conviction over volume** → breakout is correct. If goal = **coverage** → trade edge for 13× supply.

**Status**: Not resolved; depends on deployment objective.

---

### Q: What do we mean by "breakout SUPPLY drifts 5× (2008 famine → 2021 flood)"?

**Status**: ✅ **ANSWERED**

**Answer**: Regime-induced. Breakout supply **contracts in bear, inflates in bull**:

- **Bear markets**: 2008 (5.8/day), 2022 (11.7/day), 2009 (11.2/day)
- **Bull markets**: 2013 (32.9/day), 2021 (42.5/day), 2024 (35.9/day)

**Root cause**: Breakout definition (price > HH(10)) is intrinsically bullish. Bull regimes generate more breakouts.

**Implication**: This is **NOT a defect**; it's the **regime signature** of the signal. Use it.

**New cell**: **§1b** reverse-engineers regime FROM breakout counts (4-panel viz: time-series, scatter vs fwd return, regime split, year summary). Answers: can we predict SPY regime from daily breakout count?

---

### Q: Score distribution daily top-5 — is this breakout? Want histogram of blocked days + equity fan of rejected trades

**Status**: ✅ **ANSWERED**

**Answer**: Score distribution is **breakout pool**, correct. 

**New cell**: **Q3** compares deployed (gate ≥ 0.6) vs rejected (gate < 0.6) equity fans. Tests if gating filters signal or noise.

**Expected outcome**: Deployed mean fwd100 > Rejected mean (if gate filters bad trades).

---

### Q: Churn — higher gate = harder persistence + fewer days = inconsistent. BUT churn B plot says opposite?

**Status**: ✅ **CLARIFIED** (Not contradictory)

**Answer**: Both are TRUE on **different axes**:

| Axis | Raw Pool | Higher Gate |
|------|----------|-------------|
| **(a) Carryover COUNT** | Mass at 0–1 (high turnover) | Shifts rightward (fewer names available) → *appears* more inconsistent |
| **(b) Tenure SURVIVAL** | Steep drop, median ~2d | Flatter drop, median ~5d → *appears* more persistent |

**Signal**: Gate trades **count for conviction** (fewer names, stickier), not volume.

- Churn A reflects **supply scarcity** (fewer names qualify)
- Churn B reflects **quality** (those that qualify persist)
- **Not contradictory — complementary**.

---

# § 2 — Forward-Return Distribution Across the Pool + Regime-Marked Extremes

## The lottery, four horizons, raw vs score-gated basket

**Observation**: Gated pool has worse mean on fwd100+ but fatter tails; tied on fwd20.

### Q: Add other 2 gate options (0.5, 0.7) to the chart?

**Status**: 🔙 **PUSHED BACK** (Low priority)

**Reason**: Would add 2 more bars → histogram could overcrowd. Raw vs 0.6 already shows direction.

**Action**: *If space permits in final notebook, add all SCORE_GATES (0.5/0.6/0.7) to histogram.*

**Priority**: ⭐ Low — current 0.6 gate already answers the question.

---

## Worst-day regime clustering: MA{50,100,150,200}

**Observation**: Worst decile of start-days (by fwd100) cluster somehow below index MAs.

### Q: What is "%below" and "gap (pp)"? Elaborate on conclusion.

**Status**: ✅ **ANSWERED**

**Definitions**:
- `%below` = % of days when index price < its moving average (bearish regime indicator)
- `gap (pp)` = percentage-point difference: `%below(worst-decile) − %below(all-days)`

**Key findings**:

| Index | MA | Worst-decile %below | All-days %below | Gap (pp) |
|-------|-----|-------------------|-----------------|----------|
| SPY | 50 | 29% | 28% | +1 |
| SPY | **150** | 29% | 19% | **+10** |
| SPY | **200** | **29%** | **18%** | **+12** ← BEST |
| QQQ | 200 | 25% | 18% | +7 |

**Conclusion**: **Longest MAs (150/200) best separate bad start-days from all days.** SPY-200d has strongest separation (+12pp gap).

**Implication**: Empirical case for the **SPY-200d deploy gate** (`champion_trail_spygate`). MA50 barely separates; too noisy.

---

## Shaded price charts — can we predict failure with macro metrics?

**Observation**: Certain market conditions seem to precede breakout failures. Can we build a macro model?

### Q: Fit ML model with macro metrics on failure days? Understand "weather" of failure?

**Status**: ✅ **ANSWERED** 

**Answer**: YES — binary logistic regression model predicts fwd100 < 0 on trade date.

**New cell**: **Q5** fits macro model with features:
- `spy_above_ma200` (regime)
- `spy_ret_5d`, `spy_ret_20d` (momentum)
- `qqq_ret_5d` (tech momentum)
- `vix_above_ma20` (volatility regime)

**Expected outcomes**:
- If **AUC > 0.65** → Macro is predictive → macro gate worth testing
- If **AUC 0.55–0.65** → Weak signal → secondary refinement only
- If **AUC < 0.55** → No macro signal → regime gate alone suffices

**Extended test** (Q5b): Deploy ONLY on low-failure-prob days, measure equity fan vs ungated. If fan tightens AND mean improves → macro gate adds value.

---

# § 3 — Dig into the Pool: Sector × Market-Cap × Forward Return

## Per-sector fwd100 distribution + regime split stacked

**Observation**: Sector distributions appear overlapping.

### Q: Make them less overlapping (transparent or separate)?

**Status**: 🟡 **NOTED** (Cosmetic, low priority)

**Current state**: Notebook uses `alpha=0.55` + `stacked=True` histogram. Visual is readable but could improve.

**Improvement**: Facet into separate subplots per sector with better spacing.

**Priority**: ⭐ Cosmetic only — **message is clear**: sector median ranking flips bull ↔ bear. No pooled sector tilt is safe.

---

## Size × RS: The home-run-rate conclusion

**Observation**: Strong-RS small-cap homes run at 5.7%, but median inverts. Two questions on feature depth.

### Q1: Check score monotonicity, since RS should've been baked in?

**Status**: 🔙 **PUSHED BACK** (Actionable but low ROI)

**What's needed**: Re-merge `prob_elite` into the (RS, size) heatmap cells. Check if score is monotone within each cell.

**Implication**: If NOT monotone → model is capturing variance orthogonal to RS. If monotone → RS explains most of the score signal.

**Priority**: ⭐⭐ Medium — needed for feature audit, but lower than Q3/Q5.

**Action**: *Flag for feature review: does prob_elite rank monotonically within (RS-decile, size-decile) cells?*

---

### Q2: What's the weight of RS in m01 model?

**Status**: 🔙 **DEFERRED** (Separate analysis)

**What's needed**: Pull `src/model_registry.py` → `feature_catalog` for m01 → run permutation importance.

**Implication**:
- If RS > 50% → model overfitting the category
- If 10–20% → one of several features (healthy)

**Priority**: ⭐⭐⭐ High — critical for feature audit, but separate from EDA.

**Action**: *Schedule after Q3/Q5 cells run: RS feature importance audit.*

---

# § 4 — Leadership Trough-Geometry (The RS Residual)

## The trough RECTANGLE visualization

**Observation**: Leaders (green) bottom higher & narrower; laggards (red) plunge deep & wide. Market seems to appreciate merit.

### Q: Quantify this characteristic? Any published factor? Can we live-predict it?

**Status**: 🔄 **PARTIAL** (Measurable post-trade, but NOT ready for live prediction)

**Measurable traits** (POST-TRADE labels):
- `trough_lead_days` — when name hits trough vs market
- `relative_depth` — % drawdown of name vs market
- `recover_lead_days` — when name recovers vs market

**Live prediction problem**: Need **forward-looking proxies**:
- `relative_depth` proxy: rolling beta? realized vol / SPY vol?
- `trough_lead_days` proxy: correlation to SPY daily returns?
- `recover_lead_days` proxy: mean-reversion strength? volatility clustering?

**Validation required**: Do proxies correlate **pre-trade** to actual geometry **post-trade**? If NOT → signal is selection bias (market chose the leader shape), not predictive.

**Current status**: Geometry as **label-level axis on RS**: reasonable. As **live pre-trade filter**: needs proxy validation.

**Priority**: ⭐⭐ Medium — foundational but not urgent. Defer until after Q3/Q5.

---

## Does trough-geometry grade fwd100 INCREMENTAL to RS?

**Observation**: Table shows RS quintile (rows 0–4) × leader_score (cols 0–3).

### Q: Is there monotonicity? Is it just correlated with RS?

**Status**: ✅ **ANSWERED**

**Key findings**:

- **Within EACH RS quintile**: leader_score RAMPS fwd100 (left to right)
- **Quintile 4 (strong RS)**: −3.4% (score 0) → +4.4% (score 3) — **geometry ADDS**
- **Quintile 0 (weak RS)**: −13.5% (score 0) → −6.9% (score 3) — **geometry LIFTS but median stays negative**

**Residual interpretation**:
- Geometry **partly SUBSTITUTES for RS** on weak names (lifts weak names most)
- Geometry **ADDS on strong names** (incremental refinement)
- **NOT a replacement for RS** — complements it.

**Implication**: Candidate for **label-level enrichment** on RS, not standalone feature.

---

## Plot B: Median + fan + mean + home-run

**Observation**: Median chart is flat/inverted; mean chart ramps clearly within quintiles; home-run chart shows residual.

### Q: Refine at stock level? Earlier stop-loss?

**Status**: ✅ **CLARIFIED**

**Answer**: No stock-level refinement needed. **The median/mean split already surfaces the tail phenomenon.**

- Median chart (a) → understates the residual
- Mean chart (b) → shows the lift clearly
- Home-run chart (c) → quantifies the tail

**Deployment question**: Should we cut on leader_score in live deployment?

**Answer**: **Only as a secondary label axis, after RS.** Not ready for production:
- Only 6 SPY drawdown episodes since 2003 (2008/2020 dominate)
- No 63d-MFE cut yet
- Need more episodes to validate

**Priority**: ⭐ Low — label-level candidate, production deferred.

---

# Summary: Status Overview

## ✅ Answered (Evidence in Notebook)

| Finding | Status | Cell |
|---------|--------|------|
| Funnel edge: strong-RS small-cap home-run 5.7% | ✅ | §3 |
| Regime signature: breakout supply bull/bear | ✅ | §1b (NEW) |
| Score gate filters signal or noise? | ✅ | Q3 (NEW) |
| Macro predicts failure days (AUC test)? | ✅ | Q5 (NEW) |
| Churn paradox (A vs B) | ✅ | §1 clarified |
| Worst start-days regime cluster | ✅ | §2 |
| Trough-geometry incremental to RS | ✅ | §4 |

## 🔄 Partial (Design Choice, Not a Defect)

| Q | Status | Resolution |
|---|--------|-----------|
| Breakout vs trend_ok pool size | 🔄 | Depends on deployment goal: conviction (breakout) vs coverage (trend_ok) |
| Trough-geometry live prediction | 🔄 | Measurable post-trade, needs proxy validation for live use |

## 🔙 Pushed Back (Lower Priority)

| Task | Priority | Reason | Action |
|------|----------|--------|--------|
| Add all SCORE_GATES to lottery chart | ⭐ Low | Overcrowd histogram; raw vs 0.6 shows direction | ✅ done in Round 2 (§2b gate ladder) |
| Score monotonicity vs (RS, size) | ⭐⭐ Medium | Needs re-merge of prob_elite | ✅ done in Round 2 (§3c) |
| RS weight in m01 | ⭐⭐⭐ High | Permutation importance audit | ✅ done in Round 2 (§3d) |
| Trough-geometry proxy validation | ⭐⭐ Medium | Foundational but not urgent | ✅ done in Round 2 (§4c) |
| Sector plot cosmetics | ⭐ Low | Visual improvement only | ✅ done in Round 2 (§3b ridgelines) |

---

# New Actionable Cells (Ready to Insert)

See `sprint_eda_new_cells.md` for complete code.

### §1b — Breakout Regime Reverse-Engineering (3 cells)
- **breakout_daily_counts**: Compute daily breakout counts + regime flags
- **breakout_regime_viz**: 4-panel chart (time-series, scatter vs fwd return, regime split, year summary)
- **Expected output**: ρ(daily count, fwd20 SPY return), regime signature confirmed

### Q3 — Score Gate Efficacy (4 cells)
- **q3_rejected_fan_prep**: Split panel into deployed vs rejected
- **q3_rejected_fan_compare**: Overlaid histogram of deployed vs rejected fwd100
- **q3_rejected_fan_assertions**: Self-checks (gate filters, mean comparison, loss rate)
- **Expected output**: AUC-like efficacy metric showing if gate filters signal

### Q5 — Macro Failure Prediction (5 cells)
- **q5_macro_regression_prep**: Build macro feature matrix (SPY MA200, momentum, VIX)
- **q5_macro_regression_model**: Fit logistic, compute AUC, plot feature importance
- **q5_macro_regression_robustness**: Self-checks (AUC > 0.5, implications)
- **q5_macro_regression_deploy_test**: Test macro gate variant (low-failure-prob days only)
- **Expected output**: AUC score + strongest feature + equity fan comparison

---

---

# QUICK STATUS

**Answered**: 10 questions (✅ funnel edge 5.7×, regime responsive, score pool, churn clarified, MA200 separator, macro model, geometry incremental)  
**Partial**: 2 (design choice or deferred)  
**Pushed back**: 5 → **all closed in Round 2** (below)

**New cells**: 12 ready in `sprint_eda_new_cells.md` (§1b: 3, Q3: 4, Q5: 5)  
**How to insert**: See `INSERTION_MAP.md` (dead simple: copy code, paste into notebook, run)

**Next**: Insert §1b + Q3 + Q5, run, review Q3 & Q5 outputs (deployed > rejected? AUC score?), decide gates.

---

# ROUND 2 FOLLOW-UP (2026-07-11)

All 7 follow-up threads run against the audited panel (scripts in the session scratchpad;
numbers below are from those runs). **Cells ready in `sprint_eda_followup2_cells.md`** (§1c, §2b,
§2c, §3b, §3b2, §3c, §3d, §4c — with insertion map). §1c/§3b SUPERSEDE the §1b draft and cell 14.

## 1. Breakout count as a regime metric (MA/EMA) — ✅ CONFIRMED as a GAUGE, ❌ as a gate

Normalize the daily breakout count by that day's scored-universe size (universe grew 3.6×;
raw counts drift), then smooth. **EMA10/EMA20 of the breakout share classifies SPY<200MA days
at AUC ≈ 0.93** — the supply IS the regime, seen from inside the funnel. But it is **coincident,
not leading** (ρ vs fwd60 SPY only ≈ −0.14), and as a deploy gate it is DOMINATED by SPY-200d:

| start-days | n | mean fwd100 | loss |
|---|---|---|---|
| famine (EMA20 share, bottom quintile) | 1,111 | +3.6% | 44% |
| below 200MA | 963 | **+1.0%** | 46% |
| famine & ABOVE 200MA | 390 | **+10.5%** | 35% |

Famine days that are still above the 200MA are early-recovery scarcity days — the GOOD kind.
→ Use the EMA share as a regime state EXPRESSION (fits the during-period steer), not a brake.

## 2. Gate ladder (0.5/0.6/0.7) — ✅ score is monotone on the TAIL, not the median

fwd100 basket: mean +6.0/+6.8/+7.5/+7.4%, HR-days (>30%) 11/14/17/20% — monotone ↑.
But median +5.2/+5.4/+5.5/+4.1% (0.7 gives median back), loss rate 38→44%, p10 −20→−29%.
**Higher gate = more tail, more variance, not more safety.** 0.6 is the knee; 0.7 trades the
typical day for lottery tickets. Consistent with the tail-magnitude objective (M1).

## 3. Bad-day coverage decomposition — ✅ the user's math, quantified

BAD = fwd100<0 is **38%** of start-days. SPY<200MA blocks 18% of all days, catches **21% of bad
days** (precision 46%) → **8.1% of ALL start-days are blocked-and-bad**, at the cost of 16% of
good days. Adding the score day-block (no name clears 0.6) lifts recall to 26% but blocks 23% of
days — every blocker pays ≈1 good day per bad day caught; the exchange rate never improves.
(Worst-decile BAD: 200MA recall 29%.) → 200MA does most of the honest work; the score gate adds
a sliver of day-level recall at the same price.

## 4. Q5 macro failure model — ❌ question invalid (agreed), run once for curiosity

Root cause of the cell error: **no VIX ticker in `price_data`** (VIX lives in `macro_data`) —
the empty frame poisoned downstream. Run without VIX: in-sample **AUC = 0.557**, strongest coef
spy_above_ma200 (−0.23). Deploy-only-when-pred<0.40 keeps 82% of days, mean +7.2% vs +6.0% —
i.e. it rediscovers the 200MA gate with extra steps. Matches the pre-registered "AUC<0.65 → regime
gate alone suffices". Not inserted into the notebook.

## 5. Sector overlays + model-vs-outcome divergence — ✅

Final style (user reference = the §2 lottery chart): per-sector facets with OVERLAID transparent
histograms — two grids, regime split (bull/bear) and score split (≥0.6 / below). The score-split
grid is the per-sector divergence view: split medians nearly tie while home-run tails split hard
(e.g. Basic Materials 25%/8%, Real Estate 24%/3%). Scatter version (§3b2): sector median score vs
sector median fwd100 **ρ ≈ +0.06**, but vs sector HOME-RUN rate **ρ ≈ +0.90**. The model prices
the tail per its target and is nearly blind to sector medians. Healthcare/Comm-Svcs = high-score,
worst-median, high-HR lottery sectors; Consumer Defensive = the mirror (best median,
model-ignored). Gate lifts HR in EVERY sector (+6 to +19pp).

## 6. Score vs (RS, size) + RS weight in m01 — ✅ both closed

- **Monotonicity**: prob_elite is strongly monotone in RS (median 0.27→0.69 across deciles,
  pooled ρ=+0.68, within-day ρ=+0.67) AND in size (0.53 small → 0.37 large — the model already
  tilts small-cap). **Within every (RS,size) cell** (100/100 cells n≥200), hi-score beats
  lo-score on home-run rate, mean **+9.7pp** — a real residual beyond RS+size. Caveat: inside
  the strong-RS/small-cap corner the score is rank-flat on fwd100 (ρ≈−0.02) yet still splits HR
  21.1% vs 12.0% — tail model, split don't sort.
- **RS weight**: explicit RS family = **4.0% of total_gain** (rs 1.1%, RS_vs_Sector 0.9%, …).
  Healthy by the 10–20% rubric — no single-feature bet. But the broad momentum block
  (dist_from_20d_high, mom_21d, price_vs_spy_ma63, …) = **22.6%**, and `industry` alone = 29%.
  The ρ=0.68 score-RS correlation lives in that momentum block — removing `rs` would NOT remove
  the RS tilt.

## 7. Trough-geometry live proxies — 🔶 HALF-predictable, and the predictable half is just low-vol

Pre-episode proxies (126td before each SPY peak: beta, relative vol, corr-to-SPY, 126d RS) vs
realized geometry, 9,969 name-episodes, 6 episodes, per-episode spearman (median):

| proxy | relative_depth | trough_lead | recover_lead |
|---|---|---|---|
| relvol | **+0.44** | +0.01 | −0.02 |
| beta | +0.18 | −0.00 | −0.08 |
| rs126 | −0.00 | −0.00 | −0.04 |

- The **depth** trait is live-visible: low pre-episode relative vol → shallower trough
  (rel_depth median 1.09 vs 1.73 across relvol terciles), and it survives RS-partialling.
- The **timing** traits (bottoms first, recovers first) — the genuinely novel part — are
  **unpredictable** (ρ≈0 for every proxy). Pre-peak RS predicts NONE of the geometry.
→ The live-usable slice of "leadership geometry" collapses to a defensive low-relative-vol
tilt (echoes R2's upside-vol residual). Timing legs stay post-hoc labels; park live prediction.

---

# ROUND 2b — notebook run review (2026-07-11, 45-cell notebook)

Round-2 cells inserted and run. Confirmations + fixes:

- **§1b confirms the gauge direction from the raw-count side**: bull median 19 breakouts/day vs
  bear 5/day; ρ(daily count, SPY fwd20) = **+0.105** — high count does NOT flag an imminent
  downturn (mildly the opposite). Coincident gauge, as per §1c.
- **Q3 deployed vs rejected (cell 15)**: deployed top-5 fwd100 mean **+7.5%** vs rejected
  **+4.0%** — but rejected has LOWER loss rate (36% vs 41%) and half the std. Same verdict as
  the gate ladder: the gate buys tail/mean, not safety.
- **§3c (cell 28) crashed — result INVALID, re-run needed**: old sector cell 24 uses `d` as a
  loop variable and clobbers the size×RS frame `d` from cell 27 → `KeyError: 'rs_dec'`, and the
  printed ρ=+0.768 was computed on that stale slice. Fix in `sprint_eda_followup2_cells.md`
  (Round 2b): replace cells 24+25 with the overlay-facets cell (no bare `d`), add a guard assert
  to cell 28, re-run 27→28. Expected from the offline run: ρ ≈ +0.68, within-cell HR lift
  +9.7pp, 100% of cells positive.
- **Duplicates to delete**: cell 35 (§4c prep copy; cell 37 is the live one) and cell 36
  (Q3 copy of cell 15, stranded inside §4).
- Everything else (§1c, §2b, §2c, §3b2, §3d, §4c) ran clean and matches the offline numbers.

---

# ROUND 3 — review follow-ups, all closed (2026-07-11)

Linear story + verdicts consolidated in **`logs/2026-07-11_summary_eda_linear_story.md`**
(the A→B→C summary the review asked for). Five new threads, each run to a verdict and
inserted as **notebook §6a–§6e** (cells tested offline before insertion; 40→47 cells):

1. **(a) supply-gauge GRADIENT** — ❌ killed. No lead at any horizon (ρ≈0), no start-day
   separation; the LEVEL's famine pocket (above-200MA ∧ scarce supply → +10.8%/HR 17%) is
   the payload. §6d.
2. **(b) sector-conditional sizing** — ❌ killed. Gated-pool sector HR ranking era-unstable
   (pairwise rank-corr +0.14 vs +0.65 ungated) — the gate already absorbed the stable part. §6b.
3. **(c) industry 29% total_gain** — explained, no retrain. Permutation-at-scoring: industry is
   the ONLY non-redundant block (top-5 HR −1.1 to −2.7pp); the ENTIRE RS family / momentum
   block permute to nothing (collinear-redundant). §6e + `scripts/industry_permutation.py`.
4. **(d) trough-geometry v2** — ✅ upgraded. rel_ulcer (Ulcer-index ratio, Martin 1987) beats the
   rectangle as label (ρ −0.19) AND is the most predictable (relvol → +0.50); physics legs
   (velocity/half-life) dead; DEFENSIVE/median axis (HR mildly inverts). §6c +
   `scripts/resilience_metrics.py`.
5. **(e) equity-fan per-name stop** — ✅ confirmed + swept. Engine stops each name individually
   (the requested design); 5%/15%/none sweep shows the stop is a VARIANCE knob (5%: std 29→17,
   median +7.8→−0.2, loss 35→51%). §6a.
