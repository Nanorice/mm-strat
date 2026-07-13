# Session Handover: 2026-07-13 (session 03)

## 🎯 Goal
Close B5 (the last open sprint-14 research item — stress sub-axis de-flicker), then
build a new **VIP watchlist** feature: a manually-curated ticker list forced into the
pipeline so their daily SEPA status + prod model score is monitored even if they'd
never pass the screen.

## ✅ Accomplished

### B5 — stress sub-axis de-flickered, `stress_z` promoted from provisional
- Root cause: `weather_gauge.stress_high` (the `DEPLOY→DEPLOY MORE` trigger) was a raw
  same-day 80th-pctile crossing → chattered. Measured: 65 toggles, 33 episodes,
  **58% were 1–2 day blips**.
- Fix: **EMA10-smooth the stress composite before the expanding-quantile cut**
  (`weather_engine` only, NOT source `_stress_ew_vix` — that feeds the backtested
  governor). Swept EMA5/10/20; EMA10 is the knee → 65→19 toggles, 0 chatter blips.
- **Leak-free (proven):** as-of-date identity test — recompute `stress_high` ending
  early at 3 dates vs full-history → **0 mismatches** over ~9k overlap days.
- Side effect flagged (not patched): `DEPLOY MORE` now fires 0× (was 1×) — EMA delays
  onset off the lone 2010-05-07 famine∧>200d day. Same GATE×TILT rarity, not a regression.
- `weather_gauge` refreshed (5903 rows); self-check carries a de-flicker assertion.

### VIP watchlist — new feature, built + tested end-to-end
- **Design:** the ONLY new state is a `vip_watchlist` table. T3's candidate filter is
  widened by one line to `sepa_watchlist UNION vip_watchlist WHERE active`, so VIP names
  get full daily features → flags → prod score **forward from add-date**, through the
  exact machinery the shortlist uses. No forked scoring/lifecycle. Confirmed with user:
  full feature readout, forward-only, assume in-universe (flag exceptions), two comment
  fields (source + comment), panel after shortlist, CLI-curated (dashboard read-only).
- **Proven:** VIP-only names (ABAT/ABOS, never in sepa_watchlist) enter the T3 candidate
  set and are absent without the union; populated path (NVCT) renders real status=active
  + prob_elite=0.62 + cohort; `not_in_universe` names show honest NULLs. CLI add/list/
  remove round-trips. View materializes with all 14 columns.

## 📝 Files Changed
**B5:**
- `src/weather_engine.py`: EMA10-smooth stress before the `stress_high` cut; docstring +
  self-check de-flicker assertion.
- `docs/session_logs/sprint_14/verdicts/2026-07-13_b5_stress_deflicker.md`: **NEW** verdict.
- `docs/session_logs/sprint_14/plans/2026-07-12_deliverables_roadmap.md`: §B5 status → DONE.
- `RESEARCH_LOG.md`: Q50 → CLOSED.

**VIP watchlist:**
- `src/managers/vip_watchlist_manager.py`: **NEW** — `vip_watchlist` table + add/remove(soft)/list.
- `scripts/vip_add.py`: **NEW** — CLI (`add/remove/list`); sys.path bootstrap; ASCII output (Win encoding).
- `src/feature_pipeline.py`: T3 candidate filter widened with `vip_watchlist WHERE active`.
- `src/managers/view_manager.py`: `_create_v_d3_vip` (VIP ⟕ latest t3 ⟕ lifecycle cohort ⟕ prod score); registered in `create_all()`; ensures base table exists.
- `scripts/build_dashboard_db.py`: MANIFEST += `v_d3_vip` (materialize_view).
- `scripts/dashboard_utils.py`: `load_vip_watchlist()`.
- `scripts/dashboard.py`: `render_vip_watchlist()` (status glyphs + comment col), wired after shortlist on `page_today`.

## 🚧 Work in Progress (CRITICAL)
- **Nothing half-finished in my work.** All changes tested in isolation.
- The one thing NOT done: **no real VIP names populated yet** — T3 free-ride happens on
  the next nightly run (forward-only by design). To see a name populate *now* needs a
  scoped T3 pass (writes the main T3 table) — deferred pending user go-ahead.
- ⚠️ **Concurrent-session hygiene:** the working tree has uncommitted changes from OTHER
  sessions today (sessions 01/02: `sepa_strategy.py`, `strategy_registry.py`,
  `run_starttime_sweep.py`, `earnings_calendar.py`, regime-tiering plan doc, 4class
  verdict, cells/*). **This session committed ONLY its own B5 + VIP files** — do not
  `git add -A`. Those other changes belong to their sessions.

## ⏭️ Next Steps
1. (optional) Populate real VIP names now via a scoped T3 pass, or let tonight's nightly run do it.
2. (deferred, agreed) Auto-fetch for VIP names outside the price universe — currently they show `not_in_universe`.
3. B5 follow-on (OPEN, do NOT patch blind): reconsider loosening `stress_high` from the top expanding-quintile now the trigger is stable — needs its own check.

## 💡 Context/Memory
- **The T3 free-ride is the whole trick:** T2 runs on the full ~2400 universe but T3
  (scoreable features + trend_ok/breakout_ok) is lazily computed ONLY over
  `ticker IN (SELECT DISTINCT ticker FROM sepa_watchlist)` (`feature_pipeline.py:630`).
  So VIP = a second source of *universe membership*; everything downstream is
  universe-driven and needs no change. The pipeline already separates "universe
  membership" from "session gating" — VIP slots cleanly into the first.
- **`v_d3_vip` builds from `t3_sepa_features` directly, NOT `v_d3_lifecycle`** — lifecycle
  drops '¬trend_ok / nothing-yet' names (the ripening VIP names we most want to watch),
  so it can only supply the cohort tag via LEFT JOIN.
- **The 2026-07-13_index.md line for session 01 over-claims "B5 de-flicker"** — the actual
  01 log has no stress content (only the COALESCE fix, already committed f5e29a7). My B5
  work is genuinely new. Index corrected this session.
