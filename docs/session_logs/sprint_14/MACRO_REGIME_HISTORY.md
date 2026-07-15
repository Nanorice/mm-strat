# Macro / Regime research — consolidated history, methodology & verdicts

**Compiled**: 2026-07-13 · **Scope**: every macro/regime instrument built or tested in this project —
M03, the dashboard pillars (5→6), the stress composite, the state label, the governor, and the
coincident trade-gauge. **Purpose**: one place that records *what we built, how we falsified/evaluated
it, and what survived.* Facts are cross-referenced to their source verdict.

> **The one-line takeaway:** across ~six independent instruments and three evaluation methodologies,
> **SPY-200d SMA is the only regime signal that shifts the trade distribution.** Everything richer
> (M03 trend score, the 6-pillar macro, the stress composite, VIX-sizing, a multivariate ML gauge)
> is either a no-op, a drawdown-control dial, or a weak contrarian tilt — never a per-day alpha gate.

---

## 1. The instruments (in order they entered the project)

There are **two entirely separate "macro regime" models** in this repo — a recurring source of
confusion, so pin it first:

| # | Instrument | What it is | Where it lives | Role today |
|---|---|---|---|---|
| A | **M03 regime score** | 3-pillar (Trend / Liquidity / Risk) composite → 0-100 → 5 categories (Strong Bull … Strong Bear) | `src/pipeline/m03_regime.py` → `t2_regime_scores` | Trend-STATE label + backtest position-sizing gate (regime 0 liquidates). **No entry-timing signal.** |
| B | **Dashboard macro pillars** | Independent macro-conditions gauge. **5-pillar** originally (VIX, Credit, Term, Rates, Net-Liquidity) → **6-pillar** once self-computed **CAPE_OURS** went live (valuation pillar) | `scripts/dashboard_utils.load_macro_pillars()` reads `macro_data` | Display context; **percentiles are look-ahead → NOT model-safe.** Raw levels feed research only. |
| C | **stress composite** (`stress_ew_vix`) | Live-safe distillation of B's value/stress pillars: expanding-z of `+credit −rates −cape +vix`, sign-aligned so higher = more stress | `entry_timing_features.py`; `macro_sizer._stress_ew_vix` | The honest, causal expression of the 6-pillar. Feeds the governor + weather gauge. A **weak bull-gated tilt.** |
| D | **M6 regime STATE label** | Rule-based coincident state: `bear = SPY<200d`; `bull-stress` (dd≥10% or stress-tercile); else `bull-calm` | `sprint_14/scripts/regime_state.py` → `regime_state_daily_*.parquet` | Model-agnostic join key for during-period analysis. **Bear/bull trunk solid; stress sub-split unsettled.** |
| E | **Regime governor** | Backtested sizing overlay: TILT up on top-quintile stress, GATE to zero below SPY-200d | `src/backtest/macro_sizer.py::governor_weight` (`--sizing governor`) | **Banked as a drawdown DIAL, not alpha.** Collapses to the SPY-200d brake in-engine. |
| F | **weather_gauge** (deploy posture) | Human-facing STAND ASIDE / DEPLOY / DEPLOY MORE / DEPLOY,TRIM-NEW from 200d + stress_high + breakout-supply | `src/weather_engine.py`, Phase 7.45 → `weather_gauge` table | Display product. Not wired into the backtest. |
| G | **coincident trade-gauge** | Supervised ML nowcaster: multivariate logistic/XGBoost on live-safe pillars → P(bad breakout-day) | `sprint_14/scripts/regime_gauge_{label,train}.py` | **Falsified as a per-day gauge** (2026-07-13). No durable lift over SPY-200d. |

**SPY-200d SMA** itself is the seventh, simplest instrument — and the only one that survived every test
as *distribution-shifting*. It is the incumbent baseline every other instrument was measured against.

---

## 1b. Full specifications (readable without the code)

Each spec gives: **inputs** (the raw data series), the **exact formula**, the **output**, whether it is
**live-safe** (usable in real time without look-ahead), and its **source of record**. Raw series are
FRED tickers unless noted (VIX = CBOE, from `macro_data`).

### SPEC · SPY-200d gate (the baseline)
- **Input:** SPY daily close.
- **Formula:** `above_200d = SPY_close > mean(SPY_close, last 200 trading days)`. A single boolean.
- **Output:** on/off. In the backtest, `SPY ≤ 200d` → `available_slots = 0` (no new entries that bar;
  open positions keep running, exits still fire).
