# Session Handover: 2026-07-07 (session 02 — calibrator / ranking EDA)

## 🎯 Goal
Answer the user's three questions — (1) how does the model output distribute / is 0.15 the right
gate, (2) can we refine/rotate the ~6-name pool, (3) what do the macro pillars mean — and settle
the raw-vs-calibrated ranking question. Ended up overturning the sprint-13 "gate-not-ranker"
mechanism and re-framing the whole ranking problem.

## ✅ Accomplished
- **Traced the "gate-not-ranker" verdict to a scoring-path artifact.** The S13 cohort-bootstrap
  tied on `normalized_score` (4 distinct buckets); the champion actually ranks on **calibrated
  `prob_elite` = iso_calibrator.transform(p_pos)**, and the isotonic calibrator is a step function
  that collapses ~2000 raw scores → ~23 plateaus. Ties are a calibrator artifact, not the model.
- **Clarified the model wiring** (user pushback): the calibrator is fit on the binary model's OWN
  raw prob vs realized outcome (NOT against the 4-class model). 0.15 gate = **raw p_pos ≈ 0.48**
  (the model's ~50/50 line; model is overconfident). prob_elite = post-calibrator in backtest but
  RAW in `daily_predictions` (naming trap that caused the early wrong turn).
- **Built the WFO raw-vs-calibrated reconciliation** (`--raw-prob` flag, one-line calibrator
  disable). Result: calibrated 0.91 vs raw 0.79 aggregate OOS — **but corrected to "NOT settled"**
  (gap is inside start-time noise; folds swing >2 Sharpe). fix-b (rank on raw) neither confirmed nor
  killed for the full pool.
- **Breakout-pool refinement study:** 0% next-day persistence (day-0 event), no within-day technical
  separator (model IC ≈ −0.03), only residual = SECTOR (Tech +9% / Healthcare −3% median).
- **Full-universe raw-score EDA (2025):** raw score grades fwd return (12.7% HR-rate top ventile);
  gate is a precision/recall dial (can tighten hard for a top-5 strategy); **continuous top-5
  persists 50% overnight / 7-place drift** (unlike breakouts); winners are cheap value-rebound names.
- **Macro 6-pillar reference doc** written (`docs/research/macro_pillars_reference.md`).
- **Docs infra:** created `RESEARCH_LOG.md` (question ledger); extended `handover` + `sprint-wrap-up`
  skills to maintain it and to handle multi-session-per-day (named files + `_index.md` meta).

## 📝 Files Changed
- `scripts/run_strategy_optimizer.py`: `prescore(raw_prob=)` — disables iso calibrator for raw arm.
- `scripts/run_strategy_wfo.py`: `--raw-prob` flag; arm-tagged output dirs (`wfo/{calibrated,raw}`).
- `docs/session_logs/sprint_14/RESEARCH_LOG.md`: **new** — linear question ledger (Threads A–D + open meta-Qs).
- `docs/session_logs/sprint_14/verdicts/`: 3 new — calibrator_flattens_ranking, breakout_pool_refinement, raw_score_forward_return_eda.
- `docs/session_logs/sprint_14/cells/model_output_eda_cells.md`: **new** — reviewable EDA cells.
- `docs/research/macro_pillars_reference.md`: **new** — 6-pillar interpretation reference.
- `docs/session_logs/sprint_14/README.md`: Goal-1 updates + M1–M5 deferred TODOs + RESEARCH_LOG link.
- `.claude/skills/handover/SKILL.md`, `.claude/skills/sprint-wrap-up/SKILL.md`: RESEARCH_LOG upkeep + multi-session-day handling.
- Memory: new `project_breakout_pool_refinement`, `project_isotonic_flattens_ranking`; MEMORY.md index.
- `data/model_output_eda/`: parquets + charts (scratch, gitignore-class).

## 🚧 Work in Progress (CRITICAL)
- **Raw-vs-calibrated is NOT settled** — WFO gap (0.91 vs 0.79) is inside start-time noise. Do NOT
  flip `rank_by` or act on "calibrated wins". Needs a start-date cone × fat-tail objective.
- **All EDA is single-window** (2025 full-universe; 169-day breakout cohort). Winner traits
  (cheap/value, Healthcare tilt) are likely regime-specific — repeat across years before acting.
- **Home-run measured as binary >30%** — ignores the fat tail (the actual alpha). The "23.4% missed"
  number is unreliable until re-cut by magnitude. This is meta-question M1.

## ⏭️ Next Steps (deferred to a fresh session — see RESEARCH_LOG "Open meta-questions")
1. **M1** — fat-tail-weighted objective (magnitude, not binary >30%). Prerequisite for everything.
2. **M3** — stability-first strategy selection (sweep good AND bad months, pick most stable not highest-mean).
3. **M4** — magnitude/quantile regressor (candidate new model; pick an id ≠ M03 regime). Design doc first.
4. **M2/M5** — start-date-cone decision harness; prototype persistent continuous-score top-N.
5. **Ops carryover** (from S13): clean_dirty_shares on sh019; t1_macro June gaps.

## 💡 Context/Memory
- **The recurring lesson:** the score is a strong GATE and a weak RANKER — confirmed 4 independent
  ways (WFO, within-day IC≈0, decile inversion, winner prob_elite 0.534 vs 0.511). Ranking signal
  that DOES exist lives at the extreme top of the continuous full-universe score and in a different
  axis (fundamentals/sector), not in a finer version of the same score.
- **Methodology reckoning (user):** the whole strategy search picked a winner on ONE horizon before
  we knew returns are start-date dependent → early decisions inherit a lucky-draw bias. Re-frame to
  stability-first selection. See RESEARCH_LOG M3.
- **Classifier can't express fat tails** — architectural limit motivating a regressor (M4).
