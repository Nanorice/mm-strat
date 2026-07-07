# M1 re-cut: replace binary home-run count (>30%) with TAIL-MAGNITUDE.
# Pure re-analysis of the existing raw_full_2025_fwd.parquet (no scoring, no DB).
# Q7 asked "how many home-runs do we miss?" (binary >30% count). That treats +35% == +400%.
# The strategy's alpha IS the tail => measure captured/missed MAGNITUDE, and whether the
# score RANKS the tail (rank-of-top-1%), not the hit-count.
import numpy as np, pandas as pd
from pathlib import Path
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[4]  # sprint_14/scripts/ -> repo root
df = pd.read_parquet(ROOT / "data/model_output_eda/raw_full_2025_fwd.parquet").dropna(subset=["fwd20"])
s = df["prob_elite"].values          # raw p_pos (verdict naming trap: "prob_elite" col == raw here)
f = df["fwd20"].values
N = len(df)
GATE = 0.48                          # = calibrated 0.15
HR = 0.30                            # home-run threshold

def excess(x):                       # tail magnitude above 30%
    return np.maximum(x - HR, 0.0)

# self-check: excess is 0 below the line, (x-HR) above, never negative
assert excess(np.array([0.0, 0.30, 0.35, 0.30001]))[1] == 0.0
assert abs(excess(np.array([0.35]))[0] - 0.05) < 1e-9
assert (excess(f) >= 0).all()

# ---- 1. binary vs magnitude view of the SAME gate --------------------------------
tail = excess(f)
tot_tail = tail.sum()
tot_hr_count = (f > HR).sum()
above = s >= GATE
print(f"rows={N}  home-run events (>30%)={tot_hr_count} ({tot_hr_count/N:.2%})  total tail sum-max(fwd-30%,0)={tot_tail:.1f}")
print(f"\n=== Q7 RE-CUT: what does the {GATE:.2f} gate capture/miss? ===")
print(f"{'metric':<34}{'captured':>10}{'missed':>10}{'miss %':>9}")
cap_c, miss_c = tot_hr_count - (f[~above] > HR).sum(), (f[~above] > HR).sum()
cap_t, miss_t = tail[above].sum(), tail[~above].sum()
print(f"{'home-run COUNT (old binary)':<34}{cap_c:>10.0f}{miss_c:>10.0f}{miss_c/tot_hr_count:>8.1%}")
print(f"{'tail MAGNITUDE sum-max(fwd-30%,0)':<34}{cap_t:>10.1f}{miss_t:>10.1f}{miss_t/tot_tail:>8.1%}")

# the gap between the two miss-rates is the whole point: are the missed home-runs small ones?
print(f"\nmedian magnitude of a captured home-run : {np.median(f[above & (f>HR)]):.3f}")
print(f"median magnitude of a MISSED home-run   : {np.median(f[~above & (f>HR)]):.3f}")
print(f"mean excess of captured HR : {excess(f[above & (f>HR)]).mean():.3f}   "
      f"missed HR : {excess(f[~above & (f>HR)]).mean():.3f}")

# ---- 2. does the score RANK the tail? (the real M1 question) -----------------------
# rank-of-top-1%: of the biggest 1% of forward returns, where do they sit in the score dist?
print(f"\n=== does the raw score RANK the fat tail? ===")
top1_cut = np.quantile(f, 0.99)
is_top1 = f >= top1_cut
score_pctile = pd.Series(s).rank(pct=True).values
print(f"top-1% fwd cutoff = {top1_cut:.3f} ({is_top1.sum()} events)")
print(f"  their MEDIAN score-percentile : {np.median(score_pctile[is_top1]):.3f}  (0.5=no signal, 1.0=all at top)")
print(f"  their MEAN   score-percentile : {np.mean(score_pctile[is_top1]):.3f}")
print(f"  frac of top-1% fwd that clear the {GATE} gate : {above[is_top1].mean():.2%}  (vs {above.mean():.2%} base)")

# concentration curve: cumulative share of TOTAL TAIL captured as you walk the score from top down
order = np.argsort(-s)               # highest score first
cum_tail = np.cumsum(tail[order]) / tot_tail
cum_n = np.arange(1, N + 1) / N
print(f"\n  tail-capture concentration (walk score top-down):")
for frac in (0.01, 0.05, 0.10, 0.25, 0.50):
    idx = int(frac * N) - 1
    lift = cum_tail[idx] / frac       # >1 = tail over-concentrated in high scores
    print(f"    top {frac:>4.0%} of scores  ->  {cum_tail[idx]:>5.1%} of total tail   (lift {lift:.2f}x)")

# ---- 3. tail magnitude by score ventile (vs the old home-run-RATE table) -----------
print(f"\n=== tail magnitude by raw-score ventile (cf verdict's home-run-RATE table) ===")
df2 = df.assign(tail=tail, ventile=pd.qcut(df["prob_elite"], 20, labels=False, duplicates="drop"))
g = df2.groupby("ventile").agg(mean_fwd=("fwd20", "mean"), hr_rate=("fwd20", lambda x: (x > HR).mean()),
                               mean_tail=("tail", "mean"), sum_tail=("tail", "sum"))
g["tail_share"] = g["sum_tail"] / tot_tail
print(f"{'ventile':>7}{'mean_fwd':>10}{'HR_rate':>9}{'mean_tail':>11}{'tail_share':>12}")
for v in (0, 9, 14, 17, 18, 19):
    if v in g.index:
        r = g.loc[v]
        print(f"{v:>7}{r.mean_fwd:>9.1%}{r.hr_rate:>9.1%}{r.mean_tail:>11.4f}{r.tail_share:>11.1%}")

# spearman of ventile vs mean_tail (does magnitude grade monotonically like the rate did?)
rho_rate = spearmanr(g.index, g.hr_rate).correlation
rho_tail = spearmanr(g.index, g.mean_tail).correlation
print(f"\nmonotonic rho  HR-rate vs ventile : {rho_rate:+.2f}   mean-tail vs ventile : {rho_tail:+.2f}")

# ---- 4. verdict number ------------------------------------------------------------
print(f"\n=== HEADLINE (replaces Q7's '23.4% missed') ===")
print(f"  binary count:  {miss_c/tot_hr_count:.1%} of home-run EVENTS missed by the {GATE} gate")
print(f"  magnitude:     {miss_t/tot_tail:.1%} of home-run MAGNITUDE missed by the {GATE} gate")