- **Live-safe:** yes — same-day close, no future data, ~zero free parameters (one window length).
- **Source:** `src/backtest/macro_sizer.py::spy_above_200d`; gate wired at `sepa_strategy.py:651`.

### SPEC A · M03 regime score
- **Inputs (3 pillars):** (1) SPY close vs its SMA-200; (2) Fed **Net Liquidity** = `WALCL − WTREGEN −
  RRPONTSYD` (Fed balance sheet minus Treasury General Account minus reverse-repo); (3) **VIX** level +
  **HY credit spread** (`BAMLH0A0HYM2`).
- **Formulas** (each pillar → 0-100, blended):
  - **Trend (40%)** = `50 + 50·tanh(pct_above_sma200 × 10)`, where `pct_above = SPY/SMA200 − 1`.
  - **Liquidity (30%)** = `50 + 50·tanh(net_liq_20d_slope_pct × 50)` (20-day slope of Net Liquidity).
  - **Risk Appetite (30%)** = `vix_score + spread_score`, each 0-50:
    `vix_score = 50·(1 − clip((VIX−10)/(VIX_extreme−10), 0, 1))`;
    `spread_score = 50·(1 − clip((HY−2)/(spread_extreme−2), 0, 1))`.
  - **Composite** = `0.40·trend + 0.30·liquidity + 0.30·risk`, clipped 0-100.
- **Output → 5 categories:** `≥80` Strong Bull (4) · `60-80` Bull (3) · `40-60` Neutral (2) · `20-40`
  Bear (1) · `<20` Strong Bear (0, all new entries blocked + existing liquidated). Persisted to
  `t2_regime_scores` as `m03_score` + the three `m03_pillar_*` (÷100) + `m03_delta_5d/20d`.
- **Live-safe:** yes — macro inputs are joined with an explicit **T+1 publication lag** (FRED releases
  lag observation dates) so a Wednesday Fed number only reaches Thursday's trading row.
- **Source:** `src/pipeline/m03_regime.py` (`M03RegimeCalculator`); methodology §5.

### SPEC B · Dashboard macro pillars (5 → 6)
- **Inputs → pillar mapping** (all from `macro_data`):
  | Pillar | Raw series | Definition |
  |---|---|---|
  | VIX | `VIX` | index level |
  | Credit | `BAMLH0A0HYM2` | ICE BofA US HY option-adjusted spread |
  | Term Spread | `DGS10 − DGS2` | 10y minus 2y Treasury yield |
  | Rates | `DGS10` | 10y Treasury yield |
  | Net Liquidity | `WALCL/1000 − WTREGEN/1000 − RRPONTSYD` | Fed balance sheet net of TGA + RRP (bn) |
  | **CAPE** (6th) | `CAPE_OURS` | **self-computed** cyclically-adjusted P/E (Yale `CAPE` dormant since 2024-09, kept as cross-check only) |
- **The 5→6 history:** the original gauge was **5-pillar** (VIX, Credit, Term, Rates, Net-Liquidity).
  The **6th (CAPE) was added** when the self-computed `CAPE_OURS` valuation series went live nightly
  (see [[project_cape_ours_pillar]]). CAPE_OURS is winsorized (a load-bearing concentration cap).
- **Display formula:** each pillar → a 0-100 **percentile rank** — *Fast Risk* (VIX/Credit/Term) use
  **all-time** rank; *Slow Fundamentals* (Rates/Liquidity/CAPE) use **5-year rolling** rank.
- **⚠️ NOT live-safe:** the display percentiles use all-time / forward-looking rank → **look-ahead. Do
  NOT feed them into a backtest.** Research uses raw *levels* only. (This is why C exists.)
- **Source:** `scripts/dashboard_utils.load_macro_pillars()`.

### SPEC C · Stress composite (`stress_ew_vix`) — the live-safe distillation of B
- **Inputs:** B's value/stress pillars — Credit, Rates, CAPE, VIX (raw levels).
- **Formula:** `stress_ew_vix = mean( +z(Credit), −z(Rates), −z(CAPE), +z(VIX) )`, where `z(·)` is an
  **expanding-window z-score** (mean/std over all data through *t−1*, then `.shift(1)`). Signs aligned
  so **higher = more stress = the direction that historically preceded *better* entries.**
- **Output:** a continuous daily score; a `stress_high` boolean = top expanding-quintile (80th pct) of
  the score (EMA10-smoothed before the cut — see F/B5).
