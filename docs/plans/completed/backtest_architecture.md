# SEPA Backtest System Architecture

> Last updated: 2026-04-20

---

## 1. Strategic Objective

**What we want to validate:** Given a universe of stocks that enter a SEPA trend template (`trend_ok`) and subsequently trigger a breakout (`breakout_ok`), does the M01 classifier's "Elite" probability (`P(Class 3)`) reliably identify the setups that go on to produce 30%+ MFE returns?

**The strategy under test:**
1. **Watchlist Construction:** When a ticker satisfies `trend_ok AND breakout_ok`, it enters the watchlist.
2. **Daily Scoring:** Every day, re-score all watchlist candidates that we have not yet purchased.
3. **Entry Gate:** Buy only when `P(Elite) >= threshold` (configurable, e.g., 0.20).
4. **Capital Allocation:** Rank eligible candidates by `P(Elite)` over a configurable lookback window. Buy the top N (e.g., 3) if capital slots are available.
5. **Position Sizing:** Regime-scaled (M03 controls gross exposure).
6. **Exit:** 3-Tranche scaling exit (stop-loss → profit targets → trend break).

---

## 2. Current System Design

### A. Data Flow Overview

```
d2_training_cache (sparse: 1 row per trade at entry)
    │
    ├─→ UniverseScorer.score_from_duckdb()     ← M01 model scoring
    │       Outputs: calibrated_score, daily_pct_rank, trailing_10d_pct
    │       Saved to: universe_scores_duckdb.parquet
    │
    ├─→ ScoreLookup (in-memory index by date)
    │       Feeds: SEPAHybridV1._process_entries()
    │
t2_regime_scores
    │
    └─→ M03RegimeFeed                          ← Regime category (0-4)
            Feeds: SEPAHybridV1.next()

price_data
    │
    └─→ SEPAStockFeed (per ticker)             ← OHLCV + inline ATR-14
            Feeds: BackTrader broker execution
```

### B. Scoring Pipeline (`UniverseScorer`)

| Step | What happens | Source |
|------|-------------|--------|
| 1. Load data | Reads `d2_training_cache` for date range | DuckDB |
| 2. Feature alignment | Maps model features; generates missing `log_*` inline | Pandas |
| 3. Predict | `model.predict_proba(X)` → 4-class probabilities | XGBoost |
| 4. Calibrated score | Weighted Expected Value: `sum(proba * [1, 6, 20, 40])` | Hardcoded midpoints |
| 5. Daily rank | Cross-sectional percentile per day | `groupby('date').rank(pct=True)` |
| 6. Trailing rank | Percentile vs all scores from past 10 trading days | Rolling window |
| 7. Normalized score | Min-max scale to 0–100 | Global across all dates |

**Key detail:** The model metadata file (`metadata.json`) supplies the feature list. The `UniverseScorer` auto-detects classifier vs regressor by inspecting the XGBoost booster config.

### C. Entry Logic (`SEPAHybridV1._process_entries()`)

Each trading day, the strategy:

1. **Checks regime capacity:** `max_positions = regime_max_pos[regime]` (0/4/8/10/12 by regime 0–4).
2. **Queries ScoreLookup:** `get_candidates(date, min_score=30, rank_by='trailing')` returns all candidates above the score floor, sorted by trailing 10-day percentile descending.
3. **Filters candidates:**
   - Skip if already holding (`has_position`)
   - Skip if in cooldown (3 days after a stop-out)
   - Skip if price < $1 (`min_price`)
   - Skip if dollar volume < threshold (`min_dollar_volume`, default: 0 = no filter)
4. **Fills available slots:** Buys the top candidates until `available_slots` is exhausted.

### D. Position Sizing (`calculate_position_size()`)

| Sizing Mode | Logic |
|-------------|-------|
| `regime` (default) | Fixed % per regime: {0: 0%, 1: 2.5%, 2: 5%, 3: 7.5%, 4: 10%} |
| `equal_weight` | `1 / max_positions` per slot |
| `rank_weighted` | Base size × (0.5 + rank × 1.5) |
| `score_weighted` | Base size × (score / 50) |

Shares = `int(portfolio_value * size_pct / price)`. Minimum 3 shares required (for 3 tranches).

