# Session Handover: 2026-05-22 (backtest case studies)

> Companion to `2026-05-22.md` (prior session: dense-grain audit + Phase 2
> engine, ending on a NEGATIVE standalone-rank verdict). This session ran the
> actual backtests on the production infra and reached the practical answers.

## 🎯 Goal
Run three case studies on the real `src/backtest` infra: (1) m01_prototype as a
standalone daily top-K signal, (2) m01_prototype selection + m01_rank as an
entry-timing gate, (3) retrain m01_rank — then validate whether m01_rank is
actually good at its designed job before wiring it into trading.

## ✅ Accomplished
- **Case 1 — m01_prototype standalone: STRONG & VERIFIED.** Daily-dense scoring
  via `score_from_t3` + SEPAHybridV1 (M03 gating, 3-tranche ATR exits), 2020-2024:
  **+201%, Sharpe 0.79, max DD -26%, positive 4/5 years, 2022 only -9%.** Closes
  the prior session's open debt ("prototype dense backtest unverified").
- **Case 2 — m01_rank as entry re-ranker: HURTS.** Same engine/floors/exits, only
  the entry-ranking key swapped to m01_rank's daily percentile: **+65%, Sharpe
  0.39, max DD -42%.** It over-weights high-nATR / more-extended names entered at
  the breakout top (entry nATR median 8.35 vs 7.22; win rate 31% vs 38%).
- **Skill validation A (per-ticker fwd-return IC): PASSES.** m01_rank IC
  0.07/0.10/0.13 at 5/10/20d, positive in ~85% of tickers, stronger within-name
  than pooled. It IS a sound setup-QUALITY signal.
- **Skill validation B (breakout-day pullback): reframes the delay-entry idea.**
  HIGH-score breakouts dip deeper (-9% @10d, -13% @20d) AND return more (+2.2%
  @20d); LOW-score names just stall. So the pullback lives in high-conviction
  names, not low ones.
- **Multi-horizon term structure (H=1,5,10,20): horizons are REDUNDANT.** The four
  daily-percentile scores are **0.92-0.99 Spearman-correlated** — one
  horizon-invariant "quality" score. The user's term-structure delay-entry cohort
  (high-20d / low-1d-5d) is **6-9 rows of ~29,700** → statistically empty.
- **Decision (user): SHIP m01_prototype standalone; SHELVE m01_rank as a timing
  layer.** Clarified that the win is "which model's daily score" (both cases score
  daily/dense), not "dynamic vs static."

## 📝 Files Changed
- `scripts/run_case1_prototype_standalone.py`: NEW — Case 1 runner; adds
  `--warmup-start` and an eval-window slice + per-year breakdown.
- `scripts/run_case2_prototype_plus_rank.py`: NEW — Case 2 runner; merges
  m01_rank's daily percentile in as the entry-ranking key (no strategy code change).
- `scripts/m01_rank_scorer.py`: NEW — inline reproduction of the m01_rank.ipynb
  binary classifier (the saved `models/m01_rank/model.json` rank:pairwise artifact
  is STALE). Date-bounded dense load to avoid the 9GB full-table copy.
- `scripts/validate_m01_rank_skill.py`: NEW — per-ticker fwd-return IC + breakout
  pullback, returns from price_data.close (adjacency-guarded).
- `scripts/m01_rank_multihorizon.py`: NEW — trains H=1/5/10/20 variants, validates
  each predicts its own horizon, cross-horizon correlation, delay-entry cohort.
- `docs/plans/m01_case_studies_2026_05_22.md`: NEW — full write-up with TL;DR
  verdict and the "both cases score daily" clarification + 3-way confound caveat.
- `data/backtest/case1_prototype_standalone/`, `case2_prototype_plus_rank/`: saved
  run artifacts (equity_curve, trades, metrics, manifest).
- No `src/` changes; no notebook edits (per workflow rule).

## 🚧 Work in Progress (CRITICAL)
- **Nothing half-finished.** All runs completed; the killed `case3_rank_h10`
  backtest left no partial artifacts (verified).
- **One unisolated confound (accepted, not a bug):** m01_prototype vs m01_rank
  differ in 3 ways at once — 4-class MFE target vs 2-class >20%/20d binary;
  2003-2026 vs shorter dense window; event-grain vs dense-grain. The +201% vs +65%
  gap is NOT cleanly attributable to training-grain alone. The controlled A/B
  (dense model w/ prototype's 4-class target + window) was DEFERRED by user choice.
- **Doc-creation flag:** `docs/plans/m01_case_studies_2026_05_22.md` was created
  this session; CLAUDE.md says check before generating docs. It's an analysis
  artifact, not auto-generated module docs — confirm you want it kept.

## ⏭️ Next Steps
1. **Ship m01_prototype standalone** as the production entry signal (daily-dense
   score via `score_from_t3` + SEPAHybridV1). Model:
   `models/m01_prototype_2003_2026/v1/model.json`.
2. **If m01_rank timing is revived later:** it needs path-distinguishing features
   (dip-depth, short-term reversal, oversold/RSI) to manufacture a real term
   structure, OR timing from a price-action buy-the-dip rule with m01_rank gating
   only setup quality. The model's horizon scores cannot supply timing.
3. **(Optional) Isolate the confound** if you ever want to claim "event-grain beats
   dense-grain": train a dense model with the prototype's 4-class MFE target +
   2003-2026 window, score daily, compare to Case 1.
4. **(Infra, carried over)** Wire `BAD_TICKERS` into the loader; populate
   `price_data.adj_close` upstream (still 100% NULL — returns use close + split clip).

## 💡 Context/Memory
- **The `src/backtest` infra is the right tool and already does daily-dense M01
  scoring.** `UniverseScorer.score_from_t3` scores every active SEPA candidate
  every day; SEPAHybridV1 ranks entries by trailing-10d percentile. Case 1 is NOT
  score-once-at-breakout.
- **Two infra gotchas (saved to memory):**
  (1) Use `models/m01_prototype_2003_2026/v1/model.json` — the bare
  `models/m01_prototype/` errors on a categorical dtype mismatch (no
  categorical_mapping.json; only the 2003_2026 model matches the company_profiles
  fallback ordering).
  (2) **Warmup stall:** SEPABacktestRunner stays in BackTrader `prenext()` until
  every feed's SMA(50) min-period is met — without a warmup year before the eval
  start, the first year never trades (verified: 2020-only run gave a single
  2020-12-31 snapshot, 0 positions). Always feed/score from a ~12-month buffer and
  slice the equity curve to the eval window.
- **The saved m01_rank model artifact is stale** (`rank:pairwise`); the live
  m01_rank work trains a `binary:logistic` classifier in the notebook and
  rank-gates on the daily cross-sectional percentile of its probability. Reproduced
  faithfully in `scripts/m01_rank_scorer.py`.
- **The big "aha":** m01_rank's skill is real but it's a single horizon-invariant
  "setup quality" score, not a timing instrument. You can't get "when to enter"
  from a model whose 1d and 20d scores are 0.92 correlated. Timing must come from
  price action or new features.
- New/updated memory: `project_m01_two_model_system` (prototype verified + rank
  shelved), `project_prototype_model_path`, `project_backtest_warmup_stall`.
