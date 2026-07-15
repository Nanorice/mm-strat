# Local vs Remote DB — parity contract

Row counts refreshed 2026-07-16 (prev 2026-06-16). Source of truth for what the
dashboard reads and what ships to the cloud. Regenerate with the query at the bottom.

## Three layers

| Layer | File | Objects | Built by |
|---|---|---|---|
| **Local full** | `data/market_data.duckdb` (~67 GB) | 49 (25 tables + 24 views) | the daily pipeline |
| **Local slim** | `data/dashboard.duckdb` (~784 MB) | 25 base tables | `scripts/build_dashboard_db.py` |
| **Remote** | R2 `latest/dashboard.duckdb` | 25 — **byte-for-byte copy of local slim** | `scripts/sync_dashboard_db.py` (`upload_file`) |

Remote is not a separate build — `sync_dashboard_db.py` uploads the slim file
verbatim. So **remote layout/content ≡ local slim, always.** The only divergence
that can exist is local-full → slim.

## Parity contract (decided 2026-06-16)

1. **No bespoke remote content.** Every object in slim/remote must exist in full
   with identical schema. Verified: zero slim-only objects.
2. **Layout parity for what the dashboard reads.** Every table/view the dashboard
   surface (`dashboard.py`, `pages/*`, `dashboard_utils.py`) queries must be in the
   MANIFEST. Verified: the dashboard reads only tables already in the manifest;
   none of the 18 full-only objects are referenced.
3. **Row-windowing is allowed, silent drops are not.** The 3 big tables are
   windowed to 252d (that's the point of the slim DB). But a table failing to
   build must **throw**, not silently drop — enforced by fail-fast in the build
   loop + a post-build invariant that asserts every manifest object exists.

## Content (shared tables — all 25 have identical column layout)

| Table | Full rows | Slim/Remote rows | Kept | Mode |
|---|--:|--:|--:|---|
| price_data | 16,183,288 | 696,034 | 4.3% | window 252d |
| t2_screener_features | 9,846,324 | 469,378 | 4.8% | window 252d |
| t3_sepa_features | 9,382,494 | 418,954 | 4.5% | window 252d |
| shares_history | 387,952 | 387,952 | 100% | full |
| fundamentals | 301,337 | 301,337 | 100% | full |
| daily_predictions | 300,670 | 300,670 | 100% | full |
| v_d3_prebreakout | 74,623 | 74,623 | 100% | materialized view |
| macro_data | 47,888 | 47,888 | 100% | full |
| screener_watchlist | 38,599 | 38,587 | ~100% | full |
| d2_training_cache | 38,599 | 38,556 | ~100% | full |
| sepa_watchlist | 35,827 | 35,827 | 100% | full |
| earnings_calendar | 17,030 | 17,030 | 100% | full |
| pipeline_error_log | 16,825 | 16,825 | 100% | full |
| screener_membership | 11,216 | 11,216 | 100% | full |
| cik_map | 10,764 | 10,764 | 100% | full |
| t2_regime_scores | 8,387 | 8,387 | 100% | full |
| t1_macro | 6,661 | 6,661 | 100% | full |
| weather_gauge | 5,903 | 5,903 | 100% | full |
| t2_risk_scores | 5,160 | 5,160 | 100% | full |
| company_profiles | 4,176 | 4,176 | 100% | full |
| v_d3_deployment | 2,090 | 2,090 | 100% | materialized view |
| pipeline_runs | 780 | 780 | 100% | full |
| v_d3_shortlist | 334 | 334 | 100% | materialized view |
| models | 19 | 19 | 100% | full |
| v_d3_vip | 0 | 0 | — | materialized view (no VIP names added yet) |

New since 2026-06-16: `weather_gauge`, `v_d3_shortlist`, `v_d3_vip` (added
alongside their dashboard panels). The near-100% on `screener_watchlist` /
`d2_training_cache` is the `window_plus_active` rebuild trimming a handful of
dead rows, not a drop.

## Objects in full but NOT in slim/remote (24)

Intentionally excluded — **none are read by the dashboard.** A dashboard page
querying any of these works locally but throws on remote. If a future page needs
one, add it to the MANIFEST (don't special-case the remote).

- **Tables (14):** `feature_catalog`, `fundamental_features`, `model_feature_sets`,
  `screener_criteria_versions`, `ticker_blacklist`, `forced_promotions`,
  `table_write_log`, `t3_training_cache`, `vip_watchlist`, `m02_breakout_targets`,
  `m02_prototype_targets`, `shadow_action`, `shadow_book`, `shadow_divergence`
- **Views (10):** `v_d1_candidates`, `v_d2_features`, `v_d2_hydrated`,
  `v_d2_training`, `v_d3_lifecycle`, `v_sepa_candidates`, `v_screener_dashboard`,
  `v_price_combined`, `v_shares_combined`, `v_t3_training`

  Note: `v_d3_lifecycle` (live nightly scoring) is deliberately full-only — the
  dashboard reads the materialized `v_d3_deployment` / `v_d3_prebreakout` snapshots,
  never the lifecycle view. `vip_watchlist` (the source table) stays local; the
  dashboard reads its materialized `v_d3_vip` snapshot to avoid a remote runtime join.

## Regenerate row counts

```python
import duckdb
cf = duckdb.connect('data/market_data.duckdb', read_only=True)
cs = duckdb.connect('data/dashboard.duckdb', read_only=True)
for t in [r[0] for r in cs.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()]:
    nf = cf.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    ns = cs.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    print(f"{t:<26}{nf:>14,}{ns:>14,}{100*ns/nf:7.1f}%")
```
