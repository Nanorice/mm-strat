# Design — Lifecycle-tagged daily scoring (replaces status-gated cohorts)

*Authored 2026-06-19. Supersedes `todo_score_held_watchlist_daily.md` (the `cohort='active'`
carry-forward view was a v1 workaround for exactly the gap this fixes structurally).*
*Target: Sprint 12, next session. Scope: `src/` + orchestrator + dashboard loader, not a pure dashboard change.*

> **✅ STATUS: IMPLEMENTED 2026-06-19** (branch `infra_uplift`). See the **§7 Implementation
> record** at the bottom for what shipped, the build-time decisions taken, and the one place
> reality diverged from this design (the 8 "missing held names" are stale-price, not t3 holes).

---

## 1. The structural flaw

Phase 7.4 selects the scoring population **by status** and bakes status into the row key:

```python
# _log_prod_model_predictions — daily_pipeline_orchestrator.py:1536
for cohort, candidates in (
    ("breakout",     self._fetch_breakout_candidates(target_date)),     # v_d3_deployment
    ("pre_breakout", self._fetch_pre_breakout_candidates(target_date)), # trend_ok & !breakout_ok
):
    engine.score_and_log(candidates, target_date, cohort, self.db_path)
```

Two things are wrongly coupled:

- **What to score** (the population) — should be the names currently in the SEPA lifecycle, period.
- **How to tag a row** (its lifecycle state) — a *derived label* off the same feature row.

Consequences of gating-by-status:

1. **Not MECE.** `breakout ∪ pre_breakout` ≠ the held population. A name that has broken
   out, is in an open trade, but is not re-qualifying as a candidate today falls in the
   gap. This is the population the user actually tracks — and it is **never re-scored**.
   Evidence: ENPH (held since 2026-05-20) has 4 `daily_predictions` rows total; nothing
   after 2026-06-02 despite still being ACTIVE on 2026-06-18.
2. **`breakout` is redundant.** A name is `active` from the day it breaks out, so the
   `breakout` cohort surfaces nothing the active snapshot doesn't. `breakout_ok=TRUE` is
   an **entry transition event**, not a monitored state.
3. **Carry-forward staleness is a symptom, not the disease.** `load_scored_watchlist`
   shows e.g. 06-15's score on 06-18 only because no 06-18 row exists for the name
   (`ROW_NUMBER() … ORDER BY prediction_date DESC`, take rn=1). When the dashboard is
   read for 06-18, a stale score from the last candidate day is surfaced silently. Fix
   the population and this special-case deletes itself — no carry-forward needed.

**The score is genuinely status-independent** — `ScoreEngine` runs the same model on the
same feature contract regardless of label. Segmenting the population *before* scoring buys
nothing and manufactures the gap.

---

## 2. The lifecycle model (3 states)

The SEPA lifecycle is governed by two t3 flags **plus** the watchlist exit rule. Crucially,
the *only* trend rule that governs held/exit status is **C1+C2+C6** (the watchlist exit
rule), not the strict C1–C9 `trend_ok`. `trend_ok` is an **entry gate only**.

| Tag | Rule | Trend definition |
|---|---|---|
| **pre_breakout** | in setup, not yet entered | `trend_ok` (C1–C9) `= TRUE AND breakout_ok = FALSE` |
| **active** | breakout fired, trade open | `screener_watchlist.status = 'ACTIVE'` (C1+C2+C6 holds) |
| **removed** | trend broke, trade closed (recent) | `screener_watchlist.status = 'EXITED'` AND `exit_date` within ~20 trading days |

`breakout_ok = TRUE` is the **pre_breakout → active** transition, not a 4th cohort.

### Why `active` ≠ `trend_ok`

A name can be `trend_ok = FALSE` (full C1–C9 broke) yet still `active`, because the
watchlist holds it while C1+C2+C6 (close > SMA50/150/200) holds. ENPH: `trend_ok` went
FALSE on 06-03 but it is still ACTIVE on 06-18. That is **correct** — it is `active`,
not in any gap. (Verified: of the 1,814 no-trend t3 rows on 06-18, 50 are ACTIVE held.)
So the held set **cannot** be derived from flags alone — it requires the watchlist join.

---

## 3. Scoring population — lifecycle scope (≈1.7×, not full t3)

Score, per `target_date`, exactly the union of the three lifecycle states:

```
population = pre_breakout (trend_ok & !breakout_ok)
           ∪ active        (watchlist status = ACTIVE)
           ∪ removed        (watchlist status = EXITED AND exit_date within last ~20 trading days)
```
deduplicated by ticker (a name resolves to one tag — priority below).

### Sizing (verified 2026-06-18)

| Population | rows/day | growth |
|---|---|---|
| Current (breakout + pre_breakout) | ~444 | 1× |
| **Lifecycle scope (chosen)** | **~750–800** | **~1.7×** |
| Full t3 panel | 2,402 | ~5.4× |

### What we deliberately skip (recorded scope decision)

The t3 panel on 06-18 is 2,402 rows. Decomposition:

