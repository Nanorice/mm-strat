# Rename plan — `sepa_watchlist` and sibling watchlist names

> Drafted 2026-07-17 for a **future session**. NOT to be executed piecemeal — a
> rename touching a persisted key is a migration, do it as one atomic change with
> the DB backed up. Glossary verdict this implements: `sepa_watchlist` → RENAME
> (it is trade sessions, not a watchlist). See `docs/architecture/glossary.md` §1.

## 0 · The scope question you asked me to confirm — ANSWERED

**The table name is wrong on its own terms, independent of the dashboard.** Measured
2026-07-16, one string `sepa_watchlist` denotes **three different populations**:

| Meaning | Count | Consumer |
|---|---|---|
| Sessions **open on the date** | 373 | what "watchlist" implies |
| **Ever** opened a session (all-time, no date filter) | 2,717 | the T3 universe gate (`SELECT DISTINCT ticker`) |
| **Scored** in `daily_predictions` | 799 | the dashboard |

Open-vs-scored overlap is 336/373 — a *different set*, not sub/superset. 35,379 of
35,884 rows are `status='EXITED'`. So it is an **event log of trade sessions**, and
the T3 gate — the load-bearing use — deliberately ignores date/status. Verdict holds:
**rename the table.** The dashboard framing ("everything that passed the SEPA rule,
scored together") does not make "watchlist" correct — it is a third population again.

## 1 · Two names, two decisions (do NOT conflate)

| Surface | Current | Proposed | Cost |
|---|---|---|---|
| **The table** | `sepa_watchlist` | `sepa_sessions` | find-replace + view rebuild + MANIFEST |
| **The phase id** | `sepa_watchlist` | `sepa_sessions` (open/close today's sessions) | **persisted key → migration** |

These are separable. The table rename is mechanical. The phase id is a persisted key
in `pipeline_runs.phase_name` — renaming it strands history unless migrated.

## 2 · Blast radius (grepped 2026-07-17)

**Table string — 15 files, ~44 refs.** Heaviest:
- `src/managers/sepa_watchlist_manager.py` (19) — also the FILE name + `class SepaWatchlistManager` + `src/managers/__init__.py` export
- `src/orchestrators/daily_pipeline_orchestrator.py` (15 — mix of table SQL and phase id)
- `src/feature_pipeline.py` (6) — the T3 `WHERE ticker IN (SELECT DISTINCT ticker FROM sepa_watchlist)` gate
- `scripts/backfill_sepa_watchlist.py` (5, + file name), `view_manager.py` (1), `portfolio_manager.py` (1), `vip_watchlist_manager.py` (2)
- dashboard: `build_dashboard_db.py` (MANIFEST entry — **R2 parity: miss this and the remote app breaks**, per memory), `dashboard_utils.py` (2), `5_Pipeline_Health.py` (freshness-tolerance key)

**Phase-id persistence — `pipeline_runs`:**
- `sepa_watchlist` — 10 rows, 2026-06-16..07-16 (current stable id)
- `phase_4b_sepa_watchlist` — 26 rows, 2026-05-07..06-15 (already-superseded positional key)

The old positional key is already orphaned (registry doesn't know it; heatmap sends
it to 999.0 since this session). So a phase-id rename adds a *second* orphan unless
handled.

## 3 · Recommended approach

**Table → `sepa_sessions`:** one atomic commit.
1. Back up `data/market_data.duckdb` first.
2. `ALTER TABLE sepa_watchlist RENAME TO sepa_sessions` (+ the `src.` slim-DB copy).
3. Scripted replace of the table string across the 15 files (careful: the string is
   BOTH table and phase id in the orchestrator — replace SQL contexts only, handle
   the phase id separately in step 4).
4. Rename file `sepa_watchlist_manager.py` → `sepa_sessions_manager.py`, class
   `SepaWatchlistManager` → `SepaSessionsManager`, fix `__init__.py` export + all
   importers. Same for `scripts/backfill_sepa_watchlist.py`.
5. MANIFEST entry in `build_dashboard_db.py` → `sepa_sessions` (R2 parity).
6. Rebuild views (`create_duckdb_views.py`), rebuild slim DB, smoke-test dashboard.
7. Run `tests/` — expect `test_phase_registry` + any watchlist test to need the id update.

**Phase id → decide between:**
- **(a) Rename + accept the orphan.** Registry id `sepa_watchlist` → `sepa_sessions`;
  old rows (`sepa_watchlist`, `phase_4b_sepa_watchlist`) become history the heatmap
  sorts to 999.0. Cheapest. The heatmap already tolerates unknown keys since this
  session. **Recommended** — the history is 10+26 rows of a monitoring heatmap, not
  analytical data; a cosmetic sort-order gap on old rows is acceptable.
- **(b) Rename + migrate.** `UPDATE pipeline_runs SET phase_name='sepa_sessions'
  WHERE phase_name IN ('sepa_watchlist','phase_4b_sepa_watchlist')`. Clean history,
  but rewrites a persisted audit log — heavier, and mutating run history is itself a
  smell. Only if the heatmap seam actually bothers you.

**Do NOT** rename the phase id without picking (a) or (b) — a bare rename gives the
worst of both (orphaned history AND no clean cut).

## 4 · Sibling names to settle in the SAME pass (avoid a second migration)

- **`screener_watchlist`** (9 files) — the OTHER "watchlist"; glossary notes it's the
  materialised dashboard trade table (1 row/trade w/ returns), coexisting with
  sepa_watchlist. Two "watchlist" tables that are neither watchlists. Candidate:
  `screener_trades` or `screener_dashboard_trades`. Confirm scope before touching —
  it has its own view (`v_screener_dashboard`).
- **`vip_watchlist`** / `vip_watchlist_manager.py` — real watchlist? confirm before
  lumping in. If it IS a watch-set, it can KEEP the name (the only honest one).
- Leave `sepa_watchlist_manager`'s references to `screener_watchlist` untouched unless
  that table is renamed in the same commit.

## 5 · Pre-flight checklist for next session
- [ ] Back up the DB.
- [ ] Confirm `sh019` (ops box) isn't mid-nightly-run — this touches the T3 gate.
- [ ] Decide phase-id path (a) vs (b) — recommend (a).
- [ ] Decide `screener_watchlist` / `vip_watchlist` in-scope or deferred.
- [ ] One atomic commit per table; run full `tests/` + dashboard smoke after.
