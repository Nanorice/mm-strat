# Sprint 13 — Research Agenda

**Dates:** 2026-06-21 → 2026-07-06 · **Status:** ✅ CLOSED · **Next:** [sprint_14](../sprint_14/README.md)

> Infra (Prefect nightly, dashboard, DuckDB memory governance) is operational — see
> [2026-06-22_prefect.md](logs/2026-06-22_prefect.md). Sprint 13's research half asks one
> core question: **is the M01 score real alpha, or a structural artifact (industry mix,
> regime, survivorship)?**

### Folder map
- **`logs/`** — dated session handovers (`YYYY-MM-DD.md`, one per work session).
- **`plans/`** — forward-looking design/plan docs written before the work.
- **`verdicts/`** — findings, reports, issues, playbooks (the "what we concluded" record).
- **`cells/`** — notebook-cell artifacts (per the no-direct-`.ipynb`-edit rule); scratch once applied.

### Headline outcomes
- **M01 is real ranking alpha, not a sector/survivorship artifact** (Goal A: A1 no Healthcare bug, A2 arena Sharpe).
- **The edge is in the EXITS, not delayed entry** — rotation / delayed-entry / persistence all falsified; **E1 top-5 immediate** is champion (OOS Sharpe 0.84).
- **VIX-banded sizing adds risk-timing value; M03-banded is a no-op** → M03 retired as a sizing lever.
- **Stage gate & m02-breakout-as-return-signal both FALSIFIED**; kept only as candidate features / event-predictors.
- **CAPE_OURS** self-computed valuation pillar shipped (zero Shiller dependency); **DQ layer hardened** (dirty-shares tiers, R2 publish gate).

## Consolidated Sprint Roadmap & Goals

### 1. Modeling (M01 & M02)
- **Finalise M02 (the ongoing scoring model).** ✅ **DONE.**
  - Shifted M02 to predict structural breakouts directly via a continuous `breakout_proximity` score.
  - Model achieved **50% Precision@50** out-of-sample (~3.6x edge over random). See [m02_final_verdict.md](../../research/m02_final_verdict.md).
- **Strip M03 from all models.** ✅ **DONE.**
  - Created `fs_m01_no_macro` feature set. Retrained `m01_no_macro` and `m01_binary_no_macro`.
  - Conclusion: Macro context is essential for binary "Home Run" predictions, but redundant for standard 4-class multi-class predictions. See [M01 No Macro Model Card](../../models/m01_no_macro/v1/model_card.html).

### 2. Strategy Evaluation & Backtesting
- **Backtester — exploratory & finalisation.** ✅ **DONE.** 
  - Fixed bugs, converged prod/backtest scoring. Evaluated `vnpy` and decided against adopting it.
- **Goal B: SEPA Staging / Entry Timing.** ✅ **DONE — hard gate FALSIFIED** (2026-07-04).
  - Built a Minervini 4-stage classifier reusing `trend_ok` + swing-pivot/slope primitives
    (`src/features/trend_segments.py`), not the from-scratch rule module originally scoped.
  - Full-N forward-return test (`scripts/falsify_stage_gate.py`, 2,711 watchlist tickers)
    killed the hard entry gate: no short-term edge, only 65bps at 60d. **The stage ranking
    inverts the Minervini prior** — on an already-filtered watchlist, Stage 1 (fresh bases)
    and Stage 4 (washout bounces) *outrun* Stage 2 at 60d. Mean reversion > momentum within
    the pre-selected set.
  - **Outcome:** primitives kept as *candidate* M02 features, inclusion **DEFERRED to its own
    study**; nothing wired. See [goal_b_stage_classifier_plan.md](plans/goal_b_stage_classifier_plan.md)
    (PHASE 3 VERDICT). Cache: `stage_gate_panel.parquet` (cache now in `data/backtest_cache/`).
- **Parameter Optimizer.** ✅ **BUILT** (2026-07-02). Optuna over the vectorized engine.
  - `scripts/run_strategy_optimizer.py` — single IS/OOS split, maximize Sharpe.
  - `scripts/run_strategy_wfo.py` — rolling/anchored walk-forward variant (the overfit gate).
  - See [2026-07-02_backtest_arena_session.md](logs/2026-07-02_backtest_arena_session.md) for full results.
