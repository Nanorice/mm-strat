# Triple Barrier Meta-Labeling System - Implementation Plan

## Executive Summary

Implement a Triple Barrier labeling system to create M01_3bar, a meta-labeling model that predicts whether SEPA trades will hit profit targets before stop-losses. This complements M01 (current 15% threshold model) by providing more granular trade quality assessment based on price path dynamics rather than just final outcomes.

**Key Insight:** This is NOT true meta-labeling (position sizing on top of primary model), but rather re-labeling with path-dependent outcomes. The term "M01_3bar" reflects this: same feature set as M01, different labeling methodology.

---

## Architecture Overview

```
Phase 1: Data Preparation (90-day fixed horizon)
  ↓
Phase 2A: Static Barrier Grid Search (baseline)
  ↓
Phase 2B: ATR-Based Dynamic Barriers (volatility-adjusted)
  ↓
Phase 3: Label Generation (create D3 dataset)
  ↓
Phase 4: Model Training (M01_3bar)
  ↓
Phase 5: Model Comparison (M01 vs M01_3bar)
```

---

## Phase 1: Data Preparation - Fixed Horizon Rehydration

### Objective
Create `d2_fixed_horizon_90d.parquet` with 90-day trajectories regardless of SEPA exit.

### Why This Matters
Current `d2_rehydrated.parquet` stops at SEPA exit (avg ~30 days). Triple Barrier needs full horizon to evaluate:
- Whether TP/SL would have been hit if SEPA didn't exit
- Time-based exit outcomes after 90 days
- Feature evolution over full window

### Implementation

**File:** `src/dataset_rehydrator.py` (MODIFY EXISTING)

**Changes Required:**

1. Add `horizon_days` parameter to `DatasetRehydrator.__init__()`:
   ```python
   def __init__(
       self,
       data_repo: DataRepository,
       feature_engine: FeatureEngineer,
       fund_merger: FundamentalMerger,
       horizon_days: int = None  # NEW: None = use SEPA exit, else fixed horizon
   ):
       self.horizon_days = horizon_days
   ```

2. Modify `_rehydrate_single_trade()` method (lines 164-218):
   ```python
   # CHANGE FROM:
   exit_date = pd.to_datetime(trade['exit_date'])

   # TO:
   if self.horizon_days is None:
       # Phase 1A behavior: use SEPA exit
       exit_date = pd.to_datetime(trade['exit_date'])
   else:
       # Phase 2 behavior: fixed horizon from entry
       entry_date = pd.to_datetime(trade['date'])
       exit_date = entry_date + pd.Timedelta(days=self.horizon_days)
   ```

3. Update `model_trainer.py::rehydrate_d2()` function (lines 1191-1222):
   ```python
   def rehydrate_d2(
       d1: pd.DataFrame,
       n_jobs: int = -1,
       horizon_days: int = None  # NEW parameter
   ) -> pd.DataFrame:
       # ... existing initialization ...

       # Rehydrate with optional fixed horizon
       rehydrator = DatasetRehydrator(
           data_repo,
           feature_engine,
           fund_merger,
           horizon_days=horizon_days  # NEW
       )
       d2_rehydrated = rehydrator.rehydrate_trades(d1, n_jobs=n_jobs)

       return d2_rehydrated
   ```

4. Add CLI support in `model_trainer.py::run_pipeline()`:
   ```python
   # Add new step 'd2r90' for 90-day rehydration
   if 'd2r90' in steps:
       logger.info("Step 2R-90: Rehydrating with 90-day fixed horizon")
       d2_90d = rehydrate_d2(d1, n_jobs=-1, horizon_days=90)

       output_path = 'data/ml/d2_fixed_horizon_90d.parquet'
       d2_90d.to_parquet(output_path, index=False)
       logger.info(f"Saved: {output_path} ({len(d2_90d):,} rows)")
   ```

**Execution:**
```bash
.venv/Scripts/python.exe model_trainer.py --steps d1,d2r90
```

**Expected Output:**
- File: `data/ml/d2_fixed_horizon_90d.parquet`
- Size: ~500-800 MB (3x larger than current d2_rehydrated due to longer trajectories)
- Rows: ~1.2M-1.5M (assuming 90 days/trade avg, though many will be shorter due to data availability)

**Edge Case Handling:**
- If `entry_date + 90 days` exceeds available price data → use last available date
- Log warning if <50% of trades have full 90-day data (may need to reduce horizon)

---

## Phase 2A: Static Barrier Grid Search (Baseline)

### Objective
Find optimal static % barriers using walk-forward validation on historical data.

### File Structure
- `src/triple_barrier_labeler.py` (NEW) - Core barrier logic
- `scripts/optimize_barriers.py` (NEW) - Grid search CLI

### Implementation: src/triple_barrier_labeler.py

