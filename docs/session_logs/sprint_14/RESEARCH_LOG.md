# Sprint 14 — Research Log (question ledger)

> **Purpose:** the linear train-of-thought — every question in the order it arose, one-line
> outcome, link to the deep verdict. This is the *middle zoom* between the per-finding `verdicts/`
> (deep, one file each) and the goal-organised `README.md` (current state). Read top-to-bottom to
> follow how the thinking evolved. Append one line per question at each key point / topic switch.
> `→` = what happened · `⟳` = a later finding revised this · `?` = open.

## Thread A — is the top-5 a skilled pick, or random? (gate vs ranker)

1. **Is the champion's top-5 a skilled pick or a random draw from a tie-pool?**
   → smoke cohort-bootstrap (1 window): pick sits at 37th pctile of random-null → looks random.
   `verdicts/2026-07-07_selection_bias_cohort_bootstrap.md`
2. **Why is it tied? — is `prob_elite` really that coarse?**
   → ⟳ the ties were on `normalized_score` (4 distinct), NOT the model's actual score. The champion
   is the **binary** model ranking on **calibrated** `prob_elite = iso_calibrator.transform(p_pos)`.
3. **So is the "gate-not-ranker" verdict real, or a calibrator artifact?**
   → the isotonic calibrator is a step function: collapses ~2000 raw scores → ~23 plateaus →
   manufactures the ties. Live `daily_predictions` raw score is continuous. **Mechanism overturned:
   ties are a calibrator artifact, not the model.** `verdicts/2026-07-07_calibrator_flattens_ranking.md`
4. **Then rank on RAW p_pos instead of calibrated?** (fix b)
   → WFO reconciliation: calibrated 0.91 vs raw 0.79 aggregate OOS. Looked like calibrated wins →
   ⟳ **corrected: 0.12 gap is inside start-time noise (folds swing >2 Sharpe). NOT settled.**
   `models/m01_binary/wfo/{calibrated,raw}/`

## Thread B — is 0.15 the right threshold? (EDA, model output)

