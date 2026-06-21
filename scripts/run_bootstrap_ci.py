"""Bootstrap CI on the standalone WF backtest trades for m01_prototype_may/v2_gated.

Step §1 of docs/plans/eval_14c_parallel_session_instructions.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evaluation.bootstrap import (
    circular_block_bootstrap,
    sharpe_from_trades,
    total_return_from_trades,
)

MODEL_DIR = Path("models/m01_binary/v1")
WF_DIR = MODEL_DIR / "wf_backtest"
OUT = MODEL_DIR / "evaluation" / "full_eval" / "bootstrap_ci.json"


def main() -> None:
    fold_dirs = sorted(WF_DIR.glob("fold_*"))
    trades_frames = []
    for fold in fold_dirs:
        path = fold / "trades.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if df.empty:
            print(f"  {fold.name}: 0 trades (skipped)")
            continue
        df["_fold"] = fold.name
        trades_frames.append(df)
        print(f"  {fold.name}: {len(df)} trades")

    if not trades_frames:
        raise RuntimeError("No trades found across folds.")

    trades = pd.concat(trades_frames, ignore_index=True)
    print(f"Loaded {len(trades)} trades from {len(trades_frames)} non-empty folds")

    sharpe_result = circular_block_bootstrap(
        trades,
        sharpe_from_trades,
        n_iterations=10_000,
        seed=42,
    )
    return_result = circular_block_bootstrap(
        trades,
        total_return_from_trades,
        n_iterations=10_000,
        seed=42,
    )

    payload = {
        "n_trades": int(len(trades)),
        "n_folds_with_trades": len(trades_frames),
        "n_iterations": 10_000,
        "block_size_days": sharpe_result["block_size_days"],
        "n_blocks": sharpe_result["n_blocks"],
        "sharpe": {
            "observed": sharpe_result["metric_observed"],
            "median": sharpe_result["metric_median"],
            "ci_lo_95": sharpe_result["ci_lo"],
            "ci_hi_95": sharpe_result["ci_hi"],
            "gate": sharpe_result["gate"],
        },
        "total_return_pct": {
            "observed": return_result["metric_observed"],
            "median": return_result["metric_median"],
            "ci_lo_95": return_result["ci_lo"],
            "ci_hi_95": return_result["ci_hi"],
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {OUT}")
    print(f"Sharpe observed = {sharpe_result['metric_observed']:.4f}")
    print(
        f"Sharpe 95% CI:    [{sharpe_result['ci_lo']:.4f}, {sharpe_result['ci_hi']:.4f}]"
    )
    print(
        f"Return 95% CI:    [{return_result['ci_lo']:.2f}, {return_result['ci_hi']:.2f}] %"
    )


if __name__ == "__main__":
    main()
