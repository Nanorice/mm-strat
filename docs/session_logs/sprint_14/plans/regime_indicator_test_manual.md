# Regime-Indicator Test Manual

**Compiled**: 2026-07-13 · **Purpose**: a hands-on lab notebook for testing each candidate coincident
regime gauge one at a time. Each section is self-contained: data needed, build steps, technical
knobs, assumptions, what "result" looks like, references, and a pre-registered evaluation protocol
so we don't move the goalposts after seeing the numbers.

> **Incumbent baseline to beat — RE-MEASURED ON THE fwd50 LABEL (2026-07-14).** The old 0.57/0.60
> figures were on fwd20 (gauge G); this manual's L1 label is **fwd50** (§0.2), so the baseline had to
> be re-run on fwd50 or every comparison is apples-to-oranges. Actual fwd50 pooled OOS AUC
> (`regime_gauge_train.py --horizon fwd50`, 2004-2025):
>
> | model | loss_mean | hostility |
> |---|--:|--:|
> | **SPY-200d baseline** | **0.531** | **0.541** |
> | logistic (multivar pillars) | 0.478 | 0.497 |
> | xgboost (multivar pillars) | 0.541 | 0.558 |
>
> - **The incumbent is barely above coin-flip (0.53-0.54), and the best multivariate model tops out at
>   0.56.** Longer horizon (fwd50 vs fwd20's 0.57) actually LOWERS day-level AUC — the regime signal
>   "grows with horizon" only in the *mean-gap* sense (Thread F), NOT in the *classification* sense.
> - BackTrader cone reference for `champion_trail_spygate`: median Sharpe **0.76**, floor **−1.93**,
>   %-neg folds **28%** (this is horizon-agnostic — it's P&L, not the fwd label).
> - The **cohort trade-gauge label** is the shared target; live in `regime_gauge_label.py` (fwd50
>   parquet already built: `gauge_label_fwd50_downside.parquet`).
>
> **⚠️ EXPECTATION-SETTING (read before setting hopes on Block A):** the feature CLASS caps near AUC
> 0.56 on this label. The **AUC ≥ 0.65 bar below is therefore a WALL, by design** — Block A is a
> *kill-gate we expect most candidates to fail*, not a hurdle we expect them to clear. This manual is
> the disciplined RETIREMENT of the regime-indicator lever, not a resurrection: the null result
> ("nothing beats SPY-200d") is the most likely and a fully acceptable outcome. Promotion via the
> P&L-based criterion (b)/(c) is the realistic path if any; AUC (a) is a long shot on purpose.
>
> **Universal kill criterion (pre-registered):** a candidate must clear AT LEAST ONE of —
> (a) OOS AUC **≥ 0.65** on the cohort bad-day label (a WALL — see above; incumbent is 0.53), OR
> (b) BackTrader 90-cell cone median Sharpe uplift **≥ +0.15** over `champion_trail_spygate`
>     WITHOUT losing more than −0.05 on the floor, OR
> (c) Cone max-drawdown reduction **≥ 20pp** with median Sharpe drop **≤ 0.10**.
> — otherwise it is a "no promotion" and gets banked as a curio.
>
> **STEP 0 (already done 2026-07-14):** re-baseline on fwd50 — the table above. Do NOT compare any
> candidate AUC to the old fwd20 0.57/0.60 numbers; use 0.531 (loss_mean) / 0.541 (hostility).

---

## Contents

- **§1 · HMM / Markov-switching regime posterior**
- **§2 · Realized-volatility targeting (Moreira-Muir / Barroso)**
- **§3 · SRISK / CATFIN systemic tail-risk nowcasters**
- **§4 · Market breadth (% above 200d, A/D, McClellan)**
- **§5 · NFCI / Financial Conditions Index**
- **§6 · Technical indicators on SPY/QQQ** (new — user request)
  - 6.1 Faster/adaptive MAs (KAMA, HMA, DEMA)
  - 6.2 ADX / trend-strength
  - 6.3 Donchian channel state
  - 6.4 Aroon oscillator
  - 6.5 SuperTrend
  - 6.6 Chandelier stop
  - 6.7 Bollinger bandwidth (vol regime)
  - 6.8 200d slope + distance
  - 6.9 QQQ-vs-SPY relative-strength as risk-on/risk-off
- **§7 · Suggested test order & how to combine**
- **§0 · Testing runbook — labels, splits, metrics, gates** ← **READ FIRST**

---

## §0 · Testing runbook — how to actually test each candidate

> Every §1-§6 section below points back here for the *how*. This section is the shared testing
> harness so results are comparable across candidates and no candidate gets a bespoke evaluation.

### 0.1 · What "regime" means operationally for THIS strategy

Our strategy is a **50-day forward-return, uptrend-conditional continuation** model (SEPA-gated
population; `trend_ok AND breakout_ok`; hold ~29d mean, exit-terminated). So a regime indicator is
"good" iff it distinguishes days on which **this specific label** — 50d forward return of names in
uptrend at time *t* — is systematically hostile vs benign. **This is not a general "bear market
detector"**; it is a "bad-day-for-my-continuation-strategy detector." Consequence: reuse of external
recession/crisis labels is only a **secondary sanity check**, never the primary bar.

### 0.2 · Labels (the target you predict / evaluate against)

Use **all four** labels for every candidate. If a candidate agrees on 3+ it's real; if it only works
on one, it's a fluke.

#### L1 · **Primary — strategy-native cohort bad-day label** (already built, `regime_gauge_label.py`)
- **Definition**: per date *t*, take the strategy's admitted cohort (`trend_ok AND breakout_ok`,
  ~650 names/day). Compute
  - `loss_mean_t = mean_i min(fwd50_i, 0)` (downside-only, weighted mean)
  - `hostility_t = fraction_i(fwd50_i ≤ −15%)` (tail concentration)
- **Binary target**: `bad_day = loss_mean_t in bottom-tercile of expanding distribution`.
- **Why 50d, not fwd20**: **user directive — our production model targets 50d fwd return.** ⚠️ NOTE
  the Thread-F "signal grows with horizon" is a *mean-gap* fact (stress-calm gap ×3 fwd20→100); it does
  NOT carry to day-level CLASSIFICATION — the fwd50 re-baseline (preamble) shows AUC actually FALLS
  vs fwd20 (0.53 vs 0.57). fwd50 is used because it's the production target, not because it separates
  days better. Don't expect the longer horizon to rescue a candidate's AUC.
- **Two variants**: `bad_day_lossmean` and `bad_day_hostility` — expected Spearman ~−0.95 (already
  verified). Report BOTH per candidate; if they disagree, prefer `loss_mean` (smoother).
- **Live-safe caveat**: the target is future by construction (fwd50). Fine for the CLASSIFIER — the
  live product is the feature at time *t*, not the label. Just no leakage in the FEATURE stack.
- **Class balance**: 33% positive by construction (bottom tercile).

#### L2 · **Strategy-native P&L label (the truth)** — backtest fold Sharpe
- **Definition**: 90-cell BackTrader cone on `champion_trail_spygate` produces per-fold Sharpe. A
  regime indicator that "works" should correlate with fold-average per-day nowcaster score.
- **Why include this**: L1 measures the *forward return distribution*; L2 measures what actually hit
  the P&L (with stops, gaps, slot rotation). Prior finding [[project_vec_engine_optimistic]]:
  label lift ≠ trade edge. If a candidate wins L1 but ties L2, it's a **label artifact** and gets
  banked, not promoted.

#### L3 · **Established external labels (sanity checks — NOT the bar)**
Use these to confirm your indicator is at least detecting known crises. Never promote on these alone.

| Label | Series | Frequency | Use as |
|---|---|---|---|
| **NBER recession** | FRED `USREC` | monthly, revised | Sanity: any indicator should catch 2001/2008/2020. |
| **Sahm Rule recession indicator** | FRED `SAHMREALTIME` | monthly | Real-time recession probability (Claudia Sahm 2019). |
| **SPX ≥ 20% drawdown (bear-market)** | Derived from SPY | daily | Peak-to-trough classical bear def. |
| **SPX ≥ 10% drawdown (correction)** | Derived from SPY | daily | Softer bar, more events (~1/yr avg). |
| **VIX regime (>25 for ≥5 days)** | CBOE VIX | daily | Elevated-vol clusters (Whaley 2000). |
| **Bry-Boschan turning points** | Computed | monthly | Peak/trough algorithm, standard business-cycle dating. |

**Derived-drawdown code** (canonical, use everywhere):
```python
spy_peak = spy_close.cummax()
dd_pct = spy_close / spy_peak - 1
in_bear = (dd_pct <= -0.20).astype(int)           # will be 1 for months after -20% until new high
in_correction = (dd_pct <= -0.10).astype(int)
```

#### L4 · **Realized-vol regime label** (independent axis)
- `rv_22d = std(spy_return, 22) * sqrt(252)`.
- `high_vol = rv_22d > expanding_median(rv_22d)` (binary) or top-quartile (stricter).
- Not the same as L1 — L1 is directional, L4 is magnitude. Some candidates (§2 vol-targeting, §6.7
  BBW) will fit L4 by design; report to check redundancy.

### 0.3 · Train/test split (universal — do not deviate per candidate)

- **Full history**: use the **maximum available span per feature**. Some features start later (CAPE
  2003, SRISK 2000, NFCI 1971). Truncate all comparisons to the shortest available candidate.
- **Walk-forward**: **anchored expanding, yearly** — train on all data ≤ year Y, score year Y+1.
- **Embargo**: **20 trading days** between train-end and test-start (removes fwd50 label leakage —
  50d fwd label at train-end contaminates the first ~50d of test; 20d is Chin et al. 2019 minimum
  for daily equity, but for our 50d target use **50d embargo**).
- **Retrain cadence for ML candidates**: quarterly (§1 HMM), yearly (§3-§5 XGB gauge).
- **Minimum train window**: 3 years / ~750 trading days before scoring begins.
- **First test year**: **2003** (post-dot-com; earliest date every candidate has ≥3y train).

### 0.4 · Metrics (report all, promote on the bar)

Per candidate, produce **all four blocks**. Use the tables literally.

#### Block A — Label-separation (L1)
| Metric | Definition | Bar |
|---|---|---|
| Pooled OOS AUC | Across all WFO folds, one AUC | **≥ 0.65** |
| Median fold AUC | Median across per-year folds | ≥ 0.62 |
| Worst-fold AUC | Min across folds | ≥ 0.55 (no fold worse than baseline) |
| AUC(crisis) | AUC restricted to years with SPY drawdown ≥ 20% | ≥ 0.65 |
| AUC(calm) | AUC restricted to years with max drawdown < 10% | ≥ 0.60 |
| Precision@op | At operating threshold, fraction of flagged days that were truly bad | ≥ 0.50 |
| Recall@op | Fraction of bad days flagged | Report vs SPY-200d |
| Cohen's κ vs SPY-200d | Agreement beyond chance | Report (want low = orthogonal info) |

**Operating threshold rule**: set threshold so the candidate flags the **same number of days** as
SPY-200d flags below the MA in the same fold. Apples-to-apples confusion matrix.

#### Block B — Bootstrap CI on AUC
- Day-**block** bootstrap. **Block length = 50 days** (NOT 20) — the block must be ≥ the label
  horizon (fwd50), or overlapping-label autocorrelation leaks across block boundaries and the CI is
  too tight (over-claims significance). This is the fwd50 analogue of the 20d-for-fwd20 rule. 1000
  resamples.
- Report 95% CI for pooled AUC and for AUC(crisis)−AUC(SPY-200d).
- **If CI on the DELTA includes 0**, indicator is not statistically better than SPY-200d.

#### Block C — Cone test (L2) — the promotion bar
Only run this if Block A passes. Otherwise banked as "feature-level positive, trade-level untested."

| Arm | Setup |
|---|---|
| Baseline | `champion_trail_spygate` (SPY-200d gate) |
| Candidate-only | Replace SPY-200d gate with candidate signal |
| Composed | SPY-200d **OR** candidate (union) — captures both regimes as risk-off |

- **Cone size**: 90 cells (18 start-quarters × 5 hold-years) — the standard.
- **Report**: median Sharpe, p25/p75, floor Sharpe, %-neg folds, agg maxDD, per-era medians
  (2003-07, 2008-09, 2010-14, 2015-19, 2020-22, 2023-26).
- **Promotion**: criterion (b) or (c) from the preamble.

#### Block D — Chop / crisis / rebound cell-level detail
Explicit cells to report every time (these were the pain points in prior threads):
- **2008-09 GFC** (crisis + rebound miss)
- **2011-08** (US downgrade)
- **2015-16** (chop, SPY-200d flipped 11×)
- **2018-Q4** (fast selloff)
- **2020 COVID** (crash + V-rebound)
- **2022** (rate-driven bear)
- Per cell: Sharpe, maxDD, days flagged risk-off, fwd50 top-5 basket mean.

### 0.5 · Two evaluation lenses — both required

**Lens 1: Nowcaster** (does it predict L1 on the day?) — Block A.
**Lens 2: Governor** (does it improve L2 when used as a gate/dial?) — Block C.

Prior threads proved these can diverge (governor: **beat SPY-200d on AUC-like metrics but killed
median Sharpe** on the cone). A candidate must pass Lens 2 for promotion. Passing only Lens 1 = a
diagnostic tag, not a strategy input.

### 0.6 · Feature engineering rules (uniform across candidates)

- **Normalization**: expanding-z, `.shift(1)`. No full-sample z, no all-time percentile. Anything
  else disqualifies.
- **Lag**: 1 business day minimum. Macro (FRED) 2 business days.
- **NaN policy**: forward-fill up to 5 business days for macro; longer = mark unavailable, do NOT
  impute.
- **Interaction features**: allowed only if the standalone version passes Block A first.
- **Signal count cap**: max **6 features** into any composite XGB, to control overfit vs the ~5,900
  daily rows OOS. Feature importance must be reported; anything with gain < 0.02 gets dropped.

### 0.7 · Runbook — the exact order of operations per candidate

Copy this checklist into the per-candidate verdict file. Nothing is optional.

```
[ ] 1. Data pull + persist (with source-of-record + date-of-pull noted).
[ ] 2. Live-safety checklist (Appendix) — as-of-date identity test PASSES.
[ ] 3. Feature compute — expanding-z, .shift(1), correct lag.
[ ] 4. Sanity plot — feature overlaid on SPY, 25y, annotate 6 crisis cells.
[ ] 5. Label join — L1 (loss_mean + hostility), L2-ready cache, L3 crises, L4 vol regime.
[ ] 6. Block A metrics — pooled/median/worst-fold AUC, calm/crisis split, confusion matrix.
[ ] 7. Block B — day-block bootstrap on AUC delta vs SPY-200d.
[ ] 8. GATE (if Block A pooled AUC < 0.62 AND worst-fold < 0.55): STOP, bank as null.
[ ] 9. Block C — cone A/B/C, three arms, 90 cells.
[ ] 10. Block D — 6 named cells, tabulated.
[ ] 11. Redundancy check — correlate with SPY-200d, credit_z, VIX, RV_22d.
       Kill if |ρ| > 0.85 with any incumbent AND no marginal AUC lift.
[ ] 12. Verdict — promote / bank / kill against the pre-registered criteria.
[ ] 13. Persist verdict as verdicts/YYYY-MM-DD_<name>.md following template §0.8.
```

### 0.8 · Verdict template

```markdown
# <candidate>: verdict

**Date**: YYYY-MM-DD · **Runbook**: §0.7 completed in full / partial (note where stopped).

## Setup
- Feature: <formula, params, source>
- Train span: <YYYY-YYYY> · Test span: <YYYY-YYYY> · Folds: N · Embargo: 50d.

## Block A — Label separation (L1)
| Metric | Value | Bar | Pass? |
| Pooled AUC | | ≥0.65 | |
| Median fold AUC | | ≥0.62 | |
| Worst-fold AUC | | ≥0.55 | |
| AUC(crisis) | | ≥0.65 | |
| AUC(calm) | | ≥0.60 | |

Confusion matrix @ matched-flag threshold vs SPY-200d: <table>

## Block B — Bootstrap CI
- Pooled AUC 95% CI: [ , ]
- Δ vs SPY-200d 95% CI: [ , ] · **Excludes 0? Y/N**

## Block C — Cone (L2)
| Arm | Median Sh | p25 | Floor | %neg | MaxDD |
| Baseline (spygate) | | | | | |
| Candidate-only | | | | | |
| Composed (OR) | | | | | |

## Block D — Named cells
<6-cell table>

## Redundancy
| vs | ρ | Marginal AUC lift |
| SPY-200d | | |
| credit_z | | |
| VIX | | |
| RV_22d | | |

## Verdict
- Passes: A / B / C / D (list)
- Fails: (list)
- **Decision**: PROMOTE / BANK / KILL
- **Reason**: <one paragraph>
- **Follow-ups**: <any>
```

### 0.9 · Common failure modes to watch for

From prior verdict archaeology — pre-check each candidate for these:

1. **Regime-only signal masquerading as all-weather** (stress composite, Q19 → Q20). Cure: always
   split AUC by SPY-200d state (calm/crisis rows separately).
2. **Look-ahead normalization** (Q17 vs Q20 halved the effect). Cure: as-of identity test in §0.7-2.
3. **GATE×TILT cancellation** (governor collapse to SPY-200d brake). Cure: report the *overlap* of
   candidate-flagged days with SPY-200d-flagged days. If overlap > 90%, the candidate ≡ SPY-200d.
4. **Label lift ≠ trade edge** (m01a M3/M4, RS-tail on the cone). Cure: **never promote on Block A
   alone**; Block C is compulsory.
5. **Chop years hide inside the aggregate** (2015-16 flip-11× problem). Cure: Block D always
   reported.
6. **Statistical illusion of significance at n=6000+ autocorrelated rows** (Kruskal-Wallis p≈0
   meaningless in Q20). Cure: only block-bootstrap CIs, never raw p-values.

---

## §1 · HMM / Markov-switching regime posterior

### Data needed
- SPY daily close, full history (already in `daily_prices`). Optional: SPY daily realized vol
  (compute from 5-min bars if available; else `abs(daily_return)`).
- Nothing else — this is a price-only model.

### Method to build
1. Compute daily log-return `r_t = ln(SPY_t / SPY_{t-1})`.
2. Fit a **2-state Gaussian HMM** on `r_t` (state 1 = "normal", μ≈+0.05%/day σ≈0.8%; state 2 =
   "crash", μ≈−0.15%/day σ≈2%). Use `hmmlearn.hmm.GaussianHMM(n_components=2, covariance_type='diag')`.
3. **Walk-forward**: retrain every quarter on the prior 5-10 years; score forward one quarter with
   `.predict_proba()` → daily `P(state=crash)`.
4. Output daily series `hmm_p_bear ∈ [0, 1]`. Persist to `regime_features_daily`.
5. **Coincident guard:** state labels flip in retraining — use posterior probs, NOT hard labels, and
   fix the "crash" state as the one with lower mean (`np.argmin(model.means_)`).

### Technical knobs (pre-register, don't tune)
- `n_components = 2`; a 3-state variant (bull / neutral / crash) is an ablation, not the primary.
- Retrain cadence: **quarterly** (weekly overfits, yearly is stale).
- Training window: **5 years** rolling (Nystrup 2018 default).
- Covariance: `diag`. Full-cov overfits at 1D.

### Assumptions
- Returns are conditionally Gaussian within a state (they're not, but 2 states + heavy tails is close
  enough — Ang-Bekaert).
- The Markov property (next state depends only on current) — violated at crisis onsets, which is why
  the effect concentrates at *sustained* bear phases, not turning points.
- Two states are enough. If the fit persistently assigns >5% of days to state boundaries, try 3.

### Result type
- Daily continuous `P(bear) ∈ [0,1]`.
- Derived: `hmm_bear_flag = P(bear) > 0.5` (for direct A/B vs SPY-200d).

### References
- Hamilton (1989) *Econometrica* 57 — original regime-switching.
- Ang & Bekaert (2002) *JBES* — 2-state on returns, state-classification benchmark.
- Kritzman, Page & Turkington (2012) *FAJ* — 60/40 Sharpe 0.44 → 0.71, DD −44% → −27%.
- **Nystrup, Madsen & Lindström (2018)** *Quantitative Finance* — closest analogue (daily, WFO,
  equity book). +0.15-0.30 Sharpe, 30-50% DD reduction OOS.

### Evaluation protocol
1. **Label separation:** join `hmm_p_bear` to the L1 cohort bad-day label (bottom-tercile **fwd50**,
   per §0.2 — NOT fwd20). Compute **pooled OOS AUC** and per-fold AUC over the standard §0.3 folds
   (first test year 2003, expanding yearly, 50d embargo) — not a bespoke 2012-2026 window.
   - Bar: **≥ 0.62** to be interesting, **≥ 0.65** to pass criterion (a). Incumbent is 0.53.
2. **Head-to-head vs SPY-200d:** confusion matrix at operating threshold (`p>0.5` vs `SPY<200d`).
   Report precision, recall, false-positive rate at crises vs calm years separately.
3. **Cone test (only if step 1 passes):** replace the SPY-200d gate in `champion_trail_spygate` with
   `hmm_p_bear < 0.4`. Run the 90-cell BackTrader cone. Judge on criterion (b)/(c).

### Expected effort
~half day: `hmmlearn` fit + WFO loop + AUC. Cone test is one more day if step 1 passes.

---

## §2 · Realized-volatility targeting (Moreira-Muir / Barroso)

### Data needed
- SPY daily close → daily returns (already have).
- Nothing else. Optional: intraday for a better RV estimate.

### Method to build
1. Compute `RV_22d = std(daily_return, 22 trailing days) × sqrt(252)`. Lag one day.
2. Define **target vol** `σ* = 15%/yr` (or the strategy's LT realized vol; keep constant, don't tune).
3. **Sizing weight**: `w_t = min(σ* / RV_22d, w_max)` where `w_max = 1.5` (cap leverage).
4. This is NOT a nowcaster — it's a **sizer**. It goes into `macro_sizer.py` as a new `--sizing
   vol_target` mode.
5. **Composition with SPY-200d gate:** multiply. `final_exposure = spy_gate × vol_target_weight`.

### Technical knobs (pre-register)
- RV window: **22 days** (Moreira-Muir default). 5d is too noisy; 63d too laggy.
- Target: **15% annualized** — matches SPY's long-run vol; no fitting.
- Cap: **1.5×** (no naked leverage; matches Barroso).
- Lag: **1 business day** (live-safe).

### Assumptions
- Vol is more persistent than returns (**true, well-documented** — ARCH effect, half-life ~10 days).
- The vol-return relationship is mostly linear in `1/σ` (Moreira-Muir assumption); minor departures
  don't kill the effect.
- The strategy's edge does NOT concentrate in high-vol days. **This is the risk** — if SEPA's
  best days ARE high-vol rebounds, vol-targeting will hurt (same trap as the governor). Pre-check
  by regressing top-5 fwd100 on RV_22d in-panel.

### Result type
- Daily `vol_target_weight ∈ [0, 1.5]`.
- Composed exposure fed to `equity_curve()` — same interface as the governor.

### References
- **Moreira & Muir (2017)** *JF* — Mkt Sharpe 0.42→0.53, Momentum 0.53→0.85.
- **Barroso & Santa-Clara (2015)** *JFE* — momentum Sharpe 0.53→0.97, maxDD −79%→−45%. **Most
  relevant** — momentum is your closest cousin.
- Cederburg et al. (2020) *JFE* — OOS attenuation warning; mom effect largely survives, market
  effect halves.

### Evaluation protocol
1. **In-panel sanity check:** regress top-5 daily fwd100 on `RV_22d_lag1`. If slope is *positive*
   (edge concentrates in high-vol days), STOP — vol-targeting will destroy the strategy. Governor
   showed this partially (bear-stress had good mean, bad tail).
2. **Cone test:** wire `--sizing vol_target` in `macro_sizer`. Run 90-cell BackTrader cone. Compare
   to `champion_trail_spygate` (SPY-gate only) and the governor.
3. **Composed variant:** SPY-gate × vol-target. This is the version with published precedent
   (Barroso + a trend filter).

### Expected effort
~1 day: 30 lines in `macro_sizer.py`, reuse the cone runner. **Highest priority** — strongest
published evidence for a momentum/continuation strategy.

---

## §3 · SRISK / CATFIN systemic tail-risk nowcasters

### Data needed
- **SRISK**: pull daily from NYU V-Lab (`https://vlab.stern.nyu.edu/srisk`, CSV export, free).
  Aggregate US SRISK ($bn).
- **CATFIN**: monthly, computable from CRSP financials tail-VaR — expensive to build; skip unless
  §1-2 both fail.
- Optional: SPX equity vol premium (VIX − RV_22d) as a cheaper proxy.

### Method to build
1. Ingest SRISK daily series → `macro_data` table under `series='SRISK_US'`.
2. Compute `srisk_z = expanding_z(SRISK_US)`, `.shift(1)` for live-safety.
3. **DO NOT** re-do the univariate correlation study — that already exists in `entry_timing_features`
   and it collapses into credit. **Only test as a residual on top of credit.**
4. Add `srisk_z` as feature #7 to `regime_gauge_train.py`. Re-run walk-forward XGB. Compare feature
   importance vs credit; check if AUC lifts.

### Technical knobs
- Normalization: expanding-z, `.shift(1)`. Same protocol as your stress composite.
- No new hyperparams for the XGB (locked from gauge G).

### Assumptions
- SRISK's coincident info about *bank* stress is priced into HY credit spreads with a 0-5 day lag.
  So residual over credit is expected to be **small**.
- V-Lab's methodology is stable — they occasionally revise historical series. Snapshot the pull.

### Result type
- Daily `srisk_z` feature; AUC lift or not.

### References
- **Brownlees & Engle (2017)** *RFS* — SRISK methodology; AUC ~0.85 for NBER recessions (but
  monthly, not daily-equity).
- Allen, Bali & Tang (2012) *RFS* — CATFIN, monthly.
- Adrian, Boyarchenko & Giannone (2019) *AER* — NFCI/FCI vulnerable-growth.

### Evaluation protocol
1. Add feature to gauge G XGB. Retrain WFO. **Expected AUC lift ≤ 0.02**.
2. If lift < 0.02: bank as "collapsed into credit"; done.
3. If lift ≥ 0.02: re-run cone as a two-feature gate (SPY-200d OR srisk_z>threshold). Judge
   criterion (c).

### Expected effort
~half day. Low expected value; only run if §1+§2 both underdeliver.

---

## §4 · Market breadth (% above 200d, A/D line, McClellan)

### Data needed
- **Already have.** Compute daily from `daily_prices` + `t3_sepa_features`.
- Universe: same universe your strategy screens (t3 SEPA population, ~5000-8000 names). Alternative:
  full CRSP.

### Method to build
1. **Pct above 200d**: `breadth_200d = mean(close > SMA200)` across the universe, daily.
2. **Advance-decline line**: `AD_line = cumsum(#advances − #declines)`. Then `ad_line_slope_20d`.
3. **McClellan Oscillator**: `MO = EMA19(A−D) − EMA39(A−D)`. Live-safe by construction (EMA past-
   weighted).
4. **New-highs vs new-lows**: `HL_ratio = (52w_new_highs − 52w_new_lows) / total`.
5. Persist all four as daily features. Add to `regime_gauge_train.py`.

### Technical knobs
- Universe filter: apply the same liquidity floor your strategy uses (dollar-vol > $1M) — breadth
  from micro-caps is noise.
- All rolling windows locked (200d, 19/39d for McClellan — standard).

### Assumptions
- Breadth divergences precede/coincide with market turns — **well-documented for 90+ years**.
- Your universe (SEPA-liquid) is representative of the market. If your universe is small-cap-tilted,
  breadth will lead SPY-200d (small caps roll first) — a **feature not a bug** for this test.

### Result type
- Four daily continuous features; expected to add ≥ SRISK to gauge G's AUC.

### References
- Chen (2009) *JBF* — A/D beats term-spread & VIX for bear-market prediction (AUC 0.71 vs 0.66-0.68).
- **Zakamulin (2015)** *JAM* — pct-above-200d as regime filter on trend strategy: **Sharpe
  0.35→0.52, DD −15pp**. Most directly analogous.
- Zweig (1994) *Winning on Wall Street* — original breadth-thrust construction.

### Evaluation protocol
1. Add all 4 features to gauge G XGB. Retrain WFO. **Bar: AUC lift ≥ 0.03**.
2. Feature importance report: which breadth measure carries the signal? (Prediction: `breadth_200d`.)
3. **Direct A/B**: replace SPY-200d gate with `breadth_200d > 50%` gate in `champion_trail_spygate`.
   Run cone. This is the sharpest test — does market-internal breadth beat the SPY price gate on
   the honest engine?
4. **Chop-year focus:** report the 2015-16 and 2018 cells specifically. The user's Q60 identified
   these as where SPY-200d flipped 11× — breadth is the natural fix.

### Expected effort
~1 day (data compute is cheapest of all candidates — already have raw). **Second priority after
vol-targeting.**

---

## §5 · NFCI / Financial Conditions Index

### Data needed
- FRED series `NFCI` (weekly, free). Optional: `ANFCI` (adjusted for GDP/inflation).

### Method to build
1. Pull weekly, forward-fill to daily, `.shift(1)`.
2. `nfci_z = expanding_z(NFCI)`.
3. Add to gauge G. Same protocol as SRISK.

### Assumptions
- NFCI is a proper PCA-weighted composite of 100+ series → should subsume individual pillars.
- Weekly cadence means it lags intra-week vol spikes by ~3 days.

### Result type
- Daily `nfci_z`; AUC lift most likely ~0.

### References
- Hatzius et al. (2010) NBER WP.
- Brave & Butters (2011) Chicago Fed *Economic Perspectives*.

### Evaluation protocol
Same as SRISK. **Expected lift 0.00-0.02**. Run only if a "does the professional composite beat our
homemade stress?" answer has independent value.

### Expected effort
~2 hours. Skip unless completeness matters.

---

## §6 · Technical indicators on SPY/QQQ

The regime literature is macro-heavy, but a **price-based technical indicator** on the index has three
advantages here: (a) coincident by definition, (b) no macro data dependency / release lag, (c) directly
falsifiable against the SPY-200d incumbent because they're on the same series. This is where a
practitioner's fastest wins usually come from.

**All §6 features are computed on SPY (primary) and QQQ (secondary — tech-leadership proxy). Same
formulas, two series.**

### 6.1 · Adaptive moving averages (KAMA, HMA, DEMA)

**Motivation:** SPY-200d is a *lagging* SMA. Adaptive/faster MAs reduce turn-detection lag at the cost
of more whipsaws. The question: is there a variant that shortens the lag *without* multiplying
whipsaws?

- **Data:** SPY daily close.
- **Build:**
  - **KAMA** (Kaufman Adaptive MA): `talib.KAMA(close, 30)`. Auto-adjusts smoothing to volatility.
  - **HMA** (Hull MA): `HMA_n = WMA(2·WMA(n/2) − WMA(n), sqrt(n))`. Faster, less lag than EMA.
  - **DEMA** (Double EMA): `2·EMA(n) − EMA(EMA(n))`. Cancels first-order lag.
- **Knobs:** Test three periods each — 50 / 100 / 200. No further tuning.
- **Assumptions:** Adaptive doesn't add regime info the SMA doesn't have; but it changes *when* the
  info arrives. Tradeoff is signal-to-noise at turns.
- **Result:** Daily `close > MA` boolean per variant.
- **References:** Kaufman (1995) *Smarter Trading*; Hull (2005); Zakamulin (2016) *JPM* comparing MA
  variants for trend strategies — finds **negligible Sharpe difference across variants**, but
  DEMA/HMA cut turn-lag ~30%.
- **Evaluation:** Direct A/B: replace SPY-200d gate with each variant, run cone. **Bar: any variant
  that lifts floor by ≥ 0.15 without dropping median > 0.05.**
- **Expected effort:** 2 hours (`talib` one-liners + cone re-run).

### 6.2 · ADX / trend strength

**Motivation:** SPY-200d is directional (above/below) but says nothing about whether the trend is
*strong* enough to trade. ADX quantifies trend intensity irrespective of direction.

- **Data:** SPY OHLC daily.
- **Build:** `adx = talib.ADX(high, low, close, timeperiod=14)`. Range 0-100.
  - Rule: `trending = ADX > 25`; `chop = ADX < 20`.
- **Knobs:** `timeperiod=14` (Wilder default). Thresholds 20/25 (Wilder default).
- **Assumptions:** ADX conflates uptrend and downtrend strength — combine with SPY-200d for direction.
- **Result:** Daily continuous `adx_14` + binary `is_trending`.
- **References:** Wilder (1978) *New Concepts*. Modern: Ilinski (2001) — ADX+MA combo lifts Sharpe on
  index-timing 0.4→0.55.
- **Evaluation:** Two-lever gate: enter only if `SPY>200d AND ADX>25`. Cone A/B vs 200d-only. **Chop
  years (2015-16) are the key test cells** — ADX < 20 during those and the gate would have flattened.
- **Expected effort:** 3 hours.

### 6.3 · Donchian channel state

**Motivation:** "New N-day high" is the classic breakout regime signal (Turtle Traders). Nowcasts
"trend is alive" without an MA lag.

- **Data:** SPY high/low daily.
- **Build:** `dc_high_20 = rolling_max(high, 20)`; `dc_low_20 = rolling_min(low, 20)`.
  - `dc_pct = (close − dc_low_20) / (dc_high_20 − dc_low_20)`. Continuous [0,1].
  - Regime: `dc_pct > 0.7` = uptrend; `< 0.3` = downtrend.
- **Knobs:** 20 (short), 55 (Turtle mid), 252 (long-term). Test all three.
- **Assumptions:** SPY isn't range-bound long enough to make the "channel" meaningless (verify:
  should be true 80%+ of days).
