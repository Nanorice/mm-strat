# Local vs Remote DB — parity contract

Generated 2026-06-16. Source of truth for what the dashboard reads and what
ships to the cloud. Regenerate the row counts with the queries at the bottom.

## Three layers

| Layer | File | Objects | Built by |
|---|---|---|---|
| **Local full** | `data/market_data.duckdb` (~67 GB) | 40 (23 tables + 17 views) | the daily pipeline |
| **Local slim** | `data/dashboard.duckdb` (~789 MB) | 22 base tables | `scripts/build_dashboard_db.py` |
| **Remote** | R2 `latest/dashboard.duckdb` | 22 — **byte-for-byte copy of local slim** | `scripts/sync_dashboard_db.py` (`upload_file`) |

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

## Content (shared tables — all 22 have identical column layout)

| Table | Full rows | Slim/Remote rows | Kept | Mode |
|---|--:|--:|--:|---|
| price_data | 16,108,617 | 706,792 | 4.4% | window 252d |
| t2_screener_features | 9,794,277 | 473,764 | 4.8% | window 252d |
| t3_sepa_features | 9,346,727 | 416,281 | 4.5% | window 252d |
| v_d3_prebreakout | 73,186 | 73,186 | 100% | materialized view |
| v_d3_deployment | 1,966 | 1,966 | 100% | materialized view |
| daily_predictions | 75,477 | 75,477 | 100% | full |
| fundamentals | 301,188 | 301,188 | 100% | full |
| shares_history | 376,282 | 376,282 | 100% | full |
| macro_data | 77,336 | 77,336 | 100% | full |
| screener_watchlist | 38,400 | 38,400 | 100% | full |
| sepa_watchlist | 35,741 | 35,741 | 100% | full |
| d2_training_cache | 37,996 | 37,996 | 100% | full |
| screener_membership | 11,169 | 11,169 | 100% | full |
| earnings_calendar | 12,279 | 12,279 | 100% | full |
| pipeline_error_log | 15,816 | 15,816 | 100% | full |
| cik_map | 10,483 | 10,483 | 100% | full |
| t2_regime_scores | 8,366 | 8,366 | 100% | full |
| t1_macro | 6,647 | 6,647 | 100% | full |
| t2_risk_scores | 5,148 | 5,148 | 100% | full |
| company_profiles | 4,176 | 4,176 | 100% | full |
| pipeline_runs | 637 | 637 | 100% | full |
| models | 17 | 17 | 100% | full |

## Objects in full but NOT in slim/remote (18)

Intentionally excluded — **none are read by the dashboard.** A dashboard page
querying any of these works locally but throws on remote. If a future page needs
one, add it to the MANIFEST (don't special-case the remote).

- **Tables (7):** `feature_catalog`, `fundamental_features`, `model_feature_sets`,
  `screener_criteria_versions`, `ticker_blacklist`, `forced_promotions`,
  `table_write_log`
- **Views (11):** `v_d1_candidates`, `v_d2_features`, `v_d2_hydrated`,
  `v_d2_training`, `v_sepa_candidates`, `v_screener_dashboard`, `v_price_combined`,
  `v_shares_combined`, `v_t3_training`, `v_d1_trades`*, `v_d2r_hydrated`*

  *`v_d1_trades` / `v_d2r_hydrated` retired in commit b258aee — will drop from full
  on the next `create_all()`.

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
