# Local vs Remote DB — parity contract

Refreshed **2026-07-19** (slim-side counts + object inventories; prev 2026-07-16).
Source of truth for what the dashboard reads and what ships to the cloud.
Regenerate with the query at the bottom.

## Three layers

| Layer | File | Objects | Built by |
|---|---|---|---|
| **Local full** | `data/market_data.duckdb` (~67 GB) | 49 (34 tables + 15 views) | the daily pipeline |
| **Local slim** | `data/dashboard.duckdb` (~750 MB) | 31 base tables (incl. 6 materialized views) | `scripts/build_dashboard_db.py` (Phase 7.5) |
| **Remote** | R2 `latest/dashboard.duckdb` | 31 — **byte-for-byte copy of local slim** | `scripts/sync_dashboard_db.py` (Phase 7.6) |

Remote is not a separate build — `sync_dashboard_db.py` uploads the slim file
verbatim, so **remote ≡ local slim, always**; the only divergence that can exist is
local-full → slim. The publish is **withheld while the Phase 1.6 plausibility gate
is red** (remote stays on its last clean snapshot). 🛑 Data flow is ONE-WAY
(local → slim → R2 → viewer); pulling from R2 requires `DASHBOARD_PULL_FROM_R2=1`.

## Parity contract (decided 2026-06-16, unchanged)

1. **No bespoke remote content.** Every object in slim/remote must exist in full
   with identical schema (views count — slim materializes them).
2. **Layout parity for what the dashboard reads.** Every table/view any dashboard
   surface queries must be in the MANIFEST — a page that reads a non-manifest
   object works locally and **throws on remote**. When adding a dashboard loader,
   add its table to the MANIFEST (don't special-case the remote).
3. **Row-windowing is allowed, silent drops are not.** The 3 big tables are
   windowed to 252d; a failed table build must throw (fail-fast + post-build
   invariant asserting every manifest object exists).

## Slim/remote content (31 objects, counts 2026-07-19)

| Object | Slim rows | Mode |
|---|--:|---|
| price_data | 695,655 | window 252d |
| t2_screener_features | 469,429 | window 252d |
| t3_sepa_features | 416,283 | window 252d |
| shares_history | 387,952 | full |
| daily_predictions | 302,220 | full |
| fundamentals | 301,378 | full |
| macro_data | 214,732 | full |
| v_d3_prebreakout | 75,757 | materialized view |
| screener_watchlist | 38,648 | materialized **view** (a VIEW over `sepa_watchlist` in full since 2026-07-18) |
| d2_training_cache | 38,648 | full |
| sepa_watchlist | 35,884 | full |
| earnings_calendar | 17,030 | full |
| pipeline_error_log | 17,046 | full |
| screener_membership | 11,220 | full |
| cik_map | 10,764 | full |
| t2_regime_scores | 8,398 | full |
| t1_macro | 6,663 | full |
| weather_gauge | 5,911 | full |
| t2_risk_scores | 5,169 | full |
| company_profiles | 4,176 | full |
| cone_cells | 2,460 | full |
| v_d3_deployment | 2,011 | materialized view |
| pipeline_runs | 813 | full |
| v_d3_screening | 720 | materialized view |
| v_d3_shortlist | 352 | materialized view |
| sector_breadth | 169 | full |
| models | 19 | full |
| trades / cash_flows / nav_history | 0 | full (portfolio book — empty until fills entered) |
| v_d3_vip | 0 | materialized view (no VIP names yet) |

New since 2026-07-16: `cone_cells`, `sector_breadth`, `trades`, `cash_flows`,
`nav_history`, `v_d3_screening` (added with their dashboard panels). Slim counts
lag the full DB by up to one nightly build — e.g. `sepa_watchlist` slim 35,884 vs
full 39,088 (the 2026-07-18 merge backfill lands remotely on the next Phase 7.5/7.6).

## Objects in full but NOT in slim/remote (18)

Intentionally excluded — none are read by the dashboard:

- **Tables (9):** `feature_catalog`, `forced_promotions`, `fundamental_features`,
  `model_feature_sets`, `screener_criteria_versions`, `shadow_divergence`,
  `table_write_log`, `ticker_blacklist`, `vip_watchlist`
- **Views (9):** `v_d1_candidates`, `v_d2_features`, `v_d2_hydrated`,
  `v_d2_training`, `v_d3_lifecycle`, `v_price_combined`, `v_sepa_candidates`,
  `v_shares_combined`, `v_t3_training`

Notes: `v_d3_lifecycle` is deliberately full-only — the dashboard reads the
materialized `v_d3_*` snapshots, never the live view. `vip_watchlist` (source
table) stays local; the dashboard reads `v_d3_vip`. The 2026-07-16 doc listed
`shadow_book`/`shadow_action`, `m02_*_targets`, and `t3_training_cache` in full —
those tables are **not present** in the current (post-recovery) full DB; they are
research artifacts recreated on demand by their scripts.

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
