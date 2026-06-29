"""
Vectorized SEPA Backtest
========================
Pure pandas/numpy engine for rapid notebook prototyping.

Trade-offs vs SEPAHybridV1 (BackTrader):
    - 10-100x faster (no event loop, no per-bar indicator updates)
    - Approximate capital constraints (assumes slots always available)
    - Simplified single-exit logic (no 3-tranche scaling)
    - Optional flat commission/slippage estimate

Use for rapid model iteration and parameter sweeps.
Use BackTrader for final production validation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import duckdb
from src import db
import numpy as np
import pandas as pd

import config
from src.backtest.universe_scorer import UniverseScorer

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = config.DATA_DIR / 'market_data.duckdb'


class VectorizedSEPABacktest:
    """
    Vectorized SEPA backtest — no event loop.

    Flow:
        1. Score all T3 candidates daily via UniverseScorer.score_from_t3()
        2. Filter by min_prob_elite, skip warmup days
        3. Rank within each day by prob_elite, take top N
        4. For each entry, vectorize-simulate exit vs price_data
        5. Compute trade-level PnL + portfolio equity curve
    """

    def __init__(
        self,
        model_path: str = 'models/m01_prototype/model.json',
        db_path: Optional[str] = None,
        start_date: str = '2020-01-01',
        end_date: str = '2025-01-01',
        min_prob_elite: float = 0.15,
        max_positions_per_day: int = 3,
        ranking_lookback_days: int = 10,
        stop_loss_pct: float = 0.10,
        sma_exit_period: int = 50,
        warmup_days: int = 10,
        commission_pct: float = 0.001,
        slippage_pct: float = 0.001,
        initial_cash: float = 100_000.0,
        position_size_pct: float = 0.10,
        max_hold_days: int = 252,
        precomputed_scores: Optional[pd.DataFrame] = None,
        precomputed_prices: Optional[pd.DataFrame] = None,
    ):
        self.model_path = model_path
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.start_date = start_date
        self.end_date = end_date
        self.min_prob_elite = min_prob_elite
        self.max_positions_per_day = max_positions_per_day
        self.ranking_lookback_days = ranking_lookback_days
        self.stop_loss_pct = stop_loss_pct
        self.sma_exit_period = sma_exit_period
        self.warmup_days = warmup_days
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.initial_cash = initial_cash
        self.position_size_pct = position_size_pct
        self.max_hold_days = max_hold_days

        # Injected caches — avoids re-scoring / re-loading on every sweep combo
        self._scores: Optional[pd.DataFrame] = precomputed_scores
        self._prices: Optional[pd.DataFrame] = precomputed_prices

    def run(self) -> pd.DataFrame:
        """
        Execute the full vectorized backtest.

        Returns:
            DataFrame with columns: ticker, entry_date, entry_price, exit_date,
            exit_price, exit_reason, pnl_pct, prob_elite_at_entry, holding_days.
        """
        entries = self._select_entries()
        if entries.empty:
            logger.warning("No entries selected — check min_prob_elite / warmup / date range")
            return pd.DataFrame(columns=[
                'ticker', 'entry_date', 'entry_price', 'exit_date', 'exit_price',
                'exit_reason', 'pnl_pct', 'prob_elite_at_entry', 'holding_days',
            ])

        prices = self._load_prices(
            entries['ticker'].unique().tolist(),
            sma_period=self.sma_exit_period,
        )
        trades = self._simulate_exits(entries, prices)
        trades = self._apply_costs(trades)
        return trades

    def _select_entries(self) -> pd.DataFrame:
        if self._scores is None:
            scorer = UniverseScorer(
                m01_path=self.model_path,
                calibration_path=None,
            )
            self._scores = scorer.score_from_t3(
                self.start_date,
                self.end_date,
                db_path=self.db_path,
                ranking_lookback_days=self.ranking_lookback_days,
            )

        if 'prob_elite' not in self._scores.columns:
            raise RuntimeError(
                "Scorer output missing prob_elite — model must be a classifier"
            )

        eligible = self._scores[self._scores['prob_elite'] >= self.min_prob_elite].copy()
        eligible['date'] = pd.to_datetime(eligible['date'])

        unique_dates = pd.Series(eligible['date'].unique()).sort_values().reset_index(drop=True)
        if len(unique_dates) <= self.warmup_days:
            logger.warning(
                f"warmup_days={self.warmup_days} >= unique dates ({len(unique_dates)}); "
                "no entries will be generated"
            )
            return eligible.iloc[0:0]

        warmup_cutoff = unique_dates.iloc[self.warmup_days]
        eligible = eligible[eligible['date'] >= warmup_cutoff]

        eligible['daily_rank'] = eligible.groupby('date')['prob_elite'].rank(
            ascending=False, method='first'
        )
        eligible = eligible[eligible['daily_rank'] <= self.max_positions_per_day]

        # Deduplicate: only first entry per ticker within the backtest window
        eligible = eligible.sort_values(['ticker', 'date'])
        first_entries = eligible.drop_duplicates(subset=['ticker'], keep='first')

        logger.info(
            f"Selected {len(first_entries)} entries from {len(eligible)} eligible "
            f"({eligible['ticker'].nunique()} unique tickers)"
        )
        cols_to_return = ['date', 'ticker', 'prob_elite', 'calibrated_score']
        if 'rs_sector_rank' in first_entries.columns:
            cols_to_return.append('rs_sector_rank')
        if 'rs_industry_rank' in first_entries.columns:
            cols_to_return.append('rs_industry_rank')
            
        return first_entries[cols_to_return].rename(
            columns={'date': 'entry_date', 'prob_elite': 'prob_elite_at_entry'}
        )

    def _load_prices(
        self,
        tickers: list[str],
        sma_period: Optional[int] = None,
    ) -> pd.DataFrame:
        """Load OHLC prices and compute SMA exit signal.

        If ``self._prices`` was injected (precomputed_prices), the raw frame is
        reused and only the SMA is (re)computed for the current sma_exit_period.
        """
        sma_period = sma_period or self.sma_exit_period

        if self._prices is not None:
            # Use cached raw prices; filter to requested tickers
            df = self._prices[self._prices['ticker'].isin(tickers)].copy()
        else:
            con = db.connect(str(self.db_path), read_only=True)
            try:
                df = con.execute("""
                    SELECT ticker, date, open, high, low, close
                    FROM price_data
                    WHERE ticker = ANY(?)
                      AND date >= ? AND date <= ?
                    ORDER BY ticker, date
                """, [tickers, self.start_date, self.end_date]).fetchdf()
            finally:
                con.close()
            df['date'] = pd.to_datetime(df['date'])

        # (Re)compute SMA for the current sweep period — fast, in-memory
        df['sma'] = (
            df.groupby('ticker')['close']
            .transform(lambda s: s.rolling(sma_period, min_periods=1).mean())
        )
        logger.info(f"Prices ready: {len(df)} rows, {df['ticker'].nunique()} tickers, SMA={sma_period}")
        return df

    def _simulate_exits(
        self,
        entries: pd.DataFrame,
        prices: pd.DataFrame,
    ) -> pd.DataFrame:
        prices = prices.sort_values(['ticker', 'date']).reset_index(drop=True)

        # Attach entry_price using the bar AT entry_date (next-day fill approximation: use close)
        entry_price_lookup = prices.merge(
            entries[['ticker', 'entry_date']],
            left_on=['ticker', 'date'],
            right_on=['ticker', 'entry_date'],
            how='inner',
        )[['ticker', 'entry_date', 'close']].rename(columns={'close': 'entry_price'})

        entries = entries.merge(entry_price_lookup, on=['ticker', 'entry_date'], how='inner')
        if entries.empty:
            return pd.DataFrame()

        # Join every post-entry bar with its originating entry
        merged = prices.merge(
            entries[['ticker', 'entry_date', 'entry_price', 'prob_elite_at_entry']],
            on='ticker',
            how='inner',
        )
        merged = merged[merged['date'] > merged['entry_date']].copy()

        merged['stop_level'] = merged['entry_price'] * (1.0 - self.stop_loss_pct)
        merged['hit_stop'] = merged['low'] <= merged['stop_level']
        merged['hit_trend'] = merged['close'] < merged['sma']
        merged['bars_held'] = (
            merged.groupby(['ticker', 'entry_date']).cumcount() + 1
        )
        merged['hit_timeout'] = merged['bars_held'] >= self.max_hold_days

        # Determine exit reason priority: stop > trend > timeout
        conditions = [merged['hit_stop'], merged['hit_trend'], merged['hit_timeout']]
        choices = ['stop_loss', 'trend_break', 'max_hold']
        merged['exit_candidate'] = np.select(conditions, choices, default=None)

        exits = merged[merged['exit_candidate'].notna()].copy()
        first_exits = exits.sort_values(['ticker', 'entry_date', 'date']).drop_duplicates(
            subset=['ticker', 'entry_date'], keep='first'
        )

        # Exit price: stop_level for stop-outs (assume fill at stop), else close
        first_exits['exit_price'] = np.where(
            first_exits['exit_candidate'] == 'stop_loss',
            first_exits['stop_level'],
            first_exits['close'],
        )

        trades = entries.merge(
            first_exits[['ticker', 'entry_date', 'date', 'exit_price', 'exit_candidate']],
            on=['ticker', 'entry_date'],
            how='left',
        ).rename(columns={'date': 'exit_date', 'exit_candidate': 'exit_reason'})

        # Open trades: still holding at end of data — mark-to-market at last available close
        open_mask = trades['exit_date'].isna()
        if open_mask.any():
            last_prices = (
                prices.sort_values(['ticker', 'date'])
                .groupby('ticker')
                .tail(1)[['ticker', 'date', 'close']]
                .rename(columns={'date': 'last_date', 'close': 'last_close'})
            )
            trades = trades.merge(last_prices, on='ticker', how='left')
            trades.loc[open_mask, 'exit_date'] = trades.loc[open_mask, 'last_date']
            trades.loc[open_mask, 'exit_price'] = trades.loc[open_mask, 'last_close']
            trades.loc[open_mask, 'exit_reason'] = 'held_open'
            trades = trades.drop(columns=['last_date', 'last_close'])

        trades['pnl_pct'] = (
            (trades['exit_price'] - trades['entry_price']) / trades['entry_price']
        )
        trades['holding_days'] = (
            pd.to_datetime(trades['exit_date']) - pd.to_datetime(trades['entry_date'])
        ).dt.days

        cols = [
            'ticker', 'entry_date', 'entry_price', 'exit_date', 'exit_price',
            'exit_reason', 'pnl_pct', 'prob_elite_at_entry', 'holding_days',
        ]
        if 'rs_sector_rank' in trades.columns:
            cols.append('rs_sector_rank')
        if 'rs_industry_rank' in trades.columns:
            cols.append('rs_industry_rank')
            
        return trades[cols].sort_values('entry_date').reset_index(drop=True)

    def _apply_costs(self, trades: pd.DataFrame) -> pd.DataFrame:
        if trades.empty:
            return trades
        cost = 2 * (self.commission_pct + self.slippage_pct)
        trades['pnl_pct'] = trades['pnl_pct'] - cost
        return trades

    def equity_curve(self, trades: pd.DataFrame) -> pd.Series:
        """Build a daily equity curve from trades (equal-weight position sizing)."""
        if trades.empty:
            return pd.Series(dtype=float)

        cash = self.initial_cash
        returns_by_date: dict[pd.Timestamp, float] = {}
        for _, t in trades.iterrows():
            exit_d = pd.Timestamp(t['exit_date'])
            pnl_dollar = cash * self.position_size_pct * t['pnl_pct']
            returns_by_date[exit_d] = returns_by_date.get(exit_d, 0.0) + pnl_dollar

        dates = pd.date_range(
            start=pd.Timestamp(trades['entry_date'].min()),
            end=pd.Timestamp(trades['exit_date'].max()),
            freq='B',
        )
        daily_pnl = pd.Series(0.0, index=dates)
        for d, v in returns_by_date.items():
            if d in daily_pnl.index:
                daily_pnl.loc[d] += v
            else:
                nearest = daily_pnl.index[daily_pnl.index >= d]
                if len(nearest):
                    daily_pnl.loc[nearest[0]] += v

        equity = self.initial_cash + daily_pnl.cumsum()
        equity.name = 'equity'
        return equity

    def summary(self, trades: pd.DataFrame) -> dict:
        """Print and return summary statistics."""
        if trades.empty:
            stats = {'n_trades': 0}
            print(stats)
            return stats

        wins = trades[trades['pnl_pct'] > 0]
        losses = trades[trades['pnl_pct'] <= 0]
        stats = {
            'n_trades': len(trades),
            'n_tickers': trades['ticker'].nunique(),
            'win_rate': len(wins) / len(trades),
            'avg_pnl_pct': trades['pnl_pct'].mean(),
            'median_pnl_pct': trades['pnl_pct'].median(),
            'avg_win_pct': wins['pnl_pct'].mean() if len(wins) else 0.0,
            'avg_loss_pct': losses['pnl_pct'].mean() if len(losses) else 0.0,
            'avg_hold_days': trades['holding_days'].mean(),
            'total_pnl_pct_sum': trades['pnl_pct'].sum(),
            'exit_reasons': trades['exit_reason'].value_counts().to_dict(),
        }

        print("=" * 60)
        print(f"Vectorized Backtest Summary ({self.start_date} -> {self.end_date})")
        print("=" * 60)
        print(f"  Trades:        {stats['n_trades']}")
        print(f"  Tickers:       {stats['n_tickers']}")
        print(f"  Win rate:      {stats['win_rate']:.2%}")
        print(f"  Avg PnL:       {stats['avg_pnl_pct']:.2%}")
        print(f"  Avg win:       {stats['avg_win_pct']:.2%}")
        print(f"  Avg loss:      {stats['avg_loss_pct']:.2%}")
        print(f"  Avg hold:      {stats['avg_hold_days']:.1f} days")
        print(f"  Exit reasons:  {stats['exit_reasons']}")
        print("=" * 60)
        return stats

    def tearsheet(
        self,
        trades: pd.DataFrame,
        benchmark: str = 'SPY',
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """Generate QuantStats tearsheet from trade results."""
        try:
            import quantstats as qs
        except ImportError:
            logger.error("quantstats not installed. Run: pip install quantstats")
            return None

        equity = self.equity_curve(trades)
        if len(equity) < 2:
            logger.warning("Insufficient equity data for tearsheet")
            return None

        returns = equity.pct_change().dropna()
        returns.index = pd.to_datetime(returns.index)
        returns.index.name = None

        if output_path:
            qs.reports.html(returns, benchmark=benchmark, output=output_path)
            logger.info(f"Tearsheet saved to {output_path}")
            return output_path

        qs.reports.html(returns, benchmark=benchmark)
        return None


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
    vbt = VectorizedSEPABacktest(
        start_date='2024-01-01',
        end_date='2024-06-30',
        min_prob_elite=0.15,
        max_positions_per_day=3,
    )
    trades = vbt.run()
    vbt.summary(trades)
