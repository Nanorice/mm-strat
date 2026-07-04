# HANDOVER — Strategy Arena + m02_breakout (Sprint 13)

> Written 2026-07-04. Start here for the next session. Everything below is verified against
> current code/data unless marked "assumed".

## Where we are (one paragraph)

Goal A (M01 score validity) is **DONE**: no Healthcare artifact (A1), M01 is real ranking alpha
(A2 bake-off — m01_binary ≈ m01_prototype at top). The open frontier is the **Manual Strategy
Arena** (compare strategy *rules* on a fixed signal, then compare signals under the best rule) and
getting **m02_breakout** (the ignition classifier — validated OOS, never backtested) into it.
B3 (m02 finalization) is **built + smoke-passed**; a full-universe final fit was kicked off at end
of session (background task `bcx7vt150`).

## Read these first (in order)

1. [strategy_arena_playbook.md](strategy_arena_playbook.md) — the arena plan: strategy taxonomy,
   test grid, run order (vectorized sweep → WFO gate → BackTrader confirm). **The script to follow.**
2. [../../architecture/backtester_manual.md](../../architecture/backtester_manual.md) — engine
   mechanics: how enter/exit/size/rebalance map to params; scores are just an injected signal.
3. [goal_a3_m02_strategy_plan.md](goal_a3_m02_strategy_plan.md) — m02 as its own strategy (2 jobs).
4. [../../model_doc/m02.md](../../model_doc/m02.md) §8a — m02 prototype→prod gap table (G1–G7).
5. [sprint13_summary.md](sprint13_summary.md) — "Pre-flight" section (B1–B4 resolved + optimizer).

## m02 is DONE and arena-ready (finished this session)

- Final model: `models/m02_breakout/final_20260704_175544/` (model.json + metadata.json,
  5.09M rows, 86 feats, 2016→2026).
- **Score panel: `models/m02_breakout/final_20260704_175544/score_panel.parquet`** —
  9.36M rows, 2,711 tickers, 6404 days, prob_elite ∈ [0, 0.31]. This is the injected signal.
- To re-generate (idempotent): `train_breakout_model.py --final` then
  `score_m02_breakout.py --run <final_dir>`.

**START the arena at step 1 below (Job-2 lead-time gate) — no prereq left.**

## What's BUILT this session (don't rebuild)

- `scripts/train_breakout_model.py --final` — single all-period booster (~9.4M rows 2016→2026) →
  `model.json` + `metadata.json` (frozen feature list). Reuses existing load_matrix/_prep_cat/params.
- `scripts/score_m02_breakout.py` — final model → arena score panel. **prob_elite = breakout_proximity
  clipped to [0,1]** (reg:squarederror overshoots ~[-0.045, 0.70]; clip is monotone → ranking safe).
- Docs: playbook, backtester manual, m02 §8a gap table, A3 plan.

## The arena work ahead (the multi-step effort)

Run order from the playbook (§3). Cheap→expensive, gate before committing:

1. **[m02 prereq — nearly done]** finalize + score m02 (above). Then optionally the cheap
   **Job-2 lead-time analysis** (A3 §3): for names that later hit the M01 watchlist, how many days
   earlier did m02 cross a high-proximity threshold? A few joins over score_panel + `sepa_watchlist`.
   Go/no-go gate before building the m02 trade strategy.
2. **Vectorized grid** (`run_strategy_optimizer.py`) — Optuna, pre-score-once-then-inject, maximize
   Sharpe. Sweep the §2 grid per strategy type. ALREADY BUILT.
3. **WFO overfit gate** (`run_strategy_wfo.py`) — keep only strategies whose aggregate OOS Sharpe
   holds (M01 ref: IS ~2.0 → WFO ~0.84). ALREADY BUILT.
4. **BackTrader confirm** (`run_strategy_array.py`, S1..S5 + winner) — capital-honest Sharpe (real
   cash-blocking, tranche exits). ALREADY BUILT (S2–S5 knobs are BackTrader-only).
5. **Sizing overlay** — VIX `exposure` on the survivor (M03 = no-op, skip). `run_sizing_experiment.py`.

**Optional convenience build:** `exit_policy` switch on the *vectorized* engine (manual §5) so the
fast engine can do short-hold sweeps for m02. BackTrader already expresses short-hold/tranche exits,
so this is only for cheap iteration, not a capability gap.

## Key facts / landmines (verify before relying — memories age)

- **Two backtest engines = fidelity ladder, not pick-one.** Vectorized = fast, approximate capital
  (pro-rata, phantom concurrency OK). BackTrader `runner.py`+`SEPAHybridV1` = real cash-blocking +
  3-tranche/ATR/min-hold exits. Sweep on vectorized, CONFIRM on BackTrader.
- **Injected-scores path bypasses UniverseScorer** — the general way to backtest ANY signal:
  `VectorizedSEPABacktest(precomputed_scores=DataFrame[date,ticker,prob_elite,calibrated_score])`.
- **m02 is RANK-ONLY until calibrated** (doc §8a G4). Don't threshold the raw proximity value.
- **"m02 no-edge spike" in old memory = the RETIRED quantile cone (m02_prototype), NOT m02_breakout.**
  Don't conflate. m02_breakout is the live champion (P@50≈50%, IC+0.37).
- **M03 retired as a sizing lever** (VIX works, M03 no-op). Not a selector anyway (all tickers share
  the macro value). Don't grid it.
- **Industry-preference strategy knob: DROPPED** (B4) — industry is already a model input.
- Env: `.venv/Scripts/python.exe`; DB `data/market_data.duckdb` (notebooks read_only=True).
  Data deps present: `m02_breakout_targets` (16.1M rows), `t3_training_cache`, `daily_predictions`.

## Definition of done (arena)

One comparison table (signal × strategy-type) → honest Sharpe/maxDD, winner named, verdict written
back to sprint summary: which (signal, strategy) pairs earn a live slot. See playbook §6.
