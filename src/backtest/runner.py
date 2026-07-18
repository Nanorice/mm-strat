"""
SEPA Backtest Runner
====================
Orchestrates backtest execution with BackTrader.

Handles:
- Loading and configuring data feeds
- Broker configuration (cash, commission, slippage)
- Strategy instantiation
- Analyzer attachment
- Results extraction
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import backtrader as bt
import pandas as pd

import duckdb
from src import db

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
import config

from .feeds import SEPAStockFeed, M03RegimeFeed
from .sepa_strategy import SEPAHybridV1
from .report import generate_report
from .analyzers import CalmarRatio

logger = logging.getLogger(__name__)

BACKTEST_DATA_DIR = config.DATA_DIR / 'backtest'
DEFAULT_DB_PATH = config.DATA_DIR / 'market_data.duckdb'


class SEPABacktestRunner:
    """Orchestrates SEPA backtest execution against DuckDB.

    Usage:
        runner = SEPABacktestRunner()
        runner.setup(scores_df=scores_df)
        metrics = runner.run()
        runner.print_results(metrics)
    """

    def __init__(
        self,
        start_date: str = '2020-01-01',
        end_date: str = '2025-01-01',
        initial_cash: float = 100_000,
        commission: float = 0.001,
        slippage_pct: float = 0.001,
        db_path: Optional[str] = None,
        model_path: Optional[str] = None,
        model_version_id: Optional[str] = None,
    ):
        self.start_date = pd.to_datetime(start_date)
        self.end_date = pd.to_datetime(end_date)
        self.initial_cash = initial_cash
        self.commission = commission
        self.slippage_pct = slippage_pct
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.model_path = str(model_path) if model_path else None
        self.model_name = self._derive_model_name(model_path) if model_path else None
        self.model_version_id = (
            model_version_id
            if model_version_id is not None
            else self._lookup_model_version_id(model_path) if model_path else None
        )

        self.scores_df: Optional[pd.DataFrame] = None

        self.cerebro: Optional[bt.Cerebro] = None
        self.results: Optional[List] = None
        self.strategy: Optional[SEPAHybridV1] = None
        self.regime_df: Optional[pd.DataFrame] = None

    def setup(
        self,
        scores_df: pd.DataFrame,
        max_tickers: Optional[int] = None,
        specific_tickers: List[str] = None,
        strategy_kwargs: Optional[Dict[str, Any]] = None,
    ):
        """Configure cerebro with regime feed, price feeds, strategy, analyzers.

        Args:
            scores_df: Output of UniverseScorer.score_from_t3() — columns
                       date, ticker, normalized_score, daily_pct_rank, trailing_pct, prob_elite.
            max_tickers: Cap ticker count (smoke-testing).
            specific_tickers: Restrict to this whitelist.
            strategy_kwargs: Extra keyword args passed straight through to
                SEPAHybridV1 (e.g., entry_top_n=5, min_hold_days=10). Lets
                strategy-array callers configure variants without subclassing.
        """
        self._strategy_kwargs = strategy_kwargs or {}
        logger.info("Setting up backtest (DuckDB)...")
        self.cerebro = bt.Cerebro()
        self.scores_df = scores_df

        regime_df = self._load_regime_from_duckdb()
        regime_df = self._filter_date_range(regime_df)
        regime_df = regime_df[regime_df.index.dayofweek < 5]
        self.regime_df = regime_df.copy()

        regime_feed = M03RegimeFeed(
            dataname=regime_df,
            name='regime',
            fromdate=self.start_date,
            todate=self.end_date,
        )
        self.cerebro.adddata(regime_feed, name='regime')
        logger.info(f"Added regime feed ({len(regime_df)} bars)")

        tickers = sorted(scores_df['ticker'].unique().tolist())
        if specific_tickers:
            tickers = [t for t in tickers if t in specific_tickers]
            logger.info(f"Filtered to {len(tickers)} specific tickers")
        elif max_tickers:
            tickers = tickers[:max_tickers]
            logger.info(f"Limited to {max_tickers} tickers")

        if not tickers:
            raise ValueError("No qualifying tickers in scores_df")

        self._add_price_feeds_from_duckdb(tickers)

        self.cerebro.broker.setcash(self.initial_cash)
        self.cerebro.broker.setcommission(commission=self.commission)
        self.cerebro.broker.set_slippage_perc(perc=self.slippage_pct)
        logger.info("Setup complete")

    setup_from_duckdb = setup

    def _load_regime_from_duckdb(self) -> pd.DataFrame:
        """Load regime data from t2_regime_scores table."""
        con = db.connect(str(self.db_path), read_only=True)
        try:
            df = con.execute("""
                SELECT
                    date,
                    CASE
                        WHEN m03_score >= 75 THEN 4
                        WHEN m03_score >= 55 THEN 3
                        WHEN m03_score >= 35 THEN 2
                        WHEN m03_score >= 15 THEN 1
                        ELSE 0
                    END AS regime_cat,
                    m03_score AS composite_score,
                    m03_pillar_trend AS trend_pillar,
                    m03_pillar_liq AS liq_pillar,
                    m03_pillar_risk AS risk_pillar
                FROM t2_regime_scores
                ORDER BY date
            """).fetchdf()
        finally:
            con.close()

        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        logger.info(f"Loaded {len(df)} regime rows from DuckDB")
        return df

    def _add_price_feeds_from_duckdb(self, tickers: List[str]):
        """Load stock price feeds directly from DuckDB price_data table."""
        start_str = self.start_date.strftime('%Y-%m-%d')
        end_str = self.end_date.strftime('%Y-%m-%d')
        late_start_cutoff = self.start_date + pd.Timedelta(days=60)

        con = db.connect(str(self.db_path), read_only=True)
        try:
            placeholders = ','.join([f"'{t}'" for t in tickers])
            df_all = con.execute(f"""
                SELECT date, ticker,
                       CAST(open AS DOUBLE) AS open,
                       CAST(high AS DOUBLE) AS high,
                       CAST(low AS DOUBLE) AS low,
                       CAST(close AS DOUBLE) AS close,
                       CAST(volume AS BIGINT) AS volume
                FROM price_data
                WHERE ticker IN ({placeholders})
                  AND date >= ?
                  AND date <= ?
                ORDER BY ticker, date
            """, [start_str, end_str]).fetchdf()
        finally:
            con.close()

        df_all['date'] = pd.to_datetime(df_all['date'])
        logger.info(f"Loaded {len(df_all)} price rows for {df_all['ticker'].nunique()} tickers from DuckDB")

        loaded_count = 0
        skipped_late = 0

        for ticker, df in df_all.groupby('ticker'):
            df = df.set_index('date').drop(columns=['ticker']).sort_index()

            if df.index.min() > late_start_cutoff:
                skipped_late += 1
                continue

            if len(df) < 50:
                continue

            # ATR-14 inline (lowercase columns from DuckDB)
            tr = pd.concat([
                df['high'] - df['low'],
                (df['high'] - df['close'].shift(1)).abs(),
                (df['low'] - df['close'].shift(1)).abs(),
            ], axis=1).max(axis=1)
            df['atr_14'] = tr.ewm(span=14, adjust=False).mean()
            df = df.dropna(subset=['atr_14'])

            if len(df) < 50:
                continue

            feed = SEPAStockFeed(
                dataname=df,
                name=ticker,
                fromdate=self.start_date,
                todate=self.end_date,
            )
            self.cerebro.adddata(feed, name=ticker)
            loaded_count += 1

        if skipped_late > 0:
            logger.info(f"Skipped {skipped_late} late-starting tickers")
        logger.info(f"Added {loaded_count} stock feeds from DuckDB")

        # === ADD STRATEGY ===
        self.cerebro.addstrategy(
            SEPAHybridV1,
            scores_df=self.scores_df,
            **self._strategy_kwargs,
        )

        # === ADD ANALYZERS ===
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                                  timeframe=bt.TimeFrame.Days, annualize=True)
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        self.cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
        self.cerebro.addanalyzer(CalmarRatio, _name='calmar')

        logger.info(f"Broker: cash=${self.initial_cash:,.0f}, "
                   f"commission={self.commission*100:.2f}%, slippage={self.slippage_pct*100:.1f}%")

    def _filter_date_range(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter DataFrame to backtest date range."""
        if df.index.name != 'date':
            df = df.set_index('date')
        df.index = pd.to_datetime(df.index)
        return df[(df.index >= self.start_date) & (df.index <= self.end_date)]

    def run(self) -> Dict[str, Any]:
        """
        Execute the backtest.

        Returns:
            Dict with backtest results and metrics
        """
        if self.cerebro is None:
            raise RuntimeError("Call setup() before run()")

        logger.info(f"Running backtest: {self.start_date.date()} to {self.end_date.date()}")

        starting_value = self.cerebro.broker.getvalue()
        self.results = self.cerebro.run()
        self.strategy = self.results[0]
        ending_value = self.cerebro.broker.getvalue()

        # Extract metrics
        metrics = self._extract_metrics()
        metrics['starting_value'] = starting_value
        metrics['ending_value'] = ending_value
        metrics['total_return'] = (ending_value - starting_value) / starting_value * 100

        logger.info(f"Backtest complete. Final value: ${ending_value:,.2f} "
                   f"({metrics['total_return']:+.1f}%)")

        return metrics

    def _extract_metrics(self) -> Dict[str, Any]:
        """Extract metrics from analyzers."""
        if self.strategy is None:
            return {}

        metrics = {}

        # Sharpe Ratio
        try:
            sharpe = self.strategy.analyzers.sharpe.get_analysis()
            metrics['sharpe_ratio'] = sharpe.get('sharperatio', None)
        except Exception:
            metrics['sharpe_ratio'] = None

        # Drawdown
        try:
            dd = self.strategy.analyzers.drawdown.get_analysis()
            metrics['max_drawdown'] = dd.get('max', {}).get('drawdown', 0)
            metrics['max_drawdown_len'] = dd.get('max', {}).get('len', 0)
        except Exception:
            metrics['max_drawdown'] = None
            metrics['max_drawdown_len'] = None

        # Trade Analysis
        try:
            trades = self.strategy.analyzers.trades.get_analysis()
            metrics['total_trades'] = trades.get('total', {}).get('total', 0)
            metrics['won_trades'] = trades.get('won', {}).get('total', 0)
            metrics['lost_trades'] = trades.get('lost', {}).get('total', 0)

            if metrics['total_trades'] > 0:
                metrics['win_rate'] = metrics['won_trades'] / metrics['total_trades'] * 100
            else:
                metrics['win_rate'] = 0

            # PnL
            pnl = trades.get('pnl', {})
            metrics['gross_profit'] = pnl.get('gross', {}).get('total', 0)
            metrics['net_profit'] = pnl.get('net', {}).get('total', 0)
        except Exception:
            metrics['total_trades'] = 0
            metrics['win_rate'] = 0

        # Returns
        try:
            returns = self.strategy.analyzers.returns.get_analysis()
            metrics['avg_return'] = returns.get('ravg', 0) * 100
        except Exception:
            metrics['avg_return'] = None

        # SQN (System Quality Number)
        try:
            sqn = self.strategy.analyzers.sqn.get_analysis()
            metrics['sqn'] = sqn.get('sqn', None)
        except Exception:
            metrics['sqn'] = None

        # Calmar Ratio
        try:
            calmar = self.strategy.analyzers.calmar.get_analysis()
            metrics['calmar_ratio'] = calmar.get('calmar_ratio', None)
            metrics['annualized_return'] = calmar.get('annualized_return', None)
        except Exception:
            metrics['calmar_ratio'] = None
            metrics['annualized_return'] = None

        # Position tracker stats
        try:
            tracker_stats = self.strategy.position_tracker.get_stats()
            metrics['tracker_stats'] = tracker_stats
        except Exception:
            metrics['tracker_stats'] = {}

        # Exposure stats
        try:
            exposure_stats = self.strategy.get_exposure_stats()
            metrics['exposure_stats'] = exposure_stats
        except Exception:
            metrics['exposure_stats'] = {}

        # Signal rejection stats
        try:
            rejection_stats = self.strategy.get_signal_rejection_stats()
            metrics['rejection_stats'] = rejection_stats
        except Exception:
            metrics['rejection_stats'] = {}

        return metrics

    def get_equity_curve_dataframe(self) -> Optional[pd.DataFrame]:
        """
        Get daily equity curve as DataFrame.

        Returns:
            DataFrame with date index and columns: value, cash, position_value, position_count, regime
        """
        if self.strategy is None:
            return None

        snapshots = self.strategy.daily_snapshots
        if not snapshots:
            return None

        records = []
        for snap in snapshots:
            records.append({
                'date': snap.date,
                'value': snap.portfolio_value,
                'cash': snap.cash,
                'position_value': snap.position_value,
                'position_count': snap.position_count,
                'regime': snap.regime,
            })

        df = pd.DataFrame(records)
        df['date'] = pd.to_datetime(df['date'])
        return df.set_index('date')

    def get_trade_dataframe(self) -> Optional[pd.DataFrame]:
        """
        Convert closed positions to DataFrame for report generation.
        Includes max_dd_pct (Maximum Drawdown from peak during trade) and mae_pct (Maximum Adverse Excursion from entry).

        Returns:
            DataFrame with trade details or None if no strategy run yet
        """
        if self.strategy is None:
            return None

        closed = self.strategy.position_tracker.closed_positions
        if not closed:
            return None

        scores_idx = None
        if hasattr(self, 'scores_df') and self.scores_df is not None:
            if not isinstance(self.scores_df.index, pd.MultiIndex):
                scores_idx = self.scores_df.set_index(['ticker', 'date'])
            else:
                scores_idx = self.scores_df

        records = []
        for pos in closed:
            max_dd_pct = 0.0
            mae_pct = 0.0
            
            if pos.entry_date and pos.exit_date:
                feed = self.cerebro.datasbyname.get(pos.ticker)
                if feed is not None and hasattr(feed.p, 'dataname'):
                    df = feed.p.dataname
                    mask = (df.index >= pd.Timestamp(pos.entry_date)) & (df.index <= pd.Timestamp(pos.exit_date))
                    trade_df = df[mask]
                    if not trade_df.empty and pos.entry_price > 0:
                        cummax = trade_df['high'].cummax()
                        dd = (trade_df['low'] - cummax) / cummax
                        max_dd_pct = dd.min() * 100
                        mae_pct = ((trade_df['low'].min() - pos.entry_price) / pos.entry_price) * 100

            record = {
                'ticker': pos.ticker,
                'entry_date': pos.entry_date,
                'entry_price': pos.entry_price,
                'exit_date': pos.exit_date,
                'exit_price': pos.exit_price,
                'exit_reason': pos.exit_reason,
                'entry_regime': pos.regime,
                'entry_score': pos.score,
                'initial_size': pos.initial_size,
                'pnl_percent': pos.pnl_percent,
                'holding_days': (pos.exit_date - pos.entry_date).days if pos.exit_date and pos.entry_date else 0,
                'max_dd_pct': max_dd_pct,
                'mae_pct': mae_pct,
            }
            
            if pos.entry_date and scores_idx is not None:
                idx_key = (pos.ticker, pd.Timestamp(pos.entry_date))
                if idx_key in scores_idx.index:
                    row_series = scores_idx.loc[idx_key]
                    if isinstance(row_series, pd.DataFrame):
                        row_series = row_series.iloc[0]
                    for k, v in row_series.to_dict().items():
                        if k not in record:  # Do not overwrite calculated trade metrics
                            record[k] = v
                            
            records.append(record)

        return pd.DataFrame(records)

    def get_daily_holding_dataframe(self) -> Optional[pd.DataFrame]:
        """
        Get time series of price and score changes for every day a position was held.
        
        Returns:
            DataFrame with columns: ticker, entry_date, date, days_held, close, pct_change_from_entry, m01_score, trailing_pct
        """
        if self.strategy is None:
            return None

        closed = self.strategy.position_tracker.closed_positions
        if not closed:
            return None

        scores_idx = None
        if hasattr(self, 'scores_df') and self.scores_df is not None:
            if not isinstance(self.scores_df.index, pd.MultiIndex):
                scores_idx = self.scores_df.set_index(['ticker', 'date'])
            else:
                scores_idx = self.scores_df

        all_daily_records = []
        for pos in closed:
            if not pos.entry_date or not pos.exit_date:
                continue
                
            feed = self.cerebro.datasbyname.get(pos.ticker)
            if feed is not None and hasattr(feed.p, 'dataname'):
                df = feed.p.dataname
                mask = (df.index >= pd.Timestamp(pos.entry_date)) & (df.index <= pd.Timestamp(pos.exit_date))
                trade_df = df[mask]
                
                if trade_df.empty or pos.entry_price == 0:
                    continue
                
                days_held = 0
                for date, row in trade_df.iterrows():
                    m01_score = None
                    trailing_pct = None
                    if scores_idx is not None:
                        idx_key = (pos.ticker, pd.Timestamp(date))
                        if idx_key in scores_idx.index:
                            score_row = scores_idx.loc[idx_key]
                            if isinstance(score_row, pd.DataFrame):
                                score_row = score_row.iloc[0]
                            m01_score = score_row.get('normalized_score')
                            trailing_pct = score_row.get('trailing_pct')
                            
                    pct_change = (row['close'] - pos.entry_price) / pos.entry_price * 100
                    
                    all_daily_records.append({
                        'ticker': pos.ticker,
                        'entry_date': pos.entry_date,
                        'date': date,
                        'days_held': days_held,
                        'close': row['close'],
                        'pct_change_from_entry': pct_change,
                        'm01_score': m01_score,
                        'trailing_pct': trailing_pct
                    })
                    days_held += 1
                    
        if not all_daily_records:
            return pd.DataFrame()
            
        return pd.DataFrame(all_daily_records)

    def save_report(self, metrics: Dict[str, Any], run_dir: Path = None) -> str:
        """
        Generate and save markdown report.

        Args:
            metrics: Dict from run() with backtest metrics
            run_dir: Directory to save report (saves as report.md)

        Returns:
            Path to saved report
        """
        if run_dir is None:
            run_dir = BACKTEST_DATA_DIR / 'reports'

        run_dir.mkdir(parents=True, exist_ok=True)
        report_path = run_dir / 'report.md'

        trade_df = self.get_trade_dataframe()
        equity_curve = self.get_equity_curve_dataframe()

        # Extract strategy params if available
        strategy_params = {}
        if self.strategy is not None:
            strategy_params = {
                'min_score': self.strategy.p.min_score,
                'min_percentile': self.strategy.p.entry_percentile_min,
                'rank_by': self.strategy.p.rank_by,
                'min_price': self.strategy.p.min_price,
                'cooldown_days': self.strategy.p.cooldown_days,
                'atr_stop_mult': self.strategy.p.atr_stop_mult,
                'max_stop_pct': self.strategy.p.max_stop_pct,
                'atr_target1_mult': self.strategy.p.atr_target1_mult,
                'min_target1_pct': self.strategy.p.min_target1_pct,
                'atr_target2_add': self.strategy.p.atr_target2_add,
                'sma_exit_period': self.strategy.p.sma_exit_period,
            }

        generate_report(
            metrics=metrics,
            trade_df=trade_df,
            equity_curve=equity_curve,
            output_path=str(report_path),
            start_date=str(self.start_date.date()),
            end_date=str(self.end_date.date()),
            initial_cash=self.initial_cash,
            strategy_params=strategy_params,
        )

        return str(report_path)

    @staticmethod
    def _sanitize_run_name(run_note: str) -> str:
        """Sanitize run note to valid folder name."""
        folder_name = run_note.lower().replace(' ', '_').replace('-', '_')
        return ''.join(c for c in folder_name if c.isalnum() or c == '_')[:50]

    def get_run_dir_path(self, run_note: str) -> Path:
        """Get the path for a run directory (may or may not exist)."""
        if run_note:
            folder_name = self._sanitize_run_name(run_note)
        else:
            folder_name = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
        return BACKTEST_DATA_DIR / folder_name

    def create_run_dir(self, run_note: str = "", overwrite: bool = False) -> Path:
        """
        Create a run directory for saving all backtest artifacts.

        Args:
            run_note: Name for the run folder (e.g., "baseline_v1")
            overwrite: If True, clear existing directory contents

        Returns:
            Path to the created run directory
        """
        run_dir = self.get_run_dir_path(run_note)

        if run_dir.exists() and overwrite:
            import shutil
            shutil.rmtree(run_dir)
            logger.info(f"Cleared existing run directory: {run_dir}")

        run_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created run directory: {run_dir}")
        return run_dir

    def save_run(self, metrics: Dict[str, Any], run_dir: Path = None, run_note: str = "",
                 strategy_name: Optional[str] = None) -> Path:
        """
        Save structured backtest run for dashboard visualization.

        Creates a run directory with:
        - manifest.json: Parameters, artifact links, summary metrics
        - equity_curve.parquet: Daily portfolio state
        - trades.parquet: All closed trades
        - metrics.json: Pre-computed analytics for charts
        - plot.png: the 6-panel diagnostic (Backtest Studio renders it inline)

        Args:
            metrics: Dict from run() with backtest metrics
            run_dir: Directory to save to (if None, creates one)
            run_note: Optional name for run folder (used if run_dir is None)
            strategy_name: registry key (e.g. "champion") — tags the manifest with the
                registry fingerprint + description so the dashboard can label the run.

        Returns:
            Path to the run directory
        """
        if run_dir is None:
            run_dir = self.create_run_dir(run_note)
        else:
            run_dir.mkdir(parents=True, exist_ok=True)

        run_id = run_dir.name
        logger.info(f"Saving backtest run to: {run_dir}")

        # 1. Save equity curve
        equity_df = self.get_equity_curve_dataframe()
        if equity_df is not None:
            equity_df.to_parquet(run_dir / 'equity_curve.parquet')
            logger.info(f"  - equity_curve.parquet ({len(equity_df)} rows)")

        # 2. Save trades
        trade_df = self.get_trade_dataframe()
        if trade_df is not None:
            trade_df.to_parquet(run_dir / 'trades.parquet')
            logger.info(f"  - trades.parquet ({len(trade_df)} rows)")

        # 3. Build and save metrics.json with pre-computed analytics
        metrics_extended = self._build_extended_metrics(metrics, equity_df, trade_df)
        with open(run_dir / 'metrics.json', 'w') as f:
            json.dump(metrics_extended, f, indent=2, default=str)
        logger.info("  - metrics.json")

        # 4. Save the 6-panel diagnostic PNG (the chart Backtest Studio renders inline)
        try:
            self.plot(save_path=str(run_dir / 'plot.png'))
            logger.info("  - plot.png")
        except Exception as e:  # plotting is cosmetic — never fail a save over it
            logger.warning(f"  - plot.png skipped ({e})")

        # 5. Build and save manifest.json
        manifest = self._build_manifest(run_id, metrics, strategy_name=strategy_name)
        with open(run_dir / 'manifest.json', 'w') as f:
            json.dump(manifest, f, indent=2, default=str)
        logger.info("  - manifest.json")

        logger.info(f"Run saved: {run_id}")
        return run_dir

    def _build_extended_metrics(
        self,
        metrics: Dict[str, Any],
        equity_df: Optional[pd.DataFrame],
        trade_df: Optional[pd.DataFrame]
    ) -> Dict[str, Any]:
        """Build extended metrics dict with pre-computed analytics for dashboard."""
        result = {**metrics}

        # Monthly returns (for heatmap)
        if equity_df is not None and len(equity_df) > 0:
            monthly_returns = self._compute_monthly_returns(equity_df)
            result['monthly_returns'] = monthly_returns

        # Regime performance (for bar chart)
        if trade_df is not None and len(trade_df) > 0:
            regime_perf = self._compute_regime_performance(trade_df)
            result['regime_performance'] = regime_perf

            # Exit reasons (for pie chart)
            exit_reasons = trade_df['exit_reason'].value_counts().to_dict()
            result['exit_reasons'] = exit_reasons

        return result

    def _compute_monthly_returns(self, equity_df: pd.DataFrame) -> List[Dict]:
        """Compute monthly returns from equity curve."""
        df = equity_df.copy()
        df['year'] = df.index.year
        df['month'] = df.index.month

        # Get first and last value per month
        monthly = df.groupby(['year', 'month'])['value'].agg(['first', 'last'])
        monthly['return'] = (monthly['last'] - monthly['first']) / monthly['first'] * 100

        records = []
        for (year, month), row in monthly.iterrows():
            records.append({
                'year': int(year),
                'month': int(month),
                'return': round(row['return'], 2)
            })
        return records

    def _compute_regime_performance(self, trade_df: pd.DataFrame) -> List[Dict]:
        """Compute average PnL by entry regime."""
        regime_names = {0: 'Strong Bear', 1: 'Bear', 2: 'Neutral', 3: 'Bull', 4: 'Strong Bull'}

        stats = trade_df.groupby('entry_regime')['pnl_percent'].agg(['mean', 'count'])

        records = []
        for regime, row in stats.iterrows():
            records.append({
                'regime': int(regime),
                'regime_name': regime_names.get(regime, f'R{regime}'),
                'avg_pnl': round(row['mean'], 2),
                'count': int(row['count'])
            })
        return records

    @staticmethod
    def _derive_model_name(model_path: str) -> Optional[str]:
        """Extract model family name from a path like models/<name>/<version>/model.json."""
        parts = Path(model_path).parts
        if 'models' in parts:
            i = parts.index('models')
            if i + 1 < len(parts):
                return parts[i + 1]
        return None

    def _lookup_model_version_id(self, model_path: str) -> Optional[str]:
        """Resolve model_version_id from the registry by matching the parent dir
        of model_path against models.artifacts_path. Falls back to <name>/<version-dir>
        derived from the path when no registry row matches."""
        parent_dir = Path(model_path).parent
        try:
            con = db.connect(str(self.db_path), read_only=True)
            try:
                rows = con.execute(
                    "SELECT version_id, artifacts_path FROM models"
                ).fetchall()
            finally:
                con.close()
        except Exception as e:
            logger.warning(f"Registry lookup failed ({e}); using path-derived id")
            rows = []

        parent_resolved = parent_dir.resolve()
        for version_id, artifacts_path in rows:
            if not artifacts_path:
                continue
            try:
                if Path(artifacts_path).resolve() == parent_resolved:
                    return version_id
            except OSError:
                continue

        # Fallback: <name>/<version-dir>, e.g. "m01_prototype_2003_2026/v1"
        if self.model_name and parent_dir.name:
            fallback = f"{self.model_name}/{parent_dir.name}"
            logger.info(f"No registry match for {model_path}; using {fallback}")
            return fallback
        return None

    def _build_manifest(self, run_id: str, metrics: Dict[str, Any],
                        strategy_name: Optional[str] = None) -> Dict[str, Any]:
        """Build manifest with parameters, artifact links, and summary metrics.

        If strategy_name matches a registry entry, tag the manifest with its
        fingerprint + description so the dashboard can label the run in plain English.
        """
        # Extract strategy params
        strategy_params = {}
        if self.strategy is not None:
            strategy_params = {
                'min_score': self.strategy.p.min_score,
                'min_percentile': self.strategy.p.entry_percentile_min,
                'atr_stop_mult': self.strategy.p.atr_stop_mult,
                'atr_target1_mult': self.strategy.p.atr_target1_mult,
                'max_stop_pct': self.strategy.p.max_stop_pct,
                'cooldown_days': self.strategy.p.cooldown_days,
            }

        strategy_class = (
            type(self.strategy).__name__ if self.strategy is not None
            else 'SEPAHybridV1'
        )

        # Registry tag: fingerprint + human description for the named strategy.
        fingerprint, description = None, None
        if strategy_name:
            try:
                from src.backtest import strategy_registry as reg
                d = reg.get(strategy_name)
                fingerprint, description = d.fingerprint, d.description
                strategy_class = d.name
            except (KeyError, ImportError) as e:
                logger.warning(f"Registry lookup for {strategy_name!r} failed: {e}")

        return {
            'manifest_version': 'v1',
            'run_id': run_id,
            'created_at': pd.Timestamp.now().isoformat(),
            'engine': 'BackTrader',
            'strategy': strategy_class,
            'fingerprint': fingerprint,
            'description': description,
            'model': {
                'name': self.model_name,
                'version_id': self.model_version_id,
                'path': self.model_path,
            },
            'params': {
                'start_date': str(self.start_date.date()),
                'end_date': str(self.end_date.date()),
                'initial_cash': self.initial_cash,
                'commission': self.commission,
                'slippage_pct': self.slippage_pct,
                **strategy_params
            },
            'summary_metrics': {
                'total_return': round(metrics.get('total_return', 0), 2),
                'sharpe_ratio': round(metrics.get('sharpe_ratio') or 0, 2),
                'max_drawdown': round(metrics.get('max_drawdown', 0), 2),
                'total_trades': metrics.get('total_trades', 0),
                'win_rate': round(metrics.get('win_rate', 0), 1),
                'net_profit': round(metrics.get('net_profit', 0), 2),
            }
        }

    def print_results(self, metrics: Optional[Dict] = None):
        """Print formatted backtest results."""
        if metrics is None:
            metrics = self._extract_metrics()

        print("\n" + "=" * 60)
        print("SEPA HYBRID V1 BACKTEST RESULTS")
        print("=" * 60)

        print(f"\nPeriod: {self.start_date.date()} to {self.end_date.date()}")
        print(f"Starting Capital: ${self.initial_cash:,.0f}")

        print("\n--- PERFORMANCE ---")
        print(f"Final Value:     ${metrics.get('ending_value', 0):,.2f}")
        print(f"Total Return:    {metrics.get('total_return', 0):+.2f}%")
        print(f"Sharpe Ratio:    {metrics.get('sharpe_ratio', 'N/A')}")
        print(f"SQN:             {metrics.get('sqn', 'N/A')}")

        print("\n--- RISK ---")
        print(f"Max Drawdown:    {metrics.get('max_drawdown', 0):.2f}%")
        print(f"Max DD Length:   {metrics.get('max_drawdown_len', 0)} bars")

        print("\n--- TRADES ---")
        print(f"Total Trades:    {metrics.get('total_trades', 0)}")
        print(f"Win Rate:        {metrics.get('win_rate', 0):.1f}%")
        print(f"Won/Lost:        {metrics.get('won_trades', 0)}/{metrics.get('lost_trades', 0)}")
        print(f"Net Profit:      ${metrics.get('net_profit', 0):,.2f}")

        # Exposure stats
        exposure = metrics.get('exposure_stats', {})
        if exposure:
            print("\n--- EXPOSURE ---")
            print(f"Avg Exposure:    {exposure.get('avg_exposure', 0):.1f}%")
            print(f"Max Exposure:    {exposure.get('max_exposure', 0):.1f}%")
            print(f"Time Invested:   {exposure.get('time_invested', 0):.1f}%")
            print(f"Avg Positions:   {exposure.get('avg_positions', 0):.1f}")

        # Signal rejection stats
        rejections = metrics.get('rejection_stats', {})
        if rejections and rejections.get('total_rejections', 0) > 0:
            print("\n--- SIGNAL REJECTIONS ---")
            print(f"Total Rejected:  {rejections['total_rejections']:,}")
            by_reason = rejections.get('by_reason', {})
            top_reasons = sorted(by_reason.items(), key=lambda x: -x[1])[:3]
            for reason, count in top_reasons:
                print(f"  - {reason}: {count:,}")

        print("\n" + "=" * 60)

    def plot(self, save_path: Optional[str] = None, **kwargs):
        """
        Plot comprehensive backtest results with diagnostics.

        Generates a 3x2 panel with:
        1. Equity curve with regime overlay
        2. Underwater (drawdown) plot
        3. Monthly returns heatmap
        4. PnL distribution
        5. Performance by regime
        6. Exit reason breakdown

        Args:
            save_path: If provided, save plot to this path instead of displaying
        """
        if self.strategy is None:
            raise RuntimeError("No backtest to plot. Run backtest first.")

        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            from matplotlib.patches import Patch
        except ImportError:
            logger.error("matplotlib required for plotting. Install with: pip install matplotlib")
            return

        # Get closed trades for analysis
        trade_df = self.get_trade_dataframe()
        if trade_df is None or len(trade_df) == 0:
            logger.warning("No closed trades to plot")
            return

        fig, axes = plt.subplots(3, 2, figsize=(16, 14))
        fig.suptitle('SEPA Hybrid V1 Backtest Results', fontsize=14, fontweight='bold')

        trade_df_sorted = trade_df.sort_values('exit_date').copy()
        trade_df_sorted['exit_date'] = pd.to_datetime(trade_df_sorted['exit_date'])
        trade_df_sorted['cumulative_pnl'] = trade_df_sorted['pnl_percent'].cumsum()

        # === 1. EQUITY CURVE WITH REGIME OVERLAY ===
        ax1 = axes[0, 0]
        self._plot_equity_with_regime(ax1, trade_df_sorted)

        # === 2. UNDERWATER (DRAWDOWN) PLOT ===
        ax2 = axes[0, 1]
        self._plot_underwater(ax2, trade_df_sorted)

        # === 3. MONTHLY RETURNS HEATMAP ===
        ax3 = axes[1, 0]
        self._plot_monthly_heatmap(ax3, trade_df_sorted)

        # === 4. PNL DISTRIBUTION ===
        ax4 = axes[1, 1]
        colors = ['green' if x > 0 else 'red' for x in trade_df_sorted['pnl_percent']]
        ax4.bar(range(len(trade_df_sorted)), trade_df_sorted['pnl_percent'], color=colors, alpha=0.7)
        ax4.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax4.axhline(y=-10, color='red', linestyle='--', linewidth=1, alpha=0.7, label='10% Hard Stop')
        ax4.set_title('Individual Trade PnL %')
        ax4.set_xlabel('Trade #')
        ax4.set_ylabel('PnL %')
        ax4.legend(loc='lower left')
        ax4.grid(True, alpha=0.3)

        # === 5. PERFORMANCE BY REGIME ===
        ax5 = axes[2, 0]
        regime_names = {0: 'Strong Bear', 1: 'Bear', 2: 'Neutral', 3: 'Bull', 4: 'Strong Bull'}
        regime_stats = trade_df.groupby('entry_regime')['pnl_percent'].agg(['mean', 'count'])
        regime_labels = [regime_names.get(r, f'R{r}') for r in regime_stats.index]
        bars = ax5.bar(regime_labels, regime_stats['mean'], color='steelblue', alpha=0.7)
        ax5.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax5.set_title('Avg PnL % by Entry Regime')
        ax5.set_ylabel('Avg PnL %')
        for bar, count in zip(bars, regime_stats['count']):
            ax5.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                    f'n={int(count)}', ha='center', va='bottom', fontsize=9)
        ax5.grid(True, alpha=0.3)

        # === 6. EXIT REASON BREAKDOWN ===
        ax6 = axes[2, 1]
        exit_counts = trade_df['exit_reason'].value_counts()
        colors_exit = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#ffeaa7', '#dfe6e9']
        ax6.pie(exit_counts.values, labels=exit_counts.index, autopct='%1.1f%%',
                colors=colors_exit[:len(exit_counts)])
        ax6.set_title('Exit Reasons')

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            logger.info(f"Plot saved to {save_path}")
            plt.close(fig)
        else:
            plt.show()

    def generate_tearsheet(
        self,
        benchmark: str = 'SPY',
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate interactive QuantStats HTML tearsheet from the equity curve.

        Args:
            benchmark: Benchmark ticker (default: SPY).
            output_path: If provided, save HTML to file. If None, render inline.

        Returns:
            Path to saved HTML, or None if displayed inline / unavailable.
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

        equity_df = equity_df.copy()
        equity_df['date'] = pd.to_datetime(equity_df['date'])
        equity_df = equity_df.set_index('date').sort_index()
        returns = equity_df['value'].pct_change().dropna()
        returns.index.name = None

        if output_path:
            qs.reports.html(returns, benchmark=benchmark, output=output_path)
            logger.info(f"Tearsheet saved to {output_path}")
            return output_path

        qs.reports.html(returns, benchmark=benchmark)
        return None

    def _plot_equity_with_regime(self, ax, trade_df: pd.DataFrame):
        """Plot equity curve with regime background colors."""
        from matplotlib.patches import Patch

        # Plot cumulative PnL
        ax.plot(trade_df['exit_date'], trade_df['cumulative_pnl'], 'b-', linewidth=1.5, zorder=3)
        ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5, zorder=2)

        # Add regime overlay if available
        if self.regime_df is not None and len(self.regime_df) > 0:
            regime_colors = {
                0: '#ffcccc',  # Strong Bear - light red
                1: '#ffe6cc',  # Bear - light orange
                2: '#ffffcc',  # Neutral - light yellow
                3: '#ccffcc',  # Bull - light green
                4: '#ccffdd',  # Strong Bull - bright green
            }

            dates = self.regime_df.index.to_pydatetime()
            regimes = self.regime_df['regime_cat'].values

            # Create regime spans
            i = 0
            while i < len(dates) - 1:
                regime = regimes[i]
                start = dates[i]
                # Find end of this regime period
                j = i + 1
                while j < len(dates) and regimes[j] == regime:
                    j += 1
                end = dates[j - 1] if j < len(dates) else dates[-1]

                ax.axvspan(start, end, alpha=0.3, color=regime_colors.get(regime, 'white'), zorder=1)
                i = j

            # Legend for regimes
            legend_elements = [
                Patch(facecolor='#ffcccc', alpha=0.5, label='Strong Bear'),
                Patch(facecolor='#ffe6cc', alpha=0.5, label='Bear'),
                Patch(facecolor='#ffffcc', alpha=0.5, label='Neutral'),
                Patch(facecolor='#ccffcc', alpha=0.5, label='Bull'),
                Patch(facecolor='#ccffdd', alpha=0.5, label='Strong Bull'),
            ]
            ax.legend(handles=legend_elements, loc='upper left', fontsize=7)

        ax.set_title('Equity Curve with Regime Overlay')
        ax.set_xlabel('Date')
        ax.set_ylabel('Cumulative PnL %')
        ax.grid(True, alpha=0.3, zorder=0)

    def _plot_underwater(self, ax, trade_df: pd.DataFrame):
        """Plot underwater (drawdown) chart."""
        cumulative = trade_df['cumulative_pnl'].values
        running_max = pd.Series(cumulative).cummax().values
        drawdown = cumulative - running_max

        ax.fill_between(trade_df['exit_date'], 0, drawdown, color='red', alpha=0.5)
        ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax.set_title('Underwater Plot (Drawdown from Peak)')
        ax.set_xlabel('Date')
        ax.set_ylabel('Drawdown %')
        ax.grid(True, alpha=0.3)

        # Annotate max drawdown
        min_dd = drawdown.min()
        min_dd_idx = drawdown.argmin()
        min_dd_date = trade_df['exit_date'].iloc[min_dd_idx]
        ax.annotate(f'Max DD: {min_dd:.1f}%',
                   xy=(min_dd_date, min_dd),
                   xytext=(10, 10), textcoords='offset points',
                   fontsize=9, color='red',
                   arrowprops=dict(arrowstyle='->', color='red', lw=0.5))

    def _plot_monthly_heatmap(self, ax, trade_df: pd.DataFrame):
        """Plot monthly returns heatmap."""
        # Group by year-month
        trade_df = trade_df.copy()
        trade_df['exit_date'] = pd.to_datetime(trade_df['exit_date'])
        trade_df['year'] = trade_df['exit_date'].dt.year
        trade_df['month'] = trade_df['exit_date'].dt.month

        monthly = trade_df.groupby(['year', 'month'])['pnl_percent'].sum().unstack(fill_value=0)

        # Create heatmap
        import numpy as np

        if len(monthly) == 0:
            ax.text(0.5, 0.5, 'Insufficient data for heatmap',
                   ha='center', va='center', transform=ax.transAxes)
            ax.set_title('Monthly Returns Heatmap')
            return

        im = ax.imshow(monthly.values, cmap='RdYlGn', aspect='auto',
                      vmin=-10, vmax=10)

        # Labels
        month_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

        ax.set_xticks(range(len(monthly.columns)))
        ax.set_xticklabels([month_labels[m-1] for m in monthly.columns], fontsize=8)
        ax.set_yticks(range(len(monthly.index)))
        ax.set_yticklabels(monthly.index, fontsize=8)

        # Add text annotations
        for i in range(len(monthly.index)):
            for j in range(len(monthly.columns)):
                val = monthly.iloc[i, j]
                color = 'white' if abs(val) > 5 else 'black'
                ax.text(j, i, f'{val:.1f}', ha='center', va='center',
                       fontsize=7, color=color)

        ax.set_title('Monthly Returns Heatmap (%)')
        import matplotlib.pyplot as plt
        plt.colorbar(im, ax=ax, shrink=0.8)


def run_backtest(
    start_date: str = '2020-01-01',
    end_date: str = '2025-01-01',
    initial_cash: float = 100_000,
    max_tickers: Optional[int] = None,
    save_results: bool = False,
    run_note: str = "",
    m01_path: str = 'models/m01_prototype/model.json',
) -> Dict[str, Any]:
    """Score universe from T3 then run backtest end-to-end."""
    from .universe_scorer import UniverseScorer

    scorer = UniverseScorer(m01_path=m01_path)
    scores_df = scorer.score_from_t3(start_date, end_date)

    runner = SEPABacktestRunner(
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
    )
    runner.setup(scores_df=scores_df, max_tickers=max_tickers)
    metrics = runner.run()
    runner.print_results(metrics)

    if save_results:
        runner.save_run(metrics, run_note=run_note)

    return metrics


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    run_backtest(save_results=True, run_note="cli_run")
