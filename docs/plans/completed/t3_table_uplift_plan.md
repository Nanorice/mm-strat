# T3 Dense Pipeline Uplift Plan (v2 — Universe Density)

> Anchors are by symbol/string, not line number. Files have moved recently — locate by
> grep for the strings shown in code blocks below, not by line number.

## Objective

Convert `t3_sepa_features` from a sparse breakout-only table to a **dense daily-features
table over the screener-active universe**, with `trend_ok` and `breakout_ok` preserved as
explicit per-row columns.

**Conceptual model**: T3 is the daily feature snapshot of the **investable universe**.
Membership is sourced from `screener_membership` (point-in-time `is_active=TRUE`).
For every `(ticker, date)` where the ticker was screener-active on that date, T3 stores
all model features plus the day's `trend_ok` and `breakout_ok` flags. Rows are never
deleted — once written, history is permanent. Daily increments only INSERT new rows for
the new date.

This replaces the previous sparse design where T3 only contained the single `breakout_ok=TRUE`
day per session.

---

## Why This Matters

### Current state (sparse, breakout-only)
- T3 has ~13–100 rows per day (only days where `trend_ok AND breakout_ok` both TRUE).
- `v_d2_hydrated` joins T3 across full hold period → NULL `sma_50`/`atr_20d` on every
  non-entry day → adaptive stop-loss silently degrades to entry-day-frozen ATR.
- `get_daily_holding_dataframe()` cannot show feature evolution during a hold.
- M01 score can only be computed on entry day, not tracked through the hold or applied
  to non-breakout universe tickers.
- No way to see how a ticker's M01 score evolved before it broke out.

### After uplift (dense over screener universe)
- T3 has ~2,500 rows per day (full screener-active universe).
- `v_d2_hydrated` gets valid `sma_50`/`atr_20d` on every hold day → adaptive stop-loss works.
- M01 daily scoring runs on the entire investable universe — supports both pre-breakout
  watchlist scoring and continuous in-hold tracking.
- Backtest can observe dynamic feature/score evolution before, during, and after setups.
- Training data: filter `WHERE trend_ok AND breakout_ok` for entries; filter
  `WHERE trend_ok` for trend-active universe; filter on neither for full universe.

---

## Design Decisions (Resolved)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Membership source = `screener_membership`** | Already implements grace period (126 days), criteria versioning, gaps-and-islands streak detection. Single source of truth for "tradeable today." |
| 2 | **No DELETE/UPDATE on T3** | INSERT OR IGNORE only. If a ticker exits the screener on Tuesday, Wednesday's run simply doesn't generate a Wednesday row. Historical rows are permanent. |
| 3 | **Both `trend_ok` and `breakout_ok` stored as columns** | Defensive — downstream filters explicitly rather than trusting an upstream filter. Required for use case (a) training data filtering. |
| 4 | **Table name unchanged: `t3_sepa_features`** | Avoid a rename refactor across views, scripts, registry, docs. Accept the misnomer. |
| 5 | **Membership join via point-in-time subquery on `screener_membership`** | Use `is_active=TRUE` as-of `wv.date`. Pure SQL, no Python loop. |
| 6 | **Backfill scope: 2001+ after test window passes** | First validate on 2020-01-01 → 2024-12-31 with `recreate_t3=True`, then full 2001+. |
| 7 | **`v_sepa_candidates` filter added** | Preserve current `get_sepa_candidates` / `get_candidate_stats` semantics — view filters `WHERE trend_ok = TRUE AND breakout_ok = TRUE`. |
| 8 | **Backfill must be vectorised** | The standalone `backfill_t3_sepa_features.py` script is dropped in favor of `compute_t3_features(recreate_t3=True)` as the single canonical entry point. |

---

## Scope of Changes

### 1. `src/feature_pipeline.py` — Replace breakout filter with membership filter

There is **only one** site in `compute_t3_features()` with the `trend_ok=TRUE AND
breakout_ok=TRUE` filter — the outer SELECT, around the line:
```sql
INNER JOIN t2_screener_features t2
    ON wv.ticker = t2.ticker AND wv.date = t2.date
    AND t2.trend_ok = TRUE AND t2.breakout_ok = TRUE
```

