"""Extend horizons to 150d/200d and build the top-5 basket panel at all horizons.

1. Enrich the multiyear parquets with fwd150/fwd200 (same recipe as enrich_fwd_horizons.py:
   per-ticker close-to-close shift(-H), idempotent, in place).
2. Build a date -> top-5-mean fwd{20,50,100,150,200} panel and merge the macro signals from
   entry_timing_daily.parquet -> data/model_output_eda/regime_weight/top5_horizons.parquet.
"""
import time
from pathlib import Path
import duckdb
import pandas as pd


def _root() -> Path:
    p = Path(__file__).resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("root not found")


ROOT = _root()
CACHE = ROOT / "data/model_output_eda/multiyear"
DB = ROOT / "data/market_data.duckdb"
OUT = ROOT / "data/model_output_eda/regime_weight"
NEW_H = [150, 200]
ALL_H = [20, 50, 100, 150, 200]


def _log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def enrich_year(fp: Path) -> None:
    df = pd.read_parquet(fp)
    df["date"] = pd.to_datetime(df["date"])
    if all(f"fwd{h}" in df.columns and df[f"fwd{h}"].notna().any() for h in NEW_H):
        return  # already done
    tk = tuple(sorted(df["ticker"].unique()))
    lo = (df["date"].min() - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    hi = (df["date"].max() + pd.Timedelta(days=max(NEW_H) * 3 + 40)).strftime("%Y-%m-%d")
    con = duckdb.connect(str(DB), read_only=True)
    try:
        px = con.execute(
            "SELECT ticker, date, close FROM price_data WHERE ticker IN "
            f"{tk} AND date BETWEEN ? AND ? ORDER BY ticker, date", [lo, hi]).df()
    finally:
        con.close()
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values(["ticker", "date"])
    for h in NEW_H:
        px[f"fwd{h}"] = px.groupby("ticker", sort=False)["close"].transform(lambda s: s.shift(-h) / s - 1)
    df = df.drop(columns=[c for c in df.columns if c in {f"fwd{h}" for h in NEW_H}], errors="ignore")
    df.merge(px[["ticker", "date"] + [f"fwd{h}" for h in NEW_H]], on=["ticker", "date"], how="left") \
        .to_parquet(fp, index=False)


def main() -> None:
    files = sorted(CACHE.glob("raw_full_*_fwd.parquet"))
    for fp in files:
        enrich_year(fp)
        _log(f"enriched {fp.stem.split('_')[2]}")

    # top-5 basket per day across all years
    frames = []
    for fp in files:
        d = pd.read_parquet(fp, columns=["date", "prob_elite"] + [f"fwd{h}" for h in ALL_H])
        d = d.sort_values("prob_elite", ascending=False).groupby("date").head(5)
        frames.append(d)
    top5 = pd.concat(frames, ignore_index=True)
    top5["date"] = pd.to_datetime(top5["date"])
    panel = top5.groupby("date")[[f"fwd{h}" for h in ALL_H]].mean().reset_index()

    # attach macro signals (rolling 2yr pct pillars + stress + vix + spy) from the entry-timing panel
    et = pd.read_parquet(ROOT / "data/model_output_eda/entry_timing/entry_timing_daily.parquet")
    PIL = ["pil_vix", "pil_credit", "pil_term", "pil_rates", "pil_liq", "pil_cape"]
    et = et.sort_values("date").reset_index(drop=True)
    for c in PIL:
        et[c + "_rp"] = et[c].rolling(504, min_periods=126).apply(lambda x: (x.iloc[-1] >= x).mean(), raw=False)
    macro = et[["date", "stress_ew_vix", "vix_close", "spy_above200", "spy_ret60"] + [c + "_rp" for c in PIL]]
    out = panel.merge(macro, on="date", how="inner")   # inner: macro starts 2003-07
    out.to_parquet(OUT / "top5_horizons.parquet", index=False)

    cov = {f"fwd{h}": f"{out[f'fwd{h}'].notna().mean():.1%}" for h in ALL_H}
    _log(f"panel {len(out)} days {out.date.min():%Y-%m}..{out.date.max():%Y-%m} | coverage {cov}")


if __name__ == "__main__":
    main()