- **Live-safe:** yes, and this is the whole point — the expanding-z + `.shift(1)` means no future
  normalization. (The look-ahead full-sample version `stress_full` inflated the edge ~2× — see §3-C.)
- **Source:** `entry_timing_features.py::add_stress_score`; `macro_sizer._stress_ew_vix`.

### SPEC D · M6 regime STATE label
- **Inputs:** SPY-200d (trunk) + one stress axis for the bull sub-split.
- **Formula (discrete states):** `bear = SPY ≤ 200d`; else within bull, `bull-stress` = either
  (**dd axis**, default) SPY drawdown-from-peak ≥ 10%, or (**macro axis**) top-tercile of expanding
  stress; else `bull-calm`.
- **Output:** one named state per date (`regime_state_daily_{dd,macro}.parquet`) — a model-agnostic
  join key, not a signal.
- **Live-safe:** yes (dd axis is price-only, full 25y; macro axis is expanding but leaks-by-time, §3-D).
- **Source:** `sprint_14/scripts/regime_state.py` (`--axis dd|macro`).

### SPEC E · Regime governor (sizing overlay)
- **Inputs:** `stress_ew_vix` (C) + SPY-200d.
- **Formula:** `weight = GATE × TILT`. **GATE** = 0 if `SPY ≤ 200d` else 1. **TILT** = full exposure
  (1.0) when stress in top expanding-quintile, else `GOV_BASE_W = 0.5`. Whole weight lagged 1 business
  day. Fed to `equity_curve(exposure=weight)`.
- **Output:** a per-day exposure multiplier ∈ {0, 0.5, 1.0}.
- **Live-safe:** yes (expanding quantile, `.shift(1)`, 1-day lag). Self-checked in `macro_sizer.__main__`.
- **Source:** `src/backtest/macro_sizer.py::governor_weight` (`--sizing governor`).

### SPEC F · weather_gauge (deploy posture)
- **Inputs:** SPY-200d + `stress_high` (EMA10-smoothed C) + **breakout-supply** (daily share of the
  universe breaking out, EMA10-smoothed, bucketed by expanding-quintile into famine ↔ flood).
- **Formula (posture rules):** `SPY ≤ 200d` → **STAND ASIDE**. Above 200d: `famine ∧ stress_high` →
  **DEPLOY MORE**; `flood ∧ ¬stress_high` → **DEPLOY, TRIM NEW**; else **DEPLOY**.
- **Output:** a human-facing posture string per day (`weather_gauge` table).
- **Live-safe:** yes — all stats expanding/EMA/`.shift(1)`; proven by an as-of-date identity test
  (0 mismatches). Note **DEPLOY MORE fires 0× in 23 years** (bull-stress-famine is genuinely that rare).
- **Source:** `src/weather_engine.py` (Phase 7.45).

### SPEC G · Coincident trade-gauge (the falsified ML nowcaster)
- **Label (target, model-agnostic):** per day, over the t3 SEPA cohort (~650 names/day, uses ONLY their
  forward returns — never any model score): **(A) loss_mean** = cohort mean of `min(fwd, 0)` (downside-
  only; swappable weight registry), and **(B) hostility** = fraction of cohort with `fwd ≤ −15%`.
  Binary target = bottom tercile of label-goodness = "BAD day."
- **Features (inputs, all live-safe):** `spy_ret20/60/120`, `vix_close`, `vix_chg20`, and the expanding
  stress composites `stress_ew_vix / stress_cr / stress_ew_rank`. (Raw pillar *levels* excluded as
  non-stationary.)
- **Model:** logistic regression + XGBoost, **walk-forward by year** (train on all prior years, score
  the next). Horizon parameterized (fwd20 first; fwd50/100 swappable).
