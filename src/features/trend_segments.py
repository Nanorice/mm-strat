"""Phase 1 swing-pivot / segmentation primitives for the Minervini stage classifier.

Pure pandas over a per-ticker daily price path (use price_data, the continuous panel —
never t3, which has active/inactive holes). Outputs the primitives Phase 2 composes into
market_stage:

    pivot_high, pivot_low, slope_63d, slope_r2_63d, prior_slope_sign

The pivot pass is a ZigZag: sequential by construction (each pivot depends on the running
extreme since the last confirmed pivot), so it cannot be a SQL window function — same reason
compute_ema_features lives in pandas. Slopes/R2 are vectorized.

# ponytail: log-price path uses close, not adj_close (adj_close is 100% NULL in this DB).
# Splits therefore aren't back-adjusted; acceptable for a 63d slope SIGN + R2, not for P&L.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SLOPE_WINDOW = 63    # ~1 quarter of trading days (recent trend)
PRIOR_WINDOW = 252   # ~1 year — position vs the prior leg, for Stage 1 vs 3


def _zigzag_pivots(log_price: np.ndarray, threshold: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mark swing pivots on a log-price series with a per-bar reversal threshold.

    A new pivot is confirmed when price reverses from the running extreme by >= threshold
    (in log units). threshold is per-bar so it can track ATR/vol regime. Returns two bool
    arrays (pivot_high, pivot_low) aligned to log_price.

    Pivots are marked at the bar of the extreme, confirmed only after the reversal — so the
    boolean at bar t uses only info up to the confirming bar (>= t). No look-ahead into the
    future beyond the confirmation lag, which is the honest cost of pivot detection.
    """
    n = len(log_price)
    pivot_high = np.zeros(n, dtype=bool)
    pivot_low = np.zeros(n, dtype=bool)
    if n == 0:
        return pivot_high, pivot_low

    direction = 0            # 0 unknown, +1 seeking high, -1 seeking low
    ext_idx = 0              # index of current running extreme
    ext_val = log_price[0]

    for i in range(1, n):
        p = log_price[i]
        thr = threshold[i]
        if direction >= 0 and p > ext_val:
            ext_val, ext_idx = p, i          # extend the high
        elif direction <= 0 and p < ext_val:
            ext_val, ext_idx = p, i          # extend the low
        elif direction >= 0 and p <= ext_val - thr:
            pivot_high[ext_idx] = True       # reversal down confirms a high
            direction, ext_val, ext_idx = -1, p, i
        elif direction <= 0 and p >= ext_val + thr:
            pivot_low[ext_idx] = True        # reversal up confirms a low
            direction, ext_val, ext_idx = 1, p, i
        if direction == 0:
            direction = 1 if p >= log_price[0] else -1

    return pivot_high, pivot_low


def _rolling_slope_r2(log_price: pd.Series, window: int) -> tuple[pd.Series, pd.Series]:
    """OLS slope of log-price vs a 0..window-1 time index, plus R2, over a rolling window.

    Vectorized via rolling covariance/variance. slope is per-bar log-return trend; R2 is
    trend cleanliness (low R2 = choppy / distribution — the Stage-3 tell).
    """
    t = pd.Series(np.arange(len(log_price), dtype=float), index=log_price.index)
    # rolling means
    ybar = log_price.rolling(window).mean()
    tbar = t.rolling(window).mean()
    cov = (log_price * t).rolling(window).mean() - ybar * tbar
    var_t = (t * t).rolling(window).mean() - tbar * tbar
    var_y = (log_price * log_price).rolling(window).mean() - ybar * ybar
    slope = cov / var_t.replace(0, np.nan)
    r2 = (cov * cov) / (var_t * var_y).replace(0, np.nan)
    return slope, r2.clip(0, 1)


def compute_trend_segments(
    df: pd.DataFrame,
    threshold_col: str = "atr_14",
    slope_window: int = SLOPE_WINDOW,
    prior_window: int = PRIOR_WINDOW,
) -> pd.DataFrame:
    """Compute the five Phase-1 primitives per ticker.

    df must have columns: ticker, date, close, and `threshold_col` (per-bar reversal size in
    price units, e.g. atr_14). Rows must be sorted or sortable by (ticker, date). Returns df
    with pivot_high, pivot_low, slope_63d, slope_r2_63d, prior_slope_sign added.

    prior_slope_sign = sign of the log-price change over PRIOR_WINDOW (~1yr) — the
    path-dependent term separating Stage 1 (flat after down) from Stage 3 (flat after up).
    A flat base after a decline still sits below its year-ago level (negative); a top after
    an advance sits near/above it (positive). Always defined once ~1yr of history exists,
    and independent of base length — no pivots needed for this term (pivots stay for Phase 4).
    """
    required = {"ticker", "date", "close", threshold_col}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"compute_trend_segments missing columns: {sorted(missing)}")

    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    out = []
    for _, g in df.groupby("ticker", sort=False):
        g = g.copy()
        log_p = np.log(g["close"].to_numpy())
        # threshold in log units: atr/close is a fractional move ~= log return
        thr = (g[threshold_col].to_numpy() / g["close"].to_numpy())
        thr = np.nan_to_num(thr, nan=0.02)  # fallback 2% during warmup
        ph, pl = _zigzag_pivots(log_p, thr)
        g["pivot_high"] = ph
        g["pivot_low"] = pl

        log_series = pd.Series(log_p, index=g.index)
        slope, r2 = _rolling_slope_r2(log_series, slope_window)
        g["slope_63d"] = slope.to_numpy()
        g["slope_r2_63d"] = r2.to_numpy()

        # prior_slope_sign: sign of the ~1yr log-price change (where are we vs the prior leg)
        prior_change = log_series - log_series.shift(prior_window)
        g["prior_slope_sign"] = np.sign(prior_change).to_numpy()
        out.append(g)

    return pd.concat(out, ignore_index=True)


