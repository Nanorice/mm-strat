# Module: backtest

## 1. Overview

**Location:** `C:\Users\Hang\PycharmProjects\quantamental\src\backtest`
**Files:** 15 (`.py`, incl. `__init__`)

## 2. Visual Architecture

Two engines share the same config vocabulary (`strategy_registry`) and position
model (`position_tracker`): the **BackTrader** event-loop backtester (`runner` +
`sepa_strategy`, the fidelity engine) and the **forward step-engine**
(`forward_engine`, a synchronous next-open mirror for live shadowing). A
**vectorized** engine (`vectorized_backtest`) is the fast within-signal screen.

```mermaid
graph TD
    strategy_registry[strategy_registry]
    population_runner[population_runner]
    feeds[feeds]
    position_tracker[position_tracker]
    report[report]
    runner[runner]
    runner --> feeds
    runner --> sepa_strategy
    score_lookup[score_lookup]
    sepa_strategy[sepa_strategy]
    sepa_strategy --> score_lookup
    sepa_strategy --> position_tracker
    forward_engine[forward_engine]
    forward_engine --> position_tracker
    forward_engine --> score_lookup
    trade_logger[trade_logger]
    universe_scorer[universe_scorer]
    vectorized_backtest[vectorized_backtest]
    analyzers[analyzers]
    macro_sizer[macro_sizer]
    population_runner --> runner
    runner --> analyzers
```

> **CLIs over these engines** (`scripts/`): `run_backtest.py` (single run),
> `run_strategy_array.py` (S-series), `run_strategy_confirm.py` (parallel grids),
> `run_oos_gate.py` (fixed-config OOS gate), `run_strategy_wfo.py` (vec re-optimize
> search), `run_starttime_sweep.py` (start-time/horizon sensitivity),
> `run_shadow_book.py` (forward shadow book), `run_model_arena.py`,
> `check_backtest_parity.py`. The array/confirm/sweep CLIs are thin wrappers over
> `population_runner`; all read configs from `strategy_registry`.

## 3. Data Schemas

### SEPAPosition (dataclass)
*Defined in: `position_tracker`*

| Field | Type |
|-------|------|
| `ticker` | `str` |
| `entry_date` | `datetime` |
| `entry_price` | `float` |
| `entry_atr` | `float` |
| `initial_size` | `int` |
| `score` | `float` |
| `regime` | `int` |
| `initial_stop` | `float` |
| `target1` | `float` |
| `target2` | `float` |
| `tranche1_sold` | `bool` |
| `tranche2_sold` | `bool` |
| `remaining_shares` | `int` |
| `tranche1_pending` | `bool` |
| `tranche2_pending` | `bool` |
| `exit_pending` | `bool` |
| `current_stop` | `float` |
| `exit_date` | `Optional[datetime]` |
| `exit_price` | `Optional[float]` |
| `exit_reason` | `Optional[str]` |
| `max_progression` | `int` |

### DailySnapshot (dataclass)
*Defined in: `sepa_strategy`*

| Field | Type |
|-------|------|
| `date` | `datetime` |
| `portfolio_value` | `float` |
| `cash` | `float` |
| `position_value` | `float` |
| `position_count` | `int` |
| `regime` | `int` |

### SignalRejection (dataclass)
*Defined in: `sepa_strategy`*

| Field | Type |
|-------|------|
| `date` | `datetime` |
| `ticker` | `str` |
| `score` | `float` |
| `reason` | `str` |

### TradeLog (dataclass)
*Defined in: `trade_logger`*

| Field | Type |
|-------|------|
| `ticker` | `str` |
| `entry_date` | `datetime` |
| `entry_price` | `float` |
| `entry_score` | `float` |
| `entry_regime` | `int` |
| `entry_atr` | `float` |
| `initial_size` | `int` |
| `initial_stop` | `float` |
| `target1` | `float` |
| `target2` | `float` |
| `exit_date` | `Optional[datetime]` |
| `exit_price` | `Optional[float]` |
| `exit_reason` | `Optional[str]` |
| `final_size` | `int` |
| `pnl_dollars` | `float` |
| `pnl_percent` | `float` |
| `holding_days` | `int` |
| `tranche1_date` | `Optional[datetime]` |
| `tranche1_price` | `Optional[float]` |
| `tranche2_date` | `Optional[datetime]` |
| `tranche2_price` | `Optional[float]` |

