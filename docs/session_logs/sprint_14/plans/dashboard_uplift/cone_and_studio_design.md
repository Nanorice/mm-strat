# Cone study on the dashboard — Studio revision + label cone + cache design

> Sprint 14, dashboard uplift. **DESIGN ONLY — no implementation** (user: *"focus on the
> design first as it can be complicated"*). Supersedes nothing; extends
> `backtest_studio_page.md`, which knows about only one of the two cones.
> Tier 2 (workshop) — dense/mono, **do NOT theta-style**.

---

## 0 · The correction this doc exists for

> **Terminology is now pinned in `docs/architecture/glossary.md`** — written *because* of
> this confusion. It carries the `label_cone` / `strategy_cone` split, the `prob_elite`
> audit, and the gate definition. **Use those names; never bare "cone".**

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

### What we cache — DECIDED 2026-07-17 (user)

**Rule: cache everything locally; sync only the slice that matters to the slim DB.**
Trades are a **dev-box** activity — the remote never needs them.

| Artifact | Where | Why |
|---|---|---|
| cell `metrics.json` → **`cone_cells` table** | main DB **+ slim** (MANIFEST) | 2,892 rows, trivial; renders the **full distribution** |
| `equity.parquet`, **selected arm** | main DB **+ slim** | ~89 × 7.4 KB ≈ **660 KB**; the stacked equity cone + exposure charts |
| `trades.parquet` / `rejections.parquet` | **local only** (~37 MB) | the trade zoom is a research-bench activity; keeps the ~751 MB slim budget clean |
| `config.json` per cell | local + fingerprint in `cone_cells` | the params that made the cell |

**`cell_id` = a CONTENT FINGERPRINT** (user's call): `sha256` of the cell's canonical config
(params + start + horizon + score_scale + input hash), following `label_registry`'s
`fingerprint()` precedent. **Not the path** — today a cell is identified by
`<arm>/<grid>/r_200301_h12`, so renaming an arm dangles every reference. A content id means
two identical configs collide to the same id → **you can prove a re-run reproduces**, and it
survives backtest-engine edits that don't change the config.

### The score cache — MEASURED, and it corrected the plan

⚠️ **An earlier draft of this doc was WRONG** about the inputs. The real numbers:

| Cache | Rows | Size | Columns |
|---|---|---|---|
| `m01_binary_calibrated_2003-01-01_2026-05-22.parquet` | **8,934,524** | **14 MB** | `date, ticker, prob_elite, calibrated_score` |
| `..._sepa_gated.parquet` | **122,359** (1.37%) | **429 KB** | same **+ `trend_ok`, `breakout_ok`** |
| `binary_2021_2026.parquet` | — | 3.29 GB | a **different, older** artifact (2021–2026 only) — NOT the alternative input |

**Neither cache holds features** — both are just scores. Features live in
`t3_sepa_features`. The earlier "3.29 GB panel vs 429 KB" framing was a false comparison;
**the whole score cache for full history is 14 MB.**

**Verified**: the gated file is a **strict subset** of the full one — same `(date,ticker)`
keys, `max |prob_elite diff| = 0.0`, and every row is `trend_ok=TRUE ∧ breakout_ok=TRUE`.
It carries **no independent information**; it is a materialized `WHERE`.

**DECISION: keep ONE cache (the 14 MB full), ADD the two flag columns to it, delete the
gated copy.** (User: *"if 14mb is the full score, why don't we just keep this? the filtering
is cheap and we can always apply on the fly"* — correct, with one caveat that makes it
true.)
- ⚠️ **The caveat**: the full cache does **not** carry `trend_ok`/`breakout_ok` today, so
  "filter on the fly" is currently **a DB join** (`attach_sepa_flags`), not a `WHERE`. That
  join is why the pre-gated copy exists at all. It also means a "pinned" study silently
  depends on **t3 being unchanged** — the one thing a file hash does NOT pin.
- Adding the flags (~15 MB) makes the artifact **self-contained**: the filter becomes a real
  `WHERE`, with no DB dependency, and the population decision is **inspectable in the file**
  rather than living in a script docstring.

### THE GATE (what `trend_ok ∧ breakout_ok` means) — the thing actually worth pinning

```sql
trend_ok  = C1-C9 Minervini trend template (src/feature_pipeline.py:397-406):
            close > SMA150 AND close > SMA200 AND SMA150 > SMA200
            AND SMA200 > SMA200_lag20        -- 200d rising
            AND SMA50 > SMA150 AND close > SMA50
            AND close > low_52w * 1.3        -- 30% off the low
            AND close > high_52w * 0.85      -- within 15% of the high
            AND price_vs_spy > price_vs_spy_ma63   -- RS line uptrending

breakout_ok = breakout = 1 AND volume / vol_avg_50_prev > 1.3   -- volume confirmation
```
i.e. **a genuine breakout day on a stock already in a Stage-2 uptrend.**

🛑 **The gate is a BUG FIX, not an optimization.** Per `_load_scores()`'s own docstring: the
full cache scores **every trend-active t3 row**, so an ungated `nlargest(prob_elite)` draws
from *"an inflated pool of off-setup days — the population-inflation bug"* — it would pick
names on days the strategy would never have traded. **8.9M → 122k (1.37%) is the
correction.** So pinning the input pins a **population decision**, not just a file: the same
scores under a different gate are **a different study**, and every cached cell must record
which gate it used.

### Input pinning — DECIDED
**Pin by path + content hash** (user preference), recorded in the cell config. At 14–15 MB
the cache is also cheap enough to copy outright for a study whose result matters (e.g. a
promotion decision) — decide per study. Re-derivable by re-scoring if lost; the scores are
the heavy lifting, the features are in the DB.

### (superseded) Original framing

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

### Score-cache sizing note — RESOLVED, see "The score cache" above
The boundary worry was **overstated by a bad comparison** (mine): `binary_2021_2026.parquet`
(3.29 GB) is a different, older artifact, not the study's input. The real input is **14 MB**
for full history. **"Cache everything" is affordable here** — the boundary that matters is
not the score cache but the **373 MB of cone cells**, and that's handled by syncing
metrics + selected-arm equity to slim while trades stay local.

---

## 5 · Materialization — DECIDED 2026-07-17 (user)

**`build_cone_cache.py` (CLI, run after a sweep) + a staleness check in the serving audit.**

- **CLI, not a phase** — the inputs change when *you* run a sweep (~monthly), not nightly.
  A nightly Phase 7.48 would re-read 2,892 dirs to write a byte-identical table ~29 nights
  in 30: the wallpaper mistake in a different costume. Same shape as `run_cone_gate.py`.
- **+ staleness check** (`tools/audit_serving_tables.py`) — CLI's weakness is exactly the
  failure this sprint just fixed: a silently stale artifact nobody watches. Check =
  **newest cell mtime vs the `cone_cells` build time**; WARNING if cells are newer than the
  table (a sweep ran, the cache wasn't rebuilt). We have the audit now — use it.
  ⚠️ Tolerance must be **measured**, not guessed, like every other check in that file.
- **Which arms**: falls out of the CLI decision — the page enumerates **whatever is in the
  table**, i.e. whatever you swept. No hardcoded arm list. (`data/cone_gate/` has 2 today;
  `selection_sweep/starttime` has more: breadth / slope / compose × grids.)

## 5b · Still open (build-time)

1. Does the **label cone** get the same cell-level cache, or is a rendered fan enough?
   `basket_paths` persists **nothing** today — it recomputes in minutes, so the Model Lab
   page needs *some* artifact. Likely the same `cone_cells` shape with an `engine` tag
   distinguishing `basket_paths` from `vec`/`backtrader`.
2. Rebuilding the score cache **with the flag columns** (see above) — a one-off, but it
   invalidates the gated copy and anything pinned to its hash.

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