### E. Exit Logic (3-Tranche Scaling)

| Phase | Trigger | Action | Stop Behavior |
|-------|---------|--------|---------------|
| **Initial Stop** | `low <= max(entry - 2×ATR, entry × 0.90)` | Sell 100% of remaining | Fixed until T1 hit |
| **Target 1** | `high >= max(entry + 3×ATR, entry × 1.15)` | Sell 1/3 of initial | Begins trailing at 1.5×ATR from high |
| **Target 2** | `high >= T1 + 2×ATR` | Sell 1/3 of initial | Tightens to 1.0×ATR from high |
| **Trend Exit** | `close < SMA(50)` (only after T1+T2 sold) | Sell remaining 1/3 | N/A |
| **Regime Liquidation** | M03 regime drops to 0 (Strong Bear) | Sell 100% of all positions | N/A |

**Stop trailing detail:** Before T1 is hit, stops do NOT trail — they stay at the initial level. After T1, stops ratchet up (high-water mark, never moves down). After T2, the trailing distance tightens from 1.5×ATR to 1.0×ATR.

### F. Broker Configuration

| Parameter | Default | Notes |
|-----------|---------|-------|
| Initial cash | $100,000 | |
| Commission | 0.1% per trade | Percentage-based (not fixed per share — Backtrader bug workaround) |
| Slippage | 0.1% | Applied to execution price |
| Late-start cutoff | 60 days into backtest | Tickers IPO'ing after this are excluded |
| Min data bars | 50 | Tickers with < 50 bars of price data are excluded |

### G. Metrics & Reporting

| Metric | Source |
|--------|--------|
| Sharpe Ratio | `bt.analyzers.SharpeRatio` (annualized daily) |
| Max Drawdown | `bt.analyzers.DrawDown` |
| Calmar Ratio | Custom `CalmarRatio` analyzer |
| SQN | `bt.analyzers.SQN` |
| Win Rate, PnL | `bt.analyzers.TradeAnalyzer` |
| Exposure stats | `SEPAHybridV1.get_exposure_stats()` from daily snapshots |
| Signal rejections | `SEPAHybridV1.get_signal_rejection_stats()` |

**Output artifacts** (saved to `data/backtest/<run_name>/`):
- `equity_curve.parquet` — daily portfolio value, cash, exposure, regime
- `trades.parquet` — all closed trades with entry/exit dates, PnL, exit reason
- `metrics.json` — extended metrics including monthly returns, regime performance
- `manifest.json` — run parameters and summary
- `report.md` — markdown summary
- `plot.png` — 3×2 matplotlib panel (equity curve, drawdown, monthly heatmap, PnL distribution, regime performance, exit reasons)

### H. Visualization

Currently uses **matplotlib** for static 3×2 panel plots saved as PNG. Six panels: equity curve with regime overlay, underwater drawdown, monthly returns heatmap, trade PnL bar chart, avg PnL by regime, exit reason pie chart. These are not interactive and cannot be zoomed/panned in a notebook.

---

## 3. Components Checklist

### Data Pipeline
- [x] Price feed loading from DuckDB (`price_data`)
- [x] Regime feed from DuckDB (`t2_regime_scores`)
- [x] M01 model scoring (`UniverseScorer`)
- [x] Feature alignment + missing feature generation (`log_*` transforms)
- [x] M03 feature merging for models that need regime inputs
- [x] Score persistence (parquet for `ScoreLookup`)
- [ ] **Daily continuous scoring** — currently only scores Day 0 breakout snapshot
- [ ] **Warmup period** — no explicit warmup buffer for trailing percentile ranking

### Entry Logic
- [x] Regime-gated max positions
- [x] Score floor filter (`min_score=30`)
- [x] Cooldown enforcement (3 days post stop-out)
- [x] Dollar volume filter
- [x] Minimum price filter
- [x] Trailing 10-day percentile ranking
- [x] Duplicate position prevention
- [x] Signal rejection tracking with reasons
- [ ] **Elite probability threshold** — currently uses Expected Value, not raw `P(Class 3)`
- [ ] **Configurable lookback window** — hardcoded to 10 days in `UniverseScorer`
- [ ] **Watchlist persistence** — no notion of "watchlist candidates not yet bought"