**Pre-build a materialised membership snapshot CTE** for the run window (avoid correlated
subqueries — DuckDB's planner historically does not push them efficiently, and this query
is now ~100× larger). Add this CTE *before* the outer SELECT, alongside the existing
`with_velocity` CTE:

```sql
,active_universe AS (
    -- Point-in-time screener membership for every (ticker, date) in the run window.
    -- ASOF LEFT JOIN finds the latest membership event ≤ date for each row.
    SELECT d.ticker, d.date
    FROM (
        SELECT DISTINCT ticker, date FROM with_velocity
    ) d
    ASOF LEFT JOIN screener_membership sm
        ON d.ticker = sm.ticker
       AND sm.effective_date <= d.date
    WHERE sm.is_active = TRUE
)
```

Then change the outer SELECT to:
```sql
FROM with_velocity wv
INNER JOIN active_universe au
    ON wv.ticker = au.ticker AND wv.date = au.date
LEFT JOIN t2_screener_features t2
    ON wv.ticker = t2.ticker AND wv.date = t2.date
LEFT JOIN t2_regime_scores r ...
LEFT JOIN fundamental_features ff ...
LEFT JOIN shares_history sh ...
WHERE wv.date BETWEEN '{start_date}' AND '{end_date}'
```

Notes:
- DuckDB supports `ASOF JOIN` natively — this is the canonical pattern for point-in-time
  membership lookups. If the executor finds an issue with `ASOF` (e.g. on the installed
  DuckDB version), fall back to the `ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY
  effective_date DESC)` + INNER JOIN pattern from `screener_manager.py:286-287`. Do NOT
  use a correlated WHERE-EXISTS — the outer query is already heavyweight.
- `INNER JOIN t2 → LEFT JOIN t2` so a screener-active ticker still gets a T3 row even on a
  rare T2 gap day. **However see §1b below** — without an inner-CTE adjustment, gap-day
  rows are dropped earlier in the pipeline regardless of this LEFT JOIN.
- This is the **only** filter site in `compute_t3_features()`. The "sibling SELECT for
  warmup" mentioned in earlier drafts does not exist — `with_velocity`/`per_ticker` already
  load full warmup history from `price_data` and don't filter on T2 flags.

---

### 1b. `src/feature_pipeline.py` — Inner-CTE join decision (`with_velocity`)

The `with_velocity` CTE (where pct_chg deltas, EMA ratios, slopes, velocity features are
computed) currently contains:
```sql
FROM per_ticker pt
INNER JOIN t2_screener_features t2
    ON pt.ticker = t2.ticker AND pt.date = t2.date
```

This INNER JOIN drops every (ticker, date) without a T2 row *before* the outer membership
filter ever runs. The outer LEFT JOIN in §1 above is irrelevant if the row already
vanished here.

**Decision: keep this INNER JOIN as-is (Option A).** Accept that "screener-active without
a T2 row on the same day" is essentially zero in practice (T2 is computed for the full
universe). T3 row count becomes `screener_active ∩ has_t2_row`, not pure `screener_active`.

The alternative (LEFT JOIN here) would force ~30 columns to NULL on gap-day rows for
marginal benefit. Skip it unless the verification step reveals a meaningful gap-day
population.

Update §7 doc wording to reflect this: T3 is dense over `screener_active ∩ has_t2_row`,
not pure screener-active.

---

### 2. `src/feature_pipeline.py` — Schema additions to `_create_t3_table()`

In the DDL block inside `_create_t3_table()`, alongside the other T2 carry-forward columns
(near `consolidation_width`):
```sql
trend_ok BOOLEAN,
breakout_ok BOOLEAN,
```

In the INSERT column list:
```
trend_ok,
breakout_ok,
```

In the final SELECT:
```sql
t2.trend_ok,
t2.breakout_ok,
```

These are nullable (LEFT JOIN preserves rows where T2 has no match for that ticker × date).

---

### 3. `src/feature_pipeline.py` — Bump `EXPECTED_T3_COLUMN_COUNT`

