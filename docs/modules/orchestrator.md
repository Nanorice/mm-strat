# Module: Daily Pipeline Orchestrator (`src/orchestrators/`)

> Verified against code 2026-07-18. `DailyPipelineOrchestrator` sequences the daily
> phases; `phase_registry.py` owns phase identity. The orchestrator delegates all
> business logic to engines/pipelines/managers — it only handles ordering, failure
> modes, idempotency, and telemetry. CLI: `scripts/run_daily_pipeline.py`.

## Phase registry (`phase_registry.py`) — single source of truth

Each phase has a **stable id** (persisted in `pipeline_runs.phase_name`, never
renumbered), a display label, and a float `order` (inserting a step changes only
`order`). Failure modes come from `config.PIPELINE_FAILURE_MODES` (HALT/WARN/SKIP;
unknown ids default to HALT, fail-safe).

| order | id | label | What runs |
|---|---|---|---|
| 1.0 | `ingestion` | Ingestion | T1 sub-phases: price (`DataRepository.update_cache`, stale tickers only), fundamentals, shares, macro (+ **interior-gap self-heal**, see below), EDGAR CIK-map refresh (weekly) + filing-date backfill (200/run) |
| — | *(gate)* | Price Quality Gate (Phase 1.5) | Coverage of *today's* prices vs active tickers; below retry threshold → targeted same-run re-ingest; never halts |
| — | *(gate)* | Plausibility Gate (Phase 1.6) | FAIL-level ceilings from `config.T1_PLAUSIBILITY_BOUNDS` (absurd shares/close/market-cap, corrupt OHLC). Non-halting, but a red gate **withholds the R2 publish** |
| 2.0 | `screener_membership` | Screener | `ScreenerManager.evaluate_and_log(date)` |
| 3.0 | `t2_screener` | T2 Features | `FeaturePipeline` incremental; <99% coverage → full-date recompute |
| 4.0 | `t2_regime` | T2 Regime | `RegimePipeline.update_incremental()` |
| 4.5 | `sepa_watchlist` | SEPA Watchlist | `SepaWatchlistManager.update_daily(date)` — after T2, before T3. Appends today's events only; a **status-vocabulary canary** warns on retired statuses (see below) |
| 5.0 | `t3_features` | T3 Features | `FeaturePipeline` incremental; missing-breakout-ticker check → rerun date |
| 6.0 | `views` | Views | `ViewManager.create_all()` (views only — nothing materialised since the 2026-07-18 watchlist merge) |
| 7.0 | `cache` | Training Cache | `ViewManager.refresh_cache()` → `d2_training_cache` |
| 7.4 | `scoring` | Scoring | Prod model scores → `daily_predictions` (breakout + pre-breakout cohorts), then the **shadow pass**: shadow model scored on the same candidates, divergence → `shadow_divergence`. Dashboard always reads these materialized scores, never scores live |
| 7.45 | `weather` | Weather Gauge | `WeatherEngine.refresh()` → `weather_gauge` (full recompute) |
| 7.46 | `sector_breadth` | Sector Breadth | `SectorBreadthEngine.refresh()` → `sector_breadth` |
| 7.47 | `portfolio_nav` | Portfolio NAV | `PortfolioManager.snapshot_nav(date)` → `nav_history` (idempotent per date; missed nights are permanent holes) |
| 7.5 | `dashboard_db` | Dashboard DB | subprocess `scripts/build_dashboard_db.py` → `data/dashboard.duckdb` (slim replica) |
| 7.6 | `r2_sync` | R2 Sync | subprocess `scripts/sync_dashboard_db.py` → Cloudflare R2 `latest/`. Skipped with a loud warning if `R2_ACCOUNT_ID` unset; **withheld if the plausibility gate is red** (stale-but-clean beats fresh-but-dirty) |
| 8.0 | `monitoring` | Monitoring | Always runs. Reads `run_stats` + table state → structured alerts (breakout drought, runtime >3× rolling average, T2/T3 coverage gaps, recent failures, missing NAV mark, **prod-model identity**) |
| 10.0 | `model_card` | Model Card | Advisory weekly **drift card** for the prod model: trailing 1-year window, registered to `model_card_drift_path` (never overwrites the promotion-gate card). Skips if <7 days old. "Phase 10" is a cosmetic label artifact — there is no Phase 9 |

Everything from 7.4 on is best-effort: failures WARN and never halt the run.
Phases 7.4–7.47 deliberately run **before** 7.5 so their tables ship in the slim DB.

## Execution semantics

- `run_pipeline(target_date=None, phase_N_only=..., universe_refresh=False)`.
  Default target = latest completed US trading day (`get_latest_trading_day()`).
- Idempotency via `PipelineRunManager.is_phase_completed()`; `--force` overrides.
  Incremental phases (3/5) skip the check and self-detect gaps instead.
- A HALT-phase failure aborts the run (`critical_success=False`); WARN/SKIP are
  absorbed.
- `universe_refresh=True` runs quarterly new-listing discovery before Phase 1 —
  never automatic.
- Per-phase peak-RSS telemetry via a background `_MemorySampler` (sums child
  processes — the dashboard build and model card run as subprocesses).

