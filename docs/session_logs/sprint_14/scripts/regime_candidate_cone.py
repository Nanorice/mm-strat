"""Regime-indicator manual — Block C (cone / P&L promotion bar) for the two
highest-prior candidates: S6.8 (SPY 200d slope+dist) and S4 (breadth).

The champion cone (`champion_trail_spygate`, 90-cell rolling) already exists as the
BASELINE arm. This runner adds, per candidate, the same 90-cell rolling cone but with
the SPY-200d `spy_deploy_gate` REPLACED by a candidate-derived {date->bool} gate:

  candidate-only : deploy iff candidate rule true.
  composed (OR)  : deploy iff (SPY>200d) OR candidate rule   -> union risk-off is stricter
                   deploy; here we use OR so EITHER says-go => go (captures both regimes).

  ⚠ semantics: gate dict True = "deploy allowed". composed OR-on-DEPLOY = spy_ok OR cand_ok.

Gate rules (from the manual):
  S6.8 slope : deploy iff SPY>200d AND sma200_slope>0   (strong-bull only; gate off weak/bear)
  S4 breadth : deploy iff breadth_200d > 0.5

Reuses run_starttime_sweep cells/jobs/metrics. Resume-safe (equity.parquet skip).

  python .../regime_candidate_cone.py --smoke                 # 2 cells/arm
  python .../regime_candidate_cone.py --candidate slope       # full slope cone
  python .../regime_candidate_cone.py --candidate breadth --compose
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from functools import partial
from pathlib import Path

REPO_ROOT = Path(__file__).resolve()
for _d in (REPO_ROOT, *REPO_ROOT.parents):
    if (_d / "config.py").exists() and (_d / "src").is_dir():
        REPO_ROOT = _d
        break
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from src.backtest import strategy_registry as reg
from src.backtest.macro_sizer import spy_above_200d
from src.backtest.population_runner import Job
from scripts.run_strategy_confirm import _load_scores, DB_PATH, MODEL
from scripts.run_starttime_sweep import build_cells, _run_cell, _cone_stats, CACHE_START, CACHE_END

FEATS = REPO_ROOT / "data" / "model_output_eda" / "regime_gauge" / "candidate_features_daily.parquet"
OUT_ROOT = REPO_ROOT / "data" / "selection_sweep" / "starttime"


# ---------------------------------------------------------------- gate builders
def _cand_flags() -> dict[str, dict]:
    """{candidate -> {date(py) -> deploy_bool}} using LIVE-SAFE raw features.
    Uses the raw (pre-z) columns for a live-safe THRESHOLD gate — expanding-z is for
    the classifier; a gate is a fixed economic rule (breadth>0.5, slope>0), already
    computed from trailing windows on price. shift(1) applied so the flag at date t
    uses data through t-1 (no lookahead at the open we'd act on)."""
    f = pd.read_parquet(FEATS)
    f["date"] = pd.to_datetime(f["date"])
    f = f.sort_values("date").reset_index(drop=True)
    # shift raw signals by 1 business day (live-safe: act at next open)
    slope = f["spy_sma200_slope"].shift(1)
    above = f["spy_above200"].shift(1)
    breadth = f["breadth_200d"].shift(1)
    d = f["date"].dt.date
    return {
        "slope": {dt: bool(a > 0.5 and s > 0) for dt, a, s in zip(d, above.fillna(0), slope.fillna(-1))},
        "breadth": {dt: bool(b > 0.5) for dt, b in zip(d, breadth.fillna(0))},
    }


def _compose_or(cand: dict, spy: dict) -> dict:
    """deploy iff spy_ok OR cand_ok (union of go-signals)."""
    keys = set(cand) | set(spy)
    return {k: bool(cand.get(k, False) or spy.get(k, True)) for k in keys}


def _spy_gate_full() -> dict:
    """Canonical SPY-200d gate over ALL history, loaded ONCE (not per cell) so we
    open the DB a single time — the per-cell open collided with a foreign RW lock
    on market_data.duckdb (an open kernel). Retries the transient IO lock a few times."""
    import time as _t
    for attempt in range(6):
        try:
            return spy_above_200d("1993-01-01", "2026-12-31", str(DB_PATH))
        except Exception as e:  # duckdb IO lock — back off and retry
            if attempt == 5:
                raise
            print(f"  [spy-gate] DB locked (attempt {attempt+1}/6), retrying in 20s: {e}", flush=True)
            _t.sleep(20)


def _cell_job(cand_name: str, arm: str, flags: dict, spy_full: dict, cell_id: str,
              start: str, end: str) -> Job:
    """Champion kwargs, but spy_deploy_gate replaced by the candidate/composed gate
    for this window. arm in {candonly, compose}. spy_full = pre-loaded canonical gate."""
    d = reg.get("champion_trail_spygate")
    kwargs = dict(d.strategy_kwargs)
    spy_gate = {k: v for k, v in spy_full.items() if start <= str(k) <= end}
    cand_gate = {k: v for k, v in flags.items() if start <= str(k) <= end}
    kwargs["spy_deploy_gate"] = _compose_or(cand_gate, spy_gate) if arm == "compose" else cand_gate
    return Job(
        id=cell_id, description=f"{cand_name}_{arm} {start}..{end}", signal=d.signal,
        model="/".join(MODEL[d.signal]), strategy_kwargs=kwargs,
        score_loader=partial(_load_scores, d.signal, start, end),
    )


def run_arm_cone(cand: str, arm: str, flags: dict, spy_full: dict, cells, initial_cash: float,
                 out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for cid, s, e in cells:
        job = _cell_job(cand, arm, flags, spy_full, cid, s, e)
        print(f"  -- {cid} {s}..{e}", flush=True)
        rows.append(_run_cell(cid, s, e, job, initial_cash, out_dir))
    rows.sort(key=lambda r: r.get("start", ""))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", choices=["slope", "breadth"], default="slope")
    ap.add_argument("--compose", action="store_true", help="also run the SPY-OR-candidate arm")
    ap.add_argument("--initial-cash", type=float, default=25_000.0)
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    # full-span cache for binary_gated is 2003..2026 (NOT the binary 2021 default)
    cache_start, cache_end = "2003-01-01", "2026-05-22"
    cells = build_cells("rolling", cache_start, cache_end, step_months=3)
    if args.smoke:
        cells = cells[:2]

    flags = _cand_flags()[args.candidate]
    spy_full = _spy_gate_full()  # ONE DB open, windowed per cell in memory
    t0 = time.time()
    print(f"CANDIDATE CONE — {args.candidate}: {len(cells)} cells "
          f"(deploy days: {sum(flags.values())}/{len(flags)})")

    results = {}
    base = OUT_ROOT / "champion_trail_spygate" / "rolling"  # existing baseline
    results["baseline"] = _cone_stats([
        r for r in json.load(open(base / "summary.json"))["cells"]])

    candonly = run_arm_cone(args.candidate, "candonly", flags, spy_full, cells, args.initial_cash,
                            OUT_ROOT / f"cand_{args.candidate}_only" / "rolling")
    results["candidate_only"] = _cone_stats(candonly)

    if args.compose:
        comp = run_arm_cone(args.candidate, "compose", flags, spy_full, cells, args.initial_cash,
                            OUT_ROOT / f"cand_{args.candidate}_compose" / "rolling")
        results["composed_or"] = _cone_stats(comp)

    out = OUT_ROOT / f"cand_{args.candidate}_cone_summary.json"
    out.write_text(json.dumps(results, indent=2, default=float))
    print(f"\n=== {args.candidate} CONE vs champion_trail_spygate baseline ===")
    print(f"{'arm':16}{'n':>4}{'median':>9}{'p25':>8}{'floor':>8}{'pct_neg':>9}")
    for arm, s in results.items():
        if s.get("n"):
            print(f"{arm:16}{s['n']:>4}{s['median']:>9.3f}{s['p25']:>8.3f}"
                  f"{s['min']:>8.3f}{s['pct_neg']:>9.1%}")
    print(f"\nwrote {out.relative_to(REPO_ROOT)}  [{time.time()-t0:.1f}s]")


if __name__ == "__main__":
    main()