## 4. Implementation Rules

| Constant | Value | File |
|----------|-------|------|
| `BACKTEST_DATA_DIR` | `config.DATA_DIR / 'backtest'` | `runner` |
| `BACKTEST_DATA_DIR` | `config.DATA_DIR / 'backtest'` | `universe_scorer` |
| `D2_PATH` | `config.DATA_DIR / 'ml' / 'd2.parquet'` | `universe_scorer` |
| `X` | `df[self._m01_features].copy()` | `universe_scorer` |

## 5. Public Interface

### `strategy_registry`

Named, versioned strategy configs (a dict of kwargs behind a stable name + a
human-readable fingerprint) — the single source of truth for the champion, the
S-series, and experiment arms. Not a class hierarchy: configs are
`SEPAHybridV1` kwargs passed straight through the runner.

**class StrategyDef** — `(name, signal, strategy_kwargs, description, status, fingerprint)`; `status ∈ {champion, candidate, baseline, retired}`. `fingerprint` auto-derives if blank.
- `parse_fingerprint(fp: str) -> Dict[str, Any]` — `E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5` → kwargs.
- `to_fingerprint(kwargs: Dict[str, Any]) -> str` — canonical label (round-trips with parse).
- `get(name: str) -> StrategyDef`
- `by_status(status: str) -> List[StrategyDef]`
- `STRATEGIES: Dict[str, StrategyDef]` — the registry. Current champion = `champion_trail_spygate` (2026-07-10): champion selection × trend-exit-only (`disable_tranches`, independent SMA50 exit, 15% stop) + SPY-200d ex-ante deploy gate (gate dict injected per-window, not baked). The 2026-07-05 tranche champion (`champion` / `E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5`) was demoted to candidate — the trail+gate arm beat it on every cone metric (floor +0.68, median +0.29, %neg −5pp).

**Fingerprint scheme** (`<Entry>_<Stop>_<TP>_<Selection>`): `E1.d0` immediate entry / `E2.dN` delayed · `X1.slNN` whole-% stop · `Xt.t1_NN` tranche T1 target · `X3.smaNN` decoupled SMA trend exit · `S0.topN` top-N by score · `skipK` selection_skip_top. Only components a config sets appear.

### `population_runner`

Shared "run one arm end-to-end, fan out across arms" path. Both
`run_strategy_array.py` and `run_strategy_confirm.py` are thin CLIs over it. Every
prod run persists the **full artifact set** (trades + rejections + equity +
metrics + config). BackTrader is serial *within* an arm (temporal fidelity),
parallel *across* arms (ProcessPoolExecutor; DuckDB reads are read-only).

**class Job** — `(id, description, strategy_kwargs, signal, model, scores_df, score_loader)`; pass `score_loader` (a picklable partial) instead of `scores_df` for parallel workers.
- `run_arm(job, start, end, initial_cash, out_dir, db_path) -> Dict` — one arm, persists `<id>/{trades,rejections,equity}.parquet + {metrics,config}.json`, returns summary row.
- `run_population(jobs, start, end, initial_cash, out_dir, db_path, workers=3) -> List[Dict]` — serial if `workers<=1`, else fan out.

### `feeds`

**class SEPAStockFeed** — OHLCV + `atr` line (`atr_14` col). **class M03RegimeFeed**
— synthetic feed carrying `regime_cat` + M03 pillars. Both are `bt.feeds.PandasData`
subclasses; `runner._add_price_feeds_from_duckdb` / `_load_regime_from_duckdb` build
the frames (there is no separate `price_feed`/`regime_feed` module — that was folded in).

### `forward_engine`

