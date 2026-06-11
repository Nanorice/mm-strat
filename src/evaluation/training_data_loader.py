"""Pre-training data loader: one source, two modes.

Modes map to the verified DuckDB lineage (view_manager.py), not new SQL:

    dense  -> t3_sepa_features  (dense daily, ~9.3M rows, NO target — feature
              hygiene BEFORE trade aggregation). NOTE: the original plan named
              v_d2_features here, but v_d1_candidates Step 4 keeps only the
              entry-date row per trade, so v_d2_features is sparse (~38K, == the
              trades set minus outcomes). t3_sepa_features is the real dense table.
    trades -> v_d2_training   (sparse trade rows + outcome cols, model_proto.ipynb input)

The trades mode prefers d2_training_cache (materialized v_d2_training, ~70x faster)
when it is fresh relative to t3_sepa_features; otherwise it falls back to the view.

Columns are lowercased on load to match model_proto.ipynb and to be stable against
DuckDB's TitleCase cross-sectional rank columns.
"""

import logging
from typing import Literal

import duckdb
import numpy as np
import pandas as pd

from config import DUCKDB_PATH

logger = logging.getLogger(__name__)

DB_PATH = str(DUCKDB_PATH)
FEATURE_VERSION = "v3.1"

# Notebook default (model_proto.ipynb cell 29): np.select on mfe_pct.
# (low, high, class) — low is exclusive, high is inclusive; first/last are open-ended.
DEFAULT_MFE_BINS = [
    (-np.inf, 2.0, 0),   # Dud   : mfe_pct <= 2
    (2.0, 10.0, 1),      # Noise : 2  < mfe_pct <= 10
    (10.0, 30.0, 2),     # Solid : 10 < mfe_pct <= 30
    (30.0, np.inf, 3),   # Elite : mfe_pct > 30
]

# Named label-set registry. Add a new entry here to expose it via the CLI
# (--label-set NAME) and the pretrain audit. Each value is:
#   {"bins": [(low, high, class_idx), ...], "class_names": (str, ...)}
# bins use the np.select convention: low exclusive, high inclusive, first/last
# are open-ended. class_idx must be 0..N-1 contiguous.
LABEL_SETS: dict[str, dict] = {
    "default": {
        "bins": DEFAULT_MFE_BINS,
        "class_names": ("Dud", "Noise", "Solid", "Elite"),
    },
    # m01_binary: single-cutoff variant — anything that runs >= 10% MFE is
    # "Win", otherwise "Lose". Maps to the m01_binary model family.
    "binary": {
        "bins": [
            (-np.inf, 10.0, 0),
            (10.0, np.inf, 1),
        ],
        "class_names": ("Lose", "Win"),
    },
}

Mode = Literal["dense", "trades"]


def _cache_is_fresh(con: duckdb.DuckDBPyConnection) -> bool:
    """d2_training_cache is fresh iff it exists, is non-empty, and its newest
    trade date is not behind the newest t3_sepa_features date."""
    try:
        cache_max = con.execute(
            "SELECT MAX(date) FROM d2_training_cache"
        ).fetchone()[0]
    except duckdb.CatalogException:
        return False
    if cache_max is None:
        return False
    t3_max = con.execute("SELECT MAX(date) FROM t3_sepa_features").fetchone()[0]
    if t3_max is None:
        return False
    return cache_max >= t3_max


def load_pretrain_data(
    mode: Mode = "trades",
    db_path: str = DB_PATH,
) -> pd.DataFrame:
    """Load the pre-training input for the given mode.

    Args:
        mode: "dense" -> t3_sepa_features (dense daily, no target);
              "trades" -> v_d2_training (or fresh d2_training_cache).
        db_path: DuckDB path. Defaults to the project database.

    Returns:
        DataFrame with lowercased column names. "trades" mode is ordered
        (date, ticker) to match model_proto.ipynb exactly.
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        if mode == "dense":
            df = con.execute(
                "SELECT * FROM t3_sepa_features WHERE feature_version = ?",
                [FEATURE_VERSION],
            ).df()
            source = "t3_sepa_features"
        elif mode == "trades":
            if _cache_is_fresh(con):
                df = con.execute(
                    "SELECT * FROM d2_training_cache ORDER BY date, ticker"
                ).df()
                source = "d2_training_cache (fresh)"
            else:
                df = con.execute(
                    "SELECT * FROM v_d2_training ORDER BY date, ticker"
                ).df()
                source = "v_d2_training (cache stale/missing)"
        else:
            raise ValueError(f"mode must be 'dense' or 'trades', got {mode!r}")
    finally:
        con.close()

    df.columns = df.columns.str.lower()
    logger.info(
        "Loaded %s: %d rows x %d cols (mode=%s)",
        source, len(df), df.shape[1], mode,
    )
    return df


def derive_target_class(
    df: pd.DataFrame,
    source_col: str = "mfe_pct",
    bins=DEFAULT_MFE_BINS,
) -> pd.Series:
    """Derive the 0..3 target class from mfe_pct via np.select.

    Param-driven so bin-edge experiments are a one-arg change. Only valid in
    trades mode (dense has no mfe_pct). NaN source falls through to the first
    bin's class (matches notebook default=0 for the default bins).

    Args:
        df: trades-mode frame containing `source_col`.
        source_col: outcome column to bin (default "mfe_pct").
        bins: list of (low, high, class) — low exclusive, high inclusive.

    Returns:
        Integer Series aligned to df.index.
    """
    if source_col not in df.columns:
        raise KeyError(
            f"{source_col!r} not in frame — derive_target_class is trades-mode only"
        )
    vals = df[source_col]
    conditions = [(vals > low) & (vals <= high) for (low, high, _) in bins]
    choices = [cls for (_, _, cls) in bins]
    default = bins[0][2]
    return pd.Series(
        np.select(conditions, choices, default=default).astype(int),
        index=df.index,
        name="target_class",
    )
