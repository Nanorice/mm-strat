# Replacement plan — `tests/test_feature_pipeline.py`

**Context (2026-07-19).** 14 tests across `TestPhaseA/B/C/TestFullPipeline` were deleted.
They drove `FeaturePipeline.compute_base_features(...)` and asserted against a
`daily_features` table. Both are gone: the method is a tombstone raising
`NotImplementedError`, and `daily_features` is absent from the production DB.
They had been erroring (not failing) since the t2/t3 split, so they were providing
**zero** signal — deleting them loses no coverage that was actually running.

## Verification performed before deleting

| Claim | How it was checked | Result |
|---|---|---|
| `daily_features` no longer exists | `information_schema.tables` on prod DB | absent; `t2_screener_features`, `t3_sepa_features` present |
| `compute_base_features` is dead | repo-wide grep for callers | only the deleted tests + its own tombstone |
| `compute_alpha_features` is dead | repo-wide grep for callers | **NO — it is live** (see gap below) |

## The real coverage gap this opens

`compute_alpha_features` is live production code with two call sites, and it is now
untested. It is parameterised, and the two paths differ in ways worth pinning:

| Call site | target_table | alpha_cols | warmup_table |
|---|---|---|---|
| `feature_pipeline.py:446` (T2) | `t2_screener_features` | `ALPHA_COLS_XS` | — |
| `feature_pipeline.py:859` (T3) | `t3_sepa_features` | `ALPHA_COLS_TS` | `t2_screener_features` |

`compute_cross_sectional_ranks` (default `target_table='t2_screener_features'`) is
likewise uncovered.

## Proposed replacement tests

Build one synthetic fixture DB (`price_data`, `company_profiles`,
`screener_membership` — reusable from the deleted `setUpModule`, recoverable via
`git show HEAD:tests/test_feature_pipeline.py`), then:

1. **`test_t2_alphas_populate_xs_columns`** — run `compute_t2_screener_features`,
   assert every `ALPHA_COLS_XS` column exists in `t2_screener_features` and is
   non-null for a majority of rows.
2. **`test_t3_alphas_populate_ts_columns`** — run T2 then `compute_t3_features`,
   assert `ALPHA_COLS_TS` present and populated in `t3_sepa_features`.
3. **`test_t3_writeback_is_scoped_to_chunk_window`** — the regression the comment at
   `feature_pipeline.py:857` documents: without `end_date`, the writeback spans to
   `MAX(t2.date)` and corrupts later chunks. Run two adjacent chunks, assert the
   first chunk's rows are unchanged after the second runs. **Highest value test here** —
   it pins a known, commented, silent-corruption bug.
4. **`test_screener_filter_excludes_inactive`** — port of the old `test_screener_filter`:
   a ticker in `price_data` but inactive in `screener_membership` must not appear in
   `t2_screener_features`.
5. **`test_cross_sectional_ranks_in_range`** — port of `test_universe_rank_range`,
   retargeted to `t2_screener_features`.

**Deliberately not ported:** `test_base_column_count` / `test_total_column_count`
(asserted `>= 60` / `>= 100` columns). Column-count assertions on a wide feature table
break on every legitimate feature addition and never localise a fault.

## Open question for the author

Tests 1/2/5 assert "column exists and is mostly non-null" — a smoke test. Whether the
intended contract is stronger (specific alpha values, a golden frame) is a modelling
decision, not one to infer from the deleted code. Confirm before writing.
