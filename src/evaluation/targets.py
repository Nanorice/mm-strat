"""
Target label engineering for M01 ablation study.
=================================================

Generates alternative target labels to test different ML approaches:
- Option A: Survivor MFE (baseline)
- Option B: Hybrid Floor (soft loser penalty)
- Option C: Risk-Adjusted (MFE / ATR)
- Option D: Log-Space (tail smoothing)
"""

import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Tuple

logger = logging.getLogger("TargetEngineer")


class TargetEngineer:
    """Generate alternative target labels for model training."""
    
    @staticmethod
    def calculate_survivor_mfe(
        d2_df: pd.DataFrame,
        d2r_df: pd.DataFrame,
        stop_multiplier: float = 2.0
    ) -> Tuple[pd.DataFrame, Dict]:
        """
        Option A: Baseline survivor MFE.
        
        Filters crashed trades, trains on y_max (MFE) only.
        This creates survivorship bias but may improve signal quality.
        
        Args:
            d2_df: D2 features DataFrame
            d2r_df: D2 rehydrated DataFrame (contains OHLC bars)
            stop_multiplier: Multiplier for structural stop (default 2.0)
            
        Returns:
            (d2_with_target, stats_dict)
        """
        logger.info("Computing Survivor MFE target (Option A)...")
        
        d2 = d2_df.copy()
        d2['date'] = pd.to_datetime(d2['date']).dt.normalize()
        
        # Calculate MFE, MAE, and survivor status from D2R
        trade_metrics = TargetEngineer._compute_trade_metrics(d2r_df, stop_multiplier)
        
        # Merge
        d2 = pd.merge(
            d2,
            trade_metrics[['ticker', 'date', 'MFE', 'MAE', 'is_survivor']],
            on=['ticker', 'date'],
            how='left'
        )
        
        # Fill missing
        if 'return_pct' in d2.columns:
            d2['MFE'] = d2['MFE'].fillna(d2['return_pct'])
        d2['is_survivor'] = d2['is_survivor'].fillna(True)
        
        # Filter to survivors only
        n_before = len(d2)
        d2_filtered = d2[d2['is_survivor'] == True].copy()
        n_after = len(d2_filtered)
        
        # Target is MFE
        d2_filtered['target'] = d2_filtered['MFE']
        
        stats = {
            'target_type': 'survivor_mfe',
            'total_trades': n_before,
            'filtered_trades': n_before - n_after,
            'remaining_trades': n_after,
            'filter_rate': (n_before - n_after) / n_before if n_before > 0 else 0,
            'mean_target': float(d2_filtered['target'].mean()),
            'std_target': float(d2_filtered['target'].std())
        }
        
        logger.info(f"   Filtered {stats['filtered_trades']} crashed trades ({stats['filter_rate']:.1%})")
        logger.info(f"   Training on {stats['remaining_trades']} survivors, mean target: {stats['mean_target']:.2f}%")
        
        return d2_filtered, stats
    
    @staticmethod
    def calculate_hybrid_floor(
        d2_df: pd.DataFrame,
        d2r_df: pd.DataFrame,
        stop_multiplier: float = 2.0,
        max_penalty: float = -10.0
    ) -> Tuple[pd.DataFrame, Dict]:
        """
        Option B: Hybrid Floor (Soft Loser Penalty).
        
        Survivors get MFE, losers get capped penalty.
        Keeps all trades in dataset but limits impact of extreme losses.
        
        Formula:
            if is_survivor: y = MFE
            else: y = min(max_penalty, -stop_multiplier × ATR)
            
        The min() function ensures we use the LESS SEVERE penalty.
        
        Args:
            d2_df: D2 features DataFrame
            d2r_df: D2 rehydrated DataFrame
            stop_multiplier: Multiplier for structural stop
            max_penalty: Maximum penalty cap (e.g., -10%)
            
        Returns:
            (d2_with_target, stats_dict)
        """
        logger.info("Computing Hybrid Floor target (Option B)...")
        
        d2 = d2_df.copy()
        d2['date'] = pd.to_datetime(d2['date']).dt.normalize()
        
        # Calculate trade metrics
        trade_metrics = TargetEngineer._compute_trade_metrics(d2r_df, stop_multiplier)
        
        # Merge
        d2 = pd.merge(
            d2,
            trade_metrics[['ticker', 'date', 'MFE', 'MAE', 'nATR', 'is_survivor']],
            on=['ticker', 'date'],
            how='left'
        )
        
        # Fill missing
        if 'return_pct' in d2.columns:
            d2['MFE'] = d2['MFE'].fillna(d2['return_pct'])
        d2['is_survivor'] = d2['is_survivor'].fillna(True)
        d2['nATR'] = d2['nATR'].fillna(5.0)
        
        # Calculate hybrid floor target
        # Survivors: Use MFE
        # Losers: Use min(max_penalty, -stop_multiplier * nATR)
        structural_penalty = -stop_multiplier * d2['nATR']
        loser_penalty = np.maximum(max_penalty, structural_penalty)  # max because both are negative
        
        d2['target'] = np.where(d2['is_survivor'], d2['MFE'], loser_penalty)
        
        n_survivors = d2['is_survivor'].sum()
        n_losers = (~d2['is_survivor']).sum()
        
        stats = {
            'target_type': 'hybrid_floor',
            'total_trades': len(d2),
            'survivors': int(n_survivors),
            'losers': int(n_losers),
            'loser_rate': float(n_losers / len(d2)) if len(d2) > 0 else 0,
            'mean_target': float(d2['target'].mean()),
            'std_target': float(d2['target'].std()),
            'mean_loser_target': float(d2[~d2['is_survivor']]['target'].mean()) if n_losers > 0 else 0,
            'max_penalty': max_penalty
        }
        
        logger.info(f"   Total: {len(d2)} trades, Losers: {n_losers} ({stats['loser_rate']:.1%})")
        logger.info(f"   Mean target: {stats['mean_target']:.2f}%, Loser avg: {stats['mean_loser_target']:.2f}%")
        
        return d2, stats
    
    @staticmethod
    def calculate_risk_adjusted(
        d2_df: pd.DataFrame,
        d2r_df: pd.DataFrame,
        stop_multiplier: float = 2.0
    ) -> Tuple[pd.DataFrame, Dict]:
        """
        Option C: Risk-Adjusted (MFE / ATR).
        
        Normalizes by entry volatility to prevent vol-detector trap.
        Model learns to find high ATR-adjusted returns, not just high ATR.
        
        Formula: y = MFE / ATR_entry
        
        Args:
            d2_df: D2 features DataFrame
            d2r_df: D2 rehydrated DataFrame
            stop_multiplier: Multiplier for structural stop
            
        Returns:
            (d2_with_target, stats_dict)
        """
        logger.info("Computing Risk-Adjusted target (Option C)...")
        
        d2 = d2_df.copy()
        d2['date'] = pd.to_datetime(d2['date']).dt.normalize()
        
        # Calculate trade metrics
        trade_metrics = TargetEngineer._compute_trade_metrics(d2r_df, stop_multiplier)
        
        # Merge
        d2 = pd.merge(
            d2,
            trade_metrics[['ticker', 'date', 'MFE', 'MAE', 'nATR', 'is_survivor']],
            on=['ticker', 'date'],
            how='left'
        )
        
        # Fill missing
        if 'return_pct' in d2.columns:
            d2['MFE'] = d2['MFE'].fillna(d2['return_pct'])
        d2['nATR'] = d2['nATR'].fillna(5.0)
        
        # Risk-adjusted target: MFE / nATR
        # Add small epsilon to avoid division by zero
        d2['target'] = d2['MFE'] / (d2['nATR'] + 0.01)
        
        # Clip extreme values
        target_clip = d2['target'].quantile(0.99)
        d2['target'] = d2['target'].clip(upper=target_clip)
        
        stats = {
            'target_type': 'risk_adjusted',
            'total_trades': len(d2),
            'mean_target': float(d2['target'].mean()),
            'std_target': float(d2['target'].std()),
            'mean_mfe': float(d2['MFE'].mean()),
            'mean_natr': float(d2['nATR'].mean())
        }
        
        logger.info(f"   Total: {len(d2)} trades")
        logger.info(f"   Mean risk-adjusted target: {stats['mean_target']:.2f}")
        logger.info(f"   vs raw MFE: {stats['mean_mfe']:.2f}%")
        
        return d2, stats
    
    @staticmethod
    def calculate_log_space(
        d2_df: pd.DataFrame,
        d2r_df: pd.DataFrame,
        stop_multiplier: float = 2.0
    ) -> Tuple[pd.DataFrame, Dict]:
        """
        Option D: Log-Space (Tail Smoothing).
        
        Compresses outlier returns to prevent dominance.
        Uses signed log transform to handle both positive and negative returns.
        
        Formula: y = sign(MFE) × log(1 + |MFE|)
        
        Args:
            d2_df: D2 features DataFrame
            d2r_df: D2 rehydrated DataFrame
            stop_multiplier: Multiplier for structural stop
            
        Returns:
            (d2_with_target, stats_dict)
        """
        logger.info("Computing Log-Space target (Option D)...")
        
        d2 = d2_df.copy()
        d2['date'] = pd.to_datetime(d2['date']).dt.normalize()
        
        # Calculate trade metrics
        trade_metrics = TargetEngineer._compute_trade_metrics(d2r_df, stop_multiplier)
        
        # Merge
        d2 = pd.merge(
            d2,
            trade_metrics[['ticker', 'date', 'MFE', 'MAE', 'is_survivor']],
            on=['ticker', 'date'],
            how='left'
        )
        
        # Fill missing
        if 'return_pct' in d2.columns:
            d2['MFE'] = d2['MFE'].fillna(d2['return_pct'])
        
        # Log-space transform: sign(x) * log(1 + |x|)
        d2['target'] = np.sign(d2['MFE']) * np.log1p(np.abs(d2['MFE']))
        
        stats = {
            'target_type': 'log_space',
            'total_trades': len(d2),
            'mean_target': float(d2['target'].mean()),
            'std_target': float(d2['target'].std()),
            'mean_mfe': float(d2['MFE'].mean()),
            'std_mfe': float(d2['MFE'].std())
        }
        
        logger.info(f"   Total: {len(d2)} trades")
        logger.info(f"   Raw MFE std: {stats['std_mfe']:.2f}% -> Log-space std: {stats['std_target']:.2f}")
        
        return d2, stats
    
    @staticmethod
    def _compute_trade_metrics(
        d2r_df: pd.DataFrame,
        stop_multiplier: float = 2.0
    ) -> pd.DataFrame:
        """
        Compute per-trade metrics (MFE, MAE, is_survivor) from D2R data.
        
        Args:
            d2r_df: D2 rehydrated DataFrame with OHLC bars
            stop_multiplier: Multiplier for structural stop
            
        Returns:
            DataFrame with one row per trade containing metrics
        """
        d2r = d2r_df.copy()
        
        # Ensure day_in_trade exists
        if 'day_in_trade' not in d2r.columns:
            d2r = d2r.sort_values(['trade_id', 'Date'])
            d2r['day_in_trade'] = d2r.groupby('trade_id').cumcount()
        
        results = []
        for trade_id, group in d2r.groupby('trade_id'):
            entry_rows = group[group['day_in_trade'] == 0]
            if len(entry_rows) == 0:
                continue
            
            entry_price = entry_rows['Close'].iloc[0]
            if entry_price <= 0:
                continue
            
            # Extract metrics
            ticker = group['ticker'].iloc[0] if 'ticker' in group.columns else None
            date = entry_rows['Date'].iloc[0] if 'Date' in entry_rows.columns else None
            natr = entry_rows['nATR'].iloc[0] if 'nATR' in entry_rows.columns else 5.0
            
            highest = group['High'].max()
            lowest = group['Low'].min()
            
            mfe = ((highest - entry_price) / entry_price) * 100
            mae = ((lowest - entry_price) / entry_price) * 100
            structural_stop = -stop_multiplier * natr
            is_survivor = mae > structural_stop
            
            results.append({
                'ticker': ticker,
                'date': pd.to_datetime(date).normalize() if date else None,
                'MFE': mfe,
                'MAE': mae,
                'nATR': natr,
                'structural_stop': structural_stop,
                'is_survivor': is_survivor
            })
        
        return pd.DataFrame(results)
    
    @staticmethod
    def prepare_target(
        d2_df: pd.DataFrame,
        d2r_df: pd.DataFrame,
        target_type: str,
        stop_multiplier: float = 2.0,
        **kwargs
    ) -> Tuple[pd.DataFrame, Dict]:
        """
        Convenience method to prepare target by type name.
        
        Args:
            d2_df: D2 features DataFrame
            d2r_df: D2 rehydrated DataFrame
            target_type: One of 'survivor_mfe', 'hybrid_floor', 'risk_adjusted', 'log_space', 'return_pct'
            stop_multiplier: Multiplier for structural stop
            **kwargs: Additional arguments passed to specific method
            
        Returns:
            (d2_with_target, stats_dict)
        """
        if target_type == 'survivor_mfe':
            return TargetEngineer.calculate_survivor_mfe(d2_df, d2r_df, stop_multiplier)
        elif target_type == 'hybrid_floor':
            return TargetEngineer.calculate_hybrid_floor(d2_df, d2r_df, stop_multiplier, **kwargs)
        elif target_type == 'risk_adjusted':
            return TargetEngineer.calculate_risk_adjusted(d2_df, d2r_df, stop_multiplier)
        elif target_type == 'log_space':
            return TargetEngineer.calculate_log_space(d2_df, d2r_df, stop_multiplier)
        elif target_type == 'return_pct':
            # Default: just use return_pct as target
            d2 = d2_df.copy()
            d2['target'] = d2['return_pct']
            stats = {
                'target_type': 'return_pct',
                'total_trades': len(d2),
                'mean_target': float(d2['target'].mean()),
                'std_target': float(d2['target'].std())
            }
            return d2, stats
        else:
            raise ValueError(f"Unknown target type: {target_type}")
