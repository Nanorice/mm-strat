"""Materialize the strategy-cone cell metrics into the `cone_cells` table.

Run after a start-time sweep (~monthly), NOT nightly — the inputs only change
when you run a sweep. Mirrors run_cone_gate.py's cadence. A staleness check in
tools/audit_serving_tables.py catches a sweep that ran without a rebuild.

Source of truth = each arm/grid's `summary.json` (`cells[]`), NOT the 2,892
per-cell metrics.json files:
  - summary.json is the CURATED set — degenerate short-window cells (matrix
    1-day → +138853% ann_return) are already filtered out of it.
  - it carries the WINDOW-FAIR `ann_return` / `sharpe`; the per-cell metrics.json
    has annualized_return=0 and calmar=0 (a known BackTrader gap).
So walking summaries is both lazier and more correct than walking cell dirs.

Each cell is ONE start-DATE draw. The table renders the full start-date
distribution (the strategy cone) — never a single Sharpe. See
docs/architecture/glossary.md (label_cone vs strategy_cone) and
docs/session_logs/sprint_14/plans/dashboard_uplift/cone_and_studio_design.md.

Usage:
    python scripts/build_cone_cache.py                 # all arms under starttime/
    python scripts/build_cone_cache.py --dry-run       # print, don't write
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import src.db as db  # noqa: E402

SWEEP_ROOT = ROOT / "data" / "selection_sweep" / "starttime"
DB_PATH = ROOT / "data" / "market_data.duckdb"


def _cell_id(cfg: dict, start: str, end: str) -> str:
    """Content fingerprint of the cell config — sha256 of canonical JSON.

    Follows label_registry.LabelDefinition.fingerprint(): identical configs
    collide to the same id, so a re-run is provably a reproduction and an arm
    rename doesn't orphan history. Excludes the volatile `description`.
    """
    payload = {
        "strategy_kwargs": cfg.get("strategy_kwargs", {}),
        "signal": cfg.get("signal"),
        "model": cfg.get("model"),
        "start": start,
        "end": end,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _score_scale(cfg: dict) -> str:
    """Which prob_elite scale the cell's gate was on — the §2 two-scale trap.

    A gate of 0.15 means opposite things on raw (~0.55 median) vs calibrated
    (~0.12 median) scores. The scale only applies when the cell RANKS on
    prob_elite; a cell ranking on RS ('rs' signal) has no prob_elite gate, so
    the scale is not-applicable, not unknown.

    Every backtest sweep cell scores off the *_calibrated cache (the only score
    cache on disk is m01_binary_calibrated_*), and prob_elite is calibrated in
    backtest — raw only in daily_predictions (project_isotonic_flattens_ranking).
    So any prob_elite-ranked cell is 'calibrated' regardless of the signal
    variant (binary / binary_gated / proto_cali_gated all rank on the calibrated
    score). Empty config → 'unknown'; NEVER guess a scale (a wrong one silently
    misreads the gate).
    """
    if not cfg:
        return "unknown"
    if cfg.get("strategy_kwargs", {}).get("rank_by") == "prob_elite":
        return "calibrated"
    return "n/a"  # ranks on something else (e.g. RS) — no prob_elite gate


def collect_cells(sweep_root: Path) -> pd.DataFrame:
    rows = []
    for summary_path in sorted(sweep_root.glob("**/summary.json")):
        grid_dir = summary_path.parent
        grid = grid_dir.name
        arm = grid_dir.parent.relative_to(sweep_root).as_posix()
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        for c in summary.get("cells", []):
            cell = c["cell"]
            cfg_path = grid_dir / cell / "config.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            else:
                cfg = {}  # summary has the metrics; config only refines id/scale
            rows.append({
                "arm": arm,
                "grid": grid,
                "cell": cell,
                "cell_id": _cell_id(cfg, c.get("start"), c.get("end")),
                "start": c.get("start"),
                "end": c.get("end"),
                "n_days": c.get("n_days"),
                "sharpe": c.get("sharpe"),
                "ann_return": c.get("ann_return"),
                "ann_vol": c.get("ann_vol"),
                "max_drawdown": c.get("max_drawdown"),
                "total_return": c.get("total_return"),
                "engine": "BackTrader",   # every sweep cell is Cerebro (population_runner)
                "score_scale": _score_scale(cfg),
                "fingerprint": summary.get("fingerprint"),
                "source_mtime": pd.Timestamp(
                    summary_path.stat().st_mtime, unit="s"),
            })
    return pd.DataFrame(rows)


def write_table(df: pd.DataFrame, db_path: Path) -> None:
    """Replace ONLY the BackTrader (strategy-cone) rows. The label cone
    (engine='basket_paths', build_label_cone_cache.py) shares this table; a bare
    CREATE OR REPLACE would wipe it. Engine-scoped upsert keeps the two cones
    co-resident without either build clobbering the other."""
    df = df.copy()
    df["built_at"] = pd.Timestamp.now()
    con = db.connect(str(db_path))  # write connection — CLI, run solo
    try:
        con.register("cone_cells_df", df)
        exists = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name='cone_cells'"
        ).fetchone()
        if exists:
            con.execute("DELETE FROM cone_cells WHERE engine = 'BackTrader'")
            con.execute("INSERT INTO cone_cells BY NAME SELECT * FROM cone_cells_df")
        else:
            con.execute("CREATE TABLE cone_cells AS SELECT * FROM cone_cells_df")
        con.unregister("cone_cells_df")
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep-root", default=str(SWEEP_ROOT))
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    df = collect_cells(Path(args.sweep_root))
    if df.empty:
        print("[ERR] no cells found — run a sweep first.")
        return 1

    n_arms = df["arm"].nunique()
    n_unknown = (df["score_scale"] == "unknown").sum()
    print(f"[OK] {len(df):,} cells across {n_arms} arms "
          f"({df['grid'].nunique()} grids); {n_unknown} with score_scale=unknown")
    print(df.groupby("arm").agg(
        cells=("cell", "count"),
        median_sharpe=("sharpe", "median"),
        pct_neg=("sharpe", lambda s: (s < 0).mean() * 100),
    ).round(2).to_string())

    if args.dry_run:
        print("\n[dry-run] not written.")
        return 0

    write_table(df, Path(args.db))
    print(f"\n[OK] wrote cone_cells -> {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
