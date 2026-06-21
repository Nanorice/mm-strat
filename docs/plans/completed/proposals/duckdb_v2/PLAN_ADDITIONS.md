# Plan Additions Summary (2026-03-14)

## Three New Items Added to DuckDB V2 Plan

### 1️⃣ Column Naming Convention: Lowercase Consistency

**Location**: [Key Decisions Made (Decision #10)](logical-hatching-dewdrop.md#key-decisions-made)

**What was added**:
- **Decision 10**: All columns use lowercase consistently (including prices: `open`, `high`, `low`, `close`, `volume`)
- **Rationale**: DuckDB is case-insensitive for SQL queries, but Python downstream requires normalized casing for consistency
- **Impact**: Affects all T1/T2/T3 table schemas and view outputs

**Implementation Notes**:
- Update `schema_design.sql` to use lowercase column names
- Update `FeaturePipeline` SQL queries to output lowercase columns
- Update `ViewManager` to ensure all views use lowercase column names
- Update any Python data loading code to expect lowercase columns

---

### 2️⃣ Feature Optimization & Model Development

**Location**: [New Phase 4.5: Feature Optimization & Model Development](logical-hatching-dewdrop.md#phase-45-feature-optimization--model-development)

**What was added**:
Two new milestones added between Phase 4 (T3 backfill) and Phase 5 (view updates):

#### **Milestone 4.5.1: Feature Selection & Pipeline Reduction** (3 hours)
- **Input**: EDA findings from `notebooks/duck_eda.ipynb`
- **Output**: Reduced feature set (30-40 core features from 79 in Phase A, ~8 alphas from 16 in Phase B)
- **Tasks**:
  1. Document EDA findings: correlation matrix, feature importance scores, which to drop
  2. Update `FeaturePipeline` to compute only retained features
  3. Update `v_d2_training` to SELECT only retained columns
  4. Validate: M01 scores on reduced set should be stable (±5% correlation)
- **Benefit**: Faster daily computation, reduced overfitting, better interpretability

#### **Milestone 4.5.2: M01 Baseline Model & Entry/Exit Rules** (4 hours)
- **Input**: Reduced feature set from 4.5.1
- **Output**: Trained M01 model + entry/exit rules
- **Tasks**:
  1. Train M01 baseline regression on reduced features
  2. Establish entry rule: SEPA breakout + M01 score ≥ Xth percentile (e.g., ≥60th)
  3. Establish exit rules:
     - Stop-loss (ATR-based or -15%)
     - Take-profit (M01 score drops below Yth percentile or time-based)
  4. Document rule thresholds and rationale
- **Benefit**: Enables backtesting and strategy validation

---

### 3️⃣ Backtesting & Strategy Validation

**Location**: [New Phase 6.5: Backtesting & Strategy Validation](logical-hatching-dewdrop.md#phase-65-backtesting--strategy-validation)

**What was added**:
Two new milestones added between Phase 6.2 (monitoring) and Phase 7 (data quality):

#### **Milestone 6.5.1: Backtesting Engine** (4 hours)
- **Input**: Historical entry signals from M01 rules + `v_d3_deployment` features
- **Output**: Trade log (entry/exit dates, prices, returns) + portfolio metrics
- **Tasks**:
  1. Build backtester that applies entry/exit logic from `v_d2r_hydrated`
  2. Integrate with M01 rules for daily signal generation
  3. Track: entry price, exit price, exit date, return %, days held, exit reason
  4. Compute metrics: Sharpe ratio, win rate, avg return, max drawdown, Calmar ratio
  5. Add configurable parameters (date range, thresholds, position sizing)
- **Validation**: Run on 2024 historical data (252 trading days), ~100-200 trades expected

#### **Milestone 6.5.2: Backtest Optimization & Sensitivity Analysis** (5 hours)
- **Input**: Backtester from 6.5.1 + historical data range
- **Output**: Optimized entry/exit parameters + walk-forward validation report
- **Tasks**:
  1. Grid search over entry/exit percentiles and position sizing
  2. Run on 2023 data (out-of-sample) to find best combo
  3. Walk-forward validation on 2024 data (verify Sharpe degrades <20%)
  4. Document best-performing parameters
- **Validation**: Heatmaps showing Sharpe vs parameter combinations

---

## Updated Milestones Summary

**Old**: 20 milestones → **New**: 24 milestones

| Phase | New Milestones | Type | Time |
|-------|---|---|---|
| 4.5.1 | Feature Selection & Reduction | Feature Engineering | 3 hours |
| 4.5.2 | M01 Baseline & Rules | Model Development | 4 hours |
| 6.5.1 | Backtesting Engine | Validation | 4 hours |
| 6.5.2 | Backtest Optimization | Parameter Tuning | 5 hours |

**Total New Time**: 16 hours (development + analysis)

---

## Execution Order

The three items fit into the critical path as follows:

1. **Feature Optimization (4.5.1)**: Must happen after T3 backfill (4.2) ✅ Placed correctly
2. **Model Development (4.5.2)**: Depends on reduced features from 4.5.1 ✅ Placed correctly
3. **Backtesting (6.5.1-6.5.2)**: Depends on entry/exit rules from 4.5.2 ✅ Placed correctly

This creates a natural flow:
- T3 backfill → Feature optimization → Model training → Backtesting → Parallel validation

---

## Discussion Topics for Next Session

You mentioned these should be discussed in detail. Ready to dive into:

1. **Feature Selection Details**: Which features did the EDA identify as redundant? What's the target reduction %?
2. **M01 Rules Design**: What entry/exit thresholds look most promising? How to handle position sizing?
3. **Backtesting Constraints**: Any transaction costs, slippage assumptions, or market hours restrictions?

Shall we start with feature selection first?