def compute_market_stage(df: pd.DataFrame) -> pd.Series:
    """Phase 2: compose market_stage in {1,2,3,4} from trend_ok + Phase-1 primitives.

    df must have trend_ok, slope_63d, prior_slope_sign (run compute_trend_segments first,
    join trend_ok from the feature table). Returns a nullable Int series aligned to df.index;
    NULL where prior_slope_sign is undefined (first ~1yr warmup) — we don't guess a stage.

    The stage cycle is directional (1->2->3->4->1): you cannot go advance->base without
    first topping and declining. So a non-trend_ok row that CAME FROM AN ADVANCE is a top,
    period — never relabelled as base. Stage 1 is reachable only from a prior decline. That
    asymmetry (not a symmetric 2x2) is deliberate: mislabelling a flat top as a base is the
    costly error for an entry gate, so prior-up never routes to Stage 1.

        prior up               -> 3  (top: came from an advance, template now lost)
        prior down + slope down -> 4  (declining)
        prior down + slope >= 0 -> 1  (base: decline flattening / turning up)
    NULL where prior_slope_sign is undefined (first ~1yr warmup) — we don't guess.
    """
    prior = df["prior_slope_sign"]
    slope_down = df["slope_63d"] < 0

    stage = pd.Series(pd.NA, index=df.index, dtype="Int8")
    stage[df["trend_ok"] == True] = 2  # noqa: E712 — nullable bool, `is True` won't vectorize
    non2 = (df["trend_ok"] != True) & prior.notna()
    stage[non2 & (prior > 0)] = 3
    stage[non2 & (prior < 0) & slope_down] = 4
    stage[non2 & (prior < 0) & ~slope_down] = 1
    return stage


def _demo() -> None:
    """Self-check: a synthetic down->flat (base) and up->flat (top) must get opposite prior signs."""
    dates = pd.date_range("2020-01-01", periods=500, freq="B")

    def _path(seg_slopes, n_each):
        p, series = 100.0, []
        for s in seg_slopes:
            for _ in range(n_each):
                p *= (1 + s)
                series.append(p)
        return series

    # each segment >= 2*slope_window so the flat tail has a fully-lagged prior slope
    base_px = _path([-0.01, 0.0], 150)          # decline then flat -> Stage 1
    top_px = _path([0.01, 0.0], 150)             # advance then flat -> Stage 3
    n = len(base_px)
    df = pd.DataFrame({
        "ticker": ["BASE"] * n + ["TOP"] * n,
        "date": list(dates[:n]) + list(dates[:n]),
        "close": base_px + top_px,
    })
    df["atr_14"] = df["close"] * 0.02

    res = compute_trend_segments(df)
    tail = res.groupby("ticker").tail(1).set_index("ticker")
    base_sign = tail.loc["BASE", "prior_slope_sign"]
    top_sign = tail.loc["TOP", "prior_slope_sign"]
    print(f"BASE prior_slope_sign={base_sign}  TOP prior_slope_sign={top_sign}")
    assert base_sign < 0, f"base should follow a decline, got {base_sign}"
    assert top_sign > 0, f"top should follow an advance, got {top_sign}"

    # pivot layer: a zig-zag path must yield both a confirmed high and low
    zz = _path([0.01, -0.01, 0.01], 40)
    zdf = pd.DataFrame({"ticker": ["ZZ"] * len(zz), "date": list(dates[:len(zz)]), "close": zz})
    zdf["atr_14"] = zdf["close"] * 0.02
    zres = compute_trend_segments(zdf)
    assert zres["pivot_high"].any(), "no pivot_high on zig-zag path"
    assert zres["pivot_low"].any(), "no pivot_low on zig-zag path"
    print(f"[OK] pivots on zig-zag: highs={zres['pivot_high'].sum()} lows={zres['pivot_low'].sum()}")

    # classifier: flat tail after advance -> Stage 3; after decline -> Stage 1
    res["trend_ok"] = False  # synthetic flats never meet the full template
    res["market_stage"] = compute_market_stage(res)
    stage_tail = res.groupby("ticker").tail(1).set_index("ticker")["market_stage"]
    print(f"BASE stage={stage_tail['BASE']}  TOP stage={stage_tail['TOP']}")
    assert stage_tail["TOP"] == 3, f"advance->flat should be Stage 3, got {stage_tail['TOP']}"
    assert stage_tail["BASE"] == 1, f"decline->flat should be Stage 1, got {stage_tail['BASE']}"
    print("[OK] trend_segments self-check passed")


if __name__ == "__main__":
    _demo()
