# Design: M4 — magnitude regressor (rank names BY expected tail contribution)

**Date:** 2026-07-07 · **Status:** 📋 DESIGN ONLY — no training run this session
**Answers:** meta-question **M4** (RESEARCH_LOG). Design doc for a regressor/quantile model that ranks
candidates by expected forward-return MAGNITUDE, not P(>30%).
**Depends on:** M1's tail-magnitude objective (`verdicts/2026-07-07_tail_magnitude_recut.md`) — the
eval metric and the pro-cyclicality caveat are inherited from there.
**Reads:** `src/evaluation/training_data_loader.py` (`mfe_pct` + `DEFAULT_MFE_BINS`); verified the
live objectives against the ARTIFACTS (`models/*/v1/model.json` learner objective), NOT the doc —
see §0. (`docs/model_doc/m01.md` was stale on this — called the champion a regressor; **corrected
2026-07-07** to `multi:softprob` 4-class.)

> ⚠️ Design only. Everything below is a proposal to build next session; no model is trained here.
> HARD CAVEAT carried from M1: the ranking edge is **pro-cyclical** (top-1% lift median 6.8× but
> **0.68× in 2001/2008**, above-gate edge negative in 5/25 yrs). Any regressor trained pooled will
> INHERIT this. Regime-conditioning is not a nice-to-have; it is the whole point of M4.

---

## 0. The gap M4 fills (premise verified against the artifacts)

The live m01 family is **all classifiers** — verified from `models/*/v1/model.json` `learner.objective`:

| model | objective | what it ranks on |
|---|---|---|
| `m01_prototype` (CHAMPION) | `multi:softprob`, `num_class: 4` | `prob_elite` = P(class 3), classes = `DEFAULT_MFE_BINS` (Dud/Noise/Solid/Elite @ MFE 2/10/30%) |
| `m01_binary` | `binary:logistic` | P(MFE > 30%) |

**No model in the family expresses tail magnitude.** A +35% and a +400% both collapse into the "Elite"
bin; the score's most granular tail statement is a single probability of crossing 30%. But M1's
objective is **tail-lift@k** — rank names by their eventual *share of the fat tail*, which is a
magnitude quantity. A classifier that only knows P(cross 30%) cannot, in principle, prefer the name
that runs to +400% over the one that stops at +35%. **M4 = the first magnitude-aware model** — targets
MFE magnitude directly so the score can order names within the tail, not just at its edge.

**The hypothesis, stated as a mechanism (this is what must be true for M4 to win):** among
already-elite names (all P(>30%)≈1 to the classifier, hence unranked), *conditional expected
magnitude* carries residual ranking signal that P(cross) throws away — and that residual is exactly
where the tail-lift@k gap between "captures 6× of the tail" and "captures the biggest names" lives.
If conditional magnitude is unpredictable (pure luck once a name is elite), M4 dies — see §2's kill
switch. That is the real, falsifiable question, not "classifiers are bad at tails" in the abstract.

---

## 1. Target design — three candidates, all on `mfe_pct`

Same raw outcome column as everything else (`mfe_pct` = Max Favorable Excursion %, the SEPA outcome
already in the training cache). The live models **bin it into 4/2 classes** (`DEFAULT_MFE_BINS`),
discarding magnitude within a bin. M4 targets the magnitude directly instead of binning. Three
candidates, cheapest first:

| # | target | what it optimizes | tail behavior | cost |
|---|---|---|---|---|
| **A** | **raw `mfe_pct`, winsorized at ~p99** (not log) | expected magnitude, squared-error | keeps tail slope; winsor caps single-name blowups | drop-in, 1 target swap |
| **B** | **quantile regression at τ=0.90 / 0.95** (XGB `reg:quantileerror`) | the *upper* conditional quantile of MFE | targets the tail edge explicitly, robust to the body | new objective, same features |
| **C** | **tail-contribution target** `max(mfe_pct − 30, 0)` (the M1 leak variable itself) | directly the quantity tail-lift@k sums | zero for non-home-runs → sparse, heavy-tailed label | needs tail-weighted loss or it fits all-zeros |

**Recommendation: build B (quantile) as the primary, A (winsorized magnitude) as the cheap baseline,
skip C first pass.** Reasoning:
- **A** is the honest control: it answers "does a plain magnitude regressor (vs the 4-class classifier)
  already buy us tail-lift?" — the minimal change from classification to regression, run first as the null.
- **B** is the thesis: a τ=0.90 quantile regressor is literally "predict how high this name runs in
  its good case," which *is* rank-by-tail. XGBoost supports it natively (`reg:quantileerror`), so it's
  the same trainer with a different `objective` — no new dependency (ladder rung 5).
- **C** is the most on-target metric but the sparsest label (most rows = 0); it needs sample-weighting
  to not collapse to predicting zero. Defer until A/B show the target axis matters at all. YAGNI.

`# ponytail: A and B are both a single objective/target swap in the existing XGB trainer — no new`
`# model class, no new dep. C is the interesting one but sparse-label; only build it if A/B move tail-lift@k.`

---

## 1b. DECIDE FIRST — which outcome does everything measure on? (`mfe_pct` vs `fwd20`)

This is a design blocker, not a caveat, because it must be one column everywhere:
- M4's **target** above is `mfe_pct` (max favorable excursion over the hold — a best-point outcome).
- M1's **tail-lift bar** (the thing M4 must beat) was computed on **`fwd20` close-to-close** return.

