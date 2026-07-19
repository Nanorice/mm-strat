# Backtester Manual — the vectorized strategy harness

> **Scope:** how to run a strategy on the **vectorized** engine
> (`src/backtest/vectorized_backtest.py`), where **model scores are just an input signal**.
> The strategy (enter / exit / size / rebalance) is defined by engine parameters, NOT by the
> model. Any model that can emit a `(date, ticker, score)` panel plugs into the same harness.
>
> Use the vectorized engine for research/iteration — it is optimistic by construction
> (no cash-block, charitable stop fills), so **promotion verdicts come from the
> BackTrader engine** (`runner.py` + `SEPAHybridV1`, DuckDB feeds — the old parquet-feed
> infra was removed). Full module reference: [backtest.md](../modules/backtest.md).

## 1. Mental model — signal vs strategy

```
  MODEL                          STRATEGY (this engine)
  ─────                          ──────────────────────
  scores each (date,ticker)  →   enter / rank / exit / size / rebalance
  = the SIGNAL                    = the DECISIONS on top of the signal
```

The engine never loads a model when you inject scores. It consumes a DataFrame:

| column | meaning | required |
|---|---|---|
| `date` | decision date | ✓ |
| `ticker` | symbol | ✓ |
| `prob_elite` | **the signal** the engine ranks/filters on (0–1 or any monotone score) | ✓ |
| `calibrated_score` | passthrough (reporting only; can equal `prob_elite`) | ✓ |

Swap the model → swap the panel → same strategy. That is the whole point.

## 2. The four strategy aspects (and the exact knobs)

All defined in `VectorizedSEPABacktest.__init__` / the run flow. None are model-specific.

### Rebalance — *when do we decide?*
**Implicit daily.** Scores exist per (date, ticker); **every trading day is a decision
point**. There is no calendar rebalance parameter — selection is continuous. Cadence is
controlled indirectly by how often the signal panel has rows and by the entry filter.

### Enter — *which names, how many?* (`_select_entries`, L112)
1. `min_prob_elite` — hard signal floor; rows below are ineligible.
2. rank remaining **descending by `prob_elite` within each day**.
3. `max_positions_per_day` — take the top-N per day.
4. **first-entry-per-ticker dedup** (L151) — a ticker is entered once per backtest window,
   on its first qualifying day. (Critical for "sticky" signals that stay high for many days.)
5. `warmup_days` — skip the first N unique dates (lets trailing features settle).

### Exit — *when do we leave?* (`_simulate_exits`, L204)
Priority order, first hit wins:
1. **stop_loss** — `low ≤ entry × (1 − stop_loss_pct)`; fills at the stop level.
2. **trend_break** — `close < SMA(sma_exit_period)` (default 50).
3. **max_hold** — `bars_held ≥ max_hold_days` (default 252).
Open at end of data → marked to last close, `exit_reason='held_open'`.

> **This is the aspect most coupled to strategy *type*.** M01 momentum-hold uses SMA50 / 252d.
> A short-hold breakout trade wants a small `max_hold_days` (and often no SMA exit). The exit
> block is where a new strategy *type* is expressed — see §5.

### Size — *how much per name?* (`equity_curve`, L302)
- `position_size_pct` (default 0.10) — fraction of current equity per position.
- shared pool: `max_slots = round(1/position_size_pct)`; when more positions are open than
  slots, each is scaled **pro-rata** (no N-way full-capital leverage).
- `initial_cash`, `commission_pct`, `slippage_pct` — accounting.
- **`exposure` (optional daily Series)** — a *separate* portfolio-level weight in [0, ~1.2],
  e.g. a VIX/regime dial. Scales each day's return **without touching selection** — same
  trades, sized differently. Must be lagged by the caller (no lookahead). This is where
  macro/regime belongs (see §6), NOT in the score.

## 3. Minimal run — inject a score panel