### Position Sizing & Risk
- [x] Regime-scaled sizing (4 modes)
- [x] Minimum 3-share floor for tranche math
- [x] Commission and slippage modeling
- [x] Daily exposure tracking (avg/max/time invested)
- [x] Portfolio value-based sizing (not fixed dollar)

### Exit Logic
- [x] ATR-based initial stop
- [x] Trailing stop with high-water mark
- [x] Stop tightening after T1 and T2
- [x] 3-tranche profit target scaling
- [x] SMA(50) trend breakdown exit
- [x] Regime liquidation (Strong Bear)
- [x] Gap-down open protection (code present but commented out)
- [x] Exit reason tracking with progression (e.g., `target2_then_stop`)
- [ ] **Rank-based exit** — code exists (`exit_use_percentile`) but disabled by default

### Reporting & Visualization
- [x] Markdown report generation
- [x] Equity curve + trade parquet persistence
- [x] Monthly returns computation
- [x] Regime performance breakdown
- [x] Signal rejection summary
- [ ] **Interactive plots** — static matplotlib only, no zoom/pan/hover
- [ ] **Benchmark comparison** — no SPY overlay on equity curve
- [ ] **Rolling metrics** — no rolling Sharpe, rolling win rate, etc.
- [ ] **QuantStats integration** — not yet implemented

### Testing & Validation
- [x] Run persistence with manifest (reproducible)
- [x] Trade-level audit trail
- [ ] **Walk-forward consistency check** — no automated comparison between notebook CV and backtest
- [ ] **Leakage guard** — `LeakageGuard` exists for training but not wired into backtest scoring

---

## 4. Areas for Improvement

### 4.1 Daily Continuous Scoring (Critical)

**Current limitation:** `UniverseScorer.score_from_duckdb()` queries `d2_training_cache`, which contains exactly **1 row per trade** at the Day 0 breakout trigger. This is a sparse signal — a stock only gets scored once, the moment it first triggers `breakout_ok`.

**The problem:** A ticker enters the watchlist on Day 1 with a mediocre Elite probability (e.g., 12%). By Day 5, it has consolidated tightly at the breakout level — volatility contracted, volume dried up — and the model would now score it at 35% Elite probability. But the backtester never sees this because it only evaluated the Day 1 snapshot.

**Proposed 2-stage flow:**
1. **Stage 1 (Watchlist Entry):** When `trend_ok AND breakout_ok` triggers, add the ticker to an active watchlist. This uses `d2_training_cache` or `v_d1_candidates` to detect the initial breakout event.
2. **Stage 2 (Daily Re-Scoring):** Every day, re-score all watchlist tickers that we have NOT yet purchased. This requires reading from `t3_sepa_features` (which contains daily rows for all active SEPA candidates) and running `.predict_proba()` on their current-day features. The scorer outputs a fresh `P(Elite)` daily, and the strategy buys when it crosses the threshold.

**Data source for re-scoring:** `t3_sepa_features` already contains daily rows for every ticker while `trend_ok AND breakout_ok` remain true. This is the correct view to query — it provides the feature vector for each candidate on each day of the active SEPA trend.

### 4.2 Elite Probability Ranking (Important)

**Current limitation:** The `UniverseScorer` merges `predict_proba()` output into a single Expected Value using hardcoded midpoints `[1, 6, 20, 40]`. This dilutes the tail signal.

**Why Expected Value is wrong for this strategy:** We are specifically looking for "Home Run" setups (Class 3: 30%+ MFE). A stock with probabilities `[0.10, 0.30, 0.25, 0.35]` has P(Elite)=0.35 and Expected Value = 0.1×1 + 0.3×6 + 0.25×20 + 0.35×40 = 21.0. Another stock with `[0.05, 0.10, 0.60, 0.25]` has P(Elite)=0.25 and Expected Value = 0.05×1 + 0.1×6 + 0.6×20 + 0.25×40 = 22.65. The second stock ranks higher by EV but has a meaningfully worse chance of being a true Home Run.

**Fix:** Directly rank by `P(Class 3)` (the 4th element of the probability vector). Apply a hard minimum threshold (e.g., `prob_elite >= 0.15`) before a stock is eligible for purchase.

### 4.3 Configurable Lookback Window for Ranking

