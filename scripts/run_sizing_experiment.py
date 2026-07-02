"""Macro Sizing Experiment — same trades, different exposure.

Decouples selection from sizing: the model picks WHAT to hold (unchanged); a
separate macro signal scales HOW MUCH. We generate ONE trade list, then mark it
to the honest bar-by-bar curve under each sizing scheme. Any Sharpe/drawdown
delta is purely sizing — selection is held fixed.

Motivated by the walk-forward result (m01_binary aggregate OOS Sharpe 0.84, but
-33% drawdown, with fold-1/2024 whiffing): does cutting exposure in high-vol
regimes fix the drawdown without killing return?

Usage:
    python scripts/run_sizing_experiment.py --model m01_binary \
        --start 2021-01-01 --end 2026-05-22 --modes flat,vix,m03
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
from src.backtest.macro_sizer import MacroSizer
from scripts.run_strategy_optimizer import resolve_model_path, prescore, MODELS_DIR

DAILY_PRED_VERSIONS = {"m01_prototype": "m01_prototype_2003_2026_20260514_233125"}
DB_PATH = REPO_ROOT / "data" / "market_data.duckdb"

# Fixed strategy config (the un-optimized diversified baseline, not tuned params).
STRAT = dict(min_prob_elite=0.0, max_positions_per_day=3, ranking_lookback_days=10,
             stop_loss_pct=0.10, sma_exit_period=50, max_hold_days=252)

logging.basicConfig(level=logging.WARNING, format="%(asctime)s | %(message)s")
logger = logging.getLogger("sizing")
logger.setLevel(logging.INFO)


def load_scores_daily_predictions(version_id: str, start: str, end: str) -> pd.DataFrame:
    con = db.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute(
            """SELECT prediction_date AS date, ticker, prob_class_3 AS prob_elite,
                      prob_class_0, prob_class_1, prob_class_2, prob_class_3
               FROM daily_predictions
               WHERE model_version_id = ? AND prediction_date BETWEEN ? AND ?""",
            [version_id, start, end],
        ).df()
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"])
    mids = [1.0, 6.0, 20.0, 40.0]
    df["calibrated_score"] = sum(df[f"prob_class_{i}"] * mids[i] for i in range(4))
    return df[["date", "ticker", "prob_elite", "calibrated_score"]]


def curve_stats(eq: pd.Series) -> dict:
    rets = eq.pct_change().dropna()
    if len(rets) < 2 or rets.std() == 0:
        return {"sharpe": float("nan"), "ann_return": float("nan"),
                "ann_vol": float("nan"), "max_drawdown": float("nan"), "total_return": float("nan")}
    ann = np.sqrt(252)
    return {
        "sharpe": float(rets.mean() / rets.std() * ann),
        "ann_return": float((eq.iloc[-1] / eq.iloc[0]) ** (252 / len(eq)) - 1),
        "ann_vol": float(rets.std() * ann),
        "max_drawdown": float((eq / eq.cummax() - 1).min()),
        "total_return": float(eq.iloc[-1] / eq.iloc[0] - 1),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--modes", type=str, default="flat,vix")
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    if args.model in DAILY_PRED_VERSIONS:
        scores = load_scores_daily_predictions(DAILY_PRED_VERSIONS[args.model], args.start, args.end)
        model_path = "models/m01_binary/v1/model.json"
    else:
        model_path = resolve_model_path(args.model)
        scores = prescore(model_path, args.start, args.end)

    # ONE trade list — selection fixed across all sizing schemes.
    vbt = VectorizedSEPABacktest(model_path=model_path, start_date=args.start, end_date=args.end,
                                 precomputed_scores=scores, **STRAT)
    trades = vbt.run()
    if trades.empty:
        logger.error("No trades — check window/model.")
        sys.exit(1)
    logger.info(f"{len(trades)} trades generated (selection fixed across sizing schemes)")

    base_curve = vbt.equity_curve(trades)  # flat, for the date grid
    dates = base_curve.index
    sizer = MacroSizer()

    rows = []
    for mode in modes:
        w = sizer.weight(mode, args.start, args.end, dates=dates)
        eq = vbt.equity_curve(trades, exposure=w)
        s = curve_stats(eq)
        s["mode"] = mode
        s["avg_exposure"] = float(w.reindex(dates).ffill().fillna(1.0).mean())
        rows.append(s)

    df = pd.DataFrame(rows).set_index("mode")
    out_dir = Path(args.out) if args.out else (MODELS_DIR / args.model / "sizing")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sizing_results.json").write_text(
        df.reset_index().to_json(orient="records", indent=2), encoding="utf-8")
    _write_report(out_dir / "sizing_report.md", df, args, len(trades))

    print("\n" + "=" * 88)
    print(f"MACRO SIZING - {args.model}  {args.start}..{args.end}  ({len(trades)} trades, selection fixed)")
    print("=" * 88)
    disp = df.copy()
    for c in ["ann_return", "total_return", "ann_vol", "max_drawdown", "avg_exposure"]:
        disp[c] = (df[c] * 100).round(1).astype(str) + "%"
    disp["sharpe"] = df["sharpe"].round(2)
    print(disp[["sharpe", "total_return", "ann_return", "ann_vol", "max_drawdown", "avg_exposure"]].to_string())
    print("=" * 88)
    print(f"Artifacts: {out_dir}")


def _write_report(path: Path, df: pd.DataFrame, args, n_trades: int) -> None:
    lines = [
        f"# Macro Sizing Experiment - {args.model}",
        "",
        f"Window: {args.start} -> {args.end}  ·  {n_trades} trades  ·  selection FIXED "
        "(same trades every scheme; only daily exposure differs).",
        "Sizing signals are lagged 1 business day (no lookahead). Bands are a fixed",
        "hypothesis, not tuned params.",
        "",
        "| mode | Sharpe | total_ret | ann_ret | ann_vol | maxDD | avg_exposure |",
        "|---|--:|--:|--:|--:|--:|--:|",
    ]
    for m, r in df.iterrows():
        lines.append(
            f"| {m} | {r['sharpe']:.2f} | {r['total_return']:.1%} | {r['ann_return']:.1%} | "
            f"{r['ann_vol']:.1%} | {r['max_drawdown']:.1%} | {r['avg_exposure']:.1%} |"
        )
    lines += [
        "",
        "> Read: if VIX/M03 sizing lifts Sharpe and shrinks maxDD vs flat while avg_exposure",
        "> stays high, regime sizing adds value. If it only cuts return in proportion to",
        "> exposure (Sharpe unchanged), it's just de-leveraging, not skill.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
