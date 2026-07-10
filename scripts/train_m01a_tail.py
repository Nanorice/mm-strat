"""M3 (m01a_v1_h63): XGBoost tail ranker on the trend_ok panel vs the RS-only bar.

Label = m01a_tail_v1 (label_registry JSON is canonical; recomputed from source_query,
never re-derived here). Two variants, both judged on the SAME metric — pooled per-fold
top-decile / top-5% tail_mag_63 lift vs universe, next to the identical statistic for
rs_universe_rank on the same fold (the M2 honesty floor: 3.5x / 4.2x full-panel):

    tweedie  reg:tweedie on tail_mag_63   (zero-inflated continuous, 88.5% zeros)
    binary   binary:logistic on home_run_63 (bins=[30] diagnostic)

HARD RULES (plan M3): no balanced-class reweighting — the imbalance IS the signal.
Horizon is invariant (63 trading bars). Anchored WF train-start 2003, test 2012->,
embargo 100 calendar days (~63 trading bars, the LeakageGuard bridge).

Infra: --smoke (10% ticker hash + short window + 50 rounds, path check only),
flush=True logging, per (variant, fold) JSON checkpoints; resume skips done folds.
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import xgboost as xgb

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DUCKDB_PATH
from src.evaluation.walk_forward import anchored_walk_forward

LABEL_JSON = Path("label_registry/m01a_tail_v1.json")
FEATURE_SET_ID = "fs_m01_prototype"
RS_COL = "rs_universe_rank"
OUT_BASE = Path("models/m01a_tail")

# variant -> (xgb objective params, target col)
VARIANTS = {
    "tweedie": ({"objective": "reg:tweedie", "tweedie_variance_power": 1.5}, "tail_mag_63"),
    "binary": ({"objective": "binary:logistic"}, "home_run_63"),
}

_XGB_BASE = {
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


def load_matrix(db_path: str, smoke: bool) -> tuple[pd.DataFrame, list[str]]:
    spec = json.loads(LABEL_JSON.read_text())
    assert spec["target_col"] == "tail_mag_63" and spec["horizon_days"] == 63
    con = duckdb.connect(db_path, read_only=True)
    try:
        feature_cols = get_feature_cols(con)
        avail = {c.lower() for c in con.execute("SELECT * FROM t3_training_cache LIMIT 1").df().columns}
        use = [c for c in feature_cols if c in avail]
        missing = sorted(set(feature_cols) - set(use))
        if missing:
            print(f"[WARN] {len(missing)} feature-set cols not in cache, dropped: {missing}", flush=True)
        if RS_COL not in avail:
            raise RuntimeError(f"{RS_COL} missing from t3_training_cache — baseline impossible")
        sel = ", ".join(f"f.{c}" for c in dict.fromkeys(use + [RS_COL]))
        where_smoke = "AND hash(f.ticker) % 10 = 0" if smoke else ""
        df = con.execute(f"""
            SELECT f.ticker, f.date, {sel}, lbl.tail_mag_63, lbl.home_run_63
            FROM t3_training_cache f
            JOIN ({spec["source_query"]}) lbl USING (ticker, date)
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


def bucket_lifts(te: pd.DataFrame, score_col: str) -> dict:
    """Pooled fold lift, M2-style: per-date PERCENT_RANK on score, bucket mean / fold universe mean."""
    pct = te.groupby("date")[score_col].rank(pct=True, method="average")
    out = {}
    for tag, lo in (("d10", 0.9), ("top5", 0.95)):
        m = pct > lo
        out[f"{tag}_tailmag_lift"] = float(te.loc[m, "tail_mag_63"].mean() / te["tail_mag_63"].mean())
        out[f"{tag}_homerun_lift"] = float(te.loc[m, "home_run_63"].mean() / te["home_run_63"].mean())
    return out


