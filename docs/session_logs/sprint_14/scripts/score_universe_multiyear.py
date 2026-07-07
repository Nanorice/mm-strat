"""M1 multi-year toolkit: score the FULL active universe per year via score_from_t3 (RAW p_pos,
calibrator bypassed), attach 20d fwd return from price_data.close, cache one parquet per year.

Reusable + resumable (long-run rule): re-running skips years whose cache exists. Smoke mode does
one year only. The 2025 baseline already exists as raw_full_2025_fwd.parquet and is symlinked/copied
into the cache dir on first run.

Usage (from repo root, project venv):
  python docs/session_logs/sprint_14/scripts/score_universe_multiyear.py --smoke        # one year (2020)
  python docs/session_logs/sprint_14/scripts/score_universe_multiyear.py                # full 2001-2025
  python docs/session_logs/sprint_14/scripts/score_universe_multiyear.py --years 2008 2022
"""
import sys, argparse, time
from pathlib import Path
import numpy as np, pandas as pd, duckdb

def _root() -> Path:
    p = Path(__file__).resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("repo root not found")

ROOT = _root(); sys.path.insert(0, str(ROOT))
from src.backtest.universe_scorer import UniverseScorer

DB = ROOT / "data" / "market_data.duckdb"
MODEL = ROOT / "models" / "m01_binary" / "v1" / "model.json"
CACHE = ROOT / "data" / "model_output_eda" / "multiyear"
CACHE.mkdir(parents=True, exist_ok=True)
H = 20                       # forward horizon (trading days)
FULL_YEARS = list(range(2001, 2026))   # t3 spans 2001-2026


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def attach_fwd(scored: pd.DataFrame) -> pd.DataFrame:
    """Attach H-day fwd close-to-close return (adj_close is 100% NULL -> use close)."""
    scored = scored.copy()
    scored["date"] = pd.to_datetime(scored["date"])
    tk = tuple(sorted(scored["ticker"].unique()))
    lo = (scored["date"].min() - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    hi = (scored["date"].max() + pd.Timedelta(days=H * 3 + 15)).strftime("%Y-%m-%d")
    con = duckdb.connect(str(DB), read_only=True)
    try:
        px = con.execute(
            "SELECT ticker,date,close FROM price_data WHERE ticker IN "
            f"{tk} AND date BETWEEN ? AND ? ORDER BY ticker,date", [lo, hi]).df()
    finally:
        con.close()
    px["date"] = pd.to_datetime(px["date"])
    pxg = {t: g.set_index("date")["close"] for t, g in px.groupby("ticker")}

    def fwd(r):
        s = pxg.get(r["ticker"])
        if s is None:
            return np.nan
        s = s[s.index >= r["date"]]
        if len(s) <= H or s.iloc[0] == 0:
            return np.nan
        return s.iloc[H] / s.iloc[0] - 1

    scored["fwd20"] = scored.apply(fwd, axis=1)
    return scored


def score_year(year: int, scorer: UniverseScorer) -> pd.DataFrame:
    out = CACHE / f"raw_full_{year}_fwd.parquet"
    if out.exists():
        _log(f"{year}: cache hit -> {out.name} (skip)")
        return pd.read_parquet(out)
    t0 = time.time()
    _log(f"{year}: scoring full universe via score_from_t3 (raw)...")
    scored = scorer.score_from_t3(f"{year}-01-01", f"{year}-12-31", db_path=DB)
    keep = ["date", "ticker", "prob_elite", "calibrated_score"]
    keep += [c for c in ("sector", "industry") if c in scored.columns]
    scored = scored[keep]
    _log(f"{year}: scored {len(scored)} rows, {scored['date'].nunique()} days — attaching fwd{H}...")
    scored = attach_fwd(scored)
    scored.to_parquet(out, index=False)
    _log(f"{year}: cached {out.name}  ({len(scored)} rows, {time.time()-t0:.0f}s)")
    return scored


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="one year only (2020)")
    ap.add_argument("--years", type=int, nargs="+", help="explicit year list")
    args = ap.parse_args()

    years = [2020] if args.smoke else (args.years or FULL_YEARS)

    # seed 2025 from the existing baseline parquet so we don't re-score it
    base_2025 = ROOT / "data" / "model_output_eda" / "raw_full_2025_fwd.parquet"
    tgt_2025 = CACHE / "raw_full_2025_fwd.parquet"
    if 2025 in years and base_2025.exists() and not tgt_2025.exists():
        pd.read_parquet(base_2025).to_parquet(tgt_2025, index=False)
        _log(f"2025: seeded cache from baseline {base_2025.name}")

    _log(f"model={MODEL.relative_to(ROOT)}  years={years}  cache={CACHE.relative_to(ROOT)}")
    scorer = UniverseScorer(m01_path=str(MODEL))
    scorer.load_model()
    scorer._iso_calibrator = None      # RAW p_pos in prob_elite (bypass calibrator, matches 2025 baseline)
    _log("calibrator bypassed -> prob_elite is RAW p_pos")

    done = 0
    for y in years:
        try:
            score_year(y, scorer)
            done += 1
        except Exception as e:
            _log(f"{y}: FAILED — {type(e).__name__}: {e}  (continuing)")
    _log(f"done: {done}/{len(years)} years cached in {CACHE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