- **Evaluate the model and strategy.** ✅ **Model Arena built + first results** (2026-07-02).
  - `scripts/run_model_arena.py` — all scoreable variants on shared strategy infra, ranked by honest mark-to-market Sharpe. m01_binary ≈ m01_prototype at top; m01_no_macro (4-class) worst.

### 3. Research: Score Validity & Macro Regime
- **Goal A: Score Attribution & Validity.**
  - **A1 — Industry-bias / Healthcare check.** ✅ **DONE — no Healthcare-specific artifact** (2026-07-04).
    `scripts/check_healthcare_bias.py` (m01_prototype `prob_class_3`, 177k ticker-days, 178 days,
    Oct 2025–Jun 2026, sector base rate = the *scored* cross-section per day, era-controlled).
    - The score **does** tilt toward growth sectors, but it is **not a Healthcare artifact.** At a
      score>0.25 top-set, sector lift (top/base): **Technology 1.54 ≈ Healthcare 1.49**, Basic
      Materials 1.28, Energy 1.25 — all growth/cyclical up; the de-weighted side is
      defensive/rate-sensitive: Real Estate **0.21**, Utilities 0.32, Financial Services 0.39,
      Consumer Defensive 0.70. Healthcare's per-day excess is a modest **+2.4% at 0.15 / +8.8% at
      0.25** (100% of days positive) — consistent but middling, not a standout.
    - **Why the eye sees "mostly Healthcare":** in the actual daily **top-20 by score**, Healthcare
      is **57%** (~11 of 20 names/day). That's two effects stacking, neither a bug: (1) Healthcare is
      the **largest sector by count** (885/4176 = 21% of the universe, biggest scored base rate too),
      and (2) the extreme tail (top-20 of ~1000 scored/day) concentrates the mild growth-tilt. A big
      base rate × a mild positive lift → a visually dominant top of the list.
    - **Takeaway:** the observed Healthcare-heavy sorts are a **base-rate + growth-tilt composition
      effect, not a sector-specific score bias.** The growth-vs-defensive tilt is *expected* for a
      breakout/momentum model (it is what SEPA is supposed to favour) — not evidence the score is
      broken. Remaining Goal A work (empirical ground-truth on recent breakouts; is the tilt
      *justified* by realized forward returns per sector?) is the real validity question. Threshold
      0.10 is uninformative (93% of rows qualify) — use ≥0.15.
  - **A2 — model bake-off.** ✅ **DONE — reuses existing arena; m02 excluded on prior evidence** (2026-07-04).
    Arena (`scripts/run_model_arena.py`, `models/arena/`, ran 2026-07-02) on the common window
    2025-10-06→2026-05-22 (bounded by prototype prod-score history), shared strategy
    (top-3/day, SL10%, SMA50), honest bar-by-bar mark-to-market Sharpe:

    | model | source | trades | win% | total_ret | ann_ret | Sharpe | maxDD |
    |---|---|--:|--:|--:|--:|--:|--:|
    | **m01_binary** | t3 | 90 | 38.9% | 44.6% | 82.1% | **2.00** | −15.6% |
    | **m01_prototype** | daily_predictions | 105 | 24.8% | **54.0%** | 101.7% | **1.99** | −19.8% |
    | m01_binary_no_macro | t3 | 44 | 25.0% | 31.1% | 55.4% | 1.63 | −13.5% |
    | m01_no_macro (4-class) | t3 | 102 | 15.7% | 3.4% | 5.5% | 0.33 | −15.5% |

    - **m01_binary ≈ m01_prototype — a dead heat at the top** (Sharpe 2.00 vs 1.99); prototype
      earns it with higher total return (54%) at lower win rate (fewer, bigger wins), binary with a
      higher hit rate. **The 4-class m01_no_macro is decisively worst** (Sharpe 0.33) — dropping
      macro *and* using 4-class multiclass guts ranking skill (consistent with the "macro essential
      for binary Home-Run, redundant for 4-class" finding). ⚠️ Arena Sharpes (~2.0) are
      **regime-flattered** (short strong-tape window); WF-aggregate steady-state ≈ 0.84.
    - **On M02 in the arena — two different models, don't conflate them.** The arena raced the *M01
      family only*. Of the models carrying the "M02" name:
      - **`m02_prototype`** (Sprint-12 quantile MFE/MAE cone) is genuinely **retired** — *negative*
        ranking edge, verdict = replace with `k×ATR` bands
        ([m02_final_verdict.md](../../research/m02_final_verdict.md)). Correctly excluded.
      - **`m02_breakout`** (the ignition classifier, `breakout_proximity`) is a **live CHAMPION
        prototype**, NOT falsified: OOS **P@50 ≈ 50% / Rank IC +0.37** across 5 anchored WF folds
        2021–2026 (`models/m02_breakout/20260629_203134/summary.json`), stable through the 2022
        bear. It has **never been backtested** — the "m02 no-edge spike" in memory was the *cone*,
        not this. The arena is the **wrong venue** for it anyway: m02_breakout is a full-universe
        *pre-breakout* early-warning ranker, but the arena strategy (top-3/day, SMA50 exit, 252d
        hold) is an M01-style *post-breakout* momentum hold. Racing it there tests the wrong job.
        **See A3.**
    - **Goal A (validity) conclusion:** the M01 score is **real ranking alpha, not a structural
      artifact.** A1 ruled out a Healthcare/sector bug (broad growth-tilt is expected, not a bias);
      A2 shows the two edged M01 variants win on honest shared-infra Sharpe while the degraded
      no-macro 4-class loses. **m01_binary and m01_prototype are the M01 keepers.**
  - **A3 — m02_breakout as a distinct strategy (NEW, OPEN).** m02_breakout should be evaluated
    *on its own two intended jobs*, not in the M01 arena:
    1. **Breakout trade** — enter on high proximity, **short hold, exit shortly after the breakout**
       (not SMA50/252d). Needs its own exit rule in the vectorized engine.
    2. **Earlier-entry signal** — its universe is broader/faster than M01's watchlist; test whether
       a high m02_breakout score gives a usable head-start *before* M01's scanner trips.
    **No scorer adapter needed** — the engine takes injected `precomputed_scores`
    (`date,ticker,prob_elite,calibrated_score`) and bypasses `UniverseScorer` entirely (same path
    m01_prototype already uses). So the "adapter" is a **~30-line leak-free fold-score loader**
    (score each date with the WF fold whose *test* window covers it), renaming
    `breakout_proximity → prob_elite`. **The one real build is a short-hold exit policy** (M01's
    SMA50/252d hold is the wrong job); everything else — enter/rank/dedup/size/metrics — is reuse.
    Full plan + reuse map + the two job configs: [goal_a3_m02_strategy_plan.md](plans/goal_a3_m02_strategy_plan.md).
    - **A3 Phase-0 gate: ❌ NO-GO for the trade build** (2026-07-04,
      [m02_signal_quality_report.md](verdicts/m02_signal_quality_report.md), all scores OOS via fold models
      + final-model tail). Job 2 head-start is real for the *event* (91.7% coverage, median 42d
      lead) but the return claim was selection-biased; the unconditional test kills it: **top-50
      forward return ≈ universe mean (+12bps/21d excess pre-cost, negative 2022–2025)**. Ignition
      rate is monotone by decile (2.2%→41.6%) yet fwd returns peak at decile 7 and fall into
      decile 10 — the score peaks where the pre-breakout move is already spent. Predicting the
      watchlist event ≠ predicting returns. Job 1 (E1 short-hold strategy) **not built**;
      prod-gap plan Phases 2–4 do not run on strategy justification. Residual value is
      operational only (M01-scanner early-warning list, no return claim) — separate decision.
  - **A-remaining (optional):** per-sector forward-return cross-check (does the A1 growth-tilt pay
    in realized returns?) — low priority; the arena already answers the core M01 validity thesis.
- **Goal C: Regime / Bearish-Event Notebook.** ✅ **RESEARCH CONCLUDED** (2026-06-26).
  - `notebooks/regime_model.ipynb` + `notebooks/signs_of_tail.ipynb`: tested lead candidates
    (absorption ratio, valuation timing, per-mechanism signals). **Conclusion: no leading signal
    besides VIX; do NOT over-complicate the macro model.** The regime model is implemented and
    already serves the dashboard's macro section.
  - **Remaining (moved to backtest):** wire the regime model into the regime/sizing layer of the
    backtest — see the "Macro-driven position sizing" TODO below (same work).
- **High-Beta / Industry-bias Feature of SEPA Candidates.** ✅ **ANSWERED** (see Goal A1 above).
  No Healthcare-specific artifact — the score has a broad growth-vs-defensive tilt (expected for a
  breakout model), and Healthcare dominates top-20 sorts via base-rate × mild-lift composition, not
  a sector bias. `scripts/check_healthcare_bias.py`.
- **Macro Evaluation.** Can macro *confirm* a trend (not lead)? — largely answered by Goal C's
  "VIX only, don't over-complicate" conclusion; the actionable remainder is the sizing experiment.

### 4. Infrastructure & Housekeeping
- **Macro Dashboard.** ✅ **IN PLACE** — weather/climate gauge live (see [macro_dashboard_implementation_plan.md](plans/macro_dashboard_implementation_plan.md)). **Remaining: final gap/pending check** (see TODO).
- **ITX.** ⏸ Deferred — being implemented on another branch; not a Sprint 13 concern.
- **Goal D: Feature Correctness & Housekeeping.** ✅ **DONE.**
  - `_pct_change` vs `_delta` features are likely duplicates — confirm and drop `_pct_change`.
  - Guard against the feature-shift SQL bug (used DuckDB's `INSERT ... BY NAME`).
  - Document cleanup — batch at sprint end.

## Sprint TODOs

- **Dirty shares/price rows escape the DQ audit.** ✅ **CLOSED** (2026-07-04, two passes +
  systemic hardening). Pass 1: 125 shares / 37 fundamentals / 76k price rows nulled, 4
  FAIL-level plausibility checks wired. Pass 2 found a **sub-ceiling tier** — the same ~1000×
  FMP dirt on *small* tickers lands below any global bound (GTLS 29.9B vs real 30M) — 86
  shares + 38 fundamentals rows adjudicated row-by-row and nulled (EXE whitelisted: legit
  pre-1:200-reverse-split count); relative tripwires (`>1B AND >500× ticker median`) added on
  both tables. OHLC-ordering class resolved: 99.9% was <0.1% rounding epsilon, 3 corrupt bars
  nulled, check recalibrated to 3 tiers. **Then the whole DQ layer was hardened** (assessment
  + 5 fixes): bounds centralized in `config.T1_PLAUSIBILITY_BOUNDS`; write-time clamps at all
  3 engines; **Phase 1.6 fast plausibility gate** (0.5s) that **withholds the R2 publish**
  while red; new-FAIL delta alerting in `run_all_audits`; filing-date thresholds unified (8d
  — killed 22.5k warn-noise rows). Issue: [ISSUE_dirty_shares_cap_dq_gap.md](verdicts/ISSUE_dirty_shares_cap_dq_gap.md);
  assessment + tracker: [DQ_orchestrator_hardening.md](verdicts/DQ_orchestrator_hardening.md).
  **⚠️ Remaining ops:** run `clean_dirty_shares_price.py` on sh019 (its DB copy still dirty);
  investigate standing FAILs (t1_macro missing 8 June-2026 dates + NULL vix row, 4 gap tickers).

- **CAPE pillar — replace dormant Shiller data with a self-computed CAPE.** ✅ **SHIPPED +
  drift fix re-evaluated and CLOSED** (2026-07-04). With caps clean, the planned
  winsorize→absolute-ceiling swap was tested and **REJECTED**: it flattens the drift
  (+0.022→+0.004/yr) but collapses tracking (rank corr 0.874→0.416) — the winsorize is a
  **load-bearing mega-cap concentration cap**, not a dirt filter. Final design: absolute
  ceiling (`implied_cap_max`) masks impossible caps first (dirt guard), winsorize retained
  deliberately. CAPE_OURS rewritten on clean data (dirt-era months moved ≤2.1%); tracking
  unchanged (0.871/0.874). Full write-up:
  [cape_fred_proxy_findings.md](verdicts/cape_fred_proxy_findings.md) (closing section).
  - **Root cause (b):** the old `econ.yale.edu` URL was a **dead mirror** (froze 2023-09)
    *and* the current canonical host (`shillerdata.com`, `Last-Modified 2024-09-04`) is
    itself **dormant** — Shiller hasn't updated the workbook in ~22mo. FRED has no S&P EPS
    series, FMP index endpoints are dead/paywalled → official S&P 500 CAPE not sourceable.
  - **Solution: compute our own** (`src/cape_engine.py`, symbol `CAPE_OURS`) — winsorized
    cap-weighted mean of per-ticker real-P/E10 over a deep-earnings basket, CPI-deflated,
    **updates nightly forever, zero Shiller dependency.** Validated vs true Shiller CAPE:
    **level corr 0.87, rank corr 0.87** (a); after a single ~1.28× rescale, mean APE 5.9%
    (a/c). Latest 2026-07 = 59.7 → pillar percentile 100 (correctly rich).
  - **Wired:** `cape_engine` → nightly Phase 1; `load_macro_pillars` valuation pillar now
    reads `CAPE_OURS` (Yale kept as `CAPE_yale` cross-check); `CPIAUCSL` added to
    `FRED_SERIES`; DQ audit monitors `CAPE_OURS` (40d) — all OK.
  - **⚠️ Survivorship caveat (accepted, documented):** basket is fixed to current survivors,
    so historical levels carry a survivorship lift (~1.28× Shiller, creeping to 1.43). Safe
    because the pillar **ranks against its own history** and the same basket every month =
    same bias every month → timing signal is consistent. **Display-only; must NOT feed any
    model/backtest.** As-of membership de-biasing deferred (needs data we don't store).

- **Macro dashboard — final gap check.** ✅ **DONE** (2026-07-04, folded into the CAPE
  pass). 5/6 pillars fresh to 2026-06-30; CAPE pillar now **live** via CAPE_OURS (2026-07).
  Earlier gap (ffill'd stale CAPE with no staleness cue) is moot now the pillar updates
  nightly. No half-wired panels. Optional polish deferred: a staleness badge on the gauge
  for any future ffill'd fallback.

- **Deferred (Goal B): stage primitives as M02 features.** `market_stage` / `slope_63d` /
  `slope_r2_63d` / `prior_slope_sign` (`src/features/trend_segments.py`) kept as *candidate*
  features after the hard gate was falsified. Study whether they add lift to M02 breakout-timing
  as a soft signal — LOW priority, only worth it if Goal A shows M02 needs help. Casing guard
  (`COLUMN_CASE_MAP`) applies if adopted. Cache: `stage_gate_panel.parquet` (cache now in `data/backtest_cache/`).

- **Macro-driven position sizing in backtest — the "no double-count" experiment.** ✅
  **LARGELY DONE** (2026-07-02). Equity-curve fix landed (bar-by-bar mark-to-market);
  `src/backtest/macro_sizer.py` (`MacroSizer`, flat/vix/m03, 1-day lag = no lookahead) +
  `scripts/run_sizing_experiment.py` built. **Finding: VIX-banded sizing adds real risk-timing
  value** (m01_binary 5yr Sharpe 0.21→0.31, maxDD −47%→−28% at 64% avg exposure); **M03-banded
  is a no-op** (de-levers without timing) — consistent with the macro-redundancy conclusion.
  This also closes Goal C's "wire regime → backtest sizing" remainder: the regime lever doesn't
  help sizing either, VIX does.
  - *Remaining (optional):* fold the sizing lever into the walk-forward gate
    (`run_strategy_wfo.py`) so the VIX-sizing uplift is confirmed OOS, not just in-sample.

- **Heavily Manual** Strategy Arena - first list types of strategies (e.g. breakout, swing, hold etc.), how to rotate and rebalance, when to enter, exit, how many tickers, % of position, preference of industry? sizing and regime, does this have an overlap with m03 inputs? do we retire m03? or do we replace with the new macro parameters. note this is not idiosyncratic, as in all ticker share the same feature, so how does this help?

## Pre-flight for the Manual Strategy Arena (blocker sweep — 2026-07-04)

> Reviewed so tomorrow's arena work starts unblocked. Foundations are **GREEN**; the one
> decision to make up front is which engine the arena standardizes on (see B1).

**Infra confirmed working (no blockers):**
- ✅ Vectorized engine + **injected scores** is the live, model-agnostic path
  (`VectorizedSEPABacktest(precomputed_scores=...)` bypasses `UniverseScorer`). Strategy
  vocabulary (enter/exit/size/rebalance) now documented once in
  [backtester_manual.md](../../architecture/backtester_manual.md) — the arena's reference.
- ✅ Honest metrics/equity (bar-by-bar mark-to-market), optimizer, WFO gate, macro sizer all
  built and validated (2026-07-02 session).
- ✅ Data deps present: `m02_breakout_targets` (16.1M rows, `breakout_proximity` populated),
  `t3_training_cache`, `daily_predictions`, `company_profiles` (sector/industry).

**Resolved (2026-07-04 review):**
- **B1 — the two engines are a FIDELITY LADDER, not a pick-one.** RESOLVED. We keep both *on
  purpose*: the **vectorized** engine is fast but approximates capital (pro-rata, allows phantom
  concurrency); the **BackTrader `runner.py` + `SEPAHybridV1`** path enforces *real* cash-blocking
  (no concurrent-trade capital fiction) and has the richer 3-tranche/ATR/min-hold exits. **Arena
  flow: sweep the grid on vectorized (cheap, ranking) → confirm the finalist(s) on BackTrader for
  capital-honest Sharpe.** `scripts/run_strategy_array.py` (S1..S5) IS the BackTrader confirm
  layer — keep it. **S1..S5 status:** valid strategy *definitions*; S1 (top-N daily) reproduces on
  vectorized, but S2–S5 use knobs the vectorized engine lacks (`rank_by='trailing'`, persistence
  gate, `min_hold_days`, `regime_max_pos`, tranche targets) → those run ONLY on BackTrader today.
- **B2 — exit is engine-specific; BackTrader already has the rich version.** RESOLVED (status
  clarified). **Vectorized:** hardcoded stop>SMA50>max_hold(252d), single whole-position exit — the
  crude version. **BackTrader `SEPAHybridV1`:** already supports ATR stop (`atr_stop_mult`, capped
  `max_stop_pct`), 3-tranche targets, SMA50 trend exit, optional percentile-rank exit, and
  `min_hold_days`. So short-hold/swing exits are *already expressible on BackTrader*. The
  `exit_policy` switch (manual §5) is only needed to give the **fast vectorized** engine a
  short-hold mode for A3 grid sweeps — a convenience for cheap iteration, not a gap in capability.
- **B4 — DROPPED.** Industry is already a model input; a separate sector-preference *strategy* knob
  is overcomplication. Not building it.

**Still to do before/at arena start:**
- **B3 — m02_breakout `--final` all-period fit + score panel.** ✅ **BUILT + smoke-passed** (2026-07-04).
  - `train_breakout_model.py --final` — single all-period booster (~9.4M rows, 2016→2026) →
    `models/m02_breakout/final_<ts>/model.json` + `metadata.json` (frozen feature list). G1/G2.
  - `scripts/score_m02_breakout.py --run <final_dir>` — runs the model over the t3 matrix → arena
    panel `date,ticker,prob_elite,calibrated_score` at `<run>/score_panel.parquet`. G3 (research).
    prob_elite = `breakout_proximity` **clipped to [0,1]** (reg overshoots slightly; monotone, so
    ranking unchanged). **RANK-ONLY contract** — uncalibrated (G4), don't threshold the raw value.
  - ✅ **DONE:** full-universe final fit `models/m02_breakout/final_20260704_175544/`
    (5.09M rows, 86 feats, 2016→2026); score panel `score_panel.parquet` = **9.36M rows,
    2,711 tickers, 6404 days**, scores [0, 0.31]. **m02_breakout is now arena-ready as an injected
    signal.** Next: Job-2 lead-time gate → then the arena ladder (see HANDOVER + playbook).

**Optimizer — is it cleared? YES.** ✅ Both built and validated (2026-07-02):
`run_strategy_optimizer.py` (Optuna, single IS/OOS, **pre-scores once then injects** so trials are
ms-fast, maximize Sharpe) + `run_strategy_wfo.py` (walk-forward re-tune = the overfit gate). Both
run on the vectorized engine with injected scores — so they slot straight into the arena as the
*grid-search* and *overfit-gate* layers. Nothing to build; only *optional* remainder is folding the
VIX-sizing lever into the WFO gate (confirm the sizing uplift OOS). Not a blocker.

**Already-answered inputs to the arena (don't relitigate):**
- Sizing/regime is a **portfolio exposure dial, not a selector** (all tickers share the macro
  value) → lives in the `exposure` Series, not the score. VIX works, **M03-banded is a no-op**
  → M03 does not earn a sizing slot. The "retire vs replace M03" question is effectively decided
  on the sizing axis (retire as a sizing lever); its only remaining role is as a model feature,
  which the no-macro study already found redundant for 4-class. See manual §6.

**Side Quest — Watchlist Cohort-Return Tracker.** ✅ **BUILT** (2026-07-05).
- Original ask: dashboard plot, x = days-before-today, y = realized-return distribution
  (median/mean + quantile bands, box-plot ok) of the tickers scored **that day** (per-day
  membership, not a fixed basket), with a **P(Home Run) knob** to filter membership. Tests the
  hypothesis that hit-rate collapses in stressed vs. bull markets (*站在风口上猪都能飞*).
- **Shipped** as a new section on Page 1 (Today):
  - `load_cohort_return_panel()` in `dashboard_utils.py` — per-signal-day return distribution via
    `daily_predictions × price_data` lateral joins; **two modes** (return-to-latest / fixed
    forward N-day). Membership = tickers scored that day, knob on `prob_class_3`.
  - `render_cohort_return_tracker()` in `dashboard.py` — cohort selectbox, P(HomeRun) slider,
    mode radio, horizon input; median line + p25–p75 / p10–p90 bands, zero-line, range caption.
    Wired after the rank bump chart.
  - `tests/test_cohort_return_panel.py` — 3 asserts (shape/finite returns, threshold shrinks
    membership, forward mode runs); **passes** against live `dashboard.duckdb`.
  - **Constraint (by design):** plottable x-range is bounded by the slim DB's ~252d `price_data`
    window, not by `daily_predictions`. No manifest change needed. Early read: on `pre_breakout`,
    hit-rate 65%→58% as the knob goes 0.0→0.5 — the conviction-vs-outcome relationship surfaces,
    but the ~1y window has no real drawdown yet, so don't over-read the stressed-vs-bull contrast.

**Side Quest follow-up — pre-breakout population + m02 knob.** ⏸️ **DEFERRED to next sprint**
(2026-07-05; finding: `2026-07-05_prebreakout_tracker_m02_finding.md`).
- The **m01-keyed** pre-breakout tracker already works — Page 1 → select cohort `pre_breakout`
  (population = `trend_ok=TRUE AND breakout_ok=FALSE`, in-setup, not yet entered). No build.
- The requested **m02-keyed** version is deferred: **m02_breakout is an XGBoost *regressor***
  (`objective: reg:squarederror`, target `breakout_proximity`), **not binary**. Its `prob_elite`
  column is a **misnomer** — clipped `breakout_proximity`, **uncalibrated, RANK-ONLY**, range
  [0, 0.31] (never near 0.6), so an absolute-threshold knob is meaningless. Panel is a `.parquet`
  not in the `build_dashboard_db` MANIFEST (would break the R2 remote if read directly).
- **To do it honestly next sprint:** either a **rank-percentile knob** (top X% of m02 score that
  day — honors the rank-only contract, lowest effort) or **calibrate m02 (G4)**; then add
  pre-breakout-windowed m02 scores as a *table* in the manifest + a loader variant joining m02
  instead of `prob_class_3`.