- **Output:** a daily P(bad-day) score, evaluated by AUC + precision/recall vs the SPY-200d baseline.
- **Live-safe:** features yes; the label is future (that's the supervised target). The *deliverable*
  would be the classifier's live-safe score — but it was **falsified** (§3-G), so nothing ships.
- **Source:** `sprint_14/scripts/regime_gauge_label.py` + `regime_gauge_train.py`.

---

## 2. The evaluation methodologies we used (and why each)

Each instrument was killed or kept by one of three progressively-stricter lenses. Knowing *which lens*
a claim rests on is essential — a signal can pass the weakest and fail the strictest.

### 2.1 Correlation / separation (weakest — "is there any signal?")
- **Spearman-ρ** of a macro feature vs cohort forward return (fwd20/50/100 grid, because SEPA holds
  long — a weak 20d entry gets a "second chance" at 100d).
- **Best-vs-worst-date gap** and **tercile/quintile spread** (T3−T1) on the outcome.
- **Regime split** (SPY>200d bull vs bear) to check a signal isn't secretly one-regime-only.
- Used for: M03 (Finding 1), the 6-pillar (Finding 2/4), the stress composite (Finding 4/5).
- **Its trap:** correlation is a *mean-shift* statement. It does NOT imply per-day separability, and
  pooled ρ hides regime sign-flips. Caught explicitly in §3.

### 2.2 Live-safe reconstruction (the leakage gate — "would it have worked in real time?")
- Rebuild every rolling statistic with an **expanding window, `.shift(1)`** so day *t* uses only data
  through *t−1*. Full-sample z / all-time percentiles are look-ahead and were shown to **inflate the
  edge ~2×** (stress_full ρ +0.167 → live stress_ew +0.074).
- **As-of-date identity test**: recompute the signal with data truncated at an early date, compare to
  the full-history value over the overlap — **0 mismatches** proves no future leak (used for the B5
  de-flicker: 0 mismatches across 2140/3145/3901 overlap days).
- Used for: the stress composite (Finding 5 flipped it from "all-weather" to "bull-only"), the
  governor, weather_gauge, the trade-gauge features.

### 2.3 Distribution / cone backtest (strictest — "does it change the tradable P&L distribution?")
- **Start-date cone**: 20 anchored yearly folds × N trials, judge the **distribution** of Sharpe /
  drawdown / %-negative folds, not one aggregate number. An edge that's real must survive the *worst*
  start-year, not just the average — because the champion's return is a start-time lottery.
- Run on **BackTrader** (cash-blocking, stop-at-level gaps) — the vectorized engine is optimistic
  (median Sharpe 1.51 vs BackTrader 0.35 same config), so promotion requires the honest engine.
- Used for: the SPY-200d gate (floor −2.62 → −1.93 ungated→gated — PASSED), the governor (maxDD
  halved but median Sharpe 0.76→0.51 — a DIAL not alpha), VIX-sizing (dominated).

### 2.4 Supervised classification (the trade-gauge — "can we NOWCAST the bad day?")
- Binary bad-day target from a model-agnostic cohort label; **walk-forward by year** (no shuffled CV —
  days autocorrelate; iid p-values over-claim at 9M rows). Report **AUC + precision/recall/accuracy at
  an operating threshold**, always vs the SPY-200d baseline.

---

## 3. What each instrument concluded (chronological, with the killing method)

### A · M03 regime score — **NO entry-timing signal** (method 2.1)
`2026-07-07_entry_timing_features.md` Finding 1. Every M03 feature correlates −0.09..+0.02 with cohort
fwd return at all horizons; best-vs-worst-date gap on `m03_score` = −0.08 (zero separation). M03 is a
trend-STATE label, not a timing signal — consistent with the standing finding that M03 position-sizing
was a **no-op** in the backtest ([[project_backtest_equity_and_sizing]]). **Kept** as a state
descriptor / capacity gate; **rejected** as a deploy-timing input.

### B · The 6-pillar macro — **carries a value/stress signal M03 misses, but it's contrarian & leaky** (2.1 → 2.2)
`2026-07-07_entry_timing_features.md` Findings 2-5.
- The **rates/credit/CAPE (value-stress) axis** is the strongest, most horizon-consistent signal in the
  panel — but weak (all |ρ| ≤ 0.12) and **contrarian**: best entry dates are macro-stress / cheap-
  valuation moments. This *fights the strategy's own continuation scope* (name-selection ≠ date-
  selection tension).
- The **display percentiles are look-ahead** (all-time / 5-yr rank) — flagged non-model-safe; research
  uses raw levels only.
- **Rejected** as a model feature (leaky + contrarian to scope); the useful part was distilled into C.

### C · The stress composite — **a weak BULL-ONLY tilt, once made honest** (2.1 → 2.2)
`2026-07-07_entry_timing_features.md` Finding 5, [[project_entry_timing_macro_axis]].
- Combining the pillars is a *real* marginal lift (not redundant): look-ahead composite ρ +0.167 at
  fwd100 vs +0.10 best single pillar.
- **BUT live-safe reconstruction roughly halves it** (→ +0.084) AND **flips the regime story**: with
  honest expanding-z, stress predicts BETTER entries in bull (+0.14) but WORSE in bear (−0.15) — high
  stress in a downtrend is a falling knife. So it is **not all-weather**; correct usage is a stress
  tilt *gated by* SPY>200d, and it's a **top-quintile step** ("deploy when stress is EXTREME"), not a
  linear scale. Net: +1.8% fwd100 uplift. **Kept** as a small, bull-gated, threshold tilt.

