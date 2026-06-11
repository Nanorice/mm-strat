# Daily Pipeline Run (2026-05-30) — Findings & Plans

Investigation of the 5/29 ingestion run kicked off to build the ticker-deactivation
list. Eight log-line questions raised; this doc records what each one actually means
(traced to source), which are working-as-designed, and the open action items.

Run context: target 2026-05-29, `active=4006`, prod model
`m01_prototype_2003_2026_20260514_233125`.

---

## TL;DR — what needs action

| # | Item | Status | Action |
|---|------|--------|--------|
| 1 | active/stale window (45d) | WAD | none — explained below |
| 2 | yfinance "no earnings dates" for live tickers | **GAP** | surface NULL-filing_date in pipeline health (proposal below) |
| 3 | `_upsert_to_duckdb` write contents | WAD | none — explained below |
| 4 | 254 stale-fundamentals equities | **ACTION** | EDGAR triage → deactivate vs backfill (plan below) |
| 5 | EDGAR backfill in daily | WAD | none — by design (drains NULL filing_date backlog) |
| 6 | audit `overall=FAIL` (6 FAIL) | ✅ **DONE** | backfilled `t1_macro` 6 dates + recomputed T2 → macro/T2 FAILs cleared (2 pre-existing low-sev residuals) |
| 7 | prediction logging | WAD | none — PIT paper-trade record, keep it |

WAD = working as designed.

---

## 1. `active=4006, stale=3989` — why the 45-day window, not last-trading-day?