**Current limitation:** The trailing percentile window is hardcoded to 10 days in `_compute_trailing_percentile()`.

**Fix:** Expose `ranking_lookback_days` as a strategy parameter and pass it through to `UniverseScorer` and `ScoreLookup`. This allows testing different ranking horizons (e.g., 5-day for aggressive momentum, 20-day for persistence).

### 4.4 Warmup Period

**Current limitation:** The backtest starts scoring immediately on Day 1. With a 10-day trailing percentile, the first 9 days of ranking are computed against a progressively smaller population.

**Fix:** Add an explicit warmup period equal to `ranking_lookback_days`. During warmup days, skip all entry logic. The `run_backtest_duckdb()` function already requests a 1-year buffer for data loading (`warmup_start = start_dt - timedelta(days=365)`), but the scoring warmup within the strategy itself is missing.

### 4.5 Interactive Visualization with QuantStats

**Current limitation:** The `runner.plot()` method generates a static matplotlib 3×2 panel saved as PNG. These plots cannot be zoomed, panned, or hovered over in a Jupyter Notebook.

**Fix:** Integrate [QuantStats](https://github.com/ranaroussi/quantstats) to generate interactive HTML tear sheets natively in notebooks. QuantStats provides:
- Interactive equity curve with benchmark overlay (SPY)
- Monthly returns heatmap
- Rolling Sharpe ratio
- Underwater drawdown plot
- Distribution analysis
- Full tear sheet as a single `qs.reports.html()` call

Implementation: After `runner.run()`, extract the equity curve via `runner.get_equity_curve_dataframe()`, compute daily returns, and feed to QuantStats:
```python
import quantstats as qs
equity_df = runner.get_equity_curve_dataframe()
returns = equity_df['value'].pct_change().dropna()
returns.index = pd.to_datetime(returns.index)
qs.reports.html(returns, benchmark='SPY', output='backtest_tearsheet.html')
```

### 4.6 Regime Gating: Keep, But Document the Rationale

**Context:** M03 features are already part of the M01 model input. However, the regime-based portfolio liquidation in the strategy serves a fundamentally different purpose:
- **M01 uses M03** to predict individual stock outcomes (statistical inference).
- **Strategy uses M03** to enforce portfolio-level risk management (capital preservation law).

These are not duplicates. Even if M01 correctly predicts a 40% Elite probability for a single stock during a crash, the portfolio rule says "we refuse to have any capital deployed during a systemic meltdown." This is the difference between stock-level alpha and portfolio-level risk management.

**No change needed**, but the rationale should be explicitly documented in the strategy docstring to avoid future confusion.

### 4.7 Partial Fill Top-Ups

**Current state:** The strategy notes "We currently do NOT support topping up partial fills." With $100K initial capital and 10% position sizing, a single position is ~$10K. For liquid US equities (min price $1, the current floor), this amount is trivially fillable — daily dollar volumes for screener-eligible stocks are typically $1M+.

**Assessment:** This is a non-issue at the current capital level. Partial fills would only matter at institutional scale ($10M+) or for micro-cap/illiquid stocks. **No change needed for now.**

---

## 5. File Reference

| File | Purpose |
|------|---------|
| [runner.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/runner.py) | `SEPABacktestRunner` — orchestration, broker config, metrics extraction |
| [sepa_strategy.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/sepa_strategy.py) | `SEPAHybridV1` — entry/exit logic, regime gating, 3-tranche exits |
| [universe_scorer.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/universe_scorer.py) | `UniverseScorer` — M01 batch scoring, calibration, percentile ranking |
| [score_lookup.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/score_lookup.py) | `ScoreLookup` — in-memory O(1) date→ticker→score index |
| [position_tracker.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/position_tracker.py) | `PositionTracker` — 3-tranche state, trailing stops, cooldowns |
| [report.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/report.py) | Markdown report generator |
| [feeds.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/feeds.py) | `SEPAStockFeed`, `M03RegimeFeed` — BackTrader data feeds |
| [analyzers.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/analyzers.py) | Custom `CalmarRatio` analyzer |
| [run_backtest.py](file:///c:/Users/Hang/PycharmProjects/quantamental/scripts/run_backtest.py) | CLI entrypoint |
