# Session Handover: 2026-07-05 (Forward Shadow Book + Start-Time Sweep)

> Phase 4 of the backtest productionisation. Prior same-day handovers cover
> Phases 1–3 (`2026-07-05_backtest-productionisation.md`) and the exit grid
> (`2026-07-05_backtrader-exit-grid.md`). This one is Phase 4 only.
> **Committed: `1fa5b61` (research branch).**

## 🎯 Goal
Implement Phase 4 of `docs/architecture/backtest_productionisation_plan.md`:
(Thing 2) run the start-time sensitivity sweep to learn how much the champion's
edge depends on *when* you start, and (Thing 1) build a parity-gated forward
"shadow book" step-engine that mirrors the BackTrader backtest for live monitoring.

## ✅ Accomplished
- **Start-time sweep (Thing 2) — all grids run, verdict in.** Fixed a real bug first:
  the sweep's parallel path submitted an unpicklable local closure (`run_sweep.<locals>._one`)
  to `ProcessPoolExecutor` — only the serial `--smoke` path ever worked. Lifted `_run_cell`
  to module level. **Verdict: the champion is strongly start-time dependent** — `rolling`
  (53 cells, fixed 12m horizon) ann_return **−39.4%..+196.6%**, Sharpe **−0.88..+2.45**,
  **17/53 cells Sharpe-negative**, regime-clustered. The edge is a beta/regime ride.
- **Forward shadow book (Thing 1), Steps 1–5 — parity GREEN.**
  - `src/backtest/forward_engine.py`: `ChampionBook.step()`, a synchronous next-open
    mirror of `SEPAHybridV1.next()` (one-day pending queue = BackTrader's fill convention).
    Reuses `PositionTracker`/`ScoreLookup` verbatim; champion-off branches raise
    `NotImplementedError`. `build_price_frame()` = the G2 parity fix. DB-free `__main__` self-check.
  - `scripts/run_shadow_book.py`: replay start→today, persists `shadow_book` + `shadow_action`
    (keyed by `book_id`), idempotent. Ran + persisted a real book (5 open, 214 actions).
  - `tests/test_forward_parity.py`: LOAD-BEARING gate, entry overlap > 0.85 — **green.**
- **Docs refreshed, no stale refs** — module doc (`backtest.md`), exploration summary
  (start-time finding + end-to-end journey table), plan doc (Phase 4 → shipped + daily mechanism).
- **3 memories written** (forward shadow book, BackTrader all-feed warmup, champion start-time dependence).

## 📝 Files Changed (committed 1fa5b61)
- `src/backtest/forward_engine.py`: NEW — synchronous step-engine + `build_price_frame` + self-check.
- `scripts/run_shadow_book.py`: NEW — replay/persist CLI for the shadow book.
- `scripts/run_starttime_sweep.py`: NEW (was uncommitted from prior session) — fixed the pickle bug.
- `tests/test_forward_parity.py`: NEW — the parity gate.
- `docs/architecture/backtest_productionisation_plan.md`: Phase 4 marked shipped; Step 6 daily mechanism.
- `docs/modules/backtest.md`: removed phantom `price_feed`/`regime_feed`; added `forward_engine`; 13→15 files.
- `docs/session_logs/sprint_13/strategy_exploration_summary.md`: start-time finding + journey narrative.

## 🚧 Work in Progress (CRITICAL)
- **Step 6 (orchestrator/nightly on `sh019`) is NOT started — deferred *by design*.** No inception
  date has been chosen for the simulation; the start-time sweep exists precisely to inform that
  decision (12m return swings −39%..+197% by start month). Until a date is picked, there is nothing
  to operate live. Do NOT wire the nightly yet.
- **Minor, not a blocker:** the persisted book ends at `cash −$78` (−0.3% of $25k) — commission-vs-5%-buffer
  rounding on same-day entries; mirrors BackTrader's own small-negative-cash behavior. Harmless for a
  paper book; tighten the 0.95 cash cap only if it bothers a real sim.
- **Not mine, left uncommitted:** working tree still has pre-existing `scripts/dashboard.py`,
  `dashboard_utils.py`, `sprint13_summary.md` edits + unrelated untracked files (skill-creator,
  notebooks, `test_cohort_return_panel.py`). Left untouched — confirm ownership before committing them.

## ⏭️ Next Steps
1. **Decide the inception date** for the champion shadow simulation (read the sweep reports first:
   `data/selection_sweep/starttime/champion/{rolling,horizon,matrix}/report.md`). This is the gate
   on everything below.
2. **Then build Step 6 (registry-driven daily), supervised on `sh019`** — the mechanism the user
   specified (see plan §Phase 4 Step 6):
   a. Human picks date → one-time **backfill** (the current `run_shadow_book.py --start-date …` replay
      *is* the backfill) → **register `(book_id, strategy, start_date, status)`** in a new
      `shadow_book_registry` table.
   b. Nightly orchestrator phase (after `daily_predictions` materializes) **detects active rows** and
      **steps ONLY the new day** incrementally — load persisted `shadow_book`, one `step(today)`,
      append `shadow_action`. NOT a full replay. `forward_engine.step()` is already the per-day unit.
   c. Add `shadow_book`/`shadow_action`/registry to `build_dashboard_db` MANIFEST or the R2 remote breaks.
   > Grids are **exploration-only** — the daily pipeline never runs a grid.
3. **Before real capital (unchanged):** the friction/liquidity-floor re-run (Tier A.2) — the microcap
   +861% is a ranking signal, not a P&L promise.

## 💡 Context/Memory
- **The parity trap that cost the first pass (17% overlap):** BackTrader's strategy `next()` does not
  fire until **every** feed's SMA50 is warm — the *latest-listing* ticker (KYTX, 50th bar 2024-04-22)
  gates the whole strategy, even in a January-start window. The parity test replicates this all-feed
  warmup. See memory `project_backtrader_allfeed_warmup`.
- **Warmup diverges intentionally between the two engines.** Parity test = all-feed (bit-faithful to
  the backtest). Live `run_shadow_book.py` = per-ticker (a name trades once its own SMA50 exists), so
  one recent IPO doesn't freeze the entire live book. Rules/fills identical; only first-tradeable-day differs.
- **Replay, not serialization.** The shadow book is a pure function of (scores, prices, regime); a few
  hundred days replays in seconds. So the runner recomputes the full book each call rather than pickling
  live `PositionTracker` state — far less fragile, same observable result as "catch-up then incremental."
  (The *nightly* path in Step 6 will be incremental for efficiency, but the backfill is this replay.)
- **The champion is a regime ride, not start-invariant skill.** The OOS fold-gate proved "not overfit
  to the split"; the start-time sweep proved "still fragile to *when* you start." Both are true; they
  measure orthogonal risks. The live monitor must present a start-date confidence *cone*, not one P&L.
