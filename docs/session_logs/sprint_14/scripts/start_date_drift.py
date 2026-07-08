"""Two EDA charts for the point-8 cells (user, 2026-07-08):

  Q1  Top-1/5/10 daily-basket fwd return over representative periods — does the
      cumulative curve DRIFT up (a real edge) or wander (start-date lottery)?
      = the rough performance of deploying the strategy from different days.

  Q2  How the 6 macro pillars move WITH the return curve — plotted as expanding-window
      percentiles (live-safe), stacked, against the full-span top-5 curve.

Pure re-analysis of the multi-year raw-score parquets (top-15/day pre-reduced) +
the entry-timing pillar panel. Score = RAW prob_elite. No backtest.
"""
import numpy as np, pandas as pd
from pathlib import Path


def _root() -> Path:
    p = Path(__file__).resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("root not found")


ROOT = _root()
OUT = ROOT / "data/model_output_eda/regime_weight"

# representative periods spanning regimes (start, end, label)
PERIODS = [
    ("2003-07-01", "2007-06-30", "2003-07 bull"),
    ("2007-07-01", "2009-06-30", "2007-09 GFC"),
    ("2013-01-01", "2015-12-31", "2013-15 calm bull"),
    ("2020-01-01", "2020-12-31", "2020 COVID"),
    ("2022-01-01", "2022-12-31", "2022 bear"),
    ("2023-01-01", "2025-12-31", "2023-25 recent"),
]


def daily_topn(topn: pd.DataFrame, n: int, h: str) -> pd.Series:
    """Mean fwd return of the top-n scored names each day -> date-indexed series."""
    g = topn.sort_values("prob_elite", ascending=False).groupby("date").head(n)
    return g.groupby("date")[h].mean()


def main() -> None:
    topn = pd.read_parquet(OUT / "_topN_scratch.parquet")

    # ---- Q1: per-period top-1/5/10 cumulative curves ----
    # "return curve from starting on different days" = cumulative SUM of the daily
    # top-N mean fwd return; upward slope => deploying on successive days compounds an edge,
    # flat/noisy => start-date lottery. Use fwd20 (comparable across periods, dense).
    q1 = {}
    for start, end, label in PERIODS:
        sub = topn[(topn.date >= start) & (topn.date <= end)]
        curves = {}
        for n in (1, 5, 10):
            s = daily_topn(sub, n, "fwd20").sort_index()
            curves[n] = s.cumsum()
        q1[label] = curves

    # ---- Q2: 6-pillar expanding percentile vs the full-span top-5 curve ----
    et = pd.read_parquet(ROOT / "data/model_output_eda/entry_timing/entry_timing_daily.parquet")
    pil = ["pil_vix", "pil_credit", "pil_term", "pil_rates", "pil_liq", "pil_cape"]
    p = et[["date"] + pil].sort_values("date").reset_index(drop=True)
    # expanding percentile: rank of today within all history through today (live-safe)
    for c in pil:
        p[c + "_pct"] = p[c].expanding().apply(lambda x: (x.iloc[-1] >= x).mean(), raw=False)
    curve5 = daily_topn(topn[topn.date >= p.date.min()], 5, "fwd20").sort_index().cumsum()

    q1_summary = pd.DataFrame({
        lab: {f"top{n}_slope_per100d": c[n].diff().mean() * 100 for n in (1, 5, 10)}
        for lab, c in q1.items()
    }).T
    print("=== Q1: cumulative top-N fwd20 slope (mean daily incr x100 = ~%/100 deploy-days) ===")
    pd.set_option("display.float_format", lambda x: f"{x:+.2f}")
    print(q1_summary.to_string())
    print("\nREAD: positive & similar across N => real drift; near-zero/negative => start-date lottery.")

    q1_summary.to_csv(OUT / "start_date_drift_summary.csv")
    print("\ncharts: run start_date_drift_chart.py (recomputes from the same parquets)")


if __name__ == "__main__":
    main()
