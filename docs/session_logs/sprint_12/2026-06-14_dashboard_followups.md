# Dashboard Follow-ups — 2026-06-14

## Done this session

### Remote model-card / asset regression (ROOT CAUSE + fix)
- **Cause**: `_ensure_asset_dirs` freshness gate keyed on file mtimes. On cloud,
  git deploys a PARTIAL subset of `model_cards/` (only the `.json` files are
  tracked; the `.html` files Model Lab renders are NOT). The gate saw fresh
  just-deployed files → skipped the R2 pull → the `.html` never arrived. Same
  for `data/audit_reports/` (→ "0 audit reports" remotely).
- **Fix**: gate now keys on a `.r2_synced` sentinel marker that ONLY the pull
  writes (git-ignored), so a cold cloud boot always pulls. Sync allow-list for
  `models/` extended to `.md`/`.json` (reports, diffs, results.json) with
  `model.json` excluded by name. Audit history "0" was remote-only — fixed by
  the same pull fix (7 reports exist locally).

### Quick wins (Pipeline Health page)
- **G2 phase sort**: heatmap rows now in natural execution order
  (`phase_1`→`phase_10`) via `_phase_sort_key`, not lexical (`phase_10` was on
  top). yaxis stays reversed so phase_1 renders at the top.
- **G5 timestamp format**: null-filing 30-day trend now prints `2026-06-12=47`
  (date only, no `00:00:00`).
- **G6 audit history**: confirmed remote-only; fixed by the asset-pull fix.
- **G7 storage table**: added dashboard.duckdb (slim), model_cards/,
  data/audit_reports/, logs/drift/ (quarterly) to the storage list.
- **Freshness explainer**: added a Tolerance column + caption so "fresh at 14d"
  (fundamentals tol=95, quarterly) and earnings_calendar −95 lag (future-looking)
  are self-explanatory. Negative-tolerance tables handled explicitly.

## Deferred — for next session (with findings to chase)

### G1 — Data flow chart (`docs/architecture/data_flow.mmd`)
Update to current pipeline (Phase 7.4 scoring, v_d3_prebreakout, R2 sync) and
de-cross the Mermaid layout; drop redundant nodes/edges. Genuine layout work —
deferred by user. Start: open the .mmd, reconcile against the orchestrator's
phase list, group by layer to reduce edge crossings.

### G3 — Data freshness investigations
- **price_data "no data"**: `load_data_freshness` queries
  `SELECT MAX(date) FROM price_data`. The slim dashboard DB DOES carry
  price_data (windowed). Check whether the slim DB's price_data window is empty
  or the query errored. If remote-only, likely the table wasn't in an older slim
  build — re-verify after a fresh build+sync.
- **earnings_calendar −95 lag / fundamentals 14d**: EXPLAINED (intentional
  tolerances; now surfaced in the UI). No fix needed unless tolerances are wrong.

### G2 — not-run / amber investigations
- **cik_map_refresh / earnings_calendar_refresh not run recently**: query
  `pipeline_runs` for these phase_names' last `target_date`. Likely cadence-gated
  (these aren't daily) — confirm the orchestrator's run condition for them.
- **T1 ingestion amber**: amber = success-with-per-entity-errors (T1 completed
  but logged per-ticker failures → see T1 Ingestion Failures section). Expected
  when a handful of tickers fail; not a phase failure. Document if acceptable.

### G4 — T1 failures → actionable deactivation window (FEATURE)
Add a window at the bottom of the T1 Ingestion Failures section:
- tickers failing ≥ N days (e.g. 14) in the window
- the CLI command to deactivate them (find the existing deactivate/blacklist
  script — `detect_bad_tickers` only warns per memory; there may be a
  `ticker_blacklist` writer)
- explanatory note on the policy
- Finviz LinkColumn (mirror the watchlist's
  `https://finviz.com/quote.ashx?t=<ticker>` pattern) for quick inspection

### G5 — NULL filing_date + 90-day fallback (INVESTIGATE)
- **When do we write NULL filing_date?** From the caption: fundamentals row
  wrote OK but the yfinance earnings fetch failed → no PIT anchor; EDGAR backfill
  repairs later. Confirm this is the only path; check the Phase-1 fundamentals
  upsert.
- **+90d fallback for next earnings date?** Check whether earnings_calendar /
  the staleness logic has a "last period_end + 90d" fallback when the next
  earnings date is unknown (memory mentions EXPECTED_NEXT_FILING_LAG_DAYS ~135d).
