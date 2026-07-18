"""Materialize start-time sweep cells as Backtest Studio runs.

Each sweep cell already has trades.parquet / equity.parquet / metrics.json / config.json
(from population_runner). Studio discovers runs by `data/backtest/*/manifest.json` (v1).
This bridges the two: per cell, write a Studio run dir with the 6-panel plot.png + a v1
manifest tagged from the registry. NO backtest is re-run — reads only cached artifacts.

Usage:
    python scripts/publish_sweep_to_studio.py --strategy champion --grid rolling
    python scripts/publish_sweep_to_studio.py --strategy champion --grid rolling --smoke
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from src.backtest.runner import SEPABacktestRunner
from src.backtest import strategy_registry as reg

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SWEEP_ROOT = REPO_ROOT / "data" / "selection_sweep" / "starttime"
STUDIO_ROOT = REPO_ROOT / "data" / "backtest"


def _render_plot(trades: pd.DataFrame, equity: pd.DataFrame, out: Path) -> bool:
    """6-panel plot.png from cached frames — no live strategy needed."""
    r = SEPABacktestRunner.__new__(SEPABacktestRunner)
    r.strategy = object()          # truthy: passes plot()'s None-guard
    r.regime_df = None             # optional overlay; helper guards on None
    r.get_trade_dataframe = lambda: trades
    r.get_equity_curve_dataframe = lambda: equity
    try:
        r.plot(save_path=str(out))
        return out.exists()
    except Exception as e:
        logger.warning("plot failed for %s: %s", out.parent.name, e)
        return False


def _manifest(cell_id: str, cfg: Dict[str, Any], metrics: Dict[str, Any],
              ann_return: Optional[float], start: str, end: str) -> Dict[str, Any]:
    name = cfg.get("description", "").split()[0] or None
    fingerprint = reg.to_fingerprint(cfg["strategy_kwargs"])
    description = None
    strategy = name or "SEPAHybridV1"
    if name and name in reg.STRATEGIES:
        description = reg.get(name).description

    model = cfg.get("model", "")  # "m01_binary/v1"
    model_name = model.split("/")[0] if model else None

    return {
        "manifest_version": "v1",
        "run_id": cell_id,
        "created_at": pd.Timestamp.now().isoformat(),
        "engine": "BackTrader",
        "strategy": strategy,
        "fingerprint": fingerprint,
        "description": description,
        "model": {"name": model_name, "version_id": model or None, "path": None},
        "params": {
            "start_date": start,
            "end_date": end,
            "initial_cash": metrics.get("starting_value"),
            "signal": cfg.get("signal"),
            **{k: cfg["strategy_kwargs"].get(k) for k in
               ("max_stop_pct", "min_target1_pct", "entry_top_n", "sma_exit_period")},
        },
        "summary_metrics": {
            # ann_return from the sweep summary (window-invariant); metrics.json's
            # annualized_return is a known-0 BackTrader gap, so we don't trust it.
            "total_return": round(metrics.get("total_return", 0), 2),
            "ann_return_pct": round(ann_return * 100, 2) if ann_return is not None else None,
            "sharpe_ratio": round(metrics.get("sharpe_ratio") or 0, 2),
            "max_drawdown": round(metrics.get("max_drawdown", 0), 2),
            "total_trades": metrics.get("total_trades", 0),
            "win_rate": round(metrics.get("win_rate", 0), 1),
            "net_profit": round(metrics.get("net_profit", 0), 2),
        },
    }


def publish(strategy: str, grid: str, smoke: bool, min_days: int) -> int:
    src_dir = SWEEP_ROOT / strategy / grid
    summary_path = src_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"No sweep summary at {summary_path} — run the sweep first.")

    # ann_return per cell, keyed by cell id, from the sweep summary
    cells_meta = {c["cell"]: c for c in json.loads(summary_path.read_text())["cells"]}

    cell_dirs = sorted(d for d in src_dir.iterdir() if d.is_dir())
    if smoke:
        cell_dirs = cell_dirs[:2]

    n = 0
    for cell in cell_dirs:
        cfg_p, met_p = cell / "config.json", cell / "metrics.json"
        tr_p, eq_p = cell / "trades.parquet", cell / "equity.parquet"
        if not all(p.exists() for p in (cfg_p, met_p, tr_p, eq_p)):
            logger.warning("skip %s — missing artifacts", cell.name)
            continue

        meta = cells_meta.get(cell.name, {})
        # Drop degenerate short windows: annualizing a <min_days cell is nonsense
        # (matrix has 1-day cells → +138853% ann_return; see strategy_exploration_summary §11).
        if meta.get("n_days", 0) < min_days:
            logger.info("skip %s — %dd < min_days=%d", cell.name, meta.get("n_days", 0), min_days)
            continue

        cfg = json.loads(cfg_p.read_text())
        metrics = json.loads(met_p.read_text())
        trades = pd.read_parquet(tr_p)
        equity = pd.read_parquet(eq_p)

        run_id = f"sweep_{strategy}_{grid}_{cell.name}"
        out = STUDIO_ROOT / run_id
        out.mkdir(parents=True, exist_ok=True)

        trades.to_parquet(out / "trades.parquet")
        equity.to_parquet(out / "equity_curve.parquet")  # Studio's expected name
        shutil.copyfile(met_p, out / "metrics.json")

        _render_plot(trades, equity, out / "plot.png")

        manifest = _manifest(cell.name, cfg, metrics, meta.get("ann_return"),
                             meta.get("start", ""), meta.get("end", ""))
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
        logger.info("✅ %s  (ret=%.1f%% sharpe=%.2f)", run_id,
                    manifest["summary_metrics"]["total_return"],
                    manifest["summary_metrics"]["sharpe_ratio"])
        n += 1
    return n


def main() -> None:
    p = argparse.ArgumentParser(description="Publish sweep cells to Backtest Studio")
    p.add_argument("--strategy", default="champion")
    p.add_argument("--grid", choices=["rolling", "horizon", "matrix"], default="rolling")
    p.add_argument("--min-days", type=int, default=40,
                   help="Skip cells shorter than this (annualized metrics are noise below ~2mo). "
                        "Guards matrix's 1-day cells.")
    p.add_argument("--smoke", action="store_true", help="First 2 cells only.")
    args = p.parse_args()
    n = publish(args.strategy, args.grid, args.smoke, args.min_days)
    print(f"\nPublished {n} cell(s) to {STUDIO_ROOT}")


if __name__ == "__main__":
    main()