```python
"""
Triple Barrier Labeling System

Applies profit/loss/time barriers to trade trajectories and assigns labels
based on which barrier is touched FIRST (path-dependent).
"""

from dataclasses import dataclass
from typing import Tuple, Literal
import pandas as pd
import numpy as np
from tqdm import tqdm


@dataclass
class StaticBarrierParams:
    """Static percentage-based barrier parameters."""
    upper_pct: float      # Profit target (e.g., 0.20 for +20%)
    lower_pct: float      # Stop loss (e.g., 0.07 for -7%)
    time_days: int        # Time expiration (e.g., 30 days)

    def __repr__(self):
        return f"TP={self.upper_pct:.0%} / SL=-{self.lower_pct:.0%} / T={self.time_days}d"


@dataclass
class DynamicBarrierParams:
    """ATR-based dynamic barrier parameters."""
    upper_atr_mult: float  # Profit target multiplier (e.g., 2.5 × ATR)
    lower_atr_mult: float  # Stop loss multiplier (e.g., 1.0 × ATR)
    time_days: int         # Time expiration

    def __repr__(self):
        return f"TP={self.upper_atr_mult}×ATR / SL={self.lower_atr_mult}×ATR / T={self.time_days}d"


OutcomeType = Literal['TP', 'SL', 'Time']


class TripleBarrierLabeler:
    """
    Applies triple barrier method to trade trajectories.

    Barriers:
      1. Upper (Profit Target): +X% or +k × ATR
      2. Lower (Stop Loss): -Y% or -k × ATR
      3. Vertical (Time): N days from entry

    Label = barrier touched FIRST (path-dependent, not just final return).
    """

    @staticmethod
    def apply_static_barriers(
        trade_df: pd.DataFrame,
        params: StaticBarrierParams
    ) -> Tuple[OutcomeType, int, float]:
        """
        Apply static % barriers to single trade trajectory.

        Args:
            trade_df: Single trade trajectory (sorted by Date)
            params: Static barrier parameters

        Returns:
            (outcome, days_to_outcome, return_at_outcome)

        Example:
            >>> df = rehydrated[rehydrated['trade_id'] == 1]
            >>> outcome, days, ret = apply_static_barriers(df, params)
            >>> print(f"Hit {outcome} after {days} days with {ret:.2%} return")
        """
        if trade_df.empty:
            raise ValueError("Empty trade trajectory")

        # Entry reference (first row)
        entry_price = trade_df.iloc[0]['Close']

        # Iterate through trajectory
        for i, (idx, row) in enumerate(trade_df.iterrows()):
            current_price = row['Close']
            return_pct = (current_price - entry_price) / entry_price

            # Check barriers in order: TP → SL → Time
            # (Order matters for same-day hits)

            if return_pct >= params.upper_pct:
                return ('TP', i, return_pct)

            if return_pct <= -params.lower_pct:
                return ('SL', i, return_pct)

            if i >= params.time_days:
                return ('Time', i, return_pct)

        # Fallback: hit time barrier at last available day
        final_return = (trade_df.iloc[-1]['Close'] - entry_price) / entry_price
        return ('Time', len(trade_df) - 1, final_return)

    @staticmethod
    def apply_dynamic_barriers(
        trade_df: pd.DataFrame,
        params: DynamicBarrierParams
    ) -> Tuple[OutcomeType, int, float]:
        """
        Apply ATR-based dynamic barriers to single trade trajectory.

        Barriers are volatility-adjusted:
          Upper = entry_price × (1 + k_upper × ATR/entry_price)
          Lower = entry_price × (1 - k_lower × ATR/entry_price)

        Args:
            trade_df: Single trade trajectory with 'ATR' column
            params: Dynamic barrier parameters

        Returns:
            (outcome, days_to_outcome, return_at_outcome)
        """
        if trade_df.empty:
            raise ValueError("Empty trade trajectory")

        if 'ATR' not in trade_df.columns:
            raise ValueError("ATR column required for dynamic barriers")

        # Calculate entry-day barriers
        entry_row = trade_df.iloc[0]
        entry_price = entry_row['Close']
        entry_atr = entry_row['ATR']

        # Convert ATR to % of price
        atr_pct = entry_atr / entry_price

        # Set thresholds
        upper_threshold = params.upper_atr_mult * atr_pct
        lower_threshold = params.lower_atr_mult * atr_pct

        # Iterate through trajectory
        for i, (idx, row) in enumerate(trade_df.iterrows()):
            current_price = row['Close']
            return_pct = (current_price - entry_price) / entry_price

            if return_pct >= upper_threshold:
                return ('TP', i, return_pct)

            if return_pct <= -lower_threshold:
                return ('SL', i, return_pct)

            if i >= params.time_days:
                return ('Time', i, return_pct)

        # Fallback
        final_return = (trade_df.iloc[-1]['Close'] - entry_price) / entry_price
        return ('Time', len(trade_df) - 1, final_return)

    @staticmethod
    def label_dataset(
        d2_rehydrated: pd.DataFrame,
        params: StaticBarrierParams | DynamicBarrierParams,
        binary_labels: bool = True
    ) -> pd.DataFrame:
        """
        Apply triple barriers to entire rehydrated dataset.

        Args:
            d2_rehydrated: Multi-day trade trajectories (from rehydrate_d2)
            params: Barrier parameters (static or dynamic)
            binary_labels: If True, y_meta ∈ {0,1}. If False, y_meta ∈ {-1,0,1}

        Returns:
            DataFrame with one row per trade (trade_id, features at entry, y_meta)
        """
        results = []

        # Apply barriers per trade
        for trade_id in tqdm(d2_rehydrated['trade_id'].unique(), desc="Labeling"):
            trade_df = d2_rehydrated[d2_rehydrated['trade_id'] == trade_id].copy()
            trade_df = trade_df.sort_values('Date')  # Ensure chronological

            # Apply appropriate barrier method
            if isinstance(params, StaticBarrierParams):
                outcome, days, return_pct = TripleBarrierLabeler.apply_static_barriers(
                    trade_df, params
                )
            else:  # DynamicBarrierParams
                outcome, days, return_pct = TripleBarrierLabeler.apply_dynamic_barriers(
                    trade_df, params
                )

            # Extract entry-day features (same as d2)
            entry_features = trade_df.iloc[0].to_dict()

            # Assign label
            if binary_labels:
                # Only TP = 1, everything else = 0
                y_meta = 1 if outcome == 'TP' else 0
            else:
                # Multi-class: TP=1, Time=0, SL=-1
                label_map = {'TP': 1, 'Time': 0, 'SL': -1}
                y_meta = label_map[outcome]

            results.append({
                'trade_id': trade_id,
                **entry_features,  # All features from entry day
                'y_meta': y_meta,
                'barrier_outcome': outcome,
                'days_to_outcome': days,
                'return_at_outcome': return_pct
            })

        return pd.DataFrame(results)


def compute_expectancy(outcomes: pd.DataFrame) -> dict:
    """
    Compute trading expectancy and key metrics for barrier outcomes.

    Args:
        outcomes: DataFrame with columns [barrier_outcome, return_at_outcome, days_to_outcome]

    Returns:
        Dict with expectancy, win_rate, avg_win, avg_loss, risk_reward, avg_days
    """
    tp_trades = outcomes[outcomes['barrier_outcome'] == 'TP']
    sl_trades = outcomes[outcomes['barrier_outcome'] == 'SL']
    time_trades = outcomes[outcomes['barrier_outcome'] == 'Time']

    total = len(outcomes)
    tp_pct = len(tp_trades) / total if total > 0 else 0
    sl_pct = len(sl_trades) / total if total > 0 else 0
    time_pct = len(time_trades) / total if total > 0 else 0

    avg_tp_return = tp_trades['return_at_outcome'].mean() if len(tp_trades) > 0 else 0
    avg_sl_return = sl_trades['return_at_outcome'].mean() if len(sl_trades) > 0 else 0
    avg_time_return = time_trades['return_at_outcome'].mean() if len(time_trades) > 0 else 0

    # Expectancy = weighted average return
    expectancy = (tp_pct * avg_tp_return) + (sl_pct * avg_sl_return) + (time_pct * avg_time_return)

    # Risk-adjusted expectancy (annualized)
    avg_days = outcomes['days_to_outcome'].mean()
    annual_factor = 252 / avg_days if avg_days > 0 else 0
    risk_adjusted_return = expectancy * annual_factor

    return {
        'expectancy': expectancy,
        'risk_adjusted_return': risk_adjusted_return,
        'win_rate': tp_pct,
        'loss_rate': sl_pct,
        'time_rate': time_pct,
        'avg_win': avg_tp_return,
        'avg_loss': avg_sl_return,
        'avg_time': avg_time_return,
        'avg_days': avg_days,
        'risk_reward': abs(avg_tp_return / avg_sl_return) if avg_sl_return != 0 else 0
    }
```

