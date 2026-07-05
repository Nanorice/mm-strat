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

### Phase 4 — Live monitoring & start-time robustness (REVISED 2026-07-05)

Phase 4 was re-scoped after a design review (this session). The original "promote into
`SEPAFlatV1` defaults" is **rejected**: `SEPAFlatV1.params` already carries a *different* live
default set (percentile entry, N=10, sl12/tp15) that other call-sites use — overwriting it would be
a silent regression. The champion is instead sourced **from the registry**
(`strategy_registry.get("champion").strategy_kwargs`), the single source of truth, exactly as
`run_oos_gate.py` already does. No `SEPAFlatV1` edit.

Two independent deliverables came out of the review:

#### Thing 2 — Start-time / horizon sensitivity sweep ✅ SHIPPED (this session)
`scripts/run_starttime_sweep.py` — the same **locked** champion over a grid of `(start, end)`
windows, to answer "how much does the day I start matter?" A robust edge → tight return spread;
a fragile / path-dependent one → wide spread. Thin CLI over `population_runner`; three grids
(`rolling` fixed-horizon walk, `horizon` growing-end, `matrix` full cross); fair
window-length-invariant metrics via `sharpe_from_returns` (ann_return / sharpe / maxDD, never raw
total_return). Smoke-passed; **early finding: two adjacent start months gave a 133-pt ann_return
spread (−24% vs +109%) → champion looks strongly start-time dependent.** This *gates* Thing 1:
a monitor for a path-dependent strategy must present start-time-conditional confidence, not one P&L.

**Full sweeps run (2026-07-05).** Also fixed a real bug: the parallel path submitted a *local
closure* to `ProcessPoolExecutor` (unpicklable) — only the serial `--smoke` path ever worked;
lifted `_run_cell` to module level.

**VERDICT — the champion is strongly start-time dependent (regime ride, not start-invariant skill):**
- **`rolling` (53 cells, fixed 12m horizon)** — the decisive read. ann_return **−39.4% .. +196.6%**
  (median 21.6%, IQR 61.2%); Sharpe **−0.88 .. +2.45** (median 0.68); **17/53 cells Sharpe-negative.**
  Regime-clustered: 2021 & 2025 starts win big, mid-2022 starts lose. Same holding period, only the
  start month differs → the edge is a beta/regime ride.
- **`horizon` (fixed start, growing end)** — ann_return mean-reverts 517% (6m) → ~35–55% (36–48m) as
  the window dilutes the 2021 melt-up. Long-run Sharpe settles ~0.9–1.2.
- **`matrix` (84 cells, full cross)** — data/selection_sweep/starttime/champion/matrix/report.md.

Implication for the monitor (confirmed): it must present **start-time-conditional confidence**, not
one P&L — the honest live number is a *distribution over start dates*, and the operated book's date
is one draw from a −39%..+197% cone. Do not headline a single equity curve.

#### Thing 1 — Forward shadow book (live monitoring) — ✅ Steps 1–5 SHIPPED (2026-07-05), parity GREEN
A dashboard "shadow book": what the champion **would buy / hold / partial / exit / cut today** if
followed live. Confirmed mechanics (design review):

- **Incremental, not a re-run.** A persisted positions book is carried day-to-day; each night
  ingests only the new day's scores + prices and applies the rules (exit/cut → partial T1 →
  hold → enter free slots). BackTrader is an event-loop *replayer* and cannot step forward one
  day — hence a new pure step engine.
- **Configurable start date**, and **many books** keyed by `book_id` (schema supports N; we
  operate 1 for now — the champion). A past `--start-date` **catches up** by looping the same
  `step()` over already-known days to reach today's realistic state, then goes incremental.
- **Fill convention:** match the backtest (next-open) so the monitor is a faithful mirror of the
  validated numbers and the parity test is tight.

