"""VIP watchlist — a manually-curated ticker list that WIDENS the T3 universe.

The pipeline normally DISCOVERS names (SEPA screen -> sepa_watchlist -> T3 features
-> prod score). This inverts it: names YOU add (from a report, a tip) get forced
into the T3 universe so the pipeline reports their daily status (trend_ok /
breakout_ok / prod score / lifecycle cohort) even if they'd never pass the screen.

Infra: the ONLY new state is this table. T3's candidate filter is widened by one
line to `sepa_watchlist UNION vip_watchlist WHERE active`, so VIP names get full
features FORWARD from their add_date — no fork of scoring/lifecycle, no backfill.
A `v_d3_vip` view (ViewManager) joins these names to their live status for display.

Curation is CLI-only (scripts/vip_add.py) — the dashboard reads the list read-only.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import duckdb
import pandas as pd

from src import db


class VipWatchlistManager:
    """CRUD for the human-curated VIP watchlist. No session/screen logic."""

    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        with db.connect(self.db_path) as conn:
            self._ensure_schema(conn)

    def _ensure_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vip_watchlist (
                ticker      VARCHAR  PRIMARY KEY,
                added_date  DATE     NOT NULL,
                source      VARCHAR,
                comment     VARCHAR,
                active      BOOLEAN  NOT NULL DEFAULT TRUE,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def add(self, ticker: str, source: str = "", comment: str = "",
            added: Optional[str] = None) -> None:
        """Add (or re-activate) a VIP name. Re-adding an existing ticker updates its
        source/comment and flips active back on (keeps the original added_date)."""
        ticker = ticker.strip().upper()
        if not ticker:
            raise ValueError("ticker is empty")
        added = added or date.today().isoformat()
        with db.connect(self.db_path) as conn:
            exists = conn.execute(
                "SELECT 1 FROM vip_watchlist WHERE ticker = ?", [ticker]
            ).fetchone()
            if exists:
                conn.execute(
                    "UPDATE vip_watchlist SET source = ?, comment = ?, active = TRUE, "
                    "updated_at = CURRENT_TIMESTAMP WHERE ticker = ?",
                    [source, comment, ticker],
                )
            else:
                conn.execute(
                    "INSERT INTO vip_watchlist (ticker, added_date, source, comment, active) "
                    "VALUES (?, ?, ?, ?, TRUE)",
                    [ticker, added, source, comment],
                )

    def remove(self, ticker: str) -> bool:
        """Soft-remove: flip active=FALSE (keeps history + stops widening T3).
        Returns True if a row was affected."""
        ticker = ticker.strip().upper()
        with db.connect(self.db_path) as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM vip_watchlist WHERE ticker = ? AND active",
                [ticker],
            ).fetchone()[0]
            conn.execute(
                "UPDATE vip_watchlist SET active = FALSE, updated_at = CURRENT_TIMESTAMP "
                "WHERE ticker = ?", [ticker],
            )
        return n > 0

    def list(self, active_only: bool = False) -> pd.DataFrame:
        where = "WHERE active" if active_only else ""
        with db.connect(self.db_path, read_only=True) as conn:
            return conn.execute(
                f"SELECT ticker, added_date, source, comment, active, updated_at "
                f"FROM vip_watchlist {where} ORDER BY added_date DESC, ticker"
            ).fetchdf()


if __name__ == "__main__":
    # Self-check: CRUD round-trip on a temp DB (add -> re-add updates -> soft-remove).
    import tempfile, os
    tmp = os.path.join(tempfile.mkdtemp(), "vip_test.duckdb")
    m = VipWatchlistManager(tmp)
    m.add("nvda", source="semis report", comment="AI capex cycle")
    assert m.list(active_only=True)["ticker"].tolist() == ["NVDA"], "add failed / not upper-cased"
    m.add("NVDA", source="semis report v2", comment="updated thesis")  # re-add updates in place
    row = m.list().iloc[0]
    assert row["source"] == "semis report v2" and row["comment"] == "updated thesis", "re-add didn't update"
    assert len(m.list()) == 1, "re-add duplicated the row"
    assert m.remove("NVDA") is True, "remove reported no active row"
    assert m.list(active_only=True).empty, "soft-remove didn't deactivate"
    assert len(m.list()) == 1, "soft-remove deleted history (should keep it)"
    print("[OK] VipWatchlistManager self-check: add / re-add-update / soft-remove all pass")
