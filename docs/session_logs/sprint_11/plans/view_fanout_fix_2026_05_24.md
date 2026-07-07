# Proposal: Fix `v_d2_features` Fan-Out (and Downstream `v_d2_training` / `v_d3_deployment`)

> **Status:** DRAFT — diagnosis complete, fix proposed, NOT applied.
> **Owner:** Hang
> **Created:** 2026-05-24
> **Blocks:** All end-to-end framework re-evaluation of M01_baseline_v0.1.
> **Linked:** [evaluation_implementation_plan_2026_05_23.md](../plans/evaluation_implementation_plan_2026_05_23.md),
> master handover [2026-05-23_handover.md](../session_logs/2026-05-23_handover.md) item #1.

---

## TL;DR

`v_d2_features` (and therefore `v_d2_training` / `v_d3_deployment` which both
build on it) returns **multiple rows per `(ticker, date)`** with inconsistent
fundamentals. Cause: two correlated as-of subqueries in
[src/managers/view_manager.py:405-485](../../src/managers/view_manager.py#L405-L485)
that join `fundamental_features` and `shares_history` using a `WHERE date =
(SELECT MAX(...))` pattern. If either side has multiple rows tied at the same
max date for a given ticker, the join fans out.

The `feature_parity_check` gate added in Phase A catches this because the two
views' `ROW_NUMBER() = 1` pick different "winning" rows.

**Proposed fix:** replace both correlated subqueries with a `QUALIFY ROW_NUMBER
() OVER (...)` pattern inside CTEs that deduplicate at the source. This is a
deterministic, single-row-per-(ticker, date) result, and it's also faster
because DuckDB can evaluate the window function in one pass instead of
re-running the subquery per outer row.

---

## Diagnosis

### Where the fan-out comes from

Both joins in `_create_v_d2_features` use the same correlated-subquery
as-of pattern:

```sql
-- fundamental_features:
LEFT JOIN fundamental_features ff
    ON d1.ticker = ff.ticker
    AND ff.filing_date = (
        SELECT MAX(filing_date) FROM fundamental_features
        WHERE ticker = d1.ticker AND filing_date <= d1.date
    )

-- shares_history (only if table exists):
LEFT JOIN shares_history sh
    ON d1.ticker = sh.ticker
    AND sh.date = (
        SELECT MAX(date) FROM shares_history
        WHERE ticker = sh.ticker AND date <= d1.date
    )
```

The query is "most recent filing on or before `d1.date`". The bug:
if `fundamental_features` has two rows with the same `(ticker, filing_date)`
(e.g., an amended filing on the same date, or a deduplication gap in the
ingestion layer), **both rows survive the join** — one `d1` row becomes two
`v_d2_features` rows with conflicting fundamentals.

Same logic for `shares_history` — if the shares table has two rows on the
same date for a ticker (e.g., intraday split vs end-of-day, or vendor
duplicate), the join multiplies.

### Why the parity check trips

`feature_parity_check` (Phase A §2.1.3) samples N rows from `v_d2_training`
and N from `v_d3_deployment` and compares feature vectors at matching
`(ticker, date)` keys. Inside both views, the deduplication is
`ROW_NUMBER() OVER (...) = 1` — but DuckDB's `ROW_NUMBER()` over a tied set
returns rows in **non-deterministic order** unless you add an explicit
tiebreaker. So `v_d2_training` picks "row A" and `v_d3_deployment` picks
"row B" for the same key. The vectors differ. Gate fails.

**This means XGBoost has been training on ambiguous data.** Every batch of
training samples could draw a different "winning" fundamental row for the
same (ticker, date), and the model averages over the inconsistency. Not a
silent failure — a silent *degradation*.

---

## Proposed Fix

Replace both correlated subqueries with **single-pass deduplication CTEs**
that use `QUALIFY ROW_NUMBER() OVER (...) = 1` with a deterministic
tiebreaker:

```sql
WITH ff_dedup AS (
    SELECT
        ticker, filing_date, fiscal_period,
        revenue, net_income, eps_diluted, ...  -- all the columns we project
    FROM fundamental_features
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY ticker, filing_date
        ORDER BY fiscal_period DESC NULLS LAST  -- tiebreaker: prefer annual over quarterly, deterministic
    ) = 1
),
ff_asof AS (
    -- As-of join: for each (ticker, d1.date), pick the latest filing_date <= d1.date
    SELECT
        d1.ticker, d1.date AS d1_date,
        ff.*,
    FROM v_d1_candidates d1
    INNER JOIN ff_dedup ff
        ON ff.ticker = d1.ticker
        AND ff.filing_date <= d1.date
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY d1.ticker, d1.date
        ORDER BY ff.filing_date DESC
    ) = 1
)
SELECT
    d1.*,
    ff.revenue, ff.net_income, ff.eps_diluted, ...
FROM v_d1_candidates d1
LEFT JOIN ff_asof ff
    ON d1.ticker = ff.ticker AND d1.date = ff.d1_date
...
```

The `QUALIFY` clause is DuckDB-native and avoids the correlated-subquery
trap entirely. The deduplication at the source (`ff_dedup`) ensures each
`(ticker, filing_date)` has exactly one row before the as-of logic runs.

**Same pattern for `shares_history`.** Wrap it in `sh_dedup` + `sh_asof`
CTEs.

---

## Why This Is Better Than `ROW_NUMBER() = 1` After the Join

The current views downstream (`v_d2_training`, `v_d3_deployment` — note
those don't actually have `ROW_NUMBER` themselves; the parity check is
where dedup happens for sampling) silently inherit the fan-out. Fixing it
at the source (`v_d2_features`) means:

1. **Single source of truth.** Every consumer of `v_d2_features` gets
   the same dedup. Today's bug would re-surface if someone built a new
   view on `v_d2_features` without knowing to add their own dedup.
2. **Deterministic.** `QUALIFY ROW_NUMBER() OVER (... ORDER BY <tiebreaker>)`
   is reproducible across runs. Today's `MAX(filing_date)` correlated
   subquery has no tiebreaker — same SQL, different results across runs.
3. **Faster.** DuckDB evaluates window functions in a single pass; the
   correlated subquery is O(N²) in the worst case (re-runs per outer row).
   That's likely why probe queries OOM the session today.

---

## Risk & Verification Plan

### Risks

1. **The `fiscal_period DESC` tiebreaker is a guess.** I assumed annual
   filings are preferred over quarterly when both share a `filing_date`,
   but the actual ingestion semantics may differ. Verify with a small
   query before locking it in:

   ```sql
   SELECT ticker, filing_date, fiscal_period, COUNT(*)
   FROM fundamental_features
   WHERE ticker = 'AAPL'
   GROUP BY 1, 2, 3
   HAVING COUNT(*) > 1
   LIMIT 20;
   ```

2. **`shares_history` tiebreaker unknown.** Need a similar probe to find
   a sensible ORDER BY column. If only `(ticker, date)` matters, may
   need `ORDER BY <ingested_at> DESC` if that column exists.
3. **`v_d2_features` row counts will change.** Almost certainly *decrease*
   (we're removing duplicate rows). Any downstream consumer that relies
   on `COUNT(*)` from `v_d2_features` will see a drop. Need to audit
   what reads from this view:
   - `v_d2_hydrated` (and alias `v_d2r_hydrated`)
   - `v_d2_training`
   - `v_d3_deployment`
   - Anything ad-hoc in scripts/ that queries `v_d2_features` directly
4. **Model retraining may be required.** If the prod model
   (`m01_prototype_2003_2026_20260514_233125`) was trained on the
   ambiguous data, its weights bake in the averaging. Retraining on
   the clean data may change accuracy — could go up (less noise) or
   down (less data leakage from inconsistent fundamentals). Either way,
   the post-fix model is what should be promoted, not the pre-fix one.

### Verification Plan

1. **Probe queries (scoped, no OOM)** — confirm `fundamental_features`
   and `shares_history` actually have dups per the suspected keys:
   ```sql
   -- Run against 3 tickers, not the whole table
   SELECT ticker, filing_date, COUNT(*) FROM fundamental_features
   WHERE ticker IN ('AAPL','NVDA','TSLA') GROUP BY 1,2 HAVING COUNT(*) > 1;
   ```
2. **Build the new view in a parallel name** — `v_d2_features_v2` — so
   the old view stays in service during testing.
3. **Compare row counts:**
   ```sql
   SELECT 'old' AS variant, COUNT(*) FROM v_d2_features WHERE date >= '2025-01-01'
   UNION ALL
   SELECT 'new', COUNT(*) FROM v_d2_features_v2 WHERE date >= '2025-01-01';
   ```
4. **Spot-check key joins** — verify that for a sample of `(ticker, date)`
   pairs, the chosen fundamentals match what a human would call "the most
   recent filing as of date."
5. **Re-run feature_parity_check** against `v_d2_features_v2` and the
   matching `v_d3_deployment_v2`. Expect: gate passes.
6. **Cut over** — rename `v_d2_features_v2` → `v_d2_features` (DuckDB
   transactional rename), and update `view_manager.py` to generate the
   new pattern by default.
7. **Retrain `M01_baseline_v0.2`** without `--skip-parity`. Promote
   only if gates pass.

---

## Effort

- Probe queries: 30min
- Write new view + parallel build + comparison: 1.5h
- Verify with `feature_parity_check`: 30min
- Cut over + retrain + re-evaluate under new framework: 2-3h (mostly
  training wallclock)

**Total: ~half-day for the fix, plus ~half-day for retraining +
re-evaluation.** Matches the master handover's estimate.

---

## What This Unblocks

Once the fan-out is fixed and `M01_baseline_v0.2` is retrained:
- `--with-walk-forward --with-regime-decomp --with-perm-importance
  --with-pretrain-audit` all run cleanly without `--skip-parity`
- The §6 promotion gate enforces all gates added in Phases A/B/C
- The walk-forward backtest harness can be wired into the training
  script (Phase B/C handover #1)
- The first quarterly PSI report (§5.2, once implemented) has a
  clean baseline to compare against
- The dashboard's `daily_predictions` toggle shows predictions from
  a model that was actually validated, not just trained
