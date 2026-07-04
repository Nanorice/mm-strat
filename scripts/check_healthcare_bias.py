"""Goal A artifact check — is Healthcare over-represented in top-score tickers
beyond its base rate in the *scored* cross-section, controlling for era?

Falsifiable framing:
  H0: Healthcare's share of top-score ticker-days == its share of the scored
      cross-section (per-day, so a Healthcare-heavy market week can't skew it).
  Reject H0 (score has a sector artifact) if the top-set share is materially and
  consistently above the daily base rate.

Score = m01_prototype prob_class_3 (top "home run" MFE class). Top-set = ticker-days
above a score threshold. Base rate = the sector mix of what was actually scored that
day (NOT the static universe — a ticker only competes on days it's scored).

Usage:
    .venv/Scripts/python.exe scripts/check_healthcare_bias.py
    .venv/Scripts/python.exe scripts/check_healthcare_bias.py --threshold 0.15 --cohort pre_breakout
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import duckdb
import numpy as np
import pandas as pd

DB_PATH = REPO_ROOT / "data" / "market_data.duckdb"
MODEL = "m01_prototype_2003_2026_20260514_233125"


def load_scored(cohort: str | None) -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        cohort_clause = "AND cohort = ?" if cohort else ""
        params = [MODEL] + ([cohort] if cohort else [])
        df = con.execute(
            f"""
            SELECT p.prediction_date AS date, p.ticker,
                   p.prob_class_3 AS score,
                   COALESCE(cp.sector, '(unknown)') AS sector
            FROM daily_predictions p
            LEFT JOIN company_profiles cp USING (ticker)
            WHERE p.model_version_id = ?
              AND p.prob_class_3 IS NOT NULL
              {cohort_clause}
            """,
            params,
        ).df()
    finally:
        con.close()
    return df


def per_day_shares(df: pd.DataFrame, threshold: float, sector: str) -> pd.DataFrame:
    """For each day: share of `sector` in the full scored set (base rate) vs in the
    top-set (score > threshold). Excess = top_share - base_share, era-controlled."""
    rows = []
    for date, g in df.groupby("date"):
        top = g[g["score"] > threshold]
        if top.empty:
            continue
        base_share = (g["sector"] == sector).mean()
        top_share = (top["sector"] == sector).mean()
        rows.append(
            dict(date=date, n_scored=len(g), n_top=len(top),
                 base_share=base_share, top_share=top_share,
                 excess=top_share - base_share)
        )
    return pd.DataFrame(rows)


def sector_lift_table(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Pooled top-set share vs pooled scored share, per sector. Lift = top/base."""
    scored = df["sector"].value_counts(normalize=True).rename("base_share")
    top = df[df["score"] > threshold]["sector"].value_counts(normalize=True).rename("top_share")
    out = pd.concat([scored, top], axis=1).fillna(0.0)
    out["lift"] = out["top_share"] / out["base_share"].replace(0, np.nan)
    return out.sort_values("top_share", ascending=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--threshold", type=float, default=0.15,
                    help="Score (prob_class_3) cutoff defining the top-set")
    ap.add_argument("--sector", default="Healthcare")
    ap.add_argument("--cohort", default=None,
                    help="Restrict to one cohort (pre_breakout/active/breakout/removed); default = all")
    args = ap.parse_args()

    df = load_scored(args.cohort)
    print(f"Scored rows: {len(df):,} | tickers: {df['ticker'].nunique():,} | "
          f"days: {df['date'].nunique()} | cohort: {args.cohort or 'ALL'}")
    top_frac = (df["score"] > args.threshold).mean()
    print(f"Top-set fraction at threshold {args.threshold}: {top_frac:.1%} "
          f"({(df['score'] > args.threshold).sum():,} ticker-days)\n")

    # --- Pooled sector lift (all sectors, so Healthcare is in context) ---
    lift = sector_lift_table(df, args.threshold)
    print("=== Pooled sector share: scored base rate vs top-set (lift = top/base) ===")
    disp = lift.head(12).copy()
    disp["base_share"] = (disp["base_share"] * 100).round(1).astype(str) + "%"
    disp["top_share"] = (disp["top_share"] * 100).round(1).astype(str) + "%"
    disp["lift"] = disp["lift"].round(2)
    print(disp.to_string())

    # --- Per-day era-controlled excess for the target sector ---
    daily = per_day_shares(df, args.threshold, args.sector)
    if daily.empty:
        print(f"\nNo days with a non-empty top-set at threshold {args.threshold}.")
        return
    ex = daily["excess"]
    # One-sample sign test analog: is per-day excess consistently > 0?
    frac_pos = (ex > 0).mean()
    mean_ex = ex.mean()
    # simple t-stat on daily excess (H0: mean excess = 0)
    t = mean_ex / (ex.std(ddof=1) / np.sqrt(len(ex))) if ex.std(ddof=1) > 0 else float("nan")

    print(f"\n=== {args.sector}: era-controlled (per-day) over-representation ===")
    print(f"days evaluated:            {len(daily)}")
    print(f"mean daily base share:     {daily['base_share'].mean():.1%}")
    print(f"mean daily top share:      {daily['top_share'].mean():.1%}")
    print(f"mean daily EXCESS:         {mean_ex:+.1%}  (top - base, per day)")
    print(f"days with excess > 0:      {frac_pos:.0%}")
    print(f"t-stat (H0: excess=0):     {t:+.1f}")

    verdict = (
        "ARTIFACT: consistent positive tilt" if (frac_pos >= 0.6 and mean_ex > 0.02 and t > 2)
        else "NO consistent tilt beyond base rate"
    )
    print(f"\nVERDICT: {verdict}")

    # sanity check: excess is bounded and daily shares are valid probabilities
    assert daily["base_share"].between(0, 1).all() and daily["top_share"].between(0, 1).all()
    assert np.isclose(lift["base_share"].sum(), 1.0, atol=1e-6)


if __name__ == "__main__":
    main()
