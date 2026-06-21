"""Shared categorical encoding for XGBoost inference.

XGBoost stores categoricals (industry/sector) as bare integer codes with no
string->code map, so every inference frame MUST be encoded against the model's
frozen training vocab or codes drift and out-of-vocab labels are rejected
("Found a category not in the training set"). The vocab is persisted at train
time as <artifacts>/categorical_mapping.json.

Daily scoring (ScoreEngine) and the model-card builder both route through here
so their encodings can't silently diverge — the failure mode that left scoring
and the drift card independently broken.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def load_categorical_map(model_path) -> dict[str, list[str]]:
    """Load the frozen training vocab persisted next to a model.

    `model_path` may be the model.json file or its artifacts directory. Returns
    {} when absent (older models) — callers then fall back to per-frame codes.
    """
    p = Path(model_path)
    base = p.parent if p.suffix == ".json" else p
    cat_path = base / "categorical_mapping.json"
    return json.loads(cat_path.read_text()) if cat_path.exists() else {}


def encode_categoricals(
    df: pd.DataFrame,
    feature_cols: list[str],
    categorical_map: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """Return a copy of `df` with categorical feature columns ready for XGBoost.

    Columns named in `categorical_map` are encoded against the frozen vocab
    (unseen labels -> NaN -> XGBoost missing, never a crash). Any other
    object-dtype feature column falls back to per-frame category codes.
    """
    categorical_map = categorical_map or {}
    out = df.copy()
    for col in feature_cols:
        if col not in out.columns:
            continue
        vocab = categorical_map.get(col)
        if vocab is not None:
            out[col] = pd.Categorical(out[col], categories=vocab)
        elif out[col].dtype == object:
            out[col] = out[col].astype("category")
    return out