Synchronous **next-open** step-engine mirroring `SEPAHybridV1.next()` for live
shadowing (BackTrader is an event-loop *replayer* and can't step forward one day at
a time). Reuses `PositionTracker` + `ScoreLookup` verbatim; the BackTrader coupling
(async orders, feed `[0]` indexing, bar-count warmup) is the only thing re-expressed.
Parity with the backtest is enforced by `tests/test_forward_parity.py`.

**class ChampionBook** — holds a `PositionTracker` + registry kwargs; steps one day.
  - `step(day, day_scores_df, day_prices) -> List[Action]` — runs the exact `next()`
    sequence (regime-liquidate → update stops → stops → targets → trend → entries)
    with a one-day pending queue (decided T, filled T+1 open × slippage). Champion-off
    branches (E2-delay, persistence, score-drop, rank-exit, warmup, skip-top) raise
    `NotImplementedError` in `__init__` — no untested ports.
  - `set_regime_series(regime_by_date: Dict[date, int])`
- `build_price_frame(price_df, sma_period=50) -> pd.DataFrame` — per-(ticker,day)
  OHLCV + `atr14` (`ewm(span=14)` TR) + `sma50` (`rolling(50)`), **definitions lifted
  verbatim from the backtest feed** (the G2 parity fix), incl. the `<50-bar` skip.
- **class Action** — `(date, ticker, kind, shares, price, reason, pnl_pct)`;
  `kind ∈ enter/target1/target2/stop/trend/regime_liquidation`.

> **Warmup diverges intentionally.** The backtest's `next()` doesn't fire until
> *every* feed's SMA50 is warm (the latest-listing ticker gates the whole strategy);
> the parity test replicates that all-feed rule. The **live** `run_shadow_book.py`
> uses **per-ticker** warmup (a name trades once its own SMA50 exists) so one recent
> IPO doesn't freeze the book. Rules/fills identical; only first-tradeable-day differs.

### `position_tracker`

**class PositionTracker**
  - `register_entry_intent(order_ref: int, intent: dict)`
  - `confirm_entry(order_ref: int, executed_price: float, executed_size: int) -> Optional[SEPAPosition]`
  - `record_partial_exit(ticker: str, shares_sold: int, exit_price: float, exit_reason: str, exit_date: Optional[datetime]) -> bool`
  - `is_in_cooldown(ticker: str, current_date: datetime, cooldown_days: int) -> bool`
  - `get_position(ticker: str) -> Optional[SEPAPosition]`
  - `has_position(ticker: str) -> bool`
  - `get_open_count() -> int`
  - `get_all_open() -> List[SEPAPosition]`
  - `get_all_closed() -> List[SEPAPosition]`
  - `update_stops(ticker: str, current_atr: float, current_high: float) -> Optional[float]`
  - `check_stops(ticker: str, current_low: float) -> bool`
  - `check_targets(ticker: str, current_high: float) -> Optional[str]`
  - `get_stats() -> Dict`

### `report`

- `calculate_rolling_sharpe(equity_curve: pd.DataFrame, window_months: int, risk_free_rate: float) -> pd.Series`
- `generate_report(metrics: Dict[str, Any], trade_df: Optional[pd.DataFrame], equity_curve: Optional[pd.DataFrame], output_path: Optional[str], start_date: str, end_date: str, initial_cash: float, strategy_params: Optional[Dict[str, Any]]) -> str`
- `generate_monthly_returns(equity_curve: pd.Series) -> pd.DataFrame`

### `runner`

**class SEPABacktestRunner**
  - `setup(scores_df: pd.DataFrame, max_tickers: Optional[int], specific_tickers: List[str], strategy_kwargs: Optional[Dict[str, Any]])` — `strategy_kwargs` passes straight through to `SEPAHybridV1` (the kwargs-passthrough the registry relies on; no subclassing).
  - `run() -> Dict[str, Any]`
  - `get_equity_curve_dataframe() -> Optional[pd.DataFrame]`
  - `get_trade_dataframe() -> Optional[pd.DataFrame]`
  - `save_report(metrics: Dict[str, Any], output_dir: Optional[Path]) -> str`
  - `print_results(metrics: Optional[Dict])`
  - `plot(save_path: Optional[str])`
