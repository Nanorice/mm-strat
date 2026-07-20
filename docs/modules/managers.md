# Module: Managers (`src/managers/`) — state & lifecycle

> Verified against code 2026-07-18. Managers own DB state transitions: universe
> membership, SEPA sessions, SQL views, run tracking, the real-money book, and the
> VIP list. No external I/O (engines) and no feature math (pipelines).

## 1. ScreenerManager (`screener_manager.py`) — Phase 2

`screener_membership` is an **append-only event log**: one row per status change
per ticker (`is_member` TRUE=entry / FALSE=exit), implemented with a
gaps-and-islands window pattern — no per-ticker Python loop.

- **Criteria v2** (effective 2020-01-01): `close >= $5`, `avg_volume_20d >= 100K`,
  `market_cap >= $150M`. Parameter history in `screener_criteria_versions`
  (`version_id`, `min_price`, `min_volume_20d`, `min_market_cap`, `effective_date`);
  version 0 is the ETF/INDEX bypass row (no filters).
- **Grace period**: `_GRACE_DAYS = 126` consecutive failing days before an exit
  event; `consec_fail_days` is exactly 126 on exit rows, 0 on entries.
- API: `backfill_all(start, end)` (vectorised full rebuild), `evaluate_and_log(date)`
  (daily), `auto_enroll_non_equity()`, `get_active_tickers(as_of)`, `get_membership_stats()`.

## 2. SepaWatchlistManager (`sepa_watchlist_manager.py`) — Phase 4b

`sepa_watchlist` is the **single session store** (2026-07-18 merge) and the T3
universe gate. One row per SEPA session (~39K sessions, ~2.7K tickers, 8 cols).
Name caveat: it is *not* a watchlist — it stores trade sessions
(see [glossary.md](../architecture/glossary.md) §1).

- **Entry**: first day with `trend_ok AND breakout_ok` and no open session.
- **Exit**: close < SMA50 OR SMA150 OR SMA200 — **C1+C2+C6 only**, not full
  `trend_ok` (full-template exits fragment one long session via C9 RS flicker).
- **No cool-down** (removed 2026-07-18): a re-trigger the day after an exit is a
  new session. `status` is only `ACTIVE`/`EXITED`; the `COOLDOWN` state and
  `cooldown_end` column are gone. Where episode-dedup matters, derive
  `is_retrigger` at read time via `LAG(exit_date)` ≤ 14d.
- Delisted tickers are kept — the store matches the training grain.
- API: `backfill()` (authoritative vectorised rebuild), `update_daily(date)`,
  `get_universe()`, `get_stats()`.

## 3. ViewManager (`view_manager.py`) — Phase 6

`create_all()` (re)creates the serving-layer views. `screener_watchlist` is a
**VIEW** over `sepa_watchlist` since 2026-07-18 (company info + realized returns;
Phase 6 no longer materialises any table). Current chain:

| View | Row represents | Consumers |
|---|---|---|
| `v_price_combined` / `v_shares_combined` | union of prod + backfill tables | internal |
| `v_sepa_candidates` | 1 day/ticker while in trend | diagnostics |
| `v_d1_candidates` | 1 trade (session) | v_d2_* |
| `v_d2_features` | 1 trade + fundamentals (query-time LEFT JOIN) | training/deployment |
| `v_d2_hydrated` | N days/trade (entry→exit) | v_d2_training |
| `v_d2_training` | 1 trade + MFE/MAE outcomes | trainer, `d2_training_cache` |
| `v_d3_deployment` | last 252d of SEPA candidates | scoring |
| `v_d3_prebreakout` | trend-ok, not-yet-broken-out cohort | scoring (pre-breakout cohort) |
| `screener_watchlist` | 1 session, display columns | dashboard, joins to outcomes |
| `v_d3_lifecycle` | one-pass MECE scoring cohorts (pre_breakout / active / removed) | dashboard Screening |
| `v_d3_shortlist` | shortlist for the weather gauge | Phase 7.45, dashboard |
| `v_d3_vip` | VIP list ⋈ lifecycle cohort | dashboard |
| `v_d3_screening` | `trend_ok` (∪ active VIP) ⋈ predictions ⋈ fundamentals, latest day; carries `stage` + "in play since" anchors | dashboard Screening |
| `v_t3_training` | dense T3 training view | `refresh_t3_training_cache()` (weekly, on demand — its ASOF joins cost ~215s; the cache table may be absent locally) |

Also: `refresh_cache()` materialises `d2_training_cache` (Phase 7, 200 cols);
`COLUMN_CASE_MAP` bridges lowercase DB names → TitleCase legacy feature names.
Retired views (`v_d1_trades`, `v_d2r_hydrated`) are explicitly dropped on each run.

⚠️ `trend_c8` CTE inside the view SQL computes C1+C2+C6 (exit criteria), not C1–C8
— known misnomer, glossary verdict RENAME.

### `v_d3_screening.stage` (corrected 2026-07-20)

Population is `trend_ok`, with **active VIP names as the sole exception** (they render
`watchlist` so a curated name stays visible while it ripens). `stage` keys off the
**open session**, not the same-day `breakout_ok` flag:

| stage | Predicate | 2026-07-17 |
|---|---|---|
| `triggered` | open `sepa_watchlist` session | 440 |
| `setup` | `trend_ok`, no open session | 190 |
| `watchlist` | active VIP, ¬`trend_ok` | 2 |

🛑 `breakout_ok` is a one-**day** event flag; the stage is a state. The previous
`CASE WHEN breakout_ok` labelled 403 of 630 rows `setup` that had broken out
days-to-months earlier and were still in an open session. The session is the
persistent record of "has broken out" — use it. See glossary §2 · Screening stages.

Two earlier corrections on this view, both still live: the population is `trend_ok`,
**not** `trend_ok ∨ breakout_ok` (the SEPA gate is AND — the OR admitted breakouts
failing C1–C9, 42 of 79 "triggered" rows on 2026-07-17); and `sess_px` is an INNER
join so `entry_date`/`entry_close` are never split across sources.

## 4. PipelineRunManager (`pipeline_run_manager.py`)

Phase execution tracking + idempotency over `pipeline_runs`, keyed by the **stable
phase ids** from `phase_registry.py`. API: `start_phase`/`complete_phase`,
`is_phase_completed(date, phase)` (the idempotency guard), `record_write` (table
write bookkeeping → `table_write_log`), `record_errors`/`classify_error`
(→ `pipeline_error_log`), `get_health_report(date)`, `get_phase_metrics`.

## 5. PortfolioManager (`portfolio_manager.py`) — the book of record

Append-only fill log of **real, hand-entered trades**. `trades` (one row per fill,
never UPDATEd — corrections are offsetting fills) + `cash_flows` (external money).
Positions, cash, and NAV are **derived**, never stored:
`nav = cash + Σ(qty × close)`. `returns()` is **time-weighted** (a deposit is not
a profit). `snapshot_nav(as_of)` writes one `nav_history` row — run nightly as
orchestrator Phase 7.47 and **cannot be honestly backfilled** (TWR needs the day's
net_flow on the day; a missed night is a permanent hole).

## 6. VipWatchlistManager (`vip_watchlist_manager.py`)

Minimal CRUD over `vip_watchlist` (hand-picked tickers + comment/source);
surfaced via `v_d3_vip`. CLI: `scripts/vip_add.py`.

## Related

- Phase order & failure modes: [orchestrator.md](orchestrator.md)
- Table inventory: [db_schema.md](../architecture/db_schema.md)