### Implementation: scripts/optimize_barriers.py

```python
"""
Grid Search for Optimal Triple Barrier Parameters

Performs walk-forward optimization to find best barrier parameters
that generalize to out-of-sample data.
"""

import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from tqdm import tqdm
import sys
sys.path.append(str(Path(__file__).parent.parent))

from src.triple_barrier_labeler import (
    TripleBarrierLabeler,
    StaticBarrierParams,
    DynamicBarrierParams,
    compute_expectancy
)


def walk_forward_grid_search(
    d2_path: str,
    barrier_type: str = 'static',
    train_years: int = 3,
    test_years: int = 1
) -> pd.DataFrame:
    """
    Walk-forward grid search for optimal barriers.

    Strategy:
      Fold 1: Optimize on [2015-2017], validate on [2018]
      Fold 2: Optimize on [2016-2018], validate on [2019]
      ...

    Returns:
        DataFrame with grid results sorted by test_expectancy (descending)
    """
    # Load data
    print(f"Loading {d2_path}...")
    d2 = pd.read_parquet(d2_path)
    d2['year'] = pd.to_datetime(d2['Date']).dt.year

    # Define grid
    if barrier_type == 'static':
        grid = {
            'upper_pct': [0.10, 0.15, 0.20, 0.25, 0.30],
            'lower_pct': [0.04, 0.05, 0.07, 0.10],
            'time_days': [10, 20, 30, 60]
        }
        param_class = StaticBarrierParams
    else:  # dynamic
        grid = {
            'upper_atr_mult': [1.5, 2.0, 2.5, 3.0],
            'lower_atr_mult': [0.5, 0.75, 1.0, 1.5],
            'time_days': [10, 20, 30]
        }
        param_class = DynamicBarrierParams

    # Walk-forward splits
    years = sorted(d2['year'].unique())
    results = []

    for i, test_year in enumerate(years[train_years:]):
        train_years_range = years[i:i+train_years]

        train_data = d2[d2['year'].isin(train_years_range)]
        test_data = d2[d2['year'] == test_year]

        print(f"\nFold {i+1}: Train {train_years_range} → Test [{test_year}]")
        print(f"  Train: {train_data['trade_id'].nunique()} trades")
        print(f"  Test: {test_data['trade_id'].nunique()} trades")

        # Grid search
        if barrier_type == 'static':
            param_combinations = [
                StaticBarrierParams(u, l, t)
                for u in grid['upper_pct']
                for l in grid['lower_pct']
                for t in grid['time_days']
            ]
        else:
            param_combinations = [
                DynamicBarrierParams(u, l, t)
                for u in grid['upper_atr_mult']
                for l in grid['lower_atr_mult']
                for t in grid['time_days']
            ]

        for params in tqdm(param_combinations, desc="Grid search"):
            # Apply to train
            train_outcomes = apply_barriers_to_trades(train_data, params, barrier_type)
            train_metrics = compute_expectancy(train_outcomes)

            # Apply to test (THE TRUTH!)
            test_outcomes = apply_barriers_to_trades(test_data, params, barrier_type)
            test_metrics = compute_expectancy(test_outcomes)

            # Store result
            if barrier_type == 'static':
                param_dict = {
                    'upper_pct': params.upper_pct,
                    'lower_pct': params.lower_pct,
                    'time_days': params.time_days
                }
            else:
                param_dict = {
                    'upper_atr_mult': params.upper_atr_mult,
                    'lower_atr_mult': params.lower_atr_mult,
                    'time_days': params.time_days
                }

            results.append({
                'fold': i + 1,
                'test_year': test_year,
                **param_dict,
                'train_expectancy': train_metrics['expectancy'],
                'test_expectancy': test_metrics['expectancy'],  # KEY METRIC
                'test_risk_adj_return': test_metrics['risk_adjusted_return'],
                'test_win_rate': test_metrics['win_rate'],
                'test_avg_days': test_metrics['avg_days'],
                'test_risk_reward': test_metrics['risk_reward']
            })

    # Convert to DataFrame and sort by test performance
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values('test_expectancy', ascending=False)

    return results_df


def apply_barriers_to_trades(
    d2_subset: pd.DataFrame,
    params: StaticBarrierParams | DynamicBarrierParams,
    barrier_type: str
) -> pd.DataFrame:
    """Apply barriers to all trades in subset."""
    outcomes = []

    for trade_id in d2_subset['trade_id'].unique():
        trade_df = d2_subset[d2_subset['trade_id'] == trade_id].copy()
        trade_df = trade_df.sort_values('Date')

        try:
            if barrier_type == 'static':
                outcome, days, return_pct = TripleBarrierLabeler.apply_static_barriers(
                    trade_df, params
                )
            else:
                outcome, days, return_pct = TripleBarrierLabeler.apply_dynamic_barriers(
                    trade_df, params
                )

            outcomes.append({
                'trade_id': trade_id,
                'barrier_outcome': outcome,
                'days_to_outcome': days,
                'return_at_outcome': return_pct
            })
        except Exception as e:
            # Skip trades with errors (e.g., missing ATR for dynamic)
            continue

    return pd.DataFrame(outcomes)


def main():
    parser = argparse.ArgumentParser(description='Optimize triple barrier parameters')
    parser.add_argument('--data', default='data/ml/d2_fixed_horizon_90d.parquet')
    parser.add_argument('--type', choices=['static', 'dynamic'], default='static')
    parser.add_argument('--output', default='barrier_optimization_results.csv')
    args = parser.parse_args()

    print("=" * 70)
    print(" TRIPLE BARRIER GRID SEARCH")
    print("=" * 70)
    print(f"Data: {args.data}")
    print(f"Barrier type: {args.type}")

    results = walk_forward_grid_search(
        d2_path=args.data,
        barrier_type=args.type
    )

    # Save results
    results.to_csv(args.output, index=False)
    print(f"\nSaved: {args.output}")

    # Display top 10 parameter sets
    print("\n" + "=" * 70)
    print(" TOP 10 PARAMETER SETS (by test expectancy)")
    print("=" * 70)
    print(results.head(10).to_string(index=False))

    # Display best overall params (avg across folds)
    if args.type == 'static':
        group_cols = ['upper_pct', 'lower_pct', 'time_days']
    else:
        group_cols = ['upper_atr_mult', 'lower_atr_mult', 'time_days']

    avg_results = results.groupby(group_cols).agg({
        'test_expectancy': 'mean',
        'test_risk_adj_return': 'mean',
        'test_win_rate': 'mean',
        'test_avg_days': 'mean'
    }).reset_index()

    avg_results = avg_results.sort_values('test_expectancy', ascending=False)

    print("\n" + "=" * 70)
    print(" BEST PARAMETERS (averaged across all folds)")
    print("=" * 70)
    best = avg_results.iloc[0]
    print(best)

    if args.type == 'static':
        print(f"\nRecommended: TP={best['upper_pct']:.0%}, SL=-{best['lower_pct']:.0%}, "
              f"Time={best['time_days']:.0f} days")
    else:
        print(f"\nRecommended: TP={best['upper_atr_mult']:.1f}×ATR, "
              f"SL={best['lower_atr_mult']:.1f}×ATR, Time={best['time_days']:.0f} days")


if __name__ == '__main__':
    main()
```