## Scheduling (Prefect, sh019 ops box)

Self-hosted Prefect 3.x owns only the outer ring — cron `0 22 * * 1-5`
Europe/London, crash-level retry, run history, UI (http://127.0.0.1:4200). The
flow (`flows/daily_pipeline_flow.py`) shells out to the CLI, so there is exactly
one execution path; no per-phase Prefect tasks. Schedule source of truth is
`CRON` in the flow file (UI edits are transient). Launchers:
`scripts/start_prefect_server.ps1`, `start_prefect_serve.ps1`,
`register_prefect_tasks.ps1`. Runbook:
`docs/session_logs/sprint_12/s4_prefect_orchestration_runbook.md`.

## CLI

```bash
python scripts/run_daily_pipeline.py                  # full run, latest trading day
python scripts/run_daily_pipeline.py --date 2026-07-17
python scripts/run_daily_pipeline.py --phase-3-only   # also: 1/2/4/5
python scripts/run_daily_pipeline.py --force --dry-run
```

### t1_macro interior-gap self-heal (Phase 1)

`_heal_t1_macro_gaps()` — `ingest_daily_macro(start_date=trading_day)` writes **only
that one date**, and the incremental path resumes from `MAX(date)`, so a date missed
during an outage is never revisited. Five June-2026 holes had persisted this way
(the "standing FAILs" in the sprint README) and would never have closed on their own.

Heals from **local data**: SPY/QQQ OHLCV from `price_data`, VIX from `macro_data` —
every `t1_macro` column is derivable, so there is no network call and therefore no
rate-limited silent-failure path. `INSERT … SELECT` with a `NOT EXISTS` guard: it only
ever fills absent dates, never overwrites a populated row. Bounded by
`T1_MACRO_HEAL_LOOKBACK_DAYS` (120) so it doesn't rescan 26 years nightly.

⚠️ `scripts/backfill_t1_macro.py` is **not** a reliable repair for this — it refetches
from yfinance and prints `[OK] Done … Rows written: 0` on a rate-limit, i.e. failure
shaped exactly like success. Prefer the self-heal.

⚠️ `macro_data` stores market quotes in `close` and FRED series in `value`. VIX is a
quote, so `value` is NULL — reading it writes NULL `vix_close`. Covered by
`test_vix_read_from_close_not_value`. Tests: `tests/test_t1_macro_gap_heal.py`.

### Watchlist status canary (Phase 4b)

`_check_watchlist_status_vocab()` — warns when `sepa_watchlist.status` holds anything
outside `{ACTIVE, EXITED}`. Phase 4b **only appends** today's session events, so unlike
T2/T3 (which have `_t2_coverage_deficit` / `_t3_holed_dates`) nothing ever re-examines
watchlist *history*. A box migrated from the pre-2026-07-18 schema keeps stale
`COOLDOWN` rows indefinitely — nothing promotes them.

Asymmetry worth remembering: the `screener_watchlist` **VIEW** self-heals every night
(`_create_screener_watchlist_view` drops a leftover `BASE TABLE` and recreates the view,
verified idempotent), but the `sepa_watchlist` **source table** does not.

Detection only. The repair — `scripts/backfill_sepa_watchlist.py` — is an authoritative
full-history DROP+rebuild, far too destructive to fire off a canary.
Tests: `tests/test_watchlist_status_canary.py`.

### Prod-model identity alert (Phase 8)

`_check_prod_model_identity()` — which model is `prod` is **per-box registry state**,
so a box that never re-promoted keeps scoring an old model silently (Phase 7.4 logs
"no prod model registered" at INFO and returns 0). That yields *wrong live output*,
not merely missing data — the failure mode that left `sh019` scoring 4-class while the
research box scored binary. Three alerts:

- **no prod model registered** — `daily_predictions` is not advancing on this box.
- **>1 model flagged `prod`** — scoring picks one arbitrarily; demote all but one.
- **prod model changed** vs. the model that scored the latest `prediction_date`.
  Expected after a promotion, so it WARNs rather than gating, and goes quiet once the
  new model has scored a day (compares against the latest date, not "any other model").

Prior identity comes from `daily_predictions.model_version_id` — already persisted per
row, so the check needs no new state. Tests: `tests/test_prod_model_identity_alert.py`.

## Related

- Audits (Phase 8 fires them; **6** JSON audits → `data/audit_reports/*.json`):
  `tools/run_all_audits.py`, runbook in [manual_for_me.md](../architecture/manual_for_me.md).
  `audit_date_coverage.py` (added 2026-07-19) generalises the per-phase gap detectors:
  it asks every daily panel whether any trading day is missing between its own first
  and last row. Tolerance 0, measured over full history. Skip key: `coverage`.
- Slim DB / R2 parity contract: [local_vs_remote_db.md](../architecture/local_vs_remote_db.md)
- 🛑 R2 data flow is ONE-WAY (local→slim→R2→viewer). Never point
  `DASHBOARD_DB_PATH` at `market_data.duckdb`; pulls require `DASHBOARD_PULL_FROM_R2=1`.