```python
from src.backtest.vectorized_backtest import VectorizedSEPABacktest

# scores: DataFrame[date, ticker, prob_elite, calibrated_score] from ANY model
vbt = VectorizedSEPABacktest(
    model_path="models/m01_binary/v1/model.json",  # only satisfies price loader; unused for selection
    start_date="2025-10-06", end_date="2026-05-22",
    precomputed_scores=scores,          # ← the signal
    min_prob_elite=0.15, max_positions_per_day=3,
    stop_loss_pct=0.10, sma_exit_period=50, max_hold_days=252,
    position_size_pct=0.10,
)
trades = vbt.run()          # → trade blotter
print(vbt.metrics(trades))  # → sharpe / ann_return / max_drawdown / win_rate ...
eq = vbt.equity_curve(trades)                    # bar-by-bar mark-to-market
eq_sized = vbt.equity_curve(trades, exposure=w)  # same trades, macro-sized
```

Without `precomputed_scores`, the engine self-scores via `UniverseScorer.score_from_t3` —
only works for models with a loadable `model.json` + `categorical_mapping.json`. **Injection
is the general path** and is required for any model the scorer can't load (WF regressors,
prod-only prototypes, etc.).

## 4. Getting a score panel — three sources

| Model type | How to get the panel | Example |
|---|---|---|
| Loadable classifier (`model.json` + `categorical_mapping.json`) | `UniverseScorer(m01_path=...).score_from_t3(start,end)` → has `prob_elite` | m01_binary |
| Prod-materialized only | pull `daily_predictions`, pick the prob column as `prob_elite` | m01_prototype (`run_model_arena.py:66`) |
| Regressor / no frozen vocab | run the booster(s) over the feature matrix, rename the output → `prob_elite` | m02_breakout |

For a **full-fit** (non-WF) model, this is one booster over the panel — trivial. (A WF model
would need per-fold routing to stay leak-free; prefer a full-fit deployable artifact so the
score panel is a single clean pass.)

## 5. Adding a new strategy *type* (e.g. short-hold breakout)

The engine already parametrizes momentum-hold. A different type = a different exit shape.
Lazy path: add an `exit_policy` arg, keep the current SMA path as the default so nothing
changes for M01.

- `exit_policy='sma'` (default) → current behaviour (stop > SMA > max_hold).
- `exit_policy='nday'` → stop > fixed N-day hold (`max_hold_days`), **no SMA break**.
- (later) `'atr_trail'`, `'confirm'` — add only when a simpler exit shows the entry has edge.

Do NOT create a subclass per strategy — one engine, an exit-policy switch. The signal panel
and enter/size knobs are unchanged across types.

## 6. Sizing / regime — why it's separate (and not idiosyncratic)

Macro/regime (VIX, M03) is a **portfolio-level exposure dial, not a stock selector.** Every
ticker shares the same macro value on a given day, so it cannot rank *which* names — it can
only scale *how much* total capital is deployed. That is exactly why it lives in the
`exposure` Series (sizing), never in `prob_elite` (selection). Keeping them separate avoids
double-counting the same macro information in both selection and sizing.

Evidence to date (`scripts/run_sizing_experiment.py`, `src/backtest/macro_sizer.py`):
**VIX-banded exposure adds real risk-timing value; M03-banded is a no-op.** Build the
`exposure` Series with `MacroSizer` (1-day lag, no lookahead) and pass it to `equity_curve`.

## 7. Related tooling (same engine, different wrapper)

- `scripts/run_model_arena.py` — many models, **one fixed strategy**, ranked by Sharpe.
- `scripts/run_strategy_optimizer.py` — Optuna over the strategy knobs (single IS/OOS split).
- `scripts/run_strategy_wfo.py` — walk-forward re-tune; the **overfit gate**. Accepts injected
  scores, so a new model/strategy can be gated OOS the same way M01 was.
- `scripts/run_sizing_experiment.py` — same trades, different `exposure`; isolates the macro dial.

## 8. Known approximations (fine for ranking; documented, not bugs)

- Entry fill = close on the entry bar (next-day-open not modelled).
- Stop fill = the stop level (no gap-through slippage beyond it).
- `held_open` trades marked to last available close.
- Capital constraint is pro-rata approximate, not a true cash-blocking ledger.
Use BackTrader `runner.py` only for a final production-fidelity pass; the vectorized engine is
for research iteration and comparative ranking.