- **Result:** Daily `dc_pct`, three horizons.
- **References:** Faith (2003) *Way of the Turtle*; Clenow (2013) *Following the Trend* — long-only
  Donchian on futures Sharpe 0.7.
- **Evaluation:** As a nowcaster in gauge G AUC test. As a gate in the cone (replace SPY-200d with
  `dc_pct_252 > 0.5`).
- **Expected effort:** 2 hours.

### 6.4 · Aroon oscillator

**Motivation:** Measures **time since** new high/low. Elegant chop detector — Aroon Up and Down both
low = choppy range.

- **Data:** SPY OHLC daily.
- **Build:** `aroon_up, aroon_down = talib.AROON(high, low, timeperiod=25)`.
  - `aroon_osc = aroon_up − aroon_down`. Range [-100, +100].
- **Knobs:** `timeperiod=25` (Chande default).
- **Assumptions:** Time-since-extreme is a stationary measure of trend age.
- **Result:** Daily `aroon_osc`.
- **References:** Chande (1995) *Stocks & Commodities*.
- **Evaluation:** Feature into gauge G; standalone gate test unlikely to beat 200d.
- **Expected effort:** 1 hour.

### 6.5 · SuperTrend

**Motivation:** ATR-based trailing regime line. Whipsaw-resistant version of SMA. Widely used by
practitioners; sparse academic evidence but strong practitioner track record.

