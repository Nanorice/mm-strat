# Y_Max Implementation Plan

## Problem Statement

Current M01 model is trained on `return_pct` (actual exit returns), but EDA reveals **exits are too late**, leaving significant profit on the table (high "regret").

**Key Finding:** MFE (Maximum Favorable Excursion) = `y_max` = max achievable return before our exit.

## Analysis Results (from Comprehensive_Model_EDA.ipynb Section 1.4)

### What is MFE/y_max?
- **MFE** = Maximum Favorable Excursion = highest intraday High during trade
- **y_max** = `((highest_high - entry_price) / entry_price) * 100`
- This represents the **best possible exit** if we sold at the peak

### Why This Matters
- **Regret** = `y_max - return_pct` (profit left on table)
- High regret indicates poor exit timing
- M01 predicting `return_pct` trains on **late exits**, not **potential**

## Proposed Solutions

### Option A: Replace y with y_max (SIMPLER)
**Change:** Train M01 to predict `y_max` instead of `return_pct`

**Pros:**
- Single model, simple change
- M01 learns to predict **potential returns** (best-case scenario)
- Directly addresses exit timing problem

**Cons:**
- Loses information about realistic exits
- Predictions may be too optimistic (predicting peaks)
- Backtesting becomes harder (need separate exit strategy)
- M01 no longer predicts what we actually make, but what we *could* make

**Use Case:** When you want M01 to be a "max potential" screener, and rely entirely on M01_3BAR + exit strategy for timing.

---

### Option B: Dual Labels - Add y_max as Feature (RECOMMENDED)
**Change:** Keep M01 on `return_pct`, add `y_max` as enrichment for M01_3BAR

**Approach:**
1. M01 still predicts `return_pct` (realistic returns)
2. Enrich D2 with `y_max`, `regret`, `exit_efficiency` columns
3. M01_3BAR uses these as features to identify "igniters" (low regret) vs "drifters" (high regret)

**Pros:**
- M01 predictions remain realistic and backtest-friendly
- M01_3BAR learns to detect trades that capture max potential quickly
- Better separation: M01 = direction/magnitude, M01_3BAR = speed/timing
- Can still analyze regret for continuous improvement

**Cons:**
- More complex pipeline
- Requires D2 regeneration with new columns

**Use Case:** Production-ready. M01 predicts realistic returns, M01_3BAR filters for fast movers.

---

## Implementation Steps (Option B - Recommended)

### Step 1: Add y_max Calculation to Dataset Rehydrator

**File:** `src/dataset_rehydrator.py`

Add this function:

```python
def add_y_max_columns(d2_rehydrated: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich d2_rehydrated with y_max (MFE), regret, and exit efficiency.

    Args:
        d2_rehydrated: Rehydrated dataset with intraday trajectories

    Returns:
        d2_rehydrated with added columns:
        - y_max: Max achievable return (highest High %)
        - regret: y_max - return_pct (profit left on table)
        - exit_efficiency: return_pct / y_max * 100 (% of potential captured)
    """
    results = []

    for trade_id, group in d2_rehydrated.groupby('trade_id'):
        # Entry price from day_in_trade = 0
        entry_rows = group[group['day_in_trade'] == 0]
        if len(entry_rows) == 0:
            continue

        entry_price = entry_rows['Close'].iloc[0]

        # y_max = MFE (highest intraday High)
        highest = group['High'].max()
        y_max = ((highest - entry_price) / entry_price) * 100

        # Actual exit return
        exit_rows = group[group['is_exit_day']]
        if len(exit_rows) == 0:
            continue

        y_actual = exit_rows['return_pct'].iloc[0]

        # Derived metrics
        regret = y_max - y_actual
        exit_efficiency = (y_actual / y_max * 100) if y_max > 0 else 0

        results.append({
            'trade_id': trade_id,
            'y_max': y_max,
            'regret': regret,
            'exit_efficiency': exit_efficiency
        })

    enrichment_df = pd.DataFrame(results)
    d2_rehydrated = d2_rehydrated.merge(enrichment_df, on='trade_id', how='left')

    return d2_rehydrated
```

**Integration Point:** Call this function at the end of `DatasetRehydrator.rehydrate_trades()`:

```python
# In src/dataset_rehydrator.py, class DatasetRehydrator, method rehydrate_trades()
# After all features are computed:
d2_rehydrated = add_y_max_columns(d2_rehydrated)
```

---

### Step 2: Update Feature Config (Optional for M01_3BAR)

**File:** `src/feature_config.py`

Add y_max features to M01_3BAR_V2 or create V3:

```python
M01_3BAR_FEATURES_V3 = M01_3BAR_FEATURES_V2 + [
    'y_max',           # Max achievable return
    'regret',          # Profit left on table
    'exit_efficiency'  # % of max potential captured
]
```

