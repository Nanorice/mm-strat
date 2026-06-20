"""Quantile calibration eval for m02 excursion variants — coverage + pinball loss.

Rank IC is the wrong metric for MFE/MAE quantile targets: their job is to give a usable
TP (P90 MFE) / SL (P10 MAE) *level*, not to rank names. The proper metric is calibration:

  P10 target: realized should fall BELOW the prediction ~10% of the time (coverage ~0.10)
  P90 target: realized should fall ABOVE the prediction ~10% of the time (coverage ~0.10)
  pinball loss: proper scoring rule for the quantile (lower = better calibrated)

Reads the per-fold boosters saved by train_m02_prototype.py (NO retraining), rebuilds each
fold's OOS test slice with the same target derivation, and reports per-variant coverage +
pinball averaged over folds.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import xgboost as xgb

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DUCKDB_PATH
from scripts.train_m02_prototype import (
    FEATURE_SET_ID, HORIZON, VARIANTS, VOL_COL,
    get_feature_cols, load_matrix, _prep_cat, _build_target, _slice,
)
from src.evaluation.walk_forward import anchored_walk_forward

EXCURSION_VARIANTS = ["raw_mfe", "vadj_mfe", "raw_mae", "vadj_mae"]


def pinball_loss(y: np.ndarray, q: np.ndarray, alpha: float) -> float:
    d = y - q
    return float(np.mean(np.maximum(alpha * d, (alpha - 1) * d)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, help="models/m02_prototype/<timestamp>")
    ap.add_argument("--db", default=str(DUCKDB_PATH))
    ap.add_argument("--train-start", default="2016-01-04")
    ap.add_argument("--test-start", default="2021-01-04")
    ap.add_argument("--test-end", default="2026-01-01")
    args = ap.parse_args()
    run_dir = Path(args.run_dir)

    con = duckdb.connect(args.db, read_only=True)
    feature_cols = get_feature_cols(con)
    con.close()
    df, used = load_matrix(args.db, feature_cols, smoke=False)

    specs = list(anchored_walk_forward(
        df, "date", date.fromisoformat(args.train_start),
        date.fromisoformat(args.test_start), date.fromisoformat(args.test_end),
        step="1Y", embargo_days=HORIZON,
    ))

    print(f"{'variant':10s} {'alpha':>5s} {'coverage':>9s} {'target':>7s} {'pinball':>9s}  (coverage should ~ target)")
    for v in EXCURSION_VARIANTS:
        alpha, raw_col, vol_norm = VARIANTS[v]
        # For P10 (alpha=.10) we want P(realized < pred) ~ .10; for P90 ~ P(realized > pred) ~ .10.
        covs, pins = [], []
        for spec in specs:
            mp = run_dir / v / f"fold_{spec.fold_idx:02d}_model.json"
            if not mp.exists():
                continue
            te = _slice(df, spec.test_start, spec.test_end).copy()
            te["_y"] = _build_target(te, raw_col, vol_norm)
            te = te.dropna(subset=["_y"])
            booster = xgb.Booster(); booster.load_model(str(mp))
            pred = booster.predict(xgb.DMatrix(_prep_cat(te[used]), enable_categorical=True))
            y = te["_y"].to_numpy()
            if alpha <= 0.5:
                cov = float(np.mean(y < pred))   # lower-tail quantile
                tgt = alpha
            else:
                cov = float(np.mean(y > pred))   # upper-tail quantile
                tgt = 1 - alpha
            covs.append(cov)
            pins.append(pinball_loss(y, pred, alpha))
        if covs:
            print(f"{v:10s} {alpha:5.2f} {np.mean(covs):9.3f} {(alpha if alpha<=.5 else 1-alpha):7.2f} "
                  f"{np.mean(pins):9.3f}")


if __name__ == "__main__":
    main()