- **Data:** SPY OHLC daily.
- **Build:** `ATR_10 = talib.ATR(h,l,c,10)`; `mid = (h+l)/2`. `upper = mid + 3·ATR_10`,
  `lower = mid − 3·ATR_10`. Flip logic: line follows price, only ratchets in trend direction.
  Reference implementation in `pandas_ta.supertrend`.
- **Knobs:** ATR period 10, multiplier 3 (Olson default). 14/2 is more sensitive.
- **Assumptions:** ATR-scaled bands are more regime-appropriate than fixed-price bands.
- **Result:** Daily binary `supertrend_up`.
- **References:** Olson (2004); Lento (2007) *Journal of Applied Business Research* — ATR-based
  trailing rules beat SMA on turn detection.
- **Evaluation:** Direct swap for SPY-200d in the cone.
- **Expected effort:** 2 hours.

### 6.6 · Chandelier stop

**Motivation:** Sibling of SuperTrend; anchors to N-day high minus K×ATR. Used by Chuck LeBeau as a
regime-off flag.

- **Data:** SPY high, close.
- **Build:** `chandelier = rolling_max(high, 22) − 3·ATR_22`. Regime = `close > chandelier`.
- **Knobs:** 22 days, multiplier 3 (LeBeau default).
- **Result:** Daily boolean.
- **References:** LeBeau & Lucas (1999) *Technical Traders Bulletin*.
- **Evaluation:** Cone gate swap.
- **Expected effort:** 1 hour.

