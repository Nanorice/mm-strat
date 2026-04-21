#!/usr/bin/env python
"""
SEPA Hybrid V1 Backtest CLI
===========================
Runs backtest against DuckDB (t3_sepa_features) with daily re-scoring.

Usage:
    python scripts/run_backtest.py
    python scripts/run_backtest.py --start 2021-01-01 --end 2023-12-31
    python scripts/run_backtest.py --max-tickers 50 --note smoke_test
    python scripts/run_backtest.py --model m01_prototype --note baseline
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.universe_scorer import UniverseScorer
from src.backtest.runner import SEPABacktestRunner

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent / 'models'
DEFAULT_MODEL = 'm01_prototype'


def list_m01_variants() -> list[str]:
    """List available M01 model variants from models/ directory."""
    variants = []
    for p in MODELS_DIR.iterdir():
        if p.is_dir() and p.name.startswith('m01'):
            if (p / 'model.json').exists():
                variants.append(p.name)
    return sorted(variants)


def resolve_model_paths(model: str) -> tuple[str, str | None]:
    """Return (m01_path, calibration_path)."""
    model_dir = MODELS_DIR / model
    m01_path = str(model_dir / 'model.json')
    cal_path = model_dir / 'calibration.json'
    return m01_path, str(cal_path) if cal_path.exists() else None


def run_backtest(
    start_date: str,
    end_date: str,
    initial_cash: float,
    model: str,
    max_tickers: int = None,
    specific_tickers: list = None,
    save_report: bool = True,
    no_plot: bool = False,
    save_run: bool = True,
    run_note: str = "",
    force_overwrite: bool = False,
):
    """Score universe from T3, then run backtest."""
    print("\n" + "=" * 60)
    print("SEPA HYBRID V1 BACKTEST")
    print("=" * 60)
    print(f"  Model: {model}")

    m01_path, calibration_path = resolve_model_paths(model)

    # Warm-up buffer for any leading-day scoring context
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    warmup_start = (start_dt - timedelta(days=365)).strftime('%Y-%m-%d')

    print(f"\n[1/2] Scoring universe from T3 ({warmup_start} -> {end_date})...")
    scorer = UniverseScorer(m01_path=m01_path, calibration_path=calibration_path)
    scores_df = scorer.score_from_t3(warmup_start, end_date)
    print(f"      Scored {len(scores_df):,} rows, {scores_df['ticker'].nunique()} tickers")

    print(f"\n[2/2] Setting up backtest...")
    runner = SEPABacktestRunner(
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
    )
    runner.setup(
        scores_df=scores_df,
        max_tickers=max_tickers,
        specific_tickers=specific_tickers,
    )

    print("\nRunning backtest...")
    metrics = runner.run()
    runner.print_results(metrics)

    # Artifacts
    run_dir = None
    if save_run or save_report or not no_plot:
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
        tearsheet_path = str(run_dir / 'tearsheet.html')
        print("  - Generating interactive tearsheet...")
        result = runner.generate_tearsheet(output_path=tearsheet_path)
        if result:
            print(f"    Saved: tearsheet.html")
        else:
            print(f"    Skipped (quantstats unavailable or insufficient equity data)")

    if run_dir:
        print(f"\n[OK] Run complete: {run_dir}")

    return metrics, runner


def main():
    parser = argparse.ArgumentParser(
        description='SEPA Hybrid V1 Backtest CLI (DuckDB)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument('--start', type=str, default='2020-01-01',
                        help='Start date YYYY-MM-DD (default: 2020-01-01)')
    parser.add_argument('--end', type=str, default='2025-01-01',
                        help='End date YYYY-MM-DD (default: 2025-01-01)')
    parser.add_argument('--capital', type=float, default=100_000,
                        help='Initial capital (default: 100000)')

    parser.add_argument('--max-tickers', type=int, default=None,
                        help='Limit number of tickers (for testing)')
    parser.add_argument('--tickers', type=str, default=None,
                        help='Comma-separated ticker whitelist (e.g. AMD,NVDA)')

    parser.add_argument('--model', type=str, default=DEFAULT_MODEL, metavar='NAME',
                        help=f'M01 model variant (default: {DEFAULT_MODEL})')
    parser.add_argument('--list-models', action='store_true',
                        help='List available M01 model variants and exit')

    parser.add_argument('--no-plot', action='store_true', help='Skip plot generation')
    parser.add_argument('--no-report', action='store_true', help='Skip markdown report')
    parser.add_argument('--no-save-run', action='store_true',
                        help='Skip saving structured run data')
    parser.add_argument('--note', type=str, default='',
                        help='Name for run folder (e.g. baseline_v1)')
    parser.add_argument('--force', '-f', action='store_true',
                        help='Overwrite existing run without confirmation')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')

    args = parser.parse_args()

    if args.list_models:
        variants = list_m01_variants()
        print("Available M01 model variants:")
        for v in variants:
            print(f"  - {v}")
        if not variants:
            print("  (none found in models/ directory)")
        sys.exit(0)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%H:%M:%S',
    )

    model_path = MODELS_DIR / args.model / 'model.json'
    if not model_path.exists():
        print(f"[ERR] Model not found: {args.model} ({model_path})")
        print("      Use --list-models to see available variants.")
        sys.exit(1)

    specific_tickers = None
    if args.tickers:
        specific_tickers = [t.strip() for t in args.tickers.split(',')]

    try:
        run_backtest(
            args.start,
            args.end,
            args.capital,
            model=args.model,
            max_tickers=args.max_tickers,
            specific_tickers=specific_tickers,
            save_report=not args.no_report,
            no_plot=args.no_plot,
            save_run=not args.no_save_run,
            run_note=args.note,
            force_overwrite=args.force,
        )
    except Exception:
        logger.exception("Backtest failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