- `run_backtest(start_date: str, end_date: str, initial_cash: float, max_tickers: Optional[int]) -> Dict[str, Any]`

### `score_lookup`

**class ScoreLookup** — indexes the `UniverseScorer.score_from_t3()` contract
(date, ticker, normalized_score, daily_pct_rank, trailing_pct, prob_elite).
  - `get_candidates(date, min_score, min_percentile, min_prob_elite, rank_by: Literal['trailing','daily','prob_elite']) -> List[Tuple[str, float, float, float]]` — returns `(ticker, score, trailing_pct, prob_elite)` sorted by `rank_by` desc.
  - `get_score(date, ticker) -> Optional[Tuple[float, float, float, float]]` — `(normalized_score, daily_pct_rank, trailing_pct, prob_elite)`.
  - `check_persistence(ticker, date, window_days, min_count, rank_threshold, rank_field) -> bool` — S5 persistence gate.
  - `get_available_dates() -> List[datetime]`
  - `get_date_range() -> Tuple[datetime, datetime]`
  - `get_stats() -> Dict`

### `sepa_strategy`

**class SEPAHybridV1**
  - `notify_order(order)`
  - `next()`
  - `stop()`
  - `get_exposure_stats() -> Dict`
  - `get_signal_rejection_stats() -> Dict`
  - `get_equity_curve() -> List[tuple]`

### `trade_logger`

**class TradeLogger**
  - `log_entry(ticker: str, entry_date: datetime, entry_price: float, entry_score: float, entry_regime: int, entry_atr: float, initial_size: int, initial_stop: float, target1: float, target2: float)`
  - `log_partial_exit(ticker: str, exit_date: datetime, exit_price: float, shares_sold: int, exit_reason: str)`
  - `get_open_trades() -> List[TradeLog]`
  - `get_closed_trades() -> List[TradeLog]`
  - `to_dataframe() -> pd.DataFrame`
  - `save(path: str)`
  - `load(path: str)`
  - `get_stats() -> Dict[str, Any]`
  - `get_exit_breakdown() -> Dict[str, int]`
  - `get_regime_breakdown() -> Dict[int, Dict[str, float]]`

### `universe_scorer`

**class UniverseScorer**
  - `load_model()`
  - `score_from_t3(start_date: str, end_date: str, db_path: Optional[Path], ranking_lookback_days: int) -> pd.DataFrame` — canonical scoring path (scores SEPA candidates daily from `t3_sepa_features`); returns the `ScoreLookup` contract.


## 7. Strategy Configuration Guide

Don't hand-write kwargs. Configs are named in `strategy_registry.STRATEGIES` and
passed to the runner via `strategy_kwargs` — reference a registry name, or add a
new `StrategyDef`. The knobs below are the ones the registry sets.

### Entry / selection (the live model)

| Parameter | Type | Description |
|-----------|------|-------------|
| `entry_mode` | `'top_n' \| 'percentile'` | Slot-fill mode. Live configs use `top_n`. |
| `entry_top_n` | `int` | N slots to fill (champion = 5). |
| `rank_by` | `'prob_elite' \| 'trailing' \| 'daily'` | Ranking metric. Champion ranks by `prob_elite`. |
| `min_prob_elite` | `float` | Entry gate on P(elite) (champion = 0.15). |
| `min_score` | `float` | Absolute M01 floor; `0` when `prob_elite` is the gate. |
| `selection_skip_top` | `int` | Drop the K highest-ranked names before slot-fill (A3 tail-pollution cap; proto-specific DD lever, no-op on binary). |
| `regime_max_pos` | `dict` | Per-M03-regime slot cap; regime 0 (strong bear) = 0 → hard-liquidate. |

### Exits (where the edge lives)

