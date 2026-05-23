"""Daily prediction logger.

Writes one row per (prediction_date, ticker, model_version_id) into
`daily_predictions`. Rank is computed by descending production-class probability
within `prediction_date`. Idempotent — re-running the same date overwrites
previous rows (INSERT OR REPLACE).

Decisioning (`decision_taken`) stays NULL until the dashboard UI lands; that's
intentional. The point of logging now is so the analysis history is already
populated when the UI starts being used.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import List, Optional

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

# Path is resolved from the package, not the cwd, so the writer works whether
# called from notebooks, the orchestrator, or a test harness.
_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "migrations"
    / "2026_05_24_create_daily_predictions.sql"
)


def ensure_schema(db_path: Path) -> None:
    """Apply the daily_predictions migration. Idempotent."""
    if not _MIGRATION_PATH.exists():
        raise FileNotFoundError(f"migration file not found: {_MIGRATION_PATH}")
    sql = _MIGRATION_PATH.read_text(encoding="utf-8")
    con = duckdb.connect(str(db_path))
    try:
        con.execute(sql)
    finally:
        con.close()


def log_daily_predictions(
    db_path: Path,
    prediction_date: date,
    model_version_id: str,
    predictions: pd.DataFrame,
    production_class_idx: int = 3,
) -> int:
    """Insert (or replace) daily predictions for `prediction_date`.

    Required columns on `predictions`:
      - ticker
      - prob_class_0, prob_class_1, ..., prob_class_K (at least one)
      - predicted_class

    Returns the number of rows written.
    """
    ensure_schema(db_path)

    if predictions.empty:
        logger.info("log_daily_predictions: empty predictions, nothing to write")
        return 0

    df = predictions.copy()

    required = {"ticker", "predicted_class"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"predictions DataFrame missing required cols: {sorted(missing)}")

    prob_cols = [c for c in df.columns if c.startswith("prob_class_")]
    if not prob_cols:
        raise ValueError("predictions DataFrame must include at least one prob_class_* column")

    prod_col = f"prob_class_{production_class_idx}"
    if prod_col not in df.columns:
        raise ValueError(
            f"production_class_idx={production_class_idx} ⇒ expected column "
            f"{prod_col!r} but it is not in the DataFrame ({prob_cols})"
        )

    # Rank by production-class probability (1 = highest).
    df["rank_within_day"] = (
        df[prod_col].rank(method="first", ascending=False).astype(int)
    )

    # Build the column list the schema expects. Pad missing prob columns with None.
    full_prob_cols = ["prob_class_0", "prob_class_1", "prob_class_2", "prob_class_3"]
    for c in full_prob_cols:
        if c not in df.columns:
            df[c] = None

    df["prediction_date"] = prediction_date
    df["model_version_id"] = model_version_id

    out_cols = [
        "prediction_date",
        "ticker",
        "model_version_id",
        "prob_class_0",
        "prob_class_1",
        "prob_class_2",
        "prob_class_3",
        "predicted_class",
        "rank_within_day",
    ]
    out = df[out_cols]

    con = duckdb.connect(str(db_path))
    try:
        con.register("_pred_batch", out)
        # INSERT OR REPLACE: the table has a composite PK so this overwrites
        # any prior row for the same (date, ticker, model).
        con.execute(
            """
            INSERT OR REPLACE INTO daily_predictions
                (prediction_date, ticker, model_version_id,
                 prob_class_0, prob_class_1, prob_class_2, prob_class_3,
                 predicted_class, rank_within_day)
            SELECT prediction_date, ticker, model_version_id,
                   prob_class_0, prob_class_1, prob_class_2, prob_class_3,
                   predicted_class, rank_within_day
            FROM _pred_batch
            """
        )
        con.unregister("_pred_batch")
    finally:
        con.close()

    logger.info(
        "log_daily_predictions: wrote %d rows for date=%s model=%s",
        len(out), prediction_date, model_version_id,
    )
    return int(len(out))
