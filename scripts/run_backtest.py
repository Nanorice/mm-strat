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
from src.backtest.universe_scorer import score_universe, UniverseScorer
from src.backtest.price_feed import prepare_price_feeds
from src.backtest.runner import SEPABacktestRunner

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent / 'models'


def list_m01_variants() -> list[str]:
    """List available M01 model variants from models/ directory."""
    variants = []
    for p in MODELS_DIR.iterdir():
        if p.is_dir() and p.name.startswith('m01'):
            if (p / 'model.json').exists():
                variants.append(p.name)
    return sorted(variants)


def prepare_data(start_date: str, end_date: str, model: str = None):
    """
    Prepare all data for backtesting.

    This includes:
    1. M03 regime feed (with warm-up buffer)
    2. Universe scores (with warm-up buffer)
    3. Price feeds (filtered to qualifying tickers)

    Args:
        start_date: Start date for backtest
        end_date: End date for backtest
        model: M01 model variant name (e.g., 'm01_v2'). If None, uses default.
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
    if model:
        model_dir = MODELS_DIR / model
        m01_path = str(model_dir / 'model.json')
        print(f"      Using model: {model}")
        scorer = UniverseScorer(m01_path=m01_path)
        scorer.score_universe(warmup_start, end_date)
    else:
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
    save_report: bool = True,
    no_plot: bool = False,
    save_run: bool = True,
    run_note: str = "",
    force_overwrite: bool = False,
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

    # Create single run directory for all artifacts
    run_dir = None
    if save_run or save_report or not no_plot:
        # Check if directory already exists
        target_dir = runner.get_run_dir_path(run_note)
        overwrite = False

        if target_dir.exists() and run_note:
            if force_overwrite:
                overwrite = True
            else:
                print(f"\n[WARN] Run '{run_note}' already exists: {target_dir}")
                response = input("Overwrite? [y/N]: ").strip().lower()
                if response in ('y', 'yes'):
                    overwrite = True
                else:
                    print("[SKIP] Saving cancelled.")
                    return metrics, runner

        run_dir = runner.create_run_dir(run_note, overwrite=overwrite)
        print(f"\nSaving all artifacts to: {run_dir}")

    if save_report and run_dir:
        print("  - Generating report...")
        report_path = runner.save_report(metrics, run_dir=run_dir)
        print(f"    Saved: {Path(report_path).name}")

    if save_run and run_dir:
        print("  - Saving run data...")
        runner.save_run(metrics, run_dir=run_dir)
        print("    Saved: equity_curve.parquet, trades.parquet, metrics.json, manifest.json")

    if not no_plot and run_dir:
        plot_path = str(run_dir / 'plot.png')
        print("  - Generating plot...")
        runner.plot(save_path=plot_path)
        print(f"    Saved: plot.png")

    if run_dir:
        print(f"\n[OK] Run complete: {run_dir}")

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

    # Model selection
    parser.add_argument(
        '--model',
        type=str,
        default=None,
        metavar='NAME',
        help='M01 model variant (e.g., m01_v2, m01_hybrid_floor). Use --list-models to see available.'
    )
    parser.add_argument(
        '--list-models',
        action='store_true',
        help='List available M01 model variants and exit'
    )

    # Output options
    parser.add_argument(
        '--no-plot',
        action='store_true',
        help='Skip plot generation'
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
    parser.add_argument(
        '--note',
        type=str,
        default='',
        help='Name for run folder (e.g., "baseline_v1" -> data/backtest/baseline_v1/)'
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Overwrite existing run without confirmation'
    )
    parser.add_argument(
        '--no-save-run',
        action='store_true',
        help='Skip saving structured run data for dashboard'
    )

    args = parser.parse_args()

    # Handle --list-models
    if args.list_models:
        variants = list_m01_variants()
        print("Available M01 model variants:")
        for v in variants:
            print(f"  - {v}")
        if not variants:
            print("  (none found in models/ directory)")
        sys.exit(0)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%H:%M:%S'
    )

    # Validate model if specified
    if args.model:
        model_path = MODELS_DIR / args.model / 'model.json'
        if not model_path.exists():
            print(f"[ERR] Model not found: {args.model}")
            print(f"      Expected: {model_path}")
            print("\nUse --list-models to see available variants.")
            sys.exit(1)

    # Default to --full if no mode specified
    if not (args.full or args.prepare_data or args.run):
        args.run = True

    # Parse tickers
    specific_tickers = None
    if args.tickers:
        specific_tickers = [t.strip() for t in args.tickers.split(',')]

    try:
        if args.full:
            prepare_data(args.start, args.end, model=args.model)
            run_backtest(
                args.start,
                args.end,
                args.capital,
                args.max_tickers,
                specific_tickers=specific_tickers,
                save_report=not args.no_report,
                no_plot=args.no_plot,
                save_run=not args.no_save_run,
                run_note=args.note,
                force_overwrite=args.force,
            )

        elif args.prepare_data:
            prepare_data(args.start, args.end, model=args.model)

        elif args.run:
            run_backtest(
                args.start,
                args.end,
                args.capital,
                args.max_tickers,
                specific_tickers=specific_tickers,
                save_report=not args.no_report,
                no_plot=args.no_plot,
                save_run=not args.no_save_run,
                run_note=args.note,
                force_overwrite=args.force,
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