def _slice(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    d = pd.to_datetime(df["date"]).dt.date
    return df.loc[(d >= start) & (d <= end)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DUCKDB_PATH))
    ap.add_argument("--train-start", default="2003-01-01")
    ap.add_argument("--test-start", default="2012-01-01")
    ap.add_argument("--test-end", default="2026-04-08")
    ap.add_argument("--step", default="1Y")
    ap.add_argument("--embargo-days", type=int, default=100)  # 63 trading bars in calendar days
    ap.add_argument("--rounds", type=int, default=NUM_BOOST_ROUND)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    args = ap.parse_args()
    if args.smoke:
        args.train_start, args.test_start, args.rounds = "2020-01-01", "2024-01-01", 50

    run_tag = ("smoke_" if args.smoke else "") + datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUT_BASE / run_tag
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"run dir: {run_dir}", flush=True)

    df, used = load_matrix(args.db, args.smoke)
    print(f"matrix: {len(df):,} rows x {len(used)} features, "
          f"{df['date'].min().date()} -> {df['date'].max().date()}", flush=True)

    fold_specs = list(anchored_walk_forward(
        df, "date", date.fromisoformat(args.train_start),
        date.fromisoformat(args.test_start), date.fromisoformat(args.test_end),
        step=args.step, embargo_days=args.embargo_days,
    ))
    print(f"{len(fold_specs)} folds, embargo={args.embargo_days}d calendar", flush=True)

    summary = {}
    for vname in args.variants.split(","):
        obj_params, target = VARIANTS[vname]
        vdir = run_dir / vname
        vdir.mkdir(exist_ok=True)
        print(f"\n=== variant {vname}: {obj_params['objective']} on {target} ===", flush=True)
        fold_rows = []
        for spec in fold_specs:
            ckpt = vdir / f"fold_{spec.fold_idx:02d}.json"
            if ckpt.exists():
                fold_rows.append(json.loads(ckpt.read_text()))
                print(f"  fold {spec.fold_idx}: resumed from checkpoint", flush=True)
                continue
            tr = _slice(df, spec.train_start, spec.train_end).dropna(subset=[target])
            te = _slice(df, spec.test_start, spec.test_end).dropna(subset=[target])
            if tr.empty or te.empty:
                continue

            t0 = datetime.now()
            dtr = xgb.DMatrix(_prep_cat(tr[used]), label=tr[target], enable_categorical=True)
            booster = xgb.train({**_XGB_BASE, **obj_params}, dtr, num_boost_round=args.rounds)
            te = te.copy()
            te["_score"] = booster.predict(xgb.DMatrix(_prep_cat(te[used]), enable_categorical=True))
            secs = (datetime.now() - t0).total_seconds()

            model_lifts = bucket_lifts(te, "_score")
            rs_lifts = bucket_lifts(te.dropna(subset=[RS_COL]), RS_COL)
            booster.save_model(str(vdir / f"fold_{spec.fold_idx:02d}_model.json"))
            row = {
                "fold": spec.fold_idx,
                "test_start": spec.test_start.isoformat(), "test_end": spec.test_end.isoformat(),
                "model": model_lifts, "rs": rs_lifts,
                "d10_margin": model_lifts["d10_tailmag_lift"] - rs_lifts["d10_tailmag_lift"],
                "n_train": int(len(tr)), "n_test": int(len(te)), "train_secs": secs,
            }
            ckpt.write_text(json.dumps(row, indent=2))
            fold_rows.append(row)
            print(f"  fold {spec.fold_idx} [{row['test_start']}..{row['test_end']}] "
                  f"D10 lift model={model_lifts['d10_tailmag_lift']:.2f}x rs={rs_lifts['d10_tailmag_lift']:.2f}x "
                  f"margin={row['d10_margin']:+.2f} | top5 {model_lifts['top5_tailmag_lift']:.2f}x/"
                  f"{rs_lifts['top5_tailmag_lift']:.2f}x n={row['n_test']:,} [{secs:.0f}s]", flush=True)

        margins = [r["d10_margin"] for r in fold_rows]
        summary[vname] = {
            "objective": obj_params["objective"], "target": target,
            "d10_lift_mean": float(np.mean([r["model"]["d10_tailmag_lift"] for r in fold_rows])),
            "rs_d10_lift_mean": float(np.mean([r["rs"]["d10_tailmag_lift"] for r in fold_rows])),
            "d10_margin_mean": float(np.mean(margins)),
            "d10_margin_worst": float(np.min(margins)),
            "folds_beating_rs": int(sum(m > 0 for m in margins)),
            "n_folds": len(fold_rows),
            "folds": fold_rows,
        }
        s = summary[vname]
        print(f"  {vname}: D10 {s['d10_lift_mean']:.2f}x vs RS {s['rs_d10_lift_mean']:.2f}x, "
              f"beats RS {s['folds_beating_rs']}/{s['n_folds']} folds, "
              f"worst margin {s['d10_margin_worst']:+.2f}", flush=True)

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nsummary -> {run_dir / 'summary.json'}", flush=True)
    print("M3 gate: model must beat RS-only across folds (M2 full-panel bar: D10 3.5x / top5 4.2x); "
          "else kill criterion #2 -> ship the one-column RS rule.", flush=True)


if __name__ == "__main__":
    main()
