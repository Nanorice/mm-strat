# Session Handover: 2026-07-18 (session 10) — DB restored (partial) · watchlist merge SHIPPED

## 🎯 Goal
Verify session 09's tier-0 incident handover, restore the main DB, and unify the two
session stores (`sepa_watchlist` / `screener_watchlist`) with an agreed cool-down treatment.

## ✅ Accomplished
1. **Incident handover independently verified** — barriers in code, 7/7 guard tests pass,
   ETag forensics confirmed (`market_data.r2etag` == `dashboard.r2etag`).
2. **DB restored — but it's a 2026-06-21 10:40 mid-run snapshot** (78 GB, last
   `pipeline_runs` row `t3_features` stuck 'running'). Full delta vs the pre-destruction
   `db_schema.md` mapped into four buckets: pipeline-backfill / rebuild-from-disk /
   re-derive / lost (see 🚧).
   **Correction**: real DB = **9,184 distinct dates (1990-01-02→)**, not the handover's
   "≈5,800 / 23yr" estimate — memory fixed so a good copy isn't distrusted.
3. **User rules locked**: recovery is **FORWARD-only** — no slim→local copy ever, even
   for restore (one-way protocol is absolute). Pipeline should detect/heal gaps itself.
4. **Reconciliation (read-only, licensed the merge)**: no-cool-down sepa candidates
   (38,759) = screener population (38,467) + 292 delisted sessions, **exact
   (ticker, entry_date) match, zero residual** — only two real axes ever differed:
   the 14-day cool-down (−2,955) and an `is_active` survivorship filter (−292).
5. **Watchlist merge SHIPPED**:
   - `sepa_watchlist` = SINGLE session store; cool-down demoted from write-time gate to
     read-time flag (`is_retrigger` via LAG ≤ 14d); statuses ACTIVE/EXITED only;
     `cooldown_end` column deleted.
   - `screener_watchlist` = **VIEW** over it (14-column parity, name kept → zero changes
     in dashboard loaders, `v_d3_lifecycle` wl CTE, `build_dashboard_db` MANIFEST).
     Delisted tickers kept; stale-price guard stops eternal-ACTIVE for delisted opens.
   - `v_d1_candidates` lost its `is_active` filter → **survivorship fix in the training
     population** (+292 mostly-failure sessions on next cache refresh).
6. **DB migrated + verified**: sessions rebuilt (38,759 = predicted), 15 views recreated,
   Screening + Session Activity driven via AppTest → 0 exceptions, view latency 0.77s.
   Suite: 401 passed; all 7 fails + 26 errors verified pre-existing (feature-catalog fails
   = restored DB missing the binary-model registration).

## 📝 Files Changed
- `src/managers/sepa_watchlist_manager.py`: cool-down gate/status/column + Python sweep deleted; DROP-recreate migration in backfill.
- `src/managers/view_manager.py`: `screener_watchlist` as view (~130-line CTE stack + nightly materialization deleted, self-migrating); `v_d1_candidates` survivorship filter removed.
- `src/orchestrators/daily_pipeline_orchestrator.py`: `cooldown_to_exited` key + stale `record_write` removed.
- `src/screener_diagnostics.py`, `scripts/backfill_sepa_watchlist.py`: repointed/trimmed.
- `docs/architecture/glossary.md`: `sepa_watchlist` entry updated (still flagged RENAME).
- Memory: `project_r2_pull_destroyed_main_db` (restore state, forward-only rule, 9,184-date check), `project_watchlist_merge` (new).
- (Carried from session 09, committed this session: R2 barriers, dashboard switch-over, new pages, guard tests.)

## 🚧 Work in Progress (CRITICAL)
- **DB is on a 06-21 snapshot.** Missing: prices/t2/t3 for 06-19→07-16; tables born after
  06-21 (`cone_cells`, `weather_gauge`, `sector_breadth`, `trades`/`cash_flows`/
  `nav_history` schemas, `m02_breakout_targets`, `shadow_action`/`shadow_book`); July
  `macro_data` series; `daily_predictions` binary backfill; `models` binary promotion.
  All recover FORWARD (engines re-fetch, builders re-run); shadow-book rows are the only
  real loss (~219 rows).
- **`d2_training_cache` not yet refreshed** — next refresh (Phase 7 or manual) shifts the
  training population by +292 delisted sessions. Deliberate; flag when comparing future
  trainings to old model cards.
- `v_d1_candidates` still derives sessions from t2 itself (third derivation; population
  proven equal). Unifying it onto `sepa_watchlist` is a clean follow-up, not urgent.
- `data/market_data.r2etag` still on disk (my delete was permission-blocked) — delete it.

## ⏭️ Next Steps
1. **Pipeline backfill 06-19→07-17** (raw + T1–T3; smoke-test batch first), then:
   `build_cone_cache.py`, training caches, re-register `m01_binary` (fixes the 4
   feature-catalog test fails), re-run `daily_predictions` backfill +
   weather_gauge/sector_breadth builders, recreate empty portfolio tables.
2. **sh019**: verify ITS DB integrity first (`count(distinct date)` = 9,184), pull code,
   run `backfill_sepa_watchlist.py` + `create_duckdb_views.py` (else stale COOLDOWN rows
   linger — nothing promotes them anymore); confirm cloud app sets
   `DASHBOARD_PULL_FROM_R2=1`.
3. **Backup story** — the restore worked by luck (a month-old snapshot existed). Even a
   weekly file-copy of the main DB to a second drive turns tier-0 into an inconvenience.
4. Gap-detection: wire "table missing/stale" checks into the Phase 8 audits (user steer:
   the daily pipeline should identify and heal gaps automatically).
5. Session-09 leftovers: dashboard feedback (rank-bump palette, supply-chain render,
   backtest-run caching design), `bootstrap_remote()` refactor, `page_today` deletion.

## 💡 Context/Memory
- **Cool-down flag-not-gate rationale**: the only structural consumer (T3 universe gate)
  reads `DISTINCT ticker`; the training grain never had the gate; a write-time drop
  destroys re-trigger info (tail-relevant). Population-invariant migration was the win.
- **The exact-match reconciliation is what licensed the view swap** — measure first, then
  the "risky" refactor is provably behavior-preserving.
- The slim `dashboard.duckdb` would have been the only backup of July serving state —
  user banned slim→local regardless; the one-way rule outranks recovery convenience.
- Incident postmortem addition: the precursor memory framed the broken creds-gate as a
  *wasteful download*, not a *destructive write* — when a known-broken gate fronts a
  WRITE, the deferral bar is "fix now".