| Parameter | Type | Description |
|-----------|------|-------------|
| `max_stop_pct` | `float` | Whole-position % stop. **Champion = 0.15** (15%). |
| `atr_stop_mult` | `float` | ATR stop multiplier. **Inert** on the champion — `initial_stop = max(price−mult·ATR, price·(1−pct))` and the 10–15% floor always wins. A *small* `max_stop_pct` is a tight CAP, not a floor (the G7 pure-ATR trap). |
| `min_target1_pct` | `float` | Tranche-1 profit-take. **Champion = 0.10** (early +10% pop). |
| `sma_exit_period` | `int` | Trend-exit SMA (champion = 50). |
| `sma_exit_independent` | `bool` | `True` = decoupled SMA (close<SMA ⇒ out), beats tranche-gated. Champion = `True`. |

> The 2026-07-05 tranche champion was a **stop×TP interaction**: the wide 15% stop
> lets winners breathe; the early +10% T1 banks the first pop before the wide stop
> gives it back (`sl15`/`tpTight` each *alone* underperform; together IS 1.10,
> OOS-gated 1.47). The R3 sweep then showed removing the tranche TP entirely
> (`disable_tranches` + independent SMA50 trend exit) harvests the tail better
> (+0.21 median), and stacking the SPY-200d deploy gate on the trail exit won on
> all cone metrics → current champion `champion_trail_spygate` (2026-07-10).
> With tranches disabled, `min_target1_pct` is inert; zeroing target legs is NOT
> an off-switch (`disable_tranches` is — see the comment in `strategy_registry`).

### Engine fidelity (which result you may believe)

- **Vectorized engine is optimistic by construction**: no cash-block, and stops
  are booked at `stop_level` even on gap-down opens (fix `min(stop_level, open)`
  known but not applied). Use it for *ranking* arms; **promote only on
  BackTrader** — configs that win vec have failed BackTrader (wash) before.
- Cone verdicts are **start-date sweeps**, never a single P&L
  (`run_starttime_sweep.py`, `run_cone_gate.py`); the reference cone has median
  Sharpe ≈ 0.47 with 33% negative cells.

## 8. Productionisation workflow (registry → gate → promote)

The 2026-07-05 backtest productionisation
(`docs/session_logs/sprint_13/plans/backtest_productionisation_plan.md`) folded the ad-hoc
strategy-exploration harness into the prod suite behind clean seams. **Phases 1–3
+ the G7 fix are shipped; Phase 4 is planned (below).**

**Shipped:**
1. **Registry (`strategy_registry`)** — every config is a named, fingerprinted
   `StrategyDef`. Champions/experiments are referenceable, diffable,
   regression-tested. `run_strategy_array` (S-series) and `run_strategy_confirm`
   (grids) both source configs here; `_base_kwargs` is single-sourced.
