"""
Triple Barrier Labeling System

Applies profit/loss/time barriers to trade trajectories and assigns labels
based on which barrier is touched FIRST (path-dependent).

Barrier Types:
1. Static: Fixed percentage thresholds (e.g., +20% TP, -7% SL)
2. Dynamic: ATR-based thresholds (e.g., 2.5x ATR TP, 1x ATR SL)
3. Hybrid: MAX(floor%, k×ATR) for targets + ATR-based stops (RECOMMENDED)
"""

from dataclasses import dataclass
from typing import Tuple, Literal, Union, Optional
import pandas as pd
import numpy as np
from tqdm import tqdm
from joblib import Parallel, delayed


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


@dataclass
class HybridBarrierParams:
    """
    Hybrid barrier with intelligent defaults based on Minervini methodology.
    
    Stop Loss: k_sl × ATR (volatility-adaptive, prevents noise wicks)
    Profit Target: MAX(min_tp, k_tp × ATR) (floor + volatility expansion)
    Time Barrier: Dynamic based on distance/speed logic
    
    Example:
        For a stock with 3% ATR and k_sl=1.0, k_tp=3.0, min_tp=0.20:
        - Stop = 1.0 × 3% = -3%
        - Target = MAX(20%, 3.0 × 3%) = MAX(20%, 9%) = 20%
        
        For a volatile stock with 8% ATR:
        - Stop = 1.0 × 8% = -8%
        - Target = MAX(20%, 3.0 × 8%) = MAX(20%, 24%) = 24%
    """
    k_sl: float = 1.0       # Stop loss multiplier (k_sl × ATR%)
    k_tp: float = 3.0       # Target multiplier for MAX logic
    min_tp: float = 0.20    # Minimum profit target floor (20%)
    max_time: int = 60      # Maximum time barrier cap
    min_time: int = 20      # Minimum time barrier floor

    def __repr__(self):
        return f"TP=MAX({self.min_tp:.0%}, {self.k_tp}×ATR) / SL={self.k_sl}×ATR / T=[{self.min_time}-{self.max_time}d]"


OutcomeType = Literal['TP', 'SL', 'Time']
BarrierParams = Union[StaticBarrierParams, DynamicBarrierParams, HybridBarrierParams]