**Note:** This is optional. These features are already calculated per-trade in d2_rehydrated, but may not be useful as **entry-day** features for prediction (they're outcomes, not predictors).

**Alternative Use:** Use `y_max` and `regret` for **post-hoc analysis** and **model evaluation**, not as training features.

---

### Step 3: Regenerate Datasets

```bash
# Activate environment
C:/Users/Hang/PycharmProjects/quantamental/.venv/Scripts/Activate.ps1

# Regenerate D2 with y_max columns
python model_trainer.py --steps d2rh --horizon 120

# Check new columns exist
python -c "import pandas as pd; df = pd.read_parquet('data/ml/d2_rehydrated.parquet'); print('Columns:', [c for c in df.columns if 'y_' in c or 'regret' in c or 'efficiency' in c])"

# Regenerate D3 (triple barrier labels)
python model_trainer.py --steps d3 --horizon 120
```

---

### Step 4: Retrain M01 (if using Option A)

**Only if you chose Option A (training M01 on y_max instead of return_pct):**

Modify `model_trainer.py` to use `y_max` as label:

```python
# In train_fixed_horizon_model() or wherever M01 training happens
# Change:
y_train = train_data['return_pct']
# To:
y_train = train_data['y_max']  # Predict max potential return
```

**Recommendation:** Don't do this unless you fully understand the implications. Keep M01 on `return_pct` for realistic predictions.

---

### Step 5: Analyze y_max in EDA Notebook

Run [Comprehensive_Model_EDA.ipynb](../notebooks/Comprehensive_Model_EDA.ipynb) Section 1.4:

- Calculate y_max, regret, exit_efficiency for all trades
- Visualize y_max vs y_actual scatter plot
- Analyze regret distribution
- Identify trades with high regret (candidates for better exit strategies)

Expected insights:
- Median regret (profit left on table)
- Exit efficiency % (how much of max potential we captured)
- Correlation between y_max and y_actual

---

## Expected Impact

### With Option B (Recommended):
1. **M01 Remains Unchanged**: Still predicts realistic `return_pct`
2. **M01_3BAR Benefits from Regret Analysis**: Can analyze which entry conditions lead to low vs high regret
3. **Post-Hoc Analysis**: Use `y_max` to evaluate exit quality and refine exit strategies
4. **No Overfitting Risk**: Not training on future information (y_max is calculated from same horizon as return_pct)

### Success Criteria:
- D2 rehydrated contains `y_max`, `regret`, `exit_efficiency` columns
- EDA notebook shows regret distribution and exit efficiency
- Can analyze "why did we exit too late?" by comparing high-regret vs low-regret trades

---

## Alternative Consideration: Is y_max Even Valid?

### Critical Question: Look-Ahead Bias?

**Concern:** Does using `y_max` (highest high during 120-day horizon) introduce look-ahead bias?

**Answer:**
- **For training M01 to predict y_max:** YES, this is valid because:
  - We're predicting a **fixed-horizon outcome** (what happens in next 120 days)
  - y_max and return_pct are calculated from the same time window
  - No future information leakage (entry day features predict 120-day outcome)

- **For M01_3BAR velocity features:** NO ISSUE
  - M01_3BAR doesn't use y_max as a feature (it's an outcome)
  - Features are all calculated at entry day (t=0)
  - y_max is used for **evaluation**, not prediction

**Conclusion:** y_max is a valid alternative label for M01, equivalent to return_pct but measuring "best possible" instead of "actual."

---

## Recommendation

**Use Option B:**
1. Keep M01 predicting `return_pct` (realistic returns)
2. Enrich D2 with `y_max`, `regret`, `exit_efficiency` for analysis
3. Use these metrics to:
   - Evaluate exit quality
   - Identify patterns in high-regret trades
   - Inform future exit strategy improvements (e.g., trailing stops, time-based exits)

**Do NOT train M01 on y_max** unless you want to change its purpose from "realistic return predictor" to "max potential screener."

---

## Next Actions

1. ✅ Run [Comprehensive_Model_EDA.ipynb](../notebooks/Comprehensive_Model_EDA.ipynb) Section 1.4 to validate y_max calculations
2. ⬜ Implement `add_y_max_columns()` in `src/dataset_rehydrator.py`
3. ⬜ Regenerate D2 with y_max columns: `python model_trainer.py --steps d2rh --horizon 120`
4. ⬜ Validate new columns exist in `data/ml/d2_rehydrated.parquet`
5. ⬜ Analyze regret patterns in EDA notebook
6. ⬜ Decide if y_max should influence M01_3BAR feature engineering (probably not needed)

---

**Author:** Claude Code
**Date:** 2026-01-23
**Status:** Implementation Ready
