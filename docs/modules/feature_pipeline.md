# Module: Feature Pipeline (`src/feature_pipeline.py`)

> Verified against code 2026-07-18. Class `FeaturePipeline`. Two-tier feature
> architecture: T2 = broad universe (cross-sectional context), T3 = SEPA universe
> (dense time-series features). Replaces the retired `daily_features` table name —
> the physical tables are `t2_screener_features` and `t3_sepa_features`.

## Public API

```python
FeaturePipeline(db_path, use_backfill=False, feature_version='v3.1')
    .compute_all(...)                       # T2 then T3
    .compute_t2_screener_features(start_date, warmup_days=400, end_date)
    .compute_t3_features(start_date, end_date)
    .compute_ema_features(...)              # Phase B-EMA (pandas ewm)
    .compute_alpha_features(...)            # Phase B (XS alphas, multiprocessing)
    .compute_cross_sectional_ranks(target_table='t2_screener_features', ...)
```

`EXPECTED_T3_COLUMN_COUNT = 144` is a hard tripwire — the T3 write fails if the
column count drifts. Update it together with any DDL change.

## Phase 3 — T2 screener features (`t2_screener_features`, 68 cols, ~9.9M rows)

Computed daily for every active screener member (~2,400 tickers/day). Sub-phases:

| Sub-phase | Method | What |
|---|---|---|
| A — SQL | CTE chain in `compute_t2_screener_features()` | OHLCV carry-through, SMAs 20/50/150/200, RS line + RS rating, 52w/20d ranges, volume ratios, ATR (10/14/20/50) + NATR, VCP ratio (`atr_10/atr_50`), consolidation width, SEPA flags `trend_ok`/`breakout_ok` |
| B — Python | `compute_alpha_features()` (multiprocessing) | 9 cross-sectional alphas: 001, 002, 004, 008, 011, 013, 015, 019, 060. Must run on the full universe for valid XS computation. |
| B-EMA — Python | `compute_ema_features()` (`pandas.ewm`) | EMAs 8/21/50/100/200 (recursive — not expressible in the SQL pass) |
| C — SQL | `compute_cross_sectional_ranks()` | `RS_Universe_Rank`, `RS_Sector_Rank`, `RS_vs_Sector`, `Sector_Momentum`, `RS_Industry_Rank`, `RS_vs_Industry`, `Industry_Momentum` |

**RS formula**: `0.4·mom_63d + 0.2·mom_126d + 0.2·mom_189d + 0.2·mom_252d`
(momentum-weighted — NOT a benchmark ratio; `price_vs_spy` is the separate
benchmark-ratio column used by C9 only).

**The SEPA gate** (definition of record: [glossary.md](../architecture/glossary.md) §2):

```sql
trend_ok  = C1-C9 Minervini trend template:
            close > SMA150 AND close > SMA200 AND SMA150 > SMA200
            AND SMA200 rising (vs 20d lag) AND SMA50 > SMA150 AND close > SMA50
            AND close > low_52w * 1.3 AND close > high_52w * 0.85
            AND price_vs_spy > price_vs_spy_ma63
breakout_ok = new 20d high AND volume / vol_avg_50_prev > 1.3
```

`vol_avg_50_prev` excludes the current bar so the breakout day doesn't inflate its
own denominator.

## Phase 5 — T3 SEPA features (`t3_sepa_features`, 144 cols, ~9.47M rows)

Universe = **`T3_UNIVERSE_SQL`** (module constant):

```sql
    SELECT ticker FROM sepa_watchlist              -- ever opened a SEPA session
    UNION
    SELECT ticker FROM vip_watchlist WHERE active  -- hand-curated
    UNION
    SELECT DISTINCT ticker FROM t2_screener_features WHERE trend_ok   -- ever trend_ok
```

carrying **complete price history** regardless of current session state ("Option C",
2026-05-08). Keyed `(ticker, date, feature_version)`. 2,836 tickers as of 2026-07-20.

The `ever trend_ok` arm was added 2026-07-20. Gating on `sepa_watchlist` alone made a
ticker invisible to the model until it had opened a session — i.e. until it
**triggered**, which is precisely when it stops being a pre-breakout candidate. Cost
measured before the change: 107 tickers / 56,085 rows = **0.6%** of t3.

⚠️ **`T3_UNIVERSE_SQL` has two readers.** This method materializes from it; the
orchestrator's Phase 5 self-heal (`_t3_holed_dates`) decides what *should* exist from
it. Never widen one by editing a SQL literal — edit the constant. A mismatch leaves
the self-heal blind to the new names, which is unobservable until a ticker surfaces
unscored on the dashboard.

`compute_t3_features(only_tickers=[...])` narrows a run to a subset of the universe,
for backfilling newly-admitted names without DELETE-ing and recomputing a whole span
(the INSERT is plain — no `OR IGNORE` — so the target must be empty). Safe for
cross-sectional correctness: XS alphas and rank columns are carried forward from T2
(already computed universe-wide) and TS alphas are per-ticker. The alpha stage is
mostly **fixed cost** (2 tickers ≈ 79s, 109 tickers ≈ 77s) — batch, never loop.

| Sub-phase | Method | What |
|---|---|---|
| A — SQL INSERT | vectorised insert from T2 | All T2 columns carried forward; per-ticker window features (momentum 21–252d, RSI-14, ATR-14, dollar-volume/turnover, velocity, pattern flags); 19 `*_pct_chg` delta columns; `sma_50_slope`, `rs_line_lag_delta`; M03 regime columns joined by date |
| B — Python UPDATE | multiprocessing, warmup loaded from T2 | 9 TS alphas (006, 009, 012, 041, 046, 049, 051, 054, 101) + 2 vol-adjusted features |

`*_pct_chg` formula: `(cur − prev) / ABS(prev) × 100`; first row per ticker NULL;
`CASE WHEN cur = prev THEN 0` guards the zero-denominator breakout-at-high case.

**Fundamentals are NOT stored in T3** (removed 2026-05-08): `v_d2_features` joins
`fundamental_features` and `shares_history` at query time.

## Coverage-aware self-healing (both incremental phases)

- **Phase 3**: if <99% of active screener tickers are present for the target date,
  the whole date is recomputed (guards against partial yfinance fetches).
- **Phase 5**: if any breakout ticker (`trend_ok AND breakout_ok`) present in T2 is
  absent from T3 for the target date, the date reruns. Separate gate from the T2
  check — it catches T3-side write failures.

## Gotchas (verified, still live)

- **T3 is a gappy panel**: rows are NOT calendar-contiguous per ticker. Compute
  forward returns from `price_data`, never `shift(-1)` on T3.
- **Lazy T3 leaves forward-only holes**: self-heal + LEFT JOIN guard exist, but holes
  behind the recompute frontier are possible for historical dates.
- **Column casing**: DuckDB stores lowercase, but the Phase C rank UPDATE produces
  TitleCase names; `COLUMN_CASE_MAP` in `view_manager.py` bridges them. XS rank
  columns are not fully mapped yet.
- Dropped raw features are silently NaN-filled by the scorer — the model-card
  builder's hard-fail is the canary (the 2026-07 `atr_pct_chg` regression).

## Related

- Serving views over T3: [managers.md](managers.md) (ViewManager)
- Session store, one input to the T3 universe: [managers.md](managers.md) (SepaWatchlistManager)
- The self-heal that reads `T3_UNIVERSE_SQL`: [orchestrator.md](orchestrator.md) (Phase 5)
- Feature metadata: `feature_catalog` + `model_feature_sets` tables ([model_registry.md](model_registry.md))
