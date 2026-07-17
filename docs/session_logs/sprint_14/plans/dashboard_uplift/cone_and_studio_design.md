# Cone study on the dashboard — Studio revision + label cone + cache design

> Sprint 14, dashboard uplift. **DESIGN ONLY — no implementation** (user: *"focus on the
> design first as it can be complicated"*). Supersedes nothing; extends
> `backtest_studio_page.md`, which knows about only one of the two cones.
> Tier 2 (workshop) — dense/mono, **do NOT theta-style**.

---

## 0 · The correction this doc exists for

**There are TWO cones and they are different objects.** The Studio plan, and my first read
of it, treated `data/cone_gate/` as *the* cone. It isn't — it's the strategy one.

| | **Label cone** (§5 "equity fan") | **Strategy cone** (`cone_gate`) |
|---|---|---|
| Engine | `basket_paths` — fixed horizon (150d), stop (15%), **no rotation, no TP** | `VectorizedSEPABacktest` / BackTrader — slots, rotation, tranche exits |
| Asks | *is the label worth anything on the population?* | *did this strategy earn promotion?* |
| Stage | **model / label** | **strategy** |
| Code | `docs/session_logs/sprint_14/scripts/start_day_basket_paths.py` (sprint-local) | `scripts/run_cone_gate.py` (repo) |
| Persisted | ❌ **nothing** — recomputed per call from a score-cache parquet | ✅ per-cell dir + aggregate JSON |
| Currency | ~C1/C2 (a label claim, buy-and-hold proxy) | **C3** (exit-P&L) |

They must never render as the same object. **A buy-and-hold-to-exit fan is not a backtest
result** — it's the proxy that tells you whether the label has anything in it before a
strategy is wrapped around it.

## 1 · The organising spine (user's, and it's better than the currencies)

> **data → model/label → strategy**

The three currencies (C1 label / C2 OOS / C3 exit-P&L) classify *how strong a claim a
result licenses*. The **stage** is the pipeline. The currency is what each stage lets you
say. Pages split by **stage**; the currency is a **banner within** the page.

| Stage | Page | Holds | Currency banner |
|---|---|---|---|
| **data** | **Dataset EDA** (exists, 120 lines) | pretrain audit reports — target dist, class balance, feature/target | none (upstream of any edge claim) |
| **model / label** | **Model Lab** (exists, 319 lines, registry + tabs) | model card *(C1 banner shipped)* · **+ the sprint-summary EDA** · **+ the LABEL cone** | **C1** |
| **strategy** | **Backtest Studio** (exists, needs revision) | run browser · **strategy cone** · per-cell zoom · compare | **C3** |

⚠️ **This is why "split EDA by currency" doesn't quite work**: EDA is *input inspection*,
upstream of every currency — a currency tag there would imply a claim it isn't making. The
split is **by stage**; the currency rides along as the claim-strength label.

---

## 2 · Model Lab — absorb the label EDA (NEW scope)

Model Lab today is a registry table + per-model tabs (Overview / Model Card / Plots /
Specs / Diff / Report). **It's a card browser; it has no population view.** The
sprint-summary EDA (`cells/sprint_summary_eda_cells.md`, 786 lines) is exactly that view
and currently lives only as notebook cells.

**Add as tabs (the page is already tabbed — no rebuild):**

1. **Funnel** (§1) — full → trend_ok → breakout counts, the ~100× compression,
   supply-drift, score distribution per tier, top-5 churn/tenure.
2. **Label outcome** (§2/§3/§4) — forward-return distribution across horizons, raw vs
   score-gated; worst-decile regime clustering; sector × market-cap cuts.
3. **Label cone** (§5) — the equity fan: every start-day's buy-and-hold-to-exit path,
   4 variants (regime-gate on/off × score-gate on/off).

**Framing that must ship with it** (from the notebook's own synthesis, non-negotiable):
- **Median is the misleading lens; the tail is the signal** (Cell A3). A median-first
  chart here would contradict the sprint's own conclusion.
- **`label lift ≠ trade edge`** — this whole page is C1. It licenses *"the label ranks the
  tail"*, never *"this makes money"*. That's the Studio's question.

🛑 **The `prob_elite` two-scale trap — load-bearing for any cached artifact.**
The panel/multiyear parquets carry **RAW** `p_pos` (median ~0.55 → gates at 0.5/0.6/0.7);
`basket_paths`' score cache carries **CALIBRATED** iso output (median ~0.12 → 0.15 ≈ the
coin-flip line). §1/§2 use RAW gates, §5 uses CALIBRATED. **A cached cone that does not
record which scale its gate was on is unreproducible AND silently misleading** — the same
number means two different things. `[[project_isotonic_flattens_ranking]]`

---

## 3 · Backtest Studio — revision (extends `backtest_studio_page.md`)

Keep that doc's build order; it's right. Restated with the new findings:

1. **C3 banner** — cheapest clarity win.
2. **Engine column + vec caption** — vec median Sharpe **1.51 vs BackTrader 0.35 on the
   same config** (`[[project_vec_engine_optimistic]]`). Today they sit in one table looking
   comparable. **This is actively misleading and one column fixes it.**
3. **Strategy cone verdict, promoted** — see §4.
4. **Demote single-Sharpe** to a per-run detail (the champion is start-time dependent;
   one Sharpe is the draw the sprint disproved).

### NEW (user): zoom into any cell + charts beyond the equity curve

The per-cell artifacts **already carry everything needed** — nothing to build, only to
surface. Verified on disk (`data/selection_sweep/starttime/<arm>/<grid>/r_*/`):

| File | Size (sample) | Gives |
|---|---|---|
| `config.json` | 813 B | **the params that made this cell** → re-runnability |
| `metrics.json` | 535 B | sharpe/maxDD/calmar/win_rate/sqn/trades/net_profit (16 keys) |
| `equity.parquet` | 7.4 KB | `date, value, cash, position_value, position_count, regime` |
| `trades.parquet` | 12.7 KB | **trade-level results** ← the zoom-in |
| `rejections.parquet` | 6.6 KB | what it *didn't* buy ← nobody has looked at this |

So a cell drill-down supports, with zero new computation:
- **trade list** (the ask) + per-trade P&L distribution,
- **exposure over time** (`position_count`, `cash` — the equity curve alone hides that a
  flat stretch is *no positions*, not a losing hold),
- **regime-shaded equity** (`regime` is per-bar already),
- **rejections** — why a slot didn't fill (slot-refill is path-dependent,
  `[[feedback_rerun_dont_postfilter]]`).

