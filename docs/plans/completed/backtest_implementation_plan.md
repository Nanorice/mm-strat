# Backtest Infrastructure Upgrade — Implementation Plan

> Last updated: 2026-04-21  
> Status: **Awaiting approval**  
> Ref: [backtest_architecture.md](file:///c:/Users/Hang/PycharmProjects/quantamental/docs/backtest_architecture.md)

---

## Goal

Upgrade the SEPA backtesting engine to:
1. Score candidates **daily** (not just at Day 0 breakout)
2. Rank by raw **P(Elite)** probability (not Expected Value)
3. Support configurable **lookback windows** and **warmup periods**
4. Generate **interactive QuantStats** tear sheets
5. Provide a **vectorized fast-backtest** option for rapid notebook iteration

---

## Background & Data Context

| Source | Rows | Granularity | Use |
|--------|------|-------------|-----|
| `d2_training_cache` | 37,988 | 1 row per trade (Day 0 only) | Current scorer input |
| `t3_sepa_features` | 125,081 | 1 row per candidate per day | **Proposed** scorer input |
| `price_data` | ~12M | OHLCV per ticker per day | Exit logic |
| `company_profiles` | ~3K | Sector/industry per ticker | Categorical features |

> [!NOTE]
> `t3_sepa_features` does NOT contain `sector`/`industry` columns. When scoring from T3, we must LEFT JOIN to `company_profiles` for the 2 categorical features that the model requires.

---

## Component 1: Daily Continuous Scoring

### [MODIFY] [universe_scorer.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/universe_scorer.py)

#### 1A. New `score_from_t3()` method

Add a new method alongside the existing `score_from_duckdb()`. Do NOT modify `score_from_duckdb()` — keep it as the legacy sparse scorer.

```python
def score_from_t3(
    self,
    start_date: str,
    end_date: str,
    db_path: Optional[Path] = None,
    ranking_lookback_days: int = 10,
) -> pd.DataFrame:
    """
    Score SEPA candidates daily from t3_sepa_features.
    
    Unlike score_from_duckdb() which only scores Day 0 breakout snapshots,
    this method scores every active SEPA candidate every day, enabling
    the strategy to catch setups whose conviction improves post-breakout.
    
    Returns DataFrame with columns: date, ticker, calibrated_score,
    prob_elite, normalized_score, daily_pct_rank, trailing_Nd_pct.
    """
```

**SQL query:**
```sql
SELECT t3.*, cp.sector, cp.industry
FROM t3_sepa_features t3
LEFT JOIN company_profiles cp ON t3.ticker = cp.ticker
WHERE t3.date >= ? AND t3.date <= ?
  AND t3.feature_version = 'v3.1'
ORDER BY t3.date, t3.ticker
```

#### 1B. Add `prob_elite` to output

In both scoring methods, when `_is_classifier` is True, extract `proba[:, -1]` and include it in the result DataFrame:

```python
if self._is_classifier:
    proba = self.m01_model.predict_proba(X)
    midpoints = np.array([1.0, 6.0, 20.0, 40.0])[:self._num_classes]
    calibrated_scores = (proba * midpoints).sum(axis=1)
    prob_elite = proba[:, -1]    # P(Class 3) — the tail signal

result = pd.DataFrame({
    'date': df['date'].values,
    'ticker': df['ticker'].values,
    'calibrated_score': calibrated_scores,
    'prob_elite': prob_elite,    # NEW
})
```

#### 1C. Parameterize trailing window

Replace the hardcoded `window=10` in trailing percentile computation:

```diff
-result['trailing_10d_pct'] = self._compute_trailing_percentile(result, window=10)
+col_name = f'trailing_{ranking_lookback_days}d_pct'
+result[col_name] = self._compute_trailing_percentile(result, window=ranking_lookback_days)
+# Backward-compatible alias
+result['trailing_10d_pct'] = result[col_name]
```

---

## Component 2: Elite Probability Ranking

### [MODIFY] [score_lookup.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/score_lookup.py)

#### 2A. Extend the index tuple

Update `_load_and_index()` (lines 61–84) to store `prob_elite` as a 4th element:

```python
self._index[date_key] = {
    row['ticker']: (
        row['normalized_score'],
        row['daily_pct_rank'],
        row['trailing_10d_pct'],
        row.get('prob_elite', 0.0),     # NEW — raw P(Elite)
    )
    for _, row in group.iterrows()
}
```

#### 2B. Add `min_prob_elite` filter to `get_candidates()`

Update `get_candidates()` signature (line 89):

```diff
 def get_candidates(
     self,
     date: datetime,
     min_score: float = 30.0,
     min_percentile: float = 0.0,
+    min_prob_elite: float = 0.0,
     rank_by: Literal['trailing', 'daily'] = 'trailing',
 ) -> List[Tuple[str, float, float]]:
```

Add filter in the candidate loop (line 133):

```python
for ticker, (score, daily_rank, trailing_rank, prob_elite) in day_data.items():
    if score < min_score:
        continue
    if prob_elite < min_prob_elite:
        continue
    # ... existing logic
```

Update return tuple to include `prob_elite`:

```python
return [(ticker, score, trailing, prob_elite) for ...]
```

### [MODIFY] [sepa_strategy.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/sepa_strategy.py)

#### 2C. Add strategy parameters (lines 81–119)

```diff
 params = (
     ...
+    ('min_prob_elite', 0.0),        # Min P(Elite) for entry (e.g., 0.15)
+    ('warmup_days', 10),            # Skip entries during initial warmup
     ...
 )
```

#### 2D. Thread `min_prob_elite` into `_process_entries()` (line 466)

```diff
 candidates = self.score_lookup.get_candidates(
     current_date,
     min_score=self.p.min_score,
     min_percentile=self.p.entry_percentile_min,
+    min_prob_elite=self.p.min_prob_elite,
     rank_by=self.p.rank_by,
 )
```

---

## Component 3: Warmup Period Enforcement

### [MODIFY] [sepa_strategy.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/sepa_strategy.py)

Add bar counter to `__init__()`:

```python
self._bars_seen = 0
```

Guard entry logic in `next()` (before `_process_entries` call at line 279):

```python
# === WARMUP CHECK ===
self._bars_seen += 1
if self._bars_seen <= self.p.warmup_days:
    return  # Skip entries; exits still run if positions somehow exist

# === ENTRY LOGIC ===
self._process_entries(regime, current_date)
```

---

## Component 4: QuantStats Interactive Visualization

### Install dependency

```bash
pip install quantstats
```

### [MODIFY] [runner.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/runner.py)

Add `generate_tearsheet()` method after `plot()` (~line 963):

```python
def generate_tearsheet(
    self,
    benchmark: str = 'SPY',
    output_path: Optional[str] = None,
) -> Optional[str]:
    """
    Generate interactive QuantStats HTML tearsheet.

    Args:
        benchmark: Benchmark ticker (default: SPY).
        output_path: If provided, saves HTML to file.
                     If None, renders inline in Jupyter notebook.
    Returns:
        Path to saved HTML, or None if displayed inline.
    """
    try:
        import quantstats as qs
    except ImportError:
        logger.error("quantstats not installed. Run: pip install quantstats")
        return None

    equity_df = self.get_equity_curve_dataframe()
    if equity_df is None or len(equity_df) < 2:
        logger.warning("Insufficient equity data for tearsheet")
        return None

    returns = equity_df['value'].pct_change().dropna()
    returns.index = pd.to_datetime(returns.index)
    returns.index.name = None

    if output_path:
        qs.reports.html(returns, benchmark=benchmark, output=output_path)
        logger.info(f"Tearsheet saved to {output_path}")
        return output_path
    else:
        qs.reports.html(returns, benchmark=benchmark)
        return None
```

### [MODIFY] [run_backtest.py](file:///c:/Users/Hang/PycharmProjects/quantamental/scripts/run_backtest.py)

Wire into artifact saving in `run_backtest_duckdb()` (after plot saving, ~line 193):

```python
# Generate QuantStats tearsheet
if run_dir:
    tearsheet_path = str(run_dir / 'tearsheet.html')
    print("  - Generating interactive tearsheet...")
    runner.generate_tearsheet(output_path=tearsheet_path)
    print(f"    Saved: tearsheet.html")
```

---

## Component 5: Vectorized Fast-Backtest Engine

### [NEW] [vectorized_backtest.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/vectorized_backtest.py)

A pure pandas/numpy backtest engine that runs entirely without BackTrader. Designed for rapid notebook prototyping — 10-100× faster than the event-driven engine.

**Trade-offs vs BackTrader:**
| Aspect | BackTrader (`SEPAHybridV1`) | Vectorized |
|--------|---------------------------|------------|
| Speed | Minutes (event loop) | Seconds (vectorized) |
| Capital constraints | Exact (broker tracks cash) | Approximate (assumes slots always available) |
| Commission/slippage | Realistic | Optional flat estimate |
| Tranche exits | Full 3-tranche logic | Simplified (single exit) |
| Use case | Final production validation | Rapid model iteration |

#### Core API

```python
class VectorizedSEPABacktest:
    """
    Vectorized SEPA backtest for rapid notebook prototyping.
    
    Scores all T3 candidates daily, applies entry filters,
    simulates exits using vectorized pandas operations.
    No event loop — entire backtest runs in seconds.
    """
    
    def __init__(
        self,
        model_path: str = 'models/m01_prototype/model.json',
        db_path: str = 'data/market_data.duckdb',
        start_date: str = '2020-01-01',
        end_date: str = '2025-01-01',
        min_prob_elite: float = 0.15,
        max_positions_per_day: int = 3,
        ranking_lookback_days: int = 10,
        stop_loss_pct: float = 0.10,
        sma_exit_period: int = 50,
        warmup_days: int = 10,
    ):
        ...

    def run(self) -> pd.DataFrame:
        """
        Execute the full vectorized backtest.

        Returns:
            DataFrame with columns: date, ticker, entry_date, entry_price,
            exit_date, exit_price, exit_reason, pnl_pct, prob_elite_at_entry,
            holding_days
        """
        ...
    
    def summary(self, trades_df: pd.DataFrame) -> dict:
        """Print and return summary statistics."""
        ...
    
    def tearsheet(self, trades_df: pd.DataFrame, benchmark: str = 'SPY'):
        """Generate QuantStats tearsheet from trade results."""
        ...
```

#### Internal Logic (All Vectorized)

**Step 1: Score all candidates daily**
```python
scorer = UniverseScorer(m01_path=self.model_path)
scores = scorer.score_from_t3(self.start_date, self.end_date, 
                               ranking_lookback_days=self.ranking_lookback_days)
```

**Step 2: Filter and rank (vectorized groupby)**
```python
# Apply elite threshold
eligible = scores[scores['prob_elite'] >= self.min_prob_elite].copy()

# Skip warmup period
min_date = eligible['date'].min() + pd.Timedelta(days=self.warmup_days)
eligible = eligible[eligible['date'] >= min_date]

# Rank within each day, take top N
eligible['daily_rank'] = eligible.groupby('date')['prob_elite'].rank(
    ascending=False, method='first'
)
entries = eligible[eligible['daily_rank'] <= self.max_positions_per_day].copy()
```

**Step 3: Simulate exits (vectorized merge)**

For each entry, find the exit date by joining against `price_data` + T3 features:
```python
# For each (ticker, entry_date), expand to all future trading days
# and find first day where either:
#   a) close < entry_price * (1 - stop_loss_pct)    → stop-out
#   b) close < sma_50                                → trend break
# Use vectorized cummin/cummax to find first trigger date
```

This avoids any Python loops — the entire exit simulation is a merge + cumulative operation.

**Step 4: Compute portfolio equity curve**
```python
# Concatenate all trade PnLs, sorted by exit_date
# Build cumulative equity curve
# Feed to QuantStats for interactive reporting
```

### [MODIFY] [backtest_simulation_snippet.py](file:///c:/Users/Hang/PycharmProjects/quantamental/notebooks/backtest_simulation_snippet.py)

Rewrite the notebook snippet to use both engines:

```python
# ============================================================
# OPTION A: Fast Vectorized Backtest (seconds, for iteration)
# ============================================================
from src.backtest.vectorized_backtest import VectorizedSEPABacktest

vbt = VectorizedSEPABacktest(
    model_path='models/m01_prototype/model.json',
    min_prob_elite=0.15,
    max_positions_per_day=3,
    ranking_lookback_days=10,
)
trades = vbt.run()
vbt.summary(trades)
vbt.tearsheet(trades)

# ============================================================
# OPTION B: Full BackTrader Backtest (minutes, for validation)
# ============================================================
# from scripts.run_backtest import run_backtest_duckdb
# metrics, runner = run_backtest_duckdb(...)
# runner.generate_tearsheet()
```

---

## Dependency Summary

| File | Action | Component |
|------|--------|-----------|
| `src/backtest/universe_scorer.py` | Add `score_from_t3()` + `prob_elite` output | 1, 2, 3 |
| `src/backtest/score_lookup.py` | Extend index tuple + `min_prob_elite` filter | 2 |
| `src/backtest/sepa_strategy.py` | Add `min_prob_elite`, `warmup_days` params + guards | 2, 3 |
| `src/backtest/runner.py` | Add `generate_tearsheet()` method | 4 |
| `scripts/run_backtest.py` | Wire tearsheet into artifact saving | 4 |
| `src/backtest/vectorized_backtest.py` | **NEW** — full vectorized engine | 5 |
| `notebooks/backtest_simulation_snippet.py` | Rewrite to use both engines | 5 |
| `requirements.txt` or `pip install` | Add `quantstats` | 4 |

---

## Execution Order

Components must be implemented in this order due to dependencies:

1. **Component 1** (Daily Scoring) — `score_from_t3()` is the foundation for everything
2. **Component 2** (Elite Ranking) — depends on `prob_elite` from Component 1
3. **Component 3** (Warmup) — independent, but makes sense with the lookback param
4. **Component 5** (Vectorized Engine) — depends on Components 1-3
5. **Component 4** (QuantStats) — independent, can be done anytime

---

## Verification Plan

### Automated Tests

1. **Scoring compatibility:** Call `score_from_t3()` and `score_from_duckdb()` for overlapping date ranges. For any `(date, ticker)` pair present in both, verify that `prob_elite` values are identical (same features → same prediction).

2. **Elite filter sanity:** Run vectorized backtest with `min_prob_elite=0.90` → expect near-zero trades. Run with `min_prob_elite=0.0` → expect significantly more. Verify monotonic relationship.

3. **Warmup enforcement:** Run with `warmup_days=30`. Inspect trade log and verify no `entry_date` falls within the warmup window.

4. **Vectorized vs BackTrader consistency:** Run both engines on the same date range + parameters. Compare total trades, win rate, and average PnL. They won't match exactly (BackTrader has realistic capital constraints), but should be directionally consistent (±10% on win rate).

5. **QuantStats output:** Call `generate_tearsheet(output_path='test.html')`. Verify HTML file is created and opens in browser.

### Manual Verification

1. **Inspect trade log:** For 3-5 sample trades in the vectorized output, manually verify entry/exit dates against the T3 features and price data.

2. **Notebook rendering:** Run the full snippet in `model_proto.ipynb` and confirm QuantStats charts render inline.
