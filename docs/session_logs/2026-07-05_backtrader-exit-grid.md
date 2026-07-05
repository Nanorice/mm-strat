# Session Handover: 2026-07-05 (cont. — BackTrader confirm, exit grid, new champion)

> Continuation of `2026-07-05.md`. That session built the vec selection sweep and left the
> BackTrader-confirm queued. This session ran it, then swept exits, found a better config, and
> OOS-gated it. **Master doc: `docs/session_logs/sprint_13/strategy_exploration_summary.md`
> (read the TL;DR + Path forward first).**

## 🎯 Goal
Take the vec selection-sweep winner to BackTrader for the capital-honest verdict; then, off the
winning seed, expand the exit grid to find and out-of-sample-validate a better tradeable config.

## ✅ Accomplished
- **Fixed the vec↔BackTrader sign-flip — root cause was SLOT CAPACITY, not the bear-gate** (the
  prior handover's diagnosis was incomplete). Added `regime_gate` (M03 strong-bear, minor) AND
  `max_concurrent_positions` (greedy slot-book — the dominant fix) to `VectorizedSEPABacktest`.
  E1 binary recovered +0.07/−29% → +0.34/+37%. The fix reordered the sweep's N-ranking (old
  "widen N=8–10" was a dilution artifact).
- **BackTrader-confirmed the 5-arm population** (`run_strategy_confirm.py`, parallel across arms).
  A1 reproduced the prior E1 champion exactly (0.871/+418%) → harness faithful. **The vec winner
  (proto skip-2 @ N=10) did NOT beat the binary E1 seed** — vec over-ranks proto because it lacks
  the 3-tranche TP. Lesson: vec is a valid *within-signal* screen, can't rank across signals.
- **Ran the exit grid (16 arms) off the champion.** Findings: (a) `atr_stop_mult` is INERT — the
  stop is a pure 10% trailing lock (drop the knob); (b) the "stop" is a profit-LOCK not a loss-cut
  (avg PnL at stop-exit is positive); (c) decoupled SMA > tranche-gated.
- **Tier-3 stop×TP interaction found what the marginal sweep missed:** `sl15` alone 0.75 + `tpTight`
  alone 0.76 (both < champion 0.87) COMBINE to **1.10 / +861% / −45% DD**.
- **Built a TRUE OOS gate** (`run_strategy_confirm.py --wfo-gate`, fixed config on rolling BackTrader
  folds — the existing `run_strategy_wfo.py` couldn't do it: it re-optimizes on the tranche-less vec
  engine). **Winner clears it: agg OOS 1.47 / +245% / −28% DD, beats old champ on every OOS metric,
  no IS→OOS collapse.** → **NEW CHAMPION.**
- **Cached every trade + rejection** across all grids (`data/selection_sweep/{exit_grid,tier3_grid,
  wfo_gate}/`) so any entry/exit is investigable.
- **Drafted results-analysis notebook cells** (`docs/session_logs/sprint_13/backtrader_analysis_cells.md`,
  dry-run-validated); user applied them into `notebooks/backtest_analysis.ipynb`.
- **Documented the full exploration + honest forward-trading read + ranked Path forward** in the
  master summary.
- **Drafted the productionisation gap analysis + implementation plan** (see Next Steps / the plan doc).

## 🏆 The champion we trade forward
`E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5` — binary top-5 by prob_elite, immediate entry, **15%
trailing stop**, **early T1 at +10%** then staged, decoupled SMA50, M03 bear-gate.
Live config = SEPAFlatV1 with `max_stop_pct=0.15, min_target1_pct=0.10, sma_exit_independent=True,
entry_top_n=5`; drop the inert `atr_stop_mult`. **Realism: 2021–2026 $25k microcap-heavy backtest,
3 OOS folds, 2024 flat — a candidate for a paper/small-size probation, NOT a proven money-maker.**

## 📝 Files Changed (this session)
- `src/backtest/vectorized_backtest.py`: `regime_gate` + `_load_regime_exposure`;
  `max_concurrent_positions` + `_enforce_capacity` (greedy slot-book, exits path-independent).
- `src/backtest/sepa_strategy.py`: `selection_skip_top` param (drop top-K ranked before slot-fill;
  default no-op) + rejection audit reason `skip_top`.
- `scripts/run_strategy_confirm.py`: **NEW** — parallel-across-arms BackTrader harness; grids
  `confirm|exit|tier3`; `--wfo-gate <arm>` fixed-config OOS gate; per-arm trades/rejections/equity
  caching. (Fixed: equity now `reset_index()` so the date axis survives to parquet.)
- `tests/test_vectorized_exit_policy.py`: `test_capacity_gate_blocks_over_subscription`.
- `tests/test_rotation_extensions.py`: `selection_skip_top` default-noop + slice test.
- `docs/session_logs/sprint_13/strategy_exploration_summary.md`: TL;DR, exit-grid + Tier3 + OOS
  sections, honest forward read, ranked Path forward.
- `docs/session_logs/sprint_13/backtrader_analysis_cells.md`: **NEW** — results-analysis cells.
- `docs/architecture/backtest_productionisation_plan.md`: **NEW** — gap analysis + impl plan.
- **NOT mine:** `run_strategy_optimizer.py` (exit_policy), `score_lookup.py`, dashboard*.py — from
  prior sessions, already in the working tree at session start.

## 🚧 Work in Progress (CRITICAL)
- **`G_x4` (pure-ATR) arm is INVALID** — the 2% "safety floor" I added mis-expressed X4 as a stop
  *cap* not a floor → 1592 trades / −69%. Discard that arm's result; fix before any pure-ATR test.
- **The OOS gate is only 3 rolling folds and 2024 was flat (+0.12).** Statistically thin — one good
  gate is not a track record. Widen before trusting (Path forward Tier A.3).
- **The champion is NOT yet wired into any live/prod config** — it lives only in the ad-hoc
  `run_strategy_confirm.py` populations. Productionising it is the next session's job (plan drafted).
- Equity parquets for `exit_grid` + `backtrader_confirm` are **undated** (written pre-fix); only
  `tier3_grid` was re-run with dates. Re-run those grids if their equity curves are needed.

## ⏭️ Next Steps
1. **Productionise per `docs/architecture/backtest_productionisation_plan.md`** — the strategy
   registry / fingerprint config, fold `run_strategy_confirm.py`'s capabilities into the prod suite,
   promote the champion into SEPAFlatV1.
2. **Path forward Tier A (de-risk before capital):** forward paper-trade a quarter → re-run with
   realistic frictions + a liquidity floor → widen the OOS gate. The friction/liquidity re-run is
   the real test (microcap artifact risk).
3. **Tier B:** stress the trailing-stop *dynamics*; decompose +861% by cohort; test on a liquid-only
   universe (the actually-scalable result).

## 💡 Context/Memory
- **The edge is in the EXITS, not selection** — every selection idea falsified; the trailing-stop-
  as-profit-lock + early-TP is the whole edge.
- **Interaction grids matter:** two knobs individually worse than baseline combined to beat it. A
  pure one-knob-at-a-time sweep would have discarded both. But joint tuning overfits → the OOS gate
  is non-negotiable (precedent: optimizer IS 1.22 → OOS −0.17).
- **`run_strategy_wfo.py` can't gate a BackTrader exit config** — it re-optimizes on the vec engine
  which has no tranche TP. That's why the new `--wfo-gate` (fixed-config, BackTrader folds) exists.
- **bt.Strategy overrides `__nonzero__`** — never test it for truthiness (`if runner.strategy`
  explodes into line arithmetic); use `is not None`.