**Layout**: keep the current run-browser → per-run-detail shape; the cone becomes the
entry point *above* it, and selecting a cone cell drills into the same existing detail
view. One detail component, two ways in (run browser, cone cell).

---

## 4 · Cone rendering — full distribution (deferred implementation)

`data/cone_gate/<arm>.json` holds **summary + gates only**:
```
n_cells 89 · median_sharpe 0.592 · p25 −0.112 · p75 1.104 · floor −1.735
pct_negative_cells 30.3 · median_calmar 0.773 · worst_max_drawdown 44.4
alpha_ann_vs_SPY 0.156 · beta_vs_SPY 0.583   (+ QQQ)
gates[]: {name, status pass/fail, value, threshold, detail, blocking}
```
That renders the **verdict** (gates carry their own pass/fail + thresholds — no logic to
re-derive). It does **not** render a distribution.

**User's call: full distribution** — i.e. the stacked equity curves, not the buy-and-hold
proxy. The inputs exist per cell. **The constraint is volume**, measured:

> **2,892 cells / 373 MB** on disk under `data/selection_sweep/starttime`.

So the page **cannot** walk the directory tree per render, and 373 MB **cannot** go into
the slim DB (currently ~751 MB total; `[[project_slim_dashboard_db]]`).

### What we cache (the decision this doc needs to make explicit)