Current value at top of file: `EXPECTED_T3_COLUMN_COUNT = 146`. Bump by exactly the number
of new columns added in §2 (today: `trend_ok` + `breakout_ok` = 2). Target: `148`.

**Pre-flight check:** before bumping, confirm the existing tripwire passes on the current
codebase (run a small `compute_t3_features` for a 1-week window and verify no
`RuntimeError`). If it already raises, the count is out of sync with reality and you must
fix that drift first — bumping by +2 from a wrong baseline won't help.

Note: the tripwire counts `information_schema.columns` (DDL-level), so it catches
DDL ↔ EXPECTED drift but **not** INSERT-list ↔ SELECT-list misalignment. DuckDB will
silently pair columns by position if list lengths match. Cross-check INSERT list and
SELECT list lengths visually after editing.

---

### 4. `src/managers/view_manager.py` — `v_sepa_candidates` filter (REQUIRED)

`v_sepa_candidates` is consumed by `get_sepa_candidates()` and `get_candidate_stats()`.
Both expect rows to represent **breakout candidates**, not the full trend-active universe.
Without an explicit filter, dense T3 inflates these consumers' results ~30×.

In `_create_v_sepa_candidates()`, add a `WHERE` clause to the view definition:
```sql
WHERE f.trend_ok = TRUE AND f.breakout_ok = TRUE
```

This preserves current consumer semantics. The dense data is still available — consumers
needing the full universe can query `t3_sepa_features` directly or via a new view.

---

### 5. `src/managers/view_manager.py` — `v_d2_hydrated` (no change required)

Already uses `LEFT JOIN t3_sepa_features` for `sma_50`/`atr_20d`. Dense T3 fixes the silent
NULL bug automatically. No view edit needed — but verify in step 4 of the verification plan.

---

### 6. `scripts/backfill_t3_sepa_features.py` — Replace with chunked-resumable wrapper

The current standalone script (its own SQL filter/SELECT) is dropped — it cannot stay in
sync with `compute_t3_features()`'s logic. Replace with a thin CLI wrapper that:

1. Iterates over **quarterly chunks** (`(year, quarter)` tuples — Q1: Jan–Mar, Q2: Apr–Jun,
   Q3: Jul–Sep, Q4: Oct–Dec). Quarterly granularity means a mid-chunk crash costs ~15 min
   to recover, not ~60 min.
2. **Pre-chunk sanity check** (mid-chunk crash recovery): if `(year, quarter)` is not in
   the checkpoint file but T3 has *any* rows for that quarter, DELETE those rows before
   running. Guarantees the chunk runs cleanly through SQL INSERT → vol-adj → TS alpha
   without risk of leftover rows from a prior crashed run having NULL alpha columns.
3. For each chunk, calls `FeaturePipeline.compute_t3_features(start_date, end_date)` —
   idempotent via `INSERT OR IGNORE` on `(ticker, date, feature_version)` PK.
4. **Only after the call returns successfully**, write a checkpoint line to
   `logs/t3_backfill_progress.log` (timestamp, year, quarter, rows inserted, wall time,
   T3 total row count as a sanity field).
5. On startup, read the checkpoint log and skip chunks already marked complete.
6. CLI flags: `--from YYYY-Q[1-4]`, `--to YYYY-Q[1-4]`, `--restart` (drops T3 table and
   starts over from `--from`), `--force-rebuild YYYY-Q[1-4]` (DELETE + re-run a single
   quarter without dropping the whole table — useful for fixing a feature bug).

**Failure modes — what survives a crash:**

| Crash point | T3 state | Restart behavior |
|---|---|---|
| During SQL INSERT | DuckDB rolls back partial INSERT (transactional) | Pre-chunk sanity sees 0 rows, runs cleanly |
| Between INSERT and vol-adj | Quarter populated, alpha cols NULL | Pre-chunk sanity sees rows but no checkpoint → DELETE + retry |
| During vol-adj UPDATE | Some alpha cols set, some NULL | Same as above — DELETE + retry |
| During TS alpha UPDATE | Some TS alpha cols set, some NULL | Same as above — DELETE + retry |
| After last UPDATE, before checkpoint write | Quarter fully complete, no checkpoint line | Same as above — DELETE + retry (wasteful but safe) |

