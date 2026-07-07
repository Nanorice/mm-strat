"""Thread E (Q13-15): basket width + ex-ante deploy gate, on the 25-year cache. No re-scoring.
Reproduces the verdict tables. Reusable — reads whatever years are cached.

  python docs/session_logs/sprint_14/scripts/capital_deployment.py
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd, duckdb

ROOT = Path(__file__).resolve().parents[4]
CACHE = ROOT / "data" / "model_output_eda" / "multiyear"
DB = ROOT / "data" / "market_data.duckdb"
HR, GATE = 0.30, 0.48


def load_all() -> pd.DataFrame:
    frames = []
    for fp in sorted(CACHE.glob("raw_full_*_fwd.parquet")):
        frames.append(pd.read_parquet(fp).dropna(subset=["fwd20"]))
    df = pd.concat(frames)
    df["date"] = pd.to_datetime(df["date"])
    return df


def q14_basket_width(df: pd.DataFrame) -> None:
    def perday(g):
        g = g.sort_values("prob_elite", ascending=False)
        t5, t10 = g.head(5)["fwd20"], g.head(10)["fwd20"]
        return pd.Series({"top5_fwd": t5.mean(), "top10_fwd": t10.mean(),
                          "top5_hr": (t5 > HR).mean(), "top10_hr": (t10 > HR).mean(),
                          "npass": (g["prob_elite"] >= GATE).sum()})
    d = df.groupby("date", group_keys=False)[["prob_elite", "fwd20"]].apply(perday)
    print("=== Q14: top-5 vs top-10 (pooled) ===")
    print(f"  top-5  mean fwd {d.top5_fwd.mean():+.2%}  HR-rate {d.top5_hr.mean():.2%}")
    print(f"  top-10 mean fwd {d.top10_fwd.mean():+.2%}  HR-rate {d.top10_hr.mean():.2%}")
    print(f"  names 6-10 implied fwd {(d.top10_fwd*10 - d.top5_fwd*5).mean()/5:+.2%}")
    print(f"  median gated-pass/day {d.npass.median():.0f}")


def q15_ex_ante_gate(df: pd.DataFrame) -> None:
    def perday(g):
        return pd.Series({"top5_fwd": g.sort_values("prob_elite", ascending=False).head(5)["fwd20"].mean()})
    day = df.groupby("date", group_keys=False)[["prob_elite", "fwd20"]].apply(perday).reset_index()

    con = duckdb.connect(str(DB), read_only=True)
    m = con.execute("SELECT date,spy_close,vix_close FROM t1_macro ORDER BY date").df()
    con.close()
    m["date"] = pd.to_datetime(m["date"])
    m["spy_above_200"] = (m.spy_close > m.spy_close.rolling(200).mean()).astype(int)
    day = day.merge(m[["date", "vix_close", "spy_above_200"]], on="date", how="left")

    print("\n=== Q15: ex-ante deploy gate (outcome = top-5 fwd20) ===")
    for feat, bins, labels in [("vix_close", [0, 15, 20, 30, 999], ["<15", "15-20", "20-30", ">30"]),
                               ("spy_above_200", [-1, 0, 1], ["below 200d", "above 200d"])]:
        day["b"] = pd.cut(day[feat], bins=bins, labels=labels)
        g = day.groupby("b", observed=True).agg(top5_fwd=("top5_fwd", "mean"),
                                                 neg_day=("top5_fwd", lambda x: (x < 0).mean()),
                                                 n=("top5_fwd", "size"))
        print(f"\n[{feat}]\n{g.to_string()}")
    print(f"\n  corr(VIX, top5)={day.vix_close.corr(day.top5_fwd):+.2f}  "
          f"corr(SPY>200d, top5)={day.spy_above_200.corr(day.top5_fwd):+.2f}")
    print(f"  baseline: {(day.top5_fwd<0).mean():.1%} neg days, mean {day.top5_fwd.mean():+.2%}")


if __name__ == "__main__":
    df = load_all()
    print(f"loaded {len(df)} rows, {df['date'].dt.year.nunique()} years\n")
    q14_basket_width(df)
    q15_ex_ante_gate(df)
