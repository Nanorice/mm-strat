"""Daily prediction logger.

Writes one row per (prediction_date, ticker, model_version_id, cohort) into
`daily_predictions`. Rank is computed by descending production-class probability
within (`prediction_date`, `cohort`). Idempotent — re-running the same date/cohort
overwrites previous rows (INSERT OR REPLACE).

`cohort` is 'breakout' (SEPA entries) or 'pre_breakout' (in-setup names); both
are scored nightly under the prod model so the dashboard never scores live.

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
    / "2026_06_12_add_cohort_to_daily_predictions.sql"
)


def _migrate_add_cohort(con: duckdb.DuckDBPyConnection) -> None:
    """Fold `cohort` into daily_predictions + its PK when the column is missing.

    DuckDB can't ALTER a primary key in place, so we rebuild: rename the old
    table, recreate via the migration SQL (which carries the new PK), copy the
    pre-cohort rows back as 'breakout', then drop the old table.
    """
    cols = {r[1] for r in con.execute("PRAGMA table_info('daily_predictions')").fetchall()}
    if "cohort" in cols:
        return  # already migrated

    # Indexes depend on the table — drop before rename, the migration SQL recreates them.
    for idx in ("idx_daily_predictions_date", "idx_daily_predictions_model",
                "idx_daily_predictions_cohort"):
        con.execute(f"DROP INDEX IF EXISTS {idx}")

    con.execute("ALTER TABLE daily_predictions RENAME TO daily_predictions_old")
    con.execute(_MIGRATION_PATH.read_text(encoding="utf-8"))
    con.execute(
        """
        INSERT INTO daily_predictions
            (prediction_date, ticker, model_version_id, cohort,
             prob_class_0, prob_class_1, prob_class_2, prob_class_3,
             predicted_class, rank_within_day,
             decision_taken, taken_at, notes, ingested_at)
        SELECT prediction_date, ticker, model_version_id, 'breakout',
               prob_class_0, prob_class_1, prob_class_2, prob_class_3,
               predicted_class, rank_within_day,
               decision_taken, taken_at, notes, ingested_at
        FROM daily_predictions_old
        """
    )
    con.execute("DROP TABLE daily_predictions_old")


def ensure_schema(db_path: Path) -> None:
    """Apply the daily_predictions schema. Idempotent.

    Three cases:
      - no table          → run the migration SQL (fresh, cohort-aware table)
      - legacy table       → rebuild via _migrate_add_cohort (adds cohort + PK)
      - cohort-aware table → no-op
    """
    if not _MIGRATION_PATH.exists():
        raise FileNotFoundError(f"migration file not found: {_MIGRATION_PATH}")
    sql = _MIGRATION_PATH.read_text(encoding="utf-8")
    con = duckdb.connect(str(db_path))
    try:
        exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'daily_predictions'"
        ).fetchone()[0] > 0
        if not exists:
            con.execute(sql)  # fresh create — table + indexes both cohort-aware
        else:
            _migrate_add_cohort(con)  # rebuild iff legacy (no cohort) table present
    finally:
        con.close()


def log_daily_predictions(
    db_path: Path,
    prediction_date: date,
    model_version_id: str,
    predictions: pd.DataFrame,
    production_class_idx: int = 3,
    cohort: str = "breakout",
) -> int:
    """Insert (or replace) daily predictions for (`prediction_date`, `cohort`).

    Required columns on `predictions`:
      - ticker
      - prob_class_0, prob_class_1, ..., prob_class_K (at least one)
      - predicted_class

    `cohort` is 'breakout' or 'pre_breakout'. Rank is computed within the cohort.
    Returns the number of rows written.
    """
    if cohort not in ("breakout", "pre_breakout"):
        raise ValueError(f"cohort must be 'breakout' | 'pre_breakout', got {cohort!r}")
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
    df["cohort"] = cohort

    out_cols = [
        "prediction_date",
        "ticker",
        "model_version_id",
        "cohort",
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
        # any prior row for the same (date, ticker, model, cohort).
        con.execute(
            """
            INSERT OR REPLACE INTO daily_predictions
                (prediction_date, ticker, model_version_id, cohort,
                 prob_class_0, prob_class_1, prob_class_2, prob_class_3,
                 predicted_class, rank_within_day)
            SELECT prediction_date, ticker, model_version_id, cohort,
                   prob_class_0, prob_class_1, prob_class_2, prob_class_3,
                   predicted_class, rank_within_day
            FROM _pred_batch
            """
        )
        con.unregister("_pred_batch")
    finally:
        con.close()

    logger.info(
        "log_daily_predictions: wrote %d rows for date=%s model=%s cohort=%s",
        len(out), prediction_date, model_version_id, cohort,
    )
    return int(len(out))
