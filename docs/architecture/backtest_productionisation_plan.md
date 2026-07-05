# Backtest Suite Productionisation — Gap Analysis & Implementation Plan

> **Context:** the 2026-07-05 strategy exploration (see
> `docs/session_logs/sprint_13/strategy_exploration_summary.md`) produced a new champion and a set
> of capabilities in the ad-hoc harness `scripts/run_strategy_confirm.py` that the prod backtest
> suite lacks. This doc is the plan to fold those capabilities into the prod suite so the analysis
> is reproducible and the champion is a first-class, tested config — not a kwargs dict in a script.

## 1. Where things stand

### Prod backtest suite (today)
| Script | Role | Config style |
|---|---|---|
| `scripts/run_backtest.py` | single BackTrader run, one model/window | CLI args + hardcoded strategy class |
| `scripts/run_strategy_array.py` | S1–S5 named configs, **serial** loop, comparison.md | hardcoded `STRATEGY_ARRAY` dict of kwargs |
| `scripts/run_strategy_wfo.py` | walk-forward, **re-optimizes** params/fold on the **vectorized** engine | Optuna `suggest_params` |
| `scripts/run_model_arena.py` | model-vs-model comparison | hardcoded |
| `scripts/check_backtest_parity.py` | guards backtest scoring == `daily_predictions` | — |
| `src/backtest/{runner,sepa_strategy,vectorized_backtest,...}.py` | the engines | params on the strategy class |

### Ad-hoc harness built this session (`run_strategy_confirm.py`)
Capabilities that **do not exist in prod**:
1. **Parallel across arms** — `ProcessPoolExecutor`, BackTrader serial *within* each arm (temporal
   fidelity), independent *across* arms. `run_strategy_array.py` is serial.
2. **Multi-signal populations** — arms carry their own `(signal, model, cache)`; binary + proto in
   one run. Prod scripts are single-model.
3. **Per-arm rejection audit** — `rejections.parquet` (why candidates did NOT enter: no_slots /
   cooldown / skip_top / …). Prod only keeps aggregate rejection *counts*.
4. **Fixed-config OOS gate** — `--wfo-gate <arm>`: rolls folds, runs the **locked** kwargs on each
   unseen BackTrader window, stitches OOS. `run_strategy_wfo.py` **cannot** do this — it
   re-optimizes on the tranche-less vec engine, so it can't gate a BackTrader exit config.
5. **Grid populations as data** — `_exit_grid()`, `_tier3_grid()` build ablations programmatically.

### New strategy primitives added to the engines (already shipped + tested)
- `VectorizedSEPABacktest.regime_gate` + `max_concurrent_positions` (honest slot-book).
- `SEPAHybridV1.selection_skip_top` (drop top-K ranked before slot-fill).

## 2. The gap (prod ← ad-hoc)

| # | Gap | Impact | Effort |
|---|---|---|---|
| G1 | **No strategy registry / fingerprint config.** Configs are scattered kwargs dicts (`_base_kwargs`, `STRATEGY_ARRAY`, arena). The champion `E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5` is not a named, versioned, testable object. | Champions can't be referenced, diffed, or regression-tested; every experiment re-derives kwargs. | M |
| G2 | **No fixed-config OOS gate in prod.** The only WFO re-optimizes (vec, no tranche TP). The gate that actually validated the champion lives in an ad-hoc script. | Can't reproducibly gate a BackTrader config → can't trust a promotion. | S (lift from confirm) |
| G3 | **`run_strategy_array.py` is serial + single-model.** | Slow, can't run a cross-signal population. | S |
| G4 | **Rejection audit not persisted in prod.** | "Why didn't we enter" is invisible in prod runs. | S |
| G5 | **The champion isn't wired into any live config.** It's a kwargs dict in `run_strategy_confirm.py`. | Not tradeable; not in the nightly shadow. | S |
| G6 | **`selection_skip_top` / `regime_gate` / `max_concurrent_positions` have no prod call-sites.** | New primitives untested against the array/parity guards. | S |
| G7 | **`G_x4` pure-ATR arm is buggy** (2% floor became a cap). | Any future pure-ATR test is wrong. | XS |

## 3. Design decision (do this before coding)

The temptation is a big "strategy framework." **Resist it.** The prod need is narrow:
1. a **named, versioned config registry** (one champion + the S-series + experiment arms), and
2. a **fixed-config OOS gate** the promotion process can call.

