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
