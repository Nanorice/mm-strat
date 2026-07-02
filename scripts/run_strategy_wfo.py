"""Rolling Walk-Forward Optimizer (Goal 5, WF variant)

The single IS/OOS split (run_strategy_optimizer.py) proved overfit-prone: on
m01_binary it found IS Sharpe 1.22 that collapsed to -0.17 OOS. A single split
lets the optimizer get lucky once. This variant is the stronger gate:

    optimize on train window -> lock params -> run on the NEXT (test) window,
    roll forward one step, repeat. Concatenate every out-of-sample slice into ONE
    equity curve and report the aggregate OOS Sharpe. Params never see their own
    test window, and the aggregate spans multiple regimes, so a single lucky
    concentration can't carry the result.

Folds are anchored (expanding train) or rolling (fixed train), yearly by default.

Usage:
    python scripts/run_strategy_wfo.py --model m01_binary \
        --start 2021-01-01 --end 2026-05-22 \
        --train-years 2 --test-years 1 --n-trials 60

    # daily_predictions-sourced model (e.g. prototype), shorter window:
    python scripts/run_strategy_wfo.py --model m01_prototype \
        --start 2025-10-06 --end 2026-05-22 --train-months 3 --test-months 1 --n-trials 40
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import db
from src.backtest.vectorized_backtest import VectorizedSEPABacktest
from scripts.run_strategy_optimizer import (
    resolve_model_path, prescore, suggest_params, run_trades, MODELS_DIR,
)

# daily_predictions-sourced models (can't load in the backtest scorer).
DAILY_PRED_VERSIONS = {
    "m01_prototype": "m01_prototype_2003_2026_20260514_233125",
}
DB_PATH = REPO_ROOT / "data" / "market_data.duckdb"

logging.basicConfig(level=logging.WARNING, format="%(asctime)s | %(message)s")
logger = logging.getLogger("wfo")
logger.setLevel(logging.INFO)


def load_scores_daily_predictions(version_id: str, start: str, end: str) -> pd.DataFrame:
    con = db.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute(
            """
            SELECT prediction_date AS date, ticker, prob_class_3 AS prob_elite,
                   prob_class_0, prob_class_1, prob_class_2, prob_class_3
            FROM daily_predictions
            WHERE model_version_id = ? AND prediction_date BETWEEN ? AND ?
            """,
            [version_id, start, end],
        ).df()
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"])
    mids = [1.0, 6.0, 20.0, 40.0]
    df["calibrated_score"] = sum(df[f"prob_class_{i}"] * mids[i] for i in range(4))
    return df[["date", "ticker", "prob_elite", "calibrated_score"]]


def make_folds(start: str, end: str, train_span: pd.DateOffset, test_span: pd.DateOffset,
               anchored: bool) -> list[dict]:
    """Rolling folds: [train_start, train_end) optimize, [test_start, test_end) evaluate."""
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    folds = []
    train_start = start_ts
    test_start = start_ts + train_span
    while test_start + test_span <= end_ts + pd.Timedelta(days=1):
        test_end = min(test_start + test_span, end_ts)
        folds.append({
            "train_start": (start_ts if anchored else train_start).strftime("%Y-%m-%d"),
            "train_end": (test_start - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            "test_start": test_start.strftime("%Y-%m-%d"),
            "test_end": test_end.strftime("%Y-%m-%d"),
        })
        train_start = train_start + test_span
        test_start = test_start + test_span
    return folds


def optimize_fold(model_path: str, scores: pd.DataFrame, fold: dict, n_trials: int, seed: int):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    tr = _slice(scores, fold["train_start"], fold["train_end"])

    def objective(trial):
        params = suggest_params(trial)
        vbt = VectorizedSEPABacktest(
            model_path=model_path, start_date=fold["train_start"], end_date=fold["train_end"],
            precomputed_scores=tr.copy(), **params,
        )
        m = vbt.metrics(vbt.run())
        if m["n_trades"] < 10 or m["sharpe"] != m["sharpe"]:
            return -1e9
        return m["sharpe"]

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    return study.best_params, study.best_value


def _slice(scores: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    m = (scores["date"] >= pd.Timestamp(start)) & (scores["date"] <= pd.Timestamp(end))
    return scores.loc[m].copy()


def oos_daily_returns(model_path: str, scores: pd.DataFrame, fold: dict, params: dict) -> pd.Series:
    """Run the locked params on the fold's test window; return that slice's daily
    portfolio returns (from the honest mark-to-market curve)."""
    te = _slice(scores, fold["test_start"], fold["test_end"])
    vbt = VectorizedSEPABacktest(
        model_path=model_path, start_date=fold["test_start"], end_date=fold["test_end"],
        precomputed_scores=te.copy(), **params,
    )
    trades = vbt.run()
    if trades.empty:
        return pd.Series(dtype=float)
    curve = vbt.equity_curve(trades)
    return curve.pct_change().dropna()


def sharpe_from_returns(rets: pd.Series) -> dict:
    if len(rets) < 2 or rets.std() == 0:
        return {"sharpe": float("nan"), "ann_return": float("nan"),
                "ann_vol": float("nan"), "max_drawdown": float("nan"), "n_days": len(rets)}
    ann = np.sqrt(252)
    eq = (1 + rets).cumprod()
    return {
        "sharpe": float(rets.mean() / rets.std() * ann),
        "ann_return": float(eq.iloc[-1] ** (252 / len(eq)) - 1),
        "ann_vol": float(rets.std() * ann),
        "max_drawdown": float((eq / eq.cummax() - 1).min()),
        "total_return": float(eq.iloc[-1] - 1),
        "n_days": len(rets),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--train-years", type=int, default=None)
    p.add_argument("--test-years", type=int, default=None)
    p.add_argument("--train-months", type=int, default=None)
    p.add_argument("--test-months", type=int, default=None)
    p.add_argument("--anchored", action="store_true", help="Expanding train window (default: rolling)")
    p.add_argument("--n-trials", type=int, default=60)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    train_span = (pd.DateOffset(years=args.train_years) if args.train_years
                  else pd.DateOffset(months=args.train_months or 24))
    test_span = (pd.DateOffset(years=args.test_years) if args.test_years
                 else pd.DateOffset(months=args.test_months or 12))

    # Score source: daily_predictions for prototype-style models, else score_from_t3.
    if args.model in DAILY_PRED_VERSIONS:
        logger.info(f"[{args.model}] scoring via daily_predictions ...")
        scores = load_scores_daily_predictions(DAILY_PRED_VERSIONS[args.model], args.start, args.end)
        model_path = "models/m01_binary/v1/model.json"  # only used for price loading
    else:
        model_path = resolve_model_path(args.model)
        scores = prescore(model_path, args.start, args.end)

    folds = make_folds(args.start, args.end, train_span, test_span, args.anchored)
    if not folds:
        logger.error("No folds fit in the window — shorten train/test spans or widen --start/--end.")
        sys.exit(1)
    logger.info(f"{len(folds)} folds ({'anchored' if args.anchored else 'rolling'})")

    fold_records = []
    all_oos_returns = []
    for i, fold in enumerate(folds):
        best, is_sharpe = optimize_fold(model_path, scores, fold, args.n_trials, args.seed)
        oos_rets = oos_daily_returns(model_path, scores, fold, best)
        oos_stats = sharpe_from_returns(oos_rets)
        logger.info(
            f"fold {i}: train {fold['train_start']}..{fold['train_end']} "
            f"-> test {fold['test_start']}..{fold['test_end']}  "
            f"IS_sharpe={is_sharpe:.2f}  OOS_sharpe={oos_stats['sharpe']:.2f}"
        )
        fold_records.append({**fold, "best_params": best, "is_sharpe": is_sharpe, "oos": oos_stats})
        if len(oos_rets):
            all_oos_returns.append(oos_rets)

    # Aggregate OOS: stitch every out-of-sample daily-return slice into one curve.
    stitched = pd.concat(all_oos_returns).sort_index() if all_oos_returns else pd.Series(dtype=float)
    agg = sharpe_from_returns(stitched)

    out_dir = Path(args.out) if args.out else (MODELS_DIR / args.model / "wfo")
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "model": args.model, "window": [args.start, args.end],
        "mode": "anchored" if args.anchored else "rolling",
        "n_trials_per_fold": args.n_trials, "n_folds": len(folds),
        "aggregate_oos": agg, "folds": fold_records,
    }
    (out_dir / "wfo_results.json").write_text(json.dumps(result, indent=2, default=float), encoding="utf-8")
    _write_report(out_dir / "wfo_report.md", result)

    print("\n" + "=" * 84)
    print(f"WALK-FORWARD - {args.model}  ({len(folds)} folds, {args.n_trials} trials/fold)")
    print("=" * 84)
    print(f"{'fold':<5}{'test window':<26}{'IS Sharpe':>11}{'OOS Sharpe':>12}")
    for i, fr in enumerate(fold_records):
        tw = f"{fr['test_start']}..{fr['test_end']}"
        print(f"{i:<5}{tw:<26}{fr['is_sharpe']:>11.2f}{fr['oos']['sharpe']:>12.2f}")
    print("-" * 84)
    print(f"AGGREGATE OOS  Sharpe={agg['sharpe']:.2f}  ann_ret={agg.get('total_return', float('nan')):.1%}  "
          f"maxDD={agg['max_drawdown']:.1%}  ({agg['n_days']} days)")
    print("=" * 84)
    print(f"Artifacts: {out_dir}")


def _write_report(path: Path, r: dict) -> None:
    agg = r["aggregate_oos"]
    lines = [
        f"# Walk-Forward Optimization - {r['model']}",
        "",
        f"Window: {r['window'][0]} -> {r['window'][1]}  ·  Mode: {r['mode']}  ·  "
        f"{r['n_folds']} folds  ·  {r['n_trials_per_fold']} trials/fold",
        "Objective per fold: Sharpe (bar-by-bar mark-to-market). Params locked on train, "
        "evaluated on the next unseen test window. Aggregate = all OOS slices stitched.",
        "",
        "## Aggregate out-of-sample (the honest number)",
        "",
        f"- **Sharpe: {agg['sharpe']:.2f}**",
        f"- Ann return: {agg.get('ann_return', float('nan')):.1%}  ·  Ann vol: {agg['ann_vol']:.1%}",
        f"- Max drawdown: {agg['max_drawdown']:.1%}  ·  {agg['n_days']} trading days",
        "",
        "## Per-fold",
        "",
        "| fold | train | test | IS Sharpe | OOS Sharpe | OOS maxDD |",
        "|---|---|---|--:|--:|--:|",
    ]
    for i, fr in enumerate(r["folds"]):
        lines.append(
            f"| {i} | {fr['train_start']}..{fr['train_end']} | {fr['test_start']}..{fr['test_end']} | "
            f"{fr['is_sharpe']:.2f} | {fr['oos']['sharpe']:.2f} | {fr['oos']['max_drawdown']:.1%} |"
        )
    lines += [
        "",
        "> A healthy WF result has aggregate OOS Sharpe in the same ballpark as the per-fold IS "
        "Sharpes. A large gap (IS strong, OOS weak/negative) is overfit — the same failure the "
        "single-split run exposed.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
