#!/usr/bin/env python
"""
SEPA Hybrid V1 Backtest CLI
===========================
Command-line interface for running SEPA backtests.

Usage:
    # Full pipeline: prepare data + run backtest
    python scripts/run_backtest.py --full

    # Prepare data only
    python scripts/run_backtest.py --prepare-data

    # Run backtest only (data must be prepared first)
    python scripts/run_backtest.py --run

    # Quick test with limited tickers
    python scripts/run_backtest.py --run --max-tickers 50

    # Custom date range
    python scripts/run_backtest.py --run --start 2021-01-01 --end 2023-12-31
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.regime_feed import prepare_regime_feed
from src.backtest.universe_scorer import score_universe
from src.backtest.price_feed import prepare_price_feeds
from src.backtest.runner import SEPABacktestRunner

logger = logging.getLogger(__name__)


def prepare_data(start_date: str, end_date: str):
    """
    Prepare all data for backtesting.

    This includes:
    1. M03 regime feed (with warm-up buffer)
    2. Universe scores (with warm-up buffer)
    3. Price feeds (filtered to qualifying tickers)
    """
    print("\n" + "=" * 60)
    print("SEPA BACKTEST DATA PREPARATION")
    print("=" * 60)

    # Add 1-year warm-up buffer for rolling calculations
    from datetime import datetime, timedelta
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    warmup_start = (start_dt - timedelta(days=365)).strftime('%Y-%m-%d')

    # Step 1: Regime feed
    print(f"\n[1/3] Preparing M03 regime feed...")
    prepare_regime_feed(warmup_start, end_date)

    # Step 2: Universe scores
    print(f"\n[2/3] Scoring universe...")
    score_universe(warmup_start, end_date)

    # Step 3: Price feeds
    print(f"\n[3/3] Preparing price feeds...")
    tickers = prepare_price_feeds(start_date, end_date)

    print("\n" + "=" * 60)
    print(f"Data preparation complete!")
    print(f"  - Regime feed: ready")
    print(f"  - Universe scores: ready")
    print(f"  - Price feeds: {len(tickers)} tickers")
    print("=" * 60)


def run_backtest(
    start_date: str,
    end_date: str,
    initial_cash: float,
    max_tickers: int = None,
    specific_tickers: list = None,
    save_plot: str = None,
    save_report: bool = True,
    no_plot: bool = False,  # Explicit opt-out
):
    """Run the backtest."""
    from pathlib import Path

    print("\n" + "=" * 60)
    print("SEPA HYBRID V1 BACKTEST")
    print("=" * 60)

    runner = SEPABacktestRunner(
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
    )

    print("\nSetting up backtest...")
    runner.setup(max_tickers=max_tickers, specific_tickers=specific_tickers)

    print("\nRunning backtest...")
    metrics = runner.run()

    runner.print_results(metrics)

    if save_report:
        print("\nGenerating report...")
        report_path = runner.save_report(metrics)
        print(f"Report saved: {report_path}")

    # Plot handling: default is to save to data/backtest/
    if not no_plot:
        if save_plot:
            plot_path = save_plot
        else:
            # Auto-generate plot path in data/backtest/
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            plot_dir = Path('data/backtest/plots')
            plot_dir.mkdir(parents=True, exist_ok=True)
            plot_path = str(plot_dir / f'backtest_plot_{timestamp}.png')

        print(f"\nSaving plot to {plot_path}...")
        runner.plot(save_path=plot_path)
        print(f"Plot saved: {plot_path}")

    return metrics, runner


def main():
    parser = argparse.ArgumentParser(
        description='SEPA Hybrid V1 Backtest CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        '--full',
        action='store_true',
        help='Run full pipeline: prepare data + run backtest'
    )
    mode_group.add_argument(
        '--prepare-data',
        action='store_true',
        help='Prepare data only (regime, scores, prices)'
    )
    mode_group.add_argument(
        '--run',
        action='store_true',
        help='Run backtest only (data must be prepared)'
    )

    # Date range
    parser.add_argument(
        '--start',
        type=str,
        default='2020-01-01',
        help='Start date (YYYY-MM-DD). Default: 2020-01-01'
    )
    parser.add_argument(
        '--end',
        type=str,
        default='2025-01-01',
        help='End date (YYYY-MM-DD). Default: 2025-01-01'
    )

    # Capital
    parser.add_argument(
        '--capital',
        type=float,
        default=100_000,
        help='Initial capital. Default: 100000'
    )

    # Testing options
    parser.add_argument(
        '--max-tickers',
        type=int,
        default=None,
        help='Limit number of tickers (for testing)'
    )
    parser.add_argument(
        '--tickers',
        type=str,
        default=None,
        help='Comma-separated list of specific tickers to run (e.g. AMD,NVDA)'
    )

    # Output options
    parser.add_argument(
        '--no-plot',
        action='store_true',
        help='Skip plot generation (default: auto-save to data/backtest/plots/)'
    )
    parser.add_argument(
        '--save-plot',
        type=str,
        default=None,
        metavar='PATH',
        help='Save plot to custom path (default: data/backtest/plots/)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--no-report',
        action='store_true',
        help='Skip generating markdown report'
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%H:%M:%S'
    )

    # Default to --full if no mode specified
    if not (args.full or args.prepare_data or args.run):
        args.run = True

    # Parse tickers
    specific_tickers = None
    if args.tickers:
        specific_tickers = [t.strip() for t in args.tickers.split(',')]

    try:
        if args.full:
            prepare_data(args.start, args.end)
            run_backtest(
                args.start,
                args.end,
                args.capital,
                args.max_tickers,
                specific_tickers=specific_tickers,
                save_plot=args.save_plot,
                save_report=not args.no_report,
                no_plot=args.no_plot,
            )

        elif args.prepare_data:
            prepare_data(args.start, args.end)

        elif args.run:
            run_backtest(
                args.start,
                args.end,
                args.capital,
                args.max_tickers,
                specific_tickers=specific_tickers,
                save_plot=args.save_plot,
                save_report=not args.no_report,
                no_plot=args.no_plot,
            )

    except FileNotFoundError as e:
        print(f"\n[ERR] Error: {e}")
        print("\nHint: Run with --prepare-data first to generate required data files.")
        sys.exit(1)
    except Exception as e:
        logger.exception("Backtest failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
