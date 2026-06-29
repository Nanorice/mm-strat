# Side-Quest: vnpy (VeighNa) vs Our Backtest Framework — Gap Analysis

> Sprint 13, Goal 4 side-quest. Question from the roadmap: *"Compare with vnpy to
> see if there are any gaps not implementable in the current framework (pros and
> cons)."* This is an **architectural comparison**, not a port. vnpy was **not**
> installed — it's a heavy live-trading stack whose value here is as a capability
> yardstick, not a dependency.

## TL;DR verdict

**Do not adopt vnpy.** It solves a different problem (real-time, multi-gateway,
China-futures/A-share live trading) and is architecturally mismatched to a
US-equity, ML-scored, end-of-day SEPA research pipeline. Our framework already
covers the backtesting surface that matters to us, plus things vnpy lacks
natively (ML model-scoring contract, prod-parity verification, regime gating).

The few genuine gaps vnpy exposes are **cheap to address in our own stack** and
worth cherry-picking as ideas, not as a framework swap:
1. **Parameter optimization** (grid/genetic) — we have a manual strategy array, no optimizer.
2. **Portfolio-level risk manager** (pre-trade order/exposure limits as a first-class layer).
3. **A live-trading bridge** — if/when SEPA goes live, our backtest strategy logic isn't reusable for execution.

None of these require vnpy; each is a focused module in our codebase.

---

## What vnpy actually is

VeighNa (formerly vnpy) is a **full-stack live algorithmic trading platform**,
event-driven at its core, built primarily for **Chinese domestic markets**
(CTP futures, A-shares, ETF options) with international access only via the
Interactive Brokers gateway. Backtesting is one app among many.

Core modules (concrete names):
- **Event Engine** (`vnpy.event`) — the real-time event bus everything sits on.
- **Gateways** — 20+ broker/exchange connectors (CTP, IB, etc.). The reason the
  platform exists; irrelevant to research backtesting.
- **Apps**: `CtaStrategy` (single-instrument CTA), `PortfolioStrategy`
  (multi-contract alpha), `SpreadTrading`, `OptionMaster`, `RiskManager`,
  `AlgoTrading` (TWAP/Iceberg/Sniper execution), `PaperAccount`, `DataManager`,
  `PortfolioManager`.
- **Backtesters**: `vnpy_ctabacktester` (GUI), Portfolio backtest, and the newer
  `AlphaLab` (data → model training → signal → backtest workflow).
- **DB**: SQLite/MySQL/PostgreSQL/MongoDB/DolphinDB. **Data**: RQData, XtQuant,
  TuShare, Wind, Polygon, etc.

Design center: **fine-grained, per-tick, live execution with a GUI**. Backtest
fidelity exists to validate strategies that will run live through the same
`CtaTemplate` code path.

---

## What our framework is

A **research backtester for an ML-scored US-equity swing strategy** (SEPA),
end-of-day bars, DuckDB-backed.

- **Two engines, shared scorer** (`src/backtest/`):
  - **BackTrader event-driven** (`runner.py` + `sepa_strategy.py`) — full fidelity:
    3-tranche scaled exits, ATR trailing stops, M03 regime gating (liquidate on
    Strong Bear), regime-based sizing, cooldowns, persistence gate, signal-rejection
    accounting, exposure stats.
  - **Vectorized** (`vectorized_backtest.py`) — pandas/numpy, 10–100× faster, for
    sweeps/prototyping.
- **Scorer** (`universe_scorer.py`) — batch XGBoost scoring from `t3_sepa_features`,
  now routed through the shared `categorical_encoding` util so backtest scoring is
  **byte-identical to prod** (`daily_predictions`), verified by
  `scripts/check_backtest_parity.py` (99.8% match).
- **Strategy array** (`run_strategy_array.py`) — runs S1..S5 parameter sets on the
  same universe/window/model and ranks them (`comparison.md`). Manual grid.
- **Reporting** — markdown report, 6-panel matplotlib, QuantStats HTML tearsheet,
  parquet/JSON run artifacts, Calmar analyzer (`analyzers.py`).
- **Walk-forward OOS** (`src/evaluation/walk_forward_backtest.py`) — folded
  out-of-sample evaluation, unit-tested.

Design center: **reproducible model comparison on historical equity data**.

---

## Capability matrix

