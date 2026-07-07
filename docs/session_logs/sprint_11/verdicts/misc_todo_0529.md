# Miscellaneous To-Do List

This document outlines various tasks grouped by category, expanded with specific plans for investigation and implementation for each item.

## Execution Priorities
1. **High Priority (Data Quality & Model Impact):** 
   - ✅ Fundamentals update audit table (missing 'filed' date) — DONE 2026-05-29 (SEC EDGAR backfill, 97.73% coverage)
   - ✅ T1 ingestion failures — DONE 2026-05-29 (Phases A+B+C; D skipped as moot). See plan doc + follow-ups below.
   - ✅ Pipeline Health Page data freshness (stale tables) — DONE 2026-05-29 (macro_data wired into daily orchestrator)
   - ✅ T1 ingestion follow-up #3 — DONE 2026-05-29 (EDGAR_NO_DATA cohort triaged; tolerance bumped 15→35d, 4 rows backfilled, 66 phantom rows deleted across 40 tickers)
   - ✅ T1 ingestion follow-up #4 — DONE 2026-05-29 (no-CIK 101-200d cohort 36→3; +33 cik_map rows; 3 dead tickers identified for deactivation. Root cause: SEC's company_tickers.json silently omits ~4K real US issuers whose `submissions.tickers=[]`.)
   - ✅ T1 ingestion follow-up #2 — DONE 2026-05-30 (deactivated 26 confirmed-dead tickers; universe 4006→3980. Audit log at `logs/data_quality/deactivations.jsonl`. `deactivate_tickers.py` now writes one JSONL row per ticker with `db_before`/`yf_evidence`/`db_after`/`reason`.)
   - ✅ Calibrate prototype model — DONE 2026-05-29 (m01_prototype_cali_v1 trained. ECE improved slightly 0.142 -> 0.125, but band degraded from ACCEPTABLE to WEAK. Calibration pushed probabilities toward the true base rate, causing the model to fail the E2_trade_frequency gate because too few trades cleared the hardcoded P>=0.30 threshold.)
   - T1 ingestion follow-ups (4 remaining deferred items; see §"T1 Ingestion Follow-ups")
2. **Medium Priority (Observability):** 
   - ✅ Pipeline Health Page: Audit history — DONE 2026-05-29 (wired `tools/run_all_audits.py` into Phase 8)
   - ✅ Pipeline Runs (last 30d) plot formatting and color criteria — DONE 2026-05-29 (continuous date axis + new yellow `warning` state surfacing T1 ticker errors)
3. **Low Priority (Dashboard Visualizations & UI Polish):** 
   - ✅ Multicollinearity plot cleanup — DONE 2026-05-29 (scipy hierarchical reorder)
   - ✅ Feature signal bar chart colors — DONE 2026-05-29 (uniform ACCENT, gradient removed)
   - ✅ Active density by class plot — DONE 2026-05-29 (truncate>p99 instead of clip)
   - ✅ MFE histogram (bundled) — DONE 2026-05-29 (overflow bar for >p99)
   - ✅ Universe activity formatting — DONE 2026-05-29 (2-row layout, smoothed line + yearly bars)
   - ✅ Sector ETF flow check — DONE 2026-05-29 (T1→T2→T3 verified end-to-end; no bypass needed)
   - ✅ Forward-Return profile explanation — DONE 2026-05-29 (renamed to "Trailing Return at Entry"; was mis-titled, columns are LAG-based not forward)
4. **Long Term / Strategic:** 
   - Fundamental engine investigation
   - Eval framework phase 4
   - Risk: 5-Factor model improvements
   - ✅ Model card with longer period
5. **Sunday Sprint** (infra_uplift — goal: get the dashboard running off a remote-hosted DB)
   - list all tables/data used in dashboard
   - upload to github
   - move to remote
   - *(details in §"Sunday Sprint Plan" below)* (use google vm?)

## 1. Dashboard Visualizations & UI

