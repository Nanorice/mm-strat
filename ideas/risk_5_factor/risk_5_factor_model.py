"""
5-Factor Regime-Switching Risk Model -- MVP Prototype

All data and output files are scoped to test_field/risk_5_factor/.

SETUP (one-time):
    1. Get a free FRED API key at: https://fred.stlouisfed.org/docs/api/api_key.html
    2. Set it as an env var:  FRED_API_KEY=your_key_here
       OR create test_field/risk_5_factor/config.py with:
           FRED_API_KEY = "your_key_here"

Run:
    python test_field/risk_5_factor/risk_5_factor_model.py
    python test_field/risk_5_factor/risk_5_factor_model.py --refresh   # force re-fetch
"""

import os
import sys
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import date

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
RAW_CACHE = BASE_DIR / "raw_data.parquet"
OUTPUT_CACHE = BASE_DIR / "risk_scores.parquet"

# ── Config ────────────────────────────────────────────────────────────────────
START_DATE = "1990-01-01"
END_DATE = date.today().isoformat()
ROLLING_WINDOW_Z   = 2555   # z-score normalization: 10yr — preserves long-term signal memory
ROLLING_WINDOW_PCT = 1260   # percentile rank: 5yr — unlocks signals from ~2005, covering 2008 GFC

WEIGHTS = {
    "z_vix":   0.25,
    "z_hy":    0.25,
    "z_term":  0.15,
    "z_trend": 0.15,
    "z_slope": 0.20,
}

EXPOSURE_BANDS = [
    (0.00, 0.20, 1.00),
    (0.20, 0.40, 0.85),
    (0.40, 0.55, 0.75),
    (0.55, 0.70, 0.50),
    (0.70, 0.85, 0.35),
    (0.85, 1.00, 0.15),
]

VETO_THRESHOLD = 2.0
VETO_EXPOSURE = 0.15


# ── FRED API Key Resolution ───────────────────────────────────────────────────

def _get_fred_api_key() -> str:
    """Resolve FRED API key from env var, project .env, or local config.py."""
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        # Walk up from BASE_DIR looking for .env
        for parent in [BASE_DIR, BASE_DIR.parent, BASE_DIR.parent.parent]:
            dotenv = parent / ".env"
            if dotenv.exists():
                for line in dotenv.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("FRED_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        break
            if key:
                break
    if not key:
        config_path = BASE_DIR / "config.py"
        if config_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("config", config_path)
            cfg = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cfg)
            key = getattr(cfg, "FRED_API_KEY", "")
    if not key:
        print(
            "\n[ERR] FRED API key not found.\n"
            "  1. Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html\n"
            "  2. Set env var:  FRED_API_KEY=your_key\n"
            "     OR add FRED_API_KEY=your_key to the project .env file\n"
        )
        sys.exit(1)
    return key


# ── Step 1: Data Ingestion ────────────────────────────────────────────────────

def _fetch_fred(series_id: str, fred_key: str) -> pd.Series:
    from fredapi import Fred
    fred = Fred(api_key=fred_key)
    s = fred.get_series(series_id, observation_start=START_DATE, observation_end=END_DATE)
    s.index = pd.to_datetime(s.index)
    s.index.name = "date"
    s.name = series_id
    return s


