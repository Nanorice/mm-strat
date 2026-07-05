# Session Handover: 2026-07-05 (cont. — Backtest productionisation, Phases 1–3 + G7)

> Continuation of `2026-07-05_backtrader-exit-grid.md`, which produced the new champion
> (`E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5`, OOS-gated 1.47) in an ad-hoc harness. This session
> folds that harness's capabilities into the prod backtest suite per
> `docs/architecture/backtest_productionisation_plan.md`. **Champion is now a named, tested,
> reproducibly-gated config — not a kwargs dict in a script.**

## 🎯 Goal
Productionise the strategy-exploration harness: give the champion a name, a fixed-config OOS gate the
promotion process can call, and a shared parallel runner — without building a "strategy framework"
(the plan's explicit YAGNI).

## ✅ Accomplished
- **Phase 1 — strategy registry (G1, G5).** `src/backtest/strategy_registry.py`: `STRATEGIES` dict of
  `StrategyDef(name, signal, kwargs, description, status)` + a fingerprint parser
  (`parse_fingerprint`/`to_fingerprint`) that round-trips
  `E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5`. Owns `_base_kwargs` (single source of truth) and the
  migrated S1–S5 array. Repointed `run_strategy_array.py` + `run_strategy_confirm.py` at it — deleted
  the duplicated kwargs dicts.
- **Phase 2 — prod OOS gate (G2).** `scripts/run_oos_gate.py --strategy <registry-name>`: fixed-config
  rolling BackTrader folds, stitches OOS → `data/selection_sweep/wfo_gate/<name>.json`. **Re-gated the
  champion: agg OOS Sharpe 1.47 / +245% / −28% — byte-matches the recorded reference.** NOT
  `run_strategy_wfo.py` (that re-optimizes on vec = *search*; complementary, kept separate).
- **Phase 3 — shared population runner (G3, G4).** `src/backtest/population_runner.py`
  (`run_arm`/`run_population`): parallel fan-out across arms, **rejection audit persisted for all prod
  runs** (`rejections.parquet` — why a qualified candidate didn't enter). Both array/confirm CLIs are
  now thin over it.
- **G7 fix.** `G_x4` pure-ATR arms: `max_stop_pct=0.02` was a tight *cap* (max-picks-tighter), not the
  intended floor → −69%. Fixed to a wide 0.30 net so ATR dominates.
- **Updated the backtest module manual** (`docs/modules/backtest.md`): file count 10→13, new module
  interfaces, fixed stale `runner.setup`/`universe_scorer.score_from_t3` signatures, removed the
  non-existent `min_percentile` config guide, added the productionisation workflow + Phase 4 plan.
- **Guards:** `tests/test_strategy_registry.py`, `tests/test_oos_gate.py`,
  `tests/test_population_runner.py` — all green (18 backtest + new tests pass).

## 📝 Files Changed
- `src/backtest/strategy_registry.py` (NEW): named/fingerprinted configs; single source of truth.
- `src/backtest/population_runner.py` (NEW): shared run-arm + rejection-persist + parallel fan-out.
- `scripts/run_oos_gate.py` (NEW): fixed-config OOS gate entrypoint (the promotion gate).
- `scripts/run_strategy_array.py`: S-series sourced from registry; `_run_one_strategy` delegates to
  `population_runner.run_arm` (now persists rejections too).
- `scripts/run_strategy_confirm.py`: `_base_kwargs` imported from registry; `_run_arm` replaced by a
  `Job` builder over `run_population`; G7 pure-ATR arms fixed.
- `tests/test_strategy_registry.py` / `test_oos_gate.py` / `test_population_runner.py` (NEW): guards.
- `docs/modules/backtest.md`: de-staled + productionisation workflow + Phase 4 plan.

## 🚧 Work in Progress (CRITICAL)
- **Nothing half-finished.** Phases 1–3 + G7 are complete, tested, and the champion re-gate is
  verified (1.47 reproduced exactly).
- Array's `avg_return_pct`/`ending_value` were dropped from `summary.json` (they never fed
  `comparison.md`) — re-add if a downstream reader needs them.
- The full re-gate is an operator command, not CI (minutes-long, needs live DB); CI has a fast
  artifact-tolerance guard instead.

## ⏭️ Next Steps (Phase 4 — wire the champion LIVE — DEFERRED, supervised)
Purpose: move the champion from *validated backtest config* → *tradeable*. Touches the running
Prefect nightly on the `sh019` infra box, so it's a separate supervised change; also gated on the
friction/liquidity re-run (Tier A.2) before any real capital.
1. **4a — live config.** Promote champion into `SEPAFlatV1` defaults
   (`max_stop_pct=0.15, min_target1_pct=0.10, sma_exit_independent=True, entry_top_n=5`), drop inert
   `atr_stop_mult`. Or a registry-driven live selector reading `strategy_registry.get("champion")`.
2. **4b — nightly shadow.** Add champion to the nightly pipeline shadow (paper, no capital); log fills
   vs backtest → the real forward-quarter OOS (Tier A.1).
3. **4c — parity guards (G6).** Extend `check_backtest_parity.py`/`test_backtest_smoke.py` to cover
   `selection_skip_top`, `regime_gate`, `max_concurrent_positions` (no prod call-site yet).

## 💡 Context/Memory
- **The plan's core insight held:** no strategy framework needed. `SEPABacktestRunner` already accepts
  any config via `strategy_kwargs` passthrough — the registry is a dict + fingerprint parser, not a
  class hierarchy.
- **Fingerprint parse gotcha:** `_` is both the component separator AND appears inside a suffix
  (`Xt.t1_10`). The parser splits on `_` then re-joins tokens that don't start a new family index
  (`E1/E2/X1/Xt/X3/S0/skip`).
- **Parallel-worker pickling:** confirm arms pass a picklable `functools.partial(_load_scores, …)` as
  `Job.score_loader` (lazy load *inside* the worker) rather than a big shared frame or a lambda.
- **G7 root cause:** `initial_stop = max(price−mult·ATR, price·(1−pct))` — `max` picks the *higher*
  (tighter) stop, so a small `max_stop_pct` is a tight cap, and "2% floor under pure ATR" is
  impossible with this formula. Pure-ATR needs a *wide* pct so ATR wins the max.
- Memory written: `project_strategy_registry.md` (indexed in `MEMORY.md`).
