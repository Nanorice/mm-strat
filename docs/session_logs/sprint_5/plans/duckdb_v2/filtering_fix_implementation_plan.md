# Architecture B: Apply `screener_members` Filter to Feature Pipeline

Introduce `screener_members` as an active population filter in the feature pipeline. Currently all phases compute features for every ticker in `price_data`. After this change, **Phases A and T2 will only process active screener members** (price ≥ $15, vol20d ≥ 500K), reducing the working universe from ~1,826 to ~700 tickers and cutting daily compute time by ~60%.

> [!IMPORTANT]
> **Semantic change to Phase C cross-sectional ranks**: `RS_Universe_Rank`, `Sector_Momentum`, `RS_Industry_Rank` etc. will now be computed relative to the *screened investable universe* (700 tickers), not the raw full price universe (1,826 tickers). This is arguably **more correct** — you want RS rank vs peers you'd actually trade, not vs micro-caps and ETFs that fail volume criteria. Worth being aware of when comparing historical rank values.

---

## Follow-up Q&A

### Q: Can SPY come from [t1_macro](file:///c:/Users/Hang/PycharmProjects/quantamental/src/macro_engine.py#441-503) instead of `price_data`?

**Yes — and it's cleaner.** [t1_macro](file:///c:/Users/Hang/PycharmProjects/quantamental/src/macro_engine.py#441-503) already has `spy_close`, `spy_high`, `spy_low`, `spy_volume` as first-class columns (see [macro_engine.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/macro_engine.py) line 461). The current `spy_data` CTE in feature_pipeline.py pulls `SELECT date, close as spy_close FROM price_data WHERE ticker = 'SPY'`. We can replace this with `SELECT date, spy_close FROM t1_macro` — no more special-casing SPY in the screener JOIN at all. This is the preferred approach: **SPY stays in [t1_macro](file:///c:/Users/Hang/PycharmProjects/quantamental/src/macro_engine.py#441-503), completely separate from the screened equity universe in `price_data`**.

The `price_base` CTE then becomes a clean screener-filtered equity-only query, and `spy_data` is a clean macro join. No hacks, no `OR ticker = 'SPY'` anywhere.

### Q: Where does the full ticker universe in `price_data` come from?

**Currently: manually seeded + yfinance for whatever tickers you tell it to track.** There is no proactive ticker discovery — `price_data` only has tickers that were explicitly onboarded. The master plan lists this as a TODO: *"Phase 1.0 sub-step to onboard new US tickers not yet in `price_data`"*.

In practice today, the universe was bootstrapped by running the old scanner/screener scripts against a pre-defined list (likely S&P 500 + Russell 1000 + some extras). New tickers don't enter automatically. This is a known gap and is separate from the Architecture B change — it's a universe discovery problem, not a filter problem.

### Q: Does Phase 6 (T3) calculate any new features?

