# Session Handover: 2026-07-04

## 🎯 Goal
Review the dirty-shares/market-cap DQ-gap issue draft, harden the T1 audit against the whole
plausibility-gap class, and clean the corrupt shares/price data safely on both machines.

## ✅ Accomplished
- **Reviewed** `ISSUE_dirty_shares_cap_dq_gap.md` — verified root cause and all counts against
  the live DB (61 shares >100B, 101 implied-cap >$8T all reproduce exactly).
- **Found the gap is systemic**, not a one-off: every integrity check validates presence/type,
  none validate plausibility. Extended the audit accordingly.
- **Wired 4 FAIL-level DQ checks** into `audit_t1_data_quality.py`: `absurd_share_count`,
  `absurd_implied_market_cap` (shares section), `absurd_close_price`, `ohlc_ordering` (price
  section). All verified firing at the correct pre-cleanup counts.
- **Traced the true source** of both corruption modes:
  - Shares: `backfill_shares_from_fundamentals.py` copied `fundamentals.basic_avg_shares`
    (FMP has 1000×+ scaling dirt, values to 64 trillion) with no upper bound.
  - Price: legacy `source=None` rows; but yfinance's own historical data is ALSO dirty for
    these low-float tickers → refetch is impossible.
- **Bounded the backfill** (`basic_avg_shares < 3e10`) so it can never re-leak — the structural fix.
- **Cleaned the data** via new `scripts/clean_dirty_shares_price.py` (machine-portable, runs on
  the ITX/`sh019` box): nulled 125 shares rows, 37 fundamentals rows, 76,333+28 price bars.
- **3 of 4 cap DQ checks now green.**

## 📝 Files Changed
- `scripts/clean_dirty_shares_price.py` (NEW): 3-part in-place null cleanup (shares_history,
  fundamentals, price_data). Config-relative DB path + `src.db` governed connection so it runs
  identically on research (Hang) and infra (sh019) boxes. Has `--dry-run` / `--smoke-test` / `--skip-price`.
- `scripts/backfill_shares_from_fundamentals.py`: added `AND basic_avg_shares < 3e10` sanity
  bound to all 3 queries — the dam that stops recurrence.
- `tools/audit_t1_data_quality.py`: 4 new FAIL-level plausibility checks (2 in
  `check_shares_integrity`, 2 in `check_price_integrity`).
- `docs/session_logs/sprint_13/ISSUE_dirty_shares_cap_dq_gap.md`: status → CLEANED; added source
  investigation, systemic-gap table, refetch-rejection, revised cleanup plan.

## 🚧 Work in Progress (CRITICAL)
- **`ohlc_ordering` DQ check is still FAIL (41,373 rows)** — a SEPARATE, larger corruption class
  (high<close / low>close / high<low), NOT the cap issue. Left untouched deliberately; existing
  downstream mitigation is `GREATEST/LEAST(close)` (memory `price_data_ohlc_dirt`). Decide: clean
  the rows, or keep the check as a tripwire only.
- **`absurd_share_count` check threshold is `1e11` (100B) but cleanup used `3e10` (30B).** The
  data is now clean below 30B, so the check passes — but they're mismatched. Tighten the *check*
  to `3e10` to match, now that the sub-100B tier (REGN/IFF) is cleaned.
- **⚠️ Refetch mishap (resolved but noteworthy):** an early smoke-test attempt used bare
  `yf.download()` (defaults to ~1 month) with delete-then-insert and no row-count floor — it
  TRUNCATED ADTX/ABVC history. Caught on the next verification, restored both to full history via
  null-in-place. The refetch code path was then deleted entirely. No lasting damage. Lesson: the
  cleanup is null-in-place ONLY; there is no clean upstream to refetch from.
- **Test suite is red (23 failed, ~30 collection errors) — ALL pre-existing**, unrelated to this
  work: missing modules (`src.evaluation.metrics`, `FeatureEngineer`), temp-file DuckDB
  collisions, and a `view_manager.py` SQL binder error (`atr_pct_chg` EXCLUDE mismatch). None
  assert on the nulled tickers/values. Verified the diff is only 3 code files + left no orphan rows.

## ⏭️ Next Steps
1. Tighten `absurd_share_count` check threshold `1e11 → 3e10` to match the cleanup bound.
2. Decide on the OHLC-ordering class (41,373 rows): clean vs tripwire-only.
3. **Revisit CAPE** — the original blocker. With clean caps, re-evaluate whether the 99th-pct
   winsorize can be replaced by the absolute ceiling (drift decomposition showed winsorize was
   ~80% of apparent drift *because* of this dirt).
4. Audit downstream cap-consumers for silent effects (universe/screener cap-filters, size features).
5. Investigate the pre-existing test-suite red (view_manager `atr_pct_chg`, missing modules) —
   separate from this work but blocks a green `pytest`.

