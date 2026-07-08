"""Enrich the 25y full-universe scored cache with fwd50 + fwd100 (currently fwd20 only).

Thread F showed SEPA signals live LONG (weak@20d heals by 100d), so fwd20 under-states the
regime story. This adds fwd50/fwd100 to raw_full_*_fwd.parquet, matching the EXACT fwd20
convention (score_universe_multiyear.attach_fwd): H trading-days ahead, close-to-close,
close[t+H]/close[t]-1, from price_data.close (adj_close is 100% NULL).

Correctness verified (2026-07-08): a vectorized per-ticker groupby.shift(-H) reproduces the
cached fwd20 EXACTLY (max abs diff 0.0 on 596k 2025 rows; every scored date is a trading day,
so no '>= date' fallback is needed). So shift(-H) is the fast, faithful vectorization of the
row-by-row .apply the original used.

Writes IN PLACE (adds columns), keeping fwd20 untouched. Idempotent: re-running recomputes.

  python docs/session_logs/sprint_14/scripts/enrich_fwd_horizons.py --smoke   # one year (2022)
  python docs/session_logs/sprint_14/scripts/enrich_fwd_horizons.py           # all 25y
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


def _root() -> Path:
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("root not found")


ROOT = _root()
CACHE = ROOT / "data" / "model_output_eda" / "multiyear"
DB = ROOT / "data" / "market_data.duckdb"
HORIZONS = [50, 100]                       # fwd20 already cached; add these
MAXH = max(HORIZONS)


def _log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def enrich_year(fp: Path) -> tuple[int, int]:
    df = pd.read_parquet(fp)
    df["date"] = pd.to_datetime(df["date"])
    tk = tuple(sorted(df["ticker"].unique()))
    lo = (df["date"].min() - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    # need MAXH trading days beyond the last scored date -> pad generously (calendar > trading days)
    hi = (df["date"].max() + pd.Timedelta(days=MAXH * 3 + 40)).strftime("%Y-%m-%d")
    con = duckdb.connect(str(DB), read_only=True)
    try:
        px = con.execute(
            "SELECT ticker, date, close FROM price_data WHERE ticker IN "
            f"{tk} AND date BETWEEN ? AND ? ORDER BY ticker, date", [lo, hi]).df()
    finally:
        con.close()
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values(["ticker", "date"])
    # vectorized per-ticker H-ahead close-to-close return (== the cached fwd20 recipe)
    for h in HORIZONS:
        px[f"fwd{h}"] = px.groupby("ticker", sort=False)["close"].transform(
            lambda s: s.shift(-h) / s - 1)
    keep = ["ticker", "date"] + [f"fwd{h}" for h in HORIZONS]
    df = df.drop(columns=[c for c in df.columns if c in {f"fwd{h}" for h in HORIZONS}], errors="ignore")
    out = df.merge(px[keep], on=["ticker", "date"], how="left")
    out.to_parquet(fp, index=False)
    n_ok = out[f"fwd{HORIZONS[0]}"].notna().sum()
    return len(out), int(n_ok)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="one year (2022) only")
    args = ap.parse_args()
    files = sorted(CACHE.glob("raw_full_*_fwd.parquet"))
    if args.smoke:
        files = [f for f in files if f.stem.split("_")[2] == "2022"]

    for fp in files:
        yr = fp.stem.split("_")[2]
        n, ok = enrich_year(fp)
        _log(f"{yr}: {n} rows, fwd{HORIZONS[0]} non-null {ok} ({ok/n:.1%})")

    # self-check on the last file written: fwd20 (untouched) still present, new cols added,
    # fwd100 non-null < fwd50 non-null (longer horizon runs off the end of recent data)
    chk = pd.read_parquet(files[-1])
    assert "fwd20" in chk.columns, "fwd20 must be preserved"
    for h in HORIZONS:
        assert f"fwd{h}" in chk.columns, f"fwd{h} missing"
    assert chk["fwd100"].notna().sum() <= chk["fwd50"].notna().sum(), "fwd100 should have >= as many NaN"
    _log(f"OK — {len(files)} file(s) enriched with fwd{HORIZONS}")


if __name__ == "__main__":
    main()