**Two tracks, deliberately separate** (user: *"we want full re-runnability, but this is an
infra topic, and no need to show in dashboard"*):

**Track A — the dashboard reads a materialized SUMMARY. Bounded.**
- `cone_cells` table: one row per cell — `arm, grid, cell, start, horizon, sharpe,
  max_drawdown, calmar, total_return, win_rate, total_trades, n_open_max, engine,
  score_scale, gate_value, code_version`. ~2,892 rows × ~15 cols = **trivial**; ships in
  the slim DB via MANIFEST (`[[project_dashboard_remote_parity]]`).
- That alone renders the **full distribution** (histogram / spaghetti of per-cell Sharpe,
  cone quantiles over start-date) — the thing the user asked for.
- **Equity curves are the bulk, not the metrics.** Options, decide at build time:
  (a) ship equity only for the *selected arm* (89 cells × 7.4 KB ≈ **660 KB** — fine), or
  (b) downsample to weekly, or (c) leave equity local-only and let the remote show the
  distribution + metrics without per-cell curves. **(a) is the lazy one that works.**
- **Trades/rejections stay local-only** (12.7 KB × 2,892 ≈ 37 MB — too big for slim, and
  the remote is a viewing surface, not the research bench). Drill-down degrades gracefully:
  distribution + metrics remote, full trade zoom local.

**Track B — re-runnability. NOT a dashboard feature.**
- `config.json` per cell already pins the params. What's missing for a true re-run:
  `basket_paths` lives in **`docs/session_logs/sprint_14/scripts/`** — a sprint folder.
  A dashboard must never import from there; and once sprint 14 is wrapped, that path is
  archaeology.
- **If** re-runnability is wanted as infra: promote `basket_paths` → `src/backtest/`, pin
  the score-cache path + hash, record the code version in the cell config. That is a
  **repo/reproducibility task, explicitly out of the dashboard's scope.**
- ⚠️ Whatever we cache **must record `score_scale` (raw|calibrated)** — see the §2 trap.
  Without it the cached gate value is ambiguous and the artifact lies.

### Score-cache sizing note (why "cache everything" needs a boundary)
`data/score_cache/`: **3.29 GB** (`binary_2021_2026.parquet`) vs **14 MB** (calibrated
2003–2026) vs **429 KB** (sepa_gated). The gated cache is ~7,600× smaller than the raw
panel and is what §5 actually reads. "Cache every info" is unbounded in the wrong
direction; **cache the outputs + the params, and pin the input by path+hash** rather than
copying 3 GB.

---

## 5 · Open questions (build-time, not now)

1. **Which arms** does the Studio show? `data/cone_gate/` has 2
   (`champion_trail_spygate`, `_4cls`); `selection_sweep/starttime` has more (breadth /
   slope / compose × grids). Does the page enumerate arms, or pin the champion?
2. **Who materializes `cone_cells`?** A phase (nightly, but cones change ~never), or a CLI
   run after a sweep (on-demand, and the artifact is a research output, not a daily one)?
   → **Lean: CLI**, like `run_cone_gate.py` itself. A nightly phase for a table that
   changes monthly is the wallpaper mistake in a different costume.
3. Does the **label cone** get the same cell-level cache, or is a rendered fan enough?
   (`basket_paths` persists nothing today — it recomputes in minutes, so the page needs
   *some* artifact.)

## 6 · Hard constraints (carried in, don't relitigate)

- **Shadow app only.** New/revised pages land in the uplift suite (`dashboard_uplift.py`
  nav + `scripts/pages/`), **never wired into live `dashboard.py`** until the user calls
  the switch-over. ⚠️ **Model Lab and Backtest Studio are LIVE pages today** (`dashboard.py`
  mounts them) — so unlike Macro/Screening/Portfolio, revising them **touches the working
  version**. The uplift versions must be **new files** in the shadow nav, leaving the live
  ones untouched, and get folded in at switch-over.
- **Promote on BackTrader, never vec.** Vec = ranking only.
- **The cone is a start-DATE sweep** — the edge is a regime ride, so a single P&L is a
  draw, not the verdict. `[[project_champion_starttime_dependent]]`
- **Tier 2 = dense/mono.** No cream/serif restyle.
- Any new table a loader reads → `build_dashboard_db` MANIFEST, verified against
  `dashboard.duckdb` **directly** (never through a loader).
