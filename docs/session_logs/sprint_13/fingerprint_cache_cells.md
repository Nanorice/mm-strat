# Fingerprint + Cache Cells — for `s13_rotation_strategy.ipynb`

> Two things:
> 1. **CLEANUP** — one canonical setup cell replacing the three inconsistent ones (duplicate
>    `ROOT`, `DB`/`DB_PATH`, `CASH`/`INITIAL_CASH`, `PROTO_VER`/`PROTO_VERSION`).
> 2. **FINGERPRINT + CACHE** — a strategy = component fingerprint; every backtest's trades are
>    cached to parquet keyed by (fingerprint, signal, window, cash) so re-runs are instant.
>
> Paste Cell A **at the top** (delete the old cells 1, 2, and the second-file setup block
> `deaff2ba`). Then Cell B, C, D after it. Everything downstream uses these names.

---

## Cell A — canonical setup (REPLACES old setup cells)

```python
import sys, hashlib, json
from pathlib import Path

def _repo_root() -> Path:
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError(f"repo root not found above {p}")

ROOT = _repo_root()
sys.path.insert(0, str(ROOT))

import numpy as np, pandas as pd, matplotlib.pyplot as plt
from src import db
from src.backtest.runner import SEPABacktestRunner
from src.backtest.universe_scorer import UniverseScorer
from src.backtest.score_lookup import prototype_scores_to_contract

# --- canonical config (ONE name per thing) ---
DB_PATH   = ROOT / "data" / "market_data.duckdb"        # Path; str() at call sites
CASH      = 25_000
BINARY    = str(ROOT / "models" / "m01_binary" / "v1" / "model.json")
PROTO_VER = "m01_prototype_2003_2026_20260514_233125"
CACHE_DIR = ROOT / "data" / "backtest_cache"; CACHE_DIR.mkdir(parents=True, exist_ok=True)

assert DB_PATH.exists(), f"DB missing at {DB_PATH}"
print(f"DB: {DB_PATH.name} ({DB_PATH.stat().st_size/1e9:.1f} GB) · cache: {CACHE_DIR}")
```

## Cell B — score loaders (canonical)

```python
def load_scores(signal: str):
    """signal in {'binary','proto'} -> (scores_df, (start,end)). binary is honest
    multi-regime (2021+); proto is the bull-only prod path (2025-10+)."""
    if signal == "binary":
        s = UniverseScorer(m01_path=BINARY, calibration_path=None).score_from_t3(
            "2021-01-01", "2026-05-22", db_path=str(DB_PATH))
        return s, ("2021-01-01", "2026-05-22")
    if signal == "proto":
        con = db.connect(str(DB_PATH), read_only=True)
        raw = con.execute("""SELECT prediction_date AS date, ticker,
            prob_class_3 AS prob_elite FROM daily_predictions
            WHERE model_version_id=? AND prediction_date BETWEEN ? AND ?""",
            [PROTO_VER, "2025-10-06", "2026-05-22"]).df()
        con.close()
        return prototype_scores_to_contract(raw), ("2025-10-06", "2026-05-22")
    raise ValueError(signal)

# load once, reuse across all experiments (⏳ binary ~2min)
SIGNAL = "binary"
scores, WINDOW = load_scores(SIGNAL)
print(f"[{SIGNAL}] {len(scores):,} rows · {scores['date'].nunique()} days · "
      f"prob_elite max={scores['prob_elite'].max():.2f}")
```

## Cell C — FINGERPRINT: components → kwargs → name

```python
# A strategy is (Entry, Stop, TP, Selection). Each component -> engine kwargs.
# The fingerprint NAME is built from the chosen components + their grid suffix,
# and is the cache key. See docs/.../strategy_exploration_summary.md for the index table.

def build_strategy(entry="E1", stop="X1.sl10", tp="X3.sma50", selection="S0.top",
                   entry_grid=None, **extra):
    """Return (fingerprint_name, strategy_kwargs). Components are strings like
    'E2.d3', 'X1.sl15', 'X4.atr2', 'X3.sma20'. Unknown suffixes pass through as-is."""
    kw = dict(entry_mode="top_n", entry_top_n=5, rank_by="prob_elite",
              min_prob_elite=0.0, min_score=0,
              regime_max_pos={0:0,1:5,2:5,3:5,4:5}, sizing_mode="equal_weight",
              sma_exit_independent=True, min_hold_days=3)

    # --- Entry ---
    e_idx, _, e_suf = entry.partition(".")
    if e_idx == "E1":
        kw["entry_delay_days"] = 0
    elif e_idx == "E2":
        kw["entry_delay_days"] = int(e_suf.replace("d","")) if e_suf else 3
        g = entry_grid or dict(entry_ret_lo=-0.15, entry_ret_hi=0.30)
        kw.update(g)

    # --- Stop (SL) ---
    # NOTE: initial_stop = max(price - atr_stop_mult*ATR, price*(1-max_stop_pct)).
    # Setting atr_stop_mult=0 makes stop_atr == price -> stop AT entry -> instant
    # stop-outs (the -84% bug). X1 keeps the engine default ATR (2.0) so the % stop
    # is the binding floor; the wider of the two protects the trade.
    s_idx, _, s_suf = stop.partition(".")
    if s_idx == "X1":
        kw["max_stop_pct"] = int(s_suf.replace("sl",""))/100 if s_suf else 0.10
        # leave atr_stop_mult at engine default (2.0) — do NOT set 0.0
    elif s_idx == "X4":
        kw["atr_stop_mult"] = float(s_suf.replace("atr","")) if s_suf else 2.0
        kw["max_stop_pct"] = 1.0  # X4 = pure ATR trail; disable the % floor

    # --- Take-profit / trend exit ---
    t_idx, _, t_suf = tp.partition(".")
    if t_idx == "X3":
        kw["sma_exit_period"] = int(t_suf.replace("sma","")) if t_suf else 50
    elif t_idx == "X2":   # score-drop rotation exit
        kw["score_drop_thresh"] = 0.08; kw["score_exit_floor"] = 0.10

    kw.update(extra)
    name = f"{entry}_{stop}_{tp}_{selection}"
    return name, kw

# selection is applied to the SCORES, not the kwargs (see Cell D rank_key).
```