5. **How does the model output distribute; is 0.15 the right gate?**
   → 0.15 is **calibrated**; = **raw p_pos ≈ 0.48** (the model's ~50/50 line). Not low — the model
   is overconfident, calibrator corrects raw 0.50 → 0.15. `verdicts/…calibrator_flattens_ranking.md`,
   `cells/model_output_eda_cells.md`
6. **On the full universe, does the raw score grade forward return / is the gate right?**
   → yes, 3× home-run-rate gradient at the top (0.48→12.7% at 0.71). Gate is a precision/recall
   dial; a top-5 strategy only fills 5 of ~805 admitted/day → **can tighten hard for free precision.**
   `verdicts/2026-07-07_raw_score_forward_return_eda.md`
7. **How many home-runs do we miss?**
   → 23.4% missed, but they're near-misses (median raw 0.41 vs 0.48 gate). ⟳ **flawed measure —
   home-run treated as binary >30%, ignores the fat tail we actually care about. Re-cut needed.**
   → ✅ **M1 re-cut (magnitude): only 14.2% of tail MAGNITUDE missed, not 23.4% of events — the
   gate keeps big winners, drops small ones (missed mean-excess +12% vs captured +23%). AND the
   raw score DOES rank the tail (top-1% fwd at score-pctile 0.89; top-1% scores hold 6.1× their
   share of tail) — "weak ranker" was only true within the gated pool, not on the full universe.**
   `verdicts/2026-07-07_tail_magnitude_recut.md`

## Thread C — can we refine / rotate the gated pool?

8. **Do the ~6 gated breakout names persist day-to-day (could we rotate)?**
   → 0% next-day persistence — breakout is a day-0 event by construction. Rotation dead *for breakouts*.
   `verdicts/2026-07-07_breakout_pool_refinement.md`
9. **Is there ANY within-day separator of winners in the pool?**
   → no — every technical feature's within-day IC ≈ noise; model score IC ≈ −0.03. Third confirm of
   weak ranking. **Only residual = SECTOR** (Tech +9% vs Healthcare −3% median, breakout cohort).
10. **Now scores are continuous, do the TOP names persist?**
    → ⟳ **yes** (top-5 50% overnight, ~7-place drift) — but on the *full active pool*, not day-0
    breakouts. A persistent, rotatable top-N exists here that the breakout gate throws away.
    `verdicts/2026-07-07_raw_score_forward_return_eda.md`
11. **What do the best performers share?**
    → cheap, lower-quality **value-rebound** names (PE 17.7 vs 37.4); technicals flat/inverted; 2025
    sector tilt Healthcare 1.65× (⚠️ opposite the breakout finding → regime/population-dependent).
    ⚠️ 2025 only, one regime.

## Thread D — macro sizing (parallel track)

12. **What do the 6 macro pillars mean / how to use in sizing?**
    → reference doc written; sizing-not-selection; VIX works, M03 no-op (S13). Credit pillar is the
    top candidate to test next to VIX. `docs/research/macro_pillars_reference.md`

## Thread E — capital deployment: bad-day risk, basket width, scope (user Qs, 2026-07-07)

13. **Is the crash pro-cyclicality a model defect?** → **No — a scope boundary.** SEPA screening
    (Stage-2 uptrend, rising MAs, high RS) structurally EXCLUDES beaten-down reversal names at their
    bottom; they only enter the full-universe test set later, after re-building a trend. The model is
    a CONTINUATION model, not a reversal model. → accept it; the 25-yr full-universe bad-regime floor
    is a slightly pessimistic read of the SEPA-gated live system (which wasn't down there ranking
    reversals). `verdicts/2026-07-07_capital_deployment.md`
14. **Does top-10 catch more winners than top-5?** → **No.** Both from the same ~284 gated/day.
    Pooled 25y: top-5 +2.36% / HR 8.75% ≈ top-10 +2.30% / 8.34%; names 6–10 average +2.23%. The
    score's power is a SHARP CLIFF at the top-5 then flat. **Widening the basket dilutes, doesn't
    help** — argues AGAINST the S13 "widen it" instinct. Inside the 5, no order (IC≈0). Same verdict.
15. **Can we tell good days from bad EX-ANTE (the limited-capital start-date problem)?** → Partly.
    **SPY-above-200d is a real deploy gate:** top-5 fwd +3.0% (above) vs +0.6% (below), 25y — a 5×
    gap from one binary known at the open. **VIX is NOT a gate** (corr +0.03; high VIX>30 days are
    the BEST +4.5% — crash-rebound, don't cut them). Residual: even in the best state 42% of days
    still go negative → the un-removable part is STAGGERED entry (dose-average the start), not
    day-timing. Confirms M2's cone-not-point; SPY-200d tightens the cone's downside. Same verdict.

## Thread F — entry-timing / regime lens: what marks the best vs worst deploy dates? (user pivot, 2026-07-07)

> User steered off the SPY-200d gate ("too early to invest in the gate") toward an EXPLORATORY
> correlation: not realistic backtesting, but finding a feature around the best (and worst) entry
> dates. Outcome = mean top-5 fwd return per day, over a horizon grid (fwd 20/50/100 — SEPA holds
> longer, so does a weak 20d entry get a second chance?). `scripts/entry_timing_features.py`,
> panel `data/model_output_eda/entry_timing/entry_timing_daily.parquet`.

16. **Does M03 flag good/bad entry timing?** → **No.** 25-yr: every M03 feature ρ ∈ [−0.09,+0.02];
    m03_score best-vs-worst-date gap −0.08 (zero separation). M03 is a trend-STATE label, not a
    timing signal — consistent with M03-sizing being a no-op. `verdicts/2026-07-07_entry_timing_features.md`
17. **Does the dashboard 6-PILLAR macro (≠ M03) do better?** → **Yes — a VALUE/STRESS axis.**
    Strongest, most horizon-consistent signal in the panel: rates −0.12 (high 10y → worse),
    credit spread +0.09 (WIDE spreads → BETTER, contrarian), CAPE −0.11 (expensive → worse), VIX
    +0.08. Best dates = macro-stress/cheap moments — opposite of trend, which is WHY M03 misses it.
    ⚠️ used RAW pillar levels; the dashboard percentiles are look-ahead ("do NOT feed to backtest").
18. **Weak@20d entries — second chance on a longer hold?** → **Partial, regime-robust.** worst-20d
    decile: −20.7% (20d) → −17.5% (50d) → −8.1% (100d). Heals ~12pp by 100d but doesn't turn
    positive. Bad entry = drag, not write-off, on SEPA's longer hold.
    - **CAVEATS:** all |ρ|≤0.12 (tilts not gates); univariate + full-pooled → resolved by Q19.
19. **(option b) Combine the pillars + split by regime.** → **Two upgrades.**
    (a) **Stress composite** = mean z(+credit, −rates, −cape) **BEATS every single pillar** — fwd100
    ρ +0.167 vs +0.10 best-single (~60% lift), strengthening with horizon (0.04→0.14→0.17). Combining
    is NOT redundant; each pillar adds a piece. (b) **Regime split (SPY>200d):** the composite works
    **equally in bull AND bear** (+0.176 / +0.190 @ fwd100) — NOT a bear-only buy-the-dip. Robust
    because parts are REGIME-DIVERSIFIED: credit fires in bull (+0.142/+0.017), rates & VIX in bear
    (−0.263, +0.206). Much stronger story than the "contrarian" framing of Q17's pooled ρ.
    ⚠️ z/percentiles are full-sample (look-ahead, EDA-only) — needs expanding-window before it can
    size real capital. n(bear)=1094 vs n(bull)=4556. `verdicts/2026-07-07_entry_timing_features.md`
20. **Make it live (expanding-window z) + measure the tilt.** → **The look-ahead flattered it;
    honest = a BULL-ONLY, top-quintile tilt.** (a) Live-safe expanding-z HALVES the signal: stress_ew
    fwd100 ρ +0.074 (vs +0.167 full-sample look-ahead); best variant stress_ew_vix +0.084; rank-based
    worse (+0.043); dropping CAPE ~neutral (+0.072). (b) Live regime split FLIPS bull-only: bull
    +0.139, **bear −0.150** — high stress in a downtrend = falling knife; the look-ahead z borrowed
    future normalization that faked all-weather robustness (Q19b overturned). → tilt must be GATED by
    SPY>200d. (c) Tilt is a TOP-QUINTILE step, not linear: Q1..Q4 flat (~+10%), Q5 +18.5%;
    stress-weighted +14.2% vs flat +12.3% = **+1.8% fwd100 uplift** (marginal, as expected).
    → **Deploy more when stress EXTREME & SPY>200d.** Small but real. `entry_timing_features.md` F5.
    - **NEXT:** wire stress_ew_vix (SPY>200d-gated, threshold not linear) as an exposure input if
      pursued (low priority, small effect); judge the strategy on fwd100 not fwd20 (signal + recovery
      both live long).

## Open meta-questions (deferred — carry to next session)

- ✅ **M1. DONE — objective re-cut to tail-magnitude, validated across 25 regimes.** New reusable
  metrics: captured/missed `Σ max(fwd−30%,0)` (2025 leak 14.2% not binary 23.4%) and **tail-lift@k**.
  Scope clarified: the "good ranker" claim is point-in-time full-universe RAW score, 20d fwd; the
  "weak ranker (4×)" was the OPPOSITE conditioning (inside the gated pool / calibrated score).
  Selection edge honestly bounded: 2025 top-1% lift 6.1× is ~half gate; **above-gate residual 3.2×**.
  **Multi-year (2001–2025, `data/model_output_eda/multiyear/`): the ranker is PRO-CYCLICAL** — median
  6.8× but 0.68× (below no-skill) in 2001/2008 crashes; above-gate edge negative in 5/25 yrs;
  corr(lift,HR-rate)=−0.44. Only regime-robust result: `miss_mag<miss_count` 25/25. → adopt the
  metric; treat ranking as a distribution; M3 judges the bad-regime floor, M4 must be
  regime-conditioned. `verdicts/2026-07-07_tail_magnitude_recut.md`
- 🔀 **M2. ABSORBED, not skipped — it's the evaluation LENS, not a standalone deliverable.**
  Single-Sharpe is unsafe → decisions go through a start-date cone (distribution not aggregate).
  Validated 3× this session (the 25-yr sweep is a coarse cone; Q15 "42% neg days → stagger not time";
  and the next step (b) IS a cone test). No separate harness to "do" — (b) applies M2. Don't
  re-litigate. cf [[project_champion_starttime_dependent]].
  → **(b) NEXT SESSION:** does the SPY>200d deploy gate (Q15) SHRINK the start-date cone — narrow the
  Sharpe *distribution* across start-months, not just lift the mean? Needs `run_strategy_wfo.py`, not
  a cache re-slice. This is the entry into M3. `verdicts/2026-07-07_capital_deployment.md`
- **M3. Did we start the whole strategy search on the wrong foot?** (user, 2026-07-07) — we ran a
  strategy grid over ONE fixed horizon, picked a winner, THEN discovered start-date dependence and
  swept it. Every early decision was backed by one horizon's result. Proposed re-frame: pick a
  strategy → sweep start-month × horizon (done) → **in both good AND bad months, sweep strategies to
  find the most STABLE one** (not the highest-mean) → refine/iterate. Stability-first, not mean-first.
- 📋 **M4. DESIGNED — premise CONFIRMED against artifacts (doc was misleading).** Checked the shipped
  `model.json` objectives: `m01_prototype` = `multi:softprob` (4-class), `m01_binary` = `binary:logistic`
  — **both classifiers, NO regressor in the live family.** (⚠️ `model_doc/m01.md` §3 wrongly calls the
  champion a "regressor on log_space MFE" — stale/wrong, flagged to fix.) So the fat tail is quantized
  at label time: +35% and +400% both collapse into the "Elite" (MFE>30) bin; the model can't express
  M1's tail-lift@k. M4 = **build the first magnitude-aware model** — regressor/quantile head on `mfe_pct`
  directly (winsorized-magnitude A / τ=0.90 quantile B / tail-contribution C). **Mechanism (falsifiable):**
  among already-elite names (all P(>30%)≈1, unranked by the classifier) does *conditional expected
  magnitude* carry residual ranking signal? If it's luck once elite, M4 dies. Eval on **tail-lift@k not
  RMSE**, bar = champion's ABOVE-GATE lift on the BAD years (regime-conditioned; pooled fit inherits
  M1's pro-cyclicality). **Design decision (§1b): target AND bar both on `mfe_pct`** — re-cut the M1
  champion lift (was fwd20) on mfe_pct so the comparison is same-outcome. id = `m04_regressor` (≠ shipped
  M03). Target+objective swap in the existing XGB trainer, reuses the multi-year toolkit; smoke-first.
  `verdicts/2026-07-07_m4_magnitude_regressor_design.md`
- ✅ **M4. SMOKE-BUILT (2026-07-08) — a magnitude regressor ranks better ON AVERAGE, but noisily.**
  Fixed the setup: M4 trains on `d2_training_cache` (the table m01 already trains on, has `mfe_pct`) —
  NOT the multi-year full-universe parquets (those only have `fwd20`), which is where the design wrongly
  pointed. Shipped m01_prototype was no-holdout (saw all rows) → built a model-level WFO harness
  (`m4_wfo_taillift.py`, expanding train, retrain+score per fold). 11 folds, 3 targets scored on OOS
  `mfe_pct`, metric `cond_lift10` (= does the score rank the big winners WITHIN its own top-10% pool):
  **A (plain winsorized-magnitude regressor, the design's null control) wins on the median** — 1.73 vs
  champion 1.29; **B (τ=0.90 quantile, the design's primary thesis) ties the champion** (quantile loss
  barely learns). So the design's bet on which target wins was wrong — the simple regressor beat the
  fancy one. **But the result is NOISY (A swings 0.21–3.41 across folds, fails 3/11).** The 2007-09 (GFC)
  fold is <1× for all three — tempting to call "pro-cyclical, dies in crash" BUT that split is CIRCULAR
  (hand-picked the GFC as "bad" because it was the weakest fold; two calm-year folds are nearly as weak).
  Can't attribute the weakness to regime vs noise without a real regime label → see M6. Settled cheaply
  on the cached table; the expensive full-universe sweep was NOT needed (wrong population/outcome).
  Next unblocked step = re-cut on SEPA-eligible-only names. `verdicts/2026-07-08_m4_smoke_wfo_taillift.md`
- **M5. Persistent continuous-score top-N** (from Q10) is a different, lower-turnover product than
  the day-0 breakout champion — worth prototyping + cone-testing.
- 📋 **M6. Quantify a REGIME state expression + characterize DURING-period behaviour.** (user, 2026-07-08)
  The sprint over-indexed on *leading-vs-coincident* (can a macro signal predict WHEN to deploy —
  Thread F). Under-served: a clean **state label** (stress / bull / bear) and how the strategy behaves
  WHILE inside each state (drawdown shape, tail-rankability, dispersion), regardless of whether we can
  predict the transition. This is a PREREQUISITE — it unblocks (a) testing M4's pro-cyclicality
  non-circularly (M4 above), and (b) M4 regime-reweighting (can't weight rows by a label we don't have).
  Large scope → DEFERRED to next session. `[[project_regime_during_period_goal]]`
- ✅ **M6. BUILT (2026-07-08) — state label shipped; M4's pro-cyclicality OVERTURNED non-circularly.**
  Built a model-agnostic date→state label (`regime_state.py`) reusing Thread F's live-safe machinery:
  **bear** (SPY≤200d) / **bull-stress** (SPY>200d & top-tercile `stress_ew_vix`) / **bull-calm**. HARD
  scope: label is **2013+ only** — credit/CAPE start 2003/2012 so the stress composite is only fully
  populated then; a full-span tercile cut left just 45 stressed-bull days (unstratifiable), fixed by
  cutting the tercile WITHIN the clean era (704). Consequence: NO 2008-scale crash in-window (worst bear
  = 2022). Joined M4 target-A's per-row OOS preds (new `--dump-preds`) to the label:
  **cond_lift10 is WEAKEST in calm-bull (1.62), STRONGEST under stress (bull-stress 2.44, bear 2.37) —
  the edge is NOT pro-cyclical, if anything counter-cyclical.** hr_rate flat (~12.5%) across states →
  genuine ranking power (best when dispersion high), not a base-rate artifact. The M4 smoke's "dies in
  the GFC" was CONFIRMED circular. ⚠️ bear thin (1,647 rows, 41% is 2022) → directional not settled;
  bull-stress (n=5,036, well-distributed) is the trustworthy cell. Doesn't contradict M1's 2001/2008
  pro-cyclicality (deeper-crash era this label can't reach → needs the drawdown/vol axis, next step).
  Next: model-agnostic SEPA-candidate behaviour by state (consumer #2), then drawdown/vol axis.
  `verdicts/2026-07-08_m6_regime_state_label.md`
- ✅ **M6 consumer #2 (2026-07-08) — m01 score×regime, full universe, all tickers, NO backtest.**
  User Qs answered: (trunk) a BAKEOFF shows NO pillar trunk (credit/term/composite) beats spx200 at
  separating fwd return — all have NEGATIVE bull-minus-bear separation (rebound lives on bear days),
  spx200 least-negative → kept, pillars REJECTED on evidence. (m01×regime) the score RANKS fwd20 in
  EVERY state — top−bottom decile gradient +2.1%/+1.6%/+1.7% (calm/stress/bear), monotone all three:
  ranking skill is regime-ROBUST (level shifts, ordering survives — complements M4's tail-specific
  counter-cyclicality). (stress gap) bear/stress precede HIGHER returns than calm bull; gap(stress-calm)
  +0.85%, 95% block-bootstrap CI [+0.47,+1.20] EXCLUDES 0 → REAL (buy-the-stress, cf Thread F). (stat)
  ran BOTH — bootstrap CI (day-resampled, honest) excludes 0 on 25y but STRADDLED 0 on the 3y smoke;
  Kruskal-Wallis p≈0 is meaningless at 9M autocorrelated rows → trust the CI. ⚠️ fwd20 only,
  directional. Next: dashboard current-state badge + regime strip beneath the 6-pillar table.
  `verdicts/2026-07-08_m01_by_regime.md`
- ✅ **fwd50/100 ENRICHED (2026-07-08) — the regime story is a LONG-HOLD one.** Enriched the full 25y
  universe with fwd50/fwd100 (`enrich_fwd_horizons.py`, per-ticker `groupby.shift(-H)` reproducing
  cached fwd20 EXACTLY, 27s). Horizon sweep: stress-calm gap +0.86%(fwd20)→+2.43%(fwd50)→+2.87%(fwd100)
  ~triples; m01 top−bottom decile gradient grows ~4× (e.g. calm +2.1%→+9.1%) in EVERY state. fwd20
  UNDERSTATED both effects → judge m01/regime on fwd100 (Thread F "signals live long", confirmed at
  full-universe scale). Dashboard badge+strip DEFERRED as a separate deliverable (user).
- ✅ **THE m01 SCORE IS REGIME-BLIND (2026-07-08 synthesis + confirm) — this is WHY the rule is a
  lottery.** Confirmed a user suspicion directly: through the entire 2022 bear, the daily mean m01 score
  is FLAT (0.37–0.45, std 0.021) while mean fwd20 swings −9%..+9.5% (std 0.054, 2.5× more variable).
  The technical continuation score has NO idea a drawdown is happening — SEPA-eligible names stay in
  uptrends (by construction) right up until they break, so the score keeps emitting "buy these 5" into
  a falling market. **Consequence (the sharp point): the trading rule has no internal brake → outcome
  is dominated by WHEN you start = a lottery, not a strategy.** The fix CANNOT be trained in (SEPA
  structurally excludes crash-bottom names — the model is continuation-only BY DESIGN); it must be an
  EXTERNAL regime governor (sizing/gating overlay) on top of the model. This closes the loop from Thread
  A (start-time dependence) → M6 (regime label) → the governor. Trunk for the governor = SPY vs 200d MA
  (coincident bull/bear is ENOUGH per the user's point-4 logic: worst case you start the day before a
  drawdown and stop the next day); the calm/stress sub-split is NOT needed for a first cut.
- ✅ **POINT-8 DONE (2026-07-08) — regime-weighting the panel REDUCES the drag → the governor earns a
  backtest.** Reweighted the existing per-day top-5 fwd100 panel (`entry_timing_daily.parquet` ⋈ dd
  regime label, 5650 days) by ENTRY-DATE regime, two weights: **(a) SPY-200MA bear=0** cuts the
  worst-decile +5.0pp (−34.9%→−29.8%) but costs −1.0pp mean — a VARIANCE BRAKE, not free alpha, because
  bear days carry BOTH the highest mean fwd100 (+16.6% rebound) AND the worst tail (−51% knife). **(b)
  stress_ew_vix bull-gated improves BOTH** (mean +0.8pp, worst-decile +6.0pp) by concentrating into
  bull-stress (good-mean/contained-tail) — the better governor, ⚠️ but deploys only ~18% of capital
  (per-$-deployed mean; a full-book scaling decision the backtest must force). Effect is a LONG-HOLD one
  (fwd20 deltas ~⅓ fwd100). **Verdict: promote to backtest, carry BOTH weights** — (a) simple full-deploy
  brake, (b) concentration tilt. Re-confirms Thread F's "deploy more when stress EXTREME & SPY>200d" now
  shown to cut DRAG not just lift mean. EDA reweight, no exits/sizing — backtest through the start-date
  cone (M2) before wiring. `scripts/regime_weight_panel.py`, `cells/regime_weight_panel_cells.md`,
  `data/model_output_eda/regime_weight/`.
  - **+2 charts (user, 2026-07-08):** (Q1) deploy-from-any-day drift — cumulative top-1/5/10 fwd20 per
    representative period: steady up-slope in every bull/rebound (2020 COVID +13.2/100d, 2003-07 +2.8,
    2023-25 +3.2, 2013-15 +1.6) but **−1.9 in the 2007-09 GFC** → the edge is a bull-regime property
    (regime-blindness as an equity curve); top-5≈top-10, top-1 noisier (cliff-at-5 confirmed). (Q2)
    6-pillar expanding-percentile stack vs the full-span top-5 curve — legible macro backdrop (credit/VIX
    spike into 2008/2020 where the curve stalls) but NOT a consolidated signal (that's stress_ew_vix).
    `scripts/start_date_drift.py` (+`_chart.py`), cells 8-12.
  - **+3 follow-up charts (user, 2026-07-08):** (C3) NON-cumulative — raw per-day top-5 fwd20 scatter the
    cumulative curve sums; (C4) whole-period 2001-25 with dd-regime shading → bear bands (2001-02/2008/
    2020/2022) sit ON the flat/declining cumulative stretches (regime change visible at 25y scale). (C5)
    FIXED the pillar viz: expanding percentile is BROKEN for TRENDING pillars — Net Liquidity (corr+0.96)
    & CAPE (+0.91) only ramp up so expanding-pct pins at ~100% after 2004 (re-encodes "later=higher");
    replaced with ROLLING 2yr percentile → Liq now dips in QT (2018/2022). Data-fact answers: CAPE
    genuinely starts 2012-12 (`CAPE_OURS` self-computed, cf [[project_cape_ours_pillar]]); the Liq pin
    was transform not data. `scripts/start_date_drift_extra.py`, cells 13-16.
  - **+2 charts / a QUANTIFICATION (user, 2026-07-08):** (C6) daily top-5 return by horizon (cumulative
    panel stripped — no realistic meaning; mean +2.6/+5.9/+12.1% fwd20/50/100, regime-shaded). (C7)
    **CAN macro quantify high/low-return periods? YES, all on ONE stress/VIX axis.** fwd100 top−bottom-
    tercile spread: VIX +11.5%, VIX-raw +11.0%, stress composite +10.5%, credit +9.6% (all buy-the-
    stress); rates −8.9% & CAPE −8.3% INVERT (same axis, flipped); **SPY>200d −5.1%** (rebound lives
    sub-200d → SPY-trend is a TAIL gate not a return-level ranker; two jobs). Stress composite NOT better
    than raw VIX (VIX carries it, cf [[project_entry_timing_macro_axis]]). THE CATCH: high-stress tercile
    = best mean (+18.5%) AND worst tail (−43.3% worst-decile) → survives only WITH the SPY>200d gate =
    the point-8 governor (b). All |ρ|≤0.09 = tilts not gates; tercile cuts full-sample (EDA).
    `scripts/return_vs_macro.py`, cells 17-21, `return_vs_macro_quantify.csv`.
  - ✅ **INSIDE the high-stress tercile + 150d/200d (user, 2026-07-08) — THE GOVERNOR IS A GATE × A
    TILT.** Enriched fwd150/200 (smoke-tested, 99.6/98.7% cov) → top-5 panel at 5 horizons
    (`build_top5_horizons.py`, `top5_horizons.parquet`). Within the top stress tercile (n=1800),
    SPY>200d cleanly splits the outcome: bull-stress vs bear-stress earn ~EQUAL MEAN at every horizon
    (fwd100 +18.9 vs +18.0%) but bear-stress worst-decile is ~2.5× DEEPER (−56 vs −24% fwd100, −65 vs
    −31% fwd200); reward/|tail| bull dominates all horizons (fwd150 1.27 vs 0.45). Bear-stress's higher
    fwd200 mean is a mirage of 2008/09 crash clusters (248+101 of its 709 days = catch-the-bottom bets).
    **STRATEGY CONCLUSION: two signals, two jobs — stress/VIX ranks the MEAN (size up on stress),
    SPY>200d is the TAIL GATE (removes the bear-stress knife at ~0 mean cost); don't stack a 2nd
    vol-sizing factor (double-counts). Confirms & explains point-8(b). Hold long & only above 200d — the
    edge & tail-heal both strengthen with horizon.** The regime-blind m01 doesn't need to become
    regime-aware; it needs this 2-part external governor. Falsifiable spec → backtest via M2 cone.
    ⚠️ bear-stress n=709 crash-clustered (few-episode tail); full-sample cuts (EDA). `high_stress_
    conditional.py`, cells 22-25, `high_stress_conditional.{csv,png}`.
  - ✅ **POINT-8 PROMOTED TO A REAL BACKTEST (2026-07-09, M2→M3) — the governor is a start-date-ROBUST
    DRAWDOWN CONTROLLER, not the "improves both" story.** Built the live-safe governor as a MacroSizer
    mode (`governor_weight`: full size in the top EXPANDING-quintile of stress_ew_vix, base 0.5 below,
    ZERO when SPY≤200d; expanding-z + expanding-quantile threshold + 1-day lag — the EDA's full-sample
    cuts can't size live capital), wired `--sizing governor` into `run_strategy_wfo.py` + a per-fold
    cone metric, cached m01_binary scores once to parquet (`cache_model_scores.py`, chunked by year to
    fix a 12.6 GiB OOM — score_from_t3 carries ~190 t3 cols; trim to date/ticker/prob_elite/cal_score).
    **25y cone, 20 anchored yearly folds, 40 trials, flat vs vix vs governor:** governor HALVES drawdown
    at EVERY start-year — worst fold DD **−46%→−19%**, median fold DD **−29%→−14%**, agg maxDD
    −50.7%→−25.4% — the durable win, survives the cone. BUT it does NOT improve Sharpe or the fold-sign
    mix: all three arms 35% negative folds, same worst folds (2008/2011); governor cone MEDIAN is the
    LOWEST (0.51 vs flat 0.76) and total return collapses (615%→212%). A pure brake can't lift the mean,
    and the losing folds are BEAR years where the SPY gate already flattened exposure (nothing left to
    protect). VIX strictly dominated (same axis, blunter). **WHY the EDA "improves both" didn't survive:
    GATE × TILT CANCEL** — of ~467 top-quintile-stress days (2007-22) only 18 are also SPY>200d
    (bull-stress), so the gate zeroes ~96% of "size up on stress" days (high stress ≈ sub-200d ≈ falling
    knife) → tilt inert → governor ≡ point-8(a) variance brake. point-8(b)'s "improves both" was
    per-$-on the rare bull-stress cell (~18% capital); at full book the brake dominates. **BANK as a
    DD-control overlay (user 2026-07-09), NOT alpha/stability; flat wins the median cone. Un-tuned
    (base-weight & hard gate deliberately not swept — the cancellation is a finding, not a knob to fit).**
    `verdicts/2026-07-09_regime_governor_backtest.md`, `macro_sizer.py`, `run_strategy_wfo.py`,
    `cache_model_scores.py`, `models/m01_binary/wfo/calibrated_{flat,vix,governor}/`.
    - ✅ **WHAT DD DOES IT CONTROL vs the 15% stop-loss? (user, 2026-07-09) — REGIME BLEED, not
      gap-down; complements the stop, no double-count.** Stop-loss runs INSIDE run() (per-position,
      intraday, `low≤entry×0.85`, truncates each trade's window); governor runs in equity_curve()
      (per-calendar-day, scales the BOOK return by exposure). Different layers → compose by
      multiplication, no conflict. PROVEN in 2007-09: the stop fired **64-76×** (−15% each) and the
      flat book STILL fell **−56%** (regime-blind re-entry into the decline, stopped again & again);
      governor gated 58-93% of the window → **−12%**. So the governor is *"don't re-enter a falling
      market"* control — a portfolio brake the per-name stop can't provide; NOT gap control (gaps are
      the stop's job). **⚠️ separate caveat (own ticket): the stop books gap-downs at the −15% level
      (`_simulate_exits` fill=stop_level), so the flat −56% baseline UNDERSTATES true gap severity; the
      governor cuts gap EXPOSURE but not gap MODELLING.** `cells/governor_vs_stoploss_cells.md`,
      `governor_vs_stoploss_2008.png`.
    - ⚠️ **GAP-DOWN LOSS UNDERSTATED — quantified (user "account for the real loss", 2026-07-09).**
      `_simulate_exits` (vectorized_backtest.py:342-344) books every stop-out at `exit_price=stop_level`
      (=entry×0.85) UNCONDITIONALLY, but `hit_stop` fires on `low≤stop_level` — so on a gap-down OPEN
      below the stop the real fill is the open, not −15%. Over the 25y stop-out population (329 stops):
      **7.0% gap through**; on those the real loss averages **−19.7% (worst −39.8%)** vs booked −15%;
      averaged over ALL stops the understatement is only **−0.33%** (doesn't distort the cone, but the
      −40% tail matters for a tail strategy). **FIX = book gap-outs at `min(stop_level, open)`** — a
      stop-loss realism change, orthogonal to the governor, LOGGED as its own ticket (not yet applied,
      awaiting user go-ahead). `cells/governor_vs_stoploss_cells.md` Cell 5.
    - ℹ️ **EQUITY MODEL HAS NO CAPITAL LEDGER (user Q, 2026-07-09).** `equity_curve` (vectorized_backtest.py
      :483-514) is pure RETURN-compounding, not a cash account: `equity = cash × cumprod(1+daily_return)`,
      `daily_return = Σ(open-position returns) × position_size_pct × scale`; `scale` (pro-rata dilution
      above `1/position_size_pct` open slots) is the ONLY capital constraint. So idle capital earns
      nothing & costs nothing (0-position or exposure=0 day → return 0 → equity FLAT); the governor `w`
      SCALES THE RETURN, not a cash allocation (`w=0` ≡ 100% cash 0% return); under-deployment is
      invisible. The chart answers "return of selected trades × exposure", NOT "how capital was
      allocated / what idle cash did". Extension A.
    - ℹ️ **GATE RE-DEPLOYS AT 200d RECLAIM, NOT THE TROUGH — quantified rebound-miss (user Q, 2026-07-09).**
      2008-09: SPY bottomed 2009-03-09 (−55% peak, −35% below 200d), reclaimed 200d **81 days later**;
      over that leg SPY +36.8%, FLAT strategy **+38.6%**, GOVERNOR **+0.0%** (gated off, mean exp 0.0) —
      the gate misses the snap-back because the rebound STARTS sub-200d. NET the governor still ends
      ahead (DD-avoided > rebound-missed). Trough hard to catch ex-ante (VIX peaked 109d BEFORE price
      trough) but a naive off-20d-low momentum trigger moves +25% within 45d → a "release near the
      bottom" v2 (recovery-momentum re-deploy) is the natural extension to recover the miss. Not built.
      `governor_missed_rebound_2009.png`, Extension B.
    - ⚠️ **ENTRY MODEL = ROLLING SLOT-BOOK + the governor MISMODELS RE-ENTRY (user Q, 2026-07-09).**
      `_select_entries`/`_enforce_capacity`: new top-N candidates DAILY, but each ticker enters ONCE
      (`drop_duplicates keep=first`, no pyramiding/re-entry), gated by a greedy concurrent-slot cap
      (over-subscribed picks DROPPED, not queued). NOT locked-day-1, NOT fresh-basket-daily — a rolling
      book. **Governor catch:** it's a RETURN multiplier applied AFTER run(), so entries KEEP FIRING
      during the gated-off window (13 entered mid-freeze Mar-2009); their returns are just zeroed. On
      unfreeze (200d reclaim) you INHERIT those stale mid-flight positions (16 open, only 2 new in 20d),
      NOT a fresh bottom basket. So the proxy = "fully invested throughout, P&L zeroed on gated days,
      switch flipped back holding tired names" — DD-control result unaffected (zeroed P&L is right) but
      RE-ENTRY is mismodelled, compounding the Extension-B rebound-miss. A faithful gate (flatten →
      redeploy fresh on unfreeze) is part of the v2. Extension C.
    - ⚠️ **GROSS EXPOSURE IS AN ARTIFACT OF BREAKOUT SUPPLY, not a sizing decision (user Q "unlimited
      capital → equity always up?", 2026-07-09).** `daily_return = Σ(open-pos returns) × pos_size_pct ×
      scale`; `scale` (dilution) only fires when open_count > 1/pos_size (=10 at default 0.10), i.e.
      96.6% of days scale=1 → gross exposure = open_count × 0.10, UNCAPPED in practice. So position
      count = gross exposure. **"Always up" is FALSE** — returns are signed, summing positions in a bear
      sums LOSSES (2008 −56% *because* it kept entering); and it's mostly UNDER-deployed (mean gross
      43%, 57% of days <50% invested, only 5% >90%, capped at 10 concurrent) so no runaway compounding.
      **The REAL flaw: exposure DRIFTS 28%(2017)→66%(2021) with breakout supply** → cross-period
      comparisons contaminated (good year may = high-supply/high-exposure year), and the governor `w`
      multiplies on top of this drifting base. A fixed-fractional / vol-targeted book would separate
      edge from accidental leverage — orthogonal backtest-fidelity upgrade. `gross_exposure_drift.png`,
      Extension D.
    - ✅ **START-DAY LOTTERY REFRAME + EQUITY FAN (user idea, 2026-07-09) — fixes the exposure artifact,
      shows start-time dependence VISUALLY.** New lens (`start_day_basket_paths.py`): every start-day =
      one lottery draw — buy that day's GOVERNOR-GATED top-5 (gate off on SPY≤200d = deploy nothing, a
      REAL cash gate at entry, unlike Ext-C's return-multiplier proxy), hold each name under SL(−15%)/
      150d, equal-weight basket forward return. Removes exposure drift (fixed 5-name notional/start-day,
      no shared-pool leverage). **Plot A (lottery):** 943 deployed start-days, mean **+13.4%** median
      **+6.3%** but std **29.6%**, **41% lose** (hard cluster at the −15% full-stop floor), max +202% —
      the histogram width IS the start-time risk. **Plot B (equity fan):** every start-day curve aligned
      at origin (x=days-after-start), VARIABLE LENGTH (ends where the basket fully exits = the
      "when-do-we-stop" variable made visual); the 10-90 fan is ~flat at entry and ENORMOUS by 150d →
      start-time dependence rendered. **TP variant (+25%):** cuts std 29.6%→10.8% (tighter fan) but mean
      +13.4%→+4.2% & max +202%→+25% — TP caps the exact right tail SEPA's edge lives in
      ([[project_tail_magnitude_objective]]). This is the honest capital-artifact-free picture; the
      natural home for the governor's value (shift the start-day DISTRIBUTION, not one curve). Directional
      basket study, NOT the shared-pool backtest. `cells/start_day_lottery_cells.md`, `start_day_lottery.png`.
      - ✅ **WITH vs WITHOUT governor on the lottery (user, 2026-07-09) — the governor's value SHOWN on
        the distribution.** No-gov (every start-day trades, n=1177): mean +14.4% median +5.6% **std
        39.6%** 42% losing max **+823%**. With-gov (n=943): mean +13.4% median **+6.3%** **std 29.6%**
        41% losing max +202%. **The gate TIGHTENS the fan (std −25%), lifts the MEDIAN, clips the extreme
        right tail** — it does NOT lift the mean (can't: it's a filter, and the 234 SPY≤200d days it
        DROPS have a HIGH mean +18.1% from crash-rebound jackpots but a LOW median +1.9% & 47% losing =
        the falling-knife-or-jackpot bear-stress cell). **So it trades tail-return for CONSISTENCY** —
        same variance/DD-tool conclusion as the cone, now shown on the start-day lottery itself. Cell 2b.
      - ⚠️ **REASSESSMENT (user challenge, 2026-07-09) — at the SINGLE-BASKET level the governor trims
        the UPSIDE, not the downside.** By-percentile: p05/p10 IDENTICAL (−15% floor untouched), losing%
        42→41% (trivial), but p95 −6.5% and max +823%→+202% — the trim is ALL upper-tail. Mean of
        WINNING trades +32.9%→+30.2%. RECONCILES with the cone's −46%→−19% DD win: a single 5-name basket
        can only lose 15% (no sequencing), so the cone's DD is a COMPOUNDING effect — up to **51
        CONSECUTIVE gated start-days** in a bear compound into the −46% book drawdown; the governor avoids
        that SEQUENCE, which an independent basket can't show. **Honest verdict: the governor buys
        compounding-DD protection by sacrificing the exact right tail SEPA's edge lives in — a BAD trade
        for a tail strategy, and it does NOT fix the lottery.** TP doesn't either (shrinks the whole
        distribution). Tighter Minervini stops (5-8%) NAIVELY HURT (SL5% → median −5%, 56% losing) —
        whipsaw on a fixed-hold basket; a tight stop only works WITH pivot-timed entry + add-on. → the
        lottery is structural: fixed day-0 basket + fixed hold. FIX = Minervini's CONDITIONAL entry
        (VCP pivot trigger, most watchlist names never fire) + PROGRESSIVE exposure (add only on
        confirmation) + tight position-level stop + asymmetric exits. Next: quantify a pivot-trigger +
        add-on-confirmation overlay on the watchlist, NOT more sizing knobs. Cell 2b + follow-up.
      - ✅ **4-PART DIAGNOSIS (user, 2026-07-09) — governor apply, VCP, progressive exposure, tight stop.**
        (1) **Governor in Plot A does NOTHING between base(0.5) & stress(1.0)** — the weight is {0.0:1222,
        0.5:4925, 1.0:29 days} but a fwd-return basket has no capital ledger, so `deployed = w>0` collapses
        base/stress to a pure BINARY entry gate (SPY>200d). Correct behavior; sizing is meaningless here.
        (2) **VCP IS ALREADY IN THE MODEL** — m01_binary features include `vcp_ratio(_delta)`,
        `consolidation_width(_delta)`, `natr(_delta)`, `dist_from_20d/52w_high`, `breakout_momentum`,
        `immediate_thrust`. → do NOT re-weight by VCP score (double-counts, same trap as regime/isotonic).
        BUT the pivot BREAKOUT-TRIGGER EVENT (cleared pivot on volume TODAY) is NOT in the model (it's a
        static setup-quality score, not a timing event) → the trigger is the non-redundant piece to add.
        (3) **Progressive exposure PROTOTYPED in the fwd lens** (path-dependent name weights): half-size
        entry, add to full only if name up +10% by day10. vs equal-weight, both 6% stop: mean +9.5%→+12.7%,
        max +429%→+602% — concentrates into confirmed winners (std rises, expected). Provable without the
        backtest engine. (4) **TIGHT STOP re-examined — I WAS WRONG that it 'hurts'.** Stop sweep payoff
        ratio (avg_win/|avg_loss|): 5%→**5.26**, 8%→3.84, 15%→2.85, 20%→2.61. Tight stop nearly DOUBLES the
        payoff ratio (Minervini's core edge: tiny losses → modest win-rate hugely profitable). Its mean
        only drops on a FIXED-HOLD basket because that can't exploit the asymmetry — **tight stop +
        progressive add-on are TWO HALVES OF ONE mechanism** (cut losers small, concentrate into winners).
        → BUILD PLAN: pivot-trigger entry + progressive add-on + tight (6-8%) stop, re-run the lottery lens;
        test = fan TIGHTENS *without* kneecapping the tail (what the governor failed).
      - ✅ **PIVOT-TRIGGER IS ALREADY IN t3 — no recompute (user asked to check, 2026-07-09).**
        `t3_sepa_features.breakout_momentum = (close − high_20d)/atr_14` (>0 = cleared the 20d-high pivot
        today, ATR-normalized) + `vol_ratio = volume/vol_avg_50` (volume confirmation). Trigger =
        `breakout_momentum>0 AND vol_ratio>~1.4`. REGIME-AWARE FOR FREE: 28% of names trigger in the 2013
        bull vs 0-1% in the 2008/2020 crashes → self-throttles by breakout supply (a cleaner, more
        fundamental version of the governor's macro gate). (daily_features table doesn't exist; t3 is the
        source. VCP itself stays in the model, not re-weighted — only the TRIGGER EVENT is added.) Build
        scope confirmed: forward-return lens first, join t3 trigger cols into start_day_basket_paths.
      - ⚠️ **MINERVINI OVERLAY BUILT + TESTED — does NOT beat the naive basket IN THIS LENS (honest null,
        2026-07-09).** `basket_paths_minervini` (pivot-trigger `breakout_momentum>0 & vol_ratio>1.4` +
        progressive half→full add-on + tight stop). Head-to-head vs baseline (all-top5, 15%): at EVERY
        stop level the trigger version has WORSE median (−8%..+1.7% vs +5.4%), HIGHER losing% (48-62% vs
        42%), similar/wider std, LOWER max (595% vs 1025%). Trigger-without-progressive also worse. **BUT
        win/loss payoff ratio doubles (6.18 @7% vs 2.85) — the asymmetry IS there.** WHY the null: (1) the
        model ALREADY priced the breakout (`prob_elite` trains on breakout_momentum/dist_20d_high) → the
        trigger is ~a double-count, just subsets to the MOST-EXTENDED = most whipsaw-prone names (confirms
        the #2 don't-re-weight-VCP concern). (2) The fwd-return lens CANNOT model Minervini's real edge —
        no TRAILING stop, no BREAKEVEN-move, no intraday progressive adds; "add half @d10 if +10%" is a
        pale shadow. The 6.18 asymmetry needs the BACKTEST ENGINE to harvest (trailing stop to breakeven +
        progressive fills). **Honest verdict: don't oversell — the overlay is a null in this lens; the
        payoff-ratio signal says port the trailing-stop + progressive-fill mechanism to the engine, OR
        accept the naive basket is the honest arena candidate.** `start_day_basket_paths.py::basket_paths_minervini`.

## Thread G — population rectification: re-derive the champion honestly, then confirm on BackTrader (2026-07-09)

21. **The SEPA-gate fix invalidated the governor verdict — did it also break the Sprint 13 Arena?**
    → **Yes.** The arena selected top-5 from the ~99% off-setup scored panel (no trend_ok/breakout_ok
    gate at selection). The `sl15×tpTight` champion + the m2 cone were all population-inflated.
    `plans/population_rectification_plan.md`, annotated `sprint_13/.../strategy_exploration_summary.md`.
22. **Build a Minervini exit+entry and re-run the arena on the gated population.** → M1: built
    `exit_policy='minervini'` (breakeven-ratchet) + progressive fills in `vectorized_backtest.py`.
    Prog-fills is the load-bearing piece (ratchet alone NULLs; single-window Sharpe 0.35→1.19).
23. **Does minervini+prog-fills beat the honest (gated) sma across the start-date cone?** → **Vec cone:
    YES** — median 1.44 vs 1.00, %neg 5% vs 25%, prog-fills chosen 20/21 folds, rescues GFC/2017 losers.
    `verdicts/2026-07-09_m2_minervini_vs_sma_gated_cone.md`.
24. **Does it survive the BackTrader confirm (M2b)?** → ⟳ **NO.** Ported prog-fills to `SEPAHybridV1`;
    BT cone median 0.53(base)/0.35(prog), %neg 45% — a WASH. `verdicts/2026-07-09_m2b_backtrader_confirm_FAILS.md`.
25. **Is the vec↔BT gap tuning or engine?** → **ENGINE.** Same fixed config both engines: vec median
    1.51/%neg 10% vs BT 0.35/%neg 45%; ~3× optimism, concentrated in bear folds. → memory
    [[project_vec_engine_optimistic]]. **Champion stays the native tranche exit; minervini NOT promoted.**
26. **Does the SPY-200d deploy gate confirm on BackTrader (M4)?** → **YES, and it UPGRADES the vec
    verdict.** 25y gated cone, native-tranche baseline vs +SPY-200d gate: the gate improves EVERY metric
    (agg Sharpe 0.52→0.79, return 299%→794%, maxDD −61%→−37%, %neg 45%→35%). Win = 3 deep-bear rescues
    (2008 −1.86→+2.50 gate-open 2%, 2022 −1.69→−0.33) dwarf 4 mid-cycle whipsaws (2007/2018/2010/2014).
    The vec governor verdict's "DD-controller only, costs the mean" was a vec ARTIFACT — vec understates
    the bear damage the gate prevents ([[project_vec_engine_optimistic]]), so only BackTrader can value a
    crash-avoidance overlay. `champion_spygate` = the promotion candidate for the deployment layer.
    `verdicts/2026-07-09_m4_deploy_gate_backtrader_confirm.md`.

## Thread H — step back: why is the population limited to breakouts? (population reframe, 2026-07-10)

27. **Why do we train the ranker only on breakout rows — does that cause the start-date lottery?**
    → **Yes.** The project collapsed Minervini's watchlist(rank)+breakout(trigger) funnel into one:
    `trend_ok AND breakout_ok` = both universe AND training pop. Ranking the post-trigger slice is
    circular (signal already spent, IC≈−0.03); a breakout-only universe is a clustered event stream →
    lottery. `verdicts/2026-07-09_population_reframe_tail_ranker.md`.
28. **Does ranking the full trend panel by RS recover a selection edge?** → **Only on the TAIL, not the
    median.** MEDIAN inverts (weak-RS > strong-RS) AND the breakout pool ramp = trend panel ramp (no
    privileged info) → naive pivot refuted. TAIL: home-run rate monotone 2.21%→12.66% (**5.7×**), P90 2×.
    → memory [[project_population_reframe_tail_ranker]].
29. **Is this just the parked m02_breakout relitigated?** → **No.** m02 = event-timing regressor,
    returns NON-monotone (peaked D7, died D10 = selection bias); this = outcome-magnitude ranker, monotone
    to D10. Lesson carried: "signal works ≠ trade works" → must survive entry-conditioning + cone + BT.
30. **How is the target horizon defined if SEPA's is undefined?** → **Two-clock split:** FIXED
    policy-free horizon to RANK, UNDEFINED SEPA event-terminated horizon to HOLD (in the backtest exit,
    not the label). Keeps selection un-entangled from exit mechanics. `plans/m01a_tail_ranker_plan.md`.
31. **At which fixed N is the RS→tail ramp strongest, monotone-to-D10, and date-stable?** → **N=63,
    GATE PASSES (M0 done 2026-07-10).** Entry-conditioned MFE, N∈{21,42,63,126}: top-end strictly
    monotone in EVERY horizon × date-third (m02 anti-test passes everywhere); N=63 most date-stable
    (D10/D1 = 5.7–6.7× across thirds, D10 home-run 28.45%); N=21/42 steeper but sparse pre-2020,
    N=126 threshold saturates. Label = continuous `max(MFE_63−0.30, 0)`, binary home-run as diagnostic.
    `verdicts/2026-07-10_m0_horizon_sweep.md`.
32. **Does the fixed-horizon MFE label survive LeakageGuard, and what's the RS-only bar (M1–M2)?**
    → **YES + bar set (2026-07-10).** `m01a_tail_v1` registered (1.61M rows, 11.45% positive), 1500-row
    audit clean. Side-find: NEW dirt class — isolated corrupt highs (EXEL 999.99 sentinel) poison
    unwinsorized tail_mag means AND would poison M3's high-based features → **fixed at source**:
    part G of clean_dirty_shares_price.py nulled 178 highs (>2× body + no dollar-volume support;
    real pumps like PHUN 2021-10-22 kept; corrupt LOWS deferred — real flash crashes, no separator).
    Label guard then removed; M2 table bit-identical. RS-only bar: top-decile tail_mag lift 3.5×,
    top-5% 4.2× (home-run 2.5×/2.7×), stable across date-thirds.
    `verdicts/2026-07-10_m1_label_m2_rs_baseline.md`.
33. **Does an ML ranker (m01a_v1_h63) beat the RS-only bar out-of-sample and across start dates
    (M3)?** → **NO — kill criterion #2 fires, ship the one-column RS rule (2026-07-10).** Tweedie
    on tail_mag + binary logistic on home_run (fs_m01_prototype ∩ cache = 86 feats, anchored WF
    2003→, 15 OOS folds 2012–26, embargo 100d, no reweighting): D10 lift 3.88×/3.93× vs RS-same-fold
    3.87× — a WASH (7–8/15 folds, worst margin −1.2). Temporal break: ML beats RS 6/7 folds
    2012–2018, loses 13/16 variant-folds 2019+ (not data scarcity — anchored folds GROW). Both
    objectives agree fold-by-fold → features/population bind, not the loss. Un-tuned by design
    (tuning to scrape +0.1 = forcing the ML). M4 selection = top-X% RS, no model registration.
    `verdicts/2026-07-10_m3_ml_vs_rs_bar.md`.
34. **Does RS-selection × breakout-trigger × SEPA-exit beat the incumbent champion on the
    BackTrader start-date cone (M4)?** → **NO — kill criterion #3, incumbent stays champion
    (2026-07-10). m01a plan CLOSED.** Clean A/B (champion exits/slots, 90 quarterly-start × 12m
    BackTrader cells 2003–26, post-gate-fix pop): rs_tail median Sharpe 0.10 / 47% neg vs
    champion_gated 0.47 / 33%; rs wins 33/90 paired cells, loses every era; equal trade counts (not
    cash drag). Why: RS concentrates the TAIL but its MEDIAN inverts — stop+tranche exits realize the
    median path and truncate the tail the label measures ("label lift ≠ trade edge", the m02 lesson
    on the selection side; exactly what M4 exists to catch). RS rule stays banked as the LABEL-level
    watchlist axis. Side deliverable: the incumbent's first post-gate-fix full-span reference cone
    (the Jul-5 −39..+197% lottery numbers were inflated-population). Un-pursued (would be cone-
    fitting): top-X sweep, tail-harvesting exits, RS×prob_elite combo.
    `verdicts/2026-07-10_m4_rs_tail_backtrader_cone.md`.

## Thread I — the SEPA funnel program: consolidate ground truth, then close steps 2–4 (2026-07-10)

> After m01a closed (Thread H), a review set the frame: **"null" is 3 currencies** — C1 label-ranking /
> C2 OOS-ranking / C3 exit-aware P&L. m01a-null (C2+C3) ≠ m01-null (m01 won C3). Steering doc
> `plans/sepa_ground_truth_roadmap.md`; memory [[project_sepa_three_currencies]].

35. **Are Minervini's step-2 fundamentals a real ranker beyond RS (R1/R1b)?** → **NO — SUBSUMED by RS.**
    rev-growth/margin-trend have real unconditional ramps but are RS-correlated (mediator); EPS
    growth/accel U-shaped nulls; verbatim screen dominated 3× depth-matched, era-fragile. Second axis =
    SIZE (label-level). `verdicts/2026-07-10_r1b_step2_screen.md`, `_r1b_axis2_smallcap.md`.
36. **Does a tail-harvesting exit convert RS-tail selection, or help the champion (R3)?** → **Helps the
    CHAMPION (+0.21 median Sharpe, era-robust), NOTHING for RS-tail (C≈B).** RS-tail un-monetizable
    under BOTH exits (0.10 tranche AND trail). Selection dominates exit (D vs C +0.42). de-gate NOT
    triggered. `verdicts/2026-07-10_r3_exit_selection_coupling.md`.
37. **Should we de-gate m01's breakout gate to expand training?** → **NO, PARKED.** De-gating =
    reproducing RS-tail selection, which stays null under the best exit (Q36) → inherits its null.
    Gated behind R3 by design; R3 landed on "exit helps, selection doesn't" → de-gate unjustified.
38. **Does any leadership trait (step 3) stack ≥1.3× on RS-D10 (R2)?** → **NO — step 3 collapses into
    RS.** Group-leadership = RS-clones (ρ 0.57–0.80); base-character (vcp/tight/52w-high) flat-to-
    inverted; only residual = upside-only vol tilt (adr_20d/natr 1.28×, below gate). Passport = manual
    aid. `verdicts/2026-07-10_r2_leadership_profile.md`.
39. **Does a rising-trail-from-entry fix champion_trail's median bleed (R3b)?** → ⟳ **NO — FALSIFIED.**
    The ratchet ELIMINATES the trend exit (38%→2%→1%), clipping the winners that made champion_trail
    work; monotone worse tighter (e25 0.32, e15 −0.29 vs 0.46). The median bleed and the tail are the
    same coin → champion_trail is a local optimum. `verdicts/2026-07-10_r3b_rising_trail_from_entry.md`.

40. **Does the SPY-200d deploy gate stack on the trail exit → promote champion_trail?** → **YES —
    PROMOTED.** Built the missing `champion_trail_spygate` arm, ran the 90-cell cone: all-metric win over
    ungated arm D (floor −2.62→−1.93, median 0.46→0.76, %neg 33%→28%, era-robust) — same signature M4
    found on tranche. Paired count (36% wins) misleads: gate inert in bull windows, all value in bears →
    judge distribution not pairs. New champion; tranche demoted. `verdicts/2026-07-10_r3_deploy_gate_reconfirm.md`.

**SEPA funnel program CLOSED** — R1/R1b/R2/R3/R3b/R4 + deploy-gate re-confirm all resolved. Selection =
one-column RS (+ size axis, label-level); exit+deployment = `champion_trail_spygate` (PROMOTED); the 63d
MFE tail is watchlist-ordering value, NOT systematic alpha. **No open action remains.**

## Thread J — the portfolio layer: from per-draw lottery to aggregated book (2026-07-11)

> Mid-sprint review (summary EDA + §6 follow-up closures, `logs/2026-07-11_summary_eda_linear_story.md`)
> concluded the SELECTION layer is saturated (Threads H/I kills) — the open questions live in the
> PORTFOLIO layer. **Strategy PURPOSE locked in (user, 2026-07-11):** the ideal trade is a stock with a
> confirmative breakout + strong fundamentals + momentum + institutional money coming in — so the
> BREAKOUT population is the intended hunting ground BY DESIGN (conviction over coverage), not a
> historical accident. End product is HUMAN-IN-THE-LOOP: the system outputs a handful of names for
> human review; technicals/price action are applied by the human at the last mile. Not an automatic
> trading system.

41. **Is the champion still a lottery?** → **Reframe, not a defect.** The equity fan is a PER-DRAW
    instrument (no re-entry; stopped names freeze); the BackTrader champion is already a ROTATING BOOK
    (exits free slots → later signals refill, cash-blocked). The fat-tail/flat-median population makes
    each draw a lottery by construction; every "safety" lever tested (score gate, per-name SL, macro
    model, governor, sector) is a variance knob, not an alpha knob. The way out is AGGREGATION (earn the
    mean, not the median) — but the rotation anatomy of the champion book has never been examined
    (slot utilization, exit→refill latency, refill-vs-fresh trade quality, concurrent exposure).
    → **planned: rotation-anatomy instrumentation of the champion trade logs (Direction A).**
42. **Temporal breadth vs cross-sectional breadth?** → **Temporal wins on existing evidence.** Widening
    top-5→10 within a day dilutes (Q14 cliff); day-over-day the gated pool is a FRESH draw (Q8, 0%
    persistence) → spreading entries across days adds diversification at full score. Caveat: consecutive
    days share the regime — temporal spread diversifies name-luck, not regime-luck (SPY-200d gate owns
    that axis). Test design (user): **max-1-position-per-day strategy**, top-1 by model score, exits/SL
    identical to champion; candidate-pool variants: (i) full breakout pool, (ii) today's NEW candidates
    only, (iii) highest trailing-average score, (iv) score down-weighted by age.
    → **planned after Direction A (Direction B).**
43. **If trend_ok becomes the population, retrain m01?** → **NO.** Covariate shift is real (m01 trained
    on breakout snapshots; trend_ok rows are off-manifold, calibration population-specific) BUT m01a M3
    (Q33) already ran the retrain-equivalent: a fresh ML on the trend_ok panel TIES one-column RS OOS.
    For the trend_ok tier use RULES (RS × size × liquidity + defensive relvol tag from §6c geometry);
    keep m01 on the breakout tier where its industry-shaped residual is real (+9.7pp within-cell).
    → two-tier watchlist architecture; feeds the human-review product.
44. **What does the champion's rotation actually look like (Direction A)?** → **Slot-constrained, not
    signal-constrained.** From the 90 persisted cone cells (no re-runs): book runs at 3.8/5 mean
    occupancy, 55% of days full, refills the SAME day a slot frees; ~23 trades/12m, hold ~29d,
    52% stop / 45% trend exits. Headline: the `no_slots` QUEUE (~1,300 rejected signals/cell-yr) is
    nearly as good as the book at label level (fwd100 +5.7% / HR 17.5% vs entered +6.4% / 21.0%) —
    marginal capital would earn ~90% of the booked edge. Refill timing is quality-neutral (the
    apparent refill penalty decomposes into regime composition). → licence for breadth via slots /
    cadence, feeds Q45. `verdicts/2026-07-11_rotation_anatomy.md`.
45. **Temporal breadth: max-1-position-per-day (top-1 by score), exits identical** → **WASH — the
    cadence knob doesn't bind (2026-07-11).** 90-cell paired cone: top1 drip median 0.65 vs champion
    0.76 (−0.10), IQR −0.32 (narrower), %neg −2pp, floor −0.13; wins only 40% of cells, worst in
    2003-09 momentum eras. Anatomy: with ~29d holds the book turns over ≤1 slot/day anyway — drip
    reaches 5/5 in ~5 days, only ~14 daily_cap rejections/yr; the stagger the fan motivated is ALREADY
    implicit in the slow rotation. Champion unchanged. Wave 2 pool variants (new-only / trailing-avg /
    age-decay) PARKED — cadence doesn't bind, and within-pool re-ranking is a closed kill (Q33, §3c).
    **Next honest lever = slot COUNT (capacity), one ex-ante arm (10 slots @ 10%), NOT a sweep** —
    distinct from the closed Q14 (same-day widening): it deepens the book across days, drawing from
    the near-book-quality no_slots queue Q44 priced. `verdicts/2026-07-11_q45_temporal_breadth_top1.md`.
    **Side find (FIXED)**: `entry_top_n` was declared but NEVER ENFORCED in `SEPAHybridV1._process_entries`
    — entries were sliced by available_slots only. Champion unaffected (slots=5 ≡ top5; regression-verified
    byte-identical), but any arm with entry_top_n < max_pos was mislabeled (e.g. S1_baseline_top3 could
    enter up to 8-12/day). Fix: per-bar cadence cap `min(available_slots, entry_top_n)` + new `daily_cap`
    rejection reason. Verified: top1 arm max 1 entry/day, daily_cap logged, smoke tests pass.
46. **Capacity: does the edge survive a 2× book (10 slots @ 10%)?** → **YES — Sharpe holds (capacity
    fact, NOT a promotion).** One ex-ante arm, 90-cell paired cone: median 0.81 vs 0.76 (+0.05 ≈
    noise), floor +0.16, but p25 −0.29 / IQR +0.42 — 47 trades/yr, book genuinely fills (7.3/10).
    Q44's queue-quality prediction confirmed in realized P&L: the marginal name is as good as the
    booked one; 2× capital deployable at flat expectancy. Extra names add regime-correlated exposure,
    not diversification. **Champion stays at 5 slots.** Thread J portfolio conclusion: the book design
    isn't leaving Sharpe on the table — the residual constraint is REGIME CONCENTRATION, which no
    portfolio knob tested (cadence Q45, breadth Q46, stops §6a, gates §2c) removes.
    `verdicts/2026-07-11_q46_capacity_n10.md`.

47. **prob_elite gate mismatch: the backtest floor (0.15 CALIBRATED ≈ raw 0.48 coin-flip) was never
    reconciled with the EDA's 0.6-RAW gate — does raising it help? (⚠️ OPEN)** → **NO for the
    champion — it's a VARIANCE knob, not alpha.** Motivation: on famine days the day's best breakout
    is itself low-score, so 0.15 enters 'the best of a bad lot' — a higher floor blocks REAL entries
    (415/20% at 0.20, measured; overlap with SPY-gate ≈0%, these are bull-regime entries). ⟳ FIRST
    took the wrong angle — post-filtered persisted trades + read a paired win-rate as absolute →
    "no rerun" (WRONG; corrected [[feedback_rerun_dont_postfilter]]). Real rerun: registered
    `champion_trail_spygate_g{20,25,30}`, paired 90-cell cone. **0.15 WINS median Sharpe (0.59 vs
    0.46/0.51/0.35)**; higher gates buy floor (−1.74→−1.44), p25 (+0.03 @0.25), %neg (30→24%) but
    cost median return and — at 0.30 — the TAIL (p90 totret 51→31%, trades halve). Reconciles the EDA
    (§2b: raw gate lifts label mean+tail but flat median / worse loss-rate) with the engine (exits
    truncate the exact tail the gate concentrates → label lift ≠ trade edge). Fix as proposed is
    wrong-signed; g0.25 = a defensive-variant candidate only; champion stays 0.15. **NOT resolved** —
    user has further checks (different exit, gate×selection, non-Sharpe objective).
    `verdicts/2026-07-11_prob_elite_gate_sensitivity.md`, `plans/2026-07-11_prob_elite_gate_mismatch.md`.

## Thread K — bridge to ship: the two deliverables (2026-07-12)

> Product assembly, not research: turn banked verdicts into two artifacts a human reviews each
> morning (roadmap `plans/2026-07-12_deliverables_roadmap.md`). Both are HUMAN-IN-THE-LOOP outputs
> (Thread J purpose). SHIPPED this session.

48. **Shortlist: how to present the validated tail edge as a daily artifact?** → `v_d3_shortlist`
    view ON `v_d3_lifecycle` active cohort (not a re-join), ranked `(RS %ile + smallcap %ile +
    prob_elite)/3`, liquidity + posture tags, tail-odds not point returns. Model-swap = `status_flag='prod'`
    (NO champion flag exists). SHIPPED. [[project_weather_gauge_shortlist]]

49. **Weather gauge: combine SPY-200d + stress + supply into one posture?** → `weather_gauge` table
    (`src/weather_engine.py`, Phase 7.45, reuses MacroSizer). §B3 rule: SPY≤200d=STAND ASIDE (brake);
    above → famine∧high-stress=DEPLOY MORE / flood∧low-stress=TRIM NEW / else DEPLOY. SHIPPED.
    ⚠️ **DEPLOY MORE fires once in 23yrs** (bull-stress-famine is rare — GATE×TILT tension); chip
    near-dead live but faithful to the rule. [[project_weather_gauge_shortlist]]

50. **B5 — stabilize the stress sub-axis so `stress_z` graduates from provisional? (✅ CLOSED 2026-07-13)** →
    **EMA10 the composite before the expanding-80th cut → chatter gone (65→19 toggles, 19→≤1 blips).**
    Raw `stress_high` was a same-day threshold crossing: 33 True episodes, 58% were 1-2 day blips.
    Swept EMA5/10/20 — EMA10 is the knee (0 chatter blips, 43d median run; EMA5 leaves 3, EMA20 no
    better). Scope (user-confirmed): EMA10 ONLY (no hysteresis band — redundant), in `weather_engine`
    ONLY (NOT source `_stress_ew_vix`, which feeds the backtested governor — would need re-backtest).
    Only the `stress_high` TRIGGER is smoothed; displayed `stress_z` stays raw. **LEAK-FREE: as-of-date
    identity test = 0 mismatches** (recompute ending early vs full-history bit-identical; EMA past-
    weighted + expanding-quantile .shift(1)). `stress_z` PROMOTED from provisional. Side effect:
    DEPLOY MORE now fires 0× (was 1× 2010-05-07 — EMA delays onset off the famine∧>200d day); same
    GATE×TILT rarity, not a regression. **Follow-on (open, don't patch blind): loosen `stress_high`
    from top-quintile now the trigger is stable.** `verdicts/2026-07-13_b5_stress_deflicker.md`.

## Thread L — binary-over-4class: practical implications of the swap (2026-07-13)

51. **What does promoting binary practically require?** → `set_prod` + backfill ONE table
    (`daily_predictions`) + rebuild dashboard DB; no feature/price rebuild. **Found+FIXED a bug:**
    `v_d3_shortlist`/`v_d3_vip` read `prob_class_3 AS prob_elite` → NULL for a binary model
    (shortlist collapses to 0.25 base rate). Fix = `COALESCE(prob_class_3, prob_class_1)`,
    verified byte-identical for 4-class prod. ⚠️ UNCOMMITTED. [[project_weather_gauge_shortlist]]

52. **How different are the 4-class-homerun vs binary-threshold shortlist populations?** → Spearman
    0.96 but top-3/day overlap only 70%. `prob_elite` IS the same operation for both (p(homerun)
    = P(pos)); scales differ (0.315 vs 0.163) → gate by per-model quantile/top-N, never absolute.

53. **Is the binary shortlist actually better (equity fan of daily candidates, §6)?** → **WASH on
    raw top-5 return** (median +3.2 vs +2.9%, per-start +0.0pp). Binary's cone edge (0.81 vs 0.52
    Sharpe) is threshold/risk-adjusted, invisible in a threshold-free return fan. [[project_4class_vs_binary]]

54. **Why is binary `prob_elite` discrete (~447 levels)?** → **Model structure, NOT calibration**
    (scorer had no iso-calibrator). 100-tree binary booster + sigmoid collapses rows onto shared
    leaf-sums; 4-class (400 trees, softmax) is continuous. No smooth score hides under a plateau.

55. **Does raising the score gate improve fwd return (§7b/§9)?** → **NO — it's a RISK knob.** Median
    FALLS for both (monotone once selection removed); binary plateau cliff (>=0.35==>=0.45). Higher
    gate = lower median + fatter/skewed tail. Consistent with [[project_prob_elite_gate_variance_knob]].

56. **Isolate scoring from selection — drop the top-N clip (§9)?** → **The top-5 clip HURTS median:
    all-survivors +4.3% BEATS top-5-by-score +3.2%.** The model earns its keep at the GATE, not the
    within-pool rank (IC≈−0.03). [[project_scoring_vs_selection_unclipped]], [[project_breakout_pool_refinement]]

57. **Which attribute carries the shortlist edge (§8)?** → **mcap monotone LARGE>small on MEDIAN**
    (mega +6.8% vs micro −3.8%) — OPPOSITE the shortlist small-cap tilt. Not a bug: tail-odds (small)
    vs median (large) OBJECTIVE FORK. ? Sector: Industrials/Real Estate lead, Energy/Healthcare lag.
    Open: resolve the objective fork (user decision). [[project_r1b_step2_subsumed]]

## Thread M — trail-exit confirm + regime tiering / system-usage synthesis (2026-07-13, session 02)

58. **Does 4-class catch up to binary on the CHAMPION TRAIL-EXIT (not the simple exit), at a
    tight high-conviction gate?** → **NO — binary wins decisively.** `champion_trail_spygate_4cls`
    (4-class prod @ gate 0.60, else == binary champion), 90-cell cone: median Sharpe 0.76 vs 0.33,
    floor −1.93 vs −2.38, %neg 28% vs 38%, paired 4-class wins 32%, loses every era. Tight gate
    did NOT rescue it. **Binary confirmed as deploy candidate (NOT auto-promoted).**
    `verdicts/2026-07-13_4class_vs_binary_TRAIL_cone.md`. [[project_4class_vs_binary]]
59. **Does raising the gate widen the harvestable tail on the trail exit?** → **NO — label
    illusion.** Raising the gate lifts only the single `max` cell but LOWERS p90/p95 (the tail
    body). The exits truncate the tail the gate concentrates → median-for-tail trade isn't on the
    menu here. Third confirm of "label lift ≠ trade edge". [[project_prob_elite_gate_variance_knob]]
60. **Is the rotation infra working (can we jump ship to a better ticker)?** → **YES, works as
    designed — that's the problem.** Worst 2015 cell: 24 trades/23 tickers rotated over 6mo, stop
    at −11% MAE, 71% stop-out. In chop the replacement pool is the same failing population
    (IC≈−0.03) → rotating faster just pays the stop more. Not a bug; structural. [[project_scoring_vs_selection_unclipped]]
61. **Does the weather gauge flag 2015 as a bad regime (coincident is fine)?** → **YES — STAND
    ASIDE 53% of the 2015-07..2016-03 window**, SPY>200d only 47% (gate flipped 11×). BUT
    `stress_high`=0 → the **SPY-200d axis** caught it, not stress (trend breakdown ≠ stress event).
    Backtest gate = SPY-200d ALONE (verified). No portfolio-level DD breaker exists. Residual loss
    happens THROUGH the open gate (71% stop-out on gate-open days). [[project_weather_gauge_shortlist]]
62. **How should the system be used, and is one all-weather usage too generalised?** → **It's a
    FILTER, the human is the ranker** (~30 gated breakouts/day → human last mile). SEPA is a
    bull-regime TAIL strategy, not all-weather → **regime-TIERED usage** is the honest reframe
    (per-regime fan/cone; test whether higher gate pays in bull — user's live-pick hunch, Q47 never
    split by regime). Explore+document only this session; ideas → to-do tracker.
    `plans/2026-07-13_regime_tiering_and_system_usage.md`. [[project_capital_deployment]]

### Thread M cont. (2026-07-14, session 01) — regime-indicator test manual + §1.2 assessment

63. **Does ANY coincident regime gauge (15 candidates: SPY/QQQ technicals + breadth) beat SPY-200d
    at telling bad-days from good?** → **NO — all 15 FAIL, lever RETIRED (5th falsification).**
    Block A (nowcaster AUC, fwd50 cohort bad-day, WFO 50d-embargo): best = breadth **0.55** vs
    SPY-200d baseline **0.531** (0.65 wall); only significant deltas are candidates *worse* than
    baseline. Block C (cone, §7 leads §6.8 slope + §4 breadth): both **worse** standalone (median
    Sharpe 0.59 / 0.46 vs 0.76), composed-OR arms washes (overlap trap → candidate ≡ SPY-200d).
    Breadth calm-AUC 0.71 did NOT convert to P&L (label lift ≠ trade edge, 4th confirm). Regime is a
    mean-shift not day-separability, reconfirmed from a fresh feature set. **→ regime-expression CLOSED:
    SPY-200d is the whole axis; §0.5.4 fork = ONE axis; §1.2 unblocked, tiers on SPY-200d only.**
    `verdicts/2026-07-14_regime_indicator_manual.md` + `cells/regime-indicator-results.ipynb`.
    [[project_regime_indicator_manual_null]]
64. **§1.2 regime-tiered usage — feasible, and how?** → **ASSESSED (design only).** §1.2a/§1.2b are a
    CHEAP re-cut of existing cone `trades.parquet` (ungated `champion_trail`: 90 cells, 2664 trades
    both regimes), NOT new backtests. Order: §1.2b (bull-only gate sweep 0.15→0.30, tests the Q47
    hunch) FIRST → §1.2a (per-regime cone) if the split matters. Re-cut is DIAGNOSTIC only; promotion
    needs a fresh per-regime CONE (trade-log lift ≠ cone edge). Honest prior: 200d gate already
    captures most of "bull-trade/chop-standaside" → realistic upside = confirm gate is regime-
    conditional + formalize a chop tier, NOT a 2nd alpha engine. `plans/2026-07-13_regime_tiering_and_system_usage.md`.

### Thread M cont. (2026-07-14, session 02) — §1.2b re-cut + §1.2 close

65. **§1.2b — does a higher score gate pay in the BULL (SPY>200d) regime, where Q47's POOLED sweep
    found it hurts?** → **NO — market-regime does NOT tier the gate (hunch dead in this axis).**
    Re-cut the 2664 ungated `champion_trail` trades tagged by SPY-200d-at-entry (1766 bull / 898 chop),
    swept the gate 0.15→0.30 on the BULL subset only (`scripts/regime_gate_recut.py`, DIAGNOSTIC —
    per-trade distribution, no cone). Bull median FALLS monotonically with the gate (−5.46 @0.15 →
    −6.17 → −6.35 → −8.00 @0.30), = the pooled Q47 result, NO bull/chop interaction; %losing flat ~69%
    across gates; higher gate only buys the tail-vs-median fork (0.30: mean +0.92/p90 +28 but median
    −8, 25% kept) = the variance-knob signature *within* bull. Chop ref (not swept): chop@0.15 mean
    −1.11 vs bull@0.15 +0.05 → the 200d gate's value is removing the negative-mean chop cohort, which
    IS the regime lever. **→ NO-GO on a bull-only gate cone** (no separation to confirm = cone-fitting
    to run one). Q47's 0.15 stays champion in bull too. **⚠️ SCOPE (user): this kills the MARKET-regime
    gate hypothesis ONLY — see Q69.** `plans/2026-07-13_regime_tiering_and_system_usage.md` §1.2 header.
    [[project_prob_elite_gate_variance_knob]]
66. **Curiosity chart (user, overfit-for-intuition) — are the best trend-runners actually higher-scored
    on day 1?** → **WEAK-POSITIVE monotone lift; the EXIT decides the lens.** (a) Cone-trade scatter
    (`q65_score_vs_trendexit_scatter.py`): 1009 `exit_reason=='trend'` trades, Spearman ρ **+0.18**,
    top-score-decile median trend-exit +8.1% vs bottom +1.5% — best runners ARE higher-scored, weakly,
    huge overlap. (b) Fresh-scored `d2_training_cache` (38,556 trades, prod 4-class,
    `q65_cache_score_vs_return.py`) under the NATIVE-SEPA one-stop exit: the MEDIAN lens is misleading
    (ρ −0.09, stop caps the typical trade) but the TAIL lens is the signal — home-run rate P(ret>30%)
    **0.2%→14.2%** low→high decile (ρ_tail +0.19, monotone). Same median-wrong-lens lesson as the
    tail-magnitude work. ⚠️ IN-SAMPLE (cache=training set) → optimistic. OVERFIT by construction,
    intuition only, NOT a selection claim. `verdicts/2026-07-14_q65_*.png`,
    `cells/sprint_summary_eda_cells.md §A`. [[project_scoring_vs_selection_unclipped]],
    [[project_tail_magnitude_objective]]
67. **§1.1 DD circuit breaker — does a book-level 6% DD brake lift the cone floor?** → **NO — REJECTED,
    it LOWERS the floor (governor's fate, worse).** 90-cell paired cone vs champion: Sharpe median
    −0.04 vs +0.76, floor −2.82 vs −1.93 (WORSE), %neg 50% vs 28%; buys only drawdown (worst maxDD
    −44%→−25%). Trip-timing: 92% of 179 trips fire on gate-OPEN bull days (NOT the double-count trap —
    genuinely additive to the SPY gate) but clustered in the STRONGEST bull years (2020:15, 2013:13) →
    it halts on routine bull pullbacks and misses the recovery that carries the tail. A 6% book DD is
    inside the normal noise of a 55%-stop-out strategy; halting on it forfeits winners. **THRESHOLD
    SWEEP 6/10/15/20/30% PROVES mechanism-not-threshold:** median Sharpe rises monotone with the trip
    (−0.04→0.35→0.49→0.71→0.75) but NEVER exceeds champion (0.757 — asymptotes to do-nothing), while the
    floor is WORSE at EVERY level (−2.82 to −3.41, all < champion −1.93) — no trip lifts the floor. A
    strict Pareto-loss across the whole range. `verdicts/2026-07-14_overlay_floor_lift_cones.md`.
    [[project_capital_deployment]]
68. **Earnings-blackout (N=5 full-exit) — does force-exiting before prints lift the floor?** → **NO —
    REJECTED, worse than the breaker (costs return AND drawdown).** 90-cell cone: Sharpe median 0.49 vs
    0.76, floor −1.97 vs −1.93, %neg 36% vs 28%; maxDD uniformly WORSE. Mechanism (quantified):
    force-exits 630 trades = 23.6% of the book, 77% of them WINNERS at +17.4% mean vs champion trend
    winners +21.7% → clips the tail ~4pp below its run. The avoided gap-loss (−0.33% agg,
    [[project_backtest_stop_gap_fill]]) is tiny vs the tail forfeited. 4th "don't clip the tail" confirm.
    Lighter variants (frac/return-gate) inherit the mechanism directionally → not worth a cone unless
    reframed to "trim only over-extended winners". `verdicts/2026-07-14_overlay_floor_lift_cones.md`.
    **→ Both Thread M floor-lift overlays REJECTED; champion unchanged. SPY-200d gate remains the only
    distribution-shifting lever.**
69. **?OPEN (deferred, user 2026-07-14) — do MODEL-SKILL-regime periods exist where a higher gate
    pays?** §1.2b conditioned on MARKET regime (SPY>200d). A different, untested axis: periods defined
    by the *model's own tail-capture skill* (when the score is genuinely separating winners), NOT by
    market trend. §1.2b says nothing about it (wrong conditioning variable). Hard part = a LEAK-FREE
    live-safe proxy for "the model is scoring well now" to condition on. **User reframe (2026-07-14):
    don't assume the axis is bull/bear at all** — the periods that matter may be liquidity / risk-on-off
    / other, not trend; AND don't assume the model is good — put a question mark on that too. User: a
    real topic, explore later, not this session. (Curiosity chart = Q66, DONE.)
70. **?OPEN (deferred, user 2026-07-14) — does an EXIT MONETIZE the score's tail (C1→C3)?** The gap Q66
    raises: the score ranks the fat right tail (home-run 0.2%→14.2% low→high decile, ρ_tail +0.19 — a C1
    label-ranking win) but the champion cone is a start-date near-null (median Sharpe ~0.47 — a C3
    exit-aware null). Not a contradiction: Q66 is in-sample; ranking ≠ capturing (stop+trail truncate
    the label-tail); per-trade ≠ portfolio-path. **Two-stage, notebook-first (user):** Stage 1 = a
    single-trade path-REPLAY proxy in `sprint_summary_eda` cells (pull `price_data` bars per trade,
    re-sim a coarse exit set + a score-conditional "loose-for-top-decile-only" arm, gap-fill stub, group
    by day-1 `prob_elite` decile); read = does the top−bottom-decile REALIZED spread WIDEN as the exit
    loosens, and does loose-for-top-only BEAT loose-for-everyone? Kill = if not, tail un-monetizable
    under stops (RS-de-gate outcome) → C1 null banked. Stage 2 = backtest cone confirm ONLY if Stage 1
    passes AND the BT queue clears (still in-sample → go-look-OOS, not a promotion). Feeds the live
    `champion_trail` rising-trail thread. `plans/2026-07-13_regime_tiering_and_system_usage.md` §3.
    [[project_sepa_three_currencies]], [[project_prob_elite_gate_variance_knob]]

## Open meta-questions (carried)
- ✅ **Regime-EXPRESSION question CLOSED (Q63, DONE 2026-07-14):** 15-candidate manual — nothing beats
  SPY-200d (Block A all <0.55 AUC vs 0.65 wall; §7 cone leads worse standalone / OR-washes). 5th
  falsification; SPY-200d is the whole regime axis. `verdicts/2026-07-14_regime_indicator_manual.md`,
  [[project_regime_indicator_manual_null]].
- ✅ **§1.2b — per-regime gate sweep DONE (Q65, 2026-07-14): NO-GO, market-regime hypothesis dead.**
  Bull-subset median falls monotonically with the gate (= pooled Q47, no interaction); no cone worth
  running. Killed the MARKET-regime gate axis ONLY. `scripts/regime_gate_recut.py`.
- ?OPEN **§1.2 model-skill-regime gate hypothesis (Q66, deferred):** untested axis — periods of high
  model tail-capture skill (NOT market trend) where a higher gate may pay. Needs a leak-free
  skill-state proxy. + deferred curiosity: day-1 score vs trend-exit return scatter (overfit, intuition).
- 📋 **Thread M ideas (remaining, NOT implemented) — implementation separate.**
  🔨 IMMEDIATE: (a) earnings-proximity + (b) DD-breaker cone floor-lift runs (both WIRED, un-run);
  (c) 1-day entry-delay on the equity FAN.
  🔍 NEXT: §1.2a regime-tiered fan/cone, m02 breakout-PROBABILITY reframe (event-prob not fwd-return,
  watchlist-ripeness not alpha). ⏸️ DEFERRED: granular day-dispersion within good/bad months.
  `plans/2026-07-13_regime_tiering_and_system_usage.md`.
- ⏭️ **Binary promotion (Thread L/M, user go/no-go):** trail cone confirms binary wins → if
  promoting: `set_prod(binary)` + `backfill_daily_predictions` + rebuild dashboard DB; threshold
  by per-day RANK not absolute floor. NOT auto-promoted.
- ⏭️ **mcap objective fork (Q57, OPEN):** shortlist as tail-odds (keep small-cap tilt) vs
  median/Sharpe (drop/invert `smallcap_pctl`). One-liner either way; user decision.
- ✅ **B5 stress sub-axis stabilization (Q50, DONE 2026-07-13):** EMA10-smooth the composite before
  the expanding-80th cut → chatter gone (65→19 toggles, 0 blips), leak-free (as-of identity test),
  `stress_z` promoted from provisional. Follow-on OPEN: loosen `stress_high` from top-quintile now
  the trigger is stable (don't patch blind — needs its own check). `verdicts/2026-07-13_b5_stress_deflicker.md`.
- ✅ **champion_trail deploy-gate re-confirm (Q40, DONE 2026-07-10):** gate STACKS on the trail →
  `champion_trail_spygate` PROMOTED to champion. `verdicts/2026-07-10_r3_deploy_gate_reconfirm.md`.
- ✅ **M4 (DONE 2026-07-09):** SPY-200d deploy gate CONFIRMED on BackTrader (Q26) — improves every
  metric on the gated population; upgrades the vec governor verdict. `champion_spygate` flagged for
  promotion to the live deployment layer (user decision, not auto-promoted).
- ✅ **m01a/m01_tail M0 (Q31, DONE 2026-07-10):** GATE PASSES — N=63, tail-magnitude label
  `max(MFE_63−0.30,0)`. `verdicts/2026-07-10_m0_horizon_sweep.md`.
- ✅ **m01a M1+M2 (Q32, DONE 2026-07-10):** label clean, RS-only bar = top-decile tail_mag lift 3.5×
  / top-5% 4.2×. `verdicts/2026-07-10_m1_label_m2_rs_baseline.md`.
- ✅ **m01a M3 (Q33, DONE 2026-07-10):** ML ranker vs RS-only bar = WASH → kill criterion #2,
  **selection signal = the one-column RS rule**. `verdicts/2026-07-10_m3_ml_vs_rs_bar.md`.
  (Corrupt-high source-null DONE 2026-07-10, part G; corrupt-LOW cleanup deliberately deferred.)
- ✅ **m01a M4 (Q34, DONE 2026-07-10):** RS-selection LOSES the BackTrader cone (median 0.10 vs
  0.47) → kill criterion #3, **incumbent stays champion; m01a plan CLOSED** (M5 moot — SPY-gate
  already confirmed Q26). `verdicts/2026-07-10_m4_rs_tail_backtrader_cone.md`.