class TripleBarrierLabeler:
    """
    Applies triple barrier method to trade trajectories.

    Barriers:
      1. Upper (Profit Target): +X% or MAX(floor%, k × ATR)
      2. Lower (Stop Loss): -Y% or -k × ATR
      3. Vertical (Time): N days from entry (fixed or dynamic)

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
        """
        if trade_df.empty:
            raise ValueError("Empty trade trajectory")

        entry_price = trade_df.iloc[0]['Close']

        for i, (idx, row) in enumerate(trade_df.iterrows()):
            current_price = row['Close']
            return_pct = (current_price - entry_price) / entry_price

            # Check barriers in order: TP → SL → Time
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

        entry_row = trade_df.iloc[0]
        entry_price = entry_row['Close']
        entry_atr = entry_row['ATR']

        if pd.isna(entry_atr) or entry_atr <= 0:
            raise ValueError(f"Invalid ATR value: {entry_atr}")

        # Convert ATR to % of price
        atr_pct = entry_atr / entry_price

        # Set thresholds
        upper_threshold = params.upper_atr_mult * atr_pct
        lower_threshold = params.lower_atr_mult * atr_pct

        for i, (idx, row) in enumerate(trade_df.iterrows()):
            current_price = row['Close']
            return_pct = (current_price - entry_price) / entry_price

            if return_pct >= upper_threshold:
                return ('TP', i, return_pct)

            if return_pct <= -lower_threshold:
                return ('SL', i, return_pct)

            if i >= params.time_days:
                return ('Time', i, return_pct)

        final_return = (trade_df.iloc[-1]['Close'] - entry_price) / entry_price
        return ('Time', len(trade_df) - 1, final_return)

    @staticmethod
    def apply_hybrid_barriers(
        trade_df: pd.DataFrame,
        params: HybridBarrierParams
    ) -> Tuple[OutcomeType, int, float, dict]:
        """
        Apply hybrid barriers (ATR-based stop + MAX logic for target).

        Logic:
            Stop Loss = k_sl × (ATR / entry_price)
            Profit Target = MAX(min_tp, k_tp × (ATR / entry_price))
            Time = MAX(min_time, MIN(max_time, target / avg_daily_move))

        Args:
            trade_df: Single trade trajectory with 'ATR' column
            params: Hybrid barrier parameters

        Returns:
            (outcome, days_to_outcome, return_at_outcome, barrier_details)
            
            barrier_details contains calculated thresholds for transparency:
            {
                'stop_pct': -0.03,      # Actual stop level used
                'target_pct': 0.20,     # Actual target level used
                'time_days': 25,        # Actual time barrier used
                'atr_pct': 0.03         # ATR as % of price
            }
        """
        if trade_df.empty:
            raise ValueError("Empty trade trajectory")

        if 'ATR' not in trade_df.columns:
            raise ValueError("ATR column required for hybrid barriers")

        entry_row = trade_df.iloc[0]
        entry_price = entry_row['Close']
        entry_atr = entry_row['ATR']

        if pd.isna(entry_atr) or entry_atr <= 0:
            raise ValueError(f"Invalid ATR value: {entry_atr}")

        # Convert ATR to % of price
        atr_pct = entry_atr / entry_price

        # Calculate stop loss threshold (k_sl × ATR%)
        stop_pct = params.k_sl * atr_pct

        # Calculate profit target threshold: MAX(min_tp, k_tp × ATR%)
        atr_target = params.k_tp * atr_pct
        target_pct = max(params.min_tp, atr_target)

        # Calculate dynamic time barrier: distance / speed
        # avg_daily_move ≈ ATR% (typical daily range as fraction of price)
        avg_daily_move = atr_pct
        if avg_daily_move > 0:
            raw_time = int(target_pct / avg_daily_move)
            time_days = max(params.min_time, min(params.max_time, raw_time))
        else:
            time_days = params.max_time

        # Store barrier details for transparency
        barrier_details = {
            'stop_pct': stop_pct,
            'target_pct': target_pct,
            'time_days': time_days,
            'atr_pct': atr_pct
        }

        # Iterate through trajectory
        for i, (idx, row) in enumerate(trade_df.iterrows()):
            current_price = row['Close']
            return_pct = (current_price - entry_price) / entry_price

            # Check barriers in order: TP → SL → Time
            if return_pct >= target_pct:
                return ('TP', i, return_pct, barrier_details)

            if return_pct <= -stop_pct:
                return ('SL', i, return_pct, barrier_details)

            if i >= time_days:
                return ('Time', i, return_pct, barrier_details)

        # Fallback: hit time barrier at last available day
        final_return = (trade_df.iloc[-1]['Close'] - entry_price) / entry_price
        return ('Time', len(trade_df) - 1, final_return, barrier_details)

    @staticmethod
    def apply_hybrid_barriers_vectorized(
        trade_df: pd.DataFrame,
        params: HybridBarrierParams
    ) -> Tuple[OutcomeType, int, float, dict]:
        """
        Vectorized barrier check - ~50-100x faster than row iteration.

        Uses NumPy vectorized operations instead of row-by-row iteration.
        Results are identical to apply_hybrid_barriers().

        Args:
            trade_df: Single trade trajectory with 'ATR' column
            params: Hybrid barrier parameters

        Returns:
            (outcome, days_to_outcome, return_at_outcome, barrier_details)
        """
        if trade_df.empty:
            raise ValueError("Empty trade trajectory")

        if 'ATR' not in trade_df.columns:
            raise ValueError("ATR column required for hybrid barriers")

        # Get entry values
        entry_price = trade_df.iloc[0]['Close']
        entry_atr = trade_df.iloc[0]['ATR']

        if pd.isna(entry_atr) or entry_atr <= 0:
            raise ValueError(f"Invalid ATR value: {entry_atr}")

        # Calculate thresholds
        atr_pct = entry_atr / entry_price
        stop_pct = params.k_sl * atr_pct
        target_pct = max(params.min_tp, params.k_tp * atr_pct)

        # Dynamic time calculation
        if atr_pct > 0:
            raw_time = int(target_pct / atr_pct)
            time_days = max(params.min_time, min(params.max_time, raw_time))
        else:
            time_days = params.max_time

        barrier_details = {
            'stop_pct': stop_pct,
            'target_pct': target_pct,
            'time_days': time_days,
            'atr_pct': atr_pct
        }

        # Vectorized returns calculation
        prices = trade_df['Close'].values
        returns = (prices - entry_price) / entry_price
        n_days = len(returns)

        # Find first index where each barrier is hit
        tp_hits = returns >= target_pct
        sl_hits = returns <= -stop_pct
        day_indices = np.arange(n_days)
        time_hits = day_indices >= time_days

        # Get first hit index for each barrier (use n_days as "never hit")
        first_tp = int(np.argmax(tp_hits)) if tp_hits.any() else n_days
        first_sl = int(np.argmax(sl_hits)) if sl_hits.any() else n_days
        first_time = int(np.argmax(time_hits)) if time_hits.any() else n_days - 1

        # Handle edge case: argmax returns 0 if all False, so check if actually hit
        if not tp_hits.any():
            first_tp = n_days
        if not sl_hits.any():
            first_sl = n_days

        # Determine which barrier was hit first
        first_hit = min(first_tp, first_sl, first_time)
        first_hit = min(first_hit, n_days - 1)  # Clamp to valid index

        # Determine outcome based on which barrier was hit first
        if first_tp <= first_sl and first_tp <= first_time and tp_hits.any():
            outcome = 'TP'
            hit_day = first_tp
        elif first_sl < first_tp and first_sl <= first_time and sl_hits.any():
            outcome = 'SL'
            hit_day = first_sl
        else:
            outcome = 'Time'
            hit_day = first_time

        return (outcome, hit_day, returns[hit_day], barrier_details)

    @staticmethod
    def label_dataset(
        d2_rehydrated: pd.DataFrame,
        params: BarrierParams,
        binary_labels: bool = True,
        n_jobs: int = 1,
        use_vectorized: bool = True
    ) -> pd.DataFrame:
        """
        Apply triple barriers to entire rehydrated dataset.

        Args:
            d2_rehydrated: Multi-day trade trajectories (from rehydrate_d2)
            params: Barrier parameters (static, dynamic, or hybrid)
            binary_labels: If True, y_meta ∈ {0,1}. If False, y_meta ∈ {-1,0,1}
            n_jobs: Number of parallel workers (-1 = all cores, 1 = sequential)
            use_vectorized: Use vectorized barrier check for hybrid (faster)

        Returns:
            DataFrame with one row per trade (trade_id, features at entry, y_meta)
        """
        is_hybrid = isinstance(params, HybridBarrierParams)
        trade_ids = d2_rehydrated['trade_id'].unique()
        
        # Pre-group trades for efficiency
        grouped = {tid: d2_rehydrated[d2_rehydrated['trade_id'] == tid].sort_values('Date')
                   for tid in trade_ids}
        
        def process_trade(trade_id):
            """Process single trade - worker function."""
            trade_df = grouped[trade_id]
            
            try:
                if isinstance(params, StaticBarrierParams):
                    outcome, days, return_pct = TripleBarrierLabeler.apply_static_barriers(
                        trade_df, params
                    )
                    barrier_details = {}
                elif isinstance(params, DynamicBarrierParams):
                    outcome, days, return_pct = TripleBarrierLabeler.apply_dynamic_barriers(
                        trade_df, params
                    )
                    barrier_details = {}
                else:  # HybridBarrierParams
                    if use_vectorized:
                        outcome, days, return_pct, barrier_details = \
                            TripleBarrierLabeler.apply_hybrid_barriers_vectorized(trade_df, params)
                    else:
                        outcome, days, return_pct, barrier_details = \
                            TripleBarrierLabeler.apply_hybrid_barriers(trade_df, params)
            except ValueError:
                return None

            # Extract entry-day features
            entry_features = trade_df.iloc[0].to_dict()

            # Assign label
            if binary_labels:
                y_meta = 1 if outcome == 'TP' else 0
            else:
                label_map = {'TP': 1, 'Time': 0, 'SL': -1}
                y_meta = label_map[outcome]

            result_row = {
                'trade_id': trade_id,
                **entry_features,
                'y_meta': y_meta,
                'barrier_outcome': outcome,
                'days_to_outcome': days,
                'return_at_outcome': return_pct
            }

            # Add hybrid barrier details if available
            if is_hybrid and barrier_details:
                result_row['barrier_stop_pct'] = barrier_details['stop_pct']
                result_row['barrier_target_pct'] = barrier_details['target_pct']
                result_row['barrier_time_days'] = barrier_details['time_days']

            return result_row

        # Process trades
        if n_jobs == 1:
            # Sequential (with progress bar)
            results = []
            for trade_id in tqdm(trade_ids, desc="Labeling"):
                result = process_trade(trade_id)
                if result is not None:
                    results.append(result)
        else:
            # Parallel processing
            results = Parallel(n_jobs=n_jobs, prefer="threads")(
                delayed(process_trade)(tid) for tid in tqdm(trade_ids, desc="Labeling")
            )
            results = [r for r in results if r is not None]

        return pd.DataFrame(results)