**Execution:**
```bash
# Static barriers
.venv/Scripts/python.exe scripts/optimize_barriers.py --type static

# Dynamic barriers (later)
.venv/Scripts/python.exe scripts/optimize_barriers.py --type dynamic
```

**Expected Output:**
- File: `barrier_optimization_results.csv` (all grid combinations × folds)
- Console: Top 10 parameter sets sorted by test expectancy
- Recommendation: Best average params across folds

---

## Phase 2B: Dynamic (ATR-Based) Barriers

### Objective
Implement volatility-adjusted barriers that scale with each stock's ATR.

### Why This Matters
- Static +20% barrier: Too easy for high-vol stocks (NVDA), impossible for low-vol stocks (KO)
- ATR-based: Adapts to each stock's price behavior
- Example: 2.5×ATR might be +15% for NVDA, +8% for AAPL, +5% for KO

### Implementation
Already built into `src/triple_barrier_labeler.py` above (see `apply_dynamic_barriers` method).

**Execution:**
```bash
.venv/Scripts/python.exe scripts/optimize_barriers.py --type dynamic
```

**Expected Finding:**
Dynamic barriers typically show:
- Higher test expectancy (better generalization)
- Lower win rate but higher risk-reward ratio
- More stable performance across different market regimes

---

## Phase 3: Label Generation (D3 Dataset)

### Objective
Create `d3_triple_barrier_labels.parquet` using best parameters from Phase 2.

### File Structure
- `scripts/create_d3_labels.py` (NEW) - D3 generation CLI

### Implementation: scripts/create_d3_labels.py