| Capability | vnpy | Ours | Notes |
|---|---|---|---|
| Event-driven backtest | ✅ `CtaStrategy` | ✅ BackTrader | Parity. Ours adds 3-tranche + regime gating out of the box. |
| Vectorized fast engine | ❌ (event-only) | ✅ `VectorizedSEPABacktest` | **We win** — vnpy has no vectorized path for fast sweeps. |
| Portfolio / multi-asset | ✅ `PortfolioStrategy` | ✅ (N feeds, slot limits) | Both handle multi-instrument portfolios. |
| Parameter optimization | ✅ grid + genetic | ⚠️ manual array (S1..S5) | **vnpy gap** — no optimizer; we sweep by hand. |
| Pre-trade risk manager | ✅ `RiskManager` app | ⚠️ in-strategy checks only | **vnpy gap** — risk limits are strategy code, not a layer. |
| Execution algos (TWAP…) | ✅ `AlgoTrading` | ❌ n/a | Irrelevant to EOD backtest. |
| Live trading / gateways | ✅ 20+ gateways | ❌ none | **By design** — we don't trade live (yet). |
| ML model scoring | ⚠️ AlphaLab (newer) | ✅ first-class | **We win** — XGBoost + frozen categorical vocab + calibration baked in. |
| Prod ↔ backtest parity | ❌ | ✅ `check_backtest_parity.py` | **We win** — provable scoring identity vs materialized predictions. |
| Regime gating | ❌ (strategy-coded) | ✅ M03 feed, native | **We win** for our use case. |
| Tearsheet / analytics | ⚠️ basic | ✅ QuantStats + custom | We lean on QuantStats. |
| GUI | ✅ Qt desktop | ❌ (dashboard instead) | Different paradigm; our Streamlit dashboard covers review. |
| Market focus | CN futures/A-share | US equities | **Fundamental mismatch.** |
| Data backend | SQL/Mongo/Dolphin | DuckDB | Ours is purpose-fit. |

---

## Genuine gaps vnpy exposes (and how to close them *without* vnpy)

### 1. Parameter optimization — **real, medium value**
vnpy's CTA backtester ships grid + genetic-algorithm optimization. We have
`run_strategy_array.py` (a hand-curated S1..S5) but no systematic sweep/optimizer.
**Close it in-house**: a thin driver over the *vectorized* engine doing
`itertools.product` across a param grid (or Optuna for larger spaces), reusing the
precomputed-scores/prices caches already in `VectorizedSEPABacktest`. ~1 module.
⚠️ Pair any optimizer with the walk-forward harness to avoid overfit — the danger
isn't the tool, it's in-sample knob-tuning.

### 2. Portfolio-level risk layer — **real, low-medium value**
vnpy's `RiskManager` is a first-class pre-trade gate (order count, flow, position
limits) independent of strategy logic. Ours lives *inside* `SEPAHybridV1`
(`regime_max_pos`, `min_price`, `min_dollar_volume`, cooldown). Fine for backtest,
but if rules grow it'd be cleaner as a separate checker the strategy consults.
Low urgency; note for later.

### 3. Live-trading reuse — **real, deferred**
vnpy's headline strength: the *same* `CtaTemplate` runs in backtest and live. Our
`SEPAHybridV1` is BackTrader-only and can't drive execution. If SEPA ever goes
live, the entry/exit logic would need re-implementation against a broker API.
**Not a backtester-finalisation concern** — flag for the eventual trading-system
phase (Goal 5).

---

## Why NOT to adopt vnpy (the cons, concretely)

- **Market/asset mismatch** — built for CN futures/A-shares; US-equity EOD support
  is thin and routes through IB. We'd fight the framework's grain constantly.
- **Live-trading weight** — event engine, gateways, Qt GUI, tick recording: all dead
  weight for a research backtester. Large dependency surface, much unused.
- **Loss of our differentiators** — we'd have to re-implement the ML scoring contract
  (categorical vocab freezing, calibration, prod-parity), regime gating, and the
  vectorized fast path. vnpy's AlphaLab is newer/less mature than our scoring stack.
- **No vectorized sweep path** — vnpy is event-only; our 10–100× vectorized engine for
  rapid model iteration would be lost.
- **Reproducibility regression** — our `daily_predictions` parity guarantee has no vnpy
  equivalent; we'd lose the proof that backtest == prod scoring.

## What's worth borrowing (ideas, not code)
- The **optimizer-as-first-class-citizen** mindset → build #1 above.
- **RiskManager as a separable layer** → refactor toward #2 if rules grow.
- The **single-codepath backtest↔live** principle → design Goal 5's execution layer
  so strategy logic is reusable, learning from vnpy's `CtaTemplate` pattern.

---

## Conclusion

The comparison **validates the current framework** for its actual job. vnpy is a
strong live-trading platform but the wrong tool for ML-scored US-equity research,
and adopting it would cost us our scoring/parity/regime differentiators. The only
backtester-relevant gap is **systematic parameter optimization**, which is a small
in-house module — recommended as the next enhancement after backtester finalisation,
gated through walk-forward to avoid overfit. Portfolio-risk-as-a-layer and
live-trading reuse are noted for the trading-system phase (Goal 5), not now.
