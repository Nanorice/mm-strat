"""Backfill fundamentals from SEC EDGAR, FMP, or yfinance for historical periods.

Sources
-------
  edgar (default)  SEC XBRL facts via EDGAR — free, no API key, INSERT OR IGNORE
  fmp              FMP quarterly IS/BS/CF — INSERT OR REPLACE (wins on conflict)
  yfinance         yfinance IS/BS/CF — free, no API key, batch fetch with resume

Usage
-----
    # EDGAR full backfill (all tickers missing pre-2024 history):
    python scripts/backfill_fundamentals.py [--start 1995-01-01] [--workers 2] [--resume]

    # FMP full backfill:
    python scripts/backfill_fundamentals.py --source fmp [--workers 4]

    # FMP with screener cross-check (intersect company_profiles ∩ FMP screener):
    python scripts/backfill_fundamentals.py --source fmp --screener-check

    # yfinance full backfill (free, no API key):
    python scripts/backfill_fundamentals.py --source yfinance [--workers 2] [--resume]

    # Test specific tickers:
    python scripts/backfill_fundamentals.py --tickers AAPL JPM NOW [--dry-run]

    # Standalone data quality report:
    python scripts/backfill_fundamentals.py --report

Steps (EDGAR)
    1. Load tickers missing pre-2024 history from company_profiles (or --tickers)
    2. Fetch CIK map (one SEC call)
    3. Batch fetch + resolve EDGAR XBRL facts per ticker
    4. INSERT OR IGNORE into fundamentals + shares_history
    5. Checkpoint every 100 tickers for resume support

Steps (FMP)
    1. Load tickers from company_profiles (or --tickers, or screener if --screener-check)
    2. Batch fetch IS/BS/CF from FMP /stable endpoints
    3. INSERT OR REPLACE into fundamentals (FMP supersedes yfinance on conflict)

Steps (yfinance)
    1. Load tickers from company_profiles (or --tickers)
    2. Fetch IS + BS + CF from yfinance via FundamentalEngine
    3. UPSERT into fundamentals table
    4. Resume support: skips tickers already populated
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional, Set

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.fundamental_edgar_engine import FundamentalEdgarEngine, TAXONOMY
from src.fundamental_fmp_engine import FundamentalFmpEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"
CHECKPOINT_FILE = Path(__file__).parent.parent / "data" / "edgar_backfill_checkpoint.json"
BATCH_SIZE = 100


def load_target_tickers(db_path: str, pre_cutoff: str = "2024-01-01") -> List[str]:
    """Return tickers in company_profiles that have no fundamentals before pre_cutoff."""
    con = duckdb.connect(db_path, read_only=True)
    try:
        result = con.execute(f"""
            SELECT cp.ticker
            FROM company_profiles cp
            WHERE cp.ticker NOT IN (
                SELECT DISTINCT ticker
                FROM fundamentals
                WHERE period_end < '{pre_cutoff}'
            )
            ORDER BY cp.ticker
        """).fetchall()
        return [r[0] for r in result]
    finally:
        con.close()


def load_all_profile_tickers(db_path: str) -> List[str]:
    """Return all tickers in company_profiles (used for FMP full backfill)."""
    con = duckdb.connect(db_path, read_only=True)
    try:
        result = con.execute("SELECT ticker FROM company_profiles ORDER BY ticker").fetchall()
        return [r[0] for r in result]
    finally:
        con.close()


def run_fmp_backfill(
    start_date: str,
    workers: int,
    tickers: Optional[List[str]],
    screener_check: bool,
    report: bool,
    overwrite: bool = False,
) -> None:
    """Fetch FMP fundamentals and write to DuckDB.

    overwrite=True  → ON CONFLICT DO UPDATE (initial backfill — clobbers edgar/yfinance)
    overwrite=False → ON CONFLICT DO NOTHING (safe re-runs)
    """
    engine = FundamentalFmpEngine(db_path=str(DB_PATH))

    if tickers:
        remaining = tickers
        logger.info(f"📋 FMP run — {len(remaining)} tickers specified")
    else:
        db_tickers = set(load_all_profile_tickers(str(DB_PATH)))
        logger.info(f"📋 {len(db_tickers)} tickers in company_profiles")

        if screener_check:
            screener_tickers = set(engine.fetch_screener_universe())
            intersection = db_tickers & screener_tickers
            screener_only = screener_tickers - db_tickers
            db_only = db_tickers - screener_tickers
            logger.info(
                f"🔍 Screener cross-check: "
                f"intersection={len(intersection)}, "
                f"screener-only={len(screener_only)} (not in DB), "
                f"db-only={len(db_only)} (not in screener)"
            )
            if screener_only:
                logger.info(
                    f"  ⚠️  Screener-only tickers (consider adding to universe): "
                    f"{sorted(screener_only)[:20]}"
                )
            remaining = sorted(intersection)
            logger.info(f"  Using intersection: {len(remaining)} tickers")
        else:
            remaining = sorted(db_tickers)

    if not remaining:
        logger.info("✅ Nothing to do.")
        return

    total_fund = 0
    for batch_start in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[batch_start: batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(remaining) + BATCH_SIZE - 1) // BATCH_SIZE

        logger.info(
            f"📦 Batch {batch_num}/{total_batches}  "
            f"({batch_start + 1}-{min(batch_start + BATCH_SIZE, len(remaining))} "
            f"of {len(remaining)})"
        )
        try:
            counts = engine.backfill(batch, start_date=start_date, workers=workers, overwrite=overwrite)
            total_fund += counts["fundamentals"]
            logger.info(
                f"  ✅ Batch done — fundamentals +{counts['fundamentals']}  "
                f"(cumulative: {total_fund})"
            )
        except Exception as exc:
            logger.error(f"  ❌ Batch failed: {exc}")
            sys.exit(1)

    logger.info(f"\n🚀 FMP backfill complete — fundamentals: {total_fund} rows")

    if report:
        print_quality_report(str(DB_PATH))


def run_yfinance_backfill(
    workers: int,
    tickers: Optional[List[str]],
    resume: bool,
    report: bool,
) -> None:
    """Fetch fundamentals from yfinance and write to DuckDB."""
    from src.fundamental_engine import FundamentalEngine

    engine = FundamentalEngine(db_path=str(DB_PATH), source='yfinance')

    if tickers:
        remaining = tickers
        logger.info(f"📋 yfinance run — {len(remaining)} tickers specified")
    else:
        all_tickers = load_all_profile_tickers(str(DB_PATH))
        logger.info(f"📋 {len(all_tickers)} tickers in company_profiles")

        if resume:
            populated = _get_populated_tickers_yf(str(DB_PATH))
            remaining = [t for t in all_tickers if t not in populated]
            logger.info(f"⏩ Resume: {len(populated)} already populated, {len(remaining)} remaining")
        else:
            remaining = all_tickers

    if not remaining:
        logger.info("✅ Nothing to do.")
        return

    total_ok = 0
    total_fail = 0

    for batch_start in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[batch_start: batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(remaining) + BATCH_SIZE - 1) // BATCH_SIZE

        logger.info(
            f"📦 Batch {batch_num}/{total_batches}  "
            f"({batch_start + 1}-{min(batch_start + BATCH_SIZE, len(remaining))} "
            f"of {len(remaining)})"
        )
        results = engine.update_fundamentals(batch, force=True, max_workers=workers)
        batch_ok = sum(results.values())
        batch_fail = len(results) - batch_ok
        total_ok += batch_ok
        total_fail += batch_fail
        logger.info(f"  ✅ Batch done: {batch_ok} OK, {batch_fail} failed (cumulative: {total_ok}/{total_ok + total_fail})")

    logger.info(f"\n🚀 yfinance backfill complete — {total_ok} OK, {total_fail} failed")

    if report:
        print_quality_report(str(DB_PATH))


def _get_populated_tickers_yf(db_path: str) -> Set[str]:
    """Return tickers already present in fundamentals table (for yfinance resume)."""
    con = duckdb.connect(db_path, read_only=True)
    try:
        rows = con.execute("SELECT DISTINCT ticker FROM fundamentals").fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()
    finally:
        con.close()


def load_checkpoint() -> Set[str]:
    if CHECKPOINT_FILE.exists():
        data = json.loads(CHECKPOINT_FILE.read_text())
        return set(data.get("completed", []))
    return set()


def save_checkpoint(completed: Set[str]) -> None:
    CHECKPOINT_FILE.write_text(json.dumps({"completed": sorted(completed)}, indent=2))


# Columns that feed directly into derived features (growth, margins, ratios, quality).
# These are the "must-have" columns — null here means broken downstream features.
_KEY_COLS = [
    "total_revenue",
    "net_income",
    "gross_profit",
    "operating_income",
    "operating_cash_flow",
    "total_assets",
    "stockholders_equity",
    "total_debt",
    "current_assets",
    "current_liabilities",
    "capex",
]
_ALL_COLS = list(TAXONOMY.keys())


def _null_pct_expr(col: str) -> str:
    """SQL expression: percentage of NULLs for a column."""
    return f"ROUND(100.0 * SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS {col}"


def print_quality_report(db_path: str) -> None:
    """Three-view data quality report across the full fundamentals table (single-pass SQL)."""
    import sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-16"):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    con = duckdb.connect(db_path, read_only=True)
    W = 90
    SEP = "=" * W
    DIV = "-" * W

    try:
        # ── View 1: Universe summary + overall null% per column ──────────────
        null_exprs = ",\n        ".join(_null_pct_expr(c) for c in _ALL_COLS)
        overview = con.execute(f"""
            SELECT
                COUNT(*)                          AS total_rows,
                COUNT(DISTINCT ticker)            AS total_tickers,
                MIN(period_end)                   AS earliest,
                MAX(period_end)                   AS latest,
                SUM(CASE WHEN source='edgar' THEN 1 ELSE 0 END) AS edgar_rows,
                SUM(CASE WHEN source='yfinance' THEN 1 ELSE 0 END) AS yf_rows,
                {null_exprs}
            FROM fundamentals
        """).df()

        row = overview.iloc[0]
        print(f"\n{SEP}")
        print(f"  FUNDAMENTALS DATA QUALITY REPORT")
        print(SEP)
        print(
            f"  Universe : {int(row['total_tickers']):,} tickers   "
            f"{int(row['total_rows']):,} rows   "
            f"{row['earliest']} → {row['latest']}"
        )
        print(
            f"  Sources  : edgar={int(row['edgar_rows']):,}   "
            f"yfinance={int(row['yf_rows']):,}"
        )

        print(f"\n{'VIEW 1':─^{W}}")
        print(f"  Overall % NULL per column (all {int(row['total_tickers']):,} tickers)\n")

        key_set = set(_KEY_COLS)
        col_w = max(len(c) for c in _ALL_COLS)
        bar_w = 30

        for col in _ALL_COLS:
            pct = float(row[col])
            filled = int(bar_w * (100 - pct) / 100)
            bar = "█" * filled + "░" * (bar_w - filled)
            flag = "  ◄ KEY" if col in key_set else ""
            status = "✅" if pct == 0 else ("⚠️" if pct < 50 else "❌")
            print(f"  {status} {col:<{col_w}}  [{bar}]  {100-pct:5.1f}% present{flag}")

        # ── View 2: null% per column, grouped by industry ────────────────────
        print(f"\n{'VIEW 2':─^{W}}")
        print(f"  % NULL per key column, by industry\n")

        key_null_exprs = ",\n        ".join(_null_pct_expr(c) for c in _KEY_COLS)
        industry_df = con.execute(f"""
            SELECT
                COALESCE(cp.industry, 'Unknown')  AS industry,
                COUNT(DISTINCT f.ticker)           AS tickers,
                COUNT(*)                           AS rows,
                {key_null_exprs}
            FROM fundamentals f
            LEFT JOIN company_profiles cp ON cp.ticker = f.ticker
            GROUP BY industry
            ORDER BY tickers DESC
        """).df()

        # Header
        ind_w = min(30, industry_df["industry"].str.len().max() + 2)
        col_headers = "  ".join(f"{c[:10]:>10}" for c in _KEY_COLS)
        print(f"  {'Industry':<{ind_w}} {'Tkrs':>5}  {col_headers}")
        print(f"  {DIV}")

        for _, r in industry_df.iterrows():
            ind = str(r["industry"])[:ind_w]
            vals = "  ".join(
                f"{100 - float(r[c]):>9.0f}%" for c in _KEY_COLS
            )
            print(f"  {ind:<{ind_w}} {int(r['tickers']):>5}  {vals}")

        # ── View 3: Top 20 tickers with worst key-column coverage ────────────
        print(f"\n{'VIEW 3':─^{W}}")
        print(f"  Top 20 tickers with most missing key columns\n")

        # Score = number of key cols with >50% null (worst = most missing)
        missing_cases = " + ".join(
            f"CASE WHEN SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) * 1.0 / COUNT(*) > 0.5 THEN 1 ELSE 0 END"
            for c in _KEY_COLS
        )
        key_null_ticker = ",\n        ".join(
            f"ROUND(100.0 * SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) / COUNT(*), 0) AS {c}"
            for c in _KEY_COLS
        )
        worst_df = con.execute(f"""
            SELECT
                f.ticker,
                COALESCE(cp.industry, 'Unknown')  AS industry,
                COUNT(*)                           AS rows,
                MIN(f.period_end)                  AS earliest,
                MAX(f.period_end)                  AS latest,
                ({missing_cases})                  AS missing_key_cols,
                {key_null_ticker}
            FROM fundamentals f
            LEFT JOIN company_profiles cp ON cp.ticker = f.ticker
            GROUP BY f.ticker, cp.industry
            HAVING missing_key_cols > 0
            ORDER BY missing_key_cols DESC, rows ASC
            LIMIT 20
        """).df()

        if worst_df.empty:
            print("  ✅ All tickers have full key-column coverage.")
        else:
            tk_w = 8
            ind_w2 = 22
            col_headers2 = "  ".join(f"{c[:9]:>9}" for c in _KEY_COLS)
            print(f"  {'Ticker':<{tk_w}} {'Industry':<{ind_w2}} {'Rows':>5}  {'Range':<23}  {col_headers2}")
            print(f"  {DIV}")
            for _, r in worst_df.iterrows():
                rng = f"{r['earliest']} – {r['latest']}"
                vals = "  ".join(
                    f"{'  --   ' if float(r[c]) == 100 else f'{100-float(r[c]):>8.0f}%'}"
                    for c in _KEY_COLS
                )
                print(
                    f"  {r['ticker']:<{tk_w}} {str(r['industry'])[:ind_w2]:<{ind_w2}} "
                    f"{int(r['rows']):>5}  {rng:<23}  {vals}"
                )

        print(f"\n{SEP}\n")

    finally:
        con.close()


def run_backfill(
    start_date: str,
    workers: int,
    resume: bool,
    tickers: Optional[List[str]] = None,
    dry_run: bool = False,
    report: bool = False,
    overwrite: bool = False,
) -> None:
    if tickers:
        remaining = tickers
        logger.info(f"📋 Test run — {len(remaining)} tickers specified")
    else:
        all_tickers = load_target_tickers(str(DB_PATH))
        logger.info(f"📋 {len(all_tickers)} tickers need historical fundamentals")
        completed: Set[str] = set()
        if resume:
            completed = load_checkpoint()
            logger.info(f"⏩ Resuming — {len(completed)} tickers already done")
        remaining = [t for t in all_tickers if t not in completed]
        logger.info(f"🔄 {len(remaining)} tickers to process")

    if not remaining:
        logger.info("✅ Nothing to do.")
        return

    engine = FundamentalEdgarEngine(db_path=str(DB_PATH))

    if dry_run:
        logger.info("🔍 Dry run — fetching without writing to DB")
        cik_map = engine._fetch_cik_map()
        for ticker in remaining:
            cik = cik_map.get(ticker)
            if not cik:
                logger.warning(f"{ticker}: not in CIK map")
                continue
            facts = engine._fetch_company_facts(cik)
            if facts is None:
                continue
            df = engine._resolve_fundamentals(ticker, facts, start_date)
            shares_df = engine._resolve_shares(ticker, facts, start_date)
            fund_rows = len(df) if df is not None else 0
            shares_rows = len(shares_df) if shares_df is not None else 0
            logger.info(f"  {ticker}: {fund_rows} fundamental rows, {shares_rows} shares rows (not written)")
        return

    total_fund = 0
    total_shares = 0

    for batch_start in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[batch_start: batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(remaining) + BATCH_SIZE - 1) // BATCH_SIZE

        logger.info(
            f"📦 Batch {batch_num}/{total_batches}  "
            f"({batch_start + 1}–{min(batch_start + BATCH_SIZE, len(remaining))} "
            f"of {len(remaining)})"
        )

        try:
            counts = engine.backfill(batch, start_date=start_date, workers=workers, overwrite_edgar=overwrite)
            total_fund += counts["fundamentals"]
            total_shares += counts["shares_history"]
            if not tickers:
                completed.update(batch)
                save_checkpoint(completed)
            logger.info(
                f"  ✅ Batch done — "
                f"fundamentals +{counts['fundamentals']}, "
                f"shares +{counts['shares_history']}  "
                f"(cumulative: {total_fund} / {total_shares})"
            )
        except Exception as exc:
            logger.error(f"  ❌ Batch failed: {exc}")
            if not tickers:
                logger.info("  Checkpoint saved — run with --resume to continue")
                save_checkpoint(completed)
            sys.exit(1)

    logger.info(
        f"\n🚀 Backfill complete — "
        f"fundamentals: {total_fund} rows, "
        f"shares_history: {total_shares} rows"
    )
    if not tickers and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("🧹 Checkpoint file removed")

    if report:
        print_quality_report(str(DB_PATH))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill fundamentals from EDGAR (free), FMP (subscription), or yfinance (free)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source", choices=["edgar", "fmp", "yfinance"], default="edgar",
        help="Data source: 'edgar' (XBRL, free), 'fmp' (API, subscription), or 'yfinance' (free)",
    )
    parser.add_argument("--start", default="1995-01-01", help="Earliest period_end to include (default: 1995-01-01)")
    parser.add_argument("--workers", type=int, default=2, help="Parallel fetch workers (edgar max 4, fmp max 8)")
    parser.add_argument("--resume", action="store_true", help="[edgar] Skip tickers in checkpoint file")
    parser.add_argument("--tickers", nargs="+", metavar="TICKER", help="Test with specific tickers instead of full universe")
    parser.add_argument("--dry-run", action="store_true", help="[edgar] Fetch and resolve but do NOT write to DB")
    parser.add_argument("--overwrite", action="store_true", help="[fmp] ON CONFLICT DO UPDATE — clobbers existing edgar/yfinance rows. [edgar] DELETE before re-inserting. Required for initial backfill.")
    parser.add_argument("--screener-check", action="store_true", help="[fmp] Cross-check target list against FMP screener universe")
    parser.add_argument("--report", action="store_true", help="Print data quality report (usable standalone or after backfill)")
    args = parser.parse_args()

    # Standalone quality report (no backfill)
    if args.report and not any([args.tickers, args.dry_run, args.resume]):
        print_quality_report(str(DB_PATH))
        return

    if args.source == "yfinance":
        workers = min(args.workers, 8)
        run_yfinance_backfill(
            workers=workers,
            tickers=args.tickers,
            resume=args.resume,
            report=args.report,
        )
    elif args.source == "fmp":
        workers = min(args.workers, 8)
        run_fmp_backfill(
            start_date=args.start,
            workers=workers,
            tickers=args.tickers,
            screener_check=args.screener_check,
            report=args.report,
            overwrite=args.overwrite,
        )
    else:
        workers = min(args.workers, 4)
        if workers != args.workers:
            logger.warning(f"Workers capped at 4 (SEC rate limit) — using {workers}")
        run_backfill(
            start_date=args.start,
            workers=workers,
            resume=args.resume,
            tickers=args.tickers,
            dry_run=args.dry_run,
            report=args.report,
            overwrite=args.overwrite,
        )


if __name__ == "__main__":
    main()
