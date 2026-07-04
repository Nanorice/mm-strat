"""Validate the Phase 2 market_stage classifier on real data.

No external ground-truth label for Minervini stages exists, so this reports (a) internal
consistency cross-checks against independent signals already in the DB, and (b) an optional
predicted-vs-expected table if you supply hand-labelled examples (from a study or the book).

Usage:
    python -m scripts.validate_market_stage                      # default sample universe
    python -m scripts.validate_market_stage --tickers AAPL NVDA GME
    python -m scripts.validate_market_stage --labels my_labels.csv
        # labels CSV columns: ticker,date,expected_stage   (date = YYYY-MM-DD)
"""

from __future__ import annotations

import argparse

import pandas as pd

from src import db
from src.features.trend_segments import compute_trend_segments, compute_market_stage

DEFAULT_TICKERS = ["AAPL", "NVDA", "GME", "TSLA", "META", "INTC", "PLTR", "F"]
DB_PATH = "data/market_data.duckdb"


def load_panel(tickers: list[str], start: str) -> pd.DataFrame:
    """Price path from price_data (continuous); atr_14/trend_ok/cross-checks from t3."""
    con = db.connect(DB_PATH, read_only=True)
    try:
        placeholders = ",".join(f"'{t}'" for t in tickers)
        return con.execute(f"""
            SELECT p.ticker, p.date, p.close,
                   f.atr_14, f.trend_ok, f.breakout, f.m03_pillar_trend
            FROM price_data p
            LEFT JOIN t3_sepa_features f ON p.ticker = f.ticker AND p.date = f.date
            WHERE p.ticker IN ({placeholders}) AND p.date >= '{start}'
            ORDER BY p.ticker, p.date
        """).df()
    finally:
        con.close()


def internal_checks(res: pd.DataFrame) -> None:
    r = res.dropna(subset=["market_stage"])
    print("\n=== stage distribution ===")
    print(r["market_stage"].value_counts(normalize=True).sort_index().round(3).to_string())

    print("\n=== Tier 1: trend_ok by stage (Stage 2 must be 1.0, all others 0.0) ===")
    print(r.groupby("market_stage")["trend_ok"].mean().round(3).to_string())
    contradiction = r.loc[(r["market_stage"] != 2) & (r["trend_ok"] == True)]  # noqa: E712
    print(f"contradictions (non-2 rows with trend_ok=True): {len(contradiction)}  <- must be 0")

    print("\n=== breakout rate by stage (should peak in Stage 2) ===")
    print(r.groupby("market_stage")["breakout"].mean().round(4).to_string())

    print("\n=== m03_pillar_trend mean by stage (independent signal; expect 4 < 3 <= 1 < 2) ===")
    print(r.groupby("market_stage")["m03_pillar_trend"].mean().round(2).to_string())


def label_check(res: pd.DataFrame, labels_path: str) -> None:
    labels = pd.read_csv(labels_path)
    labels["date"] = pd.to_datetime(labels["date"])
    res = res.copy()
    res["date"] = pd.to_datetime(res["date"])
    merged = labels.merge(
        res[["ticker", "date", "market_stage"]], on=["ticker", "date"], how="left"
    )
    print("\n=== predicted vs expected ===")
    print(merged.to_string(index=False))
    matched = merged.dropna(subset=["market_stage"])
    if matched.empty:
        print("no label dates matched a panel row (check dates are trading days).")
        return
    hit = (matched["market_stage"] == matched["expected_stage"]).mean()
    print(f"\nagreement: {hit:.1%} on {len(matched)} matched labels "
          f"({len(merged) - len(matched)} unmatched)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--labels", help="CSV of ticker,date,expected_stage to score against")
    args = ap.parse_args()

    df = load_panel(args.tickers, args.start)
    if df.empty:
        print("no data loaded — check ticker symbols.")
        return
    res = compute_trend_segments(df)
    res["market_stage"] = compute_market_stage(res)

    internal_checks(res)
    if args.labels:
        label_check(res, args.labels)


if __name__ == "__main__":
    main()