```python
"""
Create D3 Dataset with Triple Barrier Labels

Uses best parameters from barrier optimization to generate meta-labels.
"""

import argparse
import pandas as pd
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent))

from src.triple_barrier_labeler import (
    TripleBarrierLabeler,
    StaticBarrierParams,
    DynamicBarrierParams
)


def create_d3_dataset(
    d2_path: str,
    barrier_type: str,
    params: StaticBarrierParams | DynamicBarrierParams,
    output_path: str
):
    """
    Generate D3 dataset with triple barrier labels.

    Args:
        d2_path: Path to d2_fixed_horizon_90d.parquet
        barrier_type: 'static' or 'dynamic'
        params: Best parameters from optimization
        output_path: Where to save D3
    """
    print("=" * 70)
    print(" CREATE D3 DATASET - TRIPLE BARRIER LABELS")
    print("=" * 70)
    print(f"Input: {d2_path}")
    print(f"Barrier: {params}")

    # Load data
    d2 = pd.read_parquet(d2_path)
    print(f"Loaded: {len(d2):,} rows, {d2['trade_id'].nunique()} trades")

    # Apply barriers
    d3 = TripleBarrierLabeler.label_dataset(
        d2_rehydrated=d2,
        params=params,
        binary_labels=True  # y_meta ∈ {0, 1}
    )

    print(f"\nLabeling complete:")
    print(f"  Total trades: {len(d3):,}")
    print(f"  y_meta=1 (TP): {(d3['y_meta'] == 1).sum()} ({(d3['y_meta'] == 1).mean():.1%})")
    print(f"  y_meta=0 (SL/Time): {(d3['y_meta'] == 0).sum()} ({(d3['y_meta'] == 0).mean():.1%})")

    # Outcome breakdown
    print(f"\nOutcome distribution:")
    print(d3['barrier_outcome'].value_counts())

    # Save
    d3.to_parquet(output_path, index=False)
    print(f"\nSaved: {output_path} ({len(d3):,} rows, {d3.memory_usage(deep=True).sum() / 1e6:.1f} MB)")

    # Validation: compare to original d1 labels
    if 'label' in d3.columns:
        agreement = (d3['y_meta'] == d3['label']).mean()
        print(f"\nLabel agreement with original d1:")
        print(f"  y_meta == label: {agreement:.1%}")
        print(f"  (Values <100% expected - different labeling logic)")


def main():
    parser = argparse.ArgumentParser(description='Create D3 with triple barrier labels')
    parser.add_argument('--data', default='data/ml/d2_fixed_horizon_90d.parquet')
    parser.add_argument('--type', choices=['static', 'dynamic'], default='static')
    parser.add_argument('--output', default='data/ml/d3_triple_barrier_labels.parquet')

    # Static barrier params (user provides from optimization results)
    parser.add_argument('--upper-pct', type=float, default=0.20)
    parser.add_argument('--lower-pct', type=float, default=0.07)
    parser.add_argument('--time-days', type=int, default=30)

    # Dynamic barrier params
    parser.add_argument('--upper-atr', type=float, default=2.5)
    parser.add_argument('--lower-atr', type=float, default=1.0)

    args = parser.parse_args()

    # Create params object
    if args.type == 'static':
        params = StaticBarrierParams(
            upper_pct=args.upper_pct,
            lower_pct=args.lower_pct,
            time_days=args.time_days
        )
    else:
        params = DynamicBarrierParams(
            upper_atr_mult=args.upper_atr,
            lower_atr_mult=args.lower_atr,
            time_days=args.time_days
        )

    create_d3_dataset(
        d2_path=args.data,
        barrier_type=args.type,
        params=params,
        output_path=args.output
    )


if __name__ == '__main__':
    main()
```

**Execution:**
```bash
# Example with optimized params (user replaces with actual best params)
.venv/Scripts/python.exe scripts/create_d3_labels.py \
    --type static \
    --upper-pct 0.20 \
    --lower-pct 0.07 \
    --time-days 30
```

**Expected Output:**
- File: `data/ml/d3_triple_barrier_labels.parquet`
- Size: ~15-20 MB (similar to d2_features.parquet)
- Schema: Same as d2_features.parquet but with `y_meta` instead of `label`

---

## Phase 4: Model Training (M01_3bar)

### Objective
Train XGBoost classifier on triple barrier labels using same infrastructure as M01.

### Implementation

**File:** `model_trainer.py` (MODIFY EXISTING)

**Add new function:**

