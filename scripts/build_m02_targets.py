"""Phase 1 (m02_prototype): dense forward-21d target generation.

Builds `m02_prototype_targets` — one row per (ticker, date) with the forward
quantile-regression targets, computed from the calendar-contiguous `price_data`
panel (NOT t3_sepa_features, which has forward-only holes that would corrupt a
row-windowed forward aggregate; see project_t3_forward_only_holes).

Targets per pseudo-entry day t (entry at close[t]), over the next H trading days:
    fwd_mfe_pct  = MAX(high[t+1 .. t+H]) / close[t] - 1            (favorable excursion)
    fwd_mae_pct  = MIN(low [t+1 .. t+H]) / close[t] - 1            (adverse excursion)
    fwd_ret_pct  = close[t+H] / close[t] - 1                       (point return at horizon)

Semantics mirror the proven sparse trade target in view_manager.v_d2_training
(L581-582): the entry day itself is excluded from the excursion windows because
intraday high/low on day t occur before we enter at that day's close.

Window is `ROWS BETWEEN 1 FOLLOWING AND H FOLLOWING` over price_data partitioned
by ticker — "H rows" == "H trading days" exactly, and gap-safe because price_data
is contiguous. Rows without a full H-day forward window (the last H trading days
per ticker) get NULL targets and are flagged `has_full_window = FALSE`.

This table is the join source for the m02 training matrix: ASOF / equi-join it
onto t3_sepa_features by (ticker, date). It does NOT store features — features
stay in t3; this stores only targets, keeping the grain explicit and the
recompute cheap.
"""

import argparse
import logging
import sys
from pathlib import Path

import duckdb

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DUCKDB_PATH

logger = logging.getLogger(__name__)

TARGET_TABLE = "m02_prototype_targets"
DEFAULT_HORIZON = 21


def build_targets(
    db_path: str = str(DUCKDB_PATH),
    horizon: int = DEFAULT_HORIZON,
) -> int:
    """(Re)build the dense forward-target table. Returns row count."""
    con = duckdb.connect(db_path, read_only=False)
    try:
        con.execute(f"""
            CREATE OR REPLACE TABLE {TARGET_TABLE} AS
            WITH fwd AS (
                SELECT
                    ticker,
                    date,
                    close AS entry_close,
                    -- Forward excursion windows EXCLUDE day t (1 FOLLOWING .. H FOLLOWING):
                    -- intraday extremes on the entry day precede our close entry.
                    -- GREATEST/LEAST with close bounds the excursion against OHLC-integrity
                    -- dirt in price_data (21k rows have high<close, 20k have low>close —
                    -- penny-stock / bad-tick artifacts). Economically: you could always
                    -- exit at any day's close, so favorable/adverse excursion must dominate
                    -- every close in the window. This makes MFE >= ret >= MAE hold exactly.
                    MAX(GREATEST(high, close)) OVER w AS fwd_high,
                    MIN(LEAST(low, close))     OVER w AS fwd_low,
                    -- Close exactly H trading days ahead (NULL near the panel's right edge).
                    LEAD(close, {horizon}) OVER (
                        PARTITION BY ticker ORDER BY date
                    ) AS fwd_close,
                    -- Count of forward rows actually present in the window; < H means
                    -- we are inside the last H trading days for this ticker.
                    COUNT(*) OVER w AS fwd_rows
                FROM price_data
                WINDOW w AS (
                    PARTITION BY ticker ORDER BY date
                    ROWS BETWEEN 1 FOLLOWING AND {horizon} FOLLOWING
                )
            )
            SELECT
                ticker,
                date,
                entry_close,
                {horizon}                                          AS horizon,
                (fwd_rows = {horizon}) AND (fwd_close IS NOT NULL) AS has_full_window,
                CASE WHEN entry_close > 0
                    THEN (fwd_high  / entry_close - 1.0) * 100.0 END AS fwd_mfe_pct,
                CASE WHEN entry_close > 0
                    THEN (fwd_low   / entry_close - 1.0) * 100.0 END AS fwd_mae_pct,
                CASE WHEN entry_close > 0 AND fwd_close IS NOT NULL
                    THEN (fwd_close / entry_close - 1.0) * 100.0 END AS fwd_ret_pct
            FROM fwd
        """)
        n = con.execute(f"SELECT COUNT(*) FROM {TARGET_TABLE}").fetchone()[0]
        n_full = con.execute(
            f"SELECT COUNT(*) FROM {TARGET_TABLE} WHERE has_full_window"
        ).fetchone()[0]
    finally:
        con.close()

    logger.info(
        "%s built: %d rows (%d with full %dd window)",
        TARGET_TABLE, n, n_full, horizon,
    )
    print(f"[OK] {TARGET_TABLE}: {n:,} rows, {n_full:,} with full {horizon}d window")
    return n


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Build dense m02_prototype forward targets")
    parser.add_argument("--db", default=str(DUCKDB_PATH), help="DuckDB path")
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON, help="Forward H (trading days)")
    args = parser.parse_args()
    build_targets(db_path=args.db, horizon=args.horizon)


if __name__ == "__main__":
    main()
