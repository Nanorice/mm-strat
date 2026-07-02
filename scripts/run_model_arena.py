"""Model Arena — bake-off of ALL scoreable model variants on shared strategy infra.

Same strategy knobs for every model; only the model (i.e. the score source)
differs. Ranks by honest bar-by-bar mark-to-market Sharpe.

Two score sources:
  1. score_from_t3 (UniverseScorer) — for models with full artifacts incl.
     categorical_mapping.json (m01_binary, m01_binary_no_macro, m01_no_macro).
  2. daily_predictions (prod ScoreEngine output) — for models the backtest
     scorer can't load (m01_prototype has no frozen categorical vocab). We pull
     its already-materialized prod scores and inject them. This is prod-parity
     by construction, but LIMITED to the window daily_predictions covers.

Because the prototype's prod-score history is short, the arena runs on the
COMMON overlap window across all requested models so the comparison is
apples-to-apples on identical dates.

Usage:
    python scripts/run_model_arena.py --start 2025-10-06 --end 2026-05-22
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from src import db
from src.backtest.universe_scorer import UniverseScorer
from src.backtest.vectorized_backtest import VectorizedSEPABacktest

logging.basicConfig(level=logging.WARNING, format="%(asctime)s | %(message)s")
logger = logging.getLogger("arena")
logger.setLevel(logging.INFO)

MODELS_DIR = REPO_ROOT / "models"
DB_PATH = REPO_ROOT / "data" / "market_data.duckdb"

# name -> ("t3", model.json path)  OR  ("daily_predictions", model_version_id)
ARENA = {
    "m01_binary":          ("t3", "models/m01_binary/v1/model.json"),
    "m01_binary_no_macro": ("t3", "models/m01_binary_no_macro/v1/model.json"),
    "m01_no_macro":        ("t3", "models/m01_no_macro/v1/model.json"),
    "m01_prototype":       ("daily_predictions", "m01_prototype_2003_2026_20260514_233125"),
}

COMMON = dict(
    min_prob_elite=0.0, max_positions_per_day=3, ranking_lookback_days=10,
    stop_loss_pct=0.10, sma_exit_period=50, max_hold_days=252,
)


def load_scores_t3(model_path: str, start: str, end: str) -> pd.DataFrame:
    scorer = UniverseScorer(m01_path=model_path, calibration_path=None)
    return scorer.score_from_t3(start, end, ranking_lookback_days=COMMON["ranking_lookback_days"])


def load_scores_daily_predictions(model_version_id: str, start: str, end: str) -> pd.DataFrame:
    """Inject prod scores. prob_elite = P(top class) = prob_class_3 (4-class model).
    calibrated_score is required downstream only as a passthrough column — carry the
    prod predicted_class midpoint mapping so it's not degenerate."""
    con = db.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute(
            """
            SELECT prediction_date AS date, ticker, prob_class_3 AS prob_elite,
                   prob_class_0, prob_class_1, prob_class_2, prob_class_3
            FROM daily_predictions
            WHERE model_version_id = ?
              AND prediction_date BETWEEN ? AND ?
            """,
            [model_version_id, start, end],
        ).df()
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"])
    # Expected-MFE style score, same 4-class midpoints the UniverseScorer uses.
    midpoints = [1.0, 6.0, 20.0, 40.0]
    df["calibrated_score"] = sum(df[f"prob_class_{i}"] * midpoints[i] for i in range(4))
    return df[["date", "ticker", "prob_elite", "calibrated_score"]]


def metrics_row(vbt: VectorizedSEPABacktest, trades: pd.DataFrame) -> dict:
    return vbt.metrics(trades)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", required=True, help="Common window start (must be within daily_predictions coverage)")
    p.add_argument("--end", required=True)
    p.add_argument("--out", type=str, default=str(MODELS_DIR / "arena"))
    p.add_argument("--models", type=str, default=",".join(ARENA.keys()),
                   help="Comma-separated subset of arena models")
    args = p.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    requested = [m.strip() for m in args.models.split(",") if m.strip()]

    rows = []
    for name in requested:
        if name not in ARENA:
            logger.warning(f"Unknown arena model '{name}', skipping")
            continue
        source, ref = ARENA[name]
        logger.info(f"[{name}] scoring via {source} ...")
        if source == "t3":
            scores = load_scores_t3(ref, args.start, args.end)
            model_path = ref
        else:
            scores = load_scores_daily_predictions(ref, args.start, args.end)
            # Any loadable model.json just satisfies the engine's price loader; the
            # injected scores are what actually drive selection.
            model_path = "models/m01_binary/v1/model.json"
        if scores.empty:
            logger.warning(f"[{name}] no scores in window — skipping")
            continue

        vbt = VectorizedSEPABacktest(
            model_path=model_path, start_date=args.start, end_date=args.end,
            precomputed_scores=scores, **COMMON,
        )
        trades = vbt.run()
        m = metrics_row(vbt, trades)
        m["model"] = name
        m["source"] = source
        rows.append(m)

    if not rows:
        logger.error("No arena results produced.")
        sys.exit(1)

    df = pd.DataFrame(rows).set_index("model").sort_values("sharpe", ascending=False)

    (out_dir / "arena_results.json").write_text(
        df.reset_index().to_json(orient="records", indent=2), encoding="utf-8"
    )
    _write_report(out_dir / "arena_report.md", df, args.start, args.end)

    print("\n" + "=" * 92)
    print(f"MODEL ARENA  {args.start} -> {args.end}  (top-3/day, SL10%, SMA50, mark-to-market Sharpe)")
    print("=" * 92)
    disp = df.copy()
    for c in ["win_rate", "avg_pnl_pct", "ann_return", "total_return", "ann_vol", "max_drawdown"]:
        disp[c] = (df[c] * 100).round(1).astype(str) + "%"
    disp["sharpe"] = df["sharpe"].round(2)
    print(disp[["source", "n_trades", "win_rate", "total_return", "ann_return",
                "ann_vol", "sharpe", "max_drawdown"]].to_string())
    print("=" * 92)
    print(f"Artifacts: {out_dir}")


def _write_report(path: Path, df: pd.DataFrame, start: str, end: str) -> None:
    lines = [
        "# Model Arena",
        "",
        f"Window: {start} -> {end}  ·  Strategy: top-3/day, SL 10%, SMA50 exit, 252d max hold",
        f"Objective: bar-by-bar mark-to-market Sharpe (shared strategy, only model differs).",
        "",
        "> m01_prototype is scored via prod `daily_predictions` (Option B) because it lacks a",
        "> frozen categorical vocab and can't load in the backtest scorer. Its prod-score history",
        "> bounds the common window. It is macro-inclusive (M03); the m01_* no-macro models are not.",
        "",
        "| model | source | trades | win% | total_ret | ann_ret | ann_vol | Sharpe | maxDD |",
        "|---|---|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for m, r in df.iterrows():
        lines.append(
            f"| {m} | {r['source']} | {r['n_trades']:.0f} | {r['win_rate']:.1%} | "
            f"{r['total_return']:.1%} | {r['ann_return']:.1%} | {r['ann_vol']:.1%} | "
            f"{r['sharpe']:.2f} | {r['max_drawdown']:.1%} |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