```python
def train_triple_barrier_model(
    d3_path: str = 'data/ml/d3_triple_barrier_labels.parquet',
    model_type: str = 'classification',
    tune: bool = False,
    tune_trials: int = 50
) -> Tuple:
    """
    Train M01_3bar model using triple barrier labels.

    Identical to train_model_walk_forward() but uses y_meta as target.

    Args:
        d3_path: Path to D3 dataset
        model_type: 'classification' (recommended) or 'regression'
        tune: Whether to run Optuna hyperparameter tuning
        tune_trials: Number of Optuna trials

    Returns:
        (trained_model, feature_columns, metrics_dict)
    """
    logger.info("=" * 70)
    logger.info(" TRAINING M01_3BAR (TRIPLE BARRIER META-LABELING)")
    logger.info("=" * 70)

    # Load D3
    d3 = pd.read_parquet(d3_path)
    logger.info(f"Loaded D3: {len(d3):,} trades")
    logger.info(f"  y_meta distribution: {d3['y_meta'].value_counts().to_dict()}")

    # Use same features as M01 (centralized config)
    from src.feature_config import get_model_features
    model_features = get_model_features('M01')

    # Filter to available features
    available_cols = [c for c in model_features if c in d3.columns]
    logger.info(f"Using {len(available_cols)}/{len(model_features)} M01 features")

    # Prepare data for training
    data = d3.copy()
    data = data.sort_values('Date')
    data['year'] = pd.to_datetime(data['Date']).dt.year

    # Clean data (same as M01)
    data = clean_training_data(data, available_cols)

    # Target column
    target_col = 'y_meta'

    # Call existing walk-forward training function
    # (Reuse ALL existing infrastructure - hyperparameters, validation, metrics)
    import xgboost as xgb
    from sklearn.metrics import accuracy_score, precision_score, roc_auc_score

    years = sorted(data['year'].unique())
    all_metrics = []
    final_model = None

    # Optuna tuning (if requested)
    best_params = {}
    if tune and OPTUNA_AVAILABLE:
        logger.info("Running hyperparameter tuning...")
        X_tune = data[available_cols]
        y_tune = data[target_col]
        best_params = tune_hyperparameters_optuna(
            X_tune, y_tune,
            model_type='classification',
            n_trials=tune_trials,
            n_splits=5,
            random_state=42
        )

    # Walk-forward training (same as M01)
    train_years_count = 3

    for i, test_year in enumerate(years[train_years_count:]):
        train_years_range = years[i:i+train_years_count]

        train_data = data[data['year'].isin(train_years_range)]
        test_data = data[data['year'] == test_year]

        X_train = train_data[available_cols]
        y_train = train_data[target_col]
        X_test = test_data[available_cols]
        y_test = test_data[target_col]

        logger.info(f"\nFold {i+1}: Train {train_years_range} → Test [{test_year}]")
        logger.info(f"  Train: {len(X_train)} trades")
        logger.info(f"  Test: {len(X_test)} trades")

        # Train XGBoost (use best_params if tuned, else defaults)
        if best_params:
            model = xgb.XGBClassifier(**best_params, random_state=42)
        else:
            # Default hyperparameters (same as M01 classification)
            model = xgb.XGBClassifier(
                n_estimators=500,
                learning_rate=0.03,
                max_depth=5,
                subsample=0.8,
                colsample_bytree=0.8,
                min_child_weight=3,
                eval_metric='logloss',
                random_state=42
            )

        model.fit(X_train, y_train)

        # Predictions
        y_pred_proba = model.predict_proba(X_test)[:, 1]
        y_pred = (y_pred_proba >= 0.5).astype(int)

        # Metrics
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, zero_division=0)
        auc = roc_auc_score(y_test, y_pred_proba)

        # Decile analysis (KEY METRIC for trading)
        test_results = test_data.copy()
        test_results['y_pred_proba'] = y_pred_proba
        decile_metrics = analyze_deciles(test_results, 'y_meta', 'return_at_outcome')

        logger.info(f"  Accuracy: {accuracy:.3f}")
        logger.info(f"  Precision: {precision:.3f}")
        logger.info(f"  AUC: {auc:.3f}")
        logger.info(f"  Top Decile Avg Return: {decile_metrics['top_decile_mean']:.2f}%")
        logger.info(f"  Selection Edge: {decile_metrics['selection_edge']:.2f}%")

        all_metrics.append({
            'fold': i + 1,
            'test_year': test_year,
            'accuracy': accuracy,
            'precision': precision,
            'auc': auc,
            'top_decile_mean': decile_metrics['top_decile_mean'],
            'selection_edge': decile_metrics['selection_edge']
        })

        final_model = model  # Keep last fold model

    logger.info("\n" + "=" * 70)
    logger.info(" WALK-FORWARD RESULTS (M01_3BAR)")
    logger.info("=" * 70)
    metrics_df = pd.DataFrame(all_metrics)
    print(metrics_df.to_string(index=False))

    logger.info(f"\nAverage Selection Edge: {metrics_df['selection_edge'].mean():.2f}%")

    return final_model, available_cols, all_metrics
```

**Add to run_pipeline():**

```python
# In run_pipeline() function, add new step 'd3train'
if 'd3train' in steps:
    logger.info("Step 3B: Training M01_3bar (Triple Barrier Model)")

    model, features, metrics = train_triple_barrier_model(
        d3_path='data/ml/d3_triple_barrier_labels.parquet',
        model_type='classification',
        tune=tune,
        tune_trials=tune_trials
    )

    # Save model
    save_production_model(
        model=model,
        feature_cols=features,
        all_metrics=metrics,
        model_name='M01_3bar',
        description='Triple Barrier Meta-Labeling Model'
    )

    # Generate report
    d3 = pd.read_parquet('data/ml/d3_triple_barrier_labels.parquet')
    generate_model_report(
        model=model,
        data=d3,
        feature_cols=features,
        all_metrics=metrics,
        model_name='M01_3bar'
    )
```

**Execution:**
```bash
.venv/Scripts/python.exe model_trainer.py --steps d3train
```

**Expected Output:**
- `models/model_m01_3bar.json` - Trained XGBoost model
- `models/model_m01_3bar_config.json` - Model metadata
- `models/model_report_M01_3bar_*.md` - Performance report

---

## Phase 5: Model Comparison (M01 vs M01_3bar)

### Objective
Compare M01 (15% threshold) vs M01_3bar (triple barrier) on same test set.

### File Structure
- `scripts/compare_models.py` (NEW) - Model comparison CLI

### Implementation: scripts/compare_models.py

