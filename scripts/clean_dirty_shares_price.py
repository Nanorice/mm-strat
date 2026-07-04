"""Clean the dirty-shares / dirty-price corruption (sprint_13 ISSUE_dirty_shares_cap_dq_gap).

Three parts, all machine-portable (config-relative DB path + src.db governed connection),
so this runs identically on the research box (Hang) and the infra/ITX box (sh019).

  A. shares_history : null rows with shares_outstanding > 3e10 (real max ~25B; FMP 1000x dirt)
  B. fundamentals   : null basic_avg_shares > 3e10 (the source the backfill copied from)
  C. price_data     : null OHLC on dirty bars (close > 1e6) IN PLACE.
  D. shares_history : null sub-ceiling multiplicative dirt (>1B AND >100x ticker median) —
     the 1000x FMP dirt on SMALL tickers lands below any global bound (GTLS 29.9B vs real
     30M). Every flagged row was adjudicated 2026-07-04 against current fundamentals +
     implied cap; the only legit hit is whitelisted (EXE 1.957B pre-1:200-reverse-split).
  E. fundamentals   : same relative rule on basic_avg_shares (38 rows, all source=fmp,
     incl. sub-30B dirt that survived part B: CALC 15B, OPTT 1.3-1.9B at ~10x scale).
  F. price_data     : null OHLC on corrupt-ordering bars (high<close / low>close / high<low
     by >10%). 99.9% of ordering violations are <0.1% rounding epsilon — left alone.

  NOTE on C: refetch was investigated and REJECTED. yfinance's own period="max" history for
  these low-float / reverse-split tickers is ALSO dirty at the source (e.g. ADTX serves
  $3.7T/share for 1140 of 1509 bars). There is no clean upstream to refetch from, so we null
  the dirty bars and preserve the date spine (downstream returns compute from adjacent close).

All three parts are deterministic DB-only writes (no network). --smoke-test runs one price
ticker only so you can eyeball the null-out before the full pass.

Usage:
    python scripts/clean_dirty_shares_price.py --dry-run          # counts only, no writes
    python scripts/clean_dirty_shares_price.py --smoke-test       # A+B + null 1 price ticker
    python scripts/clean_dirty_shares_price.py                    # full clean
    python scripts/clean_dirty_shares_price.py --skip-price       # A+B only
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DUCKDB_PATH, T1_PLAUSIBILITY_BOUNDS
from src import db

SHARES_CAP = T1_PLAUSIBILITY_BOUNDS['shares_max']
PRICE_CAP = T1_PLAUSIBILITY_BOUNDS['close_max']
CAP_MAX = T1_PLAUSIBILITY_BOUNDS['implied_cap_max']
SCALE_ABS = T1_PLAUSIBILITY_BOUNDS['shares_scale_abs']
OHLC_EXCESS = T1_PLAUSIBILITY_BOUNDS['ohlc_excess_fail']
# Deliberately TIGHTER than the audit tripwire's 500x: this sweep was adjudicated row-by-row
# (2026-07-04) against current fundamentals + implied cap, so 100x is safe here but not as a
# standing unattended check.
SCALE_RATIO = 100
# Legit rows the relative rule would flag (verified point-in-time pre-reverse-split counts).
SCALE_WHITELIST = [("EXE", "2020-04-10")]  # Chesapeake 1.957B shares before 1:200 split


def _log(msg: str) -> None:
    print(msg, flush=True)


def clean_shares(con, dry_run: bool) -> int:
    n = con.execute(f"SELECT COUNT(*) FROM shares_history WHERE shares_outstanding > {SHARES_CAP}").fetchone()[0]
    _log(f"  A. shares_history rows > {SHARES_CAP:.0e}: {n}")
    if n and not dry_run:
        con.execute(f"UPDATE shares_history SET shares_outstanding = NULL WHERE shares_outstanding > {SHARES_CAP}")
        _log(f"     -> nulled {n} rows (downstream ffill bridges the gap)")
    return n


def clean_fundamentals(con, dry_run: bool) -> int:
    n = con.execute(f"SELECT COUNT(*) FROM fundamentals WHERE basic_avg_shares > {SHARES_CAP}").fetchone()[0]
    _log(f"  B. fundamentals.basic_avg_shares > {SHARES_CAP:.0e}: {n}")
    if n and not dry_run:
        con.execute(f"UPDATE fundamentals SET basic_avg_shares = NULL WHERE basic_avg_shares > {SHARES_CAP}")
        _log(f"     -> nulled {n} source rows (stops the backfill re-leaking them)")
    return n


def clean_price(con, dry_run: bool, smoke_test: bool) -> None:
    """Null OHLC on dirty bars (close > PRICE_CAP) in place. No refetch — see module docstring."""
    tickers = [r[0] for r in con.execute(
        f"SELECT DISTINCT ticker FROM price_data WHERE close > {PRICE_CAP} ORDER BY ticker"
    ).fetchall()]
    n_rows = con.execute(f"SELECT COUNT(*) FROM price_data WHERE close > {PRICE_CAP}").fetchone()[0]
    _log(f"  C. price_data dirty bars (close > {PRICE_CAP:.0e}): {n_rows} rows across {len(tickers)} tickers")

    if dry_run:
        _log(f"     [DRY RUN] would null OHLC on: {', '.join(tickers[:10])}{' ...' if len(tickers) > 10 else ''}")
        return

    where = f"close > {PRICE_CAP}"
    if smoke_test and tickers:
        where += f" AND ticker = '{tickers[0]}'"
        _log(f"     [SMOKE TEST] nulling 1 ticker only: {tickers[0]}")

    con.execute(f"UPDATE price_data SET open=NULL, high=NULL, low=NULL, close=NULL WHERE {where}")
    _log(f"     -> nulled OHLC on dirty bars (date spine preserved; downstream bridges the gap)")

    if smoke_test:
        return
    # Sub-ceiling cap dirt: close < $1M but implied cap > $8T (shares plausible, price still dirt).
    # Only the shares*close product reveals these; null by implied cap so we don't lower the
    # price ceiling and risk a genuinely high-priced stock.
    con.execute(f"""
        UPDATE price_data SET open=NULL, high=NULL, low=NULL, close=NULL
        WHERE (ticker, date) IN (
            SELECT p.ticker, p.date FROM price_data p JOIN shares_history s USING(ticker, date)
            WHERE s.shares_outstanding * p.close > {CAP_MAX} AND p.close <= {PRICE_CAP}
        )
    """)
    _log(f"     -> nulled sub-$1M bars with implied cap > $8T (cross-table net)")


def _whitelist_sql(col_ticker: str, col_date: str) -> str:
    if not SCALE_WHITELIST:
        return ""
    pairs = ", ".join(f"('{t}', DATE '{d}')" for t, d in SCALE_WHITELIST)
    return f" AND ({col_ticker}, {col_date}) NOT IN ({pairs})"


def clean_shares_relative(con, dry_run: bool) -> int:
    where = f"""
        (ticker, date) IN (
            SELECT s.ticker, s.date
            FROM shares_history s
            JOIN (SELECT ticker, MEDIAN(shares_outstanding) med
                  FROM shares_history WHERE shares_outstanding > 0 GROUP BY ticker) m
              USING(ticker)
            WHERE s.shares_outstanding > {SCALE_ABS}
              AND s.shares_outstanding > {SCALE_RATIO} * m.med
              {_whitelist_sql('s.ticker', 's.date')}
        )
    """
    n = con.execute(f"SELECT COUNT(*) FROM shares_history WHERE {where}").fetchone()[0]
    _log(f"  D. shares_history sub-ceiling scale dirt (>{SCALE_ABS:.0e} AND >{SCALE_RATIO}x median): {n}")
    if n and not dry_run:
        con.execute(f"UPDATE shares_history SET shares_outstanding = NULL WHERE {where}")
        _log(f"     -> nulled {n} rows (whitelist kept: {SCALE_WHITELIST})")
    return n


def clean_fundamentals_relative(con, dry_run: bool) -> int:
    where = f"""
        (ticker, period_end) IN (
            SELECT f.ticker, f.period_end
            FROM fundamentals f
            JOIN (SELECT ticker, MEDIAN(basic_avg_shares) med
                  FROM fundamentals WHERE basic_avg_shares > 0 GROUP BY ticker) m
              USING(ticker)
            WHERE f.basic_avg_shares > {SCALE_ABS}
              AND f.basic_avg_shares > {SCALE_RATIO} * m.med
        )
    """
    n = con.execute(f"SELECT COUNT(*) FROM fundamentals WHERE {where}").fetchone()[0]
    _log(f"  E. fundamentals sub-ceiling scale dirt (>{SCALE_ABS:.0e} AND >{SCALE_RATIO}x median): {n}")
    if n and not dry_run:
        con.execute(f"UPDATE fundamentals SET basic_avg_shares = NULL WHERE {where}")
        _log(f"     -> nulled {n} source rows (stops the backfill re-leaking them)")
    return n


def clean_ohlc_corrupt(con, dry_run: bool) -> int:
    where = f"""
        (high < close OR low > close OR high < low)
        AND (GREATEST(CASE WHEN high < close THEN close / NULLIF(high, 0) ELSE 1 END,
                      CASE WHEN low > close THEN low / NULLIF(close, 0) ELSE 1 END,
                      CASE WHEN high < low THEN low / NULLIF(high, 0) ELSE 1 END) - 1) > {OHLC_EXCESS}
    """
    n = con.execute(f"SELECT COUNT(*) FROM price_data WHERE {where}").fetchone()[0]
    _log(f"  F. price_data corrupt OHLC-ordering bars (violation > {OHLC_EXCESS:.0%}): {n}")
    if n and not dry_run:
        con.execute(f"UPDATE price_data SET open=NULL, high=NULL, low=NULL, close=NULL WHERE {where}")
        _log(f"     -> nulled {n} bars (date spine preserved)")
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description="Clean dirty shares/price corruption")
    ap.add_argument("--dry-run", action="store_true", help="Counts only, no writes")
    ap.add_argument("--smoke-test", action="store_true", help="A+B + null only 1 price ticker")
    ap.add_argument("--skip-price", action="store_true", help="Parts A+B only")
    args = ap.parse_args()

    mode = "DRY RUN" if args.dry_run else "SMOKE TEST" if args.smoke_test else "FULL"
    _log(f"\n{'='*60}\n  CLEAN dirty shares/price - {mode}\n  DB: {DUCKDB_PATH}\n{'='*60}")

    con = db.connect(str(DUCKDB_PATH), read_only=args.dry_run)
    try:
        clean_shares(con, args.dry_run)
        clean_fundamentals(con, args.dry_run)
        clean_shares_relative(con, args.dry_run)
        clean_fundamentals_relative(con, args.dry_run)
        if not args.skip_price:
            clean_price(con, args.dry_run, args.smoke_test)
            clean_ohlc_corrupt(con, args.dry_run)
        if not args.dry_run:
            con.commit()
    finally:
        con.close()
    _log(f"{'='*60}\n  Done ({mode}).\n{'='*60}")


if __name__ == "__main__":
    main()
