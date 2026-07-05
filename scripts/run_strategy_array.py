"""Strategy Array Backtest

Runs an array of named strategy configurations (S1..S5) against the same
universe / window / model, producing per-strategy artifacts and a top-level
comparison report.

Each strategy is a SEPAHybridV1 parameter set — the strategy itself is
unchanged, only its knobs. Comparing them isolates *trade-selection-rule*
quality from *model* quality.

Usage:
    python scripts/run_strategy_array.py \
      --model-name m01_binary --model-version v1 \
      --start 2024-11-01 --end 2026-05-22 \
      --strategies S1,S2,S3,S4,S5

Outputs:
    models/<name>/<version>/backtests/
        comparison.md          # ranking table
        summary.json           # machine-readable cross-strategy summary
        <strategy_id>/
            trades.parquet
            equity.parquet
            metrics.json
            config.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from src.backtest.universe_scorer import UniverseScorer
from src.backtest.population_runner import Job, run_arm
from src.backtest import strategy_registry

DB_PATH = REPO_ROOT / "data" / "market_data.duckdb"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class StrategyConfig:
    """One row of the strategy array — a named bundle of SEPAHybridV1 kwargs."""

    id: str
    description: str
    strategy_kwargs: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Strategy array — sourced from the registry (single source of truth).
# ---------------------------------------------------------------------------
# The S-series lives in src/backtest/strategy_registry.py. We expose it here
# keyed by both the short alias ("S1") and the full id ("S1_baseline_top3") so
# the CLI's `--strategies S1,S2` UX is unchanged.

def _load_strategy_array() -> Dict[str, StrategyConfig]:
    out: Dict[str, StrategyConfig] = {}
    for d in strategy_registry.by_status("baseline"):
        if not d.name.startswith("S") or "_" not in d.name:
            continue  # S-series ids only (skip e1_seed etc.)
        cfg = StrategyConfig(id=d.name, description=d.description,
                             strategy_kwargs=dict(d.strategy_kwargs))
        out[d.name] = cfg
        out[d.name.split("_", 1)[0]] = cfg  # short alias "S1"
    return out


STRATEGY_ARRAY: Dict[str, StrategyConfig] = _load_strategy_array()


# ---------------------------------------------------------------------------
# Core flow
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a strategy array backtest")
    parser.add_argument("--model-name", required=True,
                        help="Model family name under models/")
    parser.add_argument("--model-version", required=True,
                        help="Model version subdir (e.g., v1)")
    parser.add_argument("--start", required=True, help="Backtest start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="Backtest end date (YYYY-MM-DD)")
    parser.add_argument("--strategies", default="S1,S2,S3,S4,S5",
                        help="Comma-separated strategy IDs to run (default: all 5)")
    parser.add_argument("--initial-cash", type=float, default=100_000.0)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--include-uncalibrated", action="store_true",
                        help="Also run each strategy with the calibrator disabled, for a "
                             "calibration-impact comparison. Doubles runtime.")
    return parser.parse_args()


def _score_universe(
    model_dir: Path,
    start: str,
    end: str,
    db_path: Path,
    apply_calibrator: bool = True,
) -> pd.DataFrame:
    """Score every active SEPA candidate across the window once.

    Returns a DataFrame matching ScoreLookup's contract: date, ticker,
    normalized_score, daily_pct_rank, trailing_pct, prob_elite.
    """
    model_path = model_dir / "model.json"
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")

    scorer = UniverseScorer(m01_path=str(model_path), calibration_path=None)
    scorer.load_model()
    if not apply_calibrator:
        # Detach the isotonic calibrator for the raw run.
        scorer._iso_calibrator = None
    scores = scorer.score_from_t3(start_date=start, end_date=end, db_path=db_path)
    logger.info(
        "Scored %d (date, ticker) pairs from %s to %s (calibrated=%s)",
        len(scores), start, end, apply_calibrator,
    )
    return scores


def _run_one_strategy(
    config: StrategyConfig,
    scores_df: pd.DataFrame,
    start: str,
    end: str,
    initial_cash: float,
    db_path: Path,
    output_dir: Path,
) -> Dict[str, Any]:
    """Execute a single strategy config via the shared population runner (which
    persists trades + rejections + equity + metrics + config), then enrich the
    summary with the array's hold-days stats from the persisted trades."""
    job = Job(id=config.id, description=config.description,
              strategy_kwargs=config.strategy_kwargs, scores_df=scores_df)
    # run_arm writes into out_dir/<job.id>/ — but the array already nests per-run.
    # Point it at output_dir.parent so the run dir lands exactly at output_dir.
    summary = run_arm(job, start, end, initial_cash, output_dir.parent, str(db_path))

    trades_path = output_dir / "trades.parquet"
    trades = pd.read_parquet(trades_path) if trades_path.exists() else None
    summary.update({
        "avg_hold_days": (
            float(trades["holding_days"].mean())
            if isinstance(trades, pd.DataFrame) and "holding_days" in trades and not trades.empty
            else None
        ),
        "median_hold_days": (
            float(trades["holding_days"].median())
            if isinstance(trades, pd.DataFrame) and "holding_days" in trades and not trades.empty
            else None
        ),
    })
    # array-specific fields not in the shared summary
    summary["description"] = config.description
    return summary