### 6.7 · Bollinger bandwidth (volatility regime)

**Motivation:** Not a directional signal — a **volatility state** signal. Narrow bands = calm; wide =
stress. Same axis as RV but visual/tradition. Complements §2.

- **Data:** SPY close.
- **Build:** `BBW = (upper − lower) / middle`, where BB = SMA20 ± 2·rolling_std(close, 20).
- **Knobs:** 20/2 (standard).
- **Result:** Daily continuous `bbw`.
- **References:** Bollinger (2001) *Bollinger on Bollinger Bands*.
- **Evaluation:** Feature into gauge G. Likely correlated ρ~0.8 with RV_22d — check redundancy
  before promoting.
- **Expected effort:** 30 minutes.

### 6.8 · 200d slope + distance-from-MA

**Motivation:** The SPY-200d gate is binary. Its **slope** (up-sloping vs down-sloping 200d) is a
richer state; its **distance** (pct-above) quantifies how deep in bull/bear you are.

- **Data:** SPY close.
- **Build:**
  - `sma200_slope = (SMA200_t − SMA200_{t-20}) / SMA200_{t-20}` (20d change in the MA level).
  - `pct_above_200d = SPY / SMA200 − 1`.
  - Combined regime: `strong_bull = above AND slope>0`; `weak_bull = above AND slope<0`;
    `weak_bear = below AND slope>0`; `strong_bear = below AND slope<0`.