2. **Fixed-config OOS gate (`scripts/run_oos_gate.py --strategy <name>`)** — the
   promotion gate. Rolls train/test folds, runs the *locked* registry config on
   each unseen BackTrader window, stitches OOS → `data/selection_sweep/wfo_gate/<name>.json`.
   NOT `run_strategy_wfo.py` (that *re-optimizes* on the vectorized engine which
   lacks tranche TP — a **search**, complementary; don't merge them). Re-gating
   the champion reproduces **agg OOS Sharpe 1.47 / +245% / −28%** exactly.
3. **Shared population runner (`population_runner`)** — the parallel
   run-arm-and-persist path, with the **rejection audit** (`rejections.parquet`:
   why a qualified candidate did NOT enter — `no_slots`/`skip_top`/`cooldown`/…)
   persisted for all prod runs. Array/confirm are thin CLIs over it.
4. **G7 fix** — the `G_x4` pure-ATR arms mis-expressed the stop (small
   `max_stop_pct` = tight cap, not floor → −69%); fixed to a wide 0.30 net so ATR
   dominates.

**Guards:** `tests/test_strategy_registry.py` (kwargs validity + fingerprint
round-trip), `tests/test_oos_gate.py` (prod gate reproduces recorded Sharpe),
`tests/test_population_runner.py` (artifact set + rejection persistence + fan-out).

### Phase 4 — live monitoring & start-time robustness (REVISED 2026-07-05)

Re-scoped after a design review into two independent tracks. **Full spec + gap
analysis + step-by-step plan live in
`docs/session_logs/sprint_13/plans/backtest_productionisation_plan.md` §Phase 4** — this is the
summary.

- **Thing 2 — start-time sweep ✅ SHIPPED (all runs done).**
  `scripts/run_starttime_sweep.py`: the locked champion over a grid of
  `(start, end)` windows to measure how much the start date matters. Robust edge →
  tight return spread; fragile → wide. Three grids (`rolling`/`horizon`/`matrix`),
  fair annualized metrics (`sharpe_from_returns`, never raw total_return).
  **Verdict: strongly start-time dependent** — `rolling` (fixed 12m horizon, 53
  cells) ann_return **−39%..+197%**, Sharpe **−0.88..+2.45**, 17/53 Sharpe-negative,
  regime-clustered. The edge is a beta/regime ride, not a start-invariant skill.
  Artifacts: `data/selection_sweep/starttime/champion/{rolling,horizon,matrix}/`.
- **Thing 1 — forward shadow book ✅ Steps 1–5 SHIPPED, parity GREEN.** What the
  champion would buy/hold/partial/exit/cut today if followed live. `forward_engine`
  (§5) is the pure `step()` engine; `scripts/run_shadow_book.py --strategy champion
  --start-date …` **replays start→today** (a pure function of scores/prices/regime;
  replay beats fragile serialization) and persists to **`shadow_book`** (one row per
  open position, keyed by `book_id`) + **`shadow_action`** (append-only
  enter/target/stop/trend, `pnl_pct`), idempotent per `book_id`.
  **Step 6 (orchestrator on `sh019`) NOT done** — supervised; when wiring, add both
  tables to `build_dashboard_db` MANIFEST or the R2 remote breaks
  (dashboard-remote-parity).

> **Guard:** `tests/test_forward_parity.py` (LOAD-BEARING) runs the champion through
> both engines over 2024-H1 and asserts entry-set overlap > 0.85. If it can't be made
> green, the extraction is wrong — the forward engine must not ship.
>
> **Rejected:** the earlier "promote into `SEPAFlatV1` defaults" — that class already
> carries a *different* live default set other call-sites use; the champion is sourced
> from the registry instead (single source of truth), no `SEPAFlatV1` edit.
>
> **Prereq before any real capital:** the friction / liquidity-floor re-run
> (Tier A.2) — the microcap +861% is a ranking signal, not a P&L promise. The
> paper shadow may run in parallel; capital may not.

## 9. Maintenance Log

- **2026-07-18** — Doc refresh in the docs overhaul: champion updated to
  `champion_trail_spygate` (2026-07-10 promotion), added §7 engine-fidelity
  caveats (vec optimism, cone-not-point verdicts). Productionisation plan file
  moved to `docs/session_logs/sprint_13/plans/`.
- **2026-07-05 (cont.)** — Phase 4 shipped: added `forward_engine` (synchronous
  next-open step-engine + `build_price_frame`) and `scripts/run_shadow_book.py`
  (`shadow_book`/`shadow_action` tables); `run_starttime_sweep.py` full runs done
  (fixed an unpicklable-closure bug in its parallel path). Parity gate
  `tests/test_forward_parity.py` green. Fixed stale §2/§5 (removed phantom
  `price_feed`/`regime_feed` modules — folded into `feeds`/`runner`; file count 13→15).
- **2026-07-05** — Backtest productionisation (Phases 1–3 + G7): added
  `strategy_registry` + `population_runner`, `scripts/run_oos_gate.py`; array/confirm
  refactored to thin CLIs over the shared runner. Fixed stale §5 (`runner.setup`
  signature, `universe_scorer.score_from_t3`) and §7 (removed non-existent
  `min_percentile` guide). Phase 4 (live wiring) documented as planned.
- **2026-02-04** — Auto-generated passport.
