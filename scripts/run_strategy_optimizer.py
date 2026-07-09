"""Vectorized Strategy Parameter Optimizer (Goal 5)

Optuna sweep over VectorizedSEPABacktest strategy knobs, single IS/OOS split,
maximizing OOS-honest Sharpe off the bar-by-bar mark-to-market equity curve.

Design:
    - Pre-score the universe ONCE per model (score_from_t3). Scores are injected
      into every trial via precomputed_scores, so each trial is a millisecond
      pandas run — no re-scoring, no DB hit.
    - Search space is strategy-only knobs. ranking_lookback_days is intentionally
      excluded: with scores injected the engine ranks on daily prob_elite and never
      consults the lookback, so it is inert here (see vectorized_backtest._select_entries).
    - Optimize on the in-sample window, lock the best params, report ONCE on the
      held-out out-of-sample window. No OOS peeking during search.

Usage:
    python scripts/run_strategy_optimizer.py \
        --model m01_binary \
        --is-start 2021-01-01 --is-end 2023-12-31 \
        --oos-start 2024-01-01 --oos-end 2026-05-22 \
        --n-trials 100

    # smoke test:
    python scripts/run_strategy_optimizer.py --model m01_binary \
        --is-start 2024-01-01 --is-end 2024-06-30 \
        --oos-start 2024-07-01 --oos-end 2024-12-31 --n-trials 5
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from src.backtest.universe_scorer import UniverseScorer
from src.backtest.vectorized_backtest import VectorizedSEPABacktest

logging.basicConfig(level=logging.WARNING, format="%(asctime)s | %(message)s")
logger = logging.getLogger("optimizer")
logger.setLevel(logging.INFO)

MODELS_DIR = REPO_ROOT / "models"


def resolve_model_path(model: str) -> str:
    """Map a model slug to its model.json. Requires categorical_mapping.json to
    exist alongside — otherwise UniverseScorer hard-fails on categorical load."""
    for candidate in (MODELS_DIR / model / "model.json", MODELS_DIR / model / "v1" / "model.json"):
        if candidate.exists():
            if not (candidate.parent / "categorical_mapping.json").exists():
                raise FileNotFoundError(
                    f"{candidate} has no categorical_mapping.json — UniverseScorer "
                    f"will refuse to load it. Pick a model with full artifacts "
                    f"(m01_binary, m01_binary_no_macro, m01_no_macro)."
                )
            return str(candidate)
    raise FileNotFoundError(f"No model.json for slug '{model}' under {MODELS_DIR}")


def prescore(model_path: str, start: str, end: str, raw_prob: bool = False) -> pd.DataFrame:
    """raw_prob=True disables the isotonic calibrator so prob_elite = raw p_pos.
    The calibrator's step-function flattens ranking (see project_isotonic_flattens_ranking);
    this arm lets WFO reconcile ranking on calibrated vs raw prob."""
    logger.info(f"Pre-scoring {start} -> {end} ({'raw' if raw_prob else 'calibrated'}) ...")
    scorer = UniverseScorer(m01_path=model_path, calibration_path=None)
    if raw_prob:
        scorer.load_model()  # populate _iso_calibrator before we null it
        scorer._iso_calibrator = None
    scores = scorer.score_from_t3(start, end)
    if "prob_elite" not in scores.columns:
        raise RuntimeError("Scorer produced no prob_elite — model must be a classifier.")
    logger.info(f"  {len(scores)} score rows, {scores['date'].nunique()} dates")
    return scores


def _make_vbt(model_path: str, scores: pd.DataFrame, start: str, end: str, params: dict) -> VectorizedSEPABacktest:
    return VectorizedSEPABacktest(
        model_path=model_path,
        start_date=start,
        end_date=end,
        precomputed_scores=scores.copy(),
        **params,
    )


def run_once(model_path: str, scores: pd.DataFrame, start: str, end: str, params: dict) -> dict:
    """One backtest with the given strategy params against injected scores."""
    vbt = _make_vbt(model_path, scores, start, end, params)
    trades = vbt.run()
    return vbt.metrics(trades)


def run_trades(model_path: str, scores: pd.DataFrame, start: str, end: str, params: dict) -> pd.DataFrame:
    """Return the trade list (for stitching OOS folds into one curve)."""
    vbt = _make_vbt(model_path, scores, start, end, params)
    return vbt.run()


def suggest_params(trial) -> dict:
    """Shared strategy search space — single source of truth for both the
    single-split optimizer and the rolling walk-forward variant."""
    params = dict(
        min_prob_elite=trial.suggest_float("min_prob_elite", 0.0, 0.35),
        max_positions_per_day=trial.suggest_int("max_positions_per_day", 1, 5),
        stop_loss_pct=trial.suggest_float("stop_loss_pct", 0.05, 0.15),
        # LOCK_EXIT_POLICY env var pins the exit policy for a head-to-head cone
        # (e.g. minervini vs sma each with the full trial budget in its own
        # subspace, instead of one optimizer under-sampling across all four).
        exit_policy=(
            os.environ["LOCK_EXIT_POLICY"] if os.environ.get("LOCK_EXIT_POLICY")
            else trial.suggest_categorical(
                "exit_policy", ["sma", "nday", "atr_trail", "minervini"])),
        max_hold_days=trial.suggest_categorical("max_hold_days", [60, 120, 252]),
    )
    # Exit-type-specific knobs — only the active policy's params matter.
    if params["exit_policy"] == "sma":
        params["sma_exit_period"] = trial.suggest_categorical("sma_exit_period", [20, 50, 100])
    elif params["exit_policy"] == "nday":
        params["nday_hold"] = trial.suggest_categorical("nday_hold", [5, 10, 21])
    elif params["exit_policy"] == "atr_trail":
        params["atr_trail_mult"] = trial.suggest_categorical("atr_trail_mult", [1.5, 2.0, 2.5])
    else:  # minervini — breakeven-ratchet trail + optional progressive fills
        params["be_trigger_pct"] = trial.suggest_categorical("be_trigger_pct", [0.05, 0.10, 0.15])
        params["trail_pct"] = trial.suggest_categorical("trail_pct", [0.10, 0.15, 0.20])
        params["progressive_fills"] = trial.suggest_categorical("progressive_fills", [True, False])
        if params["progressive_fills"]:
            params["starter_frac"] = trial.suggest_categorical("starter_frac", [0.3, 0.5])
            params["add_trigger_pct"] = trial.suggest_categorical("add_trigger_pct", [0.03, 0.05, 0.08])
    return params


def build_objective(model_path: str, scores: pd.DataFrame, start: str, end: str):
    def objective(trial) -> float:
        params = suggest_params(trial)
        m = run_once(model_path, scores, start, end, params)
        sharpe = m["sharpe"]
        # Guard degenerate trials (too few trades → unstable Sharpe).
        if m["n_trades"] < 10 or sharpe != sharpe:  # NaN check
            return -1e9
        trial.set_user_attr("n_trades", m["n_trades"])
        trial.set_user_attr("max_drawdown", m["max_drawdown"])
        trial.set_user_attr("total_return", m["total_return"])
        return sharpe

    return objective


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", required=True, help="Model slug (e.g. m01_binary)")
    p.add_argument("--is-start", required=True)
    p.add_argument("--is-end", required=True)
    p.add_argument("--oos-start", required=True)
    p.add_argument("--oos-end", required=True)
    p.add_argument("--n-trials", type=int, default=100)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None, help="Output dir (default models/<model>/optimizer)")
    args = p.parse_args()

    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    model_path = resolve_model_path(args.model)
    out_dir = Path(args.out) if args.out else (MODELS_DIR / args.model / "optimizer")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Pre-score both windows once. IS drives the search; OOS is touched only at the end.
    is_scores = prescore(model_path, args.is_start, args.is_end)
    oos_scores = prescore(model_path, args.oos_start, args.oos_end)

    logger.info(f"Optimizing on IS {args.is_start}..{args.is_end} ({args.n_trials} trials)")
    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=args.seed))
    study.optimize(
        build_objective(model_path, is_scores, args.is_start, args.is_end),
        n_trials=args.n_trials,
        show_progress_bar=False,
    )

    best = study.best_params
    is_metrics = run_once(model_path, is_scores, args.is_start, args.is_end, best)
    oos_metrics = run_once(model_path, oos_scores, args.oos_start, args.oos_end, best)

    result = {
        "model": args.model,
        "model_path": model_path,
        "is_window": [args.is_start, args.is_end],
        "oos_window": [args.oos_start, args.oos_end],
        "n_trials": args.n_trials,
        "best_params": best,
        "is_metrics": is_metrics,
        "oos_metrics": oos_metrics,
    }
    (out_dir / "optimization_results.json").write_text(
        json.dumps(result, indent=2, default=float), encoding="utf-8"
    )

    _write_report(out_dir / "optimization_report.md", result)

    print("\n" + "=" * 78)
    print(f"OPTIMIZER - {args.model}   best IS Sharpe={study.best_value:.2f}")
    print("=" * 78)
    print("Best params:")
    for k, v in best.items():
        print(f"  {k:24s} {v}")
    print(f"\n{'metric':16s}{'IS':>14s}{'OOS':>14s}")
    for k in ("sharpe", "ann_return", "max_drawdown", "total_return", "win_rate", "n_trades"):
        iv, ov = is_metrics[k], oos_metrics[k]
        if k == "n_trades":
            print(f"{k:16s}{iv:>14.0f}{ov:>14.0f}")
        else:
            print(f"{k:16s}{iv:>14.2%}{ov:>14.2%}")
    print("=" * 78)
    print(f"Artifacts: {out_dir}")


def _write_report(path: Path, r: dict) -> None:
    def row(k: str, fmt: str = "pct") -> str:
        iv, ov = r["is_metrics"][k], r["oos_metrics"][k]
        if fmt == "int":
            return f"| {k} | {iv:.0f} | {ov:.0f} |"
        return f"| {k} | {iv:.2%} | {ov:.2%} |"

    lines = [
        f"# Strategy Optimizer — {r['model']}",
        "",
        f"- IS window: {r['is_window'][0]} -> {r['is_window'][1]}",
        f"- OOS window: {r['oos_window'][0]} -> {r['oos_window'][1]}",
        f"- Trials: {r['n_trials']}  ·  Objective: **Sharpe** (bar-by-bar mark-to-market)",
        "",
        "## Best parameters (locked on IS)",
        "",
        "| param | value |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in r["best_params"].items()],
        "",
        "## IS vs OOS",
        "",
        "| metric | IS | OOS |",
        "|---|---|---|",
        row("sharpe"), row("ann_return"), row("ann_vol"),
        row("max_drawdown"), row("total_return"), row("win_rate"),
        row("n_trades", "int"),
        "",
        "> A large IS→OOS Sharpe drop signals overfit to the in-sample window.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