The last case is wasteful (rerunning a complete quarter) but rare. Write the checkpoint
immediately after the `compute_t3_features` call returns to minimise the window:

```python
# scripts/backfill_t3_sepa_features.py
QUARTERS = {
    1: ('01-01', '03-31'),
    2: ('04-01', '06-30'),
    3: ('07-01', '09-30'),
    4: ('10-01', '12-31'),
}

def chunk_dates(year: int, q: int) -> tuple[str, str]:
    start_md, end_md = QUARTERS[q]
    return f'{year}-{start_md}', f'{year}-{end_md}'

def main():
    args = parse_args()  # --from, --to, --restart, --force-rebuild
    pipeline = FeaturePipeline(...)
    con = duckdb.connect(pipeline.db_path)

    # --restart: drop T3 entirely. Used once for cold start.
    if args.restart:
        con.execute("DROP TABLE IF EXISTS t3_sepa_features")
        pipeline._create_t3_table(con)
        clear_checkpoints()

    done = load_checkpoints()  # set of (year, quarter) tuples

    # --force-rebuild YYYY-Q[1-4]: DELETE one quarter + clear its checkpoint
    if args.force_rebuild:
        y, q = parse_yq(args.force_rebuild)
        s, e = chunk_dates(y, q)
        con.execute(f"DELETE FROM t3_sepa_features WHERE date BETWEEN '{s}' AND '{e}'")
        done.discard((y, q))
        clear_checkpoint_yq(y, q)

    for year, q in iter_chunks(args.from_yq, args.to_yq):
        if (year, q) in done:
            print(f"[SKIP] {year}-Q{q} (checkpoint)")
            continue

        s, e = chunk_dates(year, q)

        # Pre-chunk sanity: clean up any partial state from a prior crashed run
        partial = con.execute(
            f"SELECT COUNT(*) FROM t3_sepa_features WHERE date BETWEEN '{s}' AND '{e}'"
        ).fetchone()[0]
        if partial > 0:
            print(f"[CLEANUP] {year}-Q{q} has {partial:,} orphaned rows — deleting")
            con.execute(f"DELETE FROM t3_sepa_features WHERE date BETWEEN '{s}' AND '{e}'")

        # Run chunk
        t0 = time.time()
        rows = pipeline.compute_t3_features(start_date=s, end_date=e)
        elapsed = time.time() - t0

        # Checkpoint immediately after successful return
        save_checkpoint(year=year, quarter=q, rows=rows, elapsed=elapsed)
        print(f"[DONE] {year}-Q{q}: {rows:,} rows in {elapsed:.0f}s")
```

**Do NOT** call `compute_t3_features(recreate_t3=True)` per chunk — that drops the whole
T3 table and loses every prior chunk. The wrapper handles `DROP`/`CREATE` itself in the
`--restart` branch, so always call `compute_t3_features(start, end)` (no `recreate_t3`).

**Checkpoint file format** (`logs/t3_backfill_progress.log`, append-only, plain text):
```
2026-05-07T14:23:11Z  year=2001 q=1  rows=121584  elapsed=534s  t3_total=121584
2026-05-07T14:32:45Z  year=2001 q=2  rows=128720  elapsed=531s  t3_total=250304
...
```

`load_checkpoints()` parses this file and returns `{(2001, 1), (2001, 2), …}`. If the file
is missing, returns the empty set (cold start).

---

### 6b. Performance optimisations to apply *before* kicking off backfill

The plan as written takes ~16h projected for 2001–2026. Three targeted changes drop that
to ~8–10h with low implementation risk. **Apply these before running the full backfill**;
they each reduce wall-clock per chunk and compound.

The bottleneck per chunk is the **TS alpha pass** (~15–40 min of the ~30–60 min/chunk
total). Profile it before optimising — if your test window numbers don't match these
estimates, re-evaluate which optimisation is worth it.