- **Knobs:** slope window 20d (small; alt 60d).
- **Assumptions:** Slope adds curvature info the level doesn't have. Verified in your 2015-16 cell —
  SPY was flipping around 200d but the slope stayed near zero (chop marker).
- **Result:** Four-state categorical + two continuous features.
- **References:** Meb Faber (2007) SSRN — "A Quantitative Approach to Tactical Asset Allocation";
  slope variants of the 200d MA rule.
- **Evaluation:** **Highest-leverage §6 test** — it's a *strict refinement* of the incumbent. Add
  slope-conditioning to `champion_trail_spygate`: gate off in `weak_bull ∨ any_bear`. Cone A/B.
  Chop-year focus.
- **Expected effort:** 3 hours.

### 6.9 · QQQ-vs-SPY relative strength (risk-on/risk-off)

**Motivation:** Tech-leadership vs broad market. QQQ leading = risk-on; QQQ lagging = defensive
rotation, an early regime-off tell that precedes SPY-level turns.

- **Data:** SPY + QQQ daily close.
- **Build:** `qqq_spy_ratio = QQQ / SPY`. Then `rs_slope_63d`. Risk-on = `rs_slope > 0`.
- **Knobs:** 63d slope (a quarter). Alternate: SMA50 of the ratio, boolean cross.
- **Assumptions:** Tech-leadership is a stable proxy for risk appetite in the 2010-2026 regime. May
  break in a leadership rotation (2000-02 dot-com; the 2022 tech underperformance).
