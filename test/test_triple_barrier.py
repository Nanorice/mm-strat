"""
Unit tests for Triple Barrier Labeler

Tests barrier logic including:
- Static percentage-based barriers
- Dynamic ATR-based barriers  
- Hybrid barriers (MAX logic for targets)
- Path dependency (first touch wins)
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.triple_barrier_labeler import (
    TripleBarrierLabeler,
    StaticBarrierParams,
    DynamicBarrierParams, 
    HybridBarrierParams,
    compute_expectancy
)


def create_trade_trajectory(
    entry_price: float = 100.0,
    returns: list = None,
    atr: float = 3.0
) -> pd.DataFrame:
    """Helper to create a mock trade trajectory DataFrame."""
    if returns is None:
        returns = [0.0, 0.02, 0.05, 0.08, 0.10]  # Steady upward
    
    prices = [entry_price * (1 + r) for r in returns]
    dates = pd.date_range('2024-01-01', periods=len(prices), freq='D')
    
    return pd.DataFrame({
        'Date': dates,
        'Close': prices,
        'ATR': [atr] * len(prices)
    })


class TestStaticBarriers:
    """Tests for static percentage-based barriers."""
    
    def test_profit_target_hit(self):
        """Trade hits +20% target."""
        # Returns: 0%, 5%, 10%, 15%, 22%
        trade_df = create_trade_trajectory(
            returns=[0.0, 0.05, 0.10, 0.15, 0.22]
        )
        params = StaticBarrierParams(upper_pct=0.20, lower_pct=0.07, time_days=30)
        
        outcome, days, return_pct = TripleBarrierLabeler.apply_static_barriers(trade_df, params)
        
        assert outcome == 'TP'
        assert days == 4  # Hit on day 4 (22% >= 20%)
        assert return_pct >= 0.20
    
    def test_stop_loss_hit(self):
        """Trade hits -7% stop loss."""
        trade_df = create_trade_trajectory(
            returns=[0.0, -0.02, -0.05, -0.08]
        )
        params = StaticBarrierParams(upper_pct=0.20, lower_pct=0.07, time_days=30)
        
        outcome, days, return_pct = TripleBarrierLabeler.apply_static_barriers(trade_df, params)
        
        assert outcome == 'SL'
        assert days == 3  # Hit on day 3 (-8% <= -7%)
        assert return_pct <= -0.07
    
    def test_time_barrier_hit(self):
        """Neither TP nor SL hit, time expires."""
        # Returns stay between -5% and +15%
        trade_df = create_trade_trajectory(
            returns=[0.0, 0.02, -0.03, 0.05, -0.02, 0.03] * 6  # 36 days
        )
        params = StaticBarrierParams(upper_pct=0.20, lower_pct=0.10, time_days=20)
        
        outcome, days, return_pct = TripleBarrierLabeler.apply_static_barriers(trade_df, params)
        
        assert outcome == 'Time'
        assert days == 20


class TestDynamicBarriers:
    """Tests for ATR-based dynamic barriers."""
    
    def test_atr_scaled_stop(self):
        """Stop loss scaled by ATR."""
        # Entry=100, ATR=3 (3% of price), k_lower=1.0 → stop at -3%
        trade_df = create_trade_trajectory(
            entry_price=100.0,
            returns=[0.0, -0.01, -0.02, -0.04],  # -4% on last day
            atr=3.0
        )
        params = DynamicBarrierParams(upper_atr_mult=3.0, lower_atr_mult=1.0, time_days=30)
        
        outcome, days, return_pct = TripleBarrierLabeler.apply_dynamic_barriers(trade_df, params)
        
        assert outcome == 'SL'
        assert days == 3  # Hit on day 3 (-4% <= -3%)
    
    def test_atr_scaled_target(self):
        """Profit target scaled by ATR."""
        # Entry=100, ATR=5 (5% of price), k_upper=3.0 → target at +15%
        trade_df = create_trade_trajectory(
            entry_price=100.0,
            returns=[0.0, 0.05, 0.10, 0.16],  # +16% on last day
            atr=5.0
        )
        params = DynamicBarrierParams(upper_atr_mult=3.0, lower_atr_mult=1.0, time_days=30)
        
        outcome, days, return_pct = TripleBarrierLabeler.apply_dynamic_barriers(trade_df, params)
        
        assert outcome == 'TP'
        assert return_pct >= 0.15


class TestHybridBarriers:
    """Tests for hybrid barriers with MAX logic."""
    
    def test_floor_used_when_atr_low(self):
        """MIN floor kicks in when ATR-based target is too low."""
        # Entry=100, ATR=2 (2% of price), k_tp=3.0 → ATR target=6%
        # min_tp=20% → actual target = MAX(20%, 6%) = 20%
        trade_df = create_trade_trajectory(
            entry_price=100.0,
            returns=[0.0, 0.05, 0.10, 0.15, 0.21],
            atr=2.0
        )
        params = HybridBarrierParams(k_sl=1.0, k_tp=3.0, min_tp=0.20)
        
        outcome, days, return_pct, details = TripleBarrierLabeler.apply_hybrid_barriers(trade_df, params)
        
        assert outcome == 'TP'
        assert details['target_pct'] == 0.20  # Floor used, not 6%
        assert return_pct >= 0.20
    
    def test_atr_target_when_volatility_high(self):
        """ATR-based target used when higher than floor."""
        # Entry=100, ATR=8 (8% of price), k_tp=3.0 → ATR target=24%
        # min_tp=20% → actual target = MAX(20%, 24%) = 24%
        trade_df = create_trade_trajectory(
            entry_price=100.0,
            returns=[0.0, 0.10, 0.18, 0.25],
            atr=8.0
        )
        params = HybridBarrierParams(k_sl=1.0, k_tp=3.0, min_tp=0.20)
        
        outcome, days, return_pct, details = TripleBarrierLabeler.apply_hybrid_barriers(trade_df, params)
        
        assert outcome == 'TP'
        assert details['target_pct'] == 0.24  # 3 * 8% = 24%
        assert return_pct >= 0.24
    
    def test_dynamic_time_calculation(self):
        """Time barrier calculated from distance/speed."""
        # Entry=100, ATR=4 (4% daily move), target=20%
        # time = target / avg_daily_move = 0.20 / 0.04 = 5 days
        # But capped at min_time=20, so time = 20
        trade_df = create_trade_trajectory(
            entry_price=100.0,
            returns=[0.0, 0.01, 0.02, 0.03, 0.04] * 10,  # 50 days, never hits TP/SL
            atr=4.0
        )
        params = HybridBarrierParams(k_sl=1.5, k_tp=5.0, min_tp=0.20, min_time=20, max_time=60)
        
        outcome, days, return_pct, details = TripleBarrierLabeler.apply_hybrid_barriers(trade_df, params)
        
        assert outcome == 'Time'
        # target = MAX(20%, 5*4%) = MAX(20%, 20%) = 20%
        # raw_time = 0.20 / 0.04 = 5, clamped to [20, 60] = 20
        assert details['time_days'] == 20
        assert days == 20
    
    def test_path_dependency_tp_before_sl(self):
        """TP checked before SL when both could hit."""
        # Day 0: entry
        # Day 1: +22% (hits TP) but also if checking SL first, wouldn't hit
        trade_df = create_trade_trajectory(
            entry_price=100.0,
            returns=[0.0, 0.22],
            atr=5.0
        )
        params = HybridBarrierParams(k_sl=4.0, k_tp=4.0, min_tp=0.20)
        
        outcome, days, return_pct, _ = TripleBarrierLabeler.apply_hybrid_barriers(trade_df, params)
        
        assert outcome == 'TP'


class TestComputeExpectancy:
    """Tests for expectancy calculation."""
    
    def test_basic_expectancy(self):
        """Verify expectancy formula."""
        outcomes = pd.DataFrame({
            'barrier_outcome': ['TP', 'TP', 'SL', 'Time'],
            'return_at_outcome': [0.20, 0.25, -0.08, 0.05],
            'days_to_outcome': [15, 20, 5, 30]
        })
        
        metrics = compute_expectancy(outcomes)
        
        # Win rate = 2/4 = 50%
        assert metrics['win_rate'] == 0.5
        
        # Avg win = (0.20 + 0.25) / 2 = 0.225
        assert abs(metrics['avg_win'] - 0.225) < 0.001
        
        # Avg loss = -0.08
        assert abs(metrics['avg_loss'] - (-0.08)) < 0.001
        
        # Expectancy = 0.5 * 0.225 + 0.25 * (-0.08) + 0.25 * 0.05
        # = 0.1125 - 0.02 + 0.0125 = 0.105
        assert abs(metrics['expectancy'] - 0.105) < 0.001
    
    def test_empty_outcomes(self):
        """Handle empty outcomes gracefully."""
        outcomes = pd.DataFrame(columns=['barrier_outcome', 'return_at_outcome', 'days_to_outcome'])
        
        metrics = compute_expectancy(outcomes)
        
        assert metrics['expectancy'] == 0
        assert metrics['win_rate'] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
