"""Build + audit the m01a_tail_v1 label (fixed-horizon tail-magnitude, M1 of the m01a plan).

Writes label_registry/m01a_tail_v1.json, computes the label on the full trend_ok panel,
and runs LeakageGuard.audit_label on a random sample. Read-only DB access; the label is
cheap to recompute (~10s) so it is not materialized anywhere — source_query is canonical.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.label_registry import LabelDefinition
from src.evaluation.leakage_guard import LeakageGuard

DB_PATH = Path("data/market_data.duckdb")
REGISTRY_PATH = Path("label_registry/m01a_tail_v1.json")
HORIZON_BARS = 63
K_PCT = 0.30

SOURCE_QUERY = """
WITH panel AS (
  SELECT ticker, date
  FROM t3_sepa_features
  WHERE trend_ok
    AND RS_Universe_Rank IS NOT NULL
    AND ticker NOT IN ('LIF', 'CUE')
),
px AS (
  SELECT ticker, date, close,
    MAX(GREATEST(high, close)) OVER w AS fh63,
    COUNT(close) OVER w AS c63
  FROM price_data
  WHERE ticker IN (SELECT DISTINCT ticker FROM panel)
  WINDOW w AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 1 FOLLOWING AND 63 FOLLOWING)
)
SELECT p.ticker, p.date, x.close AS entry_close, x.fh63,
       x.fh63 / x.close - 1 AS mfe_63,
       GREATEST(x.fh63 / x.close - 1 - 0.30, 0) AS tail_mag_63,
       CAST(x.fh63 / x.close - 1 > 0.30 AS INT) AS home_run_63
FROM panel p
JOIN px x USING (ticker, date)
WHERE x.c63 = 63 AND x.close > 0
""".strip()


def build_label_definition() -> LabelDefinition:
    git_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip() or "unknown"
    return LabelDefinition(
        label_id="m01a_tail_v1",
        description=(
            "Continuous tail-magnitude label for the m01_tail suite: "
            "max(MFE_63 - 30%, 0), where MFE_63 is the entry-conditioned fixed-horizon "
            "Maximum Favorable Excursion — enter at day-t close, MFE = "
            "MAX(GREATEST(high, close)) over trading bars t+1..t+63 (entry day excluded, "
            "full 63-bar forward window required) divided by entry close, minus 1. "
            "Corrupt isolated highs (EXEL 999.99 sentinel class) are nulled AT SOURCE by "
            "clean_dirty_shares_price.py part G (2026-07-10), so no label-side guard. "
            "Population = full trend_ok panel (Minervini stage-1 watchlist), NOT the "
            "breakout slice — see verdicts/2026-07-09_population_reframe_tail_ranker.md. "
            "Horizon N=63 and label form chosen by the M0 horizon sweep "
            "(verdicts/2026-07-10_m0_horizon_sweep.md): top-end strictly monotone in RS "
            "deciles across all date-thirds, D10/D1 home-run ratio 5.7-6.7x. "
            "Binary diagnostic home_run_63 = 1[MFE_63 > 30%] (bins field). "
            "horizon_days counts TRADING BARS (~91 calendar days). Two-clock split: this "
            "fixed horizon RANKS; the SEPA event-terminated exit HOLDS (backtest policy, "
            "not the label)."
        ),
        target_col="tail_mag_63",
        horizon_days=HORIZON_BARS,
        exit_rule="fixed_horizon",
        source_query=SOURCE_QUERY,
        git_sha=git_sha,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        bins=[30.0],
    )


def _recompute_fh63(window: pd.DataFrame, label_def: LabelDefinition) -> float:
    w = window.iloc[:HORIZON_BARS]
    # row-wise max skips NaN highs (nulled dirt bars) — same as GREATEST semantics
    return round(float(w[["high", "close"]].max(axis=1).max()), 6)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=1500, help="audit sample size")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    label_def = build_label_definition()
    label_def.to_json(REGISTRY_PATH)
    print(f"[M1] wrote {REGISTRY_PATH} fingerprint={label_def.fingerprint()[:12]}", flush=True)

    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    labels = con.execute(SOURCE_QUERY).df()
    con.close()
    pos_rate = float((labels["tail_mag_63"] > 0).mean())
    print(f"[M1] label panel: {len(labels):,} rows, "
          f"{labels['date'].min()} -> {labels['date'].max()}, "
          f"positive rate {pos_rate:.2%}", flush=True)

    # Transform consistency: tail_mag / home_run must be pure functions of (fh63, entry_close).
    mfe = labels["fh63"] / labels["entry_close"] - 1
    assert ((labels["mfe_63"] - mfe).abs() < 1e-9).all()
    assert ((labels["tail_mag_63"] - (mfe - K_PCT).clip(lower=0)).abs() < 1e-9).all()
    assert (labels["home_run_63"] == (mfe > K_PCT).astype(int)).all()
    print("[M1] transform consistency: OK", flush=True)

    sample = labels.sample(n=min(args.sample, len(labels)), random_state=args.seed).copy()
    sample["fh63"] = sample["fh63"].round(6)
    # audit_label's horizon window is CALENDAR days; 63 trading bars span <=~95 calendar
    # days, so 100 guarantees the in-horizon window contains the full 63 bars while the
    # recompute_fn truncates at exactly 63 bars (the real leak boundary).
    result = LeakageGuard.audit_label(
        labels_df=sample,
        price_data_view="price_data",
        label_def=replace(label_def, target_col="fh63"),
        db_path=DB_PATH,
        max_horizon_days=100,
        recompute_fn=_recompute_fh63,
    )
    print(f"[M1] leakage audit: {result['gate']['detail']}", flush=True)
    for v in result["horizon_violations"][:10]:
        print(f"  VIOLATION: {v}", flush=True)
    for m in result["missing_price_rows"][:10]:
        print(f"  MISSING PRICE: {m}", flush=True)
    print(f"[M1] {'PASS' if result['passed'] else 'FAIL'}", flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