- **Result:** Daily continuous `qqq_spy_rs_slope`.
- **References:** Faber (2010) *The Ivy Portfolio* — cross-asset RS as regime; Antonacci (2014)
  *Dual Momentum*.
- **Evaluation:** Feature into gauge G. Standalone gate unlikely to beat SPY-200d given regime
  instability, but as a *feature* it's cheap.
- **Expected effort:** 1 hour.

---

## §7 · Test order — a STOPPING-RULE SEQUENCE, not a backlog

> **This is the key discipline (2026-07-14 review).** §1-§6 list 15 candidates ≈ 2 weeks of work.
> This is a *final try* on a lever we've falsified four independent ways — so run it as an
> **ordered sequence with a stopping rule**, NOT a checklist to grind. Do the two highest-prior
> candidates first; **if either PROMOTES (clears the cone via criterion b/c), STOP — you have your
> answer.** Only descend the ladder if the top candidates MISS. Most of the list is expected to be
> either killed at Block A or never reached. Killing the lever cleanly IS success.

### The ladder (stop at the first rung that promotes)

1. **§6.8 — 200d slope + distance. DO FIRST. Highest prior.** It is the ONLY candidate that is a
   *strict refinement of the incumbent* and it directly targets the one documented SPY-200d failure
   (2015-16 chop: SPY flipped 11× but the 200d slope stayed ~flat — the exact chop marker). If
   anything beats SPY-200d, it's SPY-200d-plus-slope. Cheap (3h). → cone A/B, chop-year focus.
