"""
Unit Tests for Fundamental Merger

Tests Phase 2 & 3: As-of join and hybrid features including:
- Fiscal year trap prevention (no look-ahead bias)
- Forward fill logic
- Staleness detection
- Hybrid feature calculation (P/E, P/B)
"""

import pandas as pd
import numpy as np
import pytest
from datetime import datetime, timedelta

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from src.fundamental_merger import FundamentalMerger
from src.fundamental_processor import FundamentalProcessor


class TestFundamentalMerger:
    """Test suite for FundamentalMerger class."""
    
    @pytest.fixture
    def merger(self):
        """Create a merger instance with mock dependencies."""
        return FundamentalMerger(
            fundamental_engine=None,  # We'll use mock data
            fundamental_processor=FundamentalProcessor(),
            staleness_threshold_days=400
        )
    
    @pytest.fixture
    def sample_price_data(self):
        """Create sample daily price data."""
        dates = pd.date_range('2024-01-01', '2024-12-31', freq='B')  # Business days
        
        data = {
            'Close': np.random.uniform(100, 110, len(dates)),
            'Volume': np.random.randint(1000000, 2000000, len(dates)),
            'High': np.random.uniform(100, 115, len(dates)),
            'Low': np.random.uniform(95, 105, len(dates)),
        }
        
        df = pd.DataFrame(data, index=dates)
        df.index.name = 'Date'
        
        return df
    
    @pytest.fixture
    def sample_processed_fundamentals(self):
        """Create sample processed fundamental data."""
        # Q4 2023, Q1 2024, Q2 2024, Q3 2024
        fiscal_dates = [
            pd.Timestamp('2023-12-31'),
            pd.Timestamp('2024-03-31'),
            pd.Timestamp('2024-06-30'),
            pd.Timestamp('2024-09-30')
        ]
        
        filing_dates = [
            pd.Timestamp('2024-01-31'),  # Q4 2023 filed in Jan
            pd.Timestamp('2024-04-30'),  # Q1 2024 filed in Apr
            pd.Timestamp('2024-07-31'),  # Q2 2024 filed in Jul
            pd.Timestamp('2024-10-31')   # Q3 2024 filed in Oct
        ]
        
        data = {
            'ticker': ['TEST'] * 4,
            'fiscal_date': fiscal_dates,
            'filing_date': filing_dates,
            'fiscal_period': ['Q4', 'Q1', 'Q2', 'Q3'],
            'fiscal_year': [2023, 2024, 2024, 2024],
            'revenue': [1000, 1100, 1200, 1300],
            'eps': [1.0, 1.1, 1.2, 1.3],
            'netIncome': [100, 110, 120, 130],
            'totalEquity': [2000, 2100, 2200, 2300],
            'revenue_growth_yoy': [10.0, 15.0, 20.0, 25.0],
            'eps_growth_yoy': [10.0, 15.0, 20.0, 25.0],
            'debt_to_equity': [0.5, 0.48, 0.45, 0.43],
            'current_ratio': [2.0, 2.1, 2.2, 2.3],
            'gross_margin': [40.0, 41.0, 42.0, 43.0],
            'operating_margin': [20.0, 21.0, 22.0, 23.0],
            'roe': [5.0, 5.2, 5.5, 5.7],
            'roa': [2.0, 2.1, 2.2, 2.3]
        }
        
        return pd.DataFrame(data)
    
    def test_fiscal_year_trap_prevention(self, merger, sample_price_data, sample_processed_fundamentals):
        """
        CRITICAL TEST: Verify no look-ahead bias (fiscal year trap).
        
        Q4 2023 ends 2023-12-31 but is FILED on 2024-01-31.
        Prices before 2024-01-31 should NOT have Q4 2023 data.
        """
        price_df = sample_price_data.loc['2024-01-01':'2024-02-29'].copy()
        fund_df = sample_processed_fundamentals.copy()
        
        result = merger._as_of_join(price_df, fund_df, 'TEST')
        
        # Check a date BEFORE Q4 2023 filing (2024-01-31)
        before_filing = result[result['Date'] < pd.Timestamp('2024-01-31')]
        
        # Should have NO Q4 2023 data (filing_date_matched should be NaT or earlier)
        if 'filing_date_matched' in before_filing.columns:
            assert before_filing['filing_date_matched'].isna().all(), \
                "Data before filing date should not have that quarter's data!"
        
        # Check a date ON OR AFTER filing
        on_or_after_filing = result[result['Date'] >= pd.Timestamp('2024-01-31')]
        on_or_after_filing = on_or_after_filing[on_or_after_filing['Date'] < pd.Timestamp('2024-04-30')]
        
        # Should have Q4 2023 data
        if not on_or_after_filing.empty:
            first_matched = on_or_after_filing.iloc[0]['filing_date_matched']
            assert first_matched == pd.Timestamp('2024-01-31'), \
                f"After filing, should have Q4 2023 data filed on 2024-01-31, got {first_matched}"
    
    def test_forward_fill(self, merger, sample_price_data, sample_processed_fundamentals):
        """Test that fundamental values are forward-filled correctly."""
        price_df = sample_price_data.loc['2024-02-01':'2024-05-31'].copy()
        fund_df = sample_processed_fundamentals.copy()
        
        result = merger._as_of_join(price_df, fund_df, 'TEST')
        
        # All dates from 2024-02-01 to 2024-04-29 should have Q4 2023 data (filed 2024-01-31)
        q4_period = result[
            (result['Date'] >= pd.Timestamp('2024-02-01')) &
            (result['Date'] < pd.Timestamp('2024-04-30'))
        ]
        
        if not q4_period.empty and 'filing_date_matched' in q4_period.columns:
            # All should be 2024-01-31
            assert (q4_period['filing_date_matched'] == pd.Timestamp('2024-01-31')).all(), \
                "Fundamentals should be forward-filled until next filing date"
        
        # All dates from 2024-04-30 to 2024-05-31 should have Q1 2024 data (filed 2024-04-30)
        q1_period = result[
            (result['Date'] >= pd.Timestamp('2024-04-30')) &
            (result['Date'] <= pd.Timestamp('2024-05-31'))
        ]
        
        if not q1_period.empty and 'filing_date_matched' in q1_period.columns:
            assert (q1_period['filing_date_matched'] == pd.Timestamp('2024-04-30')).all()
    
    def test_staleness_detection(self, merger, sample_price_data, sample_processed_fundamentals):
        """Test that stale data (>400 days) is flagged."""
        # Create scenario with very old fundamental data
        price_df = sample_price_data.copy()
        fund_df = sample_processed_fundamentals.copy()
        
        # Set filing date to 500 days ago
        old_filing_date = pd.Timestamp('2024-12-31') - timedelta(days=500)
        fund_df = pd.DataFrame({
            'ticker': ['TEST'],
            'filing_date': [old_filing_date],
            'revenue': [1000],
            'eps': [1.0],
            'netIncome': [100],
            'totalEquity': [2000]
        })
        
        result = merger._as_of_join(price_df, fund_df, 'TEST')
        result = merger._calculate_staleness(result)
        
        # Check staleness for recent dates
        recent_dates = result[result['Date'] >= pd.Timestamp('2024-12-01')]
        
        if not recent_dates.empty and 'is_stale' in recent_dates.columns:
            # Should be marked as stale
            assert recent_dates['is_stale'].all(), \
                "Data >400 days old should be flagged as stale"
            
            # Days since report should be >400
            assert (recent_dates['days_since_report'] > 400).all()
    
    def test_hybrid_pe_ratio(self, merger):
        """Test P/E ratio calculation (Close / EPS)."""
        data = {
            'Close': [100, 110, 120],
            'eps': [10, 11, 12]
        }
        df = pd.DataFrame(data)
        
        result = merger.calculate_hybrid_features(df)
        
        assert 'pe_ratio' in result.columns
        
        # P/E should be Close / EPS
        expected_pe = [10.0, 10.0, 10.0]
        for i in range(3):
            assert abs(result['pe_ratio'].iloc[i] - expected_pe[i]) < 0.01
    
    def test_pe_ratio_division_by_zero(self, merger):
        """Test P/E ratio handles EPS=0."""
        data = {
            'Close': [100],
            'eps': [0]  # Zero EPS
        }
        df = pd.DataFrame(data)
        
        result = merger.calculate_hybrid_features(df)
        
        # Should be NaN, not infinity
        assert pd.isna(result['pe_ratio'].iloc[0])
    
    def test_pe_ratio_extreme_capping(self, merger):
        """Test P/E ratio caps extreme values (>1000)."""
        data = {
            'Close': [100],
            'eps': [0.05]  # P/E would be 2000
        }
        df = pd.DataFrame(data)
        
        result = merger.calculate_hybrid_features(df)
        
        # Should be capped to NaN
        assert pd.isna(result['pe_ratio'].iloc[0])
    
    def test_empty_fundamentals_handling(self, merger, sample_price_data):
        """Test that missing fundamental data is handled gracefully."""
        price_df = sample_price_data.copy()
        
        result = merger._add_empty_fundamental_columns(price_df, 'TEST')
        
        # Should have fundamental columns
        assert 'has_fundamentals' in result.columns
        assert 'revenue' in result.columns
        assert 'eps' in result.columns
        assert 'pe_ratio' in result.columns
        
        # has_fundamentals should be False
        assert not result['has_fundamentals'].any()
        
        # is_stale should be True
        assert result['is_stale'].all()
    
    def test_nan_filling_strategy(self, merger):
        """Test NaN handling strategy for growth and ratio columns."""
        data = {
            'revenue': [1000, np.nan],
            'eps': [1.0, np.nan],
            'revenue_growth_yoy': [10.0, np.nan],
            'eps_growth_yoy': [15.0, np.nan],
            'debt_to_equity': [0.5, np.nan],
            'current_ratio': [2.0, np.nan]
        }
        df = pd.DataFrame(data)
        
        result = merger._handle_missing_fundamentals(df)
        
        # Growth metrics should be filled with 0
        assert result['revenue_growth_yoy'].iloc[1] == 0.0
        assert result['eps_growth_yoy'].iloc[1] == 0.0
        
        # Ratios should be filled with median
        assert result['debt_to_equity'].iloc[1] == 0.5  # Median of [0.5, NaN] = 0.5
        assert result['current_ratio'].iloc[1] == 2.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
