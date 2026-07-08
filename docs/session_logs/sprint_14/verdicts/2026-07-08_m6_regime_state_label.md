# M6 — regime STATE label + M4 tail-ranking by state (pro-cyclicality OVERTURNED, non-circularly)

> **⚠️ READ §3b + §5 FIRST — §1/§2 below are the ORIGINAL (macro-tercile, 2013+) build and are
> SUPERSEDED in two ways:** (a) the label now has TWO axes and **`dd` (realized drawdown, full 25y)
> is the DEFAULT**, not the macro tercile — see §3b; artifacts are `regime_state_daily_{dd,macro}.parquet`
> and `m4_by_state_{dd,macro}.csv` (the bare `regime_state_daily.parquet` / `m4_by_state.csv` named
> below were renamed/deleted). (b) A consumer #2 (m01×regime, full universe) + fwd50/100 enrichment
> landed AFTER this doc — see `verdicts/2026-07-08_m01_by_regime.md`. The M4-by-state CONCLUSION
> (counter-cyclical, cross-validated on both axes) is unchanged and correct.

**Date:** 2026-07-08 · **Status:** ✅ BUILT + RUN, then AUDITED + dd-axis added (§3b). Answers
meta-question **M6** (the deferred prerequisite) and, through it, revisits M4's circular
pro-cyclicality claim with an INDEPENDENT label.
**Scripts:** `regime_state.py` (`--axis dd|macro`), `m4_by_regime_state.py` (consumer #1, `--axis`),
`m4_wfo_taillift.py --dump-preds`, `regime_state_chart.py` (figures). **Artifacts:**
`data/model_output_eda/regime_state/{regime_state_daily_dd.parquet, regime_state_daily_macro.parquet,
m4_by_state_dd.csv, m4_by_state_macro.csv, fig*.png}`, `data/model_output_eda/m4_wfo/preds_A.parquet`.

---

## 1. The state label (model-agnostic, date-keyed)

A COINCIDENT state expression — NOT a timing signal — that any population can join by date
([[project_regime_during_period_goal]]). Reuses Thread F's live-safe machinery verbatim
(`load_macro_pillars_raw` + `add_stress_score` + SPY>200d), no re-implementation.

**States (discrete, named):**
| state | rule | 2013+ share |
|---|---|--:|
| **bear** | SPY ≤ 200d MA | 14.9% |
| **bull-stress** | SPY > 200d & `stress_ew_vix` in top tercile | 20.6% |
| **bull-calm** | SPY > 200d & not top-tercile stress | 64.5% |

Split rationale: stress FLIPS sign by trend (buy-tilt in bull, falling-knife in bear —
[[project_entry_timing_macro_axis]]), so bear is its own state; stress only sub-divides bull.
`stress_ew_vix` = expanding-z of (+credit, −rates, −cape, +vix), live-safe (day t uses only stats
through t−1).

**⚠️ HARD SCOPE — label is 2013+ only, and this is load-bearing, not a footnote.** Credit spread
starts 2003-01, CAPE_OURS 2012-12 → the composite is only fully populated 2013+. A first attempt cut
the stress tercile over the full 25y span; the boundary landed on the pre-2013 partial-composite
distribution and left only **45** stressed-bull days in 13 clean years — unstratifiable. Cutting the
tercile WITHIN the clean era fixes it (**704** stressed-bull days). So the label is scoped to 2013+
where all four pillars are live. **Consequence:** this window contains NO 2008/2001-scale crash — its
worst bear is 2022 (+ the brief 2020 COVID drop). True-crash behaviour (where M1 found pro-cyclicality)
is OUT OF REACH of this label and needs the **drawdown/vol axis** (the agreed next step, buildable on
`price_data` for the full 25y without the credit/cape gap).

---

## 2. M4's pro-cyclicality — OVERTURNED with an independent label

Joined M4 target-A's per-row OOS predictions (7 folds, 2013–2026, 25,898 rows) to the state label and
cut `cond_lift10` (= does the score rank the big winners WITHIN its own top-decile) inside each state,
each state self-contained (own score decile, own tail total).

| state | n | hr_rate | lift@1% | cond_lift10 |
|---|--:|--:|--:|--:|
| bull-calm | 19,215 | 12.5% | 6.43 | **1.62** |
| bull-stress | 5,036 | 12.7% | 9.88 | **2.44** |
| bear | 1,647 | 12.6% | 9.94 | **2.37** |
| ALL | 25,898 | 12.6% | 6.90 | 1.78 |

**The edge is NOT pro-cyclical — if anything it's counter-cyclical.** `cond_lift10` is WEAKEST in
calm bull markets (1.62) and STRONGEST under stress (bull-stress 2.44, bear 2.37). The M4 smoke's
"dies in the GFC" was **confirmed to be a circular artifact**: pooling all bear-state days 2013–2026,
the score ranks the tail *better* in bear than in calm bull, the opposite of the hand-picked fold story.
- **home-run base rate is flat across states (~12.5% everywhere)** → the difference is genuine RANKING
  power, not more/fewer tails to catch. The score separates winners best exactly when dispersion is
  highest (stress/bear), and has least to do when everything drifts up together (calm bull).

### ⚠️ Caveats (honest bounds — the result is directional, not settled)
- **bear is thin (1,647 rows) and 41% is 2022 (675 rows).** So "bear cond_lift10 2.37" ≈ "the tail
  ranking held up through the 2022 bear," NOT "robust across many bear episodes." One real bear, edge
  survived it — a genuine but single data point.
- **bull-stress (n=5,036) is the strong, well-distributed cell** (2013/2016/2020/2023) — the most
  trustworthy read: elevated macro stress → BETTER tail ranking. Consistent with Thread F (stress =
  good entry windows) now extended to: stress = good RANKING windows too.
- **2013+ has no 2008-scale crash.** This does NOT contradict M1's full-universe pro-cyclicality
  (below-no-skill in 2001/2008) — that lived in a deeper-crash era this label can't see. The two are
  about different severities; resolving them needs the drawdown/vol axis on the 25y span.
- Everything is directional `mfe_pct` (no exits/sizing) — same optimism caveat as the M4 smoke.

---

## 3. What this unblocks / next

1. **M4 regime-reweighting is now RUNNABLE** (was blocked on "no label to weight by"). But the finding
   argues AGAINST down-weighting stress/bear rows — the edge is BEST there. If anything, reweight to
   emphasize calm-bull is where the ranker underperforms. Decide direction before running.
2. **The durable goal — model-AGNOSTIC SEPA-candidate behaviour by state** (user steer: stay
   independent of m01/m04). Consumer #2: stratify the raw SEPA-candidate forward-return distribution
   (dispersion, hit-rate, drawdown shape) by state, so it survives model recalibration and can later
   feed regime IN as a training feature. Not built this session — confirm the population grain first.
3. **Drawdown/vol axis (agreed next step)** — adds a realized crash-STATE dimension that price_data
   supports for the full 25y, reaching the pre-2013 deep crashes the stress composite can't. This is
   what would let us test the M1 2001/2008 pro-cyclicality non-circularly.

## 3b. LABEL-QUALITY AUDIT + vol/drawdown axis (added 2026-07-08, same session)

On review ("how good is the label?") I stress-tested the label itself — which I'd skipped. Findings
revise §1's confidence:
- **Bear/bull trunk (SPY 200d) is GOOD** — its ≥20d runs match every known regime (dot-com, GFC,
  2015-16, 2018-Q4, COVID, 2022, 2025). Both axes share this and it's the trustworthy part.
- **The macro bull-stress split LEAKS by time.** `bull-stress` share: 2013 88% → 2017 0% → 2025 0%.
  Cause: expanding-z is mechanically higher early (short history → wider z), so a static tercile
  front-loads "stress" into 2013–2016. The macro stress state is confounded with WHEN, not just
  stress level — NOT comparable across time. (§1's "704 clean stressed-bull days" is real but those
  days are mostly early-era.)
- **Both states FLICKER** (macro 142 runs, median stress-run 1d; dd 208 runs, median 2–4d) — SPY
  oscillating around 200d + stress crossing threshold. Tolerable for POOLED stratification, ugly as
  a state narrative. Fix = a min-run persistence filter (not yet built).

**Built the vol/drawdown axis (`--axis dd`, now the DEFAULT):** bear = SPY<200d shared; bull-stress =
SPY drawdown-from-peak ≥ 10%. Price-only, stationary, live-safe, FULL 25y (reaches 2001/2008). Also
computes `spy_vol20` (20d realized vol). Its own weakness: "deep-drawdown-but-above-200d" is RARE
(752 of 25,898 M4 rows) → sparse/high-variance stress cell. So neither axis yet gives a clean,
persistent, well-populated stress state — **the stress sub-split is NOT settled; the bear axis is.**

**M4 finding CROSS-VALIDATED on both axes** (the important robustness check): cond_lift10 bull-calm
< bear < bull-stress on BOTH — dd (1.87 / 2.37 / 4.29) and macro (1.62 / 2.37 / 2.44). The
counter-cyclical result holds under two independently-constructed stress definitions. dd's 4.29 is
752-row high-variance; macro's 2.44 (5,036 rows) is the trustworthy magnitude; they agree on SIGN.

**Proposed next (user's call):** (1) persistence filter to de-flicker; (2) vol-percentile stress cut
(spy_vol20 already computed) — stationary AND fires in choppy-calm markets, fixing dd sparsity;
(3) run the dd axis on the SEPA-candidate population pre-2013 = the real "reaches 2008" test + the
model-agnostic during-period lens. Review cells: `cells/m6_regime_state_cells.md`.

## 4. Files
- `docs/session_logs/sprint_14/scripts/regime_state.py` — **new**, the date→state label + self-check.
- `docs/session_logs/sprint_14/scripts/m4_by_regime_state.py` — **new**, consumer #1.
- `docs/session_logs/sprint_14/scripts/m4_wfo_taillift.py` — added `--dump-preds` (per-row OOS export;
  keeps this harness the single source of fold scores, no re-scoring elsewhere).
- `data/model_output_eda/regime_state/{regime_state_daily_dd.parquet, regime_state_daily_macro.parquet,
  m4_by_state_dd.csv, m4_by_state_macro.csv, fig1-4*.png}` — durable evidence.
- `data/model_output_eda/m4_wfo/preds_A.parquet` — target-A per-row OOS (regenerable).

---

## 5. FINAL CONCLUSION (M6, as of 2026-07-08 wrap) + the VIX question

**Brief conclusion — what M6 established:**
1. **A regime STATE label exists and its BEAR/BULL trunk is solid** (SPY vs 200d MA; its runs match
   every known regime 2000-2026). Two axes for the stress sub-split; **`dd` (realized drawdown, full
   25y) is the default.** The stress sub-split is NOT fully settled (macro leaks by time; dd is sparse;
   both flicker) — but the trunk carries most of the signal.
2. **M4's tail-ranking edge is COUNTER-cyclical, not pro-cyclical** — weakest in calm bull, strongest
   under stress/bear — cross-validated on BOTH stress axes. The old "dies in the GFC" was circular.
3. **m01's whole-distribution ranking is REGIME-ROBUST** (consumer #2, full universe): the score ranks
   fwd return in every state; only the base LEVEL shifts. Stress/bear precede HIGHER returns than calm
   bull (gap statistically real by block-bootstrap), and **the gap + gradient GROW with the hold**
   (fwd100 ≫ fwd20). Judge on fwd100. NO pillar trunk beats spx200 (bakeoff).

**The VIX question (user, 2026-07-08) — is VIX-sizing the same as the regime, or different?**
Tested directly (VIX vs the dd label, 2000-2026):
- **VIX ≈ the BEAR/drawdown axis, essentially the same signal.** corr(VIX, is_bear) **+0.63**,
  corr(VIX, spy_dd) **+0.64**; mean VIX bear **28** vs bull-calm **16**; the high-VIX tercile is 69% bear.
- **VIX is almost identical to realized vol** — corr(VIX, spy_vol20) **+0.87**. So the proposed
  vol-percentile stress axis would largely BE a VIX axis (a point in its favor — it grounds the stress
  cut in the signal S13 already validated for sizing).
- **VIX does NOT track the current bull-stress state** (corr −0.08) — because bull-stress
  (drawdown-while-above-200d) is a narrow condition VIX doesn't isolate.
- **Reconciliation:** VIX-sizing and the regime are the SAME bet two ways — "deploy more when
  stressed." High VIX = bear/drawdown = the rebound zone where fwd returns are higher (§2 / consumer
  #2's +1.55% bear). They are NOT independent inputs; stacking VIX-sizing on a regime overlay would
  double-count one risk axis. If anything, VIX/realized-vol is the cleaner, full-history way to
  EXPRESS the stress axis than the leaky macro tercile.

**Wrap-readiness — what's still open (none blocking a wrap):**
- Stress sub-split not settled (persistence filter + vol/VIX-percentile cut) — a refinement, deferred.
- dd axis on the SEPA-candidate population pre-2013 (the real "reaches 2008" test) — deferred.
- Dashboard current-state badge + regime strip — DEFERRED as a separate deliverable (user).
- M4 regime-reweighting — runnable but the finding argues against it; parked.
These are all NEXT-sprint refinements, not gaps in the M6 conclusion. **M6 is wrap-ready.**