| trend_ok | breakout_ok | rows | disposition |
|---|---|---|---|
| T | T | 100 | breakout firing → entry event (→ active) |
| T | F | 382 | **pre_breakout** — scored |
| F | T | 106 | edge: breakout signal, trend not intact |
| F | F | 1,814 | no valid trend — **of which 50 are ACTIVE held (scored), 1,764 skipped** |

The **1,764 pure no-trend, not-held** names are dormant t3 universe members in no
lifecycle state. Correctly out of scope — we don't accrue history for names nobody tracks.
(User-confirmed fact-check: yes, the residual ~1,764 are t3 tickers with no valid trend.)

---

## 4. Implementation

### 4a. Single scoring pass (orchestrator)

Replace the two status-gated passes in `_log_prod_model_predictions`
(`daily_pipeline_orchestrator.py:1536`) with **one** lifecycle-population fetch + one
`score_and_log`, then derive the tag per row.

- New helper `_fetch_lifecycle_candidates(target_date)`: the union query above, reading
  `t3_sepa_features` (feature-hydrated like `v_d3_prebreakout`/`v_d3_deployment` so the
  feature contract matches the model's feature list) LEFT JOIN `screener_watchlist`.
  Carries a derived `cohort` column per row.
- Tag priority (one tag per ticker per day): **active > removed > pre_breakout**.
  (A name that is both held and re-setting-up is reported as `active` — it's a held
  position first.)
- Drop `_fetch_breakout_candidates` / the `breakout` pass from the prod path. (Shadow
  divergence still scores `breakout` only — leave `_log_shadow_predictions_and_divergence`
  unchanged; it compares the acted-on list, a separate concern.)

### 4b. Rank within the lifecycle population, not per status

`log_daily_predictions` currently ranks **within (`prediction_date`, `cohort`)**
(`prediction_logger.py:142`) and hard-validates `cohort ∈ {breakout, pre_breakout}`
(`:115`). Two changes:

- **Extend the cohort allow-list** to `{pre_breakout, active, removed}` (drop `breakout`
  from prod; shadow keeps writing `breakout` so keep it valid). The PK already includes
  `cohort` (migration `2026_06_12_add_cohort_to_daily_predictions.sql`) — **no schema
  change**, the new tag values are just new rows.
- **Rank semantics:** rank must be a true rank of the *held + setup* population per day,
  not per-tag. Compute `rank_within_day` over the **whole lifecycle population for the
  date** (one rank across all three tags), so the bump chart shows one coherent ranking.
  This means ranking happens **before** the per-cohort write, or the write logs all tags
  in one call and ranks across them. Adjust `log_daily_predictions` to rank within
  `prediction_date` across the lifecycle tags (keep per-cohort ranking only for the
  shadow `breakout` path).
  *(Decision to confirm at build time: one rank across tags vs. rank within each tag.
  Default = one rank across the population, since the user wants a single held-population
  bump chart.)*

### 4c. `removed` window

`removed` = EXITED with `exit_date >= target_date - ~20 trading days`. A name shows in
history for ~1 month after exit, then drops out — keeps the table bounded and shows the
exit + immediate aftermath. (Calendar-day approximation of 20 trading days ≈ 28 days is
fine; or join the trading-day spine.)

### 4d. Remove carry-forward in the dashboard loader

`load_scored_watchlist` (`dashboard_utils.py:374`) currently picks the latest
`prediction_date` per (ticker, entry_date) via `ROW_NUMBER() … DESC`. With daily lifecycle
scoring, **drop the carry-forward**: join on `prediction_date = <as-of date>` and show the
**same-day** score. A genuinely unscored name → NULL (a real signal it fell out of t3),
not a silently stale value. The ACTIVE/EXITED score-semantics branch collapses: ACTIVE =
same-day score; EXITED = its score on the exit day (last `removed` row).

### 4e. t3 completeness for held names (the one piece of new pipeline work)

A name can only be scored if it has a t3 row that day. **8 of 412 ACTIVE names are missing
from t3 on 06-18** (the [t3 forward-only holes] issue — lazy materialization leaves holes
behind the candidate frontier; F1 self-heal helps but doesn't cover held names that left
the frontier). Held + recently-removed names must be force-materialized into
`t3_sepa_features` each day regardless of candidate status, or they're unscorable. This is
the only change that is *new computation*, not relabeling — likely an extension of the F1
self-heal to cover the active/removed watchlist set.

### 4f. Binary backfill

`m01_binary` (shadow) has `breakout` rows only — no pre_breakout/active/removed history.
On promotion (or now, as shadow), run `scripts/backfill_daily_predictions.py` over the new
lifecycle population so its bump chart isn't empty. The score column stays model-agnostic
via `COALESCE(prob_class_3, prob_class_1)`.

---

## 5. Net effect

- One scoring pass, MECE over the SEPA lifecycle. The "eventual upgrade" and the "2b
  follow-up" collapse into this single change.
- `daily_predictions` grows ~1.7× (trivial; already in the slim-DB MANIFEST).
- Carry-forward special-case **deleted**, not maintained. Dashboard shows same-day scores;
  NULL means genuinely unscored.
- The 2b bump chart consumes `cohort='active'` for free (loader already takes `cohort`).
- The held-population watchlist bump chart becomes buildable with real per-day history.

## 6. Open items to confirm at build time

1. **Rank scope** (4b): one rank across the lifecycle population (default) vs. per-tag rank.
2. **Tag priority** (4a): `active > removed > pre_breakout` — confirm a held name that's
   re-setting up reports as `active`.
3. **`removed` window length** (4c): ~20 trading days (chosen) — confirm calendar approx vs
   trading-day spine.
4. **t3 self-heal scope** (4e): extend F1 to force-materialize the active + recently-removed
   watchlist set each day.

---

## 7. Implementation record (2026-06-19) ✅

Shipped on `infra_uplift`. Tests: 32 green (`test_prediction_logger`, `test_view_manager`,
`test_score_lookup_persistence`). Backfilled 120,515 rows / 174 dates; slim dashboard DB
rebuilt (781 MB — no size change). `daily_predictions` is ~20 MB / 179K rows (<0.03% of the
69 GB main DB) — the ~1k rows/day population is **not** a size concern (verified, left as-is).

### What shipped

- **`v_d3_lifecycle`** (`view_manager.py`, created AFTER `_refresh_screener_watchlist` —
  it joins `screener_watchlist`). MECE union with a derived `cohort` per (ticker,date),
  resolved by **trade interval** (see decision 1 below): `active` if `f.date` ∈
  `[entry_date, exit_date]`, `removed` if within `REMOVED_WINDOW_CALENDAR_DAYS=28` after
  exit, else `pre_breakout`. Same feature hydration as `v_d3_prebreakout`. Verified on NESR
  (3 trades): tags transition exactly on entry/exit boundaries.
- **One scoring pass** — `_log_prod_model_predictions` does one `_fetch_lifecycle_candidates`
  + `groupby('cohort')` + per-tag `score_and_log`. Dropped the prod `breakout` pass; shadow
  still scores `breakout`.
- **`prediction_logger._VALID_COHORTS`** = `{breakout, pre_breakout, active, removed}`. PK
  already had `cohort` → no schema change.
- **`load_scored_watchlist`** — carry-forward DELETED; strict same-day join
  `prediction_date = sw.price_date`. NULL = genuinely unscored.
- **`backfill_daily_predictions.py`** — new default `--cohort lifecycle` (pulls
  `v_d3_lifecycle`, logs per (date, tag)).
- **t3 self-heal** (`_t3_holed_dates`) extended to also expect t3 rows for ACTIVE +
  recently-EXITED watchlist names (`LIFECYCLE_REMOVED_WINDOW_DAYS=28`, kept in sync with the
  view constant).

### Build-time decisions (differ from §6 defaults)

1. **Rank = PER-TAG** (within each cohort), not one rank across the population (§4b default).
   Simpler and keeps `score_and_log` semantics; the view's `cohort` column drives the split.
2. **`removed` window = 28 calendar days** (§4c calendar approximation, not trading-day spine).
3. **EXITED loader rows = STRICT same-day** (no `≤ exit_date` fallback). Historical exit
   scores reappear only after the lifecycle backfill writes their past `active`/`removed`
   rows — a backfill gap, not logic loss. Post-backfill coverage: ACTIVE 407/412,
   EXITED 1,877 scored (old loader was 1,641).
4. **t3 self-heal extended** (§4e), with the caveat below.

### Where reality diverged (§4e was incomplete)

The 8 ACTIVE-but-missing-from-t3 names on 06-18 (TERN/TPH/KALV/VRE/BK/EHAB/THR/RZB) are **not
materialization holes** — they have **stale `price_data`** (last bar days–weeks behind the
frontier) → no t2 row → unscorable, and the self-heal can't fix them (it materializes t3
*from* t2). They stay ACTIVE forever because `v_screener_dashboard` keys status off per-ticker
latest close. Correct behavior: same-day join → NULL (truthful "no current data"). The
self-heal extension still helps held names that **have** t2 but drifted behind the candidate
frontier. **Fix is operator-driven deactivation** (`tools/deactivate_tickers.py` →
`is_active=FALSE` cascades through `v_screener_dashboard` → `screener_watchlist` →
`v_d3_lifecycle`), surfaced from Pipeline Health gated on days-stale + error type — tracked as
a **separate Sprint 13 task**, deliberately out of lifecycle-scoring scope.

### Not done (follow-ups)

- **Shadow `m01_binary` backfill** (§4f) — not run; its bump chart stays empty until
  `backfill_daily_predictions.py --model-version-id m01_binary_... --cohort lifecycle` is run
  (on promotion or now-as-shadow).
- **2,042 orphan prod `breakout` rows** left in place (harmless — loader prefers lifecycle tag
  per ticker/date; user chose to leave them).
