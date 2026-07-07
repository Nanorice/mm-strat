# Dashboard Implementation Plan

> **Created:** 2026-05-23
> **Revised:** 2026-05-23 (post-review: fact-corrected against repo state; Pages 3/4
> pivoted to static-HTML rendering; removed prod-promotion from UI; placeholder
> diff tab; manifest filter rule defined; audit history scope clarified).
> **Owner:** Hang
> **Status:** Draft for review.
> **Companion docs:** [whitepaper](whitepaper_path_forward_2026_05_23.md) §4 sets
> the page-level vision; this document is the page-by-page implementation spec.
> [`docs/plans/development_roadmap.md`](development_roadmap.md) §3 is the prior
> draft of the dashboard redesign.

---

## 0. Scope

**In scope.**
- Today (default landing) — enhanced version of current screener page with
  5-factor risk added and watchlist ranked by P(Home Run).
- Backtest viewer — render existing backtest artifacts (markdown reports +
  parquet trades + equity curves) inside Streamlit.
- Model Lab — list registered models, render their existing evaluation artifacts
  (PNGs + report markdown + pretrain HTML).
- Ticker Deep Dive — extend the existing Feature Time Series page with diagnostic
  matrix + score trajectory + fundamentals + earnings calendar.
- Pipeline Health — pipeline_runs RAG view + data freshness + audit history.

**Out of scope.**
- Any data ingestion or model-training work (those are pipeline/sprint
  deliverables, not dashboard).