## 💡 Context/Memory
- **The corruption originates one layer deeper than shares_history/price_data.** Shares dirt is
  a frozen snapshot of an OLDER, worse `fundamentals` state — the corrupt FMP rows the backfill
  read (e.g. REGN 2012) have since been re-fetched clean, so re-running the backfill would NOT
  reproduce most of it, but the leaked rows persisted. Clean the leak + bound the pump.
- **Delta-based checks cannot catch scale corruption.** A sustained block of $1.6T prices (MRDN)
  or 796T shares (FITB) has almost no day-over-day jump *inside* it, so the existing >200%-move
  check (WARNING-only) misses it. Absolute plausibility bounds are the only thing that works —
  same reason the doc rejects percentiles (which also corrupted the CAPE winsorize).
- **Refetch is dead for these tickers.** yfinance serves historical daily OHLC (unlike shares,
  which are point-in-time), but for low-float/reverse-split tickers that history is itself dirty
  at source ($3.7T/share). Null-in-place preserving the date spine is the only viable fix.
- **The cross-table cap check is a NET, not a primary gate** — its `JOIN USING(ticker,date)`
  covers only ~60% of shares rows. The per-table ceilings (`shares > 3e10`, `close > 1e6`) are the
  date-independent primary gates; the cap check caught the residual $810k–$1M price tier (TNXP/
  EMPD/PSTV) where shares AND price are each individually plausible but the product isn't.
- **Real bounds:** shares max ~25B (AAPL); US price max ~$810k (BRK-A). So the `3e10`/`1e6` cuts
  have zero false-positive risk — nothing legitimate sits above them.

---

# ADDENDUM — resumed session (same day): all Next Steps closed

Steps 1–4 above are **DONE**; step 5 (pre-existing test red) remains open. What happened:

1. **Threshold tightening (step 1) exposed a second dirt tier.** Nothing sat above 3e10, but the
   *sub-ceiling* band was dirty: the same ~1000× FMP dirt on SMALL tickers lands below any global
   bound (GTLS 29.9B vs real 30M; C's 29B is legit pre-2011-reverse-split — a global ceiling can't
   separate them). Adjudicated `>1B AND >100× ticker-median` rows against current fundamentals +
   implied cap: **86 shares + 38 fundamentals rows nulled** (parts D/E of the cleanup script);
   EXE 2020-04-10 whitelisted (legit 1.957B pre-1:200-reverse-split). Relative tripwires
   (`>1B AND >500× median`, FAIL) added on BOTH shares_history and fundamentals.
2. **OHLC-ordering class (step 2) resolved by profiling:** 99.91% of the 41,373 violations are
   <0.1% float-rounding epsilon (harmless); 34 are recurring live-feed tape artifacts (quad-witching
   dates — WARN tier); only **3 bars were corrupt** (>10%) and were nulled. Check recalibrated to
   3 tiers; `null_or_zero_close` refined to exclude deliberately-nulled bars.
3. **DQ layer hardened end-to-end** (assessment + 5 fixes, all implemented & verified — see
   [DQ_orchestrator_hardening.md](sprint_13/DQ_orchestrator_hardening.md)):
   bounds centralized in `config.T1_PLAUSIBILITY_BOUNDS`; write-time clamps in shares/fundamental/
   data engines; **Phase 1.6 plausibility gate** (0.5s, withholds R2 publish while red); new-FAIL
   delta alerting in `run_all_audits.py` + orchestrator; filing-date threshold unified at 8d
   (`filing_before_min_real_gap` — the 30d check's 22,561 warns were all legit accelerated filers, now 0).
4. **CAPE revisited (step 3) — planned swap FALSIFIED.** With clean caps, winsorize→absolute-ceiling
   flattens drift (+0.022→+0.004/yr) but collapses rank corr **0.874→0.416**: the winsorize is a
   load-bearing mega-cap **concentration cap**, not a dirt filter. Final: ceiling as dirt guard IN
   FRONT of the retained winsorize. CAPE_OURS rewritten (164 rows, latest 2026-07 = 59.7); memory
   updated with a don't-remove warning. See cape_fred_proxy_findings.md closing section.

**Open handoffs:** run `clean_dirty_shares_price.py` on the sh019 box (its DB copy still holds the
dirt; Phase 1.6 will withhold its R2 publish until done); standing audit FAILs (t1_macro missing 8
June-2026 dates + NULL vix_close, 4 price-gap tickers); step 5 pre-existing test-suite red
(temp-file DuckDB fixture collisions, `view_manager` binder error — untouched, still open).
Downstream cap-consumer audit (step 4) is subsumed: consumers now read clean tables and the
Phase 1.6 gate blocks publishes if dirt ever returns.