def compute_expectancy(outcomes: pd.DataFrame) -> dict:
    """
    Compute trading expectancy and key metrics for barrier outcomes.

    Args:
        outcomes: DataFrame with columns [barrier_outcome, return_at_outcome, days_to_outcome]

    Returns:
        Dict with expectancy, win_rate, avg_win, avg_loss, risk_reward, avg_days, ignition_score
    """
    tp_trades = outcomes[outcomes['barrier_outcome'] == 'TP']
    sl_trades = outcomes[outcomes['barrier_outcome'] == 'SL']
    time_trades = outcomes[outcomes['barrier_outcome'] == 'Time']

    total = len(outcomes)
    if total == 0:
        return {
            'expectancy': 0, 'risk_adjusted_return': 0,
            'win_rate': 0, 'loss_rate': 0, 'time_rate': 0,
            'avg_win': 0, 'avg_loss': 0, 'avg_time': 0,
            'avg_days': 0, 'risk_reward': 0, 'ignition_score': 0
        }

    tp_pct = len(tp_trades) / total
    sl_pct = len(sl_trades) / total
    time_pct = len(time_trades) / total

    avg_tp_return = tp_trades['return_at_outcome'].mean() if len(tp_trades) > 0 else 0
    avg_sl_return = sl_trades['return_at_outcome'].mean() if len(sl_trades) > 0 else 0
    avg_time_return = time_trades['return_at_outcome'].mean() if len(time_trades) > 0 else 0

    # Expectancy = weighted average return
    expectancy = (tp_pct * avg_tp_return) + (sl_pct * avg_sl_return) + (time_pct * avg_time_return)

    # Risk-adjusted expectancy (annualized)
    avg_days = outcomes['days_to_outcome'].mean()
    annual_factor = 252 / avg_days if avg_days > 0 else 0
    risk_adjusted_return = expectancy * annual_factor

    # Ignition Score: Separation between TP (igniters) and Time (drifters)
    # High score = TP trades clearly different from Time trades
    # This measures how well barriers distinguish fast movers from capital wasters
    std_all_returns = outcomes['return_at_outcome'].std()
    if std_all_returns > 0 and len(tp_trades) > 0 and len(time_trades) > 0:
        ignition_score = (avg_tp_return - avg_time_return) / std_all_returns
    else:
        ignition_score = 0

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
        'risk_reward': abs(avg_tp_return / avg_sl_return) if avg_sl_return != 0 else 0,
        'ignition_score': ignition_score
    }
