# Dashboard Module Passport

> Rewritten 2026-07-16. The prior version described a pre-DuckDB SQLite
> `buy_list` app (`src/dashboard_reports.py`, `M03RegimeCalculator`,
> `config.POSITION_SIZE_PCT`) that no longer exists. This reflects the current
> Streamlit multi-page app on the slim DuckDB + R2 sync.

## 1. Overview
The **Quantamental Dashboard** is a read-only Streamlit app — the daily control
surface for the system. It never scores live and never writes market data: it
renders what the nightly pipeline already materialized (`daily_predictions`,
`weather_gauge`, `v_d3_*` deployment views, watchlists). The one write path is
the decision log (`update_decision_taken` → `daily_predictions.decision_taken`),
a small paper-trade annotation.

Two run contexts, same code:
- **Local** — reads the full `data/market_data.duckdb` (or a slim DB via
  `DASHBOARD_DB_PATH`), localhost-only, no auth.
- **Streamlit Cloud** — reads a slim `dashboard.duckdb` pulled from Cloudflare
  R2; viewer allowlist by Google email; R2 creds + `DASHBOARD_DB_PATH` set as
  Streamlit secrets.

## 2. Structure

| File | Role |
|------|------|
| `scripts/dashboard.py` | **Entry point + "Today" page.** `streamlit run scripts/dashboard.py`. Registers pages via `st.navigation`; `page_today()` renders the whole landing page (weather gauge → macro → shortlist → VIP → watchlist → activity → pre-breakout → decision log → rank bump → cohort returns → sector heat → analytics). |
| `scripts/dashboard_utils.py` | **Data + infra layer.** All `load_*` loaders (each `@st.cache_data`), the DB path resolution, `_connect(read_only=True)`, and the R2 sync (`_ensure_local_db`, `_maybe_refresh_from_r2`, `_ensure_asset_dirs`). Pages stay render-only; every DB read routes through here. |
| `scripts/pages/1_Dataset_EDA.py` | Embeds the latest `docs/reports/pretrain_audit_*.html`. |
| `scripts/pages/3_Model_Lab.py` | Model-registry browser; embeds the model card HTML (+ PNG fallback). Read-only — promotion stays a CLI action (`ModelRegistry().set_prod`). |
| `scripts/pages/4_Backtest_Studio.py` | Browses current-pipeline backtest runs (only `manifest_version: v1`). |
| `scripts/pages/5_Pipeline_Health.py` | Ops view: run heatmap, data freshness, universe trend, audit history, R2 asset-pull diagnostics. |
| `scripts/build_dashboard_db.py` | **Slim-DB builder.** CTAS a thin slice of the 67 GB full DB into `data/dashboard.duckdb` (~800 MB). Run nightly; output uploaded to R2. |

## 3. Data dependency

> Audited table-by-table row counts + the full list of full-only objects
> (read by nothing) live in
> [docs/architecture/local_vs_remote_db.md](../architecture/local_vs_remote_db.md) —
> the parity ledger. This section is the how-it-works narrative.

### 3.1 The slim-DB contract (single source of layout truth)
`build_dashboard_db.py` ATTACHes the full DB read-only and CTAS-copies each
`MANIFEST` entry into a fresh `dashboard.duckdb`. Modes:

| Mode | What it keeps | Used for |
|------|---------------|----------|
| `full` | whole table | small tables: watchlists, `daily_predictions`, `weather_gauge`, `models`, macro, registry |
| `window` | last `--window-days` (default 252) of `MAX(date)` | big feature tables `t2_screener_features`, `t3_sepa_features`, `price_data` |
| `window_plus_active` | window **+** all rows for currently-ACTIVE tickers | available (not currently used) for deep per-ticker history |
| `materialize_view` | `SELECT *` snapshot of a view into a table | `v_d3_deployment`, `v_d3_prebreakout`, `v_d3_shortlist`, `v_d3_vip` |