### D · M6 regime STATE label — **bear/bull trunk solid, stress sub-split not settled** (2.1 + audit)
`2026-07-08_m6_regime_state_label.md`, `2026-07-08_m01_by_regime.md`.
- The **SPY-200d trunk is the trustworthy part** — its ≥20d runs match every known regime 2000-2026.
- The **stress sub-split leaks by time** (macro axis: expanding-z is mechanically wider early → 2013=88%
  stressed, 2017/2025=0%) **and flickers** (median stress-run 1-2 days). The **dd axis** (drawdown≥10%,
  price-only, full 25y) fixes coverage but is **sparse** (752 stress rows). **Neither axis gives a
  clean, persistent, well-populated stress state.**
- Consumers built on it: **m01 ranking is regime-ROBUST** (score ranks fwd return in every state; only
  the base level shifts) and **NO pillar trunk beats spx200** (every alternative trunk has *negative*
  bull−bear separation — the rebound lives on bear days). The regime STORY grows with horizon (stress-
  calm gap triples fwd20→fwd100). **VIX ≈ the bear/drawdown axis** (corr +0.63 with is_bear, +0.87 with
  realized vol) — not an independent input, the same bet two ways.

### E · Regime governor — **a drawdown DIAL, not a strategy fix** (2.3, the strict lens)
`2026-07-09_regime_governor_backtest.md`.
- On the 25y BackTrader start-date cone: worst-fold maxDD **−46% → −19%**, median fold DD **−29% →
  −14%** (both ~halved) at *every* start-year — a genuine, start-date-robust **drawdown controller**.
- **BUT it does NOT improve Sharpe or the %-negative-fold distribution** (all arms 35% neg folds), and
  it **COSTS median Sharpe (0.76 → 0.51)** — a pure brake mechanically can't lift the mean, and the
  start-day lens shows it trims the GOOD trades, not the bad ones (§6c). **VIX-sizing is strictly
  dominated.**
- **Why the "improves both" EDA story died:** GATE × TILT cancel — of ~467 top-quintile-stress days,
  only ~18 are also SPY>200d (**96% of "size up on stress" days are zeroed by the SPY gate** because
  high stress ≈ below-200d). Once gated, the stress tilt nearly vanishes → the governor collapses to
  the SPY-200d brake. **Banked as an optional `--sizing governor` DD overlay, un-tuned. NOT alpha.**

### F · weather_gauge — **display posture, de-flickered** (2.2 for the leak/stability check)
`2026-07-13_b5_stress_deflicker.md`, [[project_weather_gauge_shortlist]].
- Human-facing STAND-ASIDE/DEPLOY posture from 200d + stress_high + breakout-supply. Not backtested as
  alpha (it reuses C, which is already banked as a tilt).
- **B5 fix**: `stress_high` chattered (65 toggles, 58% 1-2 day blips). EMA10-smooth the composite before
  the expanding-quantile cut → 65→10 toggles, 0 chatter, leak-free (as-of identity test, 0 mismatches).
- **DEPLOY MORE fires 0× in 23 years** — bull-stress-famine is genuinely that rare (the same GATE×TILT
  rarity as E). The gauge's real content is the 200d brake + the supply axis, not stress.

### G · Coincident trade-gauge — **FALSIFIED as a per-day gauge** (2.4, the newest lens)
`2026-07-13_coincident_trade_gauge.md`, [[project_coincident_trade_gauge]].
- Built a **model-agnostic** day-level label (cohort loss-weighted fwd; two variants agree, spearman
  −0.95) and trained multivariate logistic/XGBoost — the one thing the univariate C7 bakeoff never
  tried: **do the pillars JOINTLY separate bad days?**
- **They don't.** Pooled OOS AUC: SPY-200d baseline **0.57**, logistic **0.55** (loses — top coef is
  `stress_ew_vix` with the *wrong sign*, reconfirming C7 at the multivariate level), XGBoost **0.60**.
- At an operating threshold the story sharpens (**corrects the first-draft "crisis detector" claim**):
  XGB does NOT beat the 200d in crises (they tie AUC 0.63; the 200d has *better* recall 68% vs 44%).
  XGB's only genuine edge is in **calm years** — spotting chop-inside-a-bull the 200d misses (recall
  40% vs 15%). Even there it's weak: AUC ≤ 0.60, precision ~44%, misses the majority of bad days.
