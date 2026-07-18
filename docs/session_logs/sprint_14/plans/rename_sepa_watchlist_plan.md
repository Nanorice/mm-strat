# Rename plan — `sepa_watchlist` display surface

> Drafted 2026-07-17, revised same session. **DECISION (2026-07-17): keep the infra
> name, rename only the display surface.** `sepa_watchlist` stays as the table name,
> phase-id, and T3-gate string — all infra-internal, **no DB migration, no persisted-key
> churn**. The only rename is what the *user* sees on the dashboard. This collapses the
> plan from an atomic DB migration to a display-label change.
>
> Glossary verdict context: `sepa_watchlist` is genuinely misnamed (it's trade sessions,
> not a watchlist — `docs/architecture/glossary.md` §1). But that verdict is about the
> *user-facing* meaning; burying the false name in infra defuses it at zero migration cost.
> §2 below (full blast radius) is retained as a REFERENCE MAP only — it documents where the
> name lives if a full rename is ever revisited; it is NOT the plan of record.

## 0 · The scope question you asked me to confirm — ANSWERED

**The table name is wrong on its own terms, independent of the dashboard.** Measured
2026-07-16 (numbers refreshed this session), one string `sepa_watchlist` denotes
**three different populations at different day-grains** — the original draft conflated a
daily snapshot (799) with two lifetime counts:

| Meaning | Count | Grain | Consumer |
|---|---|---|---|
| Sessions **open on the date** (`status='ACTIVE'`) | 357 | snapshot | what "watchlist" implies |
| **Ever** opened a session (all-time, no date filter) | 2,717 | lifetime | the T3 universe gate (`SELECT DISTINCT ticker`) |
| **Scored** in `daily_predictions` on the latest date | 799 | **daily snapshot** | the dashboard |

Corrections vs the first draft: open-on-date is **357** (not 373); the **799 is a
per-day count**, not lifetime (lifetime scored = 1,738 over 189 days). 799 is NOT the
T3 universe and never will be — the scorer runs the lifecycle cohorts each day
(`pre_breakout ∪ active ∪ removed`), reaching *forward* (pre-breakout candidates) and
*backward* (recently-removed) of the open-session set, not the 2,717 all-time gate.

35,379 of 35,884 rows are `status='EXITED'`. So it is an **event log of trade
sessions**, and the T3 gate — the load-bearing use — deliberately ignores date/status.
Verdict holds: **rename the table.**

## 0.5 · Findings from the 2026-07-17 design session (fold into the rename)

Investigating the rename surfaced four load-bearing facts. Capture them here so the
rename session doesn't re-derive them.

