# Session Handover: 2026-07-13

## 🎯 Goal
Answer the practical questions around promoting the binary model over the 4-class prod
`m01_prototype`: what promotion actually entails, how the shortlist populations differ,
and whether the binary shortlist is really better — via equity-fan visualisation of the
daily-shortlisted candidates.

## ✅ Accomplished
- **Q1 promotion mechanics** — traced the full serving path. Swap is `set_prod` +
  `backfill_daily_predictions --model-version-id` + rebuild dashboard DB. Backfill exactly
  ONE time series (`daily_predictions`); no feature/price rebuild. **Found a latent bug:**
  `v_d3_shortlist`/`v_d3_vip` read `prob_class_3 AS prob_elite`, which a binary model writes
  as NULL → shortlist composite silently collapses to the 0.25 base rate.
- **Q1 fix APPLIED + verified** — `COALESCE(prob_class_3, prob_class_1)` in both views.
  Rebuilt both; 0 rows differ from raw `prob_class_3` under 4-class prod (byte-identical
  today), picks up `prob_class_1`=P(pos) when a binary model is prod. **Uncommitted (user
  said leave it).**
- **Q2 population diff** — scored both on the gated breakout pool. Rankings Spearman 0.96,
  but top-3/day overlap only 70% (top-5 78%, top-10 84%). Scales differ (4cls median 0.315
  vs binary 0.163) → never reuse an absolute cut; use per-model quantile / top-N.
- **Q3 shortlist equity fan (§6)** — binary vs 4-class daily-shortlist basket = a WASH on
  raw top-5 return (median +3.2% vs +2.9%, per-start diff +0.0pp). Binary's cone edge is
  Sharpe/threshold-driven, invisible in a threshold-free return fan.
- **Score distribution (§7)** — binary `prob_elite` is DISCRETE (~447 levels), NOT
  calibration: 100-tree binary booster + sigmoid collapses rows onto shared leaf-sums;
  4-class (400 trees, softmax) is continuous (122k distinct). Corrected an earlier wrong
  "isotonic" claim.
- **Gate sweeps (§7b, §9)** — raising the gate LOWERS median for both models (risk knob, not
  return knob); binary hits a plateau cliff (>=0.35 == >=0.45, identical rows). 4-class
  denser ladder decays smoothly.
- **UNCLIPPED sweep (§9, user's methodological fix)** — dropped the top-N clip (`top_n=None`
  now default-supported) to isolate scoring from selection. **Key finding: the top-5 clip
  HURTS median — holding ALL gate-survivors (+4.3%) beats top-5-by-score (+3.2%). The model
  earns its keep at the GATE, not the within-pool rank** (confirms IC≈−0.03). Higher gate =
  lower median AND fatter/more-skewed tail; downside never symmetric (SL floors it at −15%).
- **Attribute breakdown (§8)** — mcap is monotone LARGE>small on MEDIAN (mega +6.8%/34%-loss
  vs micro −3.8%/57%-loss); opposite the shortlist's small-cap tilt → a tail-vs-median
  OBJECTIVE fork, not a bug. Sector: Industrials/Real Estate lead, Energy/Healthcare lag.

## 📝 Files Changed
- `src/managers/view_manager.py`: `COALESCE(prob_class_3, prob_class_1)` in `v_d3_shortlist`
  + `v_d3_vip` — binary-model compatibility for `prob_elite`. Verified no-op for 4-class prod.
- `docs/session_logs/sprint_14/scripts/start_day_basket_paths.py`: `basket_paths` now accepts
  `top_n=None` (no clip → hold every gate-survivor). Default stays 5 (back-compat).
- `docs/session_logs/sprint_14/scripts/breakdown_basket_fan.py`: NEW — attribute-sliced
  equity-fan engine (sector/industry/mcap/RS), reuses `_name_path`; `basket_fan` defaults
  `top_n=None`. Has a `__main__` self-check.
- `docs/session_logs/sprint_14/cells/shortlist_fan_binary_vs_4cls_cells.md`: NEW — 12 cells,
  6 charts (§6–§9) for the summary EDA notebook.
- `data/score_cache/m01_prototype_2003-01-01_2026-05-22_sepa_gated.parquet`: NEW — 4-class
  gated score cache (mirror of the binary one) so the fan engine can plot both.
- `data/model_output_eda/sprint_summary/s6..s9b_*.png`: 6 rendered charts.

## 🚧 Work in Progress (CRITICAL)
- **View fix is UNCOMMITTED** (user chose to leave it alongside other in-flight `view_manager`
  edits). It's verified safe but lives in the working tree only. Re-apply/commit before
  promoting binary or the shortlist runs blind.
- **All fan findings are the vec / simple-exit (SL15%/SMA50/150d) engine** — model-RANKING
  cones, NOT the champion trail-exit. Nothing here is a promotion. Promote on BackTrader
  (`project_vec_engine_optimistic`).

## ⏭️ Next Steps
1. **If promoting binary:** re-apply/commit the view fix → `set_prod(binary)` →
   `backfill_daily_predictions --model-version-id <binary>` → rebuild dashboard DB. Decide the
   binary operating threshold (its edge is threshold-sensitive; gate by rank not absolute).
2. **BackTrader confirm binary on the champion trail-exit** — the real kill/keep gate
   (still the outstanding blocker from the 2026-07-13 cone verdict).
3. **Resolve the mcap objective fork** (user decision): is the shortlist a tail-odds product
   (keep small-cap tilt) or median/Sharpe (drop/invert `smallcap_pctl`)? One-liner either way.
4. Optional: sector triage in the shortlist (bury Energy/Healthcare — cheap add from §8).

## 💡 Context/Memory
- **The model's value is the GATE, not the within-pool rank.** Unclipping proved a broad
  gated basket beats top-N-by-score on median. This reframes "improve the shortlist": don't
  chase a better ranker within the pool — the score already did its job selecting breakouts.
- **Binary discreteness is a model-structure artifact** (tree count + sigmoid), not
  calibration — so there's no smooth score hiding under a plateau to re-rank on. Gate binary
  by per-day rank/percentile, never an absolute floor.
- **The shortlist small-cap tilt is deliberate** (tail-odds design), not a defect — §8's
  "large wins" is median-only. Don't silently flip a load-bearing design choice.
