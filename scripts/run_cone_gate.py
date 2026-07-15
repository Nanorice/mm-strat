"""Report-only start-time CONE gate for a locked strategy arm.

The 4-fold WF-backtest gate is a 3-4 sample draw whose worst fold breaches any
absolute floor even when the edge is real (project_champion_starttime_dependent).
The promotion decision the sprint rests on is a start-date CONE (Q58): one locked
model over many (start, 12m) windows, judged on the DISTRIBUTION. This aggregates
an already-computed cone (run_starttime_sweep output) into distribution stats +
Calmar + alpha/beta vs SPY & QQQ. REPORT-ONLY — all gates non-blocking until
thresholds are calibrated against the incumbent champion.

Reads existing cells from data/selection_sweep/starttime/<arm>/<grid>/ (no re-run)
and writes evaluation-style JSON. Compare two arms to set thresholds.

Usage:
    python scripts/run_cone_gate.py --arm champion_trail_spygate
    python scripts/run_cone_gate.py --arm champion_trail_spygate_4cls --grid rolling
    python scripts/run_cone_gate.py --arm champion_trail_spygate --out data/cone_gate/binary.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import duckdb
import pandas as pd

from src.evaluation.walk_forward_backtest import aggregate_backtest_cone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cone_gate")

CONE_ROOT = REPO / "data" / "selection_sweep" / "starttime"
DB_PATH = REPO / "data" / "market_data.duckdb"


def _bench_returns() -> dict:
    """SPY & QQQ daily returns from t1_macro close, indexed by date."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute(
            "SELECT date, spy_close, qqq_close FROM t1_macro "
            "WHERE spy_close IS NOT NULL ORDER BY date"
        ).df()
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    out = {}
    for name, col in (("SPY", "spy_close"), ("QQQ", "qqq_close")):
        s = df[col].dropna().pct_change().dropna()
        out[name] = s
    return out


def _load_cells(arm: str, grid: str) -> list:
    """Read each cone cell's metrics.json + equity.parquet → daily returns series."""
    cell_dir = CONE_ROOT / arm / grid
    if not cell_dir.exists():
        raise SystemExit(f"No cone artifacts at {cell_dir} — run run_starttime_sweep first.")
    cells = []
    for d in sorted(cell_dir.glob("r_*")):
        mp = d / "metrics.json"
        if not mp.exists():
            continue
        m = json.loads(mp.read_text())
        cell = {
            "cell": d.name,
            "sharpe_ratio": m.get("sharpe_ratio"),
            "max_drawdown": m.get("max_drawdown"),
            "total_return": m.get("total_return"),
        }
        eq_path = d / "equity.parquet"
        if eq_path.exists():
            eq = pd.read_parquet(eq_path)
            if {"date", "value"}.issubset(eq.columns) and len(eq) > 1:
                s = eq.set_index(pd.to_datetime(eq["date"]))["value"].pct_change().dropna()
                cell["daily_returns"] = s
        cells.append(cell)
    return cells


def main() -> int:
    ap = argparse.ArgumentParser(description="Report-only start-time cone gate.")
    ap.add_argument("--arm", required=True, help="Registry arm (cone dir name).")
    ap.add_argument("--grid", default="rolling", help="Cone grid subdir (default: rolling).")
    ap.add_argument("--out", default=None, help="Output JSON path (default: data/cone_gate/<arm>.json).")
    args = ap.parse_args()

    cells = _load_cells(args.arm, args.grid)
    logger.info("Loaded %d cone cells for %s/%s", len(cells), args.arm, args.grid)

    agg = aggregate_backtest_cone(cells, bench_returns=_bench_returns())
    agg["arm"] = args.arm
    agg["grid"] = args.grid

    out = Path(args.out) if args.out else REPO / "data" / "cone_gate" / f"{args.arm}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(agg, indent=2, default=str))

    s = agg["summary"]
    logger.info("=" * 60)
    logger.info("CONE GATE (report-only) — %s", args.arm)
    logger.info("  n_cells        = %s", s.get("n_cells"))
    logger.info("  median Sharpe  = %.3f", s.get("median_sharpe", float("nan")))
    logger.info("  %%neg cells     = %.1f%%", s.get("pct_negative_cells", float("nan")))
    logger.info("  floor Sharpe   = %.3f", s.get("floor_sharpe", float("nan")))
    logger.info("  median Calmar  = %.3f", s.get("median_calmar", float("nan")))
    logger.info("  worst maxDD    = %.1f%%", s.get("worst_max_drawdown", float("nan")))
    for b in ("SPY", "QQQ"):
        if f"alpha_ann_vs_{b}" in s:
            logger.info("  alpha vs %s    = %.3f (ann)  beta = %.3f",
                        b, s[f"alpha_ann_vs_{b}"], s[f"beta_vs_{b}"])
    logger.info("  -> %s", out)
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
