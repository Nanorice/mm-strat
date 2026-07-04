"""Score the full universe with a FINAL m02_breakout model → arena-ready panel.

Reads a final all-period model (train_breakout_model.py --final), runs it over the
t3 feature matrix, and emits a score panel with the columns the vectorized backtest
engine consumes as an injected signal:

    date, ticker, prob_elite, calibrated_score

`prob_elite` = raw `breakout_proximity` (0..1, higher = closer to ignition). The engine
ranks on it; that's all it needs. `calibrated_score` mirrors it (passthrough only).

⚠️ RANK-ONLY contract: breakout_proximity is uncalibrated (m02 doc §8a G4). Use it to
rank/select; do NOT read the raw value as a probability or threshold on it as if it were
calibrated until a calibrator ships.

Usage:
    .venv/Scripts/python.exe scripts/score_m02_breakout.py \
        --run models/m02_breakout/final_YYYYMMDD_HHMMSS
    # → writes <run>/score_panel.parquet
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import xgboost as xgb

from config import DUCKDB_PATH
from scripts.train_breakout_model import get_feature_cols, load_matrix, _prep_cat

import duckdb


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True,
                    help="Final run dir containing model.json + metadata.json")
    ap.add_argument("--db", default=str(DUCKDB_PATH))
    ap.add_argument("--smoke", action="store_true", help="Score only the smoke tickers")
    ap.add_argument("--out", default=None, help="Output parquet (default <run>/score_panel.parquet)")
    args = ap.parse_args()

    run_dir = Path(args.run)
    model_path = run_dir / "model.json"
    meta_path = run_dir / "metadata.json"
    if not model_path.exists() or not meta_path.exists():
        raise FileNotFoundError(f"expected model.json + metadata.json in {run_dir}")

    meta = json.loads(meta_path.read_text())
    feats = meta["features"]  # frozen training feature list — source of truth for scoring

    booster = xgb.Booster()
    booster.load_model(str(model_path))

    # Reuse the training loader so the feature matrix is built identically. It reads the
    # full model_feature_sets list; we then restrict to the model's frozen `feats`.
    con = duckdb.connect(args.db, read_only=True)
    all_cols = get_feature_cols(con)
    con.close()
    df, _ = load_matrix(args.db, all_cols, args.smoke)

    missing = [c for c in feats if c not in df.columns]
    if missing:
        raise RuntimeError(f"feature matrix missing {len(missing)} model features: {missing[:10]}")

    X = _prep_cat(df[feats])
    # reg:squarederror can overshoot the [0,1] target range; clip to the proximity
    # domain. Monotone → ranking (what the engine uses) is unchanged.
    raw = booster.predict(xgb.DMatrix(X, enable_categorical=True))
    df["prob_elite"] = raw.clip(0.0, 1.0)
    df["calibrated_score"] = df["prob_elite"]  # passthrough (rank-only; not calibrated)

    panel = df[["date", "ticker", "prob_elite", "calibrated_score"]].copy()
    panel["date"] = pd.to_datetime(panel["date"])

    out = Path(args.out) if args.out else run_dir / "score_panel.parquet"
    panel.to_parquet(out, index=False)

    # Sanity: bounded score, non-empty cross-section, one row per (date,ticker).
    assert panel["prob_elite"].between(-0.01, 1.01).all(), "breakout_proximity out of [0,1]"
    assert not panel.empty and panel["date"].nunique() > 1
    assert not panel.duplicated(subset=["date", "ticker"]).any(), "duplicate (date,ticker) rows"

    print(f"panel -> {out}")
    print(f"  rows={len(panel):,}  tickers={panel['ticker'].nunique():,}  "
          f"days={panel['date'].nunique()}  "
          f"score[min/mean/max]={panel['prob_elite'].min():.3f}/"
          f"{panel['prob_elite'].mean():.3f}/{panel['prob_elite'].max():.3f}")


if __name__ == "__main__":
    main()