Train on MFE, judge against a fwd20 bar = comparing on two different outcomes; the win/loss would be
uninterpretable. **Pick one and use it for target AND eval.** Recommendation: **train on `mfe_pct`,
re-cut the M1 champion bar on `mfe_pct` too** (re-run the multi-year tail-lift with `mfe_pct` as the
outcome — same toolkit, one column swap). Rationale: MFE is the outcome the whole m01 family already
targets, it's the tail-friendly quantity the strategy actually harvests (you exit near the favorable
peak, not at a fixed 20d close), and it keeps M4 comparable to the champion's own training objective.
`# ponytail: don't invent a new outcome — reuse mfe_pct (already in cache, already the family target)`
`# and re-slice the champion bar on it. One column, not a new pipeline.`

---

## 2. The eval — NOT RMSE (this is where M4 lives or dies)

RMSE on `mfe_pct` rewards fitting the body and is dominated by the tail's variance — the exact
failure mode that makes a naive magnitude regressor no better than the classifier. **M4 is evaluated
on M1's tail metrics, on the model's SCORE-RANK, identical harness to the champion, same outcome
column (`mfe_pct`, per §1b):**

1. **tail-lift@k** (top-1% / 5% / 10% share of total tail ÷ k) — the headline. Must beat the
   **champion's own tail-lift re-cut on `mfe_pct`**, measured **above the gate** (M1's 2025 3.2× /
   multi-year 2.7× median were on fwd20 — re-cut on mfe_pct before quoting a number). Above-gate, not
   the headline 6.1× which double-counts the gate (M1 Finding 2b).
2. **captured/missed tail magnitude** `Σ max(mfe_pct−30%,0)` at a matched selection budget.
3. **Reported as a DISTRIBUTION across 2001–2025, never one number** — and the acceptance bar is the
   **bad-regime floor** (2001/2008/2011), because that is where the champion collapses to <1× and
   where a regime-conditioned model is supposed to earn its keep.

**Falsification condition:** if M4's above-gate tail-lift@k does NOT beat the champion's on the bad
years (bootstrap-CI overlapping), the hypothesis is dead — conditional magnitude among elite names is
unpredictable (§0), the features are the ceiling not the label, and we stop. Honest kill switch.

---

## 3. Regime-conditioning — the non-optional part

M1 proved the ranking edge is pro-cyclical and a pooled fit inherits it. Two ways to condition,
cheapest first:

- **(i) Regime as a feature (already partly there).** The 7 `m03_*` cols are in `fs_m01_prototype`.
  But M03 is a *coincident state* label (regime_model.md §2) — it tells the model "we're in a bull"
  not "the tail is findable now." Weak lever for this purpose; it's why the champion is still
  pro-cyclical *with* M03 in it. Necessary, not sufficient.
- **(ii) Regime-STRATIFIED training / eval (the real fix).** Split the panel good-vs-bad
  (M1's 18-vs-7) and either (a) train a bad-regime-weighted model (upweight down-year rows) or (b)
  train two models and gate by SPY>200d at score time. Start with **eval stratification only** —
  train pooled, *report* the tail-lift@k split by regime — before spending a training run on
  reweighting. If pooled already holds up on bad years, (ii-a) is unnecessary (YAGNI).

**Sequence:** eval-stratify first (free, just a groupby on the existing multi-year cache), reweight
only if the bad-year floor is the thing that's broken.

---

## 4. Naming — id = `m04_regressor`

**Id decided (user, 2026-07-08): `m04_regressor`.** Its own lane (not an `m01_*` variant), signals the
regression target philosophy, and avoids the collision with the shipped regime model M03
(`models/m03_config.json`). Artifacts → `models/m04_regressor/v1/`.

---

## 5. Build sequence (next session, smoke-first per CLAUDE.md)

1. **Reuse, don't rebuild.** Same feature set (`fs_m01_prototype`), same loader
   (`load_training_data_from_db`), same XGB trainer, same multi-year scoring toolkit
   (`scripts/score_universe_multiyear.py`) and tail-lift analysis (`scripts/m1_multiyear_analysis.py`).
   M4 is a **target + objective swap**, not a new pipeline. (ladder rung 2.)
2. **Smoke:** train target A (winsorized magnitude) on ONE train window, score ONE year, compute
   tail-lift@k. Confirm the harness end-to-ends before the 25-year sweep.
3. Add target B (τ=0.90 quantile). Compare A/B/champion tail-lift@k on the smoke year.
4. Only if a target beats the champion on the smoke year → run the multi-year sweep, report the
   regime-split distribution + bootstrap CI.
5. Gate C (sparse tail-contribution target) behind A/B showing signal.

**No large run without user sign-off + smoke batch** (CLAUDE.md). Steps 1–3 are cheap; step 4 is the
25-year re-score (the expensive one) and needs the go-ahead.

---

## ⚠️ Caveats / open questions carried forward

- **The classifier may already be near-optimal.** m01_binary ≈ m01_prototype in the arena (dead heat,
  m01.md §5) — the 2-class and 4-class classifiers tie, suggesting the extra bin granularity buys
  little. If MORE granularity (a continuous regressor) also ties, magnitude-awareness isn't the
  bottleneck (features are) — target A as the null is designed to catch this before we over-invest.

- **Outcome mismatch RESOLVED in §1b** (not a lingering caveat): train and judge both on `mfe_pct`;
  re-cut the champion bar on `mfe_pct` before quoting a beat/miss.
- **DOC BUG fixed (2026-07-07):** `m01.md` had `m01_prototype` as a `log_space` regressor; artifact is
  `multi:softprob` 4-class. Corrected; `document-model` skill hardened to read `model.json` objective.
- **Everything is directional MFE, no exits/sizing/liquidity** (M1 caveat, unchanged). Note MFE is
  optimistic vs a real exit — a name that hits +400% MFE then round-trips still books its peak here.
- **Quantile regression gives a rank, not a calibrated probability** — fine for selection (we only
  need the ORDER), but it won't drop into any P(>30%)-gated path. It's a ranker, wire it as one.
