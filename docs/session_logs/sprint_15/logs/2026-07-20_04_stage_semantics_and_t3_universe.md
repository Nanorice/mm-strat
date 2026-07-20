# Session Handover: 2026-07-20 (session 04)

## 🎯 Goal
Close the promotion defect that caused session 02, then fix what session 02 surfaced but
could not name: the Screening `stage` was a same-day event flag masquerading as a state,
and the T3 universe structurally excluded the names `pre_breakout` scoring exists to rank.
Ended by root-causing the one test the day's work left failing.

> **Recurring theme:** every defect closed today was an **event used where a state was
> meant**, or **one definition living in two places**. `breakout_ok` (a day) as the stage
> (a state); "has opened a session" (an event) as the T3 universe where "is in the trend
> template" (a state) was meant; the T3 universe defined twice; the fundamentals dedup
> defined twice. Worth carrying as a search pattern, not just a list of fixes.

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

**Root-caused the `score_from_t3` vs `daily_predictions` seam** (the failing test)
- Not scoring drift — a **data defect** surfacing through two views that dedupe differently.
- `fundamental_features` holds **939 duplicate `(ticker, filing_date)` pairs across 354
  tickers**; **602** are one populated row + one all-NULL twin filed the same day at a
  slightly different `report_date` (SNDK 2025-11-07: `report_date` 2025-09-30 → eps 0.75 /
  rev 2.308B; `report_date` 2025-10-03 → empty).
- Both dedupe sites — `ff_dedup` in `v_d3_lifecycle` and the `v_t3_training` join — order by
  `fiscal_period DESC`, which **ties** when the twins share a fiscal period. Each view lands
  on a different twin arbitrarily: lifecycle gets the numbers, `v_t3_training` the NULLs.
- The tell: all 14 diverging model features are **fundamentals**. T3 doesn't store them, it
  joins them at query time — so the divergence had to be in the join, not in the features.
- ⚠️ A further **252 pairs have two *populated* rows**, tie-broken arbitrarily too. No
  NULL-preference fix covers those.
- **Not fixed** — see Next Steps 2. Logged as RESEARCH_LOG Q10 with both options.

**Opened `sprint_15/RESEARCH_LOG.md`** — the sprint had none. Threads A–C, 10 questions
reconstructed from this sprint's handovers; Q5 (M01 validity on session-less names) and Q10
(where to fix the coin-flip) left open with methods.

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
- Docs: 7 files (above) + `docs/session_logs/sprint_15/RESEARCH_LOG.md` (new).

Commits: `e94e907` (code + docs), `6f0d431` (stale-TODO correction), `8399e31` (seam
root cause + RESEARCH_LOG), `3ccd01e` (knowledge-base design doc, not authored here —
committed separately so it isn't misattributed). `18d3a16` carries session 03's
uncommitted research-report work, which was sitting in the tree when this session began.

## 🚧 Work in Progress (CRITICAL)

- **Nothing half-finished.** Slim `dashboard.duckdb` rebuilt and verified: 766.5 MB / 320s /
  3,133,480 rows, carrying 440/190/2 stages, **0 blank scores**, both VIP names.
  (It builds into `data/dashboard.tmp.duckdb` and swaps at the end, so the target file keeps
  its old timestamp until the final second — do not read that as a stall, as I briefly did.)
- **NOT pushed to R2.** `sync_dashboard_db.py` publishes externally; left for a human. The
  nightly `r2_sync` phase will otherwise pick it up.
- **1 failing test, root-caused but deliberately NOT fixed**:
  `test_backtest_matches_prod_predictions` at **1.014% vs a 1.0% threshold**. Verified not
  mine — the 8 diverging tickers are all pre-existing and **zero** newly-admitted tickers
  appear in the test's window; my backfill merely refreshed prod predictions and nudged a
  pre-existing residual over the line. Root cause below (💡). **Left failing on purpose**:
  the fix is a judgement call between patching every consumer and a destructive prod write,
  and raising the threshold would hide ~600 silent coin-flips. Logged as RESEARCH_LOG Q10.

## ⏭️ Next Steps
1. Verify tonight's run: **first nightly under the widened universe.** Phase 5 should be a
   no-op (0 holes). Slim DB is already correct, so Phase 7.5 should simply reproduce it.
2. **Decide where to fix the duplicate-fundamentals coin-flip** (RESEARCH_LOG Q10 — root
   cause found this session, fix deliberately deferred). Answer the upstream question first:
   *why does the fundamentals engine write an empty shell at a slightly different
   `report_date`?* Then choose — patch every consumer's tie-break (small, but the next new
   view forgets it) or clean the table (correct, but a destructive prod write, and
   `d2_training_cache` needs refreshing since training data may embed the coin-flip).
   ⚠️ 252 pairs have two *populated* rows — a NULL-preference fix does **not** cover them.
3. Plan Q3 — is M01 valid on session-less names? Now recorded with a method in
   [RESEARCH_LOG.md](../RESEARCH_LOG.md) open meta-questions. The 12 first-time setups
   receive scores of unverified validity; the user accepted them as placeholder-grade for
   non-`triggered` rows, which is a **display** decision, not a validity finding.
4. ~~`sepa_watchlist` rebuild~~ — **already done**, 2026-07-20 02:31:13. Verified after the
   user challenged it: one `updated_at` across all 39,088 rows (full rewrite), the six
   formerly-corrupt days now carry 11/6/14/6/26/33 entries where they had zero, and the
   06-26 pileup drained 95 → 80. Ran after the T2 repair, the required order. **This was a
   stale TODO copied forward through three handovers without anyone re-checking the DB.**
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
- **A failing test can be a data defect wearing a threshold's clothes.** The seam looked like
  scoring drift and sat 0.014pp over a tolerance — the tempting read is "flaky, bump it". The
  diagnostic that cracked it was diffing the two views' **feature vectors** rather than their
  scores: all 14 differing columns were fundamentals, and T3 doesn't store fundamentals. That
  narrowed a 97-feature search to one join in two queries. **Diff the inputs, not the output.**
- **Two consumers deduping the same rows independently is the same class of bug as the T3
  universe having two definitions** — fixed once this session by a shared constant, found
  again hours later in `ff_dedup` vs `v_t3_training`. Worth a sweep for other duplicated
  as-of/dedup logic; each instance is a silent coin-flip, not a loud error.
- **AGL was never a self-heal bug** — an out-of-band `sepa_watchlist` rebuild at 02:31 landed
  after the previous night's Phase 5. Diagnosis came from comparing `pipeline_runs` timestamps
  against `updated_at`, not from reading the heal logic. That same 02:31 rebuild *was* the
  "outstanding" watchlist rebuild — the evidence was sitting in the timestamp I had already
  queried twice, and I still copied the stale TODO forward. **A carried TODO is a claim about
  live state; check it, don't relay it.**