def fetch_raw_data(fred_key: str) -> pd.DataFrame:
    """Fetch VIX, S&P 500, HY OAS, DGS10, DGS2 and align to SPX trading calendar."""
    print("Fetching yfinance data (^VIX, ^GSPC)...")
    yf_raw = yf.download(["^VIX", "^GSPC"], start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
    spx = yf_raw["Close"]["^GSPC"].rename("spx")
    vix = yf_raw["Close"]["^VIX"].rename("vix")

    print("Fetching FRED data (DGS10, DGS2, WBAA)...")
    dgs10 = _fetch_fred("DGS10", fred_key).rename("dgs10")
    dgs2  = _fetch_fred("DGS2",  fred_key).rename("dgs2")
    # BAMLH0A0HYM2 is FRED-restricted to last 3 years (ICE licensing, April 2026).
    # Proxy: Moody's Baa yield minus 10Y Treasury — same widening/tightening signal,
    # available from 1986. WBAA is weekly; ffill it onto a daily index BEFORE
    # subtracting DGS10, otherwise the subtraction produces NaN on non-Friday days
    # that survive the later ffill pass.
    spx_cal = spx.dropna().index
    wbaa = _fetch_fred("WBAA", fred_key).rename("wbaa")
    wbaa_daily = wbaa.reindex(spx_cal).ffill()
    dgs10_daily = dgs10.reindex(spx_cal).ffill()
    hy_oas = (wbaa_daily - dgs10_daily).rename("hy_oas")

    # Align everything to SPX trading calendar
    df = pd.concat([spx, vix, hy_oas, dgs10, dgs2], axis=1)
    df = df.loc[spx_cal]
    df = df.ffill()   # catch any remaining DGS2 gaps (also daily but has some NaN days)
    df = df.dropna(subset=["spx"])

    df.index.name = "date"
    return df


def load_raw(fred_key: str, force_refresh: bool = False) -> pd.DataFrame:
    if not force_refresh and RAW_CACHE.exists():
        print(f"Loading raw data from cache: {RAW_CACHE}")
        return pd.read_parquet(RAW_CACHE)
    df = fetch_raw_data(fred_key)
    df.to_parquet(RAW_CACHE)
    print(f"Raw data cached -> {RAW_CACHE}  ({len(df)} rows)")
    return df


# ── Step 2: Raw Factor Engineering ───────────────────────────────────────────

def compute_raw_factors(df: pd.DataFrame) -> pd.DataFrame:
    """All factors oriented so positive value = higher market risk."""
    out = df.copy()

    # Factor 1: VIX spot (+1 direction, higher VIX = higher risk)
    out["f_vix"] = out["vix"]

    # Factor 2: HY 20d absolute change (+1 direction, widening = higher risk)
    out["f_hy"] = out["hy_oas"] - out["hy_oas"].shift(20)

    # Factor 3: Term spread * -1 (inverted/negative spread = higher risk)
    out["f_term"] = -1 * (out["dgs10"] - out["dgs2"])

    # Factor 4: SPX vs 200d SMA * -1 (below SMA = higher risk)
    sma200 = out["spx"].rolling(200).mean()
    out["f_trend"] = -1 * (out["spx"] / sma200 - 1)

    # Factor 5: 200d SMA 20d slope * -1 (falling slope = higher risk)
    out["f_slope"] = -1 * (sma200 / sma200.shift(20) - 1)

    return out


# ── Step 3: Rolling Z-Scores ──────────────────────────────────────────────────

def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    roll = series.rolling(window, min_periods=window)
    return (series - roll.mean()) / roll.std(ddof=1)


def compute_zscores(df: pd.DataFrame) -> pd.DataFrame:
    factor_map = {
        "f_vix": "z_vix", "f_hy": "z_hy", "f_term": "z_term",
        "f_trend": "z_trend", "f_slope": "z_slope",
    }
    for raw, z in factor_map.items():
        df[z] = rolling_zscore(df[raw], ROLLING_WINDOW_Z)

    z_cols = list(factor_map.values())
    # Veto: True if ANY individual z-score >= threshold (uses per-column non-NaN check)
    df["veto_flag"] = (df[z_cols] >= VETO_THRESHOLD).any(axis=1)

    return df


# ── Step 4: Aggregation & Percentile Rank ────────────────────────────────────

def _rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    """
    Rolling percentile rank of the last element in each window.
    Uses a numpy loop — O(n*window) but avoids pandas apply overhead.
    ~10-20s for 6000 rows at window=2555.
    """
    arr = series.to_numpy(dtype=float)
    n = len(arr)
    result = np.full(n, np.nan)
    for i in range(window - 1, n):
        window_vals = arr[i - window + 1: i + 1]
        if np.isnan(window_vals).any():
            continue
        result[i] = (window_vals < window_vals[-1]).sum() / (window - 1)
    return pd.Series(result, index=series.index)


def compute_aggregation(df: pd.DataFrame) -> pd.DataFrame:
    df["weighted_z"] = sum(df[col] * w for col, w in WEIGHTS.items())

    # Compute percentile only on the contiguous non-NaN slice so the 2555-day
    # window doesn't waste rows counting over the earlier SMA/z-score warmup period.
    print("Computing rolling percentile rank (may take ~20s)...")
    wz = df["weighted_z"].dropna()
    pct = _rolling_percentile(wz, ROLLING_WINDOW_PCT)
    df["rolling_percentile"] = pct.reindex(df.index)

    return df


# ── Step 5: Exposure Mapping & Veto Overlay ───────────────────────────────────

def _map_band(percentile: float) -> float:
    for lo, hi, exposure in EXPOSURE_BANDS:
        if lo <= percentile < hi:
            return exposure
    return EXPOSURE_BANDS[-1][2]   # percentile == 1.0


def compute_exposure(df: pd.DataFrame) -> pd.DataFrame:
    df["base_exposure"] = df["rolling_percentile"].apply(
        lambda p: _map_band(p) if pd.notna(p) else np.nan
    )
    df["target_exposure"] = np.where(
        df["veto_flag"] & df["base_exposure"].notna(),
        VETO_EXPOSURE,
        df["base_exposure"],
    )
    return df


# ── Output Schema ─────────────────────────────────────────────────────────────
#
#  date (index)       : DatetimeIndex — SPX trading days
#  spx                : S&P 500 close
#  vix                : VIX close
#  hy_oas             : HY OAS level (bps)
#  dgs10, dgs2        : 10Y and 2Y Treasury yields
#  f_vix/hy/term/trend/slope  : signed raw factors (+ve = more risk)
#  z_vix/hy/term/trend/slope  : 2555-day rolling z-scores
#  veto_flag          : True if any z >= 2.0
#  weighted_z         : weighted aggregate z-score
#  rolling_percentile : 0-1 rolling percentile of weighted_z
#  base_exposure      : band-mapped equity exposure (pre-veto)
#  target_exposure    : final exposure after veto overlay (NaN in warmup period)


# ── Main ──────────────────────────────────────────────────────────────────────

def run(force_refresh: bool = False) -> pd.DataFrame:
    fred_key = _get_fred_api_key()
    raw = load_raw(fred_key, force_refresh=force_refresh)

    print("Computing raw factors...")
    df = compute_raw_factors(raw)

    print("Computing rolling z-scores...")
    df = compute_zscores(df)

    print("Computing weighted z and rolling percentile...")
    df = compute_aggregation(df)

    print("Mapping exposure bands...")
    df = compute_exposure(df)

    df.to_parquet(OUTPUT_CACHE)
    n_scored = df["target_exposure"].notna().sum()
    print(f"Output cached -> {OUTPUT_CACHE}  ({len(df)} rows, {n_scored} scored)")

    scored = df.dropna(subset=["target_exposure"])
    if not scored.empty:
        print("\n-- Sample output (last 10 rows) --")
        cols = [
            # raw inputs
            "spx", "vix", "hy_oas", "dgs10", "dgs2",
            # raw factors (signed)
            "f_vix", "f_hy", "f_term", "f_trend", "f_slope",
            # z-scores
            "z_vix", "z_hy", "z_term", "z_trend", "z_slope",
            # aggregation & output
            "weighted_z", "rolling_percentile", "veto_flag", "base_exposure", "target_exposure",
        ]
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 200)
        pd.set_option("display.float_format", "{:.4f}".format)
        print(scored[cols].tail(10).to_string())
        print(f"\nExposure distribution:\n{scored['target_exposure'].value_counts().sort_index()}")
    else:
        print("[WARN] No scored rows — check data coverage vs ROLLING_WINDOW.")

    return df


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="5-Factor Risk Model MVP")
    parser.add_argument("--refresh", action="store_true", help="Force re-fetch raw data (ignore cache)")
    args = parser.parse_args()
    run(force_refresh=args.refresh)
