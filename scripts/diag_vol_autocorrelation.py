"""Diagnostic: is the m02 MFE/MAE Rank IC real skill or volatility autocorrelation?

Hypothesis: the model's high IC on fwd_mfe_pct / fwd_mae_pct (+0.39 / +0.41) is mostly
because excursion MAGNITUDE tracks a stock's volatility, which is already a feature.

Test (NO model): compute the cross-sectional Rank IC of a single raw volatility feature
(natr) against each forward target, averaged over test dates. If raw natr alone gets an
IC near the model's, the model added little signal beyond "rank by volatility" — the
MFE/MAE IC is largely tautological.

For fwd_mae_pct (negative = drawdown), a more-volatile name has a MORE-NEGATIVE MAE, so
expect a strong NEGATIVE raw IC there; magnitude is what matters for the comparison.

Fast: pure correlation over t3_training_cache JOIN m02_prototype_targets, no training.
--smoke limits to a few tickers to validate the path first (per smoke-test protocol).
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DUCKDB_PATH

VOL_FEATURE = "natr"
TARGETS = ["fwd_mae_pct", "fwd_ret_pct", "fwd_mfe_pct"]
SMOKE_TICKERS = ("AAPL", "NVDA", "MSFT", "TSLA", "AMD")


def _per_date_ic(df: pd.DataFrame, pred_col: str, target_col: str) -> tuple[float, float]:
    ics = []
    for _, g in df.groupby("date"):
        if len(g) < 3:
            continue
        a, b = g[pred_col].rank(), g[target_col].rank()
        if a.std(ddof=0) == 0 or b.std(ddof=0) == 0:
            continue
        ics.append(float(a.corr(b)))
    if not ics:
        return float("nan"), float("nan")
    return float(np.mean(ics)), float(np.std(ics, ddof=0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DUCKDB_PATH))
    ap.add_argument("--test-start", default="2019-01-02")
    ap.add_argument("--smoke", action="store_true", help="limit to a few tickers")
    args = ap.parse_args()

    where_smoke = ""
    if args.smoke:
        tk = ",".join(f"'{t}'" for t in SMOKE_TICKERS)
        where_smoke = f"AND f.ticker IN ({tk})"

    con = duckdb.connect(args.db, read_only=True)
    df = con.execute(f"""
        SELECT f.ticker, f.date, f.{VOL_FEATURE} AS vol,
               t.fwd_mae_pct, t.fwd_ret_pct, t.fwd_mfe_pct
        FROM t3_training_cache f
        JOIN m02_prototype_targets t ON f.ticker = t.ticker AND f.date = t.date
        WHERE t.has_full_window AND f.date >= ? {where_smoke}
    """, [args.test_start]).df()
    con.close()

    print(f"rows: {len(df):,}  (smoke={args.smoke})", flush=True)
    print(f"\nRaw '{VOL_FEATURE}' cross-sectional Rank IC vs forward targets:")
    print("(compare magnitude to model IC: P10/MAE +0.41, P90/MFE +0.39, P50/ret +0.04)\n", flush=True)
    for tgt in TARGETS:
        sub = df[["date", "vol", tgt]].dropna()
        ic, std = _per_date_ic(sub, "vol", tgt)
        print(f"  {VOL_FEATURE} vs {tgt:14s}  IC={ic:+.4f}  (std {std:.3f})", flush=True)


if __name__ == "__main__":
    main()