**No — T3 is purely a filter + copy operation.** [compute_t3_features()](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#738-869) runs a single `INSERT OR IGNORE INTO t3_sepa_features ... SELECT ... FROM daily_features WHERE trend_ok=TRUE AND breakout_ok=TRUE`. Every column in T3 is copied verbatim from [daily_features](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#275-481). No new computation happens. It's intentionally a "materialized subset" not a feature computation step.

### Q: When does a ticker stop being added to T3? What's the lifecycle?

This is important to understand correctly:

- **T3 is NOT one-row-per-trade.** It has one row per **(ticker, date)** where `trend_ok=TRUE AND breakout_ok=TRUE` — meaning a ticker can have many T3 rows across many dates.
- **The trade lifecycle happens in [v_d1_candidates](file:///c:/Users/Hang/PycharmProjects/quantamental/src/managers/view_manager.py#238-369)**, not T3. The view does session detection: it groups consecutive `trend_ok=TRUE` days into sessions, finds the first `breakout_ok=TRUE` day per session (= entry signal), and collapses each session into one trade row.
- **A ticker "exits" a trade** when [trend_ok](file:///c:/Users/Hang/PycharmProjects/quantamental/test/test_feature_pipeline.py#156-164) flips to FALSE — that becomes the `exit_date` in [v_d1_candidates](file:///c:/Users/Hang/PycharmProjects/quantamental/src/managers/view_manager.py#238-369).
- **T3 rows never get deleted** — it's append-only. A ticker stays in T3 as long as it keeps generating `trend_ok + breakout_ok` days. When it no longer qualifies (trend breaks), it simply stops receiving new rows. Old rows remain as history.

So the lifecycle is:
```
T3 row added  ← every day where trend_ok=TRUE AND breakout_ok=TRUE
Trade entry   ← derived by v_d1_candidates (first breakout_ok per trend session)
Trade exit    ← derived by v_d1_candidates (last date where trend_ok=TRUE in session)
T3 row stops  ← when daily_features stops producing trend_ok=TRUE AND breakout_ok=TRUE
```

### Q: Should we only compute full (heavy) features for SEPA candidates?

This is the Architecture C vision from the previous analysis. The short answer: **not yet, because Phase C (cross-sectional ranks) requires the full screened universe to be meaningful**. You can't rank a ticker's RS percentile if you only have 22 tickers for that day. Arch B is the pragmatic middle ground — full features for all screened tickers (~700), T3 extracts only SEPA candidates. Full lazy computation (Arch C) would require redesigning Phase C or accepting that ranks are computed against a very small peer set.

---

---

## Before / After: Phase-by-Phase

### Phase 1 — T1 Ingestion (price/fund/shares/macro)
| | Before | After |
|---|---|---|
| Population | `price_data` all tickers | No change — always full universe |
| Code change | None | None |

### Phase 2 — Screener Membership
| | Before | After |
|---|---|---|
| Role | Audit log only, unused downstream | **Active filter** for Phases A+T2 |
| Code change | None | None (already correct) |

### Phase 3 — T2 Screener Features ([compute_t2_screener_features](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#486-733))
| | Before | After |
|---|---|---|
| SQL source | `FROM price_data` (all ~1,826 tickers) | `FROM price_data INNER JOIN screener_members ON is_active = TRUE` |
| Rows computed | ~2.59M | ~1.0M (~700 tickers) |
| Estimated time | 7.9s | ~3s |
| Code file | [src/feature_pipeline.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py) line ~578 | Same, add JOIN |

### Phase 5 — Phase A: SQL Base Features ([compute_base_features](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#874-1135))
| | Before | After |
|---|---|---|
| SQL source | `FROM price_data` (all tickers) | `FROM price_data INNER JOIN screener_members ... OR ticker = 'SPY'` |
| Rows in [daily_features](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#275-481) | ~2.59M | ~1.0M |
| Phase A time | ~8s | ~3s |
| Code file | [src/feature_pipeline.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py) line ~889 | Same, add JOIN |

### Phase 5 — Phase B: Alpha Factors ([compute_alpha_features](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#1140-1213))
| | Before | After |
|---|---|---|
| Data loaded | 2.59M rows from [daily_features](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#275-481) | ~1.0M rows (auto-reduced because Phase A wrote fewer rows) |
| Phase B time (parallel) | ~55s | ~22s |
| Code change | **None** — reads from [daily_features](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#275-481) which is already filtered |

### Phase 5 — Phase C: Cross-sectional Ranks ([compute_cross_sectional_ranks](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#1464-1536))
| | Before | After |
|---|---|---|
| Universe for PERCENT_RANK | All tickers incl. sub-$15 stocks | Screened investable universe only |
| Phase C time | ~4s | ~2s |
| Code change | **None** — runs UPDATE on [daily_features](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#275-481) which is already filtered |
| Semantic note | Ranks relative to full raw universe | Ranks relative to investable screened universe ✅ |

### Phase 5 — Phase D+E: M03 Regime Scores
| | Before | After |
|---|---|---|
| Rows updated | ~2.59M | ~1.0M |
| Phase D+E time | ~3s | ~1s |
| Code change | **None** — JOIN on `daily_features.date` already correct |

### Phase 6 — T3 Lazy Materialization ([compute_t3_features](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#738-869))
| | Before | After |
|---|---|---|
| Source | [daily_features](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#275-481) WHERE trend_ok+breakout_ok | Same — no change |
| Rows output | ~33K | Same ~33K (SEPA candidates unchanged) |
| Code change | **None** |

### Phase 7–9 — Views, Cache, Monitoring
| | Before | After |
|---|---|---|
| All downstream views | Read from `t3_sepa_features` | No change |
| `d2_training_cache` | Materialized from [v_d2_training](file:///c:/Users/Hang/PycharmProjects/quantamental/src/managers/view_manager.py#518-650) | No change |
| Code change | **None** |

---

## Summary Performance Table

| Phase | Before | After | Savings |
|---|---|---|---|
| T2 screener features | ~8s | ~3s | **-63%** |
| Phase A SQL base features | ~8s | ~3s | **-63%** |
| Phase B Python alphas | ~55s | ~22s | **-60%** |
| Phase C cross-sectional ranks | ~4s | ~2s | **-50%** |
| Phase D+E M03 | ~3s | ~1s | **-67%** |
| **Total daily compute** | **~78s** | **~31s** | **~60% faster** |

---

## Proposed Changes

### [MODIFY] [feature_pipeline.py](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py)

Three SQL changes: (1+2) add screener membership JOIN to `price_base` CTE in both feature methods, (3) swap `spy_data` CTE to read from [t1_macro](file:///c:/Users/Hang/PycharmProjects/quantamental/src/macro_engine.py#441-503) instead of `price_data`.

#### Change 1 — [compute_t2_screener_features()](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#486-733): filter `price_base` to screened tickers (~line 578)

```diff
-                    FROM {self.price_source}
-                    WHERE date >= '{fetch_start_date}'
+                    FROM {self.price_source} p
+                    INNER JOIN screener_members sm
+                        ON p.ticker = sm.ticker AND sm.is_active = TRUE
+                    WHERE p.date >= '{fetch_start_date}'
```

#### Change 2 — [compute_base_features()](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#874-1135) Phase A: filter `price_base` to screened tickers (~line 889)

```diff
-                    FROM {self.price_source}
-                    WHERE date >= '{fetch_start_date}'
+                    FROM {self.price_source} p
+                    INNER JOIN screener_members sm
+                        ON p.ticker = sm.ticker AND sm.is_active = TRUE
+                    WHERE p.date >= '{fetch_start_date}'
```

#### Change 3 — Both methods: swap `spy_data` CTE to read from [t1_macro](file:///c:/Users/Hang/PycharmProjects/quantamental/src/macro_engine.py#441-503)

The `spy_data` CTE currently reads `FROM price_data WHERE ticker = 'SPY'`. Since SPY is already in [t1_macro](file:///c:/Users/Hang/PycharmProjects/quantamental/src/macro_engine.py#441-503) with a dedicated `spy_close` column, we can source it cleanly from there — no special-casing needed.

Apply in **both** [compute_t2_screener_features()](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#486-733) and [compute_base_features()](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#874-1135):
```diff
- spy_data AS (
-     SELECT date, close as spy_close
-     FROM {self.price_source}
-     WHERE ticker = 'SPY' AND date >= '{fetch_start_date}'
- ),
+ spy_data AS (
+     SELECT date, spy_close
+     FROM t1_macro
+     WHERE date >= '{fetch_start_date}'
+ ),
```

This cleanly separates the **equity screened universe** (`price_data` filtered via `screener_members`) from the **macro/benchmark data** ([t1_macro](file:///c:/Users/Hang/PycharmProjects/quantamental/src/macro_engine.py#441-503)). No `OR ticker = 'SPY'` hacks required.

> [!IMPORTANT]
> [t1_macro](file:///c:/Users/Hang/PycharmProjects/quantamental/src/macro_engine.py#441-503) must be populated (Phase 1.4 must have run) before Phase A or T2 features can compute. This is already the case in the current pipeline ordering.

---

## Verification Plan

### Automated Tests — Existing Suite

The existing test in [test/test_feature_pipeline.py](file:///c:/Users/Hang/PycharmProjects/quantamental/test/test_feature_pipeline.py) asserts that [daily_features](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#275-481) contains exactly 4 tickers: `['AAPL', 'MSFT', 'SPY', 'TSLA']`. After this change, with a `screener_members` table present and populated, only screener-passing tickers appear. The test DB setup **does not create `screener_members`**, so the query will fail if the `INNER JOIN` is applied and the table doesn't exist.

**Required test update**: The test [_create_test_db()](file:///c:/Users/Hang/PycharmProjects/quantamental/test/test_feature_pipeline.py#17-59) / [setUpModule()](file:///c:/Users/Hang/PycharmProjects/quantamental/test/test_feature_pipeline.py#67-109) must seed a `screener_members` table with all test tickers marked `is_active = TRUE`. This preserves existing assertions while validating the new join.

Run existing tests with:
```powershell
& "c:/Users/Hang/PycharmProjects/quantamental/.venv/Scripts/Activate.ps1"
python -m pytest test/test_feature_pipeline.py -v
```

### New Test — Screener Filter Exclusion

Add one new test case: a ticker in `price_data` that is NOT in `screener_members` (or `is_active = FALSE`) should be **absent** from [daily_features](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#275-481) after the change. This directly validates the filter is active.

The test will seed an extra ticker `JUNK` in `price_data` with `is_active = FALSE` in `screener_members`, then assert `JUNK` does not appear in [daily_features](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#275-481).

### Smoke Test on Real DB

After implementing, run the full pipeline on the production database and verify:
```powershell
& "c:/Users/Hang/PycharmProjects/quantamental/.venv/Scripts/Activate.ps1"
python -c "
import duckdb
con = duckdb.connect('data/market_data.duckdb')
before = con.execute('SELECT COUNT(DISTINCT ticker) FROM price_data').fetchone()[0]
screened = con.execute('SELECT COUNT(*) FROM screener_members WHERE is_active = TRUE').fetchone()[0]
print(f'price_data tickers: {before}')
print(f'screener_members active: {screened}')
con.close()
"
```
Then run the pipeline and check [daily_features](file:///c:/Users/Hang/PycharmProjects/quantamental/src/feature_pipeline.py#275-481) only contains screened tickers:
```powershell
python -c "
import duckdb
con = duckdb.connect('data/market_data.duckdb')
after = con.execute('SELECT COUNT(DISTINCT ticker) FROM daily_features').fetchone()[0]
print(f'daily_features tickers after: {after}')
# Verify SPY still present (benchmark)
spy = con.execute(\"SELECT COUNT(*) FROM daily_features WHERE ticker = 'SPY'\").fetchone()[0]
print(f'SPY rows: {spy} (should be > 0)')
con.close()
"
```