2. **§4 — Breadth (pct-above-200d). DO SECOND. Real orthogonal info.** Market internals ≠ index
   price — the only genuinely *different* signal in the whole list, with published trend-strategy
   precedent (Zakamulin), and the data is already in hand. One honest cone A/B (breadth-gate vs
   SPY-gate) + the 2015-16 / 2018 cells.

   **↑ IF EITHER OF THE ABOVE PROMOTES, STOP HERE. ↓ Only continue if both MISS.**

3. **§2 — Vol-targeting. RECLASSIFIED: this is a SIZER, not a regime indicator.** It's the governor's
   sibling (VIX corr +0.87 with RV — [[project_entry_timing_macro_axis]]), and we already ran that
   experiment: the governor was a **DD-dial, not alpha**. Expect the same. So: (i) run its own §2
   in-panel pre-check first (regress cohort fwd50 on RV_22d — if slope > 0, STOP, it'll hurt like the
   governor's bear-stress tail); (ii) judge ONLY on criterion **(c)** (DD-reduction), NOT (b) (Sharpe
   uplift) — a pure sizer mechanically can't lift the mean. Skip Block A entirely (it's not a
   nowcaster). Do NOT re-litigate it as alpha.
4. **§1 — HMM. The one "new physics" candidate.** Only price-model with a genuinely different
   mechanism (latent-state persistence vs a threshold crossing). Medium effort. Run ONLY if §6.8+§4
   both miss and you want one more orthogonal shot before closing.
