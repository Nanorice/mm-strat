"""
Main Backtest Script
Runs historical backtest of SEPA strategy and generates performance report.
"""

import pandas as pd
import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.data_engine import DataRepository
from src.strategy import SEPAStrategy
from src.backtester import BacktestEngine, PortfolioManager
from src.reporting import PerformanceReporter
import logging

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_backtest(tickers_subset: int = None, save_report: bool = True):
    """
    Main backtest routine.

    Args:
        tickers_subset: Optional limit on number of tickers (for testing)
        save_report: If True, saves HTML report
    """
    print("=" * 80)
    print(f" SEPA STRATEGY BACKTEST | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)

    # Initialize components
    data_repo = DataRepository()

    # Step 1: Get Universe
    print("\n[1/6] Fetching S&P 500 Universe...")
    tickers = data_repo.update_universe()

    # Optionally limit tickers for faster testing
    if tickers_subset:
        tickers = tickers[:tickers_subset]
        print(f"       Using subset: {len(tickers)} tickers (for testing)")
    else:
        print(f"       Loaded {len(tickers)} tickers")

    # Step 2: Update Cache
    print("\n[2/6] Updating Price Data Cache...")
    results = data_repo.update_cache(tickers, force=False)
    success_count = sum(results.values())
    print(f"       Cached {success_count}/{len(tickers)} tickers")

    # Step 3: Load All Data
    print("\n[3/6] Loading Historical Data...")
    benchmark_data = data_repo.get_benchmark_data()
    if benchmark_data is None:
        print("       ERROR: Could not load benchmark data!")
        return

    # Load all ticker data with indicators
    print(f"       Loading and preparing data for {len(tickers)} stocks...")
    strategy = SEPAStrategy(benchmark_data=benchmark_data)
    price_data = {}

    for i, ticker in enumerate(tickers):
        if i % 50 == 0:
            print(f"       Progress: {i}/{len(tickers)}")

        df = data_repo.get_ticker_data(ticker, use_cache=True)
        if df is None or len(df) < 200:
            continue

        try:
            # Add all indicators
            df = strategy.prepare_data(df)
            price_data[ticker] = df
        except Exception as e:
            logger.debug(f"Failed to prepare {ticker}: {e}")
            continue

    print(f"       Successfully loaded {len(price_data)} stocks")

    # Step 4: Run Backtest
    print("\n[4/6] Running Backtest Simulation...")
    print(f"       Period: {config.BACKTEST_START_DATE} to Present")
    print(f"       Initial Capital: ${config.INITIAL_CAPITAL:,.0f}")
    print(f"       Max Positions: {config.MAX_POSITIONS}")
    print(f"       Position Size: {config.POSITION_SIZE_PCT * 100}% each")
    print(f"       Stop Loss: {config.STOP_LOSS_PCT * 100}%")

    portfolio = PortfolioManager(
        initial_capital=config.INITIAL_CAPITAL,
        max_positions=config.MAX_POSITIONS
    )

    engine = BacktestEngine(strategy=strategy, portfolio=portfolio)

    trades_df, equity_series = engine.run(
        price_data=price_data,
        start_date=config.BACKTEST_START_DATE
    )

    # Step 5: Generate Report
    print("\n[5/6] Calculating Performance Metrics...")

    reporter = PerformanceReporter(
        trades_df=trades_df,
        equity_series=equity_series,
        initial_capital=config.INITIAL_CAPITAL
    )

    # Print console report
    reporter.print_summary()

    # Show top trades
    if not trades_df.empty:
        winners, losers = reporter.get_top_trades(5)

        print("\n[TOP 5 WINNERS]:")
        print(winners[['Ticker', 'Entry Date', 'Exit Date', 'PnL %', 'Exit Reason']].to_string(index=False))

        print("\n[TOP 5 LOSERS]:")
        print(losers[['Ticker', 'Entry Date', 'Exit Date', 'PnL %', 'Exit Reason']].to_string(index=False))

    # Step 6: Save Results
    print("\n[6/6] Saving Results...")

    # Export trades to CSV
    if config.SAVE_TRADE_LOGS and not trades_df.empty:
        trades_path = Path('trades_log.csv')
        reporter.export_trades(str(trades_path))
        print(f"       [OK] Trades exported to {trades_path}")

    # Generate HTML report
    if save_report and not trades_df.empty:
        report_path = Path('performance_report.html')
        reporter.generate_html_report(str(report_path))
        print(f"       [OK] HTML report saved to {report_path}")

    # Plot performance
    print("\n       Generating performance charts...")
    reporter.plot_performance(save_path='performance_charts.png')

    print("\n" + "=" * 80)
    print(" BACKTEST COMPLETE!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    # Optional: Accept command line arguments
    import argparse

    parser = argparse.ArgumentParser(description='Run SEPA Strategy Backtest')
    parser.add_argument('--subset', type=int, default=None,
                       help='Limit to N tickers for testing (default: all)')
    parser.add_argument('--no-report', action='store_true',
                       help='Skip HTML report generation')

    args = parser.parse_args()

    try:
        run_backtest(
            tickers_subset=args.subset,
            save_report=not args.no_report
        )
    except KeyboardInterrupt:
        print("\n\nBacktest interrupted by user.")
    except Exception as e:
        logger.error(f"Backtest failed with error: {e}", exc_info=True)
        print(f"\n[ERROR]: {e}")
