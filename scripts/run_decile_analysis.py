"""Decile analysis on the m01_prototype_may/v2_gated WF-backtest trades.

Step §5 of docs/plans/eval_14c_parallel_session_instructions.md.

The plan calls for rescoring v_d2_training per fold and bucketing by
P(Home Run) into deciles on realized mfe_pct. The DB is currently in
use by the parallel binary training; the plan's §5 tail explicitly
says "the WF-backtest trades already contain `score` and analogues —
use those instead of rescoring from scratch."

Limitation: trades.parquet only has *selected* trades (top-3 per day
after threshold filter), so deciles span the *acted-upon* signal range
— a narrower band than the full universe. The Spearman IC here is
therefore an IC *conditional on being selected*, not the universe-wide
IC the plan envisioned. We note this in the report.

The outcome variable is `pnl_percent` (realized trade PnL). It is NOT
identical to MFE, but is the most direct ranking-power signal we have
without DB access.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODEL_DIR = ROOT / "models" / "m01_prototype_may" / "v2_gated"
WF_DIR = MODEL_DIR / "wf_backtest"
OUT = MODEL_DIR / "evaluation" / "full_eval" / "decile_analysis.json"


def main() -> None:
    frames = []
    for fold_dir in sorted(WF_DIR.glob("fold_*")):
        path = fold_dir / "trades.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if df.empty:
            continue
        df["fold"] = fold_dir.name
        frames.append(df)
    trades = pd.concat(frames, ignore_index=True)
    if trades.empty:
        raise RuntimeError("No trades available for decile analysis")
    print(f"Loaded {len(trades)} trades across {len(frames)} non-empty folds")

    # Use prob_elite as the score (raw P(Home Run) per fold's classifier).
    score_col = "prob_elite"
    outcome_col = "pnl_percent"

    # qcut into deciles; duplicates='drop' handles ties.
    trades["decile"] = pd.qcut(trades[score_col], 10, labels=False, duplicates="drop")
    n_deciles = int(trades["decile"].nunique())
    print(f"Formed {n_deciles} deciles (qcut requested 10; duplicates dropped)")

    decile_stats = trades.groupby("decile").agg(
        n=(outcome_col, "size"),
        mean_pnl=(outcome_col, "mean"),
        median_pnl=(outcome_col, "median"),
        win_rate=(outcome_col, lambda x: (x > 0).mean() * 100),
        homerun_rate_30=(outcome_col, lambda x: (x > 30).mean() * 100),
        homerun_rate_10=(outcome_col, lambda x: (x > 10).mean() * 100),
        score_min=(score_col, "min"),
        score_max=(score_col, "max"),
    ).reset_index()
    decile_stats["decile"] = decile_stats["decile"].astype(int)

    rho, p = spearmanr(trades[score_col], trades[outcome_col])

    # Monotonicity check on mean_pnl across deciles
    means = decile_stats["mean_pnl"].to_numpy()
    diffs = np.diff(means)
    monotone_up = bool(np.all(diffs >= 0))
    monotone_loose = float((diffs > 0).mean())  # fraction of adjacent-decile pairs that increase

    top_bottom = {
        "top_decile_mean_pnl": float(decile_stats["mean_pnl"].iloc[-1]),
        "bottom_decile_mean_pnl": float(decile_stats["mean_pnl"].iloc[0]),
        "top_decile_homerun_rate_30": float(decile_stats["homerun_rate_30"].iloc[-1]),
        "bottom_decile_homerun_rate_30": float(decile_stats["homerun_rate_30"].iloc[0]),
    }
    homerun_lift = (
        top_bottom["top_decile_homerun_rate_30"] / top_bottom["bottom_decile_homerun_rate_30"]
        if top_bottom["bottom_decile_homerun_rate_30"] > 0
        else float("inf") if top_bottom["top_decile_homerun_rate_30"] > 0 else float("nan")
    )

    payload = {
        "score_col": score_col,
        "outcome_col": outcome_col,
        "outcome_note": (
            "pnl_percent (realized trade PnL after stop/trend/timeout) is used "
            "as a degraded proxy for MFE. The plan asked for mfe_pct from v_d2_training "
            "but the DB is locked by the parallel binary-training session."
        ),
        "selection_bias_note": (
            "Trades are pre-filtered (top-3 per day, prob_elite >= 0.15). "
            "Spearman IC here is conditional on selection, not universe-wide IC."
        ),
        "n_trades": int(len(trades)),
        "n_deciles_formed": n_deciles,
        "decile_stats": decile_stats.to_dict(orient="records"),
        "spearman_ic": float(rho),
        "spearman_p_value": float(p),
        "monotone_strict_up": monotone_up,
        "monotone_fraction_up": monotone_loose,
        "top_vs_bottom": top_bottom,
        "homerun_30_lift_top_vs_bottom": homerun_lift,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {OUT}")
    print(f"Spearman IC = {rho:.4f} (p = {p:.4f})")
    print(f"Monotone strict-up: {monotone_up}, fraction-up: {monotone_loose:.2f}")
    print(decile_stats.to_string(index=False))


if __name__ == "__main__":
    main()
