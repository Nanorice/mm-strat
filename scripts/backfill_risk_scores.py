"""
Backfill t2_risk_scores table with 5-factor regime-switching risk scores.

Reads all available history from DuckDB (macro_data + price_data), computes
2555-day z-scores and 1260-day rolling percentile, then writes scored rows to
t2_risk_scores.

Usage:
    python scripts/backfill_risk_scores.py            # backfill (skip existing)
    python scripts/backfill_risk_scores.py --force    # overwrite all rows
    python scripts/backfill_risk_scores.py --latest   # print current score only
"""

import sys
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.pipeline.risk_5_factor import RiskFiveFactorCalculator


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill 5-factor risk scores")
    parser.add_argument("--force", action="store_true", help="Overwrite existing rows")
    parser.add_argument("--latest", action="store_true", help="Print latest score and exit")
    args = parser.parse_args()

    calc = RiskFiveFactorCalculator()

    if args.latest:
        score = calc.get_latest_score()
        if not score:
            print("[WARN] No scored rows found — run backfill first")
            return
        print(f"\n5-Factor Risk Score — {score['date']}")
        print(f"  Target exposure    : {score['target_exposure']:.0%}")
        print(f"  Base exposure      : {score['base_exposure']:.0%}")
        print(f"  Rolling percentile : {score['rolling_percentile']:.3f}")
        print(f"  Weighted Z         : {score['weighted_z']:+.3f}")
        print(f"  Veto flag          : {score['veto_flag']}")
        print(f"  z_vix={score['z_vix']:+.2f}  z_hy={score['z_hy']:+.2f}  "
              f"z_term={score['z_term']:+.2f}  z_trend={score['z_trend']:+.2f}  "
              f"z_slope={score['z_slope']:+.2f}")
        return

    mode = "replace" if args.force else "ignore"
    print(f"Backfilling t2_risk_scores (mode={mode})...")
    df = calc.compute_history()
    rows = calc.write_to_db(df, mode=mode)
    scored = df["target_exposure"].notna().sum()
    print(f"[OK] {rows} new rows written ({scored} total scored rows)")


if __name__ == "__main__":
    main()