- **Verdict:** SPY-200d stands as the whole regime tool. Coincident bad-days are ~coin-flip to nowcast
  — the 5× forward-return gap (§ Q15 below) is a **mean-shift, not day-level separability**. The XGB
  calm-chop recall is a candidate OVERLAY, not a standalone gauge.

### (supporting) Q15 capital-deployment — **SPY-200d is the one real ex-ante lever** (2.1)
`2026-07-07_capital_deployment.md`. SPY>200d → top-5 fwd20 **+3.0% vs +0.6%** below (5× gap, holds 25y).
**VIX is NOT a gate** (corr +0.03; high-VIX >30 has the BEST fwd +4.5% — a "reduce on high VIX" rule is
backwards). Residual: even in the best state 42% of days go negative → **stagger entry, don't day-time.**

---

## 4. The through-line (why they all converge on SPY-200d)

Read together, six instruments and four methods tell one coherent story:

1. **Two axes exist: TREND (SPY-200d) and STRESS (the pillars/VIX/credit).** They are near-orthogonal.
2. **The trend axis is the one that shifts the tradable distribution** — it gates *exposure* (floor
   −2.62→−1.93 on BackTrader), and it's the single ex-ante lever with a 5× forward-return gap.
3. **The stress axis is real but structurally un-monetizable here.** It's contrarian (buy-the-stress),
   which fights the continuation-model scope; it's bull-only once made live-safe; and its "size up"
   days are ~96% cancelled by the SPY gate (GATE×TILT cancel). It survives *only* as a **drawdown dial**
   (governor) or **display posture** (weather gauge) — never as alpha. VIX is just a blunter version of
   this same axis (corr +0.87 with realized vol).
4. **Coincident per-day nowcasting is near-impossible** (AUC ~0.57 even for the incumbent). Regime
   knowledge is a distribution *tilt*, not a day oracle. The residual 42% bad-day rate is dose-averaged
   by staggered entry, not timed away.

**Net for the strategy:** gate new-capital deployment on **SPY>200d**; that's the WHEN. Everything
richer is either redundant with it, a risk dial layered on it, or below the noise floor.

---

## 5. Open threads (deliberately not closed)

- **Stress sub-split still unsettled** (D) — persistence filter + vol/VIX-percentile cut would give a
  cleaner, better-populated stress state; deferred as a refinement, not a gap in the conclusion.
- **XGB calm-chop overlay** (G) — the one un-banked residual: a "calm-market chop" flag (recall 40% vs
  the 200d's 15%) could stack ON the 200d gate. Candidate overlay, NOT built — same status as the
  governor. Judge on the cone (floor-lift without median-kill) before promoting.
- **Loosening `stress_high`** (F) — top-quintile is very tight; now that B5 stabilized it, a looser cut
  is testable. Logged, not patched blind.
- **fwd50/100 re-run of the trade-gauge** (G) — infra parameterized; but it tests the mean-gap, not
  day-classification, so unlikely to flip the verdict. One cheap check.
- **Per-regime performance analysis** (next session) — with the regime *definition* now settled as
  SPY-200d (no validated 2nd axis), run the equity-fan / cone PER regime instead of one blended cone.

---

## 6. Source index

| Instrument | Primary verdict(s) | Memory |
|---|---|---|
| M03 | `verdicts/2026-07-07_entry_timing_features.md` (F1); `comprehensive_methodology.md` §5 | [[project_backtest_equity_and_sizing]] |
| 6-pillar / stress | `verdicts/2026-07-07_entry_timing_features.md` (F2-5) | [[project_entry_timing_macro_axis]], [[project_cape_ours_pillar]] |
| State label / consumers | `verdicts/2026-07-08_m6_regime_state_label.md`, `2026-07-08_m01_by_regime.md` | [[project_regime_during_period_goal]] |
| Governor | `verdicts/2026-07-09_regime_governor_backtest.md` | [[project_entry_timing_macro_axis]] |
| weather_gauge / B5 | `verdicts/2026-07-13_b5_stress_deflicker.md` | [[project_weather_gauge_shortlist]] |
| Trade-gauge | `verdicts/2026-07-13_coincident_trade_gauge.md` | [[project_coincident_trade_gauge]] |
| Deploy lever (Q15) | `verdicts/2026-07-07_capital_deployment.md` | [[project_capital_deployment]] |
| Regime tiering synthesis | `plans/2026-07-13_regime_tiering_and_system_usage.md` | — |
