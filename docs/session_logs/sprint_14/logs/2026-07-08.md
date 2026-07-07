# Session Handover: 2026-07-08 (M4 magnitude-regressor design + m01 doc correction)

## 🎯 Goal
Design the M4 magnitude regressor (meta-question M4) — a design doc only, no training run — and, on
a user challenge, root-cause + fix a stale model-doc claim that the design initially relied on.

## ✅ Accomplished
- **M4 design doc written, then revised twice** (`verdicts/2026-07-07_m4_magnitude_regressor_design.md`).
  Final design: build the **first magnitude-aware model** in the m01 family — a regressor/quantile head
  on `mfe_pct` directly (the family is all classifiers, so tail magnitude is quantized away at label
  time; +35% and +400% both = "Elite"). Three targets: A winsorized-magnitude (null control), B τ=0.90
  quantile (`reg:quantileerror`, the thesis), C tail-contribution `max(mfe−30,0)` (deferred, sparse).
  Eval = **M1's tail-lift@k, NOT RMSE**, above-gate, on the bad years, as a distribution.
- **Sharpened the hypothesis to a falsifiable mechanism:** among already-elite names (all P(>30%)≈1,
  unranked by the classifier), does *conditional expected magnitude* carry residual ranking signal? If
  it's luck once elite, M4 dies — honest kill switch.
- **Resolved a real design blocker (§1b):** M4 target = `mfe_pct` but M1's tail-lift bar was on `fwd20`
  — comparing on two outcomes is uninterpretable. Decision: **train AND judge on `mfe_pct`; re-cut the
  champion bar on `mfe_pct`** (one-column swap in the existing toolkit).
- **Root-caused & fixed a stale-doc bug** (user challenge — "isn't m01_prototype a 4-class classifier?").
  Verified against artifacts: `m01_prototype` = `multi:softprob` num_class 4 (NOT the "regressor /
  log_space MFE" the doc claimed). `m01_binary` = `binary:logistic`. **No regressor in the live family.**
  Corrected `docs/model_doc/m01.md` §0/§1/§3/§4/§6 + usage. Also caught `n_estimators`: artifact has
  `num_trees=400` = 4 classes × ~100 rounds → real n_estimators ≈100 not 300; marked the other
  train-params unverified (XGBoost doesn't persist them, no config artifact found).
- **Hardened the `document-model` skill** so this can't recur: new rule — *read the model's IDENTITY
  (objective/target/num_class) from `model.json`, never from prose; artifact wins, fix the prose.* The
  old "cite real numbers" rule only covered metrics, not model identity — that was the gap.
- **Audited m02/regime docs too:** m02.md (`reg:squarederror`) ✅ matches artifact; regime_model.md
  (rules composite, no algo claim) ✅. Only m01.md was wrong.
- **Locked the id: `m04_regressor`** (user), own lane, `models/m04_regressor/v1/`.

## 📝 Files Changed
- `docs/model_doc/m01.md`: corrected champion from "regressor/log_space MFE" → `multi:softprob` 4-class
  (§0, §1, §3, §4, §6, usage); flagged unverified hyperparams; dated correction note in §6.
- `.claude/skills/document-model/SKILL.md`: new rule to read `learner.objective` from `model.json`
  before writing Spec §3 (identity, not just metrics).
- `docs/session_logs/sprint_14/verdicts/2026-07-07_m4_magnitude_regressor_design.md`: **new** — the M4
  design (revised: mechanism-framed §0, new §1b outcome decision, self-consistent eval, id=m04_regressor).
- `docs/session_logs/sprint_14/RESEARCH_LOG.md`: M4 open-question → DESIGNED (mechanism + §1b decision
  + id).

## 🚧 Work in Progress (CRITICAL)
- **Nothing half-finished. Design only — no model trained, no artifact folder created.** `m04_regressor`
  does not exist yet; `models/m04_regressor/` is a planned path, not a real dir.
- **Unresolved before build:** the champion tail-lift bar must be **re-cut on `mfe_pct`** (M1's numbers
  are fwd20) before any M4 beat/miss can be quoted. This is step 0 of the build, not done.

## ⏭️ Next Steps (build M4, smoke-first per CLAUDE.md)
1. **Re-cut the champion bar on `mfe_pct`** (multi-year toolkit, one-column swap) — the comparison
   baseline. Without this, M4's tail-lift@k has nothing honest to beat.
2. **Smoke target A** (winsorized-magnitude regressor) on ONE train window, score ONE year, compute
   tail-lift@k vs the re-cut champion bar. Confirm harness end-to-ends.
3. **Add target B** (τ=0.90 quantile). Compare A/B/champion on the smoke year.
4. Only if a target beats champion on smoke → 25-year sweep (the expensive re-score, **needs user
   go-ahead**), report regime-split distribution + bootstrap CI. Gate C behind A/B showing signal.
5. Regime-conditioning: eval-stratify first (free groupby), reweight bad years only if the floor breaks.

## 💡 Context/Memory
- **The lesson that generated the skill fix:** a model-doc described an *unshipped experiment*
  (log_space regressor) as the live champion. I trusted the doc over the artifact and built a design on
  it; the user caught it. Guardrail now in `document-model`: identity comes from `model.json`, always.
- **Why M4 can still win despite binary≈prototype dead-heat:** the 2-class and 4-class *classifiers*
  tie (extra bin granularity buys little) — but a *continuous* magnitude target is a different axis, not
  just more bins. Target A is the null that catches "more granularity also ties → features are the
  ceiling, stop."
- **MFE is optimistic:** a name that spikes +400% then round-trips still books its peak — no exits in
  this eval. Directional, not tradable P&L (the standing M1/sprint caveat).
- **Pro-cyclicality is inherited:** M1 showed the ranker collapses in 2001/2008 (<1× above-gate); any
  pooled M4 fit inherits it, so the acceptance bar is the **bad-regime floor**, not the bull ceiling.
