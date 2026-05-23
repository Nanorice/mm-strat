"""
Inline m01_rank scorer — reproduces the m01_rank.ipynb model.

The saved models/m01_rank/model.json artifact is a stale rank:pairwise model.
The CURRENT m01_rank work (notebooks/m01_rank.ipynb cell 16) trains a fresh
XGBClassifier(binary:logistic) on dense t3 features with y_homerun (>20% in
HORIZON days), then RANK-GATES on the daily cross-sectional percentile of the
predicted probability (not the raw probability). This module reproduces that
exactly so the backtest layer (Case 2/3) uses the same signal.

train_and_score():
  - loads dense t3 (load_pretrain_data), builds y_homerun at the given horizon
  - feature_cols via _select_feature_cols minus leakage/forward cols
  - trains on date < train_end, scores [train_end, score_end]
  - returns (scored_df, model, feature_cols) where scored_df has
    date, ticker, m01_rank_prob, m01_rank_pct (daily cross-sectional rank 0-1)
"""

import sys
from pathlib import Path
from typing import Optional, Tuple

import duckdb
import numpy as np
import pandas as pd
import xgboost as xgb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from src.evaluation.data_quality import warmup_clip
from src.evaluation.pretrain_report import _select_feature_cols

LEAKAGE_EXTRAS = {"y_homerun", "mfe_pct", "mae_pct", "days_observed",
                  "return_1d", "return_5d", "return_20d", "return_60d"}
FEATURE_VERSION = "v3.1"
DB_PATH = str(config.DATA_DIR / "market_data.duckdb")


def load_dense_window(start: str, end: str) -> pd.DataFrame:
    """Date-bounded dense t3 load — avoids materializing all 9.3M rows.

    Mirrors load_pretrain_data(mode='dense') but pushes the date filter into
    DuckDB so the full-history copy never lands in RAM.
    """
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        df = con.execute(
            "SELECT * FROM t3_sepa_features "
            "WHERE feature_version = ? AND date >= ? AND date <= ?",
            [FEATURE_VERSION, start, end],
        ).df()
    finally:
        con.close()
    df.columns = df.columns.str.lower()
    return df


def build_dense_target(df: pd.DataFrame, horizon: int, threshold: float) -> pd.DataFrame:
    """Forward-return home-run target recomputed per ticker (matches notebook)."""
    df = df.sort_values(["ticker", "date"])
    df = warmup_clip(df)
    g = df.groupby("ticker", group_keys=False)
    df[f"return_{horizon}d_fwd"] = g["close"].shift(-horizon) / df["close"] - 1.0
    df["y_homerun"] = (df[f"return_{horizon}d_fwd"] > threshold).astype(int)
    return df


def select_features(df: pd.DataFrame) -> list:
    fwd_cols = [c for c in df.columns if c.endswith("_fwd")]
    candidate = _select_feature_cols(df)
    return [f for f in candidate if f not in LEAKAGE_EXTRAS and f not in fwd_cols]


def _fit(Xtr: pd.DataFrame, ytr: pd.Series) -> xgb.XGBClassifier:
    for c in Xtr.select_dtypes(include=["object", "category"]).columns:
        Xtr[c] = Xtr[c].astype("category")
    spw = (len(ytr) - ytr.sum()) / (ytr.sum() + 1e-5)
    m = xgb.XGBClassifier(
        objective="binary:logistic", n_estimators=100, max_depth=4,
        learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
        scale_pos_weight=spw, enable_categorical=True,
        tree_method="hist", random_state=42,
    )
    m.fit(Xtr, ytr)
    return m


def train_and_score(
    train_end: str,
    score_start: str,
    score_end: str,
    horizon: int = 20,
    threshold: float = 0.20,
    load_start: str = "2016-01-01",
    df_cache: Optional[pd.DataFrame] = None,
) -> Tuple[pd.DataFrame, xgb.XGBClassifier, list]:
    """Train m01_rank classifier on <train_end, score [score_start, score_end].

    Returns scored_df (date, ticker, m01_rank_prob, m01_rank_pct), model, feature_cols.
    """
    if df_cache is not None:
        df = df_cache
    else:
        # Load a few extra days beyond score_end so the forward-return target
        # has lookahead room for the last scored rows (dropped after labeling).
        load_end = (pd.Timestamp(score_end) + pd.Timedelta(days=horizon * 2)).strftime("%Y-%m-%d")
        df = load_dense_window(load_start, load_end)
        df = build_dense_target(df, horizon, threshold)

    feature_cols = select_features(df)

    tr = df[df["date"] < pd.Timestamp(train_end)]
    Xtr, ytr = tr[feature_cols].copy(), tr["y_homerun"]
    model = _fit(Xtr, ytr)

    te = df[(df["date"] >= pd.Timestamp(score_start)) &
            (df["date"] <= pd.Timestamp(score_end))].copy()
    Xte = te[feature_cols].copy()
    for c in Xte.select_dtypes(include=["object", "category"]).columns:
        Xte[c] = Xte[c].astype("category")
    te["m01_rank_prob"] = model.predict_proba(Xte)[:, 1]
    te["m01_rank_pct"] = te.groupby("date")["m01_rank_prob"].rank(pct=True)

    scored = te[["date", "ticker", "m01_rank_prob", "m01_rank_pct"]].copy()
    scored["date"] = pd.to_datetime(scored["date"])
    return scored, model, feature_cols
