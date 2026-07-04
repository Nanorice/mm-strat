"""Phase 3 (m02_breakout): XGBoost regressor, target=breakout_proximity + WF eval.

Infra:
    --smoke         limit to a few tickers, validate path in seconds
    checkpoints     per (fold) JSON under the run dir; resume skips done
"""

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import xgboost as xgb

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DUCKDB_PATH
from src.evaluation.breakout_cv import cross_sectional_rank_ic, precision_recall_at_k
from src.evaluation.walk_forward import anchored_walk_forward

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HORIZON = 60
FEATURE_SET_ID = "fs_m01_prototype"
SMOKE_TICKERS = ("AAPL", "NVDA", "MSFT", "TSLA", "AMD")
OUT_BASE = Path("models/m02_breakout")

_XGB_PARAMS = {
    "objective": "reg:squarederror",
    "tree_method": "hist",
    "max_depth": 6, "eta": 0.05,
    "subsample": 0.8, "colsample_bytree": 0.8, "min_child_weight": 20,
}
NUM_BOOST_ROUND = 300


def get_feature_cols(con: duckdb.DuckDBPyConnection) -> list[str]:
    rows = con.execute(
        "SELECT feature_name FROM model_feature_sets WHERE feature_set_id = ? ORDER BY ordinal",
        [FEATURE_SET_ID],
    ).fetchall()
    if not rows:
        raise RuntimeError(f"feature set {FEATURE_SET_ID!r} empty/missing")
    return [r[0].lower() for r in rows]


def load_matrix(db_path: str, feature_cols: list[str], smoke: bool):
    con = duckdb.connect(db_path, read_only=True)
    try:
        avail = {c.lower() for c in con.execute("SELECT * FROM t3_training_cache LIMIT 1").df().columns}
        use = [c for c in feature_cols if c in avail]
        
        sel = ", ".join(f"f.{c}" for c in dict.fromkeys(use))
        where_smoke = ""
        if smoke:
            tk = ",".join(f"'{t}'" for t in SMOKE_TICKERS)
            where_smoke = f"AND f.ticker IN ({tk})"
        df = con.execute(f"""
            SELECT f.ticker, f.date, {sel},
                   t.breakout_proximity AS _y
            FROM t3_training_cache f
            JOIN m02_breakout_targets t ON f.ticker = t.ticker AND f.date = t.date
            WHERE 1=1 {where_smoke}
            ORDER BY f.date, f.ticker
        """).df()
    finally:
        con.close()
    df.columns = df.columns.str.lower()
    return df, use


def _prep_cat(X: pd.DataFrame) -> pd.DataFrame:
    X = X.copy()
    for c in X.select_dtypes(include="object").columns:
        X[c] = X[c].astype("category")
    return X.replace([np.inf, -np.inf], np.nan)


def _slice(df, start, end):
    d = pd.to_datetime(df["date"]).dt.date
    return df.loc[(d >= start) & (d <= end)]