def _render_comparison_md(
    summaries: List[Dict[str, Any]],
    output_path: Path,
    window: str,
    model_label: str,
) -> None:
    """Write a Markdown ranking table sorted by Sharpe (desc, NaNs last)."""

    def _safe_float(v):
        if v is None:
            return float("-inf")
        try:
            f = float(v)
            return float("-inf") if f != f else f  # NaN check
        except (TypeError, ValueError):
            return float("-inf")

    ranked = sorted(summaries, key=lambda s: _safe_float(s.get("sharpe_ratio")), reverse=True)

    def _fmt(v, kind="float"):
        if v is None:
            return "—"
        try:
            f = float(v)
        except (TypeError, ValueError):
            return str(v)
        if f != f:  # NaN
            return "—"
        if kind == "int":
            return f"{int(f):,}"
        if kind == "pct":
            return f"{f:+.2f}%"
        if kind == "pct_abs":
            return f"{f:.2f}%"
        return f"{f:.3f}"

    lines = [
        f"# Strategy Array Comparison — {model_label}",
        "",
        f"**Window:** {window}",
        f"**Strategies evaluated:** {len(summaries)}",
        "",
        "## Ranking (by Sharpe, desc)",
        "",
        "| Rank | Strategy | Sharpe | Total Return | Max DD | Win Rate | Trades | Avg Hold | SQN |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(ranked, 1):
        lines.append(
            f"| {i} | **{s['id']}** | {_fmt(s.get('sharpe_ratio'))} | "
            f"{_fmt(s.get('total_return_pct'), 'pct')} | "
            f"{_fmt(s.get('max_drawdown_pct'), 'pct_abs')} | "
            f"{_fmt(s.get('win_rate_pct'), 'pct_abs')} | "
            f"{_fmt(s.get('total_trades'), 'int')} | "
            f"{_fmt(s.get('avg_hold_days'))} | "
            f"{_fmt(s.get('sqn'))} |"
        )
    lines.append("")
    lines.append("## Strategy descriptions")
    lines.append("")
    for s in summaries:
        lines.append(f"- **{s['id']}**: {s.get('description', '')}")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote comparison report → %s", output_path)


def main() -> None:
    args = parse_args()
    model_dir = REPO_ROOT / "models" / args.model_name / args.model_version
    if not model_dir.exists():
        raise SystemExit(f"Model directory not found: {model_dir}")

    requested = [s.strip() for s in args.strategies.split(",") if s.strip()]
    missing = [s for s in requested if s not in STRATEGY_ARRAY]
    if missing:
        raise SystemExit(f"Unknown strategies: {missing}. Available: {sorted(STRATEGY_ARRAY)}")

    output_dir = model_dir / "backtests"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Score once per calibration variant — strategies share the same scores.
    runs: List[Dict[str, Any]] = []
    variants = [("calibrated", True)]
    if args.include_uncalibrated:
        variants.append(("uncalibrated", False))

    for variant_name, apply_cal in variants:
        logger.info("=" * 70)
        logger.info("Variant: %s", variant_name)
        logger.info("=" * 70)
        try:
            scores_df = _score_universe(
                model_dir=model_dir,
                start=args.start,
                end=args.end,
                db_path=args.db,
                apply_calibrator=apply_cal,
            )
        except Exception as e:
            logger.exception("Scoring failed for variant=%s: %s", variant_name, e)
            continue

        for sid in requested:
            cfg = STRATEGY_ARRAY[sid]
            run_id = cfg.id if variant_name == "calibrated" else f"{cfg.id}_raw"
            run_dir = output_dir / run_id
            logger.info("─" * 70)
            logger.info("Running %s (%s)", run_id, cfg.description)
            try:
                summary = _run_one_strategy(
                    config=cfg,
                    scores_df=scores_df,
                    start=args.start,
                    end=args.end,
                    initial_cash=args.initial_cash,
                    db_path=args.db,
                    output_dir=run_dir,
                )
                summary["id"] = run_id  # ensure variant suffix is on the row
                summary["variant"] = variant_name
                runs.append(summary)
            except Exception as e:
                logger.exception("Strategy %s failed: %s", run_id, e)
                runs.append({
                    "id": run_id,
                    "variant": variant_name,
                    "description": cfg.description,
                    "error": str(e),
                })

    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps({
        "model_name": args.model_name,
        "model_version": args.model_version,
        "window": f"{args.start} → {args.end}",
        "initial_cash": args.initial_cash,
        "runs": runs,
    }, indent=2, default=str))
    logger.info("Wrote summary → %s", summary_path)

    _render_comparison_md(
        summaries=runs,
        output_path=output_dir / "comparison.md",
        window=f"{args.start} → {args.end}",
        model_label=f"{args.model_name}/{args.model_version}",
    )


if __name__ == "__main__":
    main()