Everything else (`run_strategy_confirm.py`'s grids, parallelism) is already written and just needs
lifting into the shared runner, not re-architecting. **Reuse `SEPABacktestRunner` +
`strategy_kwargs` passthrough — it already accepts any config without subclassing.** The registry is
a dict of `{name: (kwargs, signal, description)}` + a fingerprint parser, not a class hierarchy.

## 4. Implementation plan (phased, each phase independently shippable)

### Phase 1 — Strategy registry (G1, G5) — the keystone
- **`src/backtest/strategy_registry.py`**: `STRATEGIES: dict[str, StrategyDef]` where `StrategyDef =
  (fingerprint, signal, strategy_kwargs, description, status)`. `status ∈ {champion, candidate,
  baseline, retired}`.
- Register: the **champion** (`sl15/tpTight/…`), the old E1 seed (baseline), the S1–S5 array
  (migrate `STRATEGY_ARRAY` here — single source of truth), the proto arms (retired).
- **Fingerprint parser** (`parse_fingerprint(str) -> kwargs` / `to_fingerprint(kwargs) -> str`)
  from the scheme already in the summary doc (`<Entry>_<Stop>_<TP>_<Selection>`). Round-trip test.
- Point `run_strategy_array.py` and `run_strategy_confirm.py` at the registry (delete the duplicated
  kwargs dicts). **Test:** every registered strategy instantiates `SEPAHybridV1` without error.

### Phase 2 — Fold the OOS gate into prod (G2)
- Lift `wfo_gate()` from `run_strategy_confirm.py` into a prod entrypoint
  **`scripts/run_oos_gate.py --strategy <registry-name> [--anchored] [--train-years N --test-years N]`**.
  It runs the **fixed** registry config on rolling BackTrader folds, stitches OOS, writes
  `wfo_gate/<name>.json` + a report. This is the promotion gate.
- Keep `run_strategy_wfo.py` as-is for the *search* use-case (finding candidate params on vec);
  document that it re-optimizes and can't gate a fixed BackTrader config (the two are complementary).
- **Test:** re-gate the champion, assert agg OOS Sharpe within tolerance of the recorded 1.47.

### Phase 3 — Promote confirm's runner capabilities into the shared path (G3, G4)
- Move `_run_arm` (parallel, per-arm trades + **rejections** + equity + metrics + config caching)
  into a reusable `run_population(strategies, window, workers)` in
  `src/backtest/population_runner.py`. `run_strategy_array.py` and `run_strategy_confirm.py` become
  thin CLIs over it.
- Persist rejections in the standard artifact set for **all** prod runs (G4).
- **Test:** the capacity/rejection smoke already in `tests/` + one population-level parallel run.

### Phase 4 — Wire the champion live (G5) + guards (G6, G7)
- Promote the champion into the live strategy config (`SEPAFlatV1` defaults or a registry-driven
  live selector): `max_stop_pct=0.15, min_target1_pct=0.10, sma_exit_independent=True,
  entry_top_n=5`; **drop the inert `atr_stop_mult`**.
- Add the champion to the **nightly shadow** (paper, no capital) — logs fills vs backtest for the
  forward-quarter validation (Path forward Tier A.1).
- Extend `check_backtest_parity.py` / `test_backtest_smoke.py` to cover the new primitives
  (`selection_skip_top`, `regime_gate`, `max_concurrent_positions`) (G6).
- **Fix or delete the `G_x4` pure-ATR expression** (G7 — XS).

## 5. Sequencing & effort
Phase 1 first (unblocks everything — registry is the shared vocabulary). Then Phase 2 (the gate the
promotion process needs). Phases 3–4 are parallelisable. **Total ≈ 2–3 focused sessions.** None of
it is new science — it's lifting already-written, already-tested code behind clean seams and giving
the champion a name.

## 6. Explicit non-goals (YAGNI)
- No generic "strategy plugin" / class hierarchy — the kwargs-passthrough already covers every
  config we have. A registry dict + fingerprint parser is enough.
- No new optimizer — `run_strategy_wfo.py` stays for search; the OOS gate is for *validation* of a
  fixed config. Don't merge them.
- No UI/dashboard for backtests this round — artifacts + comparison.md are sufficient; revisit only
  if a human is browsing results weekly.
- **Do not chase the microcap +861%** — the productionised suite's first job is the *friction /
  liquidity-floor re-run* (Path forward Tier A.2), which likely lowers the number. That's the point.