## Cell D — CACHE: run-or-load trades, keyed by (fingerprint, signal, window, cash)

```python
def _cache_key(name, signal, window, cash, seed=None):
    raw = f"{name}|{signal}|{window[0]}_{window[1]}|{cash}|{seed}"
    h = hashlib.md5(raw.encode()).hexdigest()[:10]
    safe = name.replace("/", "-")
    return CACHE_DIR / f"{safe}__{signal}__{h}.parquet"

def run_strategy(name, kwargs, scores_df, signal, window, cash=CASH, seed=None, use_cache=True):
    """Run (or load) one strategy. Caches the TRADE HISTORY to parquet + metrics
    sidecar json. Returns (trades_df, metrics_dict). Reuse across sessions."""
    cache = _cache_key(name, signal, window, cash, seed)
    meta = cache.with_suffix(".json")
    if use_cache and cache.exists() and meta.exists():
        return pd.read_parquet(cache), json.loads(meta.read_text())

    r = SEPABacktestRunner(start_date=window[0], end_date=window[1], initial_cash=cash,
                           db_path=str(DB_PATH), model_path=None, model_version_id=None)
    r.setup(scores_df=scores_df, strategy_kwargs=kwargs)
    m = r.run()
    tr = r.get_trade_dataframe()
    tr = tr if tr is not None else pd.DataFrame()
    # persist equity too (small) for later charting without a re-run
    eq = r.get_equity_curve_dataframe()
    metrics = {k: (float(v) if isinstance(v, (int, float)) and v == v else v)
               for k, v in m.items() if not isinstance(v, (dict, list))}
    metrics["fingerprint"] = name; metrics["signal"] = signal
    metrics["window"] = list(window); metrics["cash"] = cash; metrics["seed"] = seed
    tr.to_parquet(cache, index=False)
    if eq is not None: eq.to_parquet(cache.with_name(cache.stem + "__equity.parquet"))
    meta.write_text(json.dumps(metrics, indent=2, default=str))
    return tr, metrics

def load_equity(name, signal, window, cash=CASH, seed=None):
    p = _cache_key(name, signal, window, cash, seed)
    ep = p.with_name(p.stem + "__equity.parquet")
    return pd.read_parquet(ep) if ep.exists() else None
```

## Cell E — usage: define strategies by fingerprint, run cached

```python
# Define the strategies you want to compare purely by their fingerprint components.
STRATS = [
    build_strategy(entry="E1", stop="X1.sl10", tp="X3.sma50"),               # survivor
    build_strategy(entry="E1", stop="X1.sl15", tp="X3.sma50"),               # wider stop
    build_strategy(entry="E2.d3", stop="X1.sl10", tp="X2",                   # rotation
                   entry_grid=dict(entry_ret_lo=-0.05, entry_ret_hi=0.15)),
    build_strategy(entry="E1", stop="X4.atr2", tp="X3.sma50"),               # ATR stop
]

rows = []
for name, kw in STRATS:
    tr, m = run_strategy(name, kw, scores, SIGNAL, WINDOW)   # cached after 1st run
    rows.append(dict(fingerprint=name, trades=m.get("total_trades"),
                     ret=round(m.get("total_return",0),1), sharpe=round(m.get("sharpe_ratio") or 0,2),
                     maxDD=round(m.get("max_drawdown",0),1), win=round(m.get("win_rate",0),1)))
    print(f"  {name}: {rows[-1]['ret']:+.0f}% sharpe={rows[-1]['sharpe']}", flush=True)
pd.DataFrame(rows).set_index("fingerprint")
```

---

## Notes on the cleanup

- **Deleted duplicates:** `INITIAL_CASH`→`CASH`, `PROTO_VERSION`→`PROTO_VER`, `DB`+`DB_PATH`→
  `DB_PATH` (Path; `str()` only at DuckDB/runner call sites), single `ROOT` via `_repo_root()`.
- **`scores`/`WINDOW`/`SIGNAL`** are the canonical loaded-data names — every experiment cell reads
  these, so switching signal = change `SIGNAL` in Cell B and re-run once.
- **Selection experiments** (`rank_key`) still transform `scores` before `run_strategy` — pass the
  transformed frame in and add the `S*` tag to the fingerprint name manually, e.g.
  `run_strategy("E1.d0_X1.sl10_X3.sma50_S2.rndQ", kw, rank_key(scores,"rand_top_quartile",seed=s), ...)`.
- **Cache lives in `data/backtest_cache/`** — parquet trades + `__equity.parquet` + `.json` metrics
  per run. Delete a file to force recompute; `use_cache=False` to bypass.
```