- Auth or remote hosting — localhost-only, single user.
- LLM-ticker-analysis (deferred per `development_roadmap.md` §3).
- Forward-paper-trade tracker UI — that's a separate small deliverable
  (whitepaper §6 item #11); the data layer it needs is noted here but the page
  itself is scoped separately.

**Build philosophy.** Reuse existing assets aggressively. Almost everything we
need exists as a DuckDB table, a registered Python function, a generated PNG,
or a generated Markdown report. The dashboard's job is to *expose* that work,
not to recompute it.

**Static HTML for graph-heavy pages (Model Lab + Backtest Studio).** These two
pages render a small, fixed set of results (model registry has tens of versions;
backtest archive will have tens of runs). Generate self-contained HTML reports
offline (Plotly inlined, one file per model/run) and have Streamlit `iframe` them
via `st.components.v1.html`. No live recomputation, no per-page chart wiring.
The infra for this already exists — see [src/evaluation/html_report.py:242](../../src/evaluation/html_report.py#L242)
(`build_html_report`) and its sequencer at
[src/evaluation/pretrain_report.py:221](../../src/evaluation/pretrain_report.py#L221).

---

## 1. Inventory: what we already have

### 1.1 DuckDB tables (read-only, all already populated)

| Table | Rows | What's in it | Used for |
|---|---|---|---|
| `t2_regime_scores` | ~1.5K | `m03_score`, pillars (trend/liq/risk), 5d/20d deltas, regime_vol | M03 header on every page |
| **`t2_risk_scores`** | ~6K | 5F: `target_exposure`, `weighted_z`, `rolling_percentile`, per-factor z-scores, `veto_flag` | NEW — 5F regime card on Today page |
| `screener_watchlist` | ~38K | All trades (ACTIVE/EXITED) with `entry_date`, `pct_return`, `days_held` | Today page main table |
| `sepa_watchlist` | ~35K | Session event log (ACTIVE/COOLDOWN/EXITED, `cooldown_end`) | Pre-breakout watchlist filtering |
| `v_d3_deployment` | ~last 252d × ~2K | Last 252 days of SEPA candidates with features | M01 live scoring (current dashboard already uses this) |
| `t3_sepa_features` | ~9.4M | 144 cols dense daily features for SEPA universe | Ticker Deep Dive feature panel (already used by Feature Time Series page) |
| `t2_screener_features` | ~9.6M | Broad universe daily features (includes `trend_ok`, `breakout_ok`) | "Watchlist not-yet-broken-out" cohort (`trend_ok=TRUE AND breakout_ok=FALSE`) |
| `models` | varies | Registry: `version_id`, `status_flag`, `specs_json`, `accuracy`, `weighted_f1`, `macro_f1`, `artifacts_path` | Model Lab page |
| `pipeline_runs` | varies | Phase execution: `target_date`, `phase_name`, `status`, `runtime_seconds`, `started_at`, `completed_at` | Pipeline Health page (current dashboard already uses for the status bar) |
| `fundamentals` | ~300K | IS/BS/CF quarterly | Ticker Deep Dive fundamentals snapshot |
| `earnings_calendar` | ~20K | Upcoming/past earnings dates | Ticker Deep Dive earnings warning |
| `company_profiles` | ~3K | Ticker, sector, industry, is_active | Universe metadata everywhere |

### 1.2 Existing Python modules (importable)

| Module | What it gives the dashboard |
|---|---|
| `src/screener_diagnostics.py` (`ScreenerDiagnostics`) | Per-ticker `diagnose(ticker, days)` → freshness, trades, **per-day C1-C9 / B1-B2 pass/fail matrix**, transitions. Drops into Ticker Deep Dive verbatim. |
| `src/data_loader_duckdb.py` (`load_training_data_from_db`) | Cached load of training data with column-case normalization. |
| `src/model_registry.py` (`ModelRegistry`) | `list_versions()`, `get_model_specs()`, `get_artifacts_path()`, `get_reproducibility_info()`. Directly powers Model Lab. |
| `src/evaluation/` (full library) | `ClassificationEvaluator`, `feature_signal` (IC/MI/redundancy), `data_quality.run_quality_gate`, `pretrain_report`, **`html_report.build_html_report`** (full Plotly HTML report generator). Means the Model Lab page is mostly "embed iframes". |
| `src/backtest/universe_scorer.py` (`UniverseScorer`) | `score_from_t3` / `score_from_duckdb` — used by Today page to recompute scores on demand if needed. |
| `src/pipeline/risk_5_factor.py` (`RiskFiveFactorCalculator`) | Already writes to `t2_risk_scores`; dashboard just reads. |

### 1.3 Existing artifacts on disk

| Location | Format | What |
|---|---|---|
| `models/<name>/<version>/evaluation/` | PNG + .md + .json | confusion_matrix, feature_importance, roc_curves, pr_curves, calibration_curves, class_distribution, report_*.md, results.json |
| `models/<name>/<version>/evaluation/diffs/` | .json + .txt | `model_diff.py` side-by-side comparisons (may not exist for all models) |
| `docs/reports/pretrain_audit_*.html` | self-contained HTML | Output of `scripts/run_pretrain_audit.py` (Plotly inlined, offline-viewable). **This is the canonical pretrain artifact** — Model Lab iframes these. |
| `data/evaluation/` | PNG + CSV (flat) | Legacy section-1/2/3 PNGs (e.g. `section1_4_survivor_model.png`) and `survivor_analysis.csv`. Flat layout — NOT nested under `<name>/<version>/`. Optional secondary panel; primary view is the HTML in `docs/reports/`. |
| `data/backtest/reports/` | .md | Historical backtest report Markdowns. **Mixed vintage — not all are from the current pipeline.** Only `data/backtest/<run_dir>/` directories with a `manifest.json` containing `"manifest_version": "v1"` are rendered by Page 4 (see §3.2). |
| `data/backtest/case1_prototype_standalone/`, `case2_prototype_plus_rank/` | parquet + JSON | `equity_curve.parquet`, `trades.parquet`, `metrics.json`, `manifest.json` |
| `data/audit_reports/` | JSON | `audit_report_YYYYMMDD.json` from `tools/run_all_audits.py` |
| `logs/daily_pipeline.log` | text | Daily pipeline execution |

### 1.4 Existing Streamlit pages

```
scripts/dashboard.py                                   # current main page (Screener Watchlist)
scripts/pages/1_Feature_Time_Series.py                 # TradingView-style charts + per-feature panels
```

### 1.5 Gaps in the inventory (the only new infra needed)

These three are the **only** missing data layer items. Everything else is purely
Streamlit composition.

| Gap | Why needed | Effort | Status |
|---|---|---|---|
| **`dashboard_snapshot` table** — pre-computed daily snapshot of "Today" page data | Page 1 load < 500ms on warm cache; pre-breakout cohort score needs caching (see §Page 1) | 1 day | Build as part of Phase 1 |
| **`t2_risk_scores` daily refresh wired into orchestrator** | Today page must show fresh 5F | 0.5 day | ✅ Already wired — `RiskFiveFactorCalculator` instantiated at [src/orchestrators/daily_pipeline_orchestrator.py:93](../../src/orchestrators/daily_pipeline_orchestrator.py#L93). Phase-0: verify it actually runs end-to-end and writes a row. |
| **Backtest manifest enrichment + filter rule** | Page 4 must distinguish current-pipeline runs from legacy ones | ✅ Done | Runner now writes `manifest_version: v1` + `model: {name, version_id, path}`. Page 4 filters on `manifest_version == 'v1'`. See §3.2. |
| **Daily audit-report write** | Page 5 audit-history line chart needs new data points to accumulate | 0.5 day | Currently 1 file in `data/audit_reports/`. Add a Phase-9 hook in the daily orchestrator to invoke `tools/run_all_audits.py` and drop a dated JSON. See §3.4. |
| **Per-model classification HTML report** (optional) | Mirror of pretrain HTML, one per model. Lets Model Lab embed a single file per registered model. | 0.5 day | New: factor `build_classification_html_report()` alongside `build_html_report`. Defer until Page 3 build if PNG+iframe-of-pretrain proves insufficient. |

---

## 2. Page-by-page spec

### Page 1 — Today (default landing)

**File:** `scripts/dashboard.py` (replaces current `page_screener_watchlist`)

**Goal.** What do I buy, what do I sell, what's the market doing today.

#### Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Pipeline: 🟢 phase-7 — 2026-05-23 19:42                                │
├──────────────────────────────────┬──────────────────────────────────────┤
│  M03 REGIME                       │  5-FACTOR RISK                       │
│  Score: 72.3 (BULL)               │  Exposure: 0.85                      │
│  Trend ████████░░ 78  Δ +1.2/5d   │  Percentile: 0.34 (calm)             │
│  Liq   ███████░░░ 65              │  Worst factor: z_vix = +0.8          │
│  Risk  ██████░░░░ 58              │  Veto: ✘                             │
├──────────────────────────────────┴──────────────────────────────────────┤
│  SEPA WATCHLIST — Active Trades (n=8)                                    │
│  [Filters: Status | Sector | Sort by ▾ P(HomeRun)]                       │
│  ┌───────┬──────────┬───────┬──────┬──────┬─────────┬─────────┬────────┐ │
│  │Ticker │ Entry    │Days   │Return│ M01  │P(HR)    │P(Strong)│Status  │ │
│  ├───────┼──────────┼───────┼──────┼──────┼─────────┼─────────┼────────┤ │
│  │ABC    │ 04-12    │ 41    │+18.4%│ HR   │ 0.62    │ 0.21    │ACTIVE  │ │
│  │XYZ    │ 03-08    │ 76    │ +4.0%│Mod   │ 0.18    │ 0.31    │ACTIVE  │ │
│  └───────┴──────────┴───────┴──────┴──────┴─────────┴─────────┴────────┘ │
├─────────────────────────────────────────────────────────────────────────┤
│  PRE-BREAKOUT WATCH — trend_ok=TRUE AND breakout_ok=FALSE (n=43)         │
│  Sorted by trailing-10d M01 score                                        │
│  [same table shape, plus `days_in_setup`]                                │
├──────────────────────────────────┬──────────────────────────────────────┤
│  SECTOR HEAT                      │  ANALYTICS                           │
│  Today's high-score density       │  Win rate, holding period, etc.     │
│  vs 5-day rolling avg             │  (current Analytics panel verbatim)  │
└──────────────────────────────────┴──────────────────────────────────────┘
```

#### Component-by-component

**Top bar.** Pipeline status — already exists at `dashboard.py:420-426`
(`render_pipeline_status`). Keep as-is.

**M03 Regime card.** Already exists at `dashboard.py:196-221`
(`render_regime_header`). Keep as-is.

**5-Factor Risk card (NEW).** Add `render_risk_5f_header(risk_5f)`:
```sql
SELECT date, target_exposure, weighted_z, rolling_percentile, veto_flag,
       z_vix, z_hy, z_term, z_trend, z_slope
FROM t2_risk_scores
ORDER BY date DESC LIMIT 1
```
- `target_exposure` mapped to a label band (1.00→Full, 0.85→Reduced, … 0.15→Veto)
  using the `EXPOSURE_BANDS` from `risk_5_factor.py`.
- Worst-factor row: `max(z_vix, z_hy, z_term, z_trend, z_slope)` with the factor
  name. Highlights tail risk source.
- Veto flag with explanation tooltip ("any single z ≥ 2.0σ triggers
  defensive exposure").

The 5F card sits beside the M03 card so the user sees both regimes at once. **This is the change requested by user.**

**Active Trades table.** Current `render_watchlist_table` already does this. Two
specific changes:
- **Default sort column = `P(Home Run)` descending.** Current default is by
  entry date; user explicitly said *"I can rank by P home"*.
- Move the probability columns up before status — they're the action-relevant
  ones.
- Add column toggle for `P(Strong) + P(Home Run)` (sum) — useful when both are
  borderline.

**Pre-breakout watch table (NEW).** New section below active trades. **Scoring
must NOT happen in the request path** — typical cohort is 30-80 tickers and
calling `predict_proba` per request on cold cache will dominate load time. Read
pre-scored values from `dashboard_snapshot` (refreshed nightly at end of Phase 8);
fall back to live scoring only when the snapshot is stale or empty (with an
on-screen "live scoring (slow)" badge so the user knows).
```sql
SELECT t.ticker, c.sector, t.date,
       t.close, t.trend_ok, t.breakout_ok,
       t.dist_from_20d_high, t.vol_ratio, t.vcp_ratio,
       sw.entry_date AS setup_started,
       DATEDIFF('day', sw.entry_date, t.date) AS days_in_setup
FROM t2_screener_features t
LEFT JOIN sepa_watchlist sw
   ON t.ticker = sw.ticker
  AND sw.status = 'ACTIVE'
LEFT JOIN company_profiles c ON t.ticker = c.ticker
WHERE t.date = (SELECT MAX(date) FROM t2_screener_features)
  AND t.trend_ok = TRUE
  AND t.breakout_ok = FALSE
```
- Then score with M01 (same `predict_proba` pipeline as active trades) and rank
  by `P(Home Run)`.
- Once **M01-Watch** (whitepaper §2.2) is trained, add its column alongside.
- `days_in_setup` becomes informative — late-setup names that haven't broken out
  may be losing momentum.

**Sector Heat (NEW).** Top of `development_roadmap.md` §8.
```sql
SELECT c.sector,
       COUNT(*) FILTER (WHERE t.trend_ok = TRUE)             AS trend_ok_n,
       COUNT(*) FILTER (WHERE t.trend_ok AND t.breakout_ok)  AS breakout_n,
       AVG(s.prob_elite) AS mean_prob_elite
FROM t3_sepa_features t
JOIN company_profiles c ON t.ticker = c.ticker
LEFT JOIN scores_cache s ON s.ticker = t.ticker AND s.date = t.date
WHERE t.date = (SELECT MAX(date) FROM t3_sepa_features)
GROUP BY c.sector
ORDER BY breakout_n DESC
```
- Bar chart by sector, two series: today's count vs 5-day rolling average. Delta
  highlight when today > 1.5× rolling.

**Analytics panel.** Current `render_analytics` at `dashboard.py:341-417`.
Keep as-is.

#### Acceptance criteria — Page 1

- Page load < 1s with warm cache (`@st.cache_data(ttl=300)`).
- 5F card renders for any date in `t2_risk_scores` (graceful empty-state if missing).
- Active table defaults to sort by P(HomeRun) descending and that sort survives
  the next refresh (use `st.session_state` for sort key).
- Pre-breakout table is empty-state-tolerant (rare: 0 candidates) and bounded
  (cap at 100 rows; user usually sees 30–80).
- All four data loaders survive `pipeline_runs` showing today's run as RUNNING
  or FAILED — no crashes, just stale-data badges.

---

### Page 2 — Ticker Deep Dive

**File:** `scripts/pages/1_Feature_Time_Series.py` (rename → `2_Ticker_Deep_Dive.py`, extend).

**Goal.** Everything about a single name on one page, no tab-switching.

#### Layout (additive — current page is the bottom half)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  TICKER: ABC  [search box]   Sector: Tech / Software   Active           │
│  Last price: $142.50  (+1.2%)  Date: 2026-05-22                          │
├─────────────────────────────────────────────────────────────────────────┤
│  Diagnostic matrix (per-day C1–C9 + B1–B2 pass/fail, last 15 days)      │
│  ┌─────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐         │
│  │Date │ C1 │ C2 │ C3 │ C4 │ C5 │ C6 │ C7 │ C8 │ C9 │ B1 │ B2 │         │
│  ├─────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤         │
│  │5-22 │ ✓  │ ✓  │ ✓  │ ✓  │ ✓  │ ✓  │ ✓  │ ✓  │ ✓  │ ✓  │ ✓  │         │
│  │…    │…   │…   │…   │…   │…   │…   │…   │…   │…   │…   │…   │         │
├─────────────────────────────────────────────────────────────────────────┤
│  M01 SCORE TRAJECTORY (T-30 to T+30 around latest breakout)             │
│  [line chart of prob_elite + threshold reference @ 0.435]                │
├──────────────────────────────────┬──────────────────────────────────────┤
│  FUNDAMENTALS (last 4 Q)         │  EARNINGS CALENDAR                   │
│  Rev / NI / EPS YoY              │  Next: 2026-07-25  (in 63d)          │
│  [small table]                   │  Past 4: dates + surprise %          │
├──────────────────────────────────┴──────────────────────────────────────┤
│  TRADE HISTORY (this ticker only)                                        │
│  Entry / Exit / PnL / Reason / Regime — from screener_watchlist          │
├─────────────────────────────────────────────────────────────────────────┤
│  PRICE + FEATURE PANELS  ← current Feature Time Series page lives here  │
└─────────────────────────────────────────────────────────────────────────┘
```

#### Component-by-component

**Header.** Ticker selector (search), company name + sector + industry, latest
close + day-change. From `company_profiles` + `price_data`.

**Diagnostic matrix.** Call `ScreenerDiagnostics().diagnose(ticker, days=15)`
verbatim. Result is a dict that `print_report` formats for console; we render
the per-day matrix as a pandas DataFrame with conditional formatting
(green/red cells). **Estimated effort: 1 day** (function exists; just need the
Streamlit rendering).

**M01 Score trajectory.** Load 60 days of `prob_elite` from a scoring run for
this ticker; mark breakout day(s) from `sepa_watchlist`; horizontal reference
line at 0.435 (decile-9 floor from `development_roadmap.md` §6a). If
`scores_cache.parquet` exists (referenced in development_roadmap; check for
file), use it; else recompute on the fly via `UniverseScorer.score_from_t3`
filtered to one ticker (fast).

**Fundamentals snapshot.** Latest 4 quarters from `fundamentals`:
```sql
SELECT period_end, total_revenue, net_income, diluted_eps, filing_date
FROM fundamentals
WHERE ticker = ?
ORDER BY period_end DESC LIMIT 4
```
With YoY deltas computed inline.

**Earnings calendar.** Next earnings + last 4 from `earnings_calendar`. Warning
banner if `days_until_earnings < 5` and trade is ACTIVE.

**Trade history.** From `screener_watchlist WHERE ticker = ?`. Show all sessions,
not just the current one, so we can see the ticker's behavior over multiple
cycles.

**Feature time series panel.** Current page content (candles + per-feature
subplots). Keep as-is.

#### Acceptance criteria — Page 2

- Diagnostic matrix renders for any ticker in `sepa_watchlist` history.
- Score trajectory chart aligns dates correctly with sepa_watchlist entry/exit
  markers.
- Fundamentals/earnings sections gracefully degrade for tickers with no data
  (e.g., recent IPOs).
- Performance: < 2s to switch tickers on warm cache.

---

### Page 3 — Model Lab

**File:** `scripts/pages/3_Model_Lab.py` (new)

**Goal.** Browse the model registry; click a model → see its full evaluation
artifacts without leaving the browser.

#### Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  MODEL REGISTRY                                                          │
│  [Filter: status ▾ All  |  feature_version ▾ v3.1]                      │
│  ┌─────────────────────────┬─────────┬────────────┬─────┬─────────────┐ │
│  │version_id               │status   │training    │acc  │trained on   │ │
│  ├─────────────────────────┼─────────┼────────────┼─────┼─────────────┤ │
│  │M01_baseline_v0.1         │ ★ prod  │ 2026-04-10 │0.67 │ 38K trades │ │
│  │m01_prototype_2003_2026… │   test  │ 2026-05-06 │0.30 │ 37K trades │ │
│  │m01_v2_binary_20…         │   test  │ 2026-05-30 │0.71 │ 38K trades │ │
│  └─────────────────────────┴─────────┴────────────┴─────┴─────────────┘ │
│                                                                          │
│  Select two models to diff: [model A ▾] [model B ▾]   [Diff →]          │
├─────────────────────────────────────────────────────────────────────────┤
│  Selected: m01_prototype_2003_2026_20260506_160054                      │
│                                                                          │
│  [Tabs: Overview | Plots | Pretrain Report | Specs | Diff vs Prod]      │
│  ──────────────────────────────────────────────────────────────────     │
│  Overview                                                                │
│    Features: 105   |   Hyperparameters: max_depth=4, lr=0.05, …         │
│    Training samples: 31364  |  Val: 5551                                 │
│    Macro F1: 0.288  |  Weighted F1: 0.277  |  Acc: 0.299                │
│                                                                          │
│  Plots tab → embeds the 6 PNGs from evaluation/                          │
│  Pretrain tab → iframes the pretrain HTML report (already built)         │
│  Specs tab → JSON viewer of specs_json from registry                     │
│  Diff tab → renders existing model_diff text or .json                    │
└─────────────────────────────────────────────────────────────────────────┘
```

#### Component-by-component

**Registry table.** `ModelRegistry().list_versions()` returns the dataframe
directly. Display columns: `version_id`, `status_flag`, `training_date`,
`accuracy`, `weighted_f1`, `macro_f1`, `dataset_rows`. **Read-only in v1** —
promotion and archive remain CLI actions (`ModelRegistry().set_prod(...)`),
not UI buttons. Reasoning: mutating prod state from a one-click UI on a
single-user dashboard is a foot-gun with no upside.

**Action buttons per model:**
- "View" → loads the model into the right-hand detail panel.
- ~~Promote / Archive~~ — deferred. CLI-only until we have a backtest-gated
  promotion workflow (see Open Question §6.2).

**Detail tabs:**
- **Overview** — From `specs_json` in the registry row. Shows feature count,
  hyperparameters, training config, eval metrics.
- **Pretrain Report (HTML)** — `st.components.v1.html()` of the
  `docs/reports/pretrain_audit_*.html` file for this model. Self-contained
  (Plotly inlined), produced offline by `scripts/run_pretrain_audit.py`.
  This is the primary chart-rich view.
- **Plots (legacy PNG)** — `st.image()` each PNG from
  `<artifacts_path>/evaluation/`: confusion_matrix, feature_importance,
  roc_curves, pr_curves, calibration_curves, class_distribution. Secondary
  view; renderable when the HTML doesn't exist for older models.
- **Specs** — Pretty-printed JSON of `specs_json`. Useful for debugging feature
  set drift.
- **Diff vs Prod (placeholder)** — v1 shows a "no diff available" message with
  a copy-paste CLI hint: `python scripts/model_diff.py <A> <B>`. Embedding
  `model_diff.py` as a subprocess from Streamlit is brittle (cwd, venv,
  stdout capture); skip it for MVP. Promote to "render pre-generated diff
  if file exists" once `evaluation/diffs/` is reliably populated.

**Pretrain-report linkage.** Today, `scripts/run_pretrain_audit.py` writes one
HTML per audit run with a timestamped filename. Model Lab needs a stable
"which HTML belongs to which model" mapping. **Action:** when training a new
model, the trainer should call `run_pretrain_audit(output_path=...)` with a
deterministic path (e.g., `docs/reports/pretrain_<version_id>.html`) and write
that path into `models.artifacts_path` or a new `pretrain_html_path` column.
Until that wiring exists, Page 3 shows the most recent pretrain HTML by mtime
with a "not version-pinned" badge.

#### Acceptance criteria — Page 3

- Lists all models in registry (read-only — no mutation buttons in v1).
- Pretrain HTML iframe loads in < 1.5s for the standard ~5MB report.
- PNG plots tab loads in < 1s (image cached).
- Diff tab renders the placeholder cleanly when no pre-generated diff exists.

---

### Page 4 — Backtest Studio

**File:** `scripts/pages/4_Backtest_Studio.py` (new)

**Goal.** Browse historical backtest results; rerun with new parameters from
the UI; compare runs.

#### Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  BACKTEST RUNS                                                           │
│  [List of runs: directory name | model_version | start–end | total ret] │
│  ┌─────────────────────────────────┬──────────────┬───────┬───────────┐ │
│  │ case1_prototype_standalone      │m01_prot_2003 │+201.4%│Sharpe 0.79│ │
│  │ case2_prototype_plus_rank       │m01_prot_2003 │ +64.8%│Sharpe 0.39│ │
│  │ 20260210_012608 (legacy)        │m01_baseline  │ +49.5%│Sharpe 0.51│ │
│  └─────────────────────────────────┴──────────────┴───────┴───────────┘ │
│                                                                          │
│  Selected: case1_prototype_standalone                                    │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ EQUITY CURVE vs SPY                                              │   │
│  │ [Plotly line: portfolio NAV + SPY NAV from same period]          │   │
│  ├──────────────────────────────────────────────────────────────────┤   │
│  │ DRAWDOWN                                                          │   │
│  │ [filled area chart, max-DD annotation]                           │   │
│  ├──────────────────────────────────────────────────────────────────┤   │
│  │ PER-YEAR                  PER-REGIME                              │   │
│  │ 2020:+xx% Sharpe x        Strong Bull:n trades, +x%               │   │
│  │ …                          Bull:        n trades, +x%             │   │
│  │ 2024:+xx% Sharpe x        Neutral:    n trades, +x%               │   │
│  │                            Bear:        n trades, +x%             │   │
│  ├──────────────────────────────────────────────────────────────────┤   │
│  │ TRADES (sortable, filterable by sector/regime/outcome)            │   │
│  │ [data table from trades.parquet]                                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  [Compare ▾ select 2nd run]  →  side-by-side metrics & overlaid curves  │
└─────────────────────────────────────────────────────────────────────────┘
```

#### Component-by-component

**Run list.** Scan `data/backtest/*/manifest.json` and **filter to entries with
`"manifest_version": "v1"`**. Stale runs from earlier pipelines (e.g.,
`20260214_174034`, `baseline_2`, `prototype_test_1`) lack that key and are
silently skipped — they remain on disk but invisible to the UI. This is the
"only show output from the current backtest pipeline" rule.

For each surviving run, show:
- Run directory name
- `manifest.json` → `model.name`, `model.version_id`, `params.start_date`,
  `params.end_date`, `params.initial_cash`
- `manifest.json.summary_metrics` (or `metrics.json` if richer) → total return,
  Sharpe, max DD

Sortable by date / Sharpe / return.

**Equity curve.** Load `equity_curve.parquet` → Plotly line chart. Overlay SPY
NAV from `t1_macro.spy_close` indexed at `start_capital` for fair comparison.

**Drawdown.** Computed from the equity curve: `(NAV - cummax(NAV)) / cummax(NAV)`.
Filled area, max DD annotated.

**Per-year breakdown.** From `trades.parquet`: group by year(entry_date),
aggregate. Same table for per-regime (need to join trades to `t2_regime_scores`
on entry date — already done by the Case 1 manifest in some runs; if not,
compute on the fly).

**Trade table.** Load `trades.parquet`, render with column filters. Reuse the
markdown report format columns (Ticker, Entry, Exit, PnL%, Reason, Regime).

**Compare mode.** Pick a 2nd run from the list. Overlay equity curves;
side-by-side metrics table.

**Connection to Model Lab.** Each run links back to its model version (link
opens Page 3 with that model selected). The reverse is also useful: from Model
Lab, a "Backtests" link that filters Page 4 to runs using this model.

#### Acceptance criteria — Page 4

- Lists every run with `manifest_version == 'v1'`; pre-v1 runs are filtered
  out (visible only via the on-disk archive).
- Loads case1/case2 cleanly (re-run with the new schema as part of §3.2).
- Comparison overlay works for any 2 runs, even if they span different date
  ranges (axis aligns on portfolio-relative time, not absolute date — toggleable).
- Trade filter doesn't crash on missing columns (e.g., legacy runs without
  `regime` column).

---

### Page 5 — Pipeline Health

**File:** `scripts/pages/5_Pipeline_Health.py` (new)

**Goal.** Weekly / daily ops check; spot drift, freshness issues, audit drift
before they propagate.

#### Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PIPELINE RUNS — last 30 days                                            │
│  [RAG-colored heatmap: phase × date]                                     │
│  Phase 1 Price       🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢…                            │
│  Phase 2 Screener    🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢…                            │
│  Phase 3 T2          🟢🟢🟡🟢🟢🟢🟢🟢🟢🟢🟢🟢…                            │
│  …                                                                       │
│  [Click a cell → drill into pipeline_runs row + log snippet]            │
├─────────────────────────────────────────────────────────────────────────┤
│  DATA FRESHNESS                                                          │
│  Table             Max date       Lag (days)       Status               │
│  price_data        2026-05-22     1                🟢                    │
│  fundamentals      2026-03-31     52               🟢 (quarterly)       │
│  t3_sepa_features  2026-05-22     1                🟢                    │
│  …                                                                       │
├─────────────────────────────────────────────────────────────────────────┤
│  UNIVERSE & BREAKOUT TIMESERIES (60d trailing)                           │
│  [line chart: daily count of trend_ok, breakout_ok, active SEPA]        │
├─────────────────────────────────────────────────────────────────────────┤
│  AUDIT HISTORY (last 30 days)                                            │
│  [line chart: FAIL/WARN/PASS counts per audit_report_YYYYMMDD.json]     │
│  Latest report: audit_report_2026-05-22.json  →  [view raw JSON]        │
├─────────────────────────────────────────────────────────────────────────┤
│  STORAGE                                                                 │
│  market_data.duckdb: 4.2 GB  (growth: +120MB/wk)                        │
│  models/: 850 MB (12 versions)   data/backtest/: 280 MB (38 runs)       │
└─────────────────────────────────────────────────────────────────────────┘
```

#### Component-by-component

**Pipeline runs heatmap.** `pipeline_runs` last 30 days, pivot date × phase,
color by status. Click → expand row with runtime, error message if any.

**Data freshness.** `SELECT table_name, MAX(date) ...` for each key table.
Configurable lag tolerance per table (price_data: ≤2d, fundamentals: ≤90d,
audit JSON: ≤7d).

**Universe / breakout trend.** From `t2_screener_features`:
```sql
SELECT date,
       COUNT(*) FILTER (WHERE trend_ok)                AS trend_ok_n,
       COUNT(*) FILTER (WHERE trend_ok AND breakout_ok) AS breakout_n
FROM t2_screener_features
WHERE date >= CURRENT_DATE - INTERVAL 60 DAY
GROUP BY date
ORDER BY date
```

**Audit history.** Scan `data/audit_reports/audit_report_*.json` files.
For each, extract `summary.fail_count`, `warn_count`, `pass_count`. Plot trend.

**Bootstrap state:** today there is exactly one file
(`audit_report_20260328.json`). Page 5 shows a single point on the line chart
with a "history accumulating — 1 data point" badge. The line will populate
naturally once the daily orchestrator starts writing audit JSONs (see §3.4).
Do not generate synthetic backfill.

**Storage.** OS-level filesize check on key directories. Trended over time if a
log is kept (small TODO: log to `pipeline_runs` extension or a tiny stats file).

#### Acceptance criteria — Page 5

- Heatmap loads for any 30-day window with no errors when some phases are
  missing (e.g., the day Phase 4b was added).
- Audit history page survives if `data/audit_reports/` is empty (warning state).

---

## 3. New data layer items (the only infra work)

### 3.1 `dashboard_snapshot` table — required for Page 1

Page 1's pre-breakout cohort runs M01 `predict_proba` on 30-80 tickers; doing
that in the request path is too slow for a "warm cache" target. Build this
during Phase 1 (not deferred):

```sql
CREATE TABLE dashboard_snapshot (
  date           DATE,
  cohort         VARCHAR,   -- 'active' | 'pre_breakout' | 'sector_heat'
  payload        JSON,      -- pre-rendered table rows
  created_at     TIMESTAMP
);
```

Refreshed at the end of Phase 8 (monitoring). Page 1 reads the latest row per
cohort; falls back to live scoring with a "live scoring (slow)" badge if the
snapshot is missing or > 1 day stale.

### 3.2 Backtest manifest enrichment — ✅ DONE

[src/backtest/runner.py](../../src/backtest/runner.py) now writes:
```json
{
  "manifest_version": "v1",
  "run_id": "case1_prototype_standalone",
  "created_at": "...",
  "model": {
    "name": "m01_prototype_2003_2026",
    "version_id": "m01_prototype_2003_2026/v1",
    "path": "models/m01_prototype_2003_2026/v1/model.json"
  },
  "params": { ... },
  "summary_metrics": { ... }
}
```

`model.version_id` is resolved via `_lookup_model_version_id` — matches the
`models.artifacts_path` column when a registry row exists; falls back to
`<name>/<version-dir>` otherwise (with a log line). Case scripts pass
`--model` through to `SEPABacktestRunner(model_path=...)`. case1/case2
manifests regenerated post-edit.

Page 4 filters runs to `manifest_version == 'v1'` (see §Page 4 / "Run list").

### 3.3 ~~Verify `t2_risk_scores` wiring~~ — ✅ ALREADY WIRED

`RiskFiveFactorCalculator` is imported and instantiated at
[src/orchestrators/daily_pipeline_orchestrator.py:25,93](../../src/orchestrators/daily_pipeline_orchestrator.py#L25).
Phase-0 action shrinks to: tail the latest daily-pipeline run and confirm a
fresh row appeared in `t2_risk_scores`. If not, debug the existing call site
rather than adding a new phase.

### 3.4 Daily audit-report write — new Phase-9 hook

`data/audit_reports/` has one historical file. To make Page 5's audit-history
line chart populate over time, add to the daily orchestrator's monitoring
phase: invoke `tools/run_all_audits.py` (or whichever script produces the
canonical audit JSON) and write `audit_report_YYYYMMDD.json` to
`data/audit_reports/`. **Effort: 0.5 day** (mostly: confirm the audit script
runs idempotently and emits the expected schema).

---

## 4. Build sequence

Sized to be shippable in ~2 weeks for a single dev, in this order:

| Phase | Days | Deliverable | Unblocks |
|---|---|---|---|
| **0. Audit + verify** | 0.5 | ✅ Manifest enrichment in `runner.py` done; verify `t2_risk_scores` freshness end-to-end; add Phase-9 audit-write hook (§3.4) | All later phases |
| **1. Page 1 (Today) enhancements** | 2.5 | 5F card + default sort by P(HR) + pre-breakout watch table + sector heat + `dashboard_snapshot` table (§3.1) | First user-visible win |
| **2. Page 3 (Model Lab)** | 1.5 | Registry list (read-only) + pretrain HTML iframe + PNG fallback + specs tab + placeholder diff | Enables S1 modelling sprint (whitepaper §2.4) |
| **3. Page 4 (Backtest Studio)** | 2.5 | Run list (filtered by `manifest_version=v1`) + equity/DD + per-year/per-regime + trade table + compare | Enables walk-forward CV reporting (whitepaper §5.1) |
| **4. Page 5 (Pipeline Health)** | 1.5 | Heatmap + freshness + universe trend + audit history (single-point initially) | Ops confidence going forward |
| **5. Page 2 (Ticker Deep Dive)** | 3 | Diagnostic matrix + score trajectory + fundamentals + earnings + trade history (price chart already done) | Highest single-name research utility |
| **6. Polish** | 1 | Cross-page links, `st.session_state` for filters, rename `1_Feature_Time_Series.py`, performance pass | — |
| **Total** | **12.5 days** | — | — |

Pages 1 + 3 can be built in parallel (3 unblocks the modelling sprint, so it
moves ahead of Page 5). Pages 4 + 5 + 2 follow. **Realistic 2-week sprint** with
one developer. Page 3 is smaller than originally scoped because the static-HTML
approach eliminates per-tab chart wiring.

---

## 5. Streamlit architecture notes

- Multipage navigation already wired via `st.navigation([...])` in
  `dashboard.py:472-476`. New pages drop into `scripts/pages/` and auto-mount.
- Shared utilities go into a new `scripts/dashboard_utils.py`:
  - DB connection pool / cached loaders
  - Class-label / color constants (currently duplicated)
  - Regime / 5F label helpers
  - Page-1 snapshot loaders
- `@st.cache_data(ttl=300)` everywhere on read paths. Reset by clicking the
  reload icon — sufficient for daily-cadence use.
- `@st.cache_resource` for model loading (already used).
- Auth: none. localhost-only. Add an explicit comment at the top of `dashboard.py`
  warning against `--server.address 0.0.0.0`.

---

## 6. Open questions

1. Should the 5F card show **target_exposure** alone or also expose the per-
   factor z-scores by default? Recommend: show `target_exposure` + worst-factor
   by default, with an expander for full z-score breakdown.
2. ~~Promote to prod gating~~ — **Resolved:** removed from UI entirely in v1.
   Promotion remains a CLI action until a backtest-gated workflow exists.
3. Do we want a "paper-trade log" feature on Page 1 (manual toggle per
   candidate: "taken / skipped / pending"), or is that a separate sprint?
   Recommend: separate sprint — whitepaper §6 item #11. Adds a small new table.
4. Page 4 currently scans `data/backtest/*/manifest.json` on every load — do we
   want a `backtest_runs` table? Recommend: defer until we have > 100 runs;
   filesystem scan is fine until then. (Filter by `manifest_version == 'v1'`
   keeps the scan cheap.)
5. Pretrain HTML versioning — should the trainer always write
   `docs/reports/pretrain_<version_id>.html` so Page 3 can pin per-model
   reports? Recommend: yes, but defer the trainer change until Page 3 is built
   and we've confirmed the iframe approach is what we want.

---

## Appendix A — File diff summary

```
scripts/
├── dashboard.py                  # MODIFIED — split into Page 1 + entry navigation
├── dashboard_utils.py            # NEW — shared loaders & constants
└── pages/
    ├── 1_Today.py                # MOVED from dashboard.py (page 1 content)
    ├── 2_Ticker_Deep_Dive.py     # RENAMED from 1_Feature_Time_Series.py, EXTENDED
    ├── 3_Model_Lab.py            # NEW
    ├── 4_Backtest_Studio.py      # NEW
    └── 5_Pipeline_Health.py      # NEW

src/backtest/
└── runner.py                     # MODIFIED — manifest enrichment (§3.2)

src/orchestrators/
└── daily_pipeline_orchestrator.py # MODIFIED — add Phase 4c if 5F not wired (§3.3)
```

No new dependencies (all already in `requirements.txt`: streamlit, plotly,
duckdb, xgboost, pandas, numpy). No schema changes required for the dashboard
itself (only the optional `dashboard_snapshot` deferred until needed).
