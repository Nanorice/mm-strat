# Phase 2 — Screener Membership Redesign
> Created: 2026-03-23 | Status: MOSTLY COMPLETE — Steps 1–3, 5 done. Step 4 partially done (Phase 3 join done, Phase 5 join pending). Step 6 pending.

## Goal

Replace the current `screener_members` (current-state table) with an **event-log design** that supports point-in-time universe membership across the full backfilled history. The result is a correct investable universe for every trading day, usable by both the historical backtest and live daily pipeline.

---

## Confirmed Design Decisions

| Parameter | Value | Rationale |
|---|---|---|
| Evaluation cadence | Daily | Event-log means negligible storage cost |
| Price filter | `close >= 5` (spot) | Broad admission; SEPA filter is the real quality gate |
| Volume filter | `avg_volume_20d >= 100K` | 20d average; spot vol too noisy |
| Market cap filter | `close × shares_ffill >= 150M` | Spot close × forward-filled shares |
| Grace period | 126 consecutive failing days (~6 months) | Counter increments daily on fail, resets on pass |
| Entry | Immediate on first passing day | No dwell requirement |
| Re-entry after exit | Immediate on first passing day | Grace period handles noise |
| Storage | Event log — write only on status change | ~tens of thousands of rows for full history |

---

## Schema

### New table: `screener_membership`

```sql
CREATE TABLE screener_membership (
    ticker              VARCHAR     NOT NULL,
    effective_date      DATE        NOT NULL,   -- date this status took effect
    is_active           BOOLEAN     NOT NULL,   -- TRUE=entered, FALSE=exited
    criteria_version    INTEGER     NOT NULL,
    last_price          DOUBLE,
    avg_volume_20d      DOUBLE,
    market_cap          DOUBLE,
    consec_fail_days    INTEGER     DEFAULT 0,  -- 0 when is_active=TRUE; count when failing
    PRIMARY KEY (ticker, effective_date)
)
```

### Drop / migrate

- `screener_members` — keep during transition as a compatibility view, drop after Phase 3/5 join is updated
- `screener_criteria_versions` — unchanged; `criteria_version` FK references it

### Compatibility view (during transition)

```sql
CREATE VIEW screener_members AS
WITH latest AS (
    SELECT ticker, is_active,
           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY effective_date DESC) as rn
    FROM screener_membership
)
SELECT ticker,
       is_active,
       last_price,
       avg_volume_20d,
       market_cap
FROM latest WHERE rn = 1;
```

---

## Event-Log Logic

### Evaluation query (runs daily, for `target_date`)

```sql
WITH shares_ffill AS (
    -- Forward-fill shares_outstanding per ticker up to target_date
    SELECT ticker,
           LAST_VALUE(shares IGNORE NULLS) OVER (
               PARTITION BY ticker ORDER BY date
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS shares_ffill
    FROM shares_outstanding
    WHERE date <= target_date
    QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) = 1
),
vol_20d AS (
    -- 20-day average volume per ticker as of target_date
    SELECT ticker,
           AVG(CAST(volume AS BIGINT)) AS avg_volume_20d
    FROM (
        SELECT ticker, volume
        FROM price_data
        WHERE date <= target_date
        QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) <= 20
    )
    GROUP BY ticker
),
latest_price AS (
    SELECT ticker, close
    FROM price_data
    WHERE date = target_date
),
candidates AS (
    SELECT
        p.ticker,
        p.close,
        v.avg_volume_20d,
        p.close * s.shares_ffill AS market_cap
    FROM latest_price p
    JOIN vol_20d v ON p.ticker = v.ticker
    LEFT JOIN shares_ffill s ON p.ticker = s.ticker
)
SELECT ticker, close, avg_volume_20d, market_cap,
       (close >= 5
        AND avg_volume_20d >= 100000
        AND market_cap >= 150000000) AS passes
FROM candidates
```

### State machine (per ticker, runs after evaluation query)

```
passes = TRUE:
    consec_fail_days = 0
    if was inactive → write event (is_active=TRUE, effective_date=target_date)
    if was active   → no write (no change)

passes = FALSE:
    consec_fail_days += 1
    if consec_fail_days < 126 → no write (grace period, stays active)
    if consec_fail_days == 126 → write event (is_active=FALSE, effective_date=target_date)
    if consec_fail_days > 126  → already inactive, no write
```