def _train_final(args) -> None:
    """G1: single all-period booster → deployable model.json + metadata.json.

    Same params/features as the WF folds; trains on [train_start, test_end] with no
    holdout (WF already banked the OOS evidence). Output is the artifact the score
    loader and daily scanner consume — one booster, one clean scoring pass.
    """
    run_dir = OUT_BASE / (("final_smoke_" if args.smoke else "final_") + datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"run dir: {run_dir}", flush=True)

    con = duckdb.connect(args.db, read_only=True)
    feature_cols = get_feature_cols(con)
    con.close()
    df, used = load_matrix(args.db, feature_cols, args.smoke)

    lo, hi = date.fromisoformat(args.train_start), date.fromisoformat(args.test_end)
    df = _slice(df, lo, hi).dropna(subset=["_y"]).copy()
    print(f"final-fit matrix: {len(df):,} rows x {len(used)} features [{lo}..{hi}]", flush=True)
    if df.empty:
        raise RuntimeError("no rows in [train_start, test_end] with a non-null target")

    t0 = datetime.now()
    dtr = xgb.DMatrix(_prep_cat(df[used]), label=df["_y"], enable_categorical=True)
    booster = xgb.train(_XGB_PARAMS, dtr, num_boost_round=NUM_BOOST_ROUND)
    secs = (datetime.now() - t0).total_seconds()

    model_path = run_dir / "model.json"
    booster.save_model(str(model_path))
    metadata = {
        "model": "m02_breakout",
        "kind": "final_all_period",
        "target": "breakout_proximity",
        "features": used,
        "xgb_params": _XGB_PARAMS,
        "num_boost_round": NUM_BOOST_ROUND,
        "train_start": args.train_start,
        "train_end": args.test_end,
        "n_rows": int(len(df)),
        "horizon_days": HORIZON,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "note": "OOS evidence is the WF run (summary.json); this is the deployable fit, no holdout.",
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print(f"final model -> {model_path}  ({len(used)} feats, {secs:.0f}s)", flush=True)
    print(f"metadata    -> {run_dir / 'metadata.json'}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DUCKDB_PATH))
    ap.add_argument("--train-start", default="2016-01-04")
    ap.add_argument("--test-start", default="2021-01-04")
    ap.add_argument("--test-end", default="2026-01-01")
    ap.add_argument("--step", default="1Y")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--final", action="store_true",
                    help="Fit ONE booster on all data [train_start..test_end] and save "
                         "model.json + metadata.json (the deployable artifact). Skips WF eval.")
    args = ap.parse_args()

    if args.final:
        _train_final(args)
        return

    run_tag = ("smoke_" if args.smoke else "") + datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUT_BASE / run_tag
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"run dir: {run_dir}", flush=True)

    con = duckdb.connect(args.db, read_only=True)
    feature_cols = get_feature_cols(con)
    con.close()
    df, used = load_matrix(args.db, feature_cols, args.smoke)
    print(f"matrix: {len(df):,} rows x {len(used)} features", flush=True)

    fold_specs = list(anchored_walk_forward(
        df, "date", date.fromisoformat(args.train_start),
        date.fromisoformat(args.test_start), date.fromisoformat(args.test_end),
        step=args.step, embargo_days=HORIZON,
    ))
    print(f"{len(fold_specs)} folds, embargo={HORIZON}d", flush=True)

    summary = {}
    fold_rows = []
    
    for spec in fold_specs:
        ckpt = run_dir / f"fold_{spec.fold_idx:02d}.json"
        if ckpt.exists():
            fold_rows.append(json.loads(ckpt.read_text()))
            print(f"  fold {spec.fold_idx}: resumed from checkpoint", flush=True)
            continue
            
        tr = _slice(df, spec.train_start, spec.train_end).copy()
        te = _slice(df, spec.test_start, spec.test_end).copy()
        
        tr = tr.dropna(subset=["_y"])
        te = te.dropna(subset=["_y"])
        
        if tr.empty or te.empty:
            continue

        t0 = datetime.now()
        dtr = xgb.DMatrix(_prep_cat(tr[used]), label=tr["_y"], enable_categorical=True)
        booster = xgb.train(_XGB_PARAMS, dtr, num_boost_round=NUM_BOOST_ROUND)
        pred = booster.predict(xgb.DMatrix(_prep_cat(te[used]), enable_categorical=True))
        secs = (datetime.now() - t0).total_seconds()

        sc = te[["date", "_y"]].copy()
        sc["_pred"] = pred
        ic, ic_std = cross_sectional_rank_ic(sc, "date", "_pred", "_y")
        p50, r50 = precision_recall_at_k(sc, "date", "_pred", "_y", k=50)

        booster.save_model(str(run_dir / f"fold_{spec.fold_idx:02d}_model.json"))
        row = {
            "fold": spec.fold_idx,
            "test_start": spec.test_start.isoformat(), "test_end": spec.test_end.isoformat(),
            "rank_ic": ic, "rank_ic_std": ic_std, 
            "precision_at_50": p50, "recall_at_50": r50,
            "n_train": int(len(tr)), "n_test": int(len(te)), "train_secs": secs,
        }
        ckpt.write_text(json.dumps(row, indent=2))
        fold_rows.append(row)
        print(f"  fold {spec.fold_idx} [{row['test_start']}..{row['test_end']}] "
              f"IC={ic:+.4f} P@50={p50:+.4f} R@50={r50:+.4f} "
              f"n_test={row['n_test']} [{secs:.0f}s]", flush=True)

    ics = [r["rank_ic"] for r in fold_rows if not np.isnan(r["rank_ic"])]
    p50s = [r["precision_at_50"] for r in fold_rows if not np.isnan(r["precision_at_50"])]
    
    summary = {
        "ic_mean": float(np.mean(ics)) if ics else None,
        "ic_worst": float(np.min(ics)) if ics else None,
        "precision_at_50_mean": float(np.mean(p50s)) if p50s else None,
        "folds": fold_rows,
    }

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nsummary -> {run_dir / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