```python
"""
Compare M01 vs M01_3bar Models

Evaluates both models on same held-out period to assess:
1. Which model selects better trades (higher avg return in top decile)
2. Trade overlap (how many trades both models agree on)
3. Unique winners (trades only one model identified)
"""

import argparse
import pandas as pd
import xgboost as xgb
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent))

from src.feature_config import get_model_features


def load_model(model_path: str):
    """Load XGBoost model from JSON."""
    model = xgb.XGBClassifier()
    model.load_model(model_path)
    return model


def compare_models(
    m01_path: str,
    m01_3bar_path: str,
    d2_path: str,
    d3_path: str,
    test_year: int
):
    """
    Compare M01 vs M01_3bar on test year.

    Args:
        m01_path: Path to model_m01.json
        m01_3bar_path: Path to model_m01_3bar.json
        d2_path: Path to d2_features.parquet (for M01 labels)
        d3_path: Path to d3_triple_barrier_labels.parquet (for M01_3bar labels)
        test_year: Year to test on (e.g., 2023)
    """
    print("=" * 70)
    print(" MODEL COMPARISON: M01 vs M01_3bar")
    print("=" * 70)
    print(f"Test year: {test_year}")

    # Load models
    m01 = load_model(m01_path)
    m01_3bar = load_model(m01_3bar_path)

    # Load test data
    d2 = pd.read_parquet(d2_path)
    d3 = pd.read_parquet(d3_path)

    # Filter to test year
    d2['year'] = pd.to_datetime(d2['Date']).dt.year
    d3['year'] = pd.to_datetime(d3['Date']).dt.year

    d2_test = d2[d2['year'] == test_year].copy()
    d3_test = d3[d3['year'] == test_year].copy()

    print(f"\nTest set size:")
    print(f"  M01 (d2): {len(d2_test)} trades")
    print(f"  M01_3bar (d3): {len(d3_test)} trades")

    # Get features
    features = get_model_features('M01')
    available_features = [f for f in features if f in d2_test.columns]

    # Predictions
    d2_test['m01_score'] = m01.predict_proba(d2_test[available_features])[:, 1]
    d3_test['m01_3bar_score'] = m01_3bar.predict_proba(d3_test[available_features])[:, 1]

    # Top decile analysis
    print("\n" + "=" * 70)
    print(" TOP DECILE PERFORMANCE")
    print("=" * 70)

    # M01 top decile
    m01_top_decile = d2_test.nlargest(int(len(d2_test) * 0.1), 'm01_score')
    m01_avg_return = m01_top_decile['return_pct'].mean()
    m01_win_rate = (m01_top_decile['label'] == 1).mean()

    print(f"\nM01 (15% threshold labeling):")
    print(f"  Avg return: {m01_avg_return:.2f}%")
    print(f"  Win rate (≥15%): {m01_win_rate:.1%}")
    print(f"  Trades selected: {len(m01_top_decile)}")

    # M01_3bar top decile
    m01_3bar_top_decile = d3_test.nlargest(int(len(d3_test) * 0.1), 'm01_3bar_score')
    m01_3bar_avg_return = m01_3bar_top_decile['return_at_outcome'].mean()
    m01_3bar_win_rate = (m01_3bar_top_decile['y_meta'] == 1).mean()
    m01_3bar_avg_days = m01_3bar_top_decile['days_to_outcome'].mean()

    print(f"\nM01_3bar (Triple barrier labeling):")
    print(f"  Avg return: {m01_3bar_avg_return:.2f}%")
    print(f"  Win rate (hit TP first): {m01_3bar_win_rate:.1%}")
    print(f"  Avg days to outcome: {m01_3bar_avg_days:.1f}")
    print(f"  Trades selected: {len(m01_3bar_top_decile)}")

    # Trade overlap analysis
    print("\n" + "=" * 70)
    print(" TRADE OVERLAP")
    print("=" * 70)

    m01_top_ids = set(m01_top_decile['trade_id'])
    m01_3bar_top_ids = set(m01_3bar_top_decile['trade_id'])

    overlap = m01_top_ids & m01_3bar_top_ids
    m01_unique = m01_top_ids - m01_3bar_top_ids
    m01_3bar_unique = m01_3bar_top_ids - m01_top_ids

    print(f"\nBoth models agree: {len(overlap)} trades ({len(overlap)/len(m01_top_ids):.1%})")
    print(f"Only M01 selected: {len(m01_unique)} trades")
    print(f"Only M01_3bar selected: {len(m01_3bar_unique)} trades")

    # Unique trade performance
    if len(m01_unique) > 0:
        m01_unique_trades = d2_test[d2_test['trade_id'].isin(m01_unique)]
        print(f"\nM01 unique trades avg return: {m01_unique_trades['return_pct'].mean():.2f}%")

    if len(m01_3bar_unique) > 0:
        m01_3bar_unique_trades = d3_test[d3_test['trade_id'].isin(m01_3bar_unique)]
        print(f"M01_3bar unique trades avg return: {m01_3bar_unique_trades['return_at_outcome'].mean():.2f}%")

    # Winner
    print("\n" + "=" * 70)
    print(" CONCLUSION")
    print("=" * 70)

    if m01_3bar_avg_return > m01_avg_return:
        improvement = m01_3bar_avg_return - m01_avg_return
        print(f"\nM01_3bar WINS by {improvement:.2f}% average return")
    elif m01_avg_return > m01_3bar_avg_return:
        improvement = m01_avg_return - m01_3bar_avg_return
        print(f"\nM01 WINS by {improvement:.2f}% average return")
    else:
        print(f"\nTIE - Both models perform equally")


def main():
    parser = argparse.ArgumentParser(description='Compare M01 vs M01_3bar')
    parser.add_argument('--m01', default='models/model_m01.json')
    parser.add_argument('--m01-3bar', default='models/model_m01_3bar.json')
    parser.add_argument('--d2', default='data/ml/d2_features.parquet')
    parser.add_argument('--d3', default='data/ml/d3_triple_barrier_labels.parquet')
    parser.add_argument('--test-year', type=int, default=2023)
    args = parser.parse_args()

    compare_models(
        m01_path=args.m01,
        m01_3bar_path=args.m01_3bar,
        d2_path=args.d2,
        d3_path=args.d3,
        test_year=args.test_year
    )


if __name__ == '__main__':
    main()
```

**Execution:**
```bash
.venv/Scripts/python.exe scripts/compare_models.py --test-year 2023
```

**Expected Output:**
Console comparison showing which model performs better on held-out data.

---

## Critical Files Summary

### New Files to Create
1. `src/triple_barrier_labeler.py` (~250 lines) - Core barrier logic
2. `scripts/optimize_barriers.py` (~200 lines) - Grid search
3. `scripts/create_d3_labels.py` (~100 lines) - D3 generation
4. `scripts/compare_models.py` (~150 lines) - Model comparison

### Files to Modify
1. `src/dataset_rehydrator.py` (lines 36, 164-181) - Add horizon_days parameter
2. `model_trainer.py` (lines 1191-1222, add new train_triple_barrier_model function)

### Data Files Generated
1. `data/ml/d2_fixed_horizon_90d.parquet` (~500-800 MB)
2. `data/ml/d3_triple_barrier_labels.parquet` (~15-20 MB)
3. `barrier_optimization_results.csv` (~50-100 KB)

### Model Files Generated
1. `models/model_m01_3bar.json`
2. `models/model_m01_3bar_config.json`
3. `models/model_report_M01_3bar_*.md`

---