### (a) `cohort` column on `daily_predictions` → DROP from the PK
- **What it is:** a denormalized, *point-in-time* copy of the lifecycle state
  (`pre_breakout`/`active`/`removed`), written per prediction row. It affects **nothing**
  in scoring — the model scores each ticker identically regardless of cohort; cohort only
  partitions the `rank_within_day` computation ([prediction_logger.py:151](../../../../src/evaluation/prediction_logger.py#L151)).
- **The bug it caused:** cohort is in the PK
  (`PRIMARY KEY(prediction_date, ticker, model_version_id, cohort)`). A ticker is **one**
  lifecycle state per day (the derivation is one-tag-per-row), so this 4th key column buys
  no legitimate dual-membership — but it let a **double backfill** (ingested 2026-06-14
  *and* re-ingested 06-19) INSERT stale twins instead of overwriting: **53,210 dual-cohort
  rows on archived `m01_prototype`; ZERO on prod `m01_binary`.** `check_backtest_parity.py:59`
  already papers over these with `drop_duplicates(["date","ticker"])` — a workaround for
  exactly this bug.
- **Decision:** new PK = `(prediction_date, ticker, model_version_id)`. Keep the lifecycle
  tag as a plain *frozen column* (point-in-time value is legit; it just isn't identity).
  Rerun-safety returns (a re-backfill collides and overwrites). **Requires a table rebuild**
  (the `_migrate_add_cohort` pattern already does one) and **dedup the 53k prototype rows
  first** or the new PK rejects the rebuild. Prototype dups are archived cruft — safe to
  delete. **Does NOT affect sprint-14 studies** — those read parquet caches
  (`data/model_output_eda/**`), never `daily_predictions`.

### (b) `daily_predictions` is the ONLY serving store of scores
`v_d3_shortlist` / `v_d3_vip` carry `prob_elite` but are **views that JOIN
`daily_predictions`** — not independent storage. The sprint-14 parquet caches are a
separate research copy (full-universe, **prototype-era** scores) that live outside the
serving path — don't conflate "sprint-14 scores" with prod scores.

### (c) `v_d3_lifecycle` ≠ "all trend_ok" — a real population fork for the new table
The scored population (799) is NOT the same as the trend_ok universe (609 on 2026-07-16):
- **190 lifecycle rows are NOT trend_ok** (34 active + 156 removed) — a held/recently-exited
  name keeps being scored after its full C1–C9 `trend_ok` flag dies (the session closes only
  on `close < sma_50/150/200`, which lags the flag).
- **84 trend_ok∧breakout_ok names are excluded** from the pre_breakout arm (which requires
  `breakout_ok=FALSE`).

So the proposed new dashboard table ("all trend_ok, breakout as a column", ≈609) is a
**genuinely different population** from what is scored today (799): it drops the 190
held/removed-but-not-trend_ok names and adds back the 84 breakout-day names. This is a
scope decision, not a rename. The view is also **fat** (~80 cols: T3 features + all
fundamentals + valuation) because it doubles as a *display* source, not just a scoring
input — a candidate split (thin scoring view + separate display join) but not required.

### (d) Cohort/stage must be written at score time
Every downstream reader (per-cohort rank, dashboard filters, portfolio annotation) reads
the tag from `daily_predictions`, not from the live view. Whatever replaces `cohort`
(a Weinstein-style `stage` field) must be **written into `daily_predictions` at score
time**, exactly as cohort is now. Single integration point.

**Cooldown:** left AS-IS this session (see §4.5). Not a bug — a training de-correlation
policy. Do not remove as part of the rename.

## 1 · What renames, what doesn't (DECISION 2026-07-17)

| Surface | Name | Action | Cost |
|---|---|---|---|
| **The table** (`sepa_watchlist`) | KEEP | infra-internal; nobody user-facing reads it | none |
| **The phase id** (`pipeline_runs.phase_name`) | KEEP | persisted key; renaming strands audit history | none (avoided) |
| **The T3-gate string** (`SELECT DISTINCT ticker FROM sepa_watchlist`) | KEEP | pure pipeline plumbing | none |
| **The file/class** (`sepa_watchlist_manager.py` / `SepaWatchlistManager`) | KEEP | internal module identity | none |
| **The dashboard label / column header** the user sees | **RENAME** | this is the only misnamed *user-facing* surface | display-string edit |

**Rationale:** the "watchlist" name is only *wrong* where a user reads it and infers "things
I'm watching now" (it's actually an event log of trade sessions). Everywhere else it's an
internal identifier whose literal meaning nobody consumes. Keeping the infra name avoids the
DB migration, the persisted-key orphan decision, and the R2 MANIFEST churn entirely — all
the cost in the original draft was in the infra rename, which we are NOT doing.

**Scope of the actual rename:** wherever the dashboard prints "SEPA watchlist" (or similar)
as a heading/label/tooltip to the user, replace with an accurate term (e.g. "SEPA trade
sessions" / "SEPA setups"). Grep the dashboard render strings, not the table refs. The new
dashboard table (§0.5c) is where this lands — it gets an honest name from the start.

## 2 · Blast radius — REFERENCE MAP ONLY (not the plan of record)

> Retained from the original full-rename draft. This documents where the `sepa_watchlist`
> string lives IF an infra rename is ever revisited. Per §1 it is NOT happening this pass —
> the infra name stays. Skip to §4 for what actually executes.

**Table string — 15 files, ~44 refs.** Heaviest:
- `src/managers/sepa_watchlist_manager.py` (19) — also the FILE name + `class SepaWatchlistManager` + `src/managers/__init__.py` export

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

## 3 · Approach — display-label rename only

No DB migration, no file/class rename, no phase-id decision. Just the user-facing strings.

1. Grep the dashboard render layer for the user-visible name — `scripts/dashboard.py`,
   `scripts/pages/*.py`, and any `st.subheader`/`st.title`/label/tooltip literal containing
   "watchlist" / "SEPA watchlist". (NOT table refs, NOT SQL — those keep `sepa_watchlist`.)
2. Replace each with an accurate user term (e.g. "SEPA trade sessions" / "SEPA setups").
   Pick one term and use it consistently; note it in the glossary.
3. Smoke-test the dashboard renders. No view rebuild, no slim-DB rebuild, no MANIFEST edit
   (the table name is unchanged, so R2 parity is untouched).
4. This naturally folds into building the new dashboard table (§0.5c) — give that table an
   honest user-facing name from the start rather than renaming twice.

**What is explicitly NOT touched** (per §1): the `sepa_watchlist` table, the
`pipeline_runs.phase_name` phase-id, the T3-gate SQL, `sepa_watchlist_manager.py` /
`SepaWatchlistManager`, `scripts/backfill_sepa_watchlist.py`, the `build_dashboard_db.py`
MANIFEST entry. No backup-and-migrate ceremony is required because no persisted data or key
changes. (If a full infra rename is ever revisited, §2 is the map and the phase-id path (a)
"accept the orphan" was the prior recommendation — but that is out of scope now.)

## 4 · Sibling names

With the infra rename dropped (§1), these are display-surface notes only — no migration to
coordinate.

- **`screener_watchlist`** — the OTHER "watchlist". **DROP** (§4.6) — it's a duplicate of
  `sepa_watchlist` + derivable columns; replace with a view. Post-new-dashboard, not this
  pass.
- **`vip_watchlist`** / `vip_watchlist_manager.py` — likely a real watchlist; if so it can
  KEEP the name honestly (infra and display).

## 4.5 · Cooldown — LEFT AS-IS (decision 2026-07-17)

`sepa_watchlist` and `screener_watchlist` disagree on session *boundaries* because of the
**14-day cooldown**: sepa suppresses a re-entry within 14 days of a prior exit
([sepa_watchlist_manager.py:250](../../../../src/managers/sepa_watchlist_manager.py#L250));
`v_screener_dashboard` has no cooldown, so every trend run with a breakout is its own
session → **+2,764 sessions** (38,648 vs 35,884).

It is **not "hiding data"** — all OHLC/flags stay in `price_data`/`t2`/`t3`. The cooldown
only controls **how many trade-labels** the same price action produces: without it, one
choppy uptrend fragments into 2–3 overlapping labeled trades sharing the same forward
window (correlated samples → label inflation). Of the 3,170 no-cooldown re-entries, ~253
last ≤5 days (flicker the cooldown correctly kills); the median is 36 days (genuine
re-breakouts it also merges). **Correct for training, over-aggressive for display.**
Decision: leave as-is. Open (deferred): re-tune 14 → shorter if the merged genuine
re-breakouts matter for display.

## 4.6 · `screener_watchlist` — DROP (decision 2026-07-17), sequenced post-new-dashboard

**Column-wise, (a) `screener_watchlist` ≈ (b) `sepa_watchlist` enriched.** Shared session
identity: `ticker, entry_date, exit_date, status`. (a) adds only **derivable display
columns** (`company_name, sector, industry, market_cap, entry_price, close_price,
pct_return, days_held, price_date` — all reconstructable from `price_data`+`company_profiles`).
(b) adds only **lifecycle state** (`trend_ok, breakout_ok, cooldown_end, session_id`).
Neither holds session data the other's source can't rebuild.

**Row-wise they differ** — the cooldown (§4.5): (a) 38,648 sessions, (b) 35,884.

**The paradox you flagged, confirmed:** despite (b) being the "authoritative" gate, its
**session intervals are barely consumed** — `sepa_watchlist` is read almost entirely as
`SELECT DISTINCT ticker` (the T3 universe gate: `feature_pipeline.py`, `get_universe`,
`vip_watchlist_manager`). The **intervals that actually feed scoring come from (a)** —
`v_d3_lifecycle`'s cohort derivation joins `screener_watchlist`
([view_manager.py:924](../../../../src/managers/view_manager.py#L924)), and the old
dashboard reads (a) for every trade table. So today: **(b) supplies the ticker SET, (a)
supplies the session INTERVALS + display.**

**The concern (real):** the *scored cohort* is derived from (a) — the **no-cooldown**
table — while the *training universe* uses (b)'s cooldown boundaries. The model's scoring
population and its training population sit on **inconsistent session definitions.** That is
the latent issue, not the table name.

**Decision: DROP (a).** It is a duplicate of (b) enriched with derivable columns; (b) is an
earlier, authoritative pipeline step. Replace it with a **view** over `sepa_watchlist` and
repoint everything that reads (a) at that view.

> **Frame this correctly: the payload is a correctness fix, not a rename.** The rename (§1)
> is cosmetic — a display string. THIS step fixes the real issue above: the scored cohort is
> derived from the no-cooldown table (a) while the model trains on (b)'s cooldown boundaries,
> so scoring and training sit on **inconsistent session definitions**. Moving the cohort join
> onto a `sepa_watchlist`-sourced view is what makes them consistent. The table drop falls
> out of that fix; it is not the goal. Sequence and risk-gate it as a correctness change.

### The substitution the enrichment view makes (corrected 2026-07-17)

> **Correction:** the original draft framed this as two independent "gaps" and prescribed a
> `COALESCE(exit_date, latest)` fix for ACTIVE rows. That is **wrong about the mechanism**
> and was verified against code:
>
> - `v_screener_dashboard` (→ `screener_watchlist`) does NOT store ACTIVE `exit_date = NULL`.
>   Its intervals come from a `trades` CTE built off `price_data`/`t2` sessions
>   ([view_manager.py:1387-1394](../../../../src/managers/view_manager.py#L1387)):
>   `exit_date = COALESCE(px.next_date, sb.last_trend_date)` — **never NULL for anyone**.
>   ACTIVE/EXITED is a *derived status* (`exit_date >= latest_date`), not a NULL sentinel.
> - Raw `sepa_watchlist` (from `SepaWatchlistManager`) genuinely stores `exit_date = NULL`
>   for the 357 open sessions.
>
> So the two tables have **different interval provenance**, not the same value stored two
> ways. There is nothing to `COALESCE`-patch: `v_d3_lifecycle`'s cohort intervals today come
> from `v_screener_dashboard`'s **price-derived sessions**, not from `sepa_watchlist` rows.

**Therefore Gap 1 and Gap 2 are the SAME substitution, not two.** Repointing the cohort join
from `screener_watchlist` to a `sepa_watchlist`-sourced view **changes the interval source**
from price-derived sessions to `sepa_watchlist`'s own (cooldown-suppressed) rows. That single
change is exactly the ±2,764-session cooldown difference (§4.5). The enrichment view must:
1. Handle `sepa_watchlist`'s NULL ACTIVE `exit_date` so the `BETWEEN` interval join matches
   (`x BETWEEN a AND NULL` → NULL → no match; verified) — else all 357 open sessions drop
   from the `active` cohort. `COALESCE(exit_date, latest_trading_date)`.
2. Accept that the interval SET now follows `sepa_watchlist`'s cooldown boundaries, so some
   names re-tag active↔removed on boundary days.

**This is a behavior change, not a lift-verbatim.** The `_create_v_screener_dashboard`
SELECT/`with_status` block can be reused for the DISPLAY columns, but the session intervals
are now sourced from `sepa_watchlist`, not the price-derived `trades` CTE. **Guard = the
before/after cohort-tag diff (step 2), on a sample of dates; confirm the 357 ACTIVE names
still tag `active`.** Do NOT assume a no-op.

### Execution (5 steps, post-new-dashboard)
1. **New view** `v_sepa_sessions_enriched` — `sepa_watchlist` + display columns. Lift the
   `with_status` + final-SELECT block from `_create_v_screener_dashboard`
   ([view_manager.py:1413-1450](../../../../src/managers/view_manager.py#L1413)) verbatim,
   but source sessions from `sepa_watchlist` and apply the Gap-1 `COALESCE(exit_date,
   latest)` for ACTIVE. Columns: `entry_price` = `price_data.close` at entry;
   `close_price/price_date/pct_return/days_held` = the existing CASE logic; company fields
   from `company_profiles`.
2. **Repoint `v_d3_lifecycle`** cohort join `screener_watchlist` → the new view
   ([view_manager.py:924](../../../../src/managers/view_manager.py#L924)). **Run the Gap-2
   cohort-tag diff** (before/after on a sample of dates); confirm the 357 ACTIVE names still
   tag `active`.
3. **Repoint the remaining readers** at the new view (or confirm the new dashboard replaced
   them): `dashboard_utils.py` (trade tables at :390/:536/:1022/:1049/:1068),
   `show_screener.py`.
4. **Drop the table + its wiring:** `DROP TABLE screener_watchlist`, delete
   `_refresh_screener_watchlist` + its slot in the view-build order, and **remove its
   `build_dashboard_db.py` MANIFEST entry** (R2 parity — miss this and the remote app
   breaks).
5. **Verify:** rebuild views, rebuild slim DB, dashboard smoke-test, and run one scoring
   pass — confirm active-name count and cohort counts hold vs the pre-drop baseline.

**Sequencing:** post-new-dashboard cleanup (step 3 readers depend on the new pages landing),
NOT part of the display-rename pass. Inherits the §4.5 cooldown decision — moving to (b) *is*
choosing cooldown-merged sessions for the model.

## 5 · Checklist — display rename (this is small now)
- [ ] Grep dashboard render strings for the user-visible "watchlist" label (§3 step 1).
- [ ] Replace with one consistent honest term; add it to the glossary.
- [ ] Dashboard smoke-test. No DB backup / view rebuild / MANIFEST edit needed (table
      name unchanged → T3 gate + R2 parity untouched, so `sh019` timing is a non-issue).
- [ ] `screener_watchlist` KEEP (§4.6); `vip_watchlist` display-label only.
- [ ] Cooldown: **leave as-is** (§4.5).
- [ ] Ideally fold into building the new dashboard table (§0.5c) — name it honestly once.

**Decoupled follow-ups (NOT the rename — separate sessions):**
- [ ] `daily_predictions` PK rebuild → `(prediction_date, ticker, model_version_id)`; dedup
      53k prototype dual-cohort rows first; keep tag as frozen column (§0.5a).
- [ ] Drop `screener_watchlist` → view over `sepa_watchlist` (§4.6, 5 steps). Watch Gap 1
      (ACTIVE exit_date COALESCE — else 357 held names drop from scoring) + Gap 2 (cooldown
      tag-shift diff). After new dashboard lands.
- [ ] New "all trend_ok" dashboard table: confirm the 799→609 population fork (§0.5c).
