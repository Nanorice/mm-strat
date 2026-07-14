"""Regime-indicator manual — candidate feature builder (§0.6 rules, uniform).

Builds ONE daily parquet of every ladder candidate signal on a LIVE-SAFE basis:
  §6.8  SPY 200d slope + distance-from-MA         (highest prior, strict refinement)
  §4    market breadth (% liquid names > own SMA200) + A/D slope
  §6.2  ADX(14) on SPY (trend strength)
  §6.3  Donchian channel %-position (20/55/252)
  §6.5  SuperTrend(10, 3) on SPY (binary regime)
  §5-batch  RV_22d, BBW(20,2), QQQ/SPY RS slope(63d), Aroon osc(25)

RAW price/OHLC for SPY & QQQ come from price_data (1993+/1999+). Breadth is a
DuckDB window over the whole liquid universe (dollar-vol > $1M/day, own SMA200).

LIVE-SAFETY (Appendix / §0.6):
  - every rolling stat is trailing / expanding, `.shift(1)` applied to the FEATURE.
  - expanding-z normalization (no full-sample z, no all-time percentile).
  - as-of-date identity self-check: recompute ending at date D == full-history value.

  python .../regime_candidate_features.py --smoke   # 3y, print, self-check, no write
  python .../regime_candidate_features.py           # full -> candidate_features_daily.parquet
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


def _root() -> Path:
    p = Path(__file__).resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("repo root not found")


ROOT = _root()
DB = ROOT / "data" / "market_data.duckdb"
OUT = ROOT / "data" / "model_output_eda" / "regime_gauge"
LIQ_FLOOR = 1e6  # $1M/day 63d-avg dollar volume — breadth from micro-caps is noise (§4)


# ------------------------------------------------------------------ raw pulls
def _spy_qqq() -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute("""
        SELECT ticker, date, open, high, low, close
        FROM price_data WHERE ticker IN ('SPY','QQQ') ORDER BY ticker, date
    """).df()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


def _breadth() -> pd.DataFrame:
    """Per-day % of liquid names above their own SMA200 + advance/decline counts.
    Window sees FULL history (n200>=200 guards the warm-up), date filter is post-window."""
    con = duckdb.connect(str(DB), read_only=True)
    con.execute("PRAGMA threads=4")
    df = con.execute("""
        WITH base AS (
          SELECT ticker, date, close,
                 close - LAG(close) OVER (PARTITION BY ticker ORDER BY date) AS chg,
                 AVG(close) OVER w AS sma200,
                 COUNT(*) OVER w AS n200,
                 AVG(CAST(volume AS BIGINT)*close) OVER w63 AS advol63
          FROM price_data
          WINDOW w AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW),
                 w63 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 62 PRECEDING AND CURRENT ROW)
        )
        SELECT date,
               COUNT(*) FILTER (WHERE liq) AS n_liquid,
               AVG(CASE WHEN close>sma200 THEN 1.0 ELSE 0.0 END) FILTER (WHERE liq) AS breadth_200d,
               (COUNT(*) FILTER (WHERE liq AND chg>0) - COUNT(*) FILTER (WHERE liq AND chg<0)) AS ad_net
        FROM (SELECT *, (n200>=200 AND advol63>%f) AS liq FROM base)
        GROUP BY date ORDER BY date
    """ % LIQ_FLOOR).df()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    # A/D line slope: 20d change in the cumulative A/D line.
    df["ad_line"] = df["ad_net"].cumsum()
    df["ad_slope_20d"] = df["ad_line"] - df["ad_line"].shift(20)
    return df[["date", "n_liquid", "breadth_200d", "ad_slope_20d"]]


# --------------------------------------------------------------- indicators
def _wma(s: pd.Series, n: int) -> pd.Series:
    w = np.arange(1, n + 1)
    return s.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def _adx(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    """Wilder ADX(n). Trend strength irrespective of direction, range 0-100."""
    up, dn = h.diff(), -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=h.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=h.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def _supertrend_up(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 10, mult: float = 3.0) -> pd.Series:
    """SuperTrend regime: True = uptrend. ATR-scaled trailing band with flip logic."""
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    mid = (h + l) / 2
    upper, lower = mid + mult * atr, mid - mult * atr
    fu = upper.copy(); fl = lower.copy()
    up_trend = pd.Series(True, index=c.index)
    for i in range(1, len(c)):
        fu.iat[i] = min(upper.iat[i], fu.iat[i - 1]) if c.iat[i - 1] <= fu.iat[i - 1] else upper.iat[i]
        fl.iat[i] = max(lower.iat[i], fl.iat[i - 1]) if c.iat[i - 1] >= fl.iat[i - 1] else lower.iat[i]
        if c.iat[i] > fu.iat[i - 1]:
            up_trend.iat[i] = True
        elif c.iat[i] < fl.iat[i - 1]:
            up_trend.iat[i] = False
        else:
            up_trend.iat[i] = up_trend.iat[i - 1]
    return up_trend.astype(float)


def _aroon_osc(h: pd.Series, l: pd.Series, n: int = 25) -> pd.Series:
    up = h.rolling(n + 1).apply(lambda x: (n - x.argmax()) / n * 100, raw=True)
    dn = l.rolling(n + 1).apply(lambda x: (n - x.argmin()) / n * 100, raw=True)
    return up - dn


def _index_features(g: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """All price-only technicals for one index (SPY or QQQ). g sorted by date."""
    c, h, l = g["close"], g["high"], g["low"]
    sma200 = c.rolling(200).mean()
    out = pd.DataFrame({"date": g["date"].values})
    # §6.8 slope + distance
    out[f"{prefix}_sma200_slope"] = ((sma200 - sma200.shift(20)) / sma200.shift(20)).values
    out[f"{prefix}_dist200"] = (c / sma200 - 1).values
    out[f"{prefix}_above200"] = (c > sma200).astype(float).values
    # §6.2 ADX
    out[f"{prefix}_adx14"] = _adx(h, l, c, 14).values
    # §6.3 Donchian %-position
    for w in (20, 55, 252):
        hi, lo = h.rolling(w).max(), l.rolling(w).min()
        out[f"{prefix}_dc_pct{w}"] = ((c - lo) / (hi - lo)).values
    # §6.5 SuperTrend
    out[f"{prefix}_supertrend_up"] = _supertrend_up(h, l, c, 10, 3.0).values
    # §6.4 Aroon
    out[f"{prefix}_aroon_osc"] = _aroon_osc(h, l, 25).values
    # §2/§6.7 vol-state: realized vol + Bollinger bandwidth
    ret = c.pct_change()
    out[f"{prefix}_rv22"] = (ret.rolling(22).std() * np.sqrt(252)).values
    m20, s20 = c.rolling(20).mean(), c.rolling(20).std()
    out[f"{prefix}_bbw"] = ((m20 + 2 * s20 - (m20 - 2 * s20)) / m20).values
    return out


def build(smoke: bool = False) -> pd.DataFrame:
    px = _spy_qqq()
    spy = px[px["ticker"] == "SPY"].sort_values("date").reset_index(drop=True)
    qqq = px[px["ticker"] == "QQQ"].sort_values("date").reset_index(drop=True)
    feats = _index_features(spy, "spy").merge(_index_features(qqq, "qqq"), on="date", how="left")

    # §6.9 QQQ/SPY relative-strength slope (63d)
    m = spy[["date", "close"]].rename(columns={"close": "spy_c"}).merge(
        qqq[["date", "close"]].rename(columns={"close": "qqq_c"}), on="date", how="inner")
    m["rs"] = m["qqq_c"] / m["spy_c"]
    m["qqq_spy_rs_slope"] = (m["rs"] - m["rs"].shift(63)) / m["rs"].shift(63)
    feats = feats.merge(m[["date", "qqq_spy_rs_slope"]], on="date", how="left")

    # §4 breadth (whole-universe window)
    feats = feats.merge(_breadth(), on="date", how="left")

    feats = feats.sort_values("date").reset_index(drop=True)
    if smoke:
        feats = feats[feats["date"] >= feats["date"].max() - pd.Timedelta(days=365 * 3)].reset_index(drop=True)
    return feats


# ---------------------------------------------------------- live-safety z + lag
# raw feature columns (pre-z). booleans/oscillators already bounded — z anyway for uniformity.
FEATURE_COLS = [
    "spy_sma200_slope", "spy_dist200", "spy_above200", "spy_adx14",
    "spy_dc_pct20", "spy_dc_pct55", "spy_dc_pct252", "spy_supertrend_up",
    "spy_aroon_osc", "spy_rv22", "spy_bbw",
    "qqq_sma200_slope", "qqq_dist200", "qqq_above200", "qqq_adx14",
    "qqq_dc_pct252", "qqq_supertrend_up", "qqq_rv22",
    "qqq_spy_rs_slope", "breadth_200d", "ad_slope_20d",
]


def expanding_z(s: pd.Series, min_periods: int = 252) -> pd.Series:
    """Expanding-z, then shift(1) — the FEATURE at time t uses only info <= t-1."""
    mu = s.expanding(min_periods).mean()
    sd = s.expanding(min_periods).std()
    z = (s - mu) / sd
    return z.shift(1)


def add_live_safe(feats: pd.DataFrame) -> pd.DataFrame:
    for col in FEATURE_COLS:
        if col in feats.columns:
            feats[f"{col}_z"] = expanding_z(feats[col])
    return feats


def _asof_identity_check(feats: pd.DataFrame) -> None:
    """§0.7-2: recompute a signal ending at date D; must equal full-history value at D.
    Tests the expanding-z path for a few probe columns at 3 cut points."""
    probes = ["spy_dist200", "breadth_200d", "spy_adx14"]
    cuts = [int(len(feats) * f) for f in (0.4, 0.7, 0.95)]
    bad = 0
    for col in probes:
        if col not in feats:
            continue
        full = expanding_z(feats[col])
        for cut in cuts:
            partial = expanding_z(feats[col].iloc[: cut + 1])
            a, b = partial.iloc[cut], full.iloc[cut]
            if not (pd.isna(a) and pd.isna(b)) and abs((a or 0) - (b or 0)) > 1e-9:
                bad += 1
    assert bad == 0, f"as-of identity FAILED: {bad} mismatches (look-ahead in z-norm)"
    print(f"[self-check] as-of identity OK across {len(probes)} probes x 3 cuts")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    feats = build(smoke=args.smoke)
    feats = add_live_safe(feats)
    print(f"built {len(feats)} days ({feats['date'].min().date()}->{feats['date'].max().date()}), "
          f"{len(FEATURE_COLS)} raw features  [{time.time()-t0:.1f}s]")
    _asof_identity_check(feats)
    print("\nfeature head (raw + a few z):")
    show = ["date", "spy_dist200", "spy_dist200_z", "breadth_200d", "breadth_200d_z", "spy_adx14"]
    print(feats[show].dropna().head().to_string(index=False))
    print("\nbreadth coverage:", feats["breadth_200d"].notna().sum(), "days; "
          f"n_liquid median={feats['n_liquid'].median():.0f}")

    if not args.smoke:
        OUT.mkdir(parents=True, exist_ok=True)
        f = OUT / "candidate_features_daily.parquet"
        feats.to_parquet(f, index=False)
        print(f"\nwrote {f.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
