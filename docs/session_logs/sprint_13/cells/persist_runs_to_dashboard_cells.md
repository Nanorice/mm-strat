# Notebook cell — persist backtest runs to Backtest Studio

Paste after the `runs = {...}` loop in `s13_bt_strategy.ipynb`. Writes each run to
`data/backtest/<run_note>/` (manifest + equity + trades + metrics + **plot.png**), where
[scripts/pages/4_Backtest_Studio.py](../../scripts/pages/4_Backtest_Studio.py) discovers it.

Pass `strategy_name` = a registry key to tag the run with its fingerprint + description
(the dashboard then shows the tag, the plain-English blurb, and a term glossary). The
notebook's `E1_immediate`/`E2_delay3_band` aren't registry entries — use `None` (they still
persist, just without the registry blurb), or map them to `champion` / `e1_seed` if the
kwargs match.

```python
# E1 ≈ e1_seed's spirit (immediate, top-5, SMA exit); E2 is a bespoke rotation arm (no reg key).
REG_TAG = {"E1_immediate": "e1_seed", "E2_delay3_band": None}

from pathlib import Path
BT_DIR = ROOT / "data" / "backtest"
for name, (r, m) in runs.items():
    run_dir = BT_DIR / f"nb_{name}"          # nb_ prefix = notebook-sourced, easy to spot
    r.save_run(m, run_dir=run_dir, strategy_name=REG_TAG.get(name))
    print(f"saved {name} -> {run_dir}  (tag={REG_TAG.get(name)})")
```

Then open the dashboard → **Backtest Studio** page. Each `nb_*` run lists with its metrics,
the 6-panel PNG inline, and (if tagged) the description + fingerprint glossary.

> **Local-only** (per this session's decision): these live on the research box's filesystem,
> not in `dashboard.duckdb`, so the R2 remote app won't show them. To publish remotely later,
> add the run artifacts to `build_dashboard_db.py`'s MANIFEST (parity rule
> [[project_dashboard_remote_parity]]).

**Skipped:** registering E1/E2 as formal strategies — they're notebook experiments, not
champions. Add to `strategy_registry.py` only if one graduates.
