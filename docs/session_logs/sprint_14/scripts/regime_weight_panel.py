"""Point-8 experiment: regime-weight the per-day top-5 fwd-return panel (NOT a backtest).

Does an ENTRY-DATE regime weight lower the AVERAGE and WORST-DECILE loss of the
existing entry-timing panel? Two weights, both already on the panel:
  (a) crude SPY-200MA 2-state  (bull = full, bear = down-weight/zero)
  (b) continuous stress_ew_vix, SPY>200d-gated  (the 6-pillar tilt in native form)

Judge on fwd100 (biggest gap). Weight on the entry-date regime only (no look-ahead).
This is an EDA reweight of a table already built — directional, no exits/sizing.
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
HORIZ = "fwd100"


def load() -> pd.DataFrame:
    et = pd.read_parquet(ROOT / "data/model_output_eda/entry_timing/entry_timing_daily.parquet")
    dd = pd.read_parquet(ROOT / "data/model_output_eda/regime_state/regime_state_daily_dd.parquet")
    df = et.merge(dd[["date", "state"]], on="date", how="left")
    return df


def wmean(f: np.ndarray, w: np.ndarray) -> float:
    """Capital-weighted mean fwd return: what you'd realize deploying w_t capital per date."""
    return float(np.sum(w * f) / np.sum(w))


def w_worst_decile(f: np.ndarray, w: np.ndarray) -> float:
    """Mean of the worst 10% of deployed capital, weight-aware.

    Order dates by return; walk from the bottom accumulating capital mass until 10%
    of total weight is reached; return the capital-weighted mean of that tail.
    Flat weights -> the ordinary bottom-decile mean.
    """
    o = np.argsort(f)                       # ascending: worst first
    fo, wo = f[o], w[o]
    cutoff = 0.10 * wo.sum()
    cum = np.cumsum(wo)
    k = np.searchsorted(cum, cutoff) + 1    # include the date that crosses 10%
    return wmean(fo[:k], wo[:k])


def weights(df: pd.DataFrame, kind: str, bear_w: float = 0.0) -> np.ndarray:
    bull = (df["state"] != "bear").values.astype(float)     # SPY>200d
    if kind == "flat":
        return np.ones(len(df))
    if kind == "spx200":                                    # (a) 2-state
        return np.where(bull > 0, 1.0, bear_w)
    if kind == "stress_gated":                              # (b) 6-pillar tilt, bull-gated
        s = df["stress_ew_vix"].values
        # min-max the live composite to [0,1] as the extra tilt on top of the bull gate;
        # bear -> 0 (never deploy into a downtrend, per the falling-knife finding)
        z = (s - np.nanmin(s)) / (np.nanmax(s) - np.nanmin(s))
        z = np.nan_to_num(z, nan=0.5)                       # warmup dates: neutral tilt
        return bull * z
    raise ValueError(kind)


def main() -> None:
    df = load().dropna(subset=[HORIZ]).reset_index(drop=True)
    f = df[HORIZ].values

    rows = []
    for kind, label in [("flat", "FLAT (no governor)"),
                        ("spx200", "(a) SPY-200MA, bear=0"),
                        ("stress_gated", "(b) stress_ew_vix, bull-gated")]:
        w = weights(df, kind)
        deployed = w.sum() / len(w)          # fraction of full-capital days actually funded
        rows.append(dict(rule=label, mean=wmean(f, w), worst_decile=w_worst_decile(f, w),
                         deployed_frac=deployed))
    # (a') a softer variant: bear=0.25 rather than 0, to show it's not just "sit out"
    w = weights(df, "spx200", bear_w=0.25)
    rows.append(dict(rule="(a') SPY-200MA, bear=0.25", mean=wmean(f, w),
                     worst_decile=w_worst_decile(f, w), deployed_frac=w.sum() / len(w)))

    res = pd.DataFrame(rows)
    base = res.iloc[0]
    res["d_mean"] = res["mean"] - base["mean"]
    res["d_worst"] = res["worst_decile"] - base["worst_decile"]

    pd.set_option("display.float_format", lambda x: f"{x:+.4f}")
    print(f"=== regime-weighted top-5 {HORIZ} panel  (n={len(df)} days, {df.date.min():%Y-%m}..{df.date.max():%Y-%m}) ===\n")
    print(res.to_string(index=False))
    print("\nREAD: a governor helps iff it lifts mean (d_mean>0) AND raises worst_decile (d_worst>0, less negative).")

    out = ROOT / "data/model_output_eda/regime_weight"
    out.mkdir(exist_ok=True)
    res.to_csv(out / f"regime_weight_{HORIZ}.csv", index=False)

    # multi-horizon summary (mean + worst decile), same three rules
    hz_rows = []
    for h in ("fwd20", "fwd50", "fwd100"):
        d = load().dropna(subset=[h]).reset_index(drop=True)
        fh = d[h].values
        for kind, label in [("flat", "flat"), ("spx200", "spx200_bear0"),
                            ("stress_gated", "stress_gated")]:
            w = weights(d, kind)
            hz_rows.append(dict(horizon=h, rule=label, mean=wmean(fh, w),
                                worst_decile=w_worst_decile(fh, w)))
    hz = pd.DataFrame(hz_rows)
    hz.to_csv(out / "regime_weight_horizon_sweep.csv", index=False)
    print(f"\n=== horizon sweep (mean | worst-decile) ===")
    piv = hz.pivot(index="rule", columns="horizon", values="mean")
    pivw = hz.pivot(index="rule", columns="horizon", values="worst_decile")
    print("mean:\n", piv.to_string())
    print("worst-decile:\n", pivw.to_string())


if __name__ == "__main__":
    main()
