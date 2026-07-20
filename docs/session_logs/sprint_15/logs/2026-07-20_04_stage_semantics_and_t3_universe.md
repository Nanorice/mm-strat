# Session Handover: 2026-07-20 (session 04)

## 🎯 Goal
Close the promotion defect that caused session 02, then fix what session 02 surfaced but
could not name: the Screening `stage` was a same-day event flag masquerading as a state,
and the T3 universe structurally excluded the names `pre_breakout` scoring exists to rank.

## ✅ Accomplished

**`set_prod()` score-coverage gate** (`model_registry.py`)
- `_assert_scores_backfilled()` refuses promotion if the incoming version has fewer scored
  dates in `daily_predictions` than the outgoing prod. `force=True` overrides.
- Compares **date coverage, not existence** — deliberately. The 2026-07-20 shadow model had
  2,249 rows and would have sailed through a non-zero check.
- Chose *refuse* over *auto-backfill*: the backfill is ~8-11 min holding the single write
  lock, and it already takes `--model-version-id`, so "backfill then promote" is the natural
  order. Test added to `test_promotion_gate.py` reproducing the exact failure.

**`set_shadow()` — no contradiction, doc was wrong**
- The **live** `models` CHECK is `('prod','test','archived','shadow')` (read from
  `duckdb_tables()`). Only `ViewManager._create_models_table` carried the stale 3-value list,
  and being `CREATE TABLE IF NOT EXISTS` it never touched the live table. Shadow always worked.
- Fixed the DDL so a fresh DB doesn't inherit it. **Lesson: read the DB's own DDL, not the
  code's, before calling a constraint contradiction.**

**Screening `stage` re-keyed to the session** (`view_manager.py`) — the session's real finding
- `stage` was `CASE WHEN breakout_ok`. `breakout_ok` is a one-**day** event flag, so
  `triggered` meant "is breaking out right now", not "has broken out".
- Effect: **403 of 630 rows** labelled `setup` had broken out days-to-months earlier and were
  still in an open session (35 within 7d, 179 within 8-30d, 136 within 31-90d, 53 within a year).
- Now keys off the open `sepa_watchlist` session — the persistent record of "has broken out".
  The join was already present for the anchor dates, so it was a one-line change.

| stage | before | after | predicate |
|---|---|---|---|
| triggered | 37 | **440** | open session |
| setup | 593 | **190** | `trend_ok`, no open session |
| watchlist | — | **2** | active VIP, ¬`trend_ok` |

**VIP exception** — `pop` was `trend_ok` only, so a curated name outside the template would
silently never render. Now `trend_ok ∨ active VIP`. MRVL + RKLB added as live test; both are
¬`trend_ok` and render `watchlist` with scores.

**T3 universe widened to ever-`trend_ok`** (`feature_pipeline.py` + orchestrator)
- Measured first: **107 tickers / 56,085 rows = 0.6% of t3**. The plan's fear that
  history-depth would dominate did not survive measurement.
- **The trap:** the universe was defined in TWO places — `compute_t3_features` (what gets
  materialized) and `_t3_holed_dates` (what the self-heal expects). Widening one alone leaves
  the self-heal blind. Both now read one `feature_pipeline.T3_UNIVERSE_SQL`.
- `compute_t3_features(only_tickers=…)` added so newly-admitted names backfill without
  DELETE-ing a whole span. Alpha stage is mostly fixed cost (2 tickers 79s, 109 tickers 77s).
- Backfilled 111 tickers full history (59,031 rows), ran the self-heal (11 holed dates →
  **0**), then the full prediction backfill (121,478 rows / 172 dates).

**Result: `v_d3_screening` blank scores 13 → 0.** t3 9.41M → 9.47M rows, 2,726 → 2,836 tickers.

**Docs suite updated** — `comprehensive_methodology.md` (§2.2, §4, §6, §7, §11), `glossary.md`
(new `session` + **Screening stages** entries), `feature_pipeline.md`, `orchestrator.md` (new
T3 self-heal section), `model_registry.md`, `managers.md`, `dashboard.md`.

## 📝 Files Changed
- `src/model_registry.py`: `_assert_scores_backfilled()` + call in `set_prod`.
- `src/managers/view_manager.py`: `stage` keyed to session; `pop` admits active VIP; `models`
  DDL CHECK gains `'shadow'`.