5. **BATCH — everything else into ONE gauge-G XGB re-train, or cut.** §3 SRISK, §5 NFCI, §6.1/6.2/6.5
   (MA-variant bakeoff), §6.3/6.4/6.6/6.7/6.9. The manual's own text predicts AUC lift ≤ 0.02 for most,
   and the feature class caps at 0.56 (preamble). Add them as features in a single retrain (half a day
   total) — that one run answers all of them via feature-importance + Δ-AUC. **§3 SRISK specifically:
   needs an external V-Lab pull (snapshot/repro burden) for a residual-over-credit it already expects
   to be ~0 — this is completeness theater; only pull it if the batch retrain shows a credit-shaped
   hole worth filling.** Do NOT build these as standalone cone candidates.

### How to combine (if two candidates individually pass)

- **NEVER stack more than 2 gates.** Every extra AND kills a real signal (you saw this: GATE×TILT
  cancellation collapsed the governor to just the SPY brake).
- Combination rule of thumb from your prior findings:
  - **1 gate for direction** (SPY-200d or breadth-based).
  - **1 dial for exposure** (vol-target or governor-style).
  - **Nothing more.** Additional filters shrink deployable days without lifting per-$-Sharpe.
- If two directional gates both pass individually, run them **in parallel arms** on the cone — don't
  AND them. Whichever wins the distribution is the promotion, the other gets banked.

### Reporting template (use per candidate)

For each candidate, produce a single-page verdict with:
1. AUC pooled + per-fold (bar 0.65).
2. Confusion matrix at operating threshold vs SPY-200d.
3. Cone: median Sharpe, floor Sharpe, %-neg folds, agg maxDD — **table format, three arms**
   (`champion_trail_spygate` / candidate-only / candidate ∪ SPY-gate).
4. Chop-year cells: 2015-16 and 2018 fold-level results.
5. Crisis-year cells: 2008, 2020, 2022 fold-level results.
6. **Verdict:** promote / bank / kill against the pre-registered criterion.

---

## Appendix · Universal live-safety checklist

Every candidate must pass BEFORE any evaluation:
- [ ] All rolling stats use expanding or trailing windows, `.shift(1)` applied.
- [ ] Publication lag applied for macro series (FRED = T+1 minimum).
- [ ] **As-of-date identity test**: recompute the signal ending at date `D`; compare to full-history
      value at the same date `D`. Zero mismatches required.
- [ ] Walk-forward retrains (if any ML) use expanding train + purge, no shuffled CV.
- [ ] Feature normalization (z-score, percentile) is expanding, never full-sample.

Any failure here = the candidate is disqualified regardless of headline AUC/Sharpe. This is the trap
that made the stress composite look "all-weather" until Q20 caught it.