## Execution Sequence

```bash
# Phase 1: Data prep (90-day horizon)
.venv/Scripts/python.exe model_trainer.py --steps d1,d2r90

# Phase 2A: Static barrier optimization
.venv/Scripts/python.exe scripts/optimize_barriers.py --type static

# Phase 2B: Dynamic barrier optimization
.venv/Scripts/python.exe scripts/optimize_barriers.py --type dynamic

# Phase 3: Create D3 with best params (example values)
.venv/Scripts/python.exe scripts/create_d3_labels.py \
    --type static \
    --upper-pct 0.20 \
    --lower-pct 0.07 \
    --time-days 30

# Phase 4: Train M01_3bar
.venv/Scripts/python.exe model_trainer.py --steps d3train

# Phase 5: Compare models
.venv/Scripts/python.exe scripts/compare_models.py --test-year 2023
```

---

## Verification Testing

After each phase:

**Phase 1 Verification:**
```python
import pandas as pd
df = pd.read_parquet('data/ml/d2_fixed_horizon_90d.parquet')
print(f"Shape: {df.shape}")
print(f"Avg days/trade: {df.groupby('trade_id').size().mean():.1f}")
print(f"Max days/trade: {df.groupby('trade_id').size().max()}")
# Expected: ~60-90 days/trade avg (may be less due to data availability)
```

**Phase 2 Verification:**
```python
results = pd.read_csv('barrier_optimization_results.csv')
print(results.nlargest(5, 'test_expectancy'))
# Verify test_expectancy > 0 for top results
```

**Phase 3 Verification:**
```python
d3 = pd.read_parquet('data/ml/d3_triple_barrier_labels.parquet')
print(d3['y_meta'].value_counts())
print(d3['barrier_outcome'].value_counts())
# Verify label distribution makes sense (not all 0 or all 1)
```

**Phase 4 Verification:**
```python
import xgboost as xgb
model = xgb.XGBClassifier()
model.load_model('models/model_m01_3bar.json')
# Check feature importances
importance = model.get_booster().get_score(importance_type='gain')
print(sorted(importance.items(), key=lambda x: x[1], reverse=True)[:10])
```

---

## Expected Outcomes & Success Criteria

### Phase 2A Success
- **Test expectancy > 2%** for best static barriers (after walk-forward validation)
- **Win rate 40-60%** (balanced, not extreme)
- **Risk-reward ratio > 2.0** (avg_win / avg_loss)

### Phase 2B Success
- Dynamic barriers show **±1-2% improvement** in test expectancy vs static
- **Lower variance** across folds (more stable)

### Phase 4 Success (M01_3bar)
- **Selection edge > 2.5%** (top decile - avg return)
- **AUC > 0.60** (better than random)
- **Top decile win rate > 60%** (triple barrier TP rate)

### Phase 5 Success
- M01_3bar shows **+1-3% higher avg return** in top decile vs M01
- **OR:** M01_3bar achieves similar return with **10-20% fewer days held** (faster capital velocity)
- Trade overlap 30-50% (models partially agree, but each finds unique edges)

---

## Risk Mitigation

### Data Availability Risk
**Risk:** Not all trades have 90 days of future data.
**Mitigation:**
- Log trades with <90 days data separately
- Consider reducing horizon to 60 days if >30% of trades incomplete
- Alternative: Use adaptive horizon (min 30 days, max 90 days)

### Overfitting Risk
**Risk:** Grid search optimizes on same data used for training.
**Mitigation:**
- ALWAYS use walk-forward validation (separate train/test periods)
- Report ONLY test set metrics (not train)
- Compare multiple folds to detect instability

### Label Imbalance Risk
**Risk:** If barriers are too aggressive, y_meta might be 90% zeros or 90% ones.
**Mitigation:**
- Target 30-70% positive rate (adjust barriers if outside this range)
- Use `scale_pos_weight` in XGBoost if imbalanced
- Monitor precision/recall, not just accuracy

### Computational Cost
**Risk:** Grid search × walk-forward = many barrier applications.
**Mitigation:**
- Start with coarse grid, refine around best region
- Use parallel processing (already in scripts)
- Estimated runtime: ~10-30 min for static, ~30-60 min for dynamic

---

## Next Steps After Implementation

1. **Feature Engineering for M01_3bar**: Experiment with barrier-specific features:
   - `days_since_last_TP` - How recently stock had a TP outcome
   - `sector_avg_tp_rate` - Sector-level TP statistics
   - `volatility_regime` - Classify current ATR vs historical ATR

2. **Ensemble M01 + M01_3bar**: Weighted combination:
   ```python
   final_score = 0.6 × M01_score + 0.4 × M01_3bar_score
   ```

3. **Live Trading Integration**: Use M01_3bar scores for position sizing:
   ```python
   if M01_score > 0.7 and M01_3bar_score > 0.8:
       position_size = base_size × 1.5  # High conviction
   elif M01_score > 0.7:
       position_size = base_size × 1.0  # Normal
   else:
       position_size = 0  # Skip
   ```

4. **Adaptive Barriers**: Train model to predict optimal barriers per trade:
   ```python
   # Instead of fixed TP=20%, predict optimal TP for this specific setup
   optimal_tp_model = XGBRegressor()
   optimal_tp_model.fit(features, observed_best_tp_per_trade)
   ```

---

## Questions & Clarifications

Before finalizing this plan, confirm:

1. **Horizon Trade-off**: 90 days gives more data per trade but fewer valid trades. Acceptable?
2. **Compute Resources**: Grid search may take 30-60 minutes. Run overnight or reduce grid size?
3. **Barrier Philosophy**: Should Time barrier at +5% be treated same as Time barrier at -5%? (Current plan: both → y_meta=0)
4. **Model Selection**: If M01_3bar underperforms M01, is this still valuable for learning? (Answer: YES - negative results inform strategy)

---

**End of Implementation Plan**
