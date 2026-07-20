# Session Handover: 2026-07-20 (session 02)

## 🎯 Goal
Add "in play since" date/price/%-return columns to the Screening page — which surfaced two
pre-existing defects (near-total score loss after the binary promotion, and a screening
population that never matched the SEPA gate) that took over the session.

## ✅ Accomplished

**Date columns shipped** (`v_d3_screening` + `3_Screening.py`)
- `trend_start_date` / `trend_start_close` — first day of the current unbroken `trend_ok` run
  (gaps-and-islands, 400-day window so it doesn't scan the 57 GB table). 0.4s over 672 rows.
- `entry_date` / `entry_close` — ACTIVE `sepa_watchlist` session entry.
- `anchor_date` / `anchor_close` / `pct_return` — the anchor the UI shows: session entry where
  one exists, else trend-run start. Displayed as Since / Px @ since / Price / Δ %, with
  Trend since + Entry kept visible so the anchor is auditable.

**Score backfill — DONE and verified**
- Root cause: `m01_binary_20260524_222020` was promoted to prod while it had only ever run as
  shadow, which scores the `breakout` cohort alone — 2,249 rows total, 6 on 2026-07-17. The
  837 rows/day were under `m01_prototype_2003_2026_20260514_233125`, now `archived`, which
  `v_d3_screening` ignores (it joins `status_flag='prod'`).
- Smoke-tested one week first (project long-run rule): 4,092 rows / 5 dates / 31s.
- Full window: **120,708 rows across 167 dates** in 667s.
- Binary now 127,049 rows / 194 dates across all four cohorts (71,255 active / 33,243 removed /
  20,302 pre_breakout / 2,249 breakout).

**Screening population corrected** — the session's real finding
- The population was `trend_ok OR breakout_ok` since 93497c9 (2026-07-16), written as the plain
  union of the two stage flags. But `breakout_ok` is computed independently of the trend template
  (`breakout = 1 AND volume/vol_avg_50_prev > 1.3`, feature_pipeline.py:407) and never references
  `trend_ok`. **The SEPA gate is AND; the view used OR.**
- Effect: 42 of 79 "triggered" rows on 2026-07-17 were breakouts *failing* C1-C9 — 29 had not been
  `trend_ok` once in 400 days. Never tradeable, no run or session to date, and outside every
  `v_d3_lifecycle` cohort so nothing scored them. They rendered as blank Since/Trend/Entry/Score.
- Population narrowed to `trend_ok`. `triggered` now means the real gate.

| | before | after |
|---|---|---|
| rows | 672 | 630 |
| triggered | 79 (42 failing C1-C9) | 37, all `trend_ok` |
| blank Since / Trend / Entry | 42 | 0 |
| blank Score | 55 | 13 |

**Slim dashboard DB rebuilt** — 760.8 MB / 223s / 3,120,973 rows. Verified it carries this
session's work: `v_d3_screening` materialized at 630 rows (593 setup / 37 triggered, all
`trend_ok`), 0 blank anchors, 127,049 binary predictions. Page boots against it.

## 📝 Files Changed
- `src/managers/view_manager.py`: `_create_v_d3_screening` — added the anchor/date block
  (`mx`/`sess`/`sess_px`/`hist`/`runs`/`trend_runs`/`trend_start` CTEs); narrowed `pop` from
  `trend_ok OR breakout_ok` to `trend_ok`; `sess_px` is INNER so `entry_date`/`entry_close` are
  never split across sources.
- `scripts/pages/3_Screening.py`: 6 new columns + "How to read the dates" expander.
- `docs/session_logs/sprint_15/plans/t3_universe_widening.md`: NEW — plan for the 13 remaining
  blank scores, gated behind two read-only measurements.
- View applied to `market_data.duckdb` (CREATE OR REPLACE, metadata only) and rebuilt into
  `data/dashboard.duckdb`.

## 🚧 Work in Progress (CRITICAL)

- **Nothing half-finished in code.** All changes applied to the DB, 18 view tests pass, page
  smoke-runs against both the main and slim DB.
- **Slim DB NOT pushed to R2.** `scripts/sync_dashboard_db.py` is a publish step to an external
  service — deliberately left for a human. The nightly `r2_sync` phase will otherwise pick it up.
- **A correction I owe the record:** when offering the population options I quoted "630 rows" for
  `trend_ok OR active-session`. That was wrong — I had filtered the *old* frame, which can only
  subtract. The true figure for that variant is 672 (42 dropped, 42 holdings added). The option
  actually shipped is `trend_ok` = 630.
- **Backed out deliberately:** `trend_ok OR active-session` would keep open positions visible, but
  labelled 445 rows `setup` that are actually held. Needs a third `held` stage — a taxonomy change
  not requested, so reverted. **Consequence: a name you hold that falls out of the trend template
  now disappears from the Screening page entirely.**

## ⏭️ Next Steps
1. **`set_prod()` does not trigger the score backfill.** Promotion orphans all history under the
   outgoing model id; the only signal is a monitoring WARN ~10 min later. The next promotion blanks
   the page again. Either `set_prod` calls `backfill_daily_predictions`, or it refuses until scores
   exist. This is the highest-value item — it is the defect that caused this session.
2. **`set_shadow()` writes `'shadow'`, which the `models` CHECK constraint rejects**
   (`model_registry.py:558`; constraint allows `prod`/`test`/`archived` only). No row holds it, so
   `get_shadow_version()` returns None and the shadow pass should be dead — yet the 2026-07-19 log
   shows it ran and wrote 6 breakout rows. Unresolved contradiction; resolve before trusting shadow.
3. Decide the **holdings-visibility** question (🚧 above) — `held` stage or leave as-is.
4. `t3_universe_widening.md` — start with AGL's self-heal miss (small, independent), then the two
   read-only measurements. **Do not widen T3 before those numbers exist.**
5. `sepa_watchlist` rebuild still outstanding (carried from session 01).
6. `tests/test_feature_pipeline.py` — 14 errors, calls a method deleted before this work.

## 💡 Context/Memory

- **The two defects were one seam.** Screening reads t2 (~2,750 tickers/day); the model reads t3
  (~2,430) and only for tickers that have opened a SEPA session at least once. Blank scores are
  where a t2-wide display meets a t3-narrow model. Widening the display without widening the model
  just moves the blank.
- **The 13 remaining blanks are chicken-and-egg, not corruption.** A ticker in the trend template
  for the *first time* has no session, so no t3 row, so no cohort, so no score — and it becomes
  scoreable exactly when it triggers, i.e. when it stops being a pre-breakout candidate. That is
  the highest-value case for pre-breakout ranking and the one we structurally cannot rank.
- **`v_d3_lifecycle`'s docstring claims MECE; it isn't** relative to the screening population. Its
  filter is `(trend_ok AND NOT breakout_ok) OR has-session`, so `trend_ok ∧ breakout_ok ∧ no-session`
  falls through too — not just the non-trend breakouts.
- **Why the OR went unnoticed for four days:** commit 93497c9 verified "619 rows / 558 scored",
  which looked healthy because the prototype was prod and covered `pre_breakout` broadly. The
  promotion exposed a latent population bug rather than creating one.
- **Market holidays carry phantom vendor bars.** 2026-06-19 (Juneteenth) has 4 price rows and
  2001-09-11 has 1, with no SPY bar and correctly no `t1_macro` row. Any "is this a trading day"
  test must key off **SPY's own `price_data` row**, not "any price row" — the first version of
  `_assert_benchmark_coverage` got this wrong and would have blocked session 01's backfill, whose
  range spans 06-19.
