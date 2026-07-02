"""Phase 1 (m02_breakout): dense forward target generation.

Builds `m02_breakout_targets` — one row per (ticker, date) with the forward
regression target, computed from the `price_data` panel joined with `sepa_watchlist`.

Target: `breakout_proximity`
    - days_to_breakout = MIN(entry_date - date) where entry_date > date
    - If days_to_breakout <= horizon (e.g. 60 calendar days):
        breakout_proximity = exp(-decay * days_to_breakout)
    - Else:
        breakout_proximity = 0.0

This continuous target prioritizes tickers that are closer to a breakout event.
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

TARGET_TABLE = "m02_breakout_targets"
DEFAULT_HORIZON_DAYS = 60
DEFAULT_DECAY = 0.1


def build_targets(
    db_path: str = str(DUCKDB_PATH),
    horizon: int = DEFAULT_HORIZON_DAYS,
    decay: float = DEFAULT_DECAY
) -> int:
    """(Re)build the dense forward-target table. Returns row count."""
    con = duckdb.connect(db_path, read_only=False)
    try:
        # We need a cross/asof/range join.
        # An efficient way is a LATERAL join or windowing, but DuckDB supports ASOF and range joins.
        # Alternatively, we can use a window function over a combined table, but range join is easier:
        # "Find the earliest entry_date > date"
        
        con.execute(f"""
            CREATE OR REPLACE TABLE {TARGET_TABLE} AS
            WITH next_breakouts AS (
                SELECT 
                    p.ticker,
                    p.date,
                    p.close,
                    MIN(s.entry_date) AS next_breakout_date
                FROM price_data p
                LEFT JOIN sepa_watchlist s
                    ON p.ticker = s.ticker
                    AND s.entry_date > p.date
                    -- Only look forward up to the horizon to keep the join bounded
                    AND s.entry_date <= p.date + INTERVAL {horizon} DAY
                GROUP BY p.ticker, p.date, p.close
            )
            SELECT
                ticker,
                date,
                close AS entry_close,
                next_breakout_date,
                CASE 
                    WHEN next_breakout_date IS NOT NULL 
                    THEN date_diff('day', date, next_breakout_date) 
                    ELSE NULL 
                END AS days_to_breakout,
                CASE 
                    WHEN next_breakout_date IS NOT NULL 
                    THEN EXP(-{decay} * date_diff('day', date, next_breakout_date))
                    ELSE 0.0 
                END AS breakout_proximity
            FROM next_breakouts
        """)
        n = con.execute(f"SELECT COUNT(*) FROM {TARGET_TABLE}").fetchone()[0]
        n_pos = con.execute(
            f"SELECT COUNT(*) FROM {TARGET_TABLE} WHERE breakout_proximity > 0"
        ).fetchone()[0]
    finally:
        con.close()

    logger.info(
        "%s built: %d rows (%d with positive proximity score)",
        TARGET_TABLE, n, n_pos
    )
    print(f"[OK] {TARGET_TABLE}: {n:,} rows, {n_pos:,} with positive proximity score")
    return n


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Build dense m02_breakout forward targets")
    parser.add_argument("--db", default=str(DUCKDB_PATH), help="DuckDB path")
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON_DAYS, help="Forward horizon (calendar days)")
    parser.add_argument("--decay", type=float, default=DEFAULT_DECAY, help="Exponential decay rate (k)")
    args = parser.parse_args()
    build_targets(db_path=args.db, horizon=args.horizon, decay=args.decay)


if __name__ == "__main__":
    main()