**Hard invariant (build fails otherwise):** every `MANIFEST` object must exist
as a table in the slim DB. The remote DB is a byte-copy of this file, so this
one assert is what guarantees *remote layout == local layout* — a table read
by any loader that isn't in the manifest works locally but throws on the
remote. **Adding a loader that reads a new table/view ⇒ add it to `MANIFEST`.**
(cf. memory `project_dashboard_remote_parity`.)

### 3.2 Loader → source map (what "Today" reads)

| Loader (`dashboard_utils`) | Reads | Feeds |
|---|---|---|
| `load_weather_gauge` | `weather_gauge` | deploy-posture headline + history strip |
| `load_macro_pillars` | `macro_data` | 6-pillar percentiles + trends |
| `load_shortlist` | `v_d3_shortlist` | daily tail-edge shortlist |
| `load_vip_watchlist` | `v_d3_vip` | manually-curated names + status |
| `load_scored_watchlist` / `load_watchlist` | `screener_watchlist` ⋈ `daily_predictions` | active/exited trades table |
| `load_scored_pre_breakout` | `v_d3_prebreakout` ⋈ `daily_predictions` | pre-breakout watch |
| `load_recent_exits` / `load_activity_feed` | `screener_watchlist`, `screener_membership` | exits + universe add/remove feed |
| `load_daily_predictions_today` / `load_past_decisions` / `update_decision_taken` | `daily_predictions` | decision log (**only write path**) |
| `load_rank_cohorts` / `load_rank_history` / `load_cohort_return_panel` | `daily_predictions` (+ `price_data` for returns) | rank-bump + cohort-return charts |
| `load_sector_heat` | `t2_screener_features` / deployment view | sector setup counts |
| `load_prod_model_version_id` | `models` | resolves prod model (binary → `prob_class_1`, 4-class → `prob_class_3`) |

### 3.3 R2 sync (cloud only)
- Nightly: `build_dashboard_db.py` → upload `dashboard.duckdb` to `latest/` on R2.
- App boot pulls it; `_connect()` re-checks the R2 **ETag** (content hash, not
  size — size matched spuriously) at most every 120s and re-pulls atomically
  (temp + rename) when it changed. The 300s query cache then surfaces new data
  within ~5 min without a container reboot.
- Disk-file asset dirs (`model_cards`, `audit_reports`, `docs/reports`,
  `models`) pull separately via `_ensure_asset_dirs`, best-effort, 23h-gated;
  failures degrade to "not available", never block the app.

## 4. Design rules
- **Read-only everywhere.** `_connect()` defaults `read_only=True`; the app
  never scores live (all scores are pre-materialized in `daily_predictions`).
  Only the decision log writes. (cf. `feedback_readonly_connections`.)
- **Configurable DB path.** `DASHBOARD_DB_PATH` (absolute or repo-relative)
  points the same code at full-local or slim-remote; unset ⇒ full local DB.
- **Caching:** loaders use `@st.cache_data` (query cache); the R2 recheck
  throttle is a module global that survives Streamlit reruns.
- **Filters in `st.form`** on the heavy tables (watchlist, rank bump, cohort
  returns) so the whole-page rerun fires on *Apply*, not per keystroke.
- **Honest labels in the UI, not just docs:** captions state the caveats the
  research earned — shortlist is *tail-odds, the median inverts*; SPY-200d is
  the brake; `stress_z` is provisional; scores are P(Home Run), materialized
  nightly, blank when a session predates the scored window.
- **Prod-model agnostic:** the score column is resolved from the registered
  prod model id (`_rank_metric_for`), so binary vs 4-class doesn't fork the UI.

## 5. Run
```bash
# local (full DB)
streamlit run scripts/dashboard.py
# local against the slim DB
DASHBOARD_DB_PATH=data/dashboard.duckdb streamlit run scripts/dashboard.py
# rebuild the slim DB (nightly; then upload to R2)
python scripts/build_dashboard_db.py --window-days 252
```
