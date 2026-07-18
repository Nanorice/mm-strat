"""Materialize the LABEL cone (basket_paths) into the shared `cone_cells` table.

The label cone is C1 — a buy-and-hold-to-exit proxy that asks *is the label worth
anything on the population?* It is NOT the strategy cone (C3, BackTrader, slots +
rotation). They are different objects (docs/architecture/glossary.md: label_cone vs
strategy_cone) and must never render as one — but they share the cone_cells shape,
distinguished by `engine`:
  - strategy cone: engine='BackTrader', metric = sharpe (build_cone_cache.py)
  - label cone:    engine='basket_paths', metric = total_return (fwd_return)

A label-cone cell is ONE start-day basket forward return. sharpe/ann_*/max_drawdown
are NULL by design: a buy-and-hold basket produces no Sharpe, and inventing one would
be the exact category error the two-cone split exists to prevent. total_return carries
the fwd_return; n_days carries exit_day (the "when does the basket close" variable).

score_scale = 'calibrated' — basket_paths reads the *_calibrated score cache and gates
on the calibrated prob_elite (project_isotonic_flattens_ranking); a min_score of 0.20
means the calibrated ~coin-flip line, NOT raw 0.20.

Run after re-scoring (~monthly), NOT nightly. Recomputes in ~30s (4 variants); the
staleness check in tools/audit_serving_tables.py catches a stale table.

Usage:
    python scripts/build_label_cone_cache.py
    python scripts/build_label_cone_cache.py --dry-run
    python scripts/build_label_cone_cache.py --sample-every 1   # full density
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs" / "session_logs" / "sprint_14" / "scripts"))

import src.db as db  # noqa: E402
from start_day_basket_paths import basket_paths  # noqa: E402

DB_PATH = ROOT / "data" / "market_data.duckdb"
HORIZON = 150
SL_PCT = 0.15
CAL_GATE = 0.20  # calibrated scale — the §5 basket_paths gate

# The 4 fan variants (design §2.3 / cells §5): regime-gate on/off × score-gate on/off.
VARIANTS = {
    "label_baseline":      dict(use_governor=False, min_score=None),
    "label_regime_gated":  dict(use_governor=True,  min_score=None),
    "label_score_gated":   dict(use_governor=False, min_score=CAL_GATE),
    "label_both_gated":    dict(use_governor=True,  min_score=CAL_GATE),
}


def _cell_id(arm: str, start: pd.Timestamp, kw: dict) -> str:
    """Content fingerprint — sha256 of the variant config + start day. Mirrors
    build_cone_cache._cell_id so a re-run provably reproduces."""
    payload = {
        "engine": "basket_paths", "arm": arm,
        "horizon": HORIZON, "sl_pct": SL_PCT,
        "use_governor": kw["use_governor"], "min_score": kw["min_score"],
        "start": start.strftime("%Y-%m-%d"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def collect_cells(sample_every: int) -> pd.DataFrame:
    rows = []
    for arm, kw in VARIANTS.items():
        summary, _paths, _starts = basket_paths(
            top_n=5, horizon=HORIZON, sl_pct=SL_PCT, sample_every=sample_every, **kw)
        deployed = summary[summary["deployed"]]
        print(f"[{arm}] {len(summary)} start-days, {len(deployed)} deployed")
        for r in deployed.itertuples():
            start = pd.Timestamp(r.start)
            end = start + pd.Timedelta(days=HORIZON)
            rows.append({
                "arm": arm,
                "grid": "basket",              # label cone has no horizon/matrix split
                "cell": f"b_{start:%Y%m%d}",
                "cell_id": _cell_id(arm, start, kw),
                "start": start.strftime("%Y-%m-%d"),
                "end": end.strftime("%Y-%m-%d"),
                "n_days": int(r.exit_day),     # when the basket fully closed
                "sharpe": None,                # buy-and-hold: no Sharpe (by design)
                "ann_return": None,
                "ann_vol": None,
                "max_drawdown": None,
                "total_return": float(r.fwd_return),   # the label-cone metric
                "engine": "basket_paths",
                "score_scale": "calibrated",   # reads the *_calibrated cache
                "fingerprint": f"{arm}_h{HORIZON}_sl{int(SL_PCT*100)}",
                "source_mtime": None,          # no summary.json source
            })
    return pd.DataFrame(rows)


def write_table(df: pd.DataFrame, db_path: Path) -> None:
    """Replace ONLY the basket_paths (label-cone) rows — leave BackTrader rows
    (the strategy cone) untouched. Engine-scoped upsert, mirrors build_cone_cache."""
    df = df.copy()
    df["built_at"] = pd.Timestamp.now()
    con = db.connect(str(db_path))
    try:
        con.register("label_cone_df", df)
        exists = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name='cone_cells'"
        ).fetchone()
        if exists:
            con.execute("DELETE FROM cone_cells WHERE engine = 'basket_paths'")
            con.execute("INSERT INTO cone_cells BY NAME SELECT * FROM label_cone_df")
        else:
            con.execute("CREATE TABLE cone_cells AS SELECT * FROM label_cone_df")
        con.unregister("label_cone_df")
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--sample-every", type=int, default=5,
                    help="start-day stride; 5 = the design fan density, 1 = full.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    df = collect_cells(args.sample_every)
    if df.empty:
        print("[ERR] no label-cone cells — is the score cache present?")
        return 1

    print(f"\n[OK] {len(df):,} label-cone cells across {df['arm'].nunique()} arms")
    print(df.groupby("arm").agg(
        cells=("cell", "count"),
        median_fwd=("total_return", "median"),
        pct_neg=("total_return", lambda s: (s < 0).mean() * 100),
    ).round(3).to_string())

    if args.dry_run:
        print("\n[dry-run] not written.")
        return 0

    write_table(df, Path(args.db))
    print(f"\n[OK] wrote label-cone rows -> {args.db} (cone_cells, engine=basket_paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