- `src/feature_pipeline.py`: `T3_UNIVERSE_SQL` constant; `only_tickers=` param.
- `src/orchestrators/daily_pipeline_orchestrator.py`: `_t3_holed_dates` reads the constant;
  docstring corrected.
- `tests/test_promotion_gate.py`: score-coverage test.
- `tests/test_feature_pipeline.py`: universe test rewritten to the new contract + a
  "guard the guard" assertion so it can't pass trivially.
- Docs: 7 files (above).

## 🚧 Work in Progress (CRITICAL)

- **Nothing half-finished.** Slim `dashboard.duckdb` rebuilt and verified: 766.5 MB / 320s /
  3,133,480 rows, carrying 440/190/2 stages, **0 blank scores**, both VIP names.
  (It builds into `data/dashboard.tmp.duckdb` and swaps at the end, so the target file keeps
  its old timestamp until the final second — do not read that as a stall, as I briefly did.)
- **NOT pushed to R2.** `sync_dashboard_db.py` publishes externally; left for a human. The
  nightly `r2_sync` phase will otherwise pick it up.
- **1 failing test, deliberately not silenced**: `test_backtest_matches_prod_predictions` at
  **1.014% vs a 1.0% threshold**. Verified NOT mine — the 8 diverging tickers (AXTI, BLTE,
  GALT, GRC, HYMC, NHC, SNDK, VERI) are all pre-existing and **zero** newly-admitted tickers
  appear in the test's window. It is a real seam: `score_from_t3` reads t3 directly while
  `daily_predictions` is hydrated via `v_d3_lifecycle`, and they disagree for a few names.
  My backfill refreshed prod predictions and nudged a pre-existing residual over the line.
  **Do not raise the threshold** — find the feature that differs.

## ⏭️ Next Steps
1. Verify tonight's run: **first nightly under the widened universe.** Phase 5 should be a
   no-op (0 holes). Slim DB is already correct, so Phase 7.5 should simply reproduce it.
2. Root-cause the `score_from_t3` vs `v_d3_lifecycle` feature seam (the failing test).
3. Plan Q3 — is M01 valid on session-less names? The 12 first-time setups now receive scores
   of unverified validity. User accepted this as placeholder-grade for non-`triggered` rows.
4. `sepa_watchlist` rebuild — still outstanding, carried from session 01.
5. Optional cosmetic: `watchlist`-stage rows fall through the anchor COALESCE to today, so
   MRVL/RKLB read "0.0% since 2026-07-17". User OK'd leaving it.

## 💡 Context/Memory

- **The stage bug and the T3 gap were the same mistake at two layers**: both confused an
  *event* with a *state*. `breakout_ok` (a day) was used as the stage (a state); session
  membership (an event that has happened) was used as the T3 universe when "is in the trend
  template" (a state) was meant. Naming the distinction in the glossary is the durable fix.
- **The glossary had no entry for `session` or the stages.** That absence is *why* the view
  drifted — there was nowhere to look up what `triggered` was supposed to mean. Added both.
- **Entry and exit use different tests, deliberately**: entry needs full C1–C9, exit only
  breaks on C1+C2+C6 (C9 RS flicker would shred one session into many). So a name can fail
  `trend_ok` while its session stays open — 42 such names, all verified `trend_ok ∧
  breakout_ok` at entry and still above all three SMAs. Not a bug.
- **"Never materialised" ≠ corrupt.** T3 is built per date-chunk; a ticker admitted later
  never gets earlier dates because those chunks already ran. The rows were never written.
  This is why the gap grows monotonically between bulk rebuilds — it is not data rot.
- **Do not run `pytest tests/` while a prod-DB writer is in flight.** It produces ~10
  failures with `IO Error: ... used by another process` that look exactly like real
  regressions. Cost me a debugging detour; now recorded in memory.
- **AGL was never a self-heal bug** — an out-of-band `sepa_watchlist` rebuild at 02:31 landed
  after the previous night's Phase 5. Diagnosis came from comparing `pipeline_runs` timestamps
  against `updated_at`, not from reading the heal logic.