### Active Density by Class Plot ✅ DONE 2026-05-29
* **Diagnosis:** Not a bad ticker. DB audit of `d2_training_cache` showed the Elite tail is real: 22 multi-year SEPA runs (UHT 2011→2024 = 3425d, NWPX 1862d, SAFT 1770d, …). All `sepa_exit_date` populated — no open-trade clipping. The visible "spike" was the **p98 clip itself** — `clip(upper=p98)` piled every value ≥ p98 onto the rightmost histogram bar.
* **Fix:** [src/evaluation/html_report.py:148-179](../../../src/evaluation/html_report.py#L148-L179) — switched from clip to truncate (drop rows > p99), title now reports the cutoff and dropped count. Bumped cap p98 → p99 to preserve more of the legit Solid/Elite tail.

### Multicollinearity Plot ✅ DONE 2026-05-29
* **Diagnosis:** Top-40 selection by sum-of-|ρ| was correct, but features were rendered in ranking order, scrambling related blocks (SMA/EMA, dist_from_X, pct_chg/delta pairs sat far apart). Visually messy despite holding real signal.
* **Fix:** [src/evaluation/html_report.py:169-205](../../../src/evaluation/html_report.py#L169-L205) — added `scipy.cluster.hierarchy.linkage(method='average')` on `1-|ρ|` distance, reorder rows/cols by `leaves_list()`. Block structure now jumps out (notebook's "Hierarchical Clustermap: Feature Redundancy" pattern, plotly-interactive). Falls back to sum-of-|ρ| order if linkage fails on degenerate input.

### Feature Signal Bar Chart ✅ DONE 2026-05-29
* **Diagnosis:** `_fig_bar` was colouring bars by their own value via `Viridis` — pure decoration, since the bar length already encodes the value. Same redundancy on both IC and MI charts.
* **Fix:** [src/evaluation/html_report.py:195-213](../../../src/evaluation/html_report.py#L195-L213) — `_fig_bar` now uses a single `ACCENT` colour, colorbar removed. (Briefly tried divergent RdBu on the IC chart's signed value; reverted because magnitude alone is more readable.)

### MFE Histogram (bundled with Active Density fix) ✅ DONE 2026-05-29
* **Diagnosis:** Same `clip(upper=p99)` bug as Elite density — was producing a fake spike at the right edge.
* **Fix:** [src/evaluation/html_report.py:112-153](../../../src/evaluation/html_report.py#L112-L153) — bin the 0..p99 body normally, then add a single red **overflow bar** one bin-width past p99 with count + max-value in legend & hover. Visually distinct from the body so the multi-year breakouts are honestly represented without crushing the 0–p99 detail.

### Sector ETF ✅ DONE 2026-05-29
* **Question:** are ETFs being ingested correctly through T1 → T2 → T3? Specifically, can they pass trend_ok / breakout_ok and reach the SEPA tables?
* **Findings:**
  * **T1:** all 36 ETFs in `price_data`, historical depth back to 1993 (SPY), shortest 2015 (XLRE).
  * **T2:** all 36 ETFs are picked up by `t2_screener_features` every trading day since 2026-05-12 (12/12 days, full coverage, no gaps). The `auto_enroll_non_equity()` path in [src/managers/screener_manager.py:409-454](../../../src/managers/screener_manager.py#L409-L454) correctly enrolls ETFs into `screener_membership` (criteria_version=0, evergreen), and the t2 builder's point-in-time join at [src/feature_pipeline.py:286-301](../../../src/feature_pipeline.py#L286-L301) treats ETFs the same as equities once enrolled. No bypass needed.
  * **T2 → T3 promotion works:** 11 ETFs hit `trend_ok` at least once in the recent window (QQQ, XLK, SOXX on all 12 days; USO, BNO, EEM, PDBC partial). 3 ETFs triggered `breakout_ok` (CPER, WEAT, XLY). CPER cleared both → entered `sepa_watchlist` (session_id=1, status=ACTIVE 2026-05-12) → propagated 11 rows into `t3_sepa_features`. End-to-end chain functional.
  * **Training set unaffected:** `d2_training_cache` has 0 ETF rows (CPER session still open — no closed-trade outcome yet).
* **Known gap (decided to skip):** historical t2 coverage for ETFs pre-2026-05-12 is missing because t2 is incrementally built (DELETE+INSERT per date window). Each ETF's `effective_date` correctly backdates to its first price day, but no historical backfill of t2 has been run. Going forward, daily runs keep ETFs current; backfill is a one-off `FeaturePipeline.compute_t2_features(start_date='YYYY-MM-DD', ...)` invocation if/when sector RS context over a longer window is needed.

### Universe Activity
* **Issue:** Formatting makes new SEPA additions per week almost invisible.
* **Investigation Plan:** Check the data scaling and formatting. New additions are likely dwarfed by the total universe size when plotted on the same axis.
* **Implementation Plan:** Use a secondary y-axis for new additions, change the plot type (e.g., switch from a stacked bar to a grouped bar or line chart), or adjust the scale to highlight weekly marginal changes.

### Forward-Return Profile ✅ DONE 2026-05-29
* **Diagnosis:** The chart was mis-titled. The columns `return_1d/5d/20d/60d` in `daily_features` are `close / LAG(close, N) − 1` — **trailing** N-day returns at the entry date, not forward outcomes. So "every bin shows a positive return" was correct by construction (SEPA only fires on uptrend + breakout) and "unclear what the population is" was driven by the misleading "Forward-Return" framing.
* **Fix:** Pure rename. [src/evaluation/html_report.py:66-82](../../../src/evaluation/html_report.py#L66-L82) chart title → "Trailing Return at Entry by Horizon". [src/evaluation/html_report.py:376-385](../../../src/evaluation/html_report.py#L376-L385) section heading "Forward-Return Profile" → "Trailing Return at Entry"; caption rewritten to explicitly call out (a) the trailing-not-forward nature, (b) the LAG-based formula, (c) the structural reason for positive values, and (d) that real forward outcomes (MFE / MAE / days active) live in §3.
* **Deferred:** option to add a SPY same-window baseline overlay (would show whether SEPA entries fire when the whole market is hot vs SEPA picking hot names in any regime). Not implemented this session — keep the simpler rename until there's a concrete use case.

### Pipeline Runs (last 30d) Plot ✅ DONE 2026-05-29
* **Diagnosis (uneven widths):** Heatmap x-axis was categorical, populated only from dates that had `pipeline_runs` rows. Weekends + holidays + missed days were collapsed out, so adjacent cells were not the same calendar-distance apart — visually "lumpy."
* **Diagnosis (always-green):** Phase status came straight from `pipeline_runs.status`. T1 ingestion ran to completion even when 14–30 tickers errored, so the row was logged as `success`. The per-ticker errors lived in `pipeline_error_log` and were never reflected in the heatmap.
* **Fix:**
  * [scripts/dashboard_utils.py:171-197](../../../scripts/dashboard_utils.py#L171-L197) — `load_pipeline_runs_window` now LEFT JOINs `pipeline_error_log` (grouped by `run_id`) so each row carries `n_errors`.
  * [scripts/pages/5_Pipeline_Health.py:35-46](../../../scripts/pages/5_Pipeline_Health.py#L35-L46) — color palette reworked: 🔴 failed / 🟡 warning / 🔵 running / 🟢 success / ⬜ no-run.
  * [scripts/pages/5_Pipeline_Health.py:108-205](../../../scripts/pages/5_Pipeline_Health.py#L108-L205) — `render_runs_heatmap` promotes `success + n_errors > 0` → `warning`, reindexes x-axis to a continuous `pd.date_range(min, max, freq='D')` (NaN cells for no-run days), discrete colorscale with sharp stops, separate drill-downs for failed vs warning runs.
* **Verified offline:** date axis went 20 → 31 day-cells; 19 cells correctly promoted from green→yellow for `phase_1_t1_ingestion` over the last 30 days.

---

## 2. Data Pipeline & Data Quality

### Pipeline Health Page: Data Freshness ✅ DONE 2026-05-29
* **Original framing (incorrect):** Both `earnings_calendar` and `macro_data` showing stale; assume broken update jobs.
* **Actual diagnosis:**
  * `earnings_calendar` — NOT stale. Tolerance of `-200` correctly handles future-looking dates; was a UI false positive.
  * `macro_data` — Genuinely stale (17 days), but the cause was wrong table being written. Orchestrator's Phase 1 macro step called `ingest_daily_macro()` which only writes to `t1_macro` (wide: SPY/QQQ/VIX OHLCV). The long-format `macro_data` table (consumed by `risk_5_factor` and `m03_regime`) had no daily writer wired up — `write_to_macro_data` was only callable via the legacy `scripts/backfill_macro_rates.py`.
  * Downstream impact: `t2_risk_scores` and m03 regime computations were silently using 17-day-old macro data for ~3 weeks.
* **Fix (Option A — minimal):** [src/orchestrators/daily_pipeline_orchestrator.py:693-732](../../../src/orchestrators/daily_pipeline_orchestrator.py#L693-L732) now calls both `ingest_daily_macro()` and `update_macro_cache(write_db=True)` and reports correct row counts for each table.
* **Catch-up:** Manual `update_macro_cache` run brought all 8 series (WALCL/WTREGEN/RRPONTSYD/BAMLH0A0HYM2/DGS10/DGS2/WBAA/VIX) to within ~1 day of current.
* **Dashboard tweak:** `macro_data` freshness tolerance bumped 2d → 8d ([scripts/pages/5_Pipeline_Health.py:44](../../../scripts/pages/5_Pipeline_Health.py#L44)) — weekly series (WALCL/WTREGEN/WBAA) were flashing false-positive stale.
* **Known limitation (not fixed):** the freshness panel uses one tolerance per table, but `macro_data` is long-format with mixed daily/weekly frequencies. Per-symbol freezes would still be hidden. Acceptable for now; revisit if it bites.

### T1 Ingestion Failures ✅ DONE 2026-05-29
* **Plan:** [t1_ingestion_failures_plan.md](t1_ingestion_failures_plan.md)
* **Phase A (errors readable):** per-ticker failure causes now captured; classifier widened to recognise yfinance-flavoured NO_DATA strings. Today's 14 failures correctly classified `NO_DATA` (vs. all-`FETCH_FAILURE` before).
* **Phase B (price triage):** deactivated 14 chronic-NO_DATA tickers (BLBX, THAR, VRAR, PX, ATGE, CASI, TSE, AHH, ABP, IMG, GLTO, CTHR, CMLS, ULY) via `tools/deactivate_tickers.py`. Universe 4020 → 4006 active.
* **Phase C (fundamentals staleness root cause):** found `_get_stale_fundamental_tickers` measured staleness against `MAX(updated_at)` (audit timestamp) instead of `MAX(period_end)` (data date). Result: 34 has-CIK tickers had missing 10-Q/10-K filings 57-183 days behind EDGAR. Fixed the query + added 24h cooldown. Daily fetch list goes from 1 → 345; new query flags 31/34 known-missed tickers vs old query's 0/34.
* **Phase D (dashboard reconciliation):** SKIPPED — investigated, found no hardcoded headline; dashboard reads `pipeline_error_log` live and is accurate by construction.
* **Follow-ups:** see §"T1 Ingestion Follow-ups" below.

### T1 Ingestion Follow-ups
Carved out of the T1 ingestion plan after Phases A+B+C landed. Listed roughly by effort × value.

| # | Item | Source | Notes |
|---|---|---|---|
| 1 | **Chronic-empty fundamentals re-fetch loop** | Generated by Phase C fix | DEFERRED per 2026-05-29 review — the daily cost of re-fetching ~30 chronic-empty tickers is trivial. Skip unless ATCX-style tickers become a measurable load. |
| 2 | ~~**16 cohort tickers with stale prices (>7d)**~~ ✅ DONE 2026-05-30 | Phase C cohort split | By the next daily run the cohort had grown to 34. Cross-checked all 36 of follow-up #4's cohort against yfinance: 26 confirmed dead (no data in 10d), 8 frozen at 2026-05-15 (likely pending M&A close — left active), 2 live (PSTG, RVYL). Deactivated the 26, including CMPO/COEP/VCIC from follow-up #4. Universe 4006→3980. **New audit trail:** `tools/deactivate_tickers.py` now requires `--reason` with `--execute` and writes one JSONL row per deactivation to `logs/data_quality/deactivations.jsonl` capturing `db_before`/`yf_evidence`/`db_after`. Remaining 101-200d cohort × >7d stale-price shrank 34→8 (the deferred frozen-at-05-15 group). Re-check next week. |
| 3 | ~~**25 EDGAR_NO_DATA tickers**~~ ✅ DONE 2026-05-29 | Phase C.2 finding | Probe found 66 active+CIK tickers w/ NULL filing_date. Triage: (a) bumped `REPORT_DATE_TOLERANCE_DAYS` 15→35d in [src/edgar_engine.py:230](../../../src/edgar_engine.py#L230) — covers fiscal-calendar drift like AZO Aug-FY, COST May-FY (4 rows filled on rerun); (b) deleted 66 phantom yfinance rows across 40 tickers where every EDGAR reportDate was >35d from the period_end — these were calendar-quarter slots yfinance fabricated for recent SPAC IPOs / blank-check shells / banks with annual-only filing cadence. Residual 22 cohort: 13 foreign filers (architectural floor), 8 pe-newer-than-EDGAR (self-resolves when next 10-Q files), 1 COST gap-guard-miss (genuine fiscal-calendar issuer, would need fiscal-quarter-aware matching). Scripts: `scratch/probe_edgar_no_data.py`, `scratch/delete_phantom_fundamentals.py`. **Regen risk:** yfinance will rewrite these phantom rows on the next daily run; structural fix would require a write-time EDGAR check, but the per-run delta is now small enough to re-clean if it bites. |
| 4 | ~~**27 no-CIK active equities**~~ ✅ DONE 2026-05-29 | Phase C cohort split | Cohort had grown to 36 by audit time. Root cause: SEC's `company_tickers.json` (loaded by `refresh_cik_map`) silently omits ~4K real US issuers whose `submissions.tickers` field is empty — EXAS, HOLX, TGNA, SEE, FOLD, GLDD all confirmed cases. **33/36 resolvable** via EDGAR full-text search + submissions cross-check (27 clean, 6 CIK-correct but issuer renamed in EDGAR post-merger). 3 dead-ticker successors (CMPO, COEP, VCIC) **not patched** — would surface wrong entity's filings; recommend deactivation via follow-up #2. `cik_map` 10,365 → 10,398; active-equity CIK coverage 98.2% → 99.0%. Scripts: `scratch/probe_no_cik_cohort.py`, `scratch/patch_no_cik_cohort.py`. Report: `scratch/probe_no_cik_cohort_report.md`. **Durability:** verified safe against quarterly `refresh_cik_map()` — that path only INSERT/UPDATEs rows present in the SEC file, leaves our patched rows untouched. |
| 5 | **Universe lifecycle automation** | Mid-session discovery | Both arms manual today. **Inflows:** `UniverseBackfillEngine.discover_tickers_fmp()` exists in [src/universe_backfill.py:265](../../../src/universe_backfill.py#L265) but only callable via `scripts/run_universe_backfill.py --discover-fmp`; no cron, no orchestrator hook. **Outflows:** [tools/deactivate_tickers.py](../../../tools/deactivate_tickers.py) (now with audit log per follow-up #2) is fully manual — humans must notice and run it (this sprint's #2 work surfaced 26 dead tickers that had been stale for 23-71 days). **Proposed scope:** (a) weekly inflow phase: discover→diff→queue backfill→write `pipeline_runs`; (b) daily outflow phase: detect tickers with N≥14 consecutive NO_DATA AND `last_px>30d`, yfinance-confirm via existing probe, auto-deactivate writing to existing `logs/data_quality/deactivations.jsonl` with `reason="auto: …"`; (c) safety: daily cap (e.g. ≤50/day) + dry-run first weeks + alert on inflow spikes. ~1 day + tests. See plan §"Universe Lifecycle Gap". |
| 6 | **`earnings_calendar` rate-limit-at-scale** | Pre-existing, flagged in EDGAR notes | yfinance silently rate-limits at ~3,400/3,981 tickers. Affects upcoming-earnings triggers for fundamentals refresh (not critical — 100d staleness covers it). Separate ticket. |
| 7 | **Bulk yfinance batch tuning** | Pre-existing | Revisit only if RATE_LIMIT ever dominates the error_type distribution. Currently NO_DATA dominates → not warranted. |
| 8 | **Audit scripts slow / 120s timeout** (premise corrected) | 2026-05-31 t1_macro fix | **CORRECTION 2026-05-31:** the original premise — "the audits *recompute* features in-process" — is FALSE. Verified by reading both files: `audit_t2_screener_features.py` and `audit_t3_sepa_features.py` already open `duckdb.connect(..., read_only=True)` and run **pure SELECTs over the stored tables** — no `FeaturePipeline`, no recompute, no progress bars. There is no stored-vs-recomputed drift to hide. **Actual residual (minor):** `tools/run_all_audits.py:51` uses a hardcoded **120s** subprocess timeout while the orchestrator's Phase-8 wrapper uses 600s, so a *manual* `run_all_audits` run can hit a false `subprocess_timeout` FAIL on the slow `ROW_NUMBER() OVER (PARTITION BY ticker)` warmup-split query against the 183M-row t2 table. **Fix (if pursued):** bump the run_all_audits timeout 120→600s to match the orchestrator. Out of scope per 2026-05-31 session decision. |
| 9 | ~~**Stale-fundamentals check has 4 false-positive classes**~~ ✅ DONE 2026-05-31 (scopes a+b) | 2026-05-31 #4 investigation | **Scope (b) — check rewrite:** `_check_filing_date_quality` now anchors on the most recent period_end *that has an actual filing* (`MAX(period_end) FILTER (filing_date IS NOT NULL)`) and flags stale ⟺ `today > last_filed_pe + EXPECTED_NEXT_FILING_LAG_DAYS` (135d, new config const), with the old flat-100d-since-`last_filing` kept only as a fallback when no filed quarter exists. **Discovery that changed the design:** anchoring on bare `MAX(period_end)` would MASK dead tickers — yfinance fabricates future-quarter rows with `filing_date=NULL` (NEGG/CMBM/ETHM had a `2026-03-31` phantom row, 61d old), so the filed-only filter is essential. Net effect: cohort 159→204 (un-masked ~45 genuinely-stale names the old check silently passed) AND cleared the per-quarter laggard false positives (PANW now OK; NEGG/CMBM/ETHM correctly flagged). The doc's assumption that (b) would *shrink* the cohort was wrong. **Scope (a) — instrument reclassification:** new `EDGAREngine.classify_ticker_types` (form-type → EQUITY/FOREIGN/FUND; 10-Q/10-K presence wins, else 20-F/40-F/6-K→FOREIGN, N-CSR/NPORT/...→FUND) + `scripts/enrich_ticker_types_edgar.py` (dry-run default, `--execute`, JSONL audit at `logs/data_quality/ticker_type_reclass.jsonl`, defaults to the stale cohort). **EXECUTED 2026-05-31** on the 204 cohort: **42 reclassified** (23 FOREIGN incl. TURB/DOX/ZNB/HIVE, 19 FUND incl. TY/EIC/ECC/OXLC), 127 confirmed EQUITY, 35 inconclusive (no-CIK, = follow-up #4 cohort, left unchanged). Active `ticker_type` now EQUITY 3899 / ETF 36 / FOREIGN 23 / FUND 19 / INDEX 3. Audit trail: 42 rows at `logs/data_quality/ticker_type_reclass.jsonl`. Orchestrator's `equity_tickers` query already filters `ticker_type='EQUITY'`, so the reclass dropped these 42 out of both the fundamentals fetch and the DQ check automatically — **verified end-to-end: stale equity cohort 204 → 162** (no orchestrator change needed). **Post-reclass deactivation triage (2026-05-31):** EDGAR-cross-referenced + yfinance-probed all 162 remaining flagged names. Split: **102 LIVE_BACKFILL** (EDGAR has a 10-Q/10-K ≤135d — fundamentals just lag), **25 "DEAD_CANDIDATE"** (EDGAR 10-x >135d), **3 NO_EDGAR_10X** (banks OZK/PFBC/DMRC — file off the recent-40 window). **Deactivation list is EMPTY:** all 28 dead-candidate+no-edgar names are *actively trading* (yfinance 10/10 bars, last 2026-05-29). The doc's "~25 dead, e.g. TURB 928d" premise was wrong — TURB was a live FOREIGN filer (now reclassified); the rest are (i) more funds/foreign filers my one-shot reclass missed because their *recent* form window had rolled past the last 10-x (EARN→CEF, DXR→CEF, NEGG/WALD/ZBAI→foreign), or (ii) genuine late/delinquent filers still trading (HUBG filed NT 10-Q; banks file off-window). **Staleness of fundamentals ≠ death of ticker** — deactivation keys on price liveness, and zero are price-dead. Artifacts: `scratch/stale_cohort_edgar_split.csv`, `scratch/dead_candidates_probed.csv`. **Open follow-ups (not deactivation):** (1) classifier improvement — reclass should inspect the *full historical* form set, not just recent-40, to catch rolled-window funds/foreign filers like EARN/DXR/NEGG; (2) the 102 LIVE_BACKFILL are backfill candidates (EDGAR/yfinance), low priority since the check no longer false-alarms on them per-quarter. Original 4-population analysis retained below. |
| 9-orig | (original analysis, retained) | 2026-05-31 #4 investigation | `_check_filing_date_quality`'s >100d stale flag conflates 4 populations (EDGAR cross-ref of the 159 active-equity cohort): **(a) closed-end funds / BDCs** (EIC, TY, ECC) that file `N-CSR`/`NPORT-P` and **never** 10-Q/10-K — have no quarterly fundamentals by design; **(b) foreign filers** (EEIQ, ZNB) filing `6-K`/`20-F`; **(c) genuinely dead** (DXR last 10-K 2012, HIVE only 8-K/13G) → real deactivation; **(d) false-positive laggards** (T filed 4/27, PANW filed 2/18) — current with EDGAR, just past 100d because the next quarter hasn't filed yet. **Only (c) is a deactivation target.** (a)+(b) are a `ticker_type`/instrument-class **misclassification** (they're in the EQUITY fundamentals cohort but shouldn't be); (d) means the flat 100d threshold is too tight. See §"Stale-Fundamentals Triage (#4)" for the full plan. |
| 10 | ~~**NULL-filing_date on write is invisible to pipeline health**~~ ✅ DONE 2026-05-31 (orig issue #2) | 2026-05-30 pipeline run | yfinance earnings-endpoint failures write a fundamentals row with `filing_date=NULL` but mark the ticker OK (`rows_written>0`), so it never enters `pipeline_error_log`. **Fix shipped (no new error_type, no schema change):** (1) `FundamentalEngine._null_filing_writes` set, reset each run, populated in the single-threaded write loop when a ticker's *newest* written quarter has a NULL filing_date (detected at write time on the actual data — more accurate than a fetch-side `earnings_dates is None` flag, and avoids worker-side shared state). (2) Orchestrator reads `len(_null_filing_writes)` into `results['fundamentals']['null_filing_written']`, logs a `[Phase 1] ... DQ:` summary line, and persists it via new `PipelineRunManager.update_phase_metadata(run_id, {...})` which JSON-merges into the existing `pipeline_runs.metadata` (preserves `ticker_count`). (3) Dashboard: `load_null_filing_writes(days)` reads `json_extract_string(metadata,'$.null_filing_date_written')` from the `phase_1_t1_ingestion` runs; Pipeline Health → Fundamentals Updates Audit shows an `st.metric` (last run) + 30-day trend caption. Deliberately NOT an error_type — would falsely flip the run to `warning` when the EDGAR backfill self-heals it. **Tested:** metadata merge round-trip (original keys preserved), newest-row NULL detection across ordered/shuffled/filed cases, loader query clean on live DB (0 rows until next daily run populates the field). Files: `src/fundamental_engine.py`, `src/orchestrators/daily_pipeline_orchestrator.py`, `src/managers/pipeline_run_manager.py`, `scripts/dashboard_utils.py`, `scripts/pages/5_Pipeline_Health.py`. |

### Stale-Fundamentals Triage (#4) — investigated 2026-05-31, plan below
**Trigger:** issue #4 from the 2026-05-30 pipeline run — "254 equities with stale fundamentals
(last_filing>100d)". Cohort is now **159** (the 5/30 EDGAR backfill of 468 rows drained the rest).
EDGAR-cross-referenced all 159 active EQUITY-typed tickers by form type + most-recent 10-Q/10-K.

**The cohort is NOT a dead-vs-live split — it's 4 distinct populations:**

| Bucket | N | What | Action |
|--------|---|------|--------|
| **1. Misclassified** | 39 | Closed-end funds / BDCs (`N-CSR`/`25-NSE`/`40-17G`: TY, EIC, HQL, OXLC, NXP, OZK) + foreign filers (`20-F`/`40-F`: ZNB, CRML, **TURB**, DOX, KGEI, HIVE). **Never file 10-Q/10-K** → no quarterly fundamentals *by design*. | **Exclude from cohort**, not deactivate. Tag `ticker_type` (CEF/ADR/FOREIGN) so the staleness check skips them. *NB: TURB — the original doc's "928d worst case dead ticker" — is a foreign 20-F filer, very much alive. The "may be delisted" framing was wrong.* |
| **2. Dead** | 25 | Filed 10-Q/10-K historically, nothing in 120d (DXR last 10-K 2012, EARN, NEGG, HUBG, WINT, CARV, …). | **Deactivate** — but yf-confirm each via the follow-up-#2 probe pattern first (some may be pending-M&A, not dead). Write to `logs/data_quality/deactivations.jsonl` with `reason="stale-fundamentals: no EDGAR 10-Q/10-K in >120d + no yf data"`. |
| **3. Current / laggard** | 69 | EDGAR has a 10-Q/10-K ≤120d. **Two sub-cases:** (i) genuine backfill — EDGAR newer than ours (T: EDGAR 4/27 vs our 2/9; GYRO: EDGAR 5/13 vs our 2024-03; RMCF/FNGR/NTRP: EDGAR 5/29 vs our 1/13); (ii) pure threshold false-positive — already have the latest quarter (PANW our=EDGAR=2/18; UVV/MLAB period_end 2026-03-31), flagged only because 100d elapsed since the *last filing* though no new quarter exists yet. | (i) **Backfill** via `FundamentalEngine.backfill_fundamentals` + EDGAR filing-date fill. (ii) **No action** — fix the *check* (below). |
| **4. No CIK** | 26 | `submissions.tickers=[]` artifact (same as follow-up #4). HPCO, SYRS, PBF, CMBM, … | Run `scratch/patch_no_cik_cohort.py`-style probe to recover CIKs, then re-triage into 1–3. |

**Root-cause takeaway — the deactivation list is the *small* part of this.** Only ~25 are real
deactivations. The bigger structural issues the cohort exposes:
1. **Instrument misclassification (39):** CEFs/BDCs/foreign filers are typed `EQUITY` and run through
   the equity fundamentals path, which can never succeed for them. They pollute the staleness cohort
   *and* waste a yfinance fetch every run. Needs a `ticker_type` enrichment (EDGAR form-type is the
   authoritative signal: presence of `20-F`/`40-F` → FOREIGN; `N-CSR`/`N-CEN`/`25-NSE` → FUND).
2. **Flat 100d threshold is too tight (sub-bucket 3-ii):** a normal issuer is >100d-since-last-filing
   for ~45 days of every quarter (10-Q lands ~45d after period_end, next quarter ends ~90d later).
   The check should compare against **expected next-filing date** (last `period_end` + ~135d), not a
   flat days-since-last-filing.

**Phased plan:**
- **Phase 1 (deactivation — the original ask):** yf-confirm the 25 Bucket-2 dead tickers, deactivate the
  confirmed dead via `tools/deactivate_tickers.py --reason ... --execute`. ~45 min. *This is the list the
  5/30 run was started to build.*
- **Phase 2 (backfill):** run EDGAR/yfinance backfill for the ~30-40 genuine Bucket-3(i) laggards. ~30 min.
- **Phase 3 (CIK recovery):** patch the 26 no-CIK, re-triage. ~30 min.
- **Phase 4 (structural — the real fix):** (a) EDGAR form-type → `ticker_type` enrichment to pull the 39
  misclassified out of the equity cohort; (b) rewrite `_check_filing_date_quality` staleness to use
  `last_period_end + expected_filing_lag` instead of flat 100d-since-filing. ~half day + tests.
- Triage script: `scratch/triage_stale_fundamentals.py` (to be saved from this session's probe).

### Fundamentals Update Audit Table ✅ DONE 2026-05-29
* **Original framing (incorrect):** Assumed broken mapping logic — fix the transform.
* **Actual diagnosis:** Mapping logic was fine. Two real causes:
  1. **Path was the wrong source.** Existing `_fetch_filing_dates_for_ticker` round-trips yfinance live for each ticker, ignoring our local `earnings_calendar` table (which already has the data for ~570 tickers).
  2. **earnings_calendar itself is sparse** — only **570 / 3,981 active equities** have any entries. The orchestrator's `phase_1_earnings_calendar_refresh` ran exactly once (2026-05-27), took 9.6 min, and wrote **0 rows** for 3,744 attempted tickers — yfinance silently rate-limits at scale.
  3. The fundamental issue is that yfinance is the wrong primary source for authoritative filing dates. SEC EDGAR is.
* **Three-stage fix shipped:**
  1. **Stage 1 (low-hanging):** `backfill_filing_dates_from_calendar` — SQL-only path that uses the local `earnings_calendar` table without yfinance round-trips ([src/fundamental_engine.py:508-580](../../../src/fundamental_engine.py#L508-L580)). Updated 244 rows from existing local data.
  2. **Stage 2 (the real fix):** New `EDGAREngine` ([src/edgar_engine.py](../../../src/edgar_engine.py)) querying SEC's `data.sec.gov/submissions/CIK*.json` directly. Matches `reportDate ≈ period_end` within ±15 days, gap guard ≥8 days. Authoritative source. **Updated 3,068 rows across 2,516 tickers in 8 minutes.** Coverage 42.9% → **97.73%**.
  3. **Stage 3 (orchestrator wiring):** Daily pipeline now runs `phase_1_cik_map_refresh` (weekly, gated) and replaced `phase_1_filing_date_backfill` to use EDGAR. ([src/orchestrators/daily_pipeline_orchestrator.py:739-859](../../../src/orchestrators/daily_pipeline_orchestrator.py#L739-L859))
* **Residual 143 NULL rows breakdown:**
  * 95 — active tickers with CIK but EDGAR `reportDate` outside ±15d tolerance (fiscal-calendar mismatch — e.g. AZO has Aug fiscal year-end)
  * 41 — active, no CIK in EDGAR (foreign ADRs, SPACs, OTC) — architectural floor
  * 7 — inactive tickers
* **Files added/touched:**
  * NEW: [src/edgar_engine.py](../../../src/edgar_engine.py) (EDGARClient + EDGAREngine)
  * NEW: [scripts/backfill_filing_dates_edgar.py](../../../scripts/backfill_filing_dates_edgar.py) (CLI)
  * NEW DuckDB table: `cik_map` (10,365 rows)
  * Edited: [config.py](../../../config.py) (EDGAR_*, CIK_MAP_REFRESH_DAYS, failure modes)
  * Edited: [src/fundamental_engine.py](../../../src/fundamental_engine.py) (Stage 1 calendar backfill)
  * Edited: [src/orchestrators/daily_pipeline_orchestrator.py](../../../src/orchestrators/daily_pipeline_orchestrator.py) (cik_map refresh + EDGAR backfill phases)
* **Note on `EDGAR_USER_AGENT`:** defaults to a placeholder. Set a real `EDGAR_USER_AGENT="Your Name your@email"` in `.env` before next daily run.
* **Out-of-scope discovery — earnings_calendar refresh is broken at scale.** The path that *should* keep `earnings_calendar` current silently fails for ~3,400 of 3,981 active equities (yfinance rate-limit at parallelism). It's now less critical because filing_date no longer depends on it, but **the upcoming-earnings trigger for fundamentals refresh** still uses it. If a ticker doesn't get into `earnings_calendar`, the daily pipeline won't know to re-pull its fundamentals after a reporting event — falls back to the 100-day staleness check. Worth a separate investigation later.

### Pipeline Health Page: Audit History ✅ DONE 2026-05-29
* **Diagnosis:** Wasn't an overwrite bug. The orchestrator simply *never* invoked `tools/run_all_audits.py` — so `data/audit_reports/` only ever held the one JSON the user had generated manually back on 2026-03-28. Filename pattern is already date-keyed (`audit_report_YYYYMMDD.json`), so appending is automatic once the orchestrator writes.
* **Fix:**
  * [src/orchestrators/daily_pipeline_orchestrator.py:1106-1170](../../../src/orchestrators/daily_pipeline_orchestrator.py#L1106-L1170) — new `_run_daily_audits()` method invoked from Phase 8 after drift report. Subprocess call to `tools/run_all_audits.py --date <target_date> --warn-only` (600s timeout). Best-effort: failures only log a warning, never break the phase. Logs summary line `FAIL=N WARN=N OK=N overall=...` for grep-ability.
  * [scripts/pages/5_Pipeline_Health.py:359-376](../../../scripts/pages/5_Pipeline_Health.py#L359-L376) — added caption explaining the new daily write path; tightened the single-point warning copy.
* **Why subprocess (not direct import):** `run_all_audits` already spawns one subprocess per audit module to keep their module-level state isolated. Direct import would couple the orchestrator's start-time to four audit script imports plus their transitive deps. Subprocess matches the script's existing contract (`--json`, exit 0/1/2) and trivially handles timeouts.

### Fundamental Engine Investigation
* **Issue:** Needs general investigation/review.
* **Investigation Plan:** Define the specific performance, accuracy, or efficiency bottlenecks currently suspected in the fundamental engine. Review execution logs, query times, and resource usage.
* **Implementation Plan:** Refactor inefficient queries, add necessary database indices, optimize memory usage, or parallelize processing based on findings.

---

## 3. Model & Evaluation

### Calibrate Prototype Model ✅ DONE 2026-05-29
* See §Execution Priorities for the one-line result summary (m01_prototype_cali_v1, ECE 0.142→0.125, band degraded due to E2_trade_frequency gate). Detailed post-mortem TBD.

### Model Card with Longer Period ✅ DONE 2026-05-29
* Diagnosis / fix notes TBD.

### Risk: 5-Factor Model
* **Issue:** Clarify Z-score memory, consider adding more factors, clarify what the output numbers mean, show factor weights, and try combining factors.
* **Investigation Plan:** Investigate the current Z-score memory mechanism to understand its behavior. Analyze the current 5 factors to see if they capture enough variance. Determine the mathematical representation of the current output numbers.
* **Implementation Plan:** Add documentation explaining the meaning of the output numbers. Add visualizations to show the weight/contribution of each factor in the UI. Experiment with combining existing factors or adding new macroeconomic/statistical factors. Refine the Z-score memory implementation.

### Eval Framework Phase 4
* **Issue:** Needs implementation/planning for Phase 4.
* **Investigation Plan:** Review the requirements document or previous architectural discussions for Phase 4 of the evaluation framework. Identify the specific metrics or capabilities missing (e.g., real-time tracking, advanced attribution analysis).
* **Implementation Plan:** Develop and integrate the Phase 4 features into the eval framework codebase. Write unit tests and generate sample reports to verify the new functionality.

---

## 4. Sunday Sprint Plan (infra_uplift)

**Goal (inferred):** get the Streamlit dashboard running against a **remote-hosted database**
so it's accessible off the dev box, with the code on GitHub. This is a deployment-prep sprint,
not a feature sprint.

**The dominating constraint — DB size.** `data/market_data.duckdb` is **71.8 GB**, almost
entirely `t2_screener_features` (183M rows) + `price_data` (29M) + `t3_sepa_features` (9.3M).
That single fact drives every decision below: you cannot put this DB on GitHub (100 MB/file hard
limit), and shipping 72 GB to a remote host is slow/expensive. **But the dashboard reads only a
thin slice of it.** So the sprint is really: *carve out the dashboard's actual data dependency,
host that, point the app at it.*

### 4.1 List all tables/data used in dashboard
* **Status:** First pass done (scanned `scripts/pages/*.py` + `scripts/dashboard_utils.py`).
  **Tables/views the dashboard actually queries:**
  `company_profiles`, `price_data`, `daily_features`*, `t2_screener_features`,
  `t3_sepa_features`, `d2_training_cache`, `daily_predictions`, `fundamentals`,
  `shares_history`, `macro_data`, `t1_macro`, `t2_regime_scores`, `t2_risk_scores`,
  `screener_membership`, `screener_watchlist`, `sepa_watchlist`, `earnings_calendar`,
  `pipeline_runs`, `pipeline_error_log`, `models`, `v_d3_deployment`.
* **TODO to finish this item properly:**
  1. Confirm the list programmatically (the regex scan caught CTE aliases like `latest_t2`,
     `t3_latest` — filter those out; they're derived, not base tables).
  2. For each table, record **what slice** the dashboard needs (e.g. Pipeline Health only reads
     `pipeline_runs`/`pipeline_error_log` last 30d; EDA reads `price_data` but likely only recent
     window + screener universe, not all 29M rows; `t2_screener_features` — does any page read the
     full 183M, or only `latest_t2`/spot-date?). **This is the key question** — if the dashboard
     only needs *recent* t2/t3 + full small tables, the hosted DB could be <1 GB.
  3. Produce a manifest: `table → (columns, row-filter, approx size)` → drives 4.3.

### 4.2 Upload to GitHub
* **Code, not data.** Verify `.gitignore` excludes `data/*.duckdb`, `data/*.bak_*`,
  `logs/`, `scratch/`, model artifacts (`models/**/*.json` may be wanted — decide), and the
  72 GB backups (`data/market_data.duckdb.bak_0531_t1macro` etc — **delete these first**, they're
  67 GB each).
* **Pre-flight:**
  1. `git status` is currently dirty (12 modified, several untracked incl. `scratch/`, model_cards) —
     review and stage deliberately. `scratch/` should NOT go up (probe scripts, ephemeral).
  2. Scan for secrets before first push: `.env` (FMP/FRED API keys, `EDGAR_USER_AGENT`),
     any hardcoded creds. Ensure `.env` is gitignored and add `.env.example` with key names only.
  3. Decide model-artifact policy: `models/*/v1/model.json` are smallish (XGBoost JSON) — probably
     keep in git or Git LFS; `model_cards/*.json` are tiny → keep.
* **Risk:** first push of a repo that has ever had a 72 GB file *committed* would be fatal. Confirm
  the DB was never committed (`git log --all --oneline -- data/market_data.duckdb` should be empty).

### 4.3 Move to remote
* **Decision needed first (blocks everything):** what's the remote? Options, cheapest→heaviest:
  * **(A) Slim read-replica DuckDB + object storage.** Build a `dashboard.duckdb` containing only the
    4.1 slices (likely <1 GB), push to S3/R2/GCS, have the deployed app download-on-boot or read via
    `duckdb`'s httpfs. Simplest if the dashboard is read-only (it is). **Recommended starting point.**
  * **(B) Hosted Postgres** (Supabase/Neon/RDS). More work (schema port, type mapping, ETL), but
    proper concurrent access + incremental updates. Overkill unless multiple writers/users.
  * **(C) MotherDuck** (hosted DuckDB). Closest to current code — minimal query changes, `md:` DSN.
    Pay-per-use; good middle ground if you want to keep DuckDB SQL verbatim.
* **Recommended path (A):**
  1. Write `scripts/build_dashboard_db.py` — reads the 4.1 manifest, `ATTACH` source DB, `CREATE
     TABLE ... AS SELECT <slice>` into a fresh `dashboard.duckdb`. Idempotent, re-runnable nightly
     after the daily pipeline.
  2. Parameterize the dashboard's DB path (env var `DASHBOARD_DB_PATH`, default local) so the same
     code runs local-full or remote-slim.
  3. Host: push `dashboard.duckdb` to object storage; deploy Streamlit (Streamlit Community Cloud /
     Fly.io / a small VM) that pulls it on boot or refreshes on a schedule.
  4. Wire the nightly refresh: orchestrator Phase 8 (or a separate cron) rebuilds + re-uploads the
     slim DB after the daily run.
* **Open questions for the user (resolve before building):**
  * Who/what accesses the remote dashboard — just you, or shared? (drives auth + host choice)
  * Read-only snapshot refreshed nightly (path A), or live-updating (path B/C)?
  * Budget tolerance (A ≈ storage-only cents; C = usage-based; B = always-on instance)?
* **Definition of done:** dashboard loads every page from the remote slim DB, off the dev box,
  with a documented nightly refresh path.