**Gap** (why this isn't free): the *rules* are pure, but in `SEPAHybridV1` they're expressed
through BackTrader primitives a nightly incremental doesn't have —
  - **G1 async orders:** `self.sell()` → `pending_orders` → `notify_order` fill confirmation, and
    the whole `*_pending` dedupe machinery. Forward = synchronous fill at a known price.
  - **G2 feed indexing:** `data.{low,high,close,volume,atr}[0]`, `sma50.get(t)[0]`. Forward has one
    row per ticker per day; needs ATR14 + SMA50 precomputed per (ticker, day).
  - **G3 warmup/bar-count** (`_bars_seen`, `prenext`) — irrelevant forward.
  - **G4 no persistence** — state is RAM-only for one backtest run.

  **Not a gap (reuse verbatim):** `SEPAPosition` + `PositionTracker.{check_stops,check_targets,`
  `update_stops,is_in_cooldown,effective_exit_reason}` are already plain-value; `ScoreLookup.`
  `get_candidates()` is a plain DataFrame lookup. The BackTrader coupling is *only* in
  `SEPAHybridV1`.

**Implementation steps** (Steps 1–5 = research box, zero infra risk; Step 6 = supervised `sh019`):

1. ✅ **`src/backtest/forward_engine.py`** — `ChampionBook.step(day, scores, prices) -> list[Action]`
   runs the exact `next()` sequence (regime-liquidate → update stops → stops → targets → trend →
   entries) with **synchronous next-open fills** (a one-day pending queue mirrors BackTrader:
   decided on T, filled at T+1 open × slippage). Reuses `PositionTracker` unchanged. Unsupported
   champion-off branches (E2-delay, persistence, score-drop, rank-exit, warmup, skip-top) raise
   `NotImplementedError` in `__init__` rather than shipping untested ports. Has a DB-free `__main__`
   self-check (queue → next-open fill → stop).
2. ✅ **`build_price_frame()`** (in `forward_engine.py`) — atr14 = `ewm(span=14)` of TR and the
   `<50 bar` skip lifted verbatim from `runner._add_price_feeds_from_duckdb`; sma50 = `rolling(50)`
   (bt SMA emits NaN until warm, engine skips trend-exit on NaN). This is the G2 fix.
3. ✅ **`shadow_book` + `shadow_action` tables** — DDL + idempotent-per-`book_id` upsert in
   `run_shadow_book.persist()` (DELETE-then-INSERT for the book_id). Many-book keyed by `book_id`.
4. ✅ **`scripts/run_shadow_book.py --strategy champion --start-date … [--book-id …] [--no-persist]`**
   — **replay-to-today, not incremental serialization**: the book is a pure function of
   (scores, prices, regime), a few hundred days replays in seconds, so every run recomputes the full
   book and rewrites the two tables (idempotent). Far less fragile than pickling live tracker state;
   same observable result as "catch-up then incremental".
5. ✅ **`tests/test_forward_parity.py`** (LOAD-BEARING GATE) — **GREEN.** Runs the champion through
   both engines over 2024-H1, feeding the forward engine the *exact* feed frames the backtest built
   (isolates engine-logic parity from data-load drift), asserts entry-set Jaccard > 0.85. Also
   asserts the unsupported-config guard raises. First pass was 17% overlap → root cause: BackTrader's
   `next()` doesn't fire until **every** feed's SMA50 is warm (the latest-listing ticker gates the
   whole strategy — global warmup at 2024-04-22, not Jan). The parity test replicates that all-feed
   warmup; overlap jumped to green.

> **Design decision — warmup diverges intentionally between backtest and live book.** The parity
> test uses BackTrader's **all-feed** global warmup (bit-faithful). The *live* `run_shadow_book.py`
> uses **per-ticker** warmup (a name trades once its own SMA50 exists) — chosen because all-feed
> means one recent IPO freezes the entire book (with the full universe, warmup slipped to
> ~2024-06-24, ~2 trading days before window end). Rules/fills are identical; only the
> first-tradeable-day gating differs. If a future need requires the two to match, revisit.

6. **Orchestrator phase** (LAST, on `sh019`, supervised — NOT started). **Deferred by design: no
   start date chosen yet.** The start-time sweep (Thing 2) exists precisely to inform *when* to begin
   the simulation — a 12-month return swings −39%..+197% by start month, so the inception date is a
   real decision, not a default. Until it's picked, there is nothing to operate.

   **Intended daily mechanism (registry-driven, replaces the ad-hoc replay):**
   a. A human decides an inception date, runs a **one-time backfill** (the current `run_shadow_book.py
      --start-date …` replay is exactly this backfill), and **registers `(book_id, strategy,
      start_date, status=active)`** in a small `shadow_book_registry` table.
   b. The nightly orchestrator phase (after scoring materializes `daily_predictions`) **detects active
      registry rows** and, for each, **steps only the new day forward incrementally** — NOT a full
      replay. The forward engine's `step()` is already the per-day unit; the nightly path loads the
      persisted `shadow_book` state, applies one `step(today)`, and appends to `shadow_action`.
   c. Materialize `shadow_book`/`shadow_action` to the dashboard DB — **must add both tables (and the
      registry) to `build_dashboard_db` MANIFEST or the R2 remote app breaks** (dashboard-remote-parity).

   > The **grid sweeps are exploration-only** — the daily pipeline never runs a grid. The registry
   > entry is the trigger; incremental `step()` is the daily unit of work. Flag before touching the
   > infra box.

#### Carried-over guards (still valid)
- Extend `check_backtest_parity.py` / `test_backtest_smoke.py` to cover the new primitives
  (`selection_skip_top`, `regime_gate`, `max_concurrent_positions`) (G6).
- **Fix or delete the `G_x4` pure-ATR expression** (G7 — XS). *(G7 already fixed in the 07-05
  productionisation — 0.30 wide net; verify and close.)*

#### Prerequisites before ANY real capital (unchanged, non-negotiable)
- **Tier A.2 friction / liquidity-floor re-run** — the champion's edge (esp. microcap +861%) is
  unproven under realistic costs. Paper shadow (Thing 1) may run in parallel; capital may not.
- Forward-quarter probation on unseen 2026-H2 — the OOS gate's 3 folds were all designable-in;
  the paper shadow *is* the real forward OOS.

## 5. Sequencing & effort
Phase 1 first (registry — the shared vocabulary), then Phase 2 (the gate), then Phase 3 (shared
runner). **Phases 1–3 + G7 are SHIPPED (2026-07-05).**

Phase 4 is now two tracks:
- **Thing 2 (start-time sweep)** — SHIPPED this session; only the full runs remain.
- **Thing 1 (forward shadow book)** — next session. Unlike Phases 1–3 this *is* a small piece of
  new code (the pure `step()` engine): the rules are already written, but they're currently trapped
  inside BackTrader's async-order + feed-indexing model, so they must be extracted. Steps 1–5 are
  research-box, gated by the parity test (Step 5). Step 6 (orchestrator wiring) is a separate,
  supervised change on the `sh019` infra box — do not touch the running Prefect nightly until parity
  is green and the sweep confirms the edge is worth monitoring.

## 6. Explicit non-goals (YAGNI)
- No generic "strategy plugin" / class hierarchy — the kwargs-passthrough already covers every
  config we have. A registry dict + fingerprint parser is enough.
- No new optimizer — `run_strategy_wfo.py` stays for search; the OOS gate is for *validation* of a
  fixed config. Don't merge them.
- No UI/dashboard for *backtest sweeps* — artifacts + comparison.md/report.md are sufficient. (The
  Phase-4 *forward shadow book* dashboard is a separate, deliberate deliverable — live monitoring of
  the operated champion, not backtest browsing.)
- No generic forward "paper-trading framework" — the shadow book is one `step()` function + two
  tables for the champion. Many-book is a `book_id` key, not a plugin system. YAGNI the broker sim.
- **Do not chase the microcap +861%** — the productionised suite's first job is the *friction /
  liquidity-floor re-run* (Path forward Tier A.2), which likely lowers the number. That's the point.
