"""Build a slim dashboard.duckdb from the full market_data.duckdb.

The full DB is ~67 GB, almost entirely t2_screener_features (57 GB) and
t3_sepa_features (8 GB) bloat. The dashboard reads only a thin slice: small
tables in full, the two big feature tables only at/near the latest date.

This script ATTACHes the source read-only and CREATE TABLE AS SELECTs each
manifest entry into a fresh dashboard.duckdb. A fresh CTAS also re-compacts
every table (the full DB carries heavy dead-space fragmentation), so the slim
DB lands far smaller than the row ratio alone implies.

Idempotent: the output file is rebuilt from scratch each run.

Usage:
    python scripts/build_dashboard_db.py [--window-days 252] [--out PATH] [--source PATH]

Manifest modes:
    full                 copy the whole table (small tables, watchlists, registry)
    window               keep rows within the last <window-days> of the table's MAX(date)
    window_plus_active   window PLUS all rows for tickers currently ACTIVE in the
                         watchlists (so multi-year super-performers keep full
                         feature history; dead names get trimmed)
    materialize_view     CREATE TABLE AS SELECT * FROM <view> (snapshot a view)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DB = ROOT / "data" / "market_data.duckdb"
OUT_DB = ROOT / "data" / "dashboard.duckdb"

DEFAULT_WINDOW_DAYS = 252

# Tickers considered "active" — their full feature history is preserved even
# when older than the window. Union of ACTIVE status across both watchlists.
ACTIVE_TICKERS_SQL = """
    SELECT ticker FROM src.sepa_watchlist     WHERE status = 'ACTIVE'
    UNION
    SELECT ticker FROM src.screener_watchlist WHERE status = 'ACTIVE'
"""

# (name, mode, spec). spec keys depend on mode:
#   window / window_plus_active: {"date_col": "date"}
#   materialize_view:            {"view": "v_d3_deployment"}
#   full:                        {} (or {"order_by": "..."} cosmetic)
MANIFEST: list[tuple[str, str, dict]] = [
    # ── Big feature tables — sliced to a plain window ────────────────────────
    #    The dashboard reads these only at/near the latest date (MAX-date spot,
    #    60d trend, 20d sector heat), so a flat window suffices. The
    #    `window_plus_active` mode below preserves full history for active
    #    tickers if a future page ever needs deep per-ticker feature history —
    #    swap the mode here to enable it.
    ("t2_screener_features", "window", {"date_col": "date"}),
    ("t3_sepa_features",     "window", {"date_col": "date"}),
    # ── Deployment features — materialized from the view (dashboard reads it
    #    via `SELECT * FROM v_d3_deployment`, table or view is transparent) ────
    ("v_d3_deployment",      "materialize_view",   {"view": "v_d3_deployment"}),
    # ── Small tables copied whole ────────────────────────────────────────────
    ("company_profiles",     "full", {}),
    ("d2_training_cache",    "full", {}),
    ("daily_predictions",    "full", {}),
    ("fundamentals",         "full", {}),
    ("shares_history",       "full", {}),
    ("macro_data",           "full", {}),
    ("t1_macro",             "full", {}),
    ("t2_regime_scores",     "full", {}),
    ("t2_risk_scores",       "full", {}),
    ("screener_membership",  "full", {}),   # ticker add/remove effective-date history
    ("screener_watchlist",   "full", {}),   # every ACTIVE + EXITED trade (removals via exit_date/status)
    ("sepa_watchlist",       "full", {}),
    ("earnings_calendar",    "full", {}),
    ("pipeline_runs",        "full", {}),   # 597 rows; 297 MB on disk is pure fragmentation, compacts to <1 MB
    ("pipeline_error_log",   "full", {}),
    ("models",               "full", {}),
    ("cik_map",              "full", {}),
]


def _build_table(con: duckdb.DuckDBPyConnection, name: str, mode: str,
                 spec: dict, window_days: int) -> int:
    """Create one slim table from the attached source. Returns row count."""
    con.execute(f'DROP TABLE IF EXISTS "{name}"')

    if mode == "full":
        select = f"SELECT * FROM src.{name}"

    elif mode == "materialize_view":
        select = f"SELECT * FROM src.{spec['view']}"

    elif mode in ("window", "window_plus_active"):
        date_col = spec["date_col"]
        cutoff = (
            f"(SELECT MAX({date_col}) - INTERVAL {int(window_days)} DAY "
            f"FROM src.{name})"
        )
        window_pred = f"{date_col} >= {cutoff}"
        if mode == "window":
            select = f"SELECT * FROM src.{name} WHERE {window_pred}"
        else:  # window_plus_active
            select = (
                f"SELECT * FROM src.{name} "
                f"WHERE {window_pred} "
                f"   OR ticker IN ({ACTIVE_TICKERS_SQL})"
            )
    else:
        raise ValueError(f"unknown manifest mode: {mode!r}")

    con.execute(f'CREATE TABLE "{name}" AS {select}')
    return con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]


def build(source: Path, out: Path, window_days: int) -> None:
    if not source.exists():
        raise FileNotFoundError(f"source DB not found: {source}")
    if out.exists():
        out.unlink()  # idempotent: rebuild from scratch

    t0 = time.time()
    con = duckdb.connect(str(out))
    try:
        con.execute(f"ATTACH '{source}' AS src (READ_ONLY)")
        print(f"[BUILD] {out.name} from {source.name} "
              f"(window={window_days}d)\n")
        print(f"{'table':<24}{'mode':<22}{'rows':>12}")
        print("-" * 58)
        total = 0
        for name, mode, spec in MANIFEST:
            try:
                n = _build_table(con, name, mode, spec, window_days)
                total += n
                print(f"{name:<24}{mode:<22}{n:>12,}")
            except duckdb.Error as e:
                print(f"{name:<24}{mode:<22}{'ERR':>12}  {e}")
        print("-" * 58)
        print(f"{'TOTAL':<46}{total:>12,}")
        con.execute("DETACH src")
    finally:
        con.close()

    size_mb = out.stat().st_size / 1024 ** 2
    print(f"\n[OK] {out.name}: {size_mb:,.1f} MB | {time.time() - t0:.1f}s")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build slim dashboard.duckdb")
    ap.add_argument("--source", type=Path, default=SOURCE_DB)
    ap.add_argument("--out", type=Path, default=OUT_DB)
    ap.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                    help="Lookback window for the big feature tables.")
    args = ap.parse_args()
    build(args.source, args.out, args.window_days)


if __name__ == "__main__":
    main()