**Key invariant**: `consec_fail_days` is NOT stored in `screener_membership` (that's an event log, not a state store). It is computed at runtime by counting consecutive failing days from `price_data` backward from `target_date` for any ticker currently active. See checkpoint 3 below for how this is derived without a separate state table.

---

## Feature Pipeline Join

Phase 3 and Phase 5 currently do:
```sql
INNER JOIN screener_members WHERE is_active = TRUE
```

After this change, they join on:
```sql
-- Get active universe for a given feature_date
WITH membership AS (
    SELECT ticker, is_active,
           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY effective_date DESC) as rn
    FROM screener_membership
    WHERE effective_date <= feature_date
)
-- INNER JOIN above WHERE rn = 1 AND is_active = TRUE
```

This is point-in-time correct — the pipeline sees the universe as it was on `feature_date`, not today's universe projected backward.

---

## Implementation Steps

### Step 1 — Schema migration ✅ DONE
- [x] Create `screener_membership` table — done in `ScreenerManager._ensure_schema()`
- [x] Seed `screener_criteria_versions` with v2 criteria row (price≥5, vol≥100K, mcap≥150M) — seeded on init
- [x] Create compatibility view `screener_members` — created in `_ensure_schema()`

---

### Step 2 — Rewrite `ScreenerManager` ✅ DONE
- [x] `evaluate_and_log(target_date)` — single-date incremental path (daily pipeline)
- [x] `backfill_all(start_date, end_date)` — vectorised SQL full-history pass (replaces per-date loop from original plan)
- [x] `get_active_tickers(as_of_date)` — point-in-time lookup
- [x] Grace period via gaps-and-islands window function (no per-ticker Python)
- [x] `rowcount` bug fixed — uses before/after COUNT instead of `.rowcount`

---

### Step 3 — Historical backfill script ✅ DONE + EXECUTED
- [x] `scripts/backfill_screener_membership.py` — delegates to `backfill_all()` (single SQL pass, not a date loop)
- [x] `--reset` flag with confirmation prompt for full rebuild
- [x] Pre-flight stats + post-run audit hint
- [x] Idempotent (`INSERT OR IGNORE`)

**Run:**
```
python scripts/backfill_screener_membership.py
python tools/audit_t2_membership.py --warn-only
```

---

### Step 4 — Update Phase 3 and Phase 5 joins ⚠️ PARTIAL
- [x] `FeaturePipeline.compute_t2_screener_features()` — Phase 3 `price_base` CTE already uses point-in-time `screener_membership` interval join
- [ ] `FeaturePipeline._compute_full_rebuild()` — Phase 5 `price_base` CTE still uses `screener_members` (old view) — **needs migration**
- [x] `ViewManager` — no references to `screener_members` (already clean)

**Checkpoint**: After Phase 5 join is updated, run `FeaturePipeline.compute_all('2024-01-15')` and verify `daily_features` row count matches active universe size on that date.

---

### Step 5 — Update daily orchestrator ✅ DONE
- [x] `_run_phase_2_screener_membership()` calls `evaluate_and_log(target_date)`
- [x] `--phase-2-only` flag added to `scripts/run_daily_pipeline.py`

---

### Step 6 — Drop `screener_members` view ⏳ PENDING (blocked by Step 4)
- [ ] Migrate Phase 5 `price_base` CTE to use `screener_membership` directly (Step 4 above)
- [ ] Verify no remaining `screener_members` references: `grep -r "screener_members" src/`
- [ ] Drop the `screener_members` view from `_ensure_schema()`

**Checkpoint**: `grep -r "screener_members" src/` returns zero hits.

---

## Files Changed

| File | Change |
|---|---|
| `src/managers/screener_manager.py` | Full rewrite of membership logic |
| `src/feature_pipeline.py` | Update `price_base` CTE in Phase 3 + Phase 5 |
| `src/managers/view_manager.py` | Update views referencing `screener_members` |
| `src/orchestrators/daily_pipeline_orchestrator.py` | Update Phase 2 call + return dict |
| `scripts/backfill_screener_membership.py` | New script |

---

## What Is NOT Changing

- `screener_criteria_versions` table — unchanged, new criteria row added
- `company_profiles.is_active` — separate concern (ingestion gate), untouched
- `_get_active_criteria()` — reused as-is
- Phase 1 ingestion, Phase 4 regime, Phase 6-9 — no changes

---

## Open Questions ✅ RESOLVED

- [x] `shares_outstanding` gaps — **forward-fill accepted**. Tickers with no shares data at all have `market_cap=0` and fail the 150M filter. This is correct conservative behaviour. The `audit_t2_membership.py` market_cap section quantifies impact.
- [x] Criteria v2 `effective_date` — **`2020-01-01`** used, matching existing convention.