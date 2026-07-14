# Session Handover: 2026-07-14 (session 02)

## 🎯 Goal
Chase the user's "first conviction the model has alpha" — the Q65/Q66 curiosity that day-1 score
ranks the tail — from a scatter, through a notebook proxy, to a real backtest: **does an exit
MONETIZE the score's tail (C1→C3)?**

## ✅ Accomplished
- **Q66 curiosity chart** (score vs trend-exit return): cone substrate ρ +0.18; then re-scored the
  `d2_training_cache` fresh with prod 4-class m01_prototype to fix the exit-mechanism confusion —
  under the native SEPA stop the MEDIAN lens is misleading (ρ −0.09) but the TAIL lens is the signal
  (home-run rate 0.2%→14.2% low→high score decile). Cells added to `sprint_summary_eda_cells.md` §A.
- **Q70 Stage 1 — notebook path-replay proxy** (`cells/q67_stage1_exit_replay.ipynb`, direct-edit
  approved): pulled each trade's forward 60d `price_data` bars, replayed 4 exits with a gap-fill stub,
  read by score decile. **KEEP (qualified, in-sample):** tail is real ON THE PATH (MFE ceiling
  7.8%→35.6% by decile) but every exit gives ~76% back; the TRAILING stop is the killer, not the hard
  stop. Caught + fixed a stop-pinned median metric mid-run (flipped a hasty KILL to the correct KEEP).
- **Q70 Stage 2 — backtest cone confirm.** Wired a score-conditional exit into the engine, ran the
  paired cone. **KILL:** median Sharpe 0.25→−0.01, %neg 38%→51%, max 1.76→1.32. The in-sample tail did
  NOT survive the portfolio path — same C1→C3 death as RS / minervini+progfills.
- Fixed a `Δ` console-encoding crash in `run_starttime_sweep.py --compare-spygate` (glyph rule).

## 📝 Files Changed
- `src/backtest/sepa_strategy.py`: +3 params (`hi_score_thresh/_stop_pct/_sma_period`) + 2 hooks
  (wider hard stop, longer SMA trend-exit for hi-score names). Default-None → prod byte-identical.
- `src/backtest/strategy_registry.py`: +2 arms `champion_trail_spygate_4cls_histop{,_hold}` (Q70 S2).
- `scripts/run_starttime_sweep.py`: `Δ`→`delta` in the compare-cone console print (cp1252 crash).
- `docs/.../cells/q67_stage1_exit_replay.ipynb`: NEW — Stage-1 path-replay proxy (18 cells, executes clean).
- `docs/.../cells/sprint_summary_eda_cells.md`: §A appendix (Q66 cone + cache reads); `d.tail`→`d["tail"]` bugfix.
- `docs/.../verdicts/`: 3 PNGs (q66 trendexit, q66 cache, q67 stage1 replay).
- `docs/.../plans/2026-07-13_regime_tiering_and_system_usage.md` + `RESEARCH_LOG.md`: Q66/Q70 documented.

## 🚧 Work in Progress (CRITICAL)
- **None half-finished.** Q70 is CLOSED (kill). `_histop_hold` arm registered but deliberately NOT run
  (moot — primary failed). Engine `hi_score_*` params KEPT as a reusable, default-off mechanism (the
  null is the config, not the code).
- Stale cone dir: `champion_trail_spygate_4cls/rolling` holds 123 mixed cells (old 2003–2025 quarterly
  + fresh 2021+ monthly). Verdict used only the 53 shared 2021+ cells (valid). User said leave it; a
  future cleanup could purge pre-2021 cells (scored outside the 4-class window).

## ⏭️ Next Steps
1. **Q69 (deferred, user):** model-skill-regime gate — do periods of genuine model tail-capture skill
   exist where a higher gate pays? Needs a LEAK-FREE live-safe "model scoring well now" proxy (NOT
   SPY-trend). User reframe: don't assume the axis is bull/bear; don't assume the model is good.
2. **§1.2a regime-tiered fan/cone** and other open §1 items in the plan (lower priority).
3. If revisiting exit ideas: the `hi_score_*` engine hooks are ready to reuse — but Q70 says
   score-conditional STOP WIDTH is a dead lever specifically.

## 💡 Context/Memory
- **The through-line:** a C1 label/path tail signal ≠ a monetizable C3 trade edge. Third kill this
  sprint (RS, minervini+progfills, now score-tail-exit). The user's "first conviction of alpha" is
  half-right: the tail-ranking is REAL and in-sample; it just keeps dying at the portfolio path.
  ([[project_sepa_three_currencies]] — the three currencies of null.)
- **Mechanism of the kill:** a wider hard stop bleeds losers deeper (25% vs 15%); under slot
  contention those deeper losses tie up capital and deepen bad-cell drawdowns — wide stop widens LOSS
  magnitude more reliably than GAIN once slots + capital are real.
- **Two metric traps caught this session:** (1) `d.tail` is the DataFrame method not the column; (2)
  decile-MEDIAN spread is STOP-PINNED (= the stop level, not the score) — the median-lens trap bites
  the metric, not just the result. Use mean / home-run-rate / tail-magnitude for stop-gated data.
- **Threshold-above-gate rule:** a score-conditional threshold MUST sit above the entry gate or it's a
  uniform arm (0.35 was below the 0.60 gate → every entry got it; fixed to 0.665). Caught in smoke.
