# Session Handover: 2026-07-07

## 🎯 Goal
Review the macro-vs-sweep notebook, sharpen the sprint-14 research questions, and produce a
runnable cohort-bootstrap study to measure the top-5 **selection bias** (gate vs. ranker).

## ✅ Accomplished
- **Reviewed `cells/macro-vs-sweep.ipynb`** (sprint 13 artifact). Confirmed its conclusion is
  correct and *resolved* (not conditional): no macro signal times entries; the **5-factor
  `veto_flag` is the one weak directional lever** (veto-off starts 32.6%/22.1% mean/median vs
  veto-on 21.7%/10.0%).
- **Diagnosed the two data-quality flags** the user raised:
  - "5-factor z-score truncated at 200/−40" → **not a data bug**. The orange line is
    `target_exposure×100`; exposure is hard-capped by the 6 exposure bands (floor 0.15, ceil
    1.00 → 15..100 on the ×100 scale). The flat-tops are the band step-function saturating, not
    truncation. `risk_5_factor.py` has no `.clip`/winsorize. Cosmetic axis only.
  - Clarified the "new macro model" = the **dashboard 6-pillar macro section**
    (`load_macro_pillars` in `scripts/dashboard_utils.py`, incl. CAPE_OURS), NOT the M03 doc
    (which is outdated vs. sprint 13). Key point: the 6-pillar macro is a **sizing** input, not a
    ranker — all tickers share it, so it can't break selection-bias ties (README:284 confirms).
- **Built + ran the cohort-bootstrap study** answering sprint-14 Goal 1's premise with numbers.
  Finding below. Draft: [cells/cohort-bootstrap_cells.md](../cells/cohort-bootstrap_cells.md).
- **Documented the research questions** in the sprint 14 README (see Files Changed).

## 📝 Files Changed
- `docs/session_logs/sprint_14/cells/cohort-bootstrap_cells.md`: **new** — 6-cell notebook
  artifact. Reconstructs the per-day gated tie-pool from existing sweep parquets
  (`trades`=picked, `rejections` reason `no_slots`=gated-but-unslotted), scores 20d fwd return
  from `price_data.close`, bootstraps the actual top-5 vs random 5-draws. Two tie-pool defs
  (`exact` = same tie score, `min` = ≥ lowest picked) reported side by side. Saves to
  `data/cohort_bootstrap/`.
- `docs/session_logs/sprint_14/README.md`: added the research-question framing under Goal 1 +
  a "Research questions we're answering" big-picture block; recorded the cohort-bootstrap finding.
- `docs/session_logs/sprint_14/verdicts/2026-07-07_selection_bias_cohort_bootstrap.md`: **new** —
  the finding write-up.

## 🚧 Work in Progress (CRITICAL)
- **Cohort-bootstrap finding is a SMOKE TEST, not a verdict.** Ran on ONE start window
  (`r_202101_h12`), 34–36 usable entry days → underpowered. Both tie modes agree (pick_percentile
  ~0.37, median edge ≈ 0, beats null ~31%) → top-5 ≈ random draw from the tie-pool on this window.
  **Do NOT act on it until it's looped over all 53 sweep cells (or the seed best/worst months).**
- The notebook itself has not been created (`.ipynb`) — user applies the cells manually
  (no-direct-notebook-edit rule). The draft was validated by running the code standalone.

## ⏭️ Next Steps
1. **Loop the bootstrap over all 53 cells** (or seed best/worst months) for a real verdict on
   selection skill. If pick_percentile stays ~0.5 in `exact` mode → confirmed gate-not-ranker.
2. **If confirmed random:** the lazy fix is **widen the basket** (hold 15–20, not 5) — one prod
   re-run of `scripts/run_starttime_sweep.py` with `entry_top_n` bumped; compare Sharpe/variance
   to top-5. This IS sprint-14 Goal 1 fix (a) "limit/rethink the selection set".
3. **Only if `exact` shows skill (pctile > 0.6):** build a within-cohort ranker (finer prob_elite
   or RS-momentum) instead of widening — and then test rotation/#5b (momentum persistence).

## 💡 Context/Memory
- **The selection bias is structural and now quantified:** `prob_elite` is coarse — on **55/57
  entry days every picked name shares ONE identical value**. The top-5 rank is a pure tie →
  random draw. This is the mechanism behind sprint-14's "top-5/day is effectively random
  rotation" premise; the bootstrap measures it directly.
- **Method insight:** the tie-pool definition is load-bearing. Raw picked-vs-rejected split
  (+1.9% vs −0.8%) looks like skill but conflates the **score gradient** (gating) with
  tie-breaking (ranking). The bootstrap on the tie-restricted pool separates them — and the
  *median* (not mean) is the honest stat (mean is inflated by a few right-tail days).
- **Lazy fix framing:** if the pick is random, don't build a ranker — hold the whole gated
  survivor set. No selection → no selection bias, no new model. Only build a ranker if there's
  measured skill to extract. Ties to memory [[project_cohort_vs_model_scores]] (pre-breakout has
  rank persistence, breakout doesn't → informs whether rotation could ever work).