[`DataRepository._get_stale_tickers`](../../../src/data_engine.py#L199-L227).

Two independent filters in one query:

- **Staleness test** = `fresh.ticker IS NULL`, i.e. *no price row dated exactly
  `latest_trading_day`*. This is the last-trading-day check you expected.
- **45-day window** = a **liveness floor** (`INNER JOIN ... recent` on
  `date >= latest_trading_day - 45d`). It restricts the retry set to tickers that
  traded *at least once* in the last ~2 months.

Why the floor exists: without it, a delisted/dead ticker that has no bar for months
would be flagged stale **forever**, retried every run, fail every run, and pollute
`pipeline_error_log`. 45 calendar days (~31 trading days) is comfortably longer than
any halt/holiday gap but short enough to drop genuinely-dead names from the retry loop.

So `active − stale = 17` non-stale tickers already had a 5/29 bar before the run
(prior partial run / index instruments). This is expected. The real guarantee comes
from **Phase 1.5** ([orchestrator L497-547](../../../src/orchestrators/daily_pipeline_orchestrator.py#L497-L547)),
which re-ingests any active ticker still missing a 5/29 bar after Phase 1.

**Verdict: working as designed.** Target date → stale/fresh; 45d → worth-retrying/abandoned.

---

## 2. `ERROR <T>: No earnings dates found, symbol may be delisted` — for live names like "A"

### What it is
The string is printed **by yfinance internally**, not our code. It comes from
`t.get_earnings_dates()` inside
[`_fetch_from_yfinance`](../../../src/fundamental_engine.py#L246-L248), which is wrapped:

```python
try:
    earnings_dates = t.get_earnings_dates(limit=40)
except Exception:
    earnings_dates = None
```

When earnings fetch returns nothing, `_map_period_end_to_filing_date` returns `{}`
→ the row is written with **`filing_date = NULL`**. The IS/BS/CF statements are
*separate* yfinance calls and usually still succeed, so the fundamentals row lands fine.

The "may be delisted" text is yfinance's, **not a reliable delisting signal**. Genuine
delistings (ACLX) look identical to transient rate-limit failures (A = Agilent, very
much alive). So this line **cannot** be used to drive deactivation.

### The real problem: it is invisible to pipeline health
Confirmed against the DB. Ticker "A":
- latest fundamentals row `2026-04-30 (yfinance)` has **`filing_date = None`**, yet
- there is **no fundamentals error** for "A" in `pipeline_error_log`. The only "A"
  rows there are `phase_1_t1_price` FETCH_FAILUREs — a different sub-phase.

Structural cause: [`update_fundamentals`](../../../src/fundamental_engine.py#L977-L1000)
marks a ticker **OK** when *any* row is written (`rows_written > 0`), and **only
not-OK tickers** flow into `last_errors → record_errors → pipeline_error_log`. A
ticker with good statements but a failed earnings call is `OK`, so the NULL
filing_date never registers as an error anywhere.

The EDGAR backfill (#5) does repair most of these NULLs on a later run, but until it
runs the gap is silent — and the EDGAR floor (foreign filers, no-CIK) never gets repaired.

### Proposed fix (observability, low risk)
Don't touch the OK/not-OK logic (statements *did* write — that's correct). Instead, add
a **non-fatal DQ counter** so the failure is visible:

- In `_fetch_from_yfinance`, when `earnings_dates is None`, record the ticker in a
  `self._earnings_fetch_failures` set (distinct from `_fetch_error_causes`, which is
  reserved for genuine write failures).
- In `update_fundamentals`, after the loop, emit these via `record_errors` with a new
  `error_type = 'EARNINGS_NO_DATA'` (so the heatmap promotes the run to `warning`,
  not `failed`) — OR simpler: log a single summary line
  `[Phase 1] DQ: N tickers wrote fundamentals but NULL filing_date (earnings fetch failed)`
  and let `_check_filing_date_quality` (already runs right after) own the count.

Recommendation: the **summary-line + existing DQ check** is enough; `_check_filing_date_quality`
already reports NULL/stale filing_date counts. The only missing piece is that *new*
NULLs from this run aren't distinguished from legacy NULLs. A per-run
`null_filing_date_written` count in the Phase-1 stats dict, surfaced on the Pipeline
Health page, closes the gap without new tables. **~30 min.**

---

## 3. What `_upsert_to_duckdb` writes

[`_upsert_to_duckdb`](../../../src/fundamental_engine.py#L341-L392) writes **one row per
fiscal quarter** into the `fundamentals` table. Per row:

- **PK**: `(ticker, period_end)`
- `period_type` (`'quarterly'`), `filing_date`, `source='yfinance'`, `updated_at`
- **35 numeric financial columns** mapped from yfinance
  ([`_INCOME_MAP`/`_BALANCE_MAP`/`_CASHFLOW_MAP`](../../../src/fundamental_engine.py#L32-L79)):
  - **15 income-statement**: total_revenue, cost_of_revenue, gross_profit,
    operating_income, operating_expense, ebit, ebitda, net_income, basic_eps,
    diluted_eps, basic_avg_shares, diluted_avg_shares, r_and_d, sga, tax_provision
  - **14 balance-sheet**: total_assets, current_assets, cash_and_equivalents,
    inventory, accounts_receivable, total_debt, net_debt, current_liabilities,
    long_term_debt, stockholders_equity, retained_earnings, working_capital,
    invested_capital, tangible_book_value
  - **6 cash-flow**: operating_cash_flow, free_cash_flow, capex, stock_based_comp,
    change_in_working_capital, depreciation_amortization

Two non-obvious rules in this write:
- `operating_income` is **component-derived** (`gross_profit − sga − r_and_d`), not
  yfinance's headline value, because the headline is inconsistent (sometimes
  adjusted/non-GAAP). Falls back to raw only when components are missing.
- UPSERT on `(ticker, period_end)` conflict **overwrites** (to absorb restated
  quarters) **EXCEPT** where `source='fmp'` — FMP rows are the authoritative backfill
  and are never clobbered by yfinance (`WHERE fundamentals.source != 'fmp'`).

**Verdict: working as designed.**

---

## 4. `254 equities with stale fundamentals (last_filing>100d)` — ACTION

[`_check_filing_date_quality`](../../../src/orchestrators/daily_pipeline_orchestrator.py#L1396-L1411).
254 active equities whose **most recent `filing_date` is >100d old**
(`FUNDAMENTAL_STALENESS_DAYS`); `null_filing=0` (all 254 have *a* filing date, just old).
Worst sample: TURB at 928d (~2.5yr → almost certainly delisted).

These are two populations that need different handling:

- **(A) Genuinely dead** — delisted/acquired/long-dark issuers. A 928d gap can't be
  re-fetched into existence; the company simply hasn't filed. → **deactivate** (feeds
  the very list this run was started to build).
- **(B) Real laggards** — a recent 10-Q exists in EDGAR but our pipeline missed it
  (yfinance earnings-date failure per #2, or an ingestion gap). → **backfill**, not deactivate.

### Plan (the cross-reference splits A from B authoritatively)

1. **Pull the 254** with `last_filing` age, from `_check_filing_date_quality`'s query
   (or a standalone script `scratch/triage_stale_fundamentals.py`).
2. **Join to `cik_map`** and query EDGAR `submissions/CIK*.json` for each:
   - **No CIK / no recent EDGAR filing** (most recent 10-Q/10-K also >100d, or none) →
     **bucket A (deactivate)**. TURB expected here.
   - **EDGAR has a 10-Q/10-K filed within ~100d** → **bucket B (backfill)**: our data is
     stale but the issuer is live. Run `EDGAREngine.backfill_filing_dates_from_edgar`
     (filing dates) and/or `FundamentalEngine.backfill_fundamentals` (the actual
     statements) for these tickers.
3. **Apply**:
   - Bucket A → `tools/deactivate_tickers.py` (same path used for the 14 chronic-NO_DATA
     names in T1 Phase B).
   - Bucket B → targeted backfill, then re-run `_check_filing_date_quality` to confirm
     they drop off the stale list.
4. **Record** the A/B split + counts in this doc and in `misc_todo_0529.md` follow-up #2
   (which already tracks "stale-price likely-delisting" deactivations — fold the
   fundamentals-stale deactivations into the same batch).

Reuses existing tooling end-to-end; no new infrastructure. Est. ~1h including the EDGAR
round-trip for 254 tickers (rate-limited at 10 req/s → ~30s of API + triage).

> Note: this overlaps T1-ingestion follow-up #2 (stale-price delistings). Run both
> cross-references together and deactivate once.

---

## 5. `[EDGAR/Backfill] Updated 468 rows across 159 tickers` — why in the daily pipeline?

[`_run_phase_1_filing_date_backfill`](../../../src/orchestrators/daily_pipeline_orchestrator.py#L797-L862).
**By design** — it exists precisely to repair the NULL `filing_date` rows that #2
produces. Daily fundamentals come from yfinance (flaky earnings endpoint → frequent
NULL filing dates); SEC EDGAR is the authoritative filing-date source.

It is **bounded and cheap**, not a re-backfill of everything:
- Eligible only where `source='yfinance' AND filing_date IS NULL AND period_end older
  than FILING_BACKFILL_MIN_AGE_DAYS`.
- Capped at `FILING_BACKFILL_MAX_TICKERS` per run, most-missing-first.
- 468 rows / 159 tickers this run = draining a small backlog, not churning.

Running it daily keeps `filing_date` (the point-in-time anchor; NULL = no lookahead-safe
timestamp) from accumulating gaps. **Verdict: working as designed.**

---

## 6. Audit `FAIL=6 WARN=32 OK=140 overall=FAIL` — ✅ FIXED 2026-05-31

> **RESOLVED.** Backfilled `t1_macro` for the 6 missing dates (`INSERT OR IGNORE`,
> exactly 6 rows added, existing rows untouched) then recomputed T2 **per-date** (6
> single-day `DELETE WHERE date=d` + `INSERT` calls — never touched the surrounding
> ~6 weeks of good data). DB backed up first → `data/market_data.duckdb.bak_0531_t1macro`.
>
> **Verification:** all 6 dates now have `null price_vs_spy = 0` (was 100%) and real
> `trend_ok` counts (272–668 true, was 0). The 4 macro/T2 FAILs
> (`date_gaps_vs_price_data`, `null_vix_close`-via-gap, `zero_trend_ok_dates`,
> `price_vs_spy_null_dates`) all cleared.
>
> **Direct DB verification (bypassing the slow audit wrapper):**
> - `t1_macro` gaps vs price_data: **6 → 1**. The 1 residual is **2001-09-11** (market
>   closed post-attacks; 1 stray price row, no SPY/QQQ/VIX because the market never
>   opened) — a legitimate market-closure date the audit whitelists, NOT my fix.
> - T2 dates with 0 `trend_ok` since 2026-03-01: **0** (was 6).
> - T2 dates fully NULL `price_vs_spy` since 2026-03-01: **0** (was 6).
>
> **Residual (NOT this gap, pre-existing, low severity — separate tickets):**
> - `price_data/tickers_with_gaps = 4` — thin/halted names with >20% fewer bars than SPY. Data shape, not a bug.
> - `t1_macro/null_vix_close = 1` on **2026-04-08** — single-day NULL VIX (SPY present). Pre-existing, outside the 6 fixed dates. Trivial one-day VIX backfill.
> - `null_rs_on_2026-05-29 = 385` — tickers without enough trailing lookback. Data shape.
>
> **Note on the audit wrapper:** `audit_t2/t3_*.py` *recompute* features internally, so
> they're slow (the manual re-run hit a 120s subprocess timeout — a wrapper artifact,
> not a data failure). The orchestrator's Phase 8 uses a 600s timeout and is unaffected.
>
> Original diagnosis below, retained for the record.

---



`tools/run_all_audits.py` run as a Phase-8 subprocess with `--warn-only` (non-blocking;
recorded for the Pipeline Health dashboard). The report:
`data/audit_reports/audit_report_20260530.json`.

**5 of the 6 FAILs trace to a single `t1_macro` gap.** Confirmed in DB — `t1_macro` is
missing rows for 6 trading days that exist in `price_data`:

```
2026-03-30, 2026-04-06, 2026-04-09, 2026-04-15, 2026-05-04, 2026-05-08
```

(`t1_macro` MAX date = 2026-05-29, so the head is current; these are mid-history holes.)

| FAIL | Root |
|------|------|
| `t1_macro/date_gaps_vs_price_data = 6` | the gap itself |
| `t1_macro/null_vix_close = 1` | same gap family (1 NULL VIX) |
| `T2 trend_continuity/zero_trend_ok_dates = 6` | **downstream** — no SPY in t1_macro → `price_vs_spy` NULL → `trend_ok` can't compute → 0 trend_ok on those 6 dates |
| `T2 trend_continuity/price_vs_spy_null_dates = 6` | **downstream** — same 6 dates |
| `price_data/tickers_with_gaps = 4` | 4 thin/halted names with >20% fewer bars than SPY (independent, minor) |
| `spot_date/null_rs_on_2026-05-29 = 385` | 385 rows NULL `rs` on 5/29 — tickers without enough trailing lookback (newly-active/sparse), independent |

The 32 WARNs are mostly **expected** NULLs: first-row-per-ticker `pct_chg`, warmup-period
ranks, ~5.7% T3 rank/M03 nulls inherited from T2 joins, plus the same 6-date drop
appearing as `trend_ok_large_drops`.

### Action
**Backfill `t1_macro` for the 6 missing dates, then recompute T2 for that range.** That
clears 4 macro/T2 FAILs in one shot. The remaining 2 (`tickers_with_gaps`,
`null_rs_on_2026-05-29`) are low-severity data-shape facts, not bugs — note and move on.

Root-cause question to chase separately: **why did `ingest_daily_macro` skip those 6
specific dates?** They span Mar 30 → May 8 — not a contiguous outage, so it looks like
per-day ingestion misses rather than one window. Likely the same class of issue as the
macro_data "wrong table" bug fixed 2026-05-29; worth a targeted look once backfilled.

---

## 7. `Logged 17 predictions ... model=m01_prototype_...` — do we need this?

Yes. [`_log_prod_model_predictions`](../../../src/orchestrators/daily_pipeline_orchestrator.py#L1178-L1272)
scores **every** SEPA candidate dated 5/29 from `v_d3_deployment` and writes the **full
probability vector** per ticker (`prob_class_0..N`, `predicted_class`) — 17 candidates
that day, **not** a top-N cut.

Purpose: **point-in-time paper-trade logging** — capture what the prod model said *on the
day*, before outcomes are known. Without it, live model performance can only be
reconstructed later from possibly-revised features (lookahead risk). "Top tickers of the
day" is a *view* you derive by filtering these rows on probability; the stored record is
the raw scored output needed for calibration, hit-rate tracking, and drift.

**Verdict: working as designed — keep it.**

---

## Consolidated action items

1. **[#6] Backfill `t1_macro`** for `2026-03-30, 04-06, 04-09, 04-15, 05-04, 05-08`,
   recompute T2 for the range → clears 4 audit FAILs. Then investigate why those 6 dates
   were skipped by `ingest_daily_macro`.
2. **[#4] EDGAR-triage the 254 stale-fundamentals equities** → bucket A (deactivate, e.g.
   TURB) vs bucket B (backfill). Fold deactivations into the same batch as T1 follow-up #2.
3. **[#2] Surface NULL-filing_date-on-write in pipeline health** — per-run
   `null_filing_date_written` count in Phase-1 stats → Pipeline Health page. ~30 min.
