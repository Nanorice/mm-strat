# DQ Orchestrator Hardening — Findings & Implementation Tracker

**Date:** 2026-07-04 · **Follow-on from:** [ISSUE_dirty_shares_cap_dq_gap.md](ISSUE_dirty_shares_cap_dq_gap.md) (CLOSED)
**Scope:** assessment of how data quality is enforced across the daily pipeline, and the fixes.

---

## Context: what the audit layer looks like today

Four DQ layers exist in `daily_pipeline_orchestrator.py`:

1. **Phase 1 HALT** — catastrophic ingestion failure stops the run.
2. **Phase 1.5 gate** — price *coverage* on the exact trading day; one same-run retry <90%,
   warn <80%. Never blocks. Presence-only (a row of garbage counts as covered).
3. **Inline `_check_filing_date_quality`** — log-only, during Phase 1 fundamentals.
4. **Phase 8 audits** — subprocess `tools/run_all_audits.py` (4 audits × 120s cap, 600s
   overall), best-effort; report JSON → `data/audit_reports/`, surfaced in Pipeline Health.

T1 audit runtime measured 6.7s (research box) — ample headroom under the 120s cap.

---

## Findings (ranked)

### F1. Detection is post-hoc and nothing gates on it  — HIGH
The audit runs at Phase 8, **after** features (3/5), scoring (7.4), dashboard build (7.5) and
**R2 publish (7.6)**. A FAIL changes nothing: dirty data is already in `daily_predictions` and
published remotely before the tripwire fires. The next run doesn't consult yesterday's report.

### F2. No write-time validation at the engines (the pump is unguarded) — HIGH
Only the one-off backfill script got a bound. Live writers validate nothing:
- `shares_engine.py` — only `shares > 0`.
- `fundamental_engine.py` — no bound on `basic_avg_shares` (FMP 1000×/10× units dirt arrives here).
- `data_engine.py::_flush_buffer` — `_quality_check` is log-only; any close accepted.

### F3. Threshold constants duplicated → drift — MEDIUM
`3e10` lived as a literal in 3 places (audit SQL, cleanup script, backfill script); `1e6`,
`8e12`, ratio bounds likewise. The 1e11-vs-3e10 mismatch in the last session was exactly this
failure mode. Precedent for the fix: `PIPELINE_ALERT_THRESHOLDS` in config.py.

### F4. Alert saturation — exit code 1 carries no signal — MEDIUM
Audit stands at ~4 FAIL / 8 WARNING permanently, so "exit 1" is the steady state and Phase 8
treats it like success. No delta logic ("a FAIL appeared that wasn't there yesterday").
Standing FAILs being ignored right now: t1_macro missing 8 June-2026 trading days + 1 NULL
vix_close (the exact class that broke `trend_ok` before), 4 gap tickers.

### F5. Filing-date check duplicated with disagreeing thresholds — LOW
Orchestrator inline check says filing <8d after period_end = bogus; audit warns at <30d and
flags 22,561 rows as permanent noise. Two implementations of one check, disagreeing.

### F6. Subprocess plumbing edge cases (run_all_audits.py) — LOW / accepted
- JSON extraction via `stdout.find("[")` — breaks if any pre-JSON line ever contains `[`.
- Report keyed by UTC date stamped at *start*; orchestrator resolves path *after* completion —
  tiny UTC-midnight straddle window logs "report not written".
- One report per UTC day — manual rerun overwrites the nightly report (no run-id).

### F7. Phase 1.5 blind spots — LOW / accepted
Presence-only; denominator trusts `is_active` (stale actives → false retries); immediate retry
with no backoff.

### F8. Known limits of the new relative checks — accepted, documented
- Majority-dirty ticker → dirty median → relative check blind (absolute ceiling + cap net only).
- Ticker with 1–2 rows → median = value → never flags; sub-30B single-row dirt slips.
- ~10× scale dirt (OPTT mode) only detectable when ticker median is tiny.
- Audit tripwire at 500× vs one-time adjudicated cleanup at 100× is deliberate (EXE legit at 200×).
- `null_or_zero_close` now excludes fully-nulled bars → an ingestion bug writing fully-NULL bars
  would be misread as deliberate cleanup (freshness/coverage checks partially cover).

### F9. Cross-machine divergence — operational
Two DB copies (research + sh019). Cleanups are per-machine; **sh019 still holds the dirt** and
its audit will FAIL once this code is pulled, until `clean_dirty_shares_price.py` runs there.

---

## Implementation checklist

Order matters: F3 is a prerequisite for F2/F1 staying consistent.

- [x] **Fix A (F3):** centralize plausibility bounds in `config.py` (`T1_PLAUSIBILITY_BOUNDS`);
      rewire `audit_t1_data_quality.py`, `clean_dirty_shares_price.py`,
      `backfill_shares_from_fundamentals.py` to read them.
- [x] **Fix B (F2):** write-time clamps at the engines, mirroring the audit ceilings
      (absolute bounds only — relative checks need full history and stay in the audit):
  - [x] `shares_engine.py`: drop fetched rows with `shares_outstanding > shares_max`, log WARN.
  - [x] `fundamental_engine.py`: null `basic_avg_shares`/`diluted_avg_shares` > `shares_max`
        in both write paths (upsert + no-overwrite), log WARN.
  - [x] `data_engine.py::_flush_buffer`: null OHLC on rows with `close > close_max` before
        insert (keep spine/volume), log WARN.
- [x] **Fix C (F1):** Phase 1.6 fast plausibility gate in the orchestrator — the FAIL-level
      absolute ceilings only (sub-second queries), run right after Phase 1.5. Non-halting, but
      sets `run_stats['plausibility_fail']`; **Phase 7.6 R2 sync skips publish** when set
      (local dashboard still builds; stale-but-clean beats fresh-but-dirty).
- [x] **Fix D (F4):** new-FAIL delta in `run_all_audits.py` — diff FAIL set vs the most recent
      previous report, embed `new_fails` in the report JSON + print prominently; orchestrator
      logs new FAILs at ERROR level.
- [x] **Fix E (F5):** audit's fast-filing warn threshold aligned to the orchestrator's 8d via a
      shared config constant (`FILING_MIN_REAL_GAP_DAYS`).

## Open items (tracked, not in this pass)

- [ ] Run `clean_dirty_shares_price.py` on the sh019 box (F9).
- [ ] Investigate standing FAILs: t1_macro 8 missing June-2026 dates + NULL vix_close row;
      4 price-gap tickers (F4 tail).
- [ ] Phase 1.5 retry backoff + is_active staleness (F7) — pair with the Pipeline Health
      deactivation prompt TODO.
- [ ] run_all_audits report run-id / UTC-midnight straddle (F6) — cosmetic.
- [x] CAPE revisit (original blocker): DONE 2026-07-04 — swap tested and **rejected**
      (rank corr 0.874 → 0.416; the winsorize is a load-bearing concentration cap, not a
      dirt filter). Final: absolute ceiling as dirt guard + winsorize retained. See
      [cape_fred_proxy_findings.md](cape_fred_proxy_findings.md) closing section.