#### Optimisation A: Replace `multiprocessing.Pool` with `ThreadPoolExecutor` for alpha parallelism

`compute_alpha_features()` ([feature_pipeline.py:1093-1103](src/feature_pipeline.py#L1093-L1103))
uses `multiprocessing.Pool` to run 18 alphas in parallel. Each worker pickles the full
~1.1M-row DataFrame on Windows (no `fork` syscall) — ~80MB × 8 workers = ~640MB of pickle
overhead per chunk. The actual alpha compute is mostly numpy/Cython under `groupby.rolling`,
which **releases the GIL**, so threads work fine and skip the pickle entirely.

**Change:** swap `from multiprocessing import Pool` → `from concurrent.futures import
ThreadPoolExecutor`, and replace the `Pool(...).imap_unordered` block with a
`ThreadPoolExecutor.submit` loop. Keep the env-var gates (`USE_PARALLEL_ALPHAS`,
`ALPHA_WORKERS`) so behavior is tunable.

**A/B test before committing:** run one quarter both ways (current `Pool` vs new
`ThreadPoolExecutor`). If threads are not faster, leave the existing `Pool` code in place
— some alphas may be GIL-bound in pure-Python paths. **Estimated savings: 1.5–2× on the
TS alpha step**, but verify empirically.

#### Optimisation B: Replace DELETE+UPDATE-temp+INSERT pattern in `_write_alpha_columns` with direct UPDATE FROM

[feature_pipeline.py:1155-1186](src/feature_pipeline.py#L1155-L1186) currently does:
1. `CREATE TEMP TABLE _alpha_chunk AS SELECT * FROM target WHERE date BETWEEN ...` (copies ~600K rows × 150 cols)
2. `DELETE FROM target WHERE date BETWEEN ...`
3. `UPDATE _alpha_chunk SET col = src.col FROM alpha_src ...`
4. `INSERT INTO target SELECT * FROM _alpha_chunk` (copies it all back)

This is ~30–60s of pure write-back overhead per chunk × ~100 chunks = ~50–100 min of the
total backfill. The copy-out + copy-back exists for historical reasons (likely a prior
DuckDB version not supporting `UPDATE ... FROM` cleanly). **Modern DuckDB supports it.**

**Change:** replace the four-step block with a direct `UPDATE target FROM alpha_src` scoped
by date range:
```python
con.register('alpha_src', alpha_df)
set_clause = ', '.join(f"{c} = src.{c}" for c in cols)
con.execute(f"""
    UPDATE {target_table} t
    SET {set_clause}
    FROM alpha_src src
    WHERE t.ticker = src.ticker
      AND t.date = src.date
      AND t.date BETWEEN '{min_date}' AND '{max_date}'
""")
```

The `t.date BETWEEN ...` predicate scopes the index probe so the cost is O(chunk), same as
the current pattern. **Estimated savings: ~30s/chunk × 100 chunks = ~50 min total.**

**Caveat:** verify with a small chunk first that the UPDATE writes the same values as the
old pattern (column-by-column diff query). If for any reason the old DELETE+INSERT path
was masking a bug, this will surface it.

#### Optimisation C: Lazy alpha pre-compute

[feature_pipeline.py:1052-1067](src/feature_pipeline.py#L1052-L1067) pre-computes 9
intermediates for every alpha run, but ~3 of them are used by 1–2 alphas only:
- `open_sum5`, `returns_sum5` → only `alpha008`, `alpha019`
- `returns_sum250` → only `alpha101`

For a 1.1M-row frame, each `groupby.rolling(...).sum()` is ~5–15s. Computing them only
when the requested alpha set actually needs them shaves ~20–40s/chunk.

**Change:** wrap each pre-compute in a check against the requested alpha set:
```python
requested = set(alpha_cols or ALPHA_COLS)
if {'alpha008', 'alpha019'} & requested:
    df['open_sum5'] = df.groupby('ticker')['open'].transform(lambda x: x.rolling(5).sum())
    df['returns_sum5'] = df.groupby('ticker')['wq_returns'].transform(lambda x: x.rolling(5).sum())
if 'alpha101' in requested:
    df['returns_sum250'] = df.groupby('ticker')['wq_returns'].transform(lambda x: x.rolling(250).sum())
```

For T3's `ALPHA_COLS_TS` set (which includes alpha008/019/101), all three still run during
backfill — but the lazy pre-compute pays off whenever a future caller requests a subset.
**Estimated savings: marginal on backfill (alphas all requested), but free correctness
hygiene.** Apply alongside A and B; don't ship it standalone.

#### What NOT to do (deferred)

- **Cross-chunk warmup sharing** (load the 365d warmup once, share across 4 quarters):
  biggest theoretical win (~2–3× total speedup) but requires refactoring
  `compute_t3_features()` to accept a pre-loaded DF. That signature is shared with the
  daily orchestrator path. Out of scope for this plan — revisit if A+B+C don't get the
  backfill under your tolerance.
- **Sub-quarterly chunking** (monthly): more loads, more transactions, slower in aggregate.
- **Reducing `warmup_days` from 365**: alpha101 needs 250d rolling sum. Don't touch it.

#### Verification of optimisations

Run the test window (2020-01-01 → 2024-12-31, full or one year of it) twice — once on
`infra_uplift` HEAD before A/B/C, once after — and confirm:
1. Wall-clock improves (no regression).
2. Spot-check 5 random `(ticker, date)` rows: every alpha column matches between the two
   runs to within float tolerance. **Any mismatch on optimisation B is a blocker** — it
   means the new UPDATE pattern produced different values, which would silently corrupt
   downstream M01 training. Halt and investigate.

---

### 7. `docs/manual_for_me.md` — Phase 5 design notes

Update the line that currently reads:
> "T3 only stores rows where `trend_ok AND breakout_ok` — these flags are NOT stored in T3
> (implicit TRUE for all rows)."

to:
> "T3 stores one row per day per ticker that is screener-active on that date (sourced from
> `screener_membership`). Both `trend_ok` and `breakout_ok` are explicit columns — neither
> is implicit. Filter on `trend_ok=TRUE AND breakout_ok=TRUE` to get entry candidates;
> filter on `trend_ok=TRUE` to get the trend-active watchlist; filter on neither to get
> the full investable universe."

Update the row-count estimate from `~13–100 rows/day` to `~2,500 rows/day`.

---

## What Does NOT Need to Change

| Component | Reason safe |
|---|---|
| `v_d1_candidates` | Session detection reads T2 (`trend_c8_base` CTE). Trade boundaries are still defined by T2's `trend_ok AND breakout_ok` — T3 is only joined for feature values. |
| `v_d2_training` | Derives from `v_d1_candidates`. Training set boundary defined by T2 logic, not T3 density. |
| `v_d3_deployment` | Reads last 252 days of T3 for scoring — now correctly scores the full universe instead of only breakout days. This is the desired behavior change for use case (b). |
| `v_d2_hydrated` | Already a LEFT JOIN to T3. Dense T3 fixes the silent NULL bug. |
| Post-INSERT Python (TS alphas, vol-adj) | Both methods load full price_data history for screener tickers and write back to existing T3 rows. More rows = more write-backs, but zero code change. |
| Fundamentals join | Already a LEFT JOIN with point-in-time subquery. Works across all dates. |
| M03 join | Already a LEFT JOIN on date. Works correctly. |

---

## Training Integrity Guarantee

`v_d1_candidates` detects SEPA sessions exclusively from `t2_screener_features` (the
`trend_c8_base` CTE reads `t2.trend_ok` and `t2.breakout_ok`). The `entries` CTE filters
`WHERE trend_ok AND breakout_ok` in T2 to find entry dates. T3 is joined only at step 6
(`enriched` CTE) for feature values.

Making T3 dense over the universe therefore cannot introduce non-setup rows into
`v_d2_training`. The training dataset boundary is defined by T2 logic, not T3 density.

---

## Storage & Performance

| Metric | Sparse (current) | Dense over universe (after) |
|---|---|---|
| Rows per day | ~70 | ~2,500 |
| Total rows (2020–2026) | ~500K | ~16M |
| Total rows (2001–2026) | n/a | ~50M |
| Daily SQL INSERT | <1s | ~1–2s |
| Daily total (incl. TS alpha + vol-adj passes) | ~60–120s | ~65–130s (+5–10s) |
| Backfill 2020–2026 (no optimisations) | ~10 min | ~2–4 hours |
| Backfill 2001–2026 (no optimisations) | n/a | ~12–16 hours |
| Backfill 2001–2026 (with §6b A+B+C) | n/a | ~6–10 hours |

DuckDB handles 50M rows trivially. **Daily-run impact is small (+5–10s):** the TS alpha
and vol-adj passes already load 365d × full T2 universe (~3K tickers) regardless of T3
density — T3 density only affects the final UPDATE-back match count, which scales linearly
with T3 rows in the run window (negligible for one day).

**Backfill is where the cost lives:** a quarterly chunk's UPDATE-back hits ~150K T3 rows
instead of ~18K, and the in-memory pandas DataFrame for TS alphas is the same size whether
you backfill 1 year or 1 day (always loads 365d warmup from price_data + T2). So per-chunk
wall time is dominated by the alpha compute step, not by T3 density.

**Backfill must be vectorised within a chunk — no per-date Python loop.** Implementation must:
- Run SQL INSERT in quarterly-chunk windows (see §6).
- Within a chunk, run Python TS alphas / vol-adj across the full ticker × date matrix in
  one pass, not per-date.
- Use multiprocessing/threads (see §6b option A) where it applies.

**Resumability: quarterly chunks + checkpoint file.** See §6 for the wrapper design.
Each chunk is one quarter (~150K T3 rows). Wall time per chunk: estimate ~10–25 min after
§6b optimisations. Crash mid-chunk → that quarter re-runs cleanly (pre-chunk DELETE +
`INSERT OR IGNORE`); other quarters are skipped via the checkpoint log.

**Stop-conditions during backfill** — if any of these trigger, halt and investigate before
continuing:
- A chunk takes >2× the test-window-extrapolated estimate.
- A chunk inserts <50% of expected rows (membership filter or T2 coverage issue).
- The Python TS alpha pass OOMs (try a single quarter; if still OOM, see §6b for monthly
  fallback — but expect aggregate slowdown).

---

## Verification Plan

After implementing, run for a test window (2020-01-01 → 2024-12-31) with `recreate_t3=True`:

1. **Row count check**:
   ```sql
   SELECT date, COUNT(*) FROM t3_sepa_features GROUP BY date ORDER BY date LIMIT 5;
   ```
   Expect ~2,500 rows/day. If <500/day, membership filter is wrong. If >5,000/day,
   either screener criteria changed or membership join is duplicating.

2. **Membership alignment check**:
   ```sql
   WITH active_on_date AS (
     SELECT '2024-03-10'::DATE AS d, ticker
     FROM (
       SELECT ticker, is_active,
              ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY effective_date DESC) AS rn
       FROM screener_membership
       WHERE effective_date <= '2024-03-10'
     ) WHERE rn = 1 AND is_active = TRUE
   )
   SELECT
     (SELECT COUNT(*) FROM t3_sepa_features WHERE date = '2024-03-10') AS t3_rows,
     (SELECT COUNT(*) FROM active_on_date) AS sm_active;
   ```
   `t3_rows` should match `sm_active` ±1% (gap-day tolerance).

3. **Flag distribution check**:
   ```sql
   SELECT trend_ok, breakout_ok, COUNT(*)
   FROM t3_sepa_features GROUP BY 1, 2;
   ```
   Expect: most rows `trend_ok=FALSE` or NULL, a small fraction `trend_ok=TRUE`,
   tiny fraction `trend_ok=TRUE AND breakout_ok=TRUE` (~0.1–1%).

4. **Stop-loss NULL fix**:
   ```sql
   SELECT date, sma_50, atr_20d, sl_level
   FROM v_d2_hydrated
   WHERE trade_id = '<known multi-week trade id>'
   ORDER BY date;
   ```
   Expect non-NULL `sma_50`/`atr_20d` on **every** hold day (was NULL on non-entry days).

5. **Training isolation check**:
   ```sql
   SELECT COUNT(*) FROM v_d1_candidates
   WHERE date BETWEEN '2024-01-01' AND '2024-06-30';
   ```
   Row count must be unchanged vs. pre-uplift (same trades detected).

6. **`v_sepa_candidates` filter check**:
   ```sql
   SELECT COUNT(*) FROM v_sepa_candidates
   WHERE date = (SELECT MAX(date) FROM t3_sepa_features);
   ```
   Must equal pre-uplift count (preserved consumer semantics).

7. **Column count tripwire**:
   Verify `compute_t3_features()` does not raise `RuntimeError` after INSERT.
   Confirms DDL, INSERT list, SELECT list, `EXPECTED_T3_COLUMN_COUNT` are in sync.

8. **Backfill timing sanity**:
   Time the test window. Extrapolate to 2001–2026. If projection >8 hours, stop and
   profile before running the full backfill.

---

## Execution Sequence (Implementation Session)

**Phase 1 — Code edits (uplift)**

1. Confirm current tripwire passes (run small `compute_t3_features` window — see §3 pre-flight).
2. Edit `_create_t3_table()` DDL — add `trend_ok BOOLEAN`, `breakout_ok BOOLEAN`.
3. Edit INSERT column list — add `trend_ok`, `breakout_ok`.
4. Edit final SELECT — add `t2.trend_ok`, `t2.breakout_ok`.
5. Bump `EXPECTED_T3_COLUMN_COUNT` (146 → 148). **Do this immediately after steps 2–4 so
   DDL/SELECT/tripwire move together — separate from the membership-filter change so any
   tripwire failure points at the right edit.**
6. Replace breakout filter with `active_universe` CTE (§1) — single site.
7. Edit `_create_v_sepa_candidates()` — add `WHERE f.trend_ok = TRUE AND f.breakout_ok = TRUE`.
8. Replace `scripts/backfill_t3_sepa_features.py` with chunked-resumable wrapper (§6).
9. Update `docs/manual_for_me.md` Phase 5 design notes.

**Phase 2 — Correctness verification (1 quarter, no optimisations)**

10. Run the new wrapper on a **single quarter** to validate code edits:
    `--from 2024-Q1 --to 2024-Q1 --restart`. Run verification plan steps 1–7. Time it.

**Phase 3 — Performance optimisations (apply §6b A, B, C)**

11. Apply §6b optimisation A (`ThreadPoolExecutor` swap). A/B test on one quarter — if
    threads are not faster, revert and keep `Pool`.
12. Apply §6b optimisation B (direct `UPDATE FROM`). **A/B verify**: spot-check 5
    `(ticker, date)` rows have identical alpha values vs Phase 2's run. Mismatch = halt.
13. Apply §6b optimisation C (lazy alpha pre-compute). Free hygiene; no A/B needed.
14. Re-run `--from 2024-Q1 --to 2024-Q1 --force-rebuild 2024-Q1` to confirm optimised path
    still passes verification steps 1–7 and writes identical alpha values.

**Phase 4 — Test window backfill**

15. Run full test window (2020–2024) with optimisations: `--from 2020-Q1 --to 2024-Q4
    --restart`. Time it. If extrapolated 2001+ backfill exceeds 12 hours, stop and profile
    before continuing.

**Phase 5 — Production backfill**

16. Run `--from 2001-Q1 --to 2026-Q2` (no `--restart` — resumable from checkpoint file).
    Run overnight; the wrapper handles crashes and resume automatically.

---

## Rollback Plan

If verification fails or row counts explode unexpectedly:

1. Revert all source edits (git checkout for the modified files).
2. Drop the polluted T3:
   ```sql
   DROP TABLE t3_sepa_features;
   ```
3. Recreate via the reverted code path: `compute_t3_features(start='2020-01-01', recreate_t3=True)`.
4. Refresh views: `ViewManager.create_all()`.

T3 contains no irreplaceable data — it is fully derivable from `daily_features` +
`t2_screener_features` + `screener_membership`. Rebuild time ~10 min for the sparse version